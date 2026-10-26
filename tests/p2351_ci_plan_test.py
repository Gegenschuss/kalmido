#!/usr/bin/env python3
# kalmido-suite: nodata
"""CI fix of 2.351.0: the plan job of ci.yml ran tests/stages.py 6+ min for the 204 changed files of the live train push and the
job limit (5 min) cancelled it, every shard was skipped. No server.

- one file that needs the full run (VERSION) decides the stage before any search through the test files
- importers() of a server module gives the same set twice (the second time from the cache)
- Repo.mentioning() finds a token in the same test files as the plain search through every file
- ci.yml limits stages.py and every download of suite times, so a slow step means a full run, not a cancelled plan"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(os.path.dirname(N), "tools"))
import stages  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

repo = stages.Repo(stages.ROOT, os.path.join(N, "run_all.sh"))

# 1. VERSION decides at once: neither the importers of the server module nor the test files are searched
calls = []
real_importers, real_mentioning = stages.importers, repo.mentioning
stages.importers = lambda *a, **k: calls.append("importers") or real_importers(*a, **k)
repo.mentioning = lambda *a, **k: calls.append("mentioning") or real_mentioning(*a, **k)
stage, reason, groups, _ = stages.select(repo, ["kalmido/agents/admin.py", "VERSION", "static/sw.js"])
check(stage == "full" and "VERSION" in reason and not groups, f"VERSION = full run: {stage} {reason!r}")
check(calls == [], f"no search before the stage is decided: {calls}")
kind, res = stages.classify(repo, "kalmido/agents/admin.py", cheap=True)
check(kind == "later" and res is None, f"cheap classification leaves a server module for later: {kind}")
stages.importers, repo.mentioning = real_importers, real_mentioning

# 2. importers: the cache gives the same set as a fresh search
rel = "kalmido/accounts/discover.py"
first = stages.importers(repo, rel)
check(rel in first and repo._importers, f"{rel}: {len(first)} modules, {len(repo._importers)} cached")
repo._importers = {}
check(stages.importers(repo, rel) == first, "a fresh search gives the cached set")

# 3. mentioning: the joined text finds the same files as the plain search
for tok in ("/api/lists", "kt.py", "freelancer-matrix:", "no-such-token-p2351"):
    plain = [r for r in repo.tests if tok in repo.text(r)]
    check(repo._files_with(tok) == plain, f"{tok}: {len(plain)} files")

# 4. ci.yml: the limits of the plan job
ci = open(os.path.join(os.path.dirname(N), ".github", "workflows", "ci.yml"), encoding="utf-8").read()
check("timeout 150 python3 tests/stages.py --ci" in ci, "ci.yml limits tests/stages.py to 150 s (then the full run)")
check('timeout 60 gh run download "$id"' in ci, "ci.yml limits each download of suite times to 60 s")

print(f"p2351_ci_plan: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
