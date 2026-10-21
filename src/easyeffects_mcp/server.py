"""MCP server exposing Easy Effects controls as tools."""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from .client import EasyEffectsClient, EasyEffectsError, split_plugin_key

Pipeline = Literal["input", "output"]
Channel = Literal["both", "left", "right"]

# Index order matches the Easy Effects / LSP parametric equalizer enums.
BAND_TYPES = [
    "off", "bell", "hi-pass", "hi-shelf", "lo-pass", "lo-shelf",
    "notch", "resonance", "allpass", "bandpass", "ladder-pass", "ladder-rej",
]
BAND_MODES = ["rlc-bt", "rlc-mt", "bwc-bt", "bwc-mt", "lrx-bt", "lrx-mt", "apo-dr"]
BAND_FIELDS = ("Type", "Mode", "Frequency", "Gain", "Q", "Slope", "Mute", "Solo")
MAX_BANDS = 32

mcp = MCPServer(
    "easyeffects",
    instructions=(
        "Controls Easy Effects (PipeWire audio effects) on the local Linux desktop. "
        "'output' is the speakers/headphones pipeline, 'input' is the microphone pipeline. "
        "Call get_status first to see which plugins are active before editing properties. "
        "Gains are in dB, frequencies in Hz."
    ),
)
client = EasyEffectsClient()


def _enum_index(value: str | int, names: list[str], label: str) -> int:
    if isinstance(value, int) or str(value).isdigit():
        index = int(value)
    else:
        key = str(value).lower().replace("_", "-").replace(" ", "-")
        if key not in names:
            raise EasyEffectsError(f"Unknown {label} {value!r}; choose from {names}")
        index = names.index(key)
    if not 0 <= index < len(names):
        raise EasyEffectsError(f"{label} index {index} out of range")
    return index


def _channels(channel: Channel) -> list[str]:
    return ["left", "right"] if channel == "both" else [channel]


# --- status & global switches ------------------------------------------------


@mcp.tool()
def get_status() -> dict:
    """Overview: global bypass, mic monitoring, audio sharing, devices, last loaded presets and active plugin chains."""
    return {
        "global_bypass": client.get_global_bypass(),
        "microphone_monitoring": client.get_microphone_monitoring(),
        "audio_sharing": client.get_audio_sharing(),
        "devices": client.devices(),
        "last_loaded_preset": {p: client.last_loaded_preset(p) or None for p in ("input", "output")},
        "plugins": {p: client.active_plugins(p) for p in ("input", "output")},
    }


@mcp.tool()
def set_global_bypass(enabled: bool) -> str:
    """Enable (true) or disable (false) the global bypass. Bypass on = all effects off."""
    client.set_global_bypass(enabled)
    return f"Global bypass is now {'on' if client.get_global_bypass() else 'off'}"


@mcp.tool()
def set_microphone_monitoring(enabled: bool) -> str:
    """Turn microphone monitoring (hear your processed mic) on or off."""
    client.set_microphone_monitoring(enabled)
    return f"Microphone monitoring is now {'on' if client.get_microphone_monitoring() else 'off'}"


@mcp.tool()
def set_audio_sharing(enabled: bool) -> str:
    """Turn audio sharing (route processed output to the virtual source) on or off."""
    client.set_audio_sharing(enabled)
    return f"Audio sharing is now {'on' if client.get_audio_sharing() else 'off'}"


@mcp.tool()
def window(action: Literal["show", "hide"]) -> str:
    """Show or hide the Easy Effects window."""
    client.show_window() if action == "show" else client.hide_window()
    return f"Window {action} requested"


# --- presets -----------------------------------------------------------------


@mcp.tool()
def list_presets() -> dict:
    """List saved input and output presets, plus the last loaded one for each."""
    return {
        p: {"presets": client.list_presets(p), "last_loaded": client.last_loaded_preset(p) or None}
        for p in ("input", "output")
    }


@mcp.tool()
def load_preset(pipeline: Pipeline, name: str) -> str:
    """Load a saved preset into the input or output pipeline."""
    client.load_preset(pipeline, name)
    return f"Loaded {pipeline} preset {name!r}"


@mcp.tool()
def read_preset(pipeline: Pipeline, name: str) -> dict:
    """Return the JSON contents of a saved preset file."""
    path = client.preset_dir(pipeline) / f"{name}.json"
    if not path.is_file():
        raise EasyEffectsError(f"No {pipeline} preset named {name!r}")
    return json.loads(path.read_text())


@mcp.tool()
def save_preset(pipeline: Pipeline, name: str, preset: dict, overwrite: bool = False) -> str:
    """Write a preset JSON file (same format read_preset returns; top-level key must be the pipeline name).

    Tip: read an existing preset first and modify it, rather than writing one from scratch.
    """
    if not re.fullmatch(r"[\w .+-]{1,100}", name):
        raise EasyEffectsError("Preset name may only contain letters, digits, spaces, '.', '+', '-', '_'")
    if pipeline not in preset or not isinstance(preset[pipeline], dict):
        raise EasyEffectsError(f"Preset JSON must have a top-level {pipeline!r} object")
    directory = client.preset_dir(pipeline)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    if path.exists() and not overwrite:
        raise EasyEffectsError(f"Preset {name!r} already exists; pass overwrite=true to replace it")
    path.write_text(json.dumps(preset, indent=4) + "\n")
    return f"Saved {path}"


# --- generic plugin properties -----------------------------------------------


@mcp.tool()
def get_plugin_property(
    pipeline: Pipeline,
    plugin: Annotated[str, Field(description="Plugin name, e.g. equalizer, compressor, limiter, bass_enhancer")],
    property: Annotated[str, Field(description="Property name in camelCase, e.g. inputGain, threshold, bypass")],
    instance: int = 0,
    channel: Annotated[Literal["left", "right"] | None, Field(description="Equalizer only")] = None,
) -> str:
    """Read one property of an active plugin (see get_status for the plugin chain)."""
    return client.get_property(pipeline, plugin, property, instance, channel)


@mcp.tool()
def set_plugin_property(
    pipeline: Pipeline,
    plugin: Annotated[str, Field(description="Plugin name, e.g. equalizer, compressor, limiter")],
    property: Annotated[str, Field(description="Property name in camelCase, e.g. inputGain, bypass")],
    value: str | float | int | bool,
    instance: int = 0,
    channel: Annotated[Literal["left", "right"] | None, Field(description="Equalizer only")] = None,
) -> str:
    """Set one property of an active plugin. Returns the value read back from Easy Effects."""
    current = client.set_property(pipeline, plugin, property, value, instance, channel)
    return f"{plugin}#{instance}.{property} = {current}"


@mcp.tool()
def bypass_plugin(pipeline: Pipeline, plugin: str, bypassed: bool, instance: int = 0) -> str:
    """Bypass (disable) or re-enable a single plugin in the chain."""
    current = client.set_property(pipeline, plugin, "bypass", bypassed, instance)
    return f"{plugin}#{instance} bypass = {current}"


# --- equalizer convenience ---------------------------------------------------


@mcp.tool()
def get_equalizer(pipeline: Pipeline = "output", instance: int = 0) -> dict:
    """Read the parametric equalizer: gains, mode and every active band for both channels."""
    get = lambda prop, ch=None: client.get_property(pipeline, "equalizer", prop, instance, ch)  # noqa: E731
    num_bands = int(get("numBands"))
    result: dict = {
        "inputGain": float(get("inputGain")),
        "outputGain": float(get("outputGain")),
        "numBands": num_bands,
        "splitChannels": get("splitChannels") == "true",
        "bypass": get("bypass") == "true",
    }
    for ch in ("left", "right"):
        bands = []
        for i in range(num_bands):
            band = {field.lower(): get(f"band{i}{field}", ch) for field in BAND_FIELDS}
            bands.append({
                "band": i,
                "type": BAND_TYPES[int(band["type"])] if int(band["type"]) < len(BAND_TYPES) else band["type"],
                "mode": BAND_MODES[int(band["mode"])] if int(band["mode"]) < len(BAND_MODES) else band["mode"],
                "frequency": float(band["frequency"]),
                "gain": float(band["gain"]),
                "q": float(band["q"]),
                "slope": int(band["slope"]),
                "mute": band["mute"] == "true",
                "solo": band["solo"] == "true",
            })
        result[ch] = bands
    return result


@mcp.tool()
def set_equalizer_band(
    band: Annotated[int, Field(ge=0, lt=MAX_BANDS)],
    pipeline: Pipeline = "output",
    gain: Annotated[float | None, Field(description="dB")] = None,
    frequency: Annotated[float | None, Field(description="Hz")] = None,
    q: float | None = None,
    type: Annotated[str | None, Field(description=f"One of {BAND_TYPES}")] = None,
    mode: Annotated[str | None, Field(description=f"One of {BAND_MODES}")] = None,
    mute: bool | None = None,
    channel: Channel = "both",
    instance: int = 0,
) -> dict:
    """Change one equalizer band. Only the fields you pass are changed. Applies to both channels by default."""
    updates: dict[str, object] = {}
    if gain is not None:
        updates["Gain"] = gain
    if frequency is not None:
        updates["Frequency"] = frequency
    if q is not None:
        updates["Q"] = q
    if type is not None:
        updates["Type"] = _enum_index(type, BAND_TYPES, "band type")
    if mode is not None:
        updates["Mode"] = _enum_index(mode, BAND_MODES, "band mode")
    if mute is not None:
        updates["Mute"] = mute
    if not updates:
        raise EasyEffectsError("Nothing to change: pass at least one of gain, frequency, q, type, mode, mute")
    result = {}
    for ch in _channels(channel):
        result[ch] = {
            field.lower(): client.set_property(pipeline, "equalizer", f"band{band}{field}", value, instance, ch)
            for field, value in updates.items()
        }
    return result


class EqBand(BaseModel):
    frequency: float = Field(description="Hz")
    gain: float = Field(0.0, description="dB")
    q: float = 0.7
    type: str = Field("bell", description=f"One of {BAND_TYPES}")


@mcp.tool()
def apply_parametric_eq(
    bands: list[EqBand],
    pipeline: Pipeline = "output",
    preamp: Annotated[float | None, Field(description="Input gain in dB (e.g. AutoEQ 'Preamp')")] = None,
    mode: str = "apo-dr",
    instance: int = 0,
) -> str:
    """Replace the whole equalizer with a list of bands (e.g. from an AutoEQ ParametricEQ.txt), applied to both channels.

    Requires an equalizer plugin in the chain.
    """
    if not 1 <= len(bands) <= MAX_BANDS:
        raise EasyEffectsError(f"Need between 1 and {MAX_BANDS} bands")
    mode_index = _enum_index(mode, BAND_MODES, "band mode")
    set_ = lambda prop, value, ch=None: client.set_property(pipeline, "equalizer", prop, value, instance, ch)  # noqa: E731
    set_("numBands", len(bands))
    if preamp is not None:
        set_("inputGain", preamp)
    for ch in ("left", "right"):
        for i, b in enumerate(bands):
            set_(f"band{i}Type", _enum_index(b.type, BAND_TYPES, "band type"), ch)
            set_(f"band{i}Mode", mode_index, ch)
            set_(f"band{i}Frequency", b.frequency, ch)
            set_(f"band{i}Gain", b.gain, ch)
            set_(f"band{i}Q", b.q, ch)
            set_(f"band{i}Mute", False, ch)
    return f"Applied {len(bands)}-band EQ to {pipeline} equalizer#{instance}"


@mcp.tool()
def list_plugin_instances(pipeline: Pipeline) -> list[dict]:
    """Active plugins in a pipeline, in processing order, with their bypass state."""
    out = []
    for key in client.active_plugins(pipeline):
        name, instance = split_plugin_key(key)
        try:
            bypass = client.get_property(pipeline, name, "bypass", instance) == "true"
        except EasyEffectsError:
            bypass = None
        out.append({"plugin": name, "instance": instance, "bypass": bypass})
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
