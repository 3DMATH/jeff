#!/bin/bash
#
# run.sh -- test verb: isolated syntax validation (py_compile) of this node's
# top-level Python. No proxy started, no chip mounted, no live mcp required.
# Degenerate tier -- sharpens to behavioural tests later.
#
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DIR=$(cd "$(dirname "$0")" && pwd)
NODE=$(dirname "$DIR")
# jeff is a submodule: walk up to find a python-with-deps -- its own .venv when
# standalone, else the host repo's (maestro/.venv) when vendored -- else system.
PY=python3
d="$NODE"
for _ in 1 2 3 4; do
    [ -x "$d/.venv/bin/python3" ] && { PY="$d/.venv/bin/python3"; break; }
    d=$(dirname "$d")
done
cd "$NODE"
n=0
for f in *.py; do
    [ -e "$f" ] || continue
    "$PY" -m py_compile "$f" || { echo "FAIL  $f does not compile"; exit 1; }
    n=$((n+1))
done
echo "ok  ${n} python file(s) compile"
echo ""
echo "1 passed"
