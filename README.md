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

> **Where this is going (2026-11-19).** This repo is the current Jeff **substrate** — the vault
> array, the bash CLI, the spectral tools, and the on-card MCP described below. The product is
> converging on a simpler, unified **Jeff card** model being built in
> [`3DMATH/cue`](https://github.com/3DMATH/cue): a card holds the model (plaintext weights), your
> home (plaintext files + `rules.md`), and one encrypted **brain** (the index) sealed with
> **N-factor auth** — the [`keeper`](https://github.com/3DMATH/keeper) reference component. The
> governing principle is *encrypt the map, never the territory*: content stays a normal file,
> only the brain is sealed. The `heartbeat.json` / `sparseimage` model below is the older
> substrate and will be reconciled toward that standard. `jeff tui` and `dev flash` already point
> the right way.

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

### Dev flash

```bash
jeff dev flash            # reduce the inserted card to the dev baseline
jeff dev flash /dev/diskN # or name the disk explicitly
```

Reduces a card to the **dev baseline**: nothing but the model weights, byte-identical to the
source. It stashes `models/`, erases + formats the card, restores only the weights, and verifies
the result is byte-identical (a sha-256 manifest of every file). Everything else -- heartbeat,
vault, MCP server, datasets, search index -- is dropped. Destructive (same confirm gate), but the
weights are stashed before the erase and kept safe if any step fails.

This bare card is the clean floor the product flash is designed on: the weights are the one
expensive thing worth preserving; all other provisioning is rebuilt deliberately.

## The terminal

```bash
jeff tui
```

A first-class, standalone terminal over the Vault Array -- a smaller cousin of Claude Code and
Cue Vault, on the **same chrome and sounds** ([cue-tui-kit](https://github.com/3DMATH/cue-tui-kit)).
It does not reimplement Jeff; it drives this same CLI, so it is always in sync with the
substrate. The command rail adapts to Jeff's state -- idle, activated, read-write, read-only --
and you arrow-step it, press Enter, or hit the letter, exactly like Cue Vault.

Installable on its own (pulls in the kit):

```bash
pip install jeff-tui        # provides `jeff-tui`; `jeff tui` also launches it
jeff tui
```

The Python TUI lives in `src/jefftui/` and shells out to the `jeff` CLI via `JEFF_CLI`. The old
sourced `tui.sh` (for a host shell like maestro) still works; this is the standalone face.

## Requirements

- macOS (hdiutil for AES-256 vault)
- Python 3
- MCP client (Claude Code, etc.)
- Ollama (optional, for on-card model inference)
- [cue-tui-kit](https://github.com/3DMATH/cue-tui-kit) for `jeff tui` (auto-found in a sibling checkout during dev)

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
