#!/usr/bin/env python3
"""2.116.0 API tests, part A (#2063): the trash period of tasks, own container (start.sh). Invented names only.
 - the run (tasks/tasktrash.py ttp_tick, called in the container with force=True like the watchdog does hourly):
   switch off (default) = nothing deleted, the counts are right (tasks, attachments)
 - switch on (KALMIDO_PURGE_TRASH=1 for that run): a task older than the period goes with its comment, field value,
   subtask and the attachment file on disk; 29 days old stays; restored stays; a task in another owner's shared list goes
   too; an organisation task goes; a time entry of a deleted task stays (only the link goes); a subtask restored on its
   own stays
 - GET /api/tasks?scope=trash says the period (`days`)
 - a person without an organisation (freelancer-matrix: tasks): the private trash follows the same period
usage: p2116_a_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2116A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
FEAT = "collab,comments,fields,office,clients,time"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
c = dbx.connect(DATA)


def tick(on):
    """One run of the task trash, as the watchdog does it (force: no hourly wait). -> the counts."""
    env = ["-e", "KALMIDO_PURGE_TRASH=1"] if on else []
    code = ("import json, app\nfrom kalmido.tasks.tasktrash import ttp_tick\nc = app.connect()\n"
            "try:\n    print(json.dumps(ttp_tick(c, force=True)))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", *env, CT, "python", "-c", code], capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-600:]}")
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def trash(s, tid):
    r = s.delete(B + f"/api/tasks/{tid}")
    check(r.ok, f"to the trash {tid} {r.text[:120]}")


def age(tid, days):
    """deleted_at of the task (and its subtasks trashed with it) moves days into the past."""
    ts = c.execute("SELECT to_char((now() at time zone 'utc') - make_interval(days => ?), 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"')",
                   (days,)).fetchone()[0]
    c.execute("UPDATE tasks SET deleted_at=? WHERE deleted_at IS NOT NULL AND (id=? OR parent_id=?)", (ts, tid, tid))


def exists(tid):
    return bool(c.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone())


# ---------------------------------------------------------------- the setting up
PRIV = A.post(B + "/api/lists", json={"name": "Home", "org_id": None}).json()["id"]
ORGL = A.post(B + "/api/lists", json={"name": "Work", "org_id": 1}).json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Bob's list", "org_id": None}).json()["id"]  # another owner's list, shared with alice
check(Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": 1, "role": "edit"}).ok, "setup: bob shares his list with alice")
r = A.post(B + f"/api/lists/{PRIV}/fields", json={"name": "Amount", "type": "number"})
check(r.ok, "setup: a field " + r.text[:120])
FID = r.json().get("id")

OLD = task(A, PRIV, "Old one", fields={str(FID): "12"})
SUB = task(A, PRIV, "Its subtask", parent_id=OLD)
check(A.post(B + f"/api/tasks/{OLD}/comments", json={"body": "a comment"}).ok, "setup: a comment")
r = A.post(B + f"/api/tasks/{OLD}/attachments", files={"file": ("note.txt", b"invented content", "text/plain")})
check(r.ok, "setup: an attachment " + r.text[:120])
APATH = (c.execute("SELECT path FROM attachments WHERE task_id=?", (OLD,)).fetchone() or [""])[0]
AFILE = os.path.join(DATA, "attachments", APATH)
check(APATH and os.path.isfile(AFILE), f"setup: the attachment is on disk {AFILE}")
YOUNG = task(A, PRIV, "29 days")
BACK = task(A, PRIV, "Restored")
FOREIGN = task(Bo, BL, "In bob's shared list")
ORGT = task(A, ORGL, "Organisation task")
LIVE = task(A, PRIV, "Not in the trash")
for t in (OLD, YOUNG, BACK, ORGT):
    trash(A, t)
trash(A, FOREIGN)  # alice puts it into the trash; "Empty" would leave it to bob, the period does not
for t in (OLD, BACK, FOREIGN, ORGT):
    age(t, 31)
age(YOUNG, 29)
check(A.post(B + f"/api/tasks/{BACK}/restore").ok, "setup: restored before the run")
age_back = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (BACK,)).fetchone()[0]
check(age_back is None, "setup: the restored task is out of the trash")
# ---------------------------------------------------------------- the trash says the period
j = A.get(B + "/api/tasks?scope=trash").json()
check(j.get("days") == 30, f"#2063: the trash says the period: {j.get('days')}")

# ---------------------------------------------------------------- switch off (default): count only
n = tick(False)
check(n.get("tasks") == 4 and n.get("attachments") == 1, f"#2063: dry run counts OLD + SUB + FOREIGN + ORGT and 1 file: {n}")
check(all(exists(t) for t in (OLD, SUB, YOUNG, BACK, FOREIGN, ORGT, LIVE)) and os.path.isfile(AFILE), "#2063: dry run deletes nothing")

# ---------------------------------------------------------------- switch on
n = tick(True)
check(n.get("tasks") == 4 and n.get("attachments") == 1, f"#2063: the run deletes 4 tasks and 1 file: {n}")
check(not exists(OLD) and not exists(SUB), "#2063: the old task and its subtask are gone")
check(not os.path.isfile(AFILE), "#2063: the attachment file is gone from disk")
check(c.execute("SELECT COUNT(*) FROM comments WHERE task_id=?", (OLD,)).fetchone()[0] == 0, "#2063: its comment is gone")
check(c.execute("SELECT COUNT(*) FROM task_field_values WHERE task_id=?", (OLD,)).fetchone()[0] == 0, "#2063: its field value is gone")
check(c.execute("SELECT COUNT(*) FROM attachments WHERE task_id=?", (OLD,)).fetchone()[0] == 0, "#2063: its attachment row is gone")
check(exists(YOUNG), "#2063: 29 days in the trash stays")
check(exists(BACK) and exists(LIVE), "#2063: restored / live tasks stay")
check(not exists(FOREIGN), "#2063: a task in another owner's shared list goes too")
check(not exists(ORGT), "#2063: an organisation task goes")
j = A.get(B + "/api/tasks?scope=trash").json()
check([t["id"] for t in j["tasks"]] == [YOUNG], f"#2063: only the young one is left in the trash: {[t['id'] for t in j['tasks']]}")
n = tick(True)
check(n.get("tasks", 0) == 0, f"#2063: a second run finds nothing: {n}")

# ---------------------------------------------------------------- a subtask restored on its own stays (detached)
P = task(A, PRIV, "Parent")
K = task(A, PRIV, "Kid", parent_id=P)
trash(A, P)
age(P, 40)
check(A.post(B + f"/api/tasks/{K}/restore").ok, "setup: the kid comes back on its own")
tick(True)
r = c.execute("SELECT parent_id, deleted_at FROM tasks WHERE id=?", (K,)).fetchone()
check(not exists(P) and r is not None and r["deleted_at"] is None and r["parent_id"] is None,
      f"#2063: the restored subtask stays, top level: {dict(r) if r else None}")

# ---------------------------------------------------------------- legal retention: a time entry of a deleted task stays
TT = task(A, PRIV, "Billed work")
r = A.post(B + "/api/time/entries", json={"task_id": TT, "start": "2026-10-01T08:00:00+00:00", "minutes": 60, "note": "invented"})
if r.ok:
    TE = r.json().get("id")
    trash(A, TT)
    age(TT, 31)
    tick(True)
    row = c.execute("SELECT task_id FROM time_entries WHERE id=?", (TE,)).fetchone()
    check(not exists(TT) and row is not None and row["task_id"] is None, "#2063: the time entry stays, only the link goes")
else:
    print("note: no time entry route in this shape:", r.status_code, r.text[:120])

# ---------------------------------------------------------------- freelancer-matrix: tasks
FIDF, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Own", "org_id": None}).json()["id"]
FT = task(Fr, FL, "Freelancer old")
FY = task(Fr, FL, "Freelancer young")
trash(Fr, FT)
trash(Fr, FY)
age(FT, 31)
j = Fr.get(B + "/api/tasks?scope=trash").json()
check(j.get("days") == 30 and {t["id"] for t in j["tasks"]} == {FT, FY}, f"freelancer: the private trash with the period {j.get('days')}")
tick(True)
j = Fr.get(B + "/api/tasks?scope=trash").json()
check([t["id"] for t in j["tasks"]] == [FY] and not exists(FT), "freelancer: the old task is gone, the young one stays")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
