#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.537.0 C2 API tests (#3433, decision 5): "tracked X of Y h" per task. Own container (kt.fresh).
 - GET /api/time/entries?task_id= carries budget {h, s, pct, level, own} for a task with a "Budget h" value in a project
   with time tracking: the time of the task and its subtasks against the budget, warn from 80 %, over from 100 % (like the
   client's budget); a subtask's own budget replaces its parent's value (once per branch, like the head bar, #3437)
 - no budget: a task without a value, a project without time tracking
 - rights like the project head bar: a member (edit) counts only their own time (own=True), a participant gets none
 - the same for a person without an organisation
freelancer-matrix: time
usage: p3433_c2_task_budget_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "collab,time,fields,comments"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})


def budget(S, tid):
    r = S.get(B + f"/api/time/entries?task_id={tid}")
    assert r.ok, r.text
    j = r.json()
    check("budget" in j, f"the task's entries carry the key budget: {sorted(j)}")
    return j.get("budget")


def case(S, tag):
    P = S.post(B + "/api/lists", json={"name": f"Film {tag}", "ptype": "agency", "time_tracking": True}).json()["id"]
    fb = next(f for f in S.get(B + "/api/state").json()["fields"] if f["list_id"] == P and f["name"] == "Budget h")

    def task(title, v=None, parent=None, lid=P):
        b = {"title": title, "list_id": lid}
        if v is not None:
            b["fields"] = {str(fb["id"]): str(v)}
        if parent:
            b["parent_id"] = parent
        r = S.post(B + "/api/tasks", json=b)
        assert r.ok, r.text
        return r.json()["id"]

    def track(tid, minutes, who=S, day="2026-10-20T09:00"):
        r = who.post(B + "/api/time/entries", json={"task_id": tid, "start": day, "minutes": minutes})
        check(r.ok, f"{tag}: time entry " + r.text[:120])

    ep = task("Episode", 10)
    sub = task("Cut", None, ep)
    track(ep, 120)
    track(sub, 300)
    b = budget(S, ep)
    check(b and b["h"] == 10 and b["s"] == 7 * 3600 and b["pct"] == 70 and b["level"] == "ok" and b["own"] is False,
          f"{tag}: 7 of 10 h, the subtask counts along: {b}")
    track(sub, 60)
    b = budget(S, ep)
    check(b and b["pct"] == 80 and b["level"] == "warn", f"{tag}: 8 of 10 h = warn: {b}")
    track(ep, 180)
    b = budget(S, ep)
    check(b and b["pct"] == 110 and b["level"] == "over", f"{tag}: 11 of 10 h = over: {b}")
    check(budget(S, sub) is None, f"{tag}: the subtask without a value has no budget")
    # once per branch: valued subtasks replace the parent's own value
    p2 = task("Episode 2", 10)
    a2 = task("Shoot", 4, p2)
    task("Grade", 3, p2)
    track(a2, 240)
    b = budget(S, p2)
    check(b and b["h"] == 7 and b["s"] == 4 * 3600, f"{tag}: the subtasks' 4 + 3 h replace the parent's 10 h: {b}")
    b = budget(S, a2)
    check(b and b["h"] == 4 and b["pct"] == 100 and b["level"] == "over", f"{tag}: a subtask's own budget, 4 of 4 h = over: {b}")
    check(budget(S, task("No budget")) is None, f"{tag}: a task without a value: no budget")
    # a project without time tracking: none
    Q = S.post(B + "/api/lists", json={"name": f"Notes {tag}", "ptype": "agency", "time_tracking": False}).json()["id"]
    fq = next(f for f in S.get(B + "/api/state").json()["fields"] if f["list_id"] == Q and f["name"] == "Budget h")
    r = S.post(B + "/api/tasks", json={"title": "Draft", "list_id": Q, "fields": {str(fq["id"]): "5"}})
    check(budget(S, r.json()["id"]) is None, f"{tag}: a project without time tracking: no budget")
    return P, ep


P, EP = case(A, "org-less admin")
# rights like the head bar: a member sees only their own time, a participant no budget
for u, role in (("bob", "edit"), ("carol", "participant")):
    r = A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role})
    if r.status_code == 409:
        r = A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role, "bridge_ok": True})
    check(r.ok, f"setup: {u} {role} " + r.text[:120])
r = Bo.post(B + "/api/time/entries", json={"task_id": EP, "start": "2026-10-21T09:00", "minutes": 30})
check(r.ok, "bob tracks on the task " + r.text[:120])
b = budget(Bo, EP)
check(b and b["own"] is True and b["s"] == 1800 and b["h"] == 10, f"member: only the own 0.5 h of the 10 h: {b}")
b = budget(A, EP)
check(b and b["own"] is False and b["s"] == 11 * 3600 + 1800, f"owner: everyone's time (11.5 h): {b}")
A.patch(B + f"/api/tasks/{EP}", json={"assignee_id": ids["carol"]})
r = Ca.get(B + f"/api/time/entries?task_id={EP}")
check(r.ok and r.json().get("budget") is None, f"participant: no budget: {r.status_code} {r.text[:160]}")

FID, Fr = freelancer(B, A)
case(Fr, "freelancer")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
