#!/usr/bin/env python3
"""Jeff's toolchain registry.

Jeff owns the connection to the toolchains the system maintains: it discovers
them, tracks their status, and exposes them through its panel and APIs. The
reasoning inside a toolchain (e.g. C2D2's triage + shelf) stays with the
toolchain; Jeff is the doorway, not the room.

A toolchain declares itself with a `toolchain.json` manifest under tools/<x>/.
This mirrors how Jeff registers engines from mounted cards (engine_sync /
engine_list): drop a manifest, Jeff surfaces it.

Usage:
    toolchains.py            human-readable registry (for the Jeff panel)
    toolchains.py --json     machine-readable (for Jeff's APIs / surfaces)
"""

import json
import os
import re
import subprocess
import sys

_JEFF_DIR = os.path.dirname(os.path.abspath(__file__))
_MAESTRO_ROOT = os.path.dirname(os.path.dirname(_JEFF_DIR))
_TOOLS_DIR = os.path.join(_MAESTRO_ROOT, "tools")


def _load_manifests():
    """Discover toolchain.json manifests under tools/<x>/."""
    found = []
    if not os.path.isdir(_TOOLS_DIR):
        return found
    for name in sorted(os.listdir(_TOOLS_DIR)):
        path = os.path.join(_TOOLS_DIR, name, "toolchain.json")
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    tc = json.load(f)
                tc["_manifest"] = os.path.relpath(path, _MAESTRO_ROOT)
                found.append(tc)
            except Exception as exc:
                found.append({"name": name, "error": "bad manifest: %s" % exc})
    return found


def _tool_count(tc):
    """Count the tools a toolchain exposes, from its declared tools_manifest."""
    rel = tc.get("tools_manifest")
    if not rel:
        return None
    path = os.path.join(_MAESTRO_ROOT, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return sum(1 for line in f if re.match(r"\s+-\s+name:", line))
    except Exception:
        return None


def _probe_status(tc):
    """Run the toolchain's declared status_probe. rc == 0 means up."""
    probe = tc.get("status_probe")
    if not probe or not probe.get("command"):
        return "unknown"
    cmd = [probe["command"]] + probe.get("args", [])
    try:
        r = subprocess.run(cmd, cwd=_MAESTRO_ROOT, capture_output=True,
                           text=True, timeout=8)
        return "up" if r.returncode == 0 else "down"
    except Exception:
        return "down"


def summary(probe=True):
    """The registry: one dict per registered toolchain, with live status."""
    out = []
    for tc in _load_manifests():
        if tc.get("error"):
            out.append({"name": tc.get("name", "?"), "error": tc["error"]})
            continue
        ep = tc.get("endpoint", {})
        tri = tc.get("triage") or {}
        triage_cmd = ([tri["command"]] + tri.get("args", [])) if tri.get("command") else None
        out.append({
            "name": tc.get("name", "?"),
            "title": tc.get("title", ""),
            "kind": tc.get("kind", ""),
            "tier": tc.get("tier", ""),
            "summary": tc.get("summary", ""),
            "tools": _tool_count(tc),
            "capabilities": tc.get("capabilities", []),
            "triage": bool(tc.get("triage")),
            "triage_cmd": triage_cmd,
            "endpoint": ("%s %s %s" % (
                ep.get("type", "?"), ep.get("command", ""),
                " ".join(ep.get("args", [])))).strip(),
            "status": _probe_status(tc) if probe else "unprobed",
            "manifest": tc.get("_manifest", ""),
        })
    return out


def _print_human(rows):
    if not rows:
        print("No toolchains registered with Jeff.")
        return
    dot = {"up": "●", "down": "○", "unknown": "◌"}
    print("Toolchains registered with Jeff: %d\n" % len(rows))
    for r in rows:
        if r.get("error"):
            print("  ○ %s — %s" % (r["name"], r["error"]))
            continue
        tags = ", ".join(t for t in (r.get("tier"), r.get("kind")) if t)
        print("  %s %s — %s  [%s]" % (
            dot.get(r["status"], "◌"), r["name"], r["title"], tags))
        bits = ["status: %s" % r["status"]]
        if r.get("tools") is not None:
            bits.append("%d tools" % r["tools"])
        bits.append("triage: %s" % ("yes" if r["triage"] else "no"))
        print("    %s" % " · ".join(bits))
        print("    endpoint: %s" % r["endpoint"])
        if r.get("summary"):
            print("    %s" % r["summary"])
        print()


def _print_compact(rows):
    """One line per toolchain -- for the always-visible panel header."""
    if not rows:
        print("  (none registered)")
        return
    dot = {"up": "●", "down": "○", "unknown": "◌", "unprobed": "●"}
    for r in rows:
        if r.get("error"):
            print("  ○ %s — %s" % (r["name"], r["error"]))
            continue
        bits = []
        if r.get("tools") is not None:
            bits.append("%d tools" % r["tools"])
        if r.get("triage"):
            bits.append("triage")
        tier = ("  [%s]" % r["tier"]) if r.get("tier") else ""
        line = "  %s %s" % (dot.get(r["status"], "●"), r["name"])
        if bits:
            line += "  %s" % " · ".join(bits)
        print(line + tier)


def main():
    if "--compact" in sys.argv:
        # No probe: the panel redraws every keypress, keep it instant.
        _print_compact(summary(probe=False))
        return
    rows = summary(probe="--no-probe" not in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
    else:
        _print_human(rows)


if __name__ == "__main__":
    main()
