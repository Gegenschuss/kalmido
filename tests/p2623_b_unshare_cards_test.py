#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.623.0 (#4778): a share taken back in the file store's dialog (DELETE /api/files/shares/<id>) on a table's / a knowledge
page's or folder's node marks the card in sheet_shares / wiki_shares ended (revoked_at) and puts the row into obj_revoked --
an older version after a rollback reads only the card and must not open the share again. Invented names only.
 - tables: the card of an organisation's table is marked, the guest reads nothing; Undo (share again) opens the card again
 - freelancer-matrix: sheets, wiki (a private table shared by address: the card goes, as in the table's dialog; a page and a
   folder of a person without an organisation: the card is marked, the folder card ends as a whole -- both core shares)
 - a share made in the file store on a table's node (no card) goes into obj_revoked too; a plain folder's share is deleted as
   before (no obj_revoked row)
 - tenant-matrix: sheet_share (a person of another workspace cannot take the share back: 404, the card stays)
usage: p2623_b_unshare_cards_test.py <datadir>      (a fresh container; P2623B_NOSTART=1 = the server already runs)"""
import sys

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, dbx, sess

FEAT = "wiki,files,collab,comments,sheets"
kt.fresh(prefix="P2623B", env={"KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}


def person(name, role, org=ORG):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}] if org else [], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
    return s


Bo, Gi, Ca = person("bob", "member"), person("gina", "guest"), person("carl", "member")
FID, Fr = freelancer(B, A, "frida")
FIO, Fi = freelancer(B, A, "fiona")
for s in (Fr, Fi):
    s.patch(B + "/api/settings", json={"features": FEAT})
BOB, GINA, CARL = uid["bob"], uid["gina"], uid["carl"]


def table(s, title, space):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def page(s, path, text="text"):
    r = s.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def revoked(kind, rid):
    return dbx("SELECT COUNT(*) FROM obj_revoked WHERE src='fs_shares' AND kind=? AND ref_id=?", (kind, rid))[0][0]


def shared(s):
    return {x["id"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


# ================================================================ tables: the card of an organisation's table is marked
T1 = table(Bo, "Rates", SP)
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201 and Gi.get(B + f"/api/sheets/{T1}").status_code == 200, f"bob shares the table with the guest {r.status_code}")
SH1 = r.json().get("id")
fsid = dbx("SELECT core_id FROM sheet_shares WHERE id=?", (SH1,))[0][0]
check(Fi.delete(B + f"/api/files/shares/{fsid}").status_code in (403, 404), "tenant-matrix: sheet_share -- fiona (another workspace) cannot take it back")
check(dbx("SELECT revoked_at IS NULL FROM sheet_shares WHERE id=?", (SH1,)) == [(True,)], "... the card stays")
r = Bo.delete(B + f"/api/files/shares/{fsid}")
check(r.ok and Gi.get(B + f"/api/sheets/{T1}").status_code == 404, f"taken back in the file store's dialog: the guest reads nothing {r.status_code}")
check(dbx("SELECT revoked_at IS NOT NULL FROM sheet_shares WHERE id=?", (SH1,)) == [(True,)], "#4778: the card is marked ended (revoked_at)")
check(revoked("sheet", T1) == 1, "... the row lies in obj_revoked")
check(Bo.get(B + f"/api/sheets/{T1}/shares").json()["shares"] == [], "... the table's dialog lists nothing")
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201 and dbx("SELECT revoked_at IS NULL, core_id IS NOT NULL FROM sheet_shares WHERE id=?", (SH1,)) == [(True, True)],
      f"Undo (share again): the same card opens again with a new core share {r.status_code}")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "... and works")

# a share made in the file store on the table's node (no card): into obj_revoked as well
nid = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id=?", (T1,))[0][0]
r = Bo.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": CARL, "role": "view"})
check(r.ok, f"bob shares the table's node with carl in the file store {r.status_code} {r.text[:120]}")
fs2 = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (nid, CARL))
check(bool(fs2) and Bo.delete(B + f"/api/files/shares/{fs2[0][0] if fs2 else 0}").ok, "... and takes it back there")
check(revoked("sheet", T1) == 2 and not dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND user_id=?", (nid, CARL)),
      "... gone, the row in obj_revoked")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "... the guest's share is untouched")

# a plain folder's share: deleted as before
FO = Bo.post(B + "/api/files/folders", json={"name": "Plain", "space": SP}).json()["id"]
r = Bo.post(B + f"/api/files/nodes/{FO}/shares", json={"user_id": CARL, "role": "view"})
fs3 = dbx("SELECT id FROM fs_shares WHERE node_id=?", (FO,))
check(r.ok and bool(fs3), f"a plain folder shared {r.status_code}")
n0 = dbx("SELECT COUNT(*) FROM obj_revoked")[0][0]
check(Bo.delete(B + f"/api/files/shares/{fs3[0][0] if fs3 else 0}").ok and not dbx("SELECT 1 FROM fs_shares WHERE node_id=?", (FO,)),
      "... taken back: deleted")
check(dbx("SELECT COUNT(*) FROM obj_revoked")[0][0] == n0, "... as before without an obj_revoked row")

# ================================================================ freelancer-matrix: sheets -- a card by address goes
P1 = table(Fr, "Own rates", "private")
r = Fr.post(B + f"/api/sheets/{P1}/shares", json={"email": "fiona@example.com", "role": "read"})
check(r.status_code == 201 and Fi.get(B + f"/api/sheets/{P1}").status_code == 200, f"frida shares a private table by address {r.status_code}")
fsp = dbx("SELECT core_id FROM sheet_shares WHERE sheet_id=? AND user_id=?", (P1, FIO))
check(bool(fsp) and Fr.delete(B + f"/api/files/shares/{fsp[0][0] if fsp else 0}").ok, "frida takes it back in the file store's dialog")
check(Fi.get(B + f"/api/sheets/{P1}").status_code == 404, "... fiona reads nothing")
check(dbx("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (P1,))[0][0] == 0,
      "#4778: no open card left (the one with the typed address goes, as in the table's dialog)")
check(revoked("sheet", P1) == 1, "... the row in obj_revoked")

# ================================================================ freelancer-matrix: wiki -- a page card
W1 = page(Fr, "Note", "first note")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "fiona@example.com"})
check(r.ok and W1 in shared(Fi), f"frida shares a page with fiona {r.status_code}")
card = dbx("SELECT id, core_id FROM wiki_shares WHERE kind='person' AND page_id=?", (W1,))
check(bool(card and card[0][1]), f"the card has its core share {card}")
CID, FS1 = card[0] if card else (0, 0)
r = Fr.delete(B + f"/api/files/shares/{FS1}")
check(r.ok and W1 not in shared(Fi) and Fi.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 404,
      f"taken back in the file store's dialog: fiona reads nothing {r.status_code}")
check(dbx("SELECT revoked_at IS NOT NULL FROM wiki_shares WHERE id=?", (CID,)) == [(True,)], "#4778: the page card is marked ended")
check(revoked("wiki", W1) == 1, "... the row in obj_revoked")
r = Fr.post(B + f"/api/wiki/shares/{CID}/restore")
check(r.ok and dbx("SELECT revoked_at IS NULL FROM wiki_shares WHERE id=?", (CID,)) == [(True,)], f"Undo: the card opens again {r.status_code}")
check(Fi.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 200, "... with a new core share, fiona reads again")

# a folder card with two core shares (the folder, the page of the same name): it ends as a whole
W2 = page(Fr, "Docs", "the index")
W3 = page(Fr, "Docs/Intro")
r = Fr.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Docs", "kind": "person", "email": "fiona@example.com"})
check(r.ok, f"frida shares the folder Docs {r.status_code} {r.text[:120]}")
fc = dbx("SELECT id, core_id, core_id2 FROM wiki_shares WHERE kind='person' AND owner_id=? AND path='Docs' AND is_folder=1", (FID,))
check(bool(fc and fc[0][1] and fc[0][2]), f"the folder card has two core shares {fc}")
FC, C1, C2 = fc[0] if fc else (0, 0, 0)
check(W3 in shared(Fi), "fiona reads the folder's page")
check(Fr.delete(B + f"/api/files/shares/{C1}").ok, "the folder's core share taken back in the file store's dialog")
check(dbx("SELECT revoked_at IS NOT NULL FROM wiki_shares WHERE id=?", (FC,)) == [(True,)], "#4778: the folder card is marked ended")
check(not dbx("SELECT 1 FROM fs_shares WHERE id IN (?, ?)", (C1, C2)), "... its other core share went with it")
check(W2 not in shared(Fi) and W3 not in shared(Fi), "... fiona reads none of its pages")
check(Gi.get(B + f"/api/wiki/shared/pages/{W3}").status_code == 404, "another person reads nothing of frida's pages")

sys.exit(kt.done("p2623_b_unshare_cards"))
