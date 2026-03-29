```
       ██╗███████╗███████╗███████╗
       ██║██╔════╝██╔════╝██╔════╝
       ██║█████╗  █████╗  █████╗
  ██   ██║██╔══╝  ██╔══╝  ██╔══╝
  ╚█████╔╝███████╗██║     ██║
   ╚════╝ ╚══════╝╚═╝     ╚═╝
```

Your AI only knows what's on the host. Jeff fixes that.

Plug in an SD card. Your AI gets its own tools, its own model,
and knowledge that lives on the card -- not in the cloud, not
in the config, on the hardware. Pull it out, it's gone. Plug
it into another machine, it's there.

```bash
jeff flash /dev/disk4 --label YELLOW
jeff activate /Volumes/YELLOW
```

Ask your AI: "tell me about spectral binding."

It answers from the chip. It didn't know that before you plugged it in.

## What happens

1. Flash burns an MCP server, model weights, and an encrypted vault onto the card
2. Activate verifies the chip identity (SHA-256), starts the MCP, injects a CueSheet
3. Your AI gets 11 tools. The chip carries its own knowledge. Pull it out, nothing breaks

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

## Tools

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

## Spec

[Booster Chip Protocol v1.0](chip/CHIP_SPEC_v1.0.md) -- frozen.

## License

Apache 2.0

---

3DMATH -- tooling for machines that see
