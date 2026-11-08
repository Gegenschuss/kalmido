#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.707.0 (#5185): the step "Start PostgreSQL" of the job "zap" in .github/workflows/ci.yml, run for real with bash and a
stand-in docker (no container, no network). A short registry hang made the first docker command fail and the step was
red in 20 s (runs 40192975983, 42478203214), which held the live train.
 1. the registry fails twice, then answers: the step pulls up to 3 times and is green (without the fix: red at once)
 2. the registry fails three times: the step is red and says so (no endless retry)
 3. the image is there but the database never gets ready: red, and the container log is printed
2.715.0 (#5187): the real cause of run 42478203214 - the image's setup server is ready on the socket, then restarts:
 4. socket ready at once, then "rejecting" during the restart, TCP ready only after it: the step waits over TCP and is
    green (the socket check of 2.707 broke out at once and its one final check met the restart: red)
 5. the readiness check names -h 127.0.0.1 on every call (TCP, never the socket)
The pauses between the tries go to a stand-in sleep (recorded, not waited). Standard library only.
usage: python3 tests/p2707_zap_db_start_test.py"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import check, done  # noqa: E402

ROOT = os.path.dirname(HERE)


def step_script(name="Start PostgreSQL", job="zap"):
    """The run: block of step NAME in job JOB, by indentation (no YAML module needed)."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = lines.index(f"  {job}:")
    while lines[i].strip() != f"- name: {name}":
        i += 1
    while lines[i].strip() != "run: |":
        i += 1
    ind = len(lines[i]) - len(lines[i].lstrip()) + 2
    out = []
    for ln in lines[i + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) < ind:
            break
        out.append(ln[ind:])
    return "\n".join(out) + "\n"


# The stand-in docker: the registry fails the first FAIL_NET network accesses (pull, or a run that has to pull itself);
# exec pg_isready answers READY (1/0); logs prints a marker line. Every call is written to calls.log.
# 2.715.0 (#5187): with SETUP=1 the image behaves like postgres:17 at its first start, counted per exec call: the setup
# server answers on the socket at call 1, the socket rejects during the restart (calls 2-3), from call 4 on the real
# server answers on the socket and over TCP (-h 127.0.0.1); TCP never answers before call 4.
DOCKER = r"""#!/bin/bash
d="$STUB_DIR"
echo "$*" >> "$d/calls.log"
net() {
  n=$(cat "$d/net" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$d/net"
  if [ "$n" -le "$FAIL_NET" ]; then echo "Error response from daemon: Get https://registry-1.docker.io/v2/: net/http: request canceled" >&2; return 1; fi
  touch "$d/image"
}
case "$1" in
  pull) net ;;
  run) [ -e "$d/image" ] || net || exit 125; echo cafe ;;
  exec)
    [ "$READY" = 1 ] || exit 1
    [ "$SETUP" = 1 ] || exit 0
    e=$(cat "$d/exec" 2>/dev/null || echo 0); e=$((e + 1)); echo "$e" > "$d/exec"
    [ "$e" -ge 4 ] && exit 0
    case " $* " in *" -h 127.0.0.1 "*) exit 2 ;; esac
    [ "$e" = 1 ] ;;
  logs) echo "STUB-LOG: FATAL could not start database" ;;
  *) exit 0 ;;
esac
"""
SLEEP = """#!/bin/bash
echo "$1" >> "$STUB_DIR/sleeps.log"
"""


def run_step(fail_net, ready, setup=False):
    d = tempfile.mkdtemp(prefix="p2707-")
    try:
        for name, body in (("docker", DOCKER), ("sleep", SLEEP)):
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        script = os.path.join(d, "step.sh")
        with open(script, "w") as f:
            f.write(step_script())
        env = dict(os.environ, PATH=d + os.pathsep + os.environ.get("PATH", ""), STUB_DIR=d,
                   FAIL_NET=str(fail_net), READY="1" if ready else "0", SETUP="1" if setup else "0")
        # the shell of a GitHub run: step on ubuntu-latest
        r = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", script], env=env,
                           capture_output=True, text=True, timeout=60)

        def rd(n):
            p = os.path.join(d, n)
            return open(p).read().split("\n")[:-1] if os.path.exists(p) else []
        return r, rd("calls.log"), rd("sleeps.log")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# 1. two registry failures, then fine
r, calls, sleeps = run_step(2, True)
check(r.returncode == 0, f"1: two registry hangs, third try works -> green (exit {r.returncode}, {r.stderr[-300:]!r})")
check(sum(c.startswith("pull") for c in calls) == 3, f"1: three pulls ({calls})")
check(sleeps == ["10", "20"], f"1: a growing pause between the tries ({sleeps})")
check(any(c.startswith("run -d --name kalmido-zap-db") for c in calls), "1: the database is started after the pull")

# 2. the registry stays down: red after 3 tries, with a message
r, calls, sleeps = run_step(9, True)
check(r.returncode != 0, "2: the registry fails three times -> red")
check(sum(c.startswith("pull") for c in calls) == 3, f"2: exactly three pulls ({calls})")
check("failed 3 times" in r.stdout, f"2: the step says why ({r.stdout[-300:]!r})")
check(not any(c.startswith("run") for c in calls), "2: no start without the image")

# 3. image there, the database never ready: red with the container log
r, calls, sleeps = run_step(0, False)
check(r.returncode != 0, "3: database not ready -> red")
check("STUB-LOG: FATAL" in r.stdout, f"3: the container log is printed ({r.stdout[-300:]!r})")
# 2.715.0 (#5187): 90 checks, the loop is the final check (was 60 + one one-shot check)
check(sum(c.startswith("exec") for c in calls) == 90, f"3: 90 checks of the state, no extra one-shot ({len(calls)} calls)")

# 4. the setup server of the image: socket ready, restart, then the real server (run 42478203214)
r, calls, sleeps = run_step(0, True, setup=True)
check(r.returncode == 0, f"4: setup server + restart -> green, waits for the real server (exit {r.returncode}, {r.stdout[-300:]!r})")
check(sum(c.startswith("exec") for c in calls) == 4, f"4: ready at the 4th check, after the restart ({calls})")

# 5. every readiness check goes over TCP
ex = [c for c in calls if c.startswith("exec")]
check(ex and all(" -h 127.0.0.1 " in f" {c} " for c in ex), f"5: pg_isready -h 127.0.0.1 on every call ({ex})")

sys.exit(done("p2707_zap_db_start"))
