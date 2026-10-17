#!/usr/bin/env python3
"""2.78.0 API tests (#1881, "Duplicate list"): invented names only.
 - POST /api/lists/{id}/duplicate: a new list of the caller named "<list> (copy)" (or the name sent) with the sections, the
   open tasks with their exact dates (an overdue one stays overdue), subtasks, tags, field values, dependencies, the notepads
   (new ids, rewritten in page_layout / page_style) and the list's colour; no members, no assignees; the original unchanged
 - done = true: the completed and won't-do tasks come along with their state (a done subtask too); without it neither
 - the copy stays in the original's organisation and in the caller's folder of the list; an editor's copy is the editor's
 - participants get 403, strangers 404 (tenant-matrix: template)
 - /api/v1/lists/{id}/duplicate (structure): 201 {list_id}, unknown fields / a non-boolean done = 400, a stranger's token 404
usage: p278_dup_api_test.py <datadir>      (a fresh container; P278_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def D(n):
    return (date.today() + timedelta(days=n)).isoformat()


if not os.environ.get("P278_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "fields", "deps"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
for s_ in (A, Bo, Ca, Da):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,fields,deps", "tour": "done"})
ORG = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u in ("alice", "bob", "carol"):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (ORG, ids[u]))

# ============================================================ the original: a project with everything a copy carries
P = A.post(B + "/api/lists", json={"name": "Harbour site", "kind": "project", "folder": "Clients/North", "color": "#3366cc"}).json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P))
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["carol"], "role": "participant"})
S1 = A.post(B + "/api/sections", json={"list_id": P, "name": "Planning"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": P, "name": "Build"}).json()["id"]
F = A.post(B + f"/api/lists/{P}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
T_late = A.post(B + "/api/tasks", json={"title": "Permit", "list_id": P, "section_id": S1, "due": D(-3), "priority": 5,
                                        "tags": ["legal"], "assignee_id": ids["bob"], "fields": {str(F): "1200"}}).json()["id"]
T_next = A.post(B + "/api/tasks", json={"title": "Foundation", "list_id": P, "section_id": S2, "due": D(10), "start": D(7)}).json()["id"]
T_sub_open = A.post(B + "/api/tasks", json={"title": "Order concrete", "list_id": P, "parent_id": T_next}).json()["id"]
T_sub_done = A.post(B + "/api/tasks", json={"title": "Soil test", "list_id": P, "parent_id": T_next}).json()["id"]
T_done = A.post(B + "/api/tasks", json={"title": "Site visit", "list_id": P, "section_id": S1}).json()["id"]
T_wont = A.post(B + "/api/tasks", json={"title": "Old idea", "list_id": P}).json()["id"]
check(A.post(B + f"/api/tasks/{T_sub_done}/complete", json={}).ok, "subtask done")
check(A.post(B + f"/api/tasks/{T_done}/complete", json={}).ok, "task done")
check(A.post(B + f"/api/tasks/{T_wont}/complete", json={"status": -1}).ok, "task won't do")
check(A.post(B + "/api/deps", json={"task_id": T_next, "blocker_id": T_late}).ok, "dependency")
N1 = A.post(B + f"/api/lists/{P}/notepads", json={"title": "Gate codes", "body": "north gate"}).json()["id"]
lay = {"order": ["kpis", "desc", f"np{N1}"], "half": [f"np{N1}"]}
check(A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps(lay), "scope": "standard"}).ok, "standard arrangement")
check(A.put(B + f"/api/lists/{P}/page-style", json={"block": f"np{N1}", "color": "yellow"}).ok, "notepad colour")
before = dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (P,))[0][0]


def tasks_of(lid):
    return {r[0]: r for r in dbx("""SELECT t.title, t.status, t.due, t.start, t.priority, s.name, t.parent_id, t.id, t.assignee_id,
                                           t.completed_at FROM tasks t LEFT JOIN sections s ON s.id=t.section_id
                                    WHERE t.list_id=? AND t.deleted_at IS NULL""", (lid,))}


# ============================================================ 1. the default copy: open tasks only
r = A.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.ok, f"duplicate {r.status_code} {r.text[:200]}")
C1 = r.json().get("list_id")
row = dbx("SELECT name, owner_id, folder, org_id, kind, color, page_layout, page_style FROM lists WHERE id=?", (C1,))[0]
check(row[0] == "Harbour site (copy)", f"default name {row[0]}")
check(row[1] == ids["alice"] and row[2] == "Clients/North" and row[3] == ORG, f"mine, same folder and organisation {row[1:4]}")
check(row[4] == "project" and row[5] == "#3366cc", f"kind and colour {row[4:6]}")
check([x[0] for x in dbx("SELECT name FROM sections WHERE list_id=? ORDER BY sort, id", (C1,))] == ["Planning", "Build"], "sections")
ts = tasks_of(C1)
check(set(ts) == {"Permit", "Foundation", "Order concrete"}, f"open tasks only (no done subtask) {sorted(ts)}")
check(ts["Permit"][2] == D(-3) and ts["Permit"][1] == 0 and ts["Permit"][4] == 5 and ts["Permit"][5] == "Planning",
      f"overdue date kept exactly {ts['Permit'][1:6]}")
check(ts["Foundation"][2] == D(10) and ts["Foundation"][3] == D(7) and ts["Foundation"][5] == "Build", f"dates + section {ts['Foundation'][1:6]}")
check(ts["Order concrete"][6] == ts["Foundation"][7], "subtask under its parent")
check(ts["Permit"][8] is None, "no assignee in the copy")
check(dbx("SELECT tag FROM task_tags WHERE task_id=?", (ts["Permit"][7],)) and
      dbx("SELECT tag FROM task_tags WHERE task_id=?", (ts["Permit"][7],))[0][0] == "legal", "tags")
fv = dbx("""SELECT v.value, f.name FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE v.task_id=?""", (ts["Permit"][7],))
check(fv and fv[0][1] == "Budget" and float(fv[0][0]) == 1200 and dbx("SELECT list_id FROM list_fields WHERE name='Budget' AND list_id=?", (C1,)),
      f"field + value on the copy's own field {fv}")
check(dbx("SELECT 1 FROM task_deps WHERE task_id=? AND blocker_id=?", (ts["Foundation"][7], ts["Permit"][7])), "dependency between the copies")
check(dbx("SELECT COUNT(*) FROM list_members WHERE list_id=?", (C1,))[0][0] == 0, "no members copied")
pads = dbx("SELECT id, title, body FROM list_notepads WHERE list_id=?", (C1,))
check(len(pads) == 1 and pads[0][1] == "Gate codes" and pads[0][0] != N1, f"notepad copied with a new id {pads}")
pl, ps = json.loads(row[6] or "{}"), json.loads(row[7] or "{}")
check(pads and pl.get("order") == ["kpis", "desc", f"np{pads[0][0]}"] and ps == {f"np{pads[0][0]}": "yellow"}, f"page arrangement + colour rewritten {pl} {ps}")
check(dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (P,))[0][0] == before and
      dbx("SELECT assignee_id FROM tasks WHERE id=?", (T_late,))[0][0] == ids["bob"], "the original is unchanged")
check(any(x["id"] == C1 for x in A.get(B + "/api/state").json()["lists"]), "the copy is in my lists")
check(not any(x["id"] == C1 for x in Bo.get(B + "/api/state").json()["lists"]), "a member of the original does not see the copy")

# ============================================================ 2. with the completed tasks
r = A.post(B + f"/api/lists/{P}/duplicate", json={"name": "  Harbour archive ", "done": True})
check(r.ok, f"duplicate with done {r.status_code} {r.text[:200]}")
C2 = r.json().get("list_id")
check(dbx("SELECT name FROM lists WHERE id=?", (C2,))[0][0] == "Harbour archive", "the name sent (trimmed)")
ts = tasks_of(C2)
check(set(ts) == {"Permit", "Foundation", "Order concrete", "Soil test", "Site visit", "Old idea"}, f"all tasks {sorted(ts)}")
check(ts["Site visit"][1] == 2 and ts["Site visit"][9], f"done stays done {ts['Site visit'][1]} {ts['Site visit'][9]}")
check(ts["Old idea"][1] == -1, f"won't do stays won't do {ts['Old idea'][1]}")
check(ts["Soil test"][1] == 2 and ts["Soil test"][6] == ts["Foundation"][7], "done subtask under its parent, done")
check(ts["Permit"][1] == 0, "open stays open")

# ============================================================ 3. who may
r = Bo.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.status_code == 200, f"an editor may {r.status_code} {r.text[:200]}")
C3 = r.json().get("list_id")
check(dbx("SELECT owner_id FROM lists WHERE id=?", (C3,))[0][0] == ids["bob"], "the editor's copy is the editor's")
check(dbx("SELECT COUNT(*) FROM list_members WHERE list_id=?", (C3,))[0][0] == 0, "nobody else in the editor's copy")
r = Ca.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.status_code == 403, f"a participant may not {r.status_code}")
r = Da.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.status_code == 404, f"a stranger gets 404 {r.status_code}")
r = Da.post(B + "/api/lists/999999/duplicate", json={})
check(r.status_code == 404, f"unknown list 404 {r.status_code}")
# a private list stays private
Q = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
dbx("UPDATE lists SET org_id=NULL WHERE id=?", (Q,))
A.post(B + "/api/tasks", json={"title": "Milk", "list_id": Q})
r = A.post(B + f"/api/lists/{Q}/duplicate", json={})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),))[0][0] is None, "a private list's copy is private")
# N35 (#476): a list locked in the browser is never duplicated into an unlocked copy
dbx("UPDATE lists SET e2e='on' WHERE id=?", (Q,))
n0 = dbx("SELECT COUNT(*) FROM lists")[0][0]
r = A.post(B + f"/api/lists/{Q}/duplicate", json={})
check(r.status_code == 409 and r.json().get("code") == "list_e2e", f"locked list: 409 list_e2e {r.status_code} {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM lists")[0][0] == n0, "locked list: no copy was made")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (Q,))

# ============================================================ 4. REST API
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "structure"], "expires_days": 30}).json().get("token")
V1 = {"Authorization": "Bearer " + tok}
r = requests.post(B + f"/api/v1/lists/{P}/duplicate", json={"name": "Via API", "done": False}, headers=V1)
check(r.status_code == 201 and r.json().get("list_id"), f"v1 201 {r.status_code} {r.text[:200]}")
if r.status_code == 201:
    check(dbx("SELECT name FROM lists WHERE id=?", (r.json()["list_id"],))[0][0] == "Via API", "v1 name")
r = requests.post(B + f"/api/v1/lists/{P}/duplicate", json={"done": "yes"}, headers=V1)
check(r.status_code == 400, f"v1 done must be a boolean {r.status_code}")
r = requests.post(B + f"/api/v1/lists/{P}/duplicate", json={"members": True}, headers=V1)
check(r.status_code == 400, f"v1 unknown field {r.status_code}")
tok_r = A.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read"], "expires_days": 30}).json().get("token")
r = requests.post(B + f"/api/v1/lists/{P}/duplicate", json={}, headers={"Authorization": "Bearer " + tok_r})
check(r.status_code == 403, f"v1 needs structure {r.status_code}")
tok_d = Da.post(B + "/api/me/tokens", json={"name": "d", "scopes": ["read", "structure"], "expires_days": 30}).json().get("token")
r = requests.post(B + f"/api/v1/lists/{P}/duplicate", json={}, headers={"Authorization": "Bearer " + tok_d})
check(r.status_code == 404, f"v1 stranger 404 {r.status_code}")

print(f"p278_dup_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
