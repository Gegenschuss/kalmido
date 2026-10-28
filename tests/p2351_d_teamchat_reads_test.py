#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 D (#3214) API tests: leaving the organisation takes the read marks of its team chat rooms along, own container (start.sh).
Invented names only, addresses @example.com. tenant-matrix: org  freelancer-matrix: team
 - bob (member) has read marks in a channel of the organisation, the chat of a list of it and a direct message with alice;
   he leaves the organisation: the marks of the channel and the list chat are gone (tchat_sig_q counted them), the direct one stays
 - nora is taken out by the admin (the same way): her channel mark goes too; alice's marks stay
 - a person without an organisation: the read mark of her own channel stays untouched by the others leaving
 - 2.373.0 (#3337): a group (no organisation, bob stays a member) keeps bob's read mark after he leaves
usage: p2351_d_teamchat_reads_test.py <datadir>"""
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


def marks(u, rooms):
    return {x[0] for x in sql("SELECT room_id FROM tchat_reads WHERE user_id=?", (u,))} & set(rooms)


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
for u in ("bob", "nora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, No = usess("bob"), usess("nora")
BOB, NORA = uid["bob"], uid["nora"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ================================================================ setup: read marks in the organisation's rooms + a DM
r = A.post(B + "/api/team/channels", json={"name": "Studio", "org_id": ORG, "open": False, "members": [BOB, NORA]})
check(r.status_code == 201, "setup: alice's channel " + r.text[:200])
CH = r.json()["id"]
check(A.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "Shoot moves to Friday"}).ok, "setup: a channel message")
L = A.post(B + "/api/lists", json={"name": "Spring campaign", "org_id": ORG, "kind": "project"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the list")
rooms = Bo.get(B + "/api/team").json().get("rooms") or []
LR = next((x["id"] for x in rooms if x.get("list_id") == L), None)
check(LR, "setup: the list chat " + str(rooms)[:300])
check(A.post(B + f"/api/team/rooms/{LR}/messages", json={"body": "Brief is in the list"}).ok, "setup: a list chat message")
r = Bo.post(B + "/api/team/dm", json={"user_id": ALICE})
DM = r.json().get("id") if r.ok else None
check(DM and Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Quick question"}).ok, "setup: a direct message " + r.text[:200])
for s, who in ((Bo, "bob"), (No, "nora"), (A, "alice")):
    for rid in ((CH, LR, DM) if who == "bob" else (CH, LR) if who == "alice" else (CH,)):
        check(s.post(B + f"/api/team/rooms/{rid}/read", json={}).ok, f"setup: {who} reads room {rid}")
check(marks(BOB, (CH, LR, DM)) == {CH, LR, DM}, "setup: bob's three read marks")
r = A.post(B + "/api/team/groups", json={"members": [BOB, NORA], "name": "Lunch"})
GR = r.json().get("id") if r.status_code == 201 else None
check(GR and Bo.post(B + f"/api/team/rooms/{GR}/read", json={}).ok and marks(BOB, (GR,)) == {GR}, "setup: a group, bob's read mark there " + r.text[:200])
check(marks(NORA, (CH,)) == {CH}, "setup: nora's read mark")

# ================================================================ a person without an organisation (own space)
FID, Fr = freelancer(B, A)  # freelancer-matrix: team
r = Fr.post(B + "/api/team/channels", json={"name": "Notes", "org_id": None})
FC = r.json()["id"] if r.status_code == 201 else None
check(FC and Fr.post(B + f"/api/team/rooms/{FC}/read", json={}).ok, "frida: reads her own channel " + r.text[:200])

# ================================================================ bob leaves, nora is taken out
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{BOB}")
check(r.ok, "bob leaves the organisation " + r.text[:200])
check(not marks(BOB, (CH, LR)), "#3214: bob's read marks of the organisation's channel and list chat are gone " + str(marks(BOB, (CH, LR))))
check(marks(BOB, (DM,)) == {DM}, "#3214: bob's direct message keeps its read mark")
check(marks(BOB, (GR,)) == {GR}, "2.373.0 (#3337): the group (no organisation, bob stays in it) keeps his read mark")
r = A.delete(B + f"/api/orgs/{ORG}/members/{NORA}")
check(r.ok, "alice takes nora out " + r.text[:200])
check(not marks(NORA, (CH,)), "#3214: nora's read mark of the channel is gone")
check(marks(ALICE, (CH, LR)) == {CH, LR}, "#3214: alice (stays) keeps her read marks")
check(marks(FID, (FC,)) == {FC}, "#3214: frida (no organisation) keeps hers")
check(Bo.get(B + "/api/version").ok and Bo.get(B + "/api/team").ok, "bob: version and team overview still answer")

print(f"p2351_d_teamchat_reads: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
