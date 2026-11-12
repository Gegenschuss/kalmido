#!/usr/bin/env python3
# kalmido-suite: nodata
"""#5787 (decision 12.11.2026): the merge queue gets its own lean check - without a server (CI Lint):
- tests/stages.py: a merge queue entry (merge_group) gets the stage "queue" = the groups of the hard suites
  (tests/hard_suites.txt) + the suites it touches, never the push stage (1442 of 2176 groups for a README change) or the
  full run; the CI basics (ci.yml, stages.py) do not make it a full run either;
- tools/ci_gate.py judge_queue (ci.yml job "Merge queue gate"): judged by SUITE, not by shard - a hard shard red with only
  soft suites red is green (runs 43149840388 / 43127929985 / 43107949743), a hard suite red, a shard without a named suite,
  a cancelled shard, a hard job (e-invoice, ZAP) red, Lint / PR lint / semgrep / plan not green = red; a pull request is
  green on Lint and PR lint alone;
- ci.yml: the job "Merge queue gate" (needs, if, permissions), a pull request runs no test shards (plan skipped), the
  queue stage is accepted by the plan, tests-done stays for push / schedule / workflow_dispatch."""
import importlib.util
import os
import re
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(os.path.join(N, ".."))
sys.path.insert(0, N)
from kt import check, done  # noqa: E402
import stages  # noqa: E402

spec = importlib.util.spec_from_file_location("ci_gate", os.path.join(R, "tools", "ci_gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

# ---- 1. tests/stages.py: the queue stage
repo = stages.Repo(R, os.path.join(N, "run_all.sh"))
hard = stages.hard_groups(repo)
pats = gate.patterns(R)
check(len(hard) > 20 and all(any(gate.hard_suite(s, pats, {}) for g2, s, _ in repo.rows if g2 == g) for g in hard),
      f"the hard groups: every one holds a hard suite ({len(hard)})")
reason, groups = stages.queue(repo, ["README.md"], None, None)
st, _, push_groups, _ = stages.select(repo, ["README.md"])
check(set(hard) <= set(groups) and len(groups) < len(push_groups) and len(groups) < len(repo.first) / 3,
      f"a README change in the queue: the hard groups only, far below the push stage ({len(groups)} vs {len(push_groups)} of {len(repo.first)}) - {reason}")
reason, groups = stages.queue(repo, ["tests/p5787_queue_gate_test.py"], None, None)
check("p5787_queue_gate" in {repo.first[g] for g in groups} and set(hard) <= set(groups), "a changed test file: its own suite + the hard groups")
reason2, groups2 = stages.queue(repo, [".github/workflows/ci.yml", "tests/stages.py", "VERSION"], None, None)
check(set(hard) <= set(groups2) and len(groups2) < len(repo.first) / 3, f"the CI basics / VERSION make no full run in the queue ({len(groups2)} groups)")
# the CI mode: merge_group -> stage=queue and the groups file
head = subprocess.run(["git", "-C", R, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
base = subprocess.run(["git", "-C", R, "rev-parse", "--verify", "-q", "HEAD~1^{commit}"], capture_output=True, text=True).stdout.strip()
# 2.1047.0 (#5841): the CI checks out a shallow clone (no HEAD~1) - a bare "rev-parse HEAD~1" echoed the literal "HEAD~1"
# as the base and stages.py rightly fell back to the full run; without a parent the entry is compared with itself (no change)
base = base or head
if head and base:
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"p5787-groups-{os.getpid()}.txt")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "CI_"))}
    env.update(GITHUB_EVENT_NAME="merge_group", CI_BASE_SHA=base, CI_MESSAGE="#5787: x")
    p = subprocess.run([sys.executable, os.path.join(N, "stages.py"), "--ci", "--groups-out", out], capture_output=True, text=True, env=env, timeout=600)
    lines = open(out, encoding="utf-8").read().split() if os.path.exists(out) else []
    check(p.returncode == 0 and "stage=queue" in p.stdout and {repo.first[g] for g in hard} <= set(lines),
          f"--ci with merge_group: stage=queue, the hard groups in the groups file ({p.stdout[:300]} {p.stderr[-300:]})")
    env["GITHUB_EVENT_NAME"] = "push"
    env["CI_BEFORE"] = base
    p = subprocess.run([sys.executable, os.path.join(N, "stages.py"), "--ci", "--groups-out", out], capture_output=True, text=True, env=env, timeout=600)
    check(p.returncode == 0 and "stage=queue" not in p.stdout, f"a push keeps its stage (push / full): {p.stdout[:120]}")
    try:
        os.remove(out)
    except OSError:
        pass

# ---- 2. tools/ci_gate.py judge_queue
OK = {"result": "success"}
NEEDS = {"plan": OK, "checks": OK, "pr-lint": OK, "semgrep": OK, "einvoice": OK, "zap": OK, "tests": {"result": "failure"}}
GRP = {"p2103_c_api": "p2103_c_api", "p2272_ui": "p2272_ui", "p2272_b_ui": "p2272_ui", "office_api": "office_api", "nogroup_x": None}
GRP = {k: v for k, v in GRP.items() if v}


def job(i, name, concl="success", status="completed"):
    return {"id": i, "name": name, "conclusion": concl, "status": status, "steps": []}


def shard(i, n, concl="success", hart=False):
    return job(i, f"Test suites {i}/{n} queue{' hart' if hart else ''} (API, UI, security)", concl)


def jobs(*shards, extra=()):
    return [job(100, "Lint, i18n, scanners"), job(101, "Pull request lint (task number, changelog part, privacy, one-way steps)"),
            job(102, "semgrep"), job(103, "Shard plan (stage, suite times of the last runs)"), job(104, "E-invoice validators (veraPDF, KoSIT)"),
            job(105, "OWASP ZAP baseline"), job(106, "Image (build once, cache)"), job(107, "Merge queue gate", None, "in_progress"),
            job(110, "Trivy image scan (reporting only)", "skipped"), job(111, "Browser demo + quick add languages", "skipped"),
            job(112, "Test suites (API, UI, security)", "skipped"),
            *shards, *extra]


ok, txt, soft = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 3, "failure", True), shard(2, 3), shard(3, 3)), lambda j: {1: ["p2272_b_ui"]}.get(j["id"], []), pats, GRP)
check(ok and soft == ["p2272_b_ui"], f"a hard shard red with only a soft suite red: green, the soft suite named ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 2, "failure", True), shard(2, 2)), lambda j: {1: ["p2103_c_api"]}.get(j["id"], []), pats, GRP)
check(not ok and "p2103_c_api" in txt, f"a hard suite red: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 2, "failure", True), shard(2, 2)), lambda j: {1: ["office_api"]}.get(j["id"], []), pats, GRP)
check(not ok, f"a hard suite by its name pattern (office): red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 2), shard(2, 2, "failure")), lambda j: {2: ["nogroup_x"]}.get(j["id"], []), pats, GRP)
check(not ok, f"a red suite in no known group = hard: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 2), shard(2, 2, "failure")), lambda j: [], pats, GRP)
check(not ok and "without a named suite" in txt, f"a red shard without a named suite: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 2), shard(2, 2, "failure")), lambda j: None, pats, GRP)
check(not ok and "not readable" in txt, f"the annotations not readable: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": {"result": "cancelled"}}, jobs(shard(1, 2), shard(2, 2, "cancelled")), lambda j: [], pats, GRP)
check(not ok and "not finished" in txt, f"a cancelled shard (its suites untested): red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 2, hart=True), shard(2, 2)), lambda j: [], pats, GRP)
check(ok, f"all green: green ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 1), extra=[job(108, "E-invoice validators (veraPDF, KoSIT)", "failure")]), lambda j: [], pats, GRP)
check(not ok and "hard job" in txt, f"a hard job (e-invoice validators) red: red ({txt})")
ok, txt, soft = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 1), extra=[job(109, "Browser demo + quick add languages", "failure")]), lambda j: [], pats, GRP)
check(ok and soft == ["Browser demo + quick add languages"], f"a soft job red: green, named ({txt})")
# review (Fable 2.1021): a shard skipped / missing, more red suites than GitHub names, the red shard not in the list, a hard job not run
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 2), shard(2, 2, "skipped")), lambda j: [], pats, GRP)
check(not ok, f"a skipped shard (its suites untested): red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 3), shard(3, 3)), lambda j: [], pats, GRP)
check(not ok and "missing" in txt, f"a shard missing from the job list: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 1)), lambda j: [], pats, GRP)
check(not ok, f"tests red, but no red shard in the list: red ({txt})")
ten = ["p2272_b_ui"] * gate.ANN_MAX
ok, txt, _ = gate.judge_queue("merge_group", NEEDS, jobs(shard(1, 1, "failure")), lambda j: ten, pats, GRP)
check(not ok and "maybe more" in txt, f"{gate.ANN_MAX} red suites named (GitHub names at most 10): unknown = red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 1), extra=[job(113, "OWASP ZAP baseline", "skipped")]), lambda j: [], pats, GRP)
check(not ok and "did not run" in txt, f"a hard job skipped: red ({txt})")
for k in ("checks", "pr-lint", "semgrep", "plan", "einvoice", "zap"):
    ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK, k: {"result": "failure"}}, jobs(shard(1, 1)), lambda j: [], pats, GRP)
    check(not ok and k in txt, f"{k} red: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": {"result": "skipped"}}, jobs(), lambda j: [], pats, GRP)
check(not ok, f"no test shard ran in a queue entry: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(), lambda j: [], pats, GRP)
check(not ok, f"no shard in the job list: red ({txt})")
ok, txt, _ = gate.judge_queue("merge_group", {**NEEDS, "tests": OK}, jobs(shard(1, 1)), lambda j: [], [], GRP)
check(not ok, f"no tests/hard_suites.txt: red ({txt})")
PRN = {"checks": OK, "pr-lint": OK, "plan": {"result": "skipped"}, "semgrep": {"result": "skipped"}, "tests": {"result": "skipped"}}
ok, txt, _ = gate.judge_queue("pull_request", PRN, [], lambda j: None, pats, {})
check(ok, f"a pull request: Lint + PR lint green = green, no shards ({txt})")
ok, txt, _ = gate.judge_queue("pull_request", {**PRN, "pr-lint": {"result": "failure"}}, [], lambda j: None, pats, {})
check(not ok, f"a pull request with PR lint red: red ({txt})")
ok, txt, _ = gate.judge_queue("push", NEEDS, [], lambda j: None, pats, {})
check(not ok, f"another event: red ({txt})")
# the release gate does not read a queue run as the full stage
check(gate.stage(["Test suites 1/3 queue hart (API, UI, security)"]) == "?", "ci_gate.stage: a queue run is no full / push stage")
check(gate.base_patterns(R, "HEAD") == [] and gate.base_patterns(R, "0" * 40) == [], "base_patterns: only a commit id, an unknown one = []")

# ---- 3. ci.yml
with open(os.path.join(R, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
    ci = f.read()


def ci_job(name):
    m = re.search(r"^  " + re.escape(name) + r":\n((?:    .*\n|\n)+)", ci, re.M)
    return m.group(1) if m else ""


qg = ci_job("queue-gate")
check("name: Merge queue gate\n" in qg and re.search(r"needs: \[plan, checks, pr-lint, semgrep, einvoice, zap, tests\]", qg)
      and "if: always() && (github.event_name == 'pull_request' || github.event_name == 'merge_group')" in qg,
      "ci.yml: the job Merge queue gate (name fixed, needs, runs for pull requests and queue entries)")
check("QUEUE_BASE_SHA: ${{ github.event.merge_group.base_sha }}" in qg and "fetch-depth: 0" in qg, "ci.yml: the gate reads the hard list of the queue's base too")
check("actions: read" in qg and "checks: read" in qg and "tools/ci_gate.py --queue-gate" in qg and "NEEDS: ${{ toJSON(needs) }}" in qg,
      "ci.yml: the gate reads the jobs and annotations of its run (tools/ci_gate.py --queue-gate)")
check("if: github.event_name != 'pull_request'" in ci_job("plan"), "ci.yml: a pull request runs no plan, so no test shards")
check("needs: plan" in ci_job("tests"), "ci.yml: the shards need the plan (skipped with it)")
td = ci_job("tests-done")
check("if: always() && github.event_name != 'pull_request' && github.event_name != 'merge_group'" in td and re.search(r"needs: tests\n", td),
      "ci.yml: tests-done stays for push / schedule / workflow_dispatch")
pl = ci_job("plan")
check('[ "$stage" = queue ]' in pl and "--only /tmp/push-groups.txt" in pl, "ci.yml: the plan accepts the queue stage and cuts it from its groups")
for j in ("demo", "trivy", "windows-launcher-changes"):
    check("github.event_name != 'merge_group'" in ci_job(j), f"ci.yml: {j} (soft) is not in the merge queue")
for j in ("semgrep", "einvoice", "zap", "image"):
    b = ci_job(j)
    check("github.event_name != 'pull_request'" in b and "merge_group" not in b.split("steps:", 1)[0], f"ci.yml: {j} runs for a queue entry, not for a pull request")
check("if: github.event_name == 'pull_request' || github.event_name == 'merge_group'" in ci_job("pr-lint"), "ci.yml: PR lint as before")

sys.exit(done("p5787_queue_gate"))
