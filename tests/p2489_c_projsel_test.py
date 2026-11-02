#!/usr/bin/env python3
"""2.489.0 C (#2652): travel expenses and the logbook offer the real projects (lists) to choose, the free text stays the
fallback. Invented data only. tenant-matrix: office, freelancer-matrix: office
 - GET /api/office/trips and GET /api/office/vehicles carry real_projects [{id, name}]: the projects the person may see in
   the office's own workspace only - an organisation's office lists its lists, never the person's private ones nor those of
   another organisation; no basket, no archived list
 - a person without an organisation (the personal office): the own private projects, none of an organisation
 - a trip / drive keeps the chosen project's name as its text (nothing new stored), a free text still saves
usage: p2489_c_projsel_test.py <datadir>"""
# kalmido-suite: fresh
import sys

from freelancer_fixture import freelancer
from kt import B, check, docker_logs_on_first_fail, done, fresh, sess, setup

fresh(prefix="P2489CP")
docker_logs_on_first_fail()
A = setup()
FEAT = "clients,office"
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "frank", "display_name": "Frank", "password": "password123", "email": "frank@example.com"})
assert r.ok, r.text
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": r.json()["id"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Fr = sess("frank")
Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT, "workspace": f"org:{BETA}"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def mk(s, name, org):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


SHOOT = mk(A, "Alpha Shoot", ORG)
OLD = mk(A, "Alpha Old", ORG)
check(A.patch(B + f"/api/lists/{OLD}", json={"archived": 1}).ok, "an Alpha project archived")
GARDEN = mk(A, "Alice Garden", None)
FILM = mk(Fr, "Beta Film", BETA)
FPRIV = mk(Fr, "Frank Private", None)


def names(s, url):
    r = s.get(B + url)
    check(r.ok, f"{url} {r.status_code}")
    rp = r.json().get("real_projects") if r.ok else None
    check(isinstance(rp, list) and all(set(p) == {"id", "name"} for p in rp), f"{url}: real_projects [{{id, name}}] {rp}")
    return {p["name"] for p in rp or []}


for url in ("/api/office/trips", "/api/office/vehicles"):
    n = names(A, url)
    check("Alpha Shoot" in n, f"Alpha's office {url}: its project {n}")
    check(not n & {"Alpha Old", "Alice Garden", "Beta Film", "Frank Private"}, f"Alpha's office {url}: no archived, private or Beta project {n}")
    check(not any(x.lower() in ("inbox", "basket") for x in n), f"Alpha's office {url}: no basket {n}")
    n = names(Fr, url)
    check("Beta Film" in n and not n & {"Alpha Shoot", "Alpha Old", "Alice Garden", "Frank Private"}, f"Beta's office {url}: only its own projects {n}")

# the chosen name is the trip's text; a free text still saves
r = A.post(B + "/api/office/trips", json={"date_from": "2026-03-02", "dest": "Hamburg", "purpose": "job", "project": "Alpha Shoot", "people": []})
check(r.status_code in (200, 201), "a trip with the chosen project " + r.text[:200])
tid = (r.json().get("trip") or {}).get("id") or r.json().get("id")
r = A.patch(B + f"/api/office/trips/{tid}", json={"project": "Some old title"})
check(r.ok, "a free text as project " + r.text[:200])
t = [x for x in A.get(B + "/api/office/trips?year=2026").json()["trips"] if x["id"] == tid]
check(t and t[0]["project"] == "Some old title", f"the free text is kept {t[:1]}")

# a person without an organisation: the personal office offers the own private projects only
FID, Fl = freelancer(B, A)
for name in ("Frida Doc", "Frida Ad"):
    r = Fl.post(B + "/api/lists", json={"name": name})
    check(r.ok, "a private project of the freelancer " + r.text[:200])
for url in ("/api/office/trips", "/api/office/vehicles"):
    n = names(Fl, url)
    check({"Frida Doc", "Frida Ad"} <= n and not n & {"Alpha Shoot", "Alice Garden", "Beta Film", "Frank Private"}, f"the personal office {url}: the own projects only {n}")
r = Fl.post(B + "/api/office/trips", json={"date_from": "2026-04-01", "dest": "Köln", "purpose": "job", "project": "Frida Doc", "people": []})
check(r.status_code in (200, 201), "the freelancer's trip with the chosen project " + r.text[:200])

sys.exit(done("p2489_c_projsel"))
