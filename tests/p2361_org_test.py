#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.361.0 (#2920 / #2922): leaving and deleting an organisation, seen from its members. Own container in mode workspaces.
 #2922 leaving / being removed:
 - a project the person brought in from the private space (PATCH org_id) goes back there, not to an admin; one made in the
   organisation goes to the admin as before
 - GET /api/orgs/<oid>/leave-info names it (back), what goes to the admin, what stays (a table) and the end of assignments;
   only the person or an admin of the organisation (404 / 403 else, also for a person without an organisation)
 - the removed person's News item counts the projects that came back
 #2920 deleting (instance admin):
 - delete-info lists per member what of theirs goes along
 - POST delete-notice: every member gets a News item with the day and their own numbers, the deletion waits (409);
   DELETE calls it off (told again, the old item disappears); after the deletion every member gets "orggone"
usage: p2361_org_test.py <datadir>      (P2361_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

if os.environ.get("P2361_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin", "frank"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN, FRANK = (ids[u] for u in ("bob", "carol", "dave", "erin", "frank"))


def setup(name, admin, members):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": admin})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    adm = sess([u for u, i in ids.items() if i == admin][0])
    for u in members:
        check(adm.put(B + f"/api/orgs/{oid}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, oid), f"setup: {u} joins {name}")
    return oid


def user(u, oid):
    s = sess(u)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "workspace": f"org:{oid}", "features": FEATURES + ",sheets"})
    return s


def lists(s):
    return {x["id"]: x for x in s.get(B + "/api/state").json()["lists"]}


def news(s, kind):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == kind]


def table(s, oid, title):
    r = s.post(B + "/api/sheets", json={"title": title, "space": f"org:{oid}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ================================================================ #2922 leaving
ORG = setup("Alpha", BOB, ("carol", "dave"))
Bo, Ca, Da = sess("bob"), user("carol", ORG), user("dave", ORG)
r = Ca.post(B + "/api/lists", json={"name": "Carols own", "org_id": None})
assert r.ok, r.text
OWN = r.json()["id"]
check(Ca.post(B + "/api/tasks", json={"list_id": OWN, "title": "Private work"}).ok, "setup: a task in carol's private project")
r = Ca.patch(B + f"/api/lists/{OWN}", json={"org_id": ORG})
check(r.ok and lists(Ca)[OWN].get("org_id") == ORG, f"setup: carol brings her private project into Alpha ({r.status_code} {r.text[:120]})")
r = Ca.post(B + "/api/lists", json={"name": "Made in Alpha", "org_id": ORG})
assert r.ok, r.text
BORN = r.json()["id"]
table(Ca, ORG, "Carols table")

j = Ca.get(B + f"/api/orgs/{ORG}/leave-info").json()
check(j.get("back") == ["Carols own"], f"leave-info: the brought-in project goes back ({j.get('back')})")
check((j.get("to_heir") or {}).get("lists") == 1 and j.get("heir") == "Bob", f"leave-info: the project made in Alpha goes to Bob ({j.get('to_heir')}, {j.get('heir')})")
check((j.get("stays") or {}).get("tables") == 1 and "table" in (j.get("stays_text") or ""), f"leave-info: the table stays, named ({j.get('stays')}, {j.get('stays_text')})")
check(Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": CAROL}).json().get("back") == ["Carols own"], "leave-info: the admin sees it for a member")
check(Da.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": CAROL}).status_code == 403, "leave-info: another member may not look at carol's")
check(sess("erin").get(B + f"/api/orgs/{ORG}/leave-info").status_code == 404, "leave-info: 404 for a person not in the organisation")
# freelancer-matrix: orgadmin
FID, Fr = freelancer(B, A)
check(Fr.get(B + f"/api/orgs/{ORG}/leave-info").status_code == 404, "freelancer: no leave preview of somebody else's organisation")
check(Fr.post(B + f"/api/admin/orgs/{ORG}/delete-notice", json={}).status_code == 403, "freelancer: no delete notice")

r = Ca.delete(B + f"/api/orgs/{ORG}/members/{CAROL}")
check(r.ok and r.json().get("transferred") == 1 and r.json().get("back") == 1, f"carol leaves: one project to Bob, one back ({r.text[:120]})")
mine = lists(Ca)
check(OWN in mine and not mine[OWN].get("org_id"), f"carol keeps her brought-in project, private now ({mine.get(OWN, {}).get('org_id')})")
check(BORN not in mine and BORN in lists(Bo), "the project made in Alpha went to Bob")
mo = [x for x in news(Bo, "orglist") if x["data"].get("action") == "moveout"]
check(mo and mo[0]["data"].get("name") == "Carols own", f"review: Bob (admin) is told the project left Alpha ({[x['data'] for x in mo]})")

# removed by an admin: the person keeps what they brought in, and is told
r = Da.post(B + "/api/lists", json={"name": "Daves own", "org_id": None})
DOWN = r.json()["id"]
check(Da.patch(B + f"/api/lists/{DOWN}", json={"org_id": ORG}).ok, "setup: dave brings a project in")
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{DAVE}")
check(r.ok and r.json().get("back") == 1 and r.json().get("transferred") == 0, f"bob removes dave: his project goes back ({r.text[:120]})")
check(DOWN in lists(Da) and DOWN not in lists(Bo), "dave keeps his project")
un = news(Da, "unshare")
check(un and un[0]["data"].get("back") == 1, f"dave's News item counts the project that came back ({[x['data'] for x in un]})")
# moved out and in again by an admin of another organisation path: a project made in an organisation is never "brought in"
r = Bo.post(B + "/api/lists", json={"name": "Bobs Alpha", "org_id": ORG})
check(Bo.get(B + f"/api/orgs/{ORG}/leave-info").json().get("back") == [], "a project made in the organisation is not brought in")

# ================================================================ #2920 deleting
KURZ = setup("Kurzorg", ERIN, ("frank",))
Er, Fk = sess("erin"), user("frank", KURZ)
table(Fk, KURZ, "Franks table")
di = A.get(B + f"/api/admin/orgs/{KURZ}/delete-info").json()
fm = [m for m in di.get("members", []) if m["id"] == FRANK]
check(fm and fm[0]["counts"].get("tables") == 1 and fm[0]["name"] == "Frank", f"delete-info: frank's table is named per member ({di.get('members')})")
check(di.get("notice") is None, "delete-info: no notice yet")
check(A.post(B + f"/api/admin/orgs/{KURZ}/delete-notice", json={"days": 0}).status_code == 400, "delete-notice: days 0 -> 400")
check(Er.post(B + f"/api/admin/orgs/{KURZ}/delete-notice", json={}).status_code == 403, "delete-notice: an organisation admin is no instance admin -> 403")
r = A.post(B + f"/api/admin/orgs/{KURZ}/delete-notice", json={"days": 14})
check(r.ok and r.json().get("told") == 2, f"delete-notice: both members told ({r.text[:120]})")
DAY = r.json().get("notice")
nd = news(Fk, "orgdelnotice")
check(nd and nd[0]["data"].get("day") == DAY and nd[0]["data"].get("own", {}).get("tables") == 1 and nd[0].get("to_me"),
      f"frank: News item with the day and his table, 'For you' ({[x.get('data') for x in nd]})")
check(news(Er, "orgdelnotice"), "erin (its admin) is told too")
r = A.delete(B + f"/api/admin/orgs/{KURZ}", params={"confirm": "1"})
check(r.status_code == 409 and DAY in r.text, f"the deletion waits for the day ({r.status_code} {r.text[:120]})")
check(A.get(B + f"/api/admin/orgs/{KURZ}/delete-info").json().get("notice") == DAY, "delete-info: shows the day")
check(A.delete(B + f"/api/admin/orgs/{KURZ}/delete-notice").ok, "the notice is called off")
nd = news(Fk, "orgdelnotice")
check(len(nd) == 1 and nd[0]["data"].get("day") == "", f"frank: only the call-off item is left ({[x.get('data') for x in nd]})")
r = A.delete(B + f"/api/admin/orgs/{KURZ}", params={"confirm": "1"})
check(r.ok, f"deleted ({r.status_code} {r.text[:160]})")
g = news(Fk, "orggone")
check(g and g[0]["data"].get("name") == "Kurzorg" and g[0]["data"].get("own", {}).get("tables") == 1, f"frank: told it is gone, with his table ({[x.get('data') for x in g]})")
check(news(Fk, "orgdelnotice") == [], "frank: the notice items disappear with the organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
