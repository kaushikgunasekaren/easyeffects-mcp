# easyeffects-mcp

[![test](https://github.com/kaushikgunasekaren/easyeffects-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaushikgunasekaren/easyeffects-mcp/actions/workflows/test.yml)

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants (Claude Code, Claude Desktop, Cursor, VS Code, etc.) control [Easy Effects](https://github.com/wwmm/easyeffects), the PipeWire audio effects app for Linux.

Ask things like:

- "Turn off all my audio effects" / "turn them back on"
- "Load my `headphones` preset"
- "Boost the bass a bit on my EQ"
- "Apply this AutoEQ profile for my HD 600s: …"
- "What plugins are active on my mic?"

## Requirements

- Linux with Easy Effects running (native package or Flatpak)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.10+ for you if needed)

| Easy Effects version | What works |
|---|---|
| **8.0+** (Arch, Fedora, Flatpak) | Everything |
| **7.x** (e.g. Ubuntu 24.04, Debian 12) | Global bypass and presets only, through the `easyeffects` command line. EQ and plugin settings need 8.0+, which you can get from [Flathub](https://flathub.org/apps/com.github.wwmm.easyeffects). |

Check your version with `easyeffects --version` (or `flatpak run com.github.wwmm.easyeffects --version`).

## Install

You don't need to clone anything. Point your MCP client at:

```
uvx --from git+https://github.com/kaushikgunasekaren/easyeffects-mcp easyeffects-mcp
```

### Claude Code

```bash
claude mcp add easyeffects --scope user -- uvx --from git+https://github.com/kaushikgunasekaren/easyeffects-mcp easyeffects-mcp
```

### Claude Desktop, Cursor, Windsurf and other JSON-configured clients

```json
{
  "mcpServers": {
    "easyeffects": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kaushikgunasekaren/easyeffects-mcp", "easyeffects-mcp"]
    }
  }
}
```

### VS Code (`.vscode/mcp.json`)

```json
{
  "servers": {
    "easyeffects": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kaushikgunasekaren/easyeffects-mcp", "easyeffects-mcp"]
    }
  }
}
```

`uvx` caches the install. To pick up a newer version, run `uv cache clean easyeffects-mcp` and restart your client.

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

- Adding or removing plugins from the chain isn't exposed by Easy Effects' control socket. Do that in the app, or save a preset with the plugins you want and load it.
- Live property changes aren't saved into a preset until you save it in Easy Effects.

## Troubleshooting

**"control socket not found"**: Easy Effects isn't running. Start it in the background with `easyeffects --service-mode -w` (Flatpak: `flatpak run com.github.wwmm.easyeffects --service-mode -w`). Enabling "Launch on system startup" in its settings keeps it running.

**"error_plugin_not_found"**: that plugin isn't in the chain. Ask for `get_status` to see which plugins are loaded, and add the plugin in the Easy Effects window.

**Socket in an unusual place**: set `EASYEFFECTS_SOCKET` to its path in your MCP client's `env` block.

## Development

```bash
git clone https://github.com/kaushikgunasekaren/easyeffects-mcp.git
cd easyeffects-mcp
uv sync
uv run pytest
npx @modelcontextprotocol/inspector uv run easyeffects-mcp   # MCP Inspector
```

## License

MIT
