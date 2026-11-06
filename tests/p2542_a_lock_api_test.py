#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.542.0 A API tests (#4609): a locked task (tasks.locked = 1) is not completed and not reopened on any way.
 - the app (session): complete / reopen / won't do -> 409 with the reason and the way to unlock ("locked: false"); the
   status stays; unlocking first (PATCH locked false) and then completing works, the history shows the unlock (who)
 - the agent API (token, the way MCP's complete_task / reopen_task go): the same 409 for complete and reopen; the agent may
   unlock (PATCH /api/v1/tasks/<id> locked false) and complete then, the unlock is in the history with the agent
 - multi-select (batch complete / reopen / undo): the locked task is skipped (skipped [id], the reason in errors), the rest
   changes
 - completing a parent leaves a locked subtask open (the cascade skips it), the open ones complete with it
 - an undo of a completion of a task locked since then is refused, the status stays
 - CalDAV: STATUS:COMPLETED of a locked task -> 403, nothing of the PUT is taken over; other fields of a locked task stay
   free for CalDAV (only the status is bound); after unlocking the PUT completes it
 - the MCP tool texts name the way to unlock (complete_task, update_task locked)
 - a person without an organisation: the same 409, unlock + complete works (freelancer-matrix: tasks)
usage: p2542_a_lock_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import check, done, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def status(tid):
    return dbx("SELECT status FROM tasks WHERE id=?", (tid,))[0][0]


def locked_409(r):
    return r.status_code == 409 and "locked" in r.text.lower() and "unlock" in r.text.lower() and "locked: false" in r.text


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent in the list")


def mk(title, lock=True, **kw):
    t = A.post(B + "/api/tasks", json={"title": title, "list_id": W, **kw}).json()["id"]
    if lock:
        check(A.patch(B + f"/api/tasks/{t}", json={"locked": True}).json().get("locked") == 1, f"setup: {title} locked")
    return t


# ================================================================== the app
T = mk("Release train step")
r = A.post(B + f"/api/tasks/{T}/complete", json={})
check(locked_409(r) and status(T) == 0, f"app: completing a locked task -> 409 with the way to unlock {r.status_code} {r.text[:160]}")
r = A.post(B + f"/api/tasks/{T}/complete", json={"status": -1})
check(r.status_code == 409 and status(T) == 0, "app: won't do of a locked task -> 409 too")
DONE = mk("Shipped", lock=False)
check(A.post(B + f"/api/tasks/{DONE}/complete", json={}).ok and status(DONE) == 2, "setup: a done task")
check(A.patch(B + f"/api/tasks/{DONE}", json={"locked": True}).ok, "setup: ... locked afterwards")
r = A.post(B + f"/api/tasks/{DONE}/reopen", json={})
check(locked_409(r) and status(DONE) == 2, f"app: reopening a locked done task -> 409, stays done {r.status_code} {r.text[:120]}")
check(A.patch(B + f"/api/tasks/{T}", json={"locked": False}).ok and A.post(B + f"/api/tasks/{T}/complete", json={}).ok
      and status(T) == 2, "app: unlock first, then complete")
acts = dbx("SELECT kind, data::text, user_id FROM activity WHERE task_id=? AND kind IN ('lock', 'complete') ORDER BY id", (T,))
check([a[0] for a in acts][-2:] == ["lock", "complete"] and '"on": false' in acts[-2][1] and acts[-2][2] is not None,
      "history: unlocked (by whom), then completed " + str(acts))

# ================================================================== the agent API (and MCP through it)
TA = mk("Agent step")
r = requests.post(V + f"/tasks/{TA}/complete", headers=AGH, json={})
check(locked_409(r) and status(TA) == 0, f"agent token: complete of a locked task -> 409 with the reason {r.status_code} {r.text[:160]}")
r = requests.post(V + f"/tasks/{DONE}/reopen", headers=AGH, json={})
check(r.status_code == 409 and status(DONE) == 2, f"agent token: reopen of a locked done task -> 409 {r.status_code}")
r = requests.patch(V + f"/tasks/{TA}", headers=AGH, json={"locked": False})
check(r.ok and r.json()["locked"] is False, "agent token: the agent may unlock a task it may change " + r.text[:120])
r = requests.post(V + f"/tasks/{TA}/complete", headers=AGH, json={})
check(r.ok and status(TA) == 2, "agent token: unlocked -> completes " + r.text[:120])
ua = dbx("SELECT user_id FROM activity WHERE task_id=? AND kind='lock' ORDER BY id DESC LIMIT 1", (TA,))
check(ua and ua[0][0] == AG, f"history: the unlock names the agent {ua}")

# ================================================================== multi-select
T1, O1 = mk("Locked one"), mk("Free one", lock=False)
r = A.post(B + "/api/tasks/batch", json={"ids": [T1, O1], "action": "complete", "data": {}})
j = r.json()
check(r.ok and j["count"] == 1 and j["skipped"] == [T1] and any("unlock" in e.lower() for e in j["errors"])
      and status(T1) == 0 and status(O1) == 2, f"batch complete: the locked task is skipped, the free one completes {j}")
UNDO = j.get("undo", {}).get(str(O1))
check(A.patch(B + f"/api/tasks/{O1}", json={"locked": True}).ok, "setup: lock the completed free one")
r = A.post(B + "/api/tasks/batch", json={"ids": [O1], "action": "undo", "data": {"items": {str(O1): UNDO}}})
check(r.ok and r.json()["skipped"] == [O1] and status(O1) == 2, f"batch undo of a completion: locked since -> skipped, stays done {r.text[:200]}")
r = A.post(B + f"/api/tasks/{O1}/undo", json=UNDO)
check(not r.ok and status(O1) == 2, f"single undo: locked since -> refused, stays done {r.status_code}")
r = A.post(B + "/api/tasks/batch", json={"ids": [O1, DONE], "action": "reopen", "data": {}})
check(r.ok and sorted(r.json()["skipped"]) == sorted([O1, DONE]) and status(O1) == 2, "batch reopen: locked done tasks are skipped " + r.text[:200])
r = A.post(B + "/api/tasks/batch", json={"ids": [T1], "action": "reopen", "data": {}})
check(r.ok and r.json()["skipped"] == [], "batch reopen of an open locked task: nothing to do, not counted as skipped")

# ================================================================== the cascade
P = mk("Parent", lock=False)
K1 = A.post(B + "/api/tasks", json={"title": "Open kid", "parent_id": P}).json()["id"]
K2 = A.post(B + "/api/tasks", json={"title": "Locked kid", "parent_id": P}).json()["id"]
check(A.patch(B + f"/api/tasks/{K2}", json={"locked": True}).ok, "setup: a locked subtask")
check(A.post(B + f"/api/tasks/{P}/complete", json={}).ok and status(P) == 2 and status(K1) == 2 and status(K2) == 0,
      f"completing the parent completes the open subtask, a locked one stays open {status(K1)} {status(K2)}")

# 2.542.0 review: completing a locked task that is done already changes nothing (200, no new history), an undo of the
# parent's completion leaves a subtask locked since then as it is
ca = dbx("SELECT completed_at FROM tasks WHERE id=?", (DONE,))[0][0]
na = dbx("SELECT count(*) FROM activity WHERE task_id=?", (DONE,))[0][0]
r = requests.post(V + f"/tasks/{DONE}/complete", headers=AGH, json={})
check(r.ok and status(DONE) == 2 and dbx("SELECT completed_at FROM tasks WHERE id=?", (DONE,))[0][0] == ca
      and dbx("SELECT count(*) FROM activity WHERE task_id=?", (DONE,))[0][0] == na,
      f"agent token: complete of a locked done task again -> 200, nothing changes {r.status_code} {r.text[:120]}")
P2 = mk("Parent two", lock=False)
K3 = A.post(B + "/api/tasks", json={"title": "Kid done along", "parent_id": P2}).json()["id"]
r = A.post(B + f"/api/tasks/{P2}/complete", json={})
check(r.ok and status(K3) == 2, "setup: the kid completes with its parent")
check(A.patch(B + f"/api/tasks/{K3}", json={"locked": True}).ok, "setup: the kid locked afterwards")
r = A.post(B + f"/api/tasks/{P2}/undo", json=r.json()["undo"])
check(r.ok and status(P2) == 0 and status(K3) == 2, f"undo of the parent: open again, the kid locked since stays done {r.status_code} {status(K3)}")

# ================================================================== CalDAV
r = A.post(B + "/api/me/app-passwords", json={"name": "Phone"})
PW = r.json()["password"]
D = requests.Session()
D.auth = ("alice", PW)
D.headers.update({"X-Forwarded-Proto": "https"})
HREF = f"/dav/calendars/alice/{W}/lk-4609.ics"


def vtodo(*lines):
    body = "".join(x + "\r\n" for x in ("UID:lk-4609", "DTSTAMP:20261105T080000Z", *lines))
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\nBEGIN:VTODO\r\n" + body + "END:VTODO\r\nEND:VCALENDAR\r\n").encode()


CT = {"Content-Type": "text/calendar; charset=utf-8"}
check(D.put(B + HREF, data=vtodo("SUMMARY:Phone task", "STATUS:NEEDS-ACTION"), headers=CT).status_code == 201, "CalDAV: a task from the phone")
TD = dbx("SELECT task_id FROM dav_meta WHERE uid='lk-4609'")[0][0]
check(A.patch(B + f"/api/tasks/{TD}", json={"locked": True}).ok, "setup: locked in the app")
r = D.put(B + HREF, data=vtodo("SUMMARY:Phone task renamed", "STATUS:COMPLETED", "COMPLETED:20261105T090000Z", "PERCENT-COMPLETE:100"), headers=CT)
row = dbx("SELECT status, title FROM tasks WHERE id=?", (TD,))[0]
check(r.status_code == 403 and row[0] == 0 and row[1] == "Phone task", f"CalDAV: STATUS:COMPLETED of a locked task -> 403, nothing taken over {r.status_code} {row}")
r = D.put(B + HREF, data=vtodo("SUMMARY:Phone task renamed", "STATUS:NEEDS-ACTION"), headers=CT)
check(r.status_code == 204 and dbx("SELECT title FROM tasks WHERE id=?", (TD,))[0][0] == "Phone task renamed",
      f"CalDAV: other fields of a locked task stay free (only the status is bound) {r.status_code}")
check(A.patch(B + f"/api/tasks/{TD}", json={"locked": False}).ok, "unlock in the app")
r = D.put(B + HREF, data=vtodo("SUMMARY:Phone task renamed", "STATUS:COMPLETED", "COMPLETED:20261105T090000Z"), headers=CT)
check(r.status_code == 204 and status(TD) == 2, f"CalDAV: unlocked -> completed {r.status_code}")

# ================================================================== MCP texts
src = open(os.path.join(N, "..", "mcp", "kalmido_mcp.py"), encoding="utf-8").read()
seg = src[src.index('("complete_task",'):][:900]
check("locked" in seg and "update_task" in seg, "MCP: complete_task names the lock and how to unlock (update_task locked false)")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Solo"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Tax return", "list_id": FL}).json()["id"]
check(Fr.patch(B + f"/api/tasks/{FT}", json={"locked": True}).ok, "freelancer: lock a task")
r = Fr.post(B + f"/api/tasks/{FT}/complete", json={})
check(locked_409(r) and status(FT) == 0, f"freelancer: completing the locked task -> 409 {r.status_code}")
r = Fr.post(B + "/api/tasks/batch", json={"ids": [FT], "action": "complete", "data": {}})
check(r.ok and r.json()["skipped"] == [FT] and status(FT) == 0, "freelancer: batch skips it")
check(Fr.patch(B + f"/api/tasks/{FT}", json={"locked": False}).ok and Fr.post(B + f"/api/tasks/{FT}/complete", json={}).ok
      and status(FT) == 2, "freelancer: unlock, then complete")

sys.exit(done("p2542_a_lock_api"))
