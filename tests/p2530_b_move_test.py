#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.530.0 B (#4316): a move keeps watchers and the delegation for the way back; a series Undo does not overwrite later changes.
Own container (kt.fresh). Invented people and titles only; every step as the person without an organisation with an own agent.
freelancer-matrix: tasks
 - a task moved into a project the watcher and the delegated agent do not reach: move_ended names watchers / delegate; moving
   it back (by hand or the Undo step) within a day brings both back (move_restored), the agent hears "assigned" again; a
   watcher who no longer reaches the project is not brought back
 - Undo of a recurring task's completion after the series was changed (a new start, a fixed reminder): the later values stay,
   the due date goes back; without a change the old values come back as before
 - the table view's "Delete field" asks the server for the number of tasks with a value (static look at tablecells.js)
usage: p2530_b_move_test.py <datadir>      (KMT_NOSTART=1 / P2530BM_NOSTART=1: a running server)"""
import os
import sys
from datetime import timedelta

import requests

import testclock
from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup, until

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2530BM")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
V = B + "/api/v1"
D = lambda n: (testclock.today() + timedelta(days=n)).isoformat()  # noqa: E731


def person(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab"})
    return r.json()["id"], s


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def watchers(tid):
    # 2.972.0 (#5285): the watching rows of the core's obj_follow
    return sorted(x[0] for x in dbx("SELECT user_id FROM obj_follow WHERE kind='task' AND ref_id=? AND mode='watch'", (tid,)))


def delegate(tid):
    return dbx("SELECT delegate_agent_id FROM tasks WHERE id=?", (tid,))[0][0]


BID, Bo = person("bob")
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write", "comments"]})
assert r.status_code in (200, 201), r.text
AG = r.json()["id"]
TA = requests.Session()
TA.headers.update({"Authorization": "Bearer " + r.json()["token"]})
L = F.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
L2 = F.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": BID, "role": "edit"}).ok

# ================================================================== a move and the way back
T = task(F, L, "Fix the login page", delegate_agent_id=AG)
check(Bo.post(B + f"/api/tasks/{T}/watchers", json={}).ok and watchers(T) == [BID], "setup: bob watches the task")
check(delegate(T) == AG, "setup: delegated to the agent")
r = F.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
me = r.json().get("move_ended") or {}
check(r.ok and me.get("watchers") == 1 and me.get("delegate") == 1, f"move: move_ended names the watcher and the delegation {me}")
check(watchers(T) == [] and delegate(T) is None, "move: in the project without them both ended (as before)")
seq = max([e.get("seq", 0) for e in TA.get(V + "/agent/events", params={"since": 0}).json().get("data") or []] or [0])
r = F.patch(B + f"/api/tasks/{T}", json={"list_id": L})
mr = r.json().get("move_restored") or {}
check(r.ok and mr.get("watchers") == 1 and mr.get("delegate") == 1, f"moving back by hand restores both {mr} {r.text[:160]}")
check(watchers(T) == [BID] and delegate(T) == AG, f"back: bob watches again, the agent is delegated again {watchers(T)} {delegate(T)}")
ev = [e for e in TA.get(V + "/agent/events", params={"since": seq}).json().get("data") or []
      if e.get("event") == "assigned" and e["data"]["task"]["id"] == T]
check(len(ev) == 1 and ev[0]["data"].get("delegated") is True, f"the agent hears of the delegation again {ev}")

# the Undo step (batch patch_each with _prev) works the same way
r = F.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
check(r.ok and (r.json().get("move_ended") or {}).get("watchers") == 1, "second move ends the watcher again")
r = F.post(B + "/api/tasks/batch", json={"ids": [T], "action": "patch_each",
                                          "data": {"items": {str(T): {"list_id": L, "_prev": {"list_id": L2}}}}})
check(r.ok and watchers(T) == [BID] and delegate(T) == AG, f"Undo brings back watcher and delegation {r.text[:160]}")

# a watcher who no longer reaches the project stays out
r = F.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
check(r.ok and watchers(T) == [], "third move")
check(F.delete(B + f"/api/lists/{L}/members/{BID}").ok, "setup: bob is removed from the project")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L, BID)), "setup: bob left the project")
r = F.patch(B + f"/api/tasks/{T}", json={"list_id": L})
check(r.ok and watchers(T) == [] and delegate(T) == AG, f"back: only the agent comes back, bob no longer reaches it {watchers(T)}")

# ================================================================== Undo of a series completion
def complete(tid, due):
    j = F.post(B + f"/api/tasks/{tid}/complete", json={"expect_due": due}).json()
    return j["undo"]


def past(at):
    """Wait until the database clock is past the completion's second (updated_at has whole seconds)."""
    return until(lambda: dbx("SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS')")[0][0] > at[:19], timeout=5)


RC = task(F, L2, "Water plants", due=D(0), start=D(-1), repeat="FREQ=WEEKLY", remind_at=D(0) + "T09:00")
u = complete(RC, D(0))
check(u.get("copy_id") and dbx("SELECT due FROM tasks WHERE id=?", (RC,))[0][0] == D(7), "series: completed, the series moved on")
past(u["at"])
check(F.patch(B + f"/api/tasks/{RC}", json={"start": D(3), "remind_at": D(5) + "T18:30"}).ok, "series: changed after the completion")
r = F.post(B + f"/api/tasks/{RC}/undo", json=u)
x = dbx("SELECT due, start, remind_at FROM tasks WHERE id=?", (RC,))[0]
check(r.ok and x[0] == D(0), f"series undo: the due date goes back {r.status_code} {r.text[:120]} {x}")
check(x[1] == D(3) and str(x[2]).startswith(D(5) + "T18:30"), f"series undo: the later start and reminder stay {x}")
# without a change in between: everything comes back as before
RC2 = task(F, L2, "Feed the cat", due=D(0), start=D(-1), repeat="FREQ=WEEKLY", remind_at=D(0) + "T08:00")
u = complete(RC2, D(0))
r = F.post(B + f"/api/tasks/{RC2}/undo", json=u)
x = dbx("SELECT due, start, remind_at FROM tasks WHERE id=?", (RC2,))[0]
check(r.ok and x[0] == D(0) and x[1] == D(-1) and str(x[2]).startswith(D(0) + "T08:00"), f"series undo without a change: all back {x}")

# ================================================================== the table view's field delete asks the server
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "js", "tablecells.js"), encoding="utf-8").read()
fn = src[src.find("async function tcFieldAct"):src.find("function tcFieldAdd")]
check("/api/fields/${f.id}/count" in fn and fn.find("/count") < fn.find("askConfirm"),
      "tablecells.js: the delete confirmation counts on the server (GET /api/fields/<id>/count) before it asks")

sys.exit(done("p2530_b_move"))
