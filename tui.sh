#!/usr/bin/env bash
# ============================================================
#  JEFF TUI -- Sourced by host TUI (e.g. maestro.sh)
# ============================================================
#  Requires in caller scope:
#    JEFF_CLI         -- path to jeff CLI
#    tui_menu         -- menu renderer (sets TUI_INDEX)
#    tui_input        -- text input (sets TUI_RESULT)
#    tui_confirm      -- yes/no confirmation
#
#  Optional hooks (defined by caller):
#    jeff_hook_on_activate    -- called after successful activate
#    jeff_hook_on_deactivate  -- called before deactivate
# ============================================================

_JEFF_TUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# PUBLIC: Main TUI loop
# ============================================================

jeff_tui_loop() {
    while true; do
        # Re-read state on EVERY iteration (fixes stale menu bug)
        local _jt_state _jt_mode _jt_label
        _jt_state=$("${JEFF_CLI}" state)
        _jt_mode=$(echo "${_jt_state}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('mode',''))" 2>/dev/null || echo "")
        _jt_label=$(echo "${_jt_state}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('label',''))" 2>/dev/null || echo "")

        # Build menu for current state
        local _jt_title
        local _jt_items=()
        local _jt_handlers=()
        _jeff_tui_build_menu "${_jt_mode}" "${_jt_label}"

        local _jt_count=${#_jt_items[@]}
        _jt_items+=("Back")

        tui_menu "${_jt_title}" "${_jt_items[@]}" || true

        if [[ "${TUI_INDEX}" -ge "${_jt_count}" ]] || [[ "${TUI_INDEX}" -eq -1 ]]; then
            return 0
        fi

        tput clear 2>/dev/null
        ${_jt_handlers[${TUI_INDEX}]} || true

        echo ""
        echo "  Press any key to return to menu..."
        read -rsn1
        tput clear 2>/dev/null
    done
}

# ============================================================
# MENU BUILDER
# ============================================================

_jeff_tui_build_menu() {
    local mode="$1"
    local label="$2"

    _jt_items=()
    _jt_handlers=()

    case "${mode}" in
        activated)
            _jt_title="Jeff (${label}) [ACTIVE]"
            _jt_items+=("Status")       ; _jt_handlers+=("_jeff_tui_status")
            _jt_items+=("Toolchains")   ; _jt_handlers+=("_jeff_tui_toolchains")
            _jt_items+=("Scan")         ; _jt_handlers+=("_jeff_tui_scan")
            _jt_items+=("Resolve Hex")  ; _jt_handlers+=("_jeff_tui_resolve")
            _jt_items+=("Midpoint")     ; _jt_handlers+=("_jeff_tui_midpoint")
            _jt_items+=("Mount Vault")  ; _jt_handlers+=("_jeff_tui_mount")
            _jt_items+=("Backups")      ; _jt_handlers+=("_jeff_tui_backups")
            _jt_items+=("Deactivate")   ; _jt_handlers+=("_jeff_tui_deactivate")
            ;;
        read-write)
            _jt_title="Jeff (${label}) [READ-WRITE]"
            _jt_items+=("Status")              ; _jt_handlers+=("_jeff_tui_status")
            _jt_items+=("Toolchains")          ; _jt_handlers+=("_jeff_tui_toolchains")
            _jt_items+=("Vaults")              ; _jt_handlers+=("_jeff_tui_vaults")
            _jt_items+=("Resolve Hex")         ; _jt_handlers+=("_jeff_tui_resolve")
            _jt_items+=("Midpoint")            ; _jt_handlers+=("_jeff_tui_midpoint")
            _jt_items+=("Run CueSheet")        ; _jt_handlers+=("_jeff_tui_run_sheet")
            _jt_items+=("Backups")             ; _jt_handlers+=("_jeff_tui_backups")
            _jt_items+=("Flip to Read-Only")   ; _jt_handlers+=("_jeff_tui_flip")
            _jt_items+=("Unmount")             ; _jt_handlers+=("_jeff_tui_unmount")
            ;;
        read-only)
            _jt_title="Jeff (${label}) [READ-ONLY]"
            _jt_items+=("Status")              ; _jt_handlers+=("_jeff_tui_status")
            _jt_items+=("Toolchains")          ; _jt_handlers+=("_jeff_tui_toolchains")
            _jt_items+=("Vaults")              ; _jt_handlers+=("_jeff_tui_vaults")
            _jt_items+=("Resolve Hex")         ; _jt_handlers+=("_jeff_tui_resolve")
            _jt_items+=("Midpoint")            ; _jt_handlers+=("_jeff_tui_midpoint")
            _jt_items+=("Backups")             ; _jt_handlers+=("_jeff_tui_backups")
            _jt_items+=("Flip to Read-Write")  ; _jt_handlers+=("_jeff_tui_flip")
            _jt_items+=("Unmount")             ; _jt_handlers+=("_jeff_tui_unmount")
            ;;
        *)
            _jt_title="Jeff"
            _jt_items+=("Scan")                 ; _jt_handlers+=("_jeff_tui_scan")
            _jt_items+=("Toolchains")           ; _jt_handlers+=("_jeff_tui_toolchains")
            _jt_items+=("Activate")             ; _jt_handlers+=("_jeff_tui_activate")
            _jt_items+=("Create Local Volume")  ; _jt_handlers+=("_jeff_tui_create_volume")
            _jt_items+=("Flash")                ; _jt_handlers+=("_jeff_tui_flash")
            _jt_items+=("Init")                 ; _jt_handlers+=("_jeff_tui_init")
            _jt_items+=("Status")               ; _jt_handlers+=("_jeff_tui_status")
            _jt_items+=("Backups")              ; _jt_handlers+=("_jeff_tui_backups")
            _jt_items+=("Version")              ; _jt_handlers+=("_jeff_tui_version")
            ;;
    esac
}


# ============================================================
# Backups -- surface the host's encrypted-backup status, if present. Jeff is the
# doorway: the host's backup engine drops a non-PII status manifest at the repo
# root (.maestro-backup-status.json); we read and show it. Standalone jeff (no
# host) simply reports "not configured". Never reads PII -- only store location,
# counts, and integrity.
# ============================================================

_jeff_tui_backups() {
    # Find the host's rendezvous manifest. Walk up from our dir (jeff may be at core/jeff of a
    # host, or standalone) -- same idiom status.sh uses to locate the host venv.
    local status_file="${MAESTRO_BACKUP_STATUS:-}"
    if [[ -z "${status_file}" ]]; then
        local _d="${_JEFF_TUI_DIR}"
        for _ in 1 2 3 4; do
            if [[ -f "${_d}/.maestro-backup-status.json" ]]; then
                status_file="${_d}/.maestro-backup-status.json"; break
            fi
            _d=$(dirname "${_d}")
        done
    fi
    echo ""
    if [[ -z "${status_file}" || ! -f "${status_file}" ]]; then
        echo "  Backups: not configured on this host."
        echo "  (the host's backup engine writes .maestro-backup-status.json when active)"
        return 0
    fi
    python3 - "${status_file}" <<'PY'
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except Exception as e:
    print("  Backups: status unreadable (%s)" % e); sys.exit(0)
def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024: return "%.0f%s" % (n, u)
        n /= 1024
    return "%.1fTB" % n
print("  Backup store : %s" % s.get("store", "?"))
print("  Location     : %s" % s.get("provider", "?"))
print("  Tracked      : %d files" % s.get("tracked", 0))
print("  History      : %d snapshots, back to %s  (retain %dd)" % (s.get("snapshots", 0), s.get("oldest") or "-", s.get("retain_days", 30)))
print("  Blobs        : %d  (%s)" % (s.get("blobs", 0), human(s.get("size_bytes", 0))))
print("  Last backup  : %s" % (s.get("last_backup") or "never"))
print("  Key          : %s" % ("present (out of store)" if s.get("key_present") else "MISSING -- cannot restore"))
PY
}


# ============================================================
# HANDLERS: Direct CLI passthrough
# ============================================================

_jeff_tui_scan() {
    "${JEFF_CLI}" scan
}

_jeff_tui_status() {
    "${JEFF_CLI}" status
}

_jeff_tui_toolchains() {
    "${JEFF_CLI}" toolchains
}

_jeff_tui_version() {
    "${JEFF_CLI}" version
}

# ============================================================
# HANDLERS: Chip lifecycle
# ============================================================

_jeff_tui_activate() {
    local chips_json
    chips_json=$("${JEFF_CLI}" scan --json)

    local count
    count=$(echo "${chips_json}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [[ "${count}" == "0" ]]; then
        echo ""
        echo "  No chips detected. Insert an SD card."
        return 1
    fi

    # Parse JSON into arrays
    local paths=()
    local labels_arr=()

    while IFS='|' read -r path display; do
        paths+=("${path}")
        labels_arr+=("${display}")
    done < <(echo "${chips_json}" | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    print('%s|%s (%s, %s)' % (c['path'], c['label'], c['root'], c['band']))
" 2>/dev/null)

    labels_arr+=("Back")
    tui_menu "Activate which chip?" "${labels_arr[@]}"

    if [[ "${TUI_INDEX}" -ge "${#paths[@]}" ]] || [[ "${TUI_INDEX}" -eq -1 ]]; then
        return 1
    fi

    "${JEFF_CLI}" activate "${paths[${TUI_INDEX}]}" || {
        echo "  Activation failed."
        return 1
    }

    # Fire hook if defined
    if type -t jeff_hook_on_activate >/dev/null 2>&1; then
        jeff_hook_on_activate
    fi
}

_jeff_tui_deactivate() {
    # Fire hook before deactivate (so it can read state)
    if type -t jeff_hook_on_deactivate >/dev/null 2>&1; then
        jeff_hook_on_deactivate
    fi

    "${JEFF_CLI}" deactivate
}

_jeff_tui_mount() {
    "${JEFF_CLI}" mount
    # Fire hook to update caller state
    if type -t jeff_hook_on_state_change >/dev/null 2>&1; then
        jeff_hook_on_state_change
    fi
}

_jeff_tui_unmount() {
    "${JEFF_CLI}" unmount
    if type -t jeff_hook_on_state_change >/dev/null 2>&1; then
        jeff_hook_on_state_change
    fi
}

_jeff_tui_flip() {
    "${JEFF_CLI}" flip
    if type -t jeff_hook_on_state_change >/dev/null 2>&1; then
        jeff_hook_on_state_change
    fi
}

# ============================================================
# HANDLERS: Spectral
# ============================================================

_jeff_tui_resolve() {
    echo ""
    tui_input "Hex color (e.g. #FF5500)" || return 1
    local hex="${TUI_RESULT}"
    if [[ -n "${hex}" ]]; then
        "${JEFF_CLI}" resolve "${hex}"
    fi
}

_jeff_tui_midpoint() {
    echo ""
    tui_input "First hex color" || return 1
    local hex_a="${TUI_RESULT}"
    tui_input "Second hex color" || return 1
    local hex_b="${TUI_RESULT}"
    if [[ -n "${hex_a}" ]] && [[ -n "${hex_b}" ]]; then
        "${JEFF_CLI}" midpoint "${hex_a}" "${hex_b}"
    fi
}

# ============================================================
# HANDLERS: Flash / Init
# ============================================================

_jeff_tui_flash() {
    echo ""
    echo "  Scanning for flashable disks..."
    echo ""

    local disks_json
    disks_json=$("${JEFF_CLI}" disks --flashable)

    local count
    count=$(echo "${disks_json}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [[ "${count}" == "0" ]]; then
        echo "  No flashable disks found. Is your SD card inserted?"
        return 1
    fi

    local paths=()
    local labels_arr=()

    while IFS='|' read -r disk display; do
        paths+=("${disk}")
        labels_arr+=("${display}")
    done < <(echo "${disks_json}" | python3 -c "
import json, sys
for d in json.load(sys.stdin):
    tag = ' [CHIP]' if d['has_chip'] else ''
    print('%s|%s (%s)%s' % (d['disk'], d['label'], d['size'], tag))
" 2>/dev/null)

    labels_arr+=("Back")
    tui_menu "Flash which disk?" "${labels_arr[@]}"

    if [[ "${TUI_INDEX}" -ge "${#paths[@]}" ]] || [[ "${TUI_INDEX}" -eq -1 ]]; then
        return 1
    fi

    local selected_disk="${paths[${TUI_INDEX}]}"
    local selected_name
    selected_name=$(echo "${disks_json}" | python3 -c "import json,sys; print(json.load(sys.stdin)[${TUI_INDEX}]['label'])" 2>/dev/null || echo "Chip")

    echo ""
    echo "  Disk:  ${selected_disk}"
    echo ""

    tui_input "Label [${selected_name}]" || return 1
    local label="${TUI_RESULT}"
    if [[ -z "${label}" ]]; then
        label="${selected_name}"
    fi

    echo ""
    echo "  !! This will ERASE ALL DATA on ${selected_disk} !!"
    echo ""
    read -rp "  Type YES to continue: " CONFIRM
    echo ""

    if [[ "${CONFIRM}" != "YES" ]]; then
        echo "  Aborted."
        return 1
    fi

    "${JEFF_CLI}" admin flash "${selected_disk}" --label "${label}" --yes
}

_jeff_tui_init() {
    echo ""
    echo "  Scanning for uninitialized volumes..."
    echo ""

    local vols_json
    vols_json=$("${JEFF_CLI}" disks --uninitialized)

    local count
    count=$(echo "${vols_json}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [[ "${count}" == "0" ]]; then
        echo "  No uninitialized volumes found."
        return 1
    fi

    local paths=()
    local labels_arr=()

    while IFS='|' read -r path display; do
        paths+=("${path}")
        labels_arr+=("${display}")
    done < <(echo "${vols_json}" | python3 -c "
import json, sys
for v in json.load(sys.stdin):
    print('%s|%s' % (v['path'], v['name']))
" 2>/dev/null)

    labels_arr+=("Back")
    tui_menu "Init which volume?" "${labels_arr[@]}"

    if [[ "${TUI_INDEX}" -ge "${#paths[@]}" ]] || [[ "${TUI_INDEX}" -eq -1 ]]; then
        return 1
    fi

    local selected_path="${paths[${TUI_INDEX}]}"
    local selected_name
    selected_name=$(echo "${vols_json}" | python3 -c "import json,sys; print(json.load(sys.stdin)[${TUI_INDEX}]['name'])" 2>/dev/null || echo "Chip")

    tui_input "Label [${selected_name}]" || return 1
    local label="${TUI_RESULT}"
    if [[ -z "${label}" ]]; then
        label="${selected_name}"
    fi

    "${JEFF_CLI}" admin init "${selected_path}" --label "${label}"
}

# ============================================================
# HANDLERS: Local Volume Creation
# ============================================================

_jeff_tui_create_volume() {
    echo ""
    echo "  Create a new local volume in the maestro repo."
    echo "  It will live at vault-<name>/ and be registered in volumes.json."
    echo ""

    tui_input "Volume name (e.g. test_vault)" || return 1
    local vol_name="${TUI_RESULT}"

    if [[ -z "${vol_name}" ]]; then
        echo "  Cancelled."
        return 1
    fi

    echo ""
    "${JEFF_CLI}" vol create "${vol_name}" || return 1

    echo ""
    if tui_confirm "Activate ${vol_name} now?"; then
        "${JEFF_CLI}" vol up "${vol_name}"
    fi
}

# ============================================================
# HANDLERS: Vault CueSheets
# ============================================================

_jeff_tui_run_sheet() {
    local state_json
    state_json=$("${JEFF_CLI}" state)

    local vault_mount
    vault_mount=$(echo "${state_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('vault_mount',''))" 2>/dev/null || echo "")

    if [[ -z "${vault_mount}" ]]; then
        echo "  No vault mounted."
        return 1
    fi

    local sheets_dir="${vault_mount}/data/cuesheets"
    if [[ ! -d "${sheets_dir}" ]]; then
        echo "  No cuesheets directory in vault."
        return 1
    fi

    local files=()
    local labels_arr=()

    while IFS= read -r f; do
        [[ -z "${f}" ]] && continue
        files+=("${f}")
        labels_arr+=("$(basename "${f}" .yaml)")
    done < <(find "${sheets_dir}" -name "*.yaml" -type f 2>/dev/null | sort)

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "  No cuesheets found in vault."
        return 1
    fi

    labels_arr+=("Back")
    tui_menu "Run CueSheet" "${labels_arr[@]}"

    if [[ "${TUI_INDEX}" -ge "${#files[@]}" ]] || [[ "${TUI_INDEX}" -eq -1 ]]; then
        return 1
    fi

    local selected="${files[${TUI_INDEX}]}"
    echo ""
    echo "  Running: $(basename "${selected}")"
    echo ""
    cat "${selected}"
}

# ============================================================
# HANDLERS: Nested Vault Tree
# ============================================================

# Current state mode -- "read-write" or "read-only"
_jeff_tui_vault_mode() {
    "${JEFF_CLI}" state | python3 -c "import json,sys; print(json.load(sys.stdin).get('mode',''))" 2>/dev/null || echo ""
}

# Direct children of a slug prefix.
# Args: prefix ("" for root)
# Stdout: one slug per line
_jeff_tui_vault_children() {
    local prefix="$1"
    "${JEFF_CLI}" vault list --json 2>/dev/null | python3 - "${prefix}" << 'PYEOF'
import json, sys
prefix = sys.argv[1]
data = json.load(sys.stdin)
for v in data:
    slug = v.get("slug", "")
    if prefix == "":
        if "/" not in slug:
            print(slug)
    else:
        rest = slug[len(prefix) + 1:] if slug.startswith(prefix + "/") else ""
        if rest and "/" not in rest:
            print(slug)
PYEOF
}

# Public entry: opens the root vaults menu.
_jeff_tui_vaults() {
    _jeff_tui_vault_menu ""
}

# Recursive menu: lists children of prefix, lets user drill in or create.
# Args: prefix ("" for root, "cube" for cube's children, etc.)
_jeff_tui_vault_menu() {
    local prefix="$1"
    local mode
    mode=$(_jeff_tui_vault_mode)

    while true; do
        local title
        if [[ -z "${prefix}" ]]; then
            title="Vaults"
        else
            title="Vault: ${prefix}"
        fi

        # Collect children
        local children=()
        while IFS= read -r line; do
            [[ -z "${line}" ]] && continue
            children+=("${line}")
        done < <(_jeff_tui_vault_children "${prefix}")

        local labels=()
        local actions=()  # parallel array: "drill:<slug>" or "create" or "show:<slug>"

        local c
        for c in "${children[@]}"; do
            # Strip prefix for display
            local display="${c}"
            if [[ -n "${prefix}" ]]; then
                display="${c#${prefix}/}"
            fi
            labels+=("${display}")
            actions+=("drill:${c}")
        done

        if [[ "${mode}" == "read-write" ]]; then
            labels+=("[Create vault here]")
            actions+=("create")
        fi

        labels+=("Back")

        tui_menu "${title}" "${labels[@]}"

        local idx="${TUI_INDEX}"
        if [[ "${idx}" -ge "${#actions[@]}" ]] || [[ "${idx}" -eq -1 ]]; then
            return 0
        fi

        local action="${actions[${idx}]}"

        case "${action}" in
            drill:*)
                local sub_slug="${action#drill:}"
                _jeff_tui_vault_action "${sub_slug}"
                ;;
            create)
                _jeff_tui_vault_create "${prefix}"
                ;;
        esac
    done
}

# When a vault is selected -- show info, then offer drill / create-child.
_jeff_tui_vault_action() {
    local slug="$1"
    local mode
    mode=$(_jeff_tui_vault_mode)

    local path
    path=$("${JEFF_CLI}" vault path "${slug}" 2>/dev/null || echo "")

    echo ""
    echo "  Vault: ${slug}"
    if [[ -n "${path}" ]]; then
        echo "  Path:  ${path}"
    fi
    echo ""

    local labels=("Enter (show children)")
    local actions=("enter")

    if [[ "${mode}" == "read-write" ]]; then
        labels+=("[Create child here]")
        actions+=("create-child")
    fi
    labels+=("Back")

    tui_menu "${slug}" "${labels[@]}"

    local idx="${TUI_INDEX}"
    if [[ "${idx}" -ge "${#actions[@]}" ]] || [[ "${idx}" -eq -1 ]]; then
        return 0
    fi

    case "${actions[${idx}]}" in
        enter)
            _jeff_tui_vault_menu "${slug}"
            ;;
        create-child)
            _jeff_tui_vault_create "${slug}"
            ;;
    esac
}

# Prompt for a new vault name under the given parent slug ("" = root).
_jeff_tui_vault_create() {
    local parent="$1"

    echo ""
    if [[ -z "${parent}" ]]; then
        echo "  New root vault"
    else
        echo "  New vault under: ${parent}"
    fi
    echo ""

    tui_input "Slug segment (lowercase, hyphens ok)" || return 1
    local segment="${TUI_RESULT}"

    if [[ -z "${segment}" ]]; then
        echo "  Cancelled."
        return 1
    fi

    local full_slug
    if [[ -z "${parent}" ]]; then
        full_slug="${segment}"
    else
        full_slug="${parent}/${segment}"
    fi

    tui_input "Display name (optional, defaults to slug)" || true
    local display_name="${TUI_RESULT}"

    echo ""
    if [[ -n "${display_name}" ]]; then
        "${JEFF_CLI}" vault create "${full_slug}" --name "${display_name}"
    else
        "${JEFF_CLI}" vault create "${full_slug}"
    fi
}
