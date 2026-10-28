#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.401.0 (#2924) API tests, own container (kt.fresh): a project into another workspace loses nothing silently.
 - the dry run POST /api/lists/<id>/move-space {to, dry: 1} names what the move ends (client, "also in" link), what goes
   along (customer reports) and what stays in the old workspace (an attached table); it blocks what the move refuses (a
   member outside the organisation, a family project) and answers 400 without dry
 - a project with client, table, customer report and "also in" link out of the organisation and back: the customer report
   goes along both ways (visible in the space of its project), its client is unbound outside and back with the move back;
   client and link of the project come back (move_restored)
 - freelancer-matrix: lists (the person without an organisation: no other workspace -> 409, never 403 / 5xx)
usage: p2401_a_api_test.py <datadir>"""
import secrets
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer, org_join

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,family,files,wiki,sheets,office,clients"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
FID, Fr = freelancer(B, A, "frida")


def new_list(s, name, org=None, **b):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org, **b})
    assert r.ok, r.text
    return r.json()["id"]


def new_task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def dry(s, lid, to):
    return s.post(B + f"/api/lists/{lid}/move-space", json={"to": to, "dry": 1})


def one(sql, args=()):
    rows = kt.dbx(sql, args)
    return rows[0] if rows else None


# ================================================================== setup: an organisation project with everything attached
W = new_list(A, "Website relaunch", ORG)
W2 = new_list(A, "Content", ORG)
cl = A.post(B + "/api/clients", json={"name": "Northwind Example GmbH", "org_id": ORG})
CL = cl.json().get("id") if cl.ok else None
check(CL and A.patch(B + f"/api/lists/{W}", json={"client_id": CL}).ok, f"setup: the project has a client of the organisation {cl.text[:120]}")
T1 = new_task(A, W, "Logo is blurry")
T2 = new_task(A, W2, "Texts for the start page")
check(A.post(B + f"/api/tasks/{T2}/links", json={"list_id": W}).ok, "setup: a task of another project is also in the project")
sh = A.post(B + "/api/sheets", json={"title": "Budget", "space": f"org:{ORG}", "list_id": W})
check(sh.ok, f"setup: a table attached to the project {sh.text[:120]}")
tok = secrets.token_urlsafe(24)
kt.dbx("INSERT INTO portal_tickets(task_id,list_id,org_id,owner_id,client_id,name,email,email_hash,token,token_hash,notify,created_at,claimed) "
       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)", (T1, W, ORG, None, CL, "Erika Example", "", "", "x", "th-" + tok, 0, "2026-10-28T08:00:00Z"))
PT = one("SELECT id FROM portal_tickets WHERE task_id=?", (T1,))
check(PT, "setup: a customer report on a task of the project")

# ================================================================== the dry run
r = dry(A, W, "private")
j = r.json() if r.ok else {}
notes = " | ".join(j.get("notes") or [])
check(r.ok and not j.get("block"), f"#2924: the dry run out of the organisation (alice is its admin) does not block {r.status_code} {r.text[:200]}")
check("client of the project" in notes, f"#2924: the dry run names the client that is taken off: {notes}")
check("1 link to another project" in notes, f"#2924: the dry run names the 'also in' link that ends: {notes}")
check("1 customer report moves along" in notes, f"#2924: the dry run names the customer report that goes along: {notes}")
check("1 table" in notes and "old workspace" in notes, f"#2924: the dry run names the table that stays behind: {notes}")
check(one("SELECT org_id FROM lists WHERE id=?", (W,))["org_id"] == ORG, "#2924: the dry run moves nothing")
r = A.post(B + f"/api/lists/{W}/move-space", json={"to": "private"})
check(r.status_code == 400, f"#2924: without dry the route answers 400 (the move is PATCH /api/lists/<id>) {r.status_code}")
r = dry(A, W, f"org:{ORG}")
check(r.status_code == 409, f"#2924: the same workspace = 409 {r.status_code}")

# a private project shared with frida (no member of the organisation) cannot go into it: block, named
P = new_list(A, "Garden party")
check(A.put(B + f"/api/lists/{P}/members", json={"email": "frida@example.com", "role": "edit"}).ok, "setup: frida is in alice's private project")
r = dry(A, P, f"org:{ORG}")
check(r.ok and "frida" in (r.json().get("block") or "").lower(), f"#2924: a member outside the organisation blocks the dry run {r.text[:200]}")
FAM = new_list(A, "Shopping", family="shopping")
r = dry(A, FAM, f"org:{ORG}")
check(r.ok and r.json().get("block"), f"#2924: a family project blocks the dry run {r.text[:200]}")
r = dry(A, P, "private")
check(r.status_code == 409, f"#2924: private -> private = 409 {r.status_code}")

# ================================================================== the move out of the organisation and back
r = A.patch(B + f"/api/lists/{W}", json={"org_id": None})
me = r.json().get("move_ended") or {}
check(r.ok and me.get("client") == 1 and me.get("links") == 1 and me.get("tclients") == 1,
      f"#2924: out of the organisation the answer names client, link and the report's client {r.text[:200]}")
t = one("SELECT org_id, owner_id, client_id FROM portal_tickets WHERE id=?", (PT["id"],))
check(t and t["org_id"] is None and t["owner_id"] == AID,
      f"#2924: the customer report goes along into the private space (else it is invisible there) {t}")
check(t and t["client_id"] is None, f"#2924: the report's client of the organisation is unbound in the private space {t}")
check(one("SELECT COUNT(*) AS n FROM portal_tickets p JOIN lists l ON l.id=p.list_id WHERE p.org_id IS DISTINCT FROM l.org_id")["n"] == 0,
      "#2924: no customer report outside the space of its project (tenancy portal_ticket)")

r = A.patch(B + f"/api/lists/{W}", json={"org_id": ORG})
mr = r.json().get("move_restored") or {}
check(r.ok and mr.get("client") == 1 and mr.get("links") == 1 and mr.get("tclients") == 1,
      f"#2924: back into the organisation client, link and the report's client come back {r.text[:200]}")
check(one("SELECT client_id FROM lists WHERE id=?", (W,))["client_id"] == CL, "#2924: the project has its client again")
t = one("SELECT org_id, owner_id, client_id FROM portal_tickets WHERE id=?", (PT["id"],))
check(t and t["org_id"] == ORG and t["owner_id"] is None and t["client_id"] == CL, f"#2924: the customer report is back in the organisation with its client {t}")
check(one("SELECT COUNT(*) AS n FROM task_links WHERE task_id=? AND list_id=?", (T2, W))["n"] == 1, "#2924: the 'also in' link is back")
check(one("SELECT list_id, org_id FROM sheets WHERE id=?", (sh.json().get("id"),)) and
      one("SELECT org_id FROM sheets WHERE id=?", (sh.json().get("id"),))["org_id"] == ORG, "#2924: the table stayed in the organisation (named by the dry run)")

# ================================================================== freelancer (freelancer-matrix: lists)
FL = new_list(Fr, "Client work")
r = dry(Fr, FL, "private")
check(r.status_code == 409, f"freelancer: her own project is already private (no other workspace) -> 409, not 403 / 5xx {r.status_code}")
r = dry(Fr, FL, f"org:{ORG}")
check(r.status_code == 409, f"freelancer: an organisation she is not a member of -> 409 {r.status_code}")
r = dry(Fr, W, "private")
check(r.status_code in (403, 404), f"freelancer: somebody else's project -> 403 / 404 {r.status_code}")

sys.exit(kt.done("p2401_a"))
