#!/usr/bin/env python3
# kalmido-suite: fresh
# freelancer-matrix: agents
"""2.1039.0 (#5804 #5805): what an agent asks the person in its chat stands in the bell's "For you" and counts
(kalmido/agents/chatnews.py). Run as a person WITHOUT an organisation (tests/freelancer_fixture.py) with her own agent.
 - #5804 an approval card of the agent chat: one News entry kind approval (to_me, unread, the bell's number +1); answered
   = out of the number; a permission question that expires = out; a card the agent takes back = out
 - #5804 a job without a task that waits: an entry too (before: only the push); its card in the chat does not count a
   second time; answering the card takes the job's entry along
 - #5805 a question: a job message of kind question, a message with answer buttons -> ONE row for the agent, each question
   counted; a plain message, a result, buttons that are only links -> nothing; opening the agent's chat = read
usage: p21039_a_chat_bell_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import B, check, done, fresh, setup, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
fresh()
A = setup("alice", "Alice")
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok
FID, Fr = freelancer(B, A)
ag = Fr.post(B + "/api/my/agents", json={"username": "helper", "display_name": "Helper", "scopes": ["read", "tasks:write", "comments"]}).json()
assert "id" in ag, ag
AG, AH = ag["id"], {"Authorization": "Bearer " + ag["token"]}
L = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
Fr.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"})


def say(**b):
    r = requests.post(V + f"/agent/chats/{FID}", headers=AH, json=b)
    assert r.status_code == 201, (r.status_code, r.text[:300])
    return r.json()


def bell():
    return Fr.get(B + "/api/state").json()["news"]["unread_me"]


def feed(kind):
    return [x for x in Fr.get(B + "/api/news").json()["items"] if x["kind"] == kind]


def unread(kind):
    return [x for x in feed(kind) if not x["read"]]


n0 = bell()
# ---- #5804 an approval card
m1 = say(approval={"title": "Deploy version 1.2"})
it = unread("approval")
check(len(it) == 1 and it[0]["to_me"] and it[0]["data"].get("chat") == m1["id"] and it[0]["data"].get("title") == "Deploy version 1.2",
      f"#5804 the card is an entry for you: {feed('approval')}")
check(bell() == n0 + 1, f"#5804 the bell counts it: {bell()} (was {n0})")
check(Fr.get(B + f"/api/agents/{AG}/chat").ok and len(unread("approval")) == 1, "#5804 opening the chat does not decide it: it stays")
r = Fr.post(B + f"/api/agents/{AG}/chat/{m1['id']}/choice", json={"choice_ids": ["yes"]})
check(r.ok, f"answer {r.status_code} {r.text[:200]}")
check(not unread("approval") and bell() == n0, f"#5804 decided = out of the number: {bell()} {feed('approval')}")

# a card the agent takes back, a permission question that expires
m2 = say(approval={"title": "Delete the branch"})
check(bell() == n0 + 1, "#5804 a second card counts")
r = requests.post(V + f"/agent/chats/{FID}/messages/{m2['id']}/withdraw", headers=AH, json={})
check(r.ok and bell() == n0, f"#5804 taken back = out: {r.status_code} {bell()}")
m3 = say(body="May I run the migration?", permission=True, expires_in=10)
check(bell() == n0 + 1, f"#5804 a permission question counts: {bell()}")
check(until(lambda: bell() == n0, timeout=25, step=1), f"#5804 expired = out: {bell()} {feed('approval')}")

# ---- #5804 a job without a task waits: an entry, its card does not count twice, the card's answer takes it along
j = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Release 3", "user_id": FID, "state": "waiting"})
check(j.status_code == 201, f"job {j.status_code} {j.text[:200]}")
JID = j.json()["id"]
check(bell() == n0 + 1 and any(x["data"].get("job") == JID for x in unread("approval")), f"#5804 the waiting job without a task counts: {feed('approval')}")
m4 = say(approval={"title": "Release 3 live?"}, job_id=JID)
check(bell() == n0 + 1, f"#5804 its card in the chat does not count a second time: {bell()} {unread('approval')}")
check(Fr.post(B + f"/api/agents/{AG}/chat/{m4['id']}/choice", json={"choice_ids": ["no"]}).ok, "answer the job's card")
check(bell() == n0, f"#5804 answering the card takes the job's entry along: {bell()} {unread('approval')}")

# ---- #5805 questions
say(body="All builds are green.")
say(body="Done: 12 files.", job_id=JID, job_msg="result")
say(body="Open it here", choices=[{"id": "o", "label": "Open", "href": "#office/offers/1"}])
check(bell() == n0 and not unread("agentask"), f"#5805 plain message, result, link buttons: nothing {bell()} {feed('agentask')}")
say(body="Which branch should I take?", job_id=JID, job_msg="question")
say(body="Short or long?", choices=["Short", "Long"])
it = unread("agentask")
check(len(it) == 1 and it[0]["count"] == 2 and it[0]["to_me"] and it[0]["actor_id"] == AG and it[0]["data"].get("text") == "Short or long?",
      f"#5805 one row for the agent, the newest question on top: {feed('agentask')}")
check(bell() == n0 + 2, f"#5805 each question counts: {bell()} (was {n0})")
check(Fr.get(B + f"/api/agents/{AG}/chat").ok, "open the chat")
check(not unread("agentask") and bell() == n0, f"#5805 the chat opened = read: {bell()} {feed('agentask')}")

# ---- a member of an organisation the same way (an agent of the organisation)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "orgbot", "display_name": "Orgbot"})
OB, OBH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
AL = A.post(B + "/api/lists", json={"name": "Office"}).json()["id"]
A.put(B + f"/api/lists/{AL}/members", json={"user_id": OB, "role": "edit"})
ALICE = A.get(B + "/api/me").json()["id"]
a0 = A.get(B + "/api/state").json()["news"]["unread_me"]
r = requests.post(V + f"/agent/chats/{ALICE}", headers=OBH, json={"approval": {"title": "Send the invoices"}})
check(r.status_code == 201 and A.get(B + "/api/state").json()["news"]["unread_me"] == a0 + 1, f"#5804 alice too: {r.status_code} {r.text[:200]}")
sys.exit(done("p21039_a_chat_bell"))
