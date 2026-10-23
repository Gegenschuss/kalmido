#!/usr/bin/env python3
"""2.154.0 D (#2567) duplicating an invoice made from times: the copy remembers where it came from (dup_times_from) while it
keeps client + period, shows no mark on a plain invoice; a copy of a copy points at the copy. Own container (start.sh),
invented companies only (@example.com). A person without an organisation does the same (freelancer-matrix: office).
usage: p2154_d_dup_test.py <datadir>      (a fresh container; P2154DD_NOSTART=1 = the server already runs)"""
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


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        assert s.post(B + "/api/auth/login", json={"username": user, "password": "password123"}).ok
    return s


def run(s, tag):
    r = s.post(B + "/api/clients", json={"name": "ACME " + tag, "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE"})
    cl = r.json().get("id")
    D = B + "/api/office/docs"
    plain = s.post(D, json={"kind": "invoice", "client_id": cl}).json()
    check(not plain.get("timesheet_ok"), tag + ": no period = no timesheet")
    p2 = s.post(f"{D}/{plain['id']}/duplicate").json()
    check(p2.get("dup_times_from") == "", tag + ": plain invoice copy has no mark " + str(p2.get("dup_times_from")))
    inv = s.post(D, json={"kind": "invoice", "client_id": cl, "service_from": "2030-03-01", "service_to": "2030-03-31"})
    check(inv.status_code == 201 and inv.json().get("timesheet_ok"), tag + ": invoice with period " + inv.text[:200])
    inv = inv.json()
    check(inv.get("dup_times_from") == "", tag + ": the original has no mark")
    cp = s.post(f"{D}/{inv['id']}/duplicate")
    check(cp.status_code == 201, tag + ": duplicate " + cp.text[:200])
    cp = cp.json()
    check(cp.get("dup_times_from") == (inv.get("number") or f"#{inv['id']}"), tag + ": copy names the original " + str(cp.get("dup_times_from")))
    check(cp.get("client_id") == cl and cp.get("service_from") == "2030-03-01", tag + ": copy keeps client + period")
    cc = s.post(f"{D}/{cp['id']}/duplicate").json()
    check(cc.get("dup_times_from") == (cp.get("number") or f"#{cp['id']}"), tag + ": a copy of a copy points at the copy")


if not os.environ.get("P2154DD_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,comments,collab,clients,office"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
run(A, "org")

# freelancer-matrix: office
FID, F = freelancer(B, A)
run(F, "freelancer")

print(f"p2154_d_dup: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
