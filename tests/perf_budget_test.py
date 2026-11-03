#!/usr/bin/env python3
"""2.65.0 (#1822) the start-up performance budget (tools/perf_budget.py), static, no container:
 (a) the current state is within tools/perf_budget.json
 (b) a budget with too small limits fails, naming "Budget" and the key
 (c) an artificially enlarged state (a copy of the tree with one extra big script in index.html) fails
 (d) 2.501.0 (#4198) --ratchet in a throwaway git repo: a raise alone is red, a raise with an equal cut is green, gzip and bytes
     are separate sums, a new limit does not count, a removed one is red, no base is red in the CI and only a visible line outside
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
check(all(d["limits"].get(k) for k in ("start_i18n_bytes", "start_i18n_gzip")) and d["measured"]["start_i18n_gzip"] > 0, "(a) 2.501.0 (#4198): the language core has limits")

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
    h = h.replace('<script src="/static/i18n.js" defer></script>', '<script src="/static/i18n.js" defer></script>\n<script src="/static/js/bloat.js" defer></script>', 1)  # 2.191.0 B (#2505): defer
    open(p, "w", encoding="utf-8").write(h)
    rc, out = run("--root", root)
    check(rc == 1 and "Budget exceeded: start_js_bytes" in out, "(c) enlarged state exits 1: " + out)
    rc, out = run("--root", os.path.join(tmp, "tree"), "--budget", BUDGET)
    check(rc == 1, "(c) with the real budget file too")


# (d) 2.501.0 (#4198): the ratchet
def git(cwd, *a):
    subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)


CI_VARS = ("GITHUB_EVENT_NAME", "GITHUB_REF", "CI_BEFORE")


def ratchet(root, *a, **env):
    e = {k: v for k, v in os.environ.items() if k not in CI_VARS}
    r = subprocess.run([sys.executable, TOOL, "--root", root, "--budget", os.path.join(root, "tools", "perf_budget.json"), "--ratchet", *a],
                       capture_output=True, text=True, env={**e, **env})
    return r.returncode, r.stdout + r.stderr


with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "r")
    os.makedirs(os.path.join(root, "static"))
    os.makedirs(os.path.join(root, "tools"))
    open(os.path.join(root, "static", "index.html"), "w").write("<html></html>")
    open(os.path.join(root, "static", "sw.js"), "w").write("")
    bfile = os.path.join(root, "tools", "perf_budget.json")
    BASE_LIM = {"start_js_bytes": 1000, "start_js_gzip": 500, "start_css_bytes": 1000, "start_css_gzip": 500, "start_scripts": 10}

    def limits(**kw):
        json.dump({**BASE_LIM, **kw}, open(bfile, "w"))

    limits()
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    rc, out = ratchet(root, sha)
    check(rc == 0 and "ok against" in out, "(d) unchanged limits green: " + out)
    limits(start_js_gzip=501)
    rc, out = ratchet(root, sha)
    check(rc == 1 and "Budget ratchet: gzip" in out and "lazyload.js" in out, "(d) gzip raise alone red, says how to shrink: " + out)
    limits(start_js_gzip=600, start_css_gzip=400)
    rc, out = ratchet(root, sha)
    check(rc == 0, "(d) gzip raise with an equal cut green: " + out)
    limits(start_js_gzip=600, start_css_gzip=401)
    rc, out = ratchet(root, sha)
    check(rc == 1, "(d) a cut one byte short red: " + out)
    limits(start_js_gzip=600, start_css_bytes=900)
    rc, out = ratchet(root, sha)
    check(rc == 1 and "Budget ratchet: gzip" in out and "Budget ratchet: bytes" not in out, "(d) a cut in the bytes does not pay for gzip: " + out)
    limits(start_js_bytes=1100, start_css_gzip=400)
    rc, out = ratchet(root, sha)
    check(rc == 1 and "Budget ratchet: bytes" in out and "Budget ratchet: gzip" not in out, "(d) a cut in gzip does not pay for the bytes: " + out)
    limits(start_scripts=11, start_css_gzip=1)
    rc, out = ratchet(root, sha)
    check(rc == 1 and "Budget ratchet: scripts" in out, "(d) start_scripts must not rise: " + out)
    limits(start_i18n_gzip=300000, start_i18n_bytes=900000)
    rc, out = ratchet(root, sha)
    check(rc == 0, "(d) a new limit is no raise: " + out)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "i18n limits")
    sha2 = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    limits(start_i18n_gzip=300001, start_i18n_bytes=900000)
    rc, out = ratchet(root, sha2)
    check(rc == 1 and "Budget ratchet: gzip" in out, "(d) the new limit counts once it is in the base: " + out)
    limits(start_i18n_bytes=900000)
    rc, out = ratchet(root, sha2)
    check(rc == 1 and "limit removed: start_i18n_gzip" in out, "(d) a removed limit red: " + out)
    limits(start_i18n_gzip=300000, start_i18n_bytes=900000)

    rc, out = ratchet(root, "0" * 40)
    check(rc == 1 and "NOT COMPARED" in out, "(d) a base that cannot be read red: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", CI_BEFORE="0" * 40)
    check(rc == 1 and "NOT COMPARED" in out, "(d) CI push without a previous commit red: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", CI_BEFORE="1" * 40)
    check(rc == 1 and "NOT COMPARED" in out, "(d) CI push with an unreachable previous commit red: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", CI_BEFORE=sha2)
    check(rc == 0 and "ok against" in out, "(d) CI push compares with CI_BEFORE: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="pull_request")
    check(rc == 0 and "against HEAD^1" in out, "(d) pull request compares with the parent: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="schedule")
    check(rc == 0 and "NOT COMPARED" in out, "(d) nightly run: a visible line, not red: " + out)
    rc, out = ratchet(root, GITHUB_EVENT_NAME="surprise")
    check(rc == 1 and "NOT COMPARED" in out, "(d) unknown event red: " + out)

    # the train's lint replay: no CI event, the base is the merge base with main (main + package on a branch)
    git(root, "checkout", "-q", "-b", "job/1")
    limits(start_js_gzip=501, start_i18n_gzip=300000, start_i18n_bytes=900000)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "raise")
    rc, out = ratchet(root)
    check(rc == 1 and "merge base with main" in out, "(d) replay without a CI event finds main: " + out)

    one = os.path.join(tmp, "one")
    shutil.copytree(root, one, ignore=shutil.ignore_patterns(".git"))
    git(one, "init", "-q", "-b", "main")
    git(one, "add", ".")
    git(one, "commit", "-q", "-m", "only")
    rc, out = ratchet(one, GITHUB_EVENT_NAME="pull_request")
    check(rc == 1 and "NOT COMPARED" in out, "(d) pull request without a parent red: " + out)

    plain = os.path.join(tmp, "plain")
    shutil.copytree(root, plain, ignore=shutil.ignore_patterns(".git"))
    rc, out = ratchet(plain)
    check(rc == 0 and "NOT COMPARED" in out, "(d) replay in a tree without git: a visible line, no crash: " + out)

print(f"{'FAILED ' + str(len(FAILS)) if FAILS else 'all ok'}")
sys.exit(1 if FAILS else 0)
