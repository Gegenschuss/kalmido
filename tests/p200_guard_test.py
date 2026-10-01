#!/usr/bin/env python3
"""2.0.0 (#279): Kalmido never creates a new, empty database on top of existing data. A data dir with the marker file,
attachments or backups but a missing, empty, unreadable or damaged tasks.db makes the container REFUSE to start (exit code 3,
clear log line) instead of starting empty (whose first visitor would become the admin). An empty data dir starts fresh and
gets the marker; an existing install without the marker (1.x) gets it on its first start.
Starts its OWN test container (start.sh).
usage: p200_guard_test.py <datadir>"""
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
DBF = os.path.join(DATA, "tasks.db")
MARK = os.path.join(DATA, ".kalmido-initialized")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def up(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CT], capture_output=True, text=True).stdout.strip()
        if st == "false":
            return False
        time.sleep(0.5)
    return False


def exited():
    """(exit code, logs) once the container stopped by itself (or None after 30 s)."""
    t0 = time.time()
    while time.time() - t0 < 30:
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", CT], capture_output=True, text=True).stdout.split()
        if st and st[0] == "false":
            return int(st[1]), subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stdout
        time.sleep(0.5)
    return None, ""


def stop():
    subprocess.run(["docker", "stop", "-t", "5", CT], capture_output=True)


def start():
    subprocess.run(["docker", "start", CT], capture_output=True)


def db_files(suffix_from="", suffix_to=".away"):
    for s in ("", "-wal", "-shm"):
        p = DBF + s
        if os.path.exists(p + suffix_from):
            os.rename(p + suffix_from, p + suffix_to)


subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA, exist_ok=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

# ---- empty data dir: a fresh install, marker written
check(os.path.exists(MARK), "fresh install writes the marker")
s = requests.Session()
s.headers.update(H)
check(s.post(B + "/api/auth/setup", json={"username": "alice", "password": "password123"}).ok, "setup")
tid = s.post(B + "/api/tasks", json={"title": "keep me"}).json()["id"]
check(s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("a.txt", b"data")}, headers=H).ok, "an attachment")

# ---- database missing, marker there: refuse
stop()
db_files()
start()
code, logs = exited()
check(code == 3 and "Refusing to start" in logs and "is missing" in logs, f"missing tasks.db: refused (exit {code})")
check(not os.path.exists(DBF) or os.path.getsize(DBF) == 0, "no new database was created")
# ---- also without the marker (attachments are data)
os.rename(MARK, MARK + ".away")
start()
code, logs = exited()
check(code == 3, f"missing tasks.db, no marker but attachments: refused (exit {code})")
os.rename(MARK + ".away", MARK)
# ---- empty file
if os.path.exists(DBF):
    os.remove(DBF)
open(DBF, "wb").close()
start()
code, logs = exited()
check(code == 3 and "is empty" in logs, f"empty tasks.db: refused (exit {code})")
os.remove(DBF)
# ---- garbage / damaged file
shutil.copy(DBF + ".away", DBF + ".copy")
with open(DBF, "wb") as f:
    f.write(b"\x00garbage, not a database" * 400)
start()
code, logs = exited()
check(code == 3 and "Refusing to start" in logs, f"damaged tasks.db: refused (exit {code})")
os.remove(DBF)
# ---- a real database with a damaged page
with open(DBF + ".copy", "rb") as f:
    raw = bytearray(f.read())
if len(raw) > 8192:
    raw[4096:8192] = b"\xff" * 4096
with open(DBF, "wb") as f:
    f.write(raw)
start()
code, logs = exited()
check(code == 3, f"database with a damaged page: refused (exit {code})")
os.remove(DBF)
os.remove(DBF + ".copy")
# ---- the real one back: starts, data intact
db_files(".away", "")
start()
check(up(), "original database back: starts")
s = requests.Session()
s.headers.update(H)
s.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"})
check(any(t["id"] == tid for t in s.get(B + "/api/state").json()["tasks"]), "data intact")
# ---- an install from before 2.0 (no marker): gets it on the first start
stop()
os.remove(MARK)
start()
check(up() and os.path.exists(MARK), "existing install without the marker: starts and writes it")

stop()
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"p200_guard: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
