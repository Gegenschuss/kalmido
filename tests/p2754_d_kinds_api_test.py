#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.754.0 (#5268, Q0b): the light kinds task, event, hub_mail, client of the shared core (kalmido/core/objlight.py).
obj_role on such a kind is exactly the area's own check -- never more -- asked through the test route
GET /api/test/objrole/<kind>/<id>[?as=<account>] (test containers only), compared with the area's own routes:
 - task: owner manage, editor edit, read-only member view, participant edit on the assigned subtask and nothing on its
   parent (only context) or another task, another organisation / an agent without a share nothing, an agent with an edit
   share edit
 - event: calendar owner manage, calendar member view, an invited person view, the rest nothing
 - hub_mail: the recipient edit (also "Not assigned"), a member who sees the client view, an organisation admin edit, a
   read-only viewer of the project nothing (mail_guests off); an agent with the project view (the API's rule, also asked
   outside its own request: #5268 hmv_client of the account asked), never "Not assigned"
 - client: its creator / the organisation admin manage, a member edit, read-only view, agents / another organisation nothing
 - a person without an organisation (freelancer-matrix: obj): her private task / event / client / mail manage resp. edit,
   nobody else
 - title / open_url / space with the role; no generic routes and no core write path for a light kind (404 / ValueError)
tenant-matrix: obj (another organisation's person and agent get no role on any of the four kinds)
usage: p2754_d_kinds_api_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, H, check, docker_logs_on_first_fail, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

V = B + "/api/v1"
D = "2026-11-17"


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


def hdr(token):
    return {**H, "Authorization": "Bearer " + token}


fresh(prefix="P2754D")
docker_logs_on_first_fail()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True,
                                     "modules": ["cal", "comments", "collab", "agents"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u, rk in (("bob", "member"), ("carl", "member"), ("rita", "readonly"), ("pia", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
ORG2 = r.json().get("id")
BOB, CARL, RITA, PIA, OLGA = (uid[u] for u in ("bob", "carl", "rita", "pia", "olga"))
S = {u: sess(u) for u in ("bob", "carl", "rita", "pia", "olga")}
S["alice"] = A
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
Bo, Ca, Ri, Pi, Ol = (S[u] for u in ("bob", "carl", "rita", "pia", "olga"))
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "planbot", "display_name": "Planbot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG, AGH = r.json()["id"], hdr(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "lonebot", "display_name": "Lonebot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG2, AG2H = r.json()["id"], hdr(r.json()["token"])
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})


def role(kind, rid, s=None, who=None):
    """The core's role on (kind, rid): of session s, or (who) of account who asked by alice outside its own request."""
    r = (s or A).get(B + f"/api/test/objrole/{kind}/{rid}", params={"as": who} if who else None)
    return r.json().get("role") if r.ok else r.status_code


def matrix(kind, rid, want, what):
    """want: {name: role} -- the sessions' own answer, the same asked for them by alice (?as=), and agents only by ?as=."""
    got, got_as = {}, {}
    for name in want:
        who = {"alice": ALICE, "frida": FID, "agent": AG, "agent2": AG2}.get(name) or uid.get(name)
        if name in S:
            got[name] = role(kind, rid, S[name])
        elif name == "frida":
            got[name] = role(kind, rid, Fr)
        got_as[name] = role(kind, rid, who=who)
    check(all(got[k] == want[k] for k in got), f"{what}: the roles {got} == {want}")
    check(got_as == want, f"{what}: the same asked for each account outside its request {got_as}")


def visible(r):
    return r.status_code == 200


# ================================================================ task
r = Bo.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG})
check(r.ok, "setup: bob's project " + r.text[:160])
P = r.json()["id"]
for who, rl in ((CARL, "edit"), (RITA, "edit"), (PIA, "participant"), (AG, "edit")):
    r = Bo.put(B + f"/api/lists/{P}/members", json={"user_id": who, "role": rl})
    check(r.ok, f"setup: member {who} as {rl} " + r.text[:160])
T1 = Bo.post(B + "/api/tasks", json={"title": "Location scout", "list_id": P}).json()["id"]
S1 = Bo.post(B + "/api/tasks", json={"title": "Call the venue", "list_id": P, "parent_id": T1, "assignee_id": PIA}).json()["id"]
T3 = Bo.post(B + "/api/tasks", json={"title": "Budget", "list_id": P}).json()["id"]
matrix("task", T1, {"bob": "manage", "carl": "edit", "rita": "view", "pia": None, "olga": None, "agent": "edit", "agent2": None},
       "task (a parent: for the participant only context)")
matrix("task", S1, {"bob": "manage", "carl": "edit", "rita": "view", "pia": "edit", "olga": None, "agent": "edit", "agent2": None},
       "subtask assigned to the participant")
matrix("task", T3, {"pia": None, "olga": None}, "another task of the project")
# the same as the area's own routes (need_task): a role <=> GET 200, edit / manage <=> PATCH allowed
for name, s in (("bob", Bo), ("carl", Ca), ("rita", Ri), ("pia", Pi), ("olga", Ol)):
    for tid in (S1, T3):
        rl = role("task", tid, s)
        check(visible(s.get(B + f"/api/tasks/{tid}")) == bool(rl), f"task {tid}: {name}'s core role {rl} matches GET /api/tasks")
        w = s.patch(B + f"/api/tasks/{tid}", json={"priority": 1})
        check(w.ok == (rl in ("edit", "manage")), f"task {tid}: {name}'s core role {rl} matches PATCH ({w.status_code})")
for h, rl, who in ((AGH, "edit", "planbot"), (AG2H, None, "lonebot")):
    check(visible(requests.get(V + f"/tasks/{S1}", headers=h)) == bool(rl), f"task: {who}'s core role {rl} matches GET /api/v1/tasks")
j = A.get(B + f"/api/test/objrole/task/{S1}", params={"as": BOB}).json()
check(j.get("title") == "Call the venue" and j.get("open") == f"t/{S1}" and j.get("space") == [ORG, BOB],
      f"task: title, open_url, space from its project ({j})")

# ================================================================ event
K = Bo.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/evcals/{K}/members", json={"user_id": CARL, "role": "view"}).ok, "setup: the calendar shared with carl (view)")
r = Bo.post(B + "/api/events", json={"cal_id": K, "title": "Kick-off", "start": f"{D}T09:00", "end": f"{D}T10:00",
                                     "attendees": [{"user_id": PIA}]})
check(r.ok, "setup: an event with pia invited " + r.text[:160])
E1 = r.json()["id"]
matrix("event", E1, {"bob": "manage", "carl": "view", "pia": "view", "rita": None, "olga": None, "agent": None, "agent2": None},
       "event (owner, calendar member, invited person)")
for name, s in (("bob", Bo), ("carl", Ca), ("pia", Pi), ("rita", Ri), ("olga", Ol)):
    rl = role("event", E1, s)
    check(visible(s.get(B + f"/api/events/{E1}")) == bool(rl), f"event: {name}'s core role {rl} matches GET /api/events")
check(Ca.patch(B + f"/api/events/{E1}", json={"title": "x"}).status_code == 403, "event: carl (view) cannot change it there either")
check(not visible(requests.get(V + f"/events/{E1}", headers=AGH)), "event: the agent without the calendar gets 404 in the API too")
j = A.get(B + f"/api/test/objrole/event/{E1}", params={"as": PIA}).json()
check(j.get("title") == "Kick-off" and j.get("open") == f"ev/{E1}" and j.get("space") == [ORG, BOB], f"event: title, open_url, space ({j})")

# ================================================================ client
r = Bo.post(B + "/api/clients", json={"name": "Acme", "org_id": ORG})
check(r.ok, "setup: bob's client " + r.text[:160])
CB = r.json()["id"]
matrix("client", CB, {"bob": "manage", "alice": "manage", "carl": "edit", "rita": "view", "olga": None, "agent": None, "agent2": None},
       "client (creator, organisation admin, member, read-only)")
for name, s in (("bob", Bo), ("carl", Ca), ("rita", Ri), ("olga", Ol)):
    rl = role("client", CB, s)
    check(visible(s.get(B + f"/api/clients/{CB}")) == bool(rl), f"client: {name}'s core role {rl} matches GET /api/clients")
j = A.get(B + f"/api/test/objrole/client/{CB}", params={"as": CARL}).json()
check(j.get("title") == "Acme" and j.get("open") == f"client/{CB}", f"client: title, open_url ({j})")
check(Bo.patch(B + f"/api/lists/{P}", json={"client_id": CB}).ok, "setup: the project belongs to the client")

# ================================================================ hub_mail
NM = [0]


def mail(owner, org, cid=None, lid=None, subject="Hello"):
    NM[0] += 1
    mid = f"<p2754d-{NM[0]}@example.com>"
    sql("INSERT INTO hub_mails(org_id,owner_id,client_id,list_id,ws,message_id,from_addr,from_name,subject,body,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (org, owner, cid, lid, f"o{org}" if org else f"u{owner}", mid, "kunde@example.com",
                                         "Kunde", subject, "Text of " + subject, "2026-11-08T10:00:00Z"), write=True)
    return sql("SELECT id FROM hub_mails WHERE message_id=?", (mid,))[0][0]


m_cl = mail(BOB, ORG, CB, None, "Invoice question")
m_li = mail(BOB, ORG, CB, P, "Shoot dates")
m_un = mail(BOB, ORG, None, None, "Not assigned yet")
# #5268: the agent's role asked outside its own request (?as=) -- hmv_client used the session's kind before, an agent then got nothing
matrix("hub_mail", m_cl, {"bob": "edit", "alice": "edit", "carl": "view", "rita": "view", "olga": None, "agent": "view", "agent2": None},
       "a client's mail (recipient, organisation admin, who sees the client)")
matrix("hub_mail", m_li, {"bob": "edit", "carl": "edit", "rita": None, "olga": None, "agent": "view", "agent2": None},
       "a project's mail (edit roles; read-only viewer without mail_guests nothing)")
matrix("hub_mail", m_un, {"bob": "edit", "carl": None, "alice": None, "agent": None}, "\"Not assigned\": only its recipient")
for name, s in (("bob", Bo), ("carl", Ca), ("rita", Ri), ("olga", Ol)):
    for mid in (m_cl, m_li, m_un):
        rl = role("hub_mail", mid, s)
        check(visible(s.get(B + f"/api/hubmail/mails/{mid}")) == bool(rl), f"mail {mid}: {name}'s core role {rl} matches the app route")
for h, mid, rl in ((AGH, m_cl, "view"), (AGH, m_li, "view"), (AGH, m_un, None), (AG2H, m_cl, None)):
    check(visible(requests.get(V + f"/mails/{mid}", headers=h)) == bool(rl), f"mail {mid}: the agent's core role {rl} matches GET /api/v1/mails")
j = A.get(B + f"/api/test/objrole/hub_mail/{m_li}", params={"as": CARL}).json()
check(j.get("title") == "Shoot dates" and j.get("open") == f"mailhub/{m_li}", f"hub_mail: subject as title, open_url ({j})")

# ================================================================ a person without an organisation (freelancer-matrix: obj)
FL = Fr.post(B + "/api/lists", json={"name": "Private shoot"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Private task", "list_id": FL}).json()["id"]
FK = Fr.post(B + "/api/evcals", json={"name": "Private calendar"}).json()["id"]
FE = Fr.post(B + "/api/events", json={"cal_id": FK, "title": "Private event", "start": f"{D}T09:00", "end": f"{D}T10:00"}).json()["id"]
r = Fr.post(B + "/api/clients", json={"name": "Private client"})
check(r.ok, "freelancer: her private client " + r.text[:160])
FC = r.json()["id"]
FM = mail(FID, None, None, None, "Private not assigned")
for kind, rid, want in (("task", FT, "manage"), ("event", FE, "manage"), ("client", FC, "manage"), ("hub_mail", FM, "edit")):
    matrix(kind, rid, {"frida": want, "bob": None, "alice": None, "agent": None}, f"freelancer: her private {kind}")
    j = A.get(B + f"/api/test/objrole/{kind}/{rid}", params={"as": FID}).json()
    check(j.get("space") == [None, FID], f"freelancer: her private {kind} lies in her own space ({j})")

# ================================================================ no generic routes, no core write path, no listing
for kind, rid in (("task", T3), ("event", E1), ("hub_mail", m_cl), ("client", CB)):
    check(Bo.get(B + f"/api/obj/{kind}/{rid}").status_code == 404 and Bo.post(B + f"/api/obj/{kind}/{rid}/trash").status_code == 404,
          f"{kind}: the core's generic routes do not serve a light kind")
check(Bo.get(B + f"/api/test/objrole/list/{P}").status_code == 404, "the test route answers only light kinds")
out = in_app(f"""from kalmido.core.writes import obj_trash, obj_write
from kalmido.core.objects import obj_rows, obj_visible_sql
for f in (lambda: obj_trash(c, {BOB}, "task", {T3}), lambda: obj_write(c, {BOB}, "client", {CB}, {{"name": "x"}})):
    try:
        f()
        print("WROTE")
    except Denied as e:
        print("DENIED", e.code)
for f in (lambda: obj_visible_sql(c, {BOB}, "task"), lambda: obj_rows(c, {BOB}, "event")):
    try:
        f()
        print("LISTED")
    except ValueError:
        print("NOLIST")""")
got = [x for x in out.split() if x in ("DENIED", "404", "WROTE", "NOLIST", "LISTED")]  # the start-up's own notes stay out
check(got == ["DENIED", "404", "DENIED", "404", "NOLIST", "NOLIST"], f"no core write path and no core listing for a light kind ({out[-600:]})")
check(sql("SELECT deleted_at FROM tasks WHERE id=?", (T3,))[0][0] is None, "the task stayed where it was")
sys.exit(done("p2754_d_kinds_api"))
