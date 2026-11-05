#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.558.0 (#4709): the shared core, stage 1 -- the register and THE role function (kalmido/core/objects.py) through the
generic routes (core/objweb.py) with the test kind 'objprobe' (KALMIDO_TEST_OBJ=1, tests/obj_probe.py). Invented names only.
 - the role matrix of an organisation's object: admin manage, its owner (member) manage, member edit, read-only view (403 on
   change), guest / accounting / another organisation / a person without one 404; the list (obj_visible_sql) says the same
 - a private object: only its owner; shares (person, group, agent) give view / edit, never manage; an expired share nothing;
   only people / agents of the same workspace (409); taken back = gone, restorable (obj_revoked)
 - a folder share of the file store opens an object filed there (one register: fsref)
 - agents: only an explicit share, never another workspace, hidden objects and the data lock give nothing
 - a listing reads the share chain once (review F3): 12 more objects cost a member or a folder share no statement more
 - called outside a request (an area's own code): an agent creates nothing (F4), obj_share uses its uid, not the session (F5)
 - the trash: only who manages it sees it (?trash=1), restore, a member gets 404 meanwhile
 - an account deleted: its organisation objects go to the heir (review F1), its private ones go with it
 - obj_revoke_person: leaving takes the shares on the organisation's nodes and the team chat rooms along (coming back as a
   guest revives nothing), the heir owns the leaver's objects; a demotion to guest leaves the open channels joined
tenant-matrix: obj (another organisation and its agent: 404 on every route of an object, its shares, history, undo, trash)
freelancer-matrix: obj (a person without an organisation: her private object, shared with her own agent)
usage: obj_core_test.py <datadir>"""
import os
import re
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, docker_logs_on_first_fail, done, sess  # noqa: E402
from obj_probe import K, agent, ids, in_app, new, role, start  # noqa: E402

start("OBJCORE")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, rk in (("bob", "member"), ("carl", "member"), ("rita", "readonly"), ("gina", "guest"), ("acco", "accounting")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
ORG2 = r.json().get("id")
S = {u: sess(u) for u in ("bob", "carl", "rita", "gina", "acco", "olga")}
Bo, Ca, Ri, Gi, Ac, Ol = (S[u] for u in ("bob", "carl", "rita", "gina", "acco", "olga"))
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A)

# ---------------------------------------------------------------- an organisation's object: the role matrix
O1 = new(Bo, "Weekly plan", ORG)["id"]
got = {u: role(s, O1) for u, s in (("alice", A), ("bob", Bo), ("carl", Ca), ("rita", Ri), ("gina", Gi), ("acco", Ac), ("olga", Ol), ("frida", Fr))}
check(got == {"alice": "manage", "bob": "manage", "carl": "edit", "rita": "view", "gina": 404, "acco": 404, "olga": 404, "frida": 404},
      f"roles on the organisation's object {got}")
check(O1 in ids(Ca) and O1 in ids(Ri) and O1 not in ids(Gi) and O1 not in ids(Ol) and O1 not in ids(Fr), "the list says the same (obj_visible_sql)")
check(Ri.patch(B + f"/api/obj/{K}/{O1}", json={"note": "x"}).status_code == 403, "read-only: no change (403)")
check(Ca.patch(B + f"/api/obj/{K}/{O1}", json={"note": "carl was here"}).ok, "member: changes it")
check(Ca.post(B + f"/api/obj/{K}/{O1}/trash").status_code == 403, "member (edit): no trash (manage)")
check(Ca.get(B + f"/api/obj/{K}/{O1}/shares").status_code == 403, "member (edit): shares only for who manages it")
check(Gi.post(B + f"/api/obj/{K}", json={"title": "Guest's", "org_id": ORG}).status_code == 403, "a guest makes nothing in the organisation")
check(Ol.post(B + f"/api/obj/{K}", json={"title": "Foreign", "org_id": ORG}).status_code == 404, "another organisation's admin makes nothing in it")

# ---------------------------------------------------------------- a private object and its shares
P1 = new(Ca, "Carl's notes")["id"]
check(role(Ca, P1) == "manage" and role(A, P1) == 404 and role(Bo, P1) == 404, "a private object: only its owner (not the instance admin)")
r = Ca.post(B + f"/api/obj/{K}/{P1}/shares", json={"user_id": uid["bob"], "role": "view"})
check(r.status_code == 201 and role(Bo, P1) == "view" and P1 in ids(Bo), f"shared with bob: view, listed ({r.status_code} {r.text[:160]})")
SB = r.json().get("id")
check(Bo.patch(B + f"/api/obj/{K}/{P1}", json={"note": "no"}).status_code == 403, "view: no change")
check(Ca.post(B + f"/api/obj/{K}/{P1}/shares", json={"user_id": uid["bob"], "role": "edit"}).status_code == 201 and role(Bo, P1) == "edit",
      "the same target again: edit")
check(Bo.post(B + f"/api/obj/{K}/{P1}/shares", json={"user_id": uid["rita"], "role": "view"}).status_code == 403, "edit by share: no sharing (never manage)")
r = Ca.get(B + f"/api/obj/{K}/{P1}/shares")
check(r.ok and [x["user_id"] for x in r.json()["shares"]] == [uid["bob"]], f"the shares of the object {r.text[:200]}")
check(dbx("SELECT by_role FROM fs_shares WHERE id=?", (SB,))[0][0] == "owner", "the share notes the role of who made it (by_role)")
r = Ca.delete(B + f"/api/obj/{K}/{P1}/shares/{SB}")
RV = r.json().get("revoked_id") if r.ok else 0
check(r.ok and role(Bo, P1) == 404 and [x["id"] for x in r.json()["revoked"]] == [RV] if r.ok else False, f"taken back: bob nothing, restorable ({r.status_code})")
check(Bo.post(B + f"/api/obj/{K}/{P1}/shares/{RV}/restore").status_code == 404, "bob cannot restore it")
r = Ca.post(B + f"/api/obj/{K}/{P1}/shares/{RV}/restore")
check(r.ok and role(Bo, P1) == "edit", f"restored: bob edit again ({r.status_code} {r.text[:160]})")
r = Ca.post(B + f"/api/obj/{K}/{P1}/shares", json={"user_id": uid["rita"], "role": "view", "expires_at": "2020-01-01"})
check(r.status_code == 201 and role(Ri, P1) == 404 and P1 not in ids(Ri), "an expired share gives nothing (role and list)")
GID = A.post(B + "/api/admin/groups", json={"name": "Planners", "members": [uid["rita"]]}).json().get("id")
r = Ca.post(B + f"/api/obj/{K}/{P1}/shares", json={"group_id": GID, "role": "view"})
check(r.status_code == 201 and role(Ri, P1) == "view" and P1 in ids(Ri), f"a group share: rita view ({r.status_code} {r.text[:120]})")
O2 = new(A, "Board", ORG)["id"]
check(A.post(B + f"/api/obj/{K}/{O2}/shares", json={"user_id": uid["olga"], "role": "view"}).status_code == 409, "another organisation's person: 409")
check(A.post(B + f"/api/obj/{K}/{O2}/shares", json={"user_id": uid["gina"], "role": "view"}).status_code == 201 and role(Gi, O2) == "view"
      and O2 in ids(Gi), "a guest with a personal share: view, listed")

# ---------------------------------------------------------------- one register: a folder share of the file store opens it
fol = A.post(B + "/api/files/folders", json={"name": "Plans", "space": f"org:{ORG}"}).json()["id"]
O3 = new(A, "Filed plan", ORG)["id"]
r = A.post(B + "/api/files/refs", json={"ref_kind": K, "ref_id": O3, "parent_id": fol})
check(r.ok, f"filed into a folder ({r.status_code} {r.text[:160]})")
check(role(Ac, O3) == 404, "accounting: nothing before the folder share")
check(A.post(B + f"/api/files/nodes/{fol}/shares", json={"user_id": uid["acco"], "role": "edit"}).status_code == 201 and role(Ac, O3) == "edit"
      and O3 in ids(Ac), "a folder share: accounting edit, listed")

# ---------------------------------------------------------------- agents: only an explicit share, the same workspace
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG = agent(A, "planbot", ORG)
check(AG.role(O1) == 404 and AG.get().json()["data"] == [], "an organisation's agent: nothing without a share (org access gives it nothing)")
check(A.post(B + f"/api/obj/{K}/{O1}/shares", json={"agent_id": AG.id, "role": "view"}).status_code == 201 and AG.role(O1) == "view"
      and [x["id"] for x in AG.get().json()["data"]] == [O1], "shared with the agent: view, listed")
H1 = new(A, "hide this plan", ORG)["id"]
A.post(B + f"/api/obj/{K}/{H1}/shares", json={"agent_id": AG.id, "role": "view"})
A.post(B + f"/api/obj/{K}/{H1}/shares", json={"user_id": uid["gina"], "role": "view"})
check(AG.role(H1) == 404 and role(Gi, H1) == 404 and role(Ca, H1) == "edit", "hidden: no share opens it (agent, guest), the member's own role stays")
FA = agent(Fr, "fridabot")
check(Fr.post(B + f"/api/obj/{K}/{O1}/shares", json={"agent_id": FA.id}).status_code == 404 and FA.role(O1) == 404, "a private agent: never the organisation's object")
check(A.post(B + f"/api/obj/{K}/{O1}/shares", json={"agent_id": FA.id, "role": "view"}).status_code == 409, "another workspace's agent is no share target")
r = A.patch(B + f"/api/agents/{AG.id}/data-lock", json={"areas": {"contracts": True}})
check(r.ok and AG.role(O1) == 404 and AG.get().json()["data"] == [], f"the data lock of the kind's area: nothing ({r.status_code})")
A.patch(B + f"/api/agents/{AG.id}/data-lock", json={"areas": {"contracts": False}})
check(AG.role(O1) == "view", "lock off: view again")

# ---------------------------------------------------------------- the trash
check(Bo.post(B + f"/api/obj/{K}/{O1}/trash").ok, "the owner puts it into the trash")
check(role(Ca, O1) == 404 and O1 not in ids(Ca) and AG.role(O1) == 404, "in the trash: member and agent 404")
check(O1 in ids(A, trash=True) and O1 in ids(Bo, trash=True) and O1 not in ids(Ca, trash=True), "the trash list: only who manages it")
check(Ca.post(B + f"/api/obj/{K}/{O1}/restore").status_code == 404, "a member cannot restore it")
check(Bo.post(B + f"/api/obj/{K}/{O1}/restore").ok and role(Ca, O1) == "edit", "restored: the member edits again")

# ---------------------------------------------------------------- review F3: a listing reads the share chain once, not per row
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def nstmt(s):
    r = s.get(B + f"/api/obj/{K}")
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return (int(m.group(1)) if m else -1), len(r.json().get("items") or []) if r.ok else 0


n1, c1 = nstmt(Ca)
a1, d1 = nstmt(Ac)
for i in range(12):
    oid = new(A, f"Plan {i}", ORG)["id"]
    A.post(B + "/api/files/refs", json={"ref_kind": K, "ref_id": oid, "parent_id": fol})
n2, c2 = nstmt(Ca)
a2, d2 = nstmt(Ac)
print(f"PERF obj list: member {n1} -> {n2} statements ({c1} -> {c2} rows), folder share {a1} -> {a2} ({d1} -> {d2} rows)")
check(n1 > 0 and c2 == c1 + 12 and n2 <= n1 + 2, f"a member's list: 12 more rows, the same statements ({n1} -> {n2})")
check(a1 > 0 and d2 == d1 + 12 and a2 <= a1 + 2, f"by a folder share: 12 more rows, the same statements ({a1} -> {a2})")

# ---------------------------------------------------------------- review F4 / F5: the core's functions called from an area's own code
out = in_app(f"""from kalmido.core.writes import obj_create
try:
    obj_create(c, {AG.id}, "{K}", {{"title": "Bot's plan"}}, org_id={ORG})
    print("MADE")
except Denied as e:
    print("DENIED", e.code)""")
check("DENIED 403" in out and dbx("SELECT COUNT(*) FROM obj_probe WHERE title=?", ("Bot's plan",))[0][0] == 0,
      f"F4: an agent makes no object (creating stays with people): {out[-300:]}")
out = in_app(f"""from kalmido.core.objects import obj_share
for t in ({uid['carl']}, {uid['olga']}):
    try:
        print("SHARED", t, obj_share(c, {ALICE}, "{K}", {O3}, "user_id", t, "view"))
    except Denied as e:
        print("DENIED", t, e.code)
c.rollback()""")
check(f"SHARED {uid['carl']}" in out and f"DENIED {uid['olga']} 409" in out,
      f"F5: obj_share outside a request takes its uid (the same workspace still only): {out[-300:]}")

# ---------------------------------------------------------------- another organisation / person: 404 on every route (tenant-matrix: obj)
OAG = agent(Ol, "otherbot", ORG2)
for s, who in ((Ol, "olga"), (Fr, "frida")):
    for m, url, body in (("get", f"/api/obj/{K}/{O1}", None), ("patch", f"/api/obj/{K}/{O1}", {"note": "x"}),
                         ("post", f"/api/obj/{K}/{O1}/trash", None), ("post", f"/api/obj/{K}/{O1}/restore", None),
                         ("delete", f"/api/obj/{K}/{O1}", None), ("get", f"/api/obj/{K}/{O1}/history", None),
                         ("post", f"/api/obj/{K}/{O1}/undo", {"sess": "ab" * 8, "op": "undo"}),
                         ("get", f"/api/obj/{K}/{O1}/shares", None), ("post", f"/api/obj/{K}/{O1}/shares", {"user_id": uid["olga"]}),
                         ("delete", f"/api/obj/{K}/{O1}/shares/{SB}", None), ("post", f"/api/obj/{K}/{O1}/shares/{RV}/restore", None)):
        r = getattr(s, m)(B + url, json=body)
        check(r.status_code == 404, f"{who}: {m.upper()} {url} -> 404 ({r.status_code})")
check(requests.get(B + f"/api/v1/agent/objects/{K}/{O1}", headers=OAG.h).status_code == 404
      and requests.patch(B + f"/api/v1/agent/objects/{K}/{O1}", headers=OAG.h, json={"note": "x", "expect_updated_at": "x"}).status_code == 404
      and requests.get(B + f"/api/v1/agent/objects/{K}", headers=OAG.h).json()["data"] == [], "another organisation's agent: 404, its list empty")
check(A.get(B + f"/api/obj/nosuchkind/{O1}").status_code == 404, "an unknown kind: 404")

# ---------------------------------------------------------------- obj_revoke_person: leaving, coming back, the heir, a demotion
r = A.post(B + "/api/team/channels", json={"name": "General", "org_id": ORG, "open": True})
CH = r.json().get("id") or (r.json().get("room") or {}).get("id")
r = A.post(B + "/api/team/channels", json={"name": "Inner", "org_id": ORG})
CL = r.json().get("id") or (r.json().get("room") or {}).get("id")
check(CH and CL and Ca.post(B + f"/api/team/rooms/{CH}/members", json={"user_id": uid["carl"]}).ok, f"setup: carl joins the open channel {CH}")
A.post(B + f"/api/team/rooms/{CL}/members", json={"user_id": uid["gina"]})
check(dbx("SELECT COUNT(*) FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE s.user_id=? AND n.org_id=?", (uid["gina"], ORG))[0][0] >= 1
      and dbx("SELECT COUNT(*) FROM tchat_members WHERE user_id=? AND room_id=?", (uid["gina"], CL))[0][0] == 1, "setup: gina has shares and a closed channel")
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['gina']}").ok, "gina leaves the organisation")
check(dbx("SELECT COUNT(*) FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE s.user_id=? AND n.org_id=?", (uid["gina"], ORG))[0][0] == 0
      and dbx("SELECT COUNT(*) FROM tchat_members WHERE user_id=? AND room_id=?", (uid["gina"], CL))[0][0] == 0, "her shares and channel rows are gone")
check(dbx("SELECT COUNT(*) FROM obj_revoked WHERE user_id=? AND reason='leave'", (uid["gina"],))[0][0] >= 2, "... into obj_revoked (restorable)")
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "gina@example.com", "role": "guest"})
back = dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["gina"]))
check(r.ok and len(back) == 1 and back[0][0] == "guest", f"gina comes back as a guest ({r.status_code} {r.text[:160]})")
Gi = sess("gina")
check(role(Gi, O2) == 404 and O2 not in ids(Gi), "coming back revives no old share")
r = A.get(B + f"/api/obj/{K}/{O2}/shares")
GR = [x["id"] for x in (r.json().get("revoked") or []) if x.get("user_id") == uid["gina"] and x.get("reason") == "leave"] if r.ok else []
check(len(GR) == 1, f"review F2: the share taken on leaving shows on the object, restorable ({r.status_code} {r.text[:200]})")
r = A.post(B + f"/api/obj/{K}/{O2}/shares/{GR[0] if GR else 0}/restore")
check(r.ok and role(Gi, O2) == "view", f"... and the admin gives it back ({r.status_code} {r.text[:160]})")
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['bob']}").ok, "bob (the owner of O1) leaves")
check(dbx("SELECT owner_id FROM obj_probe WHERE id=?", (O1,))[0][0] == ALICE and role(A, O1) == "manage" and role(Bo, O1) == 404,
      "his organisation object goes to the heir (the admin who removed him)")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carl"], "role": "guest"}).ok, "carl is demoted to guest")
check(dbx("SELECT COUNT(*) FROM tchat_members WHERE user_id=? AND room_id=?", (uid["carl"], CH))[0][0] == 0
      and role(Ca, O3) == 404, "a guest: out of the open channel joined, the object no longer by the organisation's role")

# ---------------------------------------------------------------- review F1: an account deleted keeps the organisation's objects
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "dave", "display_name": "Dave",
                                   "password": "password123", "email": "dave@example.com"})
uid["dave"] = r.json().get("id")
Da = sess("dave")
D1 = new(Da, "Dave's team plan", ORG)["id"]
DP = new(Da, "Dave's own notes")["id"]
r = A.delete(B + f"/api/users/{uid['dave']}")
check(r.ok, f"the admin deletes dave's account ({r.status_code} {r.text[:160]})")
check((dbx("SELECT owner_id FROM obj_probe WHERE id=?", (D1,)) or [[None]])[0][0] == ALICE and role(A, D1) == "manage",
      "his organisation object lives on with the heir")
check(dbx("SELECT COUNT(*) FROM obj_probe WHERE id=?", (DP,))[0][0] == 0, "his private object goes with the account")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: obj)
FP = new(Fr, "Frida's plan", size=3)
check(FP["org_id"] is None and role(Fr, FP["id"]) == "manage" and ids(Fr) == [FP["id"]], "her private object, only hers")
r = Fr.post(B + f"/api/obj/{K}/{FP['id']}/shares", json={"agent_id": FA.id, "role": "edit"})
check(r.status_code == 201 and FA.role(FP["id"]) == "edit" and [x["id"] for x in FA.get().json()["data"]] == [FP["id"]], f"shared with her own agent ({r.status_code})")
check(Fr.get(B + f"/api/obj/{K}/{FP['id']}/shares").ok and Fr.get(B + f"/api/obj/{K}/{FP['id']}/history").ok, "her shares and history")
r = Fr.delete(B + f"/api/obj/{K}/{FP['id']}/shares/{r.json().get('id')}")
check(r.ok and FA.role(FP["id"]) == 404, "taken back from her agent")
check(Fr.post(B + f"/api/obj/{K}/{FP['id']}/shares/{r.json().get('revoked_id')}/restore").ok and FA.role(FP["id"]) == "edit", "and given back")
check(role(A, FP["id"]) == 404 and role(Ol, FP["id"]) == 404 and AG.role(FP["id"]) == 404, "nobody else reaches it")

sys.exit(done("obj_core"))
