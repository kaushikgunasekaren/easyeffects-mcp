# easyeffects-mcp

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants (Claude Code, Claude Desktop, etc.) control [Easy Effects](https://github.com/wwmm/easyeffects), the PipeWire audio effects app for Linux.

Ask things like:

- "Turn off all my audio effects" / "turn them back on"
- "Load my `headphones` preset"
- "Boost the bass a bit on my EQ"
- "Apply this AutoEQ profile for my HD 600s: …"
- "What plugins are active on my mic?"

## Requirements

- Linux with **Easy Effects 8.0 or newer** running (it talks to the `EasyEffectsServer` control socket that 8.x provides; 7.x is not supported)
- Python 3.10+ and [uv](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/kaushikgunasekaren/easyeffects-mcp.git
cd easyeffects-mcp
uv sync
```

### Claude Code

```bash
claude mcp add easyeffects --scope user -- uv --directory /path/to/easyeffects-mcp run easyeffects-mcp
```

### Claude Desktop / other MCP clients

```json
{
  "mcpServers": {
    "easyeffects": {
      "command": "uv",
      "args": ["--directory", "/path/to/easyeffects-mcp", "run", "easyeffects-mcp"]
    }
  }
}
```

Or run straight from GitHub without cloning:

```json
"command": "uvx",
"args": ["--from", "git+https://github.com/kaushikgunasekaren/easyeffects-mcp", "easyeffects-mcp"]
```

## Tools

| Tool | What it does |
|---|---|
| `get_status` | Bypass / mic monitoring / audio sharing state, devices, last presets, plugin chains |
| `set_global_bypass` | Turn all effects off (bypass) or on |
| `set_microphone_monitoring` | Hear your processed microphone |
| `set_audio_sharing` | Route processed output to the virtual source |
| `window` | Show or hide the Easy Effects window |
| `list_presets` / `load_preset` | List and load saved input/output presets |
| `read_preset` / `save_preset` | Read or write preset JSON files |
| `list_plugin_instances` | Active plugins in a pipeline with their bypass state |
| `bypass_plugin` | Bypass a single plugin |
| `get_plugin_property` / `set_plugin_property` | Read/write any plugin property (e.g. `compressor` `threshold`) |
| `get_equalizer` | Full parametric EQ state, both channels |
| `set_equalizer_band` | Change gain/frequency/Q/type/mode of one band |
| `apply_parametric_eq` | Replace the EQ with a list of bands (great for AutoEQ profiles) |

`output` is the speakers/headphones pipeline, `input` is the microphone pipeline. Property names are the camelCase keys Easy Effects stores in `~/.config/easyeffects/db/*rc` (e.g. `inputGain`, `band3Gain`, `bypass`).

## Limitations

- Adding or removing plugins from the chain isn't exposed by Easy Effects' control socket — do that in the app (or save a preset with the plugins you want and load it).
- Live property changes aren't saved into a preset until you save it in Easy Effects.

## Configuration

| Env var | Purpose |
|---|---|
| `EASYEFFECTS_SOCKET` | Override the control socket path (default `$XDG_RUNTIME_DIR/EasyEffectsServer`, Flatpak paths are also checked) |

## Development

```bash
uv sync
uv run pytest
npx @modelcontextprotocol/inspector uv run easyeffects-mcp   # MCP Inspector
```

## License

MIT
