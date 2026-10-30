#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.412.0 (#3552): the properties of a project per project type (freelancer-matrix: lists)
 - lists.props keeps only the properties switched by hand against the type's cut (lists/templates.py PTYPE_PROPS_OFF);
   PATCH /api/lists/<id> {props: {key: 0 | 1}} by the owner and the project admins, a member who edits gets 403; unknown
   keys and values are 400; {} / null = as the project type; /api/state carries it
 - a type change takes the new type's cut: what was switched on by hand and the new type hides stays on, a property
   switched off by hand follows the new type again; the change returns the old value in ptype_prev (undo) and the undo
   with _prev puts it back
 - hidden = display only: a value of a hidden property (story points of a personal project) is still set and kept
 - the same for a person without an organisation (own admin of the private projects)
usage: p2412_props_api_test.py <datadir>      (KMT_NOSTART=1 / P2412_NOSTART=1: a running server)"""
import json

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, check, dbx, done, fresh, setup

fresh(prefix="P2412")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": [ORG]})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Da = login(B, "bob"), login(B, "carol"), login(B, "dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES, "workspace": f"org:{ORG}"})


def lst(s, lid):
    return [x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid][0]


def props(lid):
    v = dbx("SELECT props FROM lists WHERE id=?", (lid,))[0][0]
    return json.loads(v) if v else {}


def project(s, name, ptype):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "ptype": ptype})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== rights and validation
SW = project(Bo, "Web app", "software")
check(Bo.put(B + f"/api/lists/{SW}/members", json={"user_id": uid["carol"], "role": "admin"}).ok, "setup: carol is a project admin")
check(Bo.put(B + f"/api/lists/{SW}/members", json={"user_id": uid["dave"], "role": "edit"}).ok, "setup: dave edits")
check(lst(Bo, SW).get("props") == "" and props(SW) == {}, "#3552: a new software project: no deviations (the type's cut)")
r = Bo.patch(B + f"/api/lists/{SW}", json={"props": {"video": 1}})
check(r.ok and props(SW) == {"video": 1}, f"#3552: the owner switches the video sign-off on {r.status_code} {r.text[:160]}")
r = Ca.patch(B + f"/api/lists/{SW}", json={"props": {"video": 1, "deps": 0}})
check(r.ok and props(SW) == {"deps": 0, "video": 1}, f"#3552: a project admin switches too {r.status_code} {r.text[:160]}")
check(json.loads(lst(Da, SW)["props"]) == {"deps": 0, "video": 1}, "#3552: every member gets it with the state")
r = Da.patch(B + f"/api/lists/{SW}", json={"props": {}})
check(r.status_code == 403 and props(SW) == {"deps": 0, "video": 1}, f"#3552: a member who edits cannot (403) {r.status_code}")
check(Bo.patch(B + f"/api/lists/{SW}", json={"props": {"nope": 1}}).status_code == 400, "#3552: an unknown property is 400")
check(Bo.patch(B + f"/api/lists/{SW}", json={"props": {"video": 2}}).status_code == 400, "#3552: a value other than 0 / 1 is 400")
check(Bo.patch(B + f"/api/lists/{SW}", json={"props": ["video"]}).status_code == 400, "#3552: a list is 400")
check(props(SW) == {"deps": 0, "video": 1}, "#3552: refused requests change nothing")
r = Bo.patch(B + f"/api/lists/{SW}", json={"props": {"video": 1, "deps": None}})
check(r.ok and props(SW) == {"video": 1}, "#3552: null = as the type again")

# ================================================================== a type change takes the new type's cut
# by hand: video on (agency shows it anyway), repo on (agency hides it), time off (agency shows it)
check(Bo.patch(B + f"/api/lists/{SW}", json={"props": {"video": 1, "repo": 1, "time": 0}}).ok, "setup: three by hand")
before = dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0]
r = Bo.patch(B + f"/api/lists/{SW}", json={"ptype": "agency"})
check(r.ok, f"#3552: switched to agency {r.status_code} {r.text[:160]}")
check(props(SW) == {"repo": 1}, f"#3552: switched on by hand and hidden by the new type stays on, the rest follows the type {props(SW)}")
check((r.json().get("ptype_prev") or {}).get("props") == before, "#3552: ptype_prev carries the old props (undo) " + str(r.json().get("ptype_prev")))
after = dbx("SELECT props FROM lists WHERE id=?", (SW,))[0][0]
r = Bo.patch(B + f"/api/lists/{SW}", json={"ptype": "software", "props": before, "_prev": {"ptype": "agency", "props": after}})
check(r.ok and lst(Bo, SW)["ptype"] == "software" and props(SW) == {"repo": 1, "time": 0, "video": 1}, f"#3552: the undo puts type and props back {props(SW)} {r.text[:120]}")
r = Ca.patch(B + f"/api/lists/{SW}", json={"ptype": "private"})
check(r.ok and props(SW) == {"repo": 1, "video": 1}, f"#3552: a project admin's type change too (private hides both, the switched-off time follows) {props(SW)}")
r = Bo.patch(B + f"/api/lists/{SW}", json={"ptype": ""})
check(r.ok and props(SW) == {}, f"#3552: a blank project shows everything: no deviations left {props(SW)}")

# ================================================================== hidden = display only
PV = project(Bo, "Garden", "private")
t = Bo.post(B + "/api/tasks", json={"title": "Plant tulips", "list_id": PV}).json()
r = Bo.patch(B + f"/api/tasks/{t['id']}", json={"points": 3})
check(r.ok and dbx("SELECT points FROM tasks WHERE id=?", (t["id"],))[0][0] == 3, f"#3552: story points of a personal project (hidden) are still set {r.status_code}")
check(Bo.patch(B + f"/api/lists/{PV}", json={"props": {"points": 1}}).ok and dbx("SELECT points FROM tasks WHERE id=?", (t["id"],))[0][0] == 3,
      "#3552: switched on again the value is there")

# ================================================================== a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
FP = project(Fr, "Client site", "software")
r = Fr.patch(B + f"/api/lists/{FP}", json={"props": {"client": 1, "docs": 1}})
check(r.ok and props(FP) == {"client": 1, "docs": 1}, f"#3552: freelancer: own admin of the own project {r.status_code} {r.text[:160]}")
r = Fr.patch(B + f"/api/lists/{FP}", json={"ptype": "agency"})
check(r.ok and props(FP) == {}, f"#3552: freelancer: the type change takes the agency's cut {props(FP)}")
check(Fr.patch(B + f"/api/lists/{SW}", json={"props": {}}).status_code in (403, 404), "#3552: freelancer: not in someone else's project")

raise SystemExit(done("p2412_props_api"))
