#!/usr/bin/env python3
# kalmido-suite: after=perf_budget nodata
"""2.653.0 part B (#5087): tools/check_touch_switch.py - finger operation on isTouchUi(), the width only for layout.
Static, no container:
 - the rule on single lines: isMobile() / a max-width query next to focus(), draggable, a touch handler, a key hint (kb,
   kbText, keys:), inputmode, navtouch or an_on is a hit; layout alone, isTouch()/isTouchUi() in the line, a 'layout:'
   comment and comment lines are not
 - a tree: a hit on the list (tools/touch_switch_legacy.txt format) is known, even moved to another line; a new hit is
   exit 1 with the file and line; a listed hit that is gone only warns (exit 0)
 - the real tree is green and check_layout.py runs the rule
usage: python3 tests/p2653_b_touchswitch_test.py"""
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import check, done  # noqa: E402
import check_touch_switch as ts  # noqa: E402

RED = [
    "if (!isMobile()) setTimeout(() => $('#w-note', md).focus(), 50);",
    "const drag = isMobile() ? '' : ' draggable=\"true\"';",
    "if (!S.sel || !isMobile() || e.touches.length !== 1) return;",
    "el.addEventListener('touchstart', e => { if (isMobile()) go(e); });",
    "d.addEventListener('pointerdown', e => isMobile() && hold(e));",
    "${isMobile() ? '' : kb(it.keys)}",
    "title: isMobile() ? t : `${t} (${kbText('Shift+T')})`,",
    "add('a:x', 'action', 'X', 'plus', () => { if (!isMobile()) q.focus(); }, {keys: 'n'});",
    "<input inputmode=\"${isMobile() ? 'numeric' : 'text'}\">",
    "return `<div class=\"naved${isMobile() ? ' navtouch' : ''}\">`;",
    "const an_on = () => isMobile() && !reduced();",
    "if (matchMedia('(max-width:767px)').matches) i.select();",
]
GREEN = [
    "if (isMobile()) el.classList.add('sheet');",                       # layout only
    "if (!isTouchUi()) setTimeout(() => $('#w-note', md).focus(), 50);",  # the finger switch
    "if (isMobile() || isTouch()) history.back(); i.focus();",          # the touch side decided in the line
    "if (isMobile()) d.focus({preventScroll: true});  // layout: the detail covers the list on a phone",
    "// if (!isMobile()) i.focus();",                                   # a comment line
    "i.focus(); el.setAttribute('draggable', 'true');",                 # no width test
]
for ln in RED:
    check(ts.is_hit(ln), "a hit: " + ln)
for ln in GREEN:
    check(not ts.is_hit(ln), "no hit: " + ln)
check(ts.line_key("  a  b ") == ts.line_key("a b") and ts.line_key("a b") != ts.line_key("a c"), "the key folds white space, a changed line has a new key")


def tree(files, legacy):
    d = tempfile.mkdtemp(prefix="p2653b-")
    os.makedirs(os.path.join(d, "static", "js"))
    for n, text in files.items():
        with open(os.path.join(d, "static", "js", n), "w", encoding="utf-8") as f:
            f.write(text)
    lp = os.path.join(d, "legacy.txt")
    with open(lp, "w", encoding="utf-8") as f:
        f.write("# comment\n" + legacy)
    return d, lp


OLD = "if (!isMobile()) setTimeout(() => $('#w-note', md).focus(), 50);"
NEW = "if (!isMobile()) $('#pm-name').focus();"
k_old = ts.line_key(OLD)
# the known hit moved down two lines: still known
d, lp = tree({"a.js": "'use strict';\n\n\n" + OLD + "\n"}, f"static/js/a.js {k_old} #5081 a.js:1\n")
e, w, known = ts.check(d, lp)
check(not e and not w and len(known) == 1 and "a.js:4" in known[0] and "#5081" in known[0], f"a listed hit that moved stays known: {e} {w} {known}")
shutil.rmtree(d)
# a new hit next to it: an error with file and line
d, lp = tree({"a.js": OLD + "\n" + NEW + "\n"}, f"static/js/a.js {k_old} #5081\n")
e, w, known = ts.check(d, lp)
check(len(e) == 1 and "static/js/a.js:2" in e[0] and "isTouchUi()" in e[0] and "layout:" in e[0] and not w, f"a new hit is an error naming the place and the way out: {e} {w}")
shutil.rmtree(d)
# the listed hit fixed: only a warning to delete the line
d, lp = tree({"a.js": OLD.replace("isMobile()", "isTouchUi()") + "\n"}, f"static/js/a.js {k_old} #5081\n")
e, w, known = ts.check(d, lp)
check(not e and len(w) == 1 and k_old in w[0] and "delete its line" in w[0], f"a fixed listed hit only warns: {e} {w}")
shutil.rmtree(d)
# the same line text twice in one file needs two list lines
d, lp = tree({"a.js": OLD + "\n" + OLD + "\n"}, f"static/js/a.js {k_old} #5081\n")
e, w, known = ts.check(d, lp)
check(len(e) == 1 and len(known) == 1, f"one list line covers one copy of a line: {e} {known}")
shutil.rmtree(d)

# the real tree: green, and check_layout.py runs the rule
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_touch_switch.py")], capture_output=True, text=True)
check(r.returncode == 0 and " 0 new hit(s)" in r.stdout, "the tree is green: " + r.stdout[-400:])
with open(os.path.join(ROOT, "tools", "check_layout.py"), encoding="utf-8") as f:
    check("import check_touch_switch" in f.read(), "check_layout.py (CI lint, Mac lint) runs check_touch_switch")
with open(os.path.join(ROOT, "static", "js", "icons.js"), encoding="utf-8") as f:
    src = f.read()
check("const isTouchUi = () => td_rc('touchui'" in src and "(pointer:coarse)" in src and "const isTouch = () =>" in src, "icons.js: isTouchUi() next to the unchanged isTouch()")

sys.exit(done("p2653_b_touchswitch_test"))
