#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 B (#3354): columns with a status meaning, each block red without its fix (everything as a person without an
organisation; invented names only)
 - the meaning: POST / PATCH / undo of a section, only the five values, viewers 403; a software project with the standard
   sections carries them, switching the type changes no existing column
 - moving: into done completes (PATCH and reorder alike), into rejected = won't do, out of them reopens; another project's
   task keeps its status when it lands without a meaning; a list without meanings behaves as before
 - ticking: into the first done column, not with "Keep completed in their section" off; undo goes back; a subtask stays; a
   recurring task: the completed copy moves, the original stays; moved in by hand: the original goes back, undo works
 - reopening out of done / rejected goes to the first open column, undo goes back; no loop between tick and move
 - review: the column with the meaning review comes before the name "Review"; the gate refuses a move into done
 - API: section_kind in tasks, lists and sections, ?section_kind=, POST /tasks/{id}/state, the mandate boundary
 - rules fire once for a completion by a move
freelancer-matrix: tasks
usage: p2577_a_seckind_api_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, docker_logs_on_first_fail, done, fresh, setup

V = B + "/api/v1"
fresh(prefix="PR2472B")
docker_logs_on_first_fail(tail=120, chars=12000)
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)
GID, G = freelancer(B, A, "gerd")
tok = F.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure"]})
check(tok.status_code == 201, "token " + tok.text[:150])
H = {"Authorization": "Bearer " + tok.json().get("token", "")}


def task(tid):
    return F.get(B + f"/api/tasks/{tid}").json()


def v1(tid):
    return requests.get(V + f"/tasks/{tid}", headers=H).json()


def board(name, cols):
    lid = F.post(B + "/api/lists", json={"name": name}).json()["id"]
    return lid, {n: F.post(B + "/api/sections", json={"list_id": lid, "name": n, "kind": k}).json()["id"] for n, k in cols}


def new(lid, sid=None, **kw):
    r = F.post(B + "/api/tasks", json={"title": "Ticket", "list_id": lid, **({"section_id": sid} if sid else {}), **kw})
    check(r.status_code in (200, 201), "new task " + r.text[:120])
    return r.json()["id"]


def drag(tid, sid):
    return F.post(B + "/api/tasks/reorder", json={"items": [{"id": tid, "section_id": sid}]})


COLS = (("Later", "open"), ("Soon", "open"), ("Doing", "progress"), ("Check", "review"), ("Over", "done"), ("No", "rejected"))

# ---- the meaning of a column
L, S = board("Board", COLS)
got = {r["id"]: r["kind"] for r in F.get(B + "/api/state").json()["sections"] if r["list_id"] == L}
check(got[S["Over"]] == "done" and got[S["No"]] == "rejected", "POST /api/sections stores the meaning, the state carries it")
check(F.post(B + "/api/sections", json={"list_id": L, "name": "x", "kind": "maybe"}).status_code == 400, "an unknown meaning is refused")
check(F.patch(B + f"/api/sections/{S['Doing']}", json={"kind": "later"}).status_code == 400, "PATCH: an unknown meaning is refused")
r = F.patch(B + f"/api/sections/{S['Doing']}", json={"kind": "review", "_prev": {"kind": "open"}})
check(r.ok and r.json()["conflicts"], "_prev: a meaning changed elsewhere meanwhile stays")
x = F.post(B + "/api/sections", json={"list_id": L, "name": "Gone", "kind": "progress"}).json()["id"]
check(F.delete(B + f"/api/sections/{x}").json()["section"]["kind"] == "progress", "delete returns the meaning for the undo")
check(G.patch(B + f"/api/sections/{S['Doing']}", json={"kind": ""}).status_code in (403, 404), "another person's column: refused")
P = requests.post(V + "/lists", headers=H, json={"name": "App", "project_type": "software", "sections": True})
check(P.status_code == 201, "software project " + P.text[:150])
sw = [(s["name"], s["section_kind"]) for s in requests.get(V + f"/lists/{P.json()['id']}/sections", headers=H).json()["data"]]
check([k for _, k in sw] == ["open", "open", "progress", "review", "done"], "software project: standard columns with meanings " + str(sw))
Q, QS = board("Typed", (("Over", ""),))
check(F.patch(B + f"/api/lists/{Q}", json={"ptype": "software"}).ok, "switch the type")
check(F.get(B + "/api/state").json()["sections"] and [r["kind"] for r in F.get(B + "/api/state").json()["sections"] if r["id"] == QS["Over"]] == [""],
      "switching the type changes no existing column")

# ---- moving
t = new(L, S["Later"])
check(drag(t, S["Over"]).ok and task(t)["status"] == 2 and task(t)["completed_at"], "reorder into done completes")
check(drag(t, S["Doing"]).ok and task(t)["status"] == 0 and not task(t)["completed_at"], "out of done reopens")
check(F.patch(B + f"/api/tasks/{t}", json={"section_id": S["No"]}).ok and task(t)["status"] == -1, "PATCH into rejected = won't do")
check(F.patch(B + f"/api/tasks/{t}", json={"section_id": S["Over"]}).ok and task(t)["status"] == 2, "rejected -> done")
check(F.patch(B + f"/api/tasks/{t}", json={"section_id": S["Later"]}).ok and task(t)["status"] == 0, "PATCH out of done reopens")
M, MS = board("Plain", (("A", ""), ("B", "")))
t = new(M, MS["A"])
F.post(B + f"/api/tasks/{t}/complete", json={})
check(drag(t, MS["B"]).ok and task(t)["status"] == 2, "without meanings: moving a completed task leaves it completed")
t = new(L, S["Later"])
F.patch(B + f"/api/tasks/{t}", json={"section_id": S["Over"]})
check(F.patch(B + f"/api/tasks/{t}", json={"list_id": M, "section_id": None}).ok and task(t)["status"] == 2, "to another project: stays completed")

# ---- ticking
t = new(L, S["Doing"])
j = F.post(B + f"/api/tasks/{t}/complete", json={}).json()
check(j["section_id"] == S["Over"], "the tick moves into the first done column")
r = F.post(B + f"/api/tasks/{t}/undo", json=j["undo"])
check(r.ok and r.json()["section_id"] == S["Doing"] and r.json()["status"] == 0, "undo of the tick: back in its column " + r.text[:100])
j = F.post(B + f"/api/tasks/{t}/complete", json={"status": -1}).json()
check(j["section_id"] == S["No"] and j["status"] == -1, "won't do moves into the rejected column")
j = F.post(B + f"/api/tasks/{t}/reopen", json={}).json()
check(j["section_id"] == S["Later"] and j["status"] == 0, "reopening goes to the first open column")
r = F.post(B + f"/api/tasks/{t}/undo", json=j["undo"])
check(r.ok and r.json()["section_id"] == S["No"] and r.json()["status"] == -1, "undo of the reopen: back in the rejected column")
b = F.post(B + "/api/tasks/batch", json={"ids": [t], "action": "reopen"}).json()
check(task(t)["section_id"] == S["Later"] and b["undo"], "batch reopen: the same way")
F.post(B + "/api/tasks/batch", json={"ids": [t], "action": "complete"})
check(task(t)["section_id"] == S["Over"], "batch complete: the same way")
sub = F.post(B + "/api/tasks", json={"title": "Part", "list_id": L, "parent_id": new(L, S["Doing"])}).json()
j = F.post(B + f"/api/tasks/{sub['id']}/complete", json={}).json()
check(j["section_id"] == sub["section_id"], "a subtask stays where it is")
par = new(L, S["Doing"])
kid = F.post(B + "/api/tasks", json={"title": "Part 2", "list_id": L, "parent_id": par}).json()["id"]
check(drag(par, S["Over"]).ok and task(par)["status"] == 2 and task(kid)["status"] == 2, "completing by a move completes the subtasks")
in_done = F.post(B + "/api/tasks", json={"title": "Part 3", "list_id": L, "parent_id": new(L, S["Over"])}).json()
check(task(in_done["id"])["status"] == 0, "a subtask under a task in the done column is not completed by it")
F.patch(B + f"/api/lists/{L}", json={"done_in_section": 0})
t = new(L, S["Doing"])
check(F.post(B + f"/api/tasks/{t}/complete", json={}).json()["section_id"] == S["Doing"], "keep completed off: the tick does not move")
F.patch(B + f"/api/lists/{L}", json={"done_in_section": None})

# ---- recurring tasks
t = new(L, S["Doing"], due="2030-01-07", repeat="FREQ=DAILY")
j = F.post(B + f"/api/tasks/{t}/complete", json={}).json()
cp = j["undo"]["copy_id"]
check(j["status"] == 0 and j["section_id"] == S["Doing"] and task(cp)["section_id"] == S["Over"], "recurring tick: the copy moves, the original stays")
t = new(L, S["Doing"], due="2030-01-07", repeat="FREQ=DAILY")
r = drag(t, S["Over"]).json()
x = task(t)
check(x["status"] == 0 and x["section_id"] == S["Doing"] and x["due"] == "2030-01-08", "recurring into done: the next date, back in its column")
u = r.get("section_moved", {}).get(str(t), {})
check(u.get("next_due") == "2030-01-08" and u.get("undo", {}).get("copy_id"), "the answer carries the way back " + str(r)[:120])
c0 = task(u["undo"]["copy_id"])
check(c0["status"] == 2 and c0["section_id"] == S["Over"], "the completed copy stands in the done column")
r = F.post(B + f"/api/tasks/{t}/undo", json=u["undo"])
check(r.ok and r.json()["due"] == "2030-01-07", "undo: the date is back " + r.text[:100])

# ---- review
R, RS = board("Rev", (("Review", ""), ("Look", "review"), ("Over", "done")))
check(F.put(B + f"/api/lists/{R}/members", json={"user_id": GID, "role": "edit"}).ok, "shared")
r = F.put(B + f"/api/lists/{R}/review", json={"on": True, "gate": True, "reviewer": GID})
check(r.ok, "review on " + r.text[:120])
t = new(R, RS["Review"])
check(drag(t, RS["Look"]).ok and task(t).get("review") == "pending", "the column with the meaning review asks for the review, before the name")
t2 = new(R, RS["Look"])
check(drag(t2, RS["Review"]).ok and not task(t2).get("review"), "the column named Review is only the fallback")
check(drag(t, RS["Over"]).status_code == 409 and task(t)["status"] == 0, "the gate refuses the move into done")
check(F.patch(B + f"/api/tasks/{t}", json={"section_id": RS["Over"]}).status_code == 409 and task(t)["section_id"] == RS["Look"], "PATCH: refused, the column stays")

r = F.post(B + f"/api/lists/{R}/rules", json={"name": "Close", "trigger": {"kind": "section", "section_id": RS["Look"]}, "action": {"kind": "move", "section_id": RS["Over"]}})
check(r.status_code in (200, 201), "rule " + r.text[:150])
t3 = new(R, RS["Review"])
check(drag(t3, RS["Look"]).ok and task(t3)["section_id"] == RS["Look"] and task(t3)["status"] == 0, "a rule moving into done stops at the gate, the task stays")
check(all(x["active"] for x in F.get(B + f"/api/lists/{R}/rules").json()["rules"]), "... and the rule is not paused")

# ---- API
t = new(L, S["Doing"])
check(v1(t)["section_kind"] == "progress", "v1: the column's meaning")
o = new(L, S["Later"])
check(v1(o)["section_kind"] == "open", "v1: open column")
n = new(M, None)
check(v1(n)["section_kind"] == "open", "v1: no column = open")
d = new(L, S["Later"])
F.post(B + f"/api/tasks/{d}/complete", json={})
check(v1(d)["section_kind"] == "done", "v1: completed = done")
ids = lambda q: {x["id"] for x in requests.get(V + "/tasks?" + q, headers=H).json()["data"]}  # noqa: E731
check(t in ids(f"list_id={L}&section_kind=progress") and o not in ids(f"list_id={L}&section_kind=progress"), "?section_kind=progress")
check(d in ids(f"list_id={L}&section_kind=done"), "?section_kind=done finds completed tasks without status=")
check({t, o} <= ids(f"list_id={L}&section_kind=open,progress"), "several meanings")
check(n in ids(f"list_id={M}&section_kind=open"), "no column counts as open")
check(requests.get(V + "/tasks?section_kind=maybe", headers=H).status_code == 400, "an unknown meaning: 400")
ls = requests.get(V + f"/lists/{L}", headers=H).json()
check({s["id"]: s["section_kind"] for s in ls["sections"]}[S["No"]] == "rejected", "the list's sections carry section_kind")
r = requests.patch(V + f"/sections/{S['Soon']}", headers=H, json={"section_kind": None})
check(r.ok and r.json()["section_kind"] is None, "v1: the meaning removed")
requests.patch(V + f"/sections/{S['Soon']}", headers=H, json={"section_kind": "open"})
st = lambda tid, k: requests.post(V + f"/tasks/{tid}/state", headers=H, json={"section_kind": k})  # noqa: E731
r = st(t, "review")
check(r.ok and r.json()["section_id"] == S["Check"] and r.json()["section_kind"] == "review", "state: into the review column " + r.text[:100])
r = st(t, "done")
check(r.ok and r.json()["status"] == "done" and r.json()["section_id"] == S["Over"], "state: done")
r = st(t, "rejected")
check(r.ok and r.json()["status"] == "wont_do" and r.json()["section_id"] == S["No"], "state: rejected")
r = st(t, "open")
check(r.ok and r.json()["status"] == "open" and r.json()["section_id"] == S["Later"], "state: open again")
check(st(n, "progress").status_code == 400, "state: no such column: 400")
r = st(n, "done")
check(r.ok and r.json()["status"] == "done", "state: done works without a column")
check(st(t, "maybe").status_code == 400, "state: an unknown value: 400")
check(requests.post(V + f"/tasks/{t}/state", headers=H, json={"section_kind": "open", "x": 1}).status_code == 400, "state: unknown fields: 400")
foreign = G.post(B + "/api/tasks", json={"title": "Not yours"}).json()["id"]
check(st(foreign, "done").status_code == 404 and G.get(B + f"/api/tasks/{foreign}").json()["status"] == 0, "state: another person's task: 404")

# ---- rules fire once
t = new(L, S["Doing"])
r = F.post(B + f"/api/lists/{L}/rules", json={"name": "Say it", "trigger": {"kind": "done"}, "action": {"kind": "comment", "text": "finished"}})
check(r.status_code in (200, 201), "rule " + r.text[:150])
drag(t, S["Over"])
k = requests.get(V + f"/tasks/{t}/comments", headers=H).json()["data"]
check(len([x for x in k if "finished" in str(x)]) == 1, "the done rule fires once for a move " + str(k)[:200])

sys.exit(done("p2577_a_seckind_api"))
