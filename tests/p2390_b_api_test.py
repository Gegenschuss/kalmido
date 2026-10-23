#!/usr/bin/env python3
"""2.39.0 API tests (agent B: #1151 "Tidy up the list"), own container (start.sh).
 - the request POST /api/proposals {kind: cleanup, list_id, task_ids?, hint?}: only people with write access (a viewer 403),
   always the list's tidy agent (agent_id is ignored), a list without one 409, a health list 403, an agent limited to other
   lists 409, proposals off 409; the selection (task_ids) only open top-level tasks of the list (400 otherwise)
 - packages: 50 tasks per job_request, at most 5 (the first 250, truncated), one job per package, titles "package n of m";
   the event job_request carries list_id on top and the documented input (notes cut at 2000, list tags, comments count)
 - the agent's proposal (kind cleanup): unknown / foreign / repeated task ids, a merge with one task, close without a reason,
   an unknown section, op or field: 400
 - applying as the person: merge (notes appended with "Merged from #id title", the others closed as won't do, their comments
   stay), rename (edited title), move (section and the place inside the section), close (won't do, reason in the history);
   skipped with the reason: someone editing it (#999), changed since the request, already completed; the answer and the
   agent's job event list them; the job event has list_id on top
 - undo takes everything back in one step, redo applies it again; discard tells the agent (reject, list_id)
usage: p2390_b_api_test.py <datadir>"""
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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def q(sql, args=()):
    con = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=30, **k)

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=30, **k)


def events(cl, kind):
    return [e for e in cl.get("/agent/events", params={"since": 0, "limit": 500}).json()["data"] if e["event"] == kind]


def ask(s, **b):
    return s.post(B + "/api/proposals", json={"kind": "cleanup", **b})


def task(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def new_task(s, lid, title, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol"):
    uid[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                            "email": f"{u}@example.com"}).json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")
for x in (Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "tidy", "display_name": "Tidy"})
assert r.status_code in (200, 201), r.text
AG, cl = r.json()["id"], Api(r.json()["token"])

W = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
for who, role in ((AG, "edit"), (BOB, "edit"), (CAROL, "view")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: member {who}")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})
SEC = A.post(B + "/api/sections", json={"list_id": W, "name": "Later"}).json()["id"]
T = {}
for k in ("dup1", "dup2", "vague", "misplaced", "stale", "editing", "changed", "done", "top"):
    T[k] = new_task(A, W, "Task " + k, content=("note of " + k) if k != "dup2" else "x" * 2500)
SUB = new_task(A, W, "a subtask", parent_id=T["stale"])
SUB2 = new_task(A, W, "a subtask of dup2", parent_id=T["dup2"])  # review M2: moves to the kept task on merge
check(A.post(B + f"/api/tasks/{T['dup2']}/comments", json={"body": "a comment that stays"}).status_code in (200, 201), "setup: comment")

# ================================================================== the request: rights, the tidy agent, health, limits
EMPTY = A.post(B + "/api/lists", json={"name": "No agent"}).json()["id"]
new_task(A, EMPTY, "lonely")
r = ask(A, list_id=EMPTY)
check(r.status_code == 409 and "agent" in r.json().get("error", ""), f"no tidy agent: 409 with a readable reason {r.status_code} {r.text[:120]}")
r = ask(Ca, list_id=W)
check(r.status_code == 403, f"a viewer may not ask: {r.status_code}")
r = ask(A, list_id=999999)
check(r.status_code == 404, f"an unknown list: 404 ({r.status_code})")
HL = A.post(B + "/api/lists", json={"name": "Doctor"}).json()["id"]
new_task(A, HL, "appointment")
check(A.patch(B + f"/api/lists/{HL}", json={"life": "health"}).ok, "setup: a health list")
r = ask(A, list_id=HL)
check(r.status_code == 403, f"a health list never reaches the agent: 403 ({r.status_code} {r.text[:100]})")
check(not events(cl, "job_request"), "nothing reached the agent yet")
# the agent's list limit and its proposals setting
SIDE = A.post(B + "/api/lists", json={"name": "Side"}).json()["id"]
A.put(B + f"/api/lists/{SIDE}/members", json={"user_id": AG, "role": "edit"})
r = A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [SIDE]})
check(r.ok, f"setup: agent limited to another list {r.status_code} {r.text[:100]}")
r = ask(A, list_id=W)
check(r.status_code == 409, f"an agent limited to other lists: 409 ({r.status_code} {r.text[:100]})")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [], "bridge_ok": True}).ok, "setup: limit lifted")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "off"}).ok, "setup: proposals off")
r = ask(A, list_id=W)
check(r.status_code == 409, f"proposals off: 409 ({r.status_code})")
A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "shared"})
# the selection
r = ask(A, list_id=W, task_ids=[T["dup1"], SUB])
check(r.status_code == 400, f"a subtask is no top-level task: 400 ({r.status_code})")
r = ask(A, list_id=W, task_ids=[T["dup1"], new_task(A, EMPTY, "elsewhere")])
check(r.status_code == 400, f"a task of another list: 400 ({r.status_code})")

# Bob (edit, the list's members may use its agent) asks for a selection; agent_id is ignored (always the tidy agent)
r = ask(Bo, list_id=W, agent_id=ALICE, task_ids=[T["dup1"], T["top"]], hint="only these")
check(r.status_code == 201 and r.json()["agent"]["id"] == AG and r.json()["packages"] == 1, f"Bob asks for a selection: {r.status_code} {r.text[:200]}")
JB = r.json()["job"]["id"]
ev = events(cl, "job_request")[-1]["data"]
check(ev["list_id"] == W and ev["kind"] == "cleanup" and sorted(i["task_id"] for i in ev["input"]["items"]) == sorted([T["dup1"], T["top"]])
      and ev["input"]["hint"] == "only these", f"job_request: list_id on top, the selection only {ev.get('list_id')}")
check(Bo.post(B + f"/api/proposals/{JB}/discard").ok, "Bob discards his request")
rj = events(cl, "job")[-1]["data"]
check(rj["action"] == "reject" and rj["list_id"] == W and rj["proposal"]["state"] == "discarded", f"discard: job event reject with list_id {rj}")

# Alice asks for the whole list
r = ask(A, list_id=W, hint="duplicates first")
check(r.status_code == 201 and r.json()["tasks"] == 9 and r.json()["packages"] == 1 and not r.json()["truncated"], f"whole list: {r.text[:200]}")
J = r.json()["job"]["id"]
ev = events(cl, "job_request")[-1]["data"]
inp = ev["input"]
it = {i["task_id"]: i for i in inp["items"]}
check(ev["list_id"] == W and inp["list"]["id"] == W and {"id": SEC, "name": "Later"} in inp["list"]["sections"], f"input.list with sections {inp['list']}")
check(inp["package"]["n"] == 1 and inp["package"]["of"] == 1 and inp["snapshot_at"], f"package 1 of 1 {inp['package']}")
check(len(it[T["dup2"]]["notes"]) == 2000 and it[T["dup2"]]["comments_count"] == 1 and SUB not in it, "notes cut at 2000, comments counted, no subtasks")
check(all(set(x) >= {"task_id", "title", "notes", "section_id", "sort", "due", "priority", "list_tags", "assignee_id", "created_at",
                     "updated_at", "comments_count"} for x in inp["items"]), "every item has the documented fields")
check(ev["requested_by"]["id"] == ALICE and ev["job"]["kind"] == "cleanup", "requested_by + job kind")

# ================================================================== the agent's proposal: validation
def submit(body):
    return cl.post(f"/agent/jobs/{J}/proposal", json=body)


bad = [
    ({"items": [{"op": "rename", "task_id": 999999, "title": "x"}]}, "a task id that is not in the input"),
    ({"items": [{"op": "rename", "task_id": T["vague"], "title": "x"}, {"op": "close", "task_id": T["vague"], "reason": "y"}]}, "a task twice"),
    ({"items": [{"op": "merge", "task_ids": [T["dup1"]]}]}, "a merge with one task"),
    ({"items": [{"op": "merge", "task_ids": [T["dup1"], T["dup1"]]}]}, "a merge with the same task twice"),
    ({"items": [{"op": "close", "task_id": T["stale"]}]}, "close without a reason"),
    ({"items": [{"op": "move", "task_id": T["misplaced"], "section_id": 999999}]}, "an unknown section"),
    ({"items": [{"op": "move", "task_id": T["misplaced"]}]}, "a move without section or position"),
    ({"items": [{"op": "split", "task_id": T["misplaced"]}]}, "an unknown op"),
    ({"items": [{"op": "rename", "task_id": T["vague"], "title": "x", "color": "red"}]}, "an unknown field"),
    ({"items": []}, "no entries"),
    ({"kind": "triage", "items": [{"op": "rename", "task_id": T["vague"], "title": "x"}]}, "another kind"),
]
for body, what in bad:
    r = submit(body)
    check(r.status_code == 400, f"proposal: {what} -> 400 ({r.status_code} {r.text[:100]})")
check(A.get(B + f"/api/proposals/{J}").json()["state"] == "requested", "still waiting after the bad proposals")

PROP = {"kind": "cleanup", "summary": "Two duplicates, a vague title, one in the wrong section, one stale.", "items": [
    {"op": "merge", "task_ids": [T["dup1"], T["dup2"]], "title": "Order the flyers", "reason": "the same twice"},
    {"op": "rename", "task_id": T["vague"], "title": "Call the printer about the paper"},
    {"op": "move", "task_id": T["misplaced"], "section_id": SEC, "position": 1},
    {"op": "move", "task_id": T["top"], "position": 1, "reason": "most urgent"},
    {"op": "close", "task_id": T["stale"], "reason": "the fair was last year"},
    {"op": "rename", "task_id": T["editing"], "title": "Renamed while someone types"},
    {"op": "rename", "task_id": T["changed"], "title": "Renamed although changed"},
    {"op": "close", "task_id": T["done"], "reason": "done anyway"}]}
r = submit(PROP)
check(r.status_code == 201 and len(r.json()["proposal"]["items"]) == 8, f"a valid proposal: 201 ({r.status_code} {r.text[:200]})")
v = A.get(B + f"/api/proposals/{J}").json()
check(v["state"] == "ready" and v["kind"] == "cleanup" and v["proposal"]["items"][2]["section_id"] == SEC, "the person sees it ready")
check(len(q("SELECT id FROM notifications WHERE user_id=? AND kind='proposal'", (ALICE,))) == 1, "one News entry for the proposal")

# ================================================================== applying: four kinds, skipped with the reason
check(Bo.post(B + f"/api/tasks/{T['editing']}/editing").ok, "#999: Bob is editing a task")
check(A.patch(B + f"/api/tasks/{T['changed']}", json={"title": "Changed meanwhile"}).ok, "a task changed after the request")
check(A.post(B + f"/api/tasks/{T['done']}/complete", json={}).ok, "a task completed meanwhile")
r = A.post(B + f"/api/proposals/{J}/apply", json={"select": [str(i) for i in range(8)], "edits": {"1": {"title": "Call the printer"}}})
check(r.status_code == 200, f"apply: {r.status_code} {r.text[:300]}")
res = r.json()
why = {s["task_id"]: s["why"] for s in res.get("skipped", [])}
check(why == {T["editing"]: "editing", T["changed"]: "changed", T["done"]: "closed"}, f"skipped with the reason: {why}")
check(all(s.get("why_text") and s.get("title") for s in res.get("skipped", [])), "every skipped one with title and a readable reason")
check(res.get("merge") == 1 and res.get("rename") == 1 and res.get("move") == 2 and res.get("close") == 1, f"counts per kind {res}")
k = task(A, T["dup1"])
check(k["title"] == "Order the flyers" and f"Merged from #{T['dup2']} Task dup2" in (k.get("content") or "") and "note of dup1" in k["content"],
      f"merge: the kept task has the title and the notes of the other {k.get('title')} {k.get('content', '')[:120]!r}")
d2 = task(A, T["dup2"])
check(d2["status"] == -1, f"merge: the other one is closed as won't do ({d2['status']})")
check(len(q("SELECT id FROM comments WHERE task_id=? AND deleted_at IS NULL", (T["dup2"],))) == 1, "merge: its comment stays with it")
check(task(A, SUB2)["parent_id"] == T["dup1"] and task(A, SUB2)["status"] == 0, "merge: an open subtask of the other one moves to the kept task")
check(task(A, T["vague"])["title"] == "Call the printer", "rename with the person's edited title")
m = task(A, T["misplaced"])
check(m["section_id"] == SEC, f"move: into the section {m['section_id']}")
top = task(A, T["top"])
others = [r_[0] for r_ in q("SELECT sort FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL AND section_id IS NULL AND id<>?",
                            (W, T["top"]))]
check(top["section_id"] is None and all(top["sort"] < s for s in others), "move: place 1 inside its section (no section)")
st = task(A, T["stale"])
check(st["status"] == -1 and task(A, SUB)["status"] == -1, "close: won't do, with its open subtask")
acts = [r_[0] for r_ in q("SELECT data FROM activity WHERE task_id=? AND kind='wont'", (T["stale"],))]
check(any("the fair was last year" in str(a) for a in acts), f"close: the reason in the history {acts}")
check(task(A, T["editing"])["title"] == "Task editing" and task(A, T["changed"])["title"] == "Changed meanwhile", "skipped tasks untouched")
je = events(cl, "job")[-1]["data"]
check(je["action"] == "approve" and je["list_id"] == W and je["proposal"]["state"] == "applied" and len(je["proposal"]["skipped"]) == 3
      and je["proposal"]["list_id"] == W, f"the agent's job event: list_id, counts and the skipped ones {str(je)[:300]}")
check(A.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code == 409, "applying twice: 409")

# ================================================================== one undo step, redo
r = A.post(B + f"/api/proposals/{J}/undo")
check(r.ok and not r.json()["none"], f"undo: {r.text[:200]}")
check(task(A, T["dup1"])["title"] == "Task dup1" and task(A, T["dup1"])["content"] == "note of dup1", "undo: merge title + notes back")
check(task(A, T["dup2"])["status"] == 0 and task(A, T["stale"])["status"] == 0 and task(A, SUB)["status"] == 0, "undo: closed tasks open again (subtask too)")
check(task(A, T["vague"])["title"] == "Task vague" and task(A, T["misplaced"])["section_id"] is None, "undo: rename + move back")
check(task(A, SUB2)["parent_id"] == T["dup2"] and task(A, SUB2)["status"] == 0, "undo: the moved subtask is back under its task")
check(task(A, T["done"])["status"] == 2, "undo leaves the task completed by the person alone")
r = A.post(B + f"/api/proposals/{J}/redo")
check(r.ok and not r.json()["none"], f"redo: {r.text[:200]}")
check(task(A, T["dup1"])["title"] == "Order the flyers" and task(A, T["dup2"])["status"] == -1 and task(A, T["stale"])["status"] == -1
      and task(A, T["misplaced"])["section_id"] == SEC and task(A, T["vague"])["title"] == "Call the printer", "redo: everything again")
check(A.post(B + f"/api/proposals/{J}/redo").status_code == 409, "redo twice: 409")
r = A.post(B + f"/api/proposals/{J}/undo")
check(r.ok and task(A, T["dup2"])["status"] == 0, "undo again after redo")

# ================================================================== packages: 50 per job, at most 5
BIG = A.post(B + "/api/lists", json={"name": "Backlog"}).json()["id"]
A.put(B + f"/api/lists/{BIG}/members", json={"user_id": AG, "role": "edit"})
for i in range(120):
    new_task(A, BIG, f"Backlog {i}")
before = len(events(cl, "job_request"))
r = ask(A, list_id=BIG)
d = r.json()
check(r.status_code == 201 and d["packages"] == 3 and d["tasks"] == 120 and len(d["jobs"]) == 3, f"120 tasks: 3 packages {r.text[:200]}")
new = events(cl, "job_request")[before:]
check([len(e["data"]["input"]["items"]) for e in new] == [50, 50, 20] and [e["data"]["input"]["package"]["n"] for e in new] == [1, 2, 3]
      and len({e["data"]["input"]["package"]["group"] for e in new}) == 1, "50 / 50 / 20, numbered, one group")
check(all("package" in j["title"] and "of 3" in j["title"] for j in d["jobs"]), f"titles name the package {[j['title'] for j in d['jobs']]}")
for j in d["jobs"]:
    A.post(B + f"/api/proposals/{j['id']}/discard")
for i in range(140):
    new_task(A, BIG, f"More {i}")
r = ask(A, list_id=BIG)
d = r.json()
check(r.status_code == 201 and d["packages"] == 5 and d["tasks"] == 250 and d["total"] == 260 and d["truncated"], f"260 tasks: the first 250 in 5 packages {r.text[:200]}")
for j in d["jobs"]:
    A.post(B + f"/api/proposals/{j['id']}/discard")

print(f"p2390_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
