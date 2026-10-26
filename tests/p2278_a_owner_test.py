#!/usr/bin/env python3
"""2.278.0 part A (#3093, #3095): the organisation export belongs to its starter; the organisation import invites.
Invented names only.
 - #3093: alice and bob administer Alpha; alice starts the export. bob sees only that an export of alice exists (no file
   name), gets 403 on download, delete and a new start; alice downloads. After bob removes alice from Alpha, bob may
   replace the archive and download his own.
 - #3095: dave (admin of Gamma, no member of Alpha) imports alice's archive into Gamma: the preview names the roles of the
   file (bob admin, carol member); the ticked existing accounts are NOT added but invited with the confirmed role (an
   unknown role = member); their rows stay with dave, no project is shared with them; bob accepts and is admin.
 - P4: a person without organisation imports the same archive into the private space: nobody is invited, the ticked
   person gets the projects shared as before.
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY.
usage: p2278_a_owner_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import hashlib
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # noqa: E402 -- shared helpers (tests/kt.py)


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def wait_export(s, oid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/orgs/{oid}/export").json()
        if j.get("state") != "running":
            return j
        time.sleep(0.25)
    return j


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


# ---------------------------------------------------------------- server, people, organisations
env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Start", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ids = {}
for u, n in (("bob", "Bob Zweitadmin"), ("carol", "Carol Mitglied"), ("dave", "Dave Ziel")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Dv = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Dv):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "collab,comments,time", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Export", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"}).ok
# 2.278.0 review M2: an admin of Alpha without an address (key "id<old id>" in the preview) keeps the file's role there too
r = A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin Ohneadresse", "password": "password123", "email": "erin@example.com"})
assert r.ok, r.text
ERIN = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "erin@example.com", "role": "admin"}).ok
assert A.patch(B + f"/api/users/{ERIN}", json={"email": ""}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": DAVE})
assert r.status_code == 201, r.text
GAMMA = r.json()["id"]


def connect_people(s, uid, others):
    """Workspaces mode shows only members of my organisations + connections: a private list in common connects them (the
    import finds only people the importer may see, review M1)."""
    lid = s.post(B + "/api/lists", json={"name": "Kontaktliste", "org_id": None}).json()["id"]
    for o in others:
        dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
            (lid, o, "edit", "edit"))


connect_people(Dv, DAVE, (ALICE, BOB, CAROL))
L = Bo.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}).json()["id"]
check(Bo.post(B + "/api/tasks", json={"title": "Aufgabe von Bob", "list_id": L}).ok, "setup: bob's task in the organisation")
# 2.305 (#2880): the export takes only the projects the exporting admin sees -> bob shares his project with alice
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
    (L, ALICE, "edit", "edit"))

# ---------------------------------------------------------------- #3093: the archive belongs to its starter
P = f"/api/orgs/{ORG}/export"
r = A.post(B + P)
check(r.status_code == 202, f"alice starts the export {r.status_code} {r.text[:160]}")
ja = wait_export(A, ORG)
check(ja.get("state") == "done" and ja.get("file") and not ja.get("foreign"), f"alice: done with her file {ja}")
jb = Bo.get(B + P).json()
check(jb.get("state") == "done" and jb.get("foreign") is True and "file" not in jb and "Alice Start" in (jb.get("by_name") or "")
      and jb.get("may_replace") is False and "Alice Start" in (jb.get("hint") or ""), f"bob: only that alice's archive exists {jb}")
r = Bo.get(B + P + "/file")
check(r.status_code == 403 and "Alice Start" in r.text and not r.content.startswith(b"KALMIDO-ORGX"), f"bob: download 403 {r.status_code}")
check(Bo.delete(B + P).status_code == 403, "bob: delete 403")
r = Bo.post(B + P)
check(r.status_code == 403 and "Alice Start" in r.text, f"bob: no replacing while alice holds the organisation {r.status_code} {r.text[:160]}")
OX = A.get(B + P + "/file")
check(OX.status_code == 200 and OX.content[:13] == b"KALMIDO-ORGX\n", "alice: download 200")
OX = OX.content
check(A.get(B + P).json().get("file") == ja.get("file"), "alice's archive is still there")
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(bool(RK), "the recovery key")

# ---------------------------------------------------------------- #3095: the import invites, the role is a confirmed suggestion
iid, pv = opened(Dv, OX, RK)
roles = {x["key"]: x.get("role") for x in pv.get("people", [])}
check(roles.get(EH("bob@example.com")) == "admin" and roles.get(EH("carol@example.com")) == "member", f"preview: the roles of the file {roles}")
check(roles.get(f"id{ERIN}") == "admin", f"preview: the file's role also for a person without an address (review M2) {roles}")
j = run(Dv, iid, GAMMA, people={EH("bob@example.com"): {"share": True},  # no role sent: the file's (admin)
                                EH("carol@example.com"): {"share": True, "role": "admin"},  # confirmed other role
                                EH("alice@example.com"): {"share": True, "role": "owner"}})  # unknown: member
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
res = j.get("result") or {}
st = {p.get("name"): p.get("state") for p in res.get("people", [])}
check(set(st.values()) == {"org_invited"} and len(st) == 3, f"result: everyone invited, nobody shared {st}")
check(any("invited to the organisation" in (w.get("text") or "") and w.get("count") == 3 for w in res.get("warnings", [])),
      f"warning: invited, content stays with the importing admin {res.get('warnings')}")
for u, uid in (("alice", ALICE), ("bob", BOB), ("carol", CAROL)):
    check(not one("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (GAMMA, uid)), f"{u}: not a member of Gamma")
jr = {r["user_id"]: r["role"] for r in dbx("SELECT user_id, role FROM org_joins WHERE org_id=?", (GAMMA,))}
check(jr.get(BOB) == "admin" and jr.get(CAROL) == "admin" and jr.get(ALICE) == "member", f"open invitations with the roles {jr}")
NL = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (GAMMA,))
check(NL and one("SELECT created_by FROM tasks WHERE list_id=? AND title='Aufgabe von Bob'", (NL,)) == DAVE, "bob's task stays with dave")
check(NL and not one("SELECT 1 FROM list_members WHERE list_id=? AND user_id IN (?,?,?)", (NL, ALICE, BOB, CAROL)), "no project shared with the invited")
check(Bo.post(B + f"/api/orgs/{GAMMA}/join").ok, "bob accepts the invitation")
check(one("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (GAMMA, BOB)) == "admin", "bob: member of Gamma as admin")
Dv.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- P4: a person without organisation, into the private space
FID, Fr = freelancer(B, A)
connect_people(Fr, FID, (CAROL,))
iid, _pv = opened(Fr, OX, RK)
j = run(Fr, iid, "private", people={EH("carol@example.com"): {"share": True, "role": "admin"}})
st = {p.get("name"): p.get("state") for p in (j.get("result") or {}).get("people", [])}
check(j.get("state") == "done" and st.get("Carol Mitglied") == "shared", f"private space: carol shared as before {st}")
check(not one("SELECT 1 FROM org_joins WHERE user_id=? AND created_by=?", (CAROL, FID)), "private space: nobody invited into an organisation")

# ---------------------------------------------------------------- #3093: the starter left -> another admin may replace it
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{ALICE}").ok, "bob removes alice from Alpha")
jb = Bo.get(B + P).json()
check(jb.get("foreign") is True and jb.get("may_replace") is True and "file" not in jb, f"bob: alice left, replacing allowed {jb}")
check(Bo.get(B + P + "/file").status_code == 403, "bob: still no download of alice's archive")
r = Bo.post(B + P)
check(r.status_code == 202, f"bob starts a new export {r.status_code} {r.text[:160]}")
jb = wait_export(Bo, ORG)
check(jb.get("state") == "done" and not jb.get("foreign") and jb.get("file"), f"bob: his own archive {jb}")
r = Bo.get(B + P + "/file")
check(r.status_code == 200 and r.content[:13] == b"KALMIDO-ORGX\n", "bob: download of his own archive 200")
check(Bo.delete(B + P).ok and Bo.get(B + P).json().get("state") == "none", "bob deletes his archive")

print(f"p2278_a_owner: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
