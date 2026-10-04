#!/usr/bin/env python3
"""2.18.0 API tests (#430 milestones as tasks + "Software 2" B / D: milestones with progress, burndown, release notes), own
container (start.sh). The one-shot migration of the overview milestones (list_milestones, 2.7.1) into milestone tasks on
start-up AND after restoring an old backup that still holds such rows; the compatibility routes (web + v1, ids = task ids);
ms / milestone_id validation (top level, no subtasks, same list, moves / deleting for good / turning it off clear the link, the trash keeps it); rights;
activity lines; agent events; v1 fields + filters + OpenAPI; export, list templates; burndown + release notes data; the MCP
tool get_milestone."""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def dbx(q, a=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


def healthy():
    try:
        return requests.get(B + "/api/health", timeout=2).ok
    except requests.RequestException:
        return False


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_BACKUPS=1 -e KALMIDO_BACKUP_MAX_MB=5")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,kanban,cal,timeline,progress", "lang": "en", "tour": "done"})
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("carol", "Carol"), ("dave", "Dave"), ("zed", "Zed")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, C, D, Z = (sess(u) for u in ("bob", "carol", "dave", "zed"))
for s in (Bo, C, D, Z):
    s.patch(B + "/api/settings", json={"features": "collab,agents,comments,progress", "tour": "done", "lang": "en"})
L = A.post(B + "/api/lists", json={"name": "App", "kind": "project", "tickets": 1}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Other", "kind": "project"}).json()["id"]
for u, role in (("bob", "edit"), ("carol", "view"), ("dave", "participant")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"}).json()
AG = Api(ag["token"])
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"}).ok
SEC = A.post(B + "/api/sections", json={"list_id": L, "name": "Backlog"}).json().get("id")
T0 = A.post(B + "/api/tasks", json={"title": "Existing task", "list_id": L}).json()

# ================================================================== migration (start-up) + an old backup
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
dbx("INSERT INTO list_milestones(list_id,name,day,done,created_by,created_at) VALUES(?,?,?,?,?,?)", (L, "Beta", "2026-11-01", 0, ids["bob"], now))
dbx("INSERT INTO list_milestones(list_id,name,day,done,created_by,created_at) VALUES(?,?,?,?,?,?)", (L, "Alpha", "2026-10-01", 1, 999, now))
n0 = len(A.get(B + "/api/admin/backups").json()["items"])
check(A.post(B + "/api/admin/backups").status_code == 202, "a backup with the old milestone rows")
until(lambda: len(A.get(B + "/api/admin/backups").json()["items"]) > n0 and not A.get(B + "/api/admin/backups").json()["running"], 40)
OLD_BK = A.get(B + "/api/admin/backups").json()["items"][0]["name"]
subprocess.run(["docker", "restart", CT], capture_output=True)
time.sleep(1)
check(until(healthy, 40), "the app comes back after the restart")
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_ntfy.py"])
check(dbx("SELECT COUNT(*) FROM list_milestones")[0][0] == 0, "start-up: the old rows are gone (the table stays)")
rows = {r[0]: r for r in dbx("SELECT title, ms, due, status, created_by, section_id, parent_id, sort, list_id FROM tasks WHERE ms=1")}
check(set(rows) == {"Alpha", "Beta"} and all(r[8] == L and r[5] is None and r[6] is None for r in rows.values()), f"start-up: two milestone tasks in the list {rows}")
check(rows["Alpha"][2] == "2026-10-01" and rows["Alpha"][3] == 2 and rows["Alpha"][4] == 1, "done milestone -> done task; unknown creator -> the list owner")
check(rows["Beta"][3] == 0 and rows["Beta"][4] == ids["bob"], "open milestone, created by its creator")
maxs = dbx("SELECT MAX(sort) FROM tasks WHERE list_id=? AND ms=0", (L,))[0][0]
check(all(r[7] > maxs for r in rows.values()), "migrated milestones go to the end of the list")
A = sess("alice")
st = A.get(B + "/api/state").json()
lst = next(x for x in st["lists"] if x["id"] == L)
MS_A = next(t for t in st["tasks"] if t["title"] == "Alpha")["id"]
MS_B = next(t for t in st["tasks"] if t["title"] == "Beta")["id"]
check([m["id"] for m in lst["milestones"]] == [MS_A, MS_B] and lst["milestones"][1] == {"id": MS_B, "name": "Beta", "day": "2026-11-01", "done": False},
      f"/api/state: l.milestones keep their shape, ids = task ids {lst['milestones']}")
t_b = next(t for t in st["tasks"] if t["id"] == MS_B)
t_0 = next(t for t in st["tasks"] if t["id"] == T0["id"])
check(t_b.get("ms") == 1 and "milestone_id" not in t_b, "web dict: ms on a milestone")
check("ms" not in t_0 and "milestone_id" not in t_0, "web dict: ms / milestone_id omitted on other tasks")
ov = A.get(B + f"/api/lists/{L}/overview").json()
check([m["name"] for m in ov["milestones"]] == ["Alpha", "Beta"] and ov["milestones"][0]["done"] is True, "overview: the milestone block from the tasks")

# ================================================================== compatibility routes (web + v1)
r = A.post(B + f"/api/lists/{L}/milestones", json={"name": "GA", "day": "2026-12-01"})
GA = r.json()["id"]
check(r.ok and r.json() == {"id": GA, "name": "GA", "day": "2026-12-01", "done": False}, f"web POST: a milestone task {r.text}")
g = A.get(B + f"/api/tasks/{GA}").json()
check(g.get("ms") == 1 and g["list_id"] == L and g["due"] == "2026-12-01" and g["parent_id"] is None, "… which is a task with ms = 1")
check(A.patch(B + f"/api/lists/{L}/milestones/{GA}", json={"done": True}).json()["done"] is True and A.get(B + f"/api/tasks/{GA}").json()["status"] == 2,
      "web PATCH done -> the task is completed")
check(A.patch(B + f"/api/lists/{L}/milestones/{GA}", json={"done": False, "day": "2026-12-02", "name": "GA 1"}).json() == {"id": GA, "name": "GA 1", "day": "2026-12-02", "done": False},
      "web PATCH: reopen, new day + name")
check(A.patch(B + f"/api/lists/{L}/milestones/{T0['id']}", json={"done": True}).status_code == 404, "a normal task is no milestone here: 404")
check(C.post(B + f"/api/lists/{L}/milestones", json={"name": "x", "day": "2026-12-01"}).status_code == 403, "a viewer cannot add milestones")
check(A.post(B + f"/api/lists/{L}/milestones", json={"name": "x"}).status_code == 400, "web POST needs a day")
check(A.delete(B + f"/api/lists/{L}/milestones/{GA}").ok and dbx("SELECT deleted_at FROM tasks WHERE id=?", (GA,))[0][0], "web DELETE -> trash")
check(A.post(B + f"/api/tasks/{GA}/restore").ok, "restore it")
tw = A.post(B + "/api/me/tokens", json={"name": "w", "scopes": ["read", "tasks:write", "structure", "delete"]}).json()["token"]
W = Api(tw)
d = W.get(f"/lists/{L}/milestones").json()["data"]
check([m["id"] for m in d] == [MS_A, MS_B, GA], f"v1 GET: by day, task ids {d}")
r = W.post(f"/lists/{L}/milestones", json={"name": "RC", "day": "2026-11-15"})
RC = r.json()["id"]
check(r.status_code == 201 and W.get(f"/tasks/{RC}").json()["milestone"] is True, "v1 POST creates a milestone task")
check(W.patch(f"/lists/{L}/milestones/{RC}", json={"done": True}).json()["done"] is True, "v1 PATCH")
check(W.delete(f"/lists/{L}/milestones/{RC}").status_code == 204 and W.get(f"/tasks/{RC}").status_code == 404, "v1 DELETE -> trash")

# ================================================================== ms / milestone_id: validation, links, activity
P1 = A.post(B + "/api/tasks", json={"title": "Parent", "list_id": L}).json()["id"]
check(A.post(B + "/api/tasks", json={"title": "x", "parent_id": P1, "ms": 1}).status_code == 400, "a milestone cannot be a subtask")
check(A.post(B + "/api/tasks", json={"title": "x", "parent_id": MS_B}).status_code == 400, "no subtask under a milestone")
check(A.post(B + "/api/tasks", json={"title": "Sub", "parent_id": P1}).ok and A.patch(B + f"/api/tasks/{P1}", json={"ms": 1}).status_code == 400,
      "a task with subtasks cannot become a milestone")
check(A.patch(B + f"/api/tasks/{MS_B}", json={"parent_id": P1}).status_code == 400, "a milestone cannot be indented")
check(A.post(B + "/api/tasks", json={"title": "x", "ms": "yes"}).status_code == 400, "ms must be a boolean / 0 / 1")
M2 = A.post(B + "/api/tasks", json={"title": "Other list milestone", "list_id": L2, "ms": True}).json()
check(M2.get("ms") == 1, "creating a milestone (ms true)")
check(A.patch(B + f"/api/tasks/{T0['id']}", json={"milestone_id": M2["id"]}).status_code == 400, "a milestone of another list: 400")
check(A.patch(B + f"/api/tasks/{T0['id']}", json={"milestone_id": P1}).status_code == 400, "a task that is no milestone: 400")
check(A.patch(B + f"/api/tasks/{T0['id']}", json={"milestone_id": T0["id"]}).status_code == 400, "itself: 400")
check(A.post(B + "/api/tasks", json={"title": "y", "list_id": L, "milestone_id": 999999}).status_code == 400, "an unknown milestone: 400")
r = A.patch(B + f"/api/tasks/{T0['id']}", json={"milestone_id": MS_B})
check(r.ok and r.json()["milestone_id"] == MS_B, "a task joins the milestone")
check(A.patch(B + f"/api/tasks/{MS_A}", json={"milestone_id": MS_B}).ok and "milestone_id" not in A.get(B + f"/api/tasks/{MS_A}").json(),
      "a milestone belongs to no milestone (ignored)")
acts = [a["kind"] for a in A.get(B + f"/api/tasks/{T0['id']}/timeline").json().get("items", []) if "kind" in a]
acts = acts or [x[0] for x in dbx("SELECT kind FROM activity WHERE task_id=?", (T0["id"],))]
check("milestone" in acts, f"activity: setting the milestone {acts}")
dd = json.loads(dbx("SELECT data FROM activity WHERE task_id=? AND kind='milestone' ORDER BY id DESC", (T0["id"],))[0][0])
check(dd.get("title") == "Beta" and dd.get("id") == MS_B, f"the activity line names the milestone {dd}")
check(C.patch(B + f"/api/tasks/{T0['id']}", json={"milestone_id": None}).status_code == 403, "a viewer cannot change it")
T1 = A.post(B + "/api/tasks", json={"title": "Login page", "list_id": L, "ttype": "feature", "milestone_id": MS_B}).json()
check(T1.get("milestone_id") == MS_B, "create with a milestone")
T2 = A.post(B + "/api/tasks", json={"title": "Crash on start", "list_id": L, "ttype": "bug"}).json()
T3 = A.post(B + "/api/tasks", json={"title": "Polish", "list_id": L}).json()
r = A.post(B + "/api/tasks/batch", json={"ids": [T2["id"], T3["id"]], "action": "patch", "data": {"milestone_id": MS_B}})
check(r.ok and not r.json()["errors"] and all(A.get(B + f"/api/tasks/{i}").json().get("milestone_id") == MS_B for i in (T2["id"], T3["id"])), "batch: set milestone")
r = A.post(B + "/api/tasks/batch", json={"ids": [T3["id"]], "action": "patch", "data": {"milestone_id": M2["id"]}})
check(r.json()["errors"] and A.get(B + f"/api/tasks/{T3['id']}").json().get("milestone_id") == MS_B, "batch: a milestone of another list is refused")
# moves, trash, turning off
TM = A.post(B + "/api/tasks", json={"title": "Moves away", "list_id": L, "milestone_id": MS_B}).json()["id"]
check("milestone_id" not in A.patch(B + f"/api/tasks/{TM}", json={"list_id": L2}).json(), "moving to another list clears the milestone")
TM2 = A.post(B + "/api/tasks", json={"title": "Dragged away", "list_id": L, "milestone_id": MS_B}).json()["id"]
A.post(B + "/api/tasks/reorder", json={"items": [{"id": TM2, "sort": 1, "list_id": L2}]})
check(dbx("SELECT milestone_id FROM tasks WHERE id=?", (TM2,))[0][0] is None, "… also by drag and drop (reorder)")
MX = A.post(B + "/api/tasks", json={"title": "Throwaway", "list_id": L, "ms": 1}).json()["id"]
TX = A.post(B + "/api/tasks", json={"title": "In throwaway", "list_id": L, "milestone_id": MX}).json()["id"]
A.delete(B + f"/api/tasks/{MX}")
# 2.18.0 (owner decision): a milestone in the trash keeps its tasks' links; restoring it brings them back, deleting it for good drops them
check(dbx("SELECT milestone_id FROM tasks WHERE id=?", (TX,))[0][0] == MX, "a milestone in the trash: its tasks keep the link")
check(A.post(B + f"/api/tasks/{MX}/restore").ok and A.get(B + f"/api/tasks/{TX}").json().get("milestone_id") == MX, "restored: the task belongs to it again")
check(A.get(B + f"/api/tasks/{MX}/milestone").json().get("progress", {}).get("total") == 1, "restored: the milestone counts its task again")
A.delete(B + f"/api/tasks/{MX}")
check(A.delete(B + f"/api/tasks/{MX}?hard=1").ok and not dbx("SELECT 1 FROM tasks WHERE id=?", (MX,)), "the milestone deleted for good")
check(dbx("SELECT milestone_id FROM tasks WHERE id=?", (TX,))[0][0] is None, "deleted for good: the link goes")
MY = A.post(B + "/api/tasks", json={"title": "Turned off", "list_id": L, "ms": 1}).json()["id"]
TY = A.post(B + "/api/tasks", json={"title": "In turned off", "list_id": L, "milestone_id": MY}).json()["id"]
check("ms" not in A.patch(B + f"/api/tasks/{MY}", json={"ms": 0}).json() and dbx("SELECT milestone_id FROM tasks WHERE id=?", (TY,))[0][0] is None,
      "turning a milestone off clears it on its tasks")
check(any(json.loads(x[0]).get("on") is False for x in dbx("SELECT data FROM activity WHERE task_id=? AND kind='ms'", (MY,))), "activity: ms on / off")
# undo / redo-like replay with _prev (the client omits ms = 0)
check(A.patch(B + f"/api/tasks/{MY}", json={"ms": 1, "_prev": {"ms": None}}).json().get("conflicts") == [], "_prev ms null matches a stored 0 (no false conflict)")
A.patch(B + f"/api/tasks/{MY}", json={"ms": 0})

# ================================================================== participant / outsider + the milestone report
TD = A.post(B + "/api/tasks", json={"title": "Dave's task", "list_id": L, "assignee_id": ids["dave"], "milestone_id": MS_B}).json()["id"]
check(D.get(B + f"/api/tasks/{MS_B}/milestone").status_code == 404, "a participant does not see the milestone (not his task)")
check(Z.get(B + f"/api/tasks/{MS_B}/milestone").status_code == 404, "an outsider: 404")
check(A.get(B + f"/api/tasks/{T0['id']}/milestone").status_code == 404, "the report only for milestone tasks")
A.post(B + f"/api/tasks/{T1['id']}/complete")
A.post(B + f"/api/tasks/{T2['id']}/complete")
A.post(B + f"/api/tasks/{T3['id']}/complete", json={"status": -1})
rep = C.get(B + f"/api/tasks/{MS_B}/milestone").json()
check(rep["progress"] == {"done": 3, "total": 5, "percent": 60}, f"progress: closed / all (a viewer reads it) {rep['progress']}")
check([x["status"] for x in rep["tasks"]][:2] == ["open", "open"] and {x["id"] for x in rep["tasks"]} == {T0["id"], T1["id"], T2["id"], T3["id"], TD}, "its tasks, open first")
bd = rep["burndown"]
check(bd["days"] and bd["days"][-1]["open"] == 2 and bd["days"][-1]["day"] == bd["end"] and bd["due"] == "2026-11-01", f"burndown: open tasks per day up to today {bd['days'][-1:]}")
check(bd["ideal"] == [{"day": bd["start"], "open": 5}, {"day": "2026-11-01", "open": 0}], f"burndown: the ideal line {bd['ideal']}")
rn = rep["release_notes"]
check(rn.startswith("## Beta (2026-11-01)") and "### Features" in rn and f"- #{T1['id']} Login page" in rn and "### Fixes" in rn
      and f"- #{T2['id']} Crash on start" in rn and "Polish" not in rn, f"release notes: completed tasks by type, not won't do {rn!r}")
check(rn.index("### Features") < rn.index("### Fixes"), "Features before Fixes")
D.patch(B + "/api/settings", json={"lang": "de"})
A.patch(B + "/api/settings", json={"lang": "de"})
check("### Neue Funktionen" in A.get(B + f"/api/tasks/{MS_B}/milestone").json()["release_notes"], "release notes in the user's language")
A.patch(B + "/api/settings", json={"lang": "en"})
rep2 = A.get(B + f"/api/tasks/{MS_A}/milestone").json()
check(rep2["progress"]["total"] == 0 and "No completed tasks yet." in rep2["release_notes"] and rep2["burndown"]["ideal"] == [], "an empty milestone (due in the past: no ideal line)")
M3 = A.post(B + "/api/tasks", json={"title": "Plain", "list_id": L2, "ms": 1}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Plain one", "list_id": L2, "milestone_id": M3}).json()["id"]
A.post(B + f"/api/tasks/{TP}/complete")
rn3 = A.get(B + f"/api/tasks/{M3}/milestone").json()
check(rn3["release_notes"] == f"## Plain\n\n- #{TP} Plain one\n" and rn3["milestone"]["due"] is None, f"without ticket types: one list; an undated milestone {rn3['release_notes']!r}")

# ================================================================== v1 + events + OpenAPI + MCP
v = W.get(f"/tasks/{T1['id']}").json()
check(v["milestone"] is False and v["milestone_id"] == MS_B, "v1 task: milestone + milestone_id")
check(W.get(f"/tasks/{MS_B}").json()["milestone"] is True, "v1: a milestone")
ms_ids = [x["id"] for x in W.get("/tasks", params={"milestone": "true", "list_id": L, "status": "all"}).json()["data"]]
check(sorted(ms_ids) == sorted([MS_A, MS_B, GA, MY]) or sorted(ms_ids) == sorted([MS_A, MS_B, GA]), f"v1 filter milestone=true {ms_ids}")
check(MS_B not in [x["id"] for x in W.get("/tasks", params={"milestone": "false", "list_id": L}).json()["data"]], "v1 filter milestone=false")
of = sorted(x["id"] for x in W.get("/tasks", params={"milestone_id": MS_B, "status": "all"}).json()["data"])
check(of == sorted([T0["id"], T1["id"], T2["id"], T3["id"], TD]), f"v1 filter milestone_id {of}")
check(W.get("/tasks", params={"milestone": "maybe"}).status_code == 400, "v1: invalid filter 400")
r = W.post("/tasks", json={"title": "v1 milestone", "list_id": L, "milestone": True, "due": "2027-01-01"})
V1M = r.json()["id"]
check(r.status_code == 201 and r.json()["milestone"] is True, "v1 POST milestone: true")
check(W.post("/tasks", json={"title": "x", "milestone": 1}).status_code == 400, "v1: milestone must be a boolean")
r = W.patch(f"/tasks/{T0['id']}", json={"milestone_id": V1M})
check(r.ok and r.json()["milestone_id"] == V1M, "v1 PATCH milestone_id")
check(W.patch(f"/tasks/{T0['id']}", json={"milestone_id": None}).json()["milestone_id"] is None, "v1 PATCH milestone_id null")
rep_v1 = W.get(f"/tasks/{MS_B}/milestone")
check(rep_v1.ok and rep_v1.json()["progress"]["total"] == 4, f"v1 GET /tasks/{{id}}/milestone {rep_v1.status_code} {rep_v1.text[:200]}")
spec = requests.get(B + "/api/v1/openapi.json").json()
check("/tasks/{id}/milestone" in spec["paths"] and "milestone" in spec["components"]["schemas"]["Task"]["properties"]
      and "MilestoneReport" in spec["components"]["schemas"], "OpenAPI: the report, the task fields")
check(any(p.get("name") == "milestone_id" for p in spec["paths"]["/tasks"]["get"].get("parameters", [])), "OpenAPI: the filters")
cur = AG.get("/agent/events?since=0&limit=500").json()["cursor"]
TA = A.post(B + "/api/tasks", json={"title": "For the agent", "list_id": L, "milestone_id": MS_B, "assignee_id": ag["id"]}).json()["id"]
ev = until(lambda: [e for e in AG.get(f"/agent/events?since={cur}").json()["data"] if (e["data"].get("task") or {}).get("id") == TA])
check(ev and ev[0]["data"]["task"]["milestone_id"] == MS_B and ev[0]["data"]["task"]["milestone"] is False, f"agent events carry milestone fields {ev[:1]}")
spec_m = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(N, "..", "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(mcp)
tools = {t[0]: t for t in mcp.TOOLS}
seen = []


class FakeApi:
    def call(self, m, path, *a, **k):
        seen.append((m, path, a, k))
        return {"ok": True}


check("get_milestone" in tools and mcp.TOOL_SCOPE.get("get_milestone", "read") == "read", "MCP: get_milestone (read-only)")
tools["get_milestone"][3](FakeApi(), {"task_id": MS_B})
check(seen[-1][:2] == ("GET", f"/tasks/{MS_B}/milestone"), f"MCP: calls the API {seen[-1:]}")
mcp.t_list_tasks(FakeApi(), {"milestone": True, "milestone_id": MS_B})
check(seen[-1][2][0].get("milestone") == "true" and seen[-1][2][0].get("milestone_id") == MS_B, f"MCP list_tasks filters {seen[-1]}")
check("milestone" in mcp.TASK_FIELDS and "milestone_id" in mcp.TASK_FIELDS, "MCP: create / update_task know the fields")

# ================================================================== export, templates
ex = A.get(B + "/api/export.json").json()
et = {t["id"]: t for t in ex["tasks"]}
check(et[MS_B]["ms"] == 1 and et[T1["id"]]["milestone_id"] == MS_B, "export: ms + milestone_id")
A.post(B + f"/api/tasks/{T1['id']}/reopen")
tp = A.post(B + "/api/templates", json={"list_id": L, "name": "App template"}).json()
nodes = tp["data"]["tasks"]
msn = next(n for n in nodes if n["title"] == "Beta")
check(msn.get("ms") == 1 and next(n for n in nodes if n["title"] == "Login page").get("mk") == msn["k"], "list template keeps the milestone + its tasks")
nl = A.post(B + f"/api/templates/{tp['id']}/apply", json={"name": "App 2"}).json()["list_id"]
nt = {t["title"]: t for t in A.get(B + "/api/state").json()["tasks"] if t["list_id"] == nl}
check(nt["Beta"].get("ms") == 1 and nt["Login page"].get("milestone_id") == nt["Beta"]["id"], "applied: a new milestone with its task")
tt = A.post(B + "/api/templates", json={"task_id": MS_B}).json()
nt2 = A.post(B + f"/api/templates/{tt['id']}/apply", json={"list_id": L2}).json()["task"]
check(nt2.get("ms") == 1, "a task template of a milestone makes a milestone")

# ================================================================== restore an old backup: migrated again
r = A.post(B + "/api/admin/backups/restore", json={"name": OLD_BK, "confirm": "RESTORE"})
check(r.ok, f"restore of the backup from before the migration {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM list_milestones")[0][0] == 0, "after the restore: the old rows are migrated again")
rt = sorted(x[0] for x in dbx("SELECT title FROM tasks WHERE ms=1 AND list_id=?", (L,)))
check(rt == ["Alpha", "Beta"], f"… into milestone tasks {rt}")
A = sess("alice")
check([m["name"] for m in A.get(B + f"/api/lists/{L}/overview").json()["milestones"]] == ["Alpha", "Beta"], "overview after the restore")

subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"\np2180_ms_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
