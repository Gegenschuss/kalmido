#!/usr/bin/env python3
"""2.653.0 (#5087): finger operation hangs on isTouchUi(), never on the screen width.

isMobile() (static/js/icons.js) answers "is the screen narrow" and is for LAYOUT only. Whether a finger operates the app
(gestures, autofocus that pops up the on-screen keyboard, inputmode, native HTML5 drag, keyboard shortcut hints, motion of
the phone sheets) is isTouchUi() = (pointer:coarse) or (hover:none). A touch tablet or an unfolded foldable is wider than
767 px: there isMobile() is false and every finger rule hung on it is missing (audit #3357, 07.11.2026).

Red: a line of static/js/*.js or static/*.js that tests the width (isMobile() or matchMedia('(max-/min-width ...)')) and
in the same line does something for fingers or keyboards (FINGER below), unless
  * the same line asks isTouch() / isTouchUi() as well (the touch side is decided there), or
  * the line carries a comment with "layout:" and the reason (it really is about space, e.g. "layout: the detail covers
    the list on a phone").
The hits from before this rule stand in tools/touch_switch_legacy.txt (file, hash of the line text - robust against
moved lines -, task number). Each is fixed by its own task (#5080-#5086, or marked "layout:"); a listed hit that is gone
only warns: delete its line. The list only shrinks.

Runs inside tools/check_layout.py (CI lint, Mac lint) and on its own:

usage: python3 tools/check_touch_switch.py          exit code 1 on a new hit (a stale list line only warns)
       python3 tools/check_touch_switch.py -v       also list the known hits
       python3 tools/check_touch_switch.py --list   print today's hits in the list format (to fill in by hand)
"""
import glob
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "tools", "touch_switch_legacy.txt")
WIDTH = re.compile(r"\bisMobile\(\)|matchMedia\(\s*['\"`]\(\s*(?:max|min)-width")
FINGER = re.compile(
    r"\.focus\(|\.select\??\.?\(|\bdraggable\b|\btouch(?:start|move|end|cancel)\b|\.touches\b|\bpointer(?:down|move|up)\b"
    r"|\bkb\(|\bkbText\(|\bkeys\s*:|\ban_on\b|\binputmode\b|\bnavtouch\b")
TOUCH_OK = re.compile(r"\bisTouch(?:Ui)?\(\)")
LAYOUT_NOTE = re.compile(r"(?://|/\*).*\blayout:")


def line_key(text):
    """Hash of the line text with the white space folded: stays when lines above move, changes when the line is edited."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:12]


def is_hit(text):
    """True when the line decides finger / keyboard operation by the width (the rule above)."""
    s = text.strip()
    if not s or s.startswith(("//", "*", "/*")):
        return False
    if not WIDTH.search(s) or not FINGER.search(s):
        return False
    return not TOUCH_OK.search(s) and not LAYOUT_NOTE.search(s)


def files(root=ROOT):
    return sorted(glob.glob(os.path.join(root, "static", "js", "*.js")) + glob.glob(os.path.join(root, "static", "*.js")))


def hits(root=ROOT):
    """[(relative file, line number, key, text)] of all hits."""
    out = []
    for p in files(root):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        with open(p, encoding="utf-8") as f:
            for n, ln in enumerate(f, 1):
                if is_hit(ln):
                    out.append((rel, n, line_key(ln), ln.strip()))
    return out


def legacy(path=LEGACY):
    """[(file, key, task)] from the list; a key may stand more than once (the same line text twice in one file)."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            parts = [] if ln.lstrip().startswith("#") else ln.split()
            if len(parts) >= 3:
                out.append((parts[0], parts[1], parts[2]))
    return out


def check(root=ROOT, path=LEGACY):
    """(errors, warnings, known hits)."""
    left = {}
    for fn, key, task in legacy(path):
        left.setdefault((fn, key), []).append(task)
    errs, known = [], []
    for fn, n, key, text in hits(root):
        tasks = left.get((fn, key))
        if tasks:
            known.append(f"{fn}:{n} ({tasks.pop(0)})")
            continue
        errs.append(f"ERROR: {fn}:{n}: finger operation decided by the width (isMobile() / max-width) - use isTouchUi() "
                    f"for fingers, isMobile() only for layout; or mark a real layout case with a comment 'layout: <why>' "
                    f"(tools/check_touch_switch.py, #5087): {text[:140]}")
    warns = [f"WARNING: tools/touch_switch_legacy.txt: {fn} {key} ({t}) is fixed or changed - delete its line"
             for (fn, key), ts in sorted(left.items()) for t in ts]
    return errs, warns, known


def errors():
    """For tools/check_layout.py: (errors without the prefix, warnings)."""
    e, w, _ = check()
    return [x.removeprefix("ERROR: ") for x in e], w


def main():
    if "--list" in sys.argv:
        for fn, n, key, text in hits():
            print(f"{fn} {key} #???? {n}: {text[:100]}")
        return 0
    errs, warns, known = check()
    for x in errs + warns:
        print(x)
    if "-v" in sys.argv:
        for k in known:
            print("known:", k)
    print(f"check_touch_switch: {len(known)} known hits, {len(errs)} new hit(s), {len(warns)} stale list line(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
