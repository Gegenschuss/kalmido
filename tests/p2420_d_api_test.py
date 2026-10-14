#!/usr/bin/env python3
"""2.42.0 API tests (agent D), own container (start.sh).
 - #1376: GET /api/state/delta?since=<v>: the tasks changed since v in the serialization of /api/state (a change, a new
   comment, a deletion, a move into a list the person does not see = gone), never tasks of others; a share taken away, a
   too old / too new since, a participant -> full; an agent sees only what is shared with it. PERF line: bytes of the full
   state vs. the delta after one comment
 - #1383: "Save as task" under a comment of an agent (POST /api/chat-save kind comment): a subtask of the task or a new task
   in the same list, the comment's text + a link back, the comment's files copied; saving again answers "already saved";
   comments of people, agents, readers and someone without the task -> refused
usage: p2420_d_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
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


if not os.environ.get("P2420_D_NOSTART"):  # (a quick local run against a running server sets it)
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
P = A.post(B + "/api/lists", json={"name": "Alice private"}).json()["id"]
Q = Ca.post(B + "/api/lists", json={"name": "Carol own"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"})
T1 = A.post(B + "/api/tasks", json={"title": "First", "list_id": L}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Second", "list_id": L}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Third", "list_id": L}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Private one", "list_id": P}).json()["id"]
TC = Ca.post(B + "/api/tasks", json={"title": "Carol secret", "list_id": Q}).json()["id"]


def delta(s, since, **kw):
    r = s.get(B + f"/api/state/delta?since={since}", **kw)
    assert r.ok, (r.status_code, r.text[:300])
    return r.json()


# ================================================================== #1376: delta state
st = Bo.get(B + "/api/state")
v0 = st.json()["v"]
full_bytes = len(st.content)
d = delta(Bo, v0)
check(d.get("full") is False and d["tasks"] == [] and d["gone"] == [], f"#1376: nothing changed -> an empty delta {d}")

# a change of a task + a new comment: both tasks come, as /api/state serializes them
A.patch(B + f"/api/tasks/{T1}", json={"title": "First renamed"})
r = A.post(B + f"/api/tasks/{T2}/comments", json={"body": "a note for bob"})
check(r.ok, f"#1376: comment posted {r.status_code}")
d = delta(Bo, v0)
got = {t["id"]: t for t in d.get("tasks", [])}
check(d.get("full") is False and set(got) == {T1, T2}, f"#1376: the delta has the renamed and the commented task {sorted(got)} {d.get('full')}")
full = {t["id"]: t for t in Bo.get(B + "/api/state").json()["tasks"]}
check(got.get(T1) == full.get(T1) and got.get(T2) == full.get(T2), "#1376: same serialization as /api/state")
check(got.get(T2, {}).get("comment_count") == 1 and got[T2].get("unread") == 1, f"#1376: comment count + unread {got.get(T2)}")
check(str(L) in d.get("progress", {}) and "done" in d.get("counts", {}), f"#1376: progress of the list + counts {d.get('progress')}")
check(d["v"] > v0, "#1376: the delta's v is the server's")
delta_bytes = len(Bo.get(B + f"/api/state/delta?since={v0}").content)
print(f"PERF #1376: one comment + one rename -> full state {full_bytes} B, delta {delta_bytes} B", flush=True)
v1 = d["v"]
check(delta(Bo, v1)["tasks"] == [], "#1376: from the new v nothing again")

# never tasks of others: changes in lists bob does not see are not in his delta (not even their ids)
Ca.patch(B + f"/api/tasks/{TC}", json={"title": "Carol secret 2"})
A.patch(B + f"/api/tasks/{TP}", json={"title": "Private two"})
d = delta(Bo, v1)
check(d.get("full") is False and d["tasks"] == [] and d["gone"] == [], f"#1376: changes of others' lists are not in the delta {d}")
v2 = d["v"]

# deletion and completion: the deleted task is gone
A.delete(B + f"/api/tasks/{T3}")
d = delta(Bo, v2)
check(d.get("full") is False and T3 in d.get("gone", []) and not d["tasks"], f"#1376: a deleted task is gone {d}")
v3 = d["v"]
# undo (restore) brings it back
r = A.post(B + f"/api/tasks/{T3}/restore")
d = delta(Bo, v3)
check(r.ok and [t["id"] for t in d.get("tasks", [])] == [T3], f"#1376: a restored task comes back {r.status_code} {d.get('tasks') and len(d['tasks'])}")
v4 = d["v"]

# moved into a list bob does not see: gone for bob, a change for alice
va = A.get(B + "/api/state").json()["v"]
r = A.patch(B + f"/api/tasks/{T1}", json={"list_id": P})
check(r.ok, f"#1376: move {r.status_code} {r.text[:200]}")
d = delta(Bo, v4)
check(d.get("full") is False and T1 in d.get("gone", []) and not d["tasks"], f"#1376: moved into an invisible list -> gone {d}")
da = delta(A, va)
check(da.get("full") is False and [t["id"] for t in da["tasks"]] == [T1] and da["tasks"][0]["list_id"] == P
      and {str(L), str(P)} <= set(da.get("progress", {})), f"#1376: alice gets the moved task + both lists' progress {da}")
v5 = d["v"]

# batch: several tasks at once
r = A.post(B + "/api/tasks/batch", json={"ids": [T2, T3], "action": "patch", "data": {"priority": 3}})
d = delta(Bo, v5)
check(r.ok and d.get("full") is False and {t["id"] for t in d["tasks"]} >= {T2, T3}, f"#1376: a batch change {r.status_code} {d}")
v6 = d["v"]

# 2.42.0 review: a read mark is a change for its reader only (not for everyone who sees the task)
va6 = A.get(B + "/api/state").json()["v"]
r = Bo.post(B + f"/api/tasks/{T2}/seen")
db_ = {t["id"]: t for t in delta(Bo, v6).get("tasks", [])}
da = delta(A, va6)
check(r.ok and db_.get(T2, {}).get("unread") == 0, f"#1376: bob's own read mark is in his delta {db_.get(T2)}")
check(da.get("full") is False and T2 not in {t["id"] for t in da.get("tasks", [])}, f"#1376: bob's read mark is no change for alice {da}")

# the share taken away -> full (what bob sees changed)
A.delete(B + f"/api/lists/{L}/members/{ids['bob']}")
d = delta(Bo, v6)
check(d.get("full") is True, f"#1376: share taken away -> full {d}")
# too old / too new / bad since -> full
check(delta(Bo, 0).get("full") is True, "#1376: a since from before the server's start -> full")
check(delta(Bo, 10 ** 9).get("full") is True, "#1376: a since newer than the server (restore) -> full")
check(Bo.get(B + "/api/state/delta?since=x").json().get("full") is True, "#1376: a bad since -> full")

# a participant -> full (their visibility hangs on assignments)
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "participant"})
vd = Da.get(B + "/api/state").json()["v"]
check(delta(Da, vd).get("full") is True, "#1376: a participant always gets full")

# an agent: only what is shared with it
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x"), **H}
A.put(B + f"/api/lists/{L}/members", json={"user_id": ag.get("id"), "role": "edit"})
r = requests.get(B + "/api/state", headers=AGH)
if r.ok:
    vg = r.json()["v"]
    A.patch(B + f"/api/tasks/{T2}", json={"title": "Second for the agent"})
    A.patch(B + f"/api/tasks/{TP}", json={"title": "Private three"})
    r = requests.get(B + f"/api/state/delta?since={vg}", headers=AGH)
    dg = r.json() if r.ok else {}
    check(r.ok and (dg.get("full") is True or ({t["id"] for t in dg["tasks"]} == {T2} and TP not in dg["gone"])),
          f"#1376: the agent's delta only has the shared task {r.status_code} {str(dg)[:300]}")
else:
    check(r.status_code in (401, 403), f"#1376: the agent's token does not read the web state {r.status_code}")
    r = requests.get(B + "/api/state/delta?since=1", headers=AGH)
    check(r.status_code in (401, 403), f"#1376: nor the delta {r.status_code}")

# ================================================================== #1383: save an agent's comment as a task
V = B + "/api/v1"
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["carol"], "role": "view"})
TS = A.post(B + "/api/tasks", json={"title": "Export check", "list_id": L}).json()["id"]
r = requests.post(V + f"/tasks/{TS}/comments", headers=AGH, data={"body": "## Follow-up idea\nCheck the export with the new key."},
                  files={"file": ("plan.txt", b"step one\nstep two\n", "text/plain")})
if not r.ok:  # (no files in the agent's comment form: plain JSON)
    r = requests.post(V + f"/tasks/{TS}/comments", headers=AGH, json={"body": "## Follow-up idea\nCheck the export with the new key."})
check(r.ok, f"#1383: the agent comments {r.status_code} {r.text[:200]}")
C1 = r.json().get("id")
with_file = bool(r.json().get("attachments"))
C2 = requests.post(V + f"/tasks/{TS}/comments", headers=AGH, json={"body": "Second idea: a new task in the list"}).json().get("id")
CP = A.post(B + f"/api/tasks/{TS}/comments", json={"body": "my own note"}).json().get("id")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C1})
j = r.json()
t = j.get("task") or {}
check(r.status_code == 201 and t.get("parent_id") == TS and t.get("list_id") == L and t.get("title") == "Follow-up idea",
      f"#1383: saved as a subtask of the task (default) {r.status_code} {str(j)[:300]}")
check("Check the export with the new key." in (t.get("content") or "") and f"#t/{TS}" in (t.get("content") or "")
      and "Claude" in (t.get("content") or ""), f"#1383: the comment's text + a link back + the agent {t.get('content')}")
if with_file:
    check([a["name"] for a in t.get("attachments", [])] == ["plan.txt"], f"#1383: the comment's file is copied {t.get('attachments')}")
SUB = t.get("id")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C1})
check(r.status_code == 200 and r.json().get("already") is True and r.json().get("task_id") == SUB, f"#1383: saving again: already saved {r.text[:200]}")
tl = A.get(B + f"/api/tasks/{TS}/timeline").json()
sv = {c["id"]: c.get("saved_task_id") for c in tl["comments"]}
check(sv.get(C1) == SUB and sv.get(C2) is None and sv.get(CP) is None, f"#1383: the timeline carries saved_task_id {sv}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C2, "as": "list", "title": "Own title"})
t = r.json().get("task") or {}
check(r.status_code == 201 and t.get("parent_id") is None and t.get("list_id") == L and t.get("title") == "Own title",
      f"#1383: as a new task in the same list {r.status_code} {str(t)[:200]}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": CP})
check(r.status_code == 400, f"#1383: a person's comment is refused {r.status_code}")
r = Ca.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C2, "as": "list"})
check(r.status_code == 403, f"#1383: a reader may not add tasks {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C2})
check(r.status_code == 404, f"#1383: someone without the task gets 404 {r.status_code}")
r = requests.post(B + "/api/chat-save", headers=AGH, json={"kind": "comment", "msg_id": C2})
r2 = requests.post(V + "/chat-save", headers=AGH, json={"kind": "comment", "msg_id": C2})
check(r.status_code in (401, 403) and r2.status_code in (404, 405), f"#1383: an agent never saves {r.status_code} {r2.status_code}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C2, "list_id": P})
check(r.status_code == 400, f"#1383: no list choice for a comment {r.status_code}")
r = A.post(B + "/api/chat-save", json={"kind": "comment", "msg_id": C2, "as": "elsewhere"})
check(r.status_code == 400, f"#1383: as must be sub / list {r.status_code}")
r = A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": 1, "as": "sub"})
check(r.status_code == 400, f"#1383: as only for comments {r.status_code}")

print(f"p2420_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
