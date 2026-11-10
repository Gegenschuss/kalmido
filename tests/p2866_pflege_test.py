#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.866.0 (#5302): care after the review of 2.747 -- small findings of the office rights, the file store's shares, the
master data saves and the undo across devices. Own container (kt.fresh). Invented people, firms and figures only.
 - F5 a rights group restored from the office trash is in the rights log (group_restore, its definition as after)
 - F6 a projects folder's share with a list role: the file store's log line names the final role (edit for admin / edit)
 - F7 a share that ended with a move into another workspace and came back with the move back keeps by_role of who made it,
   and its obj_revoked row of the move goes (not offered a second time)
 - F8 a master data save that changes nothing ("800" for 800, blanks around a name, an unknown key) writes no history entry,
   no undo step, keeps updated_at
 - F9 a write while a "bis hierher" of the same person holds an undone group's parts does not wait for them (no deadlock
   window): it answers, the group stays; the next step tidies it
 - F10 a person who leaves an organisation loses her step groups there (with their parts), the others' stay
 - N2 a barrier holds "bis hierher" only for the steps of its own workspace (a private step behind an office barrier goes
   back, an office step behind it stays)
 - N5 office/oubar.py _plain: a browser ciphertext (e2e1:) or a sealed value never becomes a label; no label column of the
   office (documents, clients, master data) is in orgcrypt FIELDS
The same for a person without an organisation (freelancer_fixture: her personal office, her private project) at F5 / F8 / N2.
freelancer-matrix: office
usage: p2866_pflege_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, sess  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files,sheets,office,clients,docs"
OFF = "/api/office"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


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


def in_app(code):
    cmd = ["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.close()"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout + out.stderr


def groups(u):
    return [dict(x) for x in sql("SELECT id, state, org_id, area, parts FROM undo_groups WHERE user_id=? ORDER BY id", (u,))]


def service(s, name, rate=800):
    r = s.post(B + OFF + "/services", json={"name_de": name, "daily_rate": rate})
    check(r.status_code in (200, 201), f"setup: a service {name} {r.text[:200]}")
    return r.json()


# ================================================================ F5 a rights group back from the trash: in the rights log
def f5(who, s):
    r = s.post(B + OFF + "/rights/groups", json={"name": f"Grading {who}"})
    check(r.status_code == 201, f"F5 {who}: setup: a rights group {r.text[:200]}")
    gid, levels = r.json()["id"], r.json()["levels"]
    r = s.delete(B + OFF + f"/rights/groups/{gid}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid, f"F5 {who}: the group into the office trash {r.text[:200]}")
    check(s.post(B + OFF + f"/trash/{tid}/restore").ok, f"F5 {who}: restored")
    log = s.get(B + OFF + "/rights/log").json().get("items") or []
    mine = [x for x in log if x["group"] == f"g:{gid}"]
    check([x["action"] for x in mine][:2] == ["group_restore", "group_delete"],
          f"F5 {who}: the rights log names the restore after the delete (newest first) {[x['action'] for x in mine]}")
    rs = mine[0] if mine else {}
    check(rs.get("after", {}).get("name") == f"Grading {who}" and rs.get("after", {}).get("levels") == levels and rs.get("before") is None,
          f"F5 {who}: its definition as after {rs}")


# ================================================================ setup
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2866")
kt.docker_logs_on_first_fail()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Leaving")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dora@example.com", "role": "admin"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2), (Do, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
for s in (A, Fr, Ca):
    s.put(B + OFF + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
FOFF = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))
FOFF = FOFF[0][0] if FOFF else None
check(FOFF, "setup: frida's personal office")

f5("alice", A)
f5("frida", Fr)
# -- more parts below --

raise SystemExit(kt.done("p2866_pflege"))
