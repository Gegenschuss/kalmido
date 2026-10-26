#!/usr/bin/env python3
"""2.223.2 B (#2860) API tests, own container (start.sh): "Previous access" (tpl:legacy) and the office rights groups of a
person who leaves the organisation. Invented people only.
 (a) a group manager (special "rights", no "release") gives "Previous access" -> 403, the rights page offers it no more;
     the organisation admin -> 200
 (b) a member with a group leaves the organisation and comes back -> no old group (previous access again)
 (c) a person without an organisation: the own rights page still offers "Previous access" (the own admin)
usage: p22232_b_rights_test.py <datadir>      (KMT_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, org_join  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
R = "/api/office/rights"
LEG = "tpl:legacy"


def put_groups(s, uid, refs):
    return s.put(B + f"{R}/people/{uid}", json={"groups": refs})


def people(s):
    return {p["id"]: p for p in s.get(B + R).json().get("people", [])}


def can_give(s, ref):
    return {t["ref"]: t.get("can_give") for t in s.get(B + R).json().get("templates", [])}.get(ref)


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ids, S = {}, {}
for u, n in (("tim", "Tim Teamlead"), ("xav", "Xav Member"), ("yve", "Yve Member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
    S[u] = sess(u)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
Ti = S["tim"]

# ---------------------------------------------------------------- (a) a group manager without "release"
# "Team lead": the members' previous levels plus the special "rights", no release / export
r = A.post(B + R + "/groups", json={"from": LEG, "name": "Teamleitung"})
check(r.status_code == 201, "admin: the group Teamleitung " + r.text[:160])
TL = r.json().get("id")
r = A.patch(B + f"{R}/groups/{TL}", json={"specials": ["rights"]})
check(r.ok and r.json().get("specials") == ["rights"], "admin: Teamleitung manages rights only " + r.text[:160])
check(put_groups(A, ids["tim"], [f"g:{TL}"]).ok, "admin: tim -> Teamleitung")
check(Ti.get(B + R).json().get("mine", {}).get("manager") == "group", "tim manages the office rights through the group")
check(put_groups(Ti, ids["xav"], ["tpl:none"]).ok, "(a) the group manager: xav -> no office access")
r = put_groups(Ti, ids["xav"], [LEG])
check(r.status_code == 403, f"(a) the group manager gives previous access (release / export of the role): 403 {r.status_code} {r.text[:160]}")
check(people(A)[ids["xav"]]["groups"] == ["tpl:none"], f"(a) xav keeps no office access {people(A)[ids['xav']]['groups']}")
check(can_give(Ti, LEG) is False, "(a) the group manager's rights page does not offer previous access")
check(can_give(A, LEG) is True, "(a) the admin's rights page offers previous access")
r = put_groups(A, ids["xav"], [LEG])
check(r.ok and r.json().get("groups") == [LEG], "(a) the admin gives previous access: 200 " + r.text[:160])

# ---------------------------------------------------------------- (b) leaving the organisation drops the groups
check(put_groups(A, ids["yve"], ["tpl:staff"]).ok, "(b) admin: yve -> staff")
check(people(A)[ids["yve"]]["groups"] == ["tpl:staff"], "(b) yve is staff")
r = A.delete(B + f"/api/orgs/{ORG}/members/{ids['yve']}")
check(r.ok, "(b) yve leaves the organisation " + r.text[:160])
check(ids["yve"] not in people(A), "(b) yve is no person of the office any more")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "yve@example.com", "role": "member"}).ok
check(org_join(B, "yve", ORG), "(b) yve comes back")
p = people(A).get(ids["yve"]) or {}
check(p.get("groups") == [LEG], f"(b) back in the organisation: no old group, previous access {p.get('groups')}")

# ---------------------------------------------------------------- (c) a person without an organisation  freelancer-matrix: office
FID, Fr = freelancer(B, A, "erin", features=FEAT)
r = Fr.get(B + R)
j = r.json() if r.ok else {}
check(r.ok and j.get("mine", {}).get("manager") == "admin", f"freelancer: the own admin of the rights page {r.text[:200]}")
check(can_give(Fr, LEG) is True, "freelancer: the own rights page offers previous access as before")
check(put_groups(Fr, FID, ["tpl:none"]).status_code == 409, "freelancer: the own person stays the admin (409)")
check(put_groups(Fr, ids["xav"], [LEG]).status_code == 404, "tenant-matrix: office -- a person of another office 404")

print(f"\np22232_b_rights: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
