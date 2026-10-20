#!/usr/bin/env python3
"""2.139.0 API tests, part A: threads in the team chat (#2127) and "Read by" (#2129). Invented names only.
 - threads: an answer carries thread_of (one level: an answer to an answer hangs at the same root); the main conversation
   lists no thread answers, the root carries thread_count / thread_last_at / thread_users; ?thread=<id> reads a thread
   (an answer's id names its thread too); a root of another room, a deleted root, a bad value = 400
 - unread: the main conversation + the threads I take part in (root author, answered, mentioned); reading a thread only
   looking does not make me take part; a read mark per thread
 - pushes: a thread answer notifies its people only (not the whole channel), the room's mute still applies; a DM both
 - read receipts: read_by at my own messages (main conversation: tchat_reads, a thread: its read marks), room.read_ok;
   "Send read receipts" off = not shown in either direction; agents count when they mark read; the version marker t moves
   when someone else reads
 - strangers see neither a thread nor read_by; agents read / answer threads through v1 (only rooms they are in) and get
   thread_of in team_message
 - a person without an organisation: a DM thread with read receipts (freelancer-matrix: team)
usage: p2139_a_api_test.py <datadir>      (a fresh container; P2139A_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
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


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def until(fn, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.3)
    return fn()


if not os.environ.get("P2139A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta"}).json()["id"]
A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "t-alice"})
ids = {}
for u, o in (("bob", ORG), ("carol", ORG), ("dave", ORG), ("fred", ORG), ("eve", BETA)):
    r = A.post(B + "/api/users", json={"orgs": [o], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, FRED, EVE = ids["bob"], ids["carol"], ids["dave"], ids["fred"], ids["eve"]
Bo, Ca, Da, Fe, Ev = sess("bob"), sess("carol"), sess("dave"), sess("fred"), sess("eve")
for x in (A, Bo, Ca, Da, Fe, Ev):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude", "org_id": ORG})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
# alice and bob share a list (its channel + they may write each other directly)
TEAM = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": BOB, "role": "edit"}).ok
TROOM = [x for x in A.get(B + "/api/team").json()["rooms"] if x.get("list_id") == TEAM][0]["id"]
# a channel of the organisation: alice, bob, carol, dave, fred and the agent
r = A.post(B + "/api/team/channels", json={"name": "Project", "org_id": ORG, "open": False, "members": [BOB, CAROL, DAVE, FRED]})
assert r.status_code == 201, r.text
PRJ = r.json()["id"]
assert A.post(B + f"/api/team/rooms/{PRJ}/members", json={"user_id": CL}).ok


def post(s, rid, body, **kw):
    return s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": body, **kw})


def page(s, rid, thread=None):
    return s.get(B + f"/api/team/rooms/{rid}/messages" + (f"?thread={thread}" if thread else ""))


def room_of(s, rid):
    return next((x for x in s.get(B + "/api/team").json()["rooms"] if x["id"] == rid), {})


def msg(s, rid, mid, thread=None):
    jj = j(page(s, rid, thread))
    return next((m for m in jj.get("messages", []) + ([jj["root"]] if jj.get("root") else []) if m["id"] == mid), None)


# ================================================================== threads
R = j(post(A, PRJ, "Kickoff on Monday?")).get("id")
r = post(Bo, PRJ, "Monday works for me", thread_of=R)
check(r.status_code == 201 and r.json()["thread_of"] == R, "thread: bob answers in the thread " + r.text[:200])
T1 = j(r).get("id")
r = post(Ca, PRJ, "Me too", thread_of=T1)
check(r.status_code == 201 and r.json()["thread_of"] == R, "thread: an answer to an answer hangs at the same root " + r.text[:200])
T2 = j(r).get("id")
jj = j(page(A, PRJ))
mids = [m["id"] for m in jj["messages"]]
check(R in mids and T1 not in mids and T2 not in mids, f"thread: the main conversation lists no thread answers {mids}")
root = next(m for m in jj["messages"] if m["id"] == R)
check(root["thread_count"] == 2 and root["thread_users"][:2] == [CAROL, BOB] and root["thread_last_at"] and root["thread_of"] is None,
      f"thread: the root carries count / last writers / last time {root}")
jj = j(page(A, PRJ, R))
check(jj.get("root", {}).get("id") == R and [m["id"] for m in jj["messages"]] == [T1, T2] and jj["root"]["thread_count"] == 2,
      "thread: ?thread=<root> reads it " + json.dumps(jj)[:300])
check(j(page(A, PRJ, T2)).get("root", {}).get("id") == R, "thread: an answer's id names its thread")
check(page(A, PRJ, 99999999).status_code == 404, "thread: an unknown id = 404")
check(post(A, TROOM, "elsewhere", thread_of=R).status_code == 400, "thread: a root of another room = 400")
X = j(post(A, PRJ, "to be deleted")).get("id")
assert A.delete(B + f"/api/team/messages/{X}").ok
check(post(Bo, PRJ, "late", thread_of=X).status_code == 400, "thread: a deleted root = 400")
check(post(Bo, PRJ, "bad", thread_of=True).status_code == 400 and post(Bo, PRJ, "bad", thread_of="x").status_code == 400, "thread: a bad value = 400")
check(post(Bo, PRJ, "bad", thread_of=99999999).status_code == 400, "thread: an unknown root = 400")

# a stranger (another organisation, not a member) sees nothing
check(page(Ev, PRJ, R).status_code == 404, "stranger: no thread (404)")
check(Ev.post(B + f"/api/team/rooms/{PRJ}/read", json={"thread": R}).status_code == 404, "stranger: no read mark in a thread (404)")
check(post(Ev, PRJ, "hi", thread_of=R).status_code == 404, "stranger: cannot answer (404)")

# ================================================================== unread
check(room_of(A, PRJ).get("unread") == 2, f"unread: alice (root author) counts the 2 answers {room_of(A, PRJ)}")
check(room_of(Da, PRJ).get("unread") == 1, f"unread: dave (no part in the thread) counts only the main message {room_of(Da, PRJ)}")
check(room_of(Bo, PRJ).get("unread") == 2, f"unread: bob = the root (main) + carol's answer {room_of(Bo, PRJ)}")
T3 = j(post(Ca, PRJ, f"<@{DAVE}> can you book the room?", thread_of=R)).get("id")
rd = room_of(Da, PRJ)
check(rd.get("unread") == 2 and rd.get("mention") is True, f"unread: a mention in the thread makes dave take part {rd}")
r = Da.post(B + f"/api/team/rooms/{PRJ}/read", json={"thread": R})
check(r.ok and r.json()["last_id"] == T3 and room_of(Da, PRJ).get("unread") == 1, "unread: dave read the thread " + r.text[:200])
check(Da.post(B + f"/api/team/rooms/{PRJ}/read", json={}).ok and room_of(Da, PRJ).get("unread") == 0, "unread: dave read the main conversation")
check(Da.post(B + f"/api/team/rooms/{PRJ}/read", json={"thread": "x"}).status_code == 400, "read: a bad thread = 400")
rt = msg(A, PRJ, R)
check(rt and rt["thread_unread"] == 3 and rt["thread_follow"] is True, f"unread: the root shows alice's 3 unread answers {rt}")
check(msg(Fe, PRJ, R)["thread_unread"] == 0 and msg(Fe, PRJ, R)["thread_follow"] is False, "unread: fred takes no part")
# fred only looks: his mark is kept, he still takes no part
check(Fe.post(B + f"/api/team/rooms/{PRJ}/read", json={"thread": R}).ok and msg(Fe, PRJ, R)["thread_follow"] is False, "unread: looking does not make fred take part")

# ================================================================== pushes
clear()
T4 = j(post(Bo, PRJ, "Room 2 is free")).get("id")  # a main message in a channel: no push without a mention (as before)
T4 = j(post(Bo, PRJ, "Room 2 is free", thread_of=R)).get("id")
got = until(lambda: {p["topic"] for p in pushes()} >= {"t-alice", "t-carol", "t-dave"} and {p["topic"] for p in pushes()})
time.sleep(1)
tops = sorted(p["topic"] for p in pushes())
check(set(tops) == {"t-alice", "t-carol", "t-dave"}, f"push: a thread answer goes to its people only {tops}")
check(all(f"#msg/t/{PRJ}/{T4}" in (p.get("click") or "") for p in pushes()), f"push: it opens the thread {[p.get('click') for p in pushes()]}")
check(Da.post(B + f"/api/team/rooms/{PRJ}/read", json={"muted": True}).ok, "push: dave mutes the channel")
clear()
post(Ca, PRJ, "Booked", thread_of=R)
until(lambda: {p["topic"] for p in pushes()} >= {"t-alice", "t-bob"})
time.sleep(1)
tops = sorted(p["topic"] for p in pushes())
check(set(tops) == {"t-alice", "t-bob"}, f"push: the mute still applies in a thread {tops}")
Da.post(B + f"/api/team/rooms/{PRJ}/read", json={"muted": False})
# a direct message: both people take part
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
DR = j(post(A, DM, "Quick question")).get("id")
clear()
DT = j(post(A, DM, "About the offer", thread_of=DR)).get("id")
check(until(lambda: [p for p in pushes() if p["topic"] == "t-bob"]), "push: a DM thread answer reaches the other person")
check(room_of(Bo, DM).get("unread") == 2, f"unread: in a DM both take part {room_of(Bo, DM)}")

# ================================================================== agents (v1)
r = requests.get(V + f"/team/rooms/{PRJ}/messages", headers=CLH)
check(r.ok and next(m for m in r.json()["data"] if m["id"] == R)["thread_count"] >= 4, "v1: the agent sees the thread count " + r.text[:200])
r = requests.get(V + f"/team/rooms/{PRJ}/messages?thread={R}", headers=CLH)
check(r.ok and r.json()["root"]["id"] == R and T4 in [m["id"] for m in r.json()["data"]], "v1: the agent reads the thread " + r.text[:200])
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = requests.post(V + f"/team/rooms/{PRJ}/messages", headers=CLH, json={"body": "I can draft the agenda", "thread_of": R})
check(r.status_code == 201 and r.json()["thread_of"] == R, "v1: the agent answers in the thread " + r.text[:200])
CT = j(r).get("id")
post(A, PRJ, f"<@{CL}> please add the budget", thread_of=R)
evs = until(lambda: [e for e in requests.get(V + f"/agent/events?since={cur}", headers=CLH).json()["data"] if e["event"] == "team_message"])
check(evs and evs[0]["data"]["message"]["thread_of"] == R, f"v1: team_message carries thread_of {evs[:1]}")
check(requests.get(V + f"/team/rooms/{TROOM}/messages?thread={R}", headers=CLH).status_code == 404, "v1: not a room of the agent = 404")
r = requests.post(V + f"/team/rooms/{PRJ}/read", headers=CLH, json={"thread": R})
check(r.ok and r.json()["thread"] == R, "v1: the agent marks the thread read " + r.text[:200])
check(requests.post(V + f"/team/rooms/{PRJ}/read", headers=CLH, json={"thread": R, "x": 1}).status_code == 400, "v1: unknown fields = 400")
rb = (msg(Ca, PRJ, CT, R) or {}).get("read_by")
check(rb is None, "read_by: only at one's own messages")
rb = (msg(Bo, PRJ, T4, R) or {}).get("read_by") or {}
check(CL in rb.get("users", []) and DAVE not in rb.get("users", []), f"read_by: in a thread its marks count (agent read, dave did not) {rb}")

# ================================================================== read receipts (main conversation)
M1 = j(post(A, PRJ, "Agenda is up")).get("id")
check((msg(A, PRJ, M1) or {}).get("read_by", {}).get("count") == 0, "read_by: nobody read it yet")
for s in (Bo, Da):
    s.post(B + f"/api/team/rooms/{PRJ}/read", json={})
jj = j(page(A, PRJ))
m1 = next(m for m in jj["messages"] if m["id"] == M1)
check(set(m1["read_by"]["users"]) == {BOB, DAVE} and m1["read_by"]["count"] == 2, f"read_by: bob and dave read it {m1.get('read_by')}")
check(set(jj["room"]["read_ok"]) == {BOB, CAROL, DAVE, FRED, CL}, f"read_by: read_ok = the other members {jj['room'].get('read_ok')}")
check("read_by" not in next(m for m in j(page(Bo, PRJ))["messages"] if m["id"] == M1), "read_by: not at other people's messages")
check(requests.post(V + f"/team/rooms/{PRJ}/read", headers=CLH, json={}).ok and CL in msg(A, PRJ, M1)["read_by"]["users"], "read_by: the agent counts once it marked read")
r = requests.post(V + f"/team/rooms/{PRJ}/messages", headers=CLH, json={"body": "Agenda checked"})
CM = j(r).get("id")
Bo.post(B + f"/api/team/rooms/{PRJ}/read", json={})
cm = next((m for m in requests.get(V + f"/team/rooms/{PRJ}/messages", headers=CLH).json()["data"] if m["id"] == CM), {})
check(BOB in (cm.get("read_by") or {}).get("users", []), f"v1: the agent sees who read its message {cm.get('read_by')}")
# the version marker moves when someone else reads
M2 = j(post(A, PRJ, "One more thing")).get("id")
t0 = A.get(B + "/api/version").json()["t"]
Ca.post(B + f"/api/team/rooms/{PRJ}/read", json={})
check(A.get(B + "/api/version").json()["t"] != t0, "live: alice's marker t moves when carol reads")
# off = both ways
check(Da.patch(B + "/api/settings", json={"chat_read_receipts": "0"}).ok, "receipts: dave switches them off")
check(Da.patch(B + "/api/settings", json={"chat_read_receipts": "maybe"}).status_code == 400, "receipts: a bad value = 400")
Da.post(B + f"/api/team/rooms/{PRJ}/read", json={})
jj = j(page(A, PRJ))
m2 = next(m for m in jj["messages"] if m["id"] == M2)
check(DAVE not in m2["read_by"]["users"] and DAVE not in jj["room"]["read_ok"], f"receipts off: alice does not see dave's mark {m2.get('read_by')}")
D1 = j(post(Da, PRJ, "Room booked")).get("id")
A.post(B + f"/api/team/rooms/{PRJ}/read", json={})
jd = j(page(Da, PRJ))
check("read_by" not in next(m for m in jd["messages"] if m["id"] == D1) and jd["room"]["read_ok"] is None, "receipts off: dave sees nobody's either")
check(Da.patch(B + "/api/settings", json={"chat_read_receipts": "1"}).ok and ALICE in msg(Da, PRJ, D1)["read_by"]["users"], "receipts on again: dave sees alice read it")
check("read_by" not in json.dumps(j(page(Ev, PRJ))), "stranger: no read_by")

# ================================================================== a person without an organisation
# freelancer-matrix: team
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
import dbx  # noqa: E402  (two freelancers work together through a group of the instance: a group row, like p2113b_b)
DBC = dbx.connect(DATA)
DBC.execute("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-10-20T08:00:00", ALICE))
GID = DBC.execute("SELECT id FROM groups WHERE name=?", ("Freelance pool",)).fetchone()[0]
for x in (FID, FIO):
    DBC.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-10-20T08:00:00"))
r = Fr.post(B + "/api/team/dm", json={"user_id": FIO})
check(r.ok, "freelancer: a DM with fiona " + r.text[:200])
FDM = j(r).get("id")
FR = j(post(Fr, FDM, "Invoice draft ready")).get("id")
r = post(Fi, FDM, "Looks good, one question", thread_of=FR)
check(r.status_code == 201 and r.json()["thread_of"] == FR, "freelancer: fiona answers in a thread " + r.text[:200])
FT = j(r).get("id")
jj = j(page(Fr, FDM, FR))
check(jj.get("root", {}).get("id") == FR and [m["id"] for m in jj.get("messages", [])] == [FT], "freelancer: frida reads the thread")
check(room_of(Fr, FDM).get("unread") == 1, f"freelancer: the answer counts unread {room_of(Fr, FDM)}")
check(Fr.post(B + f"/api/team/rooms/{FDM}/read", json={"thread": FR}).ok and room_of(Fr, FDM).get("unread") == 0, "freelancer: read")
Fi.post(B + f"/api/team/rooms/{FDM}/read", json={})
check(FIO in (msg(Fr, FDM, FR) or {}).get("read_by", {}).get("users", []), "freelancer: frida sees that fiona read it")
check(page(Bo, FDM, FR).status_code == 404, "freelancer: bob sees nothing of their DM")

print(f"{OKS[0]} ok, {len(FAILS)} failed", flush=True)
if FAILS:
    sys.exit(1)
print("ALL P2139 A API CHECKS PASSED")
