#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1074.0 (#5493): undo across devices, stage 3c -- a project's settings WITH side effects are server steps (lists/lpside.py,
kind listside, a diff part taken back through the project's own write path). Invented names only.
 - a person without an organisation moves her project into a folder: one step (listed, kind listside, label "Settings of"),
   taken back from the list (folder empty again), redone (in the folder again); the undo records no new step
 - a save with a plain and a side-effect setting (rename + time tracking off) is ONE step, both go back
 - a project into the organisation: the step is labelled "Workspace of", its undo puts it back into Private and brings back the
   private client the move ended (move memo)
 - the project's ticket key: back to none and forward again
 - a value changed elsewhere since stays and is named (409 when nothing else of the step is left)
 - a write with X-Kalmido-Undo-Own (a device's own way back of a step without a server group) records no step and keeps
   the way forward of an undone step
 - another person neither lists nor takes back the step (404)
 - a task's step is labelled as the app's history names it: "Priority of “X”: High", "Renamed “X”", "Date of “X”: 4 Mar"
   (was "Edited X")
freelancer-matrix: undo (a person without an organisation: her project's folder and time tracking go back and forward)
usage: p21074_a_lpside_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

kt.fresh(prefix="P21074A")
s0 = kt.sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,time,office,clients"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,time"})


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def lrow(s, lid):
    return next((x for x in s.get(B + "/api/state").json().get("lists", []) if x["id"] == lid), {})


def undo_one(s, gid):
    r = s.post(B + f"/api/undo/{gid}/undo")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


# ---------------------------------------------------------------- a person without an organisation: folder
r = Fr.post(B + "/api/lists", json={"name": "Frida Projekt"})
check(r.ok, f"(setup) her project {r.status_code} {r.text[:120]}")
FL = r.json()["id"]
r = Fr.patch(B + f"/api/lists/{FL}", json={"folder": "Kunden Beispiel", "_prev": {"folder": ""}})
ug = r.json().get("undo_group") if r.ok else None
g = newest(Fr)
check(r.ok and ug and g.get("id") == ug and g.get("kind") == "listside" and g.get("ref_id") == FL and g.get("area") == "tasks"
      and "Frida Projekt" in (g.get("label") or "") and g.get("undo"),
      f"into a folder: a server step of kind listside, labelled with the project {r.status_code} {r.text[:160]} {g}")
check(lrow(Fr, FL).get("folder") == "Kunden Beispiel", "(setup) in the folder")
res = Fr.post(B + f"/api/undo/to/{ug}").json()
check(res.get("undone") == [ug] and not res.get("stayed") and not lrow(Fr, FL).get("folder"),
      f"undo from the list: out of the folder again {res} {lrow(Fr, FL).get('folder')}")
check(newest(Fr).get("id") == ug and newest(Fr).get("state") == "undone", f"the undo recorded no new step {newest(Fr)}")
r = Fr.post(B + f"/api/undo/{ug}/redo")
check(r.ok and lrow(Fr, FL).get("folder") == "Kunden Beispiel", f"redo: in the folder again {r.status_code} {r.text[:120]}")

# rename + time tracking in one save = one step, both go back (a new project of hers tracks time: the module Time is on)
check(lrow(Fr, FL).get("time_tracking"), "(setup) her new project tracks time")
r = Fr.patch(B + f"/api/lists/{FL}", json={"name": "Frida Neu", "time_tracking": False})
ug2 = r.json().get("undo_group") if r.ok else None
x = lrow(Fr, FL)
check(r.ok and ug2 and x.get("name") == "Frida Neu" and not x.get("time_tracking"), f"(setup) renamed, time tracking off {r.text[:160]}")
check(len([y for y in lst(Fr) if y["id"] == ug2]) == 1, "one step for the save")
res = undo_one(Fr, ug2)
x = lrow(Fr, FL)
check(res.get("undone") == [ug2] and x.get("name") == "Frida Projekt" and x.get("time_tracking"),
      f"undo: the old name and time tracking on again {res} {x.get('name')} {x.get('time_tracking')}")

# changed elsewhere since: stays, named
r = Fr.patch(B + f"/api/lists/{FL}", json={"folder": "Archiv Beispiel"})
ug3 = r.json().get("undo_group") if r.ok else None
check(r.ok and ug3, f"(setup) another folder is a step {r.text[:160]}")
kt.dbx("UPDATE lists SET folder='Dritter Ordner' WHERE id=?", (FL,))  # another device moved it on meanwhile (no step of hers)
res = undo_one(Fr, ug3)
check(not res.get("undone") and res.get("stayed") and "folder" in str(res.get("stayed")) and lrow(Fr, FL).get("folder") == "Dritter Ordner",
      f"a value changed elsewhere since is not set back (named) {res}")

# a trip's dates (stored as JSON text): a change goes back to the old dates (Fable review: the _prev compare never matched)
r = Fr.post(B + "/api/lists", json={"name": "Reise Beispiel"})
RL = r.json().get("id") if r.ok else None
r = Fr.patch(B + f"/api/lists/{RL}", json={"life": "travel", "trip": {"from": "2026-05-01", "to": "2026-05-08"}})
check(r.ok and (lrow(Fr, RL).get("trip") or {}).get("from") == "2026-05-01", f"(setup) a trip {r.status_code} {r.text[:160]}")
r = Fr.patch(B + f"/api/lists/{RL}", json={"trip": {"from": "2026-06-01", "to": "2026-06-09", "where": "Lissabon"}})
ugt = r.json().get("undo_group") if r.ok else None
check(r.ok and ugt, f"(setup) new trip dates are a step {r.status_code} {r.text[:160]}")
res = undo_one(Fr, ugt)
trip = lrow(Fr, RL).get("trip") or {}
check(res.get("undone") == [ugt] and not res.get("stayed") and trip.get("from") == "2026-05-01" and trip.get("to") == "2026-05-08",
      f"undo: the old trip dates are back {res} {trip}")

# ---------------------------------------------------------------- the workspace: into the organisation and back
r = A.post(B + "/api/clients", json={"name": "Private Beispiel Kunde", "org_id": None})
PC = r.json().get("id")
r = A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": None})
P = r.json()["id"]
check(PC and A.patch(B + f"/api/lists/{P}", json={"client_id": PC}).ok, f"(setup) the private project has a private client {r.text[:120]}")
r = A.patch(B + f"/api/lists/{P}", json={"org_id": ORG})
ugw = r.json().get("undo_group") if r.ok else None
me = (r.json().get("move_ended") or {}) if r.ok else {}
g = newest(A)
check(r.ok and ugw and me.get("client") == 1 and g.get("id") == ugw and g.get("kind") == "listside"
      and (g.get("label") or "").startswith("Workspace of"), f"into the organisation: a step 'Workspace of' {r.text[:200]} {g}")
res = A.post(B + f"/api/undo/to/{ugw}").json()
x = lrow(A, P)
check(res.get("undone") == [ugw] and not x.get("org_id") and x.get("client_id") == PC,
      f"undo: back in Private, the client the move ended is back {res} org={x.get('org_id')} client={x.get('client_id')}")
r = A.post(B + f"/api/undo/{ugw}/redo")
check(r.ok and lrow(A, P).get("org_id") == ORG, f"redo: in the organisation again {r.status_code} {r.text[:120]}")

# the ticket key
r = A.patch(B + f"/api/lists/{P}", json={"ticket_key": "ALP"})
ugk = r.json().get("undo_group") if r.ok else None
check(r.ok and ugk and lrow(A, P).get("ticket_key") == "ALP", f"(setup) a ticket key {r.text[:160]}")
res = undo_one(A, ugk)
check(res.get("undone") == [ugk] and not lrow(A, P).get("ticket_key"), f"undo: no ticket key again {res}")
r = A.post(B + f"/api/undo/{ugk}/redo")
check(r.ok and lrow(A, P).get("ticket_key") == "ALP", f"redo: the key again {r.status_code} {r.text[:120]}")

# a device's own way back of a step without a server group (header X-Kalmido-Undo-Own): no new step, the undone step keeps
# its way forward
res = undo_one(A, ugk)
r = A.patch(B + f"/api/lists/{P}", json={"color": "#cc3333"}, headers={"X-Kalmido-Undo-Own": "1"})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == ugk and newest(A).get("state") == "undone",
      f"a write marked as a device's own undo records no step {r.text[:160]} {newest(A)}")
r = A.post(B + f"/api/undo/{ugk}/redo")
check(r.ok and lrow(A, P).get("ticket_key") == "ALP", f"... and the undone step keeps its way forward {r.status_code} {r.text[:120]}")
r = A.patch(B + f"/api/lists/{P}", json={"color": "#3366cc"})
check(r.ok and r.json().get("undo_group"), "(control) the same write without the header is a step")

# ---------------------------------------------------------------- task steps: labelled as the app names them
r = Fr.post(B + "/api/tasks", json={"title": "Sprung Beispiel", "list_id": FL})
T = r.json()["id"]
Fr.patch(B + f"/api/tasks/{T}", json={"priority": 5})
g = newest(Fr)
check(g.get("kind") == "task" and g.get("label") == "Priority of “Sprung Beispiel”: High", f"a priority step says which priority (was 'Edited …') {g.get('label')}")
Fr.patch(B + f"/api/tasks/{T}", json={"title": "Sprung Neu"})
check(newest(Fr).get("label") == "Renamed “Sprung Neu”", f"a rename says so {newest(Fr).get('label')}")
Fr.patch(B + f"/api/tasks/{T}", json={"due": "2026-03-04"})
check(newest(Fr).get("label") == "Date of “Sprung Neu”: 4 Mar", f"a date step names the day {newest(Fr).get('label')}")
Fr.patch(B + f"/api/tasks/{T}", json={"list_id": RL})
check(newest(Fr).get("label") == "Moved “Sprung Neu”", f"a move names no project (a lock later would keep it) {newest(Fr).get('label')}")
Fr.patch(B + f"/api/tasks/{T}", json={"list_id": FL})
Fr.patch(B + f"/api/tasks/{T}", json={"title": "Sprung Zwei", "priority": 1})
check(newest(Fr).get("label") == "Edited “Sprung Zwei”", f"several fields: 'Edited' with the title in quotes {newest(Fr).get('label')}")
Fr.post(B + f"/api/tasks/{T}/complete")
check(newest(Fr).get("label") == "Completed “Sprung Zwei”", f"completing: the title in quotes {newest(Fr).get('label')}")

# another person
check(Fr.post(B + f"/api/undo/to/{ugk}").status_code == 404 and not [y for y in lst(Fr) if y["id"] == ugk],
      "another person neither lists nor takes back alice's step (404)")

sys.exit(done("p21074_a_lpside"))
