#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.418.0 (#3560): the menus of the areas, arranged per person (freelancer-matrix: personal)
 - the setting nav_menus ({area: {order, hidden, shown}}) is stored normalised (duplicates once, empty lists / areas
   dropped) and strict (an unknown area or list, a non-string key, too many entries = 400); it is the person's, the same
   on every device (GET /api/state), and hides only: no route is locked by it
 - an organisation's admins switch menu points off for its members (PATCH /api/orgs/<id> {nav_off: ["office:travel", ...]});
   GET /api/orgs and /api/state (me.workspaces) carry it; a member cannot change it; a malformed point is 400
 - a person without an organisation arranges her own menus the same way (her own admin)
usage: p2418_api_test.py <datadir>      (KMT_NOSTART=1 / P2418_NOSTART=1: a running server)"""
import json

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, check, dbx, done, fresh, setup

fresh(prefix="P2418")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]

r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES, "workspace": f"org:{ORG}"})


def menus(s):
    return json.loads(s.get(B + "/api/state").json()["settings"].get("nav_menus") or "{}")


# ================================================================== the person's arrangement (setting nav_menus)
check(menus(Bo) == {}, "#3560: no arrangement at first (the default order, unused office points hidden by the app)")
mine = {"office": {"order": ["books", "offers", "books"], "hidden": ["pipeline"], "shown": ["kpi"]},
        "life": {"order": [], "hidden": ["family"]}, "reading": {}, "tabbar": {"order": ["s:today", "a:office", "tag:Büro", "l:12"]}}
r = Bo.patch(B + "/api/settings", json={"nav_menus": json.dumps(mine)})
check(r.ok, f"#3560: bob arranges his menus {r.status_code} {r.text[:160]}")
got = menus(Bo)
check(got == {"office": {"order": ["books", "offers"], "hidden": ["pipeline"], "shown": ["kpi"]}, "life": {"hidden": ["family"]},
              "tabbar": {"order": ["s:today", "a:office", "tag:Büro", "l:12"]}}, f"#3560: stored once each, empty dropped {got}")
check(Bo.get(B + "/api/office/settings").ok, "#3560: a hidden point only leaves the menu (no route is locked)")
for bad in ({"nope": {"order": ["x"]}}, {"office": {"sort": ["x"]}}, {"office": {"order": "books"}}, {"office": {"order": [3]}},
            {"office": {"order": ["x"] * 81}}, {"office": {"hidden": ["a\nb"]}}, ["office"], {"office": ["books"]}):
    check(Bo.patch(B + "/api/settings", json={"nav_menus": json.dumps(bad)}).status_code == 400, f"#3560: strict: {str(bad)[:60]} is 400")
check(menus(Bo)["office"]["hidden"] == ["pipeline"], "#3560: a refused value leaves the stored one as it was")
check(menus(A) == {}, "#3560: the arrangement is bob's only (alice untouched)")
check(Bo.patch(B + "/api/settings", json={"nav_menus": "{}"}).ok and menus(Bo) == {}, "#3560: back to the defaults")

# ================================================================== the admins switch points off for the organisation
ws = lambda s: [w for w in s.get(B + "/api/state").json()["me"]["workspaces"] if w["id"] == ORG][0]
org = lambda s: [x for x in s.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG][0]
check(org(Bo).get("nav_off") == [] and ws(Bo).get("nav_off") == [], "#3560: every point on by default (GET /api/orgs, state)")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"nav_off": ["office:travel"]}).status_code in (403, 404), "#3560: a member cannot switch points of the organisation")
check(org(Bo).get("nav_off") == [], "#3560: ... nothing changed")
for bad in (["travel"], ["nope:travel"], ["office:Travel Expenses"], "office:a,b c", [1]):
    check(A.patch(B + f"/api/orgs/{ORG}", json={"nav_off": bad}).status_code == 400, f"#3560: a malformed point {bad} is 400")
r = A.patch(B + f"/api/orgs/{ORG}", json={"nav_off": ["office:travel", "life:budget", "office:travel"]})
check(r.ok and r.json().get("nav_off") == ["office:travel", "life:budget"], f"#3560: the admin switches two points off (once each) {r.status_code} {r.text[:160]}")
check(dbx("SELECT nav_off FROM orgs WHERE id=?", (ORG,)) == [("office:travel,life:budget",)], "#3560: stored as csv")
check(ws(Bo).get("nav_off") == ["office:travel", "life:budget"], "#3560: the member's state carries it (the app leaves the points out)")
check(Bo.get(B + "/api/office/settings").ok, "#3560: the office itself stays open (menu points only)")
check(A.patch(B + f"/api/orgs/{ORG}", json={"nav_off": "reading:feeds"}).json().get("nav_off") == ["reading:feeds"], "#3560: csv is taken too")
check(A.patch(B + f"/api/orgs/{ORG}", json={"nav_off": []}).json().get("nav_off") == [], "#3560: all on again")

# ================================================================== a person without an organisation: her own admin
FID, Fr = freelancer(B, A)
r = Fr.patch(B + "/api/settings", json={"nav_menus": json.dumps({"office": {"hidden": ["contacts"], "shown": ["cashflow", "subs"]}, "ablage": {"order": ["docs", "ablage"]}})})
check(r.ok, f"#3560: the freelancer arranges her menus {r.status_code} {r.text[:160]}")
check(menus(Fr) == {"office": {"hidden": ["contacts"], "shown": ["cashflow", "subs"]}, "ablage": {"order": ["docs", "ablage"]}}, "#3560: freelancer: stored")
check(Fr.get(B + "/api/contacts").status_code != 403, "#3560: freelancer: a hidden point stays reachable")
check(Fr.get(B + "/api/state").json()["me"].get("workspaces") in (None, []), "#3560: freelancer: no organisation (nothing an admin switches for her)")
done("p2418_api_test")
