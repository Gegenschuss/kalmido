#!/usr/bin/env python3
"""2.399.0 (#2687): hosted, the operator is no admin over its clients' organisations -- the guard test. Own container (start.sh,
a server key; first self-hosted, then restarted with KEEP=1 and KALMIDO_HOSTED=1, same data). Invented accounts only
(example.com). Every instance-admin way into an organisation the operator does not administer, or into a client's account,
answers 403 on the hosted instance and changes nothing; the same calls work self-hosted (unchanged). Locking, quotas, its own
organisation and its own agents stay with the operator; the clients' own admins keep managing their organisation; a person
without an organisation keeps everything (creates her own company on the hosted instance).
freelancer-matrix: own, orgadmin
usage: p2399_hosting_apart_test.py <datadir>"""
import json
import os
import subprocess
import sys

import kt
from kt import B, CT, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login, org_join  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)


def dbw(q, a=()):
    """A write in the suite's database (committed)."""
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(q, a)
        c.commit()
    finally:
        c.close()


def py(code):
    """Runs code in a second process of the container (role web, no loops); the last output line = JSON."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", "-e", "KALMIDO_ROLE=web", CT, "python", "-c",
                        "import app\n" + code], capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print((r.stdout + r.stderr)[-2000:], flush=True)
        return {}


LINK = """
import json
from kalmido.accounts.oidc import oidc_link_ok
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    u = c.execute("SELECT * FROM users WHERE id=?", (%d,)).fetchone()
    print(json.dumps({"email": oidc_link_ok(c, u, "email", u["email"], None), "own": oidc_link_ok(c, u, "email", u["email"], u["id"])}))
"""

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY})
A = kt.sess(None)
assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "cara", "pia", "paul"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "orgs": [{"id": ALPHA, "role": "member"}] if u == "bob" else []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
FID, Fr = freelancer(B, A)
S = {u: login(B, u) for u in ("bob", "carl", "cara", "pia", "paul")}
for s in S.values():
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok

# a client: carl creates his company himself, cara joins by his invitation
r = S["carl"].post(B + "/api/orgs", json={"name": "Client Studio"})
assert r.status_code == 201, r.text
CO = r.json()["id"]
assert S["carl"].put(B + f"/api/orgs/{CO}/members", json={"email": "cara@example.com"}).ok
assert org_join(B, "cara", CO)
CL = S["cara"].post(B + "/api/lists", json={"name": "Client plans", "org_id": CO}).json()["id"]
CT_ = S["cara"].post(B + "/api/tasks", json={"title": "Secret launch", "list_id": CL}).json()["id"]
dbw("INSERT INTO attachments(task_id,name,size,path,created_at) VALUES(?,'secret-plan.pdf',5,'nowhere-2399','2030-01-01T00:00:00Z')", (CT_,))
PL = S["pia"].post(B + "/api/lists", json={"name": "Pia private", "org_id": None}).json()["id"]
QL = S["paul"].post(B + "/api/lists", json={"name": "Paul private", "org_id": None}).json()["id"]
r = A.post(B + "/api/admin/agents", json={"username": "cbot", "display_name": "Client bot", "org_id": CO, "scopes": ["read"]})
assert r.status_code == 201, r.text
CBOT = r.json()["id"]
r = A.post(B + "/api/admin/agents", json={"username": "abot", "display_name": "Operator bot", "scopes": ["read"]})
assert r.status_code == 201, r.text
ABOT = r.json()["id"]


def members(o):
    return kt.dbx("SELECT user_id, role FROM org_members WHERE org_id=? ORDER BY user_id", (o,))


# ================================================================ self-hosted: the instance admin reaches in (unchanged)
r = A.patch(B + f"/api/admin/orgs/{CO}", json={"name": "Client Studio GmbH"})
check(r.ok and kt.dbx("SELECT name FROM orgs WHERE id=?", (CO,)) == [("Client Studio GmbH",)],
      "self-hosted: the instance admin renames an organisation it is not in (as before) " + r.text[:120])
r = A.post(B + f"/api/users/{FID}/signin-link")
check(r.ok and r.json().get("link"), "self-hosted: a sign-in link for a person without an organisation (as before) " + r.text[:120])
r = A.get(B + "/api/admin/storage-check")
check(r.ok and any(p.get("name") == "secret-plan.pdf" for p in r.json()["problems"]), "self-hosted: the storage check names the file (as before)")
assert A.patch(B + f"/api/users/{uid['paul']}", json={"disabled": True}).ok
r = A.post(B + f"/api/lists/{QL}/owner", json={"user_id": 1})
check(r.ok and kt.dbx("SELECT owner_id FROM lists WHERE id=?", (QL,)) == [(1,)], "self-hosted: the admin takes over a disabled person's project (as before) " + r.text[:120])
org = {o["id"]: o for o in A.get(B + "/api/admin/orgs").json()["orgs"]}
check(org[CO]["members"] and not org[CO].get("apart"), "self-hosted: the organisation list shows the members (as before)")
q = py(LINK % uid["cara"])
check(q.get("email") is True, f"self-hosted: a sign-on links an account by its verified e-mail (as before) {q}")

# ================================================================ hosted (KEEP=1)
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"}, keep=True)
A = sess("alice")
before = members(CO)

# ---- the client's organisation
for body in ({"name": "Taken over"}, {"members_add": [1]}, {"members_add": [uid["pia"]]}, {"admins_add": [uid["cara"]]},
             {"members_remove": [uid["cara"]]}, {"domains": "client.example"}, {"members": [uid["carl"]], "admins": [uid["carl"]]}):
    r = A.patch(B + f"/api/admin/orgs/{CO}", json=body)
    check(r.status_code == 403, f"hosted: PATCH /api/admin/orgs/<client> {list(body)} -> 403 " + r.text[:100])
check(members(CO) == before and kt.dbx("SELECT name, domains FROM orgs WHERE id=?", (CO,)) == [("Client Studio GmbH", "")]
      and not kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id IN (1, ?)", (CO, uid["pia"])),
      "hosted: the client's organisation is unchanged, nobody invited")
r = A.post(B + "/api/admin/orgs", json={"name": "For carl", "admin_id": uid["carl"]})
check(r.status_code == 403 and not kt.dbx("SELECT 1 FROM orgs WHERE name='For carl'"), "hosted: no organisation created for a client " + r.text[:100])
r = A.post(B + "/api/admin/orgs", json={"name": "Operator team"})
check(r.status_code == 201, "hosted: the operator creates an organisation of its own " + r.text[:100])
r = A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"name": "Alpha Ops"})
check(r.ok, "hosted: the operator's own organisation stays editable " + r.text[:100])
org = {o["id"]: o for o in A.get(B + "/api/admin/orgs").json()["orgs"]}
check(org[CO].get("apart") is True and org[CO]["members"] == [] and org[CO]["admins"] == [] and org[CO]["people"] == 2,
      f"hosted: the list shows a client's organisation without its people (a number only) {org[CO]}")
check(not org[ALPHA].get("apart") and 1 in org[ALPHA]["members"], "hosted: the own organisation with its members")
r = A.post(B + "/api/users", json={"username": "newbie", "password": "password123", "orgs": [{"id": CO, "role": "admin"}]})
check(r.status_code == 403 and not kt.dbx("SELECT 1 FROM users WHERE username='newbie'"), "hosted: no new account into a client's organisation " + r.text[:100])
r = A.post(B + "/api/users", json={"username": "opsmate", "password": "password123", "orgs": [{"id": ALPHA, "role": "member"}]})
check(r.ok, "hosted: a new account into the own organisation " + r.text[:100])
check(A.delete(B + f"/api/orgs/{CO}/members/{uid['cara']}").status_code in (403, 404) and members(CO) == before,
      "hosted: the members route of the client's organisation stays its admins'")

# ---- the client's accounts (cara: member of the client, frida: no organisation)
for who in (uid["cara"], FID, uid["carl"]):
    for body in ({"orgs": []}, {"orgs": [ALPHA]}, {"email": "taken@example.com"}, {"password": "taken-over-1"}, {"display_name": "X"},
                 {"proxy_login": "x"}, {"ntfy_topic": "stolen-topic"}, {"reset_2fa": True}, {"kind": "agent"}):
        if who == uid["cara"] or "orgs" in body or "password" in body or "email" in body:
            r = A.patch(B + f"/api/users/{who}", json=body)
            check(r.status_code in (403, 404), f"hosted: PATCH /api/users/<client {who}> {list(body)} -> refused " + r.text[:100])
check(kt.dbx("SELECT email FROM users WHERE id IN (?,?,?) ORDER BY id", (uid["carl"], uid["cara"], FID))
      == [("carl@example.com",), ("cara@example.com",), ("frida@example.com",)]
      and not kt.dbx("SELECT 1 FROM org_joins WHERE user_id IN (?,?) AND org_id=?", (uid["cara"], FID, ALPHA)),
      "hosted: the clients' accounts are unchanged")
check(login(B, "cara").get(B + "/api/state").ok and login(B, "frida").get(B + "/api/state").ok, "hosted: the clients sign in with their own passwords")
for who in (uid["cara"], FID):
    r = A.post(B + f"/api/users/{who}/signin-link")
    check(r.status_code in (403, 404) and "link" not in r.text, f"hosted: no sign-in link for a client ({who}) " + r.text[:100])
    r = A.post(B + f"/api/users/{who}/invite", json={"send": False})
    check(r.status_code in (403, 404) and "link" not in r.text, f"hosted: no password link for a client ({who}) " + r.text[:100])
r = A.patch(B + f"/api/users/{FID}", json={"disabled": True})
check(r.ok, "hosted: the operator locks a client's account " + r.text[:100])
r = A.patch(B + f"/api/users/{FID}", json={"disabled": False, "storage_quota_mb": 500})
check(r.ok and kt.dbx("SELECT disabled, storage_quota_mb FROM users WHERE id=?", (FID,)) == [(0, 500)],
      "hosted: ... unlocks it and sets its quota " + r.text[:100])
users = {u["id"]: u for u in A.get(B + "/api/users?all=1").json()["users"]}
check(users[uid["cara"]].get("apart") is True and users[FID].get("apart") is True and not users[uid["bob"]].get("apart")
      and not users[1].get("apart"), "hosted: the account list marks the clients' accounts (lock / quota only)")
r = A.patch(B + f"/api/users/{uid['bob']}", json={"display_name": "Bobby"})
check(r.ok, "hosted: a member of the operator's own organisation stays editable " + r.text[:100])

# ---- the client's agents
for meth, path, body in (("post", f"/api/admin/agents/{CBOT}/token", {}), ("patch", f"/api/admin/agents/{CBOT}", {"display_name": "Mine"}),
                         ("patch", f"/api/admin/agents/{CBOT}", {"org_id": None}), ("post", f"/api/admin/agents/{CBOT}/setup-code", {}),
                         ("delete", f"/api/admin/agents/{CBOT}", None), ("get", f"/api/admin/agents/{CBOT}/audit", None)):
    r = getattr(A, meth)(B + path, **({"json": body} if body is not None else {}))
    # the audit route reads the agent without the system context: a client's organisation is invisible there already (404)
    check(r.status_code == 403 or (meth == "get" and r.status_code == 404), f"hosted: {meth.upper()} {path} -> refused " + r.text[:100])
check(kt.dbx("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (CBOT,))[0][0] >= 1
      and kt.dbx("SELECT display_name FROM users WHERE id=?", (CBOT,)) == [("Client bot",)], "hosted: the client's agent is unchanged")
r = A.patch(B + f"/api/admin/agents/{CBOT}", json={"enabled": False})
check(r.ok, "hosted: the operator pauses a client's agent (the kill switch) " + r.text[:100])
A.patch(B + f"/api/admin/agents/{CBOT}", json={"enabled": True})
r = A.post(B + "/api/admin/agents", json={"username": "intruder", "org_id": CO})
check(r.status_code == 403 and not kt.dbx("SELECT 1 FROM users WHERE username='intruder'"), "hosted: no agent in a client's organisation " + r.text[:100])
r = A.post(B + "/api/admin/agents", json={"username": "forcarl", "owner_id": uid["carl"]})
check(r.status_code == 403, "hosted: no personal agent for a client " + r.text[:100])
r = A.patch(B + f"/api/admin/agents/{ABOT}", json={"display_name": "Ops bot"})
check(r.ok, "hosted: the operator's own agent stays editable " + r.text[:100])
check(A.patch(B + f"/api/admin/agents/{ABOT}", json={"org_id": CO}).status_code == 403
      and kt.dbx("SELECT org_id FROM agents WHERE user_id=?", (ABOT,)) != [(CO,)], "hosted: the own agent does not move into a client's organisation")
r = A.patch(B + f"/api/admin/agents/{ABOT}", json={"org_id": "auto"})  # review F2: "auto" never resolves to a client's organisation
check(kt.dbx("SELECT org_id FROM agents WHERE user_id=?", (ABOT,)) != [(CO,)] and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (CO, ABOT)),
      "hosted: org_id auto does not put the own agent into a client's organisation " + r.text[:100])
r = A.post(B + "/api/admin/agents", json={"username": "autobot", "org_id": "auto"})
check(not kt.dbx("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE u.username='autobot' AND m.org_id=?", (CO,)),
      "hosted: a new agent with org_id auto does not land in a client's organisation " + r.text[:100])
q = py(LINK % uid["cara"])  # review F1: the operator sets the sign-on provider; a first link only from the account's own session
check(q.get("email") is False and q.get("own") is True, f"hosted: a sign-on links a client's account only from its own session {q}")
names = {a["id"] for a in A.get(B + "/api/admin/agents/audit").json()["agents"]}
check(ABOT in names and CBOT not in names, f"hosted: the activity log lists the operator's agents only {names}")

# ---- contents: backups, storage check, projects of disabled clients
check(A.get(B + "/api/admin/backups/kalmido-2030-01-01.zip/download").status_code == 403, "hosted: no backup download in the app")
r = A.get(B + "/api/admin/storage-check")
check(r.ok and r.json()["problems"] and all(p["name"] == "" and p["where"] == "" for p in r.json()["problems"]),
      "hosted: the storage check without titles and file names " + r.text[:160])
assert A.patch(B + f"/api/users/{uid['pia']}", json={"disabled": True}).ok
r = A.post(B + f"/api/lists/{PL}/owner", json={"user_id": 1})
check(r.status_code in (403, 404) and kt.dbx("SELECT owner_id FROM lists WHERE id=?", (PL,)) == [(uid["pia"],)],
      "hosted: no takeover of a disabled client's private project " + r.text[:100])
check(PL not in {x["id"] for x in A.get(B + "/api/admin/lists/orphaned").json()["lists"]}, "hosted: ... nor offered in the orphaned list")
assert A.patch(B + f"/api/users/{uid['pia']}", json={"disabled": False}).ok

# ---- the clients manage themselves
C = login(B, "carl")
r = C.put(B + f"/api/orgs/{CO}/members", json={"email": "pia@example.com"})
check(r.ok and kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (CO, uid["pia"])), "hosted: the client's admin invites into his organisation " + r.text[:100])
r = C.put(B + f"/api/orgs/{CO}/members", json={"user_id": uid["cara"], "role": "admin"})
check(r.ok and kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (CO, uid["cara"])) == [("admin",)],
      "hosted: the client's admin hands out roles " + r.text[:100])
check(C.patch(B + f"/api/orgs/{CO}", json={"name": "Client Studio AG"}).ok, "hosted: the client's admin renames his organisation")

# ---- a person without an organisation keeps everything
Fr = login(B, "frida")
r = Fr.post(B + "/api/orgs", json={"name": "Frida Design"})
check(r.status_code == 201, "freelancer: creates her own company on the hosted instance " + r.text[:100])
FO = r.json().get("id")
check(Fr.patch(B + f"/api/orgs/{FO}", json={"color": "#336699"}).ok, "freelancer: is its admin")
check(A.patch(B + f"/api/admin/orgs/{FO}", json={"members_add": [1]}).status_code == 403, "hosted: the operator stays out of her company, too")
check(Fr.patch(B + f"/api/admin/orgs/{CO}", json={"name": "x"}).status_code == 403, "freelancer (no instance admin): 403 as before")
check(Fr.post(B + "/api/lists", json={"name": "Portfolio", "org_id": None}).ok, "freelancer: her private workspace works as before")

sys.exit(kt.done("p2399_hosting_apart"))
