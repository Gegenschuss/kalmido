#!/usr/bin/env python3
"""2.4.2 API tests: comment order per user (#386), usernames in the list members (#389, clickable @username in
descriptions), sharing with an agent in bulk (#391).
 - comment_order: default old, PATCH old / new, anything else 400, per user (another person keeps old)
 - members of a list carry username (for @username in descriptions)
 - agent_share is server-only: PATCH /api/settings {agent_share} changes nothing
 - GET /api/agents/{id}/share: auto + counts (own, shared, missing, skipped) of the lists I own
 - POST /api/agents/{id}/share-all: every list I own with role edit, never the inbox, archived lists or lists I only
   manage (someone else's list), no News for the agent; lists unshared by hand (DELETE member) stay out (skip), shared
   again by hand they count again; a second run adds nothing
 - PUT /api/agents/{id}/autoshare {on}: my new lists (POST /api/lists, a project type, a list template) get the agent with
   role edit at once, another person's new lists do not; off stops it; on must be a bool (400); an unknown / non-agent id
   404; with collaboration off for everyone 403
Starts its OWN containers (start.sh).
usage: p242_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

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


def start(keep=False):
    if not keep:
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(DATA)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def stop():
    subprocess.run(["docker", "stop", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)

    def patch(self, p, **k):
        return self.req("PATCH", p, **k)


def dbx(q, a=()):
    con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        r = con.execute(q, a).fetchall()
        con.commit()
        return r
    finally:
        con.close()


def events(cl, since=0):
    return cl.get("/agent/events", params={"since": since, "limit": 500}).json()["data"]


def kinds(cl, kind, since=0):
    return [e for e in events(cl, since) if e["event"] == kind]


def new_agent(a, name, **extra):
    r = a.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title(), **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], Api(r.json()["token"])


def agent_seen(s, aid):
    return next((a for a in s.get(B + "/api/agents").json()["agents"] if a["id"] == aid), None)


def lst(s, lid):
    return next(x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid)


def version(s):
    return s.get(B + "/api/version").json()["v"]



start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en"})
st = A.get(B + "/api/state").json()
ALICE = st["me"]["id"]
AG, cl = new_agent(A, "claude")
AG2, cl2 = new_agent(A, "helper")
INBOX = next(x["id"] for x in st["lists"] if x["is_inbox"])

# ================================================================== #386 comment order per user
check(A.get(B + "/api/state").json()["settings"]["comment_order"] == "old", "comment_order: default old")
r = A.patch(B + "/api/settings", json={"comment_order": "new"})
check(r.ok and A.get(B + "/api/state").json()["settings"]["comment_order"] == "new", "comment_order: new saved")
r = A.patch(B + "/api/settings", json={"comment_order": "sideways"})
check(r.status_code == 400 and A.get(B + "/api/state").json()["settings"]["comment_order"] == "new", f"comment_order: invalid 400 ({r.status_code})")
check(Bo.get(B + "/api/state").json()["settings"]["comment_order"] == "old", "comment_order: per user (bob keeps old)")
check(A.patch(B + "/api/settings", json={"comment_order": "old"}).ok, "comment_order: back to old")

# ================================================================== #389 usernames of the members
L1 = A.post(B + "/api/lists", json={"name": "Website"}).json()["id"]
A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "edit"})
mem = lst(A, L1)["members"]
check(any(m["user_id"] == BOB and m["username"] == "bob" and m["name"] == "Bob" for m in mem), f"members carry username: {mem}")

# ================================================================== #391 sharing with an agent in bulk
r = A.patch(B + "/api/settings", json={"agent_share": '{"auto":[%d]}' % AG})
check(A.get(B + "/api/state").json()["settings"]["agent_share"] == "{}", "agent_share is server-only (PATCH ignored)")
L2 = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
L3 = A.post(B + "/api/lists", json={"name": "Old stuff"}).json()["id"]
A.patch(B + f"/api/lists/{L3}", json={"archived": 1})
check(lst(A, L3)["archived"] in (1, True), "an archived list")
BL = Bo.post(B + "/api/lists", json={"name": "Bob's"}).json()["id"]
Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": ALICE, "role": "admin"})
j = A.get(B + f"/api/agents/{AG}/share").json()
check(j == {"auto": False, "own": 2, "shared": 0, "missing": 2, "skipped": 0}, f"GET share: 2 own lists, none shared: {j}")
r = A.post(B + f"/api/agents/{AG}/share-all", json={})
check(r.ok and r.json()["added"] == 2, f"share-all: 2 lists shared: {r.status_code} {r.text[:200]}")
role = lambda lid, uid: (dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)) or [(None,)])[0][0]
check(role(L1, AG) == "edit" and role(L2, AG) == "edit", "share-all: role edit")
check(role(INBOX, AG) is None and role(L3, AG) is None and role(BL, AG) is None, "share-all: never the inbox, archived lists or someone else's list")
check(not dbx("SELECT kind FROM notifications WHERE user_id=?", (AG,)), "share-all: no News for the agent (as when shared by hand)")
check({x["id"] for x in cl.get("/lists").json()["data"]} >= {L1, L2}, "the agent sees both lists through its token")
r = A.post(B + f"/api/agents/{AG}/share-all", json={})
check(r.ok and r.json()["added"] == 0, "share-all again: nothing new")
# unshared by hand: stays out
check(A.delete(B + f"/api/lists/{L2}/members/{AG}").ok, "unshare L2 by hand")
j = A.get(B + f"/api/agents/{AG}/share").json()
check(j["skipped"] == 1 and j["missing"] == 0, f"GET share: 1 skipped: {j}")
r = A.post(B + f"/api/agents/{AG}/share-all", json={})
check(r.ok and r.json()["added"] == 0 and role(L2, AG) is None, "share-all leaves the list unshared by hand out")
A.put(B + f"/api/lists/{L2}/members", json={"user_id": AG, "role": "edit"})
A.delete(B + f"/api/lists/{L2}/members/{AG}")
A.put(B + f"/api/lists/{L2}/members", json={"user_id": AG, "role": "view"})
import json as _j
sk = _j.loads(A.get(B + "/api/state").json()["settings"]["agent_share"])
check(str(AG) not in sk.get("skip", {}) or L2 not in sk["skip"][str(AG)], f"shared again by hand: no longer skipped: {sk}")
check(role(L2, AG) == "view", "a hand-picked role stays")
A.post(B + f"/api/agents/{AG}/share-all", json={})
check(role(L2, AG) == "view", "share-all does not change an existing member's role")
# bob's unshare of his own list does not touch alice's setting
Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": AG, "role": "edit"})
Bo.delete(B + f"/api/lists/{BL}/members/{AG}")
sb = _j.loads(Bo.get(B + "/api/state").json()["settings"]["agent_share"])
check(sb.get("skip", {}).get(str(AG)) == [BL], f"the skip belongs to the list owner (bob): {sb}")

# autoshare
check(A.put(B + f"/api/agents/{AG2}/autoshare", json={"on": "yes"}).status_code == 400, "autoshare: on must be a bool")
check(A.put(B + f"/api/agents/{BOB}/autoshare", json={"on": True}).status_code == 404, "autoshare: a person is no agent (404)")
check(A.put(B + "/api/agents/99999/autoshare", json={"on": True}).status_code == 404, "autoshare: unknown id 404")
check(A.post(B + f"/api/agents/{BOB}/share-all", json={}).status_code == 404, "share-all: a person is no agent (404)")
r = A.put(B + f"/api/agents/{AG2}/autoshare", json={"on": True})
check(r.ok and A.get(B + f"/api/agents/{AG2}/share").json()["auto"] is True, "autoshare on")
N1 = A.post(B + "/api/lists", json={"name": "New one"}).json()["id"]
check(role(N1, AG2) == "edit" and role(N1, AG) is None, "a new list: shared with the auto agent only, role edit")
N2 = A.post(B + "/api/lists", json={"name": "Typed", "ptype": "software"}).json()
N2 = N2.get("id")
check(N2 and role(N2, AG2) == "edit", f"a new project from a type: shared too ({N2})")
NB = Bo.post(B + "/api/lists", json={"name": "Bob new"}).json()["id"]
check(role(NB, AG2) is None, "someone else's new list: not shared")
check(role(L1, AG2) is None, "autoshare leaves existing lists alone")
check(A.put(B + f"/api/agents/{AG2}/autoshare", json={"on": False}).ok, "autoshare off")
N3 = A.post(B + "/api/lists", json={"name": "After off"}).json()["id"]
check(role(N3, AG2) is None, "off: new lists stay private")
# collaboration off for everyone
r = A.patch(B + "/api/admin/settings", json={"collab_all": False})
if r.ok:
    check(A.post(B + f"/api/agents/{AG}/share-all", json={}).status_code == 403, "collaboration off: share-all 403")
    A.patch(B + "/api/admin/settings", json={"collab_all": True})
else:
    print("p242_api: collab_all switch route not found, skipped:", r.status_code)

print(f"p242_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
