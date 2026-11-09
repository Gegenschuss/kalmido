#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.777.0 (#5254): undo across devices, stage 6 -- calendar events, contacts and the file store's metadata / versions record
their steps in the core's step groups (kalmido/core/undoareas.py, events/evundo.py, contacts/ctundo.py, files/fsundo.py) and
go back from the list (POST /api/undo/to/<id>), also from another device of the same person. Invented names only.
 - an event moved (PATCH /api/events/<id>) on the laptop: the phone lists the step (area calendar, label with its title,
   device) and takes it back -> the old times; redo -> the new times; into the trash -> undo -> it is there again
 - a contact changed -> undo -> the old name; into the trash -> undo -> back (GET 200); redo -> in the trash again
 - a file renamed / moved into a folder / into the trash -> undo -> old name, top level, out of the trash; a new version ->
   undo -> the file points at version 1 again (content v1, no third version written), redo -> version 2
 - a habit renamed -> undo -> the old name; into the trash -> undo -> back
 - only own steps: another person neither lists nor takes back a step (404); a step whose object someone else changed since
   stays (named in the answer)
 - review of 2.777 (F1-F8): a move is not taken back into a folder locked since (409) nor into a folder that went into another
   workspace since (409); a file out of the trash takes " (2)" when its name is taken meanwhile; the steps of an organisation's
   contact and event carry the organisation and go when the person leaves it; the history rows of a file deleted for good go
   with the watchdog's clean-up (undogroups.ug_drop_orphans); moving a contact out of a mirrored book (a copy) records no step
freelancer-matrix: undo (a person without an organisation: her contact and her file step go back from the list)
usage: p2777_a_undo_areas_test.py <datadir>"""
import base64
import os
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2777A")
FEAT = "cal,events,contacts,files,docs,collab,comments,habits"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
BOB = r.json().get("id")
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
LAP = {"X-Kalmido-Device": "Laptop (Test)"}
PHONE = kt.sess("alice", headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in of alice = another device
FID, Fr = freelancer(B, A)
D = (date.today() + timedelta(days=3)).isoformat()


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def back(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


# ---------------------------------------------------------------- calendar
r = A.post(B + "/api/events", json={"title": "Drehtag Beispiel", "start": f"{D}T10:00", "end": f"{D}T12:00"})
check(r.ok, f"(setup) an event {r.status_code} {r.text[:120]}")
EV = r.json()["id"]
r = A.patch(B + f"/api/events/{EV}", json={"start": f"{D}T14:00", "end": f"{D}T16:00"}, headers=LAP)
check(r.ok and r.json()["start"].startswith(f"{D}T14:00"), f"the event moved on the laptop {r.status_code}")
g = newest(PHONE)
check(g.get("area") == "calendar" and "Drehtag Beispiel" in (g.get("label") or "") and g.get("device") == "Laptop (Test)"
      and g.get("kind") == "event" and g.get("ref_id") == EV and g.get("undo"),
      f"the phone lists the laptop's step: area, label with the title, device {g}")
res = back(PHONE, g["id"])
ev = A.get(B + f"/api/events/{EV}").json()
check(res.get("undone") == [g["id"]] and not res.get("stayed") and ev["start"].startswith(f"{D}T10:00") and ev["end"].startswith(f"{D}T12:00"),
      f"taken back from the phone: the event is at its old time again {res} {ev.get('start')}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
ev = A.get(B + f"/api/events/{EV}").json()
check(r.ok and ev["start"].startswith(f"{D}T14:00"), f"redo: the new time again {r.status_code} {ev.get('start')}")
check(Bo.post(B + f"/api/undo/to/{g['id']}").status_code == 404 and not [x for x in lst(Bo) if x["id"] == g["id"]],
      "another person neither lists nor takes back alice's step (404)")
r = A.delete(B + f"/api/events/{EV}")
check(r.ok and A.get(B + f"/api/events/{EV}").status_code == 404, f"the event went into the trash {r.status_code}")
g = newest(A)
check("Drehtag Beispiel" in (g.get("label") or "") and g.get("kind") == "event", f"the trash step is listed with the title {g}")
res = back(A, g["id"])
r = A.get(B + f"/api/events/{EV}")
check(res.get("undone") == [g["id"]] and r.ok and r.json()["start"].startswith(f"{D}T14:00"), f"undo of the delete: the event is there again {res}")
in_range = A.get(B + "/api/events", params={"from": D, "to": (date.fromisoformat(D) + timedelta(days=1)).isoformat()})
check(in_range.ok and EV in [x.get("eid") for x in in_range.json().get("items", [])],
      f"... and shows in the calendar's range again {in_range.status_code}")

# ---------------------------------------------------------------- contacts
BK = A.post(B + "/api/books", json={"name": "Beispielbuch", "org_id": None}).json()["id"]
r = A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Erika Beispiel", "given": "Erika", "family": "Beispiel"})
check(r.status_code == 201, f"(setup) a contact {r.status_code} {r.text[:120]}")
CT = r.json()["id"]
r = A.patch(B + f"/api/contacts/{CT}", json={"fn": "Erika Muster", "family": "Muster"})
check(r.ok, f"the contact changed {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "contact" and "Erika Beispiel" in (g.get("label") or ""), f"the contact's step is listed with its name (before the step) {g}")
res = back(PHONE, g["id"])
c = A.get(B + f"/api/contacts/{CT}").json()
check(res.get("undone") == [g["id"]] and c.get("fn") == "Erika Beispiel" and c.get("family") == "Beispiel",
      f"taken back from the phone: the old name {res} {c.get('fn')}")
r = A.delete(B + f"/api/contacts/{CT}")
check(r.ok and A.get(B + f"/api/contacts/{CT}").status_code == 404, f"the contact went into the trash {r.status_code}")
g = newest(A)
res = back(A, g["id"])
r = A.get(B + f"/api/contacts/{CT}")
check(res.get("undone") == [g["id"]] and r.ok and r.json().get("fn") == "Erika Beispiel", f"undo of the delete: the contact is back {res}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and A.get(B + f"/api/contacts/{CT}").status_code == 404, f"redo: in the trash again {r.status_code} {r.text[:120]}")

# ---------------------------------------------------------------- files
up = A.post(B + "/api/files/upload", files={"file": ("bericht.txt", b"v1", "text/plain")})
check(up.ok, f"(setup) a file {up.status_code} {up.text[:120]}")
NID = up.json()["items"][0]["id"]
r = A.post(B + "/api/files/folders", json={"name": "Ablage Beispiel"})
check(r.ok, f"(setup) a folder {r.status_code} {r.text[:120]}")
FOLD = r.json()["id"]


def node(s=A, nid=NID):
    r = s.get(B + f"/api/files/nodes/{nid}")
    return r.json() if r.ok else {"status": r.status_code}


r = A.patch(B + f"/api/files/nodes/{NID}", json={"name": "bericht-final.txt"})
check(r.ok and node()["name"] == "bericht-final.txt", f"the file renamed {r.status_code}")
g = newest(PHONE)
check(g.get("kind") == "fs_node" and "bericht.txt" in (g.get("label") or ""), f"the rename is listed with the old name {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and node()["name"] == "bericht.txt", f"taken back from the phone: the old name {res} {node().get('name')}")
r = A.patch(B + f"/api/files/nodes/{NID}", json={"parent_id": FOLD})
check(r.ok and node().get("parent_id") == FOLD, f"the file moved into the folder {r.status_code} {r.text[:120]}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and node().get("parent_id") in (None, 0), f"undo of the move: at the top again {res} {node().get('parent_id')}")
r = A.delete(B + f"/api/files/nodes/{NID}")
check(r.ok and node().get("in_trash") is True, f"the file went into the trash {r.status_code} {node().get('in_trash')}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and node().get("name") == "bericht.txt" and node().get("in_trash") is False,
      f"undo of the delete: the file is back out of the trash {res} {node().get('in_trash')}")
r = A.post(B + f"/api/files/nodes/{NID}/versions", files={"file": ("bericht.txt", b"v2", "text/plain")})
check(r.ok and A.get(B + f"/api/files/nodes/{NID}/content").content == b"v2", f"a new version {r.status_code} {r.text[:120]}")
g = newest(A)
res = back(A, g["id"])
nv = kt.dbx("SELECT COUNT(*) FROM fs_versions WHERE node_id=?", (NID,))[0][0]
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/files/nodes/{NID}/content").content == b"v1" and nv == 2,
      f"undo of the version: the file points at version 1 again, no copy written ({nv} versions) {res}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and A.get(B + f"/api/files/nodes/{NID}/content").content == b"v2", f"redo: version 2 again {r.status_code}")

# a step whose object changed since stays and is named; the rest of the group goes back anyway (one request = one group:
# two steps bundled by the header X-Kalmido-Undo-Group)
TOKH = {"X-Kalmido-Undo-Group": "cd34" * 8}
up2 = A.post(B + "/api/files/upload", files={"file": ("notiz.txt", b"n1", "text/plain")})
N2 = up2.json()["items"][0]["id"]
A.patch(B + f"/api/files/nodes/{NID}", json={"name": "bericht-2.txt"}, headers=TOKH)
A.patch(B + f"/api/files/nodes/{N2}", json={"name": "notiz-2.txt"}, headers=TOKH)
g = newest(A)
check(g.get("parts") == 2, f"(setup) two renames in one group {g}")
A.patch(B + f"/api/files/nodes/{N2}", json={"name": "notiz-3.txt"})  # a later own step of another group
# take back only the bundled group: the newer step goes first (undo/to runs newest down to the group), then both parts
res = back(A, g["id"])
check(not res.get("stayed") and node()["name"] == "bericht.txt" and node(nid=N2)["name"] == "notiz.txt",
      f"bis hierher: the newer step and the bundled group go back {res}")

# someone else changed it since: that part stays (named), the rest of the group goes back anyway
r = A.post(B + "/api/files/folders", json={"name": "Team Beispiel", "space": f"org:{ORG}"})
TF = r.json().get("id")
r = A.patch(B + f"/api/files/nodes/{TF}", json={"org_access": "edit"})
check(r.ok, f"(setup) an organisation folder open to edit {r.status_code} {r.text[:120]}")
t1 = A.post(B + "/api/files/upload", data={"parent_id": TF}, files={"file": ("plan.txt", b"p", "text/plain")}).json()["items"][0]["id"]
t2 = A.post(B + "/api/files/upload", data={"parent_id": TF}, files={"file": ("liste.txt", b"l", "text/plain")}).json()["items"][0]["id"]
TOK2 = {"X-Kalmido-Undo-Group": "ef56" * 8}
A.patch(B + f"/api/files/nodes/{t1}", json={"name": "plan-a.txt"}, headers=TOK2)
A.patch(B + f"/api/files/nodes/{t2}", json={"name": "liste-a.txt"}, headers=TOK2)
g = newest(A)
r = Bo.patch(B + f"/api/files/nodes/{t1}", json={"name": "plan-bob.txt"})
check(r.ok, f"(setup) bob renames the plan too {r.status_code} {r.text[:120]}")
res = back(A, g["id"])
st = res.get("stayed") or []
check(res.get("partial") == [g["id"]] and [x["id"] for x in st] == [t1] and st[0]["code"] == "conflict" and st[0]["reason"]
      and node(nid=t1)["name"] == "plan-bob.txt" and node(nid=t2)["name"] == "liste.txt",
      f"bob's change stays and is named, the other part goes back {res}")
check(not [x for x in lst(Bo) if x["id"] == g["id"]], "bob does not see alice's step")

# ---------------------------------------------------------------- review F1, F2, F5, F4 (2.777.0 #5254)
def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def gid_after(s):
    return newest(s).get("id")


def stayed_of(res, nid):
    return [x for x in (res.get("stayed") or []) if x.get("id") == nid]


# F1: the folder the file came from is locked since -> the undo would put a plain file with a plain name into it: 409
LF = A.post(B + "/api/files/folders", json={"name": "Tresor Beispiel"}).json()["id"]
LN = A.post(B + "/api/files/upload", data={"parent_id": LF}, files={"file": ("geheim.txt", b"g", "text/plain")}).json()["items"][0]["id"]
r = A.patch(B + f"/api/files/nodes/{LN}", json={"parent_id": None})
check(r.ok and node(nid=LN).get("parent_id") in (None, 0), f"(setup) the file moved out of the folder {r.status_code} {r.text[:120]}")
G1 = gid_after(A)
keys = {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32)},
        "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(120)},
        "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(120)}}
check(A.put(B + "/api/e2e/keys", json=keys).ok, "(setup) alice sets up her keys")
r = A.post(B + f"/api/files/lock/{LF}/start", json={"keys": [{"user_id": ALICE, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
r2 = A.post(B + f"/api/files/lock/{LF}/finish", json={})
check(r.ok and r2.ok, f"(setup) the folder is locked now {r.status_code} {r.text[:120]} {r2.status_code} {r2.text[:120]}")
res = back(A, G1)
check(stayed_of(res, LN) and stayed_of(res, LN)[0]["code"] == "conflict" and node(nid=LN).get("parent_id") in (None, 0),
      f"F1: the move is not taken back into the folder locked since (409, the file stays at the top) {res} {node(nid=LN).get('parent_id')}")

# F2: the folder went into the organisation's workspace since -> the private file would hang below another workspace: 409
SF = A.post(B + "/api/files/folders", json={"name": "Umzug Beispiel"}).json()["id"]
SN = A.post(B + "/api/files/upload", data={"parent_id": SF}, files={"file": ("privat.txt", b"p", "text/plain")}).json()["items"][0]["id"]
r = A.patch(B + f"/api/files/nodes/{SN}", json={"parent_id": None})
check(r.ok, f"(setup) the file moved out of the folder {r.status_code} {r.text[:120]}")
G2 = gid_after(A)
r = A.post(B + "/api/files/move-space", json={"ids": [SF], "to": ORG, "parent": None})
moved = kt.dbx("SELECT org_id FROM fs_nodes WHERE id=?", (SF,))
check(r.ok and moved and moved[0][0] == ORG, f"(setup) the folder went into the organisation's workspace {r.status_code} {r.text[:160]} {moved}")
res = back(A, G2)
check(stayed_of(res, SN) and stayed_of(res, SN)[0]["code"] == "conflict" and node(nid=SN).get("parent_id") in (None, 0),
      f"F2: the move is not taken back into a folder of another workspace (409, the file stays at the top) {res} {node(nid=SN).get('parent_id')}")

# ---------------------------------------------------------------- habits
r = A.post(B + "/api/habits", json={"name": "Laufen Beispiel"})
check(r.ok, f"(setup) a habit {r.status_code} {r.text[:120]}")
HB = r.json()["id"]


def habit():
    x = kt.dbx("SELECT name, deleted_at FROM habits WHERE id=?", (HB,))
    return dict(x[0]) if x else {}


r = A.patch(B + f"/api/habits/{HB}", json={"name": "Laufen Neu"})
check(r.ok and habit()["name"] == "Laufen Neu", f"the habit renamed {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "habit" and "Laufen Beispiel" in (g.get("label") or ""), f"the habit's step is listed {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and habit()["name"] == "Laufen Beispiel", f"taken back from the phone: the old name {res} {habit()}")
r = A.delete(B + f"/api/habits/{HB}")
check(r.ok and habit()["deleted_at"], f"the habit went into the trash {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and not habit()["deleted_at"], f"undo of the delete: the habit is back {res} {habit()}")

# ---------------------------------------------------------------- a person without an organisation
up = Fr.post(B + "/api/files/upload", files={"file": ("frei.txt", b"f1", "text/plain")})
FN = up.json()["items"][0]["id"]
Fr.patch(B + f"/api/files/nodes/{FN}", json={"name": "frei-neu.txt"})
g = newest(Fr)
res = back(Fr, g["id"])
check(res.get("undone") == [g["id"]] and node(Fr, FN).get("name") == "frei.txt", f"freelancer: her file step goes back {res}")
FBK = Fr.post(B + "/api/books", json={"name": "Frei", "org_id": None}).json()["id"]
FCT = Fr.post(B + "/api/contacts", json={"book_id": FBK, "fn": "Kunde Frei"}).json()["id"]
Fr.patch(B + f"/api/contacts/{FCT}", json={"fn": "Kunde Frei Neu"})
g = newest(Fr)
res = back(Fr, g["id"])
check(res.get("undone") == [g["id"]] and Fr.get(B + f"/api/contacts/{FCT}").json().get("fn") == "Kunde Frei",
      f"freelancer: her contact step goes back {res}")
check(not [x for x in lst(A) if x["id"] == g["id"]] and A.post(B + f"/api/undo/to/{g['id']}").status_code == 404,
      "the admin neither lists nor takes back the freelancer's step")

# ---------------------------------------------------------------- review F3: the steps of an organisation's contact / event
# (contacts and events carry their book's / calendar's org_id since 2.662.0 #4602, filled by triggers: the steps have it too)
r = Bo.post(B + "/api/books", json={"name": "Team Kontakte", "org_id": ORG})
check(r.ok, f"(setup) bob: an address book of the organisation {r.status_code} {r.text[:120]}")
OBK = r.json()["id"]
OCT = Bo.post(B + "/api/contacts", json={"book_id": OBK, "fn": "Kundin Team"}).json()["id"]
check(Bo.patch(B + f"/api/contacts/{OCT}", json={"fn": "Kundin Team Neu"}).ok, "(setup) bob changes the organisation's contact")
r = Bo.post(B + "/api/evcals", json={"name": "Team Kalender", "org_id": ORG})
check(r.ok, f"(setup) bob: a calendar of the organisation {r.status_code} {r.text[:120]}")
OCAL = r.json()["id"]
r = Bo.post(B + "/api/events", json={"cal_id": OCAL, "title": "Teamtermin", "start": f"{D}T09:00", "end": f"{D}T10:00"})
check(r.ok, f"(setup) an event in it {r.status_code} {r.text[:120]}")
OEV = r.json()["id"]
check(Bo.patch(B + f"/api/events/{OEV}", json={"title": "Teamtermin Neu"}).ok, "(setup) bob changes the event")


def steps_of(kind, rid):
    return kt.dbx("SELECT u.org_id, g.org_id FROM obj_undo u LEFT JOIN undo_groups g ON g.id=u.group_id WHERE u.user_id=? AND u.kind=? AND u.ref_id=?",
                  (BOB, kind, rid))


sc, se = steps_of("contact", OCT), steps_of("event", OEV)
check(sc and se and all(tuple(x) == (ORG, ORG) for x in sc + se),
      f"F3: the steps of the organisation's contact and event (and their groups) carry the organisation {sc} {se}")
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{BOB}")
check(r.ok, f"(setup) bob leaves the organisation {r.status_code} {r.text[:120]}")
sc, se = steps_of("contact", OCT), steps_of("event", OEV)
check(not sc and not se, f"F3: leaving the organisation takes his steps of its contact and event with it {sc} {se}")

sys.exit(done("p2777_a_undo_areas"))
