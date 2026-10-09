#!/usr/bin/env python3
"""2.36.0 API tests, part B: the lock of a task (#1118), own container (start.sh).
 - new column tasks.locked (default 0): existing / human tasks are open; tasks created with an agent token start locked
   (also subtasks), locked: false creates an open one; a personal access token creates open tasks
 - the app (session) cannot change title, notes, date, priority, list, tags, list tags, repeat or assignee of a locked
   task (400 with a clear message; nothing changed), also not through the multi-select batch or a drag (reorder);
   free: comments, ticking a checkbox in the notes, completing / reopening, subtasks, pin, sort order, unchanged values
 - unlocking (also together with a change) by whoever may change the task; a view-only member cannot; locking and
   unlocking show in the history
 - the agent API is not bound by the lock: it changes locked tasks and sets / clears locked; bad values 400
 - OpenAPI documents locked; the rollback image 2.35 writes tasks without the column (default 0); a backup keeps the lock
usage: p2360_b_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, t=8.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
W2 = A.post(B + "/api/lists", json={"name": "Other", "org_id": ORG}).json()["id"]
for lid in (W, W2):
    assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": CAROL, "role": "view"}).ok
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"}).ok

# ================================================================== schema + defaults
cols = {r[1]: r for r in dbx("PRAGMA table_info(tasks)")}
check("locked" in cols and cols["locked"][3] == 1 and str(cols["locked"][4]) == "0", "tasks.locked INTEGER NOT NULL DEFAULT 0 " + str(cols.get("locked")))
r = A.post(B + "/api/tasks", json={"title": "Mine", "list_id": W})
check(r.ok and r.json().get("locked") == 0, "a person's new task is open " + r.text[:120])
HT = r.json()["id"]
r = requests.post(V + "/tasks", headers=CLH, json={"title": "Agent plan", "list_id": W, "notes": "Intro\n- [ ] one\n- [ ] two", "priority": "medium"})
check(r.status_code == 201 and r.json().get("locked") is True, "a task created with the agent token starts locked " + r.text[:160])
T = r.json()["id"]
check(dbx("SELECT locked FROM tasks WHERE id=?", (T,))[0][0] == 1, "... stored as 1")
r = requests.post(V + "/tasks", headers=CLH, json={"title": "Agent open", "list_id": W, "locked": False})
check(r.status_code == 201 and r.json().get("locked") is False, "locked: false creates an open one " + r.text[:120])
r = requests.post(V + f"/tasks/{T}/subtasks", headers=CLH, json={"title": "Agent sub"})
check(r.status_code == 201 and r.json().get("locked") is True, "an agent's subtask starts locked too")
r = requests.post(V + "/tasks", headers=CLH, json={"title": "x", "list_id": W, "locked": "yes"})
check(r.status_code == 400, "locked must be a boolean -> 400 " + str(r.status_code))
pat = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "tasks:write"]}).json()["token"]
r = requests.post(V + "/tasks", headers={"Authorization": "Bearer " + pat}, json={"title": "Via my token", "list_id": W})
check(r.status_code == 201 and r.json().get("locked") is False, "a personal access token creates open tasks " + r.text[:120])
check(requests.get(V + f"/tasks/{T}", headers=CLH).json().get("locked") is True, "GET /api/v1/tasks/{id} carries locked")
check(dbx("SELECT COUNT(*) FROM tasks WHERE locked=1")[0][0] == 2, "only the two agent tasks are locked")

# ================================================================== the app: locked fields
before = dbx("SELECT title, content, due, priority, list_id, repeat, assignee_id FROM tasks WHERE id=?", (T,))[0]
for body, what in (({"title": "Renamed"}, "title"), ({"content": "Other text"}, "notes"), ({"due": "2030-01-02"}, "date"),
                   ({"due_time": "09:00"}, "time"), ({"priority": 5}, "priority"), ({"list_id": W2}, "list"),
                   ({"repeat": "FREQ=WEEKLY"}, "repeat"), ({"assignee_id": BOB}, "assignee"), ({"tags": ["x"]}, "tags"),
                   ({"add_tags": ["y"]}, "add_tags"), ({"ltags": ["urgent"]}, "list tags"),
                   ({"content": "Intro\n- [x] one\n- [ ] two\nmore"}, "a tick plus new text")):
    r = Bo.patch(B + f"/api/tasks/{T}", json=body)
    check(r.status_code == 400 and "locked" in r.text.lower(), f"locked: the app cannot change the {what} -> 400 " + f"{r.status_code} {r.text[:100]}")
check(dbx("SELECT title, content, due, priority, list_id, repeat, assignee_id FROM tasks WHERE id=?", (T,))[0] == before, "nothing changed")
check(not dbx("SELECT 1 FROM task_tags WHERE task_id=?", (T,)), "no tag stored")
# free while locked
r = Bo.patch(B + f"/api/tasks/{T}", json={"content": "Intro\n- [x] one\n- [ ] two"})
check(r.ok and "- [x] one" in r.json()["content"], "a checkbox tick in the notes is allowed " + r.text[:120])
r = Bo.patch(B + f"/api/tasks/{T}", json={"title": "Agent plan", "priority": 3, "pinned": 1, "sort": 5})
check(r.ok, "unchanged values + pin + sort order are allowed " + r.text[:120])
check(Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "Looks good"}).ok, "a comment is allowed")
r = Bo.post(B + "/api/tasks", json={"title": "My subtask", "parent_id": T})
check(r.ok and r.json().get("locked") == 0, "a person's subtask of a locked task is allowed (and open)")
check(Bo.post(B + f"/api/tasks/{T}/complete", json={}).ok and dbx("SELECT status FROM tasks WHERE id=?", (T,))[0][0] == 2, "completing is allowed")
check(Bo.post(B + f"/api/tasks/{T}/reopen", json={}).ok and dbx("SELECT status FROM tasks WHERE id=?", (T,))[0][0] == 0, "reopening is allowed")
# multi-select and drag
r = Bo.post(B + "/api/tasks/batch", json={"ids": [T, HT], "action": "patch", "data": {"due": "2030-02-02"}})
check(r.ok and any("locked" in e.lower() for e in r.json().get("errors", [])), "multi-select: the locked task is reported " + r.text[:160])
check(dbx("SELECT due FROM tasks WHERE id=?", (T,))[0][0] is None and dbx("SELECT due FROM tasks WHERE id=?", (HT,))[0][0] == "2030-02-02",
      "multi-select: the open task changed, the locked one did not")
r = Bo.post(B + "/api/tasks/batch", json={"ids": [T], "action": "patch_each", "data": {"items": {str(T): {"title": "Undo me"}}}})
check(r.ok and r.json().get("errors"), "undo / redo (patch_each) respects the lock too")
r = Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "list_id": W2, "sort": 1}]})
check(r.status_code == 400 and dbx("SELECT list_id FROM tasks WHERE id=?", (T,))[0][0] == W, "drag into another list: 400, not moved " + r.text[:100])
r = Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "due": "2030-03-03", "sort": 1}]})
check(r.status_code == 400, "drag onto another day: 400")
check(Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "sort": -10}]}).ok, "drag within the list (sort only) is allowed")
# Skip this occurrence moves the date of a recurring task: not while it is locked (review 2.36.0)
RT = Bo.post(B + "/api/tasks", json={"title": "Weekly locked", "list_id": W, "due": "2030-03-04", "repeat": "FREQ=WEEKLY"}).json()["id"]
check(Bo.patch(B + f"/api/tasks/{RT}", json={"locked": True}).ok, "lock a recurring task")
r = Bo.post(B + f"/api/tasks/{RT}/skip", json={})
check(r.status_code == 400 and dbx("SELECT due FROM tasks WHERE id=?", (RT,))[0][0] == "2030-03-04", f"skip this occurrence of a locked task: 400, date kept {r.status_code} {r.text[:100]}")
check(Bo.patch(B + f"/api/tasks/{RT}", json={"locked": False}).ok and Bo.post(B + f"/api/tasks/{RT}/skip", json={}).ok
      and dbx("SELECT due FROM tasks WHERE id=?", (RT,))[0][0] == "2030-03-11", "unlocked: skip moves to the next date")

# ================================================================== the agent API is not bound
r = requests.patch(V + f"/tasks/{T}", headers=CLH, json={"title": "Agent plan v2", "due": "2030-04-04"})
check(r.ok and r.json()["title"] == "Agent plan v2" and r.json()["locked"] is True, "the agent changes a locked task through the API " + r.text[:120])
r = requests.patch(V + f"/tasks/{T}", headers={"Authorization": "Bearer " + pat}, json={"priority": "high"})
check(r.ok, "a personal access token too (the lock guards the app only)")

# ================================================================== lock / unlock
check(Ca.patch(B + f"/api/tasks/{T}", json={"locked": False}).status_code in (403, 404), "a view-only member cannot unlock")
r = Bo.patch(B + f"/api/tasks/{T}", json={"locked": False})
check(r.ok and r.json()["locked"] == 0, "an editor unlocks " + r.text[:120])
check(Bo.patch(B + f"/api/tasks/{T}", json={"title": "Now free"}).ok, "unlocked: the title changes")
check(Bo.patch(B + f"/api/tasks/{T}", json={"locked": True}).json()["locked"] == 1, "an editor locks (true)")
r = Bo.patch(B + f"/api/tasks/{T}", json={"locked": 0, "title": "Unlock and rename"})
check(r.ok and r.json()["title"] == "Unlock and rename" and r.json()["locked"] == 0, "unlocking and changing in one request")
check(Bo.patch(B + f"/api/tasks/{T}", json={"locked": "x"}).status_code == 400, "a bad value -> 400")
acts = [(k, d) for k, d in dbx("SELECT kind, data FROM activity WHERE task_id=? AND kind='lock' ORDER BY id", (T,))]
check(len(acts) == 3 and '"on": false' in acts[0][1] and '"on": true' in acts[1][1], "history: unlocked, locked, unlocked " + str(acts))
r = requests.patch(V + f"/tasks/{T}", headers=CLH, json={"locked": True})
check(r.ok and r.json()["locked"] is True, "the agent API sets locked again")
r = requests.patch(V + f"/tasks/{T}", headers=CLH, json={"locked": False})
check(r.ok and r.json()["locked"] is False, "... and clears it")
requests.patch(V + f"/tasks/{T}", headers=CLH, json={"locked": True})

# ================================================================== OpenAPI, rollback, backup
spec = requests.get(V + "/openapi.json").json()
sch = spec["components"]["schemas"]
check(sch["Task"]["properties"].get("locked", {}).get("type") == "boolean" or "locked" in str(sch.get("Task"))[:20000], "OpenAPI: Task.locked")
check("locked" in sch["TaskInput"]["properties"], "OpenAPI: TaskInput.locked")
c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
c.execute("INSERT INTO tasks(list_id,title,sort,created_at,updated_at) VALUES(?,?,?,?,?)", (W, "Old image", 0, "2026-10-09T10:00:00+00:00", "2026-10-09T10:00:00+00:00"))
c.commit()
c.close()
check(dbx("SELECT locked FROM tasks WHERE title='Old image'")[0][0] == 0, "rollback 2.35: an INSERT without the column gets 0")
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: verifies " + r.text[:200])
dbx("UPDATE tasks SET locked=0", write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
check(wait_for(lambda: dbx("SELECT locked FROM tasks WHERE id=?", (T,))[0][0] == 1, 10), "backup: the lock is back after the restore")

print(f"p2360_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
