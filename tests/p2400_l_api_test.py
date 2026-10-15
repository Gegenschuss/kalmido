#!/usr/bin/env python3
"""2.40.0 API tests (agent L: list rights, custom fields, folders).
 - #1192 list admins manage custom fields like the owner: create, rename, sort, pin, delete (web API and REST API); a
   member with edit gets 403; limits 20 fields / 2 pinned stay; GET /api/fields/{id}/count counts the tasks with a value
   (for the delete confirmation; member 403, a stranger 404)
 - #1193 select options keep the order and the colours they are sent in (the order is the sort order of the field)
 - #1431 list admins change name, colour and the picture icon; a rename tells the owner (News orglist / lrename with the
   old and the new name), colour and icon tell nobody; kind / rate / org_id stay the owner's (403), a member 403
 - #1337 a list admin archives / restores: the owner AND the members hear about it (data.member for the members, never
   agents, never the admin who did it)
 - #1373 agent_peers is fixed off: an agent's mention never reaches another agent, also in an old list with two agents
   and after PATCH agent_peers true (accepted, ignored); folder defaults ignore it; the REST API says false
 - #1422 a new list in a folder with a workspace default: the same workspace sent along is not "differs from the folder";
   another one is
 - #1414 a new list in a folder with a default agent gets the agent (POST /api/lists with folder)
usage: p2400_l_api_test.py <datadir>"""
import os
import subprocess
import sys

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


def news(s):
    return [x.get("data") or {} for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == "orglist"]


CUR = {}


def events(hdr, key):
    r = requests.get(V + f"/agent/events?since={CUR.get(key, 0)}", headers=hdr)
    assert r.ok, r.text
    CUR[key] = r.json()["cursor"]
    return r.json()["data"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]

# bob owns "Fair stand", carol is a list admin, dave edits
SH = Bo.post(B + "/api/lists", json={"name": "Fair stand"}).json()["id"]
check(Bo.put(B + f"/api/lists/{SH}/members", json={"user_id": CAROL, "role": "admin"}).ok, "setup: carol is a list admin")
check(Bo.put(B + f"/api/lists/{SH}/members", json={"user_id": DAVE, "role": "edit"}).ok, "setup: dave edits")

# ================================================================== #1192 list admins manage custom fields
r = Ca.post(B + f"/api/lists/{SH}/fields", json={"name": "Stage", "type": "select", "options": {"options": [
    {"name": "Not started", "color": "#94a3b8"}, {"name": "In progress", "color": "#6d8cff"}, {"name": "Waiting", "color": "#f5b041"},
    {"name": "Done", "color": "#4ade80"}]}})
check(r.ok, "#1192: the list admin creates a field " + r.text[:200])
FS = r.json()["id"]
check(Da.post(B + f"/api/lists/{SH}/fields", json={"name": "X", "type": "text"}).status_code == 403, "#1192: a member with edit cannot create (403)")
check(Ca.patch(B + f"/api/fields/{FS}", json={"name": "Phase"}).ok and dbx("SELECT name FROM list_fields WHERE id=?", (FS,))[0][0] == "Phase", "#1192: the admin renames")
check(Da.patch(B + f"/api/fields/{FS}", json={"name": "No"}).status_code == 403, "#1192: a member cannot rename (403)")
FB = Ca.post(B + f"/api/lists/{SH}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
check(Ca.patch(B + f"/api/fields/{FB}", json={"sort": -1}).ok and [f["id"] for f in Ca.get(B + "/api/state").json()["fields"] if f["list_id"] == SH][0] == FB,
      "#1192: the admin sorts (Budget first)")
check(Ca.patch(B + f"/api/fields/{FB}", json={"pinned": True}).ok and Ca.patch(B + f"/api/fields/{FS}", json={"pinned": True}).ok, "#1192: the admin pins two fields")
F3 = Ca.post(B + f"/api/lists/{SH}/fields", json={"name": "Client", "type": "text"}).json()["id"]
check(Ca.patch(B + f"/api/fields/{F3}", json={"pinned": True}).status_code == 400, "#1192: still at most 2 pinned fields")
for i in range(17):
    Ca.post(B + f"/api/lists/{SH}/fields", json={"name": f"F{i}", "type": "text"})
check(dbx("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (SH,))[0][0] == 20 and Ca.post(B + f"/api/lists/{SH}/fields", json={"name": "F21", "type": "text"}).status_code == 400,
      "#1192: still at most 20 fields per list")
T1 = Bo.post(B + "/api/tasks", json={"title": "Book the booth", "list_id": SH}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Print flyers", "list_id": SH}).json()["id"]
Bo.patch(B + f"/api/tasks/{T1}", json={"fields": {str(F3): "Muster AG"}})
Bo.patch(B + f"/api/tasks/{T2}", json={"fields": {str(F3): "Beispiel GmbH"}})
Bo.patch(B + f"/api/tasks/{T2}", json={"status": 1})
r = Ca.get(B + f"/api/fields/{F3}/count")
# 2.43.0 (#1328): the count also names the formulas that use the field (used_by)
check(r.ok and r.json().get("tasks") == 2 and not r.json().get("used_by"), "#1192: the count names every task with a value (also completed ones) " + r.text[:100])
check(Da.get(B + f"/api/fields/{F3}/count").status_code == 403, "#1192: a member gets no count (403)")
check(A.get(B + f"/api/fields/{F3}/count").status_code == 404, "#1192: someone outside the list: 404")
r = Ca.delete(B + f"/api/fields/{F3}")
check(r.ok and r.json().get("values") == 2 and not dbx("SELECT 1 FROM list_fields WHERE id=?", (F3,)), "#1192: the admin deletes the field and its values " + r.text[:100])
check(Da.delete(B + f"/api/fields/{FB}").status_code == 403, "#1192: a member cannot delete (403)")
# the REST API the same
tok_c = Ca.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure", "delete"]}).json()["token"]
tok_d = Da.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure", "delete"]}).json()["token"]
VC, VD = {"Authorization": "Bearer " + tok_c}, {"Authorization": "Bearer " + tok_d}
for fid in [x[0] for x in dbx("SELECT id FROM list_fields WHERE list_id=? AND name LIKE 'F%'", (SH,))][:3]:
    Ca.delete(B + f"/api/fields/{fid}")
r = requests.post(V + f"/lists/{SH}/fields", headers=VC, json={"name": "Via API", "type": "text"})
check(r.status_code == 201, "#1192 v1: the list admin creates a field " + r.text[:160])
FV = r.json().get("id")
check(requests.patch(V + f"/fields/{FV}", headers=VC, json={"name": "Via REST"}).ok, "#1192 v1: the list admin renames")
check(requests.post(V + f"/lists/{SH}/fields", headers=VD, json={"name": "No", "type": "text"}).status_code == 403, "#1192 v1: a member 403")
check(requests.delete(V + f"/fields/{FV}", headers=VD).status_code == 403, "#1192 v1: a member cannot delete")
check(requests.delete(V + f"/fields/{FV}", headers=VC).ok, "#1192 v1: the list admin deletes")

# ================================================================== #1193 the option order and colours are kept
opts = [o for o in [f for f in Bo.get(B + "/api/state").json()["fields"] if f["id"] == FS][0]["options"]["options"]]
check([o["name"] for o in opts] == ["Not started", "In progress", "Waiting", "Done"] and [o["color"] for o in opts] == ["#94a3b8", "#6d8cff", "#f5b041", "#4ade80"],
      "#1193: the Status template's options with their colours " + str(opts)[:200])
r = Ca.patch(B + f"/api/fields/{FS}", json={"options": {"options": [opts[3], opts[0], opts[1], opts[2]]}})
check(r.ok and [o["id"] for o in r.json()["options"]["options"]] == [opts[3]["id"], opts[0]["id"], opts[1]["id"], opts[2]["id"]],
      "#1193: reordered options keep their ids (values stay) in the new order")

# ================================================================== #1431 list admins rename / recolour / change the icon
r = Ca.patch(B + f"/api/lists/{SH}", json={"name": "Fair booth", "color": "#f472b6"})
check(r.ok and dbx("SELECT name, color FROM lists WHERE id=?", (SH,))[0] == ("Fair booth", "#f472b6"), "#1431: the list admin renames and recolours " + r.text[:120])
nb = news(Bo)
check(any(x.get("action") == "lrename" and x.get("old") == "Fair stand" and x.get("name") == "Fair booth" for x in nb), "#1431: the owner hears about the rename " + str(nb)[:300])
n0 = len(news(Bo))
check(Ca.patch(B + f"/api/lists/{SH}", json={"color": "#6d8cff"}).ok and len(news(Bo)) == n0, "#1431: a colour alone tells nobody")
check(Ca.put(B + f"/api/lists/{SH}/icon", json={"preset": "kalmido"}).ok and dbx("SELECT icon FROM lists WHERE id=?", (SH,))[0][0] == "p:kalmido", "#1431: the admin picks a picture icon")
check(Ca.delete(B + f"/api/lists/{SH}/icon").ok and dbx("SELECT icon FROM lists WHERE id=?", (SH,))[0][0] is None and len(news(Bo)) == n0, "#1431: ... removes it, no News")
check(Da.put(B + f"/api/lists/{SH}/icon", json={"preset": "kalmido"}).status_code == 403, "#1431: a member cannot change the icon")
check(Da.patch(B + f"/api/lists/{SH}", json={"name": "Mine"}).status_code == 403, "#1431: a member cannot rename (403)")
for k, v in (("kind", "project"), ("rate", "80"), ("org_id", ORG), ("nag", "1d")):
    check(Ca.patch(B + f"/api/lists/{SH}", json={k: v}).status_code == 403, f"#1431: {k} stays the owner's (403)")
check(Ca.patch(B + f"/api/lists/{SH}", json={"name": "  "}).status_code == 400, "#1431: an empty name is refused")
check(requests.patch(V + f"/lists/{SH}", headers=VC, json={"name": "Fair booth 2"}).ok and dbx("SELECT name FROM lists WHERE id=?", (SH,))[0][0] == "Fair booth 2",
      "#1431 v1: the list admin renames through the REST API")
check(requests.patch(V + f"/lists/{SH}", headers=VD, json={"name": "x"}).status_code == 403, "#1431 v1: a member 403")

# ================================================================== #1337 archive by a list admin: the members hear about it too
SC = ["read", "tasks:write", "comments", "structure"]
r = A.post(B + "/api/admin/agents", json={"scopes": SC, "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", (SH, CL, "edit", "edit"), write=True)
check(Ca.patch(B + f"/api/lists/{SH}", json={"archived": 1}).ok, "#1337: the list admin archives")
nd, nb, nc = news(Da), news(Bo), news(Ca)
check(any(x.get("action") == "larchive" and x.get("member") == 1 for x in nd), "#1337: the member hears about it (data.member) " + str(nd)[:200])
check(any(x.get("action") == "larchive" and not x.get("member") for x in nb), "#1337: the owner as before (your list) " + str(nb)[:200])
check(not any(x.get("action") == "larchive" for x in nc), "#1337: not the admin who did it")
check(not dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='orglist'", (CL,)), "#1337: never the agent")
check(Ca.patch(B + f"/api/lists/{SH}", json={"archived": 0}).ok and any(x.get("action") == "lrestore" and x.get("member") == 1 for x in news(Da)),
      "#1337: the restore too")

# ================================================================== #1373 agent_peers fixed off (an old list with two agents)
r = A.post(B + "/api/admin/agents", json={"scopes": SC, "username": "codex", "display_name": "Codex"})
CX, CXH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": SC, "username": "claude2", "display_name": "Claude Two"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}  # a fresh agent (no other lists, no bridge)
L2 = A.post(B + "/api/lists", json={"name": "Legacy two agents"}).json()["id"]
check(A.put(B + f"/api/lists/{L2}/members", json={"user_id": CL, "role": "edit"}).ok, "#1373: setup: Claude Two in the list")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", (L2, CX, "edit", "edit"), write=True)
dbx("UPDATE lists SET agent_peers=1 WHERE id=?", (L2,), write=True)  # switched on before 2.40.0
t2 = A.post(B + "/api/tasks", json={"title": "Shared by two", "list_id": L2}).json()
events(CXH, "cx")
check(requests.post(V + f"/tasks/{t2['id']}/comments", headers=CLH, json={"body": f"<@{CX}> run the deploy"}).ok, "#1373: Claude comments")
check(not [e for e in events(CXH, "cx") if e["event"] in ("mention", "comment")], "#1373: an old list with agent_peers=1: still no event between agents")
r = A.patch(B + f"/api/lists/{L2}", json={"agent_peers": True})
check(r.ok, "#1373: PATCH agent_peers is accepted (old clients) " + r.text[:100])
requests.post(V + f"/tasks/{t2['id']}/comments", headers=CLH, json={"body": f"<@{CX}> again"})
check(not [e for e in events(CXH, "cx") if e["event"] in ("mention", "comment")], "#1373: ... and ignored, no event")
tok_a = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure"]}).json()["token"]
VA = {"Authorization": "Bearer " + tok_a}
r = requests.patch(V + f"/lists/{L2}", headers=VA, json={"agent_peers": True})
check(r.ok and r.json().get("agent_peers") is False, "#1373 v1: accepted, the answer says false " + r.text[:160])
check(requests.get(V + f"/lists/{L2}", headers=VA).json().get("agent_peers") is False, "#1373 v1: GET says false")
spec = requests.get(V + "/openapi.json").json()
check("deprecated" in str(spec).split("agent_peers", 1)[1][:200], "#1373: the OpenAPI marks agent_peers deprecated")
r = A.put(B + "/api/folders/props", json={"folder": "Agents", "props": {"agent_peers": True, "agent_members": True}})
check(r.ok and r.json()["props"] == {"agent_members": True}, "#1373: a folder default agent_peers is accepted and ignored " + r.text[:160])
L3 = A.post(B + "/api/lists", json={"name": "In the agents folder", "folder": "Agents"}).json()["id"]
check(dbx("SELECT agent_peers, agent_members FROM lists WHERE id=?", (L3,))[0] == (0, 1), "#1373: a new list in the folder gets no agent_peers")
check(A.post(B + f"/api/lists/{L3}/folder-reset", json={"keys": ["agent_peers"]}).ok, "#1373: folder-reset with agent_peers: no error")

# ================================================================== #1422 the workspace sent along is not "differs from the folder"
check(Bo.put(B + "/api/folders/props", json={"folder": "Org", "props": {"org_id": ORG}}).ok, "#1422: setup: a folder with a workspace default")
SAME = Bo.post(B + "/api/lists", json={"name": "Same workspace", "folder": "Org", "org_id": ORG}).json()["id"]
OTHER = Bo.post(B + "/api/lists", json={"name": "Private one", "folder": "Org", "org_id": None}).json()["id"]
own = {x["id"]: x["own"] for x in Bo.get(B + "/api/folders/props", params={"folder": "Org"}).json()["lists"]}
check(own.get(SAME) == [], "#1422: the same workspace as the folder: not marked as differing " + str(own))
check(own.get(OTHER) == ["org_id"], "#1422: another workspace: marked " + str(own))
MV = Bo.post(B + "/api/lists", json={"name": "Mover", "org_id": ORG}).json()["id"]
check(Bo.patch(B + f"/api/lists/{MV}", json={"folder": "Org", "org_id": ORG}).ok, "#1422: moved in with the same workspace sent along")
own = {x["id"]: x["own"] for x in Bo.get(B + "/api/folders/props", params={"folder": "Org"}).json()["lists"]}
check(own.get(MV) == [], "#1422: moving: the same value is not marked either " + str(own))

# ================================================================== #1414 the folder's agent joins a new list in the folder
r = A.post(B + "/api/admin/agents", json={"scopes": SC, "username": "helper", "display_name": "Helper"})
HL = r.json()["id"]
check(A.put(B + "/api/folders/props", json={"folder": "Dev", "props": {"agent_id": HL}}).ok, "#1414: setup: the folder Dev with Helper")
for body in ({"name": "App", "folder": "Dev", "kind": "project", "ptype": "software"}, {"name": "Notes", "folder": "Dev"}):
    lid = A.post(B + "/api/lists", json=body).json()["id"]
    check(dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (lid, HL)) == [("edit",)], f"#1414: {body['name']}: Helper is a member at once")

print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
