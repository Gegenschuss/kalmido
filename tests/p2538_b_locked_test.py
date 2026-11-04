#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.538.0 part B (#4372): the three free texts the lock per project cannot encrypt -- a time entry's note, the project's
status note and its description -- never stay in plain text in a locked project. Own container (start.sh), invented names.
 - switching the lock on (start / todo / bulk / finish -> le2b_scrub) empties them for good: the time entries' notes of the
   project and its tasks, the status note (also in the status history), the description and its earlier versions
 - afterwards the server refuses them with 409 list_e2e_plain (like the waiting note): new status with a note, a description,
   a time entry with a note (new, timer start, change, moving a noted entry in); the same without text still works
 - an open project of the same person keeps and accepts all three
 - review 2646 finding 2: an agent's time proposal (agents/agenttime.py) brings no note in: applying it 409, with the
   note emptied ok; redoing an entry undone before the lock 409
 - review 2646 finding 1: a project locked before 2.538 (e2e 'on' without the scrub) loses the three texts once at the next
   start (core/db.py, migr_e2efree4372; one way); the open project keeps them
 - everything as a person without an organisation (freelancer-matrix: lists, time)
usage: p2538_b_locked_test.py <datadir>      (P2538BL_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
MK = "Zqxw"  # every marker text starts with it


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def time_prop(aid, uid, note):
    """2.538.0 (#4372, review 2646 finding 2): a ready time proposal of agent aid for uid, one entry on task T with a note
    (straight into the table: the agent proposed it before the lock went on; its job names no list, so the scrub keeps it)."""
    day = (datetime.now() - timedelta(days=1)).date().isoformat()
    prop = {"items": [{"date": day, "start": "08:00", "end": "08:30", "task_id": T, "list_id": L, "title": "Locked task",
                       "note": note, "event_id": None}]}
    ts = datetime.now().isoformat(timespec="seconds") + "Z"
    return dbx("INSERT INTO agent_jobs(agent_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,proposal) "
               "VALUES(?,?,'Time from the calendar','waiting','',?,?,'time',?,'ready',?) RETURNING id",
               (aid, uid, ts, ts, json.dumps({"user_id": uid}), json.dumps(prop)), write=True)[0][0]


def cipher(n=0):
    """A synthetic ciphertext of generation 1 (only its shape is right; nobody can open it)."""
    return "e2e1:" + json.dumps({"v": 1, "g": 1, "iv": "A" * 15 + "BCDEFGHIJ"[n % 9], "ct": "Q" * (40 + 4 * n)}, separators=(",", ":"))


def keys():
    b64 = lambda n: base64.b64encode(os.urandom(n)).decode()  # noqa: E731
    b64u = lambda n: base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")  # noqa: E731
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def wrapped():
    return {"v": 1, "iv": base64.b64encode(os.urandom(12)).decode(), "ct": base64.b64encode(os.urandom(48)).decode()}


def plain_refused(r, what):
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == 409 and j.get("code") == "list_e2e_plain", f"locked: {what} refused 409 list_e2e_plain ({r.status_code} {r.text[:160]})")


if os.environ.get("P2538BL_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "time"]})
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- before: both projects carry all three texts
L = Fr.post(B + "/api/lists", json={"name": "Strongbox", "org_id": None, "time_tracking": True}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Open one", "org_id": None, "time_tracking": True}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"list_id": L, "title": "Locked task"}).json()["id"]
T2 = Fr.post(B + "/api/tasks", json={"list_id": L2, "title": "Open task"}).json()["id"]
start = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
for lid, tid, tag in ((L, T, "L"), (L2, T2, "O")):
    check(Fr.post(B + f"/api/lists/{lid}/status", json={"status": "at_risk", "note": MK + tag + "Status"}).ok, f"setup {tag}: a status with a note")
    check(Fr.patch(B + f"/api/lists/{lid}/overview", json={"description": MK + tag + "DescOld"}).ok, f"setup {tag}: a description")
    check(Fr.patch(B + f"/api/lists/{lid}/overview", json={"description": MK + tag + "Desc"}).ok, f"setup {tag}: a newer description")
    r = Fr.post(B + "/api/time/entries", json={"task_id": tid, "start": start, "minutes": 20, "note": MK + tag + "TaskTime"})
    check(r.ok, f"setup {tag}: a time entry with a note on the task ({r.text[:120]})")
    r = Fr.post(B + "/api/time/entries", json={"list_id": lid, "start": start, "minutes": 10, "note": MK + tag + "ListTime"})
    check(r.ok, f"setup {tag}: a time entry with a note on the project ({r.text[:120]})")
check(dbx("SELECT COUNT(*) FROM list_activity WHERE list_id=? AND kind='desc'", (L,))[0][0] >= 1, "setup: the earlier description is kept")
MOVE = Fr.post(B + "/api/time/entries", json={"task_id": T2, "start": start, "minutes": 5, "note": MK + "Mover"}).json()["id"]
# finding 2: an agent's time proposals, waiting (J1) and applied + undone (J2) before the lock
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "clock", "display_name": "Clock"})
check(r.status_code in (200, 201), f"setup: an agent ({r.status_code} {r.text[:160]})")
AGID = r.json().get("agent", r.json()).get("id")
J1, J2 = time_prop(AGID, FID, MK + "LAgentNew"), time_prop(AGID, FID, MK + "LAgentRedo")
r = Fr.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]})
check(r.ok, f"setup: the open time proposal applied before the lock ({r.status_code} {r.text[:160]})")
r = Fr.post(B + f"/api/proposals/{J2}/undo")
check(r.ok, f"setup: and undone ({r.status_code} {r.text[:160]})")

# ---- the switch through part A's routes (start, todo / bulk, finish -> le2b_scrub)
check(Fr.put(B + "/api/e2e/keys", json=keys()).ok, "the person's own keys are set up")
r = Fr.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": FID, "wrapped": wrapped()}]})
check(r.ok, f"switch on (start) {r.status_code} {r.text[:300]}")
k = 0
for _ in range(10):
    todo = Fr.get(B + f"/api/lists/{L}/e2e/todo?limit=200").json()
    out = {}
    for kind in ("tasks", "comments", "notes", "sections"):
        rows = []
        for x in todo.get(kind) or []:
            y = {"id": x["id"]}
            for f, v in x.items():
                if f != "id" and v is not None:
                    k += 1
                    y[f] = cipher(k)
            rows.append(y)
        if rows:
            out[kind] = rows
    if todo.get("fields"):
        out["fields"] = [{"task_id": x["task_id"], "field_id": x["field_id"], "value": cipher(1)} for x in todo["fields"]]
    if not out:
        break
    check(Fr.post(B + f"/api/lists/{L}/e2e/bulk", json=out).ok, "bulk")
r = Fr.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] == "on", f"finish: the lock is on {r.status_code} {r.text[:300]}")

# ---- what switching on emptied (for good) -- and what the open project kept
check(not dbx("SELECT id FROM time_entries WHERE note<>'' AND (list_id=? OR task_id=?)", (L, T)), "scrub: no time entry note of the locked project")
lr = dbx("SELECT status, status_note, description FROM lists WHERE id=?", (L,))[0]
check(lr[0] == "at_risk" and lr[1] == "" and lr[2] == "", f"scrub: status kept, its note and the description empty {tuple(lr)}")
check(not dbx("SELECT id FROM list_status WHERE list_id=? AND note<>''", (L,)), "scrub: the status history keeps no note")
check(not dbx("SELECT id FROM list_activity WHERE list_id=? AND kind='desc'", (L,)), "scrub: no earlier description")
check(not [x for x in dbx("SELECT note FROM time_entries") + dbx("SELECT status_note FROM lists") + dbx("SELECT description FROM lists")
           + dbx("SELECT note FROM list_status") + dbx("SELECT data::text FROM list_activity") if str(x[0]).startswith(MK + "L")],
      "scrub: no marker text of the locked project anywhere in these tables")
o = dbx("SELECT status_note, description FROM lists WHERE id=?", (L2,))[0]
check(o[0] == MK + "OStatus" and o[1] == MK + "ODesc", f"the open project keeps its texts {tuple(o)}")
check(len(dbx("SELECT id FROM time_entries WHERE note LIKE ? AND list_id=?", (MK + "O%", L2))) == 2, "the open project keeps its time notes")
check(dbx("SELECT note FROM time_entries WHERE id=?", (MOVE,))[0][0] == MK + "Mover", "the entry still in the open project keeps its note")

# ---- afterwards: the server refuses the three texts in the locked project (and takes them without text)
plain_refused(Fr.post(B + f"/api/lists/{L}/status", json={"status": "on_track", "note": "plain"}), "a status note")
check(Fr.post(B + f"/api/lists/{L}/status", json={"status": "on_track"}).ok, "locked: a status without a note works")
plain_refused(Fr.patch(B + f"/api/lists/{L}/overview", json={"description": "plain"}), "a description")
check(Fr.patch(B + f"/api/lists/{L}/overview", json={"description": ""}).ok, "locked: an empty description is fine")
plain_refused(Fr.post(B + "/api/time/entries", json={"task_id": T, "start": start, "minutes": 5, "note": "plain"}), "a new time entry with a note")
plain_refused(Fr.post(B + "/api/time/entries", json={"list_id": L, "start": start, "minutes": 5, "note": "plain"}), "a project time entry with a note")
r = Fr.post(B + "/api/time/entries", json={"task_id": T, "start": start, "minutes": 5})
check(r.ok, f"locked: a time entry without a note works ({r.text[:120]})")
EID = r.json().get("id")
plain_refused(Fr.patch(B + f"/api/time/entries/{EID}", json={"note": "plain"}), "a note added to an entry")
check(Fr.patch(B + f"/api/time/entries/{EID}", json={"minutes": 6}).ok, "locked: changing an entry without a note works")
plain_refused(Fr.patch(B + f"/api/time/entries/{MOVE}", json={"task_id": T}), "moving a noted entry into it")
check(Fr.patch(B + f"/api/time/entries/{MOVE}", json={"task_id": T, "note": ""}).ok, "locked: moving it in with the note emptied works")
plain_refused(Fr.post(B + "/api/time/start", json={"task_id": T, "note": "plain"}), "a timer start with a note")
r = Fr.post(B + "/api/time/start", json={"task_id": T})
check(r.ok, f"locked: a timer start without a note works ({r.text[:120]})")
run = (r.json().get("timer") or {}).get("id") or (r.json().get("entry") or {}).get("id")
if run:
    plain_refused(Fr.patch(B + f"/api/time/entries/{run}", json={"note": "plain"}), "a note on the running timer")
check(Fr.post(B + "/api/time/stop", json={}).ok, "the timer stops")

# ---- finding 2: the agent's time proposal brings no note into the locked project
plain_refused(Fr.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}), "an agent's time proposal with a note")
check(not dbx("SELECT id FROM time_entries WHERE note LIKE ?", (MK + "LAgent%",)), "agent proposal: no entry with its note")
r = Fr.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"], "edits": {"0": {"note": ""}}})
check(r.ok, f"agent proposal: with the note emptied it applies ({r.status_code} {r.text[:160]})")
plain_refused(Fr.post(B + f"/api/proposals/{J2}/redo"), "redoing an agent's entry with a note")

# ---- the open project: all three still work
check(Fr.post(B + f"/api/lists/{L2}/status", json={"status": "on_track", "note": "fine"}).ok, "open: a status note works")
check(Fr.patch(B + f"/api/lists/{L2}/overview", json={"description": "fine"}).ok, "open: a description works")
check(Fr.post(B + "/api/time/entries", json={"task_id": T2, "start": start, "minutes": 5, "note": "fine"}).ok, "open: a time note works")
check(not [x for x in dbx("SELECT note FROM time_entries WHERE list_id=? OR task_id=?", (L, T)) if x[0]], "no time note in the locked project at the end")

# ---- finding 1: a project locked before 2.538 (the lock on, the texts never emptied) loses them once at the next start
check([x[0] for x in dbx("SELECT value FROM settings WHERE key='migr_e2efree4372'")] == ["1"], "old lock: the one-shot is marked done on a new server")
if os.environ.get("P2538BL_NOSTART") != "1":
    L3 = Fr.post(B + "/api/lists", json={"name": "Locked long ago", "org_id": None, "time_tracking": True}).json()["id"]
    T3 = Fr.post(B + "/api/tasks", json={"list_id": L3, "title": "Old task"}).json()["id"]
    check(Fr.post(B + f"/api/lists/{L3}/status", json={"status": "at_risk", "note": MK + "PStatus"}).ok, "old lock setup: a status note")
    check(Fr.patch(B + f"/api/lists/{L3}/overview", json={"description": MK + "PDescOld"}).ok, "old lock setup: a description")
    check(Fr.patch(B + f"/api/lists/{L3}/overview", json={"description": MK + "PDesc"}).ok, "old lock setup: a newer description")
    check(Fr.post(B + "/api/time/entries", json={"task_id": T3, "start": start, "minutes": 7, "note": MK + "PTaskTime"}).ok, "old lock setup: a task time note")
    check(Fr.post(B + "/api/time/entries", json={"list_id": L3, "start": start, "minutes": 8, "note": MK + "PListTime"}).ok, "old lock setup: a project time note")
    dbx("UPDATE lists SET e2e='on', e2e_gen=1 WHERE id=?", (L3,), write=True)  # as 2.537 left it: locked, the texts still there
    dbx("DELETE FROM settings WHERE key='migr_e2efree4372'", write=True)
    check(len(dbx("SELECT id FROM time_entries WHERE note LIKE ?", (MK + "P%",))) == 2, "old lock setup: the plain notes are there before the start")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env={**os.environ, "KEEP": "1"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    check(not dbx("SELECT id FROM time_entries WHERE note<>'' AND (list_id=? OR task_id=?)", (L3, T3)), "old lock: no time note left")
    lr = dbx("SELECT status, status_note, description, e2e FROM lists WHERE id=?", (L3,))[0]
    check(lr[0] == "at_risk" and lr[1] == "" and lr[2] == "" and lr[3] == "on", f"old lock: status and lock kept, note and description empty {tuple(lr)}")
    check(not dbx("SELECT id FROM list_status WHERE list_id=? AND note<>''", (L3,)), "old lock: the status history keeps no note")
    check(not dbx("SELECT id FROM list_activity WHERE list_id=? AND kind='desc'", (L3,)), "old lock: no earlier description")
    o = dbx("SELECT status_note, description FROM lists WHERE id=?", (L2,))[0]
    check(o[0] == "fine" and o[1] == "fine", f"old lock: the open project keeps its texts {tuple(o)}")
    check(dbx("SELECT note FROM time_entries WHERE note LIKE ? AND list_id=?", (MK + "O%", L2)), "old lock: the open project keeps its time notes")
    check([x[0] for x in dbx("SELECT value FROM settings WHERE key='migr_e2efree4372'")] == ["1"], "old lock: the one-shot is marked done again")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
