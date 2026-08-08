#!/bin/bash
# card-watch.sh -- runtime disconnect for pulled/slept SD cards.
#
# Launched by com.maestro.card-watch on every /Volumes change (mount/unmount,
# incl. sleep-unmount and wake-remount) and every 600s as a backstop. Releases
# the ollama RAM held by any card-hosted model whose card is no longer present.
# The state layer (model_host.gate) already reads live presence; this is the
# runtime half. See core/jeff/reconcile-cards.py.
set -u
# Resolve the maestro root from this script's location (core/jeff/ -> ../..), so the
# reference repo carries no machine-specific path. MAESTRO_ROOT overrides if set.
cd "${MAESTRO_ROOT:-$(dirname "$0")/../..}" || exit 0
python3 core/jeff/reconcile-cards.py 2>&1
