#!/usr/bin/env python3
"""2.285.0 (#2830): the fast lane of the live train - an urgent fix goes live as a patch on the last live tag, from a
branch hotfix/X.Y.Z beside main. Without a server (CI Lint):
- ci.yml runs on pushes to hotfix/** (besides main) and its concurrency group hangs on github.ref (a hotfix push and a
  push on main never cancel each other); the suite times are still read from main only;
- tests/stages.py gives a push on a hotfix branch the full stage (a push on main keeps the push stage);
- release.yml marks a tag below the newest version tag neither as GitHub "latest" nor as image :latest (the newest
  version keeps both); the comparison is run here with stubbed tags."""
import os
import re
import subprocess
import sys
import tempfile

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
check("${{ steps.v.outputs.latest == 'true' && 'ghcr.io/gegenschuss/kalmido:latest' || '' }}" in rel,
      "image tag :latest only for the newest version")
check('--latest="${{ steps.v.outputs.latest }}"' in rel, "gh release create marks latest only for the newest version")
check("ghcr.io/gegenschuss/kalmido:${{ steps.v.outputs.version }}" in rel, "the version image tag stays")
step = re.search(r"- name: Version from tag\n(?:.*\n)*?        run: \|\n((?:          .*\n|\n)+)", rel)
script = "\n".join(line[10:] for line in step.group(1).splitlines()) if step else ""
check("ls-remote" in script and "latest=" in script, "release.yml compares the tag with the newest version tag")


def latest(ver, tags):
    """Run the 'Version from tag' step with a stubbed git (tags) and VERSION = ver; the 'latest' output."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "VERSION"), "w") as f:
            f.write(ver + "\n")
        out = os.path.join(d, "out")
        stub = "git() { for t in %s; do printf 'abc\\trefs/tags/%%s\\n' \"$t\"; done; }\n" % " ".join(tags)
        r = subprocess.run(["bash", "-ec", stub + script], cwd=d, capture_output=True, text=True,
                           env=dict(os.environ, GITHUB_REF_NAME="v" + ver, GITHUB_OUTPUT=out))
        if r.returncode:
            return "rc %d: %s" % (r.returncode, r.stdout + r.stderr)
        with open(out) as f:
            return dict(line.split("=", 1) for line in f.read().split()).get("latest")


check(latest("2.166.5", ["v2.166.4", "v2.223.1", "v2.9.0"]) == "false", "2.166.5 below v2.223.1 = not latest")
check(latest("2.223.2", ["v2.166.4", "v2.223.1", "v2.9.0"]) == "true", "2.223.2 above every tag = latest")
check(latest("2.223.1", ["v2.166.5", "v2.223.1"]) == "true", "the newest tag itself = latest")
check(latest("2.10.0", ["v2.9.0", "v2.10.0"]) == "true", "version order, not text order (2.10.0 after 2.9.0)")
check(latest("2.9.1", ["v2.9.0", "v2.10.0"]) == "false", "2.9.1 below 2.10.0 = not latest")
check(latest("1.0.0", []) == "true", "no tags yet = latest")

print("hotfix_lane: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
