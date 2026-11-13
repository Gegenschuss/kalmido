#!/usr/bin/env python3
"""2.484.0 A (#2200): scheduling polls over REST v1 / MCP (GET /api/v1/polls, GET /api/v1/polls/{id}, POST /api/v1/polls;
MCP list_polls, get_poll, create_poll). Invented names only, addresses @example.com.
 - scope calendar: a read-only token gets 403 with required_scope; the app routes /api/polls stay closed to tokens
 - a team agent of the organisation: creates a poll in its workspace (201, url = the public link), members read it in the
   app (only the owner / an admin of the organisation changes it), sees its own polls; someone else's poll of the
   organisation only when it hangs on a project / task shared with the agent; a poll without a link, one at a project not
   shared with it, a private poll of a person and a poll of another organisation: 404 and not in the list (tenant-matrix: poll)
 - the voters' addresses never in the API (names and the tally yes)
 - the public link of an agent's poll opens for a visitor; with a bearer token (an agent) the same 404 page, also POST
 - a personal agent: its private poll is its owner's too (list, read, change in the app), the owner's own private poll
   stays hidden from it; a freelancer's personal agent alike (freelancer-matrix: polls)
 - unknown fields 400 (unknown_field), one time only 400
usage: p2484_a_polls_v1_test.py"""
# kalmido-suite: fresh
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, sess  # noqa: E402

V = B + "/api/v1"
MODS = "cal,comments,collab,events,contacts,files,agents,team"
SCOPES = ["read", "tasks:write", "calendar"]
TIMES = [{"start": "2031-05-05T10:00"}, {"start": "2031-05-06T14:00"}]


def ahead(tok):
    return {"Authorization": "Bearer " + tok, **H}


def person(a, name, orgs):
    r = a.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD,
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    s = sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
    return r.json()["id"], s


def agent(s, path, name, scopes=None, **kw):
    r = s.post(B + path, json={"username": name, "display_name": name.title(), "scopes": scopes or SCOPES, **kw})
    assert r.ok, r.text
    aid = r.json()["id"]
    kt.dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
           (aid, MODS))
    return aid, ahead(r.json()["token"])


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def share(s, lid, uid):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": "edit"})
    assert r.ok, r.text


def app_poll(s, title, **kw):
    r = s.post(B + "/api/polls", json={"title": title, "options": TIMES, "tz": "Europe/Berlin", **kw})
    assert r.status_code == 201, r.text
    return r.json()["poll"]


def v1_new(h, title, **kw):
    return requests.post(V + "/polls", headers=h, json={"title": title, "options": TIMES, "tz": "Europe/Berlin", **kw})


def v1_ids(h, **params):
    r = requests.get(V + "/polls", headers=h, params=params)
    check(r.status_code == 200, f"GET /polls 200, not {r.status_code}: {r.text[:200]}")
    return [x["id"] for x in r.json().get("data", [])]


def app_ids(s):
    return [x["id"] for x in s.get(B + "/api/polls").json()["items"]]


def code(h, pid):
    return requests.get(V + f"/polls/{pid}", headers=h).status_code


kt.fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "anna", "display_name": "Anna Admin", "password": kt.PASSWORD}).ok
A = sess("anna")
assert A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "org_name": "Testorg", "modules": MODS.split(",")}).ok
assert A.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 3}).ok
me = A.get(B + "/api/state").json()["me"]
ANNA, ORG = me["id"], me["workspaces"][0]["id"]
BERT, Be = person(A, "bert", [{"id": ORG, "role": "member"}])
OTTO, Ot = person(A, "otto", [])
r = A.post(B + "/api/admin/orgs", json={"name": "Otherorg", "admin_id": OTTO})
assert r.status_code in (200, 201), r.text
OORG = Ot.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FRIDA, Fr = freelancer(B, A, features=MODS)

G, GH = agent(A, "/api/admin/agents", "orgbot", org_id=ORG)
RO, ROH = agent(A, "/api/admin/agents", "readbot", scopes=["read"], org_id=ORG)
P, PH = agent(A, "/api/my/agents", "annabot", org_id="private")
FP, FPH = agent(Fr, "/api/my/agents", "fridabot")

L = mklist(A, "Shared project", ORG)
share(A, L, G)
share(A, L, BERT)
L2 = mklist(A, "Not shared", ORG)
T = A.post(B + "/api/tasks", json={"title": "Plan the workshop", "list_id": L}).json()["id"]

# ---- scope and the app routes
r = requests.get(V + "/polls", headers=ROH)
check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "calendar", f"without calendar: 403 required_scope {r.text[:200]}")
check(requests.get(B + "/api/polls", headers=GH).status_code in (401, 403), "the app route /api/polls stays closed to a token")
check(v1_new(GH, "x", options=TIMES[:1]).status_code == 400, "one time only: 400")
r = v1_new(GH, "x", color="red")
check(r.status_code == 400 and r.json().get("error", {}).get("code") == "unknown_field", f"unknown field: 400 unknown_field {r.text[:200]}")

# ---- the team agent creates a poll in its workspace
r = v1_new(GH, "Workshop date", space=f"org:{ORG}", list_id=L, duration=90)
check(r.status_code == 201, f"agent creates: 201 {r.text[:300]}")
GP = r.json()
check(GP["space"] == f"org:{ORG}" and GP["user_id"] == G and GP["mine"] is True and GP["url"] and "/s/v/" in GP["url"]
      and len(GP["options"]) == 2 and GP["options"][0]["end"] == "2031-05-05T11:30", "in the workspace, the agent's, with the link " + json.dumps(GP)[:300])
check(GP["id"] in app_ids(Be) and GP["id"] in app_ids(A), "members of the organisation see the agent's poll in the app")
check(Be.patch(B + f"/api/polls/{GP['id']}", json={"title": "x"}).status_code == 403, "a member may not change it (403)")
check(A.patch(B + f"/api/polls/{GP['id']}", json={"description": "checked"}).ok, "the organisation's admin may change it")
check(GP["id"] in v1_ids(GH), "the agent lists its own poll")

# the public link of the agent's poll: people open it, an agent never
pp = "/s/v/" + GP["url"].rsplit("/s/v/", 1)[1]
r = requests.get(B + pp, headers={"Accept-Language": "en"})
check(r.status_code == 200 and "Workshop date" in r.text, f"the link of an agent's poll opens for a visitor ({r.status_code})")
check(requests.get(B + pp, headers=GH).status_code == 404, "with an agent token: the 404 page")
r = requests.post(B + pp, headers=GH, data={"name": "Bot", f"a{GP['options'][0]['id']}": "y"})
check(r.status_code == 404, f"an agent never votes through the link ({r.status_code})")

# ---- someone else's polls: only when they hang on something shared with the agent
on_list = app_poll(Be, "Retro", space=f"org:{ORG}", list_id=L)
on_task = app_poll(Be, "Kick-off", space=f"org:{ORG}", task_id=T)
loose = app_poll(Be, "Lunch", space=f"org:{ORG}")
other_list = app_poll(A, "Board", space=f"org:{ORG}", list_id=L2)
priv = app_poll(A, "Dentist")
foreign = app_poll(Ot, "Elsewhere", space=f"org:{OORG}")
ids = v1_ids(GH)
check(on_list["id"] in ids and on_task["id"] in ids, "polls at a shared project / its task: listed")
check(code(GH, on_list["id"]) == 200 and code(GH, on_task["id"]) == 200, "and readable")
for what, p in (("without a link", loose), ("at a project not shared", other_list), ("a person's private one", priv),
                ("another organisation's", foreign)):
    check(p["id"] not in ids and code(GH, p["id"]) == 404, f"{what}: not listed, 404")
check(set(v1_ids(GH, list_id=L)) == {GP["id"], on_list["id"]}, "filter list_id")
r = Ot.post(B + "/api/me/tokens", json={"name": "o", "scopes": ["read", "calendar"]})
assert r.ok, r.text
OTH = ahead(r.json()["token"])
check(foreign["id"] in v1_ids(OTH), "a person's token lists her own organisation's poll")
check(on_list["id"] not in v1_ids(OTH) and code(OTH, on_list["id"]) == 404, "a person of another organisation (token): 404")

# ---- the voters' addresses never go out
o1 = on_list["options"][0]["id"]
kt.dbx("INSERT INTO sched_poll_votes(poll_id,name,email,answers,edit_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
       (on_list["id"], "Vera Voter", "vera@example.com", json.dumps({str(o1): "y"}), "x" * 64, "2031-01-01T00:00:00Z", "2031-01-01T00:00:00Z"))
r = requests.get(V + f"/polls/{on_list['id']}", headers=GH)
d = r.json()
check(r.status_code == 200 and d["votes"] and d["votes"][0]["name"] == "Vera Voter" and "email" not in d["votes"][0]
      and "vera@example.com" not in r.text and d["options"][0]["y"] == 1 and d["best_id"] == o1, "names and tally, never an address " + r.text[:300])
check(d["url"] is None and d["can_edit"] is False, "someone else's poll: no link, no change")
check(Be.get(B + f"/api/polls/{on_list['id']}").json()["poll"]["votes"][0].get("email") == "vera@example.com", "the owner still sees it in the app")

# ---- a personal agent: its private poll is its owner's too
r = v1_new(PH, "Doctor slots")
check(r.status_code == 201 and r.json()["space"] == "private", f"personal agent creates a private poll {r.text[:200]}")
PP = r.json()["id"]
check(PP in app_ids(A) and A.get(B + f"/api/polls/{PP}").ok, "its owner lists and reads it in the app")
check(A.patch(B + f"/api/polls/{PP}", json={"description": "for me"}).ok, "its owner may change it")
check(PP not in app_ids(Be) and Be.get(B + f"/api/polls/{PP}").status_code == 404, "nobody else sees it")
check(code(PH, priv["id"]) == 404 and priv["id"] not in v1_ids(PH), "the owner's own private poll stays hidden from her agent")
check(code(GH, PP) == 404, "another agent: 404")

# ---- a person without an organisation (freelancer-matrix: polls): her personal agent
r = requests.post(V + "/polls", headers=FPH, json={"title": "Client call", "options": TIMES, "tz": "Europe/Berlin"})
check(r.status_code == 201, f"freelancer's agent creates: 201 {r.text[:200]}")
FPP = r.json()["id"]
check(FPP in v1_ids(FPH) and code(FPH, FPP) == 200, "her agent lists and reads it")
check(FPP in app_ids(Fr) and Fr.get(B + f"/api/polls/{FPP}").json()["poll"]["can_edit"] is True, "she sees and may change it in the app")
check(v1_new(FPH, "x", space=f"org:{ORG}").status_code == 404, "no other workspace: 404")
check(code(GH, FPP) == 404 and FPP not in app_ids(A), "nobody else sees it")

# ---- review (2.484.0 #2200): a team agent has no private space; a disabled owner closes the links of her agent's polls
r = v1_new(GH, "No space given")
check(r.status_code == 201 and r.json()["space"] == f"org:{ORG}", f"team agent without space: its workspace {r.text[:200]}")
r = v1_new(GH, "Private", space="private")
check(r.status_code == 400 and "team agent" in r.text, f"team agent with space private: 400 {r.text[:200]}")
fu = requests.post(V + "/polls", headers=FPH, json={"title": "Owner check", "options": TIMES, "tz": "Europe/Berlin"}).json()["url"]
fpath = "/s/v/" + fu.rsplit("/s/v/", 1)[1]
check(requests.get(B + fpath).status_code == 200, "the link of her agent's poll opens while she is active")
kt.dbx("UPDATE users SET disabled=true WHERE id=?", (FRIDA,))
check(requests.get(B + fpath).status_code == 404, "her account disabled: the link of her agent's poll closes (404)")

print(f"p2484_a_polls_v1: {kt.OKS[0]} ok, {len(kt.FAILS)} failed")
sys.exit(1 if kt.FAILS else 0)
