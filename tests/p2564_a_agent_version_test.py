#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.564.0 A (#4702): agents must say which version they read when they change content (API v1 / MCP), own container
(start.sh). Invented people and figures only.
 - tasks PATCH: an agent without expect_updated_at / If-Match / _prev = 400 version_required; an old one = 409 (the person's
   change stays); the current one = 200; a state step (pin) needs none; a person's token as before
 - tasks batch update: _prev for every task of the batch
 - a locked task: the agent is not bound, the history shows locked_bypass
 - knowledge page (wiki_write), table cells (expect_rev / prev), a new file version (expect_version / If-Match)
 - the same for a person without an organisation and her own agent"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402  (tests/kt.py)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "wiki,files,collab,comments,sheets"

if not os.environ.get("P2564_A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
L = A.post(B + "/api/lists", json={"name": "Shared work"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"})
SCOPES = ["read", "tasks:write", "wiki:read", "wiki:write", "sheets:read", "sheets:write", "files:read", "files:write"]
ag = A.post(B + "/api/admin/agents", json={"scopes": SCOPES, "username": "claude", "display_name": "Claude", "org_id": ORG}).json()
AGID, AGH = ag.get("id"), {"Authorization": "Bearer " + ag.get("token", "x"), **H}
A.put(B + f"/api/lists/{L}/members", json={"user_id": AGID, "role": "edit"})
tk = Bo.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "tasks:write", "files:write", "sheets:read", "sheets:write"]}).json()
PH = {"Authorization": "Bearer " + tk.get("token", "x"), **H}  # a person's token (old clients): unchanged


def call(h, m, path, hdr=None, **kw):
    return requests.request(m, V + path, headers={**h, **(hdr or {})}, **kw)


def vreq(r):
    """400 version_required with the fields that would do."""
    try:
        e = r.json()["error"]
    except Exception:  # noqa: BLE001
        return False
    return r.status_code == 400 and isinstance(e, dict) and e.get("code") == "version_required" and e.get("fields")


def conflict(r):
    try:
        return r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    except Exception:  # noqa: BLE001
        return False


def acts(s, tid, kind):
    return [a for a in s.get(B + f"/api/tasks/{tid}/timeline").json().get("activity", []) if a["kind"] == kind]


def tasks_round(who, h, lid, person):
    """A reads, the person B changes, A writes with the old version / none / the current one."""
    T = person.post(B + "/api/tasks", json={"title": "Plan the shoot", "list_id": lid, "content": "Start"}).json()["id"]
    seen = call(h, "GET", f"/tasks/{T}").json()
    check(seen.get("updated_at"), f"{who}: get_task carries updated_at")
    for i in range(50):  # updated_at counts whole seconds: the person saves until the task's version moved on (a real state)
        check(person.patch(B + f"/api/tasks/{T}", json={"content": "The person's draft" if i % 2 else "The person's text"}).ok,
              f"{who}: setup: the person changes the description")
        if call(h, "GET", f"/tasks/{T}").json()["updated_at"] != seen["updated_at"]:
            break
        time.sleep(0.1)
    check(person.patch(B + f"/api/tasks/{T}", json={"content": "The person's text"}).ok, f"{who}: setup: the person's last text")
    r = call(h, "PATCH", f"/tasks/{T}", json={"notes": "Agent text"})
    check(vreq(r) and "expect_updated_at" in r.json()["error"]["fields"], f"{who}: no version: 400 version_required {r.status_code} {r.text[:200]}")
    r = call(h, "PATCH", f"/tasks/{T}", json={"notes": "Agent text", "expect_updated_at": seen["updated_at"]})
    check(r.status_code == 409 and (r.json().get("current") or {}).get("notes") == "The person's text", f"{who}: an old version: 409 {r.status_code}")
    check(call(h, "GET", f"/tasks/{T}").json()["notes"] == "The person's text", f"{who}: the person's change stays")
    r = call(h, "PATCH", f"/tasks/{T}", json={"title": "x", "_prev": {"title": "Plan the shoot"}})
    check(r.ok and r.json()["title"] == "x", f"{who}: _prev counts as the version {r.status_code} {r.text[:200]}")
    cur = call(h, "GET", f"/tasks/{T}").json()
    r = call(h, "PATCH", f"/tasks/{T}", hdr={"If-Match": '"' + cur["updated_at"] + '"'}, json={"due": "2027-03-01"})
    check(r.ok and r.json()["due"] == "2027-03-01", f"{who}: If-Match counts as the version {r.status_code} {r.text[:200]}")
    cur = call(h, "GET", f"/tasks/{T}").json()
    r = call(h, "PATCH", f"/tasks/{T}", json={"notes": "Agent text", "expect_updated_at": cur["updated_at"]})
    check(r.ok and r.json()["notes"] == "Agent text", f"{who}: the current version writes {r.status_code} {r.text[:200]}")
    r = call(h, "PATCH", f"/tasks/{T}", json={"pinned": True})
    check(r.ok and r.json().get("pinned") is True, f"{who}: a state step (pin) needs no version {r.status_code} {r.text[:200]}")
    # the lock: the agent is not bound, but the history says so
    check(person.patch(B + f"/api/tasks/{T}", json={"locked": True}).ok, f"{who}: setup: the person locks the task")
    cur = call(h, "GET", f"/tasks/{T}").json()
    r = call(h, "PATCH", f"/tasks/{T}", json={"title": "Changed while locked", "expect_updated_at": cur["updated_at"]})
    check(r.ok and r.json()["title"] == "Changed while locked", f"{who}: the agent still changes a locked task {r.status_code} {r.text[:200]}")
    check(len(acts(person, T, "locked_bypass")) == 1, f"{who}: the history marks locked_bypass {acts(person, T, 'locked_bypass')}")
    check(person.patch(B + f"/api/tasks/{T}", json={"title": "No"}).status_code >= 400, f"{who}: the app stays bound by the lock")
    check(call(h, "PATCH", f"/tasks/{T}", json={"pinned": False}).ok and len(acts(person, T, "locked_bypass")) == 1,
          f"{who}: a free field of a locked task: no further mark")
    return T


# ================================================================== tasks (organisation)
T = tasks_round("org", AGH, L, Bo)
P = A.post(B + "/api/tasks", json={"title": "Script task", "list_id": L}).json()["id"]
r = call(PH, "PATCH", f"/tasks/{P}", json={"title": "By a script"})
check(r.ok and r.json()["title"] == "By a script", f"a person's token without a version: as before {r.status_code} {r.text[:200]}")

# batch: _prev for every task
BT = [A.post(B + "/api/tasks", json={"title": f"Batch {i}", "list_id": L, "due": "2027-04-01"}).json()["id"] for i in range(2)]
r = call(AGH, "POST", "/tasks/batch", json={"ids": BT, "action": "update", "changes": {"title": "x"}})
check(vreq(r), f"batch without _prev: 400 version_required {r.status_code} {r.text[:200]}")
r = call(AGH, "POST", "/tasks/batch", json={"ids": BT, "action": "update", "changes": {"title": "x"}, "_prev": {str(BT[0]): {"title": "Batch 0"}}})
check(vreq(r) and [A.get(B + f"/api/tasks/{i}").json()["title"] for i in BT] == ["Batch 0", "Batch 1"],
      f"batch with _prev for one of two: 400, nothing changes {r.status_code} {r.text[:200]}")
r = call(AGH, "POST", "/tasks/batch", json={"ids": BT, "action": "update", "changes": {"title": "x"}, "_prev": {str(i): {"title": f"Batch {n}"} for n, i in enumerate(BT)}})
check(r.ok and r.json()["count"] == 2, f"batch with _prev for all: writes {r.status_code} {r.text[:200]}")
r = call(AGH, "POST", "/tasks/batch", json={"ids": BT, "action": "update", "changes": {"pinned": True}})
check(r.ok and r.json()["count"] == 2, f"batch state step without _prev: as before {r.status_code} {r.text[:200]}")
r = call(PH, "POST", "/tasks/batch", json={"ids": BT, "action": "update", "changes": {"title": "y"}})
check(r.ok and r.json()["count"] == 2, f"a person's batch without _prev: as before {r.status_code} {r.text[:200]}")

# ================================================================== knowledge page
r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": "Team/Plan", "body": "First"})
check(r.status_code == 201, "setup: a knowledge page " + r.text[:200])
PID = r.json().get("id")
FOL = {f["path"]: f["id"] for f in A.get(B + "/api/wiki", params={"space": SP}).json().get("folders", [])}
check(A.post(B + f"/api/files/nodes/{FOL.get('Team')}/shares", json={"agent_id": AGID, "role": "edit"}).status_code == 201, "setup: shared with the agent")
seen = call(AGH, "GET", f"/wiki/pages/{PID}").json()
check(seen.get("updated_at"), "wiki_read carries updated_at")
pg = A.get(B + f"/api/wiki/pages/{PID}").json()
check(A.patch(B + f"/api/wiki/pages/{PID}", json={"body": "Alice's text", "expect_updated_at": pg.get("updated_at")}).ok, "setup: the person saves")  # the app sends it always
r = call(AGH, "PATCH", f"/wiki/pages/{PID}", json={"body": "Agent"})
check(vreq(r), f"wiki without a version: 400 version_required {r.status_code} {r.text[:200]}")
r = call(AGH, "PATCH", f"/wiki/pages/{PID}", json={"body": "Agent", "expect_updated_at": seen["updated_at"]})
check(r.status_code == 409 and call(AGH, "GET", f"/wiki/pages/{PID}").json()["body"] == "Alice's text", f"wiki old version: 409, the text stays {r.status_code}")
cur = call(AGH, "GET", f"/wiki/pages/{PID}").json()
r = call(AGH, "PATCH", f"/wiki/pages/{PID}", hdr={"If-Match": cur["updated_at"]}, json={"body": "Agent"})
check(r.ok and r.json()["body"] == "Agent", f"wiki If-Match writes {r.status_code} {r.text[:200]}")
r = call(AGH, "PATCH", f"/wiki/pages/{PID}", hdr={"If-Match": cur["updated_at"]}, json={"body": "Agent again"})
check(r.status_code == 409, f"wiki If-Match with the old version: 409 {r.status_code}")

# ================================================================== table cells
r = call(AGH, "POST", "/sheets", json={"title": "Budget", "space": SP, "rows": [["a", "1"], ["b", "2"]]})
check(r.status_code == 201, "setup: the agent's table " + r.text[:200])
SID = r.json().get("id")
rev = call(AGH, "GET", f"/sheets/{SID}").json()["rev"]
r = call(AGH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]})
check(vreq(r) and set(r.json()["error"]["fields"]) >= {"expect_rev", "prev"}, f"cells without a version: 400 {r.status_code} {r.text[:200]}")
r = call(AGH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "x"}, {"cell": "A2", "raw": "y", "prev": "b"}]})
check(vreq(r), f"cells with prev on only some: 400 {r.status_code}")
r = call(AGH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "x"}], "expect_rev": rev})
check(r.ok, f"cells with the current rev: write {r.status_code} {r.text[:200]}")
r = call(PH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "5"}]})
check(r.ok, f"a person's token without a version: as before (the person changes in between) {r.status_code} {r.text[:200]}")
r = call(AGH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "9"}], "expect_rev": rev})
check(r.status_code == 409, f"cells with an old rev: 409 {r.status_code}")
r = call(AGH, "PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "9", "prev": "1"}]})
check(r.ok and r.json()["conflicts"] and r.json()["conflicts"][0]["server"] == "5", f"cells with prev: the person's input stays {r.text[:300]}")


# ================================================================== a new file version
def files_round(who, h, person_h=None):
    r = call(h, "POST", "/files", json={"name": "report.md", "content": "v1"})
    check(r.status_code == 201 and r.json().get("version") == 1, f"{who}: setup: the agent's file {r.status_code} {r.text[:200]}")
    fid = r.json().get("id")
    r = call(h, "GET", f"/files/{fid}/text")
    check(r.ok and r.json().get("version") == 1, f"{who}: read_file (text) carries the version {r.text[:200]}")
    r = call(h, "POST", f"/files/{fid}/versions", json={"content": "v2"})
    check(vreq(r) and "expect_version" in r.json()["error"]["fields"], f"{who}: no version: 400 version_required {r.status_code} {r.text[:200]}")
    r = call(h, "POST", f"/files/{fid}/versions", json={"content": "v2", "expect_version": 1})
    check(r.status_code == 201 and r.json().get("version") == 2, f"{who}: the current version writes {r.status_code} {r.text[:200]}")
    r = call(h, "POST", f"/files/{fid}/versions", json={"content": "v3", "expect_version": 1})
    check(conflict(r), f"{who}: an old version: 409 conflict {r.status_code} {r.text[:200]}")
    check(call(h, "GET", f"/files/{fid}/text").json().get("version") == 2, f"{who}: no version 3 came")
    check(call(h, "POST", f"/files/{fid}/versions", json={"content": "v3", "expect_version": "2"}).status_code == 400, f"{who}: expect_version must be a number")
    r = call(h, "POST", f"/files/{fid}/versions", hdr={"If-Match": '"2"'}, json={"content": "v3"})
    check(r.status_code == 201 and r.json().get("version") == 3, f"{who}: If-Match counts {r.status_code} {r.text[:200]}")
    if person_h:
        r = call(person_h, "POST", "/files", json={"name": "mine.md", "content": "a"})
        check(r.status_code == 201, f"{who}: setup: a person's file {r.text[:200]}")
        r = call(person_h, "POST", f"/files/{r.json().get('id')}/versions", json={"content": "b"})
        check(r.status_code == 201, f"{who}: a person's token without a version: as before {r.status_code} {r.text[:200]}")


files_round("org", AGH, PH)

# ================================================================== a person without an organisation, her own agent
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "tasks:write", "files:read", "files:write"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FH = r.json().get("id"), {"Authorization": "Bearer " + r.json().get("token", "x"), **H}
FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"})
tasks_round("freelancer", FH, FL, Fr)
files_round("freelancer", FH)

print(f"p2564_a_agent_version: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
