#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1130.0 (#6057) API tests, own container: GET /api/msgpop, what the in-app pop-up for new chat messages asks for
(kalmido/agents/msgpop.py, static/js/msgpop.js).
 - the first ask (no t / a) only says where the window starts: nothing that was there before is new
 - team chat: a message of another person in a project's conversation shows (sender, first line, room name), one's own
   never; read = gone; a muted room only with an @mention; a direct message (no room name); a deleted message never
 - agent chat: a plain answer and a question show; a notice line, a job's progress line ("say") never; a job's result does;
   asking marks nothing read (unlike GET /api/agents/<id>/chat)
 - only people: an agent's token gets 403
 - the boundary: a person without an organisation never sees the messages of the organisation's people; her own agent's
   answer shows for her the same way
freelancer-matrix: own
usage: p21130_a_msgpop_api_test.py <datadir>"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P21130A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob Builder", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Shoot Berlin", "org_id": ORG}).json()
A.put(B + f"/api/lists/{L['id']}/members", json={"user_id": BOB, "role": "edit"})
ROOM = next(x for x in A.get(B + "/api/team").json()["rooms"] if x.get("list_id") == L["id"])["id"]
Bo.get(B + "/api/team")


def pop(s=A, t=None, a=None):
    q = "" if t is None else f"?t={t}&a={a}"
    r = s.get(B + "/api/msgpop" + q)
    check(r.status_code == 200, f"GET /api/msgpop{q} answers 200 ({r.status_code} {r.text[:200]})")
    return r.json() if r.ok else {"t": t or 0, "a": a or 0, "items": []}


def say(s, rid, body):
    r = s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": body})
    assert r.ok, r.text
    return r.json()


# ---- the first ask: where the window starts, nothing old
say(Bo, ROOM, "An old message before the window started")
j = pop()
check(j.get("items") == [] and isinstance(j.get("t"), int) and j["t"] > 0 and isinstance(j.get("a"), int),
      f"first ask: only the start, the old message is not new {j}")
T, AA = j["t"], j["a"]

# ---- team chat: Bob writes, Alice sees it; Bob does not see his own
m1 = say(Bo, ROOM, "The van is booked\nsecond line stays out")
j = pop(A, T, AA)
it = [x for x in j["items"] if x["src"] == "team"]
check(len(it) == 1 and it[0]["id"] == m1["id"] and it[0]["name"] == "Bob Builder" and it[0]["from"] == BOB,
      f"Bob's new message for Alice, with his name {it}")
check(it and it[0]["text"] == "The van is booked" and it[0]["room"] == "Shoot Berlin" and it[0]["room_id"] == ROOM and it[0]["kind"] == "list",
      f"the first line and the project's conversation {it}")
check(j["t"] >= m1["id"], f"t moves to the newest message ({j['t']} >= {m1['id']})")
check(pop(A, j["t"], j["a"])["items"] == [], "asked again with the new t: nothing new")
check(all(x["from"] != BOB for x in pop(Bo, 0, 0)["items"]), "Bob's own messages never show for Bob")

# ---- read = gone
check(A.post(B + f"/api/team/rooms/{ROOM}/read", json={}).ok, "Alice reads the room")
check([x for x in pop(A, T, AA)["items"] if x["src"] == "team"] == [], "read messages do not pop up any more")

# ---- a muted room: only an @mention
check(A.post(B + f"/api/team/rooms/{ROOM}/read", json={"muted": True}).ok, "Alice mutes the room")
say(Bo, ROOM, "Just chatting in the muted room")
m3 = say(Bo, ROOM, f"<@{ALICE}> please check the call sheet")
it = [x for x in pop(A, T, AA)["items"] if x["src"] == "team"]
check([x["id"] for x in it] == [m3["id"]] and it[0]["mention"], f"muted room: only the @mention {it}")
check("<@" not in (it[0]["text"] if it else "<@"), f"the mention as a name, not the token: {it[0]['text'] if it else ''}")
A.post(B + f"/api/team/rooms/{ROOM}/read", json={"muted": False})
A.post(B + f"/api/team/rooms/{ROOM}/read", json={})

# ---- a direct message, a deleted one never
DM = Bo.post(B + "/api/team/dm", json={"user_id": ALICE}).json()["id"]
m4 = say(Bo, DM, "Coffee at ten?")
m5 = say(Bo, DM, "Typo, ignore")
check(Bo.delete(B + f"/api/team/messages/{m5['id']}").status_code in (200, 204), "Bob deletes a message")
it = [x for x in pop(A, T, AA)["items"] if x["src"] == "team"]
check([x["id"] for x in it] == [m4["id"]] and it[0]["kind"] == "dm" and it[0]["room"] == "", f"the direct message shows, without a room name; the deleted one never {it}")

# ---- agent chat
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def agent_say(body, **kw):
    r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": body, **kw})
    assert r.status_code == 201, r.text
    return r.json()


j0 = pop(A, T, AA)
a1 = agent_say("The rough cut is uploaded.")
a2 = agent_say("Shall I send it to the client?")
JOB = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "Colour grading", "user_id": ALICE, "state": "running"}).json()["id"]
a3 = agent_say("Working on scene 4 now", job_id=JOB, job_msg="say")
a4 = agent_say("✅ Grading finished", job_id=JOB, job_msg="result")
a5 = agent_say("Quiet note line")
dbx("UPDATE agent_chat SET kind='notice' WHERE id=?", (a5["id"],))
it = {x["id"]: x for x in pop(A, j0["t"], j0["a"])["items"] if x["src"] == "agent"}
check(a1["id"] in it and it[a1["id"]]["name"] == "Claude" and it[a1["id"]]["agent_id"] == CL and it[a1["id"]]["text"] == "The rough cut is uploaded.",
      f"a plain answer of the agent shows {list(it.values())}")
check(a2["id"] in it and it[a2["id"]]["asks"], "a question shows (asks)")
check(a4["id"] in it, "a job's result shows")
check(a3["id"] not in it and a5["id"] not in it, "a job's progress line and a notice line never")
unread = dbx("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND read_at IS NULL", (CL, ALICE))[0][0]
check(unread >= 3, f"asking marks nothing read ({unread} unread)")
A.get(B + f"/api/agents/{CL}/chat")
check([x for x in pop(A, j0["t"], j0["a"])["items"] if x["src"] == "agent"] == [], "the chat opened (read): nothing of it pops up")

# ---- only people
r = requests.get(B + "/api/msgpop", headers=CLH)
check(r.status_code == 403, f"an agent's token: 403 ({r.status_code})")

# ---- a person without an organisation: never the organisation's messages; her own agent's answer the same way
FID, F = freelancer(B, A)
jf = pop(F)
say(Bo, ROOM, "Organisation only")
say(Bo, DM, "Only for Alice")
check(all(x["src"] != "team" for x in pop(F, 0, 0)["items"]), "freelancer: no message of the organisation's people")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "comments"]})
check(ag.status_code in (200, 201), f"freelancer: an own agent ({ag.status_code} {ag.text[:200]})")
FT = {"Authorization": "Bearer " + F.post(B + f"/api/my/agents/{ag.json()['id']}/token").json().get("token", "")}
r = requests.post(V + f"/agent/chats/{FID}", headers=FT, json={"body": "Invoice draft is ready."})
check(r.status_code == 201, f"freelancer: her agent answers ({r.status_code} {r.text[:200]})")
it = [x for x in pop(F, jf["t"], jf["a"])["items"] if x["src"] == "agent"]
check(len(it) == 1 and it[0]["text"] == "Invoice draft is ready." and it[0]["name"] == "Frida's bot", f"freelancer: her agent's answer pops up {it}")
check(all(x.get("agent_id") != ag.json()["id"] for x in pop(A, 0, 0)["items"]), "Alice never sees the freelancer's agent chat")

sys.exit(done("p21130_a_msgpop_api"))
