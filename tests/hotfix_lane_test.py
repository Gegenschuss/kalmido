#!/usr/bin/env python3
"""2.285.0 (#2830): the fast lane of the live train - an urgent fix goes live as a patch on the last live tag, from a
branch hotfix/X.Y.Z beside main. Without a server (CI Lint):
- ci.yml runs on pushes to hotfix/** (besides main) and its concurrency group hangs on github.ref (a hotfix push and a
  push on main never cancel each other); the suite times are still read from main only;
- tests/stages.py gives a push on a hotfix branch the full stage (a push on main keeps the push stage);
- 2.513.0 (#4354): "a tag below the newest keeps latest where it is" now lives in promote.yml (tests/p2513_promote_test.py)."""
import os
import re
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402
import stages  # noqa: E402


def read(*p):
    with open(os.path.join(R, *p), encoding="utf-8") as f:
        return f.read()


ci = read(".github", "workflows", "ci.yml")
m = re.search(r"^on:\n  push:\n(?:    #.*\n)*    branches: \[([^\]]*)\]", ci, re.M)
br = [b.strip().strip('"\'') for b in m.group(1).split(",")] if m else []
check("main" in br and "hotfix/**" in br, "ci.yml runs on pushes to main and hotfix/** (%s)" % br)
check("format('ci-{0}', github.ref)" in ci, "ci.yml concurrency group per ref (hotfix and main never cancel each other)")
check(ci.count("--branch main") >= 2, "suite times / flake runs are read from main only")
check("--branch hotfix" not in ci, "no suite times from hotfix branches")


def ci_base(env):
    keep = {k: os.environ.get(k) for k in ("GITHUB_EVENT_NAME", "GITHUB_REF", "CI_BEFORE", "CI_MESSAGE", "CI_INPUT_STAGE")}
    try:
        for k in keep:
            os.environ.pop(k, None)
        os.environ.update(env)
        return stages.ci_base()
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


head = subprocess.run(["git", "-C", R, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
st, why, _ = ci_base({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/hotfix/2.166.5", "CI_BEFORE": head or "1" * 40})
check(st == "full" and "hotfix" in why, "push on hotfix/2.166.5 = stage full (%s, %s)" % (st, why))
st, why, base = ci_base({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main", "CI_BEFORE": head or "1" * 40})
check(st is None and "hotfix" not in why, "push on main keeps the push stage (%s, %s)" % (st, why))
st, why, _ = ci_base({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/hotfixes", "CI_BEFORE": head or "1" * 40})
check(st is None, "a branch 'hotfixes' is no hotfix branch (%s)" % st)

rel = read(".github", "workflows", "release.yml")
check("${{ steps.v.outputs.image }}:${{ steps.v.outputs.version }}" in rel, "the version image tag stays")

print("hotfix_lane: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
