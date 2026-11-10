#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.854.0 (#5492): tools/check_lazy_calls.py got faster (identifier scan, shadowed() per file and name once). Static, no container.
 - on a small fixture root: an unguarded call of a name only a lazy file defines is reported (file:line), a typeof guard,
   a lazy-ok comment, a local variable of the same name and a name in a text or comment stay quiet
 - the repository: no finding
usage: p2854_a_lazylint_test.py"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import FAILS, OKS, check  # noqa: E402

TOOL = os.path.join(HERE, "..", "tools", "check_lazy_calls.py")


def lint(root):
    r = subprocess.run([sys.executable, TOOL, "-v", "--root", root], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


with tempfile.TemporaryDirectory() as root:
    js = os.path.join(root, "static", "js")
    os.makedirs(js)
    files = {
        "static/index.html": '<script src="/static/js/start.js"></script>\n',
        "static/js/lazyload.js": "const LD_MODS = {\n  m: ['lazy'],\n};\n",
        "static/js/lazy.js": "function badCall() {}\nfunction okTypeof() {}\nfunction okMarked() {}\nfunction shadowMe() {}\n"
                             "function inText() {}\nfunction ofish() {}\n",
        "static/js/start.js": "function go() {\n  badCall();\n  if (typeof okTypeof === 'function') okTypeof();\n"
                              "  okMarked(); // lazy-ok: runs only inside the module\n"
                              "  const shadowMe = () => 1;\n  shadowMe();\n  const t = 'inText(1)'; // inText()\n"
                              "  for (const x of ofishy(2)) x();\n}\n",
    }
    for rel, txt in files.items():
        with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
            fh.write(txt)
    code, out = lint(root)
    check(code == 1, f"the fixture is red: {out.strip()[:300]}")
    check("static/js/start.js:2: badCall() is only defined in lazy.js" in out, "badCall() at start.js:2 is reported")
    for quiet in ("okTypeof", "okMarked", "shadowMe", "inText", "ofish"):
        check(f": {quiet}()" not in out, f"{quiet}() stays quiet")
    check("1 unguarded" in out, "exactly one unguarded call counted: " + out.strip().splitlines()[-1])

code, out = lint(os.path.join(HERE, ".."))
check(code == 0 and "0 unguarded; css variables: 0 undefined" in out, "the repository: no finding: " + out.strip()[:300])
print(f"p2854_a_lazylint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
