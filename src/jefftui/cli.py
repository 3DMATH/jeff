"""cli.py -- the jefftui entry.

Opens the Jeff terminal. A few read-only words (status/state/version/scan) are proxied straight
to the real CLI so `jeff-tui status` works even without a TTY; anything else opens the TUI.
"""
import sys

_PROXY = {"status", "state", "version", "scan", "disks", "check"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _PROXY:
        from . import bridge
        print(bridge.text(*argv))
        return 0
    from . import tui
    tui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
