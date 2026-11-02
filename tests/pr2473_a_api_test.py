#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.473.0 A (#3357): "delegated to" an agent and the watchers of a task. Invented people and titles only.
freelancer-matrix: tasks
 - delegate_agent_id: only an agent of the project that is open to the person; the person stays assignee; the event "assigned"
   with delegated, its queue, the filter delegate=me; a participant cannot change it; an agent that is only a participant sees
   the task delegated to it; a move to a project out of its reach ends it ("unassigned"); leaving the project ends it
 - watchers: yourself = whoever sees the task; others only the project's owner / admins; a stranger 404; in the task object,
   GET /api/v1, filter watcher=me, webhooks and events carry them
 - comments and status changes reach a watcher as News; nothing for someone who no longer sees the task (rights when sent)
 - duplicate: the delegation goes along, the watchers do not; all as a person without an organisation with an own agent
usage: pr2473_a_api_test.py <datadir>      (KMT_NOSTART=1 / PR2473A_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="PR2473A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
V = B + "/api/v1"
FEAT = "cal,comments,collab"


def person(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
    return r.json()["id"], s


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments"]})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    t = requests.Session()
    t.headers.update({"Authorization": "Bearer " + j["token"]})
    return j["id"], t


def news(s, tid):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x.get("task_id") == tid]


def events(t, since=0):
    return t.get(V + "/agent/events", params={"since": since}).json().get("data") or []


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


BID, Bo = person("bob")
CID, Ca = person("carol")
DID, Da = person("dora")
AG, TA = agent(F, "fridabot")
OTHER, _ = agent(Ca, "carolbot")
L = F.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
L2 = F.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": DID, "role": "view"}).ok

# ---- delegated to an agent
T = task(F, L, "Fix the login page", assignee_id=FID)
r = F.patch(B + f"/api/tasks/{T}", json={"delegate_agent_id": BID})
check(r.status_code == 400 and not dbx("SELECT delegate_agent_id FROM tasks WHERE id=?", (T,))[0]["delegate_agent_id"], f"a person cannot be delegated to: {r.status_code}")
r = F.patch(B + f"/api/tasks/{T}", json={"delegate_agent_id": OTHER})
check(r.status_code == 400, f"an agent outside the project cannot: {r.status_code}")
r = Bo.patch(B + f"/api/tasks/{T}", json={"delegate_agent_id": AG})
check(r.status_code == 400, f"somebody else's personal agent is not open to a member: {r.status_code} {r.text[:100]}")
seq = max([e.get("seq", 0) for e in events(TA)] or [0])
r = F.patch(B + f"/api/tasks/{T}", json={"delegate_agent_id": AG})
check(r.ok and r.json().get("delegate_agent_id") == AG and r.json()["assignee_id"] == FID, f"delegated, the person stays assignee: {r.text[:200]}")
ev = [e for e in events(TA, seq) if e.get("event") == "assigned"]
check(len(ev) == 1 and ev[0]["data"].get("delegated") is True and ev[0]["data"]["task"]["delegate_agent_id"] == AG, f"the event assigned with delegated: {ev}")
q = TA.get(V + "/agent/queue").json()
check([x["task_id"] for x in q["items"]] == [T], f"the task counts in its queue: {q}")
check(T in [t["id"] for t in TA.get(V + "/tasks", params={"delegate": "me"}).json()["data"]], "the filter delegate=me")
check(T not in [t["id"] for t in TA.get(V + "/tasks", params={"assignee": "me"}).json()["data"]], "assignee=me stays the assignee")
hist = dbx("SELECT data FROM activity WHERE task_id=? AND kind='delegate'", (T,))
check(len(hist) == 1, f"one line in the history: {hist}")
tok = F.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "tasks:write"]}).json()["token"]
TF = {"Authorization": "Bearer " + tok}
j = requests.get(V + f"/tasks/{T}", headers=TF).json()
check(j["delegate_agent_id"] == AG and j["watchers"] == [], f"the API shows it: {j.get('delegate_agent_id')}")
r = requests.post(V + "/tasks", headers=TF, json={"title": "Second", "list_id": L, "delegate_agent_id": AG})
check(r.status_code == 201 and r.json()["delegate_agent_id"] == AG, f"POST /tasks takes it: {r.status_code} {r.text[:120]}")
T2 = r.json()["id"]
r = requests.patch(V + f"/tasks/{T2}", headers=TF, json={"delegate_agent_id": None})
check(r.ok and r.json()["delegate_agent_id"] is None, f"PATCH null clears it: {r.text[:120]}")
check(T2 not in [x["task_id"] for x in TA.get(V + "/agent/queue").json()["items"]], "and it leaves the queue")
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "participant"}).ok
TP = task(F, L, "For Bob", assignee_id=BID)
r = Bo.patch(B + f"/api/tasks/{TP}", json={"delegate_agent_id": AG})
check(r.status_code == 403, f"a participant cannot delegate: {r.status_code}")
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok

# an agent that is only a participant sees exactly what is delegated to it
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "participant"}).ok
T3 = task(F, L, "Delegated to the participant", delegate_agent_id=AG)
check(TA.get(V + f"/tasks/{T3}").ok, "a participant agent sees the task delegated to it")
check(TA.get(V + f"/tasks/{T2}").status_code == 404, "and not the others")
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok

# a move out of its reach
seq = max([e.get("seq", 0) for e in events(TA)] or [0])
T4 = task(F, L, "Moves away", delegate_agent_id=AG)
r = F.patch(B + f"/api/tasks/{T4}", json={"list_id": L2})
check(r.ok and not r.json().get("delegate_agent_id"), f"moved to a project without the agent: it ends {r.text[:160]}")
ev = [e for e in events(TA, seq) if e.get("event") == "unassigned" and e["data"]["task"]["id"] == T4]
check(len(ev) == 1 and ev[0]["data"].get("delegated") is True, f"the agent hears of it: {ev}")
r = F.patch(B + f"/api/tasks/{T4}", json={"list_id": L, "delegate_agent_id": AG})
check(r.ok and r.json().get("delegate_agent_id") == AG, f"moved back with it in one request (checked against the target): {r.text[:160]}")

# duplicate: the delegation goes along, the watchers stay behind
assert F.post(B + f"/api/tasks/{T4}/watchers", json={}).ok
r = F.post(B + f"/api/tasks/{T4}/duplicate", json={})
D1 = r.json()["task"]["id"] if r.ok else 0
check(r.ok and dbx("SELECT delegate_agent_id FROM tasks WHERE id=?", (D1,))[0]["delegate_agent_id"] == AG, f"a duplicate keeps the delegation: {r.status_code} {r.text[:120]}")
check(dbx("SELECT COUNT(*) AS n FROM task_watchers WHERE task_id=?", (D1,))[0]["n"] == 0, "not the watchers")

# ---- watchers: who may
TW = task(F, L, "Watched task", assignee_id=FID)
W = B + f"/api/tasks/{TW}/watchers"
r = Da.post(W, json={})
check(r.ok and r.json()["mine"] and [x["id"] for x in r.json()["watchers"]] == [DID] and not r.json()["can_others"], f"a viewer watches for themselves: {r.text[:160]}")
check(Da.post(W, json={}).ok and dbx("SELECT COUNT(*) AS n FROM task_watchers WHERE task_id=?", (TW,))[0]["n"] == 1, "twice = once")
check(Da.post(W, json={"user_id": BID}).status_code == 403, "a viewer cannot add others")
check(Bo.post(W, json={"user_id": DID}).status_code == 403, "a member cannot add others")
check(Bo.delete(W + f"/{DID}").status_code == 403, "nor remove them")
check(Ca.get(W).status_code == 404 and Ca.post(W, json={}).status_code == 404, "a stranger: 404")
check(F.post(W, json={"user_id": CID}).status_code == 404, "someone outside the project: 404")
check(F.post(W, json={"user_id": "x"}).status_code == 400, "a bad id: 400")
check(F.post(W, json={"nope": 1}).status_code == 400, "an unknown field: 400")
j = F.post(W, json={"user_id": BID}).json()
check(sorted(x["id"] for x in j["watchers"]) == sorted([BID, DID]) and j["can_others"] and BID in [p["id"] for p in j["people"]], f"the owner adds someone: {j}")
check(F.get(B + f"/api/tasks/{TW}").json().get("watchers") == sorted([BID, DID]), "the task carries them")
check(TW in [t["id"] for t in Da.get(B + "/api/state").json()["tasks"] if t.get("watchers")], "the app's state too")
r = requests.get(V + "/tasks", headers=TF, params={"watcher": BID}).json()["data"]
check([t["id"] for t in r] == [TW], f"the filter watcher: {r}")
check(F.delete(W + f"/{BID}").ok, "the owner removes someone")
check(Da.delete(W + f"/{DID}").ok and Da.post(W, json={}).ok, "oneself off and on again")
check(TA.post(V + f"/tasks/{TW}/watchers", json={}).ok and TA.get(V + f"/tasks/{TW}/watchers").json()["mine"], "an agent watches through the API")
seq = max([e.get("seq", 0) for e in events(TA)] or [0])
assert F.post(B + f"/api/tasks/{TW}/comments", json={"body": "Agent, please look"}).ok  # a personal agent is open to its owner only
check([e for e in events(TA, seq) if e.get("event") == "comment"], "the watching agent gets the comment event")
check(TA.delete(V + f"/tasks/{TW}/watchers/{AG}").ok, "and stops")
ro = F.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read"]}).json()["token"]
check(requests.post(V + f"/tasks/{TW}/watchers", headers={"Authorization": "Bearer " + ro}, json={}).status_code == 403, "a read token cannot")

# ---- what reaches a watcher (Dora is only a viewer, wrote nothing)
Da.post(B + "/api/news/read", json={"all": True})
assert Bo.post(B + f"/api/tasks/{TW}/comments", json={"body": "A first look"}).ok
check([x for x in news(Da, TW) if x["kind"] == "comment"], "a comment reaches the watcher")
assert Bo.post(B + f"/api/tasks/{TW}/complete", json={}).ok
check([x for x in news(Da, TW) if x["kind"] == "complete"], "the completion")
assert Bo.post(B + f"/api/tasks/{TW}/complete", json={"status": 0}).ok
check([x for x in news(Da, TW) if x["kind"] == "complete" and (x.get("data") or {}).get("st") == "reopen"], f"reopening: {news(Da, TW)}")
check(not news(Ca, TW), "a stranger hears nothing")
check(dbx("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND task_id=? AND kind='complete'", (BID, TW))[0]["n"] == 0, "the actor neither")

# rights when sent: a participant no longer sees the task, the row stays, nothing arrives
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": DID, "role": "participant"}).ok
Da.post(B + "/api/news/read", json={"all": True})
n0 = dbx("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND task_id=?", (DID, TW))[0]["n"]
assert Bo.post(B + f"/api/tasks/{TW}/comments", json={"body": "Secret after the change"}).ok
assert Bo.post(B + f"/api/tasks/{TW}/complete", json={}).ok
check(dbx("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND task_id=?", (DID, TW))[0]["n"] == n0, "no longer sees the task: nothing arrives")
check(Da.post(W, json={}).status_code == 404, "and cannot watch it")
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": DID, "role": "view"}).ok

# leaving the project ends watching and delegation
TL = task(F, L, "Left behind", delegate_agent_id=AG)
assert Da.post(B + f"/api/tasks/{TL}/watchers", json={}).ok
assert F.delete(B + f"/api/lists/{L}/members/{DID}").ok
check(dbx("SELECT COUNT(*) AS n FROM task_watchers WHERE user_id=?", (DID,))[0]["n"] == 0, "someone who left no longer watches")
assert F.delete(B + f"/api/lists/{L}/members/{AG}").ok
check(not dbx("SELECT delegate_agent_id FROM tasks WHERE id=?", (TL,))[0]["delegate_agent_id"], "an agent that left is no longer delegated")
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok

# a move to a project of other people: their list shows no old watchers
TM = task(F, L, "Moves with a watcher")
assert Bo.post(B + f"/api/tasks/{TM}/watchers", json={}).ok
assert F.patch(B + f"/api/tasks/{TM}", json={"list_id": L2}).ok
check(dbx("SELECT COUNT(*) AS n FROM task_watchers WHERE task_id=?", (TM,))[0]["n"] == 0, "a watcher out of reach of the target goes")

spec = A.get(V + "/openapi.json").json() if A.get(V + "/openapi.json").ok else {}
check("/tasks/{id}/watchers" in spec.get("paths", {}), "OpenAPI names the routes")
sys.exit(done("pr2473_a_api"))
