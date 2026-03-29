```
       ██╗███████╗███████╗███████╗
       ██║██╔════╝██╔════╝██╔════╝
       ██║█████╗  █████╗  █████╗
  ██   ██║██╔══╝  ██╔══╝  ██╔══╝
  ╚█████╔╝███████╗██║     ██║
   ╚════╝ ╚══════╝╚═╝     ╚═╝
```

Jeff is a chip you plug into your computer so your AI can learn Spectral Binding.

Put an SD card in. Run five commands. Your AI is reading a paper about spatial cognition off the chip and running the math live. That's it.

## What you need

- An SD card (any size)
- macOS
- Python 3
- Claude Code (or any MCP client)

## Setup

```bash
git clone https://github.com/3DMATH/jeff.git
cd jeff
pip install -r requirements.txt
```

## Step 1: Make a chip

Put your SD card in. Find it in /Volumes/.

```bash
./jeff init /Volumes/MYCARD --label MYCARD
```

It asks for a passphrase. Pick one. This encrypts the vault on the card. You now have a Booster Chip.

## Step 2: Scan

```bash
./jeff scan
```

Jeff finds the chip, reads its identity, and shows its root color. The root color is a hex value derived from the chip's tool chain. Every chip with the same tools gets the same color.

## Step 3: Activate

```bash
./jeff activate /Volumes/MYCARD
```

The chip is alive. MCP server is running. No passphrase needed -- activation reads the identity file on the card, not the encrypted vault. The chip has a pulse.

## Step 4: Talk to it

Add Jeff to your Claude Code MCP config (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "jeff": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/jeff/chip/mcp_server.py"],
      "env": {
        "CHIP_DEVICE_ID": "from-heartbeat-json",
        "CHIP_LABEL": "MYCARD",
        "CHIP_VOLUME": "/Volumes/MYCARD",
        "CHIP_MODE": "activated",
        "CHIP_MODEL": ""
      }
    }
  }
}
```

Or just activate the chip and point your MCP client at `chip/mcp_server.py`.

Now ask Claude:

> "What's on the chip?"

Claude calls `chip_read_card` and lists the files on the card. One of them is `spectral-binding.md`.

> "Read spectral-binding.md from the chip."

Claude reads the full Spectral Binding paper directly off the SD card. It now understands the theory.

> "Show me the spectral bands."

Claude calls `chip_registry`. Six bands. The hue wheel.

> "What band is #F882C9 in?"

Claude calls `chip_resolve_hex`. Experiment band. Hue 323.9.

> "Find the color between #FF0000 and #00FF00."

Claude calls `chip_midpoint`. Discovers an address that was always there.

> "Zoom 5 levels into #3A7F2B."

Claude calls `chip_resolve_deep`. Same 7-21 bands at every level. Infinite depth. Constant cognitive load.

The paper is the theory. The tools are the proof. Both on the same card.

## Step 5: Deactivate

```bash
./jeff deactivate
```

MCP stops. Pull the card. Done.

## What just happened

You turned an SD card into a portable MCP server with Spectral Binding tools. The chip carries its own identity (cryptographically signed), its own tool chain (Merkle-hashed to a root color), and its own encrypted vault (for credentials and state you add later).

The tools on the chip implement Spectral Binding -- a namespace system where hex colors are addresses, the hue wheel is the hierarchy, and you never run out of room because the color continuum is infinite.

## What is Spectral Binding

One rule: at any zoom level, divide into no more than 21 human-perceivable bands. Split any band by discovering the midpoint. The namespace is the continuum. Addresses are discovered, not assigned.

This means:
- 16.7 million addresses at 24-bit (6 hex chars)
- Infinite depth with 7-21 things visible at each level
- No category system that breaks when you add a 13th item
- The machine sees full hex precision, the human sees named colors

Read the full paper: [spectral/spectral-binding.md](spectral/spectral-binding.md)

## MCP Tools

These are the tools Claude gets when a chip is activated:

| Tool | What it does |
|------|-------------|
| `chip_read_card` | List or read files on the card (no vault needed) |
| `chip_status` | Chip identity, mode, root color, band |
| `chip_resolve_hex` | Resolve any hex to its spectral band and position |
| `chip_resolve_deep` | Zoom multiple levels into a hex address |
| `chip_midpoint` | Discover the address between two colors |
| `chip_split_band` | Divide a range into n equal parts |
| `chip_distance` | Hue distance between two colors in degrees |
| `chip_tool_chain` | This chip's Merkle tree and root color |
| `chip_constellation` | Group multiple hex colors by band proximity |
| `chip_registry` | The 6 Level 0 spectral bands |
| `chip_query` | Ask the chip's local model a question |

## Lineage

Spectral Binding is the formal argument for [VRGB](https://github.com/nickcottrell/haberdash) -- a hexadecimal colorspace encoding system developed at 3DMATH. VRGB uses hex color coordinates as spatial addresses for n-dimensional parameters.

The progression:
1. **VRGB** (2025) -- hex colors as parameter addresses. Shipped in [haberdash](https://github.com/nickcottrell/haberdash) design system.
2. **Spectral Binding** (2026) -- the measurement axiom. Why VRGB works: cognition-bounded continuous namespace.
3. **Jeff** (2026) -- the reference implementation. Plug in a chip, talk to the math.

## Chip Spec

The [Booster Chip Protocol v1.0](chip/CHIP_SPEC_v1.0.md) defines the format. It is frozen. The card layout:

```
/Volumes/MYCARD/
  heartbeat.json       Identity + tool chain + pulse config (readable)
  vault.sparseimage    AES-256 encrypted (credentials, state, firmware)
```

## Security

- AES-256 encrypted vault (macOS hdiutil)
- Ed25519 device identity
- Firmware checksum verified on every mount
- Identity hash detects tampering
- Read-only by default
- MCP dies on deactivate

## License

Apache 2.0

---

3DMATH -- tools for spatial cognition
