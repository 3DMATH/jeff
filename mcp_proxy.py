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
# BACKUP (host-side, manages content file backups)
# ============================================================

MAESTRO_ROOT = os.path.dirname(os.path.dirname(JEFF_DIR))

sys.path.insert(0, JEFF_DIR)
import backup as _backup


def _resolve_chip(chip_name):
    """Resolve chip name to staging directory path."""
    chip_dir = os.path.join(MAESTRO_ROOT, "chip-%s" % chip_name.lower())
    if os.path.isdir(chip_dir):
        return chip_dir
    # Try active chip
    state = _active_state()
    if state and state.get("label", "").lower() == chip_name.lower():
        return state["volume_path"]
    return None


@mcp.tool()
def chip_backup(chip_name: str):
    """Back up a chip's content files to the blob store.

    Hashes all files in HOT/ and COLD/, stores deduplicated blobs,
    writes a timestamped manifest. Git tracks metadata; this tracks content.

    Args:
        chip_name: Chip color (yellow, red, blue) or label.
    """
    chip_dir = _resolve_chip(chip_name)
    if not chip_dir:
        return json.dumps({"error": "Chip not found: %s" % chip_name})

    _notify_stream("backup", "backing up %s" % chip_name)
    result = _backup.backup(chip_name.lower(), chip_dir)
    _notify_stream("backup_done", result.get("message", "backup complete"))
    return json.dumps(result, indent=2)


@mcp.tool()
def chip_backup_status(chip_name: str):
    """Show backup history and state for a chip.

    Args:
        chip_name: Chip color (yellow, red, blue) or label.
    """
    return json.dumps(_backup.status(chip_name.lower()), indent=2)


@mcp.tool()
def chip_backup_rotate(chip_name: str, max_backups: int = 5):
    """Rotate old backups, keeping only the N most recent.

    Blobs are shared and never deleted during rotation -- only manifests
    are pruned. This is safe even with cross-chip deduplication.

    Args:
        chip_name: Chip color (yellow, red, blue) or label.
        max_backups: Maximum number of backup manifests to retain (default 5).
    """
    result = _backup.rotate(chip_name.lower(), max_backups)
    return json.dumps(result, indent=2)


@mcp.tool()
def chip_backup_list(chip_name: str, manifest: str = ""):
    """List files in a backup manifest.

    Shows each file, its hash, and whether the blob is available.
    Defaults to the latest backup if no manifest specified.

    Args:
        chip_name: Chip color (yellow, red, blue) or label.
        manifest: Specific manifest filename (default: latest).
    """
    result = _backup.restore_list(chip_name.lower(), manifest or None)
    return json.dumps(result, indent=2)


# ============================================================
# DYNAMIC VAULT ROUTING
# ============================================================

import sqlite3

VOLUMES_ACTIVE_FILE = os.path.join(JEFF_DIR, ".jeff-volumes-active.json")
VOLUMES_FILE = os.path.join(JEFF_DIR, "volumes.json")


def _load_active_volumes():
    """Load active volume names."""
    if not os.path.isfile(VOLUMES_ACTIVE_FILE):
        return []
    with open(VOLUMES_ACTIVE_FILE) as f:
        return json.load(f)


def _load_registry():
    """Load volume registry, including physical chips at /Volumes/."""
    if not os.path.isfile(VOLUMES_FILE):
        registry = []
    else:
        with open(VOLUMES_FILE) as f:
            registry = json.load(f)

    # Scan /Volumes/ for physical chips
    volumes_dir = "/Volumes"
    if os.path.isdir(volumes_dir):
        known_paths = {v["path"] for v in registry}
        for name in sorted(os.listdir(volumes_dir)):
            vol = os.path.join(volumes_dir, name)
            hb = os.path.join(vol, "heartbeat.json")
            if not os.path.isfile(hb) or name == "Macintosh HD":
                continue
            if vol in known_paths:
                continue
            try:
                with open(hb) as f:
                    chip = json.load(f)
                label = chip.get("label", name)
                registry.append({
                    "name": "sd:%s" % label.lower(),
                    "type": "chip",
                    "path": vol,
                    "physical": True,
                    "label": label,
                })
            except Exception:
                continue

    return registry


def _discover_active_vaults():
    """Discover all vaults across active volumes. Returns list of vault dicts."""
    active = set(_load_active_volumes())
    registry = _load_registry()
    vaults = []

    for vol in registry:
        if vol["name"] not in active:
            continue
        vol_path = vol["path"] if os.path.isabs(vol["path"]) else os.path.join(MAESTRO_ROOT, vol["path"])
        if not os.path.isdir(vol_path):
            continue

        if vol["type"] == "local":
            # Local volume IS a vault
            db = os.path.join(vol_path, "vault.db")
            vaults.append({
                "vault": vol["name"],
                "volume": vol["name"],
                "type": "local",
                "path": vol_path,
                "db": db if os.path.isfile(db) else None,
                "env": vol.get("env", {}),
            })
        else:
            # Chip -- discover vault-* subdirs
            for d in sorted(os.listdir(vol_path)):
                vault_dir = os.path.join(vol_path, d)
                if not os.path.isdir(vault_dir) or not d.startswith("vault-"):
                    continue
                db = os.path.join(vault_dir, "vault.db")
                vault_name = d.replace("vault-", "")
                vaults.append({
                    "vault": vault_name,
                    "volume": vol["name"],
                    "type": "chip",
                    "path": vault_dir,
                    "db": db if os.path.isfile(db) else None,
                })

    return vaults


def _find_vault(vault_name):
    """Find a specific vault by name across active volumes."""
    for v in _discover_active_vaults():
        if v["vault"] == vault_name:
            return v
    return None


def _vault_db_query(vault, query, params=()):
    """Run a query against a vault's database."""
    if not vault.get("db"):
        return []
    try:
        conn = sqlite3.connect(vault["db"])
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        conn.close()
        return rows
    except sqlite3.OperationalError:
        return []


def _vault_db_execute(vault, query, params=()):
    """Execute a write query against a vault's database."""
    if not vault.get("db"):
        return {"error": "no database"}
    try:
        conn = sqlite3.connect(vault["db"])
        cur = conn.execute(query, params)
        conn.commit()
        result = {"rows_affected": cur.rowcount, "lastrowid": cur.lastrowid}
        conn.close()
        return result
    except sqlite3.OperationalError as e:
        return {"error": str(e)}


@mcp.tool()
def chip_discover():
    """Discover all active vaults across all activated volumes.

    Call this first to see what vaults are available. Each vault
    can be queried via vault_query(vault=name, operation=...).
    """
    vaults = _discover_active_vaults()
    result = []
    for v in vaults:
        info = {
            "vault": v["vault"],
            "volume": v["volume"],
            "type": v["type"],
        }
        if v.get("db"):
            try:
                conn = sqlite3.connect(v["db"])
                entries = conn.execute("SELECT COUNT(DISTINCT slug) FROM vault_images").fetchone()[0]
                images = conn.execute("SELECT COUNT(*) FROM vault_images").fetchone()[0]
                conn.close()
                info["entries"] = entries
                info["images"] = images
            except Exception:
                info["entries"] = 0
                info["images"] = 0
        else:
            info["entries"] = 0
            info["images"] = 0

        # Check for cue-sheet
        info["has_cuesheet"] = os.path.isfile(os.path.join(v["path"], "cue-sheet.yaml"))
        result.append(info)

    return json.dumps({
        "active_volumes": sorted(set(v["volume"] for v in vaults)),
        "vaults": result,
        "operations": [
            "status", "search", "get", "list_images",
            "search_images", "filter",
            "gallery", "list_galleries", "get_gallery",
            "annotate", "get_annotations",
            "ingest",
        ],
    }, indent=2)


@mcp.tool()
def vault_query(vault: str, operation: str, slug: str = "", query: str = "",
                filename: str = "", body: str = "", title: str = "",
                slugs: str = "", tag: str = "", era: str = "",
                limit: int = 50):
    """Query any active vault dynamically. Call chip_discover first to see available vaults.

    Args:
        vault: Vault name (e.g. "hot", "cold", "rose", "finbot", "geo")
        operation: One of: status, search, get, list_images, search_images,
                   filter, gallery, list_galleries, get_gallery,
                   annotate, get_annotations, ingest
        slug: Entry slug (for get, annotate, get_annotations, gallery)
        query: Search query string (for search, search_images, gallery)
        filename: Filename (for annotate, get_annotations)
        body: Annotation body (for annotate)
        title: Gallery title (for gallery create)
        slugs: Comma-separated slugs (for gallery create)
        tag: Tag filter (for filter)
        era: Era filter (for filter)
        limit: Result limit (default 50)
    """
    v = _find_vault(vault)
    if not v:
        available = [x["vault"] for x in _discover_active_vaults()]
        return json.dumps({
            "error": "Vault '%s' not found or not active" % vault,
            "available_vaults": available,
        })

    from datetime import datetime, timezone
    utc_now = datetime.now(timezone.utc).isoformat()

    if operation == "status":
        entries = 0
        images = 0
        if v.get("db"):
            try:
                conn = sqlite3.connect(v["db"])
                entries = conn.execute("SELECT COUNT(DISTINCT slug) FROM vault_images").fetchone()[0]
                images = conn.execute("SELECT COUNT(*) FROM vault_images").fetchone()[0]
                conn.close()
            except Exception:
                pass
        return json.dumps({
            "vault": vault,
            "volume": v["volume"],
            "type": v["type"],
            "entries": entries,
            "images": images,
        })

    elif operation == "search":
        pattern = "%%%s%%" % (query or "")
        rows = _vault_db_query(v,
            "SELECT DISTINCT slug FROM vault_images WHERE slug LIKE ? ORDER BY slug LIMIT ?",
            (pattern, int(limit)))
        return json.dumps(rows)

    elif operation == "get":
        if not slug:
            return json.dumps({"error": "slug required for get"})
        rows = _vault_db_query(v,
            "SELECT slug, filename, port FROM vault_images WHERE slug = ? ORDER BY filename",
            (slug,))
        return json.dumps(rows)

    elif operation == "list_images":
        rows = _vault_db_query(v,
            "SELECT slug, filename, port FROM vault_images ORDER BY slug, filename LIMIT ?",
            (int(limit),))
        return json.dumps(rows)

    elif operation == "search_images":
        pattern = "%%%s%%" % (query or "")
        rows = _vault_db_query(v,
            "SELECT slug, filename, port FROM vault_images "
            "WHERE slug LIKE ? OR filename LIKE ? ORDER BY slug, filename LIMIT ?",
            (pattern, pattern, int(limit)))
        return json.dumps(rows)

    elif operation == "filter":
        rows = _vault_db_query(v,
            "SELECT DISTINCT slug FROM vault_images ORDER BY slug LIMIT ?",
            (int(limit),))
        return json.dumps(rows)

    elif operation == "list_galleries":
        rows = _vault_db_query(v,
            "SELECT slug, title, created_at FROM galleries ORDER BY created_at DESC LIMIT ?",
            (int(limit),))
        return json.dumps(rows)

    elif operation == "get_gallery":
        if not slug:
            return json.dumps({"error": "slug required for get_gallery"})
        rows = _vault_db_query(v,
            "SELECT slug, title, images, created_at FROM galleries WHERE slug = ? LIMIT 1",
            (slug,))
        if not rows:
            return json.dumps({})
        gallery = rows[0]
        raw = gallery.get("images")
        if isinstance(raw, str):
            try:
                gallery["images"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                gallery["images"] = []
        return json.dumps(gallery)

    elif operation == "gallery":
        if not title:
            return json.dumps({"error": "title required to create a gallery"})
        gal_slug = "gallery-%d" % int(datetime.now(timezone.utc).timestamp())
        images = []
        if slugs:
            for s in slugs.split(","):
                s = s.strip()
                imgs = _vault_db_query(v,
                    "SELECT slug, filename, port FROM vault_images WHERE slug = ? ORDER BY filename",
                    (s,))
                images.extend(imgs)
        elif query:
            pattern = "%%%s%%" % query
            images = _vault_db_query(v,
                "SELECT slug, filename, port FROM vault_images "
                "WHERE slug LIKE ? OR filename LIKE ? ORDER BY slug, filename LIMIT 50",
                (pattern, pattern))
        result = _vault_db_execute(v,
            "INSERT OR REPLACE INTO galleries (slug, title, images, created_at) VALUES (?, ?, ?, ?)",
            (gal_slug, title, json.dumps(images), utc_now))
        return json.dumps({"slug": gal_slug, "title": title, "images": images, "created_at": utc_now})

    elif operation == "annotate":
        if not slug or not filename or not body:
            return json.dumps({"error": "slug, filename, and body required for annotate"})
        result = _vault_db_execute(v,
            "INSERT INTO vault_annotations (slug, filename, content, source, created_at) "
            "VALUES (?, ?, ?, 'mcp', ?)",
            (slug, filename, body, utc_now))
        return json.dumps({"slug": slug, "filename": filename, "body": body, "id": result.get("lastrowid")})

    elif operation == "get_annotations":
        q = "SELECT id, slug, filename, content as body, pinned FROM vault_annotations"
        params = []
        filters = []
        if slug:
            filters.append("slug = ?")
            params.append(slug)
        if filename:
            filters.append("filename = ?")
            params.append(filename)
        if filters:
            q += " WHERE " + " AND ".join(filters)
        q += " ORDER BY id DESC"
        rows = _vault_db_query(v, q, tuple(params))
        return json.dumps(rows)

    elif operation == "ingest":
        # Only for local vaults with ingest.py
        ingest_script = os.path.join(v["path"], "app", "ingest.py")
        if not os.path.isfile(ingest_script):
            return json.dumps({"error": "No ingest script for vault %s" % vault})
        import subprocess
        cmd = [sys.executable, ingest_script]
        if slug:
            cmd.append(slug)
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=v["path"])
        return json.dumps({"status": "ok" if result.returncode == 0 else "error",
                          "output": result.stdout.strip(),
                          "error": result.stderr.strip() if result.returncode != 0 else ""})

    else:
        return json.dumps({"error": "Unknown operation: %s" % operation,
                          "valid": ["status", "search", "get", "list_images", "search_images",
                                   "filter", "gallery", "list_galleries", "get_gallery",
                                   "annotate", "get_annotations", "ingest"]})


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
