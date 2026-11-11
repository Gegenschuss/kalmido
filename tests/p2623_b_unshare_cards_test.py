#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.623.0 (#4778): a share taken back in the file store's dialog (DELETE /api/files/shares/<id>) on a table's / a knowledge
page's or folder's node marks the card in sheet_shares / wiki_shares ended (revoked_at) and puts the row into obj_revoked --
an older version after a rollback reads only the card and must not open the share again. Invented names only.
 - tables: the card of an organisation's table is marked, the guest reads nothing; Undo (share again) opens the card again
 - freelancer-matrix: sheets, wiki (a private table shared by address: the card goes, as in the table's dialog; a page and a
   folder of a person without an organisation: the card is marked, the folder card ends as a whole -- both core shares)
 - a share made in the file store on a table's node (no card) goes into obj_revoked too; a plain folder's share is deleted
   and (2.747.0, #5246) kept in obj_revoked as well (reason unshare, no kind)
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
# 2.937.0 (#5244): the dialog's id is the core share's (no card any more)
fsid = r.json().get("id")
check(dbx("SELECT user_id FROM fs_shares WHERE id=?", (fsid,)) == [(GINA,)], "2.937.0 (#5244): the dialog's id is the core share's")
check(Fi.delete(B + f"/api/files/shares/{fsid}").status_code in (403, 404), "tenant-matrix: sheet_share -- fiona (another workspace) cannot take it back")
check(dbx("SELECT 1 FROM fs_shares WHERE id=?", (fsid,)) == [(1,)], "... the share stays")
r = Bo.delete(B + f"/api/files/shares/{fsid}")
check(r.ok and Gi.get(B + f"/api/sheets/{T1}").status_code == 404, f"taken back in the file store's dialog: the guest reads nothing {r.status_code}")
check(revoked("sheet", T1) == 1, "... the row lies in obj_revoked")
check(Bo.get(B + f"/api/sheets/{T1}/shares").json()["shares"] == [], "... the table's dialog lists nothing")
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201 and dbx("SELECT user_id FROM fs_shares WHERE id=?", (r.json().get("id"),)) == [(GINA,)],
      f"Undo (share again): a new core share {r.status_code}")
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

# a plain folder's share: deleted, and since 2.747.0 (#5246, decision 08.11.2026) kept in obj_revoked like every core share
FO = Bo.post(B + "/api/files/folders", json={"name": "Plain", "space": SP}).json()["id"]
r = Bo.post(B + f"/api/files/nodes/{FO}/shares", json={"user_id": CARL, "role": "view"})
fs3 = dbx("SELECT id FROM fs_shares WHERE node_id=?", (FO,))
check(r.ok and bool(fs3), f"a plain folder shared {r.status_code}")
FS3 = fs3[0][0] if fs3 else 0
check(Bo.delete(B + f"/api/files/shares/{FS3}").ok and not dbx("SELECT 1 FROM fs_shares WHERE node_id=?", (FO,)),
      "... taken back: deleted")
# 2.780.0 (#5385): was "as before without an obj_revoked row" -- #5246 (08.11.2026) sends the dialog's folder share through
# the core's obj_node_unshare too (p2571_c_kern was adjusted then, this suite was missed)
rv = [x for x in dbx("SELECT reason, kind, row_json FROM obj_revoked WHERE src='fs_shares'") if f'"id": {FS3},' in x[2]]
check(len(rv) == 1 and rv[0][0] == "unshare" and rv[0][1] is None, f"... kept in obj_revoked (reason unshare, no kind) {rv}")

# review F1 (2.623.0): a share on an organisation's knowledge page, taken back in the file store's dialog, lies in obj_revoked
# under that organisation (not as a private row)
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Team note", "body": "team"})
check(r.status_code == 201, f"bob writes an organisation's page {r.status_code} {r.text[:120]}")
WO = r.json().get("id", 0) if r.ok else 0
wn = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (WO,))
r = Bo.post(B + f"/api/files/nodes/{wn[0][0] if wn else 0}/shares", json={"user_id": CARL, "role": "view"})
fsw = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (wn[0][0] if wn else 0, CARL))
check(bool(wn) and r.ok and bool(fsw), f"bob shares the page's node with carl in the file store {wn} {r.status_code} {r.text[:120]}")
check(bool(fsw) and Bo.delete(B + f"/api/files/shares/{fsw[0][0]}").ok, "... and takes it back there")
check(dbx("SELECT org_id FROM obj_revoked WHERE src='fs_shares' AND kind='wiki' AND ref_id=?", (WO,)) == [(ORG,)],
      "... the row lies in obj_revoked under the organisation")

# ================================================================ freelancer-matrix: sheets -- a card by address goes
P1 = table(Fr, "Own rates", "private")
r = Fr.post(B + f"/api/sheets/{P1}/shares", json={"email": "fiona@example.com", "role": "read"})
check(r.status_code == 201 and Fi.get(B + f"/api/sheets/{P1}").status_code == 200, f"frida shares a private table by address {r.status_code}")
# 2.937.0 (#5244): the address is bound to fiona's account, her right is her core share on the table's node
fsp = dbx("SELECT f.id FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=? "
          "AND f.user_id=?", (P1, FIO))
check(bool(fsp) and Fr.delete(B + f"/api/files/shares/{fsp[0][0] if fsp else 0}").ok, "frida takes it back in the file store's dialog")
check(Fi.get(B + f"/api/sheets/{P1}").status_code == 404, "... fiona reads nothing")
check(dbx("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (P1,))[0][0] == 0,
      "#4778: no open card left (the one with the typed address goes, as in the table's dialog)")
check(revoked("sheet", P1) == 1, "... the row in obj_revoked")

# ================================================================ freelancer-matrix: wiki -- a page card
W1 = page(Fr, "Note", "first note")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "fiona@example.com"})
check(r.ok and W1 in shared(Fi), f"frida shares a page with fiona {r.status_code}")
# 2.937.0 (#5244, stage 7c): the card is a row of wiki_share_cards on the core share (no person row of wiki_shares any more)
card = dbx("SELECT k.fs_share_id FROM wiki_share_cards k JOIN fs_shares f ON f.id=k.fs_share_id JOIN fs_nodes n ON n.id=f.node_id "
           "WHERE n.kind='ref' AND n.ref_kind='wiki' AND n.ref_id=?", (W1,))
check(bool(card), f"the core share has its card {card}")
FS1 = card[0][0] if card else 0
check(not dbx("SELECT 1 FROM wiki_shares WHERE kind<>'link'"), "#5244: wiki_shares holds no person row")
r = Fr.delete(B + f"/api/files/shares/{FS1}")
check(r.ok and W1 not in shared(Fi) and Fi.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 404,
      f"taken back in the file store's dialog: fiona reads nothing {r.status_code}")
check(not dbx("SELECT 1 FROM wiki_share_cards WHERE fs_share_id=?", (FS1,)), "#4778: the card went with its share")
check(revoked("wiki", W1) == 1, "... the row in obj_revoked")
r = Fr.post(B + f"/api/wiki/shares/p{FS1}/restore")
check(r.ok and r.json().get("id") == f"p{FS1}" and not r.json().get("revoked") and r.json().get("user", {}).get("name") == "fiona@example.com",
      f"Undo: the share and its card come back under the same id, with the typed address {r.status_code} {r.text[:160]}")
check(Fi.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 200, "... fiona reads again")

# a folder card with two core shares (the folder, the page of the same name): it ends as a whole
W2 = page(Fr, "Docs", "the index")
W3 = page(Fr, "Docs/Intro")
r = Fr.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Docs", "kind": "person", "email": "fiona@example.com"})
check(r.ok, f"frida shares the folder Docs {r.status_code} {r.text[:120]}")
fc = dbx("SELECT k.fs_share_id, k.pair_id FROM wiki_share_cards k JOIN fs_shares f ON f.id=k.fs_share_id JOIN fs_nodes n ON n.id=f.node_id "
         "WHERE n.kind='folder' AND n.owner_id=? AND k.folder", (FID,))
check(bool(fc and fc[0][0] and fc[0][1]), f"the folder card has two core shares {fc}")
C1, C2 = fc[0] if fc else (0, 0)
check(W3 in shared(Fi), "fiona reads the folder's page")
check(Fr.delete(B + f"/api/files/shares/{C1}").ok, "the folder's core share taken back in the file store's dialog")
check(not dbx("SELECT 1 FROM wiki_share_cards WHERE fs_share_id=?", (C1,)), "#4778: the folder card ended")
check(not dbx("SELECT 1 FROM fs_shares WHERE id IN (?, ?)", (C1, C2)), "... its other core share went with it")
check(W2 not in shared(Fi) and W3 not in shared(Fi), "... fiona reads none of its pages")
check(Gi.get(B + f"/api/wiki/shared/pages/{W3}").status_code == 404, "another person reads nothing of frida's pages")

sys.exit(kt.done("p2623_b_unshare_cards"))
