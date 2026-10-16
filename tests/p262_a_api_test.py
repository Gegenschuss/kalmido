#!/usr/bin/env python3
"""2.62.0 API tests, part A (#1530, #1848): sending in the chats and pinned chat messages. Invented names only.
 - #1530 client_id: the app sends one key per message; the same text of the same person in the same conversation with the
   same client_id within seconds returns the stored message (200, no second row, no second agent event); another
   client_id, another text or no client_id = a new message as before (team chat and agent chat, JSON and multipart)
usage: p262_a_api_test.py <datadir>      (a fresh container; P262A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
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


if not os.environ.get("P262A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "otto", "display_name": "Otto"})
OT, OTH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TEAM = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Other", "org_id": ORG}).json()["id"]
for uid in (BOB, CL):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": uid, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{OTHER}/members", json={"user_id": OT, "role": "edit"}).ok
rooms = A.get(B + "/api/team").json()["rooms"]
RID = next(x["id"] for x in rooms if x.get("list_id") == TEAM)
ROTHER = next(x["id"] for x in rooms if x.get("list_id") == OTHER)


def events(cur):
    return requests.get(V + f"/agent/events?since={cur}&limit=200", headers=CLH).json()["data"]


def cursor():
    return requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]


def room_msgs(s, rid):
    return s.get(B + f"/api/team/rooms/{rid}/messages").json()["messages"]


def chat_msgs(s, aid):
    return s.get(B + f"/api/agents/{aid}/chat").json()["messages"]


# ================================================================== #1530 client_id
n0 = len(room_msgs(A, RID))
r1 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Mac back online", "client_id": "c-1"})
r2 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Mac back online", "client_id": "c-1"})
check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"], "#1530 team: the same client_id -> the stored message " + r2.text[:200])
check(len(room_msgs(A, RID)) == n0 + 1, "#1530 team: only one message stored")
r3 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Mac back online", "client_id": "c-2"})
r4 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Mac back online"})
r5 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Something else", "client_id": "c-1"})
check(r3.status_code == 201 and r4.status_code == 201 and r5.status_code == 201 and len({r1.json()["id"], r3.json()["id"], r4.json()["id"], r5.json()["id"]}) == 4,
      "#1530 team: another client_id, no client_id or another text -> new messages")
r6 = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Mac back online", "client_id": "c-1"})
check(r6.status_code == 201 and r6.json()["user_id"] == BOB, "#1530 team: another person with the same key -> own message")
check(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "x", "client_id": 5}).status_code == 201, "#1530 team: a client_id that is no text is ignored")
check(requests.post(V + f"/team/rooms/{RID}/messages", headers=CLH, json={"body": "x", "client_id": "a"}).status_code == 400, "#1530 v1: client_id stays unknown for the REST API")

cur = cursor()
c1 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Are you there?", "client_id": "k-1"})
c2 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Are you there?", "client_id": "k-1"})
c3 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Are you there?", "client_id": "k-1"})
check(c1.status_code == 201 and c2.status_code == 200 and c3.status_code == 200 and c1.json()["id"] == c2.json()["id"] == c3.json()["id"], "#1530 chat: three sends, one message " + c2.text[:200])
ev = [e for e in events(cur) if e["event"] == "chat"]
check(len(ev) == 1, f"#1530 chat: the agent gets one event, not {len(ev)}")
c4 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Are you there?"})
check(c4.status_code == 201 and c4.json()["id"] != c1.json()["id"], "#1530 chat: without client_id a new message as before")
m1 = A.post(B + f"/api/agents/{CL}/chat", data={"body": "A file", "client_id": "f-1"}, files={"file": ("n.txt", b"x", "text/plain")})
m2 = A.post(B + f"/api/agents/{CL}/chat", data={"body": "A file", "client_id": "f-1"}, files={"file": ("n.txt", b"x", "text/plain")})
check(m1.status_code == 201 and m2.status_code == 200 and m1.json()["id"] == m2.json()["id"], "#1530 chat: multipart with client_id once " + m2.text[:200])

print(f"p262_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
