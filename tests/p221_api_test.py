#!/usr/bin/env python3
"""2.2.1 API tests.
#358 the agents' audit log:
 - every request with an AGENT's token is one row: method, route template (/api/v1/tasks/{tid}), status, task / list id from
   the path or the JSON body, duration; never query values or bodies (a secret title / search text is nowhere in the table)
 - denied calls are logged too: paused agent (403), over its hard usage limit (429), wrong scope (403); requests of a
   person's token and invalid tokens are not
 - GET /api/admin/agents/audit + /api/admin/agents/{id}/audit (admins only, 404 for a person's id): filters agent / status
   class / denied / day, paging (before), 400 on a bad filter, CSV export (header, rows, file name); many requests at once
   all land (the batched writer)
 - GET /api/v1/admin/agents/{id}/audit: scope admin-read (a plain read token 403, an agent's token 403), {data,
   next_cursor}, unknown parameter 400; documented in the OpenAPI spec (AuditPage, the unknown_field error)
 - retention: KALMIDO_AUDIT_DAYS=1 removes older rows (own container, restarted); KALMIDO_AUDIT_DAYS=0 logs nothing
#359 unknown fields:
 - /api/v1 task create / update / subtask, list create, comment create: 400 {"error": {"code": "unknown_field", "fields"}},
   nothing changed; `content` is accepted as an alias of `notes` (both with different values: 400, the same value: fine)
 - web /api: unknown fields are ignored as before but named in X-Kalmido-Unknown-Fields + ONE warning line in the log per
   endpoint and set of names; `notes` is accepted as an alias of `content`; known fields (_prev, add_tags, ltags …) no header;
   dep_shift is taken at list creation too (was PATCH only); comment create (JSON + form) / update, list update
Starts its OWN containers (start.sh).
usage: p221_api_test.py <datadir>"""
import csv
import io
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(env=(), keep=False):
    if not keep:
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(DATA)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=" ".join(env)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)

    def patch(self, p, **k):
        return self.req("PATCH", p, **k)


def db():
    return sqlite3.connect(os.path.join(DATA, "tasks.db"))


def rows():
    con = db()
    try:
        return con.execute("SELECT agent_id, method, route, status, task_id, list_id, ms, day FROM agent_audit ORDER BY id").fetchall()
    finally:
        con.close()


def audit(s, q="", aid=None):
    return s.get(B + (f"/api/admin/agents/{aid}/audit" if aid else "/api/admin/agents/audit") + (("?" + q) if q else ""))


def logs():
    return subprocess.run(["docker", "logs", CONTAINER], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout


def setup():
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
    a = sess("alice")
    r = a.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
    assert r.ok, r.text
    bob = r.json()["id"]
    bo = sess("bob")
    for x in (a, bo):
        x.patch(B + "/api/settings", json={"lang": "en"})
    return a, bo, bob


def new_agent(a, name):
    r = a.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title()})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], Api(r.json()["token"])


def ptok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + "-".join(scopes), "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return Api(r.json()["token"])


# ================================================================== #358 audit log
start()
A, Bo, BOB = setup()
AG, cl = new_agent(A, "claude")
AG2, cl2 = new_agent(A, "helper")
L = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
for x in (AG, AG2):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": x, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Shared", "list_id": L}).json()["id"]
SECRET = "TOPSECRET-TITLE-4711"

check(cl.get("/me").ok, "agent: GET /me")
check(cl.get(f"/tasks/{T}").ok, "agent: GET a task")
check(cl.get("/tasks", params={"list_id": L, "q": "SEARCH-WORD-0815"}).status_code in (200, 400), "agent: a list of tasks with query values")
r = cl.post("/tasks", json={"title": SECRET, "list_id": L})
check(r.status_code == 201, f"agent: create a task ({r.status_code})")
NT = r.json()["id"]
check(cl.patch(f"/tasks/{NT}", json={"notes": "secret notes"}).ok, "agent: patch a task")
check(cl.get("/nope").status_code == 404, "agent: an unknown route 404")
check(cl.get("/tasks/999999").status_code == 404, "agent: a task it cannot see 404")
check(cl2.get("/lists").ok, "second agent: GET /lists")
PT = ptok(A, ("read", "write"))
check(PT.get("/me").ok, "a person's token: not logged")
check(requests.get(V + "/me", headers={"Authorization": "Bearer abk_" + "x" * 43}).status_code == 401, "invalid token: not logged")
# paused (kill switch): every call 403, logged
assert A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": False}).ok
check(cl.get("/lists").status_code == 403, "paused: 403")
check(cl.get(f"/tasks/{T}").status_code == 403, "paused: 403 on a task")
assert A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": True}).ok
# write with a read-only person token: 403 but not an agent -> not logged; an agent over its hard limit: 429, logged
assert A.patch(B + f"/api/admin/agents/{AG2}", json={"limits": {"period": "day", "metric": "tokens", "hard": 5}}).ok
cl2.post("/agent/usage", json={"model": "m", "input_tokens": 50, "output_tokens": 0})
st = 0
for _ in range(20):
    st = cl2.get("/lists").status_code
    if st == 429:
        break
    time.sleep(0.3)
check(st == 429, f"over the hard limit: 429 ({st})")
assert A.patch(B + f"/api/admin/agents/{AG2}", json={"limits": None}).ok

r = audit(A)
j = r.json()
check(r.ok and isinstance(j["data"], list) and j["days"] == 90 and {x["id"] for x in j["agents"]} >= {AG, AG2}, f"GET audit: {r.status_code}")
D = j["data"]
routes = [(x["method"], x["route"], x["status"]) for x in D if x["agent_id"] == AG]
check(("GET", "/api/v1/me", 200) in routes, "row: GET /api/v1/me 200")
check(("GET", "/api/v1/tasks/{tid}", 200) in routes, f"route template with {{tid}}: {routes[:12]}")
check(("POST", "/api/v1/tasks", 201) in routes and ("PATCH", "/api/v1/tasks/{tid}", 200) in routes, "create + patch logged")
check(("GET", "(no route)", 404) in routes, "unknown route: (no route), 404")
check(("GET", "/api/v1/tasks/{tid}", 404) in routes, "a task it cannot see: 404 logged")
check(len([x for x in D if x["agent_id"] == AG and x["status"] == 403 and x["denied"]]) == 2, "paused: both 403 logged + denied")
check(any(x["agent_id"] == AG2 and x["status"] == 429 and x["denied"] for x in D), "429 logged + denied")
check(D == sorted(D, key=lambda x: -x["id"]), "newest first")
g = next(x for x in D if x["route"] == "/api/v1/tasks/{tid}" and x["status"] == 200 and x["method"] == "GET")
check(g["task_id"] == T and isinstance(g["ms"], int) and g["ms"] >= 0 and g["agent_name"] == "Claude", f"task id from the path, ms, name: {g}")
p = next(x for x in D if x["method"] == "POST" and x["route"] == "/api/v1/tasks")
check(p["list_id"] == L and p["task_id"] is None, f"list id from the body: {p}")
pa = next(x for x in D if x["method"] == "PATCH")
check(pa["task_id"] == NT, "patch: task id")
agents_in_log = {x[0] for x in rows()}
check(agents_in_log <= {AG, AG2}, f"only agents in the log: {agents_in_log}")
con = db()
dump = "\n".join(con.iterdump())
con.close()
aud_lines = [ln for ln in dump.splitlines() if "agent_audit" in ln]
check(aud_lines and not any(SECRET in ln or "SEARCH-WORD" in ln or "secret notes" in ln for ln in aud_lines), "no body / query value in the log")
check(all("?" not in x["route"] for x in D), "no query strings in routes")

# filters, paging
r = audit(A, f"agent_id={AG2}")
check(r.ok and r.json()["data"] and all(x["agent_id"] == AG2 for x in r.json()["data"]), "filter: agent")
r = audit(A, "status=denied")
check(r.ok and len(r.json()["data"]) == 3 and all(x["status"] in (401, 403, 429) for x in r.json()["data"]), f"filter: denied ({len(r.json()['data'])})")
r = audit(A, "status=2xx")
check(r.ok and all(200 <= x["status"] < 300 for x in r.json()["data"]) and r.json()["data"], "filter: 2xx")
r = audit(A, "status=4xx")
check(r.ok and all(400 <= x["status"] < 500 for x in r.json()["data"]) and len(r.json()["data"]) >= 5, "filter: 4xx")
check(audit(A, "status=teapot").status_code == 400, "filter: bad status 400")
check(audit(A, "day=2020-13-01").status_code == 400, "filter: bad day 400")
today = date.today().isoformat()
check(len(audit(A, f"day={today}").json()["data"]) == len(D), "filter: today")
check(audit(A, f"day={(date.today() - timedelta(days=1)).isoformat()}").json()["data"] == [], "filter: yesterday empty")
p1 = audit(A, "limit=3").json()
check(len(p1["data"]) == 3 and p1["next_before"] == p1["data"][-1]["id"], "paging: limit + next_before")
p2 = audit(A, f"limit=3&before={p1['next_before']}").json()
check(len(p2["data"]) == 3 and p2["data"][0]["id"] < p1["data"][-1]["id"], "paging: before")
check(audit(A, "limit=0").status_code == 400 and audit(A, "limit=501").status_code == 400, "paging: limit bounds")
r = audit(A, aid=AG)
check(r.ok and r.json()["data"] and all(x["agent_id"] == AG for x in r.json()["data"]), "per agent route")
check(audit(A, aid=BOB).status_code == 404 and audit(A, aid=9999).status_code == 404, "per agent route: a person / nobody 404")
check(audit(Bo).status_code == 403 and audit(Bo, aid=AG).status_code == 403, "non-admin: 403")
check(requests.get(B + "/api/admin/agents/audit").status_code in (401, 403), "without login: refused")

# CSV
r = audit(A, "format=csv&status=denied")
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "agent-activity-all-" in r.headers.get("Content-Disposition", ""),
      f"CSV: type + name {r.headers.get('Content-Disposition')}")
cr = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
check(cr[0][:5] == ["Time", "Agent", "Method", "Route", "Status"] and len(cr) == 4 and {x[4] for x in cr[1:]} <= {"401", "403", "429"}, f"CSV rows: {cr[:2]}")
check(audit(Bo, "format=csv").status_code == 403, "CSV: admins only")

# many requests at once: all land (batched writer, >= 200 flushes early)
before = len(rows())
t0 = time.monotonic()
for _ in range(250):
    cl2.get("/me")
dt = time.monotonic() - t0
n = len(audit(A, f"agent_id={AG2}&limit=500").json()["data"])
check(len(rows()) - before >= 250 or n >= 250, f"250 requests logged ({len(rows()) - before})")
print(f"250 agent requests in {dt:.1f} s", flush=True)
time.sleep(2.6)
check(len(rows()) >= before + 250, "the writer stored them without a read (within ~2 s)")

# v1: scope admin-read
AR = ptok(A, ("read", "admin-read"))
r = AR.get(f"/admin/agents/{AG}/audit", params={"status": "denied"})
check(r.ok and set(r.json()) == {"data", "next_cursor"} and len(r.json()["data"]) == 2, f"v1 admin-read: {r.status_code} {r.text[:200]}")
r = AR.get(f"/admin/agents/{AG}/audit", params={"limit": 2})
check(r.ok and r.json()["next_cursor"] and len(AR.get(f"/admin/agents/{AG}/audit", params={"limit": 2, "cursor": r.json()["next_cursor"]}).json()["data"]) == 2,
      "v1: cursor paging")
check(AR.get(f"/admin/agents/{AG}/audit", params={"x": 1}).status_code == 400, "v1: unknown parameter 400")
check(AR.get(f"/admin/agents/{BOB}/audit").status_code == 404, "v1: a person's id 404")
check(PT.get(f"/admin/agents/{AG}/audit").status_code == 403, "v1: token without admin-read 403")
check(cl.get(f"/admin/agents/{AG}/audit").status_code == 403, "v1: an agent's token 403")
spec = requests.get(V + "/openapi.json").json()
check("/admin/agents/{id}/audit" in spec["paths"] and spec["paths"]["/admin/agents/{id}/audit"]["get"]["x-kalmido-scope"] == "admin-read"
      and "AuditPage" in spec["components"]["schemas"], "spec: audit route")
err = spec["components"]["schemas"]["Error"]["properties"]["error"]["properties"]
check("unknown_field" in err["code"]["enum"] and "fields" in err, "spec: unknown_field + fields")
check("content" in spec["components"]["schemas"]["TaskInput"]["properties"], "spec: content alias")

# ================================================================== #359 unknown fields
def uerr(r, fields):
    try:
        e = r.json()["error"]
    except (ValueError, KeyError):
        return False
    return r.status_code == 400 and e.get("code") == "unknown_field" and e.get("fields") == fields and isinstance(e.get("message"), str)


def ntasks():
    con = db()
    try:
        return con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        con.close()


n0 = ntasks()
check(uerr(PT.post("/tasks", json={"title": "x", "foo": 1, "bar": 2}), ["bar", "foo"]), "v1 task create: unknown_field + fields")
check(ntasks() == n0, "v1: nothing created")
r = PT.patch(f"/tasks/{T}", json={"title": "Changed?", "colour": "red"})
check(uerr(r, ["colour"]), "v1 task update: unknown_field")
check(A.get(B + f"/api/tasks/{T}").json()["title"] == "Shared", "v1: nothing changed")
check(uerr(PT.post(f"/tasks/{T}/subtasks", json={"title": "s", "zzz": 1}), ["zzz"]), "v1 subtask: unknown_field")
check(uerr(PT.post("/lists", json={"name": "x", "owner_id": 2}), ["owner_id"]), "v1 list create: unknown_field")
check(uerr(PT.post(f"/tasks/{T}/comments", json={"body": "hi", "text": "hi"}), ["text"]), "v1 comment: unknown_field")
check(PT.post(f"/tasks/{T}/comments", json={"body": "hi"}).status_code == 201, "v1 comment: known fields fine")
r = PT.post("/tasks", json={"title": "Alias", "list_id": L, "content": "via content"})
check(r.status_code == 201 and r.json()["notes"] == "via content", f"v1: content = alias of notes ({r.status_code})")
AT = r.json()["id"]
check(PT.patch(f"/tasks/{AT}", json={"content": "c2"}).json()["notes"] == "c2", "v1 patch: content alias")
r = PT.patch(f"/tasks/{AT}", json={"content": "a", "notes": "b"})
check(r.status_code == 400 and r.json()["error"]["code"] == "invalid", "v1: notes + content differing: 400")
check(PT.patch(f"/tasks/{AT}", json={"content": "same", "notes": "same"}).json()["notes"] == "same", "v1: notes + content equal: fine")
check(uerr(PT.post(f"/tasks/{AT}/complete", json={"x": 1}), ["x"]), "v1 complete: unknown_field")

# web API: warning + header, never an error
r = A.post(B + "/api/tasks", json={"title": "Web", "list_id": L, "notes": "web notes"})
check(r.ok and r.json()["content"] == "web notes" and "X-Kalmido-Unknown-Fields" not in r.headers, "web: notes = alias of content, no header")
WT = r.json()["id"]
r = A.post(B + "/api/tasks", json={"title": "Web2", "list_id": L, "wibble": 1, "wobble": 2})
check(r.ok and r.headers.get("X-Kalmido-Unknown-Fields") == "wibble, wobble", f"web task create: 200 + header ({r.headers.get('X-Kalmido-Unknown-Fields')})")
A.post(B + "/api/tasks", json={"title": "Web3", "list_id": L, "wibble": 1, "wobble": 2})
time.sleep(0.5)
lg = logs()
check(lg.count("POST /api/tasks: unknown field(s) ignored: wibble, wobble") == 1, "web: one warning line (not per request)")
check("Web2" not in "\n".join(x for x in lg.splitlines() if "unknown field" in x), "web: the warning has no values")
r = A.patch(B + f"/api/tasks/{WT}", json={"notes": "n2", "_prev": {"content": "web notes"}})
check(r.ok and r.json()["content"] == "n2" and "X-Kalmido-Unknown-Fields" not in r.headers, "web patch: notes alias + _prev known")
r = A.patch(B + f"/api/tasks/{WT}", json={"priority": 3, "prio": 5})
check(r.ok and r.json()["priority"] == 3 and r.headers.get("X-Kalmido-Unknown-Fields") == "prio", "web patch: header, known fields applied")
check(A.patch(B + f"/api/tasks/{WT}", json={"content": "a", "notes": "b"}).status_code == 400, "web: content + notes differing 400")
r = A.patch(B + f"/api/tasks/{WT}", json={"add_tags": ["x"], "ltags": [], "fields": {}, "_act": "x"})
check(r.ok and "X-Kalmido-Unknown-Fields" not in r.headers, "web patch: add_tags / ltags / fields / _act known")
r = A.post(B + "/api/lists", json={"name": "Deps", "kind": "project", "dep_shift": True, "icon": "x"})
check(r.ok and r.json()["dep_shift"] == 1 and r.headers.get("X-Kalmido-Unknown-Fields") == "icon", f"web list create: dep_shift stored, icon named ({r.text[:120]})")
r = A.patch(B + f"/api/lists/{L}", json={"color": "#abc", "colour": "#abc"})
check(r.ok and r.headers.get("X-Kalmido-Unknown-Fields") == "colour", "web list update: header")
check("X-Kalmido-Unknown-Fields" not in A.patch(B + f"/api/lists/{L}", json={"rate": "", "_prev": {}}).headers, "web list update: rate / _prev known")
r = A.post(B + f"/api/tasks/{WT}/comments", json={"body": "hello", "text": "hello"})
check(r.ok and r.headers.get("X-Kalmido-Unknown-Fields") == "text", "web comment create: header")
CID = r.json()["id"]
r = A.post(B + f"/api/tasks/{WT}/comments", data={"body": "with file", "extra": "1"}, files={"file": ("a.txt", b"hi", "text/plain")})
check(r.ok and r.headers.get("X-Kalmido-Unknown-Fields") == "extra", f"web comment form: header ({r.status_code})")
r = A.patch(B + f"/api/comments/{CID}", json={"body": "edited", "mentions": []})
check(r.ok and r.json()["body"] == "edited" and r.headers.get("X-Kalmido-Unknown-Fields") == "mentions", "web comment update: header")
check("X-Kalmido-Unknown-Fields" not in A.post(B + f"/api/tasks/{WT}/comments", json={"body": "plain"}).headers, "web comment: known -> no header")

# ================================================================== retention + switched off
con = db()
old = (date.today() - timedelta(days=5)).isoformat()
con.execute("INSERT INTO agent_audit(agent_id,at,day,method,route,status,ms) VALUES(?,?,?,?,?,?,0)", (AG, old + "T10:00:00.000+00:00", old, "GET", "/api/v1/me", 200))
con.commit()
con.close()
check(any(x[7] == old for x in rows()), "old row inserted")
start(["-e KALMIDO_AUDIT_DAYS=1"], keep=True)
ok = False
for _ in range(30):
    if not any(x[7] == old for x in rows()):
        ok = True
        break
    time.sleep(0.5)
check(ok, "KALMIDO_AUDIT_DAYS=1: the old row is removed")
check(any(x[7] == today for x in rows()), "today's rows stay")
start(["-e KALMIDO_AUDIT_DAYS=0"], keep=True)
time.sleep(1.5)
A = sess("alice")
n1 = len(rows())
cl.get("/me")
time.sleep(2.6)
check(len(rows()) == 0 or len(rows()) <= n1, "KALMIDO_AUDIT_DAYS=0: nothing logged")
check(audit(A).json()["days"] == 0, "days 0 reported")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
