#!/usr/bin/env python3
"""2.309.0 (#3269): the gate of release.yml - the image (:X.Y.Z, :latest) and the GitHub release of a tag come only
after a GREEN FULL run of the workflow "CI" on the tagged commit ("the CI is the only gate", #1315). Self-hosters never
get a red version as "latest".

  python3 tools/ci_gate.py [--sha SHA] [--timeout-min 240] [--poll-s 60] [--no-run-min 20]

Reads the CI runs of the commit (GET /repos/R/actions/workflows/ci.yml/runs?head_sha=SHA, needs `actions: read`) and
the job names of a green run (the shard jobs "Test suites N/M full ..." = the full stage, see ci.yml / tests/stages.py).
Exit 0 = a run of SHA is green and was the full stage; 1 = the CI of SHA is red / cancelled / only the push stage /
no CI run within --no-run-min / still running at --timeout-min. While a run of SHA is queued or running it waits.
A red or cancelled run that is re-run by hand (same run, new attempt) counts again; re-run this workflow afterwards.
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

    def jobs_of(rid):
        return [j.get("name") for j in api("/repos/%s/actions/runs/%s/jobs?per_page=100" % (repo, rid)).get("jobs", [])]

    while True:
        try:
            runs = api("/repos/%s/actions/workflows/ci.yml/runs?head_sha=%s&per_page=50" % (repo, a.sha)).get("workflow_runs", [])
            res, txt = decide(runs, jobs_of)
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
