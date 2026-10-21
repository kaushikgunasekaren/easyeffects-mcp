"""Low-level client for Easy Effects.

Easy Effects 8.0+ listens on a QLocalServer socket named ``EasyEffectsServer``
in the user's runtime directory. Commands are newline-terminated ASCII lines;
some commands write a reply, others are fire-and-forget.

Older releases (7.x) have no socket, so bypass and presets fall back to the
``easyeffects`` command line, which forwards to the running instance.
"""

from __future__ import annotations

import configparser
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

SOCKET_NAME = "EasyEffectsServer"
FLATPAK_ID = "com.github.wwmm.easyeffects"
PIPELINES = ("input", "output")


class EasyEffectsError(ToolError):
    """Raised for any Easy Effects failure; ToolError so MCP clients see the message."""


class SocketUnavailable(EasyEffectsError):
    pass


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def socket_candidates() -> list[Path]:
    if override := os.environ.get("EASYEFFECTS_SOCKET"):
        return [Path(override)]
    runtime = _runtime_dir()
    return [
        runtime / SOCKET_NAME,
        runtime / "app" / FLATPAK_ID / SOCKET_NAME,
        Path("/tmp") / SOCKET_NAME,
    ]


def find_socket() -> Path | None:
    return next((p for p in socket_candidates() if p.exists()), None)


def is_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "easyeffects"], capture_output=True).returncode == 0
    except FileNotFoundError:  # no pgrep; assume it is and let the command fail
        return True


@dataclass
class Install:
    flatpak: bool
    config: Path  # .../easyeffects (7.x presets live here, 8.x settings in db/)
    data: Path  # .../easyeffects (8.x presets live here)

    @classmethod
    def detect(cls) -> "Install":
        home = Path.home()
        flatpak_root = home / ".var" / "app" / FLATPAK_ID
        native_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "easyeffects"
        native_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "easyeffects"
        sock = find_socket()
        use_flatpak = flatpak_root.exists() and (
            (sock is not None and FLATPAK_ID in str(sock))
            or shutil.which("easyeffects") is None
            or not (native_config.exists() or native_data.exists())
        )
        if use_flatpak:
            return cls(True, flatpak_root / "config" / "easyeffects", flatpak_root / "data" / "easyeffects")
        return cls(False, native_config, native_data)

    def cli(self) -> list[str]:
        if not self.flatpak and shutil.which("easyeffects"):
            return ["easyeffects"]
        if shutil.which("flatpak"):
            return ["flatpak", "run", "--command=easyeffects", FLATPAK_ID]
        raise EasyEffectsError("Could not find the easyeffects command")

    def preset_dirs(self, pipeline: str) -> list[Path]:
        """Preset directories, preferred (8.x) location first."""
        return [self.data / pipeline, self.config / pipeline]


class EasyEffectsClient:
    def __init__(self, timeout: float = 1.0) -> None:
        self.timeout = timeout
        self.install = Install.detect()

    # --- transports ---------------------------------------------------------

    def send(self, command: str, expect_reply: bool = False) -> str:
        if "\n" in command:
            raise EasyEffectsError("Commands must not contain newlines")
        path = find_socket()
        if path is None:
            raise SocketUnavailable(
                "Easy Effects control socket not found. Is Easy Effects running? "
                "(start it with `easyeffects --service-mode -w`). This feature needs Easy Effects 8.0+; "
                f"looked in: {', '.join(str(p) for p in socket_candidates())}. "
                "Set EASYEFFECTS_SOCKET if yours is elsewhere."
            )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            try:
                sock.connect(str(path))
            except OSError as exc:
                raise SocketUnavailable(f"Could not connect to {path} (is Easy Effects running?): {exc}") from exc
            sock.sendall((command + "\n").encode())
            if not expect_reply:
                return ""
            chunks: list[bytes] = []
            try:
                while data := sock.recv(4096):
                    chunks.append(data)
                    if data.endswith(b"\n"):
                        break
            except socket.timeout:
                pass
        reply = b"".join(chunks).decode(errors="replace").strip()
        if reply.startswith("error_"):
            raise EasyEffectsError(f"{command!r} failed: {reply}")
        return reply

    def run_cli(self, *args: str) -> str:
        if not is_running():
            raise EasyEffectsError("Easy Effects is not running. Start it with `easyeffects --service-mode -w`.")
        try:
            proc = subprocess.run([*self.install.cli(), *args], capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise EasyEffectsError(f"easyeffects {' '.join(args)} timed out") from exc
        if proc.returncode != 0:
            raise EasyEffectsError(f"easyeffects {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    # --- global state -------------------------------------------------------

    def _get_flag(self, name: str) -> bool:
        return self.send(f"get_{name}", expect_reply=True) == "1"

    def _set_flag(self, name: str, enabled: bool) -> None:
        self.send(f"{name}:{1 if enabled else 0}")

    def get_global_bypass(self) -> bool:
        try:
            return self._get_flag("global_bypass")
        except SocketUnavailable:
            return self.run_cli("-b", "3").splitlines()[-1].strip() == "1"

    def set_global_bypass(self, enabled: bool) -> None:
        try:
            self._set_flag("global_bypass", enabled)
        except SocketUnavailable:
            self.run_cli("-b", "1" if enabled else "2")

    def get_microphone_monitoring(self) -> bool:
        return self._get_flag("microphone_monitoring")

    def set_microphone_monitoring(self, enabled: bool) -> None:
        self._set_flag("microphone_monitoring", enabled)

    def get_audio_sharing(self) -> bool:
        return self._get_flag("audio_sharing")

    def set_audio_sharing(self, enabled: bool) -> None:
        self._set_flag("audio_sharing", enabled)

    def show_window(self) -> None:
        self.send("show_window")

    def hide_window(self) -> None:
        self.send("hide_window")

    # --- presets ------------------------------------------------------------

    def last_loaded_preset(self, pipeline: str) -> str:
        _check_pipeline(pipeline)
        try:
            return self.send(f"get_last_loaded_preset:{pipeline}", expect_reply=True)
        except SocketUnavailable:
            return self.run_cli("-a", pipeline)

    def preset_dir(self, pipeline: str) -> Path:
        """Directory new presets are written to (the existing one, else the 8.x location)."""
        _check_pipeline(pipeline)
        dirs = self.install.preset_dirs(pipeline)
        return next((d for d in dirs if d.is_dir()), dirs[0])

    def find_preset(self, pipeline: str, name: str) -> Path | None:
        _check_pipeline(pipeline)
        return next((p for d in self.install.preset_dirs(pipeline) if (p := d / f"{name}.json").is_file()), None)

    def list_presets(self, pipeline: str) -> list[str]:
        _check_pipeline(pipeline)
        names = {p.stem for d in self.install.preset_dirs(pipeline) if d.is_dir() for p in d.glob("*.json")}
        return sorted(names)

    def load_preset(self, pipeline: str, name: str) -> None:
        if self.find_preset(pipeline, name) is None:
            raise EasyEffectsError(f"No {pipeline} preset named {name!r}")
        try:
            self.send(f"load_preset:{pipeline}:{name}")
        except SocketUnavailable:
            self.run_cli("-l", name)

    # --- plugin properties --------------------------------------------------

    @staticmethod
    def _property_path(pipeline: str, plugin: str, instance: int, prop: str, channel: str | None) -> str:
        _check_pipeline(pipeline)
        for part in (plugin, prop):
            if not part or ":" in part:
                raise EasyEffectsError(f"Invalid name {part!r}")
        chan = ""
        if channel:
            if channel not in ("left", "right"):
                raise EasyEffectsError("channel must be 'left' or 'right'")
            chan = f"{channel}:"
        return f"{pipeline}:{plugin}:{instance}:{chan}{prop}"

    def get_property(self, pipeline: str, plugin: str, prop: str, instance: int = 0, channel: str | None = None) -> str:
        path = self._property_path(pipeline, plugin, instance, prop, channel)
        return self.send(f"get_property:{path}", expect_reply=True)

    def set_property(self, pipeline: str, plugin: str, prop: str, value: object, instance: int = 0, channel: str | None = None) -> str:
        """Set a property and return the value read back afterwards."""
        path = self._property_path(pipeline, plugin, instance, prop, channel)
        if isinstance(value, bool):
            value = "true" if value else "false"
        self.send(f"set_property:{path}:{value}")
        return self.send(f"get_property:{path}", expect_reply=True)

    # --- config file --------------------------------------------------------

    def read_main_config(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str  # keep key case
        parser.read(self.install.config / "db" / "easyeffectsrc")
        return parser

    def active_plugins(self, pipeline: str) -> list[str]:
        """Plugin chain as saved by Easy Effects 8.x, e.g. ['equalizer#0', 'compressor#0']."""
        _check_pipeline(pipeline)
        section = "StreamOutputs" if pipeline == "output" else "StreamInputs"
        raw = self.read_main_config().get(section, "plugins", fallback="")
        return [p.strip() for p in raw.split(",") if p.strip()]

    def devices(self) -> dict[str, str]:
        cfg = self.read_main_config()
        return {
            "input": cfg.get("StreamInputs", "inputDevice", fallback=""),
            "output": cfg.get("StreamOutputs", "outputDevice", fallback=""),
        }


def _check_pipeline(pipeline: str) -> None:
    if pipeline not in PIPELINES:
        raise EasyEffectsError("pipeline must be 'input' or 'output'")


def split_plugin_key(key: str) -> tuple[str, int]:
    """'equalizer#0' -> ('equalizer', 0)."""
    name, _, instance = key.partition("#")
    return name, int(instance or 0)
