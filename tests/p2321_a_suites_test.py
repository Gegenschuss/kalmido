#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.321 A (#1368): the suite list from tests/suites.py - tests/suites.txt (old run lines) + test files with a `kalmido-suite:`
marker. No server. This file is itself the first suite registered only by its marker line above.

- the old lines reproduce the groups exactly (shards.py / stages.py / run_all.sh see the same list)
- a marker file gets its own group at the end; after=X joins X's group right after X (by name among several); nodata drops
  the data dir argument; now= sets the group's test time
- --check: a malformed marker, a name taken twice, after= naming no suite = errors
- --bash prints the run lines run_all.sh evals; --file names a suite's test file"""
import os
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(os.path.dirname(N), "tools"))
import shards  # noqa: E402
import suites  # noqa: E402
import stages  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

# 1. the real tree: suites.txt + markers = what shards.py and stages.py read; this suite is in it by its marker
rows = suites.rows(N)
names = [n for _, n, _ in rows]
check(len(rows) > 1100 and len(names) == len(set(names)), f"{len(rows)} suites, names unique")
check("p2321_a_suites" in names, "this file is a suite by its marker line (no entry in suites.txt)")
check(not any("p2321_a_suites" in ln for ln in open(os.path.join(N, "suites.txt"), encoding="utf-8")), "and suites.txt has no line for it")
gs = shards.groups(os.path.join(N, "run_all.sh"))
check([g[0] for g in gs] == [g[0] for g in suites.groups(N)], f"shards.py reads the same {len(gs)} groups")
check([(g, s) for g, s, _ in stages.suites(os.path.join(N, "run_all.sh"))] == [(g, s) for g, s, _ in rows], "stages.py reads the same rows")
check(suites.main(["--check"]) == 0, "suites.py --check is green on the real tree")
out = subprocess.run([sys.executable, os.path.join(N, "suites.py"), "--file", "p2321_a_suites"], capture_output=True, text=True)
check(out.stdout.strip() == "p2321_a_suites_test.py", f"--file names the test file: {out.stdout.strip()!r}")

# 2. a small tree: legacy lines + markers
d = tempfile.mkdtemp(prefix="suites-")
with open(os.path.join(d, "suites.txt"), "w") as f:
    f.write('# comment\nfresh; run api "$PY" api_test.py "$KALMIDO_TEST_DATA"\n       run ui node ui_test.js\nshard 2\nnow wed 10:00; fresh; run t_api "$PY" t_api_test.py "$KALMIDO_TEST_DATA"\n')
for fn, head in (("p9_a_api_test.py", "#!/usr/bin/env python3\n# kalmido-suite: now=wed10:00\n"),
                 ("p9_c_ui.js", "// @ts-check\n// kalmido-suite: after=api nodata\n"),
                 ("p9_b_ui.js", "// kalmido-suite: after=api\n"),
                 ("p9_z_test.py", "# kalmido-suite: after=p9_a_api nodata\n"),
                 ("helper.py", "# a helper without a marker\n"),
                 ("fake_thing.py", "# kalmido-suite:\n"),  # fake_* are never suites
                 ("api_test.py", "# a legacy suite file\n"), ("ui_test.js", "// legacy\n"), ("t_api_test.py", "#\n")):
    with open(os.path.join(d, fn), "w") as f:
        f.write(head)
order, errs = suites.all_suites(d)
check(not errs, f"no errors: {errs}")
check([s.name for s in order if s.name] == ["api", "p9_b_ui", "p9_c_ui", "ui", "t_api", "p9_a_api", "p9_z"],
      f"order: legacy first, after=api suites right after api by name, own groups at the end: {[s.name for s in order]}")
bash = [s.bash() for s in order]
check(bash[1] == '       run p9_b_ui node p9_b_ui.js "$KALMIDO_TEST_DATA"' and bash[2] == "       run p9_c_ui node p9_c_ui.js", f"after= lines: {bash[1:3]}")
check(bash[4] == "shard 2", f"the shard marker of suites.txt passes through (Mac full run): {bash[4]}")
check(bash[6] == 'now wed 10:00; fresh; run p9_a_api "$PY" p9_a_api_test.py "$KALMIDO_TEST_DATA"', f"now= + fresh line: {bash[6]}")
check(bash[7] == '       run p9_z "$PY" p9_z_test.py', f"after a marker suite, nodata: {bash[7]}")
check(suites.groups(d) == [("api", ["api", "p9_b_ui", "p9_c_ui", "ui"], 1), ("t_api", ["t_api"], 2), ("p9_a_api", ["p9_a_api", "p9_z"], 2)],
      f"groups with the marker shard (new suites land in the last marked shard): {suites.groups(d)}")
check([r for r in suites.rows(d) if r[1] == "p9_z"] == [(3, "p9_z", "p9_z_test.py")], "rows carry group index + file")
# 3. errors
with open(os.path.join(d, "p9_bad_test.py"), "w") as f:
    f.write("# kalmido-suite: fresh wrongword\n")
with open(os.path.join(d, "ui_test.py"), "w") as f:
    f.write("# kalmido-suite:\n")  # name 'ui' is taken by suites.txt
with open(os.path.join(d, "p9_orphan_test.py"), "w") as f:
    f.write("# kalmido-suite: after=nosuch\n")
_, errs = suites.all_suites(d)
check(len(errs) == 3 and any("wrongword" in e for e in errs) and any("ui is taken" in e for e in errs) and any("after=nosuch" in e for e in errs),
      f"malformed marker, taken name, unknown after= are errors: {errs}")
# 4. stages: a new marker file maps to its suite; suites.txt with only added lines = those suites
repo = stages.Repo(os.path.dirname(N), os.path.join(N, "run_all.sh"))
kind, res = stages.classify(repo, "tests/p2321_a_suites_test.py")
check(kind == "suites" and "p2321_a_suites" in res, f"stages.py maps the marker file to its suite: {kind} {res}")
kind, res = stages.classify(repo, "tests/run_all.sh")
check(kind == "full", "a change of run_all.sh itself = full run")
# 2.300.0 (#3198): a touched suite that logs in as users of an earlier suite (stages-needs:) brings that suite along
order, why, _ = stages.touched(repo, ["tests/webpush_ui.js"])
check(order[:2] == ["webpush", "webpush_ui"] and "stages-needs" in why.get("webpush", ""), f"webpush_ui brings webpush (carol): {order} {why}")

print(f"p2321_a_suites: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
