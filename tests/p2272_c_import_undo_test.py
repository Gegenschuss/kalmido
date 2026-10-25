#!/usr/bin/env python3
"""2.272.0 C (#3027): the undo of an import never deletes for good what changed since -- it uses the trash.
 - task import (CSV): unchanged imported tasks go into the trash (restorable), a task with a comment of another member
   stays, so does its list (with a hint in the answer: kept_tasks / kept_lists); the same file imports again afterwards
 - a new imported list nothing else is in goes into the list trash (restorable from there)
 - account import (source "Kalmido", the rows made here like the run makes them): a list with a task of another member
   stays with that task, its unchanged imported task goes into the trash; a list without foreign content goes into the
   list trash; a calendar with an event added since stays, an untouched one goes
 - office (freelancer-matrix: office, a person without an organisation): the undo of a trips import keeps a trip with a
   receipt added since, the one of a fixed costs import keeps a changed one
 - a person without an organisation: the task import undo the same way (private space)
Every name / address here is invented (@example.com).
usage: p2272_c_import_undo_test.py <datadir>      (P2272C_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def ago(sec):
    return (datetime.now(timezone.utc) - timedelta(seconds=sec)).isoformat(timespec="seconds")


def imp(s, name, data):
    r = s.post(f"{B}/api/import/todoist", files={"file": (name, data)})  # the file name = the new list
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]})


def task(title, uid):
    r = dbx("SELECT * FROM tasks WHERE title=? AND created_by=? ORDER BY id DESC", (title, uid))
    return r[0] if r else None


def backdate(iid):
    """The import a minute ago: whatever the test does next lies clearly after it (time stamps have seconds)."""
    cr = json.loads(one("SELECT created FROM imports WHERE id=?", (iid,)))
    for t in cr.get("tasks") or []:
        dbx("UPDATE tasks SET updated_at=?, created_at=? WHERE id=?", (ago(120), ago(120), t))
    dbx("UPDATE imports SET created_at=? WHERE id=?", (ago(60), iid))


def start():
    if os.environ.get("P2272C_NOSTART") == "1":
        return
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_IMPORT_RATE=1000")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ================================================================== setup
start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================================================================== task import: a foreign comment keeps its task
st, j = imp(A, "Shared import.csv", b"TYPE,CONTENT\ntask,Keep me\ntask,Take me\ntask,Take me too\n")
check(st == 200 and j.get("import_id") and j["created"]["tasks"] == 3, f"import {st} {str(j)[:200]}")
IID = j["import_id"]
L1 = task("Keep me", ALICE)["list_id"]
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "edit"}).ok, "the imported list shared with bob")
backdate(IID)
K, T1, T2 = (task(x, ALICE)["id"] for x in ("Keep me", "Take me", "Take me too"))
check(Bo.post(B + f"/api/tasks/{K}/comments", json={"body": "Bob was here"}).ok, "bob comments on an imported task")
r = A.post(B + f"/api/imports/{IID}/undo")
j = r.json() if r.ok else {}
check(r.ok and j.get("tasks") == 2 and j.get("kept_tasks") == 1 and j.get("kept_lists") == 1 and j.get("lists") == 0 and j.get("trash"),
      f"undo: 2 into the trash, the commented task and its list stay {r.text[:200]}")
check(not task("Keep me", ALICE)["deleted_at"] and task("Take me", ALICE)["deleted_at"] and task("Take me too", ALICE)["deleted_at"],
      "the commented task is untouched, the others are in the trash")
check(one("SELECT COUNT(*) FROM comments WHERE task_id=? AND deleted_at IS NULL", (K,)) == 1, "bob's comment stays")
check(not one("SELECT deleted_at FROM lists WHERE id=?", (L1,)), "the list stays")
check(A.post(B + f"/api/tasks/{T1}/restore").ok and not task("Take me", ALICE)["deleted_at"], "a task of the undo comes back from the trash")
check(A.post(B + f"/api/imports/{IID}/undo").status_code == 409, "undo twice: 409")

# a new list nothing else is in goes into the list trash with its tasks (restorable)
st, j = imp(A, "Fresh import.csv", b"TYPE,CONTENT\ntask,Fresh one\ntask,Fresh two\n")
IID2 = j["import_id"]
L2 = task("Fresh one", ALICE)["list_id"]
backdate(IID2)
r = A.post(B + f"/api/imports/{IID2}/undo")
check(r.ok and r.json()["lists"] == 1 and r.json()["tasks"] == 2 and one("SELECT deleted_at FROM lists WHERE id=?", (L2,)),
      f"undo: the unchanged new list goes into the list trash {r.text[:200]}")
tl = A.get(B + "/api/trash/lists").json().get("lists", [])
check(any(x["id"] == L2 and x["tasks"] == 2 for x in tl), f"the list trash shows it with its 2 tasks {tl}")
check(A.post(B + f"/api/trash/lists/{L2}/restore").ok and not task("Fresh one", ALICE)["deleted_at"]
      and not task("Fresh two", ALICE)["deleted_at"], "restored: list and tasks are back")
st, j = imp(A, "Fresh import 2.csv", b"TYPE,CONTENT\ntask,Fresh one\n")
check(st == 200, "an import after an undo works")

# ================================================================== account import: a foreign task keeps its list
LA = A.post(B + "/api/lists", json={"name": "Moved list"}).json()["id"]
LB = A.post(B + "/api/lists", json={"name": "Moved quiet"}).json()["id"]
TA = A.post(B + "/api/tasks", json={"title": "Moved task", "list_id": LA}).json()["id"]
TB = A.post(B + "/api/tasks", json={"title": "Moved quiet task", "list_id": LB}).json()["id"]
for n, t in enumerate((TA, TB)):
    dbx("UPDATE tasks SET tt_id=?, updated_at=?, created_at=? WHERE id=?", (f"kalmido:abc:{n + 1}", ago(120), ago(120), t))
CAL1 = dbx("INSERT INTO ev_cals(owner_id, name, created_at, changed_at) VALUES(?, 'Moved cal', ?, ?) RETURNING id", (ALICE, ago(120), ago(120)))[0][0]
CAL2 = dbx("INSERT INTO ev_cals(owner_id, name, created_at, changed_at) VALUES(?, 'Moved busy cal', ?, ?) RETURNING id", (ALICE, ago(120), ago(120)))[0][0]
dbx("""INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?, 'Kalmido', 'export.zip', ?, '{}', ?)""",
    (ALICE, json.dumps({"lists": [LA, LB], "tasks": [TA, TB], "ev_cals": [CAL1, CAL2]}), ago(60)))
UIID = one("SELECT MAX(id) FROM imports WHERE user_id=?", (ALICE,))
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": BOB, "role": "edit"}).ok, "the moved list shared with bob")
FT = Bo.post(B + "/api/tasks", json={"title": "Bob's own task", "list_id": LA}).json()["id"]
dbx("""INSERT INTO events(cal_id, uid, href, title, start, "end", created_at, updated_at) VALUES(?, 'e1@example.com', 'e1.ics', 'Added later',
       '2026-11-02T10:00:00', '2026-11-02T11:00:00', ?, ?)""", (CAL2, ago(0), ago(0)))
r = A.post(B + f"/api/imports/{UIID}/undo")
j = r.json() if r.ok else {}
check(r.ok and j.get("tasks") == 2 and j.get("lists") == 1 and j.get("kept_lists") == 1 and j.get("kept_cals") == 1,
      f"account undo: 2 tasks into the trash, the quiet list too, the list with bob's task and the busy calendar stay {r.text[:200]}")
check(not one("SELECT deleted_at FROM lists WHERE id=?", (LA,)) and not one("SELECT deleted_at FROM tasks WHERE id=?", (FT,)),
      "the list with bob's task stays, bob's task untouched")
check(one("SELECT deleted_at FROM tasks WHERE id=?", (TA,)) and one("SELECT deleted_at FROM lists WHERE id=?", (LB,))
      and one("SELECT deleted_at FROM tasks WHERE id=?", (TB,)), "the unchanged imported task and the quiet list are in the trash")
check(not dbx("SELECT 1 FROM ev_cals WHERE id=?", (CAL1,)) and dbx("SELECT 1 FROM ev_cals WHERE id=?", (CAL2,))
      and one("SELECT COUNT(*) FROM events WHERE cal_id=?", (CAL2,)) == 1, "the untouched calendar goes, the one with a later event stays")
check(one("SELECT tt_id FROM tasks WHERE id=?", (TA,)).startswith(f"undone{UIID}:"), "the source key is freed for a new import")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
st, j = imp(Fr, "Frei import.csv", b"TYPE,CONTENT\ntask,Frei eins\ntask,Frei zwei\n")
check(st == 200 and j.get("import_id"), f"freelancer: import {st}")
FIID = j["import_id"]
backdate(FIID)
F1 = task("Frei eins", FID)["id"]
check(Fr.patch(B + f"/api/tasks/{F1}", json={"title": "Frei eins geändert"}).ok, "freelancer: an imported task changed")
r = Fr.post(B + f"/api/imports/{FIID}/undo")
check(r.ok and r.json()["tasks"] == 1 and r.json()["kept_tasks"] == 1 and r.json()["kept_lists"] == 1,
      f"freelancer: undo keeps the changed task and its list {r.text[:200]}")
check(not one("SELECT deleted_at FROM tasks WHERE id=?", (F1,)) and task("Frei zwei", FID)["deleted_at"], "freelancer: the unchanged one in the trash")
# 2.272.0 F (#3027, review M6): an account import undo keeps the imported time entries billed since
TE = [dbx("INSERT INTO time_entries(user_id, start, \"end\", seconds, billed_doc_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
          (FID, ago(7200), ago(3600), 3600, b, ago(120), ago(120)))[0][0] for b in (4711, None)]
dbx("""INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?, 'Kalmido', 'export.zip', ?, '{}', ?)""",
    (FID, json.dumps({"time_entries": TE}), ago(60)))
r = Fr.post(B + f"/api/imports/{one('SELECT MAX(id) FROM imports WHERE user_id=?', (FID,))}/undo")
check(r.ok and dbx("SELECT 1 FROM time_entries WHERE id=?", (TE[0],)) and not dbx("SELECT 1 FROM time_entries WHERE id=?", (TE[1],)),
      f"freelancer: account undo keeps the billed time entry, the other goes {r.text[:200]}")

# office: trips + fixed costs (freelancer-matrix: office)
T = "/api/office/trips"
r = Fr.post(B + T + "/import", json={"trips": [{"date_from": "2025-07-01", "dest": "Bonn", "purpose": "job", "people": [{"id": FID}]},
                                               {"date_from": "2025-07-03", "dest": "Köln", "purpose": "job", "people": [{"id": FID}]}]})
check(r.status_code == 201 and r.json()["created"] == 2, "freelancer: trips import " + r.text[:200])
TIDS = r.json().get("ids", [0, 0])
check(Fr.post(B + f"{T}/{TIDS[0]}/items", json={"date": "2025-07-01", "category": "train", "amount": "12.00"}).status_code == 201,
      "a receipt added to an imported trip")
r = Fr.post(B + T + "/delete", json={"ids": TIDS})
check(r.ok and r.json()["deleted"] == 1 and r.json()["kept"] == [TIDS[0]] and dbx("SELECT 1 FROM office_trips WHERE id=?", (TIDS[0],))
      and not dbx("SELECT 1 FROM office_trips WHERE id=?", (TIDS[1],)), f"trips undo: the trip with the later receipt stays {r.text[:200]}")
F = "/api/office/fixed-costs"
r = Fr.post(B + F + "/import", json={"items": [{"label": "Miete", "amount": "500.00", "repeat": "monthly", "start": "2025-01-01"},
                                                {"label": "Strom", "amount": "60.00", "repeat": "monthly", "start": "2025-01-01"}]})
check(r.status_code == 201 and r.json()["created"] == 2, "freelancer: fixed costs import " + r.text[:200])
FIX = r.json().get("ids", [0, 0])
dbx("UPDATE office_fixed_costs SET created_at=?, updated_at=? WHERE id IN (?, ?)", (ago(60), ago(60), FIX[0], FIX[1]))
check(Fr.patch(B + f"{F}/{FIX[0]}", json={"amount": "550.00"}).ok, "a fixed cost changed after the import")
r = Fr.post(B + F + "/delete", json={"ids": FIX})
check(r.ok and r.json()["deleted"] == 1 and r.json()["kept"] == 1 and dbx("SELECT 1 FROM office_fixed_costs WHERE id=?", (FIX[0],))
      and not dbx("SELECT 1 FROM office_fixed_costs WHERE id=?", (FIX[1],)), f"fixed costs undo: the changed one stays {r.text[:200]}")

print(f"p2272_c: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
