#!/usr/bin/env python3
"""2.37.0 API tests, part U: #1158 (folder settings of a folder with only lists of others) and #1159 (save a chat message as a
task), own container (start.sh). Invented people and texts only.
 - #1158: Alice keeps a subfolder that holds only a list Bob shared with her. PUT /api/folders/props for it, then GET returns the
   values; Bob's list keeps its settings (the tenant boundary: folder defaults never change lists of others); a new list Alice
   creates in the subfolder takes the defaults; an agent token may not set folder settings
 - #1159: see the second half (POST /api/chat-save)
usage: p2370_u_api_test.py <datadir>"""
import os
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


def state(s):
    return s.get(B + "/api/state").json()


def lists_of(s):
    return {l["id"]: l for l in state(s)["lists"]}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
ALICE = state(A)["me"]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

# ================================================================== #1158 folder of only lists of others
HP = A.post(B + "/api/lists", json={"name": "Homepage", "folder": "Studio"}).json()
MT = A.post(B + "/api/lists", json={"name": "Meeting", "folder": "Studio"}).json()
DM = Bo.post(B + "/api/lists", json={"name": "Shop DM"}).json()
check(Bo.put(B + f"/api/lists/{DM['id']}/members", json={"user_id": ALICE, "role": "edit"}).ok, "#1158: Bob shares his list with Alice")
r = A.post(B + "/api/lists/reorder", json={"folder": {str(DM["id"]): "Studio/Shopping"}})
check(r.ok and lists_of(A)[DM["id"]]["folder"] == "Studio/Shopping", "#1158: Alice keeps Bob's list in her subfolder " + r.text[:120])
dm0 = lists_of(Bo)[DM["id"]]
r = A.get(B + "/api/folders/props?folder=" + requests.utils.quote("Studio/Shopping"))
check(r.ok and r.json()["props"] == {} and r.json()["lists"] == [], "#1158: GET of a folder with only lists of others: no props, none of its lists counted as hers " + r.text[:200])
P = {"agent_members": True, "agent_peers": True, "agent_listen": False, "agent_tidy": "suggest"}
r = A.put(B + "/api/folders/props", json={"folder": "Studio/Shopping", "props": P, "dry_run": True})
check(r.ok and r.json().get("dry_run") and r.json()["lists"] == [] and A.get(B + "/api/folders/props?folder=Studio/Shopping").json()["props"] == {},
      "#1158: the dry run names no list and stores nothing " + r.text[:200])
r = A.put(B + "/api/folders/props", json={"folder": "Studio/Shopping", "props": P, "apply": "all"})
check(r.ok and r.json()["changed"] == 0, "#1158: PUT for the folder saves (nothing of others changed) " + r.text[:200])
g = A.get(B + "/api/folders/props?folder=Studio/Shopping").json()
check(g["props"] == P, "#1158: PUT then GET returns the values " + str(g["props"]))
dm1 = lists_of(Bo)[DM["id"]]
check(all(dm1.get(k) == dm0.get(k) for k in ("agent_members", "agent_peers", "agent_tidy", "agent_listen", "org_id")),
      "#1158: Bob's list keeps its own settings (tenant boundary) " + str({k: (dm0.get(k), dm1.get(k)) for k in ("agent_members", "agent_peers", "agent_tidy")}))
NL = A.post(B + "/api/lists", json={"name": "New one", "folder": "Studio/Shopping"}).json()
nl = lists_of(A)[NL["id"]]
check(nl.get("agent_members") == 1 and nl.get("agent_peers") == 1, "#1158: a new list of hers in the folder takes the defaults " + str({k: nl.get(k) for k in P}))
check(Bo.get(B + "/api/folders/props?folder=Studio/Shopping").json()["props"] == {}, "#1158: the folder settings are Alice's alone (Bob's folder of that name has none)")
r = requests.put(B + "/api/folders/props", headers={**AGH, **H}, json={"folder": "Studio/Shopping", "props": {"agent_members": False}})
check(r.status_code in (401, 403), "#1158: an agent cannot set folder settings " + str(r.status_code))
r = A.put(B + "/api/folders/props", json={"folder": "Studio/Shopping", "props": {"agent_members": None, "agent_peers": None, "agent_listen": None, "agent_tidy": None}, "apply": "new"})
check(r.ok and A.get(B + "/api/folders/props?folder=Studio/Shopping").json()["props"] == {}, "#1158: null removes the defaults again")

# ================================================================== #1159 save a chat message as a task
# another person's agent chat / a team room one is not in: 404; a list of another person: 404 / 403
# tenant-matrix: chatsave
import dbx as dbxm  # noqa: E402


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


W = A.post(B + "/api/lists", json={"name": "Work"}).json()
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": AG, "role": "edit"})
TEXT = "# Release plan 2.40\n\nWe ship **three** things:\n\n- search\n- export\n\n```bash\nmake release\n```"
r = requests.post(V + f"/agent/chats/{ALICE}", headers=AGH, data={"body": TEXT, "offer_save": "true"},
                  files={"file": ("plan-notes.txt", b"the plan in a file", "text/plain")})
check(r.status_code == 201 and r.json().get("offer_save") is True, "#1159: the agent sends a message with offer_save (multipart) " + r.text[:200])
AM = r.json()["id"]
r = requests.post(V + f"/agent/chats/{ALICE}", headers=AGH, json={"body": "short", "offer_save": "maybe"})
check(r.status_code == 400, "#1159: offer_save must be a boolean " + str(r.status_code))
r = requests.post(V + f"/agent/chats/{ALICE}", headers=AGH, json={"body": "plain answer"})
check(r.status_code == 201 and r.json().get("offer_save") is False, "#1159: without offer_save no button")
PLAIN = r.json()["id"]


def amsgs(s=A):
    return {m["id"]: m for m in s.get(B + f"/api/agents/{AG}/chat").json()["messages"]}


m = amsgs()[AM]
check(m["offer_save"] is True and m["saved_task_id"] is None and amsgs()[PLAIN]["offer_save"] is False, "#1159: the chat shows offer_save, not saved yet")
# the agent cannot save (no web route for tokens, no REST route at all)
r = requests.post(B + "/api/chat-save", headers={**AGH, **H}, json={"kind": "agent", "msg_id": AM})
check(r.status_code in (401, 403), "#1159: an agent token cannot save " + str(r.status_code))
r = requests.post(V + "/chat-save", headers=AGH, json={"kind": "agent", "msg_id": AM})
check(r.status_code in (404, 405), "#1159: there is no REST route for saving " + str(r.status_code))
n_att = dbx("SELECT COUNT(*) FROM attachments")[0][0]
# strangers: another person's agent message -> 404, nothing copied
r = Ca.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM})
check(r.status_code == 404 and dbx("SELECT COUNT(*) FROM attachments")[0][0] == n_att, "#1159: another person's agent message: 404, no file copied " + str(r.status_code))
check(A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": 999999}).status_code == 404, "#1159: unknown message 404")
check(A.post(B + "/api/chat-save", json={"kind": "mail", "msg_id": AM}).status_code == 400, "#1159: unknown kind 400")
check(A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM, "evil": 1}).status_code == 400, "#1159: unknown fields 400")
CL = Ca.post(B + "/api/lists", json={"name": "Carol private"}).json()
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM, "list_id": CL["id"]})
check(r.status_code == 404 and dbx("SELECT COUNT(*) FROM attachments")[0][0] == n_att, "#1159: a list of another person: 404 " + str(r.status_code))
BV = Bo.post(B + "/api/lists", json={"name": "Bob view"}).json()
Bo.put(B + f"/api/lists/{BV['id']}/members", json={"user_id": ALICE, "role": "view"})
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM, "list_id": BV["id"]})
check(r.status_code == 403, "#1159: a list without the right to change it: 403 " + str(r.status_code))
# saving: whole text, file copy, link back, due, the inbox by default
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM, "due": "2026-10-20"})
check(r.status_code == 201, "#1159: saved " + r.text[:200])
T1 = r.json().get("task", {})
inbox = [l for l in lists_of(A).values() if l.get("is_inbox")][0]
check(T1.get("title") == "Release plan 2.40" and T1.get("list_id") == inbox["id"] and T1.get("due") == "2026-10-20",
      "#1159: title from the heading, the inbox, the review date " + str({k: T1.get(k) for k in ("title", "list_id", "due")}))
check(T1.get("content", "").startswith(TEXT) and f"/#msg/a/{AG}/{AM})" in T1.get("content", ""), "#1159: the whole text + the link back " + T1.get("content", "")[-200:])
att = T1.get("attachments") or []
check(len(att) == 1 and att[0]["name"] == "plan-notes.txt", "#1159: the file comes along " + str(att))
if att:
    f = A.get(B + f"/api/attachments/{att[0]['id']}")
    check(f.ok and f.content == b"the plan in a file", "#1159: the file is a copy with the same content")
    ap = dbx("SELECT path FROM attachments WHERE id=?", (att[0]["id"],))[0][0]
    cp = dbx("SELECT f.path FROM chat_files f WHERE f.message_id=?", (AM,))[0][0]
    check(ap != cp and ap.startswith(str(T1["id"])), "#1159: copied (its own file), not linked " + ap)
check(amsgs()[AM]["saved_task_id"] == T1["id"], "#1159: the chat says saved (saved_task_id)")
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM})
check(r.status_code == 200 and r.json().get("already") and r.json().get("task_id") == T1["id"], "#1159: saving again: already saved, the same task " + r.text[:200])
check(dbx("SELECT COUNT(*) FROM tasks WHERE content LIKE ?", (f"%/#msg/a/{AG}/{AM})%",))[0][0] == 1, "#1159: no second task")
ev = requests.get(V + "/agent/chats", headers=AGH).json()
check(all("saved_task_id" not in x for x in ev.get("data", [])), "#1159: the agent does not see who saved what")
# a deleted task: the message can be saved again
A.delete(B + f"/api/tasks/{T1['id']}")
check(amsgs()[AM]["saved_task_id"] is None, "#1159: the task deleted -> not saved any more")
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": AM, "list_id": W["id"], "title": "Look at the plan"})
check(r.status_code == 201 and r.json()["task"]["id"] != T1["id"] and r.json()["task"]["title"] == "Look at the plan" and r.json()["task"]["list_id"] == W["id"],
      "#1159: saved again into another list with an own title " + r.text[:160])
check(amsgs()[AM]["saved_task_id"] == r.json()["task"]["id"], "#1159: the mark points to the new task")
# a message without heading: the first line, shortened
long = "A first line that is rather long " * 8
r = requests.post(V + f"/agent/chats/{ALICE}", headers=AGH, json={"body": long + "\nsecond line"})
r = A.post(B + "/api/chat-save", json={"kind": "agent", "msg_id": r.json()["id"]})
check(r.status_code == 201 and r.json()["task"]["title"].startswith("A first line") and len(r.json()["task"]["title"]) <= 120, "#1159: title = the first line, shortened")

# team chat: a list room of Alice + Bob; Carol is outside
TL = A.post(B + "/api/lists", json={"name": "Team list"}).json()
A.put(B + f"/api/lists/{TL['id']}/members", json={"user_id": BOB, "role": "edit"})
rooms = Bo.get(B + "/api/team").json()["rooms"]
RID = [x for x in rooms if x["kind"] == "list" and x.get("list_id") == TL["id"]][0]["id"]
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": f"Hello <@{ALICE}>, the **minutes** of today:\n\n- one\n- two"})
check(r.status_code in (200, 201), "#1159: Bob writes in the channel " + r.text[:120])
TM = r.json()["id"]
r = A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": TM, "list_id": TL["id"]})
check(r.status_code == 201, "#1159: Alice saves Bob's channel message (not her own) " + r.text[:160])
T2 = r.json()["task"]
check("Hello @Alice, the **minutes** of today:" in T2["content"] and f"/#msg/t/{RID}/{TM})" in T2["content"] and "<@" not in T2["content"],
      "#1159: team text with @names and the link back " + T2["content"][:200])
r = Bo.post(B + "/api/chat-save", json={"kind": "team", "msg_id": TM})
check(r.status_code == 201 and r.json()["task"]["id"] != T2["id"], "#1159: Bob saves the same message for himself (per person)")
tm = {m["id"]: m for m in A.get(B + f"/api/team/rooms/{RID}/messages").json()["messages"]}
tb = {m["id"]: m for m in Bo.get(B + f"/api/team/rooms/{RID}/messages").json()["messages"]}
check(tm[TM]["saved_task_id"] == T2["id"] and tb[TM]["saved_task_id"] == r.json()["task"]["id"], "#1159: each sees their own saved task")
check(A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": TM}).json().get("already"), "#1159: team: saving again = already saved")
r = Ca.post(B + "/api/chat-save", json={"kind": "team", "msg_id": TM})
check(r.status_code == 404, "#1159: a room one is not in: 404 " + str(r.status_code))
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "oops"})
Bo.delete(B + f"/api/team/messages/{r.json()['id']}")
check(A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": r.json()["id"]}).status_code == 404, "#1159: a deleted message cannot be saved")

print(f"p2370_u_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
