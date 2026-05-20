#!/usr/bin/env python3
"""
jeff vault -- nested vault operations.

A vault is a named, addressable directory inside an active mount. Vaults can
contain vaults. Each vault has a .vault.json manifest at its root.

Slug grammar: [a-z0-9-]+ per segment, '/' as separator.
  cube                -> <mount>/vault-cube/
  cube/drafts         -> <mount>/vault-cube/drafts/
  cube/drafts/2026-05 -> <mount>/vault-cube/drafts/2026-05/

The top-level segment translates to the legacy `vault-<name>/` directory so
the heartbeat manifest scanner in `jeff` cmd_unmount keeps finding root vaults.
Nested vaults are plain directory names underneath.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

JEFF_DIR = Path(__file__).resolve().parent
STATE_FILE = JEFF_DIR / ".jeff-state.json"
MANIFEST_NAME = ".vault.json"
SLUG_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_DEPTH = 4


class VaultError(Exception):
    pass


def _read_state() -> dict:
    if not STATE_FILE.is_file():
        raise VaultError("no chip active -- run 'jeff up' first")
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as e:
        raise VaultError("could not read jeff state: %s" % e)


def _mount_root() -> Path:
    state = _read_state()
    vault_mount = state.get("vault_mount") or ""
    if not vault_mount:
        raise VaultError("no vault mounted -- run 'jeff mount' first")
    p = Path(vault_mount)
    if not p.is_dir():
        raise VaultError("vault_mount does not exist: %s" % vault_mount)
    return p


def _mode() -> str:
    return _read_state().get("mode") or ""


def _validate_slug(slug: str) -> list[str]:
    if not slug:
        raise VaultError("slug is empty")
    if slug.startswith("/") or slug.endswith("/"):
        raise VaultError("slug must not start or end with '/'")
    segments = slug.split("/")
    if len(segments) > MAX_DEPTH:
        raise VaultError(
            "slug depth %d exceeds max %d (%s)" % (len(segments), MAX_DEPTH, slug)
        )
    for seg in segments:
        if not SLUG_SEGMENT_RE.match(seg):
            raise VaultError(
                "invalid slug segment %r -- use lowercase a-z, 0-9, hyphen" % seg
            )
    return segments


def _slug_to_path(slug: str) -> Path:
    segments = _validate_slug(slug)
    root = _mount_root()
    parts = ["vault-%s" % segments[0]] + segments[1:]
    return root.joinpath(*parts)


def _parent_slug(slug: str) -> str | None:
    segments = slug.split("/")
    if len(segments) <= 1:
        return None
    return "/".join(segments[:-1])


def _is_vault(p: Path) -> bool:
    return p.is_dir() and (p / MANIFEST_NAME).is_file()


def _read_manifest(p: Path) -> dict:
    try:
        return json.loads((p / MANIFEST_NAME).read_text())
    except Exception:
        return {}


def _walk_tree(start: Path, slug_prefix: str) -> list[dict]:
    """Return a flat list of {slug, name, parent, path} for vaults under start."""
    out = []
    if not start.is_dir():
        return out
    for entry in sorted(start.iterdir()):
        if not entry.is_dir():
            continue
        # Skip hidden + non-vault directories at root level; at nested levels
        # only descend into directories that ARE vaults.
        name = entry.name
        if slug_prefix == "":
            # Root level: legacy vault-<name> prefix
            if not name.startswith("vault-"):
                continue
            child_slug = name[len("vault-"):]
        else:
            if name.startswith(".") or name == "__pycache__":
                continue
            child_slug = name
        if not SLUG_SEGMENT_RE.match(child_slug):
            continue
        full_slug = ("%s/%s" % (slug_prefix, child_slug)) if slug_prefix else child_slug
        if _is_vault(entry):
            manifest = _read_manifest(entry)
            out.append(
                {
                    "slug": full_slug,
                    "name": manifest.get("name") or child_slug,
                    "parent": manifest.get("parent"),
                    "path": str(entry),
                    "created": manifest.get("created"),
                }
            )
            out.extend(_walk_tree(entry, full_slug))
        elif slug_prefix == "":
            # Legacy: a vault-<name>/ directory without .vault.json. Surface it
            # as a vault anyway so existing data is reachable. Created-on-demand.
            out.append(
                {
                    "slug": full_slug,
                    "name": child_slug,
                    "parent": None,
                    "path": str(entry),
                    "created": None,
                    "legacy": True,
                }
            )
            out.extend(_walk_tree(entry, full_slug))
    return out


# ----------------------------------------------------------------------
# Public operations
# ----------------------------------------------------------------------


def op_list(as_json: bool = False) -> int:
    try:
        root = _mount_root()
    except VaultError as e:
        if as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print("  %s" % e, file=sys.stderr)
        return 1

    items = _walk_tree(root, "")
    if as_json:
        print(json.dumps(items))
        return 0

    if not items:
        print("")
        print("  No vaults found at %s" % root)
        print("")
        print("  Create one with: jeff vault create <slug>")
        print("")
        return 0

    # Group by depth so we render a tree
    print("")
    print("  Vaults at %s" % root)
    print("")
    for item in items:
        depth = item["slug"].count("/")
        indent = "  " + ("  " * depth)
        marker = "+" if item.get("legacy") else "*"
        tag = " (legacy)" if item.get("legacy") else ""
        print("%s%s %s%s" % (indent, marker, item["slug"], tag))
    print("")
    return 0


def op_path(slug: str) -> int:
    try:
        p = _slug_to_path(slug)
    except VaultError as e:
        print("  %s" % e, file=sys.stderr)
        return 2
    if not p.is_dir():
        print("  no such vault: %s (expected at %s)" % (slug, p), file=sys.stderr)
        return 1
    # Accept either manifest-marked vaults OR legacy vault-<name> directories
    # at root level. Nested directories MUST have a manifest.
    if not _is_vault(p):
        if "/" in slug:
            print(
                "  %s is a directory but not a registered vault (missing %s)"
                % (slug, MANIFEST_NAME),
                file=sys.stderr,
            )
            return 1
        # Root-level legacy directory -- allow.
    print(str(p))
    return 0


def op_check(slug: str, verbose: bool = False) -> int:
    try:
        p = _slug_to_path(slug)
    except VaultError as e:
        if verbose:
            print("  %s" % e, file=sys.stderr)
        return 2
    if not p.is_dir():
        if verbose:
            print("  no such vault: %s" % slug, file=sys.stderr)
        return 1
    if not _is_vault(p) and "/" in slug:
        if verbose:
            print("  not a registered vault: %s" % slug, file=sys.stderr)
        return 1
    if verbose:
        print("  ok: %s -> %s" % (slug, p))
    return 0


def op_create(slug: str, name: str | None = None) -> int:
    if _mode() != "read-write":
        print(
            "  vault must be mounted read-write to create -- run 'jeff flip'",
            file=sys.stderr,
        )
        return 1

    try:
        segments = _validate_slug(slug)
        target = _slug_to_path(slug)
    except VaultError as e:
        print("  %s" % e, file=sys.stderr)
        return 2

    parent_slug = _parent_slug(slug)
    if parent_slug is not None:
        try:
            parent_path = _slug_to_path(parent_slug)
        except VaultError as e:
            print("  parent invalid: %s" % e, file=sys.stderr)
            return 2
        if not parent_path.is_dir():
            print(
                "  parent vault does not exist: %s" % parent_slug,
                file=sys.stderr,
            )
            return 1
        if not _is_vault(parent_path) and "/" in parent_slug:
            print(
                "  parent is not a registered vault: %s" % parent_slug,
                file=sys.stderr,
            )
            return 1

    if target.exists():
        if _is_vault(target):
            print("  already a vault: %s" % slug, file=sys.stderr)
            return 1
        # Existing legacy directory at root -- upgrade in place by writing manifest.

    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "slug": slug,
        "name": name or segments[-1],
        "parent": parent_slug,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    print(str(target))
    return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _usage() -> str:
    return (
        "Usage: jeff vault <subcommand>\n"
        "  list [--json]              tree of vaults under active mount\n"
        "  path <slug>                absolute path, exits 1 if not a vault\n"
        "  create <slug> [--name N]   create vault (nested slugs ok)\n"
        "  check <slug> [--verbose]   validate slug, exits 0 if ok\n"
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(_usage())
        return 0
    sub = argv[0]
    rest = argv[1:]

    if sub == "list":
        as_json = "--json" in rest
        return op_list(as_json=as_json)

    if sub == "path":
        if not rest:
            print("  usage: jeff vault path <slug>", file=sys.stderr)
            return 2
        return op_path(rest[0])

    if sub == "check":
        if not rest:
            print("  usage: jeff vault check <slug> [--verbose]", file=sys.stderr)
            return 2
        verbose = "--verbose" in rest or "-v" in rest
        slug = next((a for a in rest if not a.startswith("-")), "")
        if not slug:
            print("  usage: jeff vault check <slug> [--verbose]", file=sys.stderr)
            return 2
        return op_check(slug, verbose=verbose)

    if sub == "create":
        slug = ""
        name = None
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--name":
                name = rest[i + 1] if i + 1 < len(rest) else None
                i += 2
                continue
            if not a.startswith("-") and not slug:
                slug = a
            i += 1
        if not slug:
            print(
                "  usage: jeff vault create <slug> [--name NAME]",
                file=sys.stderr,
            )
            return 2
        return op_create(slug, name=name)

    print("  unknown vault subcommand: %s" % sub, file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except VaultError as e:
        print("  %s" % e, file=sys.stderr)
        sys.exit(1)
