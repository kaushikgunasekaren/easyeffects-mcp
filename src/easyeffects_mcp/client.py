"""Low-level client for the Easy Effects 8.x local control socket.

Easy Effects (8.0+) listens on a QLocalServer socket named ``EasyEffectsServer``
in the user's runtime directory. Commands are newline-terminated ASCII lines;
some commands write a reply, others are fire-and-forget.
"""

from __future__ import annotations

import configparser
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

SOCKET_NAME = "EasyEffectsServer"
FLATPAK_ID = "com.github.wwmm.easyeffects"
PIPELINES = ("input", "output")


class EasyEffectsError(ToolError):
    """Raised for any Easy Effects failure; ToolError so MCP clients see the message."""


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


def find_socket() -> Path:
    for path in socket_candidates():
        if path.exists():
            return path
    raise EasyEffectsError(
        "Easy Effects control socket not found. Is Easy Effects 8.x running? "
        "(start it with `easyeffects --service-mode -w`, or set EASYEFFECTS_SOCKET). "
        f"Looked in: {', '.join(str(p) for p in socket_candidates())}"
    )


@dataclass
class Paths:
    config: Path  # .../easyeffects/db
    data: Path  # .../easyeffects (presets live here)

    @classmethod
    def detect(cls) -> "Paths":
        home = Path.home()
        flatpak = home / ".var" / "app" / FLATPAK_ID
        native_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "easyeffects"
        native_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "easyeffects"
        if not native_config.exists() and (flatpak / "config" / "easyeffects").exists():
            return cls(flatpak / "config" / "easyeffects" / "db", flatpak / "data" / "easyeffects")
        return cls(native_config / "db", native_data)


class EasyEffectsClient:
    def __init__(self, timeout: float = 1.0) -> None:
        self.timeout = timeout
        self.paths = Paths.detect()

    # --- socket -------------------------------------------------------------

    def send(self, command: str, expect_reply: bool = False) -> str:
        if "\n" in command:
            raise EasyEffectsError("Commands must not contain newlines")
        path = find_socket()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            try:
                sock.connect(str(path))
            except OSError as exc:
                raise EasyEffectsError(f"Could not connect to {path}: {exc}") from exc
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

    # --- global state -------------------------------------------------------

    def _get_flag(self, name: str) -> bool:
        return self.send(f"get_{name}", expect_reply=True) == "1"

    def _set_flag(self, name: str, enabled: bool) -> None:
        self.send(f"{name}:{1 if enabled else 0}")

    def get_global_bypass(self) -> bool:
        return self._get_flag("global_bypass")

    def set_global_bypass(self, enabled: bool) -> None:
        self._set_flag("global_bypass", enabled)

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
        return self.send(f"get_last_loaded_preset:{pipeline}", expect_reply=True)

    def preset_dir(self, pipeline: str) -> Path:
        _check_pipeline(pipeline)
        return self.paths.data / pipeline

    def list_presets(self, pipeline: str) -> list[str]:
        directory = self.preset_dir(pipeline)
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.json"))

    def load_preset(self, pipeline: str, name: str) -> None:
        if name not in self.list_presets(pipeline):
            raise EasyEffectsError(f"No {pipeline} preset named {name!r}")
        self.send(f"load_preset:{pipeline}:{name}")

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
        parser.read(self.paths.config / "easyeffectsrc")
        return parser

    def active_plugins(self, pipeline: str) -> list[str]:
        """Plugin chain as saved by Easy Effects, e.g. ['equalizer#0', 'compressor#0']."""
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
