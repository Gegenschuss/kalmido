#!/usr/bin/env python3
"""2.281.0 API tests, part B (#3110, #3117): the team chat overview without a query per member, no channel rows written by
GET /api/state, the chat rate limit, the reminder wave and the push badge. Own container (start.sh). Invented people only.
freelancer-matrix: team
 - #3110 the members of a list channel are the same as before (owner, members, a guest and a read-only person of the
   organisation, an agent; not a participant, not a leftover member row of someone outside the organisation), the same for
   every member's /api/team and /api/v1/team/rooms; unread counts and mentions as before (/api/team, /api/state, read)
 - #3110 statements: /api/team, /api/team/channels and POST .../read no longer grow per member (2 vs. 22 members of a list
   channel / 2 vs. 22 of a channel), and per added shared list only by a small constant
 - #3110 GET /api/state writes no channel row: it answers while another transaction holds the insert of that row (before it
   waited for it), and no row appears; /api/team still creates the channel of a newly shared list
 - #3117 the 61st message of a person within the rate window: 429 with a message, a resent message (same client_id) is not
   refused, after the window it goes through again (waited for by retrying, no fixed sleep); another person is not limited
 - #3117 the reminder wave: 20 due reminders cost (almost) no more statements per reminder than 2 (list role and push
   settings once per tick); the push badge is only counted for a person with devices
 - a person without an organisation: the channel of the own list shared with another freelancer, unread / read, limits
usage: p2281_a_teamchat_test.py <datadir>   (P2281A_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

from kt import FAILS, OKS, check, until, B, H, DATA  # noqa: E402
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEATURES = "cal,collab,comments"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
NOSTART = os.environ.get("P2281A_NOSTART") or os.environ.get("KMT_NOSTART")
RATE_S = 60 if NOSTART else 30  # the rate window (KALMIDO_TEST_RATE_WINDOW_S, test containers only)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-600:]


if not NOSTART:
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + f" -e KALMIDO_TEST_RATE_WINDOW_S={RATE_S}").strip()))
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A = login(B, "alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta"})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}


def person(name, org, role="member"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = login(B, name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
    return s


A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
Bo, Gi, Ri, Da = person("bob", ORG), person("gina", ORG, "guest"), person("rita", ORG, "readonly"), person("dave", ORG)
Ca = person("carl", BETA)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
uid["claude"], CLT = r.json()["id"], r.json()["token"]
CL = requests.Session()
CL.headers.update({"Authorization": "Bearer " + CLT})


def team(s):
    r = s.get(B + "/api/team")
    assert r.ok, r.text
    return r, {x["id"]: x for x in r.json()["rooms"]}


def room_of_list(s, lid):
    return next((x for x in team(s)[1].values() if x.get("list_id") == lid), None)


def post(s, rid, text, **kw):
    return s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": text, **kw})


# ================================================================ #3110: the same members, rooms and unread counts
LA = A.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG}).json()["id"]
for who, role in (("bob", "edit"), ("gina", "view"), ("rita", "edit"), ("dave", "participant"), ("claude", "edit")):
    check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid[who], "role": role}).ok, f"setup: {who} {role} in the list")
# a member row left behind for someone outside the organisation (the boundary keeps them out, as list_role did)
dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,?,?)", (LA, uid["carl"], "edit", "2026-10-20T08:00:00"))
EXP = {uid[x] for x in ("alice", "bob", "gina", "rita", "claude")}
ra = room_of_list(A, LA)
check(ra is not None and ra["members"] == len(EXP) and ra["name"] == "Shoot plan",
      f"#3110 alice: the channel of the shared list with owner, member, guest, read-only person and agent {ra}")
RID = (ra or {}).get("id")
for who, s in (("bob", Bo), ("gina", Gi), ("rita", Ri)):
    x = room_of_list(s, LA)
    check(x is not None and x["id"] == RID and x["members"] == len(EXP), f"#3110 {who}: the same channel, the same member count {x}")
check(room_of_list(Da, LA) is None, "#3110 a participant is not in the channel")
check(room_of_list(Ca, LA) is None, "#3110 a leftover member row outside the organisation: not in the channel")
j = A.get(B + f"/api/team/rooms/{RID}/messages").json()
got = {m["id"] for m in j["room"]["members"]}
check(got == EXP, f"#3110 the members of the room page are the same {sorted(got)} vs {sorted(EXP)}")
check([m["id"] for m in j["room"]["members"] if m["agent"]] == [uid["claude"]], "#3110 the agent is marked as agent (one lookup)")
v = CL.get(B + "/api/v1/team/rooms")
check(v.ok and any(x["id"] == RID and x["members"] == len(EXP) for x in v.json().get("data", [])),
      f"#3110 the agent sees the channel through /api/v1/team/rooms {v.text[:200]}")

# unread and mentions as before
check(post(Bo, RID, "Call sheet is up").status_code == 201, "setup: bob writes")
check(post(Bo, RID, f"<@{uid['alice']}> please check the props").status_code == 201, "setup: bob mentions alice")
x = room_of_list(A, LA)
check(x["unread"] == 2 and x["mention"] is True and x["last"]["text"].endswith("please check the props"),
      f"#3110 alice: two unread, a mention, the newest as preview {x}")
x = room_of_list(Gi, LA)
check(x["unread"] == 2 and x["mention"] is False, f"#3110 gina: two unread, no mention {x}")
st = A.get(B + "/api/state").json()["team"]
check(st.get("unread") == 2 and st.get("dm_unread") == 0, f"#3110 /api/state: the same unread counts {st}")
r = A.post(B + f"/api/team/rooms/{RID}/read", json={})
check(r.ok and r.json().get("unread") == 0, f"#3110 read: the total unread count after reading {r.text[:200]}")
check(Gi.get(B + "/api/state").json()["team"].get("unread") == 2, "#3110 gina's count stays")
check(room_of_list(A, LA)["unread"] == 0, "#3110 alice: read")

# ================================================================ #3110: statements per member / per list
LB = A.post(B + "/api/lists", json={"name": "Edit plan", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LB}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob in the second list")
RB = room_of_list(A, LB)["id"]
CH = A.post(B + "/api/team/channels", json={"name": "Crew", "org_id": ORG, "members": [uid["bob"]]})
check(CH.status_code in (200, 201), f"setup: a channel {CH.text[:200]}")
CHID = CH.json().get("id")
team(A)


def counts():
    n_team = nstmt(team(A)[0])
    n_chan = nstmt(A.get(B + "/api/team/channels"))
    n_read = nstmt(A.post(B + f"/api/team/rooms/{RB}/read", json={}))
    n_state = nstmt(A.get(B + "/api/state"))
    return n_team, n_chan, n_read, n_state


c2 = counts()
MANY = []
for i in range(20):
    person(f"crew{i}", ORG)
    MANY.append(uid[f"crew{i}"])
    check(A.put(B + f"/api/lists/{LB}/members", json={"user_id": uid[f"crew{i}"], "role": "edit"}).ok, f"setup: crew{i} in the list")
    check(A.post(B + f"/api/team/rooms/{CHID}/members", json={"user_id": uid[f"crew{i}"]}).ok, f"setup: crew{i} in the channel")
x = room_of_list(A, LB)
check(x["members"] == 22, f"#3110 22 members in the list channel {x}")
check(team(A)[1][CHID]["members"] == 22, "#3110 22 members in the channel")
c22 = counts()
for k, name in enumerate(("/api/team", "/api/team/channels", "read")):  # /api/state: information (other parts list people)
    check(0 < c22[k] <= c2[k] + 2, f"#3110 {name}: 22 members cost what 2 cost ({c2[k]} -> {c22[k]})")
print(f"PERF #3110 statements 2 -> 22 members: /api/team {c2[0]} -> {c22[0]}, channels {c2[1]} -> {c22[1]}, read {c2[2]} -> "
      f"{c22[2]}, /api/state {c2[3]} -> {c22[3]}", flush=True)
# per added shared list a small constant (before: list role + members twice per list, each member's role)
for i in range(10):
    lid = A.post(B + "/api/lists", json={"name": f"Day {i}", "org_id": ORG}).json()["id"]
    for m in MANY[:5]:
        A.put(B + f"/api/lists/{lid}/members", json={"user_id": m, "role": "edit"})
team(A)  # creates the ten channel rows
c12 = counts()
check(0 < c12[0] <= c22[0] + 10 * 3, f"#3110 /api/team: ten more shared lists cost at most three statements each ({c22[0]} -> {c12[0]})")
print(f"PERF #3110 statements 2 -> 12 shared lists: /api/team {c22[0]} -> {c12[0]}, /api/state {c22[3]} -> {c12[3]}", flush=True)

# ================================================================ #3110: GET /api/state writes no channel row
LN = A.post(B + "/api/lists", json={"name": "New share", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LN}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: a newly shared list")
check(not dbx("SELECT 1 FROM tchat_rooms WHERE kind='list' AND list_id=?", (LN,)), "setup: no channel row yet")
# another transaction inserts the channel row and keeps it open: an insert of the same row by /api/state would wait for it
dbc, dbn = open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8").read().split()
hold = subprocess.Popen(["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-d", dbn, "-X", "-q"], stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
hold.stdin.write(f"BEGIN; INSERT INTO tchat_rooms(kind,list_id,created_at) VALUES('list',{int(LN)},'2026-10-24T08:00:00'); "
                 "SELECT pg_sleep(20); ROLLBACK;\n")
hold.stdin.flush()
check(bool(until(lambda: dbx("SELECT 1 FROM pg_stat_activity WHERE query LIKE '%pg_sleep(20)%' AND state='active' "
                             "AND pid<>pg_backend_pid()"), 15)), "setup: the other transaction holds the row")
res = {}


def state_of(k, s):
    t0 = time.monotonic()
    try:
        res[k] = (s.get(B + "/api/state", timeout=12).status_code, time.monotonic() - t0)
    except requests.RequestException as e:
        res[k] = (str(e)[:80], time.monotonic() - t0)


ths = [threading.Thread(target=state_of, args=(k, s)) for k, s in (("alice", A), ("bob", Bo))]
for t in ths:
    t.start()
for t in ths:
    t.join(30)
check(all(v[0] == 200 and v[1] < 8 for v in res.values()) and len(res) == 2,
      f"#3110 two parallel /api/state answer without waiting for the channel row (no insert) {res}")
hold.stdin.close()
hold.wait(40)
check(not dbx("SELECT 1 FROM tchat_rooms WHERE kind='list' AND list_id=?", (LN,)), "#3110 /api/state wrote no channel row")
x = room_of_list(A, LN)
check(x is not None and x["members"] == 2, f"#3110 /api/team creates the channel of the newly shared list {x}")
check(len(dbx("SELECT 1 FROM tchat_rooms WHERE kind='list' AND list_id=?", (LN,))) == 1, "#3110 ... and keeps it (committed)")

# ================================================================ #3117: the chat rate limit
Rh = person("rhea", ORG)  # a person who has not written yet
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["rhea"], "role": "edit"}).ok, "setup: rhea in the list")
RL = room_of_list(Rh, LA)["id"]
t0 = time.monotonic()
codes = [post(Rh, RL, f"Line {i}", client_id=f"c-{i}").status_code for i in range(60)]
check(time.monotonic() - t0 < RATE_S - 2, f"setup: the 60 messages fit into the window ({time.monotonic() - t0:.1f} s)")
check(codes == [201] * 60, f"#3117 60 messages within the window go through {sorted(set(codes))}")
r = post(Rh, RL, "Line 61", client_id="c-61")
check(r.status_code == 429 and r.json().get("error"), f"#3117 the 61st message: 429 with a message {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM tchat_msgs WHERE body='Line 61'"), "#3117 the refused message is not stored")
r = post(Rh, RL, "Line 62")
check(r.status_code == 429, "#3117 still limited")
r = post(Rh, RL, "Line 59", client_id="c-59")
check(r.status_code == 200 and r.json().get("body") == "Line 59", f"#3117 a resent message (same client_id) answers the stored one, not 429 {r.status_code}")
check(post(Gi, RL, "Gina is not limited").status_code == 201, "#3117 another person is not limited")
r = until(lambda: post(Rh, RL, "Line 61", client_id="c-61").status_code == 201, RATE_S + 20, step=1)
check(bool(r), f"#3117 after the window the message goes through (window {RATE_S} s)")
check(len(dbx("SELECT 1 FROM tchat_msgs WHERE body='Line 61'")) == 1, "#3117 stored once")
r = post(Rh, RL, "Line 61", client_id="c-61")
check(r.status_code == 200, f"#3117 the same message sent again (client_id) answers the stored one {r.status_code}")

# ================================================================ #3117: the reminder wave and the push badge
OL = A.post(B + "/api/lists", json={"name": "Due work", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob in the reminder list")
now = datetime.fromisoformat(in_app("from kalmido.core.db import local_now\nprint(local_now().replace(tzinfo=None).isoformat())"))
D1, D2 = (now + timedelta(days=3)).date().isoformat(), (now + timedelta(days=4)).date().isoformat()
for d, n in ((D1, 2), (D2, 20)):
    for i in range(n):
        r = A.post(B + "/api/tasks", json={"title": f"Due {d} {i}", "list_id": OL, "due": d, "due_time": "10:00", "reminders": "0",
                                           "assignee_id": uid["bob"]})
        check(r.ok, f"setup: task {d} {i}")
WAVE = """
from datetime import datetime
from kalmido.core.db import connect
from kalmido.core.config import TZ
from kalmido.notify import push as P
class W:
    def __init__(s, c): s.c, s.n = c, 0
    def execute(s, *a, **k):
        s.n += 1
        return s.c.execute(*a, **k)
    def __getattr__(s, k): return getattr(s.c, k)
c = connect()
users = {r["id"]: r for r in c.execute("SELECT * FROM users WHERE disabled=0")}
S = P._wd_settings(c, users)
LG = {u: "en" for u in users}
out = {}
for k, d in (("n2", "%s"), ("n20", "%s")):
    w = W(c)
    P._wd_reminders(w, users, S, LG, datetime.fromisoformat(d + "T10:01").replace(tzinfo=TZ))
    out[k] = w.n
# the badge: only for a person with devices (bob has none)
calls = []
P.badge_count = lambda u: calls.append(u) or 0
P.WEBPUSH_ON = True
P.notify(%d, "Hello", "Test", s=S[%d])
out["badge"] = len(calls)
c.close()
print(json.dumps(out))
""" % (D1, D2, uid["bob"], uid["bob"])
res = in_app(WAVE)
try:
    cnt = json.loads(res)
except ValueError:
    cnt = {}
check(bool(cnt), f"#3117 the reminder section ran inside the app: {res[:400]}")
if cnt:
    per = (cnt["n20"] - cnt["n2"]) / 18
    check(cnt["n2"] > 0 and per <= 3, f"#3117 20 due reminders: at most three statements per reminder more than 2 ({cnt})")
    check(cnt["badge"] == 0, f"#3117 a push to a person without devices counts no badge ({cnt})")
    print(f"PERF #3117 reminder wave: 2 reminders {cnt['n2']} statements, 20 reminders {cnt['n20']} ({per:.1f} per reminder)", flush=True)
fired = dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND reminded LIKE ?", (OL, "%|0%"))[0][0]
check(fired == 22, f"#3117 every due reminder fired (reminded written) {fired}")

# ================================================================ a person without an organisation (freelancer-matrix: team)
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
for s in (Fr, Fi):
    s.patch(B + "/api/settings", json={"features": FEATURES})
# two freelancers work together through a group of the instance (a group row, like p2139_a): then they may share a list
dbx("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-10-20T08:00:00", uid["alice"]))
GID = dbx("SELECT id FROM groups WHERE name=?", ("Freelance pool",))[0][0]
for x in (FID, FIO):
    dbx("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-10-20T08:00:00"))
FL = Fr.post(B + "/api/lists", json={"name": "Own studio"}).json()["id"]
r = Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FIO, "role": "edit"})
check(r.ok, f"freelancer: the own list shared with another freelancer {r.text[:200]}")
fx = room_of_list(Fr, FL)
check(fx is not None and fx["members"] == 2, f"freelancer: the channel of the own list {fx}")
if fx:
    check(post(Fi, fx["id"], "Draft is ready").status_code == 201, "freelancer: fiona writes")
    check(room_of_list(Fr, FL)["unread"] == 1 and Fr.get(B + "/api/state").json()["team"].get("unread") == 1,
          "freelancer: one unread (/api/team, /api/state)")
    r = Fr.post(B + f"/api/team/rooms/{fx['id']}/read", json={})
    check(r.ok and r.json().get("unread") == 0, "freelancer: read")
    check(room_of_list(A, FL) is None, "freelancer: alice sees nothing of it")

print(f"\np2281_a_teamchat: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
