#!/usr/bin/env python3
"""2.145.0 API tests, part A (#2444): the data the news view needs to hint at unread items in other workspaces, own
container (start.sh). Invented names only.
 - an assignment in an organisation list is unread for me, to_me, carries the list_id, and the bell's number (unread_me) counts it
 - the same for a person without an organisation: the route works, nothing from an organisation shows up
usage: p2145_a_api_test.py <datadir>"""
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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2145A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
FEAT = "collab,comments"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]["id"]
OL = A.post(B + "/api/lists", json={"name": "Projekt Alpha", "org_id": 1}).json()["id"]
check(A.put(B + f"/api/lists/{OL}/members", json={"user_id": BOB, "role": "edit"}).ok, "alice shares the list with bob")
r = Bo.post(B + "/api/tasks", json={"title": "Angebot pruefen", "list_id": OL, "assignee_id": ME})
check(r.ok, f"bob assigns a task to alice {r.status_code} {r.text[:200]}")

# freelancer-matrix: news
j = A.get(B + "/api/news").json()
mine = [it for it in j.get("items", []) if it.get("list_id") == OL and it.get("to_me") and not it.get("read")]
check(len(mine) >= 1, f"the assignment is an unread item for me with its list {j.get('items')}")
check(j.get("unread_me", 0) >= 1, f"the bell number counts it {j.get('unread_me')}")

FID, Fr = freelancer(B, A)
r = Fr.get(B + "/api/news")
fj = r.json()
check(r.ok and fj.get("unread_me", 0) == 0 and not any(it.get("list_id") == OL for it in fj.get("items", [])),
      f"freelancer: the route works and shows nothing of the organisation {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
