"""jefftui -- the Jeff terminal.

The new version of Jeff's TUI: a first-class, standalone, pip-installable terminal over the
existing Jeff Vault Array -- a smaller cousin of Claude Code and Cue Vault, on the very same
chrome and sounds (cue-tui-kit). It does NOT reimplement Jeff; it drives the existing `jeff`
bash CLI (the real substrate: chips, vaults, volumes, spectral, the MCP proxy), the same way
the old sourced tui.sh did -- but standalone, and styled like Cue Vault.

Built on cue-tui-kit. In a dev checkout where the kit isn't installed, fall back to a sibling
../cuekit/src so `jeff tui` runs straight from source.
"""
from .version import BUILD, __version__

try:  # the kit supplies the shared chrome + sounds
    import cuekit  # noqa: F401
except ModuleNotFoundError:  # dev fallback: a sibling cue-tui-kit checkout
    import os
    import sys
    _sib = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "cuekit", "src"))
    if os.path.isdir(_sib):
        sys.path.insert(0, _sib)

__all__ = ["__version__", "BUILD"]
