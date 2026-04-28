"""Jeff backup system -- zip-based chip backup with FIFO rotation.

Two backup tiers:
  1. Local volume: ~/Documents/jeff-backups (iCloud-synced), capped, FIFO
  2. Backup volume: physical flash drive with format "backup-volume" heartbeat

Backup config lives on the chip's heartbeat.json under the "backup" key.
The spec (CHIP_SPEC_v1.0) says unknown fields MUST be preserved, so this
is forward-compatible without a protocol bump.

Backup flow:
  1. Read chip heartbeat for backup config (include/exclude/scope)
  2. Walk the unencrypted chip surface per include/exclude globs
  3. Create a timestamped zip
  4. Write zip to local volume and/or backup volume
  5. FIFO rotate: oldest zips deleted when cap exceeded
"""

import fnmatch
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_LOCAL_PATH = os.path.expanduser("~/Documents/jeff-backups")
DEFAULT_CAP_MB = 10240  # 10 GB
DEFAULT_RETENTION = 5
DEFAULT_INCLUDE = ["vault-*", "datasets", "*.sql", "vault.db.split", ".jeff"]
DEFAULT_EXCLUDE = ["models", "vault.sparseimage", ".fseventsd", ".Spotlight-V100", ".DS_Store", "*.zip"]


# ============================================================
# HEARTBEAT HELPERS
# ============================================================

def _read_heartbeat(chip_path):
    """Read heartbeat.json from a chip or volume path."""
    hb_path = os.path.join(chip_path, "heartbeat.json")
    if not os.path.isfile(hb_path):
        return None
    try:
        with open(hb_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _backup_config(heartbeat):
    """Extract backup config from heartbeat, with defaults."""
    cfg = heartbeat.get("backup", {}) if heartbeat else {}
    local = cfg.get("local", {})
    return {
        "local_path": local.get("path", DEFAULT_LOCAL_PATH),
        "cap_mb": local.get("cap_mb", DEFAULT_CAP_MB),
        "retention": local.get("retention", DEFAULT_RETENTION),
        "scope": cfg.get("scope", "chip"),
        "include": cfg.get("include", DEFAULT_INCLUDE),
        "exclude": cfg.get("exclude", DEFAULT_EXCLUDE),
    }


# ============================================================
# BACKUP VOLUME DETECTION
# ============================================================

def discover_backup_volumes():
    """Scan /Volumes/ for flash drives with backup-volume heartbeats."""
    volumes = []
    volumes_dir = "/Volumes"
    if not os.path.isdir(volumes_dir):
        return volumes

    for name in sorted(os.listdir(volumes_dir)):
        if name == "Macintosh HD":
            continue
        vol_path = os.path.join(volumes_dir, name)
        hb = _read_heartbeat(vol_path)
        if hb and hb.get("format") == "backup-volume":
            volumes.append({
                "path": vol_path,
                "label": hb.get("label", name),
                "device_id": hb.get("device_id", ""),
                "capacity_gb": hb.get("capacity_gb", 0),
                "accepts_from": hb.get("accepts_from", []),
            })

    return volumes


def _find_backup_volume_for(chip_label):
    """Find a mounted backup volume that accepts this chip."""
    for vol in discover_backup_volumes():
        accepts = vol.get("accepts_from", [])
        if not accepts or chip_label.upper() in [a.upper() for a in accepts]:
            return vol
    return None


# ============================================================
# FILE WALKING
# ============================================================

def _matches_any(name, patterns):
    """Check if name matches any glob pattern in the list."""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _walk_surface(chip_path, include, exclude):
    """Walk chip surface per include/exclude, yielding (rel_path, abs_path).

    Include/exclude operate on top-level names. If a top-level entry matches
    include and does not match exclude, all its contents are included.
    """
    try:
        entries = sorted(os.listdir(chip_path))
    except OSError:
        return

    for entry in entries:
        if entry.startswith(".") and entry != ".jeff":
            continue
        if _matches_any(entry, exclude):
            continue
        if not _matches_any(entry, include):
            continue

        abs_path = os.path.join(chip_path, entry)

        if os.path.isfile(abs_path):
            if not _matches_any(entry, exclude):
                yield entry, abs_path
        elif os.path.isdir(abs_path):
            for root, dirs, files in os.walk(abs_path):
                # Skip hidden dirs and tmp
                dirs[:] = [d for d in dirs if not d.startswith(".")
                           and d != "tmp"]
                for filename in files:
                    if filename.startswith("."):
                        continue
                    if _matches_any(filename, exclude):
                        continue
                    full = os.path.join(root, filename)
                    rel = os.path.relpath(full, chip_path)
                    yield rel, full


# ============================================================
# ZIP CREATION
# ============================================================

def _create_zip(chip_path, chip_label, include, exclude):
    """Create a timestamped zip of chip surface content.

    Returns (zip_path, file_count, total_bytes) or raises on failure.
    The zip is created in a temp location first, then returned.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_name = "%s-%s.zip" % (chip_label.lower(), timestamp)
    tmp_dir = os.path.join(chip_path, ".jeff", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    zip_path = os.path.join(tmp_dir, zip_name)

    file_count = 0
    total_bytes = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, abs_path in _walk_surface(chip_path, include, exclude):
            try:
                zf.write(abs_path, rel_path)
                total_bytes += os.path.getsize(abs_path)
                file_count += 1
            except OSError:
                continue

    return zip_path, zip_name, file_count, total_bytes


# ============================================================
# FIFO ROTATION
# ============================================================

def _fifo_rotate(backup_dir, chip_label, retention, cap_mb):
    """Delete oldest backups to stay within retention count and cap.

    Returns list of deleted filenames.
    """
    pattern = "%s-*.zip" % chip_label.lower()
    zips = sorted(Path(backup_dir).glob(pattern))

    deleted = []

    # Retention count: keep only N newest
    if len(zips) > retention:
        to_prune = zips[:len(zips) - retention]
        for z in to_prune:
            try:
                z.unlink()
                deleted.append(z.name)
            except OSError:
                pass
        zips = sorted(Path(backup_dir).glob(pattern))

    # Cap: delete oldest until under cap
    if cap_mb > 0:
        cap_bytes = cap_mb * 1024 * 1024
        total = sum(z.stat().st_size for z in zips if z.is_file())
        while total > cap_bytes and zips:
            oldest = zips.pop(0)
            try:
                total -= oldest.stat().st_size
                oldest.unlink()
                deleted.append(oldest.name)
            except OSError:
                pass

    return deleted


# ============================================================
# PUBLIC API
# ============================================================

def backup(chip_name, chip_path):
    """Create a zip backup of a chip's unencrypted surface.

    Reads backup config from heartbeat.json. Writes zip to:
      1. Local backup volume (always, if configured)
      2. Physical backup volume (if mounted and accepts this chip)

    Args:
        chip_name: Chip label (e.g. "blue", "yellow")
        chip_path: Absolute path to chip (staging dir or /Volumes/LABEL)

    Returns:
        Dict with backup results
    """
    hb = _read_heartbeat(chip_path)
    cfg = _backup_config(hb)
    chip_label = chip_name.upper()

    # Create the zip
    try:
        zip_path, zip_name, file_count, total_bytes = _create_zip(
            chip_path, chip_label, cfg["include"], cfg["exclude"])
    except Exception as exc:
        return {"error": "Zip creation failed: %s" % exc}

    zip_size = os.path.getsize(zip_path)
    results = {
        "chip": chip_label,
        "zip": zip_name,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "zip_size_mb": round(zip_size / (1024 * 1024), 1),
        "targets": [],
    }

    # Tier 1: Local backup volume
    local_path = os.path.expanduser(cfg["local_path"])
    os.makedirs(local_path, exist_ok=True)
    local_dest = os.path.join(local_path, zip_name)
    try:
        shutil.copy2(zip_path, local_dest)
        deleted = _fifo_rotate(local_path, chip_label,
                               cfg["retention"], cfg["cap_mb"])
        results["targets"].append({
            "type": "local",
            "path": local_dest,
            "rotated": deleted,
        })
    except OSError as exc:
        results["targets"].append({
            "type": "local",
            "error": "Copy failed: %s" % exc,
        })

    # Tier 2: Physical backup volume (if available)
    bv = _find_backup_volume_for(chip_label)
    if bv:
        bv_dir = os.path.join(bv["path"], "backups")
        os.makedirs(bv_dir, exist_ok=True)
        bv_dest = os.path.join(bv_dir, zip_name)
        try:
            shutil.copy2(zip_path, bv_dest)
            # Backup volumes use retention from chip config, no cap
            deleted = _fifo_rotate(bv_dir, chip_label, cfg["retention"], 0)
            results["targets"].append({
                "type": "backup-volume",
                "label": bv["label"],
                "path": bv_dest,
                "rotated": deleted,
            })
        except OSError as exc:
            results["targets"].append({
                "type": "backup-volume",
                "label": bv["label"],
                "error": "Copy failed: %s" % exc,
            })

    # Clean up temp zip
    try:
        os.unlink(zip_path)
    except OSError:
        pass

    results["message"] = "Backed up %d files (%.1f MB zip) to %d targets" % (
        file_count, zip_size / (1024 * 1024), len([t for t in results["targets"] if "error" not in t]))

    return results


def status(chip_name):
    """Get backup status across all tiers.

    Returns:
        Dict with backup history per tier
    """
    chip_label = chip_name.upper()
    pattern = "%s-*.zip" % chip_label.lower()
    result = {"chip": chip_label, "tiers": []}

    # Local tier
    local_path = os.path.expanduser(DEFAULT_LOCAL_PATH)
    if os.path.isdir(local_path):
        zips = sorted(Path(local_path).glob(pattern), reverse=True)
        history = []
        total_mb = 0
        for z in zips:
            try:
                size_mb = z.stat().st_size / (1024 * 1024)
                total_mb += size_mb
                history.append({
                    "name": z.name,
                    "size_mb": round(size_mb, 1),
                    "modified": datetime.fromtimestamp(z.stat().st_mtime).isoformat(),
                })
            except OSError:
                continue
        result["tiers"].append({
            "type": "local",
            "path": local_path,
            "backup_count": len(history),
            "total_mb": round(total_mb, 1),
            "history": history,
        })

    # Backup volume tiers
    for bv in discover_backup_volumes():
        accepts = bv.get("accepts_from", [])
        if accepts and chip_label not in [a.upper() for a in accepts]:
            continue
        bv_dir = os.path.join(bv["path"], "backups")
        if not os.path.isdir(bv_dir):
            result["tiers"].append({
                "type": "backup-volume",
                "label": bv["label"],
                "backup_count": 0,
                "history": [],
            })
            continue

        zips = sorted(Path(bv_dir).glob(pattern), reverse=True)
        history = []
        for z in zips:
            try:
                size_mb = z.stat().st_size / (1024 * 1024)
                history.append({
                    "name": z.name,
                    "size_mb": round(size_mb, 1),
                    "modified": datetime.fromtimestamp(z.stat().st_mtime).isoformat(),
                })
            except OSError:
                continue
        result["tiers"].append({
            "type": "backup-volume",
            "label": bv["label"],
            "backup_count": len(history),
            "history": history,
        })

    return result


def rotate(chip_name, max_backups=None):
    """Manually trigger FIFO rotation on local tier.

    Args:
        chip_name: Chip label
        max_backups: Override retention count

    Returns:
        Dict with rotation results
    """
    chip_label = chip_name.upper()
    retention = max_backups or DEFAULT_RETENTION

    local_path = os.path.expanduser(DEFAULT_LOCAL_PATH)
    if not os.path.isdir(local_path):
        return {"chip": chip_label, "kept": 0, "pruned": 0, "message": "No local backup dir"}

    deleted = _fifo_rotate(local_path, chip_label, retention, DEFAULT_CAP_MB)
    pattern = "%s-*.zip" % chip_label.lower()
    remaining = len(list(Path(local_path).glob(pattern)))

    return {
        "chip": chip_label,
        "kept": remaining,
        "pruned": len(deleted),
        "pruned_files": deleted,
        "message": "Rotated: kept %d, pruned %d" % (remaining, len(deleted)),
    }


def restore_list(chip_name, manifest_name=None):
    """List contents of a backup zip.

    Args:
        chip_name: Chip label
        manifest_name: Specific zip filename (default: latest from local tier)

    Returns:
        Dict with file list from the zip
    """
    chip_label = chip_name.upper()
    pattern = "%s-*.zip" % chip_label.lower()

    # Find the zip
    if manifest_name:
        # Check local first, then backup volumes
        local_path = os.path.expanduser(DEFAULT_LOCAL_PATH)
        zip_path = os.path.join(local_path, manifest_name)
        if not os.path.isfile(zip_path):
            for bv in discover_backup_volumes():
                candidate = os.path.join(bv["path"], "backups", manifest_name)
                if os.path.isfile(candidate):
                    zip_path = candidate
                    break
        if not os.path.isfile(zip_path):
            return {"error": "Backup not found: %s" % manifest_name}
    else:
        local_path = os.path.expanduser(DEFAULT_LOCAL_PATH)
        zips = sorted(Path(local_path).glob(pattern), reverse=True) if os.path.isdir(local_path) else []
        if not zips:
            return {"error": "No backups found for %s" % chip_label}
        zip_path = str(zips[0])

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            files = []
            for info in zf.infolist():
                files.append({
                    "path": info.filename,
                    "size": info.file_size,
                    "compressed": info.compress_size,
                })
        return {
            "chip": chip_label,
            "backup": os.path.basename(zip_path),
            "file_count": len(files),
            "files": files,
        }
    except (zipfile.BadZipFile, OSError) as exc:
        return {"error": "Cannot read backup: %s" % exc}
