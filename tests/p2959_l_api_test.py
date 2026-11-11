#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.959.0 (job/4058): the leader's part of package 2.959. Invented people and titles only, all as a person without an
organisation with an own agent.
freelancer-matrix: agents
 - #4030: task_changed {diff: {field: {old, new}}} to the agent a task is assigned to and to a watching agent; not for its own
   change, not for its own (un)assignment, not for a task it neither has nor watches, not from a member it is not open to,
   not while its work style says task_changed: false (default true, GET / PATCH /api/agents/<id>/work-style)
usage: p2959_l_api_test.py <datadir>      (KMT_NOSTART=1 / P2959L_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2959L")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
V = B + "/api/v1"


def person(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab"})
    return r.json()["id"], s


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments"]})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    t = requests.Session()
    t.headers.update({"Authorization": "Bearer " + j["token"]})
    return j["id"], t


def events(t, since=0):
    return t.get(V + "/agent/events", params={"since": since}).json().get("data") or []


def last(t):
    return max([e.get("seq", 0) for e in events(t)] or [0])


def evs(t, since, kind, tid):
    return [e for e in events(t, since) if e.get("event") == kind and ((e.get("data") or {}).get("task") or {}).get("id") == tid]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


BID, Bo = person("bob")
AG, TA = agent(F, "fridabot")
L = F.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok

# ---------------------------------------------------------------- #4030: task_changed with old / new
TC = task(F, L, "Draft the onboarding mail", assignee_id=AG, priority=1)
s0 = last(TA)
r = F.patch(B + f"/api/tasks/{TC}", json={"due": "2030-05-04", "priority": 5})
check(r.ok, f"(setup) Frida changes due date and priority {r.status_code} {r.text[:160]}")
ev = evs(TA, s0, "task_changed", TC)
d = ev[0]["data"].get("diff") if ev else {}
check(len(ev) == 1 and d.get("due", {}).get("new") == "2030-05-04" and d.get("due", {}).get("old") is None
      and d.get("priority", {}).get("new") == "high" and d.get("priority", {}).get("old") == "low"
      and ev[0]["data"].get("assigned") is True and ev[0]["data"]["task"].get("title") == "Draft the onboarding mail",
      f"#4030: one task_changed to the assigned agent, old and new value of each field (API v1 values) {ev}")
s0 = last(TA)
r = TA.patch(V + f"/tasks/{TC}", json={"due": "2030-06-01", "expect_updated_at": TA.get(V + f"/tasks/{TC}").json().get("updated_at")})
check(r.ok and not evs(TA, s0, "task_changed", TC), f"#4030: its own change brings it nothing {r.status_code} {r.text[:160]}")
s0 = last(TA)
assert F.patch(B + f"/api/tasks/{TC}", json={"assignee_id": BID}).ok
check(not evs(TA, s0, "task_changed", TC) and evs(TA, s0, "unassigned", TC),
      f"#4030: taken away from it: unassigned, no task_changed {[e.get('event') for e in events(TA, s0)]}")
s0 = last(TA)
assert F.patch(B + f"/api/tasks/{TC}", json={"title": "Draft the onboarding mail v2"}).ok
check(not evs(TA, s0, "task_changed", TC), "#4030: a task it neither has nor watches: nothing")
assert F.post(B + f"/api/tasks/{TC}/watchers", json={"user_id": AG}).ok
s0 = last(TA)
assert Bo.patch(B + f"/api/tasks/{TC}", json={"title": "Draft the onboarding mail v3"}).ok
check(not evs(TA, s0, "task_changed", TC), "#4030 review: a member the agent is not open to reaches it neither by a change (agent gate)")
assert F.patch(B + f"/api/tasks/{TC}", json={"title": "Draft the onboarding mail v2"}).ok
s0 = last(TA)
assert F.patch(B + f"/api/tasks/{TC}", json={"title": "Draft the welcome mail"}).ok
ev = evs(TA, s0, "task_changed", TC)
check(len(ev) == 1 and ev[0]["data"]["diff"].get("title") == {"old": "Draft the onboarding mail v2", "new": "Draft the welcome mail"}
      and ev[0]["data"].get("watching") is True and ev[0]["data"].get("assigned") is False,
      f"#4030: a watched task changed by Frida: task_changed with the title before and after {ev}")
r = F.get(B + f"/api/agents/{AG}/work-style")
check(r.ok and r.json()["work_style"].get("task_changed") is True and r.json()["defaults"].get("task_changed") is True,
      f"#4030: the work style has task_changed, on by default {r.text[:200]}")
r = F.patch(B + f"/api/agents/{AG}/work-style", json={"task_changed": False})
check(r.ok and r.json()["work_style"]["task_changed"] is False, f"#4030: switched off by its owner {r.status_code} {r.text[:160]}")
check(F.patch(B + f"/api/agents/{AG}/work-style", json={"task_changed": "no"}).status_code == 400, "#4030: only true / false")
s0 = last(TA)
assert Bo.patch(B + f"/api/tasks/{TC}", json={"title": "Draft the welcome mail (short)"}).ok
check(not evs(TA, s0, "task_changed", TC), "#4030: switched off: nothing")
assert F.patch(B + f"/api/agents/{AG}/work-style", json={"task_changed": True}).ok
s0 = last(TA)
assert F.patch(B + f"/api/tasks/{TC}", json={"priority": 3}).ok
check(len(evs(TA, s0, "task_changed", TC)) == 1, "#4030: on again: it comes again")
check(TA.get(V + "/agent").json().get("work_style", {}).get("task_changed") is True, "#4030: GET /api/v1/agent shows the switch")
# review: delegated to it in the same request as a change: its event assigned says it, no task_changed with the time before
TD = task(F, L, "Plan the offsite")
s0 = last(TA)
assert F.patch(B + f"/api/tasks/{TD}", json={"title": "Plan the offsite (draft)", "delegate_agent_id": AG}).ok
check(not evs(TA, s0, "task_changed", TD) and evs(TA, s0, "assigned", TD),
      f"#4030 review: delegated in the same request: assigned, no task_changed {[e.get('event') for e in events(TA, s0)]}")

# review F2: a bulk change of more tasks than AGENT_CHANGED_MAX (50) announces at most 50 to the agent
TB = [task(F, L, f"Bulk item {i}", assignee_id=AG) for i in range(53)]
s0 = last(TA)
r = F.post(B + "/api/tasks/batch", json={"ids": TB, "action": "patch", "data": {"priority": 5}})
check(r.ok, f"(setup) a bulk change of 53 tasks {r.status_code} {r.text[:160]}")
n = len([e for e in events(TA, s0) if e.get("event") == "task_changed"])
check(n == 50, f"#4030 review F2: at most 50 task_changed per agent and request, got {n}")

sys.exit(done("p2959_l_api"))
