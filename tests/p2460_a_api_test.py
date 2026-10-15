#!/usr/bin/env python3
"""2.46.0 API tests, part A (#1592 #1562 #1561): one kind of instance (organisations + private spaces), own container
(start.sh, restarts with KEEP). Invented names only.
 - #1592: no mode set = workspaces; a new server has no organisation and everyone sees everyone (a household); the first-run
   setup creates the first organisation only when it gets a name (the admin its admin); KALMIDO_INSTANCE_MODE=organisation
   is ignored (no renaming, nobody moved); a restart never puts anybody into an organisation; an organisation admin
   removes members (their lists go to the admin) and they stay removed; people see their organisations + connections,
   people outside every organisation are reached by e-mail address; the instance admin's user management (?all=1) lists
   every account; open registration is refused once there is an organisation; a team agent is a member of its
   organisation (seen and shared with there)
 - the former automatic mode "organisation" (one organisation, accounts not yet in it): the first start of 2.46 syncs it
   once (everyone a member, the instance's admins its admins) -- nothing after that
 - #1562: an account the admin creates without organisations and a registration without a matching domain join none; a
   registration with an organisation's domain joins that one
 - #1561: POST /api/users orgs: [{id, role}] -- member / admin, a kid never an admin, an unknown organisation or a wrong
   role = 400 and no account
usage: p2460_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402

DATA = os.path.abspath(sys.argv[1])
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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


def start(extra="", keep=False):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    e.pop("KEEP", None)
    if keep:
        e["KEEP"] = "1"
    assert subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


def db(sql, args=()):
    return [tuple(r) for r in dbx.connect(DATA).execute(sql, args).fetchall()]


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def seen(s, all_=False):
    return {u["username"] for u in s.get(B + "/api/users" + ("?all=1" if all_ else "")).json()["users"]}


def new_user(A, name, **kw):
    return A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", **kw})


def members(oid):
    return dict(db("SELECT u.username, m.role FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=?", (oid,)))


# ================================================================== a new server: no organisation, a household
start()
assert requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
check(A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]}).ok, "setup without a name")
st = A.get(B + "/api/state").json()
check(st["instance_mode"] == "workspaces" and st["me"]["workspaces"] == [] and db("SELECT COUNT(*) FROM orgs") == [(0,)],
      "#1592: workspaces without a mode, no organisation from the start " + str(st["instance_mode"]))
check(st["about"].get("has_orgs") is False, "#1592: the setup still asks for a name (has_orgs false)")
for u in ("bob", "carol"):
    check(new_user(A, u, email=f"{u}@example.com").ok, "a person " + u)
Bo = sess("bob")
check({"alice", "carol"} <= seen(Bo), "#1592: a server without organisations: everyone sees everyone " + str(seen(Bo)))
check(db("SELECT COUNT(*) FROM org_members") == [(0,)], "#1562: nobody joins an organisation by default")

# ================================================================== the setup with a name creates the first organisation
check(A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"], "org_name": "Northwind"}).ok, "setup with a name")
orgs = A.get(B + "/api/orgs").json()["orgs"]
check([(o["name"], o["role"]) for o in orgs] == [("Northwind", "admin")], "#1592: the setup's name creates the organisation, the admin its admin " + str(orgs))
ORG = orgs[0]["id"]
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"], "org_name": "Second"})
check([o["name"] for o in A.get(B + "/api/admin/orgs").json()["orgs"]] == ["Northwind"], "#1592: a second setup creates no second organisation")
check(A.get(B + "/api/state").json()["about"].get("has_orgs") is True, "#1592: has_orgs once there is one")

# ================================================================== #1561: organisation + role when the admin adds a person
r = new_user(A, "dora", orgs=[{"id": ORG, "role": "admin"}])
check(r.ok and r.json()["orgs"] == [ORG] and members(ORG).get("dora") == "admin", "#1561: a new person as an admin of the organisation " + r.text[:120])
r = new_user(A, "emil", orgs=[{"id": ORG}])
check(r.ok and members(ORG).get("emil") == "member", "#1561: a new member (role member by default)")
r = new_user(A, "fritz", orgs=[ORG])
check(r.ok and members(ORG).get("fritz") == "member", "#1561: an organisation id alone = member")
r = new_user(A, "gina")
check(r.ok and r.json()["orgs"] == [] and "gina" not in members(ORG), "#1562: without orgs: no organisation (not the admin's own)")
n0 = db("SELECT COUNT(*) FROM users")[0][0]
r = new_user(A, "kid1", kid=True, parents=[1], orgs=[{"id": ORG, "role": "admin"}])
check(r.status_code == 400 and not db("SELECT 1 FROM users WHERE username='kid1'"), "#1561: a kid is never an organisation admin (400, no account)")
r = new_user(A, "kid2", kid=True, parents=[1], orgs=[{"id": ORG}])
check(r.ok and members(ORG).get("kid2") == "member", "#1561: a kid as a member")
r = new_user(A, "hugo", orgs=[{"id": 99999}])
check(r.status_code == 400 and not db("SELECT 1 FROM users WHERE username='hugo'"), "#1561: an unknown organisation: 400, no account")
r = new_user(A, "hugo", orgs=[{"id": ORG, "role": "owner"}])
check(r.status_code == 400 and not db("SELECT 1 FROM users WHERE username='hugo'"), "#1561: a wrong role: 400, no account")
check(new_user(A, "hugo", orgs="all").status_code == 400, "#1561: orgs must be a list")
check(db("SELECT COUNT(*) FROM users")[0][0] == n0 + 1, "#1561: no half account")
check(sess("bob").post(B + "/api/users", json={"username": "x1", "password": "password123", "orgs": [ORG]}).status_code == 403, "#1561: only an instance admin")

# ================================================================== visibility with an organisation
Do, Gi = sess("dora"), sess("gina")
check("bob" not in seen(Do) and "alice" in seen(Do), "#1592: a member sees the organisation, not people outside " + str(seen(Do)))
check("alice" not in seen(Gi) and "dora" not in seen(Gi), "#1592: a person outside every organisation does not see its members " + str(seen(Gi)))
check("gina" not in seen(A) and {"gina", "bob", "carol"} <= seen(A, True), "#1592: the admin's user management (?all=1) lists every account")
check(A.patch(B + "/api/users/" + str(db("SELECT id FROM users WHERE username='gina'")[0][0]), json={"display_name": "Gina G"}).ok,
      "#1592: the admin edits an account outside all organisations")
PL = A.post(B + "/api/lists", json={"name": "Private", "org_id": None}).json()["id"]
GINA = db("SELECT id FROM users WHERE username='gina'")[0][0]
check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": GINA, "role": "edit"}).status_code == 404, "#1592: no sharing by id across the boundary")
A.patch(B + f"/api/users/{GINA}", json={"email": "gina@example.com"})
r1 = A.put(B + f"/api/lists/{PL}/members", json={"email": "gina@example.com", "role": "edit"})
r2 = A.put(B + f"/api/lists/{PL}/members", json={"email": "nobody@example.com", "role": "edit"})
check(r1.json() == r2.json() == {"ok": True, "by_email": True} and PL in {l["id"] for l in Gi.get(B + "/api/state").json()["lists"]},
      "#1592: a private list reaches a person outside by e-mail address (same answer for an unknown address)")
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "open"}).status_code == 409, "#1592: no open registration with an organisation")

# ================================================================== a team agent works in its organisation
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team bot"})
TB = r.json()["id"]
check(r.status_code == 201 and members(ORG).get("teambot") == "member", "#1592: a team agent is a member of its organisation")
OL = Do.post(B + "/api/lists", json={"name": "Org list"}).json()
check(OL["org_id"] == ORG and "teambot" in seen(Do) and Do.put(B + f"/api/lists/{OL['id']}/members", json={"user_id": TB, "role": "edit"}).ok,
      "#1592: members see the team agent and share an organisation list with it")

r = A.post(B + "/api/admin/agents", json={"username": "sparebot", "display_name": "Spare bot"})
SB = r.json()["id"]
check("sparebot" in members(ORG) and A.patch(B + f"/api/admin/agents/{SB}", json={"org_id": None}).ok and "sparebot" not in members(ORG),
      "#1592 review: an agent made private leaves the organisation's members")

# ================================================================== #1592: an organisation admin removes a member
EMIL = db("SELECT id FROM users WHERE username='emil'")[0][0]
Em = sess("emil")
EL = Em.post(B + "/api/lists", json={"name": "Emil's org list"}).json()
check(EL["org_id"] == ORG, "a member's list in the organisation")
r = A.post(B + "/api/admin/agents", json={"username": "emilbot", "display_name": "Emil bot", "owner_id": EMIL})
EB = r.json()["id"]
check(r.status_code == 201 and "emilbot" in members(ORG) and Do.put(B + f"/api/lists/{OL['id']}/members", json={"user_id": EB, "role": "edit"}).ok,
      "a member's personal agent in the organisation and in an organisation list")
r = Do.delete(B + f"/api/orgs/{ORG}/members/{EMIL}")
check(r.ok and r.json()["transferred"] == 1 and "emil" not in members(ORG), "#1592: an organisation admin removes a member " + r.text[:120])
check(db("SELECT owner_id FROM lists WHERE id=?", (EL["id"],)) == [(db("SELECT id FROM users WHERE username='dora'")[0][0],)], "#1592: the list goes to the admin who removed")
check("emilbot" not in members(ORG) and not db("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (OL["id"], EB))
      and db("SELECT org_id FROM agents WHERE user_id=?", (EB,)) == [(None,)], "#1592 review: the removed member's agent leaves the organisation and its lists")

# ================================================================== restarts: nobody is put back, the old mode is ignored
start("-e KALMIDO_INSTANCE_MODE=organisation -e KALMIDO_ORG_NAME=Renamed", keep=True)
A = sess("alice")
check("emil" not in members(ORG) and "gina" not in members(ORG) and "bob" not in members(ORG), "#1592: a restart puts nobody into the organisation")
check([o["name"] for o in A.get(B + "/api/admin/orgs").json()["orgs"]] == ["Northwind"], "#1592: KALMIDO_ORG_NAME renames nothing")
check(A.get(B + "/api/state").json()["instance_mode"] == "workspaces" and "deprecated and ignored" in logs(), "#1592: the mode organisation is ignored (start-up hint)")
check(requests.get(B + "/api/auth/info").json().get("org") == "", "#1592/#1552: the login page names no organisation")

# ================================================================== #1562: registration (approval, no mail needed)
dbx.connect(DATA).execute("UPDATE orgs SET domains='northwind.example' WHERE id=?", (ORG,))
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "approval"}).ok, "approval mode")
R = requests.Session()
R.headers.update(H)
R.post(B + "/api/auth/signup", json={"name": "Ines", "email": "ines@elsewhere.example", "password": "ines-secret-1"})
R.post(B + "/api/auth/signup", json={"name": "Jan", "email": "jan@northwind.example", "password": "jan-secret-1"})
ines = db("SELECT id FROM users WHERE email='ines@elsewhere.example'")
jan = db("SELECT id FROM users WHERE email='jan@northwind.example'")
check(ines and not db("SELECT 1 FROM org_members WHERE user_id=?", (ines[0][0],)), "#1562: a registration without a matching domain joins no organisation")
check(jan and db("SELECT org_id FROM org_members WHERE user_id=?", (jan[0][0],)) == [(ORG,)], "#1562: a registration with the organisation's domain joins it")
check(ines and A.post(B + f"/api/users/{ines[0][0]}/approve").ok, "#1592: the instance admin approves a registration outside the organisation")

# ================================================================== review: clients
Gi = sess("gina")
for s_ in (A, Gi):
    s_.patch(B + "/api/settings", json={"features": "cal,comments,collab,clients"})
r = Gi.post(B + "/api/clients", json={"name": "Gina's own client"})
check(r.status_code == 201 and r.json().get("org_id") is None, "a private client of a person outside the organisation " + r.text[:120])
check("Gina's own client" not in [x["name"] for x in A.get(B + "/api/clients").json().get("clients", [])],
      "#1592 review: the instance admin does not see clients outside their organisations (one organisation, no mode set)")

# ================================================================== the former mode organisation: synced once on the first start
dbx.connect(DATA).execute("DELETE FROM settings WHERE key='migr_om2460'")
dbx.connect(DATA).execute("UPDATE org_members SET role='member' WHERE user_id=1")
start(keep=True)
A = sess("alice")
m = members(ORG)
check(m.get("alice") == "admin" and {"bob", "carol", "gina", "emil"} <= set(m), "former mode organisation: everyone a member, the admins its admins, once " + str(m))
check("former mode organisation synced once" in logs() or "synced once" in logs(), "… with a line in the log")
Do = sess("dora")
EMIL_ORG = Do.delete(B + f"/api/orgs/{ORG}/members/{EMIL}")
start(keep=True)
check("emil" not in members(ORG), "former mode organisation: only once (a removed member stays removed)")

# review: the organisation's name
dbx.connect(DATA).execute("INSERT INTO orgs(name,icon,created_at) VALUES('Elsewhere','','2026-10-15T00:00:00Z')")
check(A.patch(B + "/api/admin/settings", json={"org_name": "Renamed"}).status_code == 400 and db("SELECT name FROM orgs WHERE id=?", (ORG,)) == [("Northwind",)],
      "#1592 review: the setting org_name renames nothing once there are two organisations (also one the admin is not in)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
