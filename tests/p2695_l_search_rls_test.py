#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.695.0 (#4960): the task search under the row-level security of tasks (2.662.0, #4602). Postgres uses no index for a
condition that is not leakproof (ILIKE) under a policy, so the search's per-field id sets (2.149.0 C, #2515: SELECT id FROM
tasks WHERE title ILIKE ...) scanned the whole table -- every organisation's tasks. Now the visible lists come first and the
text conditions only filter their tasks. Mode workspaces: Alpha (alice + bob), Beta (carol), a person without an organisation.
freelancer-matrix: tasks
 - the plan of the real search request (the app inside the container, the statement recorded and explained on the request's
   own connection, so under the policy with bob's context; 4000 tasks of Beta with a comment each, statistics updated): no scan of tasks without
   an index or recheck condition (a whole-table read); the same for the person without an organisation
 - the hits stay the same: title, notes, link, a code snippet, case-insensitive; Beta's task with the same word is not found
 - the comment search the same: no whole tasks or comments table (its tasks come from the visible lists, their comments
   through the task index; the trigram index of the comments stays unused under the policy)
usage: p2695_l_search_rls_test.py <datadir>"""
import json
import re
import subprocess

import kt
from kt import B, CT, check, dbx, sess
from freelancer_fixture import freelancer

FEAT = "collab,comments"

kt.fresh()
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.post(B + "/api/admin/orgs", json={"name": "Kalmido"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, keep=True)
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.delete(B + f"/api/orgs/{ALPHA}/members/{ids['carol']}").ok, "setup: carol leaves Alpha")

LA = A.post(B + "/api/lists", json={"name": "Alpha list", "org_id": ALPHA}).json()["id"]
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "setup: the Alpha list shared with bob")
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Rechnung Oktober", "list_id": LA}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Paket", "content": "Notiz zur Rechnung am Dienstag", "list_id": LA}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Website", "url": "https://example.com/rechnung-xyz", "list_id": LA}).json()["id"]
T4 = A.post(B + "/api/tasks", json={"title": "Snippet", "list_id": LA}).json()["id"]
dbx("""UPDATE tasks SET snippets='[{"path": "src/rechnung.py", "code": "def hokus(): pass"}]'::jsonb WHERE id=?""", (T4,))
T5 = A.post(B + "/api/tasks", json={"title": "Nothing here", "list_id": LA}).json()["id"]
TB = Ca.post(B + "/api/tasks", json={"title": "Rechnung Beta", "list_id": LB}).json()["id"]
check(dbx("SELECT org_id FROM tasks WHERE id=?", (TB,))[0][0] == BETA, "setup: Beta's task carries Beta (row-level security)")
# a bigger instance: 4000 tasks of Beta (one of 25 with the word), statistics updated -- the planner sees real sizes
dbx("INSERT INTO tasks(list_id, title, created_at, updated_at) SELECT ?, CASE WHEN g % 25 = 0 THEN 'Rechnung Beta ' ELSE 'Beta item ' END || g, "
    "created_at, updated_at FROM tasks, generate_series(1, 4000) g WHERE tasks.id=?", (LB, TB))
check(Ca.post(B + f"/api/tasks/{TB}/comments", json={"body": "Beta note"}).ok, "setup: a comment of Beta")
# 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
dbx("INSERT INTO obj_comments(kind, ref_id, user_id, body, created_at) SELECT 'task', t.id, c.user_id, 'Beta note ' || t.id, c.created_at "
    "FROM obj_comments c, tasks t WHERE c.kind='task' AND c.ref_id=? AND t.list_id=? AND t.id<>?", (TB, LB, TB))
dbx("ANALYZE tasks")
dbx("ANALYZE obj_comments")  # 2.972.0 (#5272): the task comments are rows of obj_comments
check(dbx("SELECT COUNT(*) FROM tasks WHERE org_id=?", (BETA,))[0][0] == 4001, "setup: 4001 tasks of Beta")
check(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Die Rechnung ist raus"}).ok, "setup: a comment")
FID, Fr = freelancer(B, A, "frida")
FT = Fr.post(B + "/api/tasks", json={"title": "Rechnung Frida"}).json()["id"]


def search(s, q):
    r = s.get(B + "/api/tasks", params={"scope": "search", "q": q})
    return {t["id"] for t in r.json().get("tasks", [])} if r.ok else {"error", r.status_code}


# ---- the hits
check(search(Bo, "RECHNUNG") == {T1, T2, T3, T4}, f"bob finds title, notes, link and snippet, any case, not Beta's ({search(Bo, 'RECHNUNG')})")
check(TB in search(Ca, "rechnung") and not search(Ca, "rechnung") & {T1, T2, T3, T4}, "carol finds only Beta's tasks")
check(search(Fr, "rechnung") == {FT}, f"the person without an organisation finds the own task ({search(Fr, 'rechnung')})")
check(search(Bo, "hokus") == {T4}, "the code of a snippet")
check(search(Bo, "zzz-none") == set(), "no hit: empty")

# ---- the plans of the real requests (statement recorded and explained on the request's connection)
PROBE = '''
from kalmido.core import pg
from kalmido.core.config import app as fa
P = []
_ex = pg.Conn.execute
def ex(self, sql, args=None):
    if %r in sql and not sql.startswith("EXPLAIN"):
        P.append([x[0] for x in _ex(self, "EXPLAIN " + sql, args).fetchall()])
    return _ex(self, sql, args)
pg.Conn.execute = ex
cl = fa.test_client()
H = {"X-Requested-With": "kalmido"}
cl.post("/api/auth/login", json={"username": %r, "password": "password123"}, headers=H, base_url="https://localhost")
r = cl.get(%r, headers=H, base_url="https://localhost")
pg.Conn.execute = _ex
print(json.dumps({"status": r.status_code, "plans": P}))
'''


def probe(user, path, marker):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + PROBE % (marker, user, path)], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    try:
        return json.loads(out[-1]) if out else {"err": r.stderr[-800:]}
    except ValueError:
        return {"err": out[-1][:300] + " " + r.stderr[-800:]}


SCAN = re.compile(r"(Seq Scan|Index Only Scan(?: Backward)?|Index Scan(?: Backward)?|Bitmap Heap Scan)(?: using \S+)? on tasks(?: \w+)?\s*(?:\(|$)")


def bare_task_scans(plan):
    """The scan nodes on the table tasks that read it without an index or recheck condition (a whole-table read)."""
    out = []
    for i, line in enumerate(plan):
        m = SCAN.search(line)
        if not m:
            continue
        rest = []
        for x in plan[i + 1:]:
            if "->" in x:
                break
            rest.append(x)
        if m.group(1) == "Seq Scan" or not any("Index Cond" in x or "Recheck Cond" in x for x in rest):
            out.append(" | ".join(y.strip()[:300] for y in [line] + rest[:4]))
    return out


for who in ("bob", "frida"):
    # 2.1102.0 (#5958): the marker without "LIMIT" -- 2.1079.0 (#5655) ordered by ", id DESC" as the last key, the old marker
    # matched no statement any more and the probe explained nothing
    res = probe(who, "/api/tasks?scope=search&q=rechnung", "ORDER BY status, updated_at DESC")  # 2.981.0 (#5278): obj_search, no ILIKE
    plans = res.get("plans") or []
    print(f"info: search plan ({who}):\n" + "\n".join(plans[0] if plans else [str(res)]), flush=True)
    check(res.get("status") == 200 and len(plans) == 1, f"{who}: the search request ran and its statement was explained {str(res)[:300]}")
    bare = [b for p in plans for b in bare_task_scans(p)]
    check(plans and not bare, f"#4960 {who}: the search reads no whole tasks table under row-level security {bare}")
    check(plans and any("tasks" in x and ("Index Cond" in x or "Recheck Cond" in x or "Index Scan" in x) for x in plans[0]),
          f"#4960 {who}: the tasks come through an index")

# 2.972.0 (#5272): the comment search reads the core's obj_comments (collab/msgsearch.py)
res = probe("bob", "/api/search?kind=messages&q=rechnung", "FROM obj_comments m JOIN tasks t")
print("info: comment search plan (bob):\n" + "\n".join((res.get("plans") or [[str(res)]])[0]), flush=True)
check(res.get("status") == 200, f"the comment search request ran {str(res)[:200]}")
cplan = (res.get("plans") or [[]])[0]
check(not [b for b in bare_task_scans(cplan)], "#4960: the comment search reads no whole tasks table " + " || ".join(x.strip()[:110] for x in cplan if "->" in x or "Cond" in x or "Join" in x))
check(not [x for x in cplan if "Seq Scan on obj_comments" in x], "#4960: the comment search reads no whole comments table " + " || ".join(x.strip()[:160] for x in cplan[:14]))

raise SystemExit(kt.done("p2695_l_search_rls"))
