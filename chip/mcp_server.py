"""Jeff MCP Server -- Booster Chip tools.

Runs in activated mode (no vault) or mounted mode (full vault access).
Spectral Binding tools are always available.
"""

import json
import os
import sys

# MCP server runs from the card: /Volumes/YELLOW/mcp/server.py
# spectral.py and tool_chain.py are siblings in the same directory
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _MCP_DIR)

from mcp.server.fastmcp import FastMCP

import spectral
import tool_chain as tc

DEVICE_ID = os.environ.get("CHIP_DEVICE_ID", "unknown")
LABEL = os.environ.get("CHIP_LABEL", "Unknown")
VOLUME_PATH = os.environ.get("CHIP_VOLUME", "")
VAULT_MOUNT = os.environ.get("CHIP_VAULT_MOUNT", "")
CHIP_MODE = os.environ.get("CHIP_MODE", "activated")
MODEL = os.environ.get("CHIP_MODEL", "")

mcp = FastMCP("jeff")


# ============================================================
# STATUS
# ============================================================

@mcp.tool()
def chip_status():
    """Chip identity, mode, and capabilities."""
    hb_path = os.path.join(VOLUME_PATH, "heartbeat.json")
    hb = {}
    if os.path.isfile(hb_path):
        with open(hb_path) as f:
            hb = json.load(f)

    chain = hb.get("tool_chain", {})
    root = chain.get("root", "#000000")

    return json.dumps({
        "label": LABEL,
        "device_id": DEVICE_ID,
        "mode": CHIP_MODE,
        "root_color": root,
        "band": spectral.resolve(root).get("band", "?") if root != "#000000" else "unknown",
        "model": MODEL,
        "volume": VOLUME_PATH,
        "vault_mounted": bool(VAULT_MOUNT),
        "mount_count": hb.get("mount_count", 0),
    }, indent=2)


# ============================================================
# CARD SURFACE (unencrypted files, always readable)
# ============================================================

@mcp.tool()
def chip_read_card(filename: str = ""):
    """Read a file from the card surface (no vault needed).

    Files on the card root are unencrypted and always readable
    when the card is plugged in. This is how the chip shares
    public content like papers, specs, and documentation.

    Args:
        filename: File to read. Empty to list all files on the card.
    """
    if not VOLUME_PATH or not os.path.isdir(VOLUME_PATH):
        return json.dumps({"error": "No card volume available"})

    if not filename:
        files = []
        for f in sorted(os.listdir(VOLUME_PATH)):
            if f.startswith("."):
                continue
            full = os.path.join(VOLUME_PATH, f)
            if os.path.isfile(full):
                files.append({"name": f, "size_bytes": os.path.getsize(full)})
            elif os.path.isdir(full):
                files.append({"name": f + "/", "type": "directory"})
        return json.dumps({"volume": VOLUME_PATH, "files": files}, indent=2)

    safe_name = os.path.basename(filename)
    path = os.path.join(VOLUME_PATH, safe_name)

    if not os.path.isfile(path):
        return json.dumps({"error": "File not found: %s" % safe_name})

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.dumps({"file": safe_name, "content": content}, indent=2)
    except UnicodeDecodeError:
        return json.dumps({"file": safe_name, "error": "Binary file", "size_bytes": os.path.getsize(path)})


# ============================================================
# SPECTRAL BINDING
# ============================================================

@mcp.tool()
def chip_resolve_hex(hex_color: str):
    """Resolve a hex color to its spectral band, hue, and position."""
    return json.dumps(spectral.resolve(hex_color), indent=2)


@mcp.tool()
def chip_resolve_deep(hex_color: str, depth: int = 3):
    """Resolve a hex color through multiple zoom levels."""
    return json.dumps(spectral.resolve_deep(hex_color, depth), indent=2)


@mcp.tool()
def chip_midpoint(hex_a: str, hex_b: str):
    """Find the midpoint between two hex colors in HSL space."""
    return json.dumps(spectral.midpoint(hex_a, hex_b), indent=2)


@mcp.tool()
def chip_split_band(hex_a: str, hex_b: str, n: int = 2):
    """Split the range between two hex colors into n equal parts."""
    points = spectral.split_band(hex_a, hex_b, n)
    result = [{"hex": p, "hue": spectral.resolve(p)["hue"], "band": spectral.resolve(p)["band"]} for p in points]
    return json.dumps(result, indent=2)


@mcp.tool()
def chip_distance(hex_a: str, hex_b: str):
    """Shortest arc hue distance between two hex colors."""
    return json.dumps({"hex_a": hex_a, "hex_b": hex_b, "distance_degrees": spectral.hue_distance(hex_a, hex_b)}, indent=2)


@mcp.tool()
def chip_tool_chain():
    """Show this chip's Merkle-VRGB tool chain and root color."""
    hb_path = os.path.join(VOLUME_PATH, "heartbeat.json")
    if os.path.isfile(hb_path):
        with open(hb_path) as f:
            hb = json.load(f)
        chain = hb.get("tool_chain", {})
        if chain:
            chain["spectral"] = spectral.resolve(chain.get("root", "#000000"))
            return json.dumps(chain, indent=2)
    return json.dumps({"error": "No tool chain found"})


@mcp.tool()
def chip_constellation(hex_colors: str):
    """Group hex colors by spectral band proximity.

    Args:
        hex_colors: Comma-separated hex colors.
    """
    colors = [c.strip() for c in hex_colors.split(",") if c.strip()]
    return json.dumps({
        "groups": spectral.constellation(colors),
        "summary": spectral.constellation_summary(colors),
    }, indent=2)


@mcp.tool()
def chip_registry():
    """Show the Level 0 spectral band registry."""
    return json.dumps(spectral.registry(), indent=2)


# ============================================================
# MODEL INFERENCE
# ============================================================

@mcp.tool()
def chip_query(prompt: str, system: str = "", max_tokens: int = 2048):
    """Ask the chip model a question."""
    try:
        import inference
        return inference.generate(prompt=prompt, system=system or "You are Jeff, a helpful assistant on a Booster Chip.", max_tokens=max_tokens)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
