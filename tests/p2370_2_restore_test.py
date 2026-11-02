#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.370.2 (#2779): a restore and the work around it.
 - queue rows and the pushes after a request go through the maintenance gate: they wait while a restore runs, a restore waits
   for them, a thread already inside never waits for itself, and a row a restore took away never runs after it.
 - Backups names folders a hard stop left behind (also as an alert at the start); a successful restore removes them, except
   files the archive does not bring.
 - a failed swap brings the attachments back (the old folder when the new one never came in; a fresh instance is clean again).
 - attachments or office folder as a mount of its own: refused before anything changes, with a clear message.
freelancer-matrix: backup (instance-wide admin function, no organisation involved)
usage: p2370_2_restore_test.py <datadir>"""
import json
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
    return subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json, os, threading, time\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


def until_done(s):
    j, t0 = {}, time.time()
    while time.time() - t0 < 60:  # until the run has ended with a result
        j = s.get(B + "/api/admin/backups").json()
        if not j["running"]:
            return j
        time.sleep(0.2)
    return j


def wait_alert(s, word, wait=75):
    t0 = time.time()
    while time.time() - t0 < wait:
        if word in str(s.get(B + "/api/admin/alerts").json().get("items")):
            return True
        time.sleep(0.5)
    return False


assert start(), "first start"
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})

# ---- the gate
res = in_app("""
from kalmido.accounts.session import GATE, gated_thread
out = {}
# a thread inside goes in again while a restore waits for it
GATE.enter(True)
GATE.maint = True
out["nested"] = GATE.enter(False)
GATE.leave()
GATE.maint = False
GATE.leave()
# the push waits for the end of the maintenance
ran = threading.Event()
out["begin"] = GATE.begin(own=0, timeout=5)
gated_thread(ran.set)
out["push_during"] = ran.wait(0.5)
GATE.end()
out["push_after"] = ran.wait(5)
# a restore waits for work inside
go, inside = threading.Event(), threading.Event()
def job():
    with GATE.work():
        inside.set()
        go.wait(10)
threading.Thread(target=job, daemon=True).start()
inside.wait(5)
out["begin_busy"] = GATE.begin(own=0, timeout=0.3)
go.set()
out["begin_free"] = GATE.begin(own=0, timeout=5)
GATE.end()
print(json.dumps(out))
""")
out = json.loads(res) if res.startswith("{") else {}
check(out.get("nested") is True, f"a thread inside never waits for itself: {res}")
check(out.get("begin") and out.get("push_during") is False and out.get("push_after"), f"the pushes after a request wait for the end of a restore: {res}")
check(out.get("begin_busy") is False and out.get("begin_free"), f"a restore waits for work inside the gate: {res}")

res = in_app("""
from kalmido.accounts import bgjobs
from kalmido.accounts.session import GATE
from kalmido.core.db import connect, insert_id
from kalmido.core.pg import system_ctx
ran = []
bgjobs.bgj_fn("test:gate")(lambda x: ran.append(x))
bgjobs.bgj_fn("test:nogate", gate=False)(lambda x: ran.append(x))
c = connect()
def row(kind):
    with system_ctx(c):
        rid = insert_id(c, "INSERT INTO bg_jobs(kind, payload, state, attempts, created_at, run_after) VALUES(?, '', 'run', 1, '2026-01-01', '2026-01-01')", (kind,))
    c.commit()
    return rid
out = {}
GATE.begin(own=0, timeout=5)
keep, gone = row("test:gate"), row("test:gate")
t1 = threading.Thread(target=bgjobs._run, args=(keep, "test:gate", ["kept"], 1), daemon=True)
t2 = threading.Thread(target=bgjobs._run, args=(gone, "test:gate", ["gone"], 1), daemon=True)
free = threading.Thread(target=bgjobs._run, args=(row("test:nogate"), "test:nogate", ["free"], 1), daemon=True)
bgjobs._SLOTS["busy"] += 3
t1.start(); t2.start(); free.start()
free.join(5)
time.sleep(0.3)
out["during"] = sorted(ran)
with system_ctx(c):
    c.execute("DELETE FROM bg_jobs WHERE id=?", (gone,))
c.commit()
GATE.end()
t1.join(5); t2.join(5)
out["after"] = sorted(ran)
print(json.dumps(out))
""")
out = json.loads(res) if res.startswith("{") else {}
check(out.get("during") == ["free"], f"a queue row waits while a restore runs (a kind with gate=False does not): {res}")
check(out.get("after") == ["free", "kept"], f"after the restore the row runs, one the restore took away does not: {res}")

# ---- leftovers
assert A.post(B + "/api/admin/backups").status_code == 202
j = until_done(A)
assert j["items"], j
NAME = j["items"][0]["name"]
check(j.get("leftovers") == [], f"no leftovers on a clean server: {j.get('leftovers')}")
res = in_app("""
from kalmido.core.config import ATT_DIR, OFFICE_DIR
for p, f in ((ATT_DIR + ".pre-restore-aaaa", "old.txt"), (OFFICE_DIR + ".pre-restore-bbbb", None), (ATT_DIR + ".restore-cccc", "half.txt")):
    os.makedirs(os.path.join(p, "x"), exist_ok=True)
    if f:
        open(os.path.join(p, "x", f), "w").write("x")
print("ok")
""")
check(res == "ok", f"leftovers laid out: {res}")
assert start(KEEP="1"), "start with leftovers"
A = sess("alice")
left = A.get(B + "/api/admin/backups").json().get("leftovers") or []
check(len(left) == 3 and any(".pre-restore-aaaa" in x for x in left), f"Backups names the leftovers: {left}")
check(wait_alert(A, "pre-restore-aaaa"), "the start raises an alert for the admins")

# ---- own mount: nothing changes
assert start(["-e KALMIDO_TEST_BK_OWN_MOUNT=1"], KEEP="1"), "start with a mount of its own"
A = sess("alice")
r = A.post(B + "/api/admin/backups/restore", json={"password": "password123", "confirm": "RESTORE", "name": NAME})
check(r.status_code >= 400 and "mount" in r.text, f"a folder that is a mount is refused with a clear message: {r.status_code} {r.text[:160]}")
check(len(A.get(B + "/api/admin/backups").json().get("leftovers") or []) == 3, "refused: nothing changed")

# ---- failed swap: the old folder comes back
assert start(KEEP="1"), "start again"
A = sess("alice")
res = in_app(f"""
from kalmido.admin import backup as bk
from kalmido.core.config import ATT_DIR
open(os.path.join(ATT_DIR, "marker.txt"), "w").write("old")
real = os.rename
def rename(a, b):
    if b == ATT_DIR and ".restore-" in a and ".pre-restore-" not in a:
        raise OSError(18, "Invalid cross-device link")
    real(a, b)
bk.os.rename = rename
try:
    bk.bk_restore(bk.bk_path({NAME!r}), "", "alice", "session")
    code = "no error"
except bk.BackupError as e:
    code = e.code
bk.os.rename = real
there = os.path.isfile(os.path.join(ATT_DIR, "marker.txt"))
os.remove(os.path.join(ATT_DIR, "marker.txt"))
print(json.dumps([code, there, len(bk.bk_leftovers())]))
""")
check(res == '["restore", true, 3]', f"the attachments folder is back when the new one never came in: {res}")

# ---- a good restore cleans up
r = A.post(B + "/api/admin/backups/restore", json={"password": "password123", "confirm": "RESTORE", "name": NAME})
check(r.ok, f"restore: {r.status_code} {r.text[:200]}")
A = sess("alice")
left = A.get(B + "/api/admin/backups").json().get("leftovers")
# old.txt in the attachments folder of before is not in the archive: kept, like the folder of a normal restore
check(len(left) == 1 and ".pre-restore-aaaa" in left[0], f"a good restore removes the leftovers, files the archive does not bring stay: {left}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
