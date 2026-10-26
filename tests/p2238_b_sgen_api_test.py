#!/usr/bin/env python3
"""2.238.0 B API tests (#2872, own container): the sign-in mark me.sgen (GET /api/state and GET /api/me)
 - the same in both answers, stable within one session, 24 hex digits
 - another sign-in of the same account (a new session), a changed password, joining and leaving an organisation: another mark
 - a person without an organisation (freelancer-matrix: wiki) and an admin have it the same way
usage: p2238_b_sgen_api_test.py <datadir>      (P2238B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import re
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer, login

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def gen(s):
    st, me = s.get(B + "/api/state"), s.get(B + "/api/me")
    assert st.ok and me.ok, (st.status_code, me.status_code)
    a, b = st.json()["me"].get("sgen"), me.json().get("sgen")
    check(a == b, f"/api/state and /api/me give the same mark ({a} / {b})")
    return a


if os.environ.get("P2238B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================= a person without an organisation
FID, Fr = freelancer(B, A)
g1 = gen(Fr)
check(bool(g1) and re.fullmatch(r"[0-9a-f]{24}", g1 or ""), f"freelancer: a mark of 24 hex digits ({g1})")
check(gen(Fr) == g1, "freelancer: the same session keeps its mark")
Fr2 = login(B, "frida")
g2 = gen(Fr2)
check(g2 and g2 != g1, "freelancer: another sign-in of the same account = another mark")
check(gen(Fr) == g1, "freelancer: the first session keeps its mark")
r = Fr.patch(B + "/api/me", json={"password": "password456", "current_password": "password123"})
check(r.ok, f"freelancer: password changed ({r.status_code})")
st = Fr.get(B + "/api/state")
if st.ok:
    check(st.json()["me"]["sgen"] not in (g1, g2), "freelancer: a changed password = another mark")
else:  # the session that changed it ended too: a new one has another mark
    check(gen(login(B, "frida", "password456")) not in (g1, g2), "freelancer: a changed password = another mark (new session)")

# ================= an admin, a member joining and leaving an organisation
check(re.fullmatch(r"[0-9a-f]{24}", gen(A) or ""), "admin: has a mark")
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com", "orgs": []})
assert r.ok, r.text
O = login(B, "olga")
O.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
o0 = gen(O)
aid = A.get(B + "/api/state").json()["me"]["id"]
org = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": aid})
assert org.ok, org.text
oid = org.json().get("id") or next(x["id"] for x in A.get(B + "/api/admin/orgs").json().get("orgs", []) if x["name"] == "Alpha")
r = A.put(B + f"/api/orgs/{oid}/members", json={"email": "olga@example.com", "role": "member"})
check(r.ok, f"setup: olga joins Alpha ({r.status_code} {r.text[:120]})")
check([w["id"] for w in O.get(B + "/api/state").json()["me"]["workspaces"]] == [oid], "setup: olga is in Alpha")
o1 = gen(O)
check(o1 != o0, "member: joining an organisation = another mark")
r = A.delete(B + f"/api/orgs/{oid}/members/{O.get(B + '/api/me').json()['id']}")
check(r.ok, f"setup: olga leaves Alpha ({r.status_code} {r.text[:120]})")
o2 = gen(O)
check(o2 != o1, "member: removed from the organisation = another mark")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
