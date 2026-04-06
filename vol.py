#!/usr/bin/env python3
"""Jeff volume manager -- activate/deactivate volumes, regenerate .mcp.json.

All volumes (local vaults and chips) are managed uniformly.
Activated = visible to MCP chain. Deactivated = invisible.

Usage:
    vol.py list                  # show all volumes
    vol.py up <name>             # activate a volume
    vol.py down <name>           # deactivate a volume
    vol.py active                # list active volume names
    vol.py regen                 # regenerate .mcp.json from active state
    vol.py init                  # activate auto_activate volumes on first run
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

JEFF_DIR = Path(__file__).resolve().parent
MAESTRO_ROOT = JEFF_DIR.parent.parent
VOLUMES_FILE = JEFF_DIR / "volumes.json"
ACTIVE_FILE = JEFF_DIR / ".jeff-volumes-active.json"
MCP_JSON = MAESTRO_ROOT / ".mcp.json"

# Static MCP entries that Jeff never touches
STATIC_MCP = {
    "jeff": {
        "type": "stdio",
        "command": "python3",
        "args": ["tools/jeff/mcp_proxy.py"],
    },
    "legacy": {
        "type": "stdio",
        "command": "python3",
        "args": ["tools/legacy-mcp/server.py"],
    },
}


VOLUMES_SCAN_DIR = Path("/Volumes")


def load_registry():
    """Load the volume registry, including physical chips at /Volumes/."""
    if not VOLUMES_FILE.exists():
        registry = []
    else:
        with open(VOLUMES_FILE) as f:
            registry = json.load(f)

    # Scan /Volumes/ for physical chips with heartbeat.json
    known_paths = {v["path"] for v in registry}
    if VOLUMES_SCAN_DIR.is_dir():
        for d in sorted(VOLUMES_SCAN_DIR.iterdir()):
            hb = d / "heartbeat.json"
            if not hb.is_file():
                continue
            # Skip macOS system volume
            if d.name == "Macintosh HD":
                continue
            try:
                with open(hb) as f:
                    chip = json.load(f)
                vol_path = str(d)
                # Skip if a registry entry already points here
                if vol_path in known_paths or str(d.relative_to("/")) in known_paths:
                    continue
                label = chip.get("label", d.name)
                name = "sd:%s" % label.lower()
                registry.append({
                    "name": name,
                    "type": "chip",
                    "path": vol_path,
                    "physical": True,
                    "label": label,
                })
            except Exception:
                continue

    return registry


def load_active():
    """Load the active volumes list."""
    if not ACTIVE_FILE.exists():
        return []
    with open(ACTIVE_FILE) as f:
        return json.load(f)


def save_active(active_names):
    """Save the active volumes list."""
    with open(ACTIVE_FILE, "w") as f:
        json.dump(sorted(set(active_names)), f, indent=2)
        f.write("\n")


def _vault_info(vault_path):
    """Get entry count and size for a vault."""
    entries = 0
    images = 0
    db = vault_path / "vault.db"
    if db.exists():
        try:
            conn = sqlite3.connect(str(db))
            entries = conn.execute("SELECT COUNT(DISTINCT slug) FROM vault_images").fetchone()[0]
            images = conn.execute("SELECT COUNT(*) FROM vault_images").fetchone()[0]
            conn.close()
        except Exception:
            pass

    hot = vault_path / "HOT"
    size_bytes = 0
    if hot.exists():
        for f in hot.rglob("*"):
            if f.is_file():
                size_bytes += f.stat().st_size

    if size_bytes == 0:
        size_str = "empty"
    elif size_bytes < 1024 * 1024:
        size_str = "%dK" % (size_bytes // 1024)
    elif size_bytes < 1024 * 1024 * 1024:
        size_str = "%dM" % (size_bytes // (1024 * 1024))
    else:
        size_str = "%.1fG" % (size_bytes / (1024 * 1024 * 1024))

    return entries, images, size_str


def _vol_path(vol):
    """Resolve volume path -- absolute for physical chips, relative for repo."""
    p = Path(vol["path"])
    if p.is_absolute():
        return p
    return MAESTRO_ROOT / p


def _discover_vaults(vol):
    """Discover vault directories for a volume."""
    vol_path = _vol_path(vol)
    if not vol_path.exists():
        return []

    if vol["type"] == "local":
        # Local volume IS a vault
        return [vol_path]
    else:
        # Chip contains vault-* subdirectories
        return sorted([d for d in vol_path.iterdir()
                      if d.is_dir() and d.name.startswith("vault-")])


def _mcp_entries_for_volume(vol):
    """Generate .mcp.json entries for an activated volume."""
    entries = {}
    vaults = _discover_vaults(vol)

    for vault_path in vaults:
        server_py = vault_path / "app" / "mcp" / "server.py"
        if not server_py.exists():
            continue

        try:
            rel_path = str(server_py.relative_to(MAESTRO_ROOT))
        except ValueError:
            # Physical chip -- use absolute path
            rel_path = str(server_py)

        if vol["type"] == "local":
            name = "vault-%s" % vol["name"]
        else:
            name = "vault-%s" % vault_path.name.replace("vault-", "")

        entry = {
            "type": "stdio",
            "command": "python3",
            "args": [rel_path],
        }

        # Build env
        env = {}
        if vol.get("env"):
            env.update(vol["env"])
        else:
            vault_name = vault_path.name.replace("vault-", "")
            env["VAULT_NAME"] = vault_name

        if env:
            entry["env"] = env

        entries[name] = entry

    return entries


def regen_mcp_json():
    """Regenerate .mcp.json from static entries + active volumes."""
    registry = load_registry()
    active = set(load_active())

    mcp = {"mcpServers": dict(STATIC_MCP)}

    for vol in registry:
        if vol["name"] in active:
            mcp["mcpServers"].update(_mcp_entries_for_volume(vol))

    with open(MCP_JSON, "w") as f:
        json.dump(mcp, f, indent=2)
        f.write("\n")


def cmd_list():
    """List all volumes with status."""
    registry = load_registry()
    active = set(load_active())

    for vol in registry:
        is_active = vol["name"] in active
        marker = "+" if is_active else " "
        vol_path = _vol_path(vol)
        exists = vol_path.exists()

        vaults = _discover_vaults(vol) if exists else []

        if vol["type"] == "local" and exists:
            entries, images, size = _vault_info(vol_path)
            detail = "%d entries, %s" % (entries, size)
        elif vol["type"] == "chip" and vaults:
            detail = "%d vaults" % len(vaults)
        elif not exists:
            detail = "not found"
        else:
            detail = "empty"

        vol_type = "sd" if vol.get("physical") else vol["type"]
        print("  [%s] %-14s %-6s %s" % (marker, vol["name"], vol_type, detail))


def cmd_up(name):
    """Activate a volume."""
    registry = load_registry()
    vol = next((v for v in registry if v["name"] == name), None)
    if not vol:
        print("Unknown volume: %s" % name, file=sys.stderr)
        return 1

    vol_path = _vol_path(vol)
    if not vol_path.exists():
        print("Volume path not found: %s" % vol_path, file=sys.stderr)
        return 1

    active = load_active()
    if name in active:
        print("Already active: %s" % name)
        return 0

    active.append(name)
    save_active(active)

    vaults = _discover_vaults(vol)
    vault_names = [v.name for v in vaults]
    label = vol.get("label", name)
    print("Activated: %s (%s)" % (label, ", ".join(vault_names) if vault_names else "no vaults"))
    if vol.get("physical"):
        print("  Physical chip at %s" % vol_path)
    print("  Jeff routes dynamically -- no restart needed.")
    return 0


def cmd_down(name):
    """Deactivate a volume."""
    active = load_active()
    if name not in active:
        print("Not active: %s" % name)
        return 0

    active.remove(name)
    save_active(active)

    print("Deactivated: %s" % name)
    print("  Jeff routes dynamically -- no restart needed.")
    return 0


def cmd_active():
    """Print active volume names, one per line."""
    for name in load_active():
        print(name)


def cmd_init():
    """Initialize: activate auto_activate volumes if no active file exists."""
    if ACTIVE_FILE.exists():
        return 0
    registry = load_registry()
    auto = [v["name"] for v in registry if v.get("auto_activate", False)]
    save_active(auto)
    regen_mcp_json()
    if auto:
        print("Auto-activated: %s" % ", ".join(auto))
    return 0


def main():
    if len(sys.argv) < 2:
        cmd_list()
        return 0

    command = sys.argv[1]

    if command == "list":
        cmd_list()
    elif command == "up":
        if len(sys.argv) < 3:
            print("Usage: vol.py up <name>", file=sys.stderr)
            return 1
        return cmd_up(sys.argv[2])
    elif command == "down":
        if len(sys.argv) < 3:
            print("Usage: vol.py down <name>", file=sys.stderr)
            return 1
        return cmd_down(sys.argv[2])
    elif command == "active":
        cmd_active()
    elif command == "regen":
        regen_mcp_json()
        print("Regenerated .mcp.json")
    elif command == "init":
        return cmd_init()
    else:
        print("Unknown command: %s" % command, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
