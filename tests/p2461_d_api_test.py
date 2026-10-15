#!/usr/bin/env python3
"""2.46.1 API tests (part D), own container (start.sh).

 - #1639: a list shared only with an agent has a channel; an agent that listens in gets every channel message of a person as
   team_message (mentioned false, listening true), an agent that does not listen in gets nothing without an @mention, an
   agent's own message triggers nothing (no loop), a health list never; the agent may write in the channel of a list shared
   with it and not in the channel of a list it does not see
usage: p2461_d_api_test.py <datadir>"""
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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


if os.environ.get("P2461_D_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
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


def latest(h):
    return requests.get(V + "/agent/events?since=latest", headers=h).json()["cursor"]


def events(h, since, kind=None):
    d = requests.get(V + f"/agent/events?since={since}&limit=200", headers=h).json()["data"]
    return [e for e in d if kind is None or e["event"] == kind]


def room_of(s, lid):
    return next((x for x in s.get(B + "/api/team").json().get("rooms", []) if x["kind"] == "list" and x["list_id"] == lid), None)


# ================================================================== #1639 list channel for agents that listen in
# a software list shared with nobody but the agent claude: claude listens in (the default of software lists)
SW = A.post(B + "/api/lists", json={"name": "Build", "org_id": ORG, "ptype": "software"}).json()["id"]
check(A.put(B + f"/api/lists/{SW}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the software list")
st = next(l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == SW)
check(st.get("listen_agent_ids") == [CL], "setup: claude listens in " + str(st.get("listen_agent_ids")))
room = room_of(A, SW)
check(room is not None, "a list shared only with an agent has a channel")
# a plain list shared with otto, who does not listen in (not a software list)
PL = A.post(B + "/api/lists", json={"name": "Plain", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": OT, "role": "edit"}).ok, "setup: otto in the plain list")
proom = room_of(A, PL)
check(proom is not None, "setup: the plain list's channel")
if room and proom:
    c1, o1 = latest(CLH), latest(OTH)
    r = A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "What is still open here?"})
    check(r.status_code == 201, "alice writes in the channel " + r.text[:100])
    ev = events(CLH, c1)
    check([e["event"] for e in ev] == ["team_message"], "claude listens in: team_message without an @mention " + str(ev)[:200])
    if ev:
        d = ev[0]["data"]
        check(d.get("mentioned") is False and d.get("listening") is True and d["room"]["id"] == room["id"]
              and d["room"]["list_id"] == SW and d["message"]["text"] == "What is still open here?" and d["user"]["id"] == ALICE,
              "team_message: mentioned false, listening true, room, text, user " + str(d)[:300])
    check(events(OTH, o1) == [], "otto (not in the list): nothing")
    # the agent answers in the channel: allowed, and it triggers nothing (no loop)
    c2 = latest(CLH)
    r = requests.post(V + f"/team/rooms/{room['id']}/messages", headers=CLH, json={"body": "Two tasks are open.", "reply_to": r.json()["id"]})
    check(r.status_code == 201, "claude answers in the channel of a list shared only with it " + r.text[:100])
    check(events(CLH, c2) == [], "the agent's own answer: no event (no loop)")
    msgs = A.get(B + f"/api/team/rooms/{room['id']}/messages").json()["messages"]
    check([m["user_id"] for m in msgs] == [ALICE, CL], "alice sees the agent's answer in the channel")
    # otto does not listen in on the plain list: nothing without an @mention, the @mention still comes
    o3 = latest(OTH)
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Any news?"})
    check(events(OTH, o3) == [], "otto does not listen in: no team_message without an @mention")
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": f"<@{OT}> any news?"})
    ev = events(OTH, o3)
    check([e["event"] for e in ev] == ["team_message"] and ev[0]["data"].get("mentioned") is True
          and ev[0]["data"].get("listening") is False, "otto @mentioned: team_message, mentioned true " + str(ev)[:200])
    # an agent cannot read or write the channel of a list it does not see
    r = requests.post(V + f"/team/rooms/{proom['id']}/messages", headers=CLH, json={"body": "hello"})
    check(r.status_code == 404, "claude: no post in the channel of a list not shared with it " + str(r.status_code))
    r = requests.get(V + f"/team/rooms/{proom['id']}/messages", headers=CLH)
    check(r.status_code == 404, "claude: the channel of a list not shared with it does not exist " + str(r.status_code))
    rooms = requests.get(V + "/team/rooms", headers=CLH).json()["data"]
    check([x.get("list_id") for x in rooms] == [SW], "claude sees only the channel of its own list " + str(rooms)[:200])
    # otto listens in on the plain list: a member's message reaches it (the list lets members use the agent)
    check(A.patch(B + f"/api/lists/{PL}", json={"listen_agent_ids": [OT]}).ok, "setup: otto listens in on the plain list")
    check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the plain list")
    A.patch(B + f"/api/lists/{PL}", json={"agent_members": True})
    o4 = latest(OTH)
    r = Bo.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Who takes the second one?"})
    check(r.status_code == 201, "bob writes in the channel " + r.text[:120])
    ev = events(OTH, o4)
    check([e["event"] for e in ev] == ["team_message"] and ev[0]["data"]["user"]["id"] == BOB,
          "a member's message reaches the listening agent " + str(ev)[:200])
    # the agent's own message in a channel where it listens in: nothing (no loop)
    o5 = latest(OTH)
    check(requests.post(V + f"/team/rooms/{proom['id']}/messages", headers=OTH, json={"body": "I take it."}).status_code == 201,
          "otto writes in the channel")
    check(events(OTH, o5) == [], "otto's own message: no event")
    # a health list: never
    dbx("UPDATE lists SET life='health' WHERE id=?", (PL,), write=True)
    o6 = latest(OTH)
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Appointment on Monday"})
    check(events(OTH, o6) == [], "a health list: no team_message")
    dbx("UPDATE lists SET life='' WHERE id=?", (PL,), write=True)
    # listening switched off: only @mentions again
    check(A.patch(B + f"/api/lists/{SW}", json={"listen_agent_ids": []}).ok, "setup: claude stops listening in")
    c6 = latest(CLH)
    A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "Anything else?"})
    check(events(CLH, c6) == [], "listening off: no team_message without an @mention")

print(f"p2461_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
