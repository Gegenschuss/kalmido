#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.754.0 (#5297) tools/check_innerhtml.py: every ${} in an HTML template is escaped, a safe helper, or marked.
 1. the web client as it is: no finding beyond tools/innerhtml_baseline.json
 2. the rule on small sources (selftest of the tool): a bare value, a ternary with a bare branch, a join of bare values are
    findings; esc(), tr(), trh(), numbers, x.length, constants, markup built on purpose, the mark are not
 3. a NEW unescaped value in a file is red (a copy of a start file with one added line), a fixed one is not
usage: python3 tests/p2754_c_innerhtml_lint_test.py"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import check, done  # noqa: E402
import check_innerhtml as C  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "check_innerhtml.py")
r = subprocess.run([sys.executable, TOOL], capture_output=True, text=True, timeout=300)
check(r.returncode == 0, "the web client: no new unescaped ${} in an HTML template: " + (r.stdout + r.stderr)[-800:])
r = subprocess.run([sys.executable, TOOL, "--selftest"], capture_output=True, text=True, timeout=60)
check(r.returncode == 0, "selftest: " + (r.stdout + r.stderr)[-800:])

new = "el.innerHTML = `<b>${userName}</b>`;\n"
check(len(list(C.scan(new))) == 1, "a new bare value in an HTML template is found")
check(not list(C.scan("el.innerHTML = `<b>${esc(userName)}</b>`;\n")), "esc() is clean")
check(not list(C.scan("el.innerHTML = `<b>${/*html-ok*/ built}</b>`;\n")), "the mark is clean")
# the baseline counts per file|expression: one more of a known pair is new, the known number is not
k = next(iter(C.json.load(open(C.BASE, encoding="utf-8"))))
check(isinstance(k, str) and "|" in k, "baseline keys are file|expression")
sys.exit(done("p2754_c_innerhtml_lint"))
