#!/usr/bin/env python3
"""2.1024.0 (#5693): every menu goes through the shared menu() of static/js/popovers.js - no menu built by hand.

Audit 11.11.2026: "menus do not look the same" - the document view's Actions, the chat box's plus, the dots of budget /
bookmarks / feeds and the time tracking's Export / running indicator each had a fold-out of their own (#5688-#5691, all
moved onto menu()). This check keeps new ones from coming back.

Red, in static/js/*.js and static/*.js outside static/js/popovers.js:
  role   markup with role="menu" / "menuitem" / "menuitemcheckbox" / "menuitemradio" (a CSS selector [role="menuitem"]
         that looks into a menu() is fine)
  dots   a <details> fold-out whose <summary> is an icon button or shows the dots (the "⋯" menu of its own)
  toggle one tag that carries both aria-expanded and aria-haspopup, or an icon button with aria-expanded that shows only
         the dots / menu / plus symbol (a button that opens and closes a list of its own; menu() keeps that state itself)
  list   openPop(anchor, '<div class="menu-list …">…') with entries of its own instead of menu(items)

Not a menu and not caught: real choosers (date / person cards, reactions, colours, search fields, the project filter with
check boxes, view options, Last steps) - they use role="listbox" / "dialog", check boxes or no menu markup at all.

Exception: the comment `menu-ok: <reason>` (at least a few words) on the same line, e.g. /* menu-ok: a listbox in a sheet */.

Runs inside tools/check_layout.py (CI lint, Mac lint) and on its own:

usage: python3 tools/check_menu_own.py [FILE…]      exit code 1 on a hit
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join("static", "js", "popovers.js")
# the reason: words (at least ten letters / spaces), not just the comment end and the markup after it
OK = re.compile(r"menu-ok:\s*[A-Za-z][\w ,.;()'-]{9,}")
ROLE = re.compile(r"(?<!\[)\brole=\\?[\"']?menu(?:item(?:checkbox|radio)?)?\\?[\"'\s>]")
DETAILS = re.compile(r"<summary\b([^>]*)>(.*?)</summary>", re.S)
TAG = re.compile(r"<(?:button|a|div|span|summary)\b(?:[^<>$]|\$\{[^{}]*\})*>")
# an icon button that only shows dots / a menu or plus symbol: the opener of a list
ICON = re.compile(r"\s*\$\{ic\(\s*['\"](?:dots|menu|plus)['\"]")
POP = re.compile(r"\bopenPop\(")
WHY = {
    "role": "markup with role=\"menu\" built by hand - use menu(anchor, items) from popovers.js",
    "dots": "a <details> fold-out at an icon / dots button is a menu of its own - use menu(anchor, items)",
    "toggle": "a button with aria-expanded that opens a list of its own (aria-haspopup / dots / plus) - open menu(anchor, items) instead",
    "list": "openPop with a menu-list of its own buttons - use menu(anchor, items)",
}


def _call(src, at):
    """The text of the call whose "(" is at position `at` up to its ")" (strings and template literals not parsed: good enough)."""
    d = 0
    for j in range(at, min(len(src), at + 6000)):
        c = src[j]
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d == 0:
                return src[at:j + 1]
    return src[at:at + 6000]


def scan(rel, src):
    """[(line, kind)] of the hand-built menus in one file's text."""
    lines = src.split("\n")
    found = []

    def add(pos, kind):
        n = src.count("\n", 0, pos) + 1
        if not OK.search(lines[n - 1]):
            found.append((n, kind))

    for m in ROLE.finditer(src):
        add(m.start(), "role")
    for m in DETAILS.finditer(src):
        attrs, body = m.group(1), m.group(2)
        if "iconbtn" in attrs or re.search(r"\bic\(\s*['\"](?:dots|menu)['\"]", body):
            add(m.start(), "dots")
    for m in TAG.finditer(src):
        t = m.group(0)
        if "aria-expanded" in t and ("aria-haspopup" in t or "iconbtn" in t and ICON.match(src, m.end())):
            add(m.start(), "toggle")
    for m in POP.finditer(src):
        c = _call(src, m.end() - 1)
        if "menu-list" in c and 'role="listbox"' not in c and not re.search(r"type=\\?[\"'](?:checkbox|radio)", c):
            add(m.start(), "list")
    return sorted(set(found))


def files():
    return sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js")) + glob.glob(os.path.join(ROOT, "static", "*.js")))


def hits(paths=None):
    res = []
    for fn in paths or files():
        rel = os.path.relpath(os.path.abspath(fn), ROOT)
        if rel == SHARED:
            continue
        for n, kind in scan(rel, open(fn, encoding="utf-8").read()):
            res.append(f"{rel}:{n}: {WHY[kind]}, or mark the line `menu-ok: <reason>` (#5693)")
    return res


def errors():
    """For tools/check_layout.py."""
    return hits()


def main(argv):
    h = hits(argv or None)
    for x in h:
        print("ERROR:", x)
    print(f"check_menu_own: {len(h)} menu(s) built by hand")
    return 1 if h else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
