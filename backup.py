"""Jeff backup system -- content-addressed backup with rotation.

Backs up chip content (HOT/COLD directories) to a nested vault inside
the blob store. Each backup is a manifest of SHA-256 hashes pointing
to deduplicated blobs. Rotation keeps N most recent manifests.

Git tracks schema + MCP + vault.db (metadata).
Jeff backup tracks actual content files (media, documents, etc).

Design:
  - Backup root: {blob_store}/backups/{chip_name}/
  - Each backup: manifest-{timestamp}.json (file list + hashes)
  - Blobs: shared {blob_store}/{ab}/{cd}/{hash} (same as vault blob store)
  - Rotation: keep max_backups manifests, purge orphaned blobs
"""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path


DEFAULT_STORE = "/Users/nickcottrell/Documents/cue-vault-store"
DEFAULT_MAX_BACKUPS = 5


def _store_root():
    return os.environ.get("CUE_VAULT_STORE", DEFAULT_STORE)


def _backup_dir(chip_name):
    d = os.path.join(_store_root(), "backups", chip_name)
    os.makedirs(d, exist_ok=True)
    return d


def _blob_path(file_hash):
    store = _store_root()
    return os.path.join(store, file_hash[:2], file_hash[2:4], file_hash)


def _hash_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _store_blob(filepath, file_hash=None):
    """Copy file to blob store if not already there. Returns blob path."""
    if file_hash is None:
        file_hash = _hash_file(filepath)
    blob = _blob_path(file_hash)
    if os.path.isfile(blob):
        return blob  # already deduplicated
    os.makedirs(os.path.dirname(blob), exist_ok=True)
    shutil.copy2(filepath, blob)
    return blob


def _walk_content(chip_dir):
    """Walk HOT/ and COLD/ in a chip directory, yielding (rel_path, abs_path)."""
    chip = Path(chip_dir)
    for port_name in ("HOT", "COLD"):
        port = chip / port_name
        if not port.is_dir():
            continue
        for root, dirs, files in os.walk(str(port)):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                if filename.startswith("."):
                    continue
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, str(chip))
                yield rel_path, abs_path


def backup(chip_name, chip_dir):
    """Create a backup of chip content.

    Hashes all files in HOT/ and COLD/, stores blobs in the shared
    blob store, writes a manifest to backups/{chip_name}/.

    Args:
        chip_name: Chip identifier (e.g. "yellow", "red", "blue")
        chip_dir: Absolute path to chip staging directory

    Returns:
        Dict with backup statistics
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest_name = "manifest-%s.json" % timestamp
    backup_root = _backup_dir(chip_name)

    files = []
    total_bytes = 0
    new_blobs = 0
    skipped = 0

    for rel_path, abs_path in _walk_content(chip_dir):
        try:
            file_size = os.path.getsize(abs_path)
            # Resolve symlinks to get real file
            real_path = os.path.realpath(abs_path)
            file_hash = _hash_file(real_path)

            # Store blob (deduplicates automatically)
            blob = _blob_path(file_hash)
            if not os.path.isfile(blob):
                _store_blob(real_path, file_hash)
                new_blobs += 1
            else:
                skipped += 1

            files.append({
                "path": rel_path,
                "hash": file_hash,
                "size": file_size,
            })
            total_bytes += file_size
        except (IOError, OSError) as e:
            files.append({
                "path": rel_path,
                "error": str(e),
            })

    manifest = {
        "chip": chip_name,
        "source": str(chip_dir),
        "timestamp": datetime.now().isoformat(),
        "file_count": len([f for f in files if "hash" in f]),
        "total_bytes": total_bytes,
        "new_blobs": new_blobs,
        "deduplicated": skipped,
        "files": files,
    }

    manifest_path = os.path.join(backup_root, manifest_name)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return {
        "manifest": manifest_name,
        "manifest_path": manifest_path,
        "file_count": manifest["file_count"],
        "total_bytes": total_bytes,
        "new_blobs": new_blobs,
        "deduplicated": skipped,
        "message": "Backed up %d files (%d new blobs, %d deduplicated)" % (
            manifest["file_count"], new_blobs, skipped
        ),
    }


def status(chip_name):
    """Get backup status for a chip.

    Returns:
        Dict with backup history and current state
    """
    backup_root = _backup_dir(chip_name)
    manifests = sorted(Path(backup_root).glob("manifest-*.json"), reverse=True)

    history = []
    for manifest_path in manifests:
        try:
            with open(manifest_path) as f:
                m = json.load(f)
            history.append({
                "manifest": manifest_path.name,
                "timestamp": m.get("timestamp", "?"),
                "file_count": m.get("file_count", 0),
                "total_bytes": m.get("total_bytes", 0),
            })
        except (json.JSONDecodeError, IOError):
            continue

    return {
        "chip": chip_name,
        "backup_count": len(history),
        "history": history,
        "backup_dir": backup_root,
    }


def rotate(chip_name, max_backups=None):
    """Rotate backups, keeping only the N most recent manifests.

    Blobs are NOT deleted during rotation (they may be shared across
    chips or referenced by the vault blob store). Only manifests are
    pruned.

    Args:
        chip_name: Chip identifier
        max_backups: Max manifests to keep (default 5)

    Returns:
        Dict with rotation statistics
    """
    if max_backups is None:
        max_backups = DEFAULT_MAX_BACKUPS

    backup_root = _backup_dir(chip_name)
    manifests = sorted(Path(backup_root).glob("manifest-*.json"))

    if len(manifests) <= max_backups:
        return {
            "chip": chip_name,
            "kept": len(manifests),
            "pruned": 0,
            "message": "No rotation needed (%d/%d)" % (len(manifests), max_backups),
        }

    to_prune = manifests[:len(manifests) - max_backups]
    pruned_names = []

    for manifest_path in to_prune:
        try:
            manifest_path.unlink()
            pruned_names.append(manifest_path.name)
        except OSError:
            pass

    return {
        "chip": chip_name,
        "kept": max_backups,
        "pruned": len(pruned_names),
        "pruned_manifests": pruned_names,
        "message": "Rotated: kept %d, pruned %d" % (max_backups, len(pruned_names)),
    }


def restore_list(chip_name, manifest_name=None):
    """List files in a backup manifest (latest if not specified).

    Returns:
        Dict with file list and blob availability
    """
    backup_root = _backup_dir(chip_name)

    if manifest_name:
        manifest_path = os.path.join(backup_root, manifest_name)
    else:
        manifests = sorted(Path(backup_root).glob("manifest-*.json"), reverse=True)
        if not manifests:
            return {"error": "No backups found for %s" % chip_name}
        manifest_path = str(manifests[0])

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return {"error": "Cannot read manifest: %s" % e}

    files = []
    for entry in manifest.get("files", []):
        if "hash" not in entry:
            files.append({"path": entry.get("path"), "available": False, "error": entry.get("error")})
            continue
        blob = _blob_path(entry["hash"])
        files.append({
            "path": entry["path"],
            "hash": entry["hash"],
            "size": entry.get("size", 0),
            "available": os.path.isfile(blob),
        })

    return {
        "chip": chip_name,
        "manifest": os.path.basename(manifest_path),
        "timestamp": manifest.get("timestamp"),
        "files": files,
        "total": len(files),
        "available": sum(1 for f in files if f.get("available")),
    }
