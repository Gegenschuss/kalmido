#!/usr/bin/env python3
"""2.1.2 API tests.
#349 transfer the ownership of a list:
 - the owner hands a list to a member: owner_id, the old owner becomes a list admin with the list where it was in their
   sidebar (folder / place / view), the new owner's member row goes and its folder / place / view move to the list,
   other members keep their roles; to a non-member: at the end of their sidebar, top level
 - the list keeps working for everyone (the new owner, the old owner as admin, a member, a participant, the agent)
 - history (list_activity, GET /api/lists/{id}/owner) "from X to Y", News kind owner for the new owner (not for the actor)
 - refused: an agent as the new owner, a disabled / unknown user, the owner themselves, the inbox (409), a member who is
   not the owner (403), someone who does not see the list (404)
 - admins take over lists of an AGENT or a DISABLED user (for themselves or another person); the old owner stays: an
   agent as edit (never a list admin), a person as admin; GET /api/admin/lists/orphaned (admins only); a non-admin
   cannot take over; an admin cannot take over a list of an active person
 - /api/v1/lists/{id}/owner: works for the owner and admins, agent tokens always 403, documented in the OpenAPI spec
#346 agents: username (validated, unique, the token keeps working) and picture (preset / none / own photo) set by admins;
   non-admins 403; the admin user list contains the agents (kind agent)
Starts its OWN container (start.sh).
usage: p212_api_test.py <datadir>"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests
from PIL import Image

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


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)


def db():
    return sqlite3.connect(os.path.join(DATA, "tasks.db"))


def members(lid):
    con = db()
    try:
        return {r[0]: {"role": r[1], "folder": r[2], "sort": r[3], "view": r[4]} for r in con.execute(
            "SELECT user_id, role, folder, sort, view FROM list_members WHERE list_id=?", (lid,))}
    finally:
        con.close()


def lrow(lid):
    con = db()
    try:
        r = con.execute("SELECT owner_id, folder, sort, view FROM lists WHERE id=?", (lid,)).fetchone()
        return {"owner": r[0], "folder": r[1], "sort": r[2], "view": r[3]}
    finally:
        con.close()


def state_list(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def xfer(s, lid, uid):
    return s.post(B + f"/api/lists/{lid}/owner", json={"user_id": uid})


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for x in (A, Bo, Ca, Da, Er):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AG, AGTOK = r.json()["id"], r.json()["token"]
cl = Api(AGTOK)

# ================================================================== owner -> member
L1 = A.post(B + "/api/lists", json={"name": "Team", "folder": "Work", "view": "list"}).json()["id"]
for who, role in (("bob", "edit"), ("carol", "participant")):
    assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": ids[who], "role": role}).ok
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": AG, "role": "edit"}).ok
assert Bo.patch(B + f"/api/lists/{L1}", json={"folder": "Bobs folder", "view": "kanban"}).ok
bob_before = members(L1)[ids["bob"]]
alice_before = lrow(L1)
TC = A.post(B + "/api/tasks", json={"title": "Carols task", "list_id": L1, "assignee_id": ids["carol"]}).json()["id"]
TX = A.post(B + "/api/tasks", json={"title": "Somebody else's", "list_id": L1}).json()["id"]

g = A.get(B + f"/api/lists/{L1}/owner").json()
check(g["mode"] == "owner" and g["owner"]["id"] == 1 and not g["owner"]["agent"], f"GET owner: mode owner ({g})")
cids = [c["id"] for c in g["candidates"]]
check(AG not in cids and 1 not in cids and ids["bob"] in cids and ids["dave"] in cids, "candidates: people only, not the owner, not agents")
check(g["candidates"][0]["role"] is not None, "candidates: members first")
check(Bo.get(B + f"/api/lists/{L1}/owner").json()["mode"] is None, "a member: no transfer mode")
check(Da.get(B + f"/api/lists/{L1}/owner").status_code == 404, "someone outside: 404")

check(xfer(A, L1, AG).status_code == 400, "an agent cannot become the owner")
check(xfer(A, L1, 1).status_code == 400, "the owner themselves: 400")
check(xfer(A, L1, 9999).status_code == 404, "unknown user: 404")
check(xfer(Bo, L1, ids["bob"]).status_code == 403, "a member cannot transfer (403)")
check(xfer(Da, L1, ids["dave"]).status_code == 404, "someone outside the list: 404")
inbox = next(x for x in A.get(B + "/api/state").json()["lists"] if x["is_inbox"])["id"]
check(xfer(A, inbox, ids["bob"]).status_code == 409, "the inbox is never transferred (409)")

r = xfer(A, L1, ids["bob"])
check(r.ok and r.json()["owner_id"] == ids["bob"] and r.json()["previous_owner_id"] == 1, f"alice -> bob ({r.status_code} {r.text[:120]})")
lr, ms = lrow(L1), members(L1)
check(lr["owner"] == ids["bob"], "owner_id = bob")
check(ids["bob"] not in ms, "the new owner has no member row")
check(ms.get(1, {}).get("role") == "admin", f"the old owner is a list admin ({ms.get(1)})")
check(ms[1]["folder"] == alice_before["folder"] == "Work" and ms[1]["sort"] == alice_before["sort"] and ms[1]["view"] == "list",
      "the old owner keeps folder / place / view")
check(lr["folder"] == bob_before["folder"] == "Bobs folder" and lr["sort"] == bob_before["sort"] and lr["view"] == "kanban",
      f"the new owner keeps their folder / place / view ({lr} vs {bob_before})")
check(ms[ids["carol"]]["role"] == "participant" and ms[AG]["role"] == "edit", "the other members keep their roles")
check(state_list(Bo, L1)["role"] == "owner" and state_list(A, L1)["role"] == "admin", "state: bob owner, alice admin")
check(state_list(Bo, L1)["folder"] == "Bobs folder" and state_list(A, L1)["folder"] == "Bobs folder", "state: folders (2.27.0, #988: the owner's place for everyone)")
check(state_list(A, L1)["owner_name"] == "Bob", "owner_name Bob")
# the list still works for everyone
check(Bo.post(B + "/api/tasks", json={"title": "By the new owner", "list_id": L1}).ok, "the new owner adds a task")
check(A.post(B + "/api/tasks", json={"title": "By the old owner", "list_id": L1}).ok, "the old owner (admin) adds a task")
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": ids["erin"], "role": "view"}).ok, "the old owner manages members")
check(A.patch(B + f"/api/lists/{L1}", json={"name": "Renamed"}).status_code == 403, "the old owner cannot rename it any more")
check(Bo.patch(B + f"/api/lists/{L1}", json={"name": "Team 2"}).ok, "the new owner renames it")
ctasks = {t["id"] for t in Ca.get(B + "/api/state").json()["tasks"] if t["list_id"] == L1}
check(TC in ctasks and TX not in ctasks, "the participant still sees only her task")
check(cl.req("GET", f"/lists/{L1}").ok and cl.req("POST", "/tasks", json={"title": "Agent task", "list_id": L1}).status_code == 201,
      "the agent still reads and writes the list")
check(xfer(A, L1, ids["dave"]).status_code == 403, "the old owner cannot transfer any more")
# history + News
h = Ca.get(B + f"/api/lists/{L1}/owner").json()["history"]
check(len(h) == 1 and h[0]["from"] == "Alice" and h[0]["to"] == "Bob" and h[0]["by"] == "Alice", f"history from Alice to Bob ({h})")
con = db()
la = con.execute("SELECT user_id, kind, data FROM list_activity WHERE list_id=?", (L1,)).fetchall()
con.close()
check(len(la) == 1 and la[0][0] == 1 and la[0][1] == "owner" and json.loads(la[0][2])["to"] == ids["bob"], "list_activity row")
bn = [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "owner"]
check(len(bn) == 1 and bn[0]["list_id"] == L1 and bn[0]["actor_id"] == 1, f"News for the new owner ({bn})")
check(not [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "owner"], "no News for the actor")

# back to alice: her folder / place come back from her member row
r = xfer(Bo, L1, 1)
lr, ms = lrow(L1), members(L1)
check(r.ok and lr["owner"] == 1 and lr["folder"] == "Work" and 1 not in ms and ms[ids["bob"]]["role"] == "admin"
      and ms[ids["bob"]]["folder"] == "Bobs folder", f"bob -> alice again ({lr}, {ms.get(ids['bob'])})")

# to someone who was not in the list: the end of their sidebar, top level
L2 = A.post(B + "/api/lists", json={"name": "Handover", "folder": "Old"}).json()["id"]
D1 = Da.post(B + "/api/lists", json={"name": "Daves", "folder": "Dfold"}).json()["id"]
dmax = max(x["sort"] for x in Da.get(B + "/api/state").json()["lists"])
r = xfer(A, L2, ids["dave"])
lr = lrow(L2)
check(r.ok and lr["owner"] == ids["dave"] and lr["folder"] == "" and lr["sort"] > dmax, f"non-member: top level at the end ({lr}, max {dmax})")
check(members(L2)[1]["role"] == "admin" and members(L2)[1]["folder"] == "Old", "alice stays as admin in her folder")

# ================================================================== admin takeover (agent / disabled owner)
AL = cl.req("POST", "/lists", json={"name": "Dev list"}).json()["id"]
cl.req("POST", "/tasks", json={"title": "Agent's own task", "list_id": AL})
check(cl.req("POST", f"/lists/{AL}/owner", json={"user_id": 1}).status_code == 403, "agent token: 403 (own list)")
check(requests.put(B + f"/api/lists/{AL}/members", json={"user_id": 1, "role": "edit"}, headers={"Authorization": "Bearer " + AGTOK}).status_code in (401, 403),
      "an agent cannot share (why the takeover is needed)")
o = A.get(B + "/api/admin/lists/orphaned").json()
row = next((x for x in o["lists"] if x["id"] == AL), None)
check(row and row["reason"] == "agent" and row["owner_id"] == AG and row["tasks"] == 1, f"orphaned: the agent's list ({o['lists']})")
check(all(c["id"] != AG for c in o["candidates"]), "orphaned candidates: no agents")
check(L1 not in [x["id"] for x in o["lists"]], "orphaned: not the lists of active people")
check(Bo.get(B + "/api/admin/lists/orphaned").status_code == 403, "orphaned: admins only")
g = A.get(B + f"/api/lists/{AL}/owner").json()
check(g["mode"] == "takeover" and g["owner"]["agent"], "admin sees takeover mode without being a member")
check(Bo.get(B + f"/api/lists/{AL}/owner").status_code == 404 and xfer(Bo, AL, ids["bob"]).status_code == 404, "a non-admin cannot take over (404)")
check(xfer(A, L2, 1).status_code == 403, "an admin cannot take over a list of an active person (403)")
r = xfer(A, AL, 1)
ms = members(AL)
check(r.ok and lrow(AL)["owner"] == 1 and ms.get(AG, {}).get("role") == "edit" and 1 not in ms, f"admin takes the agent's list ({ms})")
check(cl.req("GET", f"/lists/{AL}").json().get("role") == "edit", "the agent is a member (edit, never admin)")
check(A.put(B + f"/api/lists/{AL}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "now it can be shared")
# a second agent list, handed straight to bob
AL2 = cl.req("POST", "/lists", json={"name": "Dev list 2"}).json()["id"]
r = xfer(A, AL2, ids["bob"])
ms = members(AL2)
check(r.ok and lrow(AL2)["owner"] == ids["bob"] and ms[AG]["role"] == "edit" and 1 not in ms, "admin hands the agent's list to bob")
check(state_list(Bo, AL2)["role"] == "owner" and state_list(A, AL2) is None, "bob owns it, alice is not in it")
check([x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "owner" and x["list_id"] == AL2], "News for bob")
# a disabled user's list
E1 = Er.post(B + "/api/lists", json={"name": "Erins"}).json()["id"]
assert Er.put(B + f"/api/lists/{E1}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
check(xfer(A, E1, 1).status_code == 404, "active person's list, admin not in it: 404")
assert A.patch(B + f"/api/users/{ids['erin']}", json={"disabled": True}).ok
check(any(x["id"] == E1 and x["reason"] == "disabled" for x in A.get(B + "/api/admin/lists/orphaned").json()["lists"]), "orphaned: disabled owner")
check(xfer(A, E1, ids["erin"]).status_code == 404, "never to a disabled user")
r = xfer(A, E1, ids["bob"])
ms = members(E1)
check(r.ok and lrow(E1)["owner"] == ids["bob"] and ms[ids["erin"]]["role"] == "admin" and ids["bob"] not in ms, f"disabled erin -> bob ({ms})")

# ================================================================== the token API
atok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
btok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
rtok = A.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read"]}).json()["token"]
L3 = A.post(B + "/api/lists", json={"name": "Via API"}).json()["id"]
check(Api(rtok).req("POST", f"/lists/{L3}/owner", json={"user_id": ids["bob"]}).status_code == 403, "read-only token: 403")
check(Api(atok).req("POST", f"/lists/{L3}/owner", json={"user_id": ids["bob"], "x": 1}).status_code == 400, "unknown field: 400")
check(Api(atok).req("POST", f"/lists/{L3}/owner", json={"user_id": AG}).status_code == 400, "v1: agent as owner 400")
r = Api(atok).req("POST", f"/lists/{L3}/owner", json={"user_id": ids["bob"]})
check(r.ok and r.json()["owner_id"] == ids["bob"], f"v1: owner transfers ({r.status_code} {r.text[:120]})")
AL3 = cl.req("POST", "/lists", json={"name": "Dev list 3"}).json()["id"]
check(Api(btok).req("POST", f"/lists/{AL3}/owner", json={"user_id": ids["bob"]}).status_code == 404, "v1: non-admin cannot take over")
check(cl.req("POST", f"/lists/{AL3}/owner", json={"user_id": 1}).status_code == 403, "v1: agent token 403")
r = Api(atok).req("POST", f"/lists/{AL3}/owner", json={"user_id": 1})
check(r.ok and lrow(AL3)["owner"] == 1, "v1: admin takes over")
spec = requests.get(V + "/openapi.json").json()
check("post" in spec["paths"].get("/lists/{id}/owner", {}), "OpenAPI documents /lists/{id}/owner")

# ================================================================== #346 agents: name, username, picture
check(Bo.patch(B + f"/api/admin/agents/{AG}", json={"username": "x"}).status_code == 403, "non-admin: 403")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"username": "Bad Name"}).status_code == 400, "invalid username: 400")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"username": "bob"}).status_code == 409, "taken username: 409")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"username": "Claude-Dev", "display_name": "Claude Dev", "avatar_preset": "robot"})
check(r.ok and r.json()["username"] == "claude-dev" and r.json()["name"] == "Claude Dev" and r.json()["avatar"] == "/static/avatars/robot.svg",
      f"rename + preset ({r.status_code} {r.text[:160]})")
check(cl.req("GET", "/me").json().get("username") == "claude-dev", "the agent's token keeps working after the rename")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"avatar_preset": "../x"}).status_code == 400, "unknown preset: 400")
png = io.BytesIO()
Image.new("RGB", (300, 300), (20, 120, 200)).save(png, "PNG")
check(Bo.post(B + f"/api/admin/agents/{AG}/avatar", files={"file": ("a.png", png.getvalue(), "image/png")}).status_code == 403, "upload: admins only")
r = A.post(B + f"/api/admin/agents/{AG}/avatar", files={"file": ("a.png", png.getvalue(), "image/png")})
url = r.json().get("avatar", "") if r.ok else ""
check(url.startswith(f"/api/avatar/{AG}/"), f"own photo for the agent ({r.status_code} {r.text[:120]})")
check(A.get(B + url).status_code == 200 and Bo.get(B + url).status_code == 200, "the photo is served to the admin and people sharing a list with it")
check(Da.get(B + url).status_code == 404, "not to someone who shares nothing with it")
check(A.post(B + f"/api/admin/agents/{AG}/avatar", files={"file": ("a.png", b"not a picture", "image/png")}).status_code == 400, "not a picture: 400")
files = os.listdir(os.path.join(DATA, "attachments", "avatars"))
check(sum(1 for f in files if f.startswith(f"u{AG}-")) == 1, "one photo file")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"avatar_preset": None})
check(r.ok and r.json()["avatar"] == "", "picture removed (initials)")
time.sleep(0.2)
check(not [f for f in os.listdir(os.path.join(DATA, "attachments", "avatars")) if f.startswith(f"u{AG}-")], "the photo file is deleted")
us = A.get(B + "/api/users").json()["users"]
ag = next((u for u in us if u["id"] == AG), None)
check(ag and ag["kind"] == "agent" and ag.get("agent") and ag["username"] == "claude-dev", "the admin user list contains the agent")
check(A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "noav", "avatar_preset": None}).json().get("avatar") == "", "create without a picture")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
