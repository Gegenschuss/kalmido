#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.728.0 (#5188): the database readiness of a first start, over TCP (same cause as #5187 in the ZAP step).
postgres:17 first runs a setup server on the socket only and then restarts it; pg_isready without -h reports that server
as ready. The database block of tests/start.sh runs for real with bash and a stand-in docker (no container):
 1. setup server + restart: the wait loop asks over TCP on every call and goes on only after the restart
 2. no fixed pause: the old "sleep 1" after the socket check is gone (the pauses are the loop's own 0.5 s)
 3. the database never gets ready: start.sh stops red and prints the container log (before: it went on silently)
 4. docker-compose.yml: the health check of the db service (Kalmido waits for it) uses pg_isready -h 127.0.0.1
The pauses go to a stand-in sleep (recorded, not waited). Standard library only.
usage: python3 tests/p2728_db_ready_tcp_test.py"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import check, done  # noqa: E402

ROOT = os.path.dirname(HERE)


def db_block():
    """The block of tests/start.sh that starts the database container (if [[ -z "$(docker ps ... ]] ... fi)."""
    with open(os.path.join(HERE, "start.sh"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith('if [[ -z "$(docker ps -q -f "name=^${DBC}$")" ]]; then'))
    j = next(n for n in range(i, len(lines)) if lines[n] == "fi")
    return "\n".join(lines[i:j + 1]) + "\n"


# The stand-in docker: "ps" lists nothing (the database is started), every exec is counted. READY=0: never ready.
# READY=1: like postgres:17 at its first start - exec 1 = the setup server answers on the socket only, exec 2-3 = the
# restart (nothing answers), from exec 4 on the real server answers on the socket and over TCP.
DOCKER = r"""#!/bin/bash
d="$STUB_DIR"
echo "$*" >> "$d/calls.log"
case "$1" in
  ps) exit 0 ;;
  run) echo cafe ;;
  exec)
    [ "$READY" = 1 ] || exit 2
    e=$(cat "$d/exec" 2>/dev/null || echo 0); e=$((e + 1)); echo "$e" > "$d/exec"
    [ "$e" -ge 4 ] && exit 0
    case " $* " in *" -h 127.0.0.1 "*) exit 2 ;; esac
    [ "$e" = 1 ] ;;
  logs) echo "STUB-LOG: database system is shut down" ;;
  *) exit 0 ;;
esac
"""
SLEEP = """#!/bin/bash
echo "$1" >> "$STUB_DIR/sleeps.log"
"""


def run_block(ready):
    d = tempfile.mkdtemp(prefix="p2728-")
    try:
        for name, body in (("docker", DOCKER), ("sleep", SLEEP)):
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        script = os.path.join(d, "block.sh")
        with open(script, "w") as f:
            f.write("set -u\nDBC=kalmido-p2728-db\n" + db_block() + "echo BLOCK-DONE\n")
        env = dict(os.environ, PATH=d + os.pathsep + os.environ.get("PATH", ""), STUB_DIR=d, READY="1" if ready else "0")
        r = subprocess.run(["bash", "--noprofile", "--norc", script], env=env, capture_output=True, text=True, timeout=60)

        def rd(n):
            p = os.path.join(d, n)
            return open(p).read().split("\n")[:-1] if os.path.exists(p) else []
        return r, rd("calls.log"), rd("sleeps.log")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# 1. setup server, restart, real server
r, calls, sleeps = run_block(True)
check(r.returncode == 0 and "BLOCK-DONE" in r.stdout, f"1: first start with restart -> the block goes on (exit {r.returncode}, {r.stderr[-300:]!r})")
ready = [c for c in calls if c.startswith("exec") and "pg_isready" in c]
check(ready and all(" -h 127.0.0.1 " in f" {c} " for c in ready), f"1: pg_isready -h 127.0.0.1 on every call ({ready})")
check(len(ready) == 4, f"1: ready only at the 4th check, after the restart ({len(ready)} checks)")

# 2. no fixed pause
check("1" not in sleeps, f"2: no fixed 'sleep 1', only the loop's pauses ({sleeps})")
check(all(s == "0.5" for s in sleeps), f"2: the pauses are the loop's 0.5 s ({sleeps})")

# 3. never ready: red, with the log
r, calls, sleeps = run_block(False)
check(r.returncode != 0 and "BLOCK-DONE" not in r.stdout, f"3: database never ready -> start.sh stops (exit {r.returncode})")
check("STUB-LOG" in r.stderr and "not ready over TCP" in r.stderr, f"3: says why and prints the container log ({r.stderr[-300:]!r})")

# 4. the health check of docker-compose.yml
with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
    dc = f.read()
db = dc.split("\n  db:\n", 1)[1] if "\n  db:\n" in dc else ""
m = re.search(r"healthcheck:\s*\n\s*test:\s*(\[.*\])", db)
check(m and "pg_isready" in m.group(1) and "-h 127.0.0.1" in m.group(1), f"4: compose db health check over TCP ({m and m.group(1)})")

sys.exit(done("p2728_db_ready_tcp"))
