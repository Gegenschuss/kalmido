#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.589.0 part A API test (#4875): empty the trash of the file store / delete for good, one or several at once.
Invented names only.
 - POST /api/files/trash/purge {ids}: the chosen rows of the trash go for good (a folder with what is in it); an id outside
   the trash 409, an id the person does not see 404, no ids 400
 - {all: true}: the whole trash the person sees; only what the person owns goes -- a node of a colleague the person deleted
   with edit rights stays, counted as "kept" (the message "x stayed, they belong to others")
 - a document deleted for good frees its archive number (doc_meta goes with the node): the number can be given again
 - a person without an organisation (freelancer fixture): the same in the private workspace
tenant-matrix: file
freelancer-matrix: files
usage: p2589_a_trash_api_test.py <datadir>      (a fresh container; P2589A_NOSTART=1 = the server already runs)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, sess, until  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

PURGE = "/api/files/trash/purge"
TEXT = "Beispiel Handel GmbH\nRechnung 2026-301\nRechnungsdatum 05.03.2026\nGesamt 119,00 EUR\n"


def folder(s, name, parent=None, space=None):
    b = {"name": name, **({"parent_id": parent} if parent else {}), **({"space": space} if space else {})}
    r = s.post(B + "/api/files/folders", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, name, data, parent=None, space=None):
    form = {"parent_id": str(parent)} if parent else {"space": space or "private"}
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def exists(nid):
    return bool(kt.dbx("SELECT 1 FROM fs_nodes WHERE id=?", (nid,)))


def trash_ids(s):
    return {x["id"] for x in s.get(B + "/api/files?space=trash").json().get("items", [])}


def doc(s, name, extra):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, (TEXT + extra).encode(), "text/plain"))])
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: (lambda r: r.ok and r.json()["state"] in ("done", "failed"))(s.get(B + f"/api/docs/{nid}")), 90)
    return nid


kt.docker_logs_on_first_fail()
kt.fresh(prefix="P2589A")
A = kt.setup()
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
for u in ("carol", "erin"):
    check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG), f"setup: {u} joins Alpha")
Ca, Er = sess("carol"), sess("erin")
for s in (Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- carol's private tree: Proj/{a.txt}, b.txt, c.txt -- all into the trash
PROJ = folder(Ca, "Proj")
A1 = upload(Ca, "a.txt", b"a", parent=PROJ)
B1 = upload(Ca, "b.txt", b"b")
C1 = upload(Ca, "c.txt", b"c")
KEEP = upload(Ca, "keep.txt", b"keep")
for n in (PROJ, B1, C1):
    check(Ca.delete(B + f"/api/files/nodes/{n}").ok, f"setup: {n} into the trash")

check(Ca.post(B + PURGE, json={"ids": []}).status_code == 400, "no ids: 400")
check(Ca.post(B + PURGE, json={"ids": [KEEP]}).status_code == 409, "a node outside the trash: 409")
check(exists(KEEP), "... and it stays")
BOBF = upload(Bo, "bob.txt", b"bob")
Bo.delete(B + f"/api/files/nodes/{BOBF}")
r = Ca.post(B + PURGE, json={"ids": [B1, BOBF]})
check(r.status_code == 404 and exists(B1) and exists(BOBF), f"someone else's trash: 404, nothing deleted ({r.status_code})")

r = Ca.post(B + PURGE, json={"ids": [B1]})
check(r.ok and r.json() == {"ok": True, "deleted": 1, "kept": 0, "locked": 0} and not exists(B1), f"one row for good ({r.status_code} {r.text[:200]})")
check(B1 not in trash_ids(Ca) and {PROJ, C1} <= trash_ids(Ca), "it left the trash, the others are there")

# ---- the organisation: carol's folder edit for all; erin deletes carol's file there and one of her own (top of the organisation)
OF = folder(Ca, "Team", space=f"org:{ORG}")
check(Ca.patch(B + f"/api/files/nodes/{OF}", json={"org_access": "edit"}).ok, "setup: the folder is open to edit")
O1 = upload(Ca, "carol-team.txt", b"o", parent=OF)
E1 = upload(Er, "erin-team.txt", b"e", space=f"org:{ORG}")  # her own (a file in carol's folder belongs to carol's branch)
check(Er.delete(B + f"/api/files/nodes/{O1}").ok and Er.delete(B + f"/api/files/nodes/{E1}").ok, "setup: erin deletes both")
check({O1, E1} <= trash_ids(Er), "both are in erin's trash")
r = Er.post(B + PURGE, json={"ids": [O1]})
check(r.ok and r.json()["deleted"] == 0 and r.json()["kept"] == 1 and exists(O1), f"erin: carol's file stays ({r.text[:200]})")
r = Er.post(B + PURGE, json={"all": True})
check(r.ok and r.json()["deleted"] == 1 and r.json()["kept"] == 1, f"erin empties: her own goes, carol's stays ({r.text[:200]})")
check(not exists(E1) and exists(O1), "erin's file gone, carol's file still there")
check(Er.get(B + f"/api/files/nodes/{O1}").ok, "erin can still restore carol's file (it shows)")

# ---- carol empties her whole trash: the folder with its file, c.txt and her organisation file erin deleted
r = Ca.post(B + PURGE, json={"all": True})
check(r.ok and r.json()["deleted"] == 3 and r.json()["kept"] == 0, f"carol empties her trash ({r.text[:200]})")
check(not any(exists(x) for x in (PROJ, A1, C1, O1)) and exists(KEEP) and exists(OF), "everything of the trash gone, the rest stays")
check(trash_ids(Ca) == set(), "carol's trash is empty")
r = Ca.post(B + PURGE, json={"all": True})
check(r.ok and r.json()["deleted"] == 0, "an empty trash: nothing to do")

# ---- the archive number of a document deleted for good is free again
D1 = doc(Ca, "rechnung-1.txt", "Kunde Eins\n")
r = Ca.patch(B + f"/api/docs/{D1}", json={"asn": 4711})
check(r.ok, f"setup: archive number 4711 ({r.text[:200]})")
D2 = doc(Ca, "rechnung-2.txt", "Kunde Zwei\n")
check(Ca.patch(B + f"/api/docs/{D2}", json={"asn": 4711}).status_code == 409, "the number is taken")
check(Ca.delete(B + f"/api/files/nodes/{D1}").ok, "setup: the document into the trash")
check(Ca.patch(B + f"/api/docs/{D2}", json={"asn": 4711}).status_code == 409, "in the trash the number is still taken")
r = Ca.post(B + PURGE, json={"ids": [D1]})
check(r.ok and r.json()["deleted"] == 1 and not kt.dbx("SELECT 1 FROM doc_meta WHERE node_id=?", (D1,)), f"the document for good, doc_meta with it ({r.text[:200]})")
r = Ca.patch(B + f"/api/docs/{D2}", json={"asn": 4711})
check(r.ok and r.json().get("asn") == 4711, f"the archive number is free again ({r.status_code} {r.text[:200]})")

# ---- a person without an organisation: the same in the private workspace
# freelancer-matrix: files
FID, Fr = freelancer(B, A)
FF = folder(Fr, "Kunde")
F1 = upload(Fr, "angebot.txt", b"Angebot", parent=FF)
F2 = upload(Fr, "notiz.txt", b"Notiz")
F3 = upload(Fr, "rest.txt", b"Rest")
for n in (FF, F2, F3):
    check(Fr.delete(B + f"/api/files/nodes/{n}").ok, f"freelancer: {n} into the trash")
r = Fr.post(B + "/api/files/trash/purge", json={"ids": [F2]})
check(r.ok and r.json()["deleted"] == 1 and not exists(F2), f"freelancer: one for good ({r.status_code} {r.text[:200]})")
r = Fr.post(B + "/api/files/trash/purge", json={"all": True})
check(r.ok and r.json()["deleted"] == 2 and not any(exists(x) for x in (FF, F1, F3)), f"freelancer: the trash emptied ({r.text[:200]})")
check(trash_ids(Fr) == set(), "freelancer: the trash is empty")
check(Fr.post(B + PURGE, json={"ids": [KEEP]}).status_code == 404, "freelancer: a file of carol 404")

# ---- review F2: a trash bigger than the trash list (500 rows) is emptied whole, in rounds (red before: 500 of 505 went)
MANY = [upload(Fr, f"viele-{k}.txt", b"x") for k in range(505)]
for k in range(0, len(MANY), 250):
    check(Fr.post(B + "/api/files/trash", json={"ids": MANY[k:k + 250]}).ok, f"setup: {k}.. into the trash")
r = Fr.post(B + PURGE, json={"all": True})
check(r.ok and r.json()["deleted"] == 505 and not any(exists(x) for x in MANY), f"freelancer: 505 rows emptied at once ({r.text[:200]})")

print(f"p2589_a_trash_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
