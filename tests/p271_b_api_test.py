#!/usr/bin/env python3
"""2.71.0 API tests (part B): #1459 a task in several lists without a copy (task_links).
 - linking (POST /api/tasks/{id}/links): write on the task AND on the target list, same workspace only (organisation <->
   another organisation / private <-> organisation refused), no health list, no archived list, not its own list, top-level
   tasks only, at most 10 further lists; again = only the place changes
 - rights stay with the task's own list: a reader of only the further list gets the task nowhere (state, delta, search,
   GET by id, timeline, calendar feed, public link, export, agent API); a participant of the further list neither
 - "also" names only lists the viewer sees (people, agents, a token limited to lists); the history names the list only
   for who sees it
 - the place in the further list (PATCH .../links/{list_id}): a section of THAT list, the task's own section untouched
 - removing (DELETE): by a writer of the further list (also without seeing the task: the same answer) or of the task; the
   task stays; deleting the further list keeps the task
 - the database trigger: moving the task into another workspace / into the further list / under a parent, or moving the
   further list into another workspace drops the link
 - counted once: state, export
 - agents (API v1): link / unlink with tasks:write, read-only 403, OpenAPI with x-kalmido-scope
 - a freelancer without organisation links between private lists
tenant-matrix: tasklink
usage: p271_b_api_test.py <datadir>"""
import os
import re
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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        r = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
        if write:
            c.commit()
        return r
    finally:
        c.close()


def links(tid):
    return sorted(r[0] for r in dbx("SELECT list_id FROM task_links WHERE task_id=?", (tid,)))


def state(s):
    return s.get(B + "/api/state").json()


def task_in(s, tid):
    return next((t for t in state(s)["tasks"] if t["id"] == tid), None)


def also_ids(t):
    return sorted(a["list_id"] for a in (t or {}).get("also") or [])


def link(s, tid, lid, **kw):
    return s.post(B + f"/api/tasks/{tid}/links", json={"list_id": lid, **kw})


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = state(A)["me"]["workspaces"][0]["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta"}).json()["id"]
uid = {}
for u, orgs in (("bob", [ORG, BETA]), ("carol", [ORG]), ("dave", [ORG]), ("gina", [ORG]), ("frank", [BETA]), ("eve", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    check(r.ok, f"setup: user {u} " + r.text[:120])
    uid[u] = r.json()["id"]
check(dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (BETA, uid["bob"])), "setup: bob is also in Beta")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (uid["eve"],)), "setup: eve has no organisation")
Bo, Ca, Da, Gi, Fr, Ev = (sess(u) for u in ("bob", "carol", "dave", "gina", "frank", "eve"))
for s in (Bo, Ca, Da, Gi, Fr, Ev):
    s.patch(B + "/api/settings", json={"lang": "en"})


def mk(s, name, org):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    check(r.ok, f"setup: list {name} " + r.text[:120])
    return r.json()["id"]


# bob: O1 (origin, carol edits), O2 (further list, dave edits, gina participant), O3 (carol may only view), P1 / P2 private,
# BL a list of the other organisation Beta
O1, O2, O3 = mk(Bo, "Sales", ORG), mk(Bo, "Marketing", ORG), mk(Bo, "Viewed", ORG)
P1, P2 = mk(Bo, "Mine one", None), mk(Bo, "Mine two", None)
BL = mk(Bo, "Beta board", BETA)
check(Bo.put(B + f"/api/lists/{O1}/members", json={"user_id": uid["carol"], "role": "edit"}).ok, "setup: carol edits O1")
check(Bo.put(B + f"/api/lists/{O2}/members", json={"user_id": uid["dave"], "role": "edit"}).ok, "setup: dave edits O2")
check(Bo.put(B + f"/api/lists/{O2}/members", json={"user_id": uid["gina"], "role": "participant"}).ok, "setup: gina participant in O2")
check(Bo.put(B + f"/api/lists/{O3}/members", json={"user_id": uid["carol"], "role": "view"}).ok, "setup: carol views O3")
SEC1 = Bo.post(B + "/api/sections", json={"list_id": O1, "name": "Own column"}).json()["id"]
SEC2 = Bo.post(B + "/api/sections", json={"list_id": O2, "name": "Doing"}).json()["id"]
TITLE = "Quarterly offer zq7"
T = Bo.post(B + "/api/tasks", json={"title": TITLE, "list_id": O1, "section_id": SEC1, "due": "2030-05-02"}).json()["id"]
SUB = Bo.post(B + "/api/tasks", json={"title": "Step zq7", "list_id": O1, "parent_id": T}).json()["id"]
Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "Comment zq7"})

# ================================================================== refusals
r = link(Bo, T, BL)
check(r.status_code == 400, "#1459: a list of another organisation is refused " + str(r.status_code))
r = link(Bo, T, P1)
check(r.status_code == 400, "#1459: organisation -> private refused " + str(r.status_code))
TP = Bo.post(B + "/api/tasks", json={"title": "Private zq7", "list_id": P1}).json()["id"]
check(link(Bo, TP, O2).status_code == 400, "#1459: private -> organisation refused")
check(link(Bo, T, O1).status_code == 400, "#1459: its own list refused")
check(link(Bo, SUB, O2).status_code == 400, "#1459: a subtask is not linked on its own")
check(link(Da, T, O2).status_code == 404, "#1459: dave (cannot see the task) cannot link it: 404")
check(link(Ca, T, O2).status_code == 404, "#1459: carol (cannot see the target) cannot link into it: 404")
check(link(Ca, T, O3).status_code == 403, "#1459: carol (view only on the target) 403")
check(link(Fr, T, BL).status_code == 404, "#1459: frank of the other organisation: the task does not exist for him")
check(Bo.post(B + f"/api/tasks/{T}/links", json={"list_id": "x"}).status_code == 400, "#1459: list_id must be a number")
HL = mk(Bo, "Health like", ORG)
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,), write=True)
check(link(Bo, T, HL).status_code == 400, "#1459: a health list is refused")
AR = mk(Bo, "Archived", ORG)
dbx("UPDATE lists SET archived=1 WHERE id=?", (AR,), write=True)
check(link(Bo, T, AR).status_code == 400, "#1459: an archived list is refused")
check(links(T) == [], "#1459: nothing linked by the refusals")

# ================================================================== linking
r = link(Bo, T, O2)
check(r.ok and also_ids(r.json()) == [O2], "#1459: bob links his task into O2, the answer carries also " + r.text[:200])
check(links(T) == [O2], "#1459: one row in task_links")
st = state(Bo)
check(sum(1 for t in st["tasks"] if t["id"] == T) == 1, "#1459: counted once in the state (one object)")
bt = next(t for t in st["tasks"] if t["id"] == T)
check(bt["list_id"] == O1 and bt["section_id"] == SEC1 and also_ids(bt) == [O2], "#1459: its own list and section unchanged")
check(dbx("SELECT org_id FROM task_links WHERE task_id=?", (T,))[0][0] == ORG, "#1459: the link carries the organisation (row-level security)")
r = link(Bo, T, O2, section_id=SEC2)
check(r.ok and r.json()["also"][0]["section_id"] == SEC2 and links(T) == [O2], "#1459: again = only the place changes")
check(link(Bo, T, O2, section_id=SEC1).status_code == 400, "#1459: a section of another list is refused")

# ================================================================== a reader of only the further list: nothing
check(task_in(Da, T) is None, "#1459: dave (only O2) does not get the task in his state")
check(Da.get(B + f"/api/tasks/{T}").status_code == 404, "#1459: dave GET by id 404")
check(Da.get(B + f"/api/tasks/{T}/timeline").status_code == 404, "#1459: dave timeline 404")
r = Da.get(B + "/api/tasks", params={"scope": "search", "q": "zq7"})
check(TITLE not in r.text, "#1459: dave's search does not find it")
check(TITLE not in Da.get(B + "/api/export.json").text and "Comment zq7" not in Da.get(B + "/api/export.json").text, "#1459: dave's export")
check(task_in(Gi, T) is None, "#1459: gina (participant of O2) does not get it")
Da.post(B + "/api/ical", json={"action": "create"})
feed = re.sub(r"^https?://[^/]+", "", Da.get(B + "/api/ical").json().get("url") or "")
if feed:
    check(TITLE not in requests.get(B + feed).text, "#1459: dave's calendar feed does not have it")
v0 = state(Da)["v"]
Bo.patch(B + f"/api/tasks/{T}", json={"title": TITLE + " changed"})
r = Da.get(B + f"/api/state/delta?since={v0}").json()
check(not any(t["id"] == T for t in r.get("tasks", [])) and T not in r.get("gone", []), "#1459: dave's delta neither has nor names it")
Bo.patch(B + f"/api/tasks/{T}", json={"title": TITLE})
pl = Bo.put(B + f"/api/lists/{O2}/public-link", json={"mode": "view"})
if pl.ok and pl.json().get("token"):
    check(TITLE not in requests.get(B + "/s/" + pl.json()["token"]).text, "#1459: the public link of O2 does not show it")
# carol sees the origin, not O2: the task without "also"; the history entry without the list's name
ct = task_in(Ca, T)
check(ct is not None and "also" not in ct, "#1459: carol (origin only) gets the task, also absent (O2 is not hers to know)")
acts = [a for a in Ca.get(B + f"/api/tasks/{T}/timeline").json().get("activity", []) if a["kind"] == "ml_add"]
check(acts and acts[-1]["data"] == {}, "#1459: carol's history: neutral, no name / id of O2 " + str(acts[-1:]))
acts = [a for a in Bo.get(B + f"/api/tasks/{T}/timeline").json().get("activity", []) if a["kind"] == "ml_add"]
check(acts and acts[-1]["data"].get("name") == "Marketing", "#1459: bob's history names O2")

# ================================================================== the place in the further list
r = Bo.patch(B + f"/api/tasks/{T}/links/{O2}", json={"section_id": None, "sort": 7.5})
check(r.ok and r.json()["also"][0]["section_id"] is None and r.json()["also"][0]["sort"] == 7.5, "#1459: place in O2 changed")
check(r.json()["section_id"] == SEC1, "#1459: the task's own section untouched")
check(Da.patch(B + f"/api/tasks/{T}/links/{O2}", json={"section_id": SEC2}).status_code == 404, "#1459: dave cannot place a task he cannot see")
check(Ca.patch(B + f"/api/tasks/{T}/links/{O2}", json={"section_id": SEC2}).status_code == 404, "#1459: carol (no O2) 404")

# ================================================================== removing
r = Da.delete(B + f"/api/tasks/{T}/links/{O2}")
check(r.ok and r.json() == {"ok": True} and links(T) == [], "#1459: dave (writer of O2) removes it, the answer tells nothing about the task")
r = Da.delete(B + f"/api/tasks/{T}/links/{O2}")
check(r.ok and r.json() == {"ok": True}, "#1459: dave: the same answer without a link")
check(Ca.delete(B + f"/api/tasks/{T}/links/{O3}").status_code in (200, 403), "#1459: carol (task writer) may remove")
check(Fr.delete(B + f"/api/tasks/{T}/links/{O2}").status_code == 404, "#1459: frank (other organisation) 404")
check(dbx("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (T,)), "#1459: the task stays")
check(link(Bo, T, O2).ok and links(T) == [O2], "#1459: linked again")

# ================================================================== the trigger: the boundary on every move
Bo.patch(B + f"/api/tasks/{T}", json={"list_id": O2})
check(links(T) == [], "#1459: moved into the further list: the link to its own list is gone")
Bo.patch(B + f"/api/tasks/{T}", json={"list_id": O1})
link(Bo, T, O2)
Bo.patch(B + f"/api/tasks/{T}", json={"list_id": P1})
check(links(T) == [], "#1459: moved into a private list: the organisation link is gone")
Bo.patch(B + f"/api/tasks/{T}", json={"list_id": O1})
link(Bo, T, O2)
T2 = Bo.post(B + "/api/tasks", json={"title": "Parent zq7", "list_id": O1}).json()["id"]
Bo.patch(B + f"/api/tasks/{T}", json={"parent_id": T2})
check(links(T) == [], "#1459: now a subtask: the link is gone")
Bo.patch(B + f"/api/tasks/{T}", json={"parent_id": None})
link(Bo, T, O2)
dbx("UPDATE lists SET org_id=NULL WHERE id=?", (O2,), write=True)
check(links(T) == [], "#1459: the further list moved out of the organisation: the link is gone")
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, O2), write=True)
check(link(Bo, T, O2).ok, "#1459: linked again after the list came back")

# ================================================================== trash, deleting the further list, the limit
Bo.delete(B + f"/api/tasks/{T}")
check(links(T) == [O2] and task_in(Bo, T) is None, "#1459: in the trash: the link stays (restore), the views do not show it")
Bo.post(B + f"/api/tasks/{T}/restore")
check(also_ids(task_in(Bo, T)) == [O2], "#1459: restored with its further list")
OX = mk(Bo, "Short lived", ORG)
link(Bo, T, OX)
check(Bo.patch(B + f"/api/lists/{OX}", json={"archived": True}).ok, "setup: the further list archived (delete needs it)")
r = Bo.delete(B + f"/api/lists/{OX}")
check(r.ok, "setup: the further list deleted " + r.text[:120])
check(links(T) == [O2] and task_in(Bo, T) is not None, "#1459: deleting the further list keeps the task")
many = [mk(Bo, f"Extra {i}", ORG) for i in range(10)]
codes = [link(Bo, T, x).status_code for x in many]
check(codes[:9] == [200] * 9 and codes[9] == 400, "#1459: at most 10 further lists " + str(codes))
for x in many:
    Bo.delete(B + f"/api/tasks/{T}/links/{x}")
check(links(T) == [O2], "#1459: back to one further list")
ex = Bo.get(B + "/api/export.json").json()
check(sum(1 for t in ex.get("tasks", []) if t.get("id") == T) == 1, "#1459: bob's export has it once")

# ================================================================== agents (API v1)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "linker", "display_name": "Linker"})
check(r.ok, "setup: agent " + r.text[:120])
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "reader", "display_name": "Reader"})
RG, RGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("UPDATE agents SET org_id=? WHERE user_id IN (?,?)", (ORG, AG, RG), write=True)
Bo.put(B + f"/api/lists/{O2}/members", json={"user_id": AG, "role": "edit"})
check(requests.get(V + f"/tasks/{T}", headers=AGH).status_code == 404, "#1459: an agent of only O2 does not get the task")
r = requests.get(V + "/tasks", headers=AGH, params={"list_id": O2})
check(TITLE not in r.text, "#1459: nor in O2's task list")
check(requests.post(V + f"/tasks/{T}/links", headers=AGH, json={"list_id": O3}).status_code == 404, "#1459: nor can it link it")
Bo.delete(B + f"/api/lists/{O2}/members/{AG}")
Bo.put(B + f"/api/lists/{O1}/members", json={"user_id": AG, "role": "edit"})
j = requests.get(V + f"/tasks/{T}", headers=AGH).json()
check(j.get("id") == T and "also" not in j, "#1459: an agent of only O1: the task without also (O2 not shared with it)")
Bo.put(B + f"/api/lists/{O3}/members", json={"user_id": AG, "role": "edit"})
r = requests.post(V + f"/tasks/{T}/links", headers=AGH, json={"list_id": O3})
check(r.ok and also_ids(r.json()) == [O3], "#1459: the agent links into O3 (both shared with it); also only O3 " + r.text[:200])
r = requests.delete(V + f"/tasks/{T}/links/{O3}", headers=AGH)
check(r.ok and links(T) == [O2], "#1459: the agent removes it again")
Bo.put(B + f"/api/lists/{O1}/members", json={"user_id": RG, "role": "view"})
check(requests.post(V + f"/tasks/{T}/links", headers=RGH, json={"list_id": O3}).status_code == 403, "#1459: a read-only token 403")
spec = requests.get(V + "/openapi.json").json()["paths"]
check(spec.get("/tasks/{id}/links", {}).get("post", {}).get("x-kalmido-scope") == "tasks:write"
      and spec.get("/tasks/{id}/links/{list_id}", {}).get("delete", {}).get("x-kalmido-scope") == "tasks:write", "#1459: OpenAPI with scopes")

# ================================================================== a freelancer without organisation
E1 = Ev.post(B + "/api/lists", json={"name": "Client work"}).json()["id"]
E2 = Ev.post(B + "/api/lists", json={"name": "This week"}).json()["id"]
ET = Ev.post(B + "/api/tasks", json={"title": "Invoice zq7", "list_id": E1}).json()["id"]
r = link(Ev, ET, E2)
check(r.ok and also_ids(r.json()) == [E2], "#1459: a freelancer links between private lists " + r.text[:160])
check(link(Ev, ET, P2).status_code == 404, "#1459: never into another person's private list")
check(task_in(Bo, ET) is None, "#1459: bob does not see eve's task")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
