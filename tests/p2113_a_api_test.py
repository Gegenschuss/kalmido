#!/usr/bin/env python3
"""2.113.0 API tests, part A (#2247, #2246): the office settings page saves every field by itself, so PUT /api/office/settings
gets one field (or the small group the server keeps together) at a time. Own container (start.sh, org encryption on).
Invented companies and figures only.
 - a partial body changes only its key: flat keys, one company field, one free line group, one language of the default
   texts, one part of the default rights, the DATEV booking export as a group; every other value stays as saved
 - a wrong value: 400, nothing changed (the other fields neither)
 - industry_packs on / off from the pack card (the full list of the switched-on packs), the rest of the settings unchanged
 - rights (tenant-matrix: office): a member 403 and nothing changed, another organisation does not see the change
 - a person without an organisation (freelancer-matrix: office): the same partial saves and the pack switch in the
   personal office
usage: p2113_a_api_test.py <datadir>      (P2113A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
S = "/api/office/settings"


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


if os.environ.get("P2113A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
me = lambda s: s.get(B + "/api/state").json()["me"]["id"]  # noqa: E731
ALICE, BOB, CAROL = me(A), me(Bo), me(Ca)
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})


def get(s):
    j = s.get(B + S).json()
    return j["settings"], j.get("company_fields") or {}


def put(s, body):
    return s.put(B + S, json=body)


def same_except(a, b, keys, what):
    """every settings key but `keys` unchanged"""
    diff = sorted(k for k in set(a) | set(b) if k not in keys and a.get(k) != b.get(k))
    check(not diff, f"{what}: nothing else changed {diff}")


def partial_suite(s, who):
    """the partial saves of the settings page, for one office admin (organisation or personal office)"""
    s0, c0 = get(s)
    texts = [t for t in s.get(B + "/api/office/texts").json().get("items", []) if t.get("kind") == "intro"]
    full = {"company": {"name": "Nordlicht Studio", "lines": ["Hafenweg 1", "20457 Hamburg"], "bank_lines": ["Beispielbank"]},
            "company_fields": {"name": "Nordlicht Studio", "street": "Hafenweg 1", "city": "Hamburg"},
            "color": "#2f5d8a", "payment_days": 21, "offer_valid_days": 45, "reminder_text_de": "Bitte zahlen.",
            "intro_text_id": {"de": texts[0]["id"] if texts else None, "en": None},
            "datev_extf": {"advisor_no": "1234", "client_no": "56"}}
    r = put(s, full)
    check(r.ok, f"{who}: the whole page saved once " + r.text[:200])
    base, cbase = get(s)
    check(base["payment_days"] == 21 and base["color"] == "#2f5d8a" and cbase.get("street") == "Hafenweg 1", f"{who}: the base values")
    # one flat field
    r = put(s, {"payment_days": 30})
    n, cn = get(s)
    check(r.ok and n["payment_days"] == 30, f"{who}: one field saved " + r.text[:200])
    same_except(base, n, {"payment_days"}, f"{who}: payment_days")
    check(cn == cbase, f"{who}: payment_days: the company fields unchanged")
    # one company field
    r = put(s, {"company_fields": {"city": "Bremen"}})
    n2, cn2 = get(s)
    check(r.ok and cn2.get("city") == "Bremen" and cn2.get("street") == "Hafenweg 1" and cn2.get("name") == "Nordlicht Studio", f"{who}: one company field, the others stay {cn2}")
    same_except(n, n2, set(), f"{who}: company field")
    # one group of free lines: the name and the other lines stay
    r = put(s, {"company": {"lines": ["Elbufer 3"]}})
    n3, _ = get(s)
    check(r.ok and n3["company"]["lines"] == ["Elbufer 3"] and n3["company"]["name"] == "Nordlicht Studio" and n3["company"]["bank_lines"] == ["Beispielbank"],
          f"{who}: one line group, the rest of the company stays {n3['company']}")
    same_except(n2, n3, {"company"}, f"{who}: line group")
    # the name: the field saves the print name and the company field together
    r = put(s, {"company": {"name": "Nordlicht Film"}, "company_fields": {"name": "Nordlicht Film"}})
    n4, cn4 = get(s)
    check(r.ok and n4["company"]["name"] == "Nordlicht Film" and n4["company"]["lines"] == ["Elbufer 3"] and cn4.get("name") == "Nordlicht Film" and cn4.get("city") == "Bremen",
          f"{who}: the name, lines and other fields stay")
    # one language of the default texts
    if texts:
        r = put(s, {"intro_text_id": {"en": texts[0]["id"]}})
        n5, _ = get(s)
        check(r.ok and n5["intro_text_id"] == {"de": texts[0]["id"], "en": texts[0]["id"]}, f"{who}: one language of the introduction, the other stays {n5['intro_text_id']}")
        same_except(n4, n5, {"intro_text_id"}, f"{who}: intro text")
    else:
        check(False, f"{who}: seeded introduction texts")
        n5 = n4
    # the DATEV booking export as one group
    dx = dict(n5.get("datev_extf") or {})
    dx["client_no"] = "77"
    r = put(s, {"datev_extf": dx})
    n6, _ = get(s)
    check(r.ok and (n6.get("datev_extf") or {}).get("client_no") == "77" and (n6.get("datev_extf") or {}).get("advisor_no") == "1234", f"{who}: the DATEV group")
    same_except(n5, n6, {"datev_extf"}, f"{who}: DATEV group")
    # a wrong value: 400, nothing changed
    r = put(s, {"payment_days": "many"})
    n7, cn7 = get(s)
    check(r.status_code == 400, f"{who}: a wrong value 400 ({r.status_code})")
    check(n7 == n6 and cn7 == cn4, f"{who}: a wrong value changes nothing")
    # #2246: the pack card switches industry_packs, nothing else
    r = put(s, {"industry_packs": ["film"]})
    p1, _ = get(s)
    check(r.ok and p1["industry_packs"] == ["film"], f"{who}: the pack card switches Film & Video on " + r.text[:200])
    same_except(n7, p1, {"industry_packs"}, f"{who}: pack on")
    r = put(s, {"industry_packs": []})
    p2, _ = get(s)
    check(r.ok and p2["industry_packs"] == [], f"{who}: and off again")
    same_except(p1, p2, {"industry_packs"}, f"{who}: pack off")
    r = put(s, {"industry_packs": ["film", "nosuchpack"]})
    check(r.ok and get(s)[0]["industry_packs"] == ["film"], f"{who}: an unknown pack code is dropped")
    put(s, {"industry_packs": []})
    return get(s)


# ---------------------------------------------------------------- an organisation's admin
sa, ca = partial_suite(A, "org admin")

# ---------------------------------------------------------------- rights (tenant-matrix: office)
r = put(Bo, {"payment_days": 3})
check(r.status_code == 403, f"a member cannot save a field ({r.status_code})")
r = put(Bo, {"industry_packs": ["film"]})
check(r.status_code == 403, f"a member cannot switch a pack ({r.status_code})")
check(get(A)[0] == sa, "the member's tries changed nothing")
cs, _ = get(Ca)
check(cs["payment_days"] != 30 and cs["company"]["name"] != "Nordlicht Film", "another organisation does not see the change")
check(cs.get("industry_packs") == [] and Ca.put(B + S, json={"industry_packs": ["film"]}).ok and get(A)[0]["industry_packs"] == [],
      "another organisation's pack switch stays in its own office")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
check(Fr.get(B + S).json().get("role") == "admin", "freelancer: admin of the personal office")
partial_suite(Fr, "freelancer")
check(get(A)[0] == sa, "freelancer: the organisation's settings untouched")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
