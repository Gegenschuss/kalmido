#!/usr/bin/env python3
"""2.39.0 API tests (agent C: #1179 a person edits their own messages in the agent chat), own container (start.sh).
 - PATCH /api/agents/{aid}/chat/{mid} {body}: only the sender (the agent's message 403, another person's message 404, an
   agent token never), empty / too long 400, the same text changes nothing; edited_at + edits (earlier versions) for the
   person, the agent sees edited_at and the current text only (v1 chat list and events)
 - not fetched yet: the text is replaced, the queued chat event carries the new text, no message_edited
 - fetched (delivered_at) or answered: message_edited only to this agent (old, new, answered), another agent gets nothing
 - an edited comment: message_edited only to the agent that got it as an event (mention), not to other agents,
   not when the agent no longer sees the task, never from a health list
 - an edited team chat message: message_edited to the agent that got it as team_message
 - the message search finds the new text, not the old one
usage: p2390_c_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
# 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = sess("bob")
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
AG = {}
for n in ("claude", "otto"):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": n, "display_name": n.title()})
    assert r.ok, r.text
    AG[n] = (r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]})
CL, CLH = AG["claude"]
OT, OTH = AG["otto"]
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for uid in (CL, BOB):  # one agent per list: otto works in a list of its own (another agent of the same person)
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid, "role": "edit"}).ok, f"setup: member {uid}")
WO = A.post(B + "/api/lists", json={"name": "Otto's list", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{WO}/members", json={"user_id": OT, "role": "edit"}).ok, "setup: otto in its own list")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})  # Bob may address the agents too
T = A.post(B + "/api/tasks", json={"title": "Write the offer", "list_id": W}).json()["id"]


def latest(h):
    return requests.get(V + "/agent/events?since=latest", headers=h).json()["cursor"]


def events(h, since, kind=None):
    d = requests.get(V + f"/agent/events?since={since}&limit=200", headers=h).json()["data"]
    return [e for e in d if kind is None or e["event"] == kind]


def say(body, s=None):
    r = (s or A).post(B + f"/api/agents/{CL}/chat", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


def edit(mid, body, s=None, aid=None):
    return (s or A).patch(B + f"/api/agents/{aid or CL}/chat/{mid}", json={"body": body})


def chat(s=None):
    return {m["id"]: m for m in (s or A).get(B + f"/api/agents/{CL}/chat").json()["messages"]}


# ================================================================== not fetched yet: the text is replaced, no event
c0, o0 = latest(CLH), latest(OTH)
m1 = say("Please plan the week with three tasks")
check(m1.get("edited_at") is None and m1.get("edits") == [], "a new message: edited_at null, no edits " + str((m1.get("edited_at"), m1.get("edits"))))
r = edit(m1["id"], "Please plan the week with five tasks")
check(r.ok and r.json()["body"] == "Please plan the week with five tasks" and r.json()["edited_at"], "the sender edits " + r.text[:160])
check([x["body"] for x in r.json().get("edits", [])] == ["Please plan the week with three tasks"] and r.json()["edits"][0]["at"] == m1["created_at"],
      "edits: the earlier version with its time " + str(r.json().get("edits")))
ev = events(CLH, c0)
check([e["event"] for e in ev] == ["chat"], "not fetched: only the chat event, no message_edited " + str([e["event"] for e in ev]))
check(ev and ev[0]["data"]["message"]["body"] == "Please plan the week with five tasks", "the queued chat event carries the new text " + str(ev and ev[0]["data"]["message"].get("body")))
check(events(OTH, o0) == [], "the other agent gets nothing")

# ================================================================== fetched: message_edited to this agent only
check(chat()[m1["id"]]["delivered_at"], "the poll delivered the message")
c1, o1 = latest(CLH), latest(OTH)
r = edit(m1["id"], "Please plan the week with four tasks")
check(r.ok and len(r.json()["edits"]) == 2, "a second edit keeps both earlier versions " + r.text[:160])
ev = events(CLH, c1)
check([e["event"] for e in ev] == ["message_edited"], "fetched: message_edited " + str([e["event"] for e in ev]))
d = ev[0]["data"] if ev else {}
check(d.get("kind") == "chat" and d.get("old") == "Please plan the week with five tasks" and d.get("new") == "Please plan the week with four tasks"
      and d.get("answered") is False and d.get("message", {}).get("id") == m1["id"] and d.get("message", {}).get("edited_at")
      and d.get("user", {}).get("id") == ALICE, "message_edited: kind, old, new, answered false, message, user " + str(d))
check("edits" not in d.get("message", {}), "the event names no earlier versions")
check(events(OTH, o1) == [], "the other agent gets no message_edited")

# ================================================================== answered (not delivered): message_edited, answered true
m2 = say("And the budget?")
dbx("UPDATE agent_chat SET delivered_at=NULL WHERE id=?", (m2["id"],), write=True)
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "The budget is 1000."})
check(r.status_code == 201, "the agent answers " + r.text[:100])
c2 = latest(CLH)
r = edit(m2["id"], "And the budget for May?")
ev = events(CLH, c2, "message_edited")
check(r.ok and len(ev) == 1 and ev[0]["data"]["answered"] is True, "answered: message_edited with answered true " + str([e["data"] for e in ev]))

# ================================================================== same text, limits, rights
c3 = latest(CLH)
r = edit(m2["id"], "  And the budget for May?  ")
check(r.ok and len(r.json()["edits"]) == 1, "the same text: no new version " + r.text[:120])
check(events(CLH, c3) == [], "the same text: no event")
check(edit(m2["id"], "   ").status_code == 400, "an empty text: 400")
check(edit(m2["id"], "x" * 8001).status_code == 400, "a too long text: 400")
ag_msg = next(m for m in chat().values() if m["from"] == "agent")
check(edit(ag_msg["id"], "changed by alice").status_code == 403, "the agent's message: 403")
check(edit(m2["id"], "bob was here", s=Bo).status_code == 404, "another person's message: 404")
check(edit(m2["id"], "otto", aid=OT).status_code == 404, "the message under another agent's address: 404")
r = requests.patch(B + f"/api/agents/{CL}/chat/{m2['id']}", headers={**H, **CLH}, json={"body": "agent"})
check(r.status_code in (401, 403, 404), "an agent token never edits a person's message " + str(r.status_code))
check(chat()[m2["id"]]["body"] == "And the budget for May?", "the text stayed")

# ================================================================== what each side sees
mine = chat()[m1["id"]]
check(mine["edited_at"] and [x["body"] for x in mine["edits"]] == ["Please plan the week with three tasks", "Please plan the week with five tasks"],
      "the person's chat: edited_at + edits, oldest first " + str(mine.get("edits")))
check("edits" in mine and "edits" not in chat()[ag_msg["id"]], "edits only on the person's own messages")
r = requests.get(V + f"/agent/chats?user_id={ALICE}", headers=CLH).json()["data"]
vm = next(x for x in r if x["id"] == m1["id"])
check(vm["edited_at"] and vm["body"] == "Please plan the week with four tasks" and "edits" not in vm, "the agent's chat list: edited_at + current text, no edits " + str(vm))
spec = requests.get(V + "/openapi.json", headers=CLH).json()
check("message_edited" in spec["components"]["schemas"]["AgentEvent"]["properties"]["event"]["enum"], "OpenAPI: message_edited in the event list")
check("edited_at" in spec["components"]["schemas"]["ChatMessage"]["properties"], "OpenAPI: ChatMessage.edited_at")
check("message_edited" in requests.get(V + "/agent", headers=CLH).json()["events"], "GET /agent lists message_edited")

# ================================================================== search
h = A.get(B + "/api/search/messages", params={"q": "four", "art": "a"}).json().get("hits", [])
check(any(x["id"] == m1["id"] for x in h), "the search finds the new text")
h = A.get(B + "/api/search/messages", params={"q": "three", "art": "a"}).json().get("hits", [])
check(not any(x["id"] == m1["id"] for x in h), "the old text is no hit any more")

# ================================================================== comments
c4, o4 = latest(CLH), latest(OTH)
r = A.post(B + f"/api/tasks/{T}/comments", json={"body": f"<@{CL}> please check the prices"})
check(r.status_code in (200, 201), "a comment mentions claude " + r.text[:100])
K = r.json()["id"]
check([e["event"] for e in events(CLH, c4)] == ["mention"], "claude: mention")
check(events(OTH, o4) == [], "otto: nothing (not mentioned, not following)")
c5, o5 = latest(CLH), latest(OTH)
r = A.patch(B + f"/api/comments/{K}", json={"body": f"<@{CL}> please check the prices and the dates"})
check(r.ok, "the author edits the comment " + r.text[:100])
ev = events(CLH, c5)
check([e["event"] for e in ev] == ["message_edited"], "claude: message_edited for the comment " + str([e["event"] for e in ev]))
d = ev[0]["data"] if ev else {}
check(d.get("kind") == "comment" and d.get("comment", {}).get("id") == K and d.get("comment", {}).get("edited_at")
      and "and the dates" in d.get("new", "") and "and the dates" not in d.get("old", "") and d.get("task", {}).get("id") == T
      and d.get("list_id") == W and d.get("user", {}).get("id") == ALICE, "comment event: kind, comment, old, new, task, list_id, user " + str(d))
check(events(OTH, o5) == [], "otto gets no message_edited for a comment it never got")
# the agent no longer sees the task: nothing
W2 = A.post(B + "/api/lists", json={"name": "Private", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/tasks/{T}", json={"list_id": W2}).ok, "setup: the task moves to a list without agents")
c6 = latest(CLH)
A.patch(B + f"/api/comments/{K}", json={"body": f"<@{CL}> now only the dates"})
check(events(CLH, c6, "message_edited") == [], "the task out of sight: no message_edited")
A.patch(B + f"/api/tasks/{T}", json={"list_id": W})
# a health list: never
HL = A.post(B + "/api/lists", json={"name": "Doctor", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{HL}/members", json={"user_id": CL, "role": "edit"})
TH = A.post(B + "/api/tasks", json={"title": "Receipt", "list_id": HL}).json()["id"]
c7 = latest(CLH)
KH = A.post(B + f"/api/tasks/{TH}/comments", json={"body": f"<@{CL}> file this"}).json()["id"]
check([e["event"] for e in events(CLH, c7)] == ["mention"], "setup: a mention in the later health list")
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,), write=True)
c8 = latest(CLH)
A.patch(B + f"/api/comments/{KH}", json={"body": f"<@{CL}> file this today"})
check(events(CLH, c8) == [], "a health list: never a message_edited")

# ================================================================== team chat
t = A.get(B + "/api/team").json()
room = next((x for x in t.get("rooms", []) if x["kind"] == "list" and x["list_id"] == W), None)
check(room is not None, "setup: the list's channel")
if room:
    c9, o9 = latest(CLH), latest(OTH)
    r = A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": f"<@{CL}> draft the offer"})
    check(r.status_code in (200, 201), "a team message mentions claude " + r.text[:100])
    TM = r.json().get("id")
    check([e["event"] for e in events(CLH, c9)] == ["team_message"], "claude: team_message")
    c10 = latest(CLH)
    r = A.patch(B + f"/api/team/messages/{TM}", json={"body": f"<@{CL}> draft the offer by Friday"})
    ev = events(CLH, c10)
    check(r.ok and [e["event"] for e in ev] == ["message_edited"] and ev[0]["data"]["kind"] == "team"
          and "by Friday" in ev[0]["data"]["new"] and ev[0]["data"]["room"]["list_id"] == W, "team: message_edited " + str([e.get("data") for e in ev]))
    check(events(OTH, o9) == [], "otto: nothing from the team chat")

print(f"p2390_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
