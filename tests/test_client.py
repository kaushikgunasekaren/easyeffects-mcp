"""Unit tests using a fake Easy Effects socket server."""

import os
import socket
import threading

import pytest

from easyeffects_mcp.client import EasyEffectsClient, EasyEffectsError, split_plugin_key


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    path = tmp_path / "EasyEffectsServer"
    state = {"global_bypass": "2", "equalizer:0:inputGain": "-3"}
    received = []
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen()

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                line = conn.recv(1024).decode().strip()
                received.append(line)
                if line == "get_global_bypass":
                    conn.sendall(state["global_bypass"].encode())
                elif line.startswith("global_bypass:"):
                    state["global_bypass"] = "1" if line.endswith("1") else "2"
                elif line.startswith("get_property:output:"):
                    key = line.removeprefix("get_property:output:")
                    conn.sendall((state.get(key, "error_plugin_not_found") + "\n").encode())
                elif line.startswith("set_property:output:"):
                    key, _, value = line.removeprefix("set_property:output:").rpartition(":")
                    state[key] = value

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setenv("EASYEFFECTS_SOCKET", str(path))
    yield received
    srv.close()


def test_bypass_roundtrip(fake_server):
    c = EasyEffectsClient()
    assert c.get_global_bypass() is False
    c.set_global_bypass(True)
    assert c.get_global_bypass() is True


def test_set_property_reads_back(fake_server):
    c = EasyEffectsClient()
    assert c.set_property("output", "equalizer", "inputGain", -6.5) == "-6.5"
    assert "set_property:output:equalizer:0:inputGain:-6.5" in fake_server


def test_error_reply_raises(fake_server):
    with pytest.raises(EasyEffectsError, match="error_plugin_not_found"):
        EasyEffectsClient().get_property("output", "compressor", "ratio")


def test_rejects_bad_input():
    c = EasyEffectsClient()
    with pytest.raises(EasyEffectsError):
        c.get_property("sideways", "equalizer", "inputGain")
    with pytest.raises(EasyEffectsError):
        c.get_property("output", "equalizer", "a:b")


def test_split_plugin_key():
    assert split_plugin_key("bass_enhancer#2") == ("bass_enhancer", 2)


@pytest.fixture
def no_socket(tmp_path, monkeypatch):
    """Simulate Easy Effects 7.x: no socket, a fake `easyeffects` CLI on PATH."""
    log = tmp_path / "cli.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "easyeffects"
    cli.write_text(f'#!/bin/sh\necho "$@" >> {log}\n[ "$1" = "-b" ] && [ "$2" = "3" ] && echo 1\n[ "$1" = "-a" ] && echo music\nexit 0\n')
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("EASYEFFECTS_SOCKET", str(tmp_path / "missing"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("easyeffects_mcp.client.is_running", lambda: True)
    return tmp_path, log


def test_cli_fallback(no_socket):
    tmp_path, log = no_socket
    (tmp_path / "config" / "easyeffects" / "output").mkdir(parents=True)  # 7.x preset location
    (tmp_path / "config" / "easyeffects" / "output" / "music.json").write_text("{}")
    c = EasyEffectsClient()
    assert c.get_global_bypass() is True
    c.set_global_bypass(False)
    assert c.last_loaded_preset("output") == "music"
    assert c.list_presets("output") == ["music"]
    c.load_preset("output", "music")
    assert log.read_text().splitlines() == ["-b 3", "-b 2", "-a output", "-l music"]


def test_socket_only_features_explain_themselves(no_socket):
    with pytest.raises(EasyEffectsError, match="8.0"):
        EasyEffectsClient().get_property("output", "equalizer", "inputGain")


def test_presets_merged_from_both_locations(no_socket):
    tmp_path, _ = no_socket
    for base, name in (("data", "new"), ("config", "old")):
        d = tmp_path / base / "easyeffects" / "input"
        d.mkdir(parents=True)
        (d / f"{name}.json").write_text("{}")
    c = EasyEffectsClient()
    assert c.list_presets("input") == ["new", "old"]
    assert c.find_preset("input", "old").parent.parent.parent.name == "config"
