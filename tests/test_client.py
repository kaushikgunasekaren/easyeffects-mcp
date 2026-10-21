"""Unit tests using a fake Easy Effects socket server."""

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
