#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1168.0 part A (#4782): the shared core, stage 3 follow-up (review N2 of 2.566.0). Own container (mode workspaces). Invented
names only.  tenant-matrix: calendar, book   freelancer-matrix: pim
 - N2: a share that ran out on the reference node of a calendar / address book stops no workspace move (accounts/orgs.py
   _obj_sharers: was a 409 for a share nobody can use); a live one still does (control)
 - the run-out shares that would not fit the new workspace (a person outside it, a group) go with the move, one that fits stays;
   the nightly boundary check then has no finding for them
 - a person without an organisation: her calendar / book saved with org_id private (no move), no move into an organisation
 (F6 / F7 / N1 of the task: built on main by 2.647.0 #5046 and 2.924.0 #5069 -- tests/p2566_c_kern_cal_test.py, p2924_b_kern_calbook)
usage: p21168_a_kern_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, sess  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files"
TS = "2026-11-05T00:00:00+00:00"
PAST = "2026-01-01T00:00:00+00:00"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P21168A")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def node(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def share(kind, rid, who):
    """The role of the core share of account who on the object's node (None: none)."""
    r = sql("SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
            "AND (s.user_id=? OR s.agent_id=?)", (kind, rid, who, who))
    return r[0][0] if r else None


def boundary(s):
    r = s.get(B + "/api/admin/orgs")
    assert r.ok, r.text
    return (r.json().get("boundary") or {}).get("kinds") or {}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina", "olga"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
BOB, GINA, OLGA = uid["bob"], uid["gina"], uid["olga"]

ORGS = []
for name in ("Northwind Studio", "Southwind Works"):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    ORGS.append(r.json()["id"])
    sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (ORGS[-1], ALICE), write=True)
ORG, ORG2 = ORGS
for oid, who in ((ORG, BOB), (ORG, GINA), (ORG2, GINA)):  # bob only in the first, gina in both, olga in none
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    r = A.put(B + f"/api/orgs/{oid}/members", json={"email": mail, "role": "member"})
    check(r.ok and sql("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, who)) == [("member",)], f"setup: {who} in {oid} {r.text[:160]}")

# ================================================================== N2: a calendar of the organisation into another one
K = A.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
for who in (BOB, GINA):
    check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": who, "role": "view"}).ok and share("evcal", K, who) == "view",
          f"the calendar shared with {who}")
NK = node("evcal", K)
r = A.patch(B + f"/api/evcals/{K}", json={"org_id": ORG2})
check(r.status_code == 409 and sql("SELECT org_id FROM ev_cals WHERE id=?", (K,)) == [(ORG,)],
      f"control: bob's live share stops the move into an organisation he is not in ({r.status_code})")
sql("UPDATE fs_shares SET expires_at=? WHERE node_id=?", (PAST, NK), write=True)  # both shares ran out
sql("INSERT INTO groups(name,created_at,created_by) VALUES('Rota team',?,?)", (TS, ALICE), write=True)
GRP = sql("SELECT id FROM groups WHERE name='Rota team'")[0][0]
sql("INSERT INTO fs_shares(node_id,group_id,role,created_at,expires_at) VALUES(?,?,'view',?,?)", (NK, GRP, TS, PAST), write=True)
r = A.patch(B + f"/api/evcals/{K}", json={"org_id": ORG2})
check(r.ok and sql("SELECT org_id FROM ev_cals WHERE id=?", (K,)) == [(ORG2,)],
      f"#4782 N2: shares that ran out (bob's, a group's) stop no move ({r.status_code} {r.text[:160]})")
check(sql("SELECT org_id FROM fs_nodes WHERE id=?", (NK,)) == [(ORG2,)], "its node followed")
check(share("evcal", K, BOB) is None, "#4782 N2: bob's run-out share (he is not in the new organisation) went with the move")
check(not sql("SELECT 1 FROM fs_shares WHERE node_id=? AND group_id=?", (NK, GRP)), "#4782 N2: so did the group's run-out share")
check(share("evcal", K, GINA) == "view", "gina's run-out share stays (she fits the new organisation)")
kinds = boundary(A)
check(not kinds.get("cal_person") and not kinds.get("cal_agent"), f"#4782 N2: the nightly boundary check finds nothing on it {kinds}")

# ================================================================== N2: a private address book into an organisation
BK = A.post(B + "/api/books", json={"name": "Private contacts"}).json()["id"]
r = A.put(B + f"/api/books/{BK}/members", json={"user_id": BOB, "role": "view"})
check(r.ok and share("address_book", BK, BOB) == "view", f"alice's private book shared with bob {r.status_code} {r.text[:160]}")
NB = node("address_book", BK)
r = A.patch(B + f"/api/books/{BK}", json={"org_id": ORG2})
check(r.status_code == 409 and sql("SELECT org_id FROM books WHERE id=?", (BK,)) == [(None,)],
      f"control: bob's live share stops the move into an organisation he is not in ({r.status_code})")
check(share("address_book", BK, BOB) == "view", "control: and the refused move dropped nothing")
# 2.1168.0 (#4782, Fable review F3): a run-out share that does not fit next to a live one that does not: the refused move
# drops nothing (the drop runs after every check)
# (olga shares no workspace with alice: the row as an old one left behind, written directly)
sql("INSERT INTO fs_shares(node_id,user_id,role,created_at,expires_at) VALUES(?,?,'view',?,?)", (NB, OLGA, TS, PAST), write=True)
r = A.patch(B + f"/api/books/{BK}", json={"org_id": ORG2})
check(r.status_code == 409 and share("address_book", BK, OLGA) == "view",
      f"#4782 review F3: bob's live share refuses the move, olga's run-out one stays with it ({r.status_code})")
sql("UPDATE fs_shares SET expires_at=? WHERE node_id=? AND user_id=?", (PAST, NB, BOB), write=True)
r = A.patch(B + f"/api/books/{BK}", json={"org_id": ORG2})
check(r.ok and sql("SELECT org_id FROM books WHERE id=?", (BK,)) == [(ORG2,)],
      f"#4782 N2: bob's run-out share stops the book's move no more ({r.status_code} {r.text[:160]})")
check(share("address_book", BK, BOB) is None and share("address_book", BK, OLGA) is None, "#4782 N2: and went with it (olga's too)")
# Fable review F2: through the core's step -- in the node's history and in obj_revoked (reason move), not silently
check(len(sql("SELECT 1 FROM fs_log WHERE node_id=? AND action='unshare'", (NB,))) == 2, "#4782 review F2: both take-backs in the node's history")
check(len(sql("SELECT 1 FROM obj_revoked WHERE src='fs_shares' AND reason='move' AND kind='address_book' AND ref_id=?", (BK,))) == 2,
      "#4782 review F2: and kept the core's way (obj_revoked, reason move)")
kinds = boundary(A)
check(not kinds.get("book_person"), f"#4782 N2: no finding of the nightly check for the book {kinds}")

# ================================================================== Fable review F3: a group's live share still refuses; out to private
K2 = A.post(B + "/api/evcals", json={"name": "Rota", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/evcals/{K2}/members", json={"user_id": GINA, "role": "view"}).ok, "a second calendar shared with gina")
NK2 = node("evcal", K2)
sql("INSERT INTO fs_shares(node_id,group_id,role,created_at) VALUES(?,?,'view',?)", (NK2, GRP, TS), write=True)
r = A.patch(B + f"/api/evcals/{K2}", json={"org_id": None})
check(r.status_code == 409 and sql("SELECT org_id FROM ev_cals WHERE id=?", (K2,)) == [(ORG,)],
      f"control: a group's live share still refuses a move ({r.status_code})")
sql("UPDATE fs_shares SET expires_at=? WHERE node_id=? AND group_id=?", (PAST, NK2, GRP), write=True)
r = A.patch(B + f"/api/evcals/{K2}", json={"org_id": None})
check(r.ok and sql("SELECT org_id FROM ev_cals WHERE id=?", (K2,)) == [(None,)]
      and not sql("SELECT 1 FROM fs_shares WHERE node_id=? AND group_id=?", (NK2, GRP)) and share("evcal", K2, GINA) == "view",
      f"#4782 review F3: out to private the run-out group share goes, gina's live one stays ({r.status_code} {r.text[:120]})")
kinds = boundary(A)
check(not kinds.get("cal_person") and not kinds.get("file_person"), f"#4782: no finding of the nightly check {kinds}")

# ================================================================== a person without an organisation (the same routes)
FID, F = freelancer(B, A)
FK = F.post(B + "/api/evcals", json={"name": "Frida's week"}).json()["id"]
FB = F.post(B + "/api/books", json={"name": "Frida's clients"}).json()["id"]
r = F.patch(B + f"/api/evcals/{FK}", json={"name": "Frida's week 2", "org_id": None})
check(r.ok and sql("SELECT name, org_id FROM ev_cals WHERE id=?", (FK,)) == [("Frida's week 2", None)],
      f"freelancer: her calendar saved with org_id private (no move) ({r.status_code} {r.text[:120]})")
r = F.patch(B + f"/api/books/{FB}", json={"name": "Frida's clients 2", "org_id": None})
check(r.ok and sql("SELECT name, org_id FROM books WHERE id=?", (FB,)) == [("Frida's clients 2", None)],
      f"freelancer: her book likewise ({r.status_code} {r.text[:120]})")
r = F.patch(B + f"/api/evcals/{FK}", json={"org_id": ORG})
check(r.status_code in (403, 409) and sql("SELECT org_id FROM ev_cals WHERE id=?", (FK,)) == [(None,)],
      f"freelancer: no move into an organisation she is not in ({r.status_code})")

sys.exit(kt.done("p21168_a_kern"))
