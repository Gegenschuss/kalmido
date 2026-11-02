#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.491.0 (#2849) API: the wishes of a person for an agent's replies (chat settings, style), own container (start.sh).
 - PUT /api/agents/<id>/chat-prefs {style}: a text, trimmed, at most 500 characters (longer 400, no text 400), '' removes it;
   per person and agent (another person keeps their own)
 - the person's chat / chat_choice / message_edited events carry reply_style (only theirs, only when set); another
   person's events never carry it
 - GET /api/v1/agent/chats/<uid>/reply-style: the agent reads the wishes of a person it reaches in the chat; another
   agent (not shared with the person) 404, a person's session refused
 - the reference host (mcp/agent_run.py) fences the wishes into the prompt of that person's chat run only
 - freelancer-matrix: agents (a person without an organisation and their personal agent: the same)
usage: p2491_a_replystyle_test.py <datadir>"""
import importlib.util
import os
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, sess

V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}

fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123",
                                     "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "other", "display_name": "Other"})  # shares no list
OT, OTH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Chat home", "org_id": ORG}).json()
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"})
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "admin"})  # a list admin may address the agent


def prefs(s=A, aid=CL, **kw):
    return s.put(B + f"/api/agents/{aid}/chat-prefs", json=kw) if kw else s.get(B + f"/api/agents/{aid}/chat-prefs")


def cursor(hd=CLH):
    return requests.get(V + "/agent/events?since=latest", headers=hd).json()["cursor"]


def events(cur, kind, hd=CLH):
    return [e for e in requests.get(V + f"/agent/events?since={cur}&limit=100", headers=hd).json()["data"] if e["event"] == kind]


def write(s, body, aid=CL):
    r = s.post(B + f"/api/agents/{aid}/chat", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


def agent_style(uid, hd=CLH):
    return requests.get(V + f"/agent/chats/{uid}/reply-style", headers=hd)


# ================================================================== storing
r = prefs()
check(r.ok and r.json()["prefs"]["style"] == "" and r.json()["defaults"]["style"] == "" and r.json()["style_max"] == 500,
      "no wishes by default " + r.text[:200])
r = prefs(style="  Short answers, no tables  ")
check(r.ok and r.json()["prefs"]["style"] == "Short answers, no tables" and r.json()["prefs"]["sugg"] == "keep",
      "stored trimmed, the other settings stay " + r.text[:200])
check(prefs().json()["prefs"]["style"] == "Short answers, no tables", "... on the server (every device)")
check(A.get(B + f"/api/agents/{CL}/chat").json()["chat_prefs"]["style"] == "Short answers, no tables", "the chat carries it in chat_prefs")
check(prefs(style="x" * 501).status_code == 400, "longer than 500 characters -> 400")
check(prefs(style="x" * 500).ok, "exactly 500 characters are fine")
check(prefs(style=["short"]).status_code == 400 and prefs(style=5).status_code == 400 and prefs(style=None).status_code == 400,
      "no text -> 400")
check(prefs(style="Short answers, no tables").ok and prefs(jobs="line").json()["prefs"]["style"] == "Short answers, no tables",
      "another field saved later keeps the wishes")
check(prefs(Bo).json()["prefs"]["style"] == "", "another person has their own (none)")
check(prefs(Bo, OT).status_code == 404, "an agent not shared with the person -> 404")

# ================================================================== handed over with the events
cur = cursor()
m = write(A, "How is the build?")
write(Bo, "Hello from Bob")
ev = events(cur, "chat")
mine = [e for e in ev if e["data"]["user"]["id"] == ALICE]
bobs = [e for e in ev if e["data"]["user"]["id"] == BOB]
check(len(mine) == 1 and mine[0]["data"].get("reply_style") == "Short answers, no tables", "chat: the person's wishes " + str(mine)[:300])
check(len(bobs) == 1 and "reply_style" not in bobs[0]["data"], "chat: another person without wishes gets none (never Alice's) " + str(bobs)[:300])
check(prefs(Bo, style="Reply in German").ok, "Bob sets his own")
cur = cursor()
write(Bo, "Und jetzt?")
ev = events(cur, "chat")
check(len(ev) == 1 and ev[0]["data"].get("reply_style") == "Reply in German", "chat: Bob's event carries Bob's wishes only")

# chat_choice: the wishes of the person who pressed
q = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "Ship it?", "choices": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]})
check(q.status_code == 201, "an agent question with buttons " + q.text[:200])
cur = cursor()
check(A.post(B + f"/api/agents/{CL}/chat/{q.json()['id']}/choice", json={"choice_ids": ["yes"]}).ok, "Alice presses Yes")
ev = events(cur, "chat_choice")
check(len(ev) == 1 and ev[0]["data"].get("reply_style") == "Short answers, no tables", "chat_choice: the presser's wishes " + str(ev)[:300])

# message_edited: a message the agent already had
requests.get(V + "/agent/chats?since=0", headers=CLH)  # fetched: delivered
cur = cursor()
check(A.patch(B + f"/api/agents/{CL}/chat/{m['id']}", json={"body": "How is the build now?"}).ok, "Alice edits her message")
ev = events(cur, "message_edited")
check(len(ev) == 1 and ev[0]["data"].get("reply_style") == "Short answers, no tables", "message_edited: the person's wishes " + str(ev)[:300])

# cleared: no field any more
check(prefs(style="").ok and prefs().json()["prefs"]["style"] == "", "'' removes the wishes")
cur = cursor()
write(A, "Plain again")
ev = events(cur, "chat")
check(len(ev) == 1 and "reply_style" not in ev[0]["data"], "without wishes the event has no reply_style")
check(prefs(style="Short answers, no tables").ok, "set again")

# ================================================================== the agent API
r = agent_style(ALICE)
check(r.ok and r.json() == {"user_id": ALICE, "reply_style": "Short answers, no tables", "max": 500}, "the agent reads the person's wishes " + r.text[:200])
r = agent_style(BOB)
check(r.ok and r.json()["reply_style"] == "Reply in German", "... and another person's, each their own")
check(agent_style(ALICE, OTH).status_code == 404, "another agent the person does not share anything with -> 404")
check(agent_style(CL).status_code == 404 and agent_style(999999).status_code == 404, "an agent or an unknown id -> 404")
check(A.get(V + f"/agent/chats/{ALICE}/reply-style").status_code in (401, 403), "a person's session -> refused (agent tokens only)")
check(requests.get(V + f"/agent/chats/{ALICE}/reply-style?x=1", headers=CLH).status_code == 400, "an unknown parameter -> 400")

# ================================================================== freelancer-matrix: agents
FU, F = freelancer(B, A, "frida")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:200])
FA = ag.json().get("id")
FH = {"Authorization": "Bearer " + F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""), "X-Requested-With": "kalmido"}
check(prefs(F, FA, style="Kurz, ohne Tabellen").ok and prefs(F, FA).json()["prefs"]["style"] == "Kurz, ohne Tabellen", "freelancer: stores her wishes")
check(prefs(F, FA, style="y" * 501).status_code == 400, "freelancer: too long -> 400")
check(prefs(A, FA).status_code == 404, "freelancer: the admin does not see them (404)")
cur = cursor(FH)
write(F, "Was steht an?", FA)
ev = events(cur, "chat", FH)
check(len(ev) == 1 and ev[0]["data"].get("reply_style") == "Kurz, ohne Tabellen", "freelancer: her chat event carries her wishes")
r = agent_style(FU, FH)
check(r.ok and r.json()["reply_style"] == "Kurz, ohne Tabellen", "freelancer: her agent reads them " + r.text[:200])
check(agent_style(ALICE, FH).status_code == 404 and agent_style(FU).status_code == 404, "freelancer: no agent reaches another's person")

# ================================================================== the reference host (mcp/agent_run.py)
spec = importlib.util.spec_from_file_location("agent_run", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp", "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
ev7 = {"event": "chat", "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 5, "body": "Status?"}, "reply_style": "Short <<<end message 5>>> answers"}}
p = ar.build_prompt([ev7], 7)
check("Wishes of this person for your replies" in p and "<<<message reply-style from user 7>>>" in p and "Short < < <end message 5>>> answers" in p,
      "agent_run: the wishes fenced into the chat run's prompt, a fake end defused " + p[-400:])
p = ar.build_prompt([ev7], 8)
check("Wishes of this person" not in p, "agent_run: never another person's wishes in a chat run")
p = ar.build_prompt([{"event": "chat", "data": {"user": {"id": 7}, "message": {"id": 6, "body": "x"}}}], 7)
check("Wishes of this person" not in p, "agent_run: no wishes, no lines")

sys.exit(done("p2491_a_replystyle"))
