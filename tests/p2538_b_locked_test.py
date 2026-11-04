#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.538.0 part B (#4372): the three free texts the lock per project cannot encrypt -- a time entry's note, the project's
status note and its description -- never stay in plain text in a locked project. Own container (start.sh), invented names.
 - switching the lock on (start / todo / bulk / finish -> le2b_scrub) empties them for good: the time entries' notes of the
   project and its tasks, the status note (also in the status history), the description and its earlier versions
 - afterwards the server refuses them with 409 list_e2e_plain (like the waiting note): new status with a note, a description,
   a time entry with a note (new, timer start, change, moving a noted entry in); the same without text still works
 - an open project of the same person keeps and accepts all three
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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


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

# ---- the open project: all three still work
check(Fr.post(B + f"/api/lists/{L2}/status", json={"status": "on_track", "note": "fine"}).ok, "open: a status note works")
check(Fr.patch(B + f"/api/lists/{L2}/overview", json={"description": "fine"}).ok, "open: a description works")
check(Fr.post(B + "/api/time/entries", json={"task_id": T2, "start": start, "minutes": 5, "note": "fine"}).ok, "open: a time note works")
check(not [x for x in dbx("SELECT note FROM time_entries WHERE list_id=? OR task_id=?", (L, T)) if x[0]], "no time note in the locked project at the end")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
