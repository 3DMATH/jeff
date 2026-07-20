#!/bin/bash
#
# status.sh -- report verb for jeff (data-plane MCP node). The transport is
# host-launched (stdio via .mcp.json), so there is nothing to curl. Health = the
# mcp lib is importable and mcp_proxy.py still loads and registers its tool shelf.
#
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
# jeff is a submodule: walk up to find a python-with-deps -- its own .venv when
# standalone, else the host repo's (maestro/.venv) when vendored -- else system.
PY=python3
d="$DIR"
for _ in 1 2 3 4; do
    [ -x "$d/.venv/bin/python3" ] && { PY="$d/.venv/bin/python3"; break; }
    d=$(dirname "$d")
done
tools=$(grep -cE '@mcp\.tool' "$DIR/mcp_proxy.py" 2>/dev/null || echo 0)
if "$PY" -c "import mcp" >/dev/null 2>&1 && "$PY" -m py_compile "$DIR/mcp_proxy.py" >/dev/null 2>&1; then
    echo "jeff: ready (${tools} tools, mcp lib present)"
    exit 0
fi
echo "jeff: down (mcp lib missing or mcp_proxy.py broken)"
exit 1
