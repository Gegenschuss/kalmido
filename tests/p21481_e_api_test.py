#!/usr/bin/env python3
"""2.148.1 API tests, part E (#2496 hardening, a selection), own container (start.sh). Invented names only, @example.com.
tenant-matrix: org
freelancer-matrix: office
 - the document number route: office admin / own office yes, a plain member 403
 - own timesheet: a second admin approves it (403 for the person themself), the only admin and a person without an organisation as before
 - bad ids / limits of the time entries answer 400, not 500
 - inbound webhook: an oversized request is 413 before anything is read; unknown tokens from one address are slowed down (429)
usage: p21481_e_api_test.py <datadir>      (P21481E_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
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
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "tz": "Europe/Berlin"})
    assert r.ok, (user, r.text)
    return s


def doc_id(r):
    j = r.json() if r.ok else {}
    return j.get("id") or (j.get("doc") or {}).get("id")


if not os.environ.get("P21481E_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "time"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
FID, Fr = freelancer(B, A)

# ================================================================ #2496: the document number route
check(A.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800}).status_code in (200, 201), "setup: a service")
da = doc_id(A.post(B + "/api/office/docs", json={"project_title": "Spring campaign"}))
db_ = doc_id(Bo.post(B + "/api/office/docs", json={"project_title": "Summer campaign"}))
check(da and db_, "setup: documents of the admin and the member")
if db_:
    check(Bo.post(B + f"/api/office/docs/{db_}/number", json={}).status_code == 403, "the number route: a plain member is refused")
if da:
    r = A.post(B + f"/api/office/docs/{da}/number", json={})
    check(r.status_code in (200, 409), f"the number route: the office admin is not refused ({r.status_code} {r.text[:120]})")
fd = doc_id(Fr.post(B + "/api/office/docs", json={"project_title": "Own job"}))
check(fd, "freelancer-matrix: office - a document in the own office")
if fd:
    r = Fr.post(B + f"/api/office/docs/{fd}/number", json={})
    check(r.status_code in (200, 409), f"freelancer-matrix: office - the own office numbers itself ({r.status_code} {r.text[:120]})")

# ================================================================ #2496: time entries answer 400
check(Bo.post(B + "/api/time/stop", json={"id": "abc"}).status_code in (400, 404, 409), "a bad entry id is no server error")
check(Bo.post(B + "/api/time/stop", json={"id": [1]}).status_code < 500, "an entry id of the wrong type is no server error")
check(Bo.get(B + "/api/time/entries", params={"limit": "abc"}).status_code == 400, "a bad limit: 400")
check(Bo.post(B + "/api/time/entries", json={"list_id": 1, "start": "2026-01-05T10:00:00Z", "minutes": "inf"}).status_code < 500,
      "an infinite number of minutes is no server error")

# ================================================================ #2496: the own timesheet needs a second admin
now = datetime.now(timezone.utc)
BER = ZoneInfo("Europe/Berlin")
cur = now.astimezone(BER).date().replace(day=1)
prev = (cur - timedelta(days=1)).replace(day=1)
M = prev.strftime("%Y-%m")
L = A.post(B + "/api/lists", json={"name": "Harbour site", "time_tracking": True}).json()["id"]
start = datetime(prev.year, prev.month, 15, 10, 0, tzinfo=BER).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
check(A.post(B + "/api/time/entries", json={"list_id": L, "start": start, "minutes": 60}).ok, "setup: an entry of last month")
check(A.post(B + "/api/time/sheets", json={"month": M, "action": "close"}).ok, "setup: the admin closes the month")
dec = lambda s, who, act: s.post(B + "/api/time/sheets/decide", json={"user_id": who, "month": M, "action": act})  # noqa: E731
r = dec(A, uid["alice"], "approve")
check(r.ok, f"the only admin approves their own month as before ({r.status_code} {r.text[:120]})")
check(dec(A, uid["alice"], "unapprove").ok, "Undo of the approval")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carol"], "role": "admin"}).ok, "setup: a second admin")
r = dec(A, uid["alice"], "approve")
check(r.status_code == 403, f"with a second admin: no approving of one's own month ({r.status_code})")
r = dec(Ca, uid["alice"], "approve")
check(r.ok, f"the second admin approves it ({r.status_code} {r.text[:120]})")
# 2.148.1 G (#2496): a deactivated second admin does not count
check(dec(Ca, uid["alice"], "unapprove").ok, "setup: Undo again")
check(A.patch(B + f"/api/users/{uid['carol']}", json={"disabled": True}).ok, "setup: the second admin deactivated")
r = dec(A, uid["alice"], "approve")
check(r.ok, f"the other admin deactivated: the only active admin approves ({r.status_code} {r.text[:120]})")
A.patch(B + f"/api/users/{uid['carol']}", json={"disabled": False})

# ================================================================ #2496: inbound webhook
big = requests.post(B + "/api/hooks/in/" + "a" * 30, data=b"x" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"})
check(big.status_code == 413, f"an oversized request: 413 ({big.status_code})")
codes = {requests.post(B + "/api/hooks/in/" + os.urandom(12).hex(), json={"title": "x"}).status_code for _ in range(45)}
check(404 in codes and 429 in codes, f"unknown tokens: 404 first, then slowed down ({sorted(codes)})")

print(f"p21481_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
