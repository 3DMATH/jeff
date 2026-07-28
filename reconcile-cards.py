#!/usr/bin/env python3
"""reconcile-cards.py -- runtime disconnect for cards that are no longer present.

Fires from the card-watch launchd agent on every /Volumes change (mount/unmount,
which also covers sleep-unmount and wake-remount) and every 600s as a backstop.

For every card-hosted engine whose SD card is NOT physically mounted right now,
stop its ollama model -- so a pulled or slept card doesn't leave a dead ~17GB pin
holding RAM. Idempotent and safe: stopping a not-loaded model is a no-op, and a
present card is left untouched (its model stays warm).

The STATE layer already reads live presence (model_host.gate returns DISCONNECTED
for a card that isn't mounted), so its engines show disconnected on their own.
This is the RUNTIME half -- it releases the memory.

Manual run: python3 core/jeff/reconcile-cards.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "cue-mem" / "lib"))
import model_host as mh  # noqa: E402  -- the presence + engine catalog

# Resolve ollama absolutely: launchd's PATH may omit /opt/homebrew/bin, so a bare
# "ollama" would silently not-be-found and the release would no-op.
OLLAMA = (shutil.which("ollama")
          or next((p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama")
                   if Path(p).exists()), "ollama"))


def _loaded_ollama_models():
    """Model names ollama currently holds in memory (from `ollama ps`)."""
    try:
        out = subprocess.run([OLLAMA, "ps"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 -- ollama down => nothing loaded to release
        return set()
    names = set()
    for line in out.splitlines()[1:]:  # skip the header row
        parts = line.split()
        if parts:
            names.add(parts[0])
    return names


def main():
    loaded = _loaded_ollama_models()
    keep, candidates, absent = set(), set(), set()
    for e in mh.available():  # ref, name, ollama_id, vault, runnable, reason
        vault = e.get("vault") or ""
        oid = e.get("ollama_id")
        if not vault.startswith("sd:") or not oid:
            continue                        # only removable card engines
        if mh._vault_connected(vault):
            keep.add(oid)                   # a PRESENT card serves this model
        else:
            absent.add(vault)
            candidates.add(oid)             # an absent card wanted this model

    # Release only models that NO present card provides. Two cards can share an
    # ollama_id (touchstone + abits both -> gemma2:27b): if either is plugged in,
    # keep it warm. Only stop a model that is exclusively backed by absent cards.
    stopped = []
    for oid in sorted(candidates - keep):
        if oid in loaded:
            try:
                subprocess.run([OLLAMA, "stop", oid], capture_output=True,
                               text=True, timeout=20)
                stopped.append(oid)
            except Exception:  # noqa: BLE001
                pass
    # HOOK: when the elevated pairing tier lands, a gone card is also the instant
    # hard-kill -- clear any elevated lease here (core/pairing/BROKER_SECURITY.md).
    print("card-reconcile: absent=%s | released=%s"
          % (", ".join(sorted(absent)) or "none", ", ".join(stopped) or "none"))


if __name__ == "__main__":
    main()
