#!/usr/bin/env python3
"""2.169.0 A API tests (#2671, own container): the offline copy of the knowledge pages asks GET /api/wiki with offline=1
 - offline=1&bodies=1: every page with its text, also in an open space (without offline=1 an open space still sends no texts)
 - since=<updated_at>: only the pages changed at or after it carry their text, the others only their entry (id, updated_at);
   a deleted page is no longer listed; a page moved in from another space is listed (the browser fetches everything then)
 - a space of another organisation stays closed (403), also with offline=1
 - a person without an organisation (freelancer-matrix: wiki): the private space the same way, nobody else reads it
usage: p2169_a_api_test.py <datadir>      (P2169A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer, login

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


def idx(s, sp, **kw):
    r = s.get(B + "/api/wiki", params={"space": sp, "bodies": "1", **kw})
    return r.status_code, (r.json() if r.ok else {})


def page(s, sp, path, body):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": body})
    assert r.ok, r.text
    return r.json()["id"]


if os.environ.get("P2169A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": ALICE}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"

# ---------------------------------------------------------------- every text with offline=1, only the changed ones with since
P1 = page(A, SP, "Docs/Start", "Alpha start")
P2 = page(A, SP, "Docs/Other", "Beta other")
st, j = idx(A, SP)
check(st == 200 and all("body" not in p for p in j.get("pages", [])), f"without offline=1 an open space sends no texts (as before) {st}")
st, j = idx(A, SP, offline="1")
by = {p["id"]: p for p in j.get("pages", [])}
check(st == 200 and by.get(P1, {}).get("body") == "Alpha start" and by.get(P2, {}).get("body") == "Beta other", f"offline=1: every page with its text {st} {j}")
since = max(p["updated_at"] for p in j["pages"])
time.sleep(1.1)
check(A.patch(B + f"/api/wiki/pages/{P2}", json={"body": "Beta changed"}).ok, "setup: a page changed")
P3 = page(A, SP, "Docs/New", "Gamma new")
st, j = idx(A, SP, offline="1", since=since)
by = {p["id"]: p for p in j.get("pages", [])}
check(st == 200 and set(by) == {P1, P2, P3}, f"since: every page of the space is listed {sorted(by)}")
check(by.get(P2, {}).get("body") == "Beta changed" and by.get(P3, {}).get("body") == "Gamma new", "since: the changed and the new page carry their text")
p1 = by.get(P1, {})
check(p1 and ("body" in p1) == (p1.get("updated_at", "") >= since), f"since: an unchanged page only with its entry (a text only at the same time) {p1}")
check(A.delete(B + f"/api/wiki/pages/{P3}").ok, "setup: a page deleted")
st, j = idx(A, SP, offline="1", since=since)
check(st == 200 and P3 not in {p["id"] for p in j.get("pages", [])}, "since: a deleted page is no longer listed (the browser drops it)")
# a page moved in from another space keeps its time: listed without text (the browser lacks it and asks for everything)
P4 = page(A, SP2, "Moved", "Delta moved")
time.sleep(1.1)
check(A.patch(B + f"/api/wiki/pages/{P1}", json={"body": "Alpha again"}).ok, "setup: another change")
st, j = idx(A, SP, offline="1")
since2 = max(p["updated_at"] for p in j["pages"])
r = A.post(B + "/api/wiki/move-space", json={"pages": [P4], "space": SP2, "to": SP, "dest": "", "dry": 0})
check(r.ok, f"setup: a page moved between spaces {r.status_code} {r.text[:200]}")
st, j = idx(A, SP, offline="1", since=since2)
p4 = {p["id"]: p for p in j.get("pages", [])}.get(P4)
check(p4 is not None and (p4.get("body") == "Delta moved" or ("body" not in p4 and p4["updated_at"] < since2)),
      f"since: a moved-in page is listed, with its text or with an older time {p4}")
st, j = idx(A, SP, offline="1", since="garbage' OR 1=1 --")
check(st == 200 and all("body" not in p or isinstance(p["body"], str) for p in j.get("pages", [])), f"a strange since value is only compared, never run {st}")

# ---------------------------------------------------------------- another organisation's space stays closed
A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG2]})
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
st, j = idx(Bo, SP, offline="1")
check(st in (403, 404) and not j.get("pages"), f"another organisation's space: closed, also with offline=1 {st}")
st, j = idx(Bo, SP2, offline="1")
check(st == 200, f"bob reads his own organisation's space {st}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: wiki)
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
F1 = page(Fr, "private", "Diary", "Papaya private notes")
st, j = idx(Fr, "private", offline="1")
by = {p["id"]: p for p in j.get("pages", [])}
check(st == 200 and by.get(F1, {}).get("body") == "Papaya private notes" and j.get("may_write") is not False, f"freelancer: the private space with its texts {st}")
fs = max(p["updated_at"] for p in j["pages"])
time.sleep(1.1)
F2 = page(Fr, "private", "Ideas", "Quince ideas")
st, j = idx(Fr, "private", offline="1", since=fs)
by = {p["id"]: p for p in j.get("pages", [])}
check(by.get(F2, {}).get("body") == "Quince ideas" and set(by) == {F1, F2}, f"freelancer: since sends the new text, lists both {by}")
st, j = idx(A, "private", offline="1")
check(st == 200 and not any(p["id"] in (F1, F2) for p in j.get("pages", [])), "freelancer: nobody else's private space shows the pages")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
