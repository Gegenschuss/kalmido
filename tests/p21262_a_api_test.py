#!/usr/bin/env python3
"""2.126.2 A API test: the backlinks of a table (#2357) for a person without an organisation.
 - freelancer-matrix: sheets: a private table, a private page with [[tabelle:<id>]]; GET /api/wiki/refs?sheet= lists the page,
   another person gets 404, a table without links answers an empty list
usage: p21262_a_api_test.py <datadir>      (P21262A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


if os.environ.get("P21262A_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FEAT = FEATURES + ",sheets"
_, Fr = freelancer(B, A)
_, Fo = freelancer(B, A, "fiona")
for s in (Fr, Fo):
    s.patch(B + "/api/settings", json={"features": FEAT})

# freelancer-matrix: sheets
S1 = Fr.post(B + "/api/sheets", json={"title": "Stunden", "space": "private"}).json()["id"]
S2 = Fr.post(B + "/api/sheets", json={"title": "Leer", "space": "private"}).json()["id"]
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kunde/Notizen", "body": f"Siehe [[tabelle:{S1}]]"})
check(r.status_code == 201, "a private page links the table " + r.text[:200])
PG = r.json()["id"]
j = Fr.get(B + "/api/wiki/refs", params={"sheet": S1}).json()
check([p["id"] for p in j.get("pages", [])] == [PG] and j["pages"][0].get("path"), f"the backlinks of the table list the page {j}")
j = Fr.get(B + "/api/wiki/refs", params={"sheet": S2})
check(j.ok and j.json().get("pages") == [], "a table without links: an empty list")
check(Fo.get(B + "/api/wiki/refs", params={"sheet": S1}).status_code == 404, "another person gets 404 for the table")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
