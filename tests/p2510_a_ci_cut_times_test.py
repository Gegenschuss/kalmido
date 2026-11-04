#!/usr/bin/env python3
# kalmido-suite: nodata
"""#4327: the plan job of ci.yml took the suite times of shards cancelled at their time limit too. Their last group is cut off and
the newest time wins in tools/shards.py, so the next plan ran into the limit again (audit 03.11. F2, 2.493.0 + 2.494.0). Runs the real
step of ci.yml with a stand-in for gh; no server."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shards  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402


def job(name, conclusion):
    return {"name": name, "conclusion": conclusion}


ALL = "Test suites %d/3 full (API, UI, security)"
# 1. the list: only shard jobs, only cancelled / timed out
check(shards.cut_shards({"jobs": [job(ALL % 1, "success"), job(ALL % 2, "cancelled"), job(ALL % 3, "timed_out"), job(ALL % 3, "failure"),
                                  job("Test suites (API, UI, security)", "cancelled"), job("Lint", "cancelled")]}) == [2, 3],
      "cancelled and timed out shards count, a red shard and other jobs do not")

# 2. the step of ci.yml itself
ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
m = re.search(r"- name: Suite times .*?\n\s+run: \|\n(.*?)\n\s+- name: Plan ", ci, re.S)
check(bool(m), "ci.yml has the step Suite times")
tmp = tempfile.mkdtemp(prefix="p2510a-")
try:
    timings = os.path.join(tmp, "timings")
    step = m.group(1).replace("/tmp/timings", timings)
    # runs newest first: 30 full with shard 2 cut off (does not end the way back), 20 list of jobs not available, 10 + 9 full and whole
    plan = {30: ("full", {1: "success", 2: "cancelled"}), 20: ("full", None), 10: ("full", {1: "success", 2: "failure"}),
            9: ("full", {1: "success", 2: "success"}), 8: ("full", {1: "success", 2: "success"})}
    with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({str(k): [v[0], {str(s): c for s, c in v[1].items()} if v[1] else None] for k, v in plan.items()}, f)
    gh = os.path.join(tmp, "bin", "gh")
    os.makedirs(os.path.dirname(gh))
    with open(gh, "w", encoding="utf-8") as f:
        f.write(f"""#!/usr/bin/env python3
import json, os, sys
plan = json.load(open({os.path.join(tmp, 'plan.json')!r}))
a = sys.argv[1:]
if a[:2] == ['run', 'list']:
    print('\\n'.join(sorted(plan, key=int, reverse=True)))
elif a[:2] == ['run', 'download']:
    d = a[a.index('-D') + 1]
    for s in plan[a[2]][1] or {{'1': 'success'}}:
        os.makedirs(f'{{d}}/timings-shard-{{s}}')
        open(f'{{d}}/timings-shard-{{s}}/timings.csv', 'w').close()
        open(f'{{d}}/timings-shard-{{s}}/timings-stage.txt', 'w').write(plan[a[2]][0] + '\\n')
elif a[:2] == ['run', 'view']:
    if plan[a[2]][1] is None: sys.exit(1)
    print(json.dumps({{'jobs': [{{'name': f'Test suites {{s}}/2 full (API, UI, security)', 'conclusion': c}} for s, c in plan[a[2]][1].items()]}}))
""")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
    r = subprocess.run(["bash", "-e", "-c", step], cwd=ROOT, text=True, capture_output=True, timeout=60,
                       env={**os.environ, "PATH": os.path.dirname(gh) + os.pathsep + os.environ["PATH"], "GITHUB_REPOSITORY": "x/y", "GH_TOKEN": "x"})
    check(r.returncode == 0, f"the step runs: {r.returncode} {r.stderr[-300:]}")
    used = open(os.path.join(timings, "order.txt"), encoding="utf-8").read().split()
    have = lambda run: sorted(d for d in os.listdir(os.path.join(timings, run)))
    check("30" in used and have("30") == ["timings-shard-1"], f"a run with a cancelled shard: the others stay, that one goes: {have('30') if '30' in used else used}")
    check("shard 2 was cancelled" in r.stdout, "the log says which shard was left out")
    check("10" in used and have("10") == ["timings-shard-1", "timings-shard-2"], "a red shard keeps its times (it ran to the end)")
    check("20" not in used, f"no job list: the run is not used, its shards may be cut off: {used}")
    check(used == ["9", "10", "30"], f"the cut full run does not end the way back, oldest first: {used}")
    # #4327: the way back stops at three runs with a whole full one: run 8 is not fetched
    check(not os.path.exists(os.path.join(timings, "8")), "the way back stops at three runs with a whole full one")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"p2510_a_ci_cut_times: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
