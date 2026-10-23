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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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


# ================================================================== #1848 pins: team chat
tm = [A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": f"Point {i}"}).json()["id"] for i in range(7)]
r = A.post(B + f"/api/team/messages/{tm[0]}/pin", json={"pinned": True})
check(r.ok and r.json()["message"]["pinned_at"] and r.json()["message"]["pinned_by"] == ALICE and [x["id"] for x in r.json()["pins"]] == [tm[0]],
      "#1848 team: alice pins " + r.text[:200])
pg = A.get(B + f"/api/team/rooms/{RID}/messages?limit=1").json()
check([x["id"] for x in pg["pins"]] == [tm[0]] and tm[0] not in [x["id"] for x in pg["messages"]], "#1848 team: the page carries the pin, also when older than the page")
r = A.post(B + f"/api/team/messages/{tm[0]}/pin", json={})
check(r.ok and r.json()["message"]["pinned_at"] is None and r.json()["pins"] == [], "#1848 team: without pinned it toggles (unpinned)")
v0 = Bo.get(B + "/api/version").json().get("t")
r = Bo.post(B + f"/api/team/messages/{tm[1]}/pin", json={"pinned": True})
check(r.ok and r.json()["message"]["pinned_by"] == BOB, "#1848 team: bob (member) pins alice's message")
check(Bo.get(B + "/api/version").json().get("t") != v0, "#1848 team: the change marker t moves (others see it live)")
check(Bo.post(B + f"/api/team/messages/{tm[1]}/pin", json={"pinned": True}).json()["pins"].__len__() == 1, "#1848 team: pinning twice keeps one pin")
check(Ca.post(B + f"/api/team/messages/{tm[2]}/pin", json={"pinned": True}).status_code == 404, "#1848 team: carol (not in the conversation) 404")
check(A.post(B + f"/api/team/messages/{tm[2]}/pin", json={"pinned": "yes"}).status_code == 400, "#1848 team: pinned must be a boolean")
check(A.post(B + "/api/team/messages/99999999/pin", json={"pinned": True}).status_code == 404, "#1848 team: an unknown message 404")
for i in (2, 3, 4, 5):
    check(A.post(B + f"/api/team/messages/{tm[i]}/pin", json={"pinned": True}).ok, f"#1848 team: pin {i}")
r = A.post(B + f"/api/team/messages/{tm[6]}/pin", json={"pinned": True})
check(r.status_code == 409 and "5" in r.text, "#1848 team: the 6th pin 409 " + r.text[:200])
assert A.delete(B + f"/api/team/messages/{tm[5]}").ok
pins = A.get(B + f"/api/team/rooms/{RID}/messages").json()["pins"]
check(tm[5] not in [x["id"] for x in pins] and len(pins) == 4, "#1848 team: a deleted message leaves the bar")
check(A.post(B + f"/api/team/messages/{tm[5]}/pin", json={"pinned": True}).status_code == 409, "#1848 team: a deleted message cannot be pinned")
r = requests.post(V + f"/team/messages/{tm[6]}/pin", headers=CLH, json={"pinned": True})
check(r.ok and r.json()["message"]["pinned_by"] == CL, "#1848 v1 team: an agent of the channel pins " + r.text[:200])
check(requests.post(V + f"/team/messages/{tm[6]}/pin", headers=OTH, json={"pinned": False}).status_code == 404, "#1848 v1 team: another agent 404")
check(requests.post(V + f"/team/messages/{tm[6]}/pin", headers=CLH, json={"pinned": False, "x": 1}).status_code == 400, "#1848 v1 team: unknown fields 400")
j = requests.get(V + f"/team/rooms/{RID}/messages", headers=CLH).json()
check(len(j.get("pins", [])) == 5 and all("pinned_at" in x for x in j["data"]), "#1848 v1 team: the page carries pins + pinned_at")
check(Ca.post(B + f"/api/team/messages/{tm[6]}/pin", json={"pinned": False}).status_code == 404 and
      len(A.get(B + f"/api/team/rooms/{RID}/messages").json()["pins"]) == 5, "#1848 team: a stranger cannot unpin either")
om = Bo.post(B + f"/api/team/rooms/{ROTHER}/messages", json={"body": "x"})
check(om.status_code == 404, "setup: bob is not in the other channel")

# ================================================================== #1848 pins: agent chat
am = [requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": f"Answer {i}"}).json()["id"] for i in range(7)]
cur = cursor()
r = A.post(B + f"/api/agents/{CL}/chat/{am[0]}/pin", json={"pinned": True})
check(r.ok and r.json()["message"]["pinned_by"] == ALICE and [x["id"] for x in r.json()["pins"]] == [am[0]], "#1848 chat: the person pins " + r.text[:200])
ev = [e for e in events(cur) if e["event"] == "chat_pinned"]
check(len(ev) == 1 and ev[0]["data"]["pinned"] is True and ev[0]["data"]["message"]["id"] == am[0] and ev[0]["data"]["user"]["id"] == ALICE,
      "#1848 chat: the agent gets chat_pinned " + str(ev)[:300])
oev = requests.get(V + "/agent/events?since=0&limit=500", headers=OTH).json()["data"]
check(not [e for e in oev if e["event"] == "chat_pinned"], "#1848 chat: another agent gets nothing")
j = A.get(B + f"/api/agents/{CL}/chat?limit=1").json()
check([x["id"] for x in j["pins"]] == [am[0]], "#1848 chat: the conversation carries pins, also older than the page")
cur = cursor()
r = A.post(B + f"/api/agents/{CL}/chat/{am[0]}/pin", json={})
ev = [e for e in events(cur) if e["event"] == "chat_pinned"]
check(r.ok and r.json()["pins"] == [] and len(ev) == 1 and ev[0]["data"]["pinned"] is False, "#1848 chat: toggled off, event pinned false")
cur = cursor()
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{am[1]}/pin", headers=CLH, json={"pinned": True})
check(r.ok and r.json()["message"]["pinned_by"] == CL, "#1848 v1 chat: the agent pins in its own conversation " + r.text[:200])
check(not [e for e in events(cur) if e["event"] == "chat_pinned"], "#1848 v1 chat: the agent's own pin sends no event")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{am[2]}/pin", headers=OTH, json={"pinned": True}).status_code == 404, "#1848 v1 chat: another agent 404")
check(requests.post(V + f"/agent/chats/{BOB}/messages/{am[2]}/pin", headers=CLH, json={"pinned": True}).status_code == 404, "#1848 v1 chat: the message of another person's conversation 404")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{am[2]}/pin", headers=CLH, json={"pinned": True, "x": 1}).status_code == 400, "#1848 v1 chat: unknown fields 400")
check(Bo.post(B + f"/api/agents/{CL}/chat/{am[2]}/pin", json={"pinned": True}).status_code == 404, "#1848 chat: bob cannot pin in alice's chat")
check(Ca.post(B + f"/api/agents/{CL}/chat/{am[2]}/pin", json={"pinned": True}).status_code == 404, "#1848 chat: carol (no chat with the agent) 404")
for i in (2, 3, 4, 5):
    check(A.post(B + f"/api/agents/{CL}/chat/{am[i]}/pin", json={"pinned": True}).ok, f"#1848 chat: pin {i}")
r = A.post(B + f"/api/agents/{CL}/chat/{am[6]}/pin", json={"pinned": True})
check(r.status_code == 409, "#1848 chat: the 6th pin 409 " + r.text[:200])
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{am[6]}/pin", headers=CLH, json={"pinned": True})
check(r.status_code == 409, "#1848 v1 chat: the agent hits the same limit")
nt = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "New session", "kind": "notice"})
check(nt.status_code == 201 and A.post(B + f"/api/agents/{CL}/chat/{nt.json()['id']}/pin", json={"pinned": False}).status_code == 400, "#1848 chat: a notice cannot be pinned")
feed = requests.get(V + f"/agent/chats?since=0&user_id={ALICE}&limit=500", headers=CLH).json()["data"]
check({x["id"] for x in feed if x.get("pinned_at")} == {am[1], am[2], am[3], am[4], am[5]}, "#1848 v1 chat: the feed carries pinned_at")
# 2.82.0 (#1862): one person's feed (?user_id=) also carries `pins` (same list as the app); without user_id there is none
fj = requests.get(V + f"/agent/chats?since=0&user_id={ALICE}&limit=5", headers=CLH).json()
check({x["id"] for x in fj.get("pins", [])} == {am[1], am[2], am[3], am[4], am[5]}, "#1862 v1 chat: pins in the feed of one person")
check("pins" not in requests.get(V + "/agent/chats?since=0&limit=5", headers=CLH).json(), "#1862 v1 chat: no pins without user_id")

print(f"p262_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
