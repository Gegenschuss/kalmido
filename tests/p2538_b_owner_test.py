#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.538.0 part B (#4371): a project of an organisation only ever goes to a member or admin of it -- every way it changes
hands uses the rule of "Transfer ownership" (list_owner_set: org_writes, else 409). Own container in mode workspaces,
invented names only, addresses @example.com.
 - an organisation admin hands a list over (POST /api/orgs/<oid>/lists/<lid>/owner): guest / read-only 409, member ok
 - the owner hands it over (POST /api/lists/<lid>/owner): guest 409 (unchanged, now the shared helper)
 - handing a folder's lists (POST /api/folders/owner): to a guest every list is skipped with the reason, to a member moved
 - removing a member with ?to= (DELETE /api/orgs/<oid>/members/<uid>) and its preview (GET leave-info): guest / read-only
   409 (the asker is an organisation admin, who sees the roles; an account from outside stays 400 as in #4076), member ok
 - the heir when the last admin is taken out by the instance admin (_members_gone): an instance admin who is only a guest
   of the organisation takes over as admin, never as a guest owning the projects
 - a person without an organisation (freelancer-matrix: lists): no handover in somebody else's organisation, an own folder
   still hands over nothing to an unknown person (404)
usage: p2538_b_owner_test.py <datadir>      (P2538B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

if os.environ.get("P2538B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol", "dave", "gina", "rita"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, GINA, RITA = (ids[u] for u in ("bob", "carol", "dave", "gina", "rita"))
MSG = "Only a member or admin of the organisation can own its projects"

r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]


def user(u):
    s = sess(u)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "workspace": f"org:{ORG}", "features": FEATURES})
    return s


Bo = user("bob")
for u, role in (("carol", "member"), ("dave", "member"), ("gina", "guest"), ("rita", "readonly")):
    check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": role}).ok and org_join(B, u, ORG),
          f"setup: {u} joins Alpha as {role}")
Ca, Da = user("carol"), user("dave")
SESS = {}
SESS.update({BOB: Bo, CAROL: Ca, DAVE: Da, ALICE: A})


def new_list(s, name, share=CAROL, **kw):
    """A project of Alpha, shared with one more person (the organisation admins' overview only knows shared ones)."""
    r = s.post(B + "/api/lists", json={"name": name, "org_id": ORG, **kw})
    assert r.ok, r.text
    lid = r.json()["id"]
    if share:
        assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": share, "role": "edit"}).ok
    return lid


def owner_of(lid):
    """Who owns lid: the one of the people here whose state names it with the role owner."""
    for u, s in SESS.items():
        x = {y["id"]: y for y in s.get(B + "/api/state").json()["lists"]}.get(lid)
        if x and x.get("role") == "owner":
            return u
    return None


# ---- an organisation admin hands a list over (oadm_owner)
L1 = new_list(Bo, "Handover")
for who, u in (("guest", GINA), ("read-only", RITA)):
    r = Bo.post(B + f"/api/orgs/{ORG}/lists/{L1}/owner", json={"user_id": u})
    check(r.status_code == 409 and MSG in r.text, f"org admin handover to a {who}: 409 ({r.status_code} {r.text[:160]})")
check(owner_of(L1) == BOB, f"the list stayed with Bob ({owner_of(L1)})")
r = Bo.post(B + f"/api/orgs/{ORG}/lists/{L1}/owner", json={"user_id": CAROL})
check(r.ok, f"org admin handover to a member: ok ({r.status_code} {r.text[:160]})")
check(owner_of(L1) == CAROL, f"the list is Carol's now ({owner_of(L1)})")
# ---- the owner hands it over (list_owner_set, the shared helper since #4371)
r = Ca.post(B + f"/api/lists/{L1}/owner", json={"user_id": GINA})
check(r.status_code == 409 and MSG in r.text, f"owner handover to a guest: 409 ({r.status_code} {r.text[:160]})")
r = Ca.post(B + f"/api/lists/{L1}/owner", json={"user_id": BOB})
check(r.ok, f"owner handover to an admin: ok ({r.status_code} {r.text[:160]})")

# ---- a folder's lists (sh_folder_owner)
F = "Shared work"
L2, L3 = new_list(Bo, "Folder one", folder=F), new_list(Bo, "Folder two", folder=F)
for who, u in (("guest", GINA), ("read-only", RITA)):
    r = Bo.post(B + "/api/folders/owner", json={"folder": F, "user_id": u})
    j = r.json() if r.ok else {}
    sk = j.get("skipped", [])
    check(r.ok and j.get("moved") == 0 and {x["id"] for x in sk} == {L2, L3} and all(MSG in x["reason"] for x in sk),
          f"folder handover to a {who}: nothing moved, both skipped with the reason ({r.status_code} {r.text[:200]})")
check(owner_of(L2) == BOB and owner_of(L3) == BOB, "the folder's lists stayed with Bob")
r = Bo.post(B + "/api/folders/owner", json={"folder": F, "user_id": CAROL})
check(r.ok and r.json().get("moved") == 2, f"folder handover to a member: both moved ({r.text[:200]})")

# ---- removing a member with ?to= and its preview (org_heir_to)
L4 = new_list(Da, "Daves project")
check(owner_of(L4) == DAVE, "setup: Dave owns his project")
for who, u in (("guest", GINA), ("read-only", RITA)):
    r = Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": DAVE, "to": u})
    check(r.status_code == 409 and MSG in r.text, f"leave-info ?to= a {who}: 409 ({r.status_code} {r.text[:160]})")
    r = Bo.delete(B + f"/api/orgs/{ORG}/members/{DAVE}", params={"to": u})
    check(r.status_code == 409, f"removal ?to= a {who}: 409 ({r.status_code} {r.text[:160]})")
check(Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": DAVE, "to": 99999}).status_code == 400,
      "leave-info ?to= an unknown account: still 400 (#4076)")
check(owner_of(L4) == DAVE, "Dave is still in Alpha with his project")
j = Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": DAVE, "to": CAROL}).json()
check(j.get("heir") == "Carol", f"leave-info ?to= a member names them ({j.get('heir')})")
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{DAVE}", params={"to": CAROL})
check(r.ok and r.json().get("transferred") == 1, f"removal ?to= a member: the project goes to Carol ({r.text[:160]})")
check(owner_of(L4) == CAROL, f"Dave's project is Carol's ({owner_of(L4)})")

# ---- the heir when the last admin goes (_members_gone): the instance admin is only a guest of Alpha
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_add": [ALICE]}).ok, "setup: Alice joins Alpha")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": ALICE, "role": "guest"}).ok, "setup: Bob makes Alice a guest")
L5 = new_list(Bo, "Bobs last")
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_remove": [BOB]})
check(r.ok, f"the instance admin takes Bob, the only admin, out ({r.status_code} {r.text[:160]})")
org = next((o for o in A.get(B + "/api/admin/orgs").json().get("orgs", []) if o["id"] == ORG), {})
check(ALICE in org.get("admins", []), f"the heir took over as admin, not as a guest ({org.get('admins')})")
check(owner_of(L5) == ALICE, f"Bob's project went to Alice, now an admin ({owner_of(L5)})")

# ---- freelancer-matrix: lists
FID, Fr = freelancer(B, A)
check(Fr.post(B + f"/api/orgs/{ORG}/lists/{L1}/owner", json={"user_id": FID}).status_code in (403, 404),
      "freelancer: no handover in somebody else's organisation")
r = Fr.post(B + "/api/lists", json={"name": "Own", "folder": "Mine", "org_id": None})
check(r.ok, f"freelancer: an own list in a folder ({r.text[:120]})")
check(Fr.post(B + "/api/folders/owner", json={"folder": "Mine", "user_id": GINA}).status_code == 404,
      "freelancer: the own folder goes to nobody they cannot see (404)")
r = Fr.post(B + f"/api/lists/{r.json().get('id')}/owner", json={"user_id": FID})
check(r.status_code in (400, 404, 409), f"freelancer: the own list keeps its rules ({r.status_code})")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
