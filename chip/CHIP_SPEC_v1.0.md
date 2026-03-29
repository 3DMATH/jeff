# Booster Chip Protocol Specification v1.0

**Status:** FROZEN
**Date:** 2026-03-28
**Protocol version:** 1

This document defines the Booster Chip format. It is the contract between
init, mount, unmount, update, and any tool that interacts with a chip.
Changes to this spec require a protocol version bump.

---

## 1. Identity File (heartbeat.json)

Lives at the root of the chip volume. **Unencrypted.** This is the only
file readable without mounting the vault.

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `format` | string | Must be `"booster-chip"`. Magic number. |
| `protocol` | integer | Protocol version. Must be `1`. |
| `device_id` | string | UUID v4. Immutable after creation. |
| `label` | string | Human-readable name. Mutable. |
| `chip_type` | string | Chip variant (e.g. `"vanilla"`). |
| `created_at` | string | ISO 8601 UTC timestamp. Immutable. |
| `mount_count` | integer | Incremented on every mount. Starts at 0. |
| `vault_image` | string | Filename of encrypted container. Must be `"vault.sparseimage"`. |
| `vault_volume_name` | string | macOS volume name for the mounted vault. |
| `model` | string | Ollama model identifier. Empty string if no model. |
| `heartbeat` | object | Heartbeat pulse configuration. See Heartbeat section. |
| `identity_hash` | string | SHA-256 of this file with `identity_hash` set to empty string. |

### Heartbeat Configuration

The `heartbeat` object defines what the chip emits while mounted.

| Field | Type | Description |
|-------|------|-------------|
| `heartbeat.interval_seconds` | integer | Seconds between emissions. |
| `heartbeat.emit` | array | Token definitions to emit each interval. |

Each entry in `heartbeat.emit`:

| Field | Type | Description |
|-------|------|-------------|
| `token_type` | string | Token type for cue-mem (e.g. `"chip_health"`). |
| `label` | string | Human-readable token label. |
| `tags` | array | String tags for filtering. |
| `temperature` | integer | Initial temperature (0-100). |
| `cooling_rate` | float | Degrees per hour decay rate. |

While mounted, a background process reads this config and calls `createtoken`
every `interval_seconds`. On unmount, the process dies. Tokens cool naturally.

### Immutable Fields

These fields MUST NOT change after creation:
- `format`
- `protocol`
- `device_id`
- `created_at`

### Identity Hash Computation

```
1. Read heartbeat.json as UTF-8 string
2. Parse as JSON
3. Set identity_hash to ""
4. Serialize as canonical JSON (sorted keys, no trailing whitespace)
5. SHA-256 hash the serialized bytes
6. Store hex digest as identity_hash
```

### Example

```json
{
  "format": "booster-chip",
  "protocol": 1,
  "device_id": "25cf43f7-39b8-4a04-a3c7-eff9631bc0a2",
  "label": "YELLOW",
  "chip_type": "vanilla",
  "created_at": "2026-03-28T15:14:13.785558+00:00",
  "mount_count": 3,
  "vault_image": "vault.sparseimage",
  "vault_volume_name": "yellow-vault",
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "heartbeat": {
    "interval_seconds": 60,
    "emit": [
      {
        "token_type": "chip_health",
        "label": "YELLOW alive",
        "tags": ["chip", "health", "yellow"],
        "temperature": 80,
        "cooling_rate": 5.0
      }
    ]
  },
  "identity_hash": "a1b2c3d4..."
}
```

---

## 2. Volume Layout

### Root (unencrypted, always readable)

```
/path/to/chip/
├── heartbeat.json                    REQUIRED  Identity file
├── vault.sparseimage           REQUIRED  AES-256 encrypted APFS container
└── models/                      OPTIONAL  Model weight files (unencrypted)
    └── *.gguf
```

### Vault (encrypted, only readable when mounted)

```
/Volumes/{vault_volume_name}/
├── firmware/                    REQUIRED  Read-only during operation (chmod 444)
│   ├── version.json             REQUIRED  Firmware version + checksum
│   ├── chip.yaml                REQUIRED  Chip manifest (tools, model config)
│   ├── mcp/                     REQUIRED  MCP server code
│   │   ├── server.py            REQUIRED  FastMCP server entrypoint
│   │   └── inference.py         REQUIRED  Ollama inference client
│   └── cuesheets/               REQUIRED  Base CueSheets (firmware-provided)
│       └── *.yaml
│
└── data/                        REQUIRED  Writable during read-write mode
    ├── .kept/                   REQUIRED  Keeper identity
    │   ├── device.json          REQUIRED  Device identity (mirrors heartbeat.json fields)
    │   ├── manifest.json        REQUIRED  File manifest
    │   ├── protocol.json        REQUIRED  Protocol declaration
    │   └── trust/               OPTIONAL  Cryptographic trust chain
    │       ├── device.key                  Ed25519 private key (chmod 600)
    │       ├── device.pub                  Ed25519 public key
    │       └── chain.json                  Manifest signature chain
    ├── cuesheets/               REQUIRED  User-added CueSheets
    ├── credentials/             REQUIRED  API keys, certs, tokens
    ├── state/                   REQUIRED  Runtime state files
    └── logs/                    REQUIRED  Audit trail
```

### Directory Rules

- All `REQUIRED` directories must exist for a chip to be valid.
- Empty directories are valid.
- `firmware/` is chmod 444 during operation. Only writable during update.
- `data/` is writable only in read-write mode. Read-only mode rejects all writes.

---

## 3. Firmware Versioning (version.json)

Lives at `firmware/version.json` inside the vault.

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Semantic version (e.g. `"1.0.0"`). |
| `checksum` | string | SHA-256 of all firmware files (excluding version.json). |
| `source_repo` | string | GitHub repo identifier. |
| `updated_at` | string | ISO 8601 UTC timestamp of last update. |
| `history` | array | Last 10 previous versions (version + checksum + replaced_at). |

### Checksum Computation

```
1. Walk firmware/ directory recursively
2. Sort files by path
3. Skip version.json
4. Read each file as bytes
5. Feed all bytes into a single SHA-256 hasher (in sorted order)
6. Store hex digest as checksum
```

---

## 4. State Machine

```
                    ┌──────────┐
           init/    │          │
           flash    │  SEALED  │   heartbeat.json readable
                    │          │   vault encrypted
                    └────┬─────┘
                         │ mount (passphrase)
                         ▼
                    ┌──────────┐
                    │          │
                    │ READ-ONLY│   MCP running
                    │          │   all reads work
                    └──┬───┬───┘   all writes refused
                  flip │   │ unmount
                       ▼   │
                    ┌──────────┐
                    │          │
                    │READ-WRITE│   MCP running
                    │          │   reads + writes work
                    └──┬───┬───┘   update/snapshot available
                  flip │   │ unmount
                       ▼   │
                    ┌──────────┐
                    │          │
                    │  SEALED  │◄──┘
                    │          │
                    └──────────┘
```

### State Transitions

| From | Action | To | Requires |
|------|--------|----|----------|
| — | init / flash | SEALED | Physical volume |
| SEALED | mount | READ-ONLY | Passphrase |
| SEALED | mount --read-write | READ-WRITE | Passphrase |
| READ-ONLY | flip | READ-WRITE | Confirmation |
| READ-WRITE | flip | READ-ONLY | — |
| READ-ONLY | unmount | SEALED | — |
| READ-WRITE | unmount | SEALED | — |
| READ-WRITE | update | READ-WRITE | Confirmation |
| READ-WRITE | snapshot | READ-WRITE | — |

### Forbidden Transitions

- SEALED → READ-WRITE without passphrase
- READ-ONLY → update (must flip first)
- READ-ONLY → snapshot (must flip first)
- Any state → modify firmware/ during operation (chmod enforced)

---

## 5. Mount Validation

Before starting the MCP server, mount.sh MUST verify:

### Step 1: Identity Check

```
1. Read heartbeat.json
2. Verify format == "booster-chip"
3. Verify protocol == 1
4. Recompute identity_hash, compare to stored value
5. FAIL if mismatch: "Identity tampered"
```

### Step 2: Vault Structure Check

After decrypting the vault, verify all REQUIRED paths exist:

```
firmware/version.json
firmware/chip.yaml
firmware/mcp/server.py
firmware/mcp/inference.py
firmware/cuesheets/
data/.kept/device.json
data/.kept/manifest.json
data/.kept/protocol.json
data/cuesheets/
data/credentials/
data/state/
data/logs/
```

FAIL if any are missing: "Incomplete chip: missing {path}"

### Step 3: Firmware Integrity Check

```
1. Read firmware/version.json
2. Recompute checksum of all firmware files
3. Compare to stored checksum
4. FAIL if mismatch: "Firmware tampered -- run chip update to repair"
```

### Step 4: Proceed

Only after all three checks pass:
- Increment mount_count in heartbeat.json
- Recompute identity_hash
- Start MCP server

---

## 6. Security Invariants

These are always true. No exceptions.

1. **Vault is AES-256 encrypted.** No unencrypted vault is a valid chip.
2. **Firmware is read-only during operation.** chmod 444, enforced.
3. **MCP server never runs while firmware is writable.** Mutually exclusive.
4. **Writes require explicit read-write mode.** Default is read-only.
5. **Credentials never leave the encrypted vault.** No copies, no symlinks.
6. **Identity hash detects tampering of heartbeat.json.** Verified on every mount.
7. **Firmware checksum detects tampering of MCP code.** Verified on every mount.
8. **Mount count is monotonic.** Never decremented. Never reset.
9. **device_id is immutable.** Set once during init, never changed.
10. **Unmount kills MCP and seals vault.** No lingering processes or open handles.

---

## 7. Compatibility

### Forward Compatibility

- Tools MUST check `protocol` field before operating on a chip.
- Tools MUST refuse to operate on chips with `protocol > 1`.
- Unknown fields in heartbeat.json MUST be preserved (not stripped).

### Backward Compatibility

- Protocol 1 is the first version. No backward compatibility needed.
- Future protocol versions MUST document migration from protocol 1.

---

## 8. Anti-Patterns

These are explicitly forbidden by this protocol:

- **No auto-mount.** Every mount is a deliberate user action.
- **No network access by default.** Chips are air-gapped unless explicitly configured.
- **No ambient credentials.** No env vars, no keychains, no SSH agents. Credentials live on the chip.
- **No firmware edits in place.** Update replaces firmware atomically from the repo.
- **No partial mounts.** Either all validation passes and MCP starts, or nothing starts.
- **No silent failures.** Every validation failure produces a clear error message.

---

**This spec is frozen.** Changes require protocol version 2.
