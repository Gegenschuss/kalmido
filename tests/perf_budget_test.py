#!/usr/bin/env python3
"""2.65.0 (#1822) the start-up performance budget (tools/perf_budget.py), static, no container:
 (a) the current state is within tools/perf_budget.json
 (b) a budget with too small limits fails, naming "Budget" and the key
 (c) an artificially enlarged state (a copy of the tree with one extra big script in index.html) fails
usage: python3 tests/perf_budget_test.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOOL = os.path.join(ROOT, "tools", "perf_budget.py")
BUDGET = os.path.join(ROOT, "tools", "perf_budget.json")
F = []


def run(*a):
    r = subprocess.run([sys.executable, TOOL, *a], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def check(c, what):
    if not c:
        F.append(what)
        print("FAIL:", what)


rc, out = run()
check(rc == 0, "(a) current state within the budget: " + out)
rc, out = run("--json")
d = json.loads(out)
check(rc == 0 and d["over"] == [] and d["measured"]["start_scripts"] > 50, "(a) --json output")

with tempfile.TemporaryDirectory() as tmp:
    small = os.path.join(tmp, "small.json")
    lim = json.load(open(BUDGET))
    for k in ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_scripts"):
        lim[k] = 10
    json.dump(lim, open(small, "w"))
    rc, out = run("--budget", small)
    check(rc == 1 and "Budget exceeded" in out, "(b) too small limits exit 1: " + out)
    for k in ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_scripts"):
        check(f"Budget exceeded: {k} " in out, "(b) message names " + k)

    # (c) a copy of static/ (only what the tool reads) with one big extra script
    root = os.path.join(tmp, "tree")
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(root, "static"),
                    ignore=shutil.ignore_patterns("fonts", "*.png", "*.svg", "*.woff2", "i18n"))
    with open(os.path.join(root, "static", "js", "bloat.js"), "wb") as f:
        f.write(os.urandom(600000))
    p = os.path.join(root, "static", "index.html")
    h = open(p, encoding="utf-8").read()
    h = h.replace('<script src="/static/i18n.js"></script>', '<script src="/static/i18n.js"></script>\n<script src="/static/js/bloat.js"></script>', 1)
    open(p, "w", encoding="utf-8").write(h)
    rc, out = run("--root", root)
    check(rc == 1 and "Budget exceeded: start_js_bytes" in out, "(c) enlarged state exits 1: " + out)
    rc, out = run("--root", os.path.join(tmp, "tree"), "--budget", BUDGET)
    check(rc == 1, "(c) with the real budget file too")

print(f"{'FAILED ' + str(len(F)) if F else 'all ok'}")
sys.exit(1 if F else 0)
