#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.565.0 part C (#4719): the team chat's channels and group conversations on the shared core (stage 5). Own container
(mode workspaces). Invented names only.
tenant-matrix: team
freelancer-matrix: team
 - adding / removing a member works through the core: the share of the room's reference node (fs_shares) and the fallback
   row (tchat_members) come and go together; a removed member's share lands in obj_revoked; leaving oneself too
 - the room's node never shows in the file store (the organisation's top, "shared with me")
 - migration: a member row written the old way (tchat_members only) gets its share at the next start and the person reads
   the channel; a row an older version removed loses its share at the next start (the fallback opens nothing taken away)
 - an open channel: a member reads it without joining, a guest / an accounting member does not (and a group gives them nothing)
 - leaving the organisation ends the channel access (share and row; obj_revoked), joining again brings no old channel back
 - a group shared with a channel: its full members read it, a guest of the group does not; unsharing ends it; a group
   conversation takes no group; only a member who manages the channel shares it
 - the boundary: a person and an agent of another organisation reach no channel of this one (404)
 - an agent reads only the channels it was added to (API v1), not an open one it was not added to
 - editing a message with an old version -> 409 with the current text (the chat part of #4701, package 2.564 D; skipped with
   a note while that part is not in this branch)
 - a person without an organisation: a private channel with a coworker on the core (add, read, remove)
usage: p2565_c_kern_teamchat_test.py <datadir>"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, sess, until  # noqa: E402,F401

FEAT = "cal,comments,collab,files"
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2565C")


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


def no(r, what):
    check(r.status_code in (403, 404), f"{what}: refused ({r.status_code} {r.text[:120]})")


def share(rid, who, key="user_id"):
    """The core's share of room rid's reference node for who (None: none)."""
    x = sql(f"SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='tchat_room' "
            f"AND n.ref_id=? AND s.{key}=?", (rid, who))
    return x[0][0] if x else None


def row(rid, who):
    return bool(sql("SELECT 1 FROM tchat_members WHERE room_id=? AND user_id=?", (rid, who)))


def revoked(rid, who, reason=None):
    q = "SELECT reason FROM obj_revoked WHERE src='fs_shares' AND kind='tchat_room' AND ref_id=? AND user_id=?"
    return [x[0] for x in sql(q, (rid, who))] if reason is None else reason in [x[0] for x in sql(q, (rid, who))]


def reads(s, rid, headers=None):
    if headers:
        return requests.get(V + f"/team/rooms/{rid}/messages", headers=headers).ok
    return s.get(B + f"/api/team/rooms/{rid}/messages").ok


def channel(s, name, oid, members=(), open_=False):
    r = s.post(B + "/api/team/channels", json={"name": name, "org_id": oid, "members": list(members), **({"open": True} if open_ else {})})
    check(r.status_code in (200, 201), f"setup: channel {name} {r.text[:160]}")
    return r.json().get("id")


def token(s, name):
    """A personal API token of session s (scopes read + comments) -> its headers."""
    r = s.post(B + "/api/me/tokens", json={"name": name, "scopes": ["read", "comments"], "expires_days": None})
    check(r.ok and r.json().get("token"), f"setup: a personal token {name} {r.text[:120]}")
    return {"Authorization": "Bearer " + (r.json().get("token") or "x")} if r.ok else {}


def restart():
    """The next start of the server (core/db.py init_db runs collab/tcxcore.py tcx_core_sync)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    check(until(lambda: _health(), timeout=90), "the server is up again after the restart")


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina", "rita", "olga", "mia"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Gi, Ri, Ol, Mi = S["bob"], S["gina"], S["rita"], S["olga"], S["mia"]
BOB, GINA, RITA, OLGA, MIA = uid["bob"], uid["gina"], uid["rita"], uid["olga"], uid["mia"]


def org(name):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (oid, ALICE), write=True)
    return oid


def member(oid, who, role="member"):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    r = A.put(B + f"/api/orgs/{oid}/members", json={"email": mail, "role": role})
    check(r.ok and sql("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, who)) == [(role,)],
          f"setup: {who} is {role} of {oid} {r.text[:160]}")


def agent(name, oid):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    check(A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": oid}).ok, f"setup: agent {name} in organisation {oid}")
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


K = org("Kappa")
OTHER = org("Omega")
member(K, BOB)
member(K, MIA)
member(K, GINA, "guest")
member(K, RITA, "accounting")
member(OTHER, OLGA)
AG, AGH = agent("kai", K)
AGO, AGOH = agent("oskar", OTHER)
A.patch(B + "/api/settings", json={"workspace": f"org:{K}"})

# ================================================================== add / remove through the core
C1 = channel(A, "Closed one", K, [BOB])
check(share(C1, BOB) == "edit" and row(C1, BOB), "add: bob's share on the room's node and his fallback row")
check(share(C1, ALICE) == "edit" and row(C1, ALICE), "add: the maker is a member through the core too")
check(reads(Bo, C1), "add: bob reads the closed channel")
no(Mi.get(B + f"/api/team/rooms/{C1}/messages"), "add: mia (not invited) reads the closed channel")
check(A.post(B + f"/api/team/rooms/{C1}/members", json={"user_id": MIA}).ok, "add: alice adds mia")
check(share(C1, MIA) == "edit" and row(C1, MIA) and reads(Mi, C1), "add: mia's share + row, she reads it")
check(A.delete(B + f"/api/team/rooms/{C1}/members/{MIA}").ok, "remove: alice removes mia")
check(share(C1, MIA) is None and not row(C1, MIA), "remove: mia's share and row are gone")
check(revoked(C1, MIA, "unshare"), "remove: mia's share is in obj_revoked (restorable)")
no(Mi.get(B + f"/api/team/rooms/{C1}/messages"), "remove: mia reads the channel no more")
check(C1 not in {x.get("id") for x in Mi.get(B + "/api/team/channels").json().get("channels") or []}, "remove: mia lists it no more")
check(A.post(B + f"/api/team/rooms/{C1}/members", json={"user_id": MIA}).ok
      and Mi.delete(B + f"/api/team/rooms/{C1}/members/{MIA}").ok, "leave: mia joins again and leaves herself")
check(share(C1, MIA) is None and not row(C1, MIA) and not reads(Mi, C1), "leave: share and row gone, no reading")

# the room's node is no item of the file store
items = (A.get(B + f"/api/files?space=org:{K}").json().get("items") or []) + (Bo.get(B + "/api/files?space=shared").json().get("items") or [])
check(not [x for x in items if x.get("ref_kind") == "tchat_room"], "files: no node of a room in the file store")
nid = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id=?", (C1,))[0][0]
no(Bo.get(B + f"/api/files?parent={nid}"), "files: the room's node by its id")

# ================================================================== migration: rows of the old way
C2 = channel(A, "Old way", K)
sql("INSERT INTO tchat_members(room_id,user_id,added_by,created_at) VALUES(?,?,?,'2026-11-01T10:00:00Z')", (C2, BOB, ALICE), write=True)
check(share(C2, BOB) is None and reads(Bo, C2), "migration: a row of the old way only (fallback) - bob reads before the start")
sql("DELETE FROM tchat_members WHERE room_id=? AND user_id=?", (C1, BOB), write=True)  # an older version removed bob from C1
check(share(C1, BOB) == "edit", "migration: bob's share in C1 still there before the start")
restart()
A, Bo = sess("alice"), sess("bob")
check(share(C2, BOB) == "edit", "migration: the next start copies bob's row of C2 into a share")
check(reads(Bo, C2), "migration: the migrated member reads the channel")
check(share(C1, BOB) is None and revoked(C1, BOB, "unshare"), "migration: the share whose row an older version removed is taken (obj_revoked)")
no(Bo.get(B + f"/api/team/rooms/{C1}/messages"), "migration: bob reads C1 no more")
check(A.post(B + f"/api/team/rooms/{C1}/members", json={"user_id": BOB}).ok and reads(Bo, C1), "migration: bob added again reads C1")

# ================================================================== open channel: the role filter
OC = channel(A, "Open one", K, open_=True)
check(reads(Bo, OC), "open: a member of the organisation reads the open channel without joining")
no(Gi.get(B + f"/api/team/rooms/{OC}/messages"), "open: a guest does not read the open channel")
no(Ri.get(B + f"/api/team/rooms/{OC}/messages"), "open: an accounting member does not read the open channel")

# ================================================================== groups as subject
r = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [MIA, GINA, OLGA]})
check(r.ok, "group: the admin makes a group " + r.text[:160])
G = r.json().get("id")
C3 = channel(A, "Crew room", K)
no(Mi.get(B + f"/api/team/rooms/{C3}/messages"), "group: mia does not read the channel before")
no(Bo.post(B + f"/api/team/rooms/{C3}/members", json={"group_id": G}), "group: a non-member cannot share the channel with a group")
check(A.post(B + f"/api/team/rooms/{C3}/members", json={"group_id": G}).ok, "group: alice shares the channel with the group")
check(share(C3, G, "group_id") == "edit" and not row(C3, MIA), "group: one share with the group, no personal row")
check(reads(Mi, C3), "group: mia (full member, in the group) reads the channel")
check(C3 in {x.get("id") for x in Mi.get(B + "/api/team/channels").json().get("channels") or []}, "group: mia lists the channel")
no(Gi.get(B + f"/api/team/rooms/{C3}/messages"), "group: a guest in the group does not read it (personal invitation needed)")
no(Ol.get(B + f"/api/team/rooms/{C3}/messages"), "group: a group member of another organisation does not read it")
OLH = token(Ol, "olga")
no(Ol.delete(B + f"/api/team/rooms/{C3}/groups/{G}"), "boundary: a person of another organisation unshares the group")
no(requests.delete(V + f"/team/rooms/{C3}/groups/{G}", headers=OLH), "boundary: ... through API v1")
no(requests.delete(V + f"/team/rooms/{C3}/groups/{G}", headers=AGOH), "boundary: an agent of another organisation (API v1)")
no(requests.delete(V + f"/team/rooms/{C3}/groups/{G}", headers=AGH), "group: an agent of the organisation does not manage groups")
check(share(C3, G, "group_id") == "edit", "boundary: the group's share stays")
j = A.get(B + "/api/team/channels").json()
mine = {x["id"]: x for x in j.get("channels") or []}
check(mine.get(C3, {}).get("groups") == [G], "group: the manager sees the group of the channel")
gr = A.post(B + "/api/team/groups", json={"members": [BOB, MIA]})
if gr.ok:
    r = A.post(B + f"/api/team/rooms/{gr.json()['id']}/members", json={"group_id": G})
    check(r.status_code == 400, f"group: a group conversation takes no group ({r.status_code})")
check(A.delete(B + f"/api/team/rooms/{C3}/groups/{G}").ok, "group: alice unshares the group")
check(share(C3, G, "group_id") is None, "group: the group's share is gone")
no(Mi.get(B + f"/api/team/rooms/{C3}/messages"), "group: mia reads the channel no more")
no(A.delete(B + f"/api/team/rooms/{C3}/groups/{G}"), "group: unsharing twice")

# ================================================================== the boundary + agents
no(Ol.get(B + f"/api/team/rooms/{C1}/messages"), "boundary: a person of another organisation")
no(requests.get(V + f"/team/rooms/{C1}/messages", headers=AGOH), "boundary: an agent of another organisation")
no(requests.get(V + f"/team/rooms/{C1}/messages", headers=AGH), "agent: not added - no reading")
no(requests.get(V + f"/team/rooms/{OC}/messages", headers=AGH), "agent: an open channel it was not added to")
check(A.post(B + f"/api/team/rooms/{C1}/members", json={"user_id": AG}).ok, "agent: alice adds the organisation's agent to C1")
check(share(C1, AG, "agent_id") == "edit" and row(C1, AG), "agent: its share (agent) and row")
check(reads(None, C1, AGH), "agent: reads the channel it was added to (API v1)")
rooms = {x.get("id") for x in (requests.get(V + "/team/rooms", headers=AGH).json().get("data") or [])}
check(C1 in rooms and OC not in rooms and C2 not in rooms, f"agent: lists only its channel ({sorted(x for x in rooms if x)})")
r = A.post(B + f"/api/team/rooms/{C1}/members", json={"user_id": AGO})
check(r.status_code in (400, 403, 404) and share(C1, AGO, "agent_id") is None, f"agent: an agent of another organisation cannot be added ({r.status_code})")

# ================================================================== leaving the organisation
check(row(C1, BOB) and share(C1, BOB), "leave org: bob is in C1 before")
check(A.delete(B + f"/api/orgs/{K}/members/{BOB}").ok, "leave org: bob leaves Kappa")
check(share(C1, BOB) is None and not row(C1, BOB) and share(C2, BOB) is None, "leave org: his shares and rows of the channels are gone")
check(revoked(C1, BOB, "leave"), "leave org: his share is in obj_revoked (reason leave)")
member(K, BOB)
no(Bo.get(B + f"/api/team/rooms/{C1}/messages"), "leave org: back the same day - no old closed channel")
check(reads(Bo, OC), "leave org: back as a member he reads the open channel again (the organisation's rule)")

# ================================================================== the chat part of #4701 (package 2.564 D)
check(A.post(B + f"/api/team/rooms/{C1}/messages", json={"body": "first text"}).status_code in (200, 201), "edit: a message")
mid = sql("SELECT id FROM tchat_msgs WHERE room_id=? ORDER BY id DESC LIMIT 1", (C1,))[0][0]
check(A.patch(B + f"/api/team/messages/{mid}", json={"body": "second text"}).ok, "edit: without a version (old client) it saves")
with open(os.path.join(os.path.dirname(N), "kalmido", "collab", "teamchat.py"), encoding="utf-8") as f:
    HAS4701 = "ccf_check(b, m[" in f.read()  # the chat part of #4701 (package 2.564 D) is in this branch
if HAS4701:
    r = A.patch(B + f"/api/team/messages/{mid}", json={"body": "third text", "expect_updated_at": "2000-01-01T00:00:00.000Z"})
    cur = (r.json().get("message") or {}) if r.status_code == 409 else {}
    check(r.status_code == 409 and cur.get("body") == "second text", f"edit: an old version -> 409 with the current text ({r.status_code} {str(cur)[:120]})")
    check(sql("SELECT body FROM tchat_msgs WHERE id=?", (mid,))[0][0] == "second text", "edit: nothing written")
else:
    print("SKIP edit with an old version: the chat part of #4701 (package 2.564 D) is not in this branch yet")

# ================================================================== a person without an organisation
FR, Fr = freelancer(B, A, "frida", features=FEAT)
FE, Fe = freelancer(B, A, "fred", features=FEAT)
# they work together through a group of the instance (a group row, like p2281_a: the admin of the mode workspaces sees no freelancer)
sql("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES('Pair','','2026-10-20T08:00:00',?)", (ALICE,), write=True)
PG = sql("SELECT id FROM groups WHERE name='Pair'")[0][0]
for x in (FR, FE):
    sql("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,'2026-10-20T08:00:00')", (PG, x), write=True)
r = Fr.post(B + "/api/team/channels", json={"name": "Own room", "org_id": None, "members": [FE]})
check(r.status_code in (200, 201), "freelancer: a private channel with a coworker " + r.text[:160])
PC = r.json().get("id")
check(share(PC, FE) == "edit" and row(PC, FE) and reads(Fe, PC), "freelancer: the coworker is a member through the core and reads it")
check(sql("SELECT org_id FROM fs_nodes WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id=?", (PC,)) == [(None,)],
      "freelancer: the room's node is in her own space")
items = Fr.get(B + "/api/files?space=private").json().get("items") or []
check(not [x for x in items if x.get("ref_kind") == "tchat_room"], "freelancer: the node is not in her own file store")
check(Fr.delete(B + f"/api/team/rooms/{PC}/members/{FE}").ok, "freelancer: she removes him")
check(share(PC, FE) is None and not row(PC, FE), "freelancer: share and row gone")
no(Fe.get(B + f"/api/team/rooms/{PC}/messages"), "freelancer: he reads it no more")
check(Fr.post(B + f"/api/team/rooms/{PC}/members", json={"group_id": PG}).ok and share(PC, PG, "group_id") == "edit",
      "freelancer: she shares her private channel with the group")
check(reads(Fe, PC), "freelancer: he reads it through the group")
FRH = token(Fr, "frida")
r = requests.delete(V + f"/team/rooms/{PC}/groups/{PG}", headers=FRH)
check(r.status_code == 204 and share(PC, PG, "group_id") is None, f"freelancer: she unshares the group through API v1 ({r.status_code})")
no(Fe.get(B + f"/api/team/rooms/{PC}/messages"), "freelancer: he reads it no more after the group")

sys.exit(kt.done("p2565_c_kern_teamchat"))
