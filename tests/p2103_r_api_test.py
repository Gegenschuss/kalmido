#!/usr/bin/env python3
"""2.103.0 API test (leader, #2165): the switch of the retention runs and GET /api/admin/retention.
Invented accounts only (example.com).
 - instance admins only (an organisation member, a person without an organisation and nobody get 401 / 403)
 - every kind (trash, logs, backups, files, chat) with its period, its env names and the switch; the test server runs
   without KALMIDO_RETENTION_PURGE, so every kind is off (count only) -- the safe default of an update
 - numbers only: no user names or mail addresses in the answer
usage: p2103_r_api_test.py <datadir>      (a fresh server on KALMIDO_TEST_PORT)
freelancer-matrix: admin"""
import os
import sys

import requests
from freelancer_fixture import freelancer

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123",
                                      "email": "bob@example.com"}).ok
Bo = sess("bob")
FID, Fr = freelancer(B, A)

r = A.get(B + "/api/admin/retention")
check(r.ok, f"#2165: the instance admin reads the retention runs {r.status_code} {r.text[:200]}")
j = r.json() if r.ok else {}
kinds = j.get("kinds") or {}
check(set(kinds) == {"trash", "logs", "backups", "files", "chat"}, f"#2165: every kind is listed {sorted(kinds)}")
check(j.get("general_switch") == "KALMIDO_RETENTION_PURGE", "#2165: the general switch is named")
check(all(k.get("on") is False for k in kinds.values()), f"#2165: without the switch every run only counts {kinds}")
check((kinds.get("trash") or {}).get("days") == 30 and (kinds.get("trash") or {}).get("env_days") == "KALMIDO_TRASH_DAYS",
      f"#2165: the trash period 30 days, KALMIDO_TRASH_DAYS {kinds.get('trash')}")
check((kinds.get("logs") or {}).get("days") == 400, f"#2171: the log period 400 days {kinds.get('logs')}")
check((kinds.get("backups") or {}).get("env_switch") == "KALMIDO_PURGE_BACKUPS", "#2172: the switch of one kind")
check((j.get("legal_years") or {}).get("receipt") == 8 and (j.get("legal_years") or {}).get("book") == 10,
      f"#2168: legal retention receipts 8, books 10 years {j.get('legal_years')}")
check("alice" not in r.text and "example.com" not in r.text, "#2165: numbers only, no account names")
check(Bo.get(B + "/api/admin/retention").status_code == 403, "#2165: a member who is no instance admin: 403")
check(Fr.get(B + "/api/admin/retention").status_code == 403, "#2165: a person without an organisation: 403")
check(requests.get(B + "/api/admin/retention", headers=H).status_code in (401, 403), "#2165: nobody signed in: 401 / 403")

print(f"p2103_r_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
