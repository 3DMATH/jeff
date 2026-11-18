"""tui.py -- the Jeff terminal, on cue-tui-kit.

A smaller cousin of the Cue Vault TUI, driving the real Jeff substrate through bridge.py. The
command rail adapts to Jeff's state the same way the old tui.sh did -- idle / activated /
read-write / read-only -- but it's standalone and styled like Cue Vault: cold-steel banner,
the 🪐 lock slot, arrow-step the rail, Enter runs the highlighted one, or press the letter.
"""
import cuekit
from cuekit import (DIM, EDGE, GOLD, INK, MUTE, RED, ask, c, clear, pause,
                    prompt_enter, read_key, sound)

from . import bridge
from .version import BUILD

LOCK = "🪐"
_cursor = 0


def _banner(w=None):
    cuekit.banner("Jeff", "the Vault Array · MCP tooling + storage", lock=LOCK, w=w)


# ---- actions: each drives the real CLI, then shows the result on a cleared screen ----
def _show(title, *cli_args):
    clear(); _banner()
    print("  " + c("▸ " + title, EDGE)); print()
    body = bridge.text(*cli_args)
    for line in (body or "(no output)").splitlines() or ["(no output)"]:
        print("    " + line)
    print()
    prompt_enter()


def _scan():
    _show("scan for chips", "scan")


def _status():
    _show("status", "status")


def _check():
    _show("check", "check")


def _disks():
    _show("disks", "disks")


def _resolve():
    hex_ = ask("hex color (e.g. #FF5500) › ")
    if not hex_:
        return
    _show("resolve " + hex_, "resolve", hex_)


def _midpoint():
    a = ask("first hex › ")
    if not a:
        return
    b = ask("second hex › ")
    if not b:
        return
    _show("midpoint", "midpoint", a, b)


def _activate():
    cs = bridge.chips()
    if not cs:
        pause("no chips detected 🪐  -- insert an SD card.\n     "
              "(no hardware? the cue node can emulate one: `cue chip new`.)", MUTE, header=_banner)
        return
    clear(); _banner()
    opts = [("%s (%s, %s)" % (ch.get("label", "?"), ch.get("root", "?"), ch.get("band", "?")),
             ch.get("path")) for ch in cs]
    opts.append(("cancel", None))
    path = cuekit.select("activate which chip?", opts)
    if not path:
        return
    out = bridge.text("up", path)
    sound.play("connect")
    pause(out or "activated.", GOLD, header=_banner)


def _deactivate():
    out = bridge.text("down")
    sound.play("down")
    pause(out or "deactivated.", MUTE, header=_banner)


def _mount():
    out = bridge.text("mount")
    sound.play("connect")
    pause(out or "mounted.", GOLD, header=_banner)


def _unmount():
    out = bridge.text("unmount")
    sound.play("toggle")
    pause(out or "unmounted.", MUTE, header=_banner)


def _flip():
    out = bridge.text("flip")
    sound.play("toggle")
    pause(out or "flipped.", GOLD, header=_banner)


def _vaults():
    vs = bridge.vaults()
    if not vs:
        pause("no vaults to show -- mount a vault first, or none created yet.", MUTE, header=_banner)
        return
    clear(); _banner()
    print("  " + c("▸ vaults", EDGE)); print()
    for v in vs:
        slug = v.get("slug", "?")
        depth = slug.count("/")
        leaf = slug.split("/")[-1]
        name = v.get("name", "")
        row = "    " + "  " * depth + c(leaf, INK)
        if name and name != leaf:
            row += "  " + c(name, MUTE)
        print(row)
    print()
    prompt_enter()


def _new_vault():
    slug = ask("new vault slug (lowercase, hyphens ok) › ")
    if not slug:
        return
    out = bridge.text("vault", "create", slug)
    sound.play("keep")
    pause(out or ("created vault " + slug), GOLD, header=_banner)


def _new_volume():
    name = ask("new local volume name › ")
    if not name:
        return
    out = bridge.text("vol", "create", name)
    sound.play("keep")
    pause(out or ("created volume " + name), GOLD, header=_banner)


# ---- the mode-adaptive command rail (mirrors tui.sh's build_menu) ----
RAILS = {
    "": [("s", "scan", _scan), ("a", "activate", _activate),
         ("o", "new volume", _new_volume), ("k", "check", _check), ("d", "disks", _disks)],
    "activated": [("s", "status", _status), ("c", "scan", _scan), ("r", "resolve", _resolve),
                  ("m", "midpoint", _midpoint), ("u", "mount", _mount), ("x", "deactivate", _deactivate)],
    "read-write": [("v", "vaults", _vaults), ("r", "resolve", _resolve), ("m", "midpoint", _midpoint),
                   ("n", "new vault", _new_vault), ("f", "flip→RO", _flip), ("u", "unmount", _unmount)],
    "read-only": [("v", "vaults", _vaults), ("r", "resolve", _resolve),
                  ("f", "flip→RW", _flip), ("u", "unmount", _unmount)],
}


def _rail_for(mode):
    rail = list(RAILS.get(mode, RAILS[""]))
    rail.append(("q", "quit", None))
    return rail


def _rail_line(rail):
    parts = []
    for i, (key, label, _fn) in enumerate(rail):
        if i == _cursor:
            parts.append(c(" " + key + " " + label + " ", "7"))
        else:
            parts.append(c(key, EDGE) + " " + c(label, MUTE))
    return "  " + c(" · ", DIM).join(parts)


def render():
    st = bridge.state()
    mode = st.get("mode", "") or ""
    label = st.get("label", "")
    rail = _rail_for(mode)
    clear()
    _banner()
    tag = {"": "no chip active", "activated": "chip active",
           "read-write": "read-write", "read-only": "read-only"}.get(mode, mode)
    print("  %s %s %s" % ("🪐", c("jeff".ljust(8), INK),
                          c(bridge.version() + "  ·  " + tag + (("  ·  " + label) if label else ""),
                            GOLD if mode else MUTE)))
    chips = bridge.chips()
    print("  %s %s %s" % ("🔌", c("chips".ljust(8), INK),
                          c("%d detected" % len(chips) if chips else "none in a slot", MUTE)))
    if mode in ("read-write", "read-only"):
        vs = bridge.vaults()
        print("  %s %s %s" % ("🗄️ ", c("vaults".ljust(8), INK),
                              c("%d in the mounted vault" % len(vs), MUTE)))
    print()
    print(_rail_line(rail))
    print()
    print("  " + c("terminal build " + BUILD, DIM))
    return rail


def run():
    global _cursor
    if not bridge.available():
        clear(); _banner()
        print("  " + c("no `jeff` CLI found.", RED))
        print("  " + c("run this from a Jeff checkout, or set JEFF_CLI to the jeff script.", MUTE))
        print()
        return
    sound.play("ready")
    while True:
        rail = render()
        if _cursor >= len(rail):
            _cursor = 0
        key = read_key()
        if key is None:                      # not a TTY -> line mode (type a letter)
            try:
                line = input("  " + c("›", EDGE) + " ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            act = line[:1]
        elif key in ("UP", "LEFT"):
            _cursor = (_cursor - 1) % len(rail); sound.play("step"); continue
        elif key in ("DOWN", "RIGHT"):
            _cursor = (_cursor + 1) % len(rail); sound.play("step"); continue
        elif key == "ENTER":
            act = rail[_cursor][0]
        elif key == "INT":
            break
        else:
            act = (key or "").lower()
        if act == "q":
            break
        for k, _label, fn in rail:
            if k == act and fn is not None:
                fn()
                break
    clear()
    sound.play("down")
    print("  " + c("jeff out.", DIM) + "\n")
