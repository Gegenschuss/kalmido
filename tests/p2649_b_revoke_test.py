#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.649.0 part B (#5051): the revocation register is complete. Own container (mode workspaces). Invented names only.
 - 1 a person's public file links (fs_ext_links) and file requests (fs_upload_requests) of an organisation are revoked when
   they leave it (revoked_at + a row in obj_revoked): back the same day as a guest, then made an admin again = still 404;
   restorable (the link's restore, the request's revoked=false) -- then they open again and the register row is gone.
   Made a guest: the links of nodes they can no longer share are revoked too (reason role); a file request stays while
   they can still write in its folder (the runtime rule of files/filereq.py frq_alive).
 - 2 an agent moved from one organisation to another loses its shares on the old organisation's nodes (obj_revoked), moving
   back opens nothing
 - 3 withdrawing an invitation (the account stays: another organisation's invitation lies on it) takes the person's shares
   through the core (obj_revoked) instead of only deleting the membership
 - 1 (Fable) while the creator may no longer share / write there, nobody can restore them (409, as obj_share_restore)
 - 4 the boundary repair takes a share and a table's card through the core: both visible in obj_revoked (reason boundary),
   the card ended (revoked_at), its core share gone
 - a person without an organisation (freelancer_fixture): their own link and file request stay untouched by all of it
freelancer-matrix: files
usage: p2649_b_revoke_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import requests  # noqa: E402
from kt import B, check, dbx, sess  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": "A" * 43 + "="},
         prefix="P2649B")

A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A.patch(B + "/api/admin/settings", json={"password": "password123", "public_links": True})
ALICE = A.get(B + "/api/me").json()["id"]


def user(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    return r.json()["id"], s


def org(name):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (oid, ALICE))
    return oid


def member(oid, email, uid, role):
    r = A.put(B + f"/api/orgs/{oid}/members", json={"email": email, "role": role})
    check(r.ok and dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)) == [(role,)], f"setup: {email} is {role} of {oid} {r.text[:160]}")


def page(path):
    return requests.get(B + path, allow_redirects=False).status_code


def link(s, nid):
    r = s.post(B + f"/api/files/nodes/{nid}/ext-links", json={"expires": "none"})
    check(r.ok, "setup: a public link " + r.text[:160])
    x = r.json()["links"][-1]
    return x["id"], x["url"][x["url"].index("/s/f/"):]


def upreq(s, nid):
    r = s.post(B + f"/api/files/nodes/{nid}/requests", json={"title": "Your documents", "days": 14})
    check(r.status_code == 201, "setup: a file request " + r.text[:160])
    return r.json()["id"], r.json()["url"][r.json()["url"].index("/u/"):]


def revoked(src, rid):
    return dbx("SELECT reason FROM obj_revoked WHERE src=? AND ref_id=?", (src, rid))


K = org("Kestrel")
BOB, Bo = user("bob")
member(K, "bob@example.com", BOB, "admin")
F = Bo.post(B + "/api/files/folders", json={"name": "Customer handover", "space": f"org:{K}"}).json()["id"]
XL, XP = link(Bo, F)
RQ, RP = upreq(Bo, F)
check(page(XP) == 200 and page(RP) == 200, "before: bob's link and file request open (a probe that always fails proves nothing)")

# the freelancer: her own link and file request in her private space
FID, Fr = freelancer(B, A, "frida")
FF = Fr.post(B + "/api/files/folders", json={"name": "Private handover", "space": "private"}).json()["id"]
FXL, FXP = link(Fr, FF)
FRQ, FRP = upreq(Fr, FF)
check(page(FXP) == 200 and page(FRP) == 200, "freelancer: her link and file request open")

# ================================================================== 1 leave -> back as a guest -> admin again: still dead
check(A.delete(B + f"/api/orgs/{K}/members/{BOB}").ok, "1: bob leaves the organisation")
check(dbx("SELECT revoked_at IS NOT NULL FROM fs_ext_links WHERE id=?", (XL,)) == [(True,)], "1 left: the link is revoked (revoked_at)")
check(dbx("SELECT revoked_at IS NOT NULL FROM fs_upload_requests WHERE id=?", (RQ,)) == [(True,)], "1 left: the file request is revoked")
check(revoked("fs_ext_links", XL) == [("leave",)] and revoked("fs_upload_requests", RQ) == [("leave",)], "1 left: both in obj_revoked (leave)")
check(not dbx("SELECT 1 FROM obj_revoked WHERE src='fs_ext_links' AND row_json LIKE '%token%'"), "1 left: no token in the register")
# Fable 1: an owner of the folder (alice) cannot bring them back while bob may no longer share / write there (409, the
# register row stays) -- else they would open again by themselves the day bob comes back as an admin
r = A.post(B + f"/api/files/ext-links/{XL}/restore")
check(r.status_code == 409 and revoked("fs_ext_links", XL) == [("leave",)], "1 left: alice restores bob's link -> 409, still in the register " + r.text[:160])
r = A.patch(B + f"/api/files/requests/{RQ}", json={"revoked": False})
check(r.status_code == 409 and revoked("fs_upload_requests", RQ) == [("leave",)]
      and dbx("SELECT revoked_at IS NOT NULL FROM fs_upload_requests WHERE id=?", (RQ,)) == [(True,)],
      "1 left: alice reopens bob's file request -> 409, still revoked " + r.text[:160])
member(K, "bob@example.com", BOB, "guest")
check(page(XP) == 404 and page(RP) == 404, "1 back as a guest: link and file request 404")
member(K, "bob@example.com", BOB, "admin")
check(page(XP) == 404, "1 back as an admin: the old link stays 404 (was: open again without any step)")
check(page(RP) == 404, "1 back as an admin: the old file request stays 404")
# restorable: the link's restore and the request's revoked=false (an owner of the folder)
r = Bo.post(B + f"/api/files/ext-links/{XL}/restore")
check(r.ok and page(XP) == 200 and not revoked("fs_ext_links", XL), "1 restored: the link opens again, the register row is gone " + r.text[:160])
r = Bo.patch(B + f"/api/files/requests/{RQ}", json={"revoked": False})
check(r.ok and page(RP) == 200 and not revoked("fs_upload_requests", RQ), "1 restored: the file request opens again " + r.text[:160])

# ---- made a guest: the links of nodes bob can no longer share go (reason role); made an admin again = still dead
member(K, "bob@example.com", BOB, "guest")
check(dbx("SELECT revoked_at IS NOT NULL FROM fs_ext_links WHERE id=?", (XL,)) == [(True,)] and revoked("fs_ext_links", XL) == [("role",)],
      "1 made a guest: the link is revoked (role)")
# a guest keeps the write right in the folder he made: his file request stays (the same rule as files/filereq.py frq_alive)
check(not revoked("fs_upload_requests", RQ) and page(RP) == 200, "1 made a guest: the file request of a folder he still writes in stays")
member(K, "bob@example.com", BOB, "admin")
check(page(XP) == 404, "1 admin again: the link does not reopen")
check(page(FXP) == 200 and page(FRP) == 200, "freelancer: untouched by bob's leaving and role changes")

# ================================================================== 2 an agent alt -> new -> alt opens nothing
K2 = org("Osprey")
r = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper"})
check(r.ok, "setup: a team agent " + r.text[:160])
AG = r.json()["id"]
check(A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": K}).ok, "setup: the agent works in Kestrel")
AF = A.post(B + "/api/files/folders", json={"name": "Agent inbox", "space": f"org:{K}"}).json()["id"]
dbx("INSERT INTO fs_shares(node_id,agent_id,role,created_by,created_at) VALUES(?,?,'edit',?,'2026-11-07T10:00:00+00:00')", (AF, AG, ALICE))
check(dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND agent_id=?", (AF, AG)), "setup: the agent has a share on Kestrel's folder")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": K2})
check(r.ok, "2: the agent moves to Osprey " + r.text[:160])
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND agent_id=?", (AF, AG)), "2 moved: its share on the old organisation's folder is gone")
check(dbx("SELECT reason FROM obj_revoked WHERE src='fs_shares' AND user_id=? AND org_id=?", (AG, K)) == [("leave",)], "2 moved: the share is in obj_revoked")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": K}).ok, "2: the agent moves back to Kestrel")
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND agent_id=?", (AF, AG)), "2 back: moving back opens nothing")

# ================================================================== 3 withdrawing an invitation goes through the core
r = A.post(B + f"/api/orgs/{K}/invites", json={"email": "nina@example.com", "role": "member"})
check(r.ok, "setup: Kestrel invites a new address " + r.text[:160])
NINA = dbx("SELECT id FROM users WHERE email='nina@example.com'")[0][0]
ERIN, Er = user("erin")  # Osprey's admin (no instance admin: an instance admin adds an existing account at once)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin')", (K2, ERIN))
r = Er.post(B + f"/api/orgs/{K2}/invites", json={"email": "nina@example.com", "role": "member"})
check(r.ok and dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (K2, NINA)), "setup: Osprey invites the same address " + r.text[:160])
NF = A.post(B + "/api/files/folders", json={"name": "Welcome pack", "space": f"org:{K}"}).json()["id"]
dbx("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,'view',?,'2026-11-07T10:00:00+00:00')", (NF, NINA, ALICE))
ref = {x["email"]: x for x in A.get(B + f"/api/orgs/{K}/invites").json()["invites"]}["nina@example.com"]["ref"]
r = A.delete(B + f"/api/orgs/{K}/invites/{ref}")
check(r.ok and dbx("SELECT 1 FROM users WHERE id=?", (NINA,)), "3: Kestrel withdraws, the account stays (Osprey's invitation) " + r.text[:160])
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND user_id=?", (NF, NINA)), "3 withdrawn: the share in Kestrel is gone")
check(dbx("SELECT reason FROM obj_revoked WHERE src='fs_shares' AND user_id=? AND org_id=?", (NINA, K)) == [("leave",)],
      "3 withdrawn: the revocation is written (obj_revoked)")

# ================================================================== 4 the boundary repair goes through obj_revoked
OTTO, _ = user("otto")  # no member of Kestrel
dbx("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,'view',?,'2026-11-07T10:00:00+00:00')", (AF, OTTO, ALICE))
CARL, _ = user("carl")
member(K, "carl@example.com", CARL, "member")
r = A.post(B + "/api/sheets", json={"title": "Fruit", "space": f"org:{K}"})
check(r.ok, "setup: a table of Kestrel " + r.text[:160])
SID = r.json()["id"]
check(A.post(B + f"/api/sheets/{SID}/shares", json={"user_id": CARL, "role": "read"}).status_code == 201, "setup: carl gets the table")
# 2.937.0 (#5244): carl's share is the core share of the table's node (no card any more)
CARD = dbx("SELECT 0, f.id FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=? "
           "AND f.user_id=?", (SID, CARL))
check(CARD and CARD[0][1], f"setup: carl's core share {CARD}")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (K, CARL))  # outside every route: a row across the boundary
r = A.post(B + "/api/admin/orgs/boundary/repair", json={})
check(r.ok and r.json().get("removed", 0) >= 2, "4: the repair runs " + r.text[:200])
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND user_id=?", (AF, OTTO)), "4: otto's share is gone")
check(dbx("SELECT reason FROM obj_revoked WHERE src='fs_shares' AND user_id=?", (OTTO,)) == [("boundary",)], "4: otto's share is in obj_revoked (boundary)")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=?", (SID,)), "4: 2.937.0 (#5244): no card of carl (the share was the core's only)")
check(not dbx("SELECT 1 FROM fs_shares WHERE id=?", (CARD[0][1],)), "4: carl's core share is gone")
check(dbx("SELECT reason FROM obj_revoked WHERE src='fs_shares' AND user_id=? AND kind='sheet' AND ref_id=?", (CARL, SID)) == [("boundary",)],
      "4: carl's core share is in obj_revoked (boundary)")
check(page(FXP) == 200 and page(FRP) == 200, "freelancer: her link and file request still open after the repair")

sys.exit(kt.done("p2649_b_revoke"))
