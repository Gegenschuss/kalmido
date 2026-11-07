#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.625 D (#4005): every suite leaves a JUnit report. Static, no container: tests/junit.py on its own, then the real
tests/run_all.sh in a folder of its own with stub suites (a kt.py suite with a red and a green check, a suite with FAIL lines
only, a crash without output, a skipped one) and a docker that does nothing; the reports are read back with ElementTree.
usage: p2625_d_junit_test.py"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import junit
from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- tests/junit.py alone
c = junit.cases_of("start\nFAIL: the total is 3\nFAIL: the name\nx: 5 ok, 2 failed\n", 1, "x")
check([n for n, f in c if f] == ["the total is 3", "the name"] and ("x: 5 checks passed", None) in c, f"FAIL lines -> failed cases, the rest one passed case {c}")
c = junit.cases_of("", 3, "x")
check(len(c) == 2 and c[-1][0] == "x" and c[-1][1].startswith("exit 3"), f"a crash without a FAIL line is a failed case {c}")
c = junit.cases_of("FAIL: b\nFAIL: own copy\n", 1, "x", "ok\ta\nfail\tb")
check([n for n, f in c] == ["a", "b", "own copy"] and [bool(f) for n, f in c] == [False, True, True], f"steps -> a case per check, FAIL lines beyond them too {c}")
x = ET.fromstring(junit.xml_of("s<&>", [("a\x01b", None), ("c", "FAIL: c <x>\nmore")], 1.5))
check(x.get("name") == "s<&>" and x.get("tests") == "2" and x.get("failures") == "1" and x.get("time") == "1.500", f"testsuite attributes {x.attrib}")
check(x.findall("testcase")[1].find("failure").get("message") == "FAIL: c <x>", "failure message = first line, escaped")

# ---- tests/run_all.sh with stub suites
tmp = tempfile.mkdtemp(prefix="p2625d-")
box = os.path.join(tmp, "t")
os.makedirs(box)
for f in ("run_all.sh", "junit.py"):
    shutil.copy(os.path.join(HERE, f), box)
KT = f"import sys; sys.path.insert(0, {HERE!r}); import kt; kt.check(1 == 1, 'first step'); kt.check(1 == 2, 'second step'); sys.exit(kt.done('s_kt'))"
LIST = f"""fresh; run s_kt {sys.executable} -c "{KT}"
run s_lines bash -c 'echo "FAIL: the list is empty"; echo "s_lines: 4 ok, 1 failed"; exit 1'
run s_ok bash -c 'echo "s_ok: 3 ok, 0 failed"'
run s_crash bash -c 'exit 3'
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
JD = os.path.join(box, ".junit")
os.makedirs(JD)
with open(os.path.join(JD, "old_suite.xml"), "w") as f:
    f.write("<testsuite/>")
base = {k: v for k, v in os.environ.items() if k not in ("ONLY", "ONLY_GROUPS", "KALMIDO_SHARD_PLAN", "KALMIDO_LIST_ONLY", "GITHUB_ACTIONS", "BUILD",
                                                        "KALMIDO_JUNIT", "KALMIDO_JUNIT_DIR", "KALMIDO_JUNIT_STEPS")}
base.update(PATH=bindir + os.pathsep + os.environ["PATH"], KALMIDO_TIMINGS=os.path.join(tmp, "timings.csv"), KALMIDO_TEST_DATA=os.path.join(tmp, "data"), PYTHON=sys.executable)


def run_all(**extra):
    p = subprocess.run(["bash", os.path.join(box, "run_all.sh")], env=dict(base, **extra), capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout


def rep(s):
    p = os.path.join(JD, s + ".xml")
    return ET.parse(p).getroot() if os.path.isfile(p) else None


rc, out = run_all()
check(rc == 1 and out.rstrip().split("\n")[-1] == "FAILED suites: s_kt s_lines s_crash", f"run_all: result as before {rc} {out[-300:]}")
check("FAIL: second step" in out and "FAIL: the list is empty" in out, f"run_all: the FAIL lines stay in the output {out[-600:]}")
check(not os.path.exists(os.path.join(JD, "old_suite.xml")), "run_all: the reports of an earlier run are gone")
check(sorted(f for f in os.listdir(JD)) == ["s_crash.xml", "s_gone.xml", "s_kt.xml", "s_lines.xml", "s_ok.xml"], f"run_all: one report per suite, no steps file left {os.listdir(JD)}")
r = rep("s_kt")
cs = {t.get("name"): t.find("failure") for t in r.findall("testcase")} if r is not None else {}
check(r is not None and r.get("tests") == "2" and r.get("failures") == "1" and cs.get("first step") is None and cs.get("second step") is not None,
      f"kt suite: a case per check, the red one failed {r.attrib if r is not None else None} {list(cs)}")
check(r is not None and float(r.get("time")) >= 0 and r.get("name") == "s_kt", "kt suite: name and time")
r = rep("s_lines")
check(r is not None and r.get("failures") == "1" and [t.get("name") for t in r.findall("testcase")] == ["the list is empty", "s_lines: 4 checks passed"],
      f"FAIL-line suite: one failed case per FAIL line + the passed ones {ET.tostring(r) if r is not None else None}")
r = rep("s_ok")
check(r is not None and r.get("failures") == "0" and r.find("testcase").get("name") == "s_ok: 3 checks passed", "green suite: no failure")
r = rep("s_crash")
check(r is not None and r.get("failures") == "1" and "exit 3" in r.find("testcase/failure").text, "crash: one failed case with the exit code")
r = rep("s_gone")
check(r is not None and r.get("skipped") == "1" and r.find("testcase/skipped") is not None, "skip.txt suite: a skipped case")
shutil.rmtree(JD)
rc, out = run_all(KALMIDO_JUNIT="0")
check(rc == 1 and not os.path.exists(JD), "KALMIDO_JUNIT=0: no report")
rc, out = run_all(ONLY="s_ok", KALMIDO_JUNIT_DIR=os.path.join(tmp, "own"))
check(rc == 0 and os.listdir(os.path.join(tmp, "own")) == ["s_ok.xml"], "KALMIDO_JUNIT_DIR + ONLY: only that suite's report there")
shutil.rmtree(tmp, ignore_errors=True)

print(f"p2625_d_junit: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
