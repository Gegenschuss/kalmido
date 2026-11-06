#!/usr/bin/env python3
"""2.309.0 (#3269): release.yml builds the image (:X.Y.Z) and the GitHub release of a tag only after a green
FULL run of the workflow CI on the tagged commit (tools/ci_gate.py). Without a server (CI Lint):
- release.yml has the job ci-gate (actions: read, runs tools/ci_gate.py on the tagged commit) and the job release
  needs it;
- tools/ci_gate.py: green full run = go; a run still queued / running = wait; red, cancelled, only the push stage = stop;
  one green full run beside a red one (re-run, nightly run of the same commit) = go; the loop in main() waits on the
  stubbed API state, not on a fixed time;
- 2.595.0 (#4905): a green full run of ANOTHER commit with the same tree counts (same files), one of another tree or only
  the push stage does not; release.yml can be re-run on a tag by workflow_dispatch and skips any other ref."""
import importlib.util
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

spec = importlib.util.spec_from_file_location("ci_gate", os.path.join(R, "tools", "ci_gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

with open(os.path.join(R, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
    rel = f.read()
jobs = rel.split("\njobs:\n", 1)[1] if "\njobs:\n" in rel else ""
g = re.search(r"^  ci-gate:\n((?:    .*\n|\n)+)", jobs, re.M)
gtxt = g.group(1) if g else ""
r = re.search(r"^  release:\n((?:    .*\n|\n)+)", jobs, re.M)
rtxt = r.group(1) if r else ""
check(bool(gtxt), "release.yml has the job ci-gate")
check("actions: read" in gtxt, "ci-gate may read the CI runs (actions: read)")
check("tools/ci_gate.py" in gtxt and "GITHUB_SHA" in gtxt, "ci-gate runs tools/ci_gate.py on the tagged commit")
check(re.search(r"^    needs: \[?ci-gate\]?$", rtxt, re.M) is not None, "the job release needs ci-gate (no image / release before green CI)")
check("write" not in gtxt, "ci-gate has no write permission")

FULL = ["Shard plan (stage, suite times of the last runs)", "Test suites 1/20 full (API, UI, security)", "Lint"]
PUSH = ["Test suites 1/6 push (API, UI, security)", "Lint"]


def run(i, status="completed", conclusion="success"):
    return {"id": i, "status": status, "conclusion": conclusion if status == "completed" else None}


def jobs_of(names):
    return lambda rid: names[rid]


check(gate.stage(FULL) == "full" and gate.stage(PUSH) == "push" and gate.stage(["Lint"]) == "?", "stage from the shard job names")
res, _ = gate.decide([run(1)], jobs_of({1: FULL}))
check(res == "green", "green full run = go (%s)" % res)
res, txt = gate.decide([run(1)], jobs_of({1: PUSH}))
check(res == "red" and "push" in txt, "green, but only the push stage = no release (%s, %s)" % (res, txt))
res, _ = gate.decide([run(1, "in_progress")], jobs_of({}))
check(res == "wait", "CI still running = wait (%s)" % res)
res, _ = gate.decide([run(1, "queued")], jobs_of({}))
check(res == "wait", "CI queued = wait (%s)" % res)
res, txt = gate.decide([run(1, conclusion="failure")], jobs_of({}))
check(res == "red" and "failure" in txt, "red CI = no release (%s, %s)" % (res, txt))
res, txt = gate.decide([run(1, conclusion="cancelled")], jobs_of({}))
check(res == "red" and "cancelled" in txt, "cancelled CI = no release (%s, %s)" % (res, txt))
res, _ = gate.decide([run(2, conclusion="failure"), run(1)], jobs_of({1: FULL}))
check(res == "green", "a green full run of the same commit beside a red one = go (%s)" % res)
res, _ = gate.decide([run(2, conclusion="failure"), run(1, "in_progress")], jobs_of({}))
check(res == "wait", "red + another run still running = wait for it (%s)" % res)
res, _ = gate.decide([], jobs_of({}))
check(res == "none", "no CI run yet = none (%s)" % res)

# main(): polls the stubbed API until the state changes (in progress -> green), stops at red, gives up without a run
states = []


def fake_api(seq, names, tree="", same=()):
    # 2.595.0 (#4905): the gate also asks the tree of the tag and the green runs; they do not count as polls
    def api(path):
        if "/jobs" in path:
            return {"jobs": [{"name": n} for n in names]}
        if "/git/commits/" in path:
            asked.append(path)
            return {"tree": {"sha": tree}}
        if "status=success" in path:
            asked.append(path)
            return {"workflow_runs": list(same)}
        states.append(path)
        return {"workflow_runs": seq[min(len(states), len(seq)) - 1]}
    return api


asked = []


def main_rc(seq, names, *extra, tree="", same=()):
    del states[:], asked[:]
    gate.api = fake_api(seq, names, tree, same)
    old = sys.argv, dict(os.environ)
    sys.argv = ["ci_gate.py", "--sha", "abc123", "--poll-s", "0"] + list(extra)
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    try:
        return gate.main()
    finally:
        sys.argv = old[0]
        os.environ.clear()
        os.environ.update(old[1])


rc = main_rc([[], [run(7, "queued")], [run(7, "in_progress")], [run(7)]], FULL)
check(rc == 0 and len(states) == 4, "main waits through none / queued / running until green (rc %s, %d polls)" % (rc, len(states)))
check("head_sha=abc123" in (states[0] if states else ""), "main asks for the runs of the tagged commit")
rc = main_rc([[run(7, "in_progress")], [run(7, conclusion="failure")]], FULL)
check(rc == 1 and len(states) == 2, "main stops when the CI turns red (rc %s)" % rc)
rc = main_rc([[]], FULL, "--no-run-min", "0")
check(rc == 1, "main gives up when no CI run shows up (rc %s)" % rc)
rc = main_rc([[run(7, "in_progress")]], FULL, "--timeout-min", "0")
check(rc == 1, "main gives up at the time limit while the CI still runs (rc %s)" % rc)

# ------------------------------------------------------------------ 2.595.0 (#4905): same tree, re-run on a tag
def trun(i, sha, tree, conclusion="success", event="push", repo="owner/repo"):
    return dict(run(i, conclusion=conclusion), head_sha=sha, head_commit={"tree_id": tree}, event=event, head_repository={"full_name": repo})


tagrun = trun(1, "abc123", "T1", "failure")
st = gate.same_tree([tagrun, trun(2, "def456", "T1"), trun(3, "fff000", "T2"), trun(4, "aaa111", "T1", "failure")], "T1", "abc123", "owner/repo")
check([r["id"] for r in st] == [2], "same_tree: only green runs of other commits with the same tree (%s)" % [r["id"] for r in st])
check(gate.same_tree([trun(2, "def456", "T1")], "", "abc123", "owner/repo") == [], "same_tree: no tree known = nothing")
# review 2.595.0 (#4905): a pull_request run (it tests the merge commit) and a run of a fork never count
check(gate.same_tree([trun(5, "def456", "T1", event="pull_request"), trun(6, "def456", "T1", repo="x/fork"),
                      trun(7, "def456", "T1", event="workflow_dispatch")], "T1", "abc123", "owner/repo") == [trun(7, "def456", "T1", event="workflow_dispatch")],
      "same_tree: only push / schedule / dispatch runs of the own repository")
res, txt = gate.decide_tree("red", "run 1 failure", [trun(2, "def456", "T1")], jobs_of({2: FULL}))
check(res == "green" and "same tree" in txt, "red tag commit + green full run of the same tree = go (%s, %s)" % (res, txt))
res, _ = gate.decide_tree("red", "run 1 failure", [trun(2, "def456", "T1")], jobs_of({2: PUSH}))
check(res == "red", "same tree but only the push stage = still no release (%s)" % res)
res, _ = gate.decide_tree("red", "x", [], jobs_of({}))
check(res == "red", "no run of the same tree = red stays (%s)" % res)
rc = main_rc([[tagrun]], FULL, tree="T9", same=[trun(2, "def456", "T1")])
check(rc == 0 and "git/commits/abc123" not in " ".join(asked), "main: the tree comes from the tag's own run, a green full run of it = go (rc %s, %s)" % (rc, asked))
rc = main_rc([[run(7, conclusion="failure")]], FULL, tree="T1", same=[trun(2, "def456", "T1")])
check(rc == 0 and any("git/commits/abc123" in x for x in asked), "main: without head_commit the tree comes from the git commit (rc %s)" % rc)
rc = main_rc([[tagrun]], FULL, same=[trun(2, "def456", "T2")])
check(rc == 1, "main: a green run of another tree does not count (rc %s)" % rc)
rc = main_rc([[]], FULL, "--no-run-min", "60", tree="T1", same=[trun(2, "def456", "T1")])
check(rc == 0, "main: no run of the tag yet, but the same tree is green = go (rc %s)" % rc)

check(re.search(r"^on:\n(?:  .*\n)*  workflow_dispatch:", rel, re.M) is not None, "#4905: release.yml can be re-run on a tag (workflow_dispatch)")
check("if: startsWith(github.ref, 'refs/tags/v')" in gtxt, "#4905: a dispatch on a branch is skipped (only refs/tags/v...)")

print("release_ci_gate: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
