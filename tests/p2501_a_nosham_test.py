#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.501.0 (#4296): no silent green. Static, no container (the run_all.sh case runs the real script with a stubbed docker and suites).
 - tests/*: no check that cannot fail (`check(True`, `.ok or True`, `else True,` in a check, `|| true,`, `: true, '...'`); the ones
   with a reason stand in ALLOWED with it. A status list that takes success and refusal (`in (201, 409)`) is frozen: MIXED_OLD
   may only shrink, a new one fails here. A check that passes either way says nothing. 2.755.0 (#5261): these rules live in
   tools/check_nosham.py (lint), called from here
 - the Firefox question lives in tests/ff.js only; without Firefox a check fails, KALMIDO_SKIP_FIREFOX=1 gives a skip line
 - tests/run_all.sh writes SKIPPED / PARTLY SKIPPED suites before its last line, which stays what a test runner reads
usage: p2501_a_nosham_test.py"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
# 2.755.0 (#5261): the static rules (sham, MIXED, ALLOWED, MIXED_OLD, Firefox asked for itself) live in tools/check_nosham.py,
# a lint step; this suite calls the same logic and keeps the parts that need node / bash
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from check_nosham import file_findings, findings, sham  # noqa: E402

# the rules themselves: red on the old forms, quiet on real checks
for bad in ('assert r.ok or True', 'check(x == 1 if y else True, "z")', 'check(True, "z")'):
    check(sham("x_test.py", bad), f"self check: {bad} is found")
for bad in ("check(/a/.test(t) || true, 'z');", "check(true, 'z');", "check(a ? b : true, 'z');"):
    check(sham("x_ui.js", bad), f"self check: {bad} is found")
for good in ('check(r.ok, "z")', 'check(a == 1 if b else c == 2, "z")', '# or True in a comment'):
    check(not sham("x_test.py", good), f"self check: {good} stays quiet")
check(file_findings("x_test.py", "check(r.status_code in (202, 403), 'z')"), "self check: a status list of success and refusal is found")
check(not file_findings("x_test.py", "check(r.status_code in (200, 201), 'z')"), "self check: two success codes stay quiet")
# 2.755.0 (#5261 review): a list / set of codes, and a # inside a string literal is no comment
check(file_findings("x_test.py", "check(r.status_code in [201, 409], 'z')"), "self check: a status list in [..] is found")
check(file_findings("x_test.py", "check(r.status_code in {200, 403}, 'z')"), "self check: a status set in {..} is found")
check(not file_findings("x_test.py", "check(r.status_code in [200, 201], 'z')"), "self check: two success codes in [..] stay quiet")
check(sham("x_test.py", 'check(r.get("# x") or True, "z")'), "self check: a # inside a string does not hide the old form")
check(sham("x_ui.js", "check(a == '// x' || true, 'z');"), "self check: a // inside a string does not hide the old form")
check(file_findings("x_ui.js", "execFileSync('firefox', ['-v'])"), "self check: a test that asks for Firefox itself is found")
for x in findings(os.path.join(HERE, "..")):
    check(False, x)

# ---- Firefox missing: red; KALMIDO_SKIP_FIREFOX=1: a skip line. With a PATH that has no firefox, the real ff.js
NODE = shutil.which("node")
tmp = tempfile.mkdtemp(prefix="p2501a-")
PROBE = """const bad = []; let ran = 0;
require(%r)({tag: 'probe', check: (c, m) => { if (!c) bad.push(m); }})(async () => { ran = 1; }).then(() => { console.log(JSON.stringify({bad, ran})); process.exit(0); });""" % os.path.join(HERE, "ff.js")
empty = os.path.join(tmp, "nobin")
os.makedirs(empty)
env = {k: v for k, v in os.environ.items() if k != "KALMIDO_SKIP_FIREFOX"}
env["PATH"] = empty
r = subprocess.run([NODE, "-e", PROBE], env=env, cwd=HERE, capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and '"ran":0' in r.stdout and "no firefox on PATH" in r.stdout, f"ff.js without firefox: a failed check, the part does not run: {r.stdout[-300:]} {r.stderr[-300:]}")
r = subprocess.run([NODE, "-e", PROBE], env=dict(env, KALMIDO_SKIP_FIREFOX="1"), cwd=HERE, capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and '"bad":[]' in r.stdout and "Firefox part skipped" in r.stdout, f"ff.js with KALMIDO_SKIP_FIREFOX=1: no failure, a skip line: {r.stdout[-300:]} {r.stderr[-300:]}")

# ---- tests/run_all.sh: the real script in a folder of its own, with stub suites and a docker that does nothing
box = os.path.join(tmp, "t")
os.makedirs(box)
shutil.copy(os.path.join(HERE, "run_all.sh"), box)
LIST = r"""fresh; run s_ok bash -c 'echo fine; echo the skip link; echo skipped_files 1; echo 3 ok, 0 skipped'
run s_part bash -c 'echo "s_part: Firefox part skipped (KALMIDO_SKIP_FIREFOX=1)"'
run s_tool bash -c 'echo "s_tool: SKIP (no pwsh)"'
run s_gone bash -c 'echo never'
"""
stubs = {"suites.py": "import sys\nsys.stdout.write(open(sys.argv[0].replace('suites.py', 'list.txt')).read())\n", "list.txt": LIST,
         "skip.txt": "s_gone 2099-12-31 #1 flaky\n", "start.sh": "exit 0\n"}
for name, text in stubs.items():
    with open(os.path.join(box, name), "w", encoding="utf-8") as f:
        f.write(text)
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
docker = os.path.join(bindir, "docker")
with open(docker, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nexit 0\n")
os.chmod(docker, os.stat(docker).st_mode | stat.S_IEXEC)
base = {k: v for k, v in os.environ.items() if k not in ("ONLY", "ONLY_GROUPS", "KALMIDO_SHARD_PLAN", "KALMIDO_LIST_ONLY", "GITHUB_ACTIONS", "BUILD")}
base.update(PATH=bindir + os.pathsep + os.environ["PATH"], KALMIDO_TIMINGS=os.path.join(tmp, "timings.csv"), KALMIDO_TEST_DATA=os.path.join(tmp, "data"), PYTHON=sys.executable)


def run_all(**extra):
    p = subprocess.run(["bash", os.path.join(box, "run_all.sh")], env=dict(base, **extra), capture_output=True, text=True, timeout=120)
    return p.returncode, [x for x in p.stdout.split("\n") if x]


rc, out = run_all()
check(rc == 0 and out[-1] == "ALL SUITES PASSED", f"run_all: the last line stays as it is {rc} {out[-3:]}")
check("SKIPPED suites (1): s_gone" in out, f"run_all: names the suite of skip.txt {out[-4:]}")
check("PARTLY SKIPPED suites (2): s_part s_tool" in out, f"run_all: names the suites with a skip line, not s_ok {out[-4:]}")
check(any("Firefox part skipped" in x and x.startswith(" ") for x in out), f"run_all: says what was skipped under the suite {out}")
check(not any(x.startswith("::warning") for x in out), "run_all: no annotation outside GitHub")
rc, out = run_all(GITHUB_ACTIONS="true")
check(any(x.startswith("::warning") and "s_gone" in x and "s_part" in x for x in out), f"run_all: an annotation on GitHub {out[-4:]}")
with open(os.path.join(box, "list.txt"), "a", encoding="utf-8") as f:
    f.write("run s_bad bash -c 'exit 3'\n")
rc, out = run_all()
check(rc == 1 and out[-1] == "FAILED suites: s_bad" and "SKIPPED suites (1): s_gone" in out, f"run_all: red names the skipped ones too {rc} {out[-4:]}")
shutil.rmtree(tmp, ignore_errors=True)

print(f"p2501_a_nosham: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
