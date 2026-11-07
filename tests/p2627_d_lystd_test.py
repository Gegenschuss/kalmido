#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.627.0 (#4504): the standard arrangement of the views (start page, Today, time tracking, overviews, review) per
organisation, set by its admins: own arrangement > the standard of the active workspace's organisation > the instance
standard; "Reset to the standard" (the own value goes) leads to the organisation's standard. Invented names only.
 - GET /api/layouts/std?ws=org:<id> | private | all (else the saved setting "workspace"): layouts = what counts there, org =
   {id, name, admin}, can, versions of the level the person writes
 - PUT /api/layouts/std/<key> {org_id}: the organisation's admin (bob) sets it; a member (carl) 403, the admin of another
   organisation (dave) 404 and reads nothing of it; without org_id only instance admins (as before)
 - per view: an organisation without a standard of a view falls back to the instance's; the instance standard stays as it is
 - version check (409 with the current state), promote (the own value goes)
 - the agent's read GET /api/v1/layouts/<view> (source own | standard | default) follows the same order
 - freelancer-matrix: settings (frida without an organisation: own > instance only, no organisation's standard, no org_id)
usage: p2627_d_lystd_test.py <datadir>      (a fresh container; P2627DL_NOSTART=1 = the server already runs)"""
import json
import os
import sys

import requests

import dbx as dbxm
import kt
from freelancer_fixture import freelancer
from kt import B, check, sess

kt.fresh(prefix="P2627DL", env={"KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
uid = {}


def wdb(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def person(name, orgs):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return s


Da, Bo = person("dave", []), person("bob", [])
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": uid["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Ca = person("carl", [{"id": ORG, "role": "member"}])
FID, Fr = freelancer(B, A, "frida")
CARL = uid["carl"]
role = lambda s, o: next((x.get("role") for x in s.get(B + "/api/orgs").json().get("orgs", []) if x["id"] == o), None)  # noqa: E731
check(role(Bo, ORG) == "admin" and role(Ca, ORG) == "member" and role(Da, ORG2) == "admin" and role(Da, ORG) is None,
      "setup: bob admin of Alpha, carl member of Alpha, dave admin of Beta only")

LI = json.dumps({"order": ["brief", "tasks"], "hidden": ["review"]})        # the instance's Today
LO = json.dumps({"order": ["wait", "tasks"], "hidden": ["brief"]})          # Alpha's Today
LD = json.dumps({"order": ["events", "tasks"]})                             # Beta's Today
DI = json.dumps({"order": ["news", "today"]})                               # the instance's start page
std = lambda s, ws="": s.get(B + "/api/layouts/std" + (f"?ws={ws}" if ws else "")).json()  # noqa: E731
put = lambda s, key, lay, **kw: s.put(B + f"/api/layouts/std/{key}", json={"layout": lay, **kw})  # noqa: E731
J = lambda v: json.loads(v or "{}")  # noqa: E731
sv = lambda s, ws="", k="view_today": J(std(s, ws)["layouts"][k])  # noqa: E731

# ---- the instance standard (as before)
r = put(A, "view_today", LI)
check(r.ok and J(r.json()["layouts"]["view_today"]) == J(LI) and "org" not in r.json(), "the instance admin sets the instance standard (answer as before) " + r.text[:200])
check(put(A, "dashboard", DI).ok, "... and the start page's")
g = std(Bo, f"org:{ORG}")
check(g["org"] == {"id": ORG, "name": "Alpha", "admin": True} and g["can"] is True and J(g["layouts"]["view_today"]) == J(LI),
      f"#4504: Alpha has no standard yet: the instance's counts, bob may set Alpha's {g}")

# ---- the organisation's admin sets Alpha's standard
r = put(Bo, "view_today", LO, org_id=ORG)
check(r.ok and J(r.json()["layouts"]["view_today"]) == J(LO) and r.json()["org"]["id"] == ORG and r.json()["versions"]["view_today"],
      "#4504: bob sets Alpha's Today " + r.text[:200])
V1 = r.json()["versions"]["view_today"] if r.ok else ""
check(J(kt.dbx("SELECT value FROM settings WHERE key='lystd_view_today'")[0][0]) == J(LI), "#4504: the instance standard is unchanged")
check(sv(A, "private") == J(LI), "#4504: ... the instance admin reads it unchanged in the private workspace")

# ---- the order for a member: org standard of the active workspace, per view the instance's fallback
g = std(Ca, f"org:{ORG}")
check(J(g["layouts"]["view_today"]) == J(LO) and g["can"] is False and g["org"] == {"id": ORG, "name": "Alpha", "admin": False},
      f"#4504: carl in Alpha reads Alpha's Today, may not set it {g}")
check(J(g["layouts"]["dashboard"]) == J(DI), "#4504: Alpha has no start page standard: the instance's counts")
check(sv(Ca, "private") == J(LI) and std(Ca, "private")["org"] is None, "#4504: carl in Private: the instance's")
check(sv(Ca, "all") == J(LO), "#4504: 'All' with his only organisation: Alpha's")
Ca.patch(B + "/api/settings", json={"workspace": "private"})
check(sv(Ca) == J(LI), "#4504: without ?ws the saved workspace counts (Private)")
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(sv(Ca) == J(LO), "#4504: ... (Alpha)")

# ---- rights: a member, another organisation's admin, an unknown organisation
r = put(Ca, "view_today", LI, org_id=ORG)
check(r.status_code == 403, f"#4504: carl (member) cannot set Alpha's standard ({r.status_code})")
check(put(Ca, "view_today", LI).status_code == 403, "#4504: ... nor the instance's")
g = std(Da, f"org:{ORG}")
check(g["org"] is None and J(g["layouts"]["view_today"]) == J(LI), f"#4504: dave (Beta) reads nothing of Alpha's standard {g}")
r = put(Da, "view_today", LD, org_id=ORG)
check(r.status_code == 404, f"#4504: dave cannot set Alpha's standard ({r.status_code})")
check(sv(Ca, f"org:{ORG}") == J(LO), "#4504: ... Alpha's stays")
r = put(Da, "view_today", LD, org_id=ORG2)
check(r.ok and J(r.json()["layouts"]["view_today"]) == J(LD), "#4504: dave sets Beta's " + r.text[:200])
check(sv(Bo, f"org:{ORG}") == J(LO) and std(Bo, f"org:{ORG2}")["org"] is None, "#4504: bob reads Alpha's, nothing of Beta")
check(put(Bo, "view_today", LO, org_id=ORG2).status_code == 404, "#4504: bob cannot set Beta's")
check(put(Bo, "view_today", LO, org_id="1").status_code == 400, "#4504: org_id must be a number")
check(put(Bo, "view_nope", LO, org_id=ORG).status_code == 400, "#4504: unknown view 400")

# ---- version check and promote
Er = person("erin", [{"id": ORG, "role": "admin"}])
check(put(Er, "view_today", LI, org_id=ORG).ok, "#4504: erin (a second admin of Alpha) sets Alpha's meanwhile")
r = put(Bo, "view_today", "", org_id=ORG, expect_updated_at=V1)
check(r.status_code == 409 and (r.json().get("current") or {}).get("layouts", {}).get("view_today") and J((r.json().get("current") or {})["layouts"]["view_today"]) == J(LI)
      and (r.json().get("current") or {}).get("org", {}).get("id") == ORG, "#4504: an undo with the old version: 409 with Alpha's current " + r.text[:200])
check(put(Bo, "view_today", LO, org_id=ORG).ok, "#4504: bob sets LO again")
Bo.patch(B + "/api/settings", json={"view_today": LD})
r = put(Bo, "view_today", LD, org_id=ORG, promote=True)
check(r.ok and Bo.get(B + "/api/state").json()["settings"].get("view_today", "") == "", "#4504: promote: bob's own Today goes")
check(sv(Ca, f"org:{ORG}") == J(LD), "#4504: ... and is Alpha's standard")
check(put(Bo, "view_today", LO, org_id=ORG).ok, "#4504: back to LO")

# ---- own > org > instance in the server's reading (the agent's GET /api/v1/layouts/<view>), reset = own value gone
r = A.post(B + "/api/admin/agents", json={"username": "lybot", "display_name": "Lybot", "scopes": ["read", "layouts"]})
assert r.status_code == 201, r.text
AID, AT = r.json()["id"], r.json().get("token") or ""
wdb("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (AID, ORG))
wdb("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AID))
wdb("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (ORG, CARL, AID))  # carl's own agent in Alpha
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + AT})
ag = lambda: AG.get(B + "/api/v1/layouts/view_today").json()  # noqa: E731
x = ag()
check(x.get("source") == "standard" and (x.get("layout") or {}).get("hidden") == ["brief"], f"#4504: carl's Today = Alpha's standard (brief hidden) {x}")
check(Ca.patch(B + "/api/settings", json={"view_today": json.dumps({"order": ["inbox", "tasks"]})}).ok, "carl arranges his own Today")
x = ag()
check(x.get("source") == "own" and x["layout"]["order"][0] == "inbox", f"#4504: his own arrangement wins {x.get('source')}")
check(Ca.patch(B + "/api/settings", json={"view_today": ""}).ok, "carl: Reset to the standard (the own value goes)")
x = ag()
check(x.get("source") == "standard" and x["layout"]["hidden"] == ["brief"], f"#4504: after the reset Alpha's standard again, not the instance's {x.get('layout')}")
# 2.627.0 (#4504, review F1): an organisation's agent reads its own organisation's standard, never the one of the workspace
# carl last chose (Private, or Beta when he is in Beta too); before the fix Alpha's agent read Beta's arrangement
Ca.patch(B + "/api/settings", json={"workspace": "private"})
x = ag()
check(x.get("source") == "standard" and x["layout"]["hidden"] == ["brief"], f"#4504 F1: carl in Private: Alpha's agent still reads Alpha's standard {x.get('layout')}")
wdb("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG2, CARL))
check(Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"}).ok and sv(Ca, f"org:{ORG2}") == J(LD), "carl in Beta too, Beta's Today counts for him there")
x = ag()
check(x.get("source") == "standard" and x["layout"]["hidden"] == ["brief"] and x["layout"]["order"][0] != "events",
      f"#4504 F1: carl in Beta: Alpha's agent reads Alpha's standard, nothing of Beta's {x.get('layout')}")
wdb("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG2, CARL))
Ca.patch(B + "/api/settings", json={"workspace": "private"})

# ---- freelancer-matrix: settings -- frida without an organisation: own > instance
g = std(Fr)
check(g["org"] is None and g["can"] is False and J(g["layouts"]["view_today"]) == J(LI), f"#4504: frida reads the instance's standard, no organisation {g}")
check(std(Fr, f"org:{ORG}")["org"] is None and sv(Fr, f"org:{ORG}") == J(LI), "#4504: ... also when she names Alpha")
check(put(Fr, "view_today", LO, org_id=ORG).status_code == 404 and put(Fr, "view_today", LO).status_code == 403,
      "#4504: frida sets no organisation's and not the instance's standard")
check(Fr.patch(B + "/api/settings", json={"view_today": LD}).ok and J(Fr.get(B + "/api/state").json()["settings"].get("view_today")) == J(LD),
      "#4504: frida keeps her own Today")
check(J(kt.dbx("SELECT value FROM settings WHERE key='lystd_view_today'")[0][0]) == J(LI), "#4504: the instance standard is still unchanged")

# 2.627.0 (#4504, review F2): deleting an organisation takes its standards along (they live in the global settings)
check(kt.dbx(f"SELECT COUNT(*) FROM settings WHERE key IN ('lystd_o{ORG2}_view_today', 'lystd_at_o{ORG2}_view_today')")[0][0] == 2, "Beta has its Today standard + version")
r = A.delete(B + f"/api/admin/orgs/{ORG2}?confirm=1")
check(r.ok, "the instance admin deletes Beta " + r.text[:200])
check(kt.dbx(f"SELECT COUNT(*) FROM settings WHERE key IN ('lystd_o{ORG2}_view_today', 'lystd_at_o{ORG2}_view_today')")[0][0] == 0, "#4504 F2: Beta's standards are gone with it")
check(J(kt.dbx("SELECT value FROM settings WHERE key='lystd_view_today'")[0][0]) == J(LI) and sv(Ca, f"org:{ORG}") != J(LI),
      "#4504 F2: the instance's and Alpha's standards stay")

sys.exit(kt.done("p2627_d_lystd"))
