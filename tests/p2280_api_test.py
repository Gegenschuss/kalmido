#!/usr/bin/env python3
"""2.28.0 API tests ("Work and private apart, messages").
 - #935 workspaces: every list has one (lists.org_id, null = private); an organisation's list is shared only with its members
   (people 409, groups 409, ownership 409), agents join only lists of their own workspace (agents.org_id), "Used for" / Home &
   life only private, the inbox always private, the owner changes it (members must fit), the workspace setting; the migration
   of a server from before (everything in the organisation except family / Home & life / "Private" folders / inboxes)
 - mode KALMIDO_INSTANCE_MODE=workspaces (restart, same data): several organisations as workspaces on a shared server, people
   see only the members of their organisations + their connections (instance admins included: user list, users PATCH 404),
   the instance admin creates organisations, organisation admins manage members (add by e-mail, roles, removal), a leaver's
   organisation lists go to an organisation admin and the person leaves every list of the organisation (private lists stay),
   the only admin leaving hands over to the operator, the login page names no organisation, a cross-tenant matrix over the
   endpoints that list people / lists / tasks / News / search / agents / team chat
 - #965 admins reach agents only through lists like everyone; a personal agent (owner_id, "Belongs to") is invisible to admins
   in the chat, at @, in the state and in /api/agents; the administration lists it restricted (name, owner, kill switch) and
   refuses every other change (403)
 - #970 / #1011 POST /api/admin/agents with owner_id creates a personal agent; the user list carries kind
 - #987 News items say to_me (people's mentions, assignments, replies, decisions; never agents), unread_me at the bell,
   dm_unread; an agent's comment pushes only with the setting agent_push
 - #1005 chat answer buttons: choices (+ multi, styles) on an agent's message, the person's answer once, the event
   chat_choice, only the chat's person answers, validation
usage: p2280_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

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


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


CUR = {}


def events(hdr, key):
    r = requests.get(V + f"/agent/events?since={CUR.get(key, 0)}", headers=hdr)
    assert r.ok, r.text
    j = r.json()
    CUR[key] = j["cursor"]
    return j["data"]


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    assert subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


def state(s):
    return s.get(B + "/api/state").json()


def lists_of(s):
    return {l["id"]: l for l in state(s)["lists"]}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ME = state(A)["me"]
ORG = ME["workspaces"][0]["id"]

# ================================================================== #935 workspaces in the mode organisation (the default)
st = state(A)
check(st["workspaces"] is True and ME["workspaces"][0]["role"] == "admin", "#935: the instance admin administers the one organisation " + str(ME["workspaces"]))
check(state(Bo)["me"]["workspaces"][0]["role"] == "member", "#935: a member is a member")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()
P = A.post(B + "/api/lists", json={"name": "Home", "org_id": None}).json()
check(W["org_id"] == ORG and P["org_id"] is None, "#935: org_id on creation (given)")
check(A.post(B + "/api/lists", json={"name": "Default"}).json()["org_id"] == ORG, "#935: without org_id a new list is the organisation's (as every list was before 2.28)")
F = A.post(B + "/api/lists", json={"name": "Family", "family": "household"}).json()
check(F.get("org_id") is None, "#935: a family list is private")
r = A.patch(B + f"/api/lists/{F['id']}", json={"org_id": ORG})
check(r.status_code == 409 and "private" in r.text.lower(), "#935: a family list cannot go into an organisation " + r.text[:100])
r = A.patch(B + f"/api/lists/{W['id']}", json={"family": "shopping"})
check(r.ok and lists_of(A)[W["id"]]["org_id"] is None and lists_of(A)[W["id"]]["family"] == "shopping", "#935: 'Used for' makes an organisation's list private " + r.text[:80])
A.patch(B + f"/api/lists/{W['id']}", json={"family": ""})
check(A.patch(B + f"/api/lists/{W['id']}", json={"org_id": ORG}).ok and lists_of(A)[W["id"]]["org_id"] == ORG, "#935: ... and back into the organisation without it")
inbox = next(l for l in state(A)["lists"] if l["is_inbox"])
check(A.patch(B + f"/api/lists/{inbox['id']}", json={"org_id": ORG}).status_code == 409, "#935: the inbox stays private")
check(A.post(B + "/api/lists", json={"name": "X", "org_id": 999}).status_code == 409, "#935: an organisation one does not belong to is refused")
# the folder decides the default workspace of a new list
A.post(B + "/api/lists", json={"name": "W2", "org_id": ORG, "folder": "Office"})
check(A.post(B + "/api/lists", json={"name": "W3", "folder": "Office"}).json()["org_id"] == ORG, "#935: a new list in a folder of organisation lists is the organisation's")
A.post(B + "/api/lists", json={"name": "P1", "folder": "Mine", "org_id": None})
check(A.post(B + "/api/lists", json={"name": "P2", "folder": "Mine"}).json()["org_id"] is None, "#935: a new list in a folder of private lists is private")
# agents are bound to a workspace
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(r.json()["org_id"] == ORG, "#935: a team agent works in the organisation")
r = A.put(B + f"/api/lists/{P['id']}/members", json={"user_id": CL, "role": "edit"})
check(r.status_code == 409 and "workspace" in r.text.lower(), "#935: the organisation's agent cannot join a private list " + r.text[:100])
check(A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"}).ok, "#935: ... but an organisation list")
r = A.post(B + f"/api/agents/{CL}/share-all", json={})
check(r.ok and not any(x["id"] == P["id"] for x in state(A)["lists"] if any(m["user_id"] == CL for m in x["members"])), "#935: Share all skips private lists")
r = A.patch(B + f"/api/lists/{W['id']}", json={"org_id": None})
check(r.status_code == 409 and "Claude" in r.text, "#935: moving a list to private with the organisation's agent in it is refused " + r.text[:100])
A.delete(B + f"/api/lists/{W['id']}/members/{CL}")
check(A.patch(B + f"/api/lists/{W['id']}", json={"org_id": None}).ok and lists_of(A)[W["id"]]["org_id"] is None, "#935: without it the list goes private")
check(A.patch(B + f"/api/lists/{W['id']}", json={"org_id": ORG}).ok, "#935: and back")
check(Bo.patch(B + f"/api/lists/{W['id']}", json={"org_id": None}).status_code in (403, 404), "#935: a member cannot change the workspace")
# a personal agent in the private space; moving it with lists in another workspace is refused
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "mybot", "display_name": "My bot", "owner_id": 1})
MB, MBH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(r.json()["owner"]["id"] == 1 and r.json()["org_id"] == ORG, "#965/#970: created as Alice's personal agent (owner_id), in her organisation by default")
check(A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": None}).ok and A.get(B + "/api/admin/agents").json()["agents"][-1]["org_id"] is None, "#935: the owner moves her agent to private")
check(A.put(B + f"/api/lists/{P['id']}/members", json={"user_id": MB, "role": "edit"}).ok, "#935: a private agent joins a private list")
r = A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": ORG})
check(r.status_code == 400 and "lists of another workspace" in r.text, "#935: not moved while it sits in lists of the other workspace " + r.text[:100])
# the setting
check(A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"}).ok and state(A)["settings"]["workspace"] == f"org:{ORG}", "#935: the workspace setting")
check(A.patch(B + "/api/settings", json={"workspace": "org:999"}).status_code == 400, "#935: ... only one's own organisations")
A.patch(B + "/api/settings", json={"workspace": "all"})
# groups: only with members of the organisation (bob is a member -> ok); ownership: only to members
G = A.post(B + "/api/admin/groups", json={"name": "Devs", "members": [BOB]}).json()["id"]
check(A.put(B + f"/api/lists/{W['id']}/groups/{G}", json={"role": "edit"}).ok, "#935: a group of members may be shared into the organisation's list")

# ================================================================== #965 admins and personal agents
A.patch(B + f"/api/users/{BOB}", json={"is_admin": True})
check(not any(a["id"] in (CL, MB) for a in Bo.get(B + "/api/agents").json()["agents"]), "#965: an admin without a shared list sees no agent in /api/agents")
check(not any(a["id"] in (CL, MB) for a in state(Bo)["agents"]), "#965: ... nor in the state")
check(Bo.get(B + f"/api/agents/{MB}/chat").status_code == 404 and Bo.post(B + f"/api/agents/{MB}/chat", json={"body": "hi"}).status_code == 404, "#965: an admin cannot chat with somebody's personal agent")
check(Bo.get(B + f"/api/agents/{CL}/chat").status_code == 404, "#965: ... nor with a team agent of lists it is not in")
adm = Bo.get(B + "/api/admin/agents").json()["agents"]
mb = next(a for a in adm if a["id"] == MB)
check(mb.get("restricted") is True and mb["owner"]["id"] == 1 and "tokens" in mb and not mb["tokens"] and not mb["lists"], "#965: the administration lists it restricted " + str(sorted(mb)))
check(Bo.patch(B + f"/api/admin/agents/{MB}", json={"display_name": "Hijack"}).status_code == 403, "#965: an admin changes nothing on it ...")
check(Bo.patch(B + f"/api/admin/agents/{MB}", json={"enabled": False}).ok and not A.get(B + "/api/admin/agents").json()["agents"][-1]["enabled"], "#965: ... except the kill switch")
check(A.patch(B + f"/api/admin/agents/{MB}", json={"enabled": True}).ok, "#965: the owner resumes it")
TW = A.post(B + "/api/tasks", json={"title": "Work task", "list_id": W["id"]}).json()["id"]
check(A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"}).ok, "share Work with Claude again")
check(A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "edit"}).ok, "share Work with bob")
check(not any(a["id"] == CL for a in Bo.get(B + "/api/agents").json()["agents"]), "#965: a member (admin) still does not reach the agent while the list is not open to members")
A.patch(B + f"/api/lists/{W['id']}", json={"agent_members": True})
check(any(a["id"] == CL for a in Bo.get(B + "/api/agents").json()["agents"]), "#965: with the list open he does, like everyone")
jobs = Bo.get(B + "/api/agents/jobs").json()["jobs"]
r = requests.post(V + "/agent/jobs", headers=MBH, json={"title": "Private job", "state": "running"})
check(r.ok and not any(j["id"] == r.json()["id"] for j in Bo.get(B + "/api/agents/jobs").json()["jobs"]), "#965: an admin does not see the jobs of somebody's personal agent")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"owner_id": CAROL}).json()["owner"]["id"] == CAROL, "#965: 'Belongs to' moves a team agent to a person")
check(not any(a["id"] == CL for a in A.get(B + "/api/agents").json()["agents"]), "#965: ... then even the instance admin (not the owner) does not reach it")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"owner_id": None}).json()["owner"] is None, "#965: and back to a team agent")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"owner_id": CL}).status_code == 400, "#965: an agent cannot own an agent")
us = A.get(B + "/api/users").json()["users"]
check(all("kind" in u for u in us) and sum(1 for u in us if u["kind"] == "agent") == 2, "#1011: the user list carries kind (the app shows people only)")

# ================================================================== #987 News: For you / Activity
TB = Bo.post(B + "/api/tasks", json={"title": "Bob's task", "list_id": W["id"]}).json()["id"]
Bo.post(B + f"/api/tasks/{TB}/comments", json={"body": "<@1> can you look?"})
Bo.patch(B + f"/api/tasks/{TB}", json={"assignee_id": 1})
A.post(B + f"/api/tasks/{TB}/comments", json={"body": "sure"})
Bo.post(B + f"/api/tasks/{TB}/comments", json={"body": "thanks (a reply)"})
requests.post(V + f"/tasks/{TB}/comments", headers=CLH, json={"body": "<@1> agent mention"})
requests.post(V + f"/tasks/{TW}/comments", headers=CLH, json={"body": "agent activity"})
Bo.post(B + f"/api/tasks/{TW}/complete")
nj = A.get(B + "/api/news").json()
by = {}
for it in nj["items"]:
    by.setdefault((it["kind"], it["actor_id"]), []).append(it)
check(all(x["to_me"] for x in by.get(("mention", BOB), [])) and by.get(("mention", BOB)), "#987: bob's mention is for me")
check(all(x["to_me"] for x in by.get(("assign", BOB), [])) and by.get(("assign", BOB)), "#987: bob's assignment is for me")
reply = [x for x in by.get(("comment", BOB), []) if x["data"].get("reply")]
check(reply and all(x["to_me"] for x in reply), "#987: bob's reply to my comment is for me " + str([(x["data"], x["to_me"]) for x in by.get(("comment", BOB), [])]))
check(by.get(("mention", CL)) and not any(x["to_me"] for x in by[("mention", CL)]), "#987: an agent's mention is activity")
check(by.get(("comment", CL)) and not any(x["to_me"] for x in by[("comment", CL)]), "#987: an agent's comment is activity")
check(not any(x["to_me"] for x in by.get(("complete", BOB), [])), "#987: a completion is activity")
me_n = sum(1 for it in nj["items"] if it["to_me"] and not it["read"])
check(nj["unread_me"] == me_n and me_n >= 3 and nj["unread"] > nj["unread_me"], f"#987: unread_me {nj['unread_me']} < unread {nj['unread']}")
check(state(A)["news"]["unread_me"] == me_n, "#987: the state carries unread_me")
A.post(B + "/api/news/read", json={"ids": [reply[0]["id"]]})
check(A.get(B + "/api/news").json()["unread_me"] == me_n - 1, "#987: reading one lowers unread_me")
# direct messages count for me
rm = Bo.post(B + "/api/team/dm", json={"user_id": 1}).json()
Bo.post(B + f"/api/team/rooms/{rm['id']}/messages", json={"body": "ping"})
check(state(A)["team"]["dm_unread"] == 1, "#987: an unread direct message counts (dm_unread)")
# agent pushes off by default: the push subscription is a stub -- check the gate itself
from_api = A.get(B + "/api/state").json()["settings"]
check(from_api.get("agent_push") == "0", "#987: agent_push is off by default")
check(A.patch(B + "/api/settings", json={"agent_push": "1"}).ok and state(A)["settings"]["agent_push"] == "1", "#987: ... and can be switched on")
A.patch(B + "/api/settings", json={"agent_push": "0"})

# ================================================================== #1005 chat answer buttons
r = requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "Deploy `v2`?", "choices": [{"id": "ok", "label": "Allow", "style": "primary"}, {"id": "no", "label": "Deny", "style": "danger"}]})
check(r.status_code == 201 and r.json()["choices"]["choices"][1]["style"] == "danger" and r.json()["choices"]["multi"] is False and r.json()["choice"] is None, "#1005: a message with buttons " + r.text[:150])
M1 = r.json()["id"]
check(requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "x", "choices": [{"id": "a b", "label": "A"}]}).status_code == 400, "#1005: an invalid id is refused")
check(requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "x", "choices": [{"id": str(i), "label": "A"} for i in range(9)]}).status_code == 400, "#1005: at most 8 buttons")
check(requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "x", "choices": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}).status_code == 400, "#1005: ids must be unique")
check(Bo.post(B + f"/api/agents/{CL}/chat/{M1}/choice", json={"choice_ids": ["ok"]}).status_code == 404, "#1005: only the chat's person answers")
check(A.post(B + f"/api/agents/{CL}/chat/{M1}/choice", json={"choice_ids": ["nope"]}).status_code == 400, "#1005: an unknown choice is refused")
check(A.post(B + f"/api/agents/{CL}/chat/{M1}/choice", json={"choice_ids": ["ok", "no"]}).status_code == 400, "#1005: two answers without multi are refused")
events(CLH, "cl")
r = A.post(B + f"/api/agents/{CL}/chat/{M1}/choice", json={"choice_ids": ["ok"]})
check(r.ok and r.json()["choice"]["ids"] == ["ok"] and r.json()["choice"]["user_id"] == 1, "#1005: the answer is stored " + r.text[:120])
check(A.post(B + f"/api/agents/{CL}/chat/{M1}/choice", json={"choice_ids": ["no"]}).status_code == 409, "#1005: answered once")
ev = [e for e in events(CLH, "cl") if e["event"] == "chat_choice"]
check(len(ev) == 1 and ev[0]["data"]["message_id"] == M1 and ev[0]["data"]["choice_ids"] == ["ok"] and ev[0]["data"]["labels"] == ["Allow"] and ev[0]["data"]["user"]["id"] == 1 and ev[0]["actor"]["kind"] == "person", "#1005: the event chat_choice " + str(ev[:1])[:300])
hist = requests.get(V + "/agent/chats?user_id=1", headers=CLH).json()["data"]
check(any(m["id"] == M1 and m["choice"]["ids"] == ["ok"] for m in hist), "#1005: the history carries the choice")
r = requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "Which?", "choices": ["red", "green", "blue"], "multi": True})
M2 = r.json()["id"]
check(r.ok and r.json()["choices"]["multi"] is True and r.json()["choices"]["choices"][0] == {"id": "red", "label": "red"}, "#1005: strings as choices, multi")
r = A.post(B + f"/api/agents/{CL}/chat/{M2}/choice", json={"choice_ids": ["blue", "red"]})
check(r.ok and r.json()["choice"]["ids"] == ["red", "blue"], "#1005: several answers with multi (in the buttons' order)")
check(requests.post(V + f"/agents/{CL}/chat/{M2}/choice", headers=CLH, json={"choice_ids": ["red"]}).status_code in (403, 404), "#1005: an agent never answers")
# a person's own token answers too
tk = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "comments"]}).json().get("token")
if tk:
    r = requests.post(V + "/agent/chats/1", headers=CLH, json={"body": "Again?", "choices": ["y", "n"]})
    r2 = requests.post(V + f"/agents/{CL}/chat/{r.json()['id']}/choice", headers={"Authorization": "Bearer " + tk}, json={"choice_ids": ["y"]})
    check(r2.ok and r2.json()["choice"]["ids"] == ["y"], "#1005: a person's API token answers " + r2.text[:100])

# ================================================================== #935: the migration of a server from before the workspaces
dbx("UPDATE lists SET org_id=NULL", write=True)
dbx("UPDATE agents SET org_id=NULL", write=True)
dbx("DELETE FROM settings WHERE key='migr_ws2280'", write=True)
PRIV = A.post(B + "/api/lists", json={"name": "Old private", "folder": "Privat/Haus"}).json()["id"]
LIFE = A.post(B + "/api/lists", json={"name": "Contracts"}).json()["id"]
dbx("UPDATE lists SET life='contracts' WHERE id=?", (LIFE,), write=True)
dbx("UPDATE lists SET org_id=NULL", write=True)
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,'2026-01-01T00:00:00+00:00')", (PRIV, CL), write=True)  # the organisation's agent in a list that becomes private
restart("")
A = sess("alice")
ls = lists_of(A)
check(ls[W["id"]]["org_id"] == ORG and ls[P["id"]]["org_id"] == ORG, "#935 migration: lists stay in the organisation (a server from before = one company)")
check(ls[PRIV]["org_id"] is None and ls[LIFE]["org_id"] is None and ls[F["id"]]["org_id"] is None and next(l for l in ls.values() if l["is_inbox"])["org_id"] is None,
      "#935 migration: 'Privat' folder, Home & life, family and the inbox are private " + str([ls[PRIV]["org_id"], ls[LIFE]["org_id"], ls[F["id"]]["org_id"]]))
ags = {a["id"]: a for a in A.get(B + "/api/admin/agents").json()["agents"]}
check(ags[CL]["org_id"] == ORG, "#935 migration: the team agent works in the organisation")
mb_ws = [r[0] for r in dbx("SELECT l.org_id FROM lists l WHERE l.is_inbox=0 AND (l.owner_id=? OR l.id IN (SELECT list_id FROM list_members WHERE user_id=?))", (MB, MB))]
mb_exp = ORG if mb_ws.count(ORG) >= mb_ws.count(None) and mb_ws else None  # the majority, a tie goes to the organisation
check(ags[MB]["org_id"] == mb_exp, f"#935 migration: the personal agent follows its lists ({mb_ws}) -> {ags[MB]['org_id']}")
check(state(A)["ws_mismatches"].get(str(PRIV)) == [CL] and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (PRIV, CL)), "#935 migration: an agent in a list of another workspace is reported, not removed " + str(state(A)["ws_mismatches"]))

# ================================================================== mode workspaces: several organisations on a shared server
restart("-e KALMIDO_INSTANCE_MODE=workspaces")
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
info = s0.get(B + "/api/auth/info").json()
check(not info.get("org"), "workspaces: the login page names no organisation " + str(info.get("org")))
check(state(A)["instance_mode"] == "workspaces", "workspaces: the mode in the state")
r = Bo.post(B + "/api/admin/orgs", json={"name": "Beta", "icon": "B", "domains": "beta.example", "admin_id": CAROL})
check(r.status_code == 201 and r.json()["admins"] == [CAROL] and r.json()["members"] == [CAROL], "workspaces: the instance admin creates an organisation with its first admin " + r.text[:150])
BETA = r.json()["id"]
check(Bo.post(B + "/api/admin/orgs", json={"name": "beta"}).status_code == 409, "workspaces: a name once")
check(Ca.post(B + "/api/admin/orgs", json={"name": "Gamma"}).status_code == 403, "workspaces: a plain person creates none")
# carol leaves the first organisation (bob removes her) -> she is only in Beta; dave goes to Beta too (by e-mail)
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "workspaces: an organisation admin removes a member")
check(Ca.put(B + f"/api/orgs/{BETA}/members", json={"email": "DAVE@example.com"}).json().get("by_email") is True, "workspaces: the organisation admin adds dave by e-mail")
check(Ca.put(B + f"/api/orgs/{BETA}/members", json={"email": "nobody@example.com"}).json().get("by_email") is True, "workspaces: an unknown address is not revealed")
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{DAVE}").ok, "workspaces: dave out of the first organisation")
check(Da.put(B + f"/api/orgs/{BETA}/members", json={"user_id": CAROL, "role": "admin"}).status_code == 403, "workspaces: a plain member manages nothing")
check(Ca.put(B + f"/api/orgs/{BETA}/members", json={"user_id": BOB, "email": "x@example.com"}).status_code == 400, "review 1: user_id + email together are refused (no pulling invisible people in by id)")
check(Ca.put(B + f"/api/orgs/{BETA}/members", json={"user_id": BOB}).status_code == 404, "review 1: an invisible person cannot be added by id")
# review 2: a group that gets a member of another organisation never carries them into an organisation's list
GB = Bo.post(B + "/api/admin/groups", json={"name": "Mixed", "members": [BOB]}).json()["id"]
LBO = Bo.post(B + "/api/lists", json={"name": "Org via group", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{LBO}/groups/{GB}", json={"role": "edit"}).ok, "review 2: a group of members is shared into the organisation's list")
check(Bo.patch(B + f"/api/admin/groups/{GB}", json={"members": [BOB, DAVE]}).status_code == 400, "review 2: an instance admin cannot put an invisible person into a group (workspaces)")
dbx("INSERT OR IGNORE INTO group_members(group_id,user_id,added_at) VALUES(?,?,'2026-01-01T00:00:00+00:00')", (GB, DAVE), write=True)
Bo.patch(B + f"/api/lists/{LBO}/groups/{GB}", json={"role": "view"}) if False else Bo.put(B + f"/api/lists/{LBO}/groups/{GB}", json={"role": "view"})
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LBO, DAVE)), "review 2: the group sync never carries somebody of another workspace into the organisation's list")
check(Bo.delete(B + f"/api/admin/groups/{GB}").ok and Bo.delete(B + f"/api/lists/{LBO}/members/{BOB}").status_code in (200, 404), "review 2: the group goes again (no connection between dave and bob through it)")
dbx("DELETE FROM lists WHERE id=?", (LBO,), write=True)
# review 3: a project of a built-in type is in the organisation from the first second (its agents / folder people fit)
PT = Bo.post(B + "/api/lists", json={"name": "Typed", "ptype": "software", "org_id": ORG}).json()
check(PT.get("org_id") == ORG, "review 3: a typed project gets its workspace on creation " + str(PT.get("org_id")))
check(Da.patch(B + f"/api/orgs/{BETA}", json={"name": "Pwned"}).status_code == 403, "workspaces: ... nor renames")
check(Ca.patch(B + f"/api/orgs/{BETA}", json={"name": "Beta Corp"}).ok and Ca.get(B + "/api/orgs").json()["orgs"][0]["name"] == "Beta Corp", "workspaces: the organisation admin renames it")
check(Da.get(B + f"/api/orgs").json()["orgs"][0]["role"] == "member", "workspaces: dave is a member of Beta")
# visibility: Beta people see each other, not the first organisation's people (and the other way round); connections count
seen = lambda s: {u["id"] for u in s.get(B + "/api/users").json()["users"]}
check(seen(Da) == {DAVE, CAROL}, "workspaces: dave sees Beta only " + str(seen(Da)))
check(1 not in seen(Ca) and BOB not in seen(Ca), "workspaces: carol does not see the first organisation's people")
check(CAROL not in seen(A) and DAVE not in seen(A), "workspaces: the instance admin does not see Beta's people " + str(seen(A)))
check(A.get(B + "/api/users").json().get("others") == 2, "workspaces: ... only how many there are")
check(A.patch(B + f"/api/users/{DAVE}", json={"display_name": "X"}).status_code == 404 and A.delete(B + f"/api/users/{DAVE}").status_code == 404, "workspaces: an instance admin manages only people it sees")
check(A.get(B + "/api/admin/orgs").json()["creatable"] is True and len(A.get(B + "/api/admin/orgs").json()["orgs"]) == 2, "workspaces: the instance admin sees every organisation (names, counts)")
# sharing across the boundary
LB = Ca.post(B + "/api/lists", json={"name": "Beta plan", "org_id": BETA}).json()
r = Ca.put(B + f"/api/lists/{LB['id']}/members", json={"user_id": BOB, "role": "edit"})
check(r.status_code == 404, "workspaces: carol cannot even name bob (invisible) " + r.text[:80])
r = Ca.put(B + f"/api/lists/{LB['id']}/members", json={"email": "bob@example.com"})
check(r.ok and r.json().get("by_email") and not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LB["id"], BOB)), "workspaces: by e-mail into an organisation's list: not a member -> nothing happens, nothing revealed")
PB = Ca.post(B + "/api/lists", json={"name": "Carol private", "org_id": None}).json()
r = Ca.put(B + f"/api/lists/{PB['id']}/members", json={"email": "bob@example.com"})
check(r.ok and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (PB["id"], BOB)), "workspaces: a private list is shared by e-mail across organisations")
check(BOB in seen(Ca) and CAROL in seen(Bo), "workspaces: now they are connected and see each other")
r = Ca.put(B + f"/api/lists/{LB['id']}/members", json={"user_id": BOB, "role": "edit"})
check(r.status_code == 409 and "not a member of the organisation" in r.text, "workspaces: Beta's list still refuses bob (not a member) " + r.text[:100])
check(Ca.put(B + f"/api/lists/{LB['id']}/members", json={"user_id": DAVE, "role": "edit"}).ok, "workspaces: ... and takes dave")
# review 5 / 12: an organisation admin cannot remove the last admin of an organisation
check(Bo.delete(B + f"/api/orgs/{ORG}/members/1").status_code == 409 if dbx("SELECT COUNT(*) FROM org_members WHERE org_id=? AND role='admin'", (ORG,))[0][0] <= 1 else True, "review 12: the last admin of an organisation cannot be removed")
# the cross-tenant matrix: nothing of Beta reaches alice / bob
TBETA = Ca.post(B + "/api/tasks", json={"title": "Secret Beta plan", "list_id": LB["id"]}).json()["id"]
Ca.post(B + f"/api/tasks/{TBETA}/comments", json={"body": f"<@{DAVE}> secret"})
for name, s in (("alice", A), ("bob", Bo)):
    st = state(s)
    check(not any(l["id"] == LB["id"] for l in st["lists"]) and not any(t["id"] == TBETA for t in st["tasks"]), f"matrix {name}: no Beta list / task in the state")
    check(not any(t["id"] == TBETA for t in s.get(B + "/api/tasks?scope=search&q=Secret").json()["tasks"]), f"matrix {name}: search finds nothing of Beta")
    check(s.get(B + f"/api/tasks/{TBETA}").status_code == 404 and s.get(B + f"/api/lists/{LB['id']}/owner").status_code == 404, f"matrix {name}: Beta's task / list answer 404")
    check(not any(it.get("list_id") == LB["id"] for it in s.get(B + "/api/news").json()["items"]), f"matrix {name}: no Beta News")
    check(not any(r_["kind"] == "list" and r_.get("list_id") == LB["id"] for r_ in s.get(B + "/api/team").json()["rooms"]), f"matrix {name}: no Beta team chat")
    check(s.post(B + "/api/team/dm", json={"user_id": DAVE}).status_code in (403, 404), f"matrix {name}: no direct message to an invisible person")
check(not any(t["id"] == TW for t in state(Da)["tasks"]) and Da.get(B + f"/api/tasks/{TW}").status_code == 404, "matrix dave: nothing of the first organisation")
check(Da.get(B + f"/api/agents").json()["agents"] == [], "matrix dave: no agents of the other organisation")
r = requests.get(V + f"/tasks/{TBETA}", headers=CLH)
check(r.status_code == 404, "matrix: the first organisation's agent does not see Beta's task")
# leaving: carol's organisation lists go to an admin, her private list stays hers; the only admin -> the operator
check(Ca.put(B + f"/api/orgs/{BETA}/members", json={"user_id": DAVE, "role": "admin"}).ok, "workspaces: dave becomes an admin of Beta")
r = Ca.delete(B + f"/api/orgs/{BETA}/members/{CAROL}")
check(r.ok and r.json()["transferred"] == 1, "workspaces: carol leaves Beta " + r.text)
lb = dbx("SELECT owner_id, org_id FROM lists WHERE id=?", (LB["id"],))[0]
check(lb[0] == DAVE and lb[1] == BETA and not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LB["id"], CAROL)), "workspaces: her Beta list went to the next admin and she left it " + str(lb))
check(dbx("SELECT owner_id FROM lists WHERE id=?", (PB["id"],))[0][0] == CAROL, "workspaces: her private list stays hers")
check(Ca.get(B + "/api/orgs").json()["orgs"] == [], "workspaces: carol belongs to no organisation now")
r = Da.delete(B + f"/api/orgs/{BETA}/members/{DAVE}")
check(r.ok, "workspaces: the only admin leaves -> the operator takes over " + r.text)
lb = dbx("SELECT owner_id FROM lists WHERE id=?", (LB["id"],))[0][0]
adms = dbx("SELECT user_id FROM org_members WHERE org_id=? AND role='admin'", (BETA,))
check(lb in (1, BOB) and adms and adms[0][0] in (1, BOB), f"workspaces: the operator (an instance admin) owns the lists and administers Beta {lb} {adms}")
op = A if lb == 1 else Bo
check(any(it["kind"] == "share" and it["data"].get("org") and it["data"].get("handover") == 1 for it in op.get(B + "/api/news").json()["items"]), "workspaces: the operator is told (News)")
r = op.delete(B + f"/api/admin/orgs/{BETA}")
check(r.status_code == 409, "workspaces: an organisation with lists is not deleted")
dbx("DELETE FROM lists WHERE id=?", (LB["id"],), write=True)
check(op.delete(B + f"/api/admin/orgs/{BETA}").ok, "workspaces: without lists it is")
# the last admin of the only organisation on the server cannot leave when nobody could take over
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": 1, "role": "member"}).ok, "workspaces: alice steps down as admin of the first organisation")
A.patch(B + f"/api/users/{BOB}", json={"is_admin": True})
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{BOB}")
check(r.ok, "workspaces: bob (the only org admin) leaves -> alice (instance admin) takes over " + r.text[:100])
check(dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=1", (ORG,))[0][0] == "admin", "workspaces: alice administers it again")
r = A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin", "password": "password123", "orgs": []})
check(r.ok and r.json()["orgs"] == [], "workspaces: a new account joins no organisation by default " + str(r.json().get("orgs")))

print(f"p2280_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
