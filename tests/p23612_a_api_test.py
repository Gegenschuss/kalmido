#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.361.2 (#2923): the way back out of an organisation for a member -- the member asks, an admin releases it with one
click, then the member moves it into the private space themselves (once, within the grant days). Invented names only,
addresses @example.com. tenant-matrix: org
 - projects: a member's own project moved into the organisation -> moving it back is 403 with out_request; asking
   (POST /api/orgs/<oid>/out-requests) only for the maker (another member / an admin 403); the admins get a News item and see
   it in GET /api/orgs/<oid>/lists; the maker cannot decide; releasing (POST .../out-requests/<rid>) tells the maker and logs
   "outok"; the move then goes through (logged "moveout" released, the admins told) and uses the release up
 - tables: the dry run already answers 403 with out_request; a declined request tells the maker and keeps the 403; asked again
   and released the table goes private; a release older than the grant days does not count
 - files: the dry run's block carries out_request; after the release the block is gone and the folder moves
 - a release for something an admin took out meanwhile closes the request (409)
 - the dry run of a move INTO the organisation tells a member the way back; an admin does not get that note
 - a person without an organisation (freelancer-matrix: lists): the organisation's requests are 404, the own private
   project and table move and copy as before (no request needed)
usage: p23612_a_api_test.py <datadir>      (P23612A_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

BACK = "Back into your private space only after an admin of the organisation releases it"


def usess(user):
    s = sess(user)
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES + ",sheets", "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def news(uid, action):
    out = []
    for (d,) in sql("SELECT data FROM notifications WHERE user_id=? AND kind='orglist'", (uid,)):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if d.get("action") == action:
            out.append(d)
    return out


def log(action, kind=None):
    out = []
    for name, d in sql("SELECT list_name, detail FROM org_list_log WHERE action=? ORDER BY id", (action,)):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if kind is None or d.get("kind") == kind:
            out.append(dict(d, name=name))
    return out


def ask(s, kind, oid_):
    return s.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": kind, "id": oid_})


def decide(s, rid, d):
    return s.post(B + f"/api/orgs/{ORG}/out-requests/{rid}", json={"decision": d})


if not os.environ.get("P23612A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = usess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A = usess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("carol", "member"), ("erin", "admin")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Er = usess("bob"), usess("carol"), usess("erin")
BOB, ERIN = uid["bob"], uid["erin"]
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEATURES + ",sheets"})

# ================================================================ projects
LP = Bo.post(B + "/api/lists", json={"name": "Brought plan", "org_id": None}).json()["id"]
check(Bo.patch(B + f"/api/lists/{LP}", json={"org_id": ORG}).ok, "setup: bob moves his own project into the organisation")
r = Bo.patch(B + f"/api/lists/{LP}", json={"org_id": None})
check(r.status_code == 403 and r.json().get("out_request") == {"org": ORG, "kind": "list", "id": LP},
      "moving it back: 403 with what to ask for " + r.text[:300])
check(sql("SELECT org_id FROM lists WHERE id=?", (LP,))[0][0] == ORG, "the project stays in the organisation")
r = ask(Ca, "list", LP)
check(r.status_code == 403, "another member cannot ask for bob's project " + r.text[:200])
r = ask(Er, "list", LP)
check(r.status_code == 403, "an admin who is not its owner cannot ask for it either " + r.text[:200])
check(ask(Bo, "nope", LP).status_code == 400, "an unknown kind is refused (400)")
r = ask(Bo, "list", LP)
check(r.ok and r.json().get("state") == "open", "bob asks the admins " + r.text[:200])
RL = r.json().get("id")
r = ask(Bo, "list", LP)
check(r.ok and r.json().get("again") and r.json().get("id") == RL, "asking again gives the same request " + r.text[:200])
check(any(d.get("name") == "Brought plan" and d.get("org_id") == ORG for d in news(ERIN, "outreq"))
      and any(d.get("name") == "Brought plan" for d in news(ALICE, "outreq")), "both admins get a News item")
check(not news(uid["carol"], "outreq"), "a plain member gets none")
check([x["id"] for x in Bo.get(B + f"/api/orgs/{ORG}/out-requests").json()["requests"]] == [RL], "bob sees his own request")
check(Ca.get(B + f"/api/orgs/{ORG}/out-requests").json()["requests"] == [], "carol sees none of bob's requests")
check(any(x["id"] == RL and x["state"] == "open" for x in Er.get(B + f"/api/orgs/{ORG}/lists").json().get("out_requests", [])),
      "the admin sees it in Projects of the organisation")
check(Bo.patch(B + f"/api/lists/{LP}", json={"org_id": None}).status_code == 403, "an open request is no release yet")
check(decide(Bo, RL, "approve").status_code == 403, "bob cannot release his own request")
check(decide(Er, RL, "maybe").status_code == 400, "an unknown decision is refused (400)")
r = decide(Er, RL, "approve")
check(r.ok and r.json().get("state") == "approved", "erin releases it with one click " + r.text[:200])
check(decide(Er, RL, "decline").status_code == 409, "a decided request is not decided again (409)")
check(any(d.get("kind") == "list" and d.get("obj") == LP for d in news(BOB, "outok")), "bob is told it is released")
check(any(x["name"] == "Brought plan" for x in log("outok", "list")), "the release is in the organisation's log")
r = Bo.patch(B + f"/api/lists/{LP}", json={"org_id": None})
check(r.ok and sql("SELECT org_id FROM lists WHERE id=?", (LP,))[0][0] is None, "now bob moves it into his private space " + r.text[:200])
check(sql("SELECT owner_id FROM lists WHERE id=?", (LP,))[0][0] == BOB, "it is bob's (not an admin's)")
check(any(x.get("released") and x.get("to") == "private" for x in log("moveout", "list")), "the move is logged as released")
check(any(d.get("name") == "Brought plan" for d in news(ERIN, "moveout")), "the admins are told about the move")
check(sql("SELECT state FROM org_out_requests WHERE id=?", (RL,))[0][0] == "used", "the release is used up")
check(Bo.patch(B + f"/api/lists/{LP}", json={"org_id": ORG}).ok, "setup: into the organisation again")
check(Bo.patch(B + f"/api/lists/{LP}", json={"org_id": None}).status_code == 403, "a used release does not count a second time")

# ================================================================ tables (decline, ask again, expiry)
r = Bo.post(B + "/api/sheets", json={"title": "Team table", "space": f"org:{ORG}"})
check(r.status_code == 201, "setup: bob makes a table in the organisation " + r.text[:200])
SB = r.json().get("id")
r = Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private", "dry": 1})
check(r.status_code == 403 and (r.json().get("out_request") or {}).get("kind") == "sheet", "the dry run answers 403 with out_request " + r.text[:300])
RS = ask(Bo, "sheet", SB).json().get("id")
r = decide(Er, RS, "decline")
check(r.ok and r.json().get("state") == "declined", "erin declines " + r.text[:200])
check(any(d.get("name") == "Team table" for d in news(BOB, "outno")), "bob is told it was declined")
check(any(x["name"] == "Team table" for x in log("outno", "sheet")), "the decline is logged")
check(Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private"}).status_code == 403, "a declined request releases nothing")
r = ask(Bo, "sheet", SB)
check(r.ok and r.json().get("id") != RS and not r.json().get("again"), "bob may ask again " + r.text[:200])
RS2 = r.json().get("id")
check(decide(A, RS2, "approve").ok, "alice (the other admin) releases it")
sql("UPDATE org_out_requests SET decided_at=? WHERE id=?", ("2020-01-01T00:00:00Z", RS2), write=True)
check(Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private"}).status_code == 403, "a release older than the grant days does not count")
sql("UPDATE org_out_requests SET state='used' WHERE id=?", (RS2,), write=True)
RS3 = ask(Bo, "sheet", SB).json().get("id")
check(decide(Er, RS3, "approve").ok, "setup: released again")
r = Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private", "dry": 1})
check(r.ok and not r.json().get("block"), "the dry run passes now " + r.text[:200])
r = Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private"})
check(r.ok and sql("SELECT org_id, owner_id FROM sheets WHERE id=?", (SB,))[0] == (None, BOB), "the table is bob's private one " + r.text[:200])
check(any(x.get("released") for x in log("moveout", "sheet")), "logged as released")

# ================================================================ files
FB = Bo.post(B + "/api/files/folders", json={"name": "Brought folder", "space": f"org:{ORG}"}).json()["id"]
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private", "dry": 1})
check(r.ok and r.json().get("block") and r.json().get("out_request") == {"org": ORG, "kind": "file", "id": FB},
      "dry run: the block carries out_request " + r.text[:300])
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private"})
check(r.status_code == 403 and (r.json().get("out_request") or {}).get("id") == FB, "the move itself: 403 with out_request " + r.text[:200])
check(decide(Er, ask(Bo, "file", FB).json().get("id"), "approve").ok, "asked and released")
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private", "dry": 1})
check(r.ok and not r.json().get("block"), "the block is gone " + r.text[:200])
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private"})
check(r.ok and sql("SELECT org_id FROM fs_nodes WHERE id=?", (FB,))[0][0] is None, "the folder is in bob's private space " + r.text[:200])

# ================================================================ released after an admin took it out
r = Bo.post(B + "/api/sheets", json={"title": "Second table", "space": f"org:{ORG}"})
S2 = r.json().get("id")
R2 = ask(Bo, "sheet", S2).json().get("id")
check(Er.post(B + f"/api/sheets/{S2}/move-space", json={"to": "private"}).ok, "setup: erin takes the table out herself")
r = decide(Er, R2, "approve")
check(r.status_code == 409 and sql("SELECT state FROM org_out_requests WHERE id=?", (R2,))[0][0] == "declined",
      "releasing what is no longer in the organisation closes the request (409) " + r.text[:200])

# ================================================================ the note moving INTO the organisation
r = Bo.post(B + "/api/sheets", json={"title": "Mine first", "space": "private"})
SP = r.json().get("id")
r = Bo.post(B + f"/api/sheets/{SP}/move-space", json={"to": f"org:{ORG}", "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "a member's dry run into the organisation names the way back " + r.text[:300])
FP = Bo.post(B + "/api/files/folders", json={"name": "Mine folder", "space": "private"}).json()["id"]
r = Bo.post(B + "/api/files/move-space", json={"ids": [FP], "to": f"org:{ORG}", "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "the files' dry run too " + r.text[:300])
r = Er.post(B + "/api/sheets", json={"title": "Admin table", "space": "private"})
r = Er.post(B + f"/api/sheets/{r.json().get('id')}/move-space", json={"to": f"org:{ORG}", "dry": 1})
check(r.ok and not any(BACK in n for n in r.json().get("notes", [])), "an admin does not get the note " + r.text[:300])

# ================================================================ freelancer-matrix: lists
check(Fr.get(B + f"/api/orgs/{ORG}/out-requests").status_code == 404, "freelancer: another organisation's requests are 404")
check(Fr.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": "list", "id": LP}).status_code == 404, "freelancer: cannot ask there (404)")
check(decide(Fr, RL, "approve").status_code == 404, "freelancer: cannot decide there (404)")
FL = Fr.post(B + "/api/lists", json={"name": "Own plan"}).json()["id"]
check(Fr.patch(B + f"/api/lists/{FL}", json={"name": "Own plan 2", "org_id": None}).ok, "freelancer: the own project is saved as before")
check(Fr.post(B + f"/api/lists/{FL}/duplicate", json={}).ok, "freelancer: and copied")
r = Fr.post(B + "/api/sheets", json={"title": "Own table"})
check(r.status_code == 201 and Fr.get(B + f"/api/sheets/{r.json().get('id')}").ok, "freelancer: an own table as before")
check(sql("SELECT COUNT(*) FROM org_out_requests WHERE by_id=?", (FID,))[0][0] == 0, "freelancer: never a request")

print(f"p23612_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
