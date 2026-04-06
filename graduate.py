#!/usr/bin/env python3
"""Graduate an entry from one vault to another.

Moves files + DB rows (entries, images, annotations) from source to target.
The entry must exist in the source vault's HOT/ directory.

Usage:
    graduate.py <slug> <source-vault-path> <target-vault-path>

Example:
    graduate.py 032726-1-bmgl-mktg vault-hot chip-red/vault-bmgl
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

MAESTRO_ROOT = Path(__file__).resolve().parent.parent.parent


def graduate(slug, source_path, target_path):
    """Move an entry from source vault to target vault.

    Args:
        slug: Entry slug (directory name in HOT/)
        source_path: Path to source vault (relative to MAESTRO_ROOT)
        target_path: Path to target vault (relative to MAESTRO_ROOT)

    Returns:
        dict with status and details
    """
    source = MAESTRO_ROOT / source_path
    target = MAESTRO_ROOT / target_path

    # Validate
    if not source.exists():
        return {"status": "error", "message": "Source vault not found: %s" % source_path}
    if not target.exists():
        return {"status": "error", "message": "Target vault not found: %s" % target_path}

    source_hot = source / "HOT" / slug
    target_hot = target / "HOT" / slug

    if not source_hot.exists():
        return {"status": "error", "message": "Entry not found in source: HOT/%s" % slug}
    if target_hot.exists():
        return {"status": "error", "message": "Entry already exists in target: HOT/%s" % slug}

    source_db = source / "vault.db"
    target_db = target / "vault.db"

    # Ensure target has schema
    target_schema = target / "schema.sql"
    if target_schema.exists() and not target_db.exists():
        conn = sqlite3.connect(str(target_db))
        conn.executescript(target_schema.read_text())
        conn.commit()
        conn.close()

    # Move files
    shutil.move(str(source_hot), str(target_hot))
    files_moved = sum(1 for _ in target_hot.rglob("*") if _.is_file())

    # Move DB rows
    rows_moved = {"entries": 0, "images": 0, "annotations": 0}

    if source_db.exists():
        src_conn = sqlite3.connect(str(source_db))
        tgt_conn = sqlite3.connect(str(target_db))

        # Ensure target schema
        if target_schema.exists():
            tgt_conn.executescript(target_schema.read_text())
            tgt_conn.commit()

        # vault_entries
        src_rows = src_conn.execute(
            "SELECT slug, title, description FROM vault_entries WHERE slug = ?", (slug,)
        ).fetchall()
        for row in src_rows:
            tgt_conn.execute(
                "INSERT OR IGNORE INTO vault_entries (slug, title, description) VALUES (?, ?, ?)",
                row,
            )
            rows_moved["entries"] += 1

        # vault_images
        src_rows = src_conn.execute(
            "SELECT slug, filename, port FROM vault_images WHERE slug = ?", (slug,)
        ).fetchall()
        for row in src_rows:
            tgt_conn.execute(
                "INSERT OR IGNORE INTO vault_images (slug, filename, port) VALUES (?, ?, ?)",
                row,
            )
            rows_moved["images"] += 1

        # vault_annotations
        src_rows = src_conn.execute(
            "SELECT slug, filename, content, source, pinned, created_at FROM vault_annotations WHERE slug = ?",
            (slug,),
        ).fetchall()
        for row in src_rows:
            tgt_conn.execute(
                "INSERT OR IGNORE INTO vault_annotations (slug, filename, content, source, pinned, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                row,
            )
            rows_moved["annotations"] += 1

        tgt_conn.commit()
        tgt_conn.close()

        # Remove from source DB
        src_conn.execute("DELETE FROM vault_annotations WHERE slug = ?", (slug,))
        src_conn.execute("DELETE FROM vault_images WHERE slug = ?", (slug,))
        src_conn.execute("DELETE FROM vault_entries WHERE slug = ?", (slug,))
        src_conn.commit()
        src_conn.close()

    return {
        "status": "ok",
        "slug": slug,
        "source": source_path,
        "target": target_path,
        "files_moved": files_moved,
        "rows_moved": rows_moved,
    }


def main():
    if len(sys.argv) < 4:
        print("Usage: graduate.py <slug> <source-vault> <target-vault>", file=sys.stderr)
        print("Example: graduate.py 032726-1-bmgl-mktg vault-hot chip-red/vault-bmgl", file=sys.stderr)
        return 1

    slug = sys.argv[1]
    source = sys.argv[2]
    target = sys.argv[3]

    result = graduate(slug, source, target)

    if result["status"] == "error":
        print("Error: %s" % result["message"], file=sys.stderr)
        return 1

    print("Graduated: %s" % slug)
    print("  from: %s" % source)
    print("  to:   %s" % target)
    print("  files: %d" % result["files_moved"])
    print("  rows: %s" % json.dumps(result["rows_moved"]))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
