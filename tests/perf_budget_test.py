#!/usr/bin/env python3
"""2.65.0 (#1822) the start-up performance budget (tools/perf_budget.py), static, no container:
 (a) the current state is within tools/perf_budget.json
 (b) a budget with too small limits fails, naming "Budget" and the key
 (c) an artificially enlarged state (a copy of the tree with one extra big script in index.html) fails
 2.521.0 (#4391): red only over a ceiling (decke_*); bytes alone are never red; --ratchet is gone (exit 2); the CI step runs the
     tool without --ratchet; the file has the ceilings and none of the old per-package limits
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import FAILS, check  # 2.206.0 (#2762): shared helpers (tests/kt.py)


def run(*a):
    r = subprocess.run([sys.executable, TOOL, *a], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


rc, out = run()
check(rc == 0, "(a) current state within the budget: " + out)
rc, out = run("--json")
d = json.loads(out)
check(rc == 0 and d["over"] == [] and d["measured"]["start_scripts"] > 50, "(a) --json output")
CEIL = ("decke_js_gzip", "decke_css_gzip", "decke_i18n_gzip", "decke_scripts")
check(all(d["limits"].get(k) for k in CEIL + ("start_ms",)) and d["measured"]["start_i18n_gzip"] > 0, "(a) 2.521.0 (#4391): the ceilings and start_ms are the limits")
check(all(k in d["measured"] for k in ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_i18n_bytes", "start_scripts")),
      "(a) 2.521.0 (#4391): everything is still measured")
lim0 = json.load(open(BUDGET))
OLD = ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_i18n_bytes", "start_i18n_gzip", "start_scripts", "_raise_note")
check(not [k for k in OLD if k in lim0] and lim0.get("decke_js_gzip") == 1050000 and lim0.get("decke_css_gzip") == 125000
      and lim0.get("decke_i18n_gzip") == 320000 and lim0.get("decke_scripts") == 145, "(a) 2.521.0 (#4391): ceilings set, old limits gone")
rc, out = run("--ratchet")
check(rc == 2 and "gone" in out, "(a) 2.521.0 (#4391): --ratchet is refused, not passed silently: " + out)
ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
steps = [ln for ln in ci.splitlines() if "tools/perf_budget.py" in ln and "run:" in ln]
step = ci[ci.index("- name: Performance budget"):][:400].split("\n      - ")[0] if "- name: Performance budget" in ci else ""
check(steps and not [ln for ln in steps if "--ratchet" in ln] and step and "CI_BEFORE" not in step, "(a) 2.521.0 (#4391): the CI step has no ratchet: " + repr(steps))

with tempfile.TemporaryDirectory() as tmp:
    small = os.path.join(tmp, "small.json")
    lim = json.load(open(BUDGET))
    for k in CEIL:
        lim[k] = 10
    json.dump(lim, open(small, "w"))
    rc, out = run("--budget", small)
    check(rc == 1 and "Budget exceeded" in out, "(b) too small ceilings exit 1: " + out)
    for k in CEIL:
        check(f"Budget exceeded: {k} " in out, "(b) message names " + k)
    check("only the project owner raises a ceiling" in out and "lazyload.js" in out and "never by cutting" in out, "(b) 2.521.0 (#4391): the message says who raises and how to shrink: " + out)
    # 2.521.0 (#4391): the bytes have no limit any more - old keys left in a file are ignored, never red
    old = dict(lim0, start_js_bytes=10, start_css_bytes=10, start_i18n_bytes=10)
    json.dump(old, open(small, "w"))
    rc, out = run("--budget", small)
    check(rc == 0 and "Budget exceeded" not in out, "(b) 2.521.0 (#4391): old byte limits are not checked: " + out)

    # (c) a copy of static/ (only what the tool reads) with one big extra script
    root = os.path.join(tmp, "tree")
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(root, "static"),
                    ignore=shutil.ignore_patterns("fonts", "*.png", "*.svg", "*.woff2", "i18n"))
    with open(os.path.join(root, "static", "js", "bloat.js"), "wb") as f:
        f.write(os.urandom(600000))
    p = os.path.join(root, "static", "index.html")
    h = open(p, encoding="utf-8").read()
    h = h.replace('<script src="/static/i18n.js" defer></script>', '<script src="/static/i18n.js" defer></script>\n<script src="/static/js/bloat.js" defer></script>', 1)  # 2.191.0 B (#2505): defer
    open(p, "w", encoding="utf-8").write(h)
    rc, out = run("--root", root)
    check(rc == 1 and "Budget exceeded: decke_js_gzip" in out, "(c) enlarged state over the JS ceiling exits 1: " + out)
    rc, out = run("--root", os.path.join(tmp, "tree"), "--budget", BUDGET)
    check(rc == 1, "(c) with the real budget file too")

print(f"{'FAILED ' + str(len(FAILS)) if FAILS else 'all ok'}")
sys.exit(1 if FAILS else 0)
