#!/usr/bin/env python3
"""2.114.4 API test, part C (#2280): the document variable client.address comes on own lines (street / zip city), the
draft PDF still renders with it. Own container (start.sh), invented companies only.
 - the admin of an organisation and a person without an organisation (freelancer-matrix: office) both get the address
   multi-line from POST /api/office/gen-docs/preview; an empty client field stays reported as missing
usage: p21144_c_api_test.py <datadir>      (P21144C_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


s0 = requests.Session()
s0.headers.update(H)
if not os.environ.get("P21144C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,comments,collab,clients,office"})
FID, F = freelancer(B, A)

for who, S in (("admin", A), ("freelancer", F)):
    cl = S.post(B + "/api/clients", json={"name": "Beispiel GmbH", "street": "Musterweg 5", "zip": "20000", "city": "Hamburg", "country": "DE"})
    check(cl.status_code < 300, f"{who}: a client {cl.status_code}")
    p = S.post(B + "/api/office/gen-docs/preview", json={"body": "An:\n{{client.address}}\nEnde {{offer.number}}", "client_id": cl.json()["id"], "lang": "de"})
    check(p.status_code == 200, f"{who}: preview {p.status_code} {p.text[:100]}")
    j = p.json()
    check(j["values"]["client.address"] == "Musterweg 5\n20000 Hamburg", f"{who}: address on own lines {j['values']['client.address']!r}")
    check("Musterweg 5\n20000 Hamburg" in j["text"], f"{who}: the filled text keeps the line break")
    check(j["missing"] == ["offer.number"], f"{who}: the empty field is reported {j['missing']}")

print(f"p21144_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
