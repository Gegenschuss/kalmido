#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.359.3: the backup checks of package 2.359.3, each against a real server.
 - #2945: pg_dump older than the database server: "Back up now" stops with its own code, Admin > Server (about) and an admin
   alert name it; with a matching pg_dump everything is clear again. KALMIDO_TEST_PG_DUMP_VERSION plays the older tool.
freelancer-matrix: backup (instance-wide admin function, no organisation involved)
usage: p2359_3_backup_test.py <datadir>"""
import os
import subprocess
import sys
import time

from kt import FAILS, OKS, check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BASE = ["-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_BACKUPS=1"]


def start(extra=(), **env):
    e = dict(os.environ, KALMIDO_ADMIN_ALERTS="1", EXTRA=" ".join(BASE + list(extra)), **env)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    return r.returncode == 0


def until_done(s):
    j, t0 = {}, time.time()
    while time.time() - t0 < 60:  # until the run has ended with a result
        j = s.get(B + "/api/admin/backups").json()
        if not j["running"]:
            return j
        time.sleep(0.2)
    return j


def wait_alert(s, word):
    t0 = time.time()
    while time.time() - t0 < 75:
        if word in str(s.get(B + "/api/admin/alerts").json().get("items")):
            return True
        time.sleep(0.5)
    return False


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-300:]


# ---- #2945
assert start(), "first start"
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
check(A.get(B + "/api/about").json().get("backup_tools_problem") == "", "#2945: the real pg_dump fits the server, no message")
res = in_app("from kalmido.admin.backup import bk_tools_majors\nfrom kalmido.core.db import connect\nc = connect()\nprint(json.dumps(bk_tools_majors(c)))\nc.close()")
check(res == "[17, 17]", f"#2945: the versions of the real pg_dump and the server are read: {res}")
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"#2945: back up now accepted ({r.status_code})")
j = until_done(A)
check(not j.get("last_error") and len(j.get("items", [])) == 1, f"#2945: the real tools write a backup: {j.get('last_error')}")

assert start(["-e KALMIDO_TEST_PG_DUMP_VERSION=16.4"], KEEP="1"), "start with the older tool"
A = sess("alice")
ab = A.get(B + "/api/about").json()
check(str(ab.get("backup_tools_problem", "")).startswith("16|"), f"#2945: Admin > Server names the older pg_dump from the start on: {ab.get('backup_tools_problem')}")
check(sess().get(B + "/api/about").json().get("backup_tools_problem") is None, "#2945: only admins see it")
check(wait_alert(A, "pg_dump 16"), "#2945: an admin alert names it at the start")
before = len(A.get(B + "/api/admin/backups").json()["items"])
A.post(B + "/api/admin/backups")
j = until_done(A)
check("pg_dump 16" in (j.get("last_error") or "") and len(j["items"]) == before, f"#2945: the backup stops with the clear message, nothing written: {j.get('last_error')}")

assert start(KEEP="1"), "start with the real tool again"
A = sess("alice")
check(A.get(B + "/api/about").json().get("backup_tools_problem") == "", "#2945: the next start with a fitting tool clears the message")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
