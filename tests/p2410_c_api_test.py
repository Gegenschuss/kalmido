#!/usr/bin/env python3
"""2.41.0 API tests of agent C, own container (start.sh):
 - #1420 one Share dialog for folders: several agents per folder (GET/PUT/DELETE /api/folders/agents); the first agent is the
   folder's default (mirrored into folder_props.props.agent_id, the lists follow it; a list keeps one agent), further agents
   wait for lists that choose them; "listens in" per agent; removing one with remove takes it out of the lists; an older
   client that writes props.agent_id still works; the start-up takes a props-only agent over (additive, every start); a
   renamed folder keeps its agents; a health list never gets an agent or a public link; the public links of the folder's
   lists together (PUT /api/folders/public-links); handing every list of the folder to someone (POST /api/folders/owner)
 - #1423 "Agent follows up" as a folder default; share a folder by e-mail address (the answer never says whether it exists)
 - #1428 /api/state folder_shares: people / groups / agents of my shared folders
usage: p2410_c_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def agent_of(lid):
    r = dbx("SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND u.kind='agent'", (lid,))
    return [x[0] for x in r]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
CL = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()["id"]
CO = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "cody", "display_name": "Cody"}).json()["id"]
F = "Proj"
L1 = A.post(B + "/api/lists", json={"name": "Alpha", "folder": F}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Beta", "folder": F}).json()["id"]
L3 = A.post(B + "/api/lists", json={"name": "Body", "folder": F}).json()["id"]
r = A.patch(B + f"/api/lists/{L3}", json={"life": "health"})
check(r.ok, f"health list: {r.status_code} {r.text[:200]}")

# ---- #1420 folder agents
r = A.put(B + "/api/folders/agents", json={"folder": F, "agent_id": CL})
check(r.ok, f"add the first folder agent: {r.status_code} {r.text[:300]}")
j = r.json()
check([a["agent_id"] for a in j["agents"]] == [CL] and j["agents"][0]["first"], f"one agent, the first: {j['agents']}")
check(agent_of(L1) == [CL] and agent_of(L2) == [CL], f"the lists follow the first agent: {agent_of(L1)} {agent_of(L2)}")
check(agent_of(L3) == [], "a health list never gets the folder's agent")
check(A.get(B + "/api/folders/props", params={"folder": F}).json()["props"].get("agent_id") == CL, "mirrored into props.agent_id (2.40 reads it)")
r = A.put(B + "/api/folders/agents", json={"folder": F, "agent_id": CO})
check(r.ok and [a["agent_id"] for a in r.json()["agents"]] == [CL, CO], f"a second agent: {r.text[:300]}")
check(agent_of(L1) == [CL], "a further agent does not replace the lists' agent (one agent per list)")
r = A.put(B + "/api/folders/agents", json={"folder": F, "agent_id": CO, "first": True})
check(r.ok and r.json()["agents"][0]["agent_id"] == CO, f"Cody becomes the default: {r.text[:300]}")
check(agent_of(L1) == [CO] and agent_of(L2) == [CO], f"the lists follow the new default: {agent_of(L1)}")
check(A.get(B + "/api/folders/props", params={"folder": F}).json()["props"].get("agent_id") == CO, "props.agent_id = the new first agent")
r = A.put(B + "/api/folders/agents", json={"folder": F, "agent_id": CO, "listen": False})
check(r.ok, f"listen per agent: {r.text[:200]}")
check(all(x[0] == "-*" for x in dbx("SELECT agent_listen FROM lists WHERE id IN (?,?)", (L1, L2))), "listen off reaches the lists of that agent")
check([a["listen"] for a in r.json()["agents"]] == [False, None], f"listen stored per agent: {r.json()['agents']}")
r = A.put(B + "/api/folders/agents", json={"folder": F, "agent_id": 99999})
check(r.status_code == 400, f"an unknown agent: 400 ({r.status_code})")
Bo = sess("bob")
r = Bo.put(B + "/api/folders/agents", json={"folder": F, "agent_id": CL})
check(r.status_code == 400, f"another person's agent is no valid choice: {r.status_code}")
r = Bo.get(B + "/api/folders/agents", params={"folder": F})
check(r.ok and r.json()["agents"] == [], "Bob sees only his own folder's agents (none)")
r = A.delete(B + "/api/folders/agents", json={"folder": F, "agent_id": CO, "remove": True})
check(r.ok and r.json()["removed"] == 2, f"remove Cody from the folder and its lists: {r.text[:300]}")
check(agent_of(L1) == [] and agent_of(L2) == [], "the lists lost Cody")
check(A.get(B + "/api/folders/props", params={"folder": F}).json()["props"].get("agent_id") == CL, "Claude is the default again")
# an older client writes the one agent into the folder settings
r = A.put(B + "/api/folders/props", json={"folder": F, "props": {"agent_id": CO}, "apply": "new"})
check(r.ok, f"old client props.agent_id: {r.text[:200]}")
j = A.get(B + "/api/folders/agents", params={"folder": F}).json()
check([a["agent_id"] for a in j["agents"]] == [CO, CL], f"the old client's agent is the folder's first agent: {j['agents']}")
# the start-up takes over a default agent that only sits in folder_props (as 2.40 writes it), additive
dbx("DELETE FROM folder_agents", write=True)
dbx("UPDATE folder_props SET props=? WHERE owner_id=(SELECT id FROM users WHERE username='alice') AND folder=?",
    (json.dumps({"agent_id": CL, "agent_listen": True}), F), write=True)
env = dict(os.environ, KEEP="1")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
A = sess("alice")
j = A.get(B + "/api/folders/agents", params={"folder": F}).json()
check([(a["agent_id"], a["listen"]) for a in j["agents"]] == [(CL, True)], f"start-up: the folder_props agent is taken over: {j['agents']}")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
A = sess("alice")
check(len(dbx("SELECT 1 FROM folder_agents")) == 1, "a second start adds nothing (idempotent)")
check(json.loads(dbx("SELECT props FROM folder_props WHERE folder=?", (F,))[0][0]).get("agent_id") == CL, "the old field stays")
# rename: the agents go along
r = A.post(B + "/api/folders/rename", json={"old": F, "new": "Work"})
check(r.ok and [a["agent_id"] for a in A.get(B + "/api/folders/agents", params={"folder": "Work"}).json()["agents"]] == [CL], "a renamed folder keeps its agents")
F = "Work"

# ---- #1423 "Agent follows up" as a folder default
r = A.put(B + "/api/folders/props", json={"folder": F, "props": {"agent_followup": True}, "apply": "all"})
check(r.ok and r.json()["props"].get("agent_followup") is True, f"agent_followup folder default: {r.text[:200]}")
check(all(x[0] == 1 for x in dbx("SELECT agent_followup FROM lists WHERE id IN (?,?)", (L1, L2))), "the lists follow agent_followup")
r = A.patch(B + f"/api/lists/{L1}", json={"agent_followup": False})
check(r.ok and "agent_followup" in json.loads(dbx("SELECT folder_own FROM lists WHERE id=?", (L1,))[0][0] or "[]"), "a list switching it itself differs from the folder")
# share by e-mail address
r = A.put(B + "/api/folders/people", json={"folder": F, "email": "nobody@example.com", "role": "edit"})
check(r.ok and r.json().get("by_email") and r.json()["shared"] == 0, f"an unknown address: the same answer ({r.text[:200]})")
r = A.put(B + "/api/folders/people", json={"folder": F, "email": "BOB@example.com", "role": "edit"})
check(r.ok and r.json().get("by_email") and r.json()["shared"] == 0, f"a known address: the same answer ({r.text[:200]})")
ppl = A.get(B + "/api/folders/people", params={"folder": F}).json()["people"]
check([(p["user_id"], p["name"]) for p in ppl] == [(BOB, "Bob")], f"shared with Bob by address, with his name: {ppl}")

# ---- #1428 folder_shares in the state
fs = A.get(B + "/api/state").json().get("folder_shares", {})
check(fs.get(F) == {"people": 1, "groups": 0, "agents": ["Claude"]}, f"folder_shares: {fs}")
check(Bo.get(B + "/api/state").json().get("folder_shares") == {}, "Bob has no shared folders of his own")

# ---- #1420 public links of the folder's lists
r = A.put(B + "/api/folders/public-links", json={"folder": F, "on": True})
check(r.ok and r.json()["created"] == 2, f"public links for the folder: {r.text[:300]}")
links = {x["id"]: x for x in r.json()["lists"]}
check(links[L1]["link"] and links[L1]["link"]["mode"] == "view" and links[L3]["link"] is None and links[L3]["health"], "read-only links; never for a health list")
check(requests.get(links[L1]["link"]["url"].replace("https://kalmido.example", B)).status_code == 200 if links[L1]["link"] else False, "the link opens")
r = A.put(B + "/api/folders/public-links", json={"folder": F, "on": False})
check(r.ok and r.json()["removed"] == 2 and not any(x["link"] for x in r.json()["lists"]), "all links off together")
check(Bo.put(B + "/api/folders/public-links", json={"folder": F, "on": True}).json().get("created") == 0, "Bob's folder of the same name: none of Alice's lists")

# ---- #1420 hand every list of the folder over
r = Bo.post(B + "/api/folders/owner", json={"folder": F, "user_id": BOB})
check(r.status_code == 404, f"not to oneself: {r.status_code}")
r = A.post(B + "/api/folders/owner", json={"folder": F, "user_id": CL})
check(r.status_code in (400, 404), f"an agent cannot own lists: {r.status_code}")
r = A.post(B + "/api/folders/owner", json={"folder": F, "user_id": BOB})
check(r.ok and r.json()["moved"] == 3, f"all three lists to Bob: {r.text[:300]}")
check(all(x[0] == BOB for x in dbx("SELECT owner_id FROM lists WHERE id IN (?,?,?)", (L1, L2, L3))), "Bob owns them")
check(dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=(SELECT id FROM users WHERE username='alice')", (L1,))[0][0] == "admin", "Alice stays as list admin")

print(f"p2410_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
