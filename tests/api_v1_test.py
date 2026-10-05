#!/usr/bin/env python3
"""REST API /api/v1 with personal access tokens: token creation (format, entropy, SHA-256 at rest, shown once, prefix),
scopes (read / write / admin-read, admin rights re-checked per request), expiry, revoke, disabled / deleted users,
bearer only (no session cookie, no proxy header, no CSRF header needed), IDOR across users and roles, every endpoint
(me, lists, tasks CRUD + complete / reopen / delete to the trash, subtasks, tags, comments, time entries, habits,
search, admin), filters, cursor pagination, validation errors, the error format, history lines "via API", the
collaboration / time switches (instance + personal), the per-token rate limit, the invalid-token limit + admin alert,
the OpenAPI 3.1 spec (validated with openapi-spec-validator when installed, every route documented) and KALMIDO_API=0.
Starts its OWN test containers (start.sh).
usage: api_v1_test.py <datadir>"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
T = date.today()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def start(env=()):
    subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=" ".join(env)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def tok(s, name="t", scopes=("read", "write"), days=None, expect=201):
    r = s.post(B + "/api/me/tokens", json={"name": name, "scopes": list(scopes), "expires_days": days})
    assert r.status_code == expect, (r.status_code, r.text)
    return r.json() if r.status_code == 201 else r


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def get(self, path, **kw):
        return requests.get(V + path, headers=self.h, **kw)

    def post(self, path, js=None, **kw):
        return requests.post(V + path, headers=self.h, json=js, **kw)

    def patch(self, path, js=None):
        return requests.patch(V + path, headers=self.h, json=js)

    def delete(self, path):
        return requests.delete(V + path, headers=self.h)


def is_err(r, code, kind=None):
    try:
        e = r.json()["error"]
    except (ValueError, KeyError, TypeError):
        return False
    return r.status_code == code and isinstance(e.get("message"), str) and e.get("code") == (kind or e.get("code"))


# ================================================================== 1. feature off (KALMIDO_API=0)
start(["-e KALMIDO_API=0"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
check(A.get(B + "/api/state").json()["api"] == {"enabled": False}, "API off: state says disabled")
check(A.post(B + "/api/me/tokens", json={"name": "x"}).status_code == 409, "API off: no new tokens")
dbx("INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,created_at) VALUES(1,'old',?,'abk_x','read,write','2026-01-01')",
    (hashlib.sha256(b"abk_" + b"a" * 43).hexdigest(),))
r = requests.get(V + "/me", headers={"Authorization": "Bearer abk_" + "a" * 43})
check(is_err(r, 404, "not_found"), f"API off: /api/v1 answers 404 even with a stored token ({r.status_code})")
check(requests.get(V + "/openapi.json").status_code == 404, "API off: no spec either")

# ================================================================== 2. main container
start(["-e KALMIDO_API_RATE=200", "-e KALMIDO_ADMIN_ALERTS=1", "-e KALMIDO_ADMIN_ALERT_WINDOW=3"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u in ("bob", "carol", "dave"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).ok, u
A.patch(B + "/api/users/1", json={"ntfy_topic": "admintopic"})
Bo, Ca = sess("bob"), sess("carol")
check(A.get(B + "/api/state").json()["api"] == {"enabled": True}, "state: API on")

# ---- token creation
j = tok(A, "cli", ("read", "write"))
TA = j["token"]
check(re.fullmatch(r"abk_[A-Za-z0-9_-]{43}", TA) is not None, "token format abk_ + 43 chars (256 bits) " + TA[:8])
check(j["prefix"] == TA[:12] and j["scopes"] == ["read", "write"] and j["expires_at"] is None, "token: prefix, scopes, no expiry " + str(j))
row = dbx("SELECT token_hash, prefix FROM api_tokens WHERE id=?", (j["id"],))[0]
check(row[0] == hashlib.sha256(TA.encode()).hexdigest(), "token: SHA-256 at rest")
raw = open(os.path.join(DATA, "tasks.db"), "rb").read() + (open(os.path.join(DATA, "tasks.db-wal"), "rb").read()
                                                          if os.path.exists(os.path.join(DATA, "tasks.db-wal")) else b"")
check(TA.encode() not in raw and TA[12:].encode() not in raw, "token: the token itself is nowhere in the database")
lst = A.get(B + "/api/me/tokens").json()
check(lst["enabled"] and len(lst["tokens"]) == 1 and "token" not in lst["tokens"][0] and "token_hash" not in lst["tokens"][0],
      "token list: never the token or its hash")
check(tok(A, "", expect=400).status_code == 400, "token: name required")
check(A.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["root"]}).status_code == 400, "token: unknown scope refused")
check(A.post(B + "/api/me/tokens", json={"name": "x", "expires_days": 0.5}).status_code == 400, "token: bad expiry refused")
check(A.post(B + "/api/me/tokens", json={"name": "x", "expires_days": 99999}).status_code == 400, "token: expiry capped")
check(Bo.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read", "admin-read"]}).status_code == 403, "token: admin-read only for admins")
check(requests.post(B + "/api/me/tokens", json={"name": "x"}, headers=H).status_code == 401, "token: needs a login")
check(A.post(B + "/api/me/tokens", json={"name": "x"}, headers={"X-Requested-With": ""}).status_code == 403, "token: creation needs the CSRF header")
jr = tok(A, "ro", ("read",))
TR = jr["token"]
TW = tok(A, "wonly", ("write",))["token"]
check(tok(A, "wonly2", ("write",))["scopes"] == ["read", "write"], "token: write implies read")
TADM = tok(A, "adm", ("read", "admin-read"))["token"]
TB = tok(Bo, "bob")["token"]
TC = tok(Ca, "carol")["token"]
a, ar, aw, adm, b, cc = Api(TA), Api(TR), Api(TW), Api(TADM), Api(TB), Api(TC)
toks = [tok(Ca, f"n{i}") for i in range(17)]  # carol: 18 tokens now, the limit is 20
check(Ca.post(B + "/api/me/tokens", json={"name": "a"}).status_code == 201 and Ca.post(B + "/api/me/tokens", json={"name": "b"}).status_code == 201
      and Ca.post(B + "/api/me/tokens", json={"name": "c"}).status_code == 409, "token: at most 20 per user")

# ---- authentication
r = requests.get(V + "/me")
check(is_err(r, 401, "unauthorized") and "Bearer" in r.headers.get("WWW-Authenticate", ""), f"no token: 401 + WWW-Authenticate ({r.status_code})")
check(A.get(V + "/me").status_code == 401, "session cookie alone: 401 (tokens only)")
r = requests.get(BP + "/api/v1/me", headers={"Remote-User": "alice"})
check(r.status_code == 401, f"proxy header on the proxy port: 401 ({r.status_code})")
r = requests.get(BP + "/api/v1/me", headers={"Remote-User": "alice", "Authorization": "Bearer abk_" + "x" * 43})
check(r.status_code == 401, "spoofed proxy header + bogus token: 401")
r = requests.get(BP + "/api/v1/me", headers={"Remote-User": "bob", "Authorization": "Bearer " + TA})
check(r.ok and r.json()["username"] == "alice", "proxy port: the token decides, never the header")
for bad in ("abk_" + "x" * 43, TA[:-1], TA + "x", "abc", "Basic " + TA, TA.upper()):
    check(requests.get(V + "/me", headers={"Authorization": "Bearer " + bad}).status_code == 401, "invalid token refused: " + bad[:12])
check(requests.get(V + "/me", headers={"Authorization": "Basic " + base64.b64encode(b"alice:password123").decode()}).status_code == 401,
      "basic auth refused")
me = a.get("/me").json()
check(me["username"] == "alice" and me["is_admin"] and me["token"]["name"] == "cli" and me["api_version"] == "1.0"
      and me["features"] == {"collaboration": True, "time_tracking": True, "dependencies": True, "custom_fields": True, "comments": True}, "me " + str(me))
check(dbx("SELECT last_used_at IS NOT NULL FROM api_tokens WHERE token_hash=?", (hashlib.sha256(TA.encode()).hexdigest(),))[0][0] == 1,
      "last_used_at recorded")
r = requests.post(V + "/tasks", headers={"Authorization": "Bearer " + TA}, json={"title": "no csrf header"})
check(r.status_code == 201, f"bearer requests need no CSRF header ({r.status_code})")

# ---- scopes
check(is_err(ar.post("/tasks", {"title": "x"}), 403, "forbidden"), "read token: no writes")
check(ar.get("/tasks").ok, "read token: reads")
check(aw.get("/tasks").ok and aw.post("/tasks", {"title": "w"}).status_code == 201, "write token: reads + writes")
check(adm.get("/admin/users").ok and adm.get("/admin/status").ok, "admin-read: admin endpoints")
check(is_err(a.get("/admin/users"), 403), "no admin-read scope: 403")
A.patch(B + "/api/users/2", json={"is_admin": True})
Bo2 = sess("bob")
TBA = tok(Bo2, "badm", ("read", "admin-read"))["token"]
check(Api(TBA).get("/admin/users").ok, "bob (admin) with admin-read")
A.patch(B + "/api/users/2", json={"is_admin": False})
check(Api(TBA).get("/admin/users").status_code == 403, "admin rights removed: the admin-read token stops at once")
check(is_err(adm.post("/admin/users"), 405) or adm.post("/admin/users").status_code in (403, 405), "admin endpoints are read-only")

# ---- expiry, revoke, disabled / deleted users
je = tok(A, "exp", days=1)
check(je["expires_at"] and Api(je["token"]).get("/me").ok, "expiring token works before the expiry")
dbx("UPDATE api_tokens SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"), je["id"]))
r = Api(je["token"]).get("/me")
check(is_err(r, 401) and "expired" in r.json()["error"]["message"], "expired token: 401 'expired'")
check(any(t["expired"] for t in A.get(B + "/api/me/tokens").json()["tokens"]), "token list shows expired")
jd = tok(A, "gone")
check(A.delete(B + f"/api/me/tokens/{jd['id']}").ok and Api(jd["token"]).get("/me").status_code == 401, "revoked token: 401")
check(Bo.delete(B + f"/api/me/tokens/{je['id']}").status_code == 404, "revoke: only own tokens (IDOR)")
A.patch(B + "/api/users/2", json={"disabled": True})
check(b.get("/me").status_code == 401, "disabled user: token refused")
A.patch(B + "/api/users/2", json={"disabled": False})
check(b.get("/me").ok, "enabled again: token works")
check(Api(toks[0]["token"]).get("/me").ok, "carol's token works")
check(A.delete(B + "/api/users/3").ok, "delete carol")
check(cc.get("/me").status_code == 401 and not dbx("SELECT 1 FROM api_tokens WHERE user_id=3"), "deleted user: tokens gone (cascade)")
Bo = sess("bob")

# ---- lists
r = a.get("/lists")
ls = r.json()
check(r.ok and ls["next_cursor"] is None and ls["data"][0]["is_inbox"] and ls["data"][0]["name"] == "Inbox", "lists: inbox first " + str(ls["data"][:1]))
r = a.post("/lists", {"name": "Shop", "checklist": True, "color": "#2dd4bf"})
L1 = r.json()
check(r.status_code == 201 and L1["checklist"] is True and L1["role"] == "owner" and L1["name"] == "Shop", "list create " + str(L1))
check(is_err(a.post("/lists", {"name": "x", "owner_id": 2}), 400), "list create: unknown field refused")
check(is_err(a.post("/lists", {"name": ""}), 400), "list create: name required")
check(is_err(a.post("/lists", {"name": "x", "checklist": "yes"}), 400), "list create: checklist must be boolean")
L2 = a.post("/lists", {"name": "Private"}).json()
L3 = a.post("/lists", {"name": "Shared", "kind": "project"}).json()  # project: time entries + fields
A.post(B + "/api/sections", json={"list_id": L3["id"], "name": "Now"})
A.put(B + f"/api/lists/{L3['id']}/members", json={"user_id": 2, "role": "view"})
d = a.get(f"/lists/{L3['id']}").json()
check(d["sections"] and d["sections"][0]["name"] == "Now" and d["shared"], "list detail with sections")
check(is_err(b.get(f"/lists/{L2['id']}"), 404, "not_found"), "IDOR: bob cannot read alice's private list")
check(b.get(f"/lists/{L3['id']}").json()["role"] == "view", "shared view-only list visible to bob")
check({x["id"] for x in b.get("/lists").json()["data"]} >= {L3["id"]} and L2["id"] not in {x["id"] for x in b.get("/lists").json()["data"]},
      "bob's lists: shared yes, private no")

# ---- tasks: create / get / patch / complete / reopen / delete
r = a.post("/tasks", {"title": "Dentist", "notes": "call **first**", "list_id": L2["id"], "priority": "high", "due": str(T),
                      "due_time": "15:00", "reminders": [0, 15], "tags": ["health", "#calls"], "url": "https://example.com/x",
                      "duration": 30, "pinned": True})
t1 = r.json()
check(r.status_code == 201 and r.headers.get("Location") == f"/api/v1/tasks/{t1['id']}", "task create 201 + Location")
check(t1["priority"] == "high" and t1["notes"] == "call **first**" and t1["due"] == str(T) and t1["due_time"] == "15:00"
      and t1["reminders"] == [0, 15] and sorted(t1["tags"]) == ["calls", "health"] and t1["pinned"] is True and t1["duration"] == 30
      and t1["status"] == "open" and t1["created_by"] == 1 and t1["list_id"] == L2["id"], "task fields " + json.dumps(t1)[:300])
check(a.post("/tasks", {"title": "inbox task"}).json()["list_id"] == ls["data"][0]["id"], "default list = inbox")
check(a.post("/tasks", {"title": "p3", "priority": 3}).json()["priority"] == "medium", "numeric priority accepted")
for bad, what in (({"title": ""}, "empty title"), ({"title": "x", "due": "2026-13-01"}, "bad date"), ({"title": "x", "priority": "urgent"}, "bad priority"),
                  ({"title": "x", "tags": "a,b"}, "tags as string"), ({"title": "x", "foo": 1}, "unknown field"), ({"title": "x", "url": "javascript:x"}, "bad url"),
                  ({"title": "x", "repeat": "FREQ=SECONDLY"}, "sub-daily rule"), ({"title": "x", "pinned": "yes"}, "pinned not boolean"),
                  ({"title": "x", "due_time": "25:00", "due": str(T)}, "bad time"), ({"title": "x", "list_id": 999999}, "unknown list"),
                  ({"title": "x", "_prev": {}}, "internal field"), ({"title": "x", "created_by": 2}, "created_by"),
                  ({"title": "x", "reminders": [99999999]}, "reminder out of range"), ({"title": ["x"]}, "title list")):
    r = a.post("/tasks", bad)
    check(r.status_code in (400, 404) and "error" in r.json(), f"validation: {what} -> {r.status_code}")
r = requests.post(V + "/tasks", headers={"Authorization": "Bearer " + TA, "Content-Type": "application/json"}, data="{not json")
check(is_err(r, 400), "invalid JSON: 400")
r = requests.post(V + "/tasks", headers={"Authorization": "Bearer " + TA, "Content-Type": "application/json"}, data="[1]")
check(is_err(r, 400), "JSON array body: 400")
check(a.get(f"/tasks/{t1['id']}").json()["title"] == "Dentist", "task get")
check(is_err(b.get(f"/tasks/{t1['id']}"), 404), "IDOR: bob cannot read alice's task")
check(is_err(b.patch(f"/tasks/{t1['id']}", {"title": "hacked"}), 404) and a.get(f"/tasks/{t1['id']}").json()["title"] == "Dentist",
      "IDOR: bob cannot change alice's task")
check(is_err(b.post(f"/tasks/{t1['id']}/complete"), 404) and is_err(b.delete(f"/tasks/{t1['id']}"), 404), "IDOR: complete / delete")
check(is_err(b.post("/tasks", {"title": "x", "list_id": L2["id"]}), 404), "IDOR: bob cannot create in alice's list")
r = a.patch(f"/tasks/{t1['id']}", {"title": "Dentist Dr. X", "priority": "low", "tags": ["health"], "due": None})
t = r.json()
check(r.ok and t["title"] == "Dentist Dr. X" and t["priority"] == "low" and t["tags"] == ["health"] and t["due"] is None and t["due_time"] is None,
      "patch " + json.dumps(t)[:200])
check(is_err(a.patch(f"/tasks/{t1['id']}", {}), 400), "patch: empty body 400")
check(is_err(a.patch(f"/tasks/{t1['id']}", {"list_id": L3["id"], "parent_id": "x"}), 400), "patch: bad value 400")
acts = dbx("SELECT kind, data, user_id FROM activity WHERE task_id=? ORDER BY id", (t1["id"],))
check(acts and all(json.loads(x[1]).get("via") == "api" and x[2] == 1 for x in acts), "history lines 'via api' " + str(acts[:3]))
ts = a.post("/tasks", {"title": "shared task", "list_id": L3["id"]}).json()
check(is_err(b.patch(f"/tasks/{ts['id']}", {"title": "x"}), 403, "forbidden"), "view-only member: patch 403")
check(is_err(b.post(f"/tasks/{ts['id']}/complete"), 403), "view-only member: complete 403")
check(is_err(b.post("/tasks", {"title": "x", "list_id": L3["id"]}), 403), "view-only member: create 403")
check(b.get(f"/tasks/{ts['id']}").ok, "view-only member: read ok")
rep = a.post("/tasks", {"title": "Water plants", "due": str(T), "repeat": "FREQ=DAILY"}).json()
r = a.post(f"/tasks/{rep['id']}/complete")
check(r.ok and r.json()["next_due"] == str(T + timedelta(days=1)) and r.json()["status"] == "open" and r.json()["due"] == str(T + timedelta(days=1)),
      "complete recurring: next_due " + str(r.json().get("next_due")))
r = a.post(f"/tasks/{t1['id']}/complete")
check(r.ok and r.json()["status"] == "done" and r.json()["completed_by"] == 1 and r.json()["next_due"] is None, "complete")
done_at = r.json()["completed_at"]
r = a.post(f"/tasks/{t1['id']}/complete")
check(r.ok and r.json()["completed_at"] == done_at, "complete twice: nothing changes (idempotent)")
check(is_err(a.post(f"/tasks/{t1['id']}/complete", {"status": -1}), 400), "complete: no body fields")
r = a.post(f"/tasks/{t1['id']}/reopen")
check(r.ok and r.json()["status"] == "open" and r.json()["completed_at"] is None, "reopen")
r = a.delete(f"/tasks/{t1['id']}")
check(r.status_code == 204 and not r.content, "delete: 204")
check(is_err(a.get(f"/tasks/{t1['id']}"), 404) and dbx("SELECT deleted_at IS NOT NULL FROM tasks WHERE id=?", (t1["id"],))[0][0] == 1,
      "delete: in the trash, not gone")
check(is_err(a.delete(f"/tasks/{t1['id']}"), 404) and is_err(a.patch(f"/tasks/{t1['id']}", {"title": "x"}), 404), "trashed task: 404 for changes")
r = requests.delete(V + f"/tasks/{ts['id']}?hard=1", headers=a.h)
check(r.status_code == 400 and dbx("SELECT COUNT(*) FROM tasks WHERE id=?", (ts["id"],))[0][0] == 1, "no permanent delete via the API (?hard=1 refused)")

# ---- subtasks
par = a.post("/tasks", {"title": "Trip", "list_id": L2["id"]}).json()
r = a.post(f"/tasks/{par['id']}/subtasks", {"title": "Pack"})
check(r.status_code == 201 and r.json()["parent_id"] == par["id"] and r.json()["list_id"] == L2["id"], "subtask create")
check(is_err(a.post(f"/tasks/{par['id']}/subtasks", {"title": "x", "parent_id": 1}), 400), "subtask: parent_id not allowed in the body")
a.post(f"/tasks/{par['id']}/subtasks", {"title": "Tickets"})
sub = a.get(f"/tasks/{par['id']}/subtasks").json()["data"]
check([x["title"] for x in sub] == ["Pack", "Tickets"], "subtasks list " + str([x["title"] for x in sub]))
check(is_err(b.get(f"/tasks/{par['id']}/subtasks"), 404), "IDOR: subtasks")

# ---- filters + pagination
for i in range(7):
    a.post("/tasks", {"title": f"page {i}", "list_id": L1["id"], "due": str(T + timedelta(days=i)), "tags": ["pg"] + (["odd"] if i % 2 else [])})
seen, cur, pages = [], None, 0
while True:
    r = a.get("/tasks", params={"list_id": L1["id"], "limit": 3, **({"cursor": cur} if cur else {})})
    j = r.json()
    seen += [x["id"] for x in j["data"]]
    pages += 1
    cur = j["next_cursor"]
    if not cur or pages > 5:
        break
check(pages == 3 and len(seen) == 7 and len(set(seen)) == 7 and seen == sorted(seen), f"cursor pages: {pages} pages, {len(seen)} tasks")
check(is_err(a.get("/tasks", params={"cursor": "zzz"}), 400) and is_err(a.get("/tasks", params={"limit": 0}), 400)
      and is_err(a.get("/tasks", params={"limit": 501}), 400), "bad cursor / limit: 400")
check(is_err(a.get("/tasks", params={"foo": 1}), 400), "unknown parameter: 400")
g = lambda **p: [x["title"] for x in a.get("/tasks", params=p).json()["data"]]  # noqa: E731
check(g(list_id=L1["id"], tag="odd") == ["page 1", "page 3", "page 5"], "filter tag")
check(g(list_id=L1["id"], due_from=str(T + timedelta(days=2)), due_to=str(T + timedelta(days=3))) == ["page 2", "page 3"], "filter due range")
a.post(f"/tasks/{a.get('/tasks', params={'tag': 'odd'}).json()['data'][0]['id']}/complete")
check(g(list_id=L1["id"], status="done") == ["page 1"] and len(g(list_id=L1["id"], status="all")) == 7, "filter status")
check(is_err(a.get("/tasks", params={"status": "nope"}), 400), "filter status: bad value")
since = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(timespec="seconds")
time.sleep(2)
x = a.post("/tasks", {"title": "fresh"}).json()
check(g(updated_since=since) == ["fresh"], "filter updated_since " + str(g(updated_since=since)))
check(is_err(a.get("/tasks", params={"updated_since": "yesterday"}), 400), "updated_since: bad value")
check(g(parent_id=par["id"]) == ["Pack", "Tickets"] and "Pack" not in g(top_level="true", list_id=L2["id"]), "filter parent / top_level")
A.put(B + f"/api/lists/{L3['id']}/members", json={"user_id": 2, "role": "edit"})
ta2 = a.post("/tasks", {"title": "for bob", "list_id": L3["id"], "assignee_id": 2}).json()
check(ta2["assignee_id"] == 2 and [x["title"] for x in b.get("/tasks", params={"assignee": "me"}).json()["data"]] == ["for bob"], "filter assignee=me")
check("for bob" not in g(assignee="none") and "fresh" in g(assignee="none"), "filter assignee=none")
check(is_err(a.post("/tasks", {"title": "x", "assignee_id": 2}), 400), "assign someone without access: 400")
check(is_err(b.get("/tasks", params={"list_id": L2["id"]}), 404), "IDOR: list filter on a foreign list")
check(all(x["list_id"] in (L3["id"],) or x["created_by"] == 2 for x in b.get("/tasks", params={"status": "all", "limit": 500}).json()["data"]),
      "bob's task list: only what bob sees")

# ---- tags, search
tg = {x["name"]: x for x in a.get("/tags").json()["data"]}
check(tg["pg"]["tasks"] == 7 and tg["pg"]["open"] == 6 and "health" not in tg, "tags with counts (trash left out) " + str(list(tg)))
check(b.get("/tags").json()["data"] == [], "tags are per user")
r = a.get("/search", params={"q": "page"})
check(r.ok and len(r.json()["data"]) == 7, "search")
r = a.get("/search", params={"q": "page", "limit": 5})
j2 = a.get("/search", params={"q": "page", "limit": 5, "cursor": r.json()["next_cursor"]}).json()
check(len(r.json()["data"]) == 5 and len(j2["data"]) == 2 and j2["next_cursor"] is None, "search pages")
check(b.get("/search", params={"q": "Dentist"}).json()["data"] == [] and b.get("/search", params={"q": "for bob"}).json()["data"], "search: only visible")
check(is_err(a.get("/search"), 400), "search: q required")

# ---- comments
r = b.post(f"/tasks/{ta2['id']}/comments", {"body": "on it <@1>"})
check(r.status_code == 201 and r.json()["author"]["name"] == "Bob" and r.json()["mentions"] == [1] and r.json()["text"] == "on it @Alice",
      "comment create " + r.text[:200])
cm = a.get(f"/tasks/{ta2['id']}/comments").json()["data"]
check(len(cm) == 1 and cm[0]["body"] == "on it <@1>", "comments list")
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=1 AND kind='mention'")[0][0] == 1, "comment via API: mention News for alice")
check(is_err(b.post(f"/tasks/{t1['id']}/comments", {"body": "x"}), 404), "IDOR: comment on an invisible task")
check(is_err(a.post(f"/tasks/{ta2['id']}/comments", {"body": ""}), 400) and is_err(a.post(f"/tasks/{ta2['id']}/comments", {"text": "x"}), 400),
      "comment validation")
# 2.0.6 (#315): comments no longer need collaboration (personal notes); writing needs the Comments module
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,stats,time,progress,comments"})
check(a.get(f"/tasks/{ta2['id']}/comments").status_code == 200 and a.post(f"/tasks/{ta2['id']}/comments", {"body": "note to self"}).status_code == 201
      and a.get("/me").json()["features"]["collaboration"] is False, "personal collaboration off: comments still work (notes)")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"})
check(is_err(a.post(f"/tasks/{ta2['id']}/comments", {"body": "x"}), 409) and a.get(f"/tasks/{ta2['id']}/comments").status_code == 200
      and a.get("/me").json()["features"]["comments"] is False, "Comments module off: writing refused (409), reading stays")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments"})
A.patch(B + "/api/admin/settings", json={"collab_all": False})
check(a.get(f"/tasks/{ta2['id']}/comments").status_code == 200 and is_err(b.get(f"/tasks/{ta2['id']}"), 404),
      "instance collaboration off: comments stay readable, shared list gone for bob")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

# ---- time entries
now_l = datetime.now().replace(microsecond=0)
r = a.post("/time/entries", {"task_id": ta2["id"], "start": (now_l - timedelta(hours=2)).isoformat(), "minutes": 45, "note": "call"})
te = r.json()
check(r.status_code == 201 and te["seconds"] == 2700 and te["task_id"] == ta2["id"] and te["note"] == "call", "time entry create " + r.text[:200])
check(is_err(a.post("/time/entries", {"task_id": ta2["id"], "start": "x", "minutes": 5}), 400), "time entry: bad start")
check(is_err(a.post("/time/entries", {"task_id": ta2["id"], "start": now_l.isoformat(), "minutes": 5, "user_id": 2}), 400), "time entry: unknown field")
check(is_err(b.post("/time/entries", {"task_id": t1["id"], "start": now_l.isoformat(), "minutes": 5}), 404), "IDOR: time on an invisible task")
el = a.get("/time/entries").json()
check(len(el["data"]) == 1 and el["data"][0]["id"] == te["id"], "time entries list")
check(b.get("/time/entries").json()["data"] == [] and b.get("/time/entries", params={"scope": "all"}).json()["data"][0]["id"] == te["id"],
      "time entries: mine vs all (shared list)")
check(is_err(a.get("/time/entries", params={"from": "x"}), 400), "time entries: bad date")
A.patch(B + "/api/admin/settings", json={"time_all": False})
check(is_err(a.get("/time/entries"), 403) and is_err(a.post("/time/entries", {"task_id": ta2["id"], "start": now_l.isoformat(), "minutes": 5}), 403),
      "time tracking off (instance): 403")
A.patch(B + "/api/admin/settings", json={"time_all": True})

# ---- habits
hid = A.post(B + "/api/habits", json={"name": "Run", "goal": 2}).json()["id"]
check([h["name"] for h in a.get("/habits").json()["data"]] == ["Run"] and b.get("/habits").json()["data"] == [], "habits (per user)")
r = a.post(f"/habits/{hid}/checkin")
check(r.ok and r.json()["count"] == 1 and r.json()["today"] == 1, "check-in +1")
check(a.post(f"/habits/{hid}/checkin").json()["today"] == 2, "check-in +1 again")
check(a.post(f"/habits/{hid}/checkin", {"count": 0}).json()["today"] == 0, "check-in absolute 0")
yd = str(T - timedelta(days=1))
r = a.post(f"/habits/{hid}/checkin", {"date": yd, "count": 3, "note": "long"})
check(r.ok and r.json()["last_30_days"].get(yd) == 3 and dbx("SELECT note FROM habit_logs WHERE day=?", (yd,))[0][0] == "long", "check-in other day + note")
for bad in ({"date": "2026-02-30"}, {"date": str(T + timedelta(days=5))}, {"count": -1}, {"count": "x"}, {"foo": 1}, {"note": 5}):
    check(is_err(a.post(f"/habits/{hid}/checkin", bad), 400), "check-in validation " + str(bad))
check(is_err(b.post(f"/habits/{hid}/checkin"), 404), "IDOR: habits")

# ---- admin
au = adm.get("/admin/users").json()["data"]
check([u["username"] for u in au] == ["alice", "bob", "dave"] and all("password_hash" not in u and "drop_token" not in u for u in au),
      "admin users (no secrets) " + str([u["username"] for u in au]))
stt = adm.get("/admin/status").json()
check(stt["users"] == 3 and stt["version"] and "webhooks_pending" in stt, "admin status " + str(stt))

# ---- error format, unknown routes, spec
check(is_err(a.get("/nope"), 404, "not_found"), "unknown route: JSON 404")
check(is_err(requests.put(V + "/tasks", headers=a.h), 405, "method_not_allowed"), "wrong method: JSON 405")
r = requests.get(V + "/openapi.json")
spec = r.json()
check(r.ok and spec["openapi"] == "3.1.0" and spec["info"]["version"] == "1.0" and "bearerAuth" in spec["components"]["securitySchemes"],
      "spec served without a token")
check(not re.search(r"\d+\.\d+\.\d+", spec["info"]["description"]) and "servers" in spec, "spec: no server version / data")
try:
    from openapi_spec_validator import validate
    validate(spec)
    check(True, "spec valid")
except ImportError:
    print("(openapi-spec-validator not installed, structural check only)")
    check(all(p.startswith("/") for p in spec["paths"]), "spec paths")
except Exception as e:  # noqa: BLE001
    check(False, "spec invalid: " + str(e)[:300])
routes = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test"), "python", "-c",
                         "import app\nfor r in app.app.url_map.iter_rules():\n  print(r.rule, ','.join(sorted(r.methods - {'HEAD','OPTIONS'})))"],
                        capture_output=True, text=True).stdout.split("\n")
v1r = {}
for ln in routes:
    if ln.startswith("/api/v1/") and "openapi" not in ln:
        rule, meth = ln.split()
        v1r.setdefault(re.sub(r"<(\w+)>", r"{\1}", re.sub(r"<int:\w+>", "{id}", rule[len("/api/v1"):])), set()).update(m.lower() for m in meth.split(","))
missing = [(p, m) for p, ms in v1r.items() for m in ms if m not in spec["paths"].get(p, {})]
extra = [(p, m) for p, ms in spec["paths"].items() for m in ms if m not in v1r.get(p, set())]
check(v1r and not missing and not extra, f"every route documented: missing {missing}, extra {extra}")
SCOPES = ("read", "tasks:write", "comments", "structure", "delete", "attachments:read", "attachments:write", "time", "export", "account",
          "admin-read", "agent", "calendar", "contacts")  # 2.15.0 (#479): fine scopes; 2.21.0: calendar, contacts
check(all(op.get("x-kalmido-scope") in SCOPES for ms in spec["paths"].values() for op in ms.values()), "spec: scope per operation")

# ---- per-token rate limit (KALMIDO_API_RATE=200 in this container)
TL = tok(A, "limited")["token"]
lim = Api(TL)
hits = [lim.get("/me").status_code for _ in range(205)]
check(hits[:200] == [200] * 200 and hits[200:] == [429] * 5, f"rate limit per token: {hits.count(200)} ok, then 429")
r = lim.get("/me")
check(is_err(r, 429, "rate_limited") and r.headers.get("Retry-After") == "60", "429 with Retry-After")
check(ar.get("/me").ok and a.get("/me").ok, "other tokens are not limited by it")

# ---- invalid tokens: limit per client address + admin alert (last: it blocks this address for 15 min)
codes = [requests.get(V + "/me", headers={"Authorization": f"Bearer abk_{'z' * 30}{i:013d}"}).status_code for i in range(40)]
n401 = codes.index(429) if 429 in codes else 99
check(18 <= n401 <= 30 and set(codes[:n401]) == {401} and set(codes[n401:]) == {429},
      f"invalid tokens: at most 30 per address (incl. the earlier ones), then 429: {n401} x 401")
check(ar.get("/me").status_code == 429, "address blocked for valid tokens too (15 min)")
time.sleep(8)
al = dbx("SELECT kind, message FROM admin_alerts WHERE kind='security' ORDER BY id")
check(any("invalid token" in m for _, m in al) and any("API rate limit" in m for _, m in al), "admin alert about invalid tokens " + str(al)[-300:])
check(not any(TA in m for _, m in al), "alerts never contain a token")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
