#!/usr/bin/env python3
"""2.285.0 (#2830): the fast lane of the live train - an urgent fix goes live as a patch on the last live tag, from a
branch hotfix/X.Y.Z beside main. Without a server (CI Lint):
- ci.yml runs on pushes to hotfix/** (besides main) and its concurrency group hangs on github.ref (a hotfix push and a
  push on main never cancel each other); the suite times are still read from main only;
- tests/stages.py gives a push on a hotfix branch the full stage (a push on main keeps the push stage);
- 2.513.0 (#4354): "a tag below the newest keeps latest where it is" now lives in promote.yml (tests/p2513_promote_test.py);
- #6063: a push on main the merge queue made (a merge_group run for the same commit) = stage "none", no test shards."""
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


# #6061 (14.11.2026): the concurrency group is evaluated like GitHub does (&&, || return a value; contains() ignores case):
# the train's release push gets a group per run (a later queue merge on main never cancels its full run), every other
# push on main shares ci-refs/heads/main (they replace each other), schedule / workflow_dispatch keep their own group.
class _Ctx(dict):
    __getattr__ = dict.get


def ci_group(event, ref="refs/heads/main", msg="", run_id="7"):
    g = re.search(r"^concurrency:\n  group: \"\$\{\{ (.*) \}\}\"$", ci, re.M)
    if not g:
        return None
    expr = g.group(1).replace("&&", " and ").replace("||", " or ")
    github = _Ctx(event_name=event, ref=ref, run_id=run_id, event=_Ctx(head_commit=_Ctx(message=msg) if event == "push" else None))
    env = {"github": github, "format": lambda f, *a: f.format(*a),
           "contains": lambda h, n: bool(h) and str(n).lower() in str(h).lower()}
    return eval(expr, {"__builtins__": {}}, env)  # the workflow file of this repo, not foreign input


zug = "2.1131.0: Live-Zug (Paket 2.1118.0, Paket 2.1120, CI-Fix)"
check(ci_group("push", msg=zug, run_id="41") == "ci-zug-41", "the train's release push has its own group per run (%s)" % ci_group("push", msg=zug, run_id="41"))
check(ci_group("push", msg=zug, run_id="41") != ci_group("push", msg="Merge pull request #19 (merge queue)", run_id="42"),
      "a queue merge on main never lands in the group of the train's run (no cancel)")
check(ci_group("push", msg="#1: fix") == ci_group("push", msg="Merge origin/main into main (merge queue)") == "ci-refs/heads/main",
      "other pushes on main share one group (they replace each other)")
check(ci_group("push", msg="Merge zug/2.1131.0 back into main (#3507: Push v2.1131.0)") == "ci-refs/heads/main",
      "the merge back of the train's branch is an ordinary push")
check(ci_group("push", ref="refs/heads/hotfix/2.1.1", msg="x") == "ci-refs/heads/hotfix/2.1.1", "hotfix pushes keep their ref group")
check(ci_group("schedule", run_id="9") == "ci-schedule-9" and ci_group("workflow_dispatch", run_id="9") == "ci-workflow_dispatch-9",
      "nightly and by-hand runs keep their own group per run")
check(ci_group("pull_request", ref="refs/pull/3/merge") == "ci-refs/pull/3/merge", "pull requests keep their ref group")
check(re.search(r"^  cancel-in-progress: true$", ci, re.M) is not None, "cancel-in-progress stays on (pushes on main replace each other)")
check("--branch hotfix" not in ci, "no suite times from hotfix branches")


def ci_base(env):
    keep = {k: os.environ.get(k) for k in ("GITHUB_EVENT_NAME", "GITHUB_REF", "CI_BEFORE", "CI_MESSAGE", "CI_INPUT_STAGE", "CI_QUEUE_RUN")}
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

# #6063 (decision 14.11.2026): a push on main the merge queue made (ci.yml finds a merge_group run for the same head SHA and
# sets CI_QUEUE_RUN) runs no test shards = stage "none"; the train's release push, nightly and by-hand runs stay full
qpush = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main", "CI_BEFORE": head or "1" * 40, "CI_QUEUE_RUN": "43560000001",
         "CI_MESSAGE": "#5951 #5967: suites follow the package (job/4412)"}
st, why, base = ci_base(qpush)
check(st == "none" and "43560000001" in why and base is None, "a push from the merge queue = stage none (%s, %s)" % (st, why))
st, why, _ = ci_base(dict(qpush, CI_QUEUE_RUN=""))
check(st is None, "a push on main without a merge_group run keeps the push stage (%s, %s)" % (st, why))
st, why, _ = ci_base(dict(qpush, CI_MESSAGE=zug))
check(st != "none", "the train's release push never gets stage none (%s, %s)" % (st, why))
st, why, _ = ci_base(dict(qpush, CI_MESSAGE="#1: fix [full]"))
check(st == "full", "[full] in the message wins over the queue (%s)" % st)
st, why, _ = ci_base(dict(qpush, GITHUB_REF="refs/heads/hotfix/2.1.1"))
check(st == "full", "a hotfix push stays full (%s)" % st)
st, why, _ = ci_base(dict(qpush, GITHUB_EVENT_NAME="schedule"))
check(st == "full", "the nightly run stays full (%s)" % st)
st, why, _ = ci_base(dict(qpush, GITHUB_EVENT_NAME="workflow_dispatch"))
check(st == "full", "a run by hand stays full (%s)" % st)
env = dict(os.environ, **qpush)
env.pop("CI_INPUT_STAGE", None)
out = subprocess.run([sys.executable, os.path.join(N, "stages.py"), "--ci"], capture_output=True, text=True, env=env, cwd=R).stdout
check("stage=none" in out.splitlines(), "stages.py --ci prints stage=none for a queue push (%s)" % out.strip()[:200])
check("event=merge_group&head_sha=$GITHUB_SHA" in ci and "export CI_QUEUE_RUN" in ci,
      "ci.yml plan looks up the merge_group run of the pushed commit")
check('[ "$stage" = none ] || stage=full' in ci, "ci.yml plan keeps the stage none")
tj = re.search(r"^  tests:\n(.*?)^  [a-z-]+:\n", ci, re.M | re.S)
check(tj is not None and "    if: needs.plan.outputs.stage != 'none'" in tj.group(1), "the shard job is skipped for stage none")
td = re.search(r"^  tests-done:\n(.*?)^  [a-z-]+:\n", ci, re.M | re.S)
check(td is not None and "needs: [plan, tests]" in td.group(1) and 'outputs.stage }}" = none ]; then exit 0' in td.group(1),
      "the overall test check is green for stage none (shards skipped on purpose)")
for step in ("- name: Suite times", "id: plan"):
    i = ci.find(step)
    check(i > 0 and "if: steps.stage.outputs.stage != 'none'" in ci[i:i + 400], "plan step skipped for stage none: %s" % step)

rel = read(".github", "workflows", "release.yml")
check("${{ steps.v.outputs.image }}:${{ steps.v.outputs.version }}" in rel, "the version image tag stays")

print("hotfix_lane: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
