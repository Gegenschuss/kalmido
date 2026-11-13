#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.1129.0 (#6054): a red CI shard ends fast instead of holding a runner for up to 90 minutes.
The real tests/run_all.sh in a folder of its own, with stub suites, a start.sh that only counts and a docker that does nothing
(no container, no server):
 - KALMIDO_SUITE_LIMIT_S=N stops a suite after N seconds (its whole process group, also a child that holds the output open):
   red with a "FAIL: ... over the limit" line, the next suite of the group gets a fresh container; off when unset
 - KALMIDO_RED_STREAK=N ends the shard after N red suites in a row (a quarantined red neither counts nor breaks the row, a green
   one starts it anew): the suites after it do not run, they are named "NOT RUN" (+ a skipped JUnit report), the last line
   stays "FAILED suites: ..." and the results of the suites that ran stay; off when unset
"""
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import FAILS, OKS, check  # noqa: E402

tmp = tempfile.mkdtemp(prefix="p6054a-")
box = os.path.join(tmp, "t")
os.makedirs(box)
shutil.copy(os.path.join(HERE, "run_all.sh"), box)
shutil.copy(os.path.join(HERE, "junit.py"), box)
ran = os.path.join(tmp, "ran.txt")
starts = os.path.join(tmp, "starts.txt")
stubs = {"suites.py": "import sys\nsys.stdout.write(open(sys.argv[0].replace('suites.py', 'list.txt')).read())\n",
         "skip.txt": "s_wack 2099-12-31 #1 flaky\n", "quarantine_never.txt": "# never quiet\n*rights*\n",
         "start.sh": f"echo start >> '{starts}'\nexit 0\n"}
for name, text in stubs.items():
    with open(os.path.join(box, name), "w", encoding="utf-8") as f:
        f.write(text)
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
docker = os.path.join(bindir, "docker")
with open(docker, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nexit 0\n")
os.chmod(docker, os.stat(docker).st_mode | stat.S_IEXEC)
base = {k: v for k, v in os.environ.items() if k not in ("ONLY", "ONLY_GROUPS", "KALMIDO_SHARD_PLAN", "KALMIDO_LIST_ONLY", "GITHUB_ACTIONS",
                                                         "BUILD", "KALMIDO_SUITE_LIMIT_S", "KALMIDO_RED_STREAK", "KALMIDO_QUARANTAENE")}
base.update(PATH=bindir + os.pathsep + os.environ["PATH"], KALMIDO_TIMINGS=os.path.join(tmp, "timings.csv"),
            KALMIDO_TEST_DATA=os.path.join(tmp, "data"), KALMIDO_JUNIT_DIR=os.path.join(tmp, "junit"), PYTHON=sys.executable)


def suite(name, body):
    """a stub suite that notes it ran, then does BODY (shell)"""
    return f"run {name} bash -c 'echo {name} >> \"{ran}\"; {body}'"


def run_all(lines, **extra):
    with open(os.path.join(box, "list.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for p in (ran, starts):
        if os.path.exists(p):
            os.remove(p)
    t0 = time.monotonic()
    p = subprocess.run(["bash", os.path.join(box, "run_all.sh")], env=dict(base, **extra), capture_output=True, text=True, timeout=120)
    took = time.monotonic() - t0

    def read(path):
        return open(path, encoding="utf-8").read().split() if os.path.exists(path) else []
    return p.returncode, [x for x in p.stdout.split("\n") if x], read(ran), len(read(starts)), took


# ---- 1. the time limit per suite
hang = ["fresh; " + suite("s_first", "echo 1 ok, 0 failed"),
        suite("s_hang", "sleep 60 & sleep 60"),  # a child in the background holds the output open: the whole group must go
        suite("s_next", "echo 1 ok, 0 failed")]
rc, out, did, nstart, took = run_all(hang, KALMIDO_SUITE_LIMIT_S="2")
check(rc == 1 and out[-1] == "FAILED suites: s_hang", f"limit: the hanging suite is red, the others pass {rc} {out[-3:]}")
check(took < 30, f"limit: the run ends soon after the limit (2 s), not after the 60 s of the suite: {took:.0f} s")
check(any(x.startswith("FAIL: s_hang stopped: over the limit of 2 s") for x in out), f"limit: says why the suite is red {out}")
check(did == ["s_first", "s_hang", "s_next"], f"limit: the suite after it still runs {did}")
check(nstart == 2, f"limit: the next suite of the group gets a fresh container (the hung one may be the cause): {nstart} starts")
xml = os.path.join(tmp, "junit", "s_hang.xml")
check(os.path.exists(xml) and "over the limit" in open(xml, encoding="utf-8").read(), "limit: the JUnit report of the suite names it")
rc, out, did, nstart, took = run_all(["fresh; " + suite("s_slow", "sleep 3; echo 1 ok, 0 failed")])
check(rc == 0 and out[-1] == "ALL SUITES PASSED" and took >= 3, f"no limit without KALMIDO_SUITE_LIMIT_S (Mac, local) {rc} {out[-2:]}")
rc, out, did, nstart, took = run_all(["fresh; " + suite("s_quick", "sleep 1; echo 1 ok, 0 failed")], KALMIDO_SUITE_LIMIT_S="20")
check(rc == 0 and out[-1] == "ALL SUITES PASSED", f"a suite under the limit passes as before {rc} {out[-2:]}")

# ---- 2. the red streak
streak = ["fresh; " + suite("s_ok", "echo 1 ok, 0 failed"),
          suite("s_r1", "echo FAIL: db down; exit 1"),
          suite("s_r2", "echo FAIL: db down; exit 1"),
          suite("s_wack", "echo FAIL: flaky; exit 1"),  # quarantine: neither counts nor breaks the row
          "fresh; " + suite("s_r3", "echo FAIL: db down; exit 1"),
          suite("s_after1", "echo 1 ok, 0 failed"),
          "fresh; " + suite("s_after2", "echo 1 ok, 0 failed")]
rc, out, did, nstart, took = run_all(streak, KALMIDO_RED_STREAK="3")
check(rc == 1 and out[-1] == "FAILED suites: s_r1 s_r2 s_r3", f"streak: red with the suites that ran red, last line as always {rc} {out[-3:]}")
check(did == ["s_ok", "s_r1", "s_r2", "s_wack", "s_r3"], f"streak: nothing after the third red in a row runs {did}")
check(nstart == 2, f"streak: no container for the groups after the stop: {nstart} starts")
nr = [x for x in out if x.startswith("NOT RUN suites (2, 3 red suites in a row up to s_r3")]
check(len(nr) == 1 and nr[0].endswith(": s_after1 s_after2"), f"streak: the suites left are named NOT RUN {out[-4:]}")
check(any(x.startswith("== STOP: 3 red suites in a row up to s_r3") for x in out), "streak: the stop is in the log where it happens")
check("QUARANTINE red suites (1, not counted): s_wack" in out, f"streak: the quarantine still reports {out[-4:]}")
check(os.path.exists(os.path.join(tmp, "junit", "s_after1.xml")) and "skipped=\"1\"" in open(os.path.join(tmp, "junit", "s_after1.xml")).read(),
      "streak: a suite not run leaves a skipped JUnit report")
check(sorted(os.path.basename(x) for x in glob.glob(os.path.join(tmp, "junit", "s_r*.xml"))) == ["s_r1.xml", "s_r2.xml", "s_r3.xml"],
      "streak: the reports of the suites that ran stay")
rc, out, did, nstart, took = run_all(streak, KALMIDO_RED_STREAK="3", GITHUB_ACTIONS="true")
check(any(x.startswith("::error title=shard stopped after 3 red suites in a row::") for x in out), "streak: an annotation on GitHub")
broken = ["fresh; " + suite("s_r1", "exit 1"), suite("s_r2", "exit 1"), suite("s_ok", "echo 1 ok, 0 failed"),
          suite("s_r3", "exit 1"), suite("s_r4", "exit 1"), suite("s_end", "echo 1 ok, 0 failed")]
rc, out, did, nstart, took = run_all(broken, KALMIDO_RED_STREAK="3")
check(did[-1] == "s_end" and not any(x.startswith("NOT RUN") for x in out), f"streak: a green suite starts the row anew {did}")
rc, out, did, nstart, took = run_all(streak)
check(did[-1] == "s_after2" and out[-1] == "FAILED suites: s_r1 s_r2 s_r3", f"no stop without KALMIDO_RED_STREAK (Mac, local) {did}")

shutil.rmtree(tmp, ignore_errors=True)
print(f"p6054_a_shard_fast: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
