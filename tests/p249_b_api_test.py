#!/usr/bin/env python3
"""2.49.0 API tests, part B: child accounts (#1537 start without errors, #1551 the parents' PIN).
 - a child's start: every call the web client makes on start answers without 403; the onboarding marks itself done and
   creates no "Getting started" list; the tour and folders_closed save
 - the PIN: only a parent (or an admin) sets / removes it, 4 to 6 digits; stored only as a hash, never in an answer
 - with a PIN: account (PATCH /api/me), settings (except the automatic keys) and log out answer 403 {pin: true};
   ticking off stays free; the right PIN opens them for this session only (another session of the child stays closed),
   for 5 minutes (an expired opening closes again); /api/me/pin/lock closes early
 - the brake counts per child, over all its sessions: the 5th wrong PIN locks for 15 minutes (429, also with the right
   PIN and from another session) and the parent gets a push
 - removing the PIN frees everything again
usage: p249_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                   env=dict(os.environ, KALMIDO_ONBOARDING="1"))  # a new account starts with onboard / tour pending
assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"tour": "done", "features": "cal,collab,comments,family"})

# ================================================================== people: Bob (parent), Lina (kid), Eve (stranger)
ids = {"alice": 1}
for u, n, kid in (("bob", "Bob", False), ("lina", "Lina", True), ("eve", "Eve", False)):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "kid": kid})
    check(r.ok, f"user {u} " + r.text[:200])
    ids[u] = r.json()["id"]
BOB, LINA, EVE = ids["bob"], ids["lina"], ids["eve"]
check(A.patch(B + f"/api/users/{LINA}", json={"parents": [BOB]}).ok, "Bob looks after Lina")
A.patch(B + f"/api/users/{BOB}", json={"ntfy_topic": "t-bob"})
Bo, Ev = sess("bob"), sess("eve")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "push_channel": "ntfy", "features": "cal,collab,comments,family"})
L = A.post(B + "/api/lists", json={"name": "Chores"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": LINA, "role": "edit"})
T1 = A.post(B + "/api/tasks", json={"title": "Feed the cat", "list_id": L, "assignee_id": LINA}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Water the plants", "list_id": L, "assignee_id": LINA}).json()["id"]

# ================================================================== #1537: the child's start
Li = sess("lina")
st = Li.get(B + "/api/state")
check(st.ok and st.json()["me"]["kid"] is True and st.json()["settings"]["onboard"] == "pending", "state of a new child: onboard pending")
for path in ("/api/version", "/api/stale?limit=200", "/api/team", "/api/family/kids", "/api/family"):
    r = Li.get(B + path)
    check(r.status_code != 403, f"start: GET {path} -> {r.status_code}")
r = Li.post(B + "/api/onboarding", json={"touch": True, "mac": False})
check(r.status_code == 200 and r.json().get("created") is False, "start: POST /api/onboarding is no 403, creates nothing " + r.text[:200])
st = Li.get(B + "/api/state").json()
check(st["settings"]["onboard"] == "done", "the onboarding is marked done")
check(not [x for x in st["lists"] if x["owner_id"] == LINA and not x.get("is_inbox")], "no \"Getting started\" list for the child")
check(any(x["id"] == L for x in st["lists"]), "the shared list is in the child's state")
for b in ({"tour": "done"}, {"folders_closed": "[]"}):
    r = Li.patch(B + "/api/settings", json=b)
    check(r.status_code == 200, f"start: PATCH /api/settings {b} -> {r.status_code}")

# ================================================================== #1551: setting the PIN
k = lambda s: s.get(B + "/api/family/kids").json()["kids"]
check(k(Bo)[0]["id"] == LINA and k(Bo)[0]["pin"] is False, "no PIN yet")
check(Ev.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": "4821"}).status_code == 404, "a stranger cannot set the PIN")
check(Li.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": "4821"}).status_code in (403, 404), "the child cannot set its PIN")
for bad in ("123", "1234567", "12a4", "", None):
    check(Bo.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": bad}).status_code == 400, f"PIN {bad!r}: 400")
r = Bo.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": "4821"})
check(r.ok and r.json()["pin"] is True and "4821" not in r.text and "pin_hash" not in r.text and "scrypt" not in r.text, "the parent sets the PIN; the answer has no PIN / hash " + r.text[:200])
h = dbx("SELECT pin_hash, fails FROM kid_pins WHERE kid_id=?", (LINA,))
check(h and h[0][0] != "4821" and "4821" not in h[0][0] and h[0][0].split(":")[0] in ("scrypt", "pbkdf2"), "stored as a password hash " + (h[0][0][:12] if h else ""))
for s, who in ((Li, "child"), (Bo, "parent"), (A, "admin")):
    check("4821" not in s.get(B + "/api/state").text and "pin_hash" not in s.get(B + "/api/state").text, f"state of the {who}: no PIN, no hash")
check(Li.delete(B + f"/api/family/kids/{LINA}/pin").status_code in (403, 404), "the child cannot remove its PIN")

# ================================================================== with the PIN
pin_err = lambda r: r.status_code == 403 and r.json().get("pin") is True
check(pin_err(Li.patch(B + "/api/me", json={"display_name": "Queen Lina"})), "without the PIN: account 403 {pin}")
check(pin_err(Li.patch(B + "/api/settings", json={"theme": "dark"})), "without the PIN: settings 403 {pin}")
check(pin_err(Li.patch(B + "/api/settings", json={"tour": "done", "theme": "dark"})), "an automatic key does not carry another one")
check(pin_err(Li.post(B + "/api/me/2fa/totp", json={})), "without the PIN: two-factor 403 {pin}")
check(pin_err(Li.post(B + "/api/auth/logout", json={})), "without the PIN: log out 403 {pin}")
check(Li.get(B + "/api/state").ok, "... and the session still works")
check(Li.patch(B + "/api/settings", json={"tour": "done"}).ok and Li.patch(B + "/api/settings", json={"folders_closed": "[]"}).ok, "automatic settings stay free")
check(Li.post(B + f"/api/tasks/{T1}/complete", json={}).ok, "ticking off stays free")
check(Li.get(B + "/api/family/kids").json()["kids"][0]["pin"] is True and not Li.get(B + "/api/family/kids").json()["kids"][0].get("pin_open"), "the child sees: PIN on, not open")

r = Li.post(B + "/api/me/pin/unlock", json={"pin": "0000"})
check(r.status_code == 403 and r.json().get("left") == 4, "wrong PIN: 403, 4 tries left " + r.text)
r = Li.post(B + "/api/me/pin/unlock", json={"pin": "4821"})
check(r.ok and r.json().get("until"), "right PIN: open until " + r.text)
check(dbx("SELECT fails FROM kid_pins WHERE kid_id=?", (LINA,))[0][0] == 0, "the right PIN resets the count")
check(Li.patch(B + "/api/me", json={"display_name": "Lina"}).ok and Li.patch(B + "/api/settings", json={"theme": "dark"}).ok, "open: account + settings")
Li2 = sess("lina")
check(pin_err(Li2.patch(B + "/api/me", json={"display_name": "Lina"})), "another session of the child stays closed")
check(Li.post(B + "/api/me/pin/lock", json={}).ok and pin_err(Li.patch(B + "/api/me", json={"display_name": "Lina"})), "lock closes early")
Li.post(B + "/api/me/pin/unlock", json={"pin": "4821"})
dbx("UPDATE kid_pin_open SET until='2000-01-01T00:00:00+00:00' WHERE kid_id=?", (LINA,))
check(pin_err(Li.patch(B + "/api/me", json={"display_name": "Lina"})), "after the 5 minutes: closed again")

# ================================================================== the brake: per child, over its sessions, a push for the parent
n0 = len(ntfy())
codes = [Li2.post(B + "/api/me/pin/unlock", json={"pin": p}).status_code for p in ("1111", "2222", "3333", "4444")]
check(codes == [403] * 4, f"four wrong PINs: 403 {codes}")
r = Li.post(B + "/api/me/pin/unlock", json={"pin": "5555"})  # the fifth from the OTHER session
check(r.status_code == 429 and r.json().get("wait") == 900, "the fifth wrong PIN (another session): locked 15 minutes " + r.text)
check(Li.post(B + "/api/me/pin/unlock", json={"pin": "4821"}).status_code == 429 and Li2.post(B + "/api/me/pin/unlock", json={"pin": "4821"}).status_code == 429,
      "locked: also the right PIN, in every session")
check(dbx("SELECT lock_until FROM kid_pins WHERE kid_id=?", (LINA,))[0][0] > "2026", "lock_until stored")
check(until(lambda: any(x.get("topic") == "t-bob" and "PIN" in json.dumps(x) for x in ntfy()[n0:]), 10), "the parent gets a push")
check(k(Li)[0].get("pin_wait", 0) > 800, "the child sees the time left")
check(pin_err(Li.patch(B + "/api/me", json={"display_name": "Lina"})), "locked: account stays closed")
r = Bo.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": "7391"})
check(r.ok and Li.post(B + "/api/me/pin/unlock", json={"pin": "7391"}).ok, "a new PIN from the parent ends the lock")

# ================================================================== removing it
check(Bo.delete(B + f"/api/family/kids/{LINA}/pin").ok and k(Bo)[0]["pin"] is False, "the parent removes the PIN")
check(not dbx("SELECT 1 FROM kid_pins WHERE kid_id=?", (LINA,)) and not dbx("SELECT 1 FROM kid_pin_open WHERE kid_id=?", (LINA,)), "nothing of it is left")
check(Li2.patch(B + "/api/settings", json={"theme": "light"}).ok and Li2.patch(B + "/api/me", json={"display_name": "Lina"}).ok, "without a PIN: as before")
check(A.put(B + f"/api/family/kids/{LINA}/pin", json={"pin": "123456"}).ok, "an admin may set it too (like stars / rewards)")
check(Li.post(B + "/api/me/pin/unlock", json={"pin": "123456"}).ok, "six digits work")
check(Bo.post(B + "/api/me/pin/unlock", json={"pin": "123456"}).status_code == 404, "a grown-up has no PIN to open")
check(Li2.post(B + "/api/auth/logout", json={}).status_code == 403 and Li.post(B + "/api/auth/logout", json={}).ok, "log out: closed session 403, open session logs out")

print("FAILED", len(FAILS), FAILS if FAILS else "") if FAILS else print("OK", OKS[0])
sys.exit(1 if FAILS else 0)
