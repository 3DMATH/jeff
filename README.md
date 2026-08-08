```
       ██╗███████╗███████╗███████╗
       ██║██╔════╝██╔════╝██╔════╝
       ██║█████╗  █████╗  █████╗
  ██   ██║██╔══╝  ██╔══╝  ██╔══╝
  ╚█████╔╝███████╗██║     ██║
   ╚════╝ ╚══════╝╚═╝     ╚═╝
```

Your AI only knows what's on the host. Jeff fixes that.

## What Jeff is

Jeff is a **data plane** for AI tools: one stable MCP entrypoint that routes every
tool call to whatever substrate is active right now -- a plugged-in SD card, a local
vault, an on-card model, an attached toolchain. You point your MCP client at Jeff
once; you swap what's behind it without restarting.

Jeff is the **doorway, not the room**. The reasoning lives in the substrate -- an
on-card model, or a toolchain like C2D2 doing geometric reasoning over a vault. Jeff's
job is to keep that substrate *reachable*: discover it, verify it, route to it, and
fail gracefully when a card is pulled mid-session. The entrypoint (`mcp_proxy.py`)
never changes; it reads live state on every call and routes to whatever is mounted.

That's the whole idea: **knowledge and tools that live on the hardware, not in the
host config or the cloud.** Plug a card in, your AI gains its tools, its model, and
its knowledge. Pull it out, it's gone. Plug it into another machine, it's there.

## The flagship substrate: a chip

```bash
jeff flash /dev/disk4 --label YELLOW
jeff activate /Volumes/YELLOW
```

Ask your AI: "tell me about spectral binding."

It answers from the chip. It didn't know that before you plugged it in.

1. **Flash** burns an MCP server, model weights, and an encrypted vault onto the card
2. **Activate** verifies the chip identity (SHA-256), starts the MCP, injects a CueSheet
3. Your AI gets the chip's tools. The chip carries its own knowledge. Pull it out, nothing breaks

```
/Volumes/YELLOW/
  heartbeat.json       identity (SHA-256 signed, tamper-detected)
  mcp/                 MCP server (runs FROM the card)
  models/              model weights (on the card)
  .jeff/docs/          hidden reference material
  Modelfile            model config
  vault.sparseimage    AES-256 encrypted vault
```

The card IS the computer.

## More than chips

A chip is one substrate. Jeff federates several behind the same MCP surface, each
declared by a manifest and surfaced the same way:

- **Chips** -- SD cards carrying an MCP server, model weights, and an encrypted vault
- **Vaults** -- named, addressable directories (nestable; each with a `.vault.json`
  manifest), whether on a card or on the local disk
- **Engines** -- models Jeff registers from mounted cards (`engine_sync` / `engine_list`)
- **Toolchains** -- external tool networks that declare themselves with a manifest.
  C2D2, the geometric-reasoning toolchain, is one: Jeff is the doorway; its reasoning
  stays with it

Drop a manifest, Jeff surfaces it. Swap the active card or vault, and the same stable
entrypoint routes to the new one -- no restart, and a vanished volume raises a clean
error instead of hanging the client.

## Tools

The chip surface -- spectral / VRGB addressing, where a hex code is a coordinate you
can zoom, split, and measure:

```
chip_status          identity, mode, root color
chip_read_card       read files off the card surface
chip_resolve_hex     hex -> spectral band + position
chip_resolve_deep    zoom N levels into a hex address
chip_midpoint        discover the address between two colors
chip_split_band      divide a range into n equal parts
chip_distance        hue distance in degrees
chip_tool_chain      Merkle-VRGB hash tree -> root color
chip_constellation   group hex colors by band proximity
chip_registry        Level 0 spectral bands
chip_query           ask the on-card model
```

Plus the substrate surface -- `vault_query`, `engine_list` / `engine_run` /
`engine_sync`, `toolchain_list`, and `chip_backup*` -- so vaults, engines, and
toolchains are reachable through the same doorway.

## Full flow

```bash
jeff scan                          # find chips
jeff flash /dev/disk4 --label X    # erase + burn
jeff activate /Volumes/X           # start MCP
jeff mount --read-write            # decrypt vault
jeff flip                          # toggle read-only/read-write
jeff unmount                       # seal vault
jeff deactivate                    # stop everything
jeff resolve "#FF5500"             # spectral binding CLI
jeff midpoint "#FF0000" "#00FF00"  # discover midpoints
jeff constellation "#F00" "#0F0" "#00F"
```

## Requirements

- macOS (hdiutil for AES-256 vault)
- Python 3
- MCP client (Claude Code, etc.)
- Ollama (optional, for on-card model inference)

## Install

```bash
git clone https://github.com/3DMATH/jeff.git
cd jeff
pip install -r requirements.txt
```

Jeff is built as the data plane of a larger personal ops engine, and stands alone as
a reference design for hardware-carried, hot-swappable AI substrate.

## Spec

[Booster Chip Protocol v1.0](chip/CHIP_SPEC_v1.0.md) -- frozen.

## License

Apache 2.0

---

3DMATH -- tooling for machines that see
