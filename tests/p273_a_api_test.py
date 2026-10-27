#!/usr/bin/env python3
"""2.73.0 API tests, part A (#661): several Kalmido servers in one app -- the server side (kalmido/accounts/servers.py).
The test server connects to ITSELF as "the other server" (http://127.0.0.1:3040 inside the container, an allowed internal
host): alice keeps an account of bob's there. A stub (stub_msv.py, port 8099) plays a misbehaving server.
 - adding: by connection code (this server's own address refused, re-pointed code accepted) and by address + token; a second
   link to the same account refused; the token sealed in the database, never in an answer
 - data: lists (inbox, write right), open tasks with the interface's fields only; a task over there: create, change,
   complete, reopen, delete (trash over there); search, events, news (+ read)
 - moving between servers in both directions: the copy has title, note, due date, priority and the open subtasks, the
   source lies in the trash; a target without write right: nothing deleted
 - errors of the other side: 424 + code (auth after revoking, denied with the scope, offline, version, rate, too large,
   redirect, deep JSON); odd values over there are type-checked and cut down
 - SSRF: private / loopback / link-local / ULA / IPv4-in-IPv6 addresses refused without the allow-list; a hosted server
   (KALMIDO_HOSTED) refuses http and every internal address
 - tenant-matrix: servers -- another person's account: 404 everywhere; agents / API tokens never reach /api/servers
usage: p273_a_api_test.py <datadir>"""
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
SELF = "http://127.0.0.1:3040"   # the app as seen from inside its container
STUB = "http://127.0.0.1:8099"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


SEEN500 = [0]


def on500(r, *a, **k):
    """A 500: the app's traceback into the log (the first three)."""
    if r.status_code == 500 and SEEN500[0] < 3:
        SEEN500[0] += 1
        print("FAIL: 500 on", r.request.method, r.request.url, flush=True)
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print((log.stdout + log.stderr)[-3000:], flush=True)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def code_of(u, t):
    return "kalmido-link:" + base64.urlsafe_b64encode(json.dumps({"u": u, "t": t}).encode()).decode().rstrip("=")


def inbox(s):
    return next(x["id"] for x in s.get(B + "/api/state").json()["lists"] if x.get("is_inbox"))


def gone(tid):
    r = dbx("SELECT deleted_at FROM tasks WHERE id=?", (tid,))
    return bool(r and r[0][0])


BASE_EXTRA = os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
env = dict(os.environ, EXTRA=BASE_EXTRA)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "stub_msv.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_msv.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice", hooks=[on500])
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "events"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob", hooks=[on500]), sess("carol", hooks=[on500])
for s_ in (Bo, Ca):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================================================================== this server's label, the connection code
r = A.get(B + "/api/servers")
if "json" not in (r.headers.get("Content-Type") or ""):
    print("FAIL: GET /api/servers", r.status_code, r.text[:500], flush=True)
    print(subprocess.run(["docker", "logs", "--tail", "60", CT], capture_output=True, text=True).stderr[-4000:], flush=True)
    sys.exit(1)
j = r.json()
check(j["links"] == [] and j["self"]["name"] == "This server" and j["self"]["short"] == "AL" and j["self"]["color"].startswith("#"),
      f"no accounts yet; this server's label from the organisation's name {j}")
check(A.patch(B + "/api/servers/self", json={"short": "toolong"}).status_code == 400, "a short name of 7 letters: 400")
check(A.patch(B + "/api/servers/self", json={"color": "red"}).status_code == 400, "a colour outside the palette: 400")
r = A.patch(B + "/api/servers/self", json={"name": "Work", "short": "w1", "color": "#3e63dd"})
check(r.ok and r.json() == {"name": "Work", "short": "W1", "color": "#3e63dd"}, f"this server labelled (upper case) {r.text[:200]}")

r = Bo.post(B + "/api/servers/code", json={"name": "Alice's app"})
check(r.status_code == 201, f"bob creates a connection code {r.text[:200]}")
cj = r.json()
raw = cj["code"][len("kalmido-link:"):]
inner = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
BTOK = inner["t"]
check(cj["code"].startswith("kalmido-link:") and inner["u"] == "https://kalmido.example" and BTOK.startswith("abk_"),
      f"the code packs this server's address and a token {inner['u']}")
tk = next((t for t in Bo.get(B + "/api/me/tokens").json()["tokens"] if t["id"] == cj["token_id"]), None)
check(tk and tk["name"] == "Kalmido-App: Alice's app" and sorted(tk["scopes"]) == sorted(["read", "tasks:write", "delete", "calendar", "comments"]),
      f"the token is one of bob's API tokens with just the needed scopes {tk}")

# ================================================================== adding
r = A.post(B + "/api/servers", json={"code": cj["code"]})
check(r.status_code == 400 and "this server" in r.json()["error"].lower(), f"the code names this server's own address: refused {r.text[:200]}")
for bad in ("kalmido-link:!!!", "kalmido-link:" + base64.urlsafe_b64encode(b"not json").decode(),
            "kalmido-link:" + base64.urlsafe_b64encode(b"[1,2]").decode(), "other-link:" + raw):
    rr = A.post(B + "/api/servers", json={"code": bad})
    check(rr.status_code == 400, f"a broken code {bad[:30]}: 400 ({rr.status_code})")
check(A.post(B + "/api/servers", json={"code": code_of(SELF, 123)}).status_code == 400, "a code with a token that is no string: 400")
r = A.post(B + "/api/servers", json={"code": code_of(SELF + "/", BTOK), "name": "Bob home"})
check(r.status_code == 201, f"the code pointing at the app inside the container: added {r.text[:300]}")
L = r.json()
SID = L.get("id")
check(L.get("name") == "Bob home" and L.get("base_url") == SELF and L.get("remote_me", {}).get("id") == BOB and L.get("ok") is True
      and L.get("missing_scopes") == [] and L.get("short") == "BH", f"the account: name, address without /, bob over there, all scopes {L}")
check(BTOK not in r.text and BTOK not in A.get(B + "/api/servers").text, "the token never comes back")
row = dbx("SELECT token_enc, user_id FROM msv_links WHERE id=?", (SID,))[0]
check(row[0].startswith("kenc1:") and BTOK not in row[0] and row[1] == 1, "the token is sealed in the database")
r = A.post(B + "/api/servers", json={"base_url": SELF + "/api/v1/", "token": BTOK})
check(r.status_code == 400 and "already" in r.json()["error"], f"the same account a second time: refused {r.text[:200]}")

# carol's read-only token, by address + token
r = Ca.post(B + "/api/me/tokens", json={"name": "ro", "scopes": ["read"]})
CTOK = r.json()["token"]
r = A.post(B + "/api/servers", json={"base_url": SELF, "token": CTOK, "name": "Carol RO", "short": "c", "color": "#30a46c"})
check(r.status_code == 201 and set(r.json().get("missing_scopes") or []) == {"tasks:write", "delete", "calendar", "comments"},
      f"address + token: added, the missing scopes named {r.text[:300]}")
SIDC = r.json().get("id")

# ================================================================== data over there
LH = Bo.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
BIN = inbox(Bo)
t1 = Bo.post(B + "/api/tasks", json={"title": "Water the plants", "list_id": LH, "due": str(testclock.today()), "priority": 5}).json()["id"]
t2 = Bo.post(B + "/api/tasks", json={"title": "<img src=x onerror=alert(1)>", "list_id": BIN}).json()["id"]
Bo.post(B + "/api/tasks", json={"title": "Done one", "list_id": LH}).json()
CRO = Ca.post(B + "/api/lists", json={"name": "Carol shared", "org_id": ORG}).json()["id"]
check(Ca.put(B + f"/api/lists/{CRO}/members", json={"user_id": BOB, "role": "view"}).ok, "setup: carol shares a list with bob (read only)")
r = A.get(B + f"/api/servers/{SID}/data")
check(r.ok, f"/data {r.text[:300]}")
D = r.json()
ls = {x["id"]: x for x in D.get("lists", [])}
check(LH in ls and ls[LH]["name"] == "Home" and ls[LH]["can_write"] is True and ls[BIN]["inbox"] is True and ls[CRO]["can_write"] is False,
      f"bob's lists: inbox, write right, carol's list read only {list(ls.values())[:4]}")
check(set(ls[LH]) == {"id", "name", "color", "folder", "inbox", "can_write"}, f"a list has the interface's fields only {set(ls[LH])}")
ts = {x["id"]: x for x in D.get("tasks", [])}
check(t1 in ts and ts[t1]["priority"] == "high" and ts[t1]["due"] == str(testclock.today()) and ts[t1]["url"] == f"{SELF}/#t/{t1}",
      f"an open task with priority, due date and the link over there {ts.get(t1)}")
check(set(ts[t1]) == {"id", "list_id", "parent_id", "title", "due", "due_time", "priority", "status", "tags", "updated_at", "url"},
      f"a task has the interface's fields only {set(ts[t1])}")
check(ts[t2]["title"] == "<img src=x onerror=alert(1)>", "HTML in a title stays plain text (the client sets textContent)")
check(D.get("today") and D.get("at") and all(x["status"] == "open" for x in ts.values()), "today, at, only open tasks")
check(not [x for x in A.get(B + "/api/state").json().get("tasks", []) if x.get("title") == "Water the plants"],
      "nothing of the other server is stored here")

# a task over there: create, change, complete, reopen, delete
r = A.post(B + f"/api/servers/{SID}/tasks", json={"title": "From alice's app", "notes": "a note", "priority": "medium", "due": "2030-01-02"})
check(r.status_code == 201, f"create over there {r.text[:200]}")
NT = r.json()
check(NT["status"] == "open" and NT["priority"] == "medium" and list(dbx("SELECT list_id, content FROM tasks WHERE id=?", (NT["id"],))[0]) == [BIN, "a note"]
      if dbx("SELECT list_id FROM tasks WHERE id=?", (NT["id"],)) else False, "without list_id: bob's inbox over there, with the note")
r = A.post(B + f"/api/servers/{SID}/tasks", json={"title": "In Home", "list_id": LH})
check(r.status_code == 201 and r.json()["list_id"] == LH, "create in a list over there")
check(A.post(B + f"/api/servers/{SID}/tasks", json={"title": ""}).status_code == 400, "no title: 400")
check(A.post(B + f"/api/servers/{SID}/tasks", json={"title": "x", "owner": 1}).status_code == 400, "an unknown field: 400")
check(A.post(B + f"/api/servers/{SID}/tasks", json={"title": "x", "due": "tomorrow"}).status_code == 400, "a bad date: 400")
r = A.patch(B + f"/api/servers/{SID}/tasks/{NT['id']}", json={"title": "Renamed", "priority": "low"})
check(r.ok and r.json()["title"] == "Renamed" and r.json()["priority"] == "low", f"change over there {r.text[:200]}")
r = A.post(B + f"/api/servers/{SID}/tasks/{NT['id']}/complete")
check(r.ok and r.json()["status"] == "done", "complete over there")
r = A.post(B + f"/api/servers/{SID}/tasks/{NT['id']}/reopen")
check(r.ok and r.json()["status"] == "open", "reopen over there")
r = A.get(B + f"/api/servers/{SID}/tasks/{NT['id']}")
check(r.ok and r.json()["notes"] == "a note" and r.json()["subtasks"] == [] and r.json()["comments_count"] == 0, f"one task with its note {r.text[:300]}")
r = A.delete(B + f"/api/servers/{SID}/tasks/{NT['id']}")
check(r.ok and r.json() == {"ok": True} and gone(NT["id"]), "delete over there = bob's trash")
r = A.get(B + f"/api/servers/{SID}/tasks/{NT['id']}")
check(r.status_code == 424 and r.json()["code"] == "notfound", f"a task in the trash over there: notfound {r.text[:200]}")
check(A.get(B + f"/api/servers/{SID}/tasks/99999").json().get("code") == "notfound", "an unknown task over there: notfound")

r = A.get(B + f"/api/servers/{SID}/search?q=plants")
check(r.ok and [x["id"] for x in r.json()["tasks"]] == [t1], f"search over there {r.text[:200]}")
check(A.get(B + f"/api/servers/{SID}/search?q=").status_code == 400, "search without q: 400")
cal = Bo.post(B + "/api/evcals", json={"name": "Bob cal", "color": "#2dd4bf"}).json()
D3 = testclock.today() + timedelta(days=3)
Bo.post(B + "/api/events", json={"title": "Dentist", "cal_id": cal["id"], "start": f"{D3}T15:00", "end": f"{D3}T16:00"})
r = A.get(B + f"/api/servers/{SID}/events?from={testclock.today()}&to={testclock.today() + timedelta(days=7)}")
ev = r.json().get("events") if r.ok else None
check(ev and ev[0]["title"] == "Dentist" and ev[0]["cal_name"] == "Bob cal" and ev[0]["color"] == "#2dd4bf" and ev[0]["all_day"] is False
      and ev[0]["url"] == f"{SELF}/#cal" and isinstance(ev[0]["id"], int), f"events over there with calendar name + colour {r.text[:300]}")
check(A.get(B + f"/api/servers/{SID}/events?from=x&to=y").status_code == 400, "events without dates: 400")
# news: carol assigns bob a task in a shared list
CW = Ca.post(B + "/api/lists", json={"name": "Carol team", "org_id": ORG}).json()["id"]
Ca.put(B + f"/api/lists/{CW}/members", json={"user_id": BOB, "role": "edit"})
Ca.post(B + "/api/tasks", json={"title": "For bob", "list_id": CW, "assignee_id": BOB})
r = A.get(B + f"/api/servers/{SID}/news?limit=20")
nj = r.json() if r.ok else {}
check(r.ok and isinstance(nj.get("items"), list) and isinstance(nj.get("unread"), int), f"news over there {r.text[:300]}")
if nj.get("items"):
    it = nj["items"][0]
    check(set(it) == {"id", "kind", "text", "task_id", "at", "read"}, f"a news item has the interface's fields {it}")
    r = A.post(B + f"/api/servers/{SID}/news/read", json={"ids": [it["id"]]})
    check(r.ok and r.json()["unread"] <= nj["unread"], f"news read over there {r.text[:200]}")
else:
    check(False, f"carol's assignment shows in bob's news {nj}")
check(A.post(B + f"/api/servers/{SID}/news/read", json={"ids": ["x"]}).status_code == 400, "news read with a bad id: 400")
check(A.get(B + f"/api/servers/{SID}/news?limit=0").status_code == 400, "news limit 0: 400")

# ================================================================== moving between servers
la = inbox(A)
ta = A.post(B + "/api/tasks", json={"title": "Move me", "list_id": la, "content": "Moved note", "due": "2030-05-06", "priority": 3}).json()["id"]
s1 = A.post(B + "/api/tasks", json={"title": "Sub open", "parent_id": ta}).json()["id"]
s2 = A.post(B + "/api/tasks", json={"title": "Sub done", "parent_id": ta}).json()["id"]
A.post(B + f"/api/tasks/{s2}/complete")
A.post(B + f"/api/tasks/{ta}/comments", json={"body": "a comment"})
r = A.post(B + "/api/servers/move", json={"from": {"server": 0, "task": ta}, "to": {"server": SID, "list_id": LH}})
check(r.ok and r.json().get("ok") is True and r.json()["task"]["server"] == SID and r.json()["lost"]["comments"] == 1 and not r.json().get("source_kept"),
      f"move here -> over there {r.text[:300]}")
nid = r.json()["task"]["id"]
cp = dbx("SELECT title, content, due, priority, list_id FROM tasks WHERE id=?", (nid,))
subs = [x[0] for x in dbx("SELECT title FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (nid,))]
check(cp and list(cp[0]) == ["Move me", "Moved note", "2030-05-06", 3, LH] and subs == ["Sub open"],
      f"the copy over there: title, note, due, priority, list, the open subtask {cp} {subs}")
check(gone(ta), "the source lies in the trash here (restorable)")
r = A.post(B + "/api/servers/move", json={"from": {"server": SID, "task": nid}, "to": {"server": 0, "list_id": None}})
check(r.ok and r.json()["task"]["server"] == 0, f"move over there -> here {r.text[:300]}")
back = r.json()["task"]["id"]
cp = dbx("SELECT title, content, list_id FROM tasks WHERE id=?", (back,))
check(cp and list(cp[0]) == ["Move me", "Moved note", la] and gone(nid)
      and [x[0] for x in dbx("SELECT title FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (back,))] == ["Sub open"],
      "the copy here (inbox), the source in bob's trash")
# a target without write right: nothing deleted
r = A.post(B + "/api/servers/move", json={"from": {"server": 0, "task": back}, "to": {"server": SID, "list_id": CRO}})
check(r.status_code == 424 and not gone(back), f"over there only read: refused, nothing deleted {r.status_code} {r.text[:200]}")
CV = Ca.post(B + "/api/lists", json={"name": "Carol view", "org_id": ORG}).json()["id"]
Ca.put(B + f"/api/lists/{CV}/members", json={"user_id": 1, "role": "view"})
r = A.post(B + "/api/servers/move", json={"from": {"server": SID, "task": t1}, "to": {"server": 0, "list_id": CV}})
check(r.status_code == 403 and not gone(t1), f"here only read: 403, nothing deleted over there {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/servers/move", json={"from": {"server": SID, "task": t1}, "to": {"server": 0, "list_id": 999999}})
check(r.status_code == 404 and not gone(t1), "a list here that does not exist: 404")
check(A.post(B + "/api/servers/move", json={"from": {"server": 0, "task": back}, "to": {"server": 0, "list_id": None}}).status_code == 400,
      "the same server: 400")
check(A.post(B + "/api/servers/move", json={"from": {"server": SID, "task": "x"}, "to": {"server": 0}}).status_code == 400, "bad data: 400")
ct = Ca.post(B + "/api/tasks", json={"title": "Carol's own", "list_id": inbox(Ca)}).json()["id"]
r = A.post(B + "/api/servers/move", json={"from": {"server": 0, "task": ct}, "to": {"server": SID, "list_id": None}})
check(r.status_code == 404 and not gone(ct), "moving a task of someone else here: 404, nothing copied")

# ================================================================== errors of the other side
r = A.post(B + f"/api/servers/{SIDC}/tasks", json={"title": "x"})
check(r.status_code == 424 and r.json()["code"] == "denied" and r.json().get("scope") == "tasks:write", f"a read-only token: denied + scope {r.text[:200]}")
r = A.patch(B + f"/api/servers/{SID}", json={"token": "abk_" + "x" * 40})
check(r.status_code == 424 and r.json()["code"] == "auth", f"a wrong token: auth {r.text[:200]}")
r = A.patch(B + f"/api/servers/{SID}", json={"token": CTOK})
check(r.status_code in (400, 409) and r.json()["error"], f"a token of another account over there: refused {r.text[:200]}")
for kind, code in (("deep", "version"), ("big", "invalid"), ("redir", "version"), ("html", "version"), ("rate", "rate"), ("e500", "offline")):
    r = A.post(B + "/api/servers", json={"base_url": f"{STUB}/{kind}", "token": "abk_" + "y" * 40})
    check(r.status_code == 424 and r.json().get("code") == code, f"stub {kind}: {code} ({r.status_code} {r.text[:200]})")
    if kind == "rate":
        check(r.json().get("retry_after") == 7, "rate: Retry-After passed on")
r = A.post(B + "/api/servers", json={"base_url": SELF + "/static", "token": BTOK})
check(r.status_code == 424 and r.json()["code"] == "version", f"no Kalmido API at the address: version {r.text[:200]}")
r = A.post(B + "/api/servers", json={"base_url": "http://127.0.0.1:3999", "token": BTOK})
check(r.status_code == 424 and r.json()["code"] == "offline", f"nothing listening: offline {r.text[:200]}")
r = A.post(B + "/api/servers", json={"base_url": f"{STUB}/evil", "token": "abk_" + "z" * 40})
check(r.status_code == 201, f"a server with odd values: added {r.text[:200]}")
SIDE = r.json().get("id")
check(r.json()["remote_me"]["name"] == "<script>alert(1)</script>", "names stay plain text")
r = A.get(B + f"/api/servers/{SIDE}/data")
d = r.json() if r.ok else {}
check(r.ok and d["lists"] == [{"id": 3, "name": "<img src=x onerror=alert(1)>", "color": "", "folder": "", "inbox": False, "can_write": True}]
      and d["tasks"] == [{"id": 9, "list_id": 3, "parent_id": None, "title": "<img src=x onerror=alert(1)>", "due": None, "due_time": None,
                          "priority": "none", "status": "open", "tags": ["a"], "updated_at": None, "url": f"{STUB}/evil/#t/9"}],
      f"odd values over there: type-checked, extra fields dropped {d}")
log = open(os.path.join(DATA, "msv.log")).read()
check("bearer=True" in log and "abk_" not in log, "the stub got the token as a bearer header (the log names no token)")
# 2.73.0 (#661) review N3: the copy exists over there, its subtasks fail -> counted, the source still goes to the trash
r = A.post(B + "/api/servers", json={"base_url": f"{STUB}/nosub", "token": "abk_" + "n" * 40})
check(r.status_code == 201, f"N3: the stub that refuses subtasks is linked {r.text[:200]}")
SIDN = r.json().get("id")
tn = A.post(B + "/api/tasks", json={"title": "Move with subtasks", "list_id": la}).json()["id"]
for x in ("Sub A", "Sub B"):
    A.post(B + "/api/tasks", json={"title": x, "parent_id": tn})
r = A.post(B + "/api/servers/move", json={"from": {"server": 0, "task": tn}, "to": {"server": SIDN, "list_id": None}})
j = r.json() if r.ok else {}
check(r.ok and j["task"] == {"server": SIDN, "id": 50} and j["lost"].get("subtasks") == 2 and not j.get("source_kept") and gone(tn),
      f"N3: the move succeeds, two subtasks named as not created, the source in the trash {r.status_code} {r.text[:300]}")
A.delete(B + f"/api/servers/{SIDN}")
# the account goes offline / the token is revoked
dbx("UPDATE msv_links SET base_url='http://127.0.0.1:3999' WHERE id=?", (SIDC,))
r = A.get(B + f"/api/servers/{SIDC}/data")
check(r.status_code == 424 and r.json()["code"] == "offline", "a stored account that is down: offline")
lk = {x["id"]: x for x in A.get(B + "/api/servers").json()["links"]}
check(lk[SIDC]["ok"] is False and lk[SIDC]["err"] == "offline" and lk[SIDC]["err_text"], "the account shows its state")
check(Bo.delete(B + f"/api/me/tokens/{cj['token_id']}").ok, "bob revokes the token")
r = A.get(B + f"/api/servers/{SID}/data?fresh=1")
check(r.status_code == 424 and r.json()["code"] == "auth", f"a revoked token: auth {r.text[:200]}")

# ================================================================== 2.73.0 (#661) review H1: a slow other server holds no thread
dbx("UPDATE msv_links SET base_url=? WHERE id=?", (f"{STUB}/hang", SIDC))  # accepts and sends nothing
RES = []


def hit(path):
    t0 = time.monotonic()
    rr = A.get(B + path)
    RES.append((rr.status_code, rr.json().get("code") if "json" in (rr.headers.get("Content-Type") or "") else None, time.monotonic() - t0))


ths = [threading.Thread(target=hit, args=(f"/api/servers/{SIDC}/search?q=x",)) for _ in range(6)]
for t_ in ths:
    t_.start()
time.sleep(1.5)
t0 = time.monotonic()
r = Bo.get(B + "/api/state")
t_state = time.monotonic() - t0
check(r.ok and t_state < 2, f"H1: other routes answer while four requests hang ({t_state:.1f} s)")
for t_ in ths:
    t_.join(40)
busy = [x for x in RES if x[1] == "busy"]
slow = [x for x in RES if x[1] == "offline"]
check(len(busy) == 2 and all(x[0] == 424 and x[2] < 1.5 for x in busy), f"H1: requests five and six of a person: 424 busy at once {RES}")
check(len(slow) == 4 and all(x[2] < 12 for x in slow), f"H1: the hanging ones end as offline within the read limit {RES}")
RES.clear()
ths = [threading.Thread(target=hit, args=(f"/api/servers/{SIDC}/data?fresh=1",)) for _ in range(3)]
for t_ in ths:
    t_.start()
for t_ in ths:
    t_.join(40)
check(sorted(x[1] for x in RES) == ["busy", "busy", "offline"] and all(x[2] < 1.5 for x in RES if x[1] == "busy"),
      f"H1: /data of one account runs once, parallel ones answer busy at once (no thread waits) {RES}")
dbx("UPDATE msv_links SET base_url='http://127.0.0.1:3999' WHERE id=?", (SIDC,))

# ================================================================== SSRF without the allow-list entry (127.0.0.1 is allowed here)
for u in ("http://10.0.0.1", "http://169.254.169.254", "http://[::1]:3040", "http://[fd00::1]", "http://[::ffff:127.0.0.2]", "http://localhost:3040",
          "http://172.20.0.9"):
    r = A.post(B + "/api/servers", json={"base_url": u, "token": BTOK})
    check(r.status_code == 400 and "internal" in r.json()["error"], f"{u}: refused as internal ({r.status_code} {r.text[:120]})")
# review M3: plain http to a public address would send the token unencrypted: refused like a hosted server does
r = A.post(B + "/api/servers", json={"base_url": "http://93.184.215.14", "token": BTOK})
check(r.status_code == 400 and "https" in r.json()["error"], f"M3: http to a public address refused ({r.status_code} {r.text[:150]})")
for u in ("ftp://example.com", "https://user:pw@example.com", "javascript:alert(1)", "https://example.com/a b", "https://example.com/<x>", "https://example.com/../x"):
    check(A.post(B + "/api/servers", json={"base_url": u, "token": BTOK}).status_code == 400, f"{u}: an invalid address 400")

# ================================================================== another person, agents, tokens (tenant-matrix: servers)
for m, u, b in (("GET", f"/api/servers/{SID}/data", None), ("PATCH", f"/api/servers/{SID}", {"name": "x"}), ("DELETE", f"/api/servers/{SID}", None),
                ("POST", f"/api/servers/{SID}/restore", None), ("GET", f"/api/servers/{SID}/tasks/{t1}", None),
                ("POST", f"/api/servers/{SID}/tasks", {"title": "x"}), ("GET", f"/api/servers/{SID}/search?q=x", None),
                ("GET", f"/api/servers/{SID}/news", None), ("DELETE", f"/api/servers/{SID}/tasks/{t1}", None),
                ("POST", "/api/servers/move", {"from": {"server": SID, "task": t1}, "to": {"server": 0, "list_id": None}})):
    r = Ca.request(m, B + u, json=b)
    check(r.status_code == 404, f"carol {m} {u}: 404 ({r.status_code})")
check(Ca.get(B + "/api/servers").json()["links"] == [] and not gone(t1), "carol sees none of alice's accounts, nothing moved")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "otto", "display_name": "Otto"}).json()
for hd in ({"Authorization": "Bearer " + ag["token"]}, {"Authorization": "Bearer " + CTOK}):
    r = requests.get(B + "/api/servers", headers={**H, **hd})
    check(r.status_code in (401, 403, 404) and "links" not in r.text, f"a bearer token on /api/servers: refused ({r.status_code})")
    r = requests.post(B + "/api/servers/code", headers={**H, **hd}, json={})
    check(r.status_code in (401, 403, 404), f"a bearer token cannot make a connection code ({r.status_code})")
paths = requests.get(B + "/api/v1/openapi.json", headers={"Authorization": "Bearer " + ag["token"]}).json().get("paths") or {}
check(paths and not [p for p in paths if "servers" in p], "no /api/v1 route (agents see nothing of it)")

# ================================================================== remove, restore, limits
r = A.delete(B + f"/api/servers/{SIDE}")
check(r.ok and "revoke" in r.json()["hint"], "remove with the hint to revoke the token over there")
check(A.get(B + f"/api/servers/{SIDE}/data").status_code == 404 and SIDE not in [x["id"] for x in A.get(B + "/api/servers").json()["links"]],
      "a removed account: 404, not listed")
r = A.post(B + f"/api/servers/{SIDE}/restore")
check(r.ok and r.json()["id"] == SIDE, "restore (undo)")
check(A.post(B + f"/api/servers/{SIDE}/restore").status_code == 404, "restoring a live account: 404")
# 2.73.0 (#661) review N1: a removed account keeps its sealed token 30 days (undo), then the watchdog wipes it
r = A.post(B + "/api/servers", json={"base_url": f"{STUB}/evil/n8", "token": "abk_" + "w" * 40})
SIDW = r.json().get("id")
check(r.status_code == 201 and A.delete(B + f"/api/servers/{SIDW}").ok, f"N1: an account added and removed {r.text[:150]}")
time.sleep(2.5)
check(dbx("SELECT token_enc FROM msv_links WHERE id=?", (SIDW,))[0][0] != "", "N1: a freshly removed account keeps its token (undo)")
dbx("UPDATE msv_links SET deleted_at='2020-01-01T00:00:00Z' WHERE id=?", (SIDW,))
for _ in range(20):
    if dbx("SELECT token_enc FROM msv_links WHERE id=?", (SIDW,))[0][0] == "":
        break
    time.sleep(0.5)
check(dbx("SELECT token_enc FROM msv_links WHERE id=?", (SIDW,))[0][0] == "", "N1: 30 days after removing the watchdog wiped the token")
r = A.post(B + f"/api/servers/{SIDW}/restore")
check(r.status_code == 409 and "token again" in r.json()["error"], f"N1: restoring it then asks for the token again {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/servers/{SIDE}", json={"default_inbox": True, "position": 5, "short": "ev"})
check(r.ok and r.json()["default_inbox"] is True and r.json()["short"] == "EV", "quick add lands there by default")
A.patch(B + f"/api/servers/{SIDC}", json={"default_inbox": True})
lk = {x["id"]: x for x in A.get(B + "/api/servers").json()["links"]}
check(lk[SIDC]["default_inbox"] and not lk[SIDE]["default_inbox"], "only one account is the default")
check(A.patch(B + f"/api/servers/{SIDE}", json={"default_inbox": "yes"}).status_code == 400, "default_inbox needs a boolean")
check(A.patch(B + f"/api/servers/{SIDE}", json={"base_url": "http://x"}).status_code == 400, "the address cannot be changed: 400")
ex = A.get(B + "/api/export.json").text
check(BTOK not in ex and CTOK not in ex, "no token in the export")
for i in range(7):
    A.post(B + "/api/servers", json={"base_url": f"{STUB}/evil/n{i}", "token": "abk_" + "q" * 40})
r = A.post(B + "/api/servers", json={"base_url": f"{STUB}/evil/n9", "token": "abk_" + "q" * 40})
check(r.status_code == 409, f"at most 10 accounts per person ({r.status_code})")

# ================================================================== a hosted server: https only, no internal hosts
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**env, "KEEP": "1", "EXTRA": BASE_EXTRA + " -e KALMIDO_HOSTED=1"})
A = sess("alice", hooks=[on500])
dbx("DELETE FROM msv_links WHERE base_url LIKE ?", (f"{STUB}/evil/n%",))
r = A.post(B + "/api/servers", json={"base_url": SELF, "token": CTOK})
check(r.status_code == 400 and "https" in r.json()["error"], f"hosted: http refused ({r.status_code} {r.text[:150]})")
r = A.post(B + "/api/servers", json={"base_url": "https://127.0.0.1:3040", "token": CTOK})
check(r.status_code == 400 and "internal" in r.json()["error"], f"hosted: an internal https address refused, the allow-list does not count {r.text[:150]}")
r = A.get(B + f"/api/servers/{SIDE}/data")
check(r.status_code == 424 and r.json()["code"] == "offline", f"hosted: a stored http account is not reached {r.text[:150]}")

# review H1: at most 120 reads of other servers per person and minute (here they fail fast: hosted refuses http)
codes = [A.get(B + f"/api/servers/{SIDE}/data").json().get("code") for _ in range(125)]
check(codes.count("busy") >= 5 and codes[-1] == "busy" and codes[0] == "offline", f"H1: the 121st read in a minute: busy {codes[-8:]}")

print(f"p273_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
