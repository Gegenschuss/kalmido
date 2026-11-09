#!/usr/bin/env python3
"""2.309.0 (#3269): release.yml builds the image (:X.Y.Z) and the GitHub release of a tag only after a green
FULL run of the workflow CI on the tagged commit (tools/ci_gate.py). Without a server (CI Lint):
- release.yml has the job ci-gate (actions: read, runs tools/ci_gate.py on the tagged commit) and the job release
  needs it;
- tools/ci_gate.py: green full run = go; a run still queued / running = wait; red, cancelled, only the push stage = stop;
  one green full run beside a red one (re-run, nightly run of the same commit) = go; the loop in main() waits on the
  stubbed API state, not on a fixed time;
- 2.595.0 (#4905): a green full run of ANOTHER commit with the same tree counts (same files), one of another tree or only
  the push stage does not; release.yml can be re-run on a tag by workflow_dispatch and skips any other ref.
- 2.767.0 (#5324): a finished full run red only in soft parts = go ("soft"), the same rule as live in the fast lane; hard red
  (a hard shard, a hard suite by name or group, a suite in no group, a red shard without a named suite, a hard job, a scanner
  step of Lint), cancelled or the push stage = still no image; the soft red parts go into the notes of the weekly release."""
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

# 2.610.0 (#4926): a start by hand on an existing tag (the live train, after a soft red full CI was made green) - same gate
head = rel.split("\njobs:\n", 1)[0]
check("workflow_dispatch:" in head and re.search(r"^      tag:\n(?:        .*\n)*?        required: false", head, re.M) is not None,
      "#4926: release.yml can be started by hand with the input tag (optional, #4905 on a tag ref needs none)")
check(re.search(r"^  push:\n    tags: \[\"v\*\.\*\.\*\"\]", head, re.M) is not None, "#4926: a pushed tag still starts it")
runs = re.findall(r"^\s+run: [|>]?\n((?:\s{10,}.*\n)+)|^\s+run: (.+)$", jobs, re.M)
check(all("inputs." not in (a or b) for a, b in runs), "#4926: the input reaches no shell line as an expression, only as env")
check("IN_TAG: ${{ inputs.tag }}" in gtxt and "grep -Eq '^v[0-9]+" in gtxt, "#4926: ci-gate checks the input is vX.Y.Z")
check("refs/tags/$tag^{commit}" in gtxt and 'TAG_SHA: ${{ steps.t.outputs.sha }}' in gtxt,
      "#4926: the gate waits for the green full CI of the TAG's commit, not of main")
check("ref: ${{ needs.ci-gate.outputs.sha }}" in rtxt and "TAG: ${{ needs.ci-gate.outputs.tag }}" in rtxt,
      "#4926: the image is built from the tag's commit and its version comes from the tag")
check("GITHUB_REF_NAME" not in rel.split("  release:\n", 1)[1], "#4926: release and publish no longer read the ref of the start")
check("if: startsWith(github.ref, 'refs/tags/v') || inputs.tag != ''" in gtxt and '[ -n "$IN_TAG" ]' in gtxt,
      "#4905 + #4926: a dispatch runs on a tag ref or with the input tag, otherwise it is skipped")

# ------------------------------------------------------------------ 2.767.0 (#5324): soft red = go (same rule as live)
PATS = ["*invoice*", "*restore*", "*login*", "*bandit*", "*audit*", "*zap*", "*owasp*"]
GRP = {"ux1_ui": "ux1_ui", "pg_prepare": "pg_layer", "p9_ui": "p9_invoice_group", "p1_invoice_ui": "p1_invoice_ui"}


def job(i, name, conclusion="success", steps=None):
    return {"id": i, "name": name, "status": "completed", "conclusion": conclusion, "steps": steps or []}


def base_jobs(*extra):
    return [job(1, "Shard plan (stage, suite times of the last runs)"), job(2, "Test suites 1/4 full hart (API, UI, security)"),
            job(3, "Test suites 2/4 full hart (API, UI, security)"), job(4, "Test suites 3/4 full (API, UI, security)"),
            job(5, "Test suites 4/4 full (API, UI, security)"), job(6, "Lint, i18n, scanners")] + list(extra)


def red(jobs, nr, conclusion="failure"):
    return [dict(j, conclusion=conclusion) if j["id"] == nr else j for j in jobs]


def suites(m):
    return lambda j: m.get(j["id"], [])


soft_case = red(base_jobs(job(9, "Test suites (API, UI, security)", "failure")), 4)
ok, txt, info = gate.judge_soft(soft_case, suites({4: ["ux1_ui", "pg_prepare"]}), PATS, GRP)
check(ok and info["suites"] == ["pg_prepare", "ux1_ui"] and "ux1_ui" in txt, "#5324: hard shards green, red soft suites only = soft go (%s, %s)" % (ok, txt))
ok, txt, _ = gate.judge_soft(red(base_jobs(), 2), suites({}), PATS, GRP)
check(not ok and "hard shard" in txt, "#5324: a red hard shard = no image (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 3, "cancelled"), suites({}), PATS, GRP)
check(not ok and "hard shard" in txt, "#5324: a hard shard cut at its time limit = no image (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({4: ["p1_invoice_ui"]}), PATS, GRP)
check(not ok and "p1_invoice_ui" in txt, "#5324: a red suite whose NAME is hard (on a soft shard) = no image (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({4: ["p9_ui"]}), PATS, GRP)
check(not ok and "p9_ui" in txt, "#5324: a red suite whose test GROUP is hard = no image (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({4: ["unknown_ui"]}), PATS, GRP)
check(not ok, "#5324: a red suite in no known group = hard (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({4: ["ux1_ui"]}), PATS, None)
check(not ok, "#5324: test groups not readable = unknown = hard (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({}), PATS, GRP)
check(not ok and "without a named suite" in txt, "#5324: a red shard without a named suite = hard (%s)" % txt)
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), lambda j: None, PATS, GRP)
check(not ok and "not readable" in txt, "#5324: annotations not readable = hard (%s)" % txt)
ok, txt, info = gate.judge_soft(red(base_jobs(), 5, "timed_out"), suites({}), PATS, GRP)
check(ok and info["cut"], "#5324: a SOFT shard at its time limit = soft, named in the notes (%s, %s)" % (ok, info))
ok, txt, _ = gate.judge_soft(red(base_jobs(), 4), suites({4: ["ux1_ui"]}), [], GRP)
check(not ok and "hard_suites.txt" in txt, "#5324: no hard list in the tree = nothing is soft (%s)" % txt)
nohard = [dict(j, name=j["name"].replace(" hart", "")) for j in base_jobs()]
ok, txt, _ = gate.judge_soft(red(nohard, 4), suites({4: ["ux1_ui"]}), PATS, GRP)
check(not ok and "no hard shard" in txt, "#5324: a plan without hard shards = unknown = hard (%s)" % txt)
pushj = [dict(j, name=j["name"].replace(" full", " push")) for j in base_jobs()]
ok, txt, _ = gate.judge_soft(red(pushj, 4), suites({4: ["ux1_ui"]}), PATS, GRP)
check(not ok and "full stage" in txt, "#5324: the push stage = no image (%s)" % txt)
ok, txt, info = gate.judge_soft(base_jobs(job(7, "Browser demo + quick add languages", "failure")), suites({}), PATS, GRP)
check(ok and info["jobs"] == ["Browser demo + quick add languages"], "#5324: a red soft job = soft, named (%s)" % txt)
for nm in ("E-invoice validators (veraPDF, KoSIT)", "OWASP ZAP baseline"):
    ok, txt, _ = gate.judge_soft(base_jobs(job(7, nm, "failure")), suites({}), PATS + ["*einvoice*", "e-invoice*"], GRP)
    check(not ok and "hard job" in txt, "#5324: a red hard job (%s) = no image (%s)" % (nm, txt))
def lint(st):
    return [job(6, "Lint, i18n, scanners", "failure", [{"name": "Set up job", "conclusion": "success"}, {"name": st, "conclusion": "failure"}])]


ok, txt, _ = gate.judge_soft([j for j in base_jobs() if j["id"] != 6] + lint("ESLint of the client"), suites({}), PATS, GRP)
check(ok, "#5324: a red Lint step that is no scanner = soft (%s)" % txt)
ok, txt, _ = gate.judge_soft([j for j in base_jobs() if j["id"] != 6] + lint("bandit (fails on high severity only)"), suites({}), PATS, GRP)
check(not ok and "Lint" in txt, "#5324: a red scanner step of Lint (bandit) = no image (%s)" % txt)
ok, txt, _ = gate.judge_soft([j for j in base_jobs() if j["id"] != 6] + [job(6, "Lint, i18n, scanners", "failure")], suites({}), PATS, GRP)
check(not ok, "#5324: a red Lint without a known step = hard (%s)" % txt)

# review 2.767.0 (#5324): a scanner that did not run, a hard job skipped, a shard missing from the list, an unparsable title = hard
lint2 = [job(6, "Lint, i18n, scanners", "failure", [{"name": "Install scanners", "conclusion": "failure"},
                                                    {"name": "bandit (fails on high severity only)", "conclusion": "skipped"}])]
ok, txt, _ = gate.judge_soft([j for j in base_jobs() if j["id"] != 6] + lint2, suites({}), PATS, GRP)
check(not ok, "#5324 review: Install scanners red, bandit skipped = hard (%s)" % txt)
lint3 = [job(6, "Lint, i18n, scanners", "failure", [{"name": "ESLint of the client", "conclusion": "failure"},
                                                    {"name": "pip-audit (image and embedding service)", "conclusion": "skipped"}])]
ok, txt, _ = gate.judge_soft([j for j in base_jobs() if j["id"] != 6] + lint3, suites({}), PATS, GRP)
check(not ok, "#5324 review: a scanner skipped after a red ESLint = hard (it never ran) (%s)" % txt)
ok, txt, _ = gate.judge_soft(base_jobs(job(7, "OWASP ZAP baseline", "skipped")), suites({}), PATS, GRP)
check(not ok and "did not run" in txt, "#5324 review: a hard job that was skipped = hard (%s)" % txt)
ok, txt, _ = gate.judge_soft([j for j in red(base_jobs(), 4) if j["id"] != 2], suites({4: ["ux1_ui"]}), PATS, GRP)
check(not ok and "missing" in txt, "#5324 review: a shard missing from the job list = hard (%s)" % txt)

res, txt = gate.decide([run(1, conclusion="failure")], jobs_of({}), soft=lambda rid: (True, "soft suites: ux1_ui"))
check(res == "soft" and "ux1_ui" in txt, "#5324: decide - a finished run red only in soft parts = soft (%s)" % res)
res, txt = gate.decide([run(1, conclusion="failure")], jobs_of({}), soft=lambda rid: (False, "hard suite red: p4286_restore"))
check(res == "red" and "p4286_restore" in txt, "#5324: decide - hard red stays red with the reason (%s, %s)" % (res, txt))
res, _ = gate.decide([run(1, conclusion="cancelled")], jobs_of({}), soft=lambda rid: (True, "x"))
check(res == "red", "#5324: decide - a cancelled run is never soft (%s)" % res)
res, _ = gate.decide([run(1, conclusion="failure"), run(2, "in_progress")], jobs_of({}), soft=lambda rid: (True, "x"))
check(res == "soft", "#5324: decide - a soft run does not wait for another one (%s)" % res)
check(gate.decide_tree("soft", "x", [], jobs_of({}))[0] == "soft", "#5324: decide_tree keeps soft")

# main(): the stubbed API with jobs (conclusions, steps) and annotations; groups / hard list stubbed like the tagged tree
import tempfile  # noqa: E402
td = tempfile.mkdtemp()
os.makedirs(os.path.join(td, "tests"))
with open(os.path.join(td, "tests", "hard_suites.txt"), "w") as f:
    f.write("# hard\n" + "\n".join(PATS) + "\n")
check(gate.patterns(td) == PATS and gate.patterns(os.path.join(td, "nope")) == [], "#5324: patterns() reads tests/hard_suites.txt of the tree")
real = gate.groups(R)
check(bool(real) and gate.hard_suite("ux1_ui", gate.patterns(R), real) is False and gate.hard_suite("p4286_restore", gate.patterns(R), real) is True,
      "#5324: the real tree - ux1_ui soft, p4286_restore hard (tests/hard_suites.txt + tools/shards.py groups)")
old_groups = gate.groups
gate.groups = lambda tree: GRP


def fake_api2(runs, jobs, anns):
    def api(path):
        if "/annotations" in path:
            jid = int(path.split("/check-runs/")[1].split("/")[0])
            return [{"title": "suite %s failed" % s, "message": "FAIL: x"} for s in anns.get(jid, [])] + [{"title": "Process completed with exit code 1."}]
        if "/jobs" in path:
            return {"jobs": jobs}
        if "/git/commits/" in path:
            return {"tree": {"sha": ""}}
        if "status=success" in path:
            return {"workflow_runs": []}
        return {"workflow_runs": runs}
    return api


def main2(runs, jobs, anns, *extra):
    gate.api = fake_api2(runs, jobs, anns)
    old = sys.argv, dict(os.environ)
    sys.argv = ["ci_gate.py", "--sha", "abc123", "--poll-s", "0", "--no-run-min", "0", "--tree", td] + list(extra)
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = gate.main()
        return rc, buf.getvalue()
    finally:
        sys.argv = old[0]
        os.environ.clear()
        os.environ.update(old[1])


rc, out = main2([run(7, conclusion="failure")], soft_case, {4: ["ux1_ui"]})
check(rc == 0 and "soft" in out, "#5324: main - soft red full run = image goes ahead (rc %s)" % rc)
rc, out = main2([run(7, conclusion="failure")], red(base_jobs(), 4), {4: ["p1_invoice_ui"]})
check(rc == 1 and "p1_invoice_ui" in out, "#5324: main - hard red suite = no image (rc %s)" % rc)
rc, out = main2([run(7, conclusion="failure")], soft_case, {4: ["ux1_ui", "pg_prepare"]}, "--report", "9.9.9")
check(rc == 0 and "### Known test failures in 9.9.9" in out and "- suite `ux1_ui`" in out and "- suite `pg_prepare`" in out
      and "actions/runs/7" in out and "FAIL" not in out, "#5324: --report - the notes section names the soft red suites, no log text (%s)" % out[:200])
_orig_fake = fake_api2


def fake_odd(runs, jobs, anns):
    inner = _orig_fake(runs, jobs, anns)
    return lambda path: [{"title": "suite odd name failed"}] if "/annotations" in path else inner(path)


fake_api2 = fake_odd
rc, out = main2([run(7, conclusion="failure")], soft_case, {})
check(rc == 1 and "not readable" in out, "#5324 review: an annotation title that does not parse = not readable = hard (rc %s)" % rc)
fake_api2 = _orig_fake
rc, out = main2([run(7)], base_jobs(), {}, "--report", "9.9.9")
check(rc == 0 and out == "", "#5324: --report - green CI = no section")
gate.groups = old_groups

check("checks: read" in gtxt and '--tree "$RUNNER_TEMP/tagtree"' in gtxt and "git worktree add" in gtxt,
      "#5324: ci-gate reads the annotations (checks: read) and judges with the hard list of the TAGGED tree")
with open(os.path.join(R, ".github", "workflows", "weekly-release.yml"), encoding="utf-8") as f:
    wk = f.read()
pk = re.search(r"^  pick:\n((?:    .*\n|\n)+)", wk.split("\njobs:\n", 1)[1], re.M)
pk = pk.group(1) if pk else ""
check("could not be read" in pk, "#5324 review: notes say so when the soft red list is not readable")
check("tools/ci_gate.py --sha" in pk and "--report" in pk and "checks: read" in pk and "actions: read" in pk and "write" not in pk,
      "#5324: the weekly release names the soft red suites of its version (read rights only in pick)")

print("release_ci_gate: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
