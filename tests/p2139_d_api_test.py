#!/usr/bin/env python3
"""2.139.0 API tests (part D), own container (start.sh).
 - #2130: "Save as task" under ANY comment (POST /api/chat-save kind comment): a person's own, another person's, an agent's;
   text + link back, saved_task_id in the timeline for every comment (only for the saver), a deleted comment / someone
   without the task -> 404, a reader -> 403; a person without an organisation saves a comment on a private task
usage: p2139_d_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

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


if not os.environ.get("P2139_D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
L = A.post(B + "/api/lists", json={"name": "Shared work"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["carol"], "role": "view"})
T = A.post(B + "/api/tasks", json={"title": "Discuss", "list_id": L}).json()["id"]
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x"), **H}
A.put(B + f"/api/lists/{L}/members", json={"user_id": ag.get("id"), "role": "edit"})

# ================================================================== #2130
CA = A.post(B + f"/api/tasks/{T}/comments", json={"body": "## Alice idea\nOwn words here."}).json()["id"]
CB = Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "Bob says: ship it on Friday"}).json()["id"]
CG = requests.post(B + f"/api/v1/tasks/{T}/comments", headers=AGH, json={"body": "Agent note"}).json().get("id")
CD = Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "to be deleted"}).json()["id"]
Bo.delete(B + f"/api/comments/{CD}")

r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CA})
t = r.json().get("task") or {}
check(r.status_code == 201 and t.get("parent_id") == T and t.get("title") == "Alice idea", f"#2130: own comment saved {r.status_code} {r.text[:200]}")
check("Own words here." in (t.get("content") or "") and f"#t/{T}" in (t.get("content") or ""), f"#2130: text + link back {t.get('content')}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CB, "as": "list", "title": "Friday ship"})
t = r.json().get("task") or {}
check(r.status_code == 201 and t.get("parent_id") is None and t.get("list_id") == L and t.get("title") == "Friday ship",
      f"#2130: another person's comment as a new task in the list {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CG})
check(r.status_code == 201, f"#2130: an agent's comment still works {r.status_code}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CB})
check(r.status_code == 200 and r.json().get("already") is True, f"#2130: saving again = already {r.status_code}")
tl = A.get(B + f"/api/tasks/{T}/timeline").json()
sv = {c["id"]: c.get("saved_task_id") for c in tl["comments"]}
check(sv.get(CA) and sv.get(CB) and sv.get(CG), f"#2130: timeline carries saved_task_id for every comment {sv}")
sb = {c["id"]: c.get("saved_task_id") for c in Bo.get(B + f"/api/tasks/{T}/timeline").json()["comments"]}
check(not any(sb.values()), f"#2130: only the saver sees the mark {sb}")
check(A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CD}).status_code == 404, "#2130: a deleted comment is 404")
check(Da.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CB}).status_code == 404, "#2130: without the task: 404")
check(Ca.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CB, "as": "list"}).status_code == 403, "#2130: a reader may not add tasks")
r = requests.post(B + "/api/chat-save", headers=AGH, json={"kind": "comment", "msg_id": CB})
check(r.status_code in (401, 403), f"#2130: an agent never saves {r.status_code}")

# freelancer-matrix: tasks
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Private", "list_id": FL}).json()["id"]
FC = Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Remember the paperwork"}).json().get("id")
r = Fr.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": FC})
check(r.status_code == 201 and (r.json().get("task") or {}).get("parent_id") == FT, f"#2130: a person without an organisation saves {r.status_code} {r.text[:200]}")

print(f"p2139_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
