#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.654.0 B (#5050): the projects' share rows of the core (kalmido/lists/lmcore.py) mirror list_members on every way. Invented names only.
 - a restore of a row that is not the project's own (list_own 0: the file store's share on the project's node) goes through the
   node's history and its hooks (core/objects.py obj_share_restore -> fs_log_add -> lffolder._on_change -> grp_sync): the person
   gets the role through the node (frole) at once and sees the project
 - joining a project visible to the whole organisation (POST /api/lists/<id>/join, lists/orgvis.py ov_join) writes the core's
   row of the own share: GET /api/lists/<id>/shares shows it
 - handing a project to someone else (POST /api/lists/<id>/owner): the old owner stays as list admin with the core's row
 - an own share that ran out ends at once (core/access.py _list_role reads the row's expiry), without the watchdog's round:
   404; a role through a group stays as that role
freelancer-matrix: lists (a person without an organisation: her private project shared by e-mail, the expiry ends it at once)
usage: p2654_b_list_mirror_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, docker_logs_on_first_fail, done, fresh, sess  # noqa: E402

fresh(prefix="P2654B")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments,fields"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "dora", "emil"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} " + r.text[:200])
    uid[u] = r.json().get("id")
S = {u: sess(u) for u in uid}
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments,fields"})


def new_list(s, name, org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "folder": "", **({"org_id": org} if org else {})})
    assert r.ok, (name, r.status_code, r.text[:300])
    return r.json()["id"]


def sees(s, lid):
    return s.get(B + f"/api/lists/{lid}/overview").ok


def core_row(lid, who_id):
    """The core's own share row of who_id on project lid: (role, list_role, list_own, expires_at) or None."""
    r = dbx("""SELECT s.role, s.list_role, s.list_own, s.expires_at FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
               WHERE n.kind='ref' AND n.ref_kind='list' AND n.ref_id=? AND COALESCE(s.user_id, s.agent_id)=? AND s.list_own=1""",
            (lid, who_id))
    return tuple(r[0]) if r else None


def node_of(lid):
    r = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='list' AND ref_id=?", (lid,))
    return r[0][0] if r else None


def expire(lid, who_id):
    """The own share's row of who_id on project lid ran out (no watchdog round follows)."""
    dbx("UPDATE fs_shares SET expires_at=? WHERE list_own=1 AND (user_id=? OR agent_id=?) AND node_id=?",
        ("2000-01-01T00:00:00Z", who_id, who_id, node_of(lid)))


# ---------------------------------------------------------------- (1) restore of the file store's row on the node
L1 = new_list(A, "Dock plan")
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: the node exists (a member)")
N1 = node_of(L1)
r = A.post(B + f"/api/files/nodes/{N1}/shares", json={"user_id": uid["carl"], "role": "view"})
check(r.status_code == 201 and sees(S["carl"], L1), "setup: the file store's share of the node gives carl the project " + r.text[:160])
FS = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=? AND COALESCE(list_own,0)=0", (N1, uid["carl"]))[0][0]
rowj = {"id": FS, "node_id": N1, "user_id": uid["carl"], "group_id": None, "agent_id": None, "role": "view", "expires_at": None,
        "created_by": ALICE, "created_at": "2026-11-01T08:00:00Z", "by_role": "admin", "list_role": None, "list_own": 0}
# the state after the row was taken (the core's revocation): no share, no role through it
dbx("DELETE FROM fs_shares WHERE id=?", (FS,))
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (L1, uid["carl"]))
RV = dbx("INSERT INTO obj_revoked(src,org_id,user_id,kind,ref_id,row_json,reason,by_id,created_at) VALUES('fs_shares',?,?,'list',?,?,'leave',?,?) RETURNING id",
         (ORG, uid["carl"], L1, json.dumps(rowj), ALICE, "2026-11-05T08:00:00Z"))[0][0]
check(not sees(S["carl"], L1), "setup: carl does not see the project")
LOGS = dbx("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='share'", (N1,))[0][0]
r = A.post(B + f"/api/lists/{L1}/shares/{RV}/restore")
m = dbx("SELECT own_role, frole FROM list_members WHERE list_id=? AND user_id=?", (L1, uid["carl"]))
check(r.ok and m == [(None, "view")], f"the restored file store row gives the role through the node at once (frole view) {m} {r.text[:160]}")
check(sees(S["carl"], L1) and core_row(L1, uid["carl"]) is None, "carl sees the project again, no own membership row")
check(dbx("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='share'", (N1,))[0][0] == LOGS + 1
      and dbx("SELECT detail FROM fs_log WHERE node_id=? AND action='share' ORDER BY id DESC LIMIT 1", (N1,)) == [(f"user:{uid['carl']}:view",)],
      "the node's history notes the restore as a share")

# ---------------------------------------------------------------- (2) joining an organisation-wide project
L2 = new_list(A, "Open board")
check(A.patch(B + f"/api/lists/{L2}", json={"org_visibility": "org"}).ok, "setup: the whole organisation may read")
check(core_row(L2, uid["dora"]) is None, "dora reads it without a row")
r = S["dora"].post(B + f"/api/lists/{L2}/join")
check(r.ok and r.json().get("role") == "edit", "dora joins " + r.text[:160])
check(core_row(L2, uid["dora"]) == ("view", "edit", 1, None), f"joining writes the core's row of the own share {core_row(L2, uid['dora'])}")
sh = A.get(B + f"/api/lists/{L2}/shares")
check(sh.ok and any(x.get("user_id") == uid["dora"] and x.get("list_role") == "edit" for x in sh.json()["shares"]),
      "GET .../shares shows the joined member " + sh.text[:300])
r = A.delete(B + f"/api/lists/{L2}/members/{uid['dora']}")
check(r.ok and r.json().get("revoked_id") and core_row(L2, uid["dora"]) is None, "removed: her row goes into the restorable ones " + r.text[:160])

# ---------------------------------------------------------------- (2) the old owner of a transfer
L3 = new_list(A, "Hand over")
check(A.put(B + f"/api/lists/{L3}/members", json={"user_id": uid["emil"], "role": "edit"}).ok, "setup: emil a member")
r = A.post(B + f"/api/lists/{L3}/owner", json={"user_id": uid["emil"]})
check(r.ok, "alice hands the project to emil " + r.text[:160])
check(core_row(L3, ALICE) == ("edit", "admin", 1, None), f"the old owner stays as list admin with the core's row {core_row(L3, ALICE)}")
sh = S["emil"].get(B + f"/api/lists/{L3}/shares")
check(sh.ok and any(x.get("user_id") == ALICE and x.get("list_role") == "admin" for x in sh.json()["shares"]),
      "the new owner's GET .../shares shows alice as list admin " + sh.text[:300])

# ---------------------------------------------------------------- (3) an expiry without the watchdog's round
L4 = new_list(A, "Short job")
r = A.put(B + f"/api/lists/{L4}/members", json={"user_id": uid["bob"], "role": "edit", "expires_at": "2099-12-31"})
check(r.ok and sees(S["bob"], L4), "setup: bob until 2099 " + r.text[:160])
expire(L4, uid["bob"])
check(S["bob"].get(B + f"/api/lists/{L4}/overview").status_code == 404 and S["bob"].get(B + f"/api/lists/{L4}/shares").status_code == 404,
      "the share ran out: 404 at once, no watchdog round")
check(S["bob"].post(B + "/api/tasks", json={"title": "late", "list_id": L4}).status_code == 404, "and no writing either (404)")
check(A.get(B + f"/api/lists/{L4}/overview").ok, "the owner keeps it")
# a role through a group stays as that role
G = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [uid["carl"]]}).json()["id"]
L5 = new_list(A, "Crew job")
check(A.put(B + f"/api/lists/{L5}/groups/{G}", json={"role": "view"}).ok, "setup: the group may read")
r = A.put(B + f"/api/lists/{L5}/members", json={"user_id": uid["carl"], "role": "edit", "expires_at": "2099-12-31"})
check(r.ok and S["carl"].post(B + "/api/tasks", json={"title": "mine", "list_id": L5}).ok, "setup: carl may write (own share) " + r.text[:160])
expire(L5, uid["carl"])
check(sees(S["carl"], L5) and S["carl"].post(B + "/api/tasks", json={"title": "late", "list_id": L5}).status_code == 403,
      "his own share ran out: the group's view stays, writing 403")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
PL = new_list(Fr, "Own studio", org=None)
r = Fr.put(B + f"/api/lists/{PL}/members", json={"email": "fiona@example.com", "role": "edit", "expires_at": "2099-12-31"})
check(r.ok and sees(Fi, PL) and core_row(PL, FIO), "frida shares her private project with fiona until 2099 " + r.text[:160])
expire(PL, FIO)
check(Fi.get(B + f"/api/lists/{PL}/overview").status_code == 404, "the share ran out: fiona gets 404 at once")
check(sees(Fr, PL), "frida keeps her project")

sys.exit(done("p2654_b_list_mirror"))
