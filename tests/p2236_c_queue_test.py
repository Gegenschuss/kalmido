#!/usr/bin/env python3
"""2.236.0 C (#2906 #2907) the queue of an agent, own container. Invented people only (example.com).
tenant-matrix: agent
freelancer-matrix: agents
 - GET /api/v1/agent/queue: the open tasks assigned to the agent that it sees, default order priority (high first), due
   date, creation; done tasks and tasks of others not in it; max_parallel of the work style: the first n "active", the
   rest "waiting" with position 1..; priority_rule of the work style along
 - PUT /api/v1/agent/queue {order}: the agent's order first, the rest in the default order; a task of someone else /
   unknown id / duplicate / no list / unknown field = 400; a person's session refused
 - GET /api/agents/<aid>/queue: the same queue for an instance admin (team agent) / the owner (personal agent); someone
   else 404, the agent's token refused
 - the event "assigned" carries queue {position, active, max_parallel} and priority_rule
 - a person without an organisation: the own agent's queue in the private space, the same rules
usage: p2236_c_queue_test.py <datadir>      (P2236C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


if os.environ.get("P2236C_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com", "orgs": []})
assert r.ok, r.text
Ca = sess("carol")
for s in (A, Ca):
    feats = set(((s.get(B + "/api/state").json().get("settings") or {}).get("features") or "").split(",")) - {""}
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": ",".join(sorted(feats | {"agents"}))}).ok
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]

ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "qbot", "display_name": "Qbot"}).json()
AG, T = ag["id"], bearer(ag["token"])
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
L = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
L2 = A.post(B + "/api/lists", json={"name": "Secret", "org_id": ORG}).json()["id"]  # not shared with the agent


def task(sess_, lid, title, prio=0, due=None, assignee=None):
    b = {"title": title, "list_id": lid, "priority": prio}
    if due:
        b["due"] = due
    if assignee:
        b["assignee_id"] = assignee
    r = sess_.post(B + "/api/tasks", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def queue(s, url):
    r = s.get(url)
    check(r.ok, f"GET {url}: {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {"items": []}


def ids(q):
    return [x["task_id"] for x in q.get("items") or []]


LOW = task(A, L, "Low", 1, assignee=AG)
HIGH = task(A, L, "High", 5, assignee=AG)
MED_LATE = task(A, L, "Medium late", 3, "2026-12-01", assignee=AG)
MED_SOON = task(A, L, "Medium soon", 3, "2026-11-01", assignee=AG)
MED_NONE = task(A, L, "Medium no date", 3, assignee=AG)
DONE = task(A, L, "Done", 5, assignee=AG)
check(A.post(B + f"/api/tasks/{DONE}/complete", json={}).ok, "complete a task")
MINE = task(A, L, "Alice's own", 5, assignee=None)
SECRET = task(A, L2, "Not shared", 5)

# ---------------------------------------------------------------- default order, no limit
q = queue(T, V + "/agent/queue")
check(ids(q) == [HIGH, MED_SOON, MED_LATE, MED_NONE, LOW], f"default order priority, due, creation: {ids(q)}")
check(q.get("max_parallel") == 0 and all(x["state"] == "active" and x["position"] is None for x in q["items"]),
      f"max_parallel 0: all active {q}")
it = (q.get("items") or [{}])[0]
check(it.get("title") == "High" and it.get("list_id") == L and it.get("list_name") == "Work" and it.get("priority") == "high",
      f"an item carries title, list, priority: {it}")
check(next((x["due"] for x in q["items"] if x["task_id"] == MED_SOON), None) == "2026-11-01", "an item carries its due date")

# ---------------------------------------------------------------- max_parallel + priority rule from the work style
r = A.patch(B + f"/api/agents/{AG}/work-style", json={"max_parallel": 2, "priority_rule": "Customer bugs before features"})
check(r.ok, f"work style: {r.status_code} {r.text[:200]}")
q = queue(T, V + "/agent/queue")
check([x["state"] for x in q["items"]] == ["active", "active", "waiting", "waiting", "waiting"]
      and [x["position"] for x in q["items"]] == [None, None, 1, 2, 3], f"max_parallel 2: 2 active, 3 waiting 1..3: {q['items']}")
check(q.get("max_parallel") == 2 and q.get("priority_rule") == "Customer bugs before features", f"queue head: {q}")

# ---------------------------------------------------------------- the agent's own order
r = T.put(V + "/agent/queue", json={"order": [LOW, MED_NONE]})
check(r.ok and ids(r.json()) == [LOW, MED_NONE, HIGH, MED_SOON, MED_LATE], f"own order first, then the rest: {r.status_code} {r.text[:300]}")
check(ids(queue(T, V + "/agent/queue")) == [LOW, MED_NONE, HIGH, MED_SOON, MED_LATE], "the order is kept")
for bad, what in (([LOW, MINE], "a task assigned to someone else"), ([LOW, SECRET], "a task the agent does not see"),
                  ([DONE], "a done task"), ([999999], "an unknown id"), ([LOW, LOW], "a duplicate"), (["x"], "no id"),
                  ([True], "a boolean"), (list(range(1, 502)), "more than 500")):
    r = T.put(V + "/agent/queue", json={"order": bad})
    check(r.status_code == 400, f"order with {what}: 400 ({r.status_code})")
check(T.put(V + "/agent/queue", json={"order": "1,2"}).status_code == 400, "order not a list: 400")
check(T.put(V + "/agent/queue", json={"order": [], "x": 1}).status_code == 400, "unknown field: 400")
r = A.put(V + "/agent/queue", json={"order": []})
check(r.status_code in (401, 403), f"a person's session: refused ({r.status_code})")
check(ids(queue(T, V + "/agent/queue"))[:2] == [LOW, MED_NONE], "a refused order changes nothing")

# a task done / unassigned leaves the queue; the stored order skips it
check(A.post(B + f"/api/tasks/{LOW}/complete", json={}).ok, "complete the first task")
check(ids(queue(T, V + "/agent/queue")) == [MED_NONE, HIGH, MED_SOON, MED_LATE], "a done task leaves the queue")

# ---------------------------------------------------------------- the person's route
q = queue(A, B + f"/api/agents/{AG}/queue")
check(ids(q) == [MED_NONE, HIGH, MED_SOON, MED_LATE] and q.get("max_parallel") == 2
      and q["items"][2]["state"] == "waiting" and q["items"][2]["position"] == 1, f"the instance admin sees the same queue: {q}")
check(Ca.get(B + f"/api/agents/{AG}/queue").status_code == 404, "someone else: 404")
r = T.get(B + f"/api/agents/{AG}/queue")
check(r.status_code in (401, 403, 404), f"the agent itself on the person's route: refused ({r.status_code})")
check(A.get(B + "/api/agents/999999/queue").status_code == 404, "unknown agent: 404")

# ---------------------------------------------------------------- the event "assigned"
NEW = task(A, L, "New", 0)
seq0 = max([e.get("seq", 0) for e in (T.get(V + "/agent/events", params={"since": 0}).json().get("data") or [])] or [0])
check(A.patch(B + f"/api/tasks/{NEW}", json={"assignee_id": AG}).ok, "assign a task to the agent")
evs = [e for e in (T.get(V + "/agent/events", params={"since": seq0}).json().get("data") or [])
       if e.get("event") == "assigned" and ((e.get("data") or {}).get("task") or {}).get("id") == NEW]
d = (evs[-1].get("data") or {}) if evs else {}
check(d.get("queue") == {"position": 3, "active": False, "max_parallel": 2} and d.get("priority_rule") == "Customer bugs before features",
      f"assigned carries queue + priority rule: {d.get('queue')} {d.get('priority_rule')!r}")

# ---------------------------------------------------------------- 2.236.0 (#2906, tenant boundary): a task of a list the
# agent shares with someone else but the person looking at its queue cannot see keeps its place without title / list / id
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "dave", "display_name": "Dave Member",
                                   "password": "password123", "email": "dave@example.com"})
assert r.ok, r.text
Da_id = r.json()["id"]
Da = sess("dave")
Da.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
DL = Da.post(B + "/api/lists", json={"name": "Dave private", "org_id": ORG}).json()["id"]
# the agent then links two lists of different people: only someone who manages both may do that (agents/safety.py bridge_check)
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": Da_id, "role": "admin"}).ok, "dave manages the agent's list"
r = Da.put(B + f"/api/lists/{DL}/members", json={"user_id": AG, "role": "edit", "bridge_ok": True})  # links lists of different people
check(r.ok, f"dave shares his list with the team agent {r.status_code} {r.text[:200]}")
DT = task(Da, DL, "Dave secret title", 5, assignee=AG)
check(A.get(B + f"/api/tasks/{DT}").status_code in (403, 404), "the admin cannot see dave's task")
q = queue(A, B + f"/api/agents/{AG}/queue")
hid = [x for x in q.get("items") or [] if x.get("hidden")]
check(len(hid) == 1 and hid[0].get("title") is None and hid[0].get("task_id") is None and hid[0].get("list_name") is None
      and "Dave secret title" not in str(q), f"admin view: dave's task hidden but counted {hid}")
check(DT in ids(queue(T, V + "/agent/queue")), "the agent itself still sees dave's task")
check(Da.delete(B + f"/api/tasks/{DT}").ok, "dave removes the task again")

# ---------------------------------------------------------------- a person without an organisation, own agent
# freelancer-matrix: agents
FID, F = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents allowed
fa = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(fa.status_code in (200, 201), f"freelancer: an own agent {fa.status_code} {fa.text[:200]}")
FA = fa.json().get("id")
FT = bearer(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
FL = F.post(B + "/api/lists", json={"name": "Private work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "freelancer: share the private list with the agent")
F1 = task(F, FL, "Invoice", 1, assignee=FA)
F2 = task(F, FL, "Offer", 5, assignee=FA)
check(ids(queue(FT, V + "/agent/queue")) == [F2, F1], "freelancer: the own agent's queue in the private space")
check(F.patch(B + f"/api/agents/{FA}/work-style", json={"max_parallel": 1}).ok, "freelancer: sets max_parallel of the own agent")
r = FT.put(V + "/agent/queue", json={"order": [F1]})
check(r.ok and ids(r.json()) == [F1, F2], f"freelancer: the agent's own order {r.status_code} {r.text[:200]}")
q = queue(F, B + f"/api/agents/{FA}/queue")
check(ids(q) == [F1, F2] and [x["state"] for x in q["items"]] == ["active", "waiting"], f"freelancer: sees the own agent's queue {q}")
check(F.get(B + f"/api/agents/{AG}/queue").status_code == 404, "freelancer: the team agent's queue 404")
check(Ca.get(B + f"/api/agents/{FA}/queue").status_code == 404, "someone else: the freelancer's agent 404")
check(A.get(B + f"/api/agents/{FA}/queue").status_code == 404, "an instance admin: someone's personal agent 404")
check(FT.put(V + "/agent/queue", json={"order": [HIGH]}).status_code == 400, "freelancer's agent: a task of the organisation 400")

print(f"p2236_c_queue: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
