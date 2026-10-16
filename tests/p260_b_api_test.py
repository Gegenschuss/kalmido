#!/usr/bin/env python3
"""2.60.0 API tests, part B (#1510 WIP limits per kanban column, #1511 story points and velocity). Invented names only.
 - WIP: PATCH /api/sections/{id} {wip_limit} sets / clears (null, 0), bad values 400, a viewer 403, a stranger 404, the
   undo's _prev keeps a limit changed meanwhile (conflict); a deleted section's undo brings its limit back; API v1 shows
   and sets it (scope structure; without it 403); a new Software project with the standard sections gets 3 for In progress
   and Review, the other sections none, a project without the sections nothing
 - story points: the allowed values 1 2 3 5 8 13, 4 / 21 / "x" 400, null clears (the task carries no points then), the web
   route, API v1 (create + change), batch; saved also where the list has them off; points_on only by the owner (a member
   403); a task template keeps the points
 - velocity: the last closed sprints only (planned / active do not count), the close-out (review json points_done) when
   there is one, else counted from the sprint's completed tasks (milestones and open tasks do not count), the average;
   a stranger 404, an agent of another organisation 404, the agent the list is shared with reads it over API v1
 - rollback: only the new column sections.wip_limit (the rest is the leader's shared schema)
tenant-matrix: list
usage: p260_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def agent(name, scopes, org=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=? WHERE user_id=?", (org, aid), write=True)
    return aid, tok(t)


def secs(lid):
    return {r[0]: (r[1], r[2]) for r in dbx("SELECT name, id, wip_limit FROM sections WHERE list_id=?", (lid,))}


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title, **kw})
    assert r.ok, r.text
    return r.json()["id"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
AG, AGS = agent("devbot", ["read", "tasks:write", "structure"], org=ORG)
AGR, AGRS = agent("readbot", ["read", "tasks:write"], org=ORG)
AGX, AGXS = agent("betabot", ["read", "tasks:write", "structure"], org=ORG2)
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- rollback: one new column only
check(dbx("SELECT 1 FROM information_schema.columns WHERE table_name='sections' AND column_name='wip_limit'"), "sections.wip_limit exists")

# ---- the software project type suggests 3 for In progress and Review
r = Bo.post(B + "/api/lists", json={"name": "App Alpha", "ptype": "software", "sections": True})
check(r.ok, f"setup: software project with sections ({r.status_code} {r.text[:120]})")
P = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P), write=True)
sc = secs(P)
check(sc.get("In progress", (0, 0))[1] == 3 and sc.get("Review", (0, 0))[1] == 3, f"software: In progress / Review 3 ({sc})")
check(all(v[1] is None for k, v in sc.items() if k not in ("In progress", "Review")), f"software: the other sections without a limit ({sc})")
r = Bo.post(B + "/api/lists", json={"name": "App Empty", "ptype": "software"})
check(r.ok and not dbx("SELECT 1 FROM sections WHERE list_id=?", (r.json()["id"],)), "software without the standard sections: no sections, no limits")
r = Bo.post(B + "/api/lists", json={"name": "Agency X", "ptype": "agency", "sections": True})
check(r.ok and all(v[1] is None for v in secs(r.json()["id"]).values()), "agency type: no limits")
INP, REV, BACK = sc["In progress"][0], sc["Review"][0], sc["Backlog"][0]

# ---- members: carol edits, dave (other organisation) is a stranger
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol edits P")
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: P shared with devbot")
Bo.put(B + f"/api/lists/{P}/members", json={"user_id": AGR, "role": "edit"})  # (the scope check comes first either way)

# ---- WIP limit: set, clear, bad values, rights
r = Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 2})
check(r.ok and secs(P)["Backlog"][1] == 2, f"owner sets a limit ({r.status_code})")
r = Ca.patch(B + f"/api/sections/{BACK}", json={"wip_limit": "4"})
check(r.ok and secs(P)["Backlog"][1] == 4, f"a member with edit rights sets it (digit string) ({r.status_code})")
for bad in (-1, 1000, "x", 2.5, True):
    r = Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": bad})
    check(r.status_code == 400 and secs(P)["Backlog"][1] == 4, f"wip_limit {bad!r}: 400, unchanged ({r.status_code})")
r = Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 0})
check(r.ok and secs(P)["Backlog"][1] is None, "0 clears")
Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 3})
r = Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": None})
check(r.ok and secs(P)["Backlog"][1] is None, "null clears")
r = Da.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 5})
check(r.status_code == 404 and secs(P)["Backlog"][1] is None, f"a stranger: 404 ({r.status_code})")
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": CAROL, "role": "view"}).ok, "setup: carol only views")
r = Ca.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 5})
check(r.status_code == 403 and secs(P)["Backlog"][1] is None, f"a viewer: 403 ({r.status_code})")
Bo.put(B + f"/api/lists/{P}/members", json={"user_id": CAROL, "role": "edit"})
# the undo's _prev: a limit changed meanwhile stays
Bo.patch(B + f"/api/sections/{INP}", json={"wip_limit": 4})
r = Bo.patch(B + f"/api/sections/{INP}", json={"wip_limit": 3, "_prev": {"wip_limit": 5}})
check(r.ok and r.json().get("conflicts") and secs(P)["In progress"][1] == 4, f"undo with a stale _prev: conflict, unchanged ({r.text[:120]})")
r = Bo.patch(B + f"/api/sections/{INP}", json={"wip_limit": 3, "_prev": {"wip_limit": 4}})
check(r.ok and not r.json().get("conflicts") and secs(P)["In progress"][1] == 3, "undo with the right _prev")
# delete + undo (re-create with its limit)
Bo.patch(B + f"/api/sections/{BACK}", json={"wip_limit": 7})
r = Bo.delete(B + f"/api/sections/{BACK}")
sec = r.json().get("section") or {}
check(r.ok and sec.get("wip_limit") == 7, f"delete returns the limit ({sec})")
r = Bo.post(B + "/api/sections", json={"list_id": P, "name": sec.get("name"), "sort": sec.get("sort"), "wip_limit": sec.get("wip_limit"), "tasks": []})
check(r.ok and r.json().get("wip_limit") == 7, f"undo re-creates it with the limit ({r.text[:120]})")
BACK = r.json()["id"]
# the state carries it
st = Bo.get(B + "/api/state").json()
check(any(s.get("id") == INP and s.get("wip_limit") == 3 for s in st.get("sections") or []), "the app's state carries wip_limit")

# ---- API v1: read and set (scope structure)
r = AGS.get(V + f"/lists/{P}/sections")
row = next((x for x in r.json().get("data") or [] if x["id"] == INP), {})
check(r.ok and row.get("wip_limit") == 3 and any(x.get("wip_limit") is None for x in r.json()["data"]), f"v1: sections carry wip_limit ({row})")
r = AGS.patch(V + f"/sections/{REV}", json={"wip_limit": 2})
check(r.ok and r.json().get("wip_limit") == 2 and secs(P)["Review"][1] == 2, f"v1: the agent sets a limit ({r.status_code} {r.text[:100]})")
r = AGS.patch(V + f"/sections/{REV}", json={"wip_limit": None})
check(r.ok and r.json().get("wip_limit") is None, "v1: null clears")
r = AGRS.patch(V + f"/sections/{REV}", json={"wip_limit": 2})
check(r.status_code == 403 and secs(P)["Review"][1] is None, f"v1: without structure 403 ({r.status_code})")
r = AGXS.patch(V + f"/sections/{REV}", json={"wip_limit": 2})
check(r.status_code == 404, f"v1: another organisation's agent 404 ({r.status_code})")
r = AGS.post(V + f"/lists/{P}/sections", json={"name": "QA", "wip_limit": 2})
check(r.status_code == 201 and r.json().get("wip_limit") == 2, f"v1: a new section with a limit ({r.text[:100]})")
r = AGS.patch(V + f"/sections/{REV}", json={"wip": 2})
check(r.status_code == 400, f"v1: an unknown field 400 ({r.status_code})")
spec = AGS.get(V + "/openapi.json").json()
check("wip_limit" in spec["components"]["schemas"]["Section"]["properties"]
      and "points" in spec["components"]["schemas"]["Task"]["properties"]
      and spec["paths"].get("/lists/{id}/velocity", {}).get("get", {}).get("x-kalmido-scope") == "read", "OpenAPI: wip_limit, points, velocity (read)")

# ---- story points
T1 = task(Bo, P, "Login page")
for v in (1, 2, 3, 5, 8, 13):
    r = Bo.patch(B + f"/api/tasks/{T1}", json={"points": v})
    check(r.ok and dbx("SELECT points FROM tasks WHERE id=?", (T1,))[0][0] == v, f"points {v} saved")
for bad in (4, 21, 0.5, "x", -1, True):
    r = Bo.patch(B + f"/api/tasks/{T1}", json={"points": bad})
    check(r.status_code == 400 and dbx("SELECT points FROM tasks WHERE id=?", (T1,))[0][0] == 13, f"points {bad!r}: 400 ({r.status_code})")
r = Bo.patch(B + f"/api/tasks/{T1}", json={"points": None})
check(r.ok and dbx("SELECT points FROM tasks WHERE id=?", (T1,))[0][0] is None and "points" not in r.json(), "null clears (the task carries no points)")
check(dbx("SELECT points_on FROM lists WHERE id=?", (P,))[0][0] == 0, "points_on is off by default")
r = Bo.patch(B + f"/api/tasks/{T1}", json={"points": 5})
check(r.ok and r.json().get("points") == 5, "saved also while the list has them off")
T2 = task(Bo, P, "Signup page", points=8)
check(dbx("SELECT points FROM tasks WHERE id=?", (T2,))[0][0] == 8, "a new task with points")
r = Ca.patch(B + f"/api/lists/{P}", json={"points_on": True})
check(r.status_code == 403 and dbx("SELECT points_on FROM lists WHERE id=?", (P,))[0][0] == 0, f"points_on: a member 403 ({r.status_code})")
r = Bo.patch(B + f"/api/lists/{P}", json={"points_on": True})
check(r.ok and dbx("SELECT points_on FROM lists WHERE id=?", (P,))[0][0] == 1, "points_on: the owner switches it on")
r = Bo.patch(B + f"/api/lists/{P}", json={"points_on": False, "_prev": {"points_on": 0}})
check(dbx("SELECT points_on FROM lists WHERE id=?", (P,))[0][0] == 1, f"points_on: an undo with a stale _prev changes nothing ({r.text[:100]})")
# API v1
r = AGS.get(V + f"/tasks/{T1}")
check(r.ok and r.json().get("points") == 5, "v1: the task carries points")
r = AGS.patch(V + f"/tasks/{T1}", json={"points": 3})
check(r.ok and r.json().get("points") == 3, f"v1: the agent changes the points ({r.text[:100]})")
r = AGS.patch(V + f"/tasks/{T1}", json={"points": 4})
check(r.status_code == 400, f"v1: points 4 -> 400 ({r.status_code})")
r = AGS.post(V + "/tasks", json={"list_id": P, "title": "API task", "points": 2})
check(r.status_code == 201 and r.json().get("points") == 2, f"v1: create with points ({r.text[:100]})")
r = AGS.get(V + f"/lists/{P}")
check(r.ok and r.json().get("points_on") is True, "v1: the list carries points_on")
r = AGXS.get(V + f"/tasks/{T1}")
check(r.status_code == 404, "v1: another organisation's agent cannot read the task")
# batch
r = Bo.post(B + "/api/tasks/batch", json={"ids": [T1, T2], "action": "patch", "data": {"points": 13}})
check(r.ok and {x[0] for x in dbx("SELECT points FROM tasks WHERE id IN (?,?)", (T1, T2))} == {13}, f"batch: points for both ({r.text[:100]})")
# a task template keeps them
r = Bo.post(B + "/api/templates", json={"task_id": T2})
check(r.ok, f"template from a task ({r.status_code})")
TPL = r.json().get("id")
r = Bo.post(B + f"/api/templates/{TPL}/apply", json={"list_id": P})
new = dbx("SELECT points FROM tasks WHERE list_id=? AND title='Signup page' AND id<>? AND deleted_at IS NULL", (P, T2))
check(r.ok and new and new[0][0] == 13, f"the template's task keeps its points ({new})")

# ---- velocity
check(Bo.get(B + f"/api/lists/{P}/velocity").json() == {"sprints": [], "average": None, "points_on": True}, "no closed sprint: empty, average null")


def sprint(num, state, review=None):
    dbx("INSERT INTO sprints(list_id,num,name,start,end_day,state,review,closed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (P, num, "", f"2026-09-{num:02d}", f"2026-09-{num + 6:02d}", state, json.dumps(review) if review else None,
         "2026-09-30T10:00:00+00:00" if state == "closed" else None, "2026-09-01T08:00:00+00:00"), write=True)
    return dbx("SELECT id FROM sprints WHERE list_id=? AND num=?", (P, num))[0][0]


S1 = sprint(1, "closed", {"done": [], "moved": [], "added": [], "count_done": 4, "count_total": 6, "points_done": 21,
                          "points_total": 30, "points_added": 0, "target": "next", "next_id": None})
S2 = sprint(2, "closed")  # no close-out: counted from its tasks
S3 = sprint(3, "active")
for title, pts, status in (("Done A", 5, 2), ("Done B", 8, 2), ("Done C", None, 2), ("Open D", 3, 0), ("Wont E", 2, 3)):
    tid = task(Bo, P, title)
    dbx("UPDATE tasks SET sprint_id=?, points=?, status=? WHERE id=?", (S2, pts, status, tid), write=True)
ms = task(Bo, P, "Release 1")
dbx("UPDATE tasks SET sprint_id=?, points=5, status=2, ms=1 WHERE id=?", (S2, ms), write=True)
t3 = task(Bo, P, "Active work")
dbx("UPDATE tasks SET sprint_id=?, points=13, status=2 WHERE id=?", (S3, t3), write=True)
r = Bo.get(B + f"/api/lists/{P}/velocity")
j = r.json()
sp = j.get("sprints") or []
check(r.ok and [s["id"] for s in sp] == [S1, S2], f"velocity: the closed sprints, oldest first ({sp})")
check(sp and sp[0]["points"] == 21 and sp[0]["count"] == 4, f"velocity: the close-out's numbers ({sp[:1]})")
check(len(sp) > 1 and sp[1]["points"] == 13 and sp[1]["count"] == 3, f"velocity: counted from completed tasks without milestones ({sp[1:]})")
check(j.get("average") == 17.0, f"velocity: average ({j.get('average')})")
for n in range(4, 10):
    sprint(n, "closed", {"points_done": n, "count_done": 1})
sp = Bo.get(B + f"/api/lists/{P}/velocity").json()["sprints"]
check([s["num"] for s in sp] == [4, 5, 6, 7, 8, 9], f"velocity: at most the last 6 ({[s['num'] for s in sp]})")
check(Ca.get(B + f"/api/lists/{P}/velocity").ok, "velocity: a member reads it")
check(Da.get(B + f"/api/lists/{P}/velocity").status_code == 404, "velocity: a stranger 404")
r = AGS.get(V + f"/lists/{P}/velocity")
check(r.ok and len(r.json()["sprints"]) == 6, f"velocity: the shared agent over API v1 ({r.status_code})")
check(AGXS.get(V + f"/lists/{P}/velocity").status_code == 404, "velocity: another organisation's agent 404")
r = Da.post(B + "/api/lists", json={"name": "Dave private"})
check(AGS.get(V + f"/lists/{r.json()['id']}/velocity").status_code == 404, "velocity: a list not shared with the agent 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
