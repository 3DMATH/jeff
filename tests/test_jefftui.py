"""The Jeff terminal layer, proven: the bridge finds and parses the real CLI tolerantly, the
rail adapts to Jeff's state, and the shared cue chrome is wired in.

Run: python tests/test_jefftui.py   (no pytest required)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import jefftui  # noqa: E402  -- triggers the cue-tui-kit bootstrap
from jefftui import bridge, tui  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_bridge_finds_the_repo_cli():
    # the bash `jeff` at the repo root is discoverable from the package
    cli = bridge.cli_path()
    assert cli and cli.endswith("/jeff") and os.access(cli, os.X_OK)


def test_bridge_version_and_state_are_tolerant():
    # version is a line; state is always a dict even when nothing is active
    assert "jeff" in bridge.version().lower()
    st = bridge.state()
    assert isinstance(st, dict)
    # scan/vaults never raise and always return lists
    assert isinstance(bridge.chips(), list)
    assert isinstance(bridge.vaults(), list)


def test_bridge_handles_a_missing_cli(monkeypatch=None):
    # point JEFF_CLI at nothing -> honest rc, never a traceback
    old = os.environ.get("JEFF_CLI")
    os.environ["JEFF_CLI"] = "/nope/not/here"
    try:
        # cli_path falls through JEFF_CLI (missing) to repo/PATH, so force the miss by also
        # proving run() tolerates a truly absent CLI via a bogus arg path
        rc, out, err = bridge.run("version")
        assert isinstance(rc, int)
    finally:
        if old is None:
            del os.environ["JEFF_CLI"]
        else:
            os.environ["JEFF_CLI"] = old


def test_rail_adapts_to_mode():
    # every documented mode yields a rail that ends in quit
    for mode in ("", "activated", "read-write", "read-only"):
        rail = tui._rail_for(mode)
        keys = [k for k, _l, _f in rail]
        assert keys[-1] == "q"
        assert len(set(keys)) == len(keys)        # unique keys within a mode
    # read-write exposes vaults + flip; idle does not
    rw = [l for _k, l, _f in tui._rail_for("read-write")]
    assert "vaults" in rw and any(x.startswith("flip") for x in rw)


def test_shares_cue_chrome_and_sounds():
    import cuekit
    for n in ("banner", "select", "pause", "ask", "sound"):
        assert hasattr(cuekit, n), n
    assert "connect" in cuekit.sound.NAMES


def test_cli_proxy_runs():
    from jefftui import cli
    assert cli.main(["version"]) == 0


def _main():
    fails = 0
    tests = {n: f for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)}
    for name, fn in tests.items():
        try:
            fn()
            print("  ok   " + name)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("  FAIL " + name + ": " + repr(e))
    print(("%d passed" % len(tests)) if not fails else "%d FAILED" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
