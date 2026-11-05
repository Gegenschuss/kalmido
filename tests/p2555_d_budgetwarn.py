#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.555.0 D API tests (#4570): the budget warning at 80 % / 100 % of "Budget h" per task and per project. Own container.
 - status from the server: GET /api/lists/<id>/overview time.budget_level none | ok | warn | over (+ budget_pct), the
   task's GET /api/time/entries?task_id= budget.level (the same rule, personal/budgetwarn.py bw_level)
 - no budget: no level, no notice; 79 %: nothing; 80 %: warn + exactly one notice (News kind budgetwarn) to the owner and
   the project's admins (never to a member with edit rights); 85 %: no second one; 100 %: over + one more notice
 - per project the same (its budget = the tasks' values), the task's and the project's notices are separate
 - the event "timebudget" switched off (News): no notice for that person, the others still get theirs
 - the share falls below the mark (entry deleted): the mark goes down, crossing again tells again
 - a person without an organisation, own private project, own time: gets their notices the same way
freelancer-matrix: time
usage: p2555_d_budgetwarn.py <datadir>"""
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
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
FEAT = "collab,time,fields,comments"
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
# carol switches the event off (News and push); the matrix has the row
r = Ca.patch(B + "/api/settings", json={"notify": {"timebudget": {"news": False, "push": False}}})
check(r.ok, "carol switches the budget warnings off " + r.text[:160])
mc = Ca.get(B + "/api/state").json().get("notify", {}).get("timebudget")
check(mc == {"news": False, "push": False}, f"the matrix has the row timebudget, off for carol: {mc}")
mb = Bo.get(B + "/api/state").json().get("notify", {}).get("timebudget")
check(mb == {"news": True, "push": True}, f"News + push on by default: {mb}")


def news(S, scope=None):
    r = S.get(B + "/api/news")
    assert r.ok, r.text
    return [x for x in r.json()["items"] if x["kind"] == "budgetwarn" and (scope is None or x["data"].get("scope") == scope)]


def overview(S, P):
    r = S.get(B + f"/api/lists/{P}/overview")
    assert r.ok, r.text
    return r.json()["time"] or {}


def task_level(S, tid):
    b = S.get(B + f"/api/time/entries?task_id={tid}").json().get("budget")
    return b and b["level"]


def project(S, tag, members=()):
    P = S.post(B + "/api/lists", json={"name": f"Spot {tag}", "time_tracking": True}).json()["id"]
    S.post(B + f"/api/lists/{P}/fields", json={"name": "Budget h", "type": "number"})
    fb = next(f for f in S.get(B + "/api/state").json()["fields"] if f["list_id"] == P and f["name"] == "Budget h")
    for u, role in members:
        r = S.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role})
        if r.status_code == 409:
            r = S.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role, "bridge_ok": True})
        check(r.ok, f"{tag}: {u} becomes {role} " + r.text[:120])

    def task(title, v=None):
        b = {"title": title, "list_id": P}
        if v is not None:
            b["fields"] = {str(fb["id"]): str(v)}
        r = S.post(B + "/api/tasks", json=b)
        assert r.ok, r.text
        return r.json()["id"]
    return P, task


def track(S, tid, minutes, tag, day="2026-10-20T09:00"):
    r = S.post(B + "/api/time/entries", json={"task_id": tid, "start": day, "minutes": minutes})
    check(r.ok, f"{tag}: time entry " + r.text[:120])
    return r.json().get("id")


def case(S, tag, others=True):
    """S owns the project; with others: bob = admin (gets the notices), carol = admin with the event off, dave = edit."""
    team = (("bob", "admin"), ("carol", "admin"), ("dave", "edit")) if others else ()
    # no budget at all: nothing
    P0, task0 = project(S, tag + " 0", team)
    track(S, task0("No budget"), 600, tag)
    ov = overview(S, P0)
    check(ov.get("budget_level") == "none" and ov.get("budget_pct") is None, f"{tag}: a project without a budget: level none: {ov}")
    check(not news(S), f"{tag}: no budget, no notice")
    # task 10 h + a second task 10 h (project 20 h): the task crosses first
    P, task = project(S, tag, team)
    t1, t2 = task("Edit", 10), task("Grade", 10)
    track(S, t1, 474, tag)  # 7.9 h = 79 %
    check(task_level(S, t1) == "ok" and not news(S), f"{tag}: 79 %: ok, no notice ({task_level(S, t1)}, {len(news(S))})")
    track(S, t1, 6, tag)  # 8 h = 80 %
    n = news(S, "task")
    check(task_level(S, t1) == "warn" and len(n) == 1 and n[0]["data"]["level"] == 80 and n[0]["task_id"] == t1,
          f"{tag}: 80 %: warn + exactly one notice: {task_level(S, t1)} {n}")
    check(n and n[0]["to_me"] is True, f"{tag}: the notice counts in the bell (to_me): {n[:1]}")
    ov = overview(S, P)
    check(ov.get("budget_level") == "ok" and ov.get("budget_pct") == 40 and not news(S, "project"), f"{tag}: the project at 8 of 20 h stays ok: {ov}")
    track(S, t1, 30, tag)  # 8.5 h = 85 %
    check(len(news(S, "task")) == 1, f"{tag}: 85 %: no second notice ({len(news(S, 'task'))})")
    e100 = track(S, t1, 90, tag)  # 10 h = 100 %
    n = news(S, "task")
    check(task_level(S, t1) == "over" and len(n) == 2 and n[0]["data"]["level"] == 100,
          f"{tag}: 100 %: over + one more notice: {task_level(S, t1)} {[x['data'] for x in n]}")
    track(S, t1, 30, tag)  # 10.5 h
    check(len(news(S, "task")) == 2, f"{tag}: above 100 %: no third notice")
    # the share falls below the mark (an entry removed) and crosses again: told again
    r = S.delete(B + f"/api/time/entries/{e100}")
    check(r.ok, f"{tag}: delete an entry " + r.text[:120])
    check(task_level(S, t1) == "warn", f"{tag}: 9 of 10 h: warn again ({task_level(S, t1)})")
    track(S, t1, 60, tag)  # 10 h
    n = news(S, "task")
    check(len(n) == 3 and n[0]["data"]["level"] == 100, f"{tag}: crossing 100 % again tells again: {[x['data'] for x in n]}")
    # the project: 10 of 20 h, then 10 h more on the second task -> 20 of 20 h = over with one save (one notice, over)
    check(overview(S, P).get("budget_level") == "ok" and not news(S, "project"), f"{tag}: the project at 10 of 20 h: ok {overview(S, P)}")
    track(S, t2, 600, tag)
    ov = overview(S, P)
    check(ov.get("seconds") == 20 * 3600 and ov.get("budget_level") == "over" and ov.get("budget_pct") == 100, f"{tag}: the project 20 of 20 h: over {ov}")
    n = news(S, "project")
    check(len(n) == 1 and n[0]["data"]["level"] == 100 and n[0]["task_id"] is None and n[0]["list_id"] == P,
          f"{tag}: the project crossed 80 and 100 % with one save: one notice (over): {n}")
    # a project of its own for the 80 % step of a project
    P2, task2 = project(S, tag + " 2", team)
    a, b = task2("Shoot", 5), task2("Sound", 5)
    track(S, b, 420, tag)  # 7 of 10 h (b alone is over: its own notice)
    check(not [x for x in news(S, "project") if x["list_id"] == P2], f"{tag}: project 2 at 70 %: nothing")
    track(S, a, 60, tag)  # 8 of 10 h
    n = [x for x in news(S, "project") if x["list_id"] == P2]
    check(overview(S, P2).get("budget_level") == "warn" and len(n) == 1 and n[0]["data"]["level"] == 80,
          f"{tag}: project 2 at 80 %: warn + one notice: {overview(S, P2)} {n}")
    track(S, a, 30, tag)
    check(len([x for x in news(S, "project") if x["list_id"] == P2]) == 1, f"{tag}: project 2 at 85 %: no second one")
    return P


P = case(A, "owner alice")
# the others: bob (admin) like alice (task: 80, 100, 100 again, the second task 100, project 2's "Sound" 100; project: 100, 80), carol (admin, switched off) none, dave (edit) none
nb = news(Bo)
check(len([x for x in nb if x["data"]["scope"] == "task"]) == 5 and len([x for x in nb if x["data"]["scope"] == "project"]) == 2,
      f"bob (project admin) gets the same notices: {[x['data'] for x in nb]}")
check(news(Ca) == [], f"carol (admin, event off): no notice: {news(Ca)}")
check(news(Da) == [], f"dave (edit member): no notice: {news(Da)}")
# the time a member books counts for the owner's notice (everyone's time, not the viewer's share)
P3, task3 = project(A, "member time", (("dave", "edit"),))
t = task3("Mix", 1)
track(Da, t, 48, "member time")  # 0.8 of 1 h, booked by dave
check(len([x for x in news(A, "task") if x["task_id"] == t]) == 1, "the time dave books tells the owner alice")
check(news(Da) == [], "dave himself gets none (no admin)")

# 2.555.0 (#4570, review F2): "delete all times" lowers the marks, so the next crossing tells again
P4, task4 = project(A, "wipe")
t = task4("Cut", 1)
track(A, t, 60, "wipe")  # 1 of 1 h: over
check(len([x for x in news(A, "task") if x["task_id"] == t]) == 1, "wipe: the first crossing tells")
nm = A.get(B + "/api/state").json()
name = next(x["name"] for x in nm["lists"] if x["id"] == P4)
r = A.post(B + f"/api/lists/{P4}/time/delete-all", json={"confirm": name})
check(r.ok and r.json().get("deleted") == 1, "wipe: delete all " + r.text[:120])
check(task_level(A, t) == "ok", f"wipe: no time left: ok ({task_level(A, t)})")
track(A, t, 60, "wipe")
check(len([x for x in news(A, "task") if x["task_id"] == t]) == 2, "wipe: crossing again after the wipe tells again")

FID, Fr = freelancer(B, A)
case(Fr, "freelancer", others=False)

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
