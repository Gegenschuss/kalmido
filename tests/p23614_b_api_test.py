#!/usr/bin/env python3
# kalmido-suite:
"""2.361.4 B (#2935) API tests, own container (kt.fresh): moving between the private space and an organisation loses
nothing silently.
 - absences: a new entry lands in the area the workspace switch shows ("Private" = the personal area, never quietly the
   first organisation; the switch on the organisation = that organisation); freelancer-matrix: absences (a person without
   an organisation: always the personal area)
 - file move: the dry run names the external links that end (links) and the file requests (requests): one's own go along,
   another person's end; after the move the own request's upload page still opens (its org_id followed the folder),
   the external link is gone
 - knowledge move: the dry run names the shares that end and that linked files of the file store stay behind
usage: p23614_b_api_test.py <datadir>"""
import sys

import requests

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer, org_join

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,files,wiki,office"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
org_join(B, "bob", ORG)
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,files,wiki"})
FID, Fr = freelancer(B, A, "frida")


# ================================================================== absences follow the workspace switch
def absence(s, day):
    r = s.post(B + "/api/team/absences", json={"kind": "off", "start_date": day, "end_date": day})
    check(r.status_code == 201, f"absence {day} saved {r.status_code} {r.text[:160]}")
    return kt.dbx("SELECT org_id FROM hub_absences WHERE id=?", (r.json().get("id"),))[0][0] if r.ok else None


Bo.patch(B + "/api/settings", json={"workspace": "private"})
got = absence(Bo, "2026-11-02")
pers = Bo.get(B + "/api/team/absences").json().get("personal")
check(got and got == pers and got != ORG, f"#2935: switch on Private: the absence is in bob's personal area {got} {pers} (org {ORG})")
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(absence(Bo, "2026-11-03") == ORG, "#2935: switch on the organisation: the absence is the organisation's")
# freelancer-matrix: absences (no organisation: the personal area)
got = absence(Fr, "2026-11-04")
check(got and got == Fr.get(B + "/api/team/absences").json().get("personal"), f"#2935: a freelancer's absence is in the personal area {got}")

# ================================================================== file move: external links + file requests
r = A.post(B + "/api/files/folders", json={"name": "Shoot", "space": f"org:{ORG}"})
FO = r.json().get("id") if r.status_code == 201 else None
check(FO, f"setup: a folder of the organisation {r.text[:120]}")
r = A.post(B + "/api/files/upload", data={"parent_id": FO}, files={"file": ("plan.txt", b"invented plan", "text/plain")})
FI = ((r.json().get("items") or [{}])[0]).get("id") if r.ok else None
check(FI, f"setup: a file in it {r.text[:120]}")
r = A.post(B + f"/api/files/nodes/{FI}/ext-links", json={"expires": "30d"})
check(r.ok, f"setup: an external link of the file {r.status_code} {r.text[:160]}")
r = A.post(B + f"/api/files/nodes/{FO}/requests", json={"title": "For the client", "days": 7})
check(r.status_code == 201 and r.json().get("url"), f"setup: alice's file request {r.status_code} {r.text[:160]}")
TOK = (r.json().get("url") or "/u/x").rsplit("/u/", 1)[1]
check(A.post(B + f"/api/files/nodes/{FO}/shares", json={"user_id": BOB, "role": "edit"}).ok, "setup: the folder shared with bob (edit)")
r = Bo.post(B + f"/api/files/nodes/{FO}/requests", json={"title": "Bob's request", "days": 7})
check(r.status_code == 201, f"setup: bob's file request {r.status_code} {r.text[:160]}")
check(requests.get(B + "/u/" + TOK, timeout=30).status_code == 200, "setup: the upload page opens before the move")

r = A.post(B + "/api/files/move-space", json={"ids": [FO], "to": "private", "dry": 1})
j = r.json() if r.ok else {}
notes = " | ".join(j.get("notes") or [])
check(r.ok and j.get("links") == 1 and "external link ends" in notes, f"#2935: the dry run names the external link that ends {j}")
check(j.get("requests") == 2 and "1 file request goes along" in notes and "1 file request of another person ends" in notes,
      f"#2935: the dry run names the file requests (alice's goes along, bob's ends) {notes}")
check(len(kt.dbx("SELECT 1 FROM fs_ext_links WHERE node_id=?", (FI,))) == 1, "#2935: the dry run changes nothing")

r = A.post(B + "/api/files/move-space", json={"ids": [FO], "to": "private"})
check(r.ok, f"the folder moved into alice's private space {r.status_code} {r.text[:160]}")
check(not kt.dbx("SELECT 1 FROM fs_ext_links WHERE node_id=?", (FI,)), "#2935: the external link ended with the move")
rows = kt.dbx("SELECT org_id FROM fs_upload_requests WHERE node_id=?", (FO,))
check(len(rows) == 2 and all(x[0] is None for x in rows), f"#2935: the file requests followed the folder into the private space {rows}")
check(requests.get(B + "/u/" + TOK, timeout=30).status_code == 200, "#2935: alice's upload page still opens after the move")
lst = A.get(B + f"/api/files/nodes/{FO}/requests")
check(lst.ok and len(lst.json().get("requests") or []) == 2, f"#2935: the folder still lists its requests {lst.status_code} {lst.text[:160]}")

# ================================================================== knowledge move: shares + linked files named
r = A.post(B + "/api/wiki/pages", json={"space": "private", "path": "Brief/Day one", "body": f"See /api/files/nodes/{FI}/download"})
check(r.status_code == 201, f"setup: a private page linking a file {r.text[:120]}")
PG = r.json().get("id")
check(A.post(B + "/api/wiki/shares", json={"page_id": PG, "kind": "person", "user_id": BOB}).status_code in (200, 201), "setup: the page shared with bob")
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "folder": "Brief", "to": f"org:{ORG}", "dry": 1})
notes = " | ".join((r.json() if r.ok else {}).get("notes") or [])
check(r.ok and "files stay in the old workspace" in notes and "share" in notes and (r.json().get("shares") or 0) >= 1,
      f"#2935: the knowledge dry run names the share that ends and the linked file staying behind {notes}")

sys.exit(kt.done("p23614_b_api"))
