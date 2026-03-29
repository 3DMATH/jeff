#!/usr/bin/env bash
# ============================================================
#  JEFF -- Initialize a chip on a volume
# ============================================================
#  Usage: ./init.sh /Volumes/MYCARD [--label MYCARD] [--size 4g]
#
#  Card surface (unencrypted, always readable):
#    heartbeat.json          Identity + tool chain + pulse config
#    mcp/                    MCP server code (runs from the card)
#    spectral-binding.md     The Spectral Binding paper
#    Modelfile               Ollama model config
#
#  Vault (encrypted, passphrase required):
#    data/credentials/       API keys, certs
#    data/state/             Runtime state
#    data/cuesheets/         User CueSheets
#    data/logs/              Audit trail
#    data/.kept/             Keeper identity
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JEFF_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VOLUME_PATH="${1:?Usage: ./init.sh /Volumes/MYCARD [--label MYCARD] [--size 4g]}"
shift

LABEL=""
VAULT_SIZE="4g"
MODEL_NAME="qwen2.5:7b-instruct-q4_K_M"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --label)  LABEL="$2"; shift 2 ;;
        --size)   VAULT_SIZE="$2"; shift 2 ;;
        --model)  MODEL_NAME="$2"; shift 2 ;;
        *)        echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "${LABEL}" ]]; then
    LABEL=$(basename "${VOLUME_PATH}")
fi

# ============================================================
# VALIDATION
# ============================================================

if [[ ! -d "${VOLUME_PATH}" ]]; then
    echo "ERROR: ${VOLUME_PATH} is not a directory"
    exit 1
fi

if [[ -f "${VOLUME_PATH}/heartbeat.json" ]]; then
    echo "ERROR: ${VOLUME_PATH} already has heartbeat.json -- already initialized?"
    exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
    echo "ERROR: hdiutil not found. Requires macOS."
    exit 1
fi

# Auto-reformat FAT32 to ExFAT
FS_TYPE=$(diskutil info "${VOLUME_PATH}" 2>/dev/null | grep "File System Personality" | sed 's/.*: *//')
if echo "${FS_TYPE}" | grep -qi "fat32\|msdos\|ms-dos"; then
    echo "  Reformatting FAT32 to ExFAT..."
    DISK_ID=$(diskutil info "${VOLUME_PATH}" 2>/dev/null | grep "Part of Whole" | awk '{print $NF}')
    diskutil eraseDisk ExFAT "${LABEL}" GPT "/dev/${DISK_ID}"
    VOLUME_PATH="/Volumes/${LABEL}"
    if [[ ! -d "${VOLUME_PATH}" ]]; then
        echo "ERROR: Volume did not remount at ${VOLUME_PATH}"
        exit 1
    fi
fi

echo ""
echo "  Jeff Init"
echo "  ========="
echo "  Volume:  ${VOLUME_PATH}"
echo "  Label:   ${LABEL}"
echo "  Vault:   ${VAULT_SIZE}"
echo ""

# ============================================================
# STEP 1: Generate identity
# ============================================================

DEVICE_ID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
CREATED_AT=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
VAULT_VOLUME_NAME=$(echo "${LABEL}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"-vault"

echo "  [1/5] Device: ${DEVICE_ID:0:8}"

# ============================================================
# STEP 2: Copy MCP server to card surface
# ============================================================

echo "  [2/5] Copying MCP server to card..."

mkdir -p "${VOLUME_PATH}/mcp"
cp "${JEFF_DIR}/chip/mcp_server.py" "${VOLUME_PATH}/mcp/server.py"
cp "${JEFF_DIR}/spectral/spectral.py" "${VOLUME_PATH}/mcp/spectral.py"
cp "${JEFF_DIR}/spectral/tool_chain.py" "${VOLUME_PATH}/mcp/tool_chain.py"
cp "${JEFF_DIR}/chip/inference.py" "${VOLUME_PATH}/mcp/inference.py"

# Copy the paper
if [[ -f "${JEFF_DIR}/spectral/spectral-binding.md" ]]; then
    cp "${JEFF_DIR}/spectral/spectral-binding.md" "${VOLUME_PATH}/spectral-binding.md"
fi

# Write Modelfile
cat > "${VOLUME_PATH}/Modelfile" << MEOF
FROM ${MODEL_NAME}
SYSTEM You are Jeff, running on a Booster Chip. You understand Spectral Binding. Answer concisely.
MEOF

echo "        mcp/server.py"
echo "        mcp/spectral.py"
echo "        mcp/tool_chain.py"
echo "        mcp/inference.py"
echo "        spectral-binding.md"
echo "        Modelfile"

# ============================================================
# STEP 3: Write heartbeat.json
# ============================================================

echo "  [3/5] Writing heartbeat.json..."

python3 - "${VOLUME_PATH}/heartbeat.json" "${DEVICE_ID}" "${LABEL}" "${CREATED_AT}" "${MODEL_NAME}" "${JEFF_DIR}/spectral" << 'PYEOF'
import json, sys, hashlib, os

path, device_id, label, created_at, model, spectral_dir = sys.argv[1:7]

# Compute tool chain
sys.path.insert(0, spectral_dir)
tool_chain = {"root": "#000000", "leaves": {}, "tree": [], "depth": 0}
try:
    from tool_chain import compute_chain
    tools = [
        "chip_status", "chip_read_card",
        "chip_resolve_hex", "chip_resolve_deep", "chip_midpoint",
        "chip_split_band", "chip_distance", "chip_tool_chain",
        "chip_constellation", "chip_registry",
        "chip_query",
    ]
    tool_chain = compute_chain(tools)
except Exception:
    pass

chip = {
    "format": "booster-chip",
    "protocol": 1,
    "device_id": device_id,
    "label": label,
    "chip_type": "vanilla",
    "created_at": created_at,
    "mount_count": 0,
    "vault_image": "vault.sparseimage",
    "vault_volume_name": label.replace(" ", "-").lower() + "-vault",
    "model": model,
    "heartbeat": {
        "interval_seconds": 300,
        "emit": [
            {
                "token_type": "chip_keepalive",
                "label": "%s keepalive" % label,
                "tags": ["chip", "keepalive", label.lower()],
                "base_temp": 100,
                "cooling_rate": 1200.0
            }
        ]
    },
    "tool_chain": tool_chain,
    "identity_hash": ""
}

canonical = json.dumps(chip, sort_keys=True, ensure_ascii=False)
chip["identity_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

with open(path, "w") as f:
    json.dump(chip, f, indent=2)

print("        Root: %s" % tool_chain.get("root", "?"))
PYEOF

# ============================================================
# STEP 4: Create encrypted vault
# ============================================================

echo "  [4/5] Creating encrypted vault..."
echo ""
echo "        Set a passphrase for the vault."
echo "        You need this to access credentials and state."
echo ""

read -rsp "        Passphrase: " VAULT_PASS
echo ""
read -rsp "        Confirm:    " VAULT_PASS2
echo ""

if [[ "${VAULT_PASS}" != "${VAULT_PASS2}" ]]; then
    echo "ERROR: Passphrases do not match."
    exit 1
fi

if [[ -z "${VAULT_PASS}" ]]; then
    echo "ERROR: Passphrase cannot be empty."
    exit 1
fi

TMP_VAULT="/tmp/jeff-vault-$(date +%s)"

echo "${VAULT_PASS}" | hdiutil create \
    -encryption AES-256 \
    -size "${VAULT_SIZE}" \
    -type SPARSE \
    -fs APFS \
    -volname "${VAULT_VOLUME_NAME}" \
    -stdinpass \
    "${TMP_VAULT}"

mv "${TMP_VAULT}.sparseimage" "${VOLUME_PATH}/vault.sparseimage"

# Mount vault to populate template
echo "${VAULT_PASS}" | hdiutil attach "${VOLUME_PATH}/vault.sparseimage" -stdinpass -quiet 2>/dev/null || {
    echo "${VAULT_PASS}" | hdiutil attach "${VOLUME_PATH}/vault.sparseimage" -stdinpass
}

VAULT_MOUNT="/Volumes/${VAULT_VOLUME_NAME}"

if [[ ! -d "${VAULT_MOUNT}" ]]; then
    echo "ERROR: Vault did not mount at ${VAULT_MOUNT}"
    exit 1
fi

# Populate vault with data template
mkdir -p "${VAULT_MOUNT}/data/credentials"
mkdir -p "${VAULT_MOUNT}/data/state"
mkdir -p "${VAULT_MOUNT}/data/cuesheets"
mkdir -p "${VAULT_MOUNT}/data/logs"
mkdir -p "${VAULT_MOUNT}/data/.kept/trust"

# Copy template files
for tpl in device.json manifest.json protocol.json; do
    if [[ -f "${JEFF_DIR}/chip/template/data/.kept/${tpl}" ]]; then
        cp "${JEFF_DIR}/chip/template/data/.kept/${tpl}" "${VAULT_MOUNT}/data/.kept/${tpl}"
    fi
done

# Stamp identity
python3 - "${VAULT_MOUNT}/data/.kept" "${DEVICE_ID}" "${LABEL}" "${CREATED_AT}" << 'PYEOF'
import json, sys, os
kept_dir, device_id, label, created_at = sys.argv[1:5]
for fname in ["device.json", "manifest.json"]:
    path = os.path.join(kept_dir, fname)
    if os.path.isfile(path):
        with open(path) as f:
            doc = json.load(f)
        doc["device_id"] = device_id
        if "label" in doc:
            doc["label"] = label
        doc["created_at"] = created_at
        with open(path, "w") as f:
            json.dump(doc, f, indent=2)
PYEOF

# Init git inside vault
(cd "${VAULT_MOUNT}" && git init -q && git add -A && git commit -q -m "Initial chip state")

hdiutil detach "${VAULT_MOUNT}" -quiet

echo "        Vault created and sealed"

# ============================================================
# STEP 5: Verify
# ============================================================

echo "  [5/5] Verifying..."

FILE_COUNT=$(find "${VOLUME_PATH}" -not -name ".*" -type f | wc -l | tr -d ' ')

echo ""
echo "  ============================="
echo "  Chip ready: ${LABEL}"
echo "  ============================="
echo "  Device:   ${DEVICE_ID:0:8}"
echo "  Files:    ${FILE_COUNT} on card surface"
echo "  Vault:    vault.sparseimage (AES-256)"
echo "  Path:     ${VOLUME_PATH}"
echo ""
echo "  Card layout:"
echo "    heartbeat.json        identity"
echo "    mcp/server.py         MCP server (runs from card)"
echo "    spectral-binding.md   the paper"
echo "    Modelfile             model config"
echo "    vault.sparseimage     encrypted vault"
echo ""
echo "  Next: jeff activate ${VOLUME_PATH}"
echo ""
