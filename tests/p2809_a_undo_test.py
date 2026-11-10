#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.809.0 (#5476, part A): undo across devices for the areas of group 1 -- their steps in the core's step groups
(core/undoareas.py), listed by GET /api/undo and taken back by POST /api/undo/to/<id> from another device of the person.
Invented names only.
 - a project's settings (lists/lpundo.py): a rename + colour on the laptop is listed on the phone (area tasks, kind listset,
   label with the old name, device, the answer names its group) and goes back from there; redo; archiving -> undo -> out of
   the archive; a save of the same values and a save with a folder (side effects) record no step; a new sidebar order since
   does not block the undo; a rename by someone else since stays (named); a project admin takes back her own rename, but not
   after she became an editor (noaccess); another person neither lists nor takes back the step (404)
freelancer-matrix: undo (a person without an organisation: her project's colour goes back from the list)
usage: p2809_a_undo_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2809A")
FEAT = "collab,comments,time"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
BOB = r.json().get("id")
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
LAP = {"X-Kalmido-Device": "Laptop (Test)"}
PHONE = kt.sess("alice", headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in of alice = another device
FID, Fr = freelancer(B, A)


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def back(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def lrow(s, lid):
    return next((x for x in s.get(B + "/api/state").json().get("lists", []) if x["id"] == lid), {})


# ---------------------------------------------------------------- a project's settings
r = A.post(B + "/api/lists", json={"name": "Projekt Beispiel", "color": "#3366cc"})
check(r.ok, f"(setup) a project {r.status_code} {r.text[:120]}")
L = r.json()["id"]
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Neu", "color": "#cc3333"}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"renamed on the laptop, the answer names its step group {r.status_code} {r.text[:160]}")
UG = r.json().get("undo_group")
g = newest(PHONE)
check(g.get("id") == UG and g.get("area") == "tasks" and g.get("kind") == "listset" and g.get("ref_id") == L
      and "Projekt Beispiel" in (g.get("label") or "") and g.get("device") == "Laptop (Test)" and g.get("undo"),
      f"the phone lists the laptop's step: area, kind, label with the old name, device {g}")
res = back(PHONE, g["id"])
x = lrow(A, L)
check(res.get("undone") == [g["id"]] and not res.get("stayed") and x.get("name") == "Projekt Beispiel" and x.get("color") == "#3366cc",
      f"taken back from the phone: the old name and colour {res} {x.get('name')} {x.get('color')}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
x = lrow(A, L)
check(r.ok and x.get("name") == "Projekt Neu" and x.get("color") == "#cc3333", f"redo: the new name again {r.status_code} {x.get('name')}")
check(Bo.post(B + f"/api/undo/to/{g['id']}").status_code == 404 and not [y for y in lst(Bo) if y["id"] == g["id"]],
      "another person neither lists nor takes back alice's step (404)")

# archive: its own label, back out of the archive
r = A.patch(B + f"/api/lists/{L}", json={"archived": 1})
g = newest(A)
check(r.ok and g.get("kind") == "listset" and (g.get("label") or "").startswith("Archived"), f"archiving is a step with its label {g.get('label')}")
res = back(A, g["id"])
x = lrow(A, L)
check(res.get("undone") == [g["id"]] and not x.get("archived"), f"undo: out of the archive again {res} {x.get('archived')}")

# nothing changed / side effects: no step
before = newest(A).get("id")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Neu"})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == before, f"a save of the same name records no step {newest(A)}")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Mappe", "folder": "Ablage Beispiel"})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == before,
      f"a save that moves it into a folder (side effects) records no server step (the browser keeps its own) {newest(A)}")
A.patch(B + f"/api/lists/{L}", json={"folder": ""})

# a new sidebar order since does not block; a rename by someone else since does
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Zwei"})
g = newest(A)
ids = [y["id"] for y in A.get(B + "/api/state").json().get("lists", []) if not y.get("is_inbox")]
A.post(B + "/api/lists/reorder", json={"ids": list(reversed(ids))})
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and lrow(A, L).get("name") == "Projekt Mappe",
      f"a new sidebar order since does not block the undo of a rename {res} {lrow(A, L).get('name')}")
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "admin"})
check(r.ok, f"(setup) bob becomes a project admin {r.status_code} {r.text[:120]}")
A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Drei"})
ga = newest(A)
r = Bo.patch(B + f"/api/lists/{L}", json={"name": "Projekt Bob"})
check(r.ok and r.json().get("undo_group"), f"the project admin renames it: a step of his {r.status_code} {r.text[:120]}")
gb = newest(Bo)
res = back(A, ga["id"])
check(not res.get("undone") and res.get("stayed") and lrow(A, L).get("name") == "Projekt Bob",
      f"alice's rename does not go back over bob's: it stays, named {res}")
res = back(Bo, gb["id"])
check(res.get("undone") == [gb["id"]] and lrow(A, L).get("name") == "Projekt Drei", f"the admin takes back his own rename {res}")
r = Bo.patch(B + f"/api/lists/{L}", json={"name": "Projekt Bob Zwei"})
gb = newest(Bo)
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
res = back(Bo, gb["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("code") == "noaccess" and lrow(A, L).get("name") == "Projekt Bob Zwei",
      f"an editor now: his step does not go back (the rights of today) {res}")

# freelancer-matrix
r = Fr.post(B + "/api/lists", json={"name": "Frida Projekt", "color": "#3366cc"})
FL = r.json()["id"]
r = Fr.patch(B + f"/api/lists/{FL}", json={"color": "#22aa22"})
g = newest(Fr)
check(r.ok and g.get("kind") == "listset", f"a person without an organisation: her colour change is a step {g}")
res = back(Fr, g["id"])
check(res.get("undone") == [g["id"]] and lrow(Fr, FL).get("color") == "#3366cc", f"... and goes back from the list {res}")

sys.exit(done("p2809_a_undo"))
