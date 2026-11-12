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
2.767.0 (#5324): the image follows the same rule as live in the fast lane - a finished FULL run that is
red only in SOFT parts counts as well ("soft green"). Hard = the list tests/hard_suites.txt of the tagged tree (the one list the
CI plan puts on its hard shards "Test suites N/M full hart" and the live train reads; invoices / office, backup, login,
scanners). A red run is soft green only when: it ended as failure (2.940.0, #5600: or cancelled), it was the full stage with at least one hard
shard, every hard shard is green, every red shard names its red suites (annotations "suite X failed" of tests/run_all.sh) and
none of them is hard (by name or by the name of its test group, tools/shards.py groups(); a suite in no group = hard), and no
other hard job is red (name matches a pattern: e-invoice validators, semgrep, ZAP ...; a red step of "Lint ..." only when it is a
scanner). Hard red, only the push stage = no image, as before (2.940.0: "failure" above reads "failure or cancelled").
2.940.0 (#5600): a CANCELLED full run counts like a red one - soft green when every hard shard and hard job ended green and
only soft shards were cut (a newer push cancels the running CI with cancel-in-progress once the fast lane has the version
live; v2.883, v2.897, v2.902 had all hard shards green and got no image). A hard shard or hard job that was cancelled before
it finished is no green one = no image. The soft red parts are printed (step summary) and
--report lists them for the release notes (weekly-release.yml).
  python3 tools/ci_gate.py --sha SHA --report   markdown of the soft red parts of SHA's newest finished full run ("" = green)
#5787 (decision 12.11.2026): the required check of the merge queue, ci.yml job "Merge queue gate":
  python3 tools/ci_gate.py --queue-gate        (env NEEDS = toJSON(needs), GITHUB_EVENT_NAME, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT)
judges the run it runs in, by SUITES (not by shards: a hard shard carries the soft suites of its groups, runs 43149840388,
43127929985, 43107949743 had a red hard shard with only soft suites red): green when Lint and PR lint (a queue entry: + the plan
and semgrep) are green, no hard suite is red (every red shard names its red suites, none hard; a cancelled shard = unknown =
hard) and no hard job (e-invoice validators, ZAP ...) is red. A pull request is green on Lint and PR lint alone (no shards).
Exit 0 green, 1 red; the soft red parts are printed (a task + collective fix, like the soft red parts of the release push).
Env: GITHUB_TOKEN (or GH_TOKEN), GITHUB_REPOSITORY, GITHUB_SHA, GITHUB_API_URL (all set on GitHub Actions)."""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

STAGE_RE = re.compile(r"^Test suites \d+/\d+ (full|push)\b")
SHARD_RE = re.compile(r"^Test suites (\d+)/\d+ (full|push)( hart)?\b")  # #5324: " hart" = a shard of the hard groups (ci.yml, #4557)
SUITE_ANN_RE = re.compile(r"^suite ([A-Za-z0-9_.-]+) failed$")  # tests/run_all.sh: ::error title=suite NAME failed::...
SCANNERS = ("audit", "gitleaks", "secret", "bandit", "semgrep", "trivy")  # a red step of the Lint job is hard only as one of these
# review 2.767.0 (#5324): the steps a scanner needs before it runs (install, the pin / OSV check) - red or not run = hard as well
SCAN_PREP = ("install scanners*", "pinned dependencies*")
# fable 2.940.0 M2 (#5600): a red Lint is soft only when these scanner steps are THERE and green (positive check: a Lint
# cancelled mid-way may list only the steps it began)
LINT_MUST = ("pinned dependencies*", "install scanners*", "bandit*", "pip-audit (image*")
QUEUE_SHARD_RE = re.compile(r"^Test suites (\d+)/\d+ (full|push|queue)( hart)?\b")  # #5787: + the queue stage of a merge queue entry
QUEUE_GATE = "Merge queue gate"  # #5787: the job name of ci.yml - a required check of the ruleset, keep it as it is
SOFT_CONCL = ("failure", "cancelled")  # #5600: the run conclusions judge_soft looks at (cancelled = a newer push cut the run)


def stage(job_names):
    """"full" | "push" | "?" - the test stage of a CI run from its shard job names."""
    seen = {m.group(1) for m in (STAGE_RE.match(n or "") for n in job_names) if m}
    return "full" if "full" in seen else ("push" if "push" in seen else "?")


def decide(runs, jobs_of, soft=None):
    """runs = the CI runs of the commit (GitHub API dicts), jobs_of(run_id) -> job names.
    ("green" | "soft" | "wait" | "red" | "none", text). Green beats everything (one green full run is enough); then (#5324,
    soft(run_id) -> (ok, text) given) a finished run red only in soft parts = "soft" (go); then a run still queued / in
    progress = wait; else red with the reasons."""
    if not runs:
        return "none", "no CI run for this commit yet"
    why = []
    for r in runs:
        if r.get("status") == "completed" and r.get("conclusion") == "success":
            st = stage(jobs_of(r["id"]))
            if st == "full":
                return "green", "CI run %s is green (full stage)" % r["id"]
            why.append("run %s green, but stage %s (a release needs the full stage)" % (r["id"], st))
    if soft is not None:  # #5324: a finished full run red only in soft parts = go, like live in the fast lane
        for r in runs:  # #5600: a cancelled run as well (its cancelled hard parts are red in judge_soft)
            if r.get("status") == "completed" and r.get("conclusion") in SOFT_CONCL:
                ok, txt = soft(r["id"])
                if ok:
                    return "soft", "CI run %s is red only in soft parts (full stage): %s" % (r["id"], txt)
                why.append("run %s failure: %s" % (r["id"], txt))
    busy = [r for r in runs if r.get("status") != "completed"]
    if busy:
        return "wait", "CI run %s %s" % (busy[0]["id"], busy[0].get("status"))
    for r in runs:
        if r.get("conclusion") != "success" and not (soft is not None and r.get("conclusion") in SOFT_CONCL):
            why.append("run %s %s" % (r["id"], r.get("conclusion")))
    return "red", "; ".join(why)


# ---------------------------------------------------------------- 2.767.0 (#5324): soft red = go (same rule as live in the fast lane)
def patterns(tree):
    """The hard patterns (fnmatch, lower case) of tests/hard_suites.txt in TREE; [] = no list (then nothing is soft)."""
    try:
        with open(os.path.join(tree, "tests", "hard_suites.txt"), encoding="utf-8") as f:
            return [ln.strip().lower() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except (OSError, UnicodeDecodeError):
        return []


_GROUPS_CODE = ("import importlib.util, json, sys\n"
                "s = importlib.util.spec_from_file_location('shards', sys.argv[1] + '/tools/shards.py'); m = importlib.util.module_from_spec(s)\n"
                "s.loader.exec_module(m)\n"
                "print(json.dumps({x: g[0] for g in m.groups(sys.argv[1] + '/tests/run_all.sh') for x in g[1]}))")


def groups(tree):
    """{suite: first suite of its test group} of TREE (tools/shards.py groups(), as the CI plan and the live train); None = unreadable."""
    try:
        p = subprocess.run([sys.executable, "-I", "-c", _GROUPS_CODE, tree], capture_output=True, text=True, timeout=120)
        d = json.loads(p.stdout or "null") if p.returncode == 0 else None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d else None


def hard_suite(name, pats, grp):
    """Is a red suite hard: its name or the name of its test group matches a pattern; a suite in no known group = hard."""
    low = (name or "").lower()
    if not low or any(fnmatch.fnmatch(low, m) for m in pats):
        return True
    g = (grp or {}).get(name)
    return g is None or any(fnmatch.fnmatch(str(g).lower(), m) for m in pats)


def hard_job(job, pats):
    """A red job that is no shard: the summing job "Test suites (...)" and "(informational)" never; "Lint ..." only with a red
    scanner step (no step known = hard); any other job when its name matches a pattern (e-invoice, semgrep, ZAP ...)."""
    low = (job.get("name") or "").strip().lower()
    if low.startswith("test suites") or "(informational)" in low:
        return False
    if low.startswith("lint"):
        steps = job.get("steps") or []
        red = [(x.get("name") or "").lower() for x in steps if x.get("conclusion") not in ("success", "skipped", None)]
        scan = [m for m in pats if m.strip("*") in SCANNERS] + list(SCAN_PREP)
        # review (#5324): a scanner (or its install / pin check) that is red OR did not run (skipped after an earlier red step) = hard
        miss = [n for n in ((x.get("name") or "").lower() for x in steps if x.get("conclusion") != "success")
                if "(informational)" not in n and any(fnmatch.fnmatch(n, m) for m in scan)]
        ok = [(x.get("name") or "").lower() for x in steps if x.get("conclusion") == "success"]
        lack = [m for m in LINT_MUST if not any(fnmatch.fnmatch(n, m) for n in ok)]  # fable 2.940.0 M2 (#5600)
        return not red or bool(miss) or bool(lack)
    return any(fnmatch.fnmatch(low, m) for m in pats)


def judge_soft(jobs, suites_of, pats, grp):
    """jobs = the jobs of a finished red run (dicts: id, name, status, conclusion, steps); suites_of(job) -> the names of its red
    suites (None = not readable). -> (soft?, text, {"suites": [...], "jobs": [...], "cut": [...]}) - see the head comment."""
    info = {"suites": [], "jobs": [], "cut": []}
    if not pats:
        return False, "no tests/hard_suites.txt in the tagged tree (unknown = hard)", info
    shards = [(SHARD_RE.match(j.get("name") or ""), j) for j in jobs]
    shards = [(m, j) for m, j in shards if m]
    if not shards or any(m.group(2) != "full" for m, _ in shards):
        return False, "not the full stage", info
    hard = [j for m, j in shards if m.group(3)]
    want = {int(m.group(1)) for m, _ in shards}
    tot = max((int(re.match(r"^Test suites \d+/(\d+)", j["name"]).group(1)) for _, j in shards), default=0)
    if want != set(range(1, tot + 1)):  # review (#5324): a shard missing from the list (paging, a matrix job that never ran) = unknown
        return False, "shards missing from the job list (%d of %d)" % (len(want), tot), info
    if not hard:
        return False, "no hard shard in the plan (unknown = hard)", info
    for j in hard:
        if j.get("conclusion") != "success":
            return False, "hard shard red: %s (%s)" % (j.get("name"), j.get("conclusion")), info
    for m, j in shards:
        c = j.get("conclusion")
        if m.group(3) or c in ("success", "skipped"):
            continue
        su = suites_of(j)
        if su is None:
            return False, "the red suites of %s are not readable (unknown = hard)" % j.get("name"), info
        if c == "failure" and not su:
            return False, "%s red without a named suite (unknown = hard)" % j.get("name"), info
        if c != "failure":  # cancelled (time limit, #5600: or a newer push) / timed out: its other suites stay untested (the train counts it soft too)
            info["cut"].append("%s (%s)" % (j.get("name"), c))
        for s in su:
            if hard_suite(s, pats, grp):
                return False, "hard suite red: %s" % s, info
            info["suites"].append(s)
    for j in jobs:
        if SHARD_RE.match(j.get("name") or "") or j.get("conclusion") == "success":
            continue
        if j.get("conclusion") is None or j.get("status") not in (None, "completed"):
            # fable 2.940.0 M1 (#5600): a job without a result in a finished (cancelled) run = unknown = hard
            return False, "job without a result: %s (%s)" % (j.get("name"), j.get("status")), info
        if j.get("conclusion") == "skipped":  # review (#5324): a hard job that did not run is no green one
            if hard_job(j, pats) or (j.get("name") or "").lower().startswith("lint"):  # fable 2.940.0 M1: Lint too
                return False, "hard job did not run: %s" % j.get("name"), info
            continue
        if hard_job(j, pats):
            return False, "hard job red: %s (%s)" % (j.get("name"), j.get("conclusion")), info
        if not (j.get("name") or "").startswith("Test suites"):
            info["jobs"].append(j.get("name"))
    info["suites"] = sorted(set(info["suites"]))
    parts = (["soft suites: " + ", ".join(info["suites"])] if info["suites"] else []) + (["soft jobs: " + ", ".join(info["jobs"])] if info["jobs"] else []) \
        + (["shards cut before the end: " + ", ".join(info["cut"])] if info["cut"] else [])
    return True, "; ".join(parts) or "no red part named", info


def judge_queue(event, needs, jobs, suites_of, pats, grp):
    """#5787: the merge queue gate (see the head comment). event = GITHUB_EVENT_NAME, needs = {job id: {"result": ...}} of the
    gate job, jobs = the jobs of the own run (dicts: id, name, status, conclusion, steps), suites_of(job) -> its red suites
    (None = not readable). -> (green?, text, soft red parts)."""
    must = ["checks", "pr-lint"] + (["plan", "semgrep"] if event == "merge_group" else [])
    for k in must:
        res = (needs.get(k) or {}).get("result")
        if res != "success":
            return False, "%s: %s" % (k, res or "missing"), []
    if event == "pull_request":
        return True, "Lint and PR lint green (a pull request runs no test shards)", []
    if event != "merge_group":
        return False, "not a pull request / merge queue entry: %s" % (event or "?"), []
    if not pats:
        return False, "no tests/hard_suites.txt (unknown = hard)", []
    tres = (needs.get("tests") or {}).get("result")
    if tres not in ("success", "failure", "cancelled"):
        return False, "test shards: %s (none ran)" % (tres or "missing"), []
    shards = [j for j in jobs if QUEUE_SHARD_RE.match(j.get("name") or "")]
    if not shards:
        return False, "no test shard in the job list of the run (unknown = hard)", []
    soft = []
    for j in shards:
        c = j.get("conclusion")
        if c in ("success", "skipped"):
            continue
        if c != "failure":  # cancelled / timed out / not finished: its suites are untested = unknown = hard
            return False, "shard not finished: %s (%s)" % (j.get("name"), c or j.get("status")), soft
        su = suites_of(j)
        if su is None:
            return False, "the red suites of %s are not readable (unknown = hard)" % j.get("name"), soft
        if not su:
            return False, "%s red without a named suite (unknown = hard)" % j.get("name"), soft
        for x in su:
            if hard_suite(x, pats, grp):
                return False, "hard suite red: %s (%s)" % (x, j.get("name")), soft
            soft.append(x)
    for j in jobs:
        name = j.get("name") or ""
        if name == QUEUE_GATE or QUEUE_SHARD_RE.match(name) or j.get("conclusion") in ("success", "skipped", "neutral"):
            continue
        if j.get("status") not in (None, "completed") or j.get("conclusion") is None:
            if hard_job(j, pats) and not name.lower().startswith("lint"):
                return False, "hard job not finished: %s (%s)" % (name, j.get("status")), soft
            continue
        if hard_job(j, pats):
            return False, "hard job red: %s (%s)" % (name, j.get("conclusion")), soft
        soft.append(name)
    soft = sorted(set(soft))
    return True, ("soft red (a task, no hold): " + ", ".join(soft)) if soft else "Lint, PR lint, semgrep and every test shard green", soft


def report_md(version, run_id, info, url=""):
    """The section for the release notes: the soft red parts of the version (empty info = nothing)."""
    if not (info.get("suites") or info.get("jobs") or info.get("cut")):
        return ""
    out = ["", "### Known test failures in %s (outside the hard areas)" % version, "",
           "The full CI of this version was red only in suites outside invoices / office, backup / restore, sign-in and the "
           "security scanners; those were all green (same rule as the live update)." + (" CI run: %s" % url if url else ""), ""]
    out += ["- suite `%s`" % s for s in info.get("suites") or []]
    out += ["- job: %s" % j for j in info.get("jobs") or []]
    out += ["- cut before the end (time limit or a newer push, suites untested): %s" % c for c in info.get("cut") or []]
    return "\n".join(out) + "\n"


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
    if res in ("green", "soft"):
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


def queue_gate(tree):
    """#5787: ci.yml job "Merge queue gate" - the jobs of the own run (this attempt) and their annotations, judge_queue."""
    repo, rid = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", "")
    att = os.environ.get("GITHUB_RUN_ATTEMPT", "") or "1"
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        needs = json.loads(os.environ.get("NEEDS") or "{}")
    except ValueError:
        needs = None
    if not isinstance(needs, dict):
        print("queue gate: NEEDS is no JSON object (unknown = red)")
        return 1
    jobs = []
    if ev == "merge_group":
        if not (repo and rid):
            print("queue gate: GITHUB_REPOSITORY / GITHUB_RUN_ID missing")
            return 1
        try:
            for page in range(1, 6):
                d = api("/repos/%s/actions/runs/%s/attempts/%s/jobs?per_page=100&page=%d" % (repo, rid, att, page))
                more = d.get("jobs", [])
                jobs += more
                if not more or len(jobs) >= int(d.get("total_count") or 0):
                    break
        except Exception as e:  # noqa: BLE001 - no job list = unknown = red
            print("queue gate: no job list of the run: %s" % e)
            return 1

    def suites_of(job):
        try:
            anns = api("/repos/%s/check-runs/%s/annotations?per_page=100" % (repo, job["id"]))
        except Exception:  # noqa: BLE001 - not readable = unknown = hard
            return None
        titles = [(x.get("title") or "").strip() for x in anns or []]
        if any(t.startswith("suite ") and not SUITE_ANN_RE.match(t) for t in titles):
            return None
        return [m.group(1) for m in map(SUITE_ANN_RE.match, titles) if m]

    ok, txt, soft = judge_queue(ev, needs, jobs, suites_of, patterns(tree), groups(tree) if ev == "merge_group" else {})
    print("queue gate (%s): %s - %s" % (ev, "green" if ok else "red", txt), flush=True)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write("### Merge queue gate: %s\n\n%s\n" % ("green" if ok else "red", txt))
            if soft:
                f.write("\nSoft red (they hold nothing; a task + collective fix): %s\n" % ", ".join(soft))
    if soft and ok:
        print("::warning title=soft red in the queue entry::%s" % ", ".join(soft)[:900])
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    ap.add_argument("--timeout-min", type=float, default=240)
    ap.add_argument("--poll-s", type=float, default=60)
    ap.add_argument("--no-run-min", type=float, default=20)
    ap.add_argument("--tree", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
                    help="#5324: checkout of the TAGGED commit (its tests/hard_suites.txt and test groups); default: this checkout")
    ap.add_argument("--report", metavar="VERSION", help="#5324: print the release-notes section of the soft red parts and exit")
    ap.add_argument("--queue-gate", action="store_true", help="#5787: judge the own run (ci.yml job \"Merge queue gate\")")
    a = ap.parse_args()
    if a.queue_gate:
        return queue_gate(a.tree)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (a.sha and repo):
        print("ci_gate: GITHUB_SHA / GITHUB_REPOSITORY missing"); return 1
    t0 = time.time()
    tree = [None]
    cache = {}
    hard = {}

    def tree_of():  # the tree of the tagged commit (from its own run, else the git commit), asked once
        if tree[0] is None:
            tree[0] = (api("/repos/%s/git/commits/%s" % (repo, a.sha)).get("tree") or {}).get("sha") or ""
        return tree[0]

    def jobs_full(rid):
        if rid not in cache:
            d = api("/repos/%s/actions/runs/%s/jobs?per_page=100" % (repo, rid))
            js = d.get("jobs", [])
            if int(d.get("total_count") or len(js)) > len(js):  # review (#5324): more than one page - read the rest
                for page in range(2, 6):
                    more = api("/repos/%s/actions/runs/%s/jobs?per_page=100&page=%d" % (repo, rid, page)).get("jobs", [])
                    js += more
                    if not more or len(js) >= int(d.get("total_count") or 0):
                        break
            cache[rid] = js
        return cache[rid]

    def jobs_of(rid):
        return [j.get("name") for j in jobs_full(rid)]

    def suites_of(job):  # #5324: the red suites of a shard from its annotations (tests/run_all.sh "suite X failed")
        try:
            anns = api("/repos/%s/check-runs/%s/annotations?per_page=100" % (repo, job["id"]))
        except Exception:  # noqa: BLE001 - not readable = unknown = hard
            return None
        titles = [(x.get("title") or "").strip() for x in anns or []]
        if any(t.startswith("suite ") and not SUITE_ANN_RE.match(t) for t in titles):
            return None  # review (#5324): a suite title that does not parse = not readable = hard
        return [m.group(1) for m in map(SUITE_ANN_RE.match, titles) if m]

    def judge(rid):
        if "pats" not in hard:
            hard["pats"], hard["grp"] = patterns(a.tree), groups(a.tree)
        ok, txt, info = judge_soft(jobs_full(rid), suites_of, hard["pats"], hard["grp"])
        hard[rid] = info
        return ok, txt

    def soft(rid):
        ok, txt = judge(rid)
        if ok:
            hard["ok"] = rid
        return ok, txt

    if a.report:  # #5324: the soft red parts for the release notes (nothing when a run of SHA is green or none is soft)
        runs = api("/repos/%s/actions/workflows/ci.yml/runs?head_sha=%s&per_page=50" % (repo, a.sha)).get("workflow_runs", [])
        res, _ = decide(runs, jobs_of, soft)
        if res == "soft":
            rid = hard["ok"]
            sys.stdout.write(report_md(a.report, rid, hard[rid], "https://github.com/%s/actions/runs/%s" % (repo, rid)))
        return 0

    while True:
        cache.clear()  # a re-run attempt of a run changes its jobs: ask again each poll
        try:
            runs = api("/repos/%s/actions/workflows/ci.yml/runs?head_sha=%s&per_page=50" % (repo, a.sha)).get("workflow_runs", [])
            res, txt = decide(runs, jobs_of, soft)
            if res not in ("green", "soft"):  # #4905: a green full run of the same files on another commit
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
        if res == "soft":  # #5324: go, and say so where the maintainer looks
            print("::warning title=CI red only in soft suites::%s - image and release go ahead (same rule as the live update, #5324)" % txt)
            summ = os.environ.get("GITHUB_STEP_SUMMARY")
            if summ:
                with open(summ, "a", encoding="utf-8") as f:
                    f.write(report_md(a.sha[:12], hard["ok"], hard[hard["ok"]]) or "CI red only in soft parts\n")
            return 0
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
