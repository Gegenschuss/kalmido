#!/usr/bin/env python3
"""2.0.0 (#279): Kalmido never creates a new, empty database on top of existing data. A data dir with the marker file,
attachments or backups but an empty database (2.37.0: Postgres; or an old SQLite tasks.db not moved yet) makes the container REFUSE to start (exit code 3,
clear log line) instead of starting empty (whose first visitor would become the admin). An empty data dir starts fresh and
gets the marker; an existing install without the marker (1.x) gets it on its first start. 2.37.0: a database whose schema
version is newer than the image's is refused too (exit code 3).
Starts its OWN test container (start.sh).
usage: p200_guard_test.py <datadir>"""
import os
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
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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

# 2.37.0 (#1150): the database is Postgres now. "tasks.db missing / empty" -> the Postgres database is empty (its schema
# moved aside). 2.37: no SQLite file any more (the cases of a damaged / unreadable tasks.db are gone with it; an old tasks.db
# next to an empty database is refused below, the move tool checks old files).
def psql(sql):
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    return subprocess.run(["docker", "exec", dbc, "psql", "-U", "kalmido", "-d", dbn, "-v", "ON_ERROR_STOP=1", "-Atqc", sql],
                          capture_output=True, text=True)


def db_aside():
    r = psql("ALTER SCHEMA public RENAME TO guard_away; CREATE SCHEMA public;")
    assert r.returncode == 0, r.stderr


def db_back():
    r = psql("DROP SCHEMA public CASCADE; ALTER SCHEMA guard_away RENAME TO public;")
    assert r.returncode == 0, r.stderr


def tables():
    return int(psql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").stdout.strip() or 0)


# ---- database empty, marker there: refuse
stop()
db_aside()
start()
code, logs = exited()
check(code == 3 and "Refusing to start" in logs and "Kalmido data" in logs, f"empty database, marker: refused (exit {code})")
check(tables() == 0, "no new database was created")
# ---- also without the marker (attachments are data)
os.rename(MARK, MARK + ".away")
start()
code, logs = exited()
check(code == 3 and tables() == 0, f"empty database, no marker but attachments: refused (exit {code})")
os.rename(MARK + ".away", MARK)
# ---- a SQLite database from before 2.37 that was not moved yet next to an empty database: refuse
with open(DBF, "wb") as f:
    f.write(b"SQLite format 3\x00" + b"\x00" * 4096)
start()
code, logs = exited()
check(code == 3 and "SQLite database from before 2.37" in logs and tables() == 0, f"old tasks.db + empty database: refused (exit {code})")
os.remove(DBF)

# ---- the real one back: starts, data intact
db_back()
start()
check(up(), "original database back: starts")
s = requests.Session()
s.headers.update(H)
s.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"})
check(any(t["id"] == tid for t in s.get(B + "/api/state").json()["tasks"]), "data intact")
# ---- 2.37.0 (#1150): a database a newer version already migrated (kalmido_meta.schema_version above this image's): refuse
stop()
ver = psql("SELECT value FROM kalmido_meta WHERE key='schema_version'").stdout.strip()
check(ver.isdigit(), f"schema version stored ({ver!r})")
psql("UPDATE kalmido_meta SET value='999' WHERE key='schema_version'")
start()
code, logs = exited()
check(code == 3 and "database schema 999 is newer than this version" in logs, f"newer schema: refused (exit {code})")
psql(f"UPDATE kalmido_meta SET value='{ver}' WHERE key='schema_version'")
start()
check(up(), "schema version back: starts")
# ---- an install from before 2.0 (no marker): gets it on the first start
stop()
os.remove(MARK)
start()
check(up() and os.path.exists(MARK), "existing install without the marker: starts and writes it")

stop()
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"p200_guard: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
