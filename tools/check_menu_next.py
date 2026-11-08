#!/usr/bin/env python3
"""2.726.0 (#5164): a menu entry that opens a further menu, choice sheet or picker shows the arrow on the right.

Decision 08.11.2026: "in ALL menus every entry with further options behind it shows the arrow on the right - secured by a
test". menu() (static/js/popovers.js) draws the arrow (.mchev) for {more: [...]} (the second level) and for {next: 1}
(the entry's fn opens a menu / sheet / picker of its own). A dialog with input keeps its "…" in the label and no arrow.

Red: an object literal in static/js/*.js or static/*.js whose `fn:` is an arrow function that directly calls menu(),
*Menu(), *_menu(), *Sheet(), *Picker(), *_picker() or askChoice() (or one of OPENS_TOO below) and that has neither `next:` nor `more:` at its own level.
A call that only looks like one (e.g. a function named …Menu that does not open a menu) carries `next: 0` on purpose.

Runs inside tools/check_layout.py (CI lint, Mac lint) and on its own:

usage: python3 tools/check_menu_next.py       exit code 1 on a hit
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# fn: () => X(  /  fn: e => { X(  /  fn: async () => X(
FN = re.compile(r"\bfn:\s*(?:async\s+)?(?:\([^()]*\)|\w+)\s*=>\s*\{?\s*(?:await\s+)?([A-Za-z_$][\w$]*)\(")
OPENS = re.compile(r"^(?:menu|askChoice|[\w$]*(?:Menu|_menu|Sheet|Picker|_picker|_listPicker))$")
# openers of a choice whose name does not say so (a menu / sheet / colour or date choice behind them)
OPENS_TOO = {"folderPick", "o3c_folderPick", "ml_pick", "ml_multiPick", "spr_pick", "nwl_ctPick", "datePop", "calColorPop"}
# names that look like one but open a dialog with a search field (keeps its "…", no arrow)
DIALOG = {"depPicker"}
OWN = re.compile(r"\b(next|more)\s*:")


def _span(src, at):
    """(start, end) of the object literal around position `at`: the nearest unclosed { before it and its }."""
    d, i = 0, at
    while i >= 0:
        c = src[i]
        if c in "})]":
            d += 1
        elif c in "{([":
            if d == 0:
                if c != "{":
                    return None
                break
            d -= 1
        i -= 1
    if i < 0:
        return None
    d, j = 0, i
    while j < len(src):
        c = src[j]
        if c in "{([":
            d += 1
        elif c in "})]":
            d -= 1
            if d == 0:
                return i, j
        j += 1
    return None


def _own_level(text):
    """The text of an object literal with everything nested blanked out (only its own keys stay)."""
    out, d = [], 0
    for c in text:
        if c in "})]":
            d -= 1
        out.append(c if d <= 1 else " ")
        if c in "{([":
            d += 1
    return "".join(out)


def hits():
    res = []
    for fn in sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js")) + glob.glob(os.path.join(ROOT, "static", "*.js"))):
        src = open(fn, encoding="utf-8").read()
        for m in FN.finditer(src):
            if m.group(1) in DIALOG or not (OPENS.match(m.group(1)) or m.group(1) in OPENS_TOO):
                continue
            sp = _span(src, m.start())
            if not sp or OWN.search(_own_level(src[sp[0]:sp[1] + 1])):
                continue
            n = src.count("\n", 0, m.start()) + 1
            res.append(f"{os.path.relpath(fn, ROOT)}:{n}: menu entry opens {m.group(1)}() without the arrow - add next: 1 (#5164)")
    return res


def errors():
    """For tools/check_layout.py."""
    return hits()


def main():
    h = hits()
    for x in h:
        print("ERROR:", x)
    print(f"check_menu_next: {len(h)} entry(ies) without the arrow")
    return 1 if h else 0


if __name__ == "__main__":
    sys.exit(main())
