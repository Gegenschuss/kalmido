#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.381.0 A (#2853): the guards every --touched selection takes along (tests/stages.py ALWAYS_SUITES, APP_GUARD_SUITES).
No server. The Mac runner's `run --auto` (the train's check before it takes a package) used to run the static guards only
when a changed file mapped to them, so parity / pg_dialect / rls_static / the agent scripts went red only in the CI.
- every name is a suite of the list (tests/suites.py) - a renamed suite would silently drop out
- ALWAYS_SUITES need no container (no data dir, no start.sh / test port) - the list stays a matter of seconds
- every test script of the CI steps "MCP server + usage hook" and "New agents" is in ALWAYS_SUITES
- --touched: a docs file brings ALWAYS_SUITES, a server / client file also p2661_b_ui (WS_VIEWS), nothing changed = nothing
- #3505: a file --touched cannot map (core) comes back as an UNMAPPED line on stderr and in --unmapped-out, not silently"""
import os
import re
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import suites  # noqa: E402
import stages  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

rows = {s.name: (s.file, s.line or s.cmd or "") for s in suites.all_suites(N)[0] if s.name}
for s in stages.ALWAYS_SUITES + stages.APP_GUARD_SUITES:
    check(s in rows, f"{s} is a suite of tests/suites.py")
for s in stages.ALWAYS_SUITES:
    fname, line = rows.get(s, (None, ""))
    src = open(os.path.join(N, fname), encoding="utf-8").read() if fname else ""
    check(fname and "KALMIDO_TEST_DATA" not in line and "start.sh" not in src and "KALMIDO_TEST_PORT" not in src,
          f"{s}: static (no data dir, no container)")

ci = open(os.path.join(os.path.dirname(N), ".github", "workflows", "ci.yml"), encoding="utf-8").read()
steps = re.findall(r"- name: (MCP server \+ usage hook|New agents)[^\n]*\n\s+run: \|\n((?:\s{10}[^\n]*\n)+)", ci)
check(len(steps) == 2, f"ci.yml has the steps MCP server + usage hook and New agents: {[x[0] for x in steps]}")
by_file = {fname: name for name, (fname, _) in rows.items() if fname}
for step, body in steps:
    for f in re.findall(r"python tests/(\S+\.py)", body):
        check(by_file.get(f) in stages.ALWAYS_SUITES, f"CI step {step}: tests/{f} ({by_file.get(f)}) is in ALWAYS_SUITES")

repo = stages.Repo(os.path.dirname(N), os.path.join(N, "run_all.sh"))
order, why, _ = stages.touched(repo, ["docs/AGENTS.md"])
check(all(s in order for s in stages.ALWAYS_SUITES) and "p2661_b_ui" not in order, f"a docs file: the static guards {order}")
order, why, _ = stages.touched(repo, ["static/js/app.js"])
check(all(s in order for s in stages.ALWAYS_SUITES + stages.APP_GUARD_SUITES), "a client file: + p2661_b_ui")
check(why.get("parity") == "guard, always (#2853)", f"--why names the reason: {why.get('parity')}")
order, _, _ = stages.touched(repo, [])
check(order == [], f"nothing changed = nothing to test: {order}")
_, _, unm = stages.touched(repo, ["kalmido/core/schema.py", "docs/AGENTS.md"])
check([u.split(" (")[0] for u in unm] == ["kalmido/core/schema.py"], f"#3505: core file unmapped, docs not: {unm}")
with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "unmapped.txt")
    p = subprocess.run([sys.executable, os.path.join(N, "stages.py"), "--touched", "--unmapped-out", out,
                        "kalmido/core/schema.py"], capture_output=True, text=True, cwd=os.path.dirname(N))
    rows_out = open(out, encoding="utf-8").read().splitlines() if os.path.exists(out) else []
    check(p.returncode == 0 and "UNMAPPED: kalmido/core/schema.py (" in p.stderr, f"#3505: UNMAPPED line on stderr: {p.stderr[-300:]}")
    check(len(rows_out) == 1 and rows_out[0].startswith("kalmido/core/schema.py\t") and rows_out[0].split("\t")[1],
          f"#3505: --unmapped-out has FILE<TAB>reason: {rows_out}")

print(f"p2381_a_guards: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
