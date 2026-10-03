#!/usr/bin/env python3
"""2.7.2 API, own container (start.sh, isolated test database):
#414 the list type "checklist" is gone: kinds list | project, the display option done_at_bottom (web: checklist) on every
list, kind "checklist" + the boolean "checklist" as deprecated aliases (web, token API, OpenAPI), the migration of stored
checklist lists after a restart, templates keep the option, the sample's packing list;
#420 personal agents: the admin policy (off by default, limit per person, default limits), create / list / rename / pause /
token / delete by the owner, refused when off or over the limit, only the owner shares lists with it and chats with it,
others never find it, never admin, an admin pause the owner cannot undo, admins see the owner and delete it (lists go to
the owner);
#421 reactions on chat messages (web + token API for people and agents): toggle, 👍 / 👎 of the person on the agent's
message = approval + the event reaction with chat_message, reactions of agents never approve and send no event;
#422 delivered_at of chat messages (event poll, the agent reading its chats), the server clock in the chat answer;
2.7.1 leftovers: project files leave the disk when the sample is removed / an import is undone.
usage: p272_api_test.py <datadir>"""
import glob
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


def db(sql, args=()):  # the isolated test database (bind-mounted data dir)
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def tok_h(t):
    return {"Authorization": "Bearer " + t}


def restart():
    subprocess.run(["docker", "restart", CT], check=True, capture_output=True)
    for _ in range(80):
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise SystemExit("container did not come back")


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
ids = {}
for u in ("bob", "carl"):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carl")
ALL = "cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments"
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": ALL})

# ================================================================== #414 list kinds + done_at_bottom
l1 = A.post(B + "/api/lists", json={"name": "Groceries", "kind": "checklist"})
check(l1.ok and l1.json()["kind"] == "list" and l1.json()["checklist"] == 1, f"web: kind checklist -> list + option on: {l1.text[:200]}")
L1 = l1.json()["id"]
l2 = A.post(B + "/api/lists", json={"name": "Packing", "done_at_bottom": True}).json()
check(l2["kind"] == "list" and l2["checklist"] == 1, "web: done_at_bottom on create")
l3 = A.post(B + "/api/lists", json={"name": "Plain"}).json()
check(l3["kind"] == "list" and l3["checklist"] == 0, "web: a plain list has the option off")
check(A.post(B + "/api/lists", json={"name": "X", "kind": "board"}).status_code == 400, "web: an unknown kind is refused")
check(A.patch(B + f"/api/lists/{l3['id']}", json={"checklist": True}).ok, "web: PATCH the option on")
st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(st[l3["id"]]["checklist"] == 1 and st[l3["id"]]["kind"] == "list", "the option does not change the kind")
check(A.patch(B + f"/api/lists/{l3['id']}", json={"kind": "project"}).ok, "web: list -> project")
st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(st[l3["id"]]["kind"] == "project" and st[l3["id"]]["checklist"] == 1, "a project keeps the option")
check(A.patch(B + f"/api/lists/{l3['id']}", json={"kind": "checklist"}).ok, "web: PATCH kind checklist (alias)")
st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(st[l3["id"]]["kind"] == "list" and st[l3["id"]]["checklist"] == 1, "alias: plain list + option on")
check(A.patch(B + f"/api/lists/{l3['id']}", json={"done_at_bottom": False}).ok, "web: done_at_bottom off")
st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(st[l3["id"]]["checklist"] == 0, "option off")
# done items of a list with the option stay in /api/state (the reusable part), like before
t = A.post(B + "/api/tasks", json={"title": "Milk", "list_id": L1}).json()["id"]
A.post(B + f"/api/tasks/{t}/complete")
db("UPDATE tasks SET completed_at='2020-01-01T00:00:00+00:00' WHERE id=?", (t,))
check(any(x["id"] == t for x in A.get(B + "/api/state").json()["tasks"]), "an old done item of a list with the option stays visible")
# token API
TA = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
v = requests.post(V + "/lists", headers=tok_h(TA), json={"name": "V1 list", "done_at_bottom": True}).json()
check(v.get("kind") == "list" and v.get("done_at_bottom") is True and v.get("checklist") is True, f"v1: done_at_bottom + alias field: {v}")
v2 = requests.post(V + "/lists", headers=tok_h(TA), json={"name": "V1 alias", "kind": "checklist"}).json()
check(v2.get("kind") == "list" and v2.get("done_at_bottom") is True, f"v1: kind checklist is a deprecated alias: {v2}")
v3 = requests.patch(V + f"/lists/{v2['id']}", headers=tok_h(TA), json={"done_at_bottom": False})
check(v3.ok and v3.json()["done_at_bottom"] is False, f"v1: PATCH done_at_bottom: {v3.text[:200]}")
check(requests.patch(V + f"/lists/{v2['id']}", headers=tok_h(TA), json={"done_at_bottom": "yes"}).status_code == 400, "v1: done_at_bottom must be a boolean")
check(requests.patch(V + f"/lists/{v2['id']}", headers=tok_h(TA), json={"checklist": True}).json()["done_at_bottom"] is True, "v1: PATCH checklist (alias)")
oa = requests.get(B + "/api/v1/openapi.json").json()
ls = oa["components"]["schemas"]["List"]["properties"]
check(ls["kind"]["enum"] == ["list", "project"] and "done_at_bottom" in ls and ls["checklist"].get("deprecated") is True, "OpenAPI: kinds, done_at_bottom, checklist deprecated")
check("checklist" in oa["components"]["schemas"]["ListPatch"]["properties"]["kind"]["enum"], "OpenAPI: the alias is documented on input")
# templates keep the option
tp = A.post(B + "/api/templates", json={"kind": "list", "list_id": L1, "name": "Weekly shop"})
check(tp.ok, f"template from a list with the option: {tp.status_code} {tp.text[:200]}")
if tp.ok:
    ap = A.post(B + f"/api/templates/{tp.json()['id']}/apply", json={"name": "Shop 2"})
    nl = ap.json().get("list_id") if ap.ok else None
    st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
    check(nl and st[nl]["kind"] == "list" and st[nl]["checklist"] == 1, f"the template's list has the option: {ap.text[:200]}")
# migration of stored checklists (as 2.7.0 left them)
db("UPDATE lists SET kind='checklist', checklist=1 WHERE id=?", (L1,))
db("UPDATE settings SET value='0' WHERE key='migr_kind272'")
restart()
A, Bo, Ca = sess("alice"), sess("bob"), sess("carl")
st = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(st[L1]["kind"] == "list" and st[L1]["checklist"] == 1, f"migration: checklist -> list + option ({st[L1]['kind']}, {st[L1]['checklist']})")
check(any(x["id"] == t for x in A.get(B + "/api/state").json()["tasks"]), "migration: nothing lost")
check(db("SELECT COUNT(*) FROM lists WHERE kind='checklist'")[0][0] == 0, "no list of kind checklist left")
# the sample: its packing list is a plain list with the option
sm = A.post(B + "/api/sample").json()
st = A.get(B + "/api/state").json()["lists"]
pk = [x for x in st if "packing" in x["name"].lower()]
check(pk and pk[0]["kind"] == "list" and pk[0]["checklist"] == 1, f"sample: packing list with the option: {[(x['name'], x['kind'], x['checklist']) for x in pk]}")

# ================================================================== 2.7.1 leftover: project files on disk
SP = next(x for x in st if x["kind"] == "project" and "Example" in x["name"])
check(A.post(B + f"/api/lists/{SP['id']}/files", files={"file": ("plan.pdf", b"%PDF-1.4 plan", "application/pdf")}).ok, "a project file on the sample")
pdir = os.path.join(DATA, "attachments", "lists", str(SP["id"]))
before = glob.glob(os.path.join(DATA, "**", "lists", str(SP["id"]), "*"), recursive=True)
check(before, f"the file is on disk ({pdir})")
check(A.delete(B + "/api/sample").ok, "remove the sample")
after = [p for p in before if os.path.exists(p)]
check(not after, f"its project files left the disk: {after}")
# import undo: a list from an import gets a project file, undo removes the list and the file
imp = A.post(B + "/api/import/todoist", files={"file": ("Imp undo.csv", b"TYPE,CONTENT,INDENT\ntask,Buy stamps,1\n")})
check(imp.ok and imp.json().get("import_id"), f"an import: {imp.status_code} {imp.text[:150]}")
lid = next((x["id"] for x in A.get(B + "/api/state").json()["lists"] if x["name"] == "Imp undo"), None)
check(lid, "the imported list")
if lid and imp.ok:
    A.patch(B + f"/api/lists/{lid}", json={"kind": "project"})
    A.post(B + f"/api/lists/{lid}/files", files={"file": ("brief.pdf", b"%PDF-1.4 x", "application/pdf")})
    fb = glob.glob(os.path.join(DATA, "**", "lists", str(lid), "*"), recursive=True)
    u = A.post(B + f"/api/imports/{imp.json()['import_id']}/undo")
    check(u.ok and u.json()["lists"] == 1 and fb and not [p for p in fb if os.path.exists(p)], f"import undo: list + project files gone ({u.text[:150]}, {fb})")

# ================================================================== #420 personal agents
j = Bo.get(B + "/api/my/agents").json()
check(j["allowed"] is False and j["agents"] == [], "off by default")
check(Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "bobbot"}).status_code == 403, "refused while off")
check(Bo.get(B + "/api/admin/agent-policy").status_code == 403 and Bo.put(B + "/api/admin/agent-policy", json={"user_agents": True}).status_code == 403, "only admins set the policy")
p = A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 1, "limits": {"period": "day", "metric": "tokens", "hard": 50000}})
check(p.ok and p.json()["user_agents"] and p.json()["max_per_user"] == 1, f"admin allows personal agents: {p.text[:200]}")
check(A.put(B + "/api/admin/agent-policy", json={"max_per_user": 0}).status_code == 400 and A.put(B + "/api/admin/agent-policy", json={"max_per_user": 21}).status_code == 400, "limit 1..20")
r = Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "bobbot", "display_name": "Bob's bot", "note": "home"})
check(r.status_code == 201 and r.json()["token"].startswith("abk_") and r.json()["owner"]["id"] == ids["bob"], f"Bob creates his agent: {r.text[:200]}")
BB = r.json()["id"]
TB = r.json()["token"]
check(r.json()["limits"] and r.json()["limits"].get("hard") == 50000, "the default limits apply to it")
check(Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "bobbot2"}).status_code == 409, "over the limit: 409")
check(Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "alice"}).status_code in (409, 400), "taken username")
u = db("SELECT is_admin, kind, paperless_access FROM users WHERE id=?", (BB,))[0]
check(u == (0, "agent", 0), f"never admin, no Paperless: {u}")
check(requests.get(V + "/agent", headers=tok_h(TB)).ok, "its token works")
check(requests.post(V + "/lists", headers=tok_h(TB), json={"name": "Own"}).ok, "it may create a list of its own")
check(requests.get(B + "/api/my/agents", headers=tok_h(TB)).status_code in (401, 403), "an agent cannot manage personal agents")
check(A.patch(B + f"/api/users/{BB}", json={"is_admin": True}).status_code == 400, "an admin cannot make it an admin")
# sharing: only Bob
BL = Bo.post(B + "/api/lists", json={"name": "Bob home"}).json()["id"]
AL = A.post(B + "/api/lists", json={"name": "Alice work"}).json()["id"]
check(A.put(B + f"/api/lists/{AL}/members", json={"user_id": BB, "role": "edit"}).status_code == 404, "others cannot share with Bob's agent")
check(Ca.get(B + "/api/users").ok and BB not in [x["id"] for x in Ca.get(B + "/api/users").json()["users"]], "others never find it")
check(BB in [x["id"] for x in Bo.get(B + "/api/users").json()["users"]], "Bob finds it")
check(A.get(B + f"/api/agents/{BB}/share").status_code == 404 and A.post(B + f"/api/agents/{BB}/share-all").status_code == 404, "no bulk sharing by others")
check(Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": BB, "role": "edit"}).ok, "Bob shares his list")
check(Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": BB, "role": "admin"}).status_code == 400, "never a list admin")
seen = [x["id"] for x in requests.get(V + "/lists", headers=tok_h(TB)).json()["data"]]
check(BL in seen and AL not in seen, f"it sees only what Bob shared: {seen}")
# chat only with the owner; not in other people's agent lists
check(BB in [x["id"] for x in Bo.get(B + "/api/agents").json()["agents"]], "Bob sees his agent")
check(BB not in [x["id"] for x in A.get(B + "/api/agents").json()["agents"]], "the admin's header does not list Bob's agent")
check(A.post(B + f"/api/agents/{BB}/chat", json={"body": "hi"}).status_code == 404, "others cannot chat with it")
check(requests.post(V + f"/agent/chats/{ids['carl']}", headers=tok_h(TB), json={"body": "hi"}).status_code == 404, "it cannot write to others")
# owner manages it
check(Bo.patch(B + f"/api/my/agents/{BB}", json={"display_name": "Bobby"}).json()["name"] == "Bobby", "rename")
check(Ca.patch(B + f"/api/my/agents/{BB}", json={"enabled": False}).status_code == 404, "others cannot manage it")
check(Bo.patch(B + f"/api/my/agents/{BB}", json={"is_admin": True}).status_code == 400, "no other fields")
check(Bo.patch(B + f"/api/my/agents/{BB}", json={"enabled": False}).json()["enabled"] is False, "the owner pauses it")
check(requests.get(V + "/agent", headers=tok_h(TB)).status_code in (401, 403), "paused: token refused")
check(Bo.patch(B + f"/api/my/agents/{BB}", json={"enabled": True}).json()["enabled"] is True, "the owner resumes it")
nt = Bo.post(B + f"/api/my/agents/{BB}/token").json()["token"]
check(requests.get(V + "/agent", headers=tok_h(TB)).status_code == 401 and requests.get(V + "/agent", headers=tok_h(nt)).ok, "a new token, the old one stops")
TB = nt
# admins see it with its owner, pause it (the owner cannot resume), delete it
ad = next(x for x in A.get(B + "/api/admin/agents").json()["agents"] if x["id"] == BB)
check(ad["owner"]["name"] == "Bob", "admins see the owner")
check(A.patch(B + f"/api/admin/agents/{BB}", json={"enabled": False}).ok, "admin pauses it")
check(Bo.patch(B + f"/api/my/agents/{BB}", json={"enabled": True}).status_code == 403, "the owner cannot resume an admin pause")
check(next(x for x in Bo.get(B + "/api/my/agents").json()["agents"] if x["id"] == BB)["admin_paused"] is True, "the owner sees why")
check(A.patch(B + f"/api/admin/agents/{BB}", json={"enabled": True}).ok, "admin resumes it")

# ================================================================== #421 #422 chat: delivery + reactions
mid = Bo.post(B + f"/api/agents/{BB}/chat", json={"body": "Shall I buy oat milk?"}).json()["id"]
c0 = Bo.get(B + f"/api/agents/{BB}/chat").json()
check(c0["messages"][-1]["delivered_at"] is None and c0.get("now"), "sent, not delivered yet; server clock in the answer")
cur = requests.get(V + "/agent", headers=tok_h(TB)).json()["cursor"]
evs = requests.get(V + "/agent/events", headers=tok_h(TB), params={"since": 0}).json()["data"]
check(any(e["event"] == "chat" and e["data"]["message"]["id"] == mid for e in evs), "the agent gets the chat event")
c1 = Bo.get(B + f"/api/agents/{BB}/chat").json()["messages"]
check(next(m for m in c1 if m["id"] == mid)["delivered_at"], "delivered once the agent fetched its events")
mid2 = Bo.post(B + f"/api/agents/{BB}/chat", json={"body": "second"}).json()["id"]
ch = requests.get(V + "/agent/chats", headers=tok_h(TB), params={"since": mid}).json()["data"]
check(ch and ch[0]["id"] == mid2 and ch[0]["delivered_at"], "reading its chats delivers too")
seq = max(e["seq"] for e in evs)
am = requests.post(V + f"/agent/chats/{ids['bob']}", headers=tok_h(TB), json={"body": "Should I add it to the list?"}).json()
check(am["from"] == "agent" and am["delivered_at"] is None and am["reactions"] == [], "the agent answers")
r = Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["approval"] == "approved" and r.json()["reactions"][0]["emoji"] == "up", f"Bob's 👍 = approval: {r.text[:200]}")
ev = [e for e in requests.get(V + "/agent/events", headers=tok_h(TB), params={"since": seq}).json()["data"] if e["event"] == "reaction"]
check(ev and ev[-1]["data"]["approval"] == "approved" and ev[-1]["data"]["chat_message"]["id"] == am["id"]
      and ev[-1]["data"]["reaction"]["emoji"] == "up" and ev[-1]["data"]["reaction"]["user"]["id"] == ids["bob"], f"reaction event with chat_message: {ev[-1:] }")
seq = max([seq] + [e["seq"] for e in ev])
r = Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"] == [] and r.json()["approval"] is None, "toggle off")
r = Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "👎"})
check(r.json()["approval"] == "rejected", "👎 = rejected")
r = Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "heart"})
check(r.ok and r.json()["approval"] is None, "❤️ is no approval")
check(Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "not an emoji"}).status_code == 400, "one emoji only")
check(Bo.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "up", "on": "x"}).status_code == 400, "on must be a boolean")
check(Ca.post(B + f"/api/agents/{BB}/chat/{am['id']}/reactions", json={"emoji": "up"}).status_code == 404, "others cannot react")
# Bob reacting on his own message: no event, no approval
n0 = len(requests.get(V + "/agent/events", headers=tok_h(TB), params={"since": seq}).json()["data"])
r = Bo.post(B + f"/api/agents/{BB}/chat/{mid}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["approval"] is None, "a reaction on my own message is no approval")
# the agent reacts: stored, never an approval, no event
r = requests.post(V + f"/agent/chats/{ids['bob']}/messages/{mid}/reactions", headers=tok_h(TB), json={"emoji": "up"})
check(r.ok and r.json()["approval"] is None and any(u["id"] == BB for x in r.json()["reactions"] for u in x["users"]), f"the agent reacts: {r.text[:200]}")
check(requests.post(V + f"/agent/chats/{ids['bob']}/messages/{mid}/reactions", headers=tok_h(TB), json={"emoji": "up", "x": 1}).status_code == 400, "v1: unknown field")
check(requests.post(V + f"/agent/chats/{ids['carl']}/messages/{mid}/reactions", headers=tok_h(TB), json={"emoji": "up"}).status_code == 404, "v1: only its own conversations")
n1 = len(requests.get(V + "/agent/events", headers=tok_h(TB), params={"since": seq}).json()["data"])
check(n1 == n0, "no event for own reactions / reactions on Bob's message")
msgs = Bo.get(B + f"/api/agents/{BB}/chat").json()["messages"]
check(any(x["emoji"] == "up" for x in next(m for m in msgs if m["id"] == mid)["reactions"]), "reactions in the chat answer")
# a person's token
TBo = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
r = requests.post(V + f"/agents/{BB}/chat/{am['id']}/reactions", headers=tok_h(TBo), json={"emoji": "up"})
check(r.ok and r.json()["approval"] == "approved", f"v1 person token: 👍 = approval: {r.text[:200]}")
check(requests.post(V + f"/agents/{BB}/chat/{am['id']}/reactions", headers=tok_h(TB), json={"emoji": "up"}).status_code == 403, "v1: agents use their own route")
pp = oa["paths"]
check("/agents/{id}/chat/{mid}/reactions" in pp and "/agent/chats/{id}/messages/{mid}/reactions" in pp, "OpenAPI: both reaction routes")
check("delivered_at" in oa["components"]["schemas"]["ChatMessage"]["properties"], "OpenAPI: delivered_at")

# delete: lists go to Bob
OWN = next(x["id"] for x in requests.get(V + "/lists", headers=tok_h(TB)).json()["data"] if x["name"] == "Own")
check(Ca.delete(B + f"/api/my/agents/{BB}").status_code == 404, "others cannot delete it")
check(Bo.delete(B + f"/api/my/agents/{BB}").ok, "Bob deletes his agent")
check(not db("SELECT 1 FROM users WHERE id=?", (BB,)), "gone")
check(db("SELECT owner_id FROM lists WHERE id=?", (OWN,))[0][0] == ids["bob"], "its list went to Bob")
check(requests.get(V + "/agent", headers=tok_h(TB)).status_code == 401, "its token is gone")
# admin deletes a personal agent: lists to its owner
r = Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "bobbot3"})
check(r.status_code == 201, "a new one fits the limit again")
B3, T3 = r.json()["id"], r.json()["token"]
OWN3 = requests.post(V + "/lists", headers=tok_h(T3), json={"name": "Own 3"}).json()["id"]
check(Bo.delete(B + f"/api/admin/agents/{B3}").status_code == 403, "only admins use the admin route")
check(A.delete(B + f"/api/admin/agents/{B3}").ok, "admin deletes it")
check(db("SELECT owner_id FROM lists WHERE id=?", (OWN3,))[0][0] == ids["bob"], "its list went to the owner")
# switched off again: no new ones, existing ones stay
A.put(B + "/api/admin/agent-policy", json={"user_agents": False})
check(Bo.post(B + "/api/my/agents", json={"scopes": ["write"], "username": "late"}).status_code == 403, "off again: refused")

print(f"p272_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
