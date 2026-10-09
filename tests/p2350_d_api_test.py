#!/usr/bin/env python3
"""2.35.0 API tests (agent D), own container (start.sh).
 - #1095 code snippets of a task (`snippets`): the web API (PATCH replaces the list, ids stay, author + time stay for an
   unchanged snippet, validation: language, path, line, size, count, unknown keys, a truncated copy), the agent API (GET /
   PATCH / POST /api/v1/tasks, POST /api/v1/tasks/{id}/snippets appends one, 201), rights (another person / an agent outside
   the list -> 404, a viewer -> 403, the scope tasks:write), the task events (at most 10, code cut to 4000 characters,
   truncated, snippets_total), the search finds code, the history line, duplicating via create, a task template keeps them,
   a repeating task's done copy keeps them, the account export, a backup with snippets verifies and restores, OpenAPI
   (schema + path), the MCP tools add_snippet / update_task against the real server
usage: p2350_d_api_test.py <datadir>"""
import json
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
MCP = os.path.join(N, "..", "mcp", "kalmido_mcp.py")
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
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")


def agent(name, scopes):
    r = A.post(B + "/api/admin/agents", json={"scopes": scopes, "username": name, "display_name": name.title()})
    check(r.ok, f"setup: agent {name} " + r.text[:200])
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude", ["read", "tasks:write", "comments"])
RO, ROH = agent("reader", ["read"])
OUT, OUTH = agent("outsider", ["read", "tasks:write"])
SW = A.post(B + "/api/lists", json={"name": "App", "kind": "project", "ptype": "software"}).json()["id"]
check(A.put(B + f"/api/lists/{SW}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the list")
check(A.put(B + f"/api/lists/{SW}/members", json={"user_id": CAROL, "role": "view"}).ok, "setup: carol views the list")
RL = A.post(B + "/api/lists", json={"name": "Reader's list"}).json()["id"]
check(A.put(B + f"/api/lists/{RL}/members", json={"user_id": RO, "role": "edit"}).ok, "setup: the reader in its list")
T = A.post(B + "/api/tasks", json={"title": "Login breaks", "list_id": SW}).json()["id"]
TR = A.post(B + "/api/tasks", json={"title": "For the reader", "list_id": RL}).json()["id"]

# ---- the web API: PATCH replaces the list
PY = "def login(user):\n    if not user:\n        raise ValueError('no user')\n    return True\n"
r = A.patch(B + f"/api/tasks/{T}", json={"snippets": [{"lang": "py", "path": "src/auth.py", "line": 42, "code": PY},
                                                       {"code": "Traceback (most recent call last):\n  KeyError: 'id'"}]})
check(r.ok, "#1095: PATCH with two snippets " + r.text[:300])
sn = r.json().get("snippets") or []
check(len(sn) == 2 and sn[0]["lang"] == "py" and sn[0]["path"] == "src/auth.py" and sn[0]["line"] == 42 and sn[0]["code"] == PY
      and sn[1]["lang"] == "" and sn[1]["path"] is None and sn[1]["line"] is None, "#1095: the snippets as sent (lang '' = automatic)")
check(all(len(s["id"]) == 8 and s["by"] == ALICE and s["updated_at"] for s in sn), "#1095: id, author and time from the server")
check(json.loads(dbx("SELECT snippets FROM tasks WHERE id=?", (T,))[0][0])[0]["code"] == PY, "#1095: stored as JSON in tasks.snippets")
first = sn[0]
# claude changes only the second one: the first keeps author + time
time.sleep(1.1)
r = requests.patch(V + f"/tasks/{T}", headers=CLH, json={"snippets": [first, {**sn[1], "code": "KeyError: 'id' (fixed?)"}]})
check(r.ok, "#1095: the agent replaces the list " + r.text[:200])
s2 = r.json()["snippets"]
check(s2[0]["id"] == first["id"] and s2[0]["by"] == ALICE and s2[0]["updated_at"] == first["updated_at"], "#1095: an unchanged snippet keeps author and time")
check(s2[1]["id"] == sn[1]["id"] and s2[1]["by"] == CL and s2[1]["updated_at"] != sn[1]["updated_at"], "#1095: the changed one is the agent's now")
# validation
bad = [({"snippets": "x"}, "not a list"), ({"snippets": [{"lang": "py"}]}, "no code"), ({"snippets": [{"code": "x", "lang": "Py Thon"}]}, "bad language"),
       ({"snippets": [{"code": "x", "line": 0}]}, "line 0"), ({"snippets": [{"code": "x", "line": "a"}]}, "line text"),
       ({"snippets": [{"code": "x", "path": "a\nb"}]}, "path with a newline"), ({"snippets": [{"code": "x", "path": "p" * 301}]}, "path too long"),
       ({"snippets": [{"code": "x" * 20001}]}, "code too long"), ({"snippets": [{"code": "x"}] * 21}, "21 snippets"),
       ({"snippets": [{"code": "x", "color": "red"}]}, "unknown key"), ({"snippets": [{"code": "x", "truncated": True}]}, "a truncated copy")]
for b, what in bad:
    check(A.patch(B + f"/api/tasks/{T}", json=b).status_code == 400, f"#1095: refused: {what}")
check(len(A.get(B + f"/api/tasks/{T}").json()["snippets"]) == 2, "#1095: nothing changed by the refused requests")
check(A.patch(B + f"/api/tasks/{T}", json={"snippets": [{"code": "x" * 20000}] * 1 + s2}).ok, "#1095: exactly 20000 characters are fine")
check(A.patch(B + f"/api/tasks/{T}", json={"snippets": s2}).ok, "setup: back to two")

# ---- the agent API
j = requests.get(V + f"/tasks/{T}", headers=CLH).json()
check(isinstance(j.get("snippets"), list) and len(j["snippets"]) == 2 and j["snippets"][0]["code"] == PY, "#1095: GET /api/v1/tasks/{id} has snippets")
j = requests.get(V + f"/tasks/{TR}", headers=ROH).json()
check(j.get("snippets") == [], "#1095: a task without snippets: [] in the API")
j = A.get(B + f"/api/tasks/{TR}").json()
check(j.get("snippets") == [] and j.get("snippets_n") == 0, "#1095: one task in the web API: an empty list")
# review M4: lists / the state carry only the number, the single task all of them
stt = {t["id"]: t for t in A.get(B + "/api/state").json()["tasks"]}
check("snippets" not in stt[T] and stt[T].get("snippets_n") == 2 and "snippets" not in stt[TR] and "snippets_n" not in stt[TR],
      "M4: the state carries only snippets_n (and nothing for tasks without) " + json.dumps({k: stt[T].get(k) for k in ("snippets_n",)}))
lt = requests.get(V + "/tasks", headers=CLH, params={"list_id": SW}).json()["data"]
lt = {t["id"]: t for t in lt}
check(T in lt and "snippets" not in lt[T] and lt[T].get("snippets_n") == 2, "M4: the API's task list: only snippets_n " + json.dumps(lt.get(T, {}).get("snippets_n")))
check(requests.get(V + f"/tasks/{T}", headers=CLH).json()["snippets_n"] == 2, "M4: GET one task: snippets + snippets_n")
DIFF = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1,2 +1,2 @@\n-    if not user:\n+    if user is None:\n"
r = requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": DIFF, "lang": "diff", "path": "src/auth.py", "line": 2})
check(r.status_code == 201 and r.json()["snippet"]["code"] == DIFF and r.json()["snippet"]["by"] == CL and len(r.json()["task"]["snippets"]) == 3,
      "#1095: POST /api/v1/tasks/{id}/snippets appends one (201) " + r.text[:300])
check(requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": "  "}).status_code == 400, "#1095: empty code -> 400")
check(requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": "x", "title": "y"}).status_code == 400, "#1095: an unknown field -> 400")
check(requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": "x", "lang": "c c"}).status_code == 400, "#1095: a bad language -> 400")
r = requests.post(V + "/tasks", headers=CLH, json={"title": "With code", "list_id": SW, "snippets": [{"code": "SELECT 1;", "lang": "sql"}]})
check(r.status_code == 201 and r.json()["snippets"][0]["lang"] == "sql", "#1095: POST /api/v1/tasks with snippets " + r.text[:200])
# rights: other people / agents outside the list -> 404, a viewer -> 403, the scope
check(requests.post(V + f"/tasks/{T}/snippets", headers=OUTH, json={"code": "x"}).status_code == 404, "#1095: an agent outside the list -> 404")
check(requests.get(V + f"/tasks/{T}", headers=OUTH).status_code == 404, "#1095: ... and cannot read the task")
check(Bo.patch(B + f"/api/tasks/{T}", json={"snippets": []}).status_code == 404, "#1095: another person (no access) -> 404")
btok = Bo.post(B + "/api/me/tokens", json={"name": "bob", "scopes": ["read", "tasks:write"]}).json()["token"]
check(requests.post(V + f"/tasks/{T}/snippets", headers={"Authorization": "Bearer " + btok}, json={"code": "x"}).status_code == 404,
      "#1095: another person's token -> 404 (no snippet of a foreign task)")
check(Ca.patch(B + f"/api/tasks/{T}", json={"snippets": []}).status_code == 403, "#1095: a viewer cannot change them (403)")
check(len(Ca.get(B + f"/api/tasks/{T}").json()["snippets"]) == 3, "#1095: ... but sees them")
check(requests.post(V + f"/tasks/{TR}/snippets", headers=ROH, json={"code": "x"}).status_code == 403, "#1095: without tasks:write -> 403")
for _ in range(17):
    requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": "print(1)"})
check(len(A.get(B + f"/api/tasks/{T}").json()["snippets"]) == 20, "setup: 20 snippets")
check(requests.post(V + f"/tasks/{T}/snippets", headers=CLH, json={"code": "x"}).status_code == 400, "#1095: the 21st -> 400")

# ---- the task events: shortened copies
LONG = "\n".join(f"line {i:05d} " + "x" * 40 for i in range(200))  # ~10000 characters
TE = A.post(B + "/api/tasks", json={"title": "Event task", "list_id": SW, "snippets": [{"code": LONG, "lang": "text"}] + [{"code": f"n{i}"} for i in range(11)]}).json()["id"]
check(A.patch(B + f"/api/tasks/{TE}", json={"assignee_id": CL}).ok, "setup: assigned to claude")
ev = wait_for(lambda: [e for e in requests.get(V + "/agent/events", headers=CLH, params={"since": 0, "limit": 500}).json()["data"]
                       if e["event"] == "assigned" and e["data"]["task"]["id"] == TE])
et = ev[0]["data"]["task"] if ev else {}
check(len(et.get("snippets", [])) == 10 and et.get("snippets_total") == 12, "#1095: the event carries at most 10 snippets + snippets_total " + str(et.get("snippets_total")))
check(et["snippets"][0]["truncated"] is True and len(et["snippets"][0]["code"]) == 4000 and "truncated" not in et["snippets"][1],
      "#1095: code cut to 4000 characters, truncated: true only there")
check(requests.patch(V + f"/tasks/{TE}", headers=CLH, json={"snippets": et["snippets"]}).status_code == 400, "#1095: sending the shortened copy back -> 400")
check(len(requests.get(V + f"/tasks/{TE}", headers=CLH).json()["snippets"][0]["code"]) == len(LONG), "#1095: get_task has the full code")

# ---- search, history, duplicate, template, repeat, export
r = A.get(B + "/api/tasks", params={"scope": "search", "q": "raise ValueError"}).json()
check(any(t["id"] == T for t in r["tasks"]), "#1095: the search finds text in a snippet")
r = requests.get(V + "/search", headers=CLH, params={"q": "is None"}).json()
check(any(t["id"] == T for t in r.get("data", r.get("tasks", []))), "#1095: the API search too")
hit = lambda q: any(t["id"] == T for t in A.get(B + "/api/tasks", params={"scope": "search", "q": q}).json()["tasks"])  # noqa: E731
check(hit("src/auth.py"), "M4: the search finds the file path of a snippet")
check(not hit("2026-") and not hit("updated_at") and not hit('"by"') and not hit("lang"), "M4: no hits on the snippets' metadata (time, keys)")
act = dbx("SELECT kind, data FROM activity WHERE task_id=? AND kind='snippets' ORDER BY id DESC", (T,))
check(act and json.loads(act[0][1])["n"] == 20, "#1095: the history line 'changed the code snippets' with the number")
r = A.post(B + "/api/templates", json={"task_id": T})
check(r.ok, "setup: template " + r.text[:200])
tpl = r.json()
check("def login" in json.dumps((tpl["data"].get("task") or {}).get("snippets")), "#1095: the template keeps the snippets")
r = A.post(B + f"/api/templates/{tpl['id']}/apply", json={"list_id": SW})
check(r.ok and len(r.json()["task"].get("snippets", [])) == 20 and r.json()["task"]["snippets"][0]["code"] == PY, "#1095: applying the template brings them " + r.text[:200])
TRP = A.post(B + "/api/tasks", json={"title": "Weekly check", "list_id": SW, "due": "2026-10-01", "repeat": "FREQ=WEEKLY",
                                      "snippets": [{"code": "make check", "lang": "sh"}]}).json()["id"]
check(A.post(B + f"/api/tasks/{TRP}/complete").ok, "setup: a repeating task completed")
done = dbx("SELECT snippets FROM tasks WHERE title='Weekly check' AND status=2")
check(done and "make check" in done[0][0], "#1095: the done copy of a repeating task keeps its snippets")
ex = A.get(B + "/api/export.json").json()
check(any(t["id"] == T and "def login" in (t.get("snippets") or "") for t in ex["tasks"]), "#1095: the account export carries them")

# ---- OpenAPI
spec = requests.get(V + "/openapi.json", headers=CLH).json()
op = spec["paths"].get("/tasks/{id}/snippets", {}).get("post") or {}
check(op.get("x-kalmido-scope") == "write" or "write" in json.dumps(op), "#1095: OpenAPI documents POST /tasks/{id}/snippets")
check("Snippet" in spec["components"]["schemas"] and "snippets" in spec["components"]["schemas"]["TaskInput"]["properties"],
      "#1095: OpenAPI: the Snippet schema and snippets in TaskInput")

# ---- MCP against this server
ENV = {**os.environ, "KALMIDO_URL": B + "/", "KALMIDO_TOKEN": CLH["Authorization"].split(" ", 1)[1]}
p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
seq = [0]


def rpc(method, params=None):
    seq[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": seq[0], "method": method, **({"params": params} if params is not None else {})}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
check("add_snippet" in tools and "snippets" in tools["update_task"]["inputSchema"]["properties"], "#1095: MCP add_snippet + update_task snippets")
TM = A.post(B + "/api/tasks", json={"title": "MCP task", "list_id": SW}).json()["id"]
res = rpc("tools/call", {"name": "add_snippet", "arguments": {"task_id": TM, "code": "console.log(1)", "lang": "js", "path": "app.js", "line": 3}})["result"]
check(res["isError"] is False and res["structuredContent"]["snippet"]["path"] == "app.js", "#1095: MCP add_snippet " + json.dumps(res)[:300])
res = rpc("tools/call", {"name": "update_task", "arguments": {"task_id": TM, "snippets": []}})["result"]
check(res["isError"] is False and not A.get(B + f"/api/tasks/{TM}").json().get("snippets"), "#1095: MCP update_task snippets [] removes all")
res = rpc("tools/call", {"name": "add_snippet", "arguments": {"task_id": T, "code": "x"}})["result"]
check(res["isError"] is True, "#1095: MCP add_snippet: the 21st is refused")
p.stdin.close()
p.wait(5)

# ---- a backup with snippets verifies and restores (the 2.34 rollback image ignores the new column)
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: a backup with snippets verifies " + r.text[:200])
dbx("UPDATE tasks SET snippets='' WHERE id=?", (T,), write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
A = sess("alice")
check(len(A.get(B + f"/api/tasks/{T}").json().get("snippets", [])) == 20, "backup: the snippets are back after the restore")

print(f"p2350_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
