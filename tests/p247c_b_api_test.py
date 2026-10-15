#!/usr/bin/env python3
"""2.47.1 API tests, part B (#1721): a fixed colour per account (agents and people). Invented names only.
 - users.color is given once and kept: per organisation the agents first, then the people, all different
 - everybody changes their own colour (PATCH /api/me), only colours of the palette; nobody changes another person's
 - an agent's colour (PATCH /api/agents/<id>/color): instance admins, the organisation's admins, the owner of a personal
   agent; a member or the admin of another organisation: 404
 - colors in /api/state: only accounts I see anyway (nothing of another organisation)
 - the setting person_colors (default on, 0 = only agents coloured; the client applies it)
 - rollback: the new column is additive (default '')
usage: p247c_b_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PAL = ["#3e63dd", "#f76b15", "#30a46c", "#a43cb4", "#cf3539", "#12a594",
       "#e2a336", "#c2307f", "#2aa7dc", "#8d5f3e", "#6e56cf", "#99b13a"]


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


def color(uid):
    return dbx("SELECT color FROM users WHERE id=?", (uid,))[0][0]


def colors(s):
    return s.get(B + "/api/state").json().get("colors") or {}


if not os.environ.get("P247CB_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
Da = sess("dave")
check(Da.put(B + f"/api/orgs/{ORG2}/members", json={"email": "erin@example.com"}).ok, "setup: erin joins Beta")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?,?))",
    (ORG, BOB, CAROL, ORG2, DAVE, ERIN), write=True)
AG, AGTOK = [], []
for n in ("alphabot", "alphahelper"):
    r = A.post(B + "/api/admin/agents", json={"username": n, "display_name": n.title(), "scopes": ["write"]})
    assert r.status_code == 201, r.text
    check(r.json().get("color") in PAL, f"a new agent gets a colour at once ({r.json().get('color')})")
    AG.append(r.json()["id"])
    AGTOK.append(r.json().get("token") or "")
    dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, AG[-1]), write=True)
    dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG[-1]), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "betabot", "display_name": "Beta bot"})
BAG = r.json()["id"]
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG2, BAG), write=True)
dbx("DELETE FROM org_members WHERE user_id=? AND org_id!=?", (BAG, ORG2), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG2, BAG), write=True)
for s in (A, Bo, Da):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- rollback: additive column
d = dbx("SELECT column_default, is_nullable FROM information_schema.columns WHERE table_name='users' AND column_name='color'")
check(d and "''" in str(d[0][0]) and d[0][1] == "NO", f"users.color: NOT NULL DEFAULT '' (2.46.6 runs on: {d})")

# ---- the colours of an organisation: agents first, all different
dbx("UPDATE users SET color='' WHERE id IN (?,?,?,?)", (AG[0], AG[1], BOB, CAROL), write=True)
m = colors(Bo)
check(m.get(str(AG[0])) == PAL[0] and m.get(str(AG[1])) == PAL[1], f"agents first: the first colours of the palette ({m})")
four = [m.get(str(x)) for x in (AG[0], AG[1], BOB, CAROL)]
check(all(four) and len(set(four)) == 4, f"two agents + two people of one organisation: four different colours ({four})")
check([color(x) for x in (AG[0], AG[1], BOB, CAROL)] == four, "the colours are stored (fixed)")
check(colors(Bo) == m, "the next state: the same colours")

# ---- the boundary: no account of another organisation
md = colors(Da)
check(not ({str(x) for x in (BOB, CAROL, AG[0], AG[1])} & set(md)), f"dave (Beta) sees no colour of Alpha's accounts ({sorted(md)})")
check(str(DAVE) in md and str(ERIN) in md, "dave sees himself and his organisation's members")
mc = colors(Ca)
check(str(DAVE) not in mc and str(ERIN) not in mc and str(BAG) not in mc, "carol (Alpha) sees nothing of Beta")
check(str(BOB) in mc and str(AG[0]) in mc, "carol sees her organisation's people and agents")

# ---- the own colour
check(Ca.patch(B + "/api/me", json={"color": PAL[7]}).ok and color(CAROL) == PAL[7], "carol changes her own colour")
check(colors(Bo).get(str(CAROL)) == PAL[7], "bob sees carol's new colour")
for bad in ("#123456", "red", "", None, 5, "#3E63DD; x"):
    check(Ca.patch(B + "/api/me", json={"color": bad}).status_code == 400, f"not a colour of the palette: 400 ({bad!r})")
check(color(CAROL) == PAL[7], "a refused colour changes nothing")
check(Ca.patch(B + "/api/me", json={"color": PAL[8].upper()}).ok and color(CAROL) == PAL[8], "upper case is the same colour")
# nobody changes another person's colour: the agent route refuses people, the admin's user route ignores it
check(Bo.patch(B + f"/api/agents/{CAROL}/color", json={"color": PAL[0]}).status_code == 404, "a person through the agent route: 404")
check(A.patch(B + f"/api/agents/{CAROL}/color", json={"color": PAL[0]}).status_code == 404, "also for the instance admin: 404")
A.patch(B + f"/api/users/{CAROL}", json={"color": PAL[0]})
check(color(CAROL) == PAL[8], "the admin's user route does not change a person's colour")

# ---- an agent's colour
# review: an agent does not change its own colour through PATCH /api/me (that is its admin's / owner's call)
was = color(AG[0])
r = requests.patch(B + "/api/me", json={"color": PAL[3] if was != PAL[3] else PAL[2]},
                   headers={**H, "Authorization": "Bearer " + AGTOK[0]})
check(r.status_code in (401, 403) and color(AG[0]) == was, f"an agent's own PATCH /api/me color: refused ({r.status_code})")
check(Bo.patch(B + f"/api/agents/{AG[0]}/color", json={"color": PAL[9]}).ok and color(AG[0]) == PAL[9],
      "the organisation's admin changes its agent's colour")
check(Ca.patch(B + f"/api/agents/{AG[0]}/color", json={"color": PAL[10]}).status_code == 404 and color(AG[0]) == PAL[9],
      "a member of the organisation: 404")
check(Da.patch(B + f"/api/agents/{AG[0]}/color", json={"color": PAL[10]}).status_code == 404 and color(AG[0]) == PAL[9],
      "the admin of another organisation: 404")
check(A.patch(B + f"/api/agents/{AG[1]}/color", json={"color": PAL[11]}).ok and color(AG[1]) == PAL[11], "the instance admin")
check(Bo.patch(B + f"/api/agents/{AG[0]}/color", json={"color": "#000000"}).status_code == 400, "an agent: only the palette")
check(Bo.patch(B + "/api/agents/999999/color", json={"color": PAL[0]}).status_code == 404, "an unknown agent: 404")
# a personal agent: its owner
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = Er.post(B + "/api/my/agents", json={"username": "erinbot", "display_name": "Erin bot"})
if r.status_code == 201:
    PA = r.json()["id"]
    check(r.json().get("color") in PAL, "a new personal agent gets a colour")
    check(Er.patch(B + f"/api/agents/{PA}/color", json={"color": PAL[4]}).ok and color(PA) == PAL[4], "the owner changes it")
    check(Bo.patch(B + f"/api/agents/{PA}/color", json={"color": PAL[5]}).status_code == 404 and color(PA) == PAL[4],
          "somebody else's personal agent (another organisation's admin): 404")
    check(Ca.patch(B + f"/api/agents/{PA}/color", json={"color": PAL[5]}).status_code == 404, "a stranger: 404")
    check(str(PA) in colors(Er), "the owner sees the colour of the personal agent")
else:
    check(False, f"setup: erin creates a personal agent ({r.status_code} {r.text[:120]})")

# ---- the setting "Show colours for people"
check(Bo.get(B + "/api/state").json()["settings"].get("person_colors") == "1", "person_colors: on by default")
check(Bo.patch(B + "/api/settings", json={"person_colors": "0"}).ok, "switched off")
st = Bo.get(B + "/api/state").json()
check(st["settings"].get("person_colors") == "0", "off is stored")
check(st.get("colors", {}).get(str(AG[0])) == PAL[9], "off: the colours are still sent (the client shows only agents)")
check(Bo.patch(B + "/api/settings", json={"person_colors": "1"}).ok and colors(Bo), "on again")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
