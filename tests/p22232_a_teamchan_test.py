#!/usr/bin/env python3
"""2.223.2 A (#2869) API tests: the creator of a closed team channel who left it no longer opens it, own container (start.sh).
Invented names only, addresses @example.com. tenant-matrix: org  freelancer-matrix: team
 - an organisation admin creates a closed channel, reads it and leaves: their read mark goes (tchat_sig_q counted it);
   PATCH {open: true}, joining themselves, adding somebody and reading the history are refused, the channel stays closed
 - the creator who is still a member opens and closes it as before
 - a person without an organisation: a channel of the own space, left, gives no way back and keeps no read mark
usage: p22232_a_teamchan_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402  shared helpers (tests/kt.py)


def usess(user, pw="password123"):
    s = sess(user, pw)
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = usess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = usess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("erin", "admin"), ("nora", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Er, No = usess("bob"), usess("erin"), usess("nora")
ERIN = uid["erin"]

# ================================================================ the creator-admin leaves a closed channel
r = Er.post(B + "/api/team/channels", json={"name": "Board room", "org_id": ORG, "open": False, "members": [uid["bob"]]})
check(r.status_code == 201, "setup: erin's closed channel " + r.text[:200])
CH = r.json()["id"]
check(Er.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "Budget for the next shoot"}).ok, "setup: a message")
check(Er.post(B + f"/api/team/rooms/{CH}/read", json={}).ok and sql("SELECT 1 FROM tchat_reads WHERE room_id=? AND user_id=?", (CH, ERIN)),
      "setup: erin's read mark")
r = Er.delete(B + f"/api/team/rooms/{CH}/members/{ERIN}")
check(r.ok, "erin leaves " + r.text[:200])
check(not sql("SELECT 1 FROM tchat_reads WHERE room_id=? AND user_id=?", (CH, ERIN)), "erin: the read mark of the left channel is gone")
r = Er.patch(B + f"/api/team/rooms/{CH}", json={"open": True})
check(r.status_code in (403, 404), f"erin (creator + admin, no member): does not open it {r.status_code} {r.text[:160]}")
check(sql("SELECT is_open FROM tchat_rooms WHERE id=?", (CH,))[0][0] == 0, "the channel stays closed")
r = Er.post(B + f"/api/team/rooms/{CH}/members", json={"user_id": ERIN})
check(r.status_code in (403, 404), f"erin: does not join it again {r.status_code} {r.text[:160]}")
r = Er.post(B + f"/api/team/rooms/{CH}/members", json={"user_id": uid["nora"]})
check(r.status_code in (403, 404), f"erin: adds nobody to it {r.status_code} {r.text[:160]}")
check(not sql("SELECT 1 FROM tchat_members WHERE room_id=? AND user_id IN (?,?)", (CH, ERIN, uid["nora"])), "nobody new in it")
r = Er.get(B + f"/api/team/rooms/{CH}/messages")
check(r.status_code in (403, 404), f"erin: its history stays closed {r.status_code}")
check(Bo.get(B + f"/api/team/rooms/{CH}/messages").ok, "bob (member): reads it as before")

# the creator who is still a member: as before
r = Er.post(B + "/api/team/channels", json={"name": "Planning", "org_id": ORG, "open": False})
CH2 = r.json()["id"] if r.status_code == 201 else None
check(CH2 and Er.patch(B + f"/api/team/rooms/{CH2}", json={"open": True}).ok, "erin (creator, member): opens her channel")
check(Er.patch(B + f"/api/team/rooms/{CH2}", json={"open": False}).ok, "and closes it again")
r = Er.post(B + f"/api/team/rooms/{CH2}/members", json={"user_id": uid["nora"]})
check(r.ok, "erin (member): adds nora to her closed channel " + r.text[:160])

# ================================================================ a person without an organisation (own space)
FID, Fr = freelancer(B, A)  # freelancer-matrix: team
r = Fr.post(B + "/api/team/channels", json={"name": "Notes", "org_id": None})
FC = r.json()["id"] if r.status_code == 201 else None
check(FC, "frida: a channel of her own space " + r.text[:200])
check(Fr.post(B + f"/api/team/rooms/{FC}/read", json={}).ok, "frida: reads it")
check(Fr.delete(B + f"/api/team/rooms/{FC}/members/{FID}").ok, "frida: leaves it")
check(not sql("SELECT 1 FROM tchat_reads WHERE room_id=? AND user_id=?", (FC, FID)), "frida: no read mark left")
check(Fr.post(B + f"/api/team/rooms/{FC}/members", json={"user_id": FID}).status_code in (403, 404), "frida: no way back in")

print(f"p22232_a_teamchan: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
