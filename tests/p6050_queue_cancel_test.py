#!/usr/bin/env python3
# kalmido-suite: nodata
"""#6050 (decision 13.11.2026): a merge queue entry whose group GitHub discarded (its gh-readonly-queue/main/pr-N-SHA ref
is deleted, e.g. after a push of the live train on main) cancels its own run instead of holding runners. Without a server
(CI Lint): the first step of the job "tests" in .github/workflows/ci.yml runs here in bash with a stubbed curl / gh:
- a gh-readonly-queue ref that answers 404 = `gh run cancel <own run>` and the shard stops (exit != 0);
- 200 (still in the queue), 500 / 403 / no network = the shard runs, nothing is cancelled;
- runs on main, tags, hotfix branches and every other event never cancel (step if + the ref prefix in the script);
- the job's token: actions: write only in the job "tests", the checkout keeps no token for the suites."""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(os.path.join(N, ".."))
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

with open(os.path.join(R, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
    ci = f.read()


def ci_job(name):
    m = re.search(r"^  " + re.escape(name) + r":\n((?:    .*\n|\n)+)", ci, re.M)
    return m.group(1) if m else ""


tests_job = ci_job("tests")
steps = tests_job.split("    steps:\n", 1)[1] if "    steps:\n" in tests_job else ""
steps = re.sub(r"^ *#.*\n", "", steps, flags=re.M)  # comment lines are no steps
first = steps.split("\n      - ", 1)[0]  # the first step (up to the next "- " of the list)
check(first.startswith("      - name: Queue entry still in the queue (#6050)\n"),
      f"ci.yml: the guard is the FIRST step of the test shards, before the checkout ({first[:80]!r})")
check("        if: github.event_name == 'merge_group'\n" in first, "ci.yml: the guard step runs for queue entries only")
check("QUEUE_REF: ${{ github.ref }}" in first and "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in first,
      "ci.yml: the guard reads the run's own ref and token")
head = tests_job.split("    steps:\n", 1)[0]
check(re.search(r"    permissions:\n      contents: read\n      actions: write\n", head) is not None,
      "ci.yml: the test shards may cancel their own run (actions: write), nothing more")
check(re.search(r"- uses: actions/checkout@\S+ # v[\d.]+\n        with:\n          persist-credentials: false", steps) is not None,
      "ci.yml: the shards' checkout keeps no token for the suites")
check(len(re.findall(r"^ +actions: write$", ci, re.M)) == 1, "ci.yml: actions: write in the job tests only")


def run_lines(step):
    m = re.search(r"\n        run: \|\n((?:          .*\n|\n)+)", step + "\n")
    return "".join(l[10:] if l.strip() else "\n" for l in m.group(1).splitlines(True)) if m else ""


SCRIPT = run_lines(first)
check("gh run cancel" in SCRIPT and "/git/ref/" in SCRIPT, "ci.yml: the guard asks for the exact ref and cancels via gh")

CURL = """#!/bin/sh
echo "curl $*" >> "$STUB_DIR/calls.log"
[ "$CURL_FAIL" = 1 ] && exit 28
printf '%s' "$HTTP_CODE"
"""
GH = """#!/bin/sh
echo "gh $*" >> "$STUB_DIR/calls.log"
exit 0
"""


def run_step(ref, code="200", event="merge_group", curl_fail=False):
    d = tempfile.mkdtemp(prefix="p6050-")
    try:
        for name, body in (("curl", CURL), ("gh", GH)):
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        script = os.path.join(d, "step.sh")
        with open(script, "w") as f:
            f.write(SCRIPT)
        env = dict(os.environ, PATH=d + os.pathsep + os.environ.get("PATH", ""), STUB_DIR=d, HTTP_CODE=code,
                   CURL_FAIL="1" if curl_fail else "0", EVENT=event, QUEUE_REF=ref, GH_TOKEN="t",
                   GITHUB_API_URL="https://api.example.invalid", GITHUB_REPOSITORY="o/r", GITHUB_RUN_ID="4711")
        # the shell of a GitHub run step on ubuntu-latest
        r = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", script], env=env, cwd=d,
                           capture_output=True, text=True, timeout=60)
        p = os.path.join(d, "calls.log")
        calls = open(p).read().splitlines() if os.path.exists(p) else []
        return r, calls
    finally:
        shutil.rmtree(d, ignore_errors=True)


Q = "refs/heads/gh-readonly-queue/main/pr-16-ef4a508246aa0000000000000000000000000000"

# 1. the group was discarded: the ref is gone -> cancel the own run, the shard stops
r, calls = run_step(Q, "404")
check(r.returncode != 0, f"1: discarded queue entry -> the shard stops (exit {r.returncode}, {r.stderr[-200:]!r})")
check(any(c == "gh run cancel 4711 -R o/r" for c in calls), f"1: the own run is cancelled ({calls})")
check(any(c.startswith("curl ") and "/repos/o/r/git/ref/heads/gh-readonly-queue/main/pr-16-" in c for c in calls),
      f"1: asked for exactly this ref ({calls})")
check("queue entry discarded" in r.stdout, "1: the log says why")

# 2. still in the queue -> runs, nothing cancelled
r, calls = run_step(Q, "200")
check(r.returncode == 0 and not any(c.startswith("gh ") for c in calls), f"2: entry in the queue -> runs ({r.returncode}, {calls})")

# 3. unclear answers never cancel (server error, no right, rate limit, no network)
for code in ("500", "403", "429"):
    r, calls = run_step(Q, code)
    check(r.returncode == 0 and not any(c.startswith("gh ") for c in calls), f"3: HTTP {code} -> runs, no cancel ({calls})")
r, calls = run_step(Q, "", curl_fail=True)
check(r.returncode == 0 and not any(c.startswith("gh ") for c in calls), f"3: no network -> runs, no cancel ({calls})")

# 4. main, tags, hotfix and other events are never cancelled, even if the API said 404
for ref, event in (("refs/heads/main", "push"), ("refs/tags/v2.1125.0", "push"), ("refs/heads/hotfix/2.1125.1", "push"),
                   ("refs/heads/main", "schedule"), ("refs/heads/main", "merge_group"), (Q, "push")):
    r, calls = run_step(ref, "404", event=event)
    check(r.returncode == 0 and calls == [], f"4: {event} {ref} -> never checked, never cancelled ({calls})")

sys.exit(done("p6050_queue_cancel"))
