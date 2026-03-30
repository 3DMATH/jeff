"""Jeff MCP Proxy -- stable host-side entrypoint.

Claude Code points at this file in .mcp.json. It never changes.
On each tool call, reads .jeff-state.json to find the active chip
and routes to it dynamically. Swap chips without restarting.
"""

import json
import os
import sys
import threading

JEFF_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(JEFF_DIR, ".jeff-state.json")
SPECTRAL_DIR = os.path.join(JEFF_DIR, "spectral")

sys.path.insert(0, SPECTRAL_DIR)

from mcp.server.fastmcp import FastMCP
import spectral

mcp = FastMCP("jeff")

# cue-vox stream notification (fire-and-forget)
CUE_VOX_PORT = os.environ.get("CUE_VOX_PORT", "3000")
CUE_VOX_CHIP_OP_URL = "http://localhost:%s/api/chip/op" % CUE_VOX_PORT


def _notify_stream(op, summary="", chip_data=None):
    """POST chip op to cue-vox stream. Non-blocking, best-effort."""
    state = _active_state()
    label = state.get("label", "?") if state else "?"
    root = "#888888"
    if state:
        hb_path = os.path.join(state.get("volume_path", ""), "heartbeat.json")
        if os.path.isfile(hb_path):
            with open(hb_path) as f:
                hb = json.load(f)
            root = hb.get("tool_chain", {}).get("root", root)

    payload = {
        "op": op,
        "label": label,
        "root_color": root,
        "summary": summary,
        "chip_data": chip_data or {},
    }

    def _post():
        try:
            import urllib.request
            req = urllib.request.Request(
                CUE_VOX_CHIP_OP_URL,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # best-effort, cue-vox may not be running

    threading.Thread(target=_post, daemon=True).start()


# ============================================================
# STATE HELPERS
# ============================================================

def _active_state():
    """Read current chip state. Returns dict or None."""
    if not os.path.isfile(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        state = json.load(f)
    volume = state.get("volume_path", "")
    if not volume or not os.path.isdir(volume):
        return None
    return state


def _require_chip():
    """Return active state or raise with a clear message."""
    state = _active_state()
    if state is None:
        return None, "No chip active. Insert a chip and run: jeff activate /Volumes/NAME"
    return state, None


# ============================================================
# CHIP TOOLS
# ============================================================

@mcp.tool()
def chip_status():
    """Chip identity, mode, and capabilities."""
    state, err = _require_chip()
    if err:
        return json.dumps({"error": err})

    volume = state["volume_path"]
    hb_path = os.path.join(volume, "heartbeat.json")
    hb = {}
    if os.path.isfile(hb_path):
        with open(hb_path) as f:
            hb = json.load(f)

    chain = hb.get("tool_chain", {})
    root = chain.get("root", "#000000")

    result = {
        "label": state.get("label", "?"),
        "device_id": state.get("device_id", "?"),
        "mode": state.get("mode", "?"),
        "root_color": root,
        "band": spectral.resolve(root).get("band", "?") if root != "#000000" else "unknown",
        "model": state.get("model", ""),
        "volume": volume,
        "vault_mounted": bool(state.get("vault_mount")),
        "mount_count": hb.get("mount_count", 0),
    }
    _notify_stream("status", "status checked", result)
    return json.dumps(result, indent=2)


@mcp.tool()
def chip_read_card(filename: str = ""):
    """Read a file from the card surface (no vault needed).

    Args:
        filename: File to read. Empty to list all files on the card.
    """
    state, err = _require_chip()
    if err:
        return json.dumps({"error": err})

    _notify_stream("read_card", "read: %s" % (filename or "(list)"))

    volume = state["volume_path"]

    if not filename:
        files = []
        for f in sorted(os.listdir(volume)):
            if f.startswith(".") and f != ".jeff":
                continue
            full = os.path.join(volume, f)
            if os.path.isfile(full):
                files.append({"name": f, "size_bytes": os.path.getsize(full)})
            elif os.path.isdir(full):
                files.append({"name": f + "/", "type": "directory"})
        return json.dumps({"volume": volume, "files": files}, indent=2)

    requested = os.path.normpath(os.path.join(volume, filename))
    if not requested.startswith(volume):
        return json.dumps({"error": "Path traversal denied"})

    if os.path.isdir(requested):
        entries = []
        for f in sorted(os.listdir(requested)):
            full = os.path.join(requested, f)
            if os.path.isfile(full):
                entries.append({"name": f, "size_bytes": os.path.getsize(full)})
            elif os.path.isdir(full):
                entries.append({"name": f + "/", "type": "directory"})
        return json.dumps({"path": filename, "files": entries}, indent=2)

    if not os.path.isfile(requested):
        return json.dumps({"error": "File not found: %s" % filename})

    try:
        with open(requested, "r", encoding="utf-8") as f:
            content = f.read()
        return json.dumps({"file": filename, "content": content}, indent=2)
    except UnicodeDecodeError:
        return json.dumps({"file": filename, "error": "Binary file", "size_bytes": os.path.getsize(requested)})


@mcp.tool()
def chip_tool_chain():
    """Show this chip's Merkle-VRGB tool chain and root color."""
    state, err = _require_chip()
    if err:
        return json.dumps({"error": err})

    _notify_stream("tool_chain", "tool chain verified")

    hb_path = os.path.join(state["volume_path"], "heartbeat.json")
    if os.path.isfile(hb_path):
        with open(hb_path) as f:
            hb = json.load(f)
        chain = hb.get("tool_chain", {})
        if chain:
            chain["spectral"] = spectral.resolve(chain.get("root", "#000000"))
            return json.dumps(chain, indent=2)
    return json.dumps({"error": "No tool chain found"})


# ============================================================
# SPECTRAL BINDING (host-side, no chip needed)
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
# MODEL INFERENCE (delegates to chip)
# ============================================================

@mcp.tool()
def chip_query(prompt: str, system: str = "", max_tokens: int = 2048):
    """Ask the chip model a question."""
    state, err = _require_chip()
    if err:
        return json.dumps({"error": err})

    truncated = prompt[:60] + ("..." if len(prompt) > 60 else "")
    _notify_stream("query", "query: \"%s\"" % truncated)

    volume = state["volume_path"]
    mcp_dir = os.path.join(volume, "mcp")
    sys.path.insert(0, mcp_dir)

    try:
        import inference
        return inference.generate(
            prompt=prompt,
            system=system or "You are Jeff, a helpful assistant on a Booster Chip.",
            max_tokens=max_tokens,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})
    finally:
        sys.path.remove(mcp_dir) if mcp_dir in sys.path else None


@mcp.tool()
def chip_search(query: str, top_k: int = 5):
    """Search the chip's knowledge base.

    Args:
        query: What to search for in natural language.
        top_k: Number of results to return (default 5).
    """
    state, err = _require_chip()
    if err:
        return json.dumps({"error": err})

    truncated_q = query[:60] + ("..." if len(query) > 60 else "")
    _notify_stream("search", "search: \"%s\"" % truncated_q)

    volume = state["volume_path"]
    mcp_dir = os.path.join(volume, "mcp")
    index_path = os.path.join(volume, ".jeff", "index", "search.json")

    if not os.path.isfile(index_path):
        return json.dumps({"error": "No search index. Run: python3 build_index.py %s" % volume})

    sys.path.insert(0, mcp_dir)
    try:
        import inference
        from build_index import search, cosine_similarity

        query_embedding = inference.embed(query)
        if not query_embedding:
            return json.dumps({"error": "Embedding failed -- is Ollama running with nomic-embed-text?"})

        results = search(index_path, query_embedding, top_k=top_k)
        return json.dumps({"query": query, "results": results}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
    finally:
        sys.path.remove(mcp_dir) if mcp_dir in sys.path else None


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
