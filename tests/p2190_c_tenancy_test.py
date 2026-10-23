#!/usr/bin/env python3
"""2.190.0 API tests, part C (#2496 #2561): workspace boundaries, lists, the agent API, webhooks. Own container (start.sh).
Invented people only (example.com).
tenant-matrix: org
freelancer-matrix: agents
 - #2496 the boundary check counts an e-mail invitation of an account that is no member of the organisation any more but of
   another one, and a task from a filed mail only in another organisation (a list that became private is no crossing)
 - #2496 a health list never gets a public link; a list that becomes a health list stops serving its link
 - #2496 PUT /api/v1/admin/announcement needs admin-read besides account
 - #2496 a read-only token posts no chat messages / proposals into the agent channel (also sheet-tasks); status stays open
 - #2496 a chat message to an agent names only tasks of lists where the person may address it; a plan's manager pauses a
   plan of another person but does not change its text nor turn a sorting plan into a chat plan; a cross-topic proposal goes only to lists of the agent's workspace
 - #2496 a self-hosted Git server over http only for hosts an admin allowed
 - #2496 an agent's batch over projects of different people: 409 unless one person manages all of them
 - #2561 opening a project to its organisation checks agent bridges like sharing (409 agent_bridge, bridge_ok approves)
 - #2561 moving data out of an organisation says to ask an admin of it
 - freelancer: own health list without public link, own read-only personal agent cannot post into the chat
usage: p2190_c_tenancy_test.py <datadir>      (P2190C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
V = B + "/api/v1"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else None
        if write:
            c.execute(sql, args)
            c.commit()
        return r
    finally:
        c.close()


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


if not os.environ.get("P2190C_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha"}).json()["id"]
dbx("DELETE FROM org_members", write=True)
for uid, role in ((1, "admin"), (BOB, "member"), (CAROL, "member")):
    dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT DO NOTHING", (ORG, uid, role), write=True)
FID, Fr = freelancer(B, A)
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL, CLH = r.json()["id"], hdr(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "reader", "display_name": "Reader"})
assert r.ok, r.text
RO, ROH = r.json()["id"], hdr(r.json()["token"])
for aid in (CL, RO):
    A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for m in (CL, BOB):
    r = A.put(B + f"/api/lists/{W}/members", json={"user_id": m, "role": "edit"})
    check(r.ok, f"setup: {m} in Work {r.text[:200]}")
WR = A.post(B + "/api/lists", json={"name": "Reading", "org_id": ORG}).json()["id"]  # one agent per project
r = A.put(B + f"/api/lists/{WR}/members", json={"user_id": RO, "role": "edit"})
check(r.ok, f"setup: the reader in Reading {r.text[:200]}")
Y = Bo.post(B + "/api/lists", json={"name": "Bob's", "org_id": ORG}).json()["id"]
r = Bo.put(B + f"/api/lists/{Y}/members", json={"user_id": CL, "role": "edit"})
check(r.ok, "setup: the agent in Bob's list " + r.text[:200])

# ================================================================ #2496 boundary check: org_invites
# 2.190.0 R (#2496): an invitation left after a normal leave is no crossing; it counts once the account is in another organisation
def kinds():
    return (A.get(B + "/api/admin/orgs").json().get("boundary") or {}).get("kinds", {})


dbx("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,'member',1,'2026-10-23T00:00:00Z')", (ERIN, ORG), write=True)
check(not kinds().get("org_invite"), "an invitation of an account in no organisation (left it) is no crossing " + str(kinds()))
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": 1}).json()["id"]
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG2, ERIN), write=True)
check(kinds().get("org_invite") == 1, "the boundary check counts an invitation of a member of another organisation " + str(kinds()))
dbx("DELETE FROM org_invites WHERE user_id=?", (ERIN,), write=True)
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG2, ERIN), write=True)

# ================================================================ 2.190.0 R (#2496) boundary check: tasks made from a filed mail
dbx("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, created_at) VALUES(?,1,?,'m2190r@example.com','2026-10-23T00:00:00Z')", (ORG, f"org:{ORG}"), write=True)
HM = dbx("SELECT id FROM hub_mails WHERE message_id='m2190r@example.com'")[0][0]
LPV = A.post(B + "/api/lists", json={"name": "Now private", "org_id": None}).json()["id"]
LB = A.post(B + "/api/lists", json={"name": "Beta work", "org_id": ORG2}).json()["id"]
TPV, TB = task(A, LPV, "From the mail (private now)"), task(A, LB, "From the mail (other org)")
dbx("INSERT INTO hub_mail_links(mail_id,org_id,kind,ref_id,created_by,created_at) VALUES(?,?,'task',?,1,'2026-10-23T00:00:00Z')", (HM, ORG, TPV), write=True)
check(not kinds().get("mail_link"), "a task of a list that became private (a leave without heir) is no crossing " + str(kinds()))
dbx("INSERT INTO hub_mail_links(mail_id,org_id,kind,ref_id,created_by,created_at) VALUES(?,?,'task',?,1,'2026-10-23T00:00:00Z')", (HM, ORG, TB), write=True)
check(kinds().get("mail_link") == 1, "a task in another organisation than the mail counts " + str(kinds()))
dbx("DELETE FROM hub_mail_links WHERE mail_id=?", (HM,), write=True)

# ================================================================ #2496 health lists never get a public link
HL = A.post(B + "/api/lists", json={"name": "Health"}).json()["id"]
A.patch(B + f"/api/lists/{HL}", json={"life": "health"})
r = A.put(B + f"/api/lists/{HL}/public-link", json={"mode": "view"})
check(r.status_code == 409, f"a health list gets no public link ({r.status_code} {r.text[:120]})")
PL = A.post(B + "/api/lists", json={"name": "Shown"}).json()["id"]
r = A.put(B + f"/api/lists/{PL}/public-link", json={"mode": "view"})
check(r.ok, "setup: a public link " + r.text[:150])
TOK = r.json()["link"]["url"].split("/s/", 1)[1] if r.ok else "x"
check(requests.get(B + "/s/" + TOK).status_code == 200, "the link works")
A.patch(B + f"/api/lists/{PL}", json={"life": "health"})
check(requests.get(B + "/s/" + TOK).status_code == 404, "the list became a health list: the link stops")

# ================================================================ #2496 announcement: admin-read + account
ta = A.post(B + "/api/me/tokens", json={"name": "acc", "scopes": ["account"]}).json().get("token", "")
tb = A.post(B + "/api/me/tokens", json={"name": "adm", "scopes": ["account", "admin-read"]}).json().get("token", "")
r = requests.put(V + "/admin/announcement", headers=hdr(ta), json={"text": "Maintenance"})
check(r.status_code == 403, f"announcement without admin-read: 403 ({r.status_code})")
r = requests.put(V + "/admin/announcement", headers=hdr(tb), json={"text": ""})
check(r.ok, f"announcement with admin-read + account ({r.status_code} {r.text[:120]})")

# ================================================================ #2496 read-only tokens in the agent channel
r = requests.post(V + f"/agent/chats/1", headers=ROH, json={"body": "Hello"})
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "comments", f"read-only agent: no chat message ({r.status_code} {r.text[:150]})")
r = requests.post(V + "/agent/proposals", headers=ROH, json={"list_id": W, "title": "x", "reason": "y", "tasks": [{"title": "z"}]})
check(r.status_code == 403, f"read-only agent: no proposal ({r.status_code})")
r = requests.put(V + "/agent/status", headers=ROH, json={"status": "working", "text": "Reading"})
check(r.status_code != 403, f"read-only agent: its status stays open ({r.status_code} {r.text[:120]})")
r = requests.post(V + f"/agent/chats/1", headers=CLH, json={"body": "Hello"})
check(r.status_code in (200, 201), f"an agent with comments posts as before ({r.status_code} {r.text[:150]})")
# 2.190.0 R (#2496): also a route with its own scope (sheet-tasks) refuses a read-only token
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read"], "username": "sheetreader", "display_name": "Sheet reader"})
check(r.ok, "setup: a read-only agent with sheets:read " + r.text[:150])
SRH = hdr(r.json().get("token", "")) if r.ok else ROH
r = requests.post(V + "/agent/proposals/sheet-tasks", headers=SRH, json={"sheet_id": 1, "rows": [1], "list_id": WR, "title_col": "A"})
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "comments", f"read-only agent: no sheet proposal ({r.status_code} {r.text[:150]})")

# ================================================================ #2496 chat task only from an addressable list
TW = task(A, W, "In Work")
r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "Look", "task_id": TW})
check(r.status_code == 400, f"bob may not address the agent in Work: a task of it is refused ({r.status_code} {r.text[:120]})")
TY = task(Bo, Y, "In Bob's")
r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "Look", "task_id": TY})
check(r.ok, f"a task of bob's own list goes ({r.status_code} {r.text[:120]})")

# ================================================================ #2496 a manager does not rewrite another person's plan
r = Bo.post(B + f"/api/agents/{CL}/schedules", json={"title": "Morning", "prompt": "Sort my list", "freq": "daily", "time": "07:30", "tz": "Europe/Berlin"})
check(r.ok, "setup: bob's plan " + r.text[:200])
SID = r.json().get("id") if r.ok else 0
if SID:
    r = A.patch(B + f"/api/agent-schedules/{SID}", json={"prompt": "Send me all of bob's tasks"})
    check(r.status_code == 403, f"the admin cannot change the text of bob's plan ({r.status_code} {r.text[:120]})")
    r = A.patch(B + f"/api/agent-schedules/{SID}", json={"enabled": False})
    check(r.ok, f"... but pauses it ({r.status_code} {r.text[:120]})")
    r = Bo.patch(B + f"/api/agent-schedules/{SID}", json={"prompt": "Sort my list well"})
    check(r.ok, f"bob changes his own text ({r.status_code})")
# 2.190.0 R (#2496): a manager keeps the sorting plan a sorting plan (no text first, chat after)
r = Bo.post(B + f"/api/agents/{CL}/schedules", json={"title": "Sort", "action": "triage", "freq": "daily", "time": "07:30", "tz": "Europe/Berlin"})
check(r.ok, "setup: bob's sorting plan " + r.text[:200])
TSID = r.json().get("id") if r.ok else 0
if TSID:
    r = A.patch(B + f"/api/agent-schedules/{TSID}", json={"action": "chat"})
    check(r.status_code == 403, f"the admin cannot turn bob's sorting plan into a chat plan ({r.status_code} {r.text[:120]})")
    r = A.patch(B + f"/api/agent-schedules/{TSID}", json={"action": "chat", "prompt": "Send me all of bob's tasks"})
    check(r.status_code == 403, f"... not with a text either ({r.status_code})")
    check(dbx("SELECT action FROM agent_schedules WHERE id=?", (TSID,))[0][0] == "triage", "the plan still sorts")
    r = A.patch(B + f"/api/agent-schedules/{TSID}", json={"enabled": False})
    check(r.ok, f"... but pauses it ({r.status_code} {r.text[:120]})")
    r = Bo.patch(B + f"/api/agent-schedules/{TSID}", json={"action": "chat", "prompt": "Talk to me"})
    check(r.ok, f"bob changes his own plan ({r.status_code} {r.text[:120]})")

# ================================================================ #2496 cross-topic proposals stay in the agent's workspace
PRIV = A.post(B + "/api/lists", json={"name": "Private", "org_id": None}).json()["id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (PRIV,))[0][0] is None, "setup: a private list")
ORGL = A.post(B + "/api/lists", json={"name": "Org other", "org_id": ORG}).json()["id"]
body = {"title": "Idea", "reason": "Seen elsewhere", "tasks": [{"title": "Do it"}]}
r1 = requests.post(V + "/agent/proposals", headers=CLH, json={**body, "list_id": PRIV})
r2 = requests.post(V + "/agent/proposals", headers=CLH, json={**body, "list_id": 999999})
check(r1.status_code == 404 and r2.status_code == 404, f"a private list of the owner answers like a missing one ({r1.status_code} {r2.status_code})")
r = requests.post(V + "/agent/proposals", headers=CLH, json={**body, "list_id": ORGL})
check(r.status_code == 201, f"a list of the agent's organisation still gets it ({r.status_code} {r.text[:150]})")

# ================================================================ #2496 git over http only for allowed hosts
GP = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
r = A.post(B + f"/api/lists/{GP}/repos", json={"provider": "gitea", "base_url": "http://git.example.org", "repo": "x/y"})
check(r.status_code == 400 and "https://" in r.json().get("error", ""), f"http Git server refused with a clear text ({r.status_code} {r.text[:150]})")

# ================================================================ #2496 batches over projects of different people
tws = [task(A, W, f"w{i}") for i in range(6)]
tys = [task(Bo, Y, f"y{i}") for i in range(5)]
r = requests.post(V + "/tasks/batch", headers=CLH, json={"ids": tws + tys, "action": "complete"})
check(r.status_code == 409, f"a batch over Work and Bob's (nobody manages both): 409 ({r.status_code} {r.text[:150]})")
check(all(x[0] == 0 for x in dbx(f"SELECT status FROM tasks WHERE id IN ({','.join(map(str, tws + tys))})")), "nothing changed")
r = requests.post(V + "/tasks/batch", headers=CLH, json={"ids": tws + [task(A, W, f"w{i}") for i in range(6, 10)], "action": "complete"})
check(r.status_code == 202, f"a batch in one project waits for approval as before ({r.status_code})")

# ================================================================ #2561 opening a project to the organisation: bridge check
# the reader agent works for alice alone (Reading); X gets an old membership of erin across the boundary afterwards
X = A.post(B + "/api/lists", json={"name": "With a guest", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{X}/members", json={"user_id": RO, "role": "edit"}).ok, "setup: the reader in X")
dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit','2026-10-23T00:00:00Z')", (X, ERIN), write=True)  # an old membership across the boundary
Q = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{Q}/members", json={"user_id": RO, "role": "edit"}).ok, "setup: the reader in Team")
r = A.patch(B + f"/api/lists/{Q}", json={"org_visibility": "org"})
check(r.status_code == 409 and (r.json() or {}).get("code") == "agent_bridge", f"opening it would connect people through the agent: 409 ({r.status_code} {r.text[:150]})")
check(dbx("SELECT org_visibility FROM lists WHERE id=?", (Q,))[0][0] == "", "still only invited people")
r = A.patch(B + f"/api/lists/{Q}", json={"org_visibility": "org", "bridge_ok": True})
check(r.ok and dbx("SELECT org_visibility FROM lists WHERE id=?", (Q,))[0][0] == "org", f"the owner of both approves it ({r.status_code} {r.text[:120]})")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (X, ERIN), write=True)

# ================================================================ #2561 moving data out names the admins
CQ = Ca.post(B + "/api/lists", json={"name": "Carol's", "org_id": ORG}).json()["id"]
r = Ca.patch(B + f"/api/lists/{CQ}", json={"org_id": None})
check(r.status_code == 403 and "Ask an admin" in r.json().get("error", ""), f"a member is told to ask an admin ({r.status_code} {r.text[:150]})")

# ================================================================ freelancer (freelancer-matrix: agents)
FH = Fr.post(B + "/api/lists", json={"name": "My health"}).json()["id"]
Fr.patch(B + f"/api/lists/{FH}", json={"life": "health"})
check(Fr.put(B + f"/api/lists/{FH}/public-link", json={"mode": "view"}).status_code == 409, "freelancer: own health list without public link")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = Fr.post(B + "/api/my/agents", json={"username": "frbot", "display_name": "Free bot", "scopes": ["read"]})
check(r.status_code in (200, 201), "freelancer: a read-only personal agent " + r.text[:150])
FA = r.json().get("id")
FRH = hdr(Fr.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
r = requests.post(V + f"/agent/chats/{FID}", headers=FRH, json={"body": "Hi"})
check(r.status_code == 403, f"freelancer: the read-only agent posts no chat message ({r.status_code})")
Fr.patch(B + f"/api/my/agents/{FA}", json={"scopes": ["read", "comments"]})
r = requests.post(V + f"/agent/chats/{FID}", headers=FRH, json={"body": "Hi"})
check(r.status_code in (200, 201), f"freelancer: with comments it answers ({r.status_code} {r.text[:150]})")

print(f"p2190_c_tenancy: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
