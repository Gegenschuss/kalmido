#!/usr/bin/env python3
"""2.62.0 part B API tests (#1854 comments by agents in the bell: all / only replies to me).
 - the setting agent_comments: "all" by default, "replies" switches, anything else 400; a person without an organisation
   (freelancer) has it the same way
 - with "replies" an agent's comment reaches me (News) only when it answers my comment (reply_to), follows right after my
   comment on that task, or mentions me; an unrelated agent comment stays quiet
 - comments by people always reach me as before; "all" brings every agent comment as before; a list bell "All" does not outrank it (leader decision), the task's "Urgent" does
 - 2.66.1 (#1943): the bell (unread_me) counts the agent's comments that reach me (replies / mentions; with "all" every
   comment), a bundle counts when any unread item in it is for me; an agent's completion / assignment has no number
usage: p262_b_api_test.py <datadir>"""
import os
import dbx as dbxm
import subprocess
import sys

import requests

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


def news_for(uid, cid):
    """The News items uid got about comment cid."""
    return dbx("SELECT kind FROM notifications WHERE user_id=? AND comment_id=?", (uid, cid))


def state(s):
    return s.get(B + "/api/state").json()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "fred", "display_name": "Fred", "password": "password123", "email": "fred@example.com"})
assert r.ok, r.text
Bo, Fr = sess("bob"), sess("fred")
ME = state(A)["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()
check(A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "edit"}).ok, "share Work with bob")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"}).ok, "share Work with the agent")


def agent_says(tid, body, reply_to=None):
    r = requests.post(V + f"/tasks/{tid}/comments", headers=CLH, json={"body": body, **({"reply_to": reply_to} if reply_to else {})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def says(s, tid, body):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": body})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== the setting
check(state(A)["settings"].get("agent_comments") == "all", "#1854: agent_comments is 'all' by default")
check(A.patch(B + "/api/settings", json={"agent_comments": "sometimes"}).status_code == 400, "#1854: an unknown value is refused")
check(Fr.patch(B + "/api/settings", json={"agent_comments": "replies"}).ok and state(Fr)["settings"]["agent_comments"] == "replies",
      "#1854: a person without an organisation has the setting too")

# ================================================================== "all": as before
T = A.post(B + "/api/tasks", json={"title": "Report", "list_id": W["id"]}).json()["id"]
says(Bo, T, "a first note")
c = agent_says(T, "unrelated agent note")
check(news_for(ALICE, c), "#1854: with 'all' an unrelated agent comment on my task reaches me")

# ================================================================== "replies"
check(A.patch(B + "/api/settings", json={"agent_comments": "replies"}).ok, "#1854: switch to 'only replies to me'")
says(Bo, T, "bob again")
c = agent_says(T, "another unrelated agent note")
check(not news_for(ALICE, c), "#1854: with 'replies' an unrelated agent comment stays quiet " + str(news_for(ALICE, c)))
mine = says(A, T, "my question")
c = agent_says(T, "right after yours")
n = news_for(ALICE, c)
check(n and n[0][0] == "comment", "#1854: an agent comment right after mine reaches me " + str(n))
says(Bo, T, "bob in between")
c = agent_says(T, "an answer to your question", reply_to=mine)
check(news_for(ALICE, c), "#1854: an agent comment with reply_to on my comment reaches me")
says(Bo, T, "bob once more")
c = agent_says(T, f"<@{ALICE}> please check")
n = news_for(ALICE, c)
check(n and n[0][0] == "mention", "#1854: an agent's mention always reaches me " + str(n))
c = says(Bo, T, "a person without any relation")
check(news_for(ALICE, c), "#1854: a person's comment reaches me as before")
# a deleted comment of mine right before does not count
mine2 = says(A, T, "soon gone")
check(A.delete(B + f"/api/comments/{mine2}").ok, "delete my comment")
c = agent_says(T, "after a deleted comment")
check(not news_for(ALICE, c), "#1854: my deleted comment right before does not make it a reply")
# 2.62.0 (#1854): "only replies" holds against the list bell "All" too
check(A.put(B + f"/api/lists/{W['id']}/bell", json={"mode": "all"}).ok, "bell: all")
says(Bo, T, "bob")
c = agent_says(T, "unrelated, but the bell says all")
check(not news_for(ALICE, c), "#1854: 'only replies' holds against a list bell 'All'")
A.put(B + f"/api/lists/{W['id']}/bell", json={"mode": "default"})
# 2.62.0 (#1854, review): an agent's approval card waits for the person - it arrives with "only replies" too
says(Bo, T, "bob again")
r = requests.post(V + f"/tasks/{T}/comments", headers=CLH, json={"body": "May I merge?", "approval": {"title": "Merge the branch"}})
check(r.status_code == 201, "agent: approval card " + r.text[:200])
check(news_for(ALICE, r.json()["id"]), "#1854: an approval card of an agent reaches 'only replies' too")
# bob kept "all": he hears the unrelated agent comments on a task he follows
c = agent_says(T, "for the followers")
check(news_for(BOB, c), "#1854: someone with 'all' still gets the agent's comment")
check(not news_for(ALICE, c), "#1854: ... and alice with 'replies' does not")

# ================================================================== 2.66.1 (#1943): the bell counts an agent's comments that reach me


def unread_me(s):
    return s.get(B + "/api/news").json()["unread_me"]


def all_read(s):
    check(s.post(B + "/api/news/read", json={"all": True}).ok and unread_me(s) == 0, "#1943: all read")


all_read(A)  # alice still has "replies"
T2 = A.post(B + "/api/tasks", json={"title": "Bell check", "list_id": W["id"]}).json()["id"]
says(Bo, T2, "bob starts")
mine = says(A, T2, "my question to the agent")
says(Bo, T2, "bob in between")  # right after mine: a person's reply, read before the agent answers
all_read(A)
agent_says(T2, "the answer to your question", reply_to=mine)
check(unread_me(A) == 1, "#1943: an agent's reply to my comment counts at the bell " + str(unread_me(A)))
all_read(A)
says(Bo, T2, "bob once more")
c = agent_says(T2, "an unrelated agent note")
check(not news_for(ALICE, c) and unread_me(A) == 0, "#1943: with 'replies' an unrelated agent comment: no item, no number")
c = agent_says(T2, f"<@{ALICE}> a mention")
check(unread_me(A) == 1, "#1943: an agent's mention counts at the bell")
all_read(A)
# a bundle (comments one after the other on a task) counts when ANY of its unread items is for me, not only the newest
T3 = A.post(B + "/api/tasks", json={"title": "Bundle check", "list_id": W["id"]}).json()["id"]
mine = says(A, T3, "my note")
agent_says(T3, "reply to you", reply_to=mine)
says(Bo, T3, "bob after the agent (plain)")
it = next(x for x in A.get(B + "/api/news").json()["items"] if x.get("task_id") == T3)
check(it["count"] == 2 and it["to_me"] and unread_me(A) == 1, "#1943: the bundle with the agent's reply is 'For you' " + str(it))
all_read(A)
# other agent actions stay Activity: completing, assigning
check(A.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"}).ok, "News about completions on")
T4 = A.post(B + "/api/tasks", json={"title": "Agent completes", "list_id": W["id"]}).json()["id"]
check(requests.patch(V + f"/tasks/{T4}", headers=CLH, json={"assignee_id": ALICE}).ok, "agent assigns the task to alice")
check(requests.post(V + f"/tasks/{T4}/complete", headers=CLH).ok, "agent completes the task")
nj = A.get(B + "/api/news").json()
kinds = sorted(x["kind"] for x in nj["items"] if x.get("task_id") == T4 and not x["read"])
check("complete" in kinds and nj["unread_me"] == 0, "#1943: an agent's completion / assignment has no number " + str(kinds) + " " + str(nj["unread_me"]))
all_read(A)
# 2.66.1 (#1943): an agent's approval card reaches "only replies" (it waits for me) - so it counts at the bell too
says(Bo, T2, "bob before the card")
r = requests.post(V + f"/tasks/{T2}/comments", headers=CLH, json={"body": "May I ship?", "approval": {"title": "Ship it"}})
check(r.status_code == 201 and unread_me(A) == 1, "#1943: an agent's approval card counts at the bell with 'replies' " + str(unread_me(A)))
all_read(A)
# "all": every agent comment that reaches me counts
check(A.patch(B + "/api/settings", json={"agent_comments": "all"}).ok, "back to 'all'")
says(Bo, T2, "bob")
c = agent_says(T2, "a plain agent note")
check(news_for(ALICE, c) and unread_me(A) == 1, "#1943: with 'all' a plain agent comment counts at the bell")

print(f"p262_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
