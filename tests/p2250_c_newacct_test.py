#!/usr/bin/env python3
"""2.250.0 C (#2995) API test, own container (start.sh). Invented names only, addresses @example.com.
 - an account the admin adds starts with the FULL sidebar like the self-set-up one: "Tomorrow", "Next 7 days", "Now doable"
   are not hidden (2.25.0 UX-26 hid them); a person without an organisation too (freelancer-matrix: settings)
 - existing accounts keep their choice: a hidden entry stays hidden (nothing is rewritten)
 - the tick in the unfolded "+ N more views" writes the same setting as Settings > Appearance > Sidebar (a valid sidebar value)
Without the change in core/db.py create_user the first two checks are red (the added account's sidebar hides the three entries)."""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
from kt import FAILS, OKS, check, sess  # noqa: E402

import requests  # noqa: E402

s0 = requests.Session()
s0.headers.update({"X-Requested-With": "kalmido"})
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"username": "dora", "display_name": "Dora", "password": "password123", "email": "dora@example.com"})
check(r.ok, "admin adds an account " + r.text[:160])
D = sess("dora")
hid = lambda s: json.loads(s.get(B + "/api/state").json()["settings"].get("sidebar") or "{}").get("hidden", [])
check(not hid(D), "#2995: an added account starts with the full sidebar " + json.dumps(hid(D)))
FID, Fr = freelancer(B, A)
check(not hid(Fr), "#2995: a person without an organisation too " + json.dumps(hid(Fr)))
# an existing account keeps what it chose
check(D.patch(B + "/api/settings", json={"sidebar": json.dumps({"order": [], "hidden": ["e:week"]})}).ok, "dora hides one view")
check(hid(D) == ["e:week"], "#2995: the choice of an existing account stays " + json.dumps(hid(D)))
# the tick of the unfolded list: the entry leaves "hidden"
check(D.patch(B + "/api/settings", json={"sidebar": json.dumps({"order": [], "hidden": []})}).ok and hid(D) == [], "#2995: the tick shows the view again")
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
