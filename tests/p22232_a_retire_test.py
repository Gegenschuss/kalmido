#!/usr/bin/env python3
"""2.223.2 A (#2859) API tests: a retired organisation cannot be entered again, own container (start.sh, mode workspaces,
server key). Invented companies only. freelancer-matrix: office  tenant-matrix: org
 - the retirement drops the open invitations of existing accounts (org_joins) and the e-mail invitations (org_invites)
 - accepting an invitation into a retired organisation is 404, also for an invitation row left from before the fix,
   and it is not listed under GET /api/orgs "joins"
 - a membership row left in a retired organisation grants nothing: the organisation is not in GET /api/orgs, members PUT /
   invites POST / PATCH / icon POST + DELETE answer 409; a person without such a row still gets 404 (the boundary)
 - the former admin still exports it; a live organisation and a person without organisation work as before
usage: p22232_a_retire_test.py <datadir>"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,files,docs,office,clients"
O = "/api/office"
KEYENV = " -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces" + KEYENV)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("dora", "Dora Director"), ("bob", "Bob Member"), ("carl", "Carl Outside")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Do, Bo, Ca = sess("dora"), sess("bob"), sess("carl")
DORA, BOB = Do.get(B + "/api/me").json()["id"], Bo.get(B + "/api/me").json()["id"]
for s in (A, Do, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

# ================================================================== invitations open at the retirement
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Studio", "admin_id": DORA}).json()["id"]
r = Do.put(B + f"/api/orgs/{GAM}/members", json={"email": "bob@example.com", "role": "admin"})
check(r.ok and sql("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (GAM, BOB)), "Gamma: bob invited (org_joins) " + r.text[:160])
r = Do.post(B + f"/api/orgs/{GAM}/invites", json={"email": "newcomer@example.com", "role": "member"})
check(r.ok and sql("SELECT 1 FROM org_invites WHERE org_id=?", (GAM,)), "Gamma: a new account invited (org_invites) " + r.text[:160])
Do.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
r = Do.post(B + O + "/docs", json={"project_title": "Event film"})
DOC = r.json().get("id") if r.status_code == 201 else None
check(DOC, "Gamma: a document " + r.text[:160])
sql("UPDATE office_docs SET locked_at=?, status='issued', number='RE-2025-007', date='2025-11-20' WHERE id=?", (now(), DOC), write=True)
r = A.delete(B + f"/api/admin/orgs/{GAM}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True, "Gamma: retired " + r.text[:200])
if not r.ok:
    app_log()
check(not sql("SELECT 1 FROM org_joins WHERE org_id=?", (GAM,)), "Gamma: the open invitations of existing accounts are gone")
check(not sql("SELECT 1 FROM org_invites WHERE org_id=?", (GAM,)), "Gamma: the e-mail invitations are gone")
check(not sql("SELECT 1 FROM org_members WHERE org_id=?", (GAM,)), "Gamma: nobody is a member (as before)")
check(Bo.post(B + f"/api/orgs/{GAM}/join").status_code == 404, "bob: accepting after the retirement = 404")

# an invitation row left from before the fix: still 404, not listed
sql("INSERT INTO org_joins(org_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (GAM, BOB, "admin", DORA, now()), write=True)
check(not any(j["org_id"] == GAM for j in (Bo.get(B + "/api/orgs").json().get("joins") or [])), "bob: the old invitation is not listed")
r = Bo.post(B + f"/api/orgs/{GAM}/join")
check(r.status_code == 404 and not sql("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (GAM, BOB)),
      f"bob: an old invitation does not let him in {r.status_code} {r.text[:120]}")
check(Bo.delete(B + f"/api/orgs/{GAM}/join").status_code == 404, "bob: declining it = 404 as well")

# a membership row left from before the fix: grants nothing, every admin change 409
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?)", (GAM, BOB, "admin"), write=True)
check(not any(o["id"] == GAM for o in Bo.get(B + "/api/orgs").json().get("orgs") or []), "bob: the retired organisation is not one of his")
check(Bo.get(B + f"/api/office/docs/{DOC}").status_code in (403, 404), "bob: its document stays closed")
for what, r in (("members PUT", Bo.put(B + f"/api/orgs/{GAM}/members", json={"email": "carl@example.com", "role": "admin"})),
                ("invites POST", Bo.post(B + f"/api/orgs/{GAM}/invites", json={"email": "second@example.com"})),
                ("PATCH", Bo.patch(B + f"/api/orgs/{GAM}", json={"name": "Taken over"})),
                ("icon POST", Bo.post(B + f"/api/orgs/{GAM}/icon", files={"file": ("i.png", b"\x89PNG\r\n\x1a\n")})),
                ("icon DELETE", Bo.delete(B + f"/api/orgs/{GAM}/icon"))):
    check(r.status_code == 409, f"bob (old row): {what} = 409 {r.status_code} {r.text[:120]}")
check(sql("SELECT name FROM orgs WHERE id=?", (GAM,)) == [("Gamma Studio",)], "Gamma: name unchanged")
check(sql("SELECT user_id FROM org_joins WHERE org_id=?", (GAM,)) == [(BOB,)], "Gamma: nobody new invited (only the old row)")
check(Ca.patch(B + f"/api/orgs/{GAM}", json={"name": "x"}).status_code == 404, "carl (never in it): 404 as before (boundary)")
sql("DELETE FROM org_members WHERE org_id=? AND user_id=?", (GAM, BOB), write=True)

# the former admin keeps the export
ret = Do.get(B + "/api/orgs").json().get("retired") or []
check([o["id"] for o in ret] == [GAM], f"dora: Gamma under retired {ret}")
r = Do.get(B + f"/api/orgs/{GAM}/export")
check(r.ok and r.json().get("enabled") is True, f"dora: the export of retired Gamma {r.status_code} {r.text[:160]}")

# ================================================================== a live organisation as before
LIV = A.post(B + "/api/admin/orgs", json={"name": "Live Works", "admin_id": DORA}).json()["id"]
check(Do.put(B + f"/api/orgs/{LIV}/members", json={"email": "carl@example.com"}).ok and Ca.post(B + f"/api/orgs/{LIV}/join").ok,
      "Live: invitation + accept work")
check(any(o["id"] == LIV for o in Ca.get(B + "/api/orgs").json().get("orgs") or []), "carl: member of Live")
r = Do.patch(B + f"/api/orgs/{LIV}", json={"color": ""})
check(r.ok, "Live: its admin changes it " + r.text[:120])

# ================================================================== a person without organisation (own office)
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office
r = Fr.post(B + O + "/docs", json={"project_title": "Corporate film"})
check(r.status_code == 201, "frida: her own office works " + r.text[:160])
r = Fr.get(B + "/api/orgs")
check(r.ok and r.json().get("orgs") == [] and r.json().get("joins") == [], "frida: no organisations, no invitations " + r.text[:160])

print(f"p22232_a_retire: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
