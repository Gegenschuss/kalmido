#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.409.0 (#3490): areas on / off per workspace (freelancer-matrix: personal)
 - an organisation's admins switch areas off for all its members (PATCH /api/orgs/<id> {areas_off}); GET /api/orgs and
   /api/state (me.workspaces) carry it; members cannot change it; unknown areas and "review" (private only) are 400
 - while the organisation is the workspace, the server refuses the area's routes (403): the office (its own area), the
   knowledge pages (also with the explicit space); the person's private space and personal office stay open
 - switching off deletes nothing: switched on again the page is there as before
 - every person switches areas off per workspace for themselves (setting ws_areas_off): stored normalised, strict, and it
   never locks a route (only hides in the app); a person without an organisation does the same for Private
usage: p2409_a_api_test.py <datadir>      (KMT_NOSTART=1 / P2409A_NOSTART=1: a running server)"""
import json

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, check, dbx, done, fresh, setup

fresh(prefix="P2409A")
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


def org_of(s):
    return [x for x in s.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG][0]


def ws_of(s):
    return [w for w in s.get(B + "/api/state").json()["me"]["workspaces"] if w["id"] == ORG][0]


# ================================================================== the admins' choice of the organisation
check(org_of(Bo).get("areas_off") == [] and ws_of(Bo).get("areas_off") == [], "#3490: all areas on by default (GET /api/orgs, state)")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["office"]}).status_code in (403, 404), "#3490: a member cannot switch an area of the organisation")
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["nope"]}).status_code == 400, "#3490: an unknown area is 400")
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["review"]}).status_code == 400, "#3490: review is private only (400)")

# before: bob reaches the organisation's office and its knowledge pages
check(Bo.get(B + "/api/office/settings").ok, "#3490: setup: bob opens the organisation's office")
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Ablauf", "body": "Schritt 1"})
check(r.ok, f"#3490: setup: a page of the organisation {r.status_code} {r.text[:160]}")
PID = r.json().get("id")
check(Bo.get(B + "/api/wiki", params={"space": f"org:{ORG}"}).ok, "#3490: setup: bob lists the organisation's pages")

r = A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["wiki", "office", "wiki"]})
check(r.ok and r.json().get("areas_off") == ["office", "wiki"], f"#3490: the admin switches office + knowledge off (ordered, once) {r.status_code} {r.text[:160]}")
check(dbx("SELECT areas_off FROM orgs WHERE id=?", (ORG,)) == [("office,wiki",)], "#3490: stored as csv")
check(ws_of(Bo).get("areas_off") == ["office", "wiki"], "#3490: the member's state carries it (the app hides the areas)")

# ================================================================== the server refuses the routes in that workspace
r = Bo.get(B + "/api/office/settings")
check(r.status_code == 403 and "switched off" in r.text, f"#3490: office routes 403 in the organisation {r.status_code} {r.text[:160]}")
check(Bo.get(B + "/api/office/docs").status_code == 403, "#3490: ... every office route")
r = Bo.get(B + "/api/wiki", params={"space": f"org:{ORG}"})
check(r.status_code == 403, f"#3490: the organisation's pages 403 (explicit space) {r.status_code}")
check(Bo.get(B + "/api/wiki", params={"space": str(ORG)}).status_code == 403, "#3490: ... also the bare id")
check(Bo.get(B + f"/api/wiki/pages/{PID}").status_code == 403, "#3490: ... a page of it by its id")
check(Bo.get(B + "/api/wiki", params={"space": "private"}).ok, "#3490: bob's private pages stay open (explicit space)")
check(Bo.get(B + "/api/sheets").status_code != 403, "#3490: an area the admin left on is untouched")

# Private: the person's own office and pages
check(Bo.patch(B + "/api/settings", json={"workspace": "private"}).ok, "#3490: bob switches to Private")
check(Bo.get(B + "/api/office/settings").ok, "#3490: his personal office stays open in Private")
check(Bo.get(B + f"/api/wiki/pages/{PID}").status_code == 403, "#3490: a link to a page of the organisation stays locked in Private too")

# ================================================================== on again: everything as before
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": []})
check(r.ok and r.json().get("areas_off") == [], f"#3490: the admin switches them on again {r.status_code}")
check(Bo.get(B + "/api/office/settings").ok, "#3490: the office opens again")
pages = Bo.get(B + "/api/wiki", params={"space": f"org:{ORG}"}).json().get("pages", [])
check(any(p["id"] == PID for p in pages), "#3490: the page is still there (nothing deleted)")
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": "time,reading"}).json().get("areas_off") == ["time", "reading"], "#3490: csv is taken too")
# the file store: only its own views are locked (the office keeps its files), the documents' parameter is "ws"
A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["ablage"]})
check(Bo.get(B + "/api/files", params={"space": f"org:{ORG}"}).status_code == 403, "#3490: file store off: its view of the organisation 403")
check(Bo.get(B + "/api/docs", params={"ws": f"org:{ORG}"}).status_code == 403, "#3490: ... the documents of the organisation (ws) 403")
check(Bo.get(B + "/api/docs", params={"ws": "private"}).status_code != 403, "#3490: ... his private documents stay open while the organisation is the workspace")
check(Bo.get(B + "/api/office/settings").ok, "#3490: ... the office (which keeps its files there) stays open")
A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": []})

# ================================================================== the own choice per workspace (setting ws_areas_off)
own = {f"org:{ORG}": ["time", "office", "time"], "private": [], "org:99999": ["wiki"]}
r = Bo.patch(B + "/api/settings", json={"ws_areas_off": json.dumps(own)})
check(r.ok, f"#3490: bob hides areas for himself {r.status_code} {r.text[:160]}")
st = json.loads(Bo.get(B + "/api/state").json()["settings"]["ws_areas_off"])
check(st == {f"org:{ORG}": ["office", "time"], "org:99999": ["wiki"]}, f"#3490: stored ordered, once, empty dropped {st}")
check(Bo.get(B + "/api/office/settings").ok, "#3490: the own choice only hides (no route is locked)")
for bad in ({"org:x": ["office"]}, {"private": ["nope"]}, {"private": "office"}, ["office"]):
    check(Bo.patch(B + "/api/settings", json={"ws_areas_off": json.dumps(bad)}).status_code == 400, f"#3490: strict: {bad} is 400")

# ================================================================== a person without an organisation: Private is her own
FID, F = freelancer(B, A)
r = F.patch(B + "/api/settings", json={"ws_areas_off": json.dumps({"private": ["office", "reading"]})})
check(r.ok, f"#3490: the freelancer switches areas off in Private {r.status_code} {r.text[:160]}")
check(json.loads(F.get(B + "/api/state").json()["settings"]["ws_areas_off"]) == {"private": ["office", "reading"]}, "#3490: freelancer: stored")
check(F.get(B + "/api/office/settings").ok, "#3490: freelancer: her personal office is never locked by the server")
check(F.patch(B + "/api/settings", json={"ws_areas_off": "{}"}).ok, "#3490: freelancer: everything on again")
done("p2409_a_api_test")
