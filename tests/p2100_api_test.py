#!/usr/bin/env python3
"""2.10.0 API, own containers (start.sh, isolated test databases), raw HTTP:
#445 trusted proxies: X-Forwarded-For / -Proto / -Host only from KALMIDO_TRUSTED_PROXIES (+ AUTH_TRUSTED_PROXIES), the
client address in failed-login lockouts per user name + address / address / user name (one attacker cannot lock a person
out), Secure cookies and CalDAV over https behind a TLS proxy, "none" = forwarded headers ignored, the proxy login still
bound to the direct peer and its port;
#441 groups: admin CRUD (people only, names unique, synced groups read-only), sharing a list / a folder with a group (role,
members gain and lose access automatically, effective role = the higher of personal and group, News), folder rename /
move / delete, assigning a task to a group (list must be shared with it, person and group exclusive, News for members,
"Assigned to me" via the API filter), "Take it" (members only, participants too), participant role via a group, CalDAV
calendars of group lists, API v1 (groups, list groups, take) + OpenAPI;
#440 day planning: working hours (validation), the built-in plan (free slots between calendar events and timed tasks,
order, default duration, overflow listed as "does not fit today", mode fill), the agent proposal of kind dayplan
(request, input, validation, apply as the person, undo / redo, only the person), the daily review (done / open / moved,
tomorrow) and its push. 2.11.0: a day plan NEVER changes due / due_time / deadline: applying sets plan_start + duration
only (web PATCH, proposal apply / undo / redo), planned tasks count as busy, a 2.10.0 "defer" answer is only listed,
plan_start validation, the API field, a repeating task's next occurrence starts unplanned.
usage: p2100_api_test.py <datadir>"""
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
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(extra=""):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=extra), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def setup():
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok


def sess(user, pw="password123", **hd):
    s = requests.Session()
    s.headers.update({**H, **hd})
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def login(user, pw, ip=None, **hd):
    h = {**H, **hd}
    if ip:
        h["X-Forwarded-For"] = ip
    return requests.post(B + "/api/auth/login", json={"username": user, "password": pw}, headers=h)


def dbx(q, a=()):
    con = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = con.execute(q, a).fetchall()
        con.commit()
        return r
    finally:
        con.close()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def wait_for(fn, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(0.25)
    return bool(fn())


def logs():
    return subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stdout


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)

    def put(self, p, **k):
        return self.req("PUT", p, **k)

    def patch(self, p, **k):
        return self.req("PATCH", p, **k)

    def delete(self, p, **k):
        return self.req("DELETE", p, **k)


def token(s, name="t"):
    r = s.post(B + "/api/me/tokens", json={"name": name, "scopes": ["read", "write"]})
    assert r.status_code == 201, r.text
    return r.json()["token"]


# ================================================================== #445 trusted proxies
start()
setup()
A = sess("alice")
A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
# the test container's peer is the Docker bridge gateway: trusted by default (and via AUTH_TRUSTED_PROXIES of start.sh)
for _ in range(5):
    check(login("bob", "wrong-pass", "203.0.113.7").status_code == 401, "wrong password: 401")
check(login("bob", "password123", "203.0.113.7").status_code == 429, "5 failures of bob from 203.0.113.7: locked there")
check(login("bob", "password123", "198.51.100.9").ok, "bob from another address still logs in (no lockout for everyone)")
check("from 203.0.113.7" in logs(), "the log names the forwarded client address")
for i in range(20):
    login(f"nobody{i}", "wrong-pass", "203.0.113.50")
check(login("alice", "password123", "203.0.113.50").status_code == 429, "20 failures from one address: that address is blocked")
check(login("alice", "password123", "203.0.113.51").ok, "a neighbour address is not")
check(login("alice", "password123", "203.0.113.50, 198.51.100.77").ok,
      "only the rightmost X-Forwarded-For entry counts (the one the proxy appended)")
r = login("alice", "password123", "198.51.100.10", **{"X-Forwarded-Proto": "https"})
check(r.ok and "Secure" in r.headers.get("Set-Cookie", ""), "X-Forwarded-Proto https from the proxy: Secure cookie")
r = login("alice", "password123", "198.51.100.10")
check(r.ok and "Secure" not in r.headers.get("Set-Cookie", ""), "plain http: no Secure flag")
check(login("alice", "password123", "not-an-ip").status_code in (200, 400), "a malformed X-Forwarded-For does not crash the app")
# the proxy login still trusts the DIRECT peer (+ its port), not a forwarded address
pp = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
A.patch(B + "/api/users/2", json={"proxy_login": "bobsso"})
r = requests.get(pp + "/api/state", headers={"Remote-User": "bobsso", "X-Forwarded-For": "198.51.100.3"})
check(r.ok and r.json()["me"]["username"] == "bob", f"proxy login on the proxy port still works with X-Forwarded-For ({r.status_code})")
r = requests.get(B + "/api/state", headers={"Remote-User": "bobsso", "X-Forwarded-For": "198.51.100.3"})
check(r.status_code == 401, "the proxy header is still ignored on the app port")
# CalDAV: http PUBLIC_URL, behind a TLS proxy -> https from X-Forwarded-Proto
start("-e PUBLIC_URL=http://kalmido.example")
setup()
A = sess("alice")
pw = A.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()["password"]
auth = ("alice", pw)
r = requests.request("PROPFIND", B + "/dav/", auth=auth, headers={"Depth": "0"})
check(r.status_code == 403, f"CalDAV over plain http without a proxy: refused ({r.status_code})")
r = requests.request("PROPFIND", B + "/dav/", auth=auth, headers={"Depth": "0", "X-Forwarded-Proto": "https"})
check(r.status_code == 207, f"CalDAV behind a TLS proxy (X-Forwarded-Proto https): allowed ({r.status_code})")
r = requests.request("PROPFIND", B + "/dav/", auth=auth, headers={"Depth": "0", "X-Forwarded-Proto": "http"})
check(r.status_code == 403, "a proxy that reports http: refused")
for _ in range(10):
    requests.request("PROPFIND", B + "/dav/", auth=("alice", "wrong"), headers={"Depth": "0", "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.8"})
r = requests.request("PROPFIND", B + "/dav/", auth=auth, headers={"Depth": "0", "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.8"})
check(r.status_code == 429, f"10 bad CalDAV logins from one address: alice locked THERE ({r.status_code})")
r = requests.request("PROPFIND", B + "/dav/", auth=auth, headers={"Depth": "0", "X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.8"})
check(r.status_code == 207, f"alice's phone on another address keeps working ({r.status_code})")
# KALMIDO_TRUSTED_PROXIES=none + no proxy login: forwarded headers are ignored (the direct peer is the client)
start("-e KALMIDO_TRUSTED_PROXIES=none -e AUTH_TRUSTED_PROXIES=")
setup()
for _ in range(5):
    login("alice", "wrong-pass", "203.0.113.9")
check(login("alice", "password123", "198.51.100.99").status_code == 429, "untrusted peer: X-Forwarded-For ignored (same peer = locked)")
check("from 203.0.113.9" not in logs(), "untrusted peer: the spoofed address is not logged")
r = login("bob", "x", None, **{"X-Forwarded-Proto": "https"})
check("Secure" not in r.headers.get("Set-Cookie", ""), "untrusted peer: X-Forwarded-Proto ignored")

# ================================================================== #441 groups
start()
setup()
A = sess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for x in (A, Bo, Ca, Da, Er):
    x.patch(B + "/api/settings", json={"lang": "en"})
ag = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper"})
AG, agt = ag.json()["id"], ag.json()["token"]

check(Bo.post(B + "/api/admin/groups", json={"name": "Office"}).status_code == 403, "only admins create groups")
check(A.post(B + "/api/admin/groups", json={"name": " "}).status_code == 400, "a name is needed")
check(A.post(B + "/api/admin/groups", json={"name": "Office", "members": [AG]}).status_code == 400, "agents cannot be group members")
r = A.post(B + "/api/admin/groups", json={"name": "Office", "members": [BOB, CAROL]})
check(r.ok and [m["user_id"] for m in r.json()["members"]] == [BOB, CAROL], f"group Office with bob + carol ({r.text[:200]})")
GID = r.json()["id"]
check(A.post(B + "/api/admin/groups", json={"name": "office"}).status_code == 409, "names are unique (case-insensitive)")
GSYNC = A.post(B + "/api/admin/groups", json={"name": "Sales", "oidc_group": "sales"}).json()["id"]
check(A.patch(B + f"/api/admin/groups/{GSYNC}", json={"members": [BOB]}).status_code == 409, "synced group: members not by hand")
st = Bo.get(B + "/api/state").json()
check(GID in st["my_groups"] and any(gr["name"] == "Office" for gr in st["groups"]), "state: groups + my groups")
check(Bo.get(B + "/api/groups").json()["mine"] == [GID], "GET /api/groups: mine")

L = A.post(B + "/api/lists", json={"name": "Office tasks"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Order paper", "list_id": L}).json()["id"]
vis = lambda s, lid: any(x["id"] == lid for x in s.get(B + "/api/state").json()["lists"])  # noqa: E731
role = lambda s, lid: next((x["role"] for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)  # noqa: E731
check(not vis(Bo, L), "before sharing: bob does not see the list")
check(Bo.put(B + f"/api/lists/{L}/groups/{GID}", json={"role": "edit"}).status_code == 404, "bob cannot share alice's list")
check(A.put(B + f"/api/lists/{L}/groups/{GID}", json={"role": "boss"}).status_code == 400, "bad role 400")
check(A.put(B + f"/api/lists/{L}/groups/{GID}", json={"role": "edit"}).ok, "alice shares the list with Office (edit)")
check(vis(Bo, L) and vis(Ca, L) and not vis(Da, L), "bob + carol see it, dave not")
check(role(Bo, L) == "edit", "role via the group: edit")
news = Bo.get(B + "/api/news").json()
check(any(n["kind"] == "share" and (n.get("data") or {}).get("group") == "Office" for n in news.get("items", [])), "News: shared via the group")
check(A.get(B + f"/api/lists/{L}/groups").json()["groups"] == [{"group_id": GID, "name": "Office", "role": "edit", "via": "list"}], "list groups")
# membership changes
check(A.patch(B + f"/api/admin/groups/{GID}", json={"members": [BOB, DAVE]}).ok, "carol out, dave in")
check(vis(Da, L) and not vis(Ca, L), "dave gains access, carol loses it")
check(Ca.get(B + f"/api/tasks/{T1}").status_code == 404, "carol: the task is gone for her")
# effective role = max(personal, group)
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "view"}).ok, "bob personally: viewer")
check(role(Bo, L) == "edit", "personal view + group edit = edit")
check(A.put(B + f"/api/lists/{L}/groups/{GID}", json={"role": "view"}).ok and role(Bo, L) == "view", "group view: bob view")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "admin"}).ok and role(Bo, L) == "admin", "personal admin wins")
r = A.delete(B + f"/api/lists/{L}/members/{BOB}")
check(r.ok and r.json().get("via_group") and role(Bo, L) == "view", "removing bob's own share: access via the group stays")
check(A.delete(B + f"/api/lists/{L}/groups/{GID}").ok and not vis(Bo, L) and not vis(Da, L), "unshared from the group: both lose access")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ERIN, "role": "edit"}).ok, "erin personal")
check(A.put(B + f"/api/lists/{L}/groups/{GID}", json={"role": "edit"}).ok, "shared with Office again")

# folder shares
F1 = A.post(B + "/api/lists", json={"name": "Plan A", "folder": "Team"}).json()["id"]
check(A.put(B + f"/api/folders/groups/{GID}", json={"folder": "Team", "role": "view"}).ok, "alice shares her folder Team with Office")
check(vis(Bo, F1) and role(Bo, F1) == "view", "bob sees the folder's list (view)")
F2 = A.post(B + "/api/lists", json={"name": "Plan B", "folder": "Team/Sub"}).json()["id"]
check(vis(Da, F2), "a new list in a subfolder is shared too")
check(A.patch(B + f"/api/lists/{F1}", json={"folder": ""}).ok and not vis(Bo, F1), "moved out of the folder: no longer shared")
check(A.post(B + "/api/folders/rename", json={"old": "Team", "new": "Crew"}).ok and vis(Bo, F2), "renamed folder: still shared")
check(A.get(B + "/api/folders/groups", params={"folder": "Crew"}).json()["groups"][0]["group_id"] == GID, "the share followed the rename")
check(A.post(B + "/api/folders/delete", json={"name": "Crew/Sub"}).ok, "subfolder deleted (its list goes up)")
check(vis(Bo, F2), "its list is now in Crew, still shared via Crew")
check(A.delete(B + f"/api/folders/groups/{GID}", params={"folder": "Crew"}).ok and not vis(Bo, F2), "folder share removed")

# assigning to a group
r = A.patch(B + f"/api/tasks/{T1}", json={"assignee_group_id": GSYNC})
check(r.status_code == 400, f"a group without access to the list cannot be assigned ({r.status_code})")
r = A.patch(B + f"/api/tasks/{T1}", json={"assignee_group_id": GID})
t = A.get(B + f"/api/tasks/{T1}").json()
check(r.ok and t["assignee_group_id"] == GID and t["assignee_id"] is None, "assigned to Office (nobody personally)")
check(any(n["kind"] == "assign" and (n.get("data") or {}).get("group") == "Office" for n in Da.get(B + "/api/news").json()["items"]),
      "News for the members: assigned to your group")
tb = Api(token(Bo))
check([x["id"] for x in tb.get("/tasks", params={"assignee_group": "mine"}).json()["data"]] == [T1], "API: assignee_group=mine")
check(tb.get(f"/tasks/{T1}").json()["assignee_group_id"] == GID, "API task: assignee_group_id")
check(Er.post(B + f"/api/tasks/{T1}/take", json={}).status_code == 409, "erin (not in the group) cannot take it")
r = Bo.post(B + f"/api/tasks/{T1}/take", json={})
t = A.get(B + f"/api/tasks/{T1}").json()
check(r.ok and t["assignee_id"] == BOB and t["assignee_group_id"] is None, "bob takes it: his, no longer the group's")
check(Da.post(B + f"/api/tasks/{T1}/take", json={}).status_code == 409, "dave is too late (409)")
check(any(n["kind"] == "take" for n in Da.get(B + "/api/news").json()["items"]), "News for the other members: bob took it")
check(A.patch(B + f"/api/tasks/{T1}", json={"assignee_group_id": GID}).ok and A.get(B + f"/api/tasks/{T1}").json()["assignee_id"] is None,
      "a group again clears the person")
check(A.patch(B + f"/api/tasks/{T1}", json={"assignee_id": DAVE}).ok and A.get(B + f"/api/tasks/{T1}").json()["assignee_group_id"] is None,
      "a person clears the group")
# participant role via a group: only assigned / group tasks
P = A.post(B + "/api/lists", json={"name": "Desk"}).json()["id"]
TP1 = A.post(B + "/api/tasks", json={"title": "for the group", "list_id": P}).json()["id"]
TP2 = A.post(B + "/api/tasks", json={"title": "secret", "list_id": P}).json()["id"]
A.put(B + f"/api/lists/{P}/groups/{GID}", json={"role": "participant"})
A.patch(B + f"/api/tasks/{TP1}", json={"assignee_group_id": GID})
seen = {x["id"] for x in Da.get(B + "/api/state").json()["tasks"] if x["list_id"] == P}
check(seen == {TP1}, f"participant via a group sees the group's task, not the rest: {seen}")
check(Da.patch(B + f"/api/tasks/{TP1}", json={"assignee_group_id": None}).status_code == 403, "a participant cannot unassign the group")
check(Da.post(B + f"/api/tasks/{TP1}/take", json={}).ok and A.get(B + f"/api/tasks/{TP1}").json()["assignee_id"] == DAVE, "a participant takes it")
# CalDAV: a group list is a calendar of the member
pw = Bo.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()["password"]
r = requests.request("PROPFIND", B + "/dav/calendars/bob/", auth=("bob", pw), headers={"Depth": "1"})
check(r.status_code == 207 and "Office tasks" in r.text,
      f"CalDAV: the group list is one of bob's calendars ({r.status_code})")
# API v1
r = tb.get("/groups").json()["data"]
check([x["name"] for x in r] == ["Office", "Sales"] and next(x for x in r if x["id"] == GID)["mine"], "API: GET /groups")
check(tb.get(f"/groups/{GID}").json()["members"][0]["user_id"] == BOB, "API: GET /groups/{id}")
check(tb.get(f"/lists/{L}/groups").json()["data"][0]["group_id"] == GID, "API: list groups")
ta = Api(token(A))
check(ta.put(f"/lists/{F1}/groups/{GID}", json={"role": "view", "x": 1}).status_code == 400, "API: unknown field 400")
check(ta.put(f"/lists/{F1}/groups/{GID}", json={"role": "view"}).ok and vis(Bo, F1), "API: share a list with a group")
check(ta.delete(f"/lists/{F1}/groups/{GID}").ok and not vis(Bo, F1), "API: unshare")
A.patch(B + f"/api/tasks/{T1}", json={"assignee_group_id": GID})
r = tb.post(f"/tasks/{T1}/take")
check(r.ok and r.json()["assignee_id"] == BOB, "API: take")
spec = requests.get(V + "/openapi.json").json()
for pth in ("/groups", "/groups/{id}", "/lists/{id}/groups", "/lists/{id}/groups/{group_id}", "/tasks/{id}/take", "/dayplan", "/dayplan/review"):
    check(pth in spec["paths"], f"OpenAPI documents {pth}")
check("assignee_group_id" in spec["components"]["schemas"]["Task"]["properties"], "OpenAPI: Task.assignee_group_id")
# deleting a group
check(A.delete(B + f"/api/admin/groups/{GID}").ok and not vis(Da, L) and vis(Er, L), "group deleted: access via it ends, personal stays")
check(dbx("SELECT COUNT(*) FROM tasks WHERE assignee_group_id IS NOT NULL")[0][0] == 0, "no task stays assigned to a deleted group")

# ================================================================== #440 day planning
check(A.patch(B + "/api/settings", json={"work_start": "25:00"}).status_code == 400, "bad working hours 400")
check(A.patch(B + "/api/settings", json={"review_time": "7"}).status_code == 400, "bad review time 400")
check(A.patch(B + "/api/settings", json={"work_start": "08:00", "work_end": "12:00"}).ok, "working hours 08:00-12:00")
check(A.get(B + "/api/state").json()["dayplan"]["work_start"] == "08:00", "state: dayplan.work_start")
D = date.today() + timedelta(days=7)
while D.weekday() != 2:  # a Wednesday in the future: the window is the whole working day
    D += timedelta(days=1)
DS = D.isoformat()
PL = A.post(B + "/api/lists", json={"name": "Day"}).json()["id"]
mk = lambda title, **k: A.post(B + "/api/tasks", json={"title": title, "list_id": PL, **k}).json()["id"]  # noqa: E731
FIX = mk("Standup", due=DS, due_time="09:00", duration=30)
HI = mk("Report", due=DS, priority=5, duration=60)
LO = mk("Tidy desk", due=DS)                       # no duration: 30 min
BIG = mk("Big thing", due=DS, duration=180)        # does not fit: deferred
SOON = mk("Prepare talk", due=(D + timedelta(days=3)).isoformat(), duration=30)
NODATE = mk("Read paper", priority=0)              # backlog without priority: not offered
# a calendar event 10:00-11:00 local (stored like a synced subscription)
dbx("INSERT INTO cal_subs(user_id,kind,name,url,status,created_at) VALUES(?,?,?,?,?,?)", (ALICE, "ics", "Work", "x", "ok", "2026-01-01T00:00:00Z"))
sub = dbx("SELECT MAX(id) FROM cal_subs")[0][0]
loc = datetime(D.year, D.month, D.day, 10, 0).astimezone()
ev0 = loc.astimezone(timezone.utc)
dbx("INSERT INTO cal_events(sub_id,uid,title,all_day,start,end,d0,d1) VALUES(?,?,?,?,?,?,?,?)",
    (sub, "e1", "Client call", 0, ev0.strftime("%Y-%m-%dT%H:%M:%SZ"), (ev0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), DS, DS))
p = A.get(B + "/api/dayplan", params={"date": DS}).json()
slots = {x["task_id"]: (x["start"], x["end"]) for x in p["plan"]}
check(p["work"] == {"start": "08:00", "end": "12:00"} and p["events"][0]["title"] == "Client call" and p["events"][0]["start"] == "10:00",
      f"plan: working hours + the event ({p['events']})")
check([x["task_id"] for x in p["fixed"]] == [FIX], "the timed task stays fixed")
check(slots.get(HI) == ("08:00", "09:00"), f"high priority + 60 min first: {slots.get(HI)}")
check(slots.get(LO) == ("09:30", "10:00"), f"the 30-min default fills the gap before the event: {slots.get(LO)}")
check(any(x["task_id"] == LO and x["estimated"] for x in p["plan"]), "the default duration is marked as estimated")
check(slots.get(SOON) == ("11:00", "11:30"), f"then a task due soon, after the event: {slots.get(SOON)}")
check(NODATE not in slots and BIG not in slots, "no backlog without priority; the 3 h task does not fit")
nxt = D + timedelta(days=1)
check([x["task_id"] for x in p["nofit"]] == [BIG] and "to" not in p["nofit"][0] and "defer" not in p,
      f"the 3 h task is only listed as not fitting (no new date): {p.get('nofit')}")
ov = [(a, b) for a, b in sorted(slots.values())]
check(all(ov[i][1] <= ov[i + 1][0] for i in range(len(ov) - 1)) and all("08:00" <= a and b <= "12:00" for a, b in ov), "no overlaps, inside the hours")
f = A.get(B + "/api/dayplan", params={"date": DS, "mode": "fill"}).json()
check({x["task_id"] for x in f["plan"]} == {SOON} and not f["nofit"], f"fill: only tasks not planned for that day ({f['plan']})")
check(A.get(B + "/api/dayplan", params={"date": "x"}).status_code == 400 and A.get(B + "/api/dayplan", params={"mode": "z"}).status_code == 400,
      "bad date / mode 400")
check(Bo.get(B + "/api/dayplan", params={"date": DS}).json()["plan"] == [], "bob's plan holds none of alice's tasks")
check(ta.get("/dayplan", params={"date": DS}).json()["plan"] == p["plan"], "API: GET /dayplan")

# the agent plans: a proposal of kind dayplan
A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "all"})
ac = Api(agt)
agents = A.get(B + "/api/proposals/agents").json()["agents"]
check(agents and agents[0]["id"] == AG and agents[0]["online"] is True, f"the agent is offered (online) ({agents})")
r = A.post(B + "/api/proposals", json={"agent_id": AG, "kind": "dayplan", "date": DS})
check(r.status_code == 201 and r.json()["kind"] == "dayplan", f"day plan request: 201 ({r.text[:200]})")
J = r.json()["id"]
inp = ac.get(f"/agent/jobs/{J}").json()["input"]
check(inp["date"] == DS and inp["work"]["start"] == "08:00" and {t["task_id"] for t in inp["tasks"]} >= {HI, LO, BIG, SOON}
      and FIX not in {t["task_id"] for t in inp["tasks"]} and inp["events"][0]["title"] == "Client call" and inp["builtin"]["plan"],
      "job input: day, hours, events, open tasks (not the fixed one), the built-in plan as a hint")
check(ac.post(f"/agent/jobs/{J}/proposal", json={"kind": "dayplan", "items": [{"task_id": NODATE + 999, "start": "08:00"}]}).status_code == 400,
      "a task that was not sent: 400")
check(ac.post(f"/agent/jobs/{J}/proposal", json={"kind": "dayplan", "items": [{"task_id": HI, "start": "8"}]}).status_code == 400, "bad time 400")
check(ac.post(f"/agent/jobs/{J}/proposal", json={"kind": "dayplan", "items": [{"task_id": HI, "start": "08:00", "x": 1}]}).status_code == 400,
      "unknown field 400")
good = {"kind": "dayplan", "summary": "Focus first", "items": [{"task_id": LO, "start": "08:00"}, {"task_id": HI, "start": "11:00", "duration": 60}],
        "defer": [{"task_id": BIG, "to": nxt.isoformat()}]}  # 2.10.0 shape: still accepted, read as nofit
r = ac.post(f"/agent/jobs/{J}/proposal", json=good)
check(r.status_code == 201, f"agent proposal accepted ({r.status_code} {r.text[:200]})")
check(ac.post(f"/agent/jobs/{J}/proposal", json=good).status_code in (200, 201), "the agent may replace it until it is applied")
v = A.get(B + f"/api/proposals/{J}").json()
check(v["state"] == "ready" and v["proposal"]["items"][0]["task_id"] == LO, "the person sees it (ready)")
check(v["proposal"].get("nofit") == [{"task_id": BIG, "note": ""}] and "defer" not in v["proposal"], f"defer is read as nofit, without a date: {v['proposal']}")
BEFORE = {i: A.get(B + f"/api/tasks/{i}").json() for i in (LO, HI, BIG)}
check(Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code == 404, "another person cannot apply it")
check(ac.post(f"/agent/jobs/{J}/approve").status_code in (400, 403, 404, 405, 409), "the agent cannot approve its own proposal")
r = A.post(B + f"/api/proposals/{J}/apply", json={"select": ["0", "1", "2"], "edits": {"1": {"time": "11:00", "duration": 45}}})
check(r.ok and r.json()["changed"] == 2, f"applied 2 changes; the nofit entry changes nothing ({r.text[:200]})")
t = {i: A.get(B + f"/api/tasks/{i}").json() for i in (LO, HI, BIG)}
check((t[LO]["plan_start"], t[LO]["duration"]) == (DS + "T08:00", 30), f"Tidy desk planned 08:00, 30 min ({t[LO]['plan_start']})")
check((t[HI]["plan_start"], t[HI]["duration"]) == (DS + "T11:00", 45), "Report planned 11:00 with the edited 45 min")
check(all((t[i]["due"], t[i]["due_time"], t[i]["deadline"]) == (BEFORE[i]["due"], BEFORE[i]["due_time"], BEFORE[i]["deadline"]) for i in t),
      "2.11.0: due date, due time and deadline of every task unchanged")
check(t[BIG] == BEFORE[BIG], "Big thing (does not fit) completely unchanged")
r = A.post(B + f"/api/proposals/{J}/undo")
t = {i: A.get(B + f"/api/tasks/{i}").json() for i in (LO, HI, BIG)}
check(r.ok and t[LO]["plan_start"] is None and t[LO]["duration"] is None and t[HI]["duration"] == 60 and t[HI]["plan_start"] is None
      and t[BIG]["due"] == DS, "undo: all back")
check(A.post(B + f"/api/proposals/{J}/redo").ok and A.get(B + f"/api/tasks/{LO}").json()["plan_start"] == DS + "T08:00", "redo")
t = A.get(B + f"/api/tasks/{LO}").json()
check(t["due"] == DS and t["due_time"] is None, "redo: the due date still untouched")
# planned tasks are busy time and no candidates any more; the rest of the day is planned around them
p2 = A.get(B + "/api/dayplan", params={"date": DS}).json()
fx = {x["task_id"]: (x["start"], x["reason"]) for x in p2["fixed"]}
check(fx.get(LO) == ("08:00", "planned") and fx.get(HI) == ("11:00", "planned") and fx.get(FIX) == ("09:00", "fixed"),
      f"planned tasks show as fixed 'planned' slots: {fx}")
check(not {LO, HI} & {x["task_id"] for x in p2["plan"]}, "planned tasks are not offered again")
s2 = sorted([(x["start"], x["end"]) for x in p2["plan"] + p2["fixed"]])
check(all(s2[i][1] <= s2[i + 1][0] for i in range(len(s2) - 1)), f"no overlaps with planned slots: {s2}")
A.post(B + f"/api/proposals/{J}/undo")
# the web app's way: PATCH plan_start + duration; due stays; an overdue task keeps its old due date
OVER = mk("Overdue report", due=(D - timedelta(days=2)).isoformat(), deadline=1)
r = A.patch(B + f"/api/tasks/{OVER}", json={"plan_start": DS + "T08:30", "duration": 20})
t = A.get(B + f"/api/tasks/{OVER}").json()
check(r.ok and t["plan_start"] == DS + "T08:30" and t["due"] == (D - timedelta(days=2)).isoformat() and t["deadline"], f"PATCH plan_start: due + deadline kept ({t})")
for bad in ("2026-13-01T08:00", DS + " 08:00", DS + "T25:00", DS, 5):
    check(A.patch(B + f"/api/tasks/{OVER}", json={"plan_start": bad}).status_code == 400, f"plan_start {bad!r}: 400")
check(A.patch(B + f"/api/tasks/{OVER}", json={"plan_start": ""}).ok and A.get(B + f"/api/tasks/{OVER}").json()["plan_start"] is None, "'' clears it")
check(ta.patch(f"/tasks/{OVER}", json={"plan_start": DS + "T09:45"}).ok and ta.get(f"/tasks/{OVER}").json()["plan_start"] == DS + "T09:45",
      "API v1: plan_start writable + readable")
spec = ta.get("/openapi.json").json()
check("plan_start" in spec["components"]["schemas"]["Task"]["properties"], "OpenAPI: Task.plan_start")
check("nofit" in spec["components"]["schemas"]["DayPlan"]["properties"] and "defer" not in spec["components"]["schemas"]["DayPlan"]["properties"],
      "OpenAPI: DayPlan.nofit")
A.delete(B + f"/api/tasks/{OVER}")
# a repeating task: the next occurrence starts unplanned
REP = mk("Weekly review", due=DS, repeat="FREQ=WEEKLY")
A.patch(B + f"/api/tasks/{REP}", json={"plan_start": DS + "T08:00"})
r = A.post(B + f"/api/tasks/{REP}/complete", json={})
t = A.get(B + f"/api/tasks/{REP}").json()
check(r.ok and t["status"] == 0 and t["due"] > DS and t["plan_start"] is None, f"repeat: next occurrence unplanned ({t['due']}, {t['plan_start']})")
u = r.json().get("undo")
if u:
    A.post(B + f"/api/tasks/{REP}/undo", json=u)
    t = A.get(B + f"/api/tasks/{REP}").json()
    check(t["due"] == DS and t["plan_start"] == DS + "T08:00", f"undo of the completion brings the plan back ({t['plan_start']})")
A.delete(B + f"/api/tasks/{REP}")
check(A.post(B + "/api/proposals", json={"agent_id": AG, "kind": "dayplan", "date": DS, "secret": 1}).status_code == 400, "unknown request field 400")

# the daily review
TODAY = date.today().isoformat()
DONE = mk("Done today", due=TODAY)
OPEN = mk("Still open", due=TODAY)
MOVED = mk("Moved away", due=TODAY)
A.post(B + f"/api/tasks/{DONE}/complete", json={})
A.patch(B + f"/api/tasks/{MOVED}", json={"due": (date.today() + timedelta(days=2)).isoformat()})
rv = A.get(B + "/api/dayplan/review").json()
check(DONE in [x["task_id"] for x in rv["done"]], "review: done today")
check(OPEN in [x["task_id"] for x in rv["open"]] and DONE not in [x["task_id"] for x in rv["open"]], "review: still open")
check(MOVED in [x["task_id"] for x in rv["moved"]], "review: moved away today")
check(rv["tomorrow"]["date"] > TODAY and isinstance(rv["tomorrow"]["plan"], list), "review: a plan for the next working day")
check(Bo.get(B + "/api/dayplan/review").json()["done"] == [], "bob's review is his own")
check(ta.get("/dayplan/review").json()["done"] == rv["done"], "API: GET /dayplan/review")
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.patch(B + "/api/settings", json={"review_time": "00:00"})
check(wait_for(lambda: any(x.get("title") == "Daily review" for x in pushes()), 10), "the review push at the chosen time")
rp = [x for x in pushes() if x.get("title") == "Daily review"]
check(rp and "1 done" in rp[0]["msg"] and "open" in rp[0]["msg"], f"push text: done / open ({rp and rp[0]['msg']})")
time.sleep(2.5)
check(len([x for x in pushes() if x.get("title") == "Daily review"]) == 1, "only once a day")

print(f"p2100_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
