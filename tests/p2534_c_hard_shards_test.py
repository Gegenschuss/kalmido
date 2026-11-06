#!/usr/bin/env python3
# kalmido-suite: nodata
"""#4557: the groups of the hard areas (office, invoices, backup, login: tests/hard_suites.txt) get
their own CI shards 1..H that are queued first (tools/shards.py --hard-target-min, ci.yml job "plan" + the matrix of "tests"); the
fast lane of a release waits for those only. Runs the plan logic and the real "Plan" step of ci.yml; no server."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shards  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

# 1. the list: lower case fnmatch patterns, the four areas present
pats = shards.hard_patterns(os.path.join(N, "hard_suites.txt"))
check(pats and all(p == p.lower() and not p.startswith("#") for p in pats), f"tests/hard_suites.txt: {len(pats)} lower case patterns")
for word in ("office", "invoice", "backup", "restore", "login", "password"):
    check(any(word in p for p in pats), f"tests/hard_suites.txt names {word}")
check(shards.hard_patterns(os.path.join(N, "no_such_file.txt")) == [], "no file = no hard groups")

# 2. a group is hard by its name or by one suite in it (a shard is waited for as soon as one suite in it is hard)
check(shards.is_hard(("backup", ["backup"], 0), pats), "group backup is hard")
check(shards.is_hard(("p2360_d_ui", ["p2360_d_ui", "office_calc"], 0), pats), "a UI group with one office suite is hard whole")
check(not shards.is_hard(("p8_api", ["p8_api", "calendar_feed"], 0), pats), "a calendar group is soft")
# 2.552.0 (#4656): "vat" only as a word of the name - *vat* hit 'private' and 'avatar' and held the fast lane
for soft in ("p2306_a_private_seal", "p2470_e_avatar_ui"):
    check(not shards.is_hard((soft, [soft], 0), pats), f"{soft} is soft (vat inside a word does not count)")
for hard in ("p9_vat_api", "vat_rates", "p12_report_vat"):
    check(shards.is_hard((hard, [hard], 0), pats), f"{hard} is hard (vat as a word)")

# 3. split_plan: hard on 1..H (as many as their target needs, at most hard_most), the others after them; off = the old LPT
costs = [600.0, 500.0, 400.0, 300.0, 1800.0, 1700.0, 1600.0, 1500.0, 1400.0, 1300.0]
plan, h = shards.split_plan(costs, [0, 1, 2, 3], 4, 30, 10)
check(h == 3, f"1800 s of hard groups at 10 min = 3 hard shards: {h}")
check([k for k, _, _ in plan] == list(range(1, len(plan) + 1)), "the shards are numbered 1..M without a gap")
hard_on = {i for k, idx, _ in plan if k <= h for i in idx}
check(hard_on == {0, 1, 2, 3}, f"the hard shards hold the hard groups and nothing else: {sorted(hard_on)}")
check(all(i >= 4 for k, idx, _ in plan if k > h for i in idx) and len(plan) == h + 4, "the others on the shards after them (--shards 4)")
plan, h = shards.split_plan(costs, [0, 1, 2, 3], 4, 30, 10, hard_most=2)
check(h == 2, "at most hard_most hard shards")
old = shards.lpt(costs, 4)
check(shards.split_plan(costs, [], 4, 0, 10) == (old, 0) and shards.split_plan(costs, [0, 1], 4, 0, 0) == (old, 0),
      "no hard group or --hard-target-min 0 = the old plan")
plan, h = shards.split_plan([100.0, 200.0], [0, 1], 4, 30, 10)
check(h == 1 and len(plan) == 1, "only hard groups: no empty soft shard")
# 2.556 (#4388): --total N = exactly N shards in all (H hard + N-H others), --shards / --target-min do not count
plan, h = shards.split_plan(costs, [0, 1, 2, 3], 28, 30, 10, total=6)
check(h == 3 and len(plan) == 6 and [k for k, _, _ in plan] == list(range(1, 7)), f"total 6 = 3 hard + 3 others: {h} {len(plan)}")
check({i for k, idx, _ in plan if k <= h for i in idx} == {0, 1, 2, 3}, "with total the hard shards still hold the hard groups")
plan, h = shards.split_plan(costs, [], 28, 30, 10, total=5)
check(h == 0 and len(plan) == 5, "total without hard groups = exactly total shards")
# 2.573.0 (#4748): --soft-shards N = H hard + exactly N others, --total / --shards / --target-min do not count for the others
plan, h = shards.split_plan(costs, [0, 1, 2, 3], 28, 30, 10, total=6, soft_shards=5)
check(len(plan) == h + 5 and {i for k, idx, _ in plan if k > h for i in idx} == set(range(4, len(costs))),
      f"soft_shards 5 = {h} hard + 5 others: {len(plan)}")
plan, h = shards.split_plan(costs, [], 28, 30, 10, soft_shards=3)
check(h == 0 and len(plan) == 3, "soft_shards without hard groups = exactly that many shards")
plan, h = shards.split_plan(costs, [0, 1, 2, 3], 28, 30, 1, hard_most=8, total=4)
check(h == 3 and len(plan) == 4, f"many hard shards leave at least one for the others: {h} {len(plan)}")

# 4. --assign on the real tree (estimates only): "# hard H" first, every hard group on 1..H, no soft one there
tmp = tempfile.mkdtemp(prefix="p2534c-")
try:
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "shards.py"), "--shards", "28", "--target-min", "30",
                        "--hard-target-min", "9", "--assign"], capture_output=True, text=True, timeout=120)
    check(r.returncode == 0, f"shards.py --assign --hard-target-min: {r.returncode} {r.stderr[-300:]}")
    lines = r.stdout.splitlines()
    m = re.fullmatch(r"# hard ([0-9]+)", lines[0] if lines else "")
    check(bool(m), f"the plan starts with '# hard H': {lines[:1]}")
    h = int(m.group(1)) if m else 0
    gs = {g[0]: g for g in shards.groups(os.path.join(N, "run_all.sh"))}
    at = {ln.split()[0]: int(ln.split()[1]) for ln in lines if not ln.startswith("#")}
    check(set(at) == set(gs), "every group is in the plan once")
    wrong = [g for g, k in at.items() if (k <= h) != shards.is_hard(gs[g], pats)]
    check(h >= 1 and not wrong, f"hard groups exactly on shards 1..{h}: {wrong[:5]}")
    r0 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "shards.py"), "--shards", "28", "--target-min", "30", "--assign"],
                        capture_output=True, text=True, timeout=120)
    check(not r0.stdout.startswith("#"), "without --hard-target-min the plan has no hard line (Mac runner, older calls)")
    # the push stage: --only keeps the hard split, "# stage push" stays the first line (run_all.sh reads it)
    only = os.path.join(tmp, "push.txt")
    first = sorted(gs)[:40]
    with open(only, "w", encoding="utf-8") as f:
        f.write("\n".join(first + ["backup"]) + "\n")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "shards.py"), "--shards", "20", "--target-min", "15",
                        "--hard-target-min", "9", "--only", only, "--assign"], capture_output=True, text=True, timeout=120)
    pl = r.stdout.splitlines()
    check(pl[:1] == ["# stage push"] and pl[1:2] == ["# hard 1"] and "backup 1" in pl, f"push stage: {pl[:3]}")

    # 5. the "Plan" step of ci.yml: the matrix lists the hard shards first, marked " hart"; the job name then reads
    #    "Test suites N/M full hart (API, UI, security)" - what the release tooling and shards.py --cut-shards match
    ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
    st = re.search(r"- name: Plan .*?\n\s+run: \|\n(.*?)\n\s+- uses: actions/upload-artifact", ci, re.S)
    check(bool(st), "ci.yml has the step Plan")
    tdir = os.path.join(tmp, "timings")
    os.makedirs(tdir)
    open(os.path.join(tdir, "order.txt"), "w").close()
    gho, ghs = os.path.join(tmp, "out"), os.path.join(tmp, "summary")
    step = st.group(1).replace("/tmp/timings", tdir)
    # the step calls tools/shards.py relative to the checkout and writes shard-plan.txt there: a copy of the layout
    os.symlink(os.path.join(ROOT, "tools"), os.path.join(tmp, "tools"))
    os.symlink(N, os.path.join(tmp, "tests"))
    r = subprocess.run(["bash", "-e", "-c", step], cwd=tmp, text=True, capture_output=True, timeout=180,
                       env={**os.environ, "STAGE": "full", "REASON": "test", "GITHUB_OUTPUT": gho, "GITHUB_STEP_SUMMARY": ghs})
    check(r.returncode == 0, f"the Plan step runs: {r.returncode} {r.stderr[-400:]}")
    o = dict(ln.split("=", 1) for ln in open(gho, encoding="utf-8").read().splitlines() if "=" in ln)
    mx = json.loads(o.get("matrix") or "[]")
    hh, n = int(o.get("hard") or 0), int(o.get("count") or 0)
    check(hh >= 1 and n == len(mx) and [x["shard"] for x in mx] == list(range(1, n + 1)), f"matrix 1..{n} in order, {hh} hard")
    check([x["hart"] for x in mx] == [" hart"] * hh + [""] * (n - hh), "the hard shards first, marked ' hart'")
    # 2.573.0 (#4748): the full run plans the hard shards + exactly 20 others (was 20 in all, #4388: 13 others at 80-84 of 90 min)
    check(n == hh + 20, f"full run: {hh} hard + 20 others: {n}")
    # job/2867 (CI v2.560.0): 60 was too short for 13 soft shards (~70 min each), all 13 were cut - 90 now
    check(re.search(r"needs: plan\n\s+timeout-minutes: 90\b", ci), "the shard job has the 90 min limit")
    tpl = re.search(r"^\s+name: (Test suites \$\{\{ matrix\.shard \}\}.*)$", ci, re.M)
    check(bool(tpl) and "${{ matrix.hart }}" in tpl.group(1), "the shard job name carries matrix.hart")
    check("include: ${{ fromJSON(needs.plan.outputs.matrix) }}" in ci, "the matrix of the shard job is the plan's list")
    if tpl:
        def name(x):
            return (tpl.group(1).replace("${{ matrix.shard }}", str(x["shard"])).replace("${{ needs.plan.outputs.count }}", str(n))
                    .replace("${{ needs.plan.outputs.stage }}", "full").replace("${{ matrix.hart }}", x["hart"]))
        hn, sn = name(mx[0]), name(mx[-1])
        check(hn == f"Test suites 1/{n} full hart (API, UI, security)" and sn == f"Test suites {n}/{n} full (API, UI, security)",
              f"job names: {hn!r} / {sn!r}")
        live = re.compile(r"^Test suites (\d+)/(\d+) (full|push)\b")  # the release tooling's shard pattern
        check(live.match(hn) and live.match(sn) and shards.SHARD_JOB_RE.match(hn), "hard and soft names stay shard jobs for every reader")
        cut = shards.cut_shards({"jobs": [{"name": hn, "conclusion": "timed_out"}, {"name": sn, "conclusion": "success"}]})
        check(cut == [1], f"--cut-shards sees a hard shard at its limit: {cut}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"p2534_c_hard_shards: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
