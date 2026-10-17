#!/usr/bin/env python3
"""2.58.0 API tests, part A (#1792, #1724): small hardening of accounts and organisations. Invented names only.
 - #1792 L4: a connection request to an account that gets disabled stays in the sender's "sent" list (dropping it would
   tell the sender about the deactivation); the disabled account is still not offered as incoming / connected
 - #1724: a group member outside the organisation, taken out of an organisation's list by the boundary clean-up, does
   not come back when the group's members change (grp_sync skips people outside the list's organisation)
 - #1724: a group picture upload stores the photo and keeps exactly one file per group (the old one goes)
usage: p258_a_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TS = "2026-01-01T00:00:00+00:00"
# a 1x1 PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]

# ---- #1792 L4: a disabled target stays in "sent"
dbx("INSERT INTO conn_requests(from_id,to_id,status,created_at) VALUES(?,?,?,?)", (BOB, CAROL, "open", TS), write=True)
Bo = sess("bob")
sent = lambda: [x["person"]["id"] for x in Bo.get(B + "/api/disc").json()["outgoing"]]  # noqa: E731
check(sent() == [CAROL], f"bob sees his request to carol as sent ({sent()})")
r = A.patch(B + f"/api/users/{CAROL}", json={"disabled": True})
check(r.ok, f"alice disables carol ({r.status_code} {r.text[:120]})")
check(sent() == [CAROL], f"#1792 L4: the request stays in bob's sent list after carol was disabled ({sent()})")
A.patch(B + f"/api/users/{CAROL}", json={"disabled": False})

# ---- #1724: a group's member outside the list's organisation does not come back after the clean-up
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, BOB, DAVE], "admins": [1]})
r = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [1, BOB]})
assert r.ok, r.text
GID = r.json()["id"]
r = A.post(B + "/api/lists", json={"name": "Alpha list", "org_id": ALPHA})
assert r.ok, r.text
LID = r.json()["id"]
check(A.put(B + f"/api/lists/{LID}/groups/{GID}", json={"role": "edit"}).ok, "the list is shared with the group")
mem = lambda: sorted(x[0] for x in dbx("SELECT user_id FROM list_members WHERE list_id=?", (LID,)))  # noqa: E731
check(BOB in mem(), f"bob is in the list through the group ({mem()})")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ALPHA, BOB), write=True)  # bob left the organisation behind its back
j = A.get(B + "/api/admin/orgs").json()["boundary"]
check(j["kinds"].get("group") == 1, f"the boundary check finds bob's group row ({j['kinds']})")
r = A.post(B + "/api/admin/orgs/boundary/repair")
check(r.ok and r.json()["removed"] == 1, f"clean up removes it ({r.text[:160]})")
check(BOB not in mem(), "bob is out of the list")
r = A.patch(B + f"/api/admin/groups/{GID}", json={"members": [1, BOB, DAVE]})
check(r.ok, f"the group gets a new member ({r.status_code})")
check(DAVE in mem() and BOB not in mem(), f"#1724: the group sync adds dave (in the organisation) but not bob again ({mem()})")
j = A.get(B + "/api/admin/orgs").json()["boundary"]
check(not j["kinds"], f"#1724: the boundary check stays clean ({j['kinds']})")

# ---- #1724: group picture -- one file per group, the old one goes
AVD = os.path.join(DATA, "attachments", "avatars")
files = lambda: sorted(f for f in (os.listdir(AVD) if os.path.isdir(AVD) else []) if f.startswith(f"g{GID}-"))  # noqa: E731
for i in range(2):
    r = A.post(B + f"/api/admin/groups/{GID}/avatar", files={"file": ("p.png", PNG, "image/png")})
    check(r.ok and "/api/group-avatar/" in r.json().get("avatar", ""), f"upload {i + 1} ({r.status_code} {r.text[:120]})")
check(len(files()) == 1, f"#1724: exactly one picture file of the group ({files()})")
check(A.delete(B + f"/api/admin/groups/{GID}/avatar").ok and not files(), "removing the picture removes its file")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
