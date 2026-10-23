#!/usr/bin/env python3
"""2.188.0 part B (#2498): tools/eslint_globals.py finds the same global name declared in two classic scripts.
Static, no container. usage: p2188_b_globals_dup_test.py"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("eg", os.path.join(ROOT, "tools", "eslint_globals.py"))
eg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eg)
FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


d = eg.duplicates({"a.js": "const PL = 1;\nfunction ok() { const PL2 = 2; }\n", "b.js": "const PL = 2;\n"})
check(d == [("PL", ["a.js", "b.js"], True)], "const + const reported as hard clash: %r" % (d,))
d = eg.duplicates({"a.js": "let X = 1;", "b.js": "function X() {}"})
check(len(d) == 1 and d[0][2], "let + function reported as hard clash")
d = eg.duplicates({"a.js": "class K {}", "b.js": "var K = 1;"})
check(len(d) == 1 and d[0][2], "class + var reported as hard clash")
d = eg.duplicates({"a.js": "function f() {}", "b.js": "function f() {}"})
check(len(d) == 1 and not d[0][2], "function + function reported (soft)")
d = eg.duplicates({"a.js": "function g() { const PL = 1; }", "b.js": "const PL = 2;"})
check(d == [], "a name inside a function is not global")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "eslint_globals.py"), "--check"], capture_output=True, text=True)
check(r.returncode == 0, "current client scripts have no duplicate global names: " + r.stdout)
if FAILS:
    print("FAILED", len(FAILS))
    sys.exit(1)
print("p2188_b_globals_dup: ok")
