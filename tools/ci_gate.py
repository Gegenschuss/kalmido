#!/usr/bin/env python3
"""2.309.0 (#3269): the gate of release.yml - the image (:X.Y.Z) and the GitHub release of a tag come only
after a GREEN FULL run of the workflow "CI" on the tagged commit ("the CI is the only gate", #1315). Self-hosters never
get a red version; "latest" comes later still, with promote.yml after the device test (2.513.0, #4354).

  python3 tools/ci_gate.py [--sha SHA] [--timeout-min 240] [--poll-s 60] [--no-run-min 20]

Reads the CI runs of the commit (GET /repos/R/actions/workflows/ci.yml/runs?head_sha=SHA, needs `actions: read`) and
the job names of a green run (the shard jobs "Test suites N/M full ..." = the full stage, see ci.yml / tests/stages.py).
Exit 0 = a run of SHA is green and was the full stage; 1 = the CI of SHA is red / cancelled / only the push stage /
no CI run within --no-run-min / still running at --timeout-min. While a run of SHA is queued or running it waits.
A red or cancelled run that is re-run by hand (same run, new attempt) counts again; re-run this workflow afterwards.
2.595.0 (#4905): when the tagged commit itself has no green full run, a green full CI run of ANOTHER commit with the same
tree (identical files: the version commit back on main, a nightly / dispatched full run, a hotfix branch) counts as well -
the CI tests files, not commit ids. Read from head_commit.tree_id of the run list (GET .../runs?status=success), no extra
request per run. Not a loosening: the code of the tag has to have passed the full stage.
Env: GITHUB_TOKEN (or GH_TOKEN), GITHUB_REPOSITORY, GITHUB_SHA, GITHUB_API_URL (all set on GitHub Actions)."""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

STAGE_RE = re.compile(r"^Test suites \d+/\d+ (full|push)\b")


def stage(job_names):
    """"full" | "push" | "?" - the test stage of a CI run from its shard job names."""
    seen = {m.group(1) for m in (STAGE_RE.match(n or "") for n in job_names) if m}
    return "full" if "full" in seen else ("push" if "push" in seen else "?")


def decide(runs, jobs_of):
    """runs = the CI runs of the commit (GitHub API dicts), jobs_of(run_id) -> job names.
    ("green" | "wait" | "red" | "none", text). Green beats everything (one green full run is enough); then a run still
    queued / in progress = wait; else red with the reasons."""
    if not runs:
        return "none", "no CI run for this commit yet"
    why = []
    for r in runs:
        if r.get("status") == "completed" and r.get("conclusion") == "success":
            st = stage(jobs_of(r["id"]))
            if st == "full":
                return "green", "CI run %s is green (full stage)" % r["id"]
            why.append("run %s green, but stage %s (a release needs the full stage)" % (r["id"], st))
    busy = [r for r in runs if r.get("status") != "completed"]
    if busy:
        return "wait", "CI run %s %s" % (busy[0]["id"], busy[0].get("status"))
    for r in runs:
        if r.get("conclusion") != "success":
            why.append("run %s %s" % (r["id"], r.get("conclusion")))
    return "red", "; ".join(why)


TREE_EVENTS = ("push", "schedule", "workflow_dispatch")  # review 2.595.0 (#4905): a pull_request run tests the merge commit, other files


def same_tree(runs, tree, sha, repo):
    """The green, finished CI runs of OTHER commits whose tree equals `tree` (the files of the tagged commit); only runs of this
    repository that tested the commit itself (push / schedule / dispatch), never pull_request runs or forks."""
    if not tree or not repo:
        return []
    return [r for r in runs if r.get("head_sha") != sha and (r.get("head_commit") or {}).get("tree_id") == tree
            and r.get("status") == "completed" and r.get("conclusion") == "success" and r.get("event") in TREE_EVENTS
            and (r.get("head_repository") or {}).get("full_name") == repo]


def decide_tree(res, txt, tree_runs, jobs_of):
    """#4905: (res, txt) of the tagged commit; a green FULL run with the same tree turns red / none / wait into green."""
    if res == "green":
        return res, txt
    for r in tree_runs:
        if stage(jobs_of(r["id"])) == "full":
            return "green", "CI run %s of %s is green (full stage) on the same tree as the tag" % (r["id"], str(r.get("head_sha"))[:12])
    return res, txt


def api(path):
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    req = urllib.request.Request(base + path, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + tok,
                                                       "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=60) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    ap.add_argument("--timeout-min", type=float, default=240)
    ap.add_argument("--poll-s", type=float, default=60)
    ap.add_argument("--no-run-min", type=float, default=20)
    a = ap.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (a.sha and repo):
        print("ci_gate: GITHUB_SHA / GITHUB_REPOSITORY missing"); return 1
    t0 = time.time()
    tree = [None]

    def tree_of():  # the tree of the tagged commit (from its own run, else the git commit), asked once
        if tree[0] is None:
            tree[0] = (api("/repos/%s/git/commits/%s" % (repo, a.sha)).get("tree") or {}).get("sha") or ""
        return tree[0]

    def jobs_of(rid):
        return [j.get("name") for j in api("/repos/%s/actions/runs/%s/jobs?per_page=100" % (repo, rid)).get("jobs", [])]

    while True:
        try:
            runs = api("/repos/%s/actions/workflows/ci.yml/runs?head_sha=%s&per_page=50" % (repo, a.sha)).get("workflow_runs", [])
            res, txt = decide(runs, jobs_of)
            if res != "green":  # #4905: a green full run of the same files on another commit
                own = [(r.get("head_commit") or {}).get("tree_id") for r in runs if r.get("head_sha") == a.sha]
                if own and own[0] and tree[0] is None:
                    tree[0] = own[0]
                tr = tree_of()
                if tr:
                    ok = api("/repos/%s/actions/workflows/ci.yml/runs?status=success&per_page=100" % repo).get("workflow_runs", [])
                    res, txt = decide_tree(res, txt, same_tree(ok, tr, a.sha, repo), jobs_of)
        except Exception as e:  # a hiccup of the API: ask again at the next poll
            res, txt = "wait", "API: %s" % e
        mins = (time.time() - t0) / 60
        print("ci_gate %s (%.0f min): %s" % (a.sha[:12], mins, txt), flush=True)
        if res == "green":
            return 0
        if res == "red":
            print("::error title=CI not green::%s - no image, no release. Fix it (new version) or re-run the CI run, then re-run this workflow." % txt)
            return 1
        if res == "none" and mins >= a.no_run_min:
            print("::error title=no CI run::no CI run for %s after %.0f min - no image, no release" % (a.sha, mins)); return 1
        if mins >= a.timeout_min:
            print("::error title=CI too slow::the CI of %s still runs after %.0f min - re-run this workflow when it is green" % (a.sha, mins)); return 1
        time.sleep(a.poll_s)


if __name__ == "__main__":
    sys.exit(main())
