#!/usr/bin/env python3
"""2.36.0 API tests, part C (#1116): the Paperless connection is removed, its data stays.
 - an instance that used Paperless (rows in paperless_links, pl_conns, pl_conn_users, pl_tokens, list_paperless and
   users.paperless_access = 1, written here with sqlite) starts and runs with the old PAPERLESS_* variables still set
 - every former Paperless route answers 404 (for an admin too); no answer carries Paperless data (task, state, project
   overview, users list, export)
 - normal work goes on: tasks, comments, a project overview, an agent, deleting a list / a person with old rows
 - backup + restore keep the old tables with their rows (no data lost on the way back)
Starts its OWN container (start.sh). usage: p2360_c_api_test.py <datadir>"""
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
PL_ENV = ["-e PAPERLESS_TOKEN=pl-old-env-token", "-e PAPERLESS_API=http://127.0.0.1:8082",
          "-e PAPERLESS_PUBLIC_URL=https://paperless.example.test", "-e KALMIDO_SECRET_KEY=" + "B" * 43 + "="]
PL_TABLES = ("paperless_links", "pl_conns", "pl_conn_users", "pl_tokens", "list_paperless")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(keep=False):
    env = dict(os.environ, EXTRA=" ".join(PL_ENV), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), path=None):
    c = sqlite3.connect(path or os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def counts(path=None):
    return {t: dbx(f"SELECT COUNT(*) FROM {t}", path=path)[0][0] for t in PL_TABLES}


# ================================================================== an instance that used Paperless
ok, out = start()
assert ok, out
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
P = A.post(B + "/api/lists", json={"name": "Renovation", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["bob"], "role": "edit"})
T = A.post(B + "/api/tasks", json={"title": "Roof offer", "list_id": P}).json()["id"]
AT = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("offer.pdf", b"%PDF-1.4 offer", "application/pdf")}).json()["attachments"][0]["id"]
L2 = A.post(B + "/api/lists", json={"name": "Old project", "kind": "project"}).json()["id"]
now = "2026-09-01T00:00:00Z"
dbx("UPDATE users SET paperless_access=1 WHERE id IN (1, ?)", (ids["bob"],))
dbx("INSERT INTO pl_conns(id,kind,owner_id,name,url,created_at) VALUES(1,'server',NULL,'Office','https://office.example.test',?)", (now,))
dbx("INSERT INTO pl_conns(id,kind,owner_id,name,url,created_at) VALUES(2,'personal',?,'Private','https://bob.example.test',?)", (ids["bob"], now))
dbx("INSERT INTO pl_conn_users(conn_id,user_id) VALUES(1,?)", (ids["bob"],))
dbx("INSERT INTO pl_tokens(conn_id,user_id,token,updated_at) VALUES(1,?,'v1.sealed-a',?)", (ids["bob"], now))
dbx("INSERT INTO pl_tokens(conn_id,user_id,token,updated_at) VALUES(2,?,'v1.sealed-b',?)", (ids["bob"], now))
dbx("INSERT INTO paperless_links(task_id,doc_id,title,correspondent,created,status,added_at,conn_id,added_by) "
    "VALUES(?,4711,'Salary slip 2026','Employer','2026-01-01','ok',?,1,1)", (T, now))
dbx("INSERT INTO paperless_links(task_id,doc_id,title,status,added_at,att_id) VALUES(?,NULL,'offer.pdf','pending',?,?)", (T, now, AT))
dbx("INSERT INTO list_paperless(list_id,conn_id,doc_id,title,correspondent,created,added_by,added_at) "
    "VALUES(?,NULL,42,'Building permit','City','2026-02-02',1,?)", (P, now))
dbx("INSERT INTO list_paperless(list_id,conn_id,doc_id,title,added_by,added_at) VALUES(?,NULL,43,'Old plan',1,?)", (L2, now))
dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,1,'paperless','{\"title\": \"Salary slip 2026\", \"conn\": 1}',?)", (T, now))
before = counts()
check(before == {"paperless_links": 2, "pl_conns": 2, "pl_conn_users": 1, "pl_tokens": 2, "list_paperless": 2}, f"rows written: {before}")

# ---- restart with the old PAPERLESS_* variables: the app starts and ignores them
ok, out = start(keep=True)
check(ok, "the app starts with PAPERLESS_* set and the old rows present: " + out[-300:])
check(requests.get(B + "/api/health").ok, "health ok")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("Traceback" not in logs.stdout + logs.stderr, "no traceback in the server log")
A, Bo = sess("alice"), sess("bob")
check(counts() == before, "the start changed none of the old rows")
check(dbx("SELECT paperless_access FROM users WHERE id=?", (ids["bob"],))[0][0] == 1, "users.paperless_access stays")

# ================================================================== every former route: 404
ROUTES = [("GET", "/api/paperless/search?q=x"), ("GET", "/api/paperless/thumb/8"), ("GET", "/api/paperless/conns"),
          ("POST", "/api/paperless/conns"), ("PATCH", "/api/paperless/conns/1"), ("DELETE", "/api/paperless/conns/2"),
          ("DELETE", "/api/paperless/conns/1/token"), ("POST", "/api/paperless/conns/1/test"),
          ("GET", "/api/admin/paperless"), ("POST", "/api/admin/paperless"), ("PATCH", "/api/admin/paperless/1"),
          ("DELETE", "/api/admin/paperless/1"), ("POST", f"/api/tasks/{T}/paperless"), ("DELETE", "/api/paperless-links/1"),
          ("POST", f"/api/attachments/{AT}/to-paperless"), ("POST", f"/api/lists/{P}/paperless"),
          ("DELETE", f"/api/lists/{P}/paperless/1")]
for s_, who in ((A, "admin"), (Bo, "member")):
    bad = [(m, p, r.status_code) for m, p in ROUTES for r in [s_.request(m, B + p, json={"doc_id": 1, "name": "x", "url": "https://x.test", "token": "t"})]
           if r.status_code != 404]
    check(not bad, f"{who}: every Paperless route 404: {bad}")
check(counts() == before, "the 404s changed nothing")

# ================================================================== no Paperless data in any answer
st = A.get(B + "/api/state")
check(st.ok and "paperless" not in st.json(), "state: no Paperless part")
check("Salary slip" not in st.text and "Building permit" not in st.text, "state: no document titles")
t = A.get(B + f"/api/tasks/{T}").json()
check("paperless" not in t and [a["name"] for a in t["attachments"]] == ["offer.pdf"], f"task: attachment stays, no Paperless field: {list(t)[:8]}")
ov = Bo.get(B + f"/api/lists/{P}/overview").json()
check("paperless" not in ov and "task_paperless" not in ov and [f["name"] for f in ov["task_files"]] == ["offer.pdf"], "project overview: no Paperless parts")
tl = A.get(B + f"/api/tasks/{T}/timeline").json()
check(not [a for a in tl.get("activity", []) if a["kind"].startswith("paperless")], "timeline: no Paperless entries")
us = A.get(B + "/api/users").json()["users"]
check(all("paperless_access" not in u for u in us), "users list: no Paperless flag")
ex = A.get(B + "/api/export.json")
check(ex.ok and "paperless" not in ex.json() and "paperless_links" not in ex.json() and "Salary slip" not in ex.text, "export: no Paperless data")
check(not [a for a in ex.json()["activity"] if a["kind"] == "paperless" and a["data"] != "{}"], "export: old activity without document data")
tok = A.post(B + "/api/me/tokens", json={"name": "c", "scopes": ["read"]}).json().get("token")
vt = requests.get(V + f"/tasks/{T}", headers={"Authorization": "Bearer " + tok}) if tok else None
check(vt is not None and vt.ok and "paperless" not in vt.json(), "v1 task: no Paperless field")
spec = requests.get(V + "/openapi.json")
check(spec.ok and "/paperless" not in spec.text and "task_paperless" not in spec.text, "OpenAPI: no Paperless paths or fields")
check(A.patch(B + "/api/settings", json={"paperless_keep": "1"}).status_code in (200, 400), "the old setting paperless_keep is no switch any more")

# ================================================================== normal work goes on
r = Bo.post(B + "/api/tasks", json={"title": "Call the roofer", "list_id": P})
check(r.status_code in (200, 201), "bob creates a task in the project")
check(Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "offer looks fine"}).ok, "bob comments")
check(A.patch(B + f"/api/tasks/{T}", json={"title": "Roof offer (checked)"}).ok, "alice edits the task")
r = A.post(B + "/api/admin/agents", json={"username": "helper-bot", "display_name": "Helper"})
check(r.status_code in (200, 201), f"an agent can be created: {r.status_code} {r.text[:120]}")
check(A.patch(B + f"/api/users/{ids['carl']}", json={"kind": "agent"}).ok and dbx("SELECT kind, paperless_access FROM users WHERE id=?", (ids["carl"],))[0] == ("agent", 0),
      "a person becomes an agent (never Paperless access)")
A.patch(B + f"/api/lists/{L2}", json={"archived": 1})
r = A.delete(B + f"/api/lists/{L2}")
check(r.ok, f"a list with an old Paperless row can be deleted (archived first): {r.status_code} {r.text[:120]}")
r = A.delete(B + f"/api/users/{ids['bob']}")
check(r.ok, f"a person with old connections and tokens can be deleted: {r.status_code} {r.text[:120]}")
check(dbx("SELECT COUNT(*) FROM pl_tokens WHERE user_id=?", (ids["bob"],))[0][0] == 0
      and dbx("SELECT COUNT(*) FROM pl_conns WHERE kind='personal' AND owner_id=?", (ids["bob"],))[0][0] == 0,
      "... their own connection and tokens go with them (as before)")
check(dbx("SELECT COUNT(*) FROM pl_conns WHERE kind='server'")[0][0] == 1 and dbx("SELECT COUNT(*) FROM paperless_links")[0][0] == 2,
      "the shared connection and the task links stay")
mid = counts()

# ================================================================== backup + restore keep the tables
n0 = len(A.get(B + "/api/admin/backups").json()["items"])
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"back up now: {r.status_code} {r.text[:120]}")
t0, j = time.time(), {}
while time.time() - t0 < 40:
    j = A.get(B + "/api/admin/backups").json()
    if not j["running"] and (len(j["items"]) > n0 or j["last_error"]):
        break
    time.sleep(0.4)
check(len(j.get("items", [])) > n0 and not j.get("last_error"), f"backup done: {j.get('last_error')}")
name = j["items"][0]["name"]
z = A.get(B + f"/api/admin/backups/{name}/download")
with tempfile.TemporaryDirectory() as td:
    try:
        zf = zipfile.ZipFile(io.BytesIO(z.content))
        dbn = next(n for n in zf.namelist() if n.endswith("tasks.db"))
        zf.extract(dbn, td)
        inside = counts(os.path.join(td, dbn))
    except (zipfile.BadZipFile, StopIteration) as e:
        inside = str(e)
check(inside == mid, f"the backup holds the old tables with their rows: {inside}")
dbx("DELETE FROM list_paperless")
A.post(B + "/api/tasks", json={"title": "after the backup", "list_id": P})
r = A.post(B + "/api/admin/backups/restore", json={"name": name, "confirm": "RESTORE"})
check(r.ok and r.json().get("ok"), f"restored: {r.text[:200]}")
time.sleep(1.0)
check(counts() == mid, f"after the restore the old rows are back: {counts()}")
A = sess("alice")
titles = [x["title"] for x in A.get(B + "/api/state").json()["tasks"]]
check("Roof offer (checked)" in titles and "after the backup" not in titles, "the restore brought the state of the backup")
check(A.post(B + "/api/tasks", json={"title": "after the restore", "list_id": P}).ok, "the app works after the restore")
check(A.get(B + "/api/paperless/conns").status_code == 404, "still no Paperless route after the restore")

print(f"p2360_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
