#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.356.0 B (#2932): joining an organisation keeps a freelancer's own office. Invented names only.
 - a person without an organisation (freelancer fixture) has a client and a quotation in the personal office, accepts an
   invitation into an organisation: the setting "workspace" becomes "private", GET /api/office/settings stays the personal
   office (personal 1, admin), the quotation is still listed and a new quotation is numbered in the personal office
 - counter-check: a person whose personal office is empty (opened once, no data) joins: nothing changes, the office is
   the organisation's as before
 - a workspace chosen before the join stays as it is; the setting office_ws_hint (the office's one-time hint) is a flag
usage: p2356_b_join_office_test.py <datadir>"""
# freelancer-matrix: office
import os
import sys

import requests

from freelancer_fixture import FEATURES, freelancer, org_join
from kt import FAILS, OKS, check, sess

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O, D = "/api/office", "/api/office/docs"

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": r.json()["id"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"})
r = Bo.get(B + O + "/settings")
check(r.ok and r.json().get("org_id") == ORG, f"setup: the organisation's office {r.status_code} {r.text[:120]}")


def ws(s):
    return s.get(B + "/api/state").json()["settings"].get("workspace")


# ---- 1. a freelancer with an own office joins by invitation
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com"})
check(r.ok, f"the freelancer's private client {r.status_code} {r.text[:120]}")
CL = r.json().get("id")
r = Fr.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm"})
check(r.ok, f"the freelancer's quotation {r.status_code} {r.text[:160]}")
Q = r.json().get("id")
st = Fr.get(B + O + "/settings").json()
PID = st.get("org_id")
check(st.get("personal") == 1 and PID and PID != ORG, f"before: the personal office {st.get('personal')} {PID}")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "frida@example.com"}).ok and org_join(B, "frida", ORG), "frida accepts the invitation")
check(ws(Fr) == "private", f"#2932: the workspace stays the private one after the join: {ws(Fr)!r}")
r = Fr.get(B + O + "/settings")
j = r.json() if r.ok else {}
check(r.ok and j.get("org_id") == PID and j.get("personal") == 1 and j.get("role") == "admin",
      f"#2932: the office stays the personal one: {r.status_code} org {j.get('org_id')} personal {j.get('personal')} role {j.get('role')}")
r = Fr.get(B + D + "?kind=offer")
check(r.ok and Q in [x["id"] for x in r.json().get("docs", [])], f"#2932: the own quotation is still listed {r.status_code}")
r = Fr.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Zweiter Film"})
Q2 = r.json().get("id") if r.ok else None
j = Fr.get(B + D + "?kind=offer").json()
check(r.ok and j.get("org_id") == PID and Q2 in [x["id"] for x in j.get("docs", [])],
      f"#2932: a new quotation lands in the personal office {r.status_code} {r.text[:120]} org {j.get('org_id')}")
check(any(o.get("id") == ORG for o in Fr.get(B + "/api/state").json()["me"].get("workspaces") or []), "frida is a member of Alpha")
# the organisation's office is one switch away
check(Fr.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"}).ok, "switch to Alpha")
r = Fr.get(B + O + "/settings")
check(r.ok and r.json().get("org_id") == ORG and r.json().get("personal") == 0, f"the organisation's office after the switch {r.status_code}")
r = Fr.get(B + D + "?kind=offer")
check(r.ok and Q not in [x["id"] for x in r.json().get("docs", [])], "the organisation's office does not list the private quotation")

# ---- 2. counter-check: an empty personal office (opened once) -> the organisation's office as before
FID2, Fi = freelancer(B, A, "fiona")
r = Fi.get(B + O + "/settings")
check(r.ok and r.json().get("personal") == 1, f"fiona opens her (empty) personal office {r.status_code}")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "fiona@example.com"}).ok and org_join(B, "fiona", ORG), "fiona joins Alpha")
check(ws(Fi) in ("all", "", None), f"#2932 counter-check: no data -> the workspace is untouched: {ws(Fi)!r}")
r = Fi.get(B + O + "/settings")
check(r.ok and r.json().get("org_id") == ORG and r.json().get("personal") == 0, f"#2932 counter-check: the organisation's office {r.status_code} {r.text[:120]}")

# ---- 3. a workspace chosen before stays; the hint flag
r = A.post(B + "/api/admin/orgs", json={"name": "Beta Werk", "admin_id": FID})
check(r.status_code == 201, f"a second organisation, frida its admin {r.status_code}")
check(ws(Fr) == f"org:{ORG}", f"#2932: a chosen workspace is not overwritten by a further membership: {ws(Fr)!r}")
check(Fr.patch(B + "/api/settings", json={"office_ws_hint": "1"}).ok and Fr.get(B + "/api/state").json()["settings"].get("office_ws_hint") == "1",
      "#2932: the hint flag office_ws_hint is stored")
check(Fr.patch(B + "/api/settings", json={"office_ws_hint": "x"}).status_code == 400, "#2932: office_ws_hint is a flag (0/1)")

# ---- 4. 2.356.0 (review N3): who creates an organisation for herself goes on in it (no switch to "private")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"workspace": "private", "features": FEATURES})
check(A.post(B + "/api/clients", json={"name": "Alice Kundin", "street": "Weg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}).status_code in (200, 201),
      "setup: alice has a client in her personal office")
A.patch(B + "/api/settings", json={"workspace": "all"})
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma Eigen", "admin_id": ALICE})
check(r.status_code == 201 and ws(A) == "all", f"#2932 N3: creating an organisation for herself keeps the workspace ({r.status_code} {ws(A)!r})")

print(f"p2356_b_join_office: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
