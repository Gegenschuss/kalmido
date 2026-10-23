#!/usr/bin/env python3
"""2.81.0 API tests (part A: small bugs).
 - #1852 a client dialog that still sends a contact link whose contact was deleted elsewhere: 400 with the code
   contact_gone and the id the caller sent (nothing of foreign contacts); without that link the same save works
 - #1466 an agent never gets a client's contact persons' e-mail / phone / address book link (client_public cuts them to
   name / role; client_rows gives agents no client today); a person still gets all of it
tenant-matrix: client
usage: p281_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,collab,comments,events,contacts,clients,agents"


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

# ---- a client with a contact person linked to an address book contact
BK = A.post(B + "/api/books", json={"name": "Own", "org_id": None}).json()["id"]
r = A.post(B + "/api/contacts", json={"book_id": BK, "given": "Petra", "family": "Buyer"})
assert r.status_code == 201, r.text
CT = r.json()["id"]
r = A.post(B + "/api/clients", json={"name": "Acme", "contacts": [{"name": "Petra Buyer", "role": "Purchasing", "email": "petra@example.com", "phone": "+49 30 1234"}]})
assert r.status_code == 201, r.text
CL = r.json()["id"]
K1 = r.json()["contacts"][0]["id"]
r = A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": K1, "name": "Petra Buyer", "role": "Purchasing", "email": "petra@example.com", "phone": "+49 30 1234", "contact_id": CT}]})
check(r.ok and r.json()["contacts"][0]["contact_id"] == CT, f"setup: linked ({r.status_code} {r.text[:160]})")

# ================================================================== #1466 agents see name / role only
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
LST = A.post(B + "/api/lists", json={"name": "Project"}).json()["id"]
A.patch(B + f"/api/lists/{LST}", json={"client_id": CL})
A.put(B + f"/api/lists/{LST}/members", json={"user_id": ag["id"], "role": "view"})
# today client_rows() gives agents no client at all (404 / empty list); the contact persons are filtered anyway in client_public
for path in (f"/clients/{CL}", "/clients"):
    r = requests.get(V + path, headers=AGH)
    check("petra@example.com" not in r.text and "1234" not in r.text and "Purchasing" not in r.text and "billing" not in r.text,
          f"#1466: the agent gets no contact person data from {path} ({r.status_code} {r.text[:160]})")
p = A.get(B + f"/api/clients/{CL}").json()["contacts"][0]
check(p["email"] == "petra@example.com" and p["phone"] == "+49 30 1234", "#1466: a person still gets e-mail and phone")

# ================================================================== #1852 the linked contact is deleted elsewhere
check(A.delete(B + f"/api/contacts/{CT}").ok, "setup: the contact is deleted")
body = {"contacts": [{"id": K1, "name": "Petra Buyer", "contact_id": CT}]}
r = A.patch(B + f"/api/clients/{CL}", json=body)
j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
check(r.status_code == 400 and j.get("code") == "contact_gone" and j.get("contact_id") == CT, f"#1852: stale link -> 400 contact_gone ({r.status_code} {r.text[:200]})")
check(isinstance(j.get("error"), str) and not j["error"].startswith("("), f"#1852: error is the plain message ({j.get('error')!r})")  # 2.81.0 review
r = A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": K1, "name": "Petra Buyer", "contact_id": None}]})
check(r.ok and r.json()["contacts"][0]["contact_id"] is None, f"#1852: without the link the save works ({r.status_code})")
r = A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": K1, "name": "Petra Buyer", "contact_id": 999999}]})
check(r.status_code == 400 and r.json().get("code") == "contact_gone", "#1852: an unknown id answers the same (no existence oracle)")

print(f"p281_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
