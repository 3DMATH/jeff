"""bridge.py -- the thin seam to the real Jeff.

The TUI never reimplements Jeff; it shells out to the existing `jeff` bash CLI and reads its
output -- exactly the pattern the old tui.sh used (state, scan --json, vault list --json). This
keeps one source of truth: the substrate is the CLI, the TUI is a face on it.

Finding the CLI, in order: JEFF_CLI env, then the `jeff` script at the repo root above this
package, then `jeff` on PATH. Every call is best-effort and never raises -- a missing CLI or a
bad command surfaces as an honest message, not a traceback.
"""
import json as _json
import os
import shutil
import subprocess
from pathlib import Path


class JeffMissing(Exception):
    """Raised (once, caught by the TUI) when no `jeff` CLI can be located."""


def cli_path():
    """Absolute path to the `jeff` bash CLI, or None if it can't be found."""
    env = os.environ.get("JEFF_CLI")
    if env and Path(env).exists():
        return env
    # repo layout: bash `jeff` at the repo root, this package at <root>/src/jefftui/
    here = Path(__file__).resolve()
    root = here.parents[2] if len(here.parents) >= 3 else here.parent
    cand = root / "jeff"
    if cand.exists() and os.access(cand, os.X_OK):
        return str(cand)
    return shutil.which("jeff")


def run(*args, timeout=30):
    """Run `jeff <args...>` and return (returncode, stdout, stderr). rc=127 if no CLI."""
    cli = cli_path()
    if not cli:
        return 127, "", "no `jeff` CLI found (set JEFF_CLI, or put jeff on your PATH)"
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "jeff %s timed out" % " ".join(args)
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def text(*args):
    """stdout of `jeff <args>` (stderr appended if the command failed), trimmed."""
    rc, out, err = run(*args)
    body = out.rstrip()
    if rc != 0 and err.strip():
        body = (body + "\n" + err.rstrip()).strip()
    return body


def jsonout(*args, default=None):
    """Parse the JSON stdout of `jeff <args>`. Returns default on any problem."""
    rc, out, _ = run(*args)
    if rc != 0:
        return default
    try:
        return _json.loads(out)
    except (ValueError, TypeError):
        return default


def available():
    return cli_path() is not None


def version():
    """The substrate's own version line, e.g. 'jeff 0.3.0'."""
    return text("version") or "jeff (version unknown)"


def state():
    """The live state dict: {mode, label, vault_mount, ...}. {} when nothing is active."""
    s = jsonout("state", default={})
    return s if isinstance(s, dict) else {}


def chips():
    """Scanned chips: [{path, label, root, band}]. [] when none / no CLI."""
    c = jsonout("scan", "--json", default=[])
    return c if isinstance(c, list) else []


def vaults():
    """The vault tree: [{slug, ...}]. [] when not mounted or on error."""
    v = jsonout("vault", "list", "--json", default=[])
    return v if isinstance(v, list) else []
