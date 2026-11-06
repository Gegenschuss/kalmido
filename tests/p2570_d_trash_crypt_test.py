#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.570.0 part D (#4716) API test: encrypt-all and decrypt-all go over the copies in the office trash too (like the key
rotation, #4669); the trash is not emptied. Own container (start.sh, org encryption on); invented names and numbers only.
freelancer-matrix: office
 - an organisation's device (office_equipment: serial number and purchase price sealed) and a draft invoice with a purchase
   price on its position (office_doc_items.cost_enc) are deleted into the office trash, decrypt-all runs: the copies in
   office_trash.snap hold plain values (cost back in cost, cost_enc empty), the trash keeps them, a restore brings readable
   values back and the database holds them plain (before the fix the copies stayed sealed and the restore wrote sealed
   values into a database that is plain now)
 - the other way: with encryption off a device and a draft are deleted into the trash (plain copies), encrypt-all runs:
   the copies are sealed (the purchase price in cost_enc, cost 0), a restore reads as before and the database holds the
   values sealed (before the fix plain copies stayed behind)
 - a person without an organisation: the same in the personal office
 - 2.570.0 (#4716 review F6): decrypt-all also opens a copy whose only protected value is a cost_enc left plain
 - 2.570.0 (#4716 review F4): encrypt-all counts a copy whose purchase price is no number as failed, migrated_at stays empty
usage: p2570_d_trash_crypt_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: F401

N = os.path.dirname(os.path.abspath(__file__))
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
D = O + "/docs"
E = "kenc1:"


def one(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        return r[0][0] if r else None
    finally:
        c.close()


def cli(*args):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def snap_rows(tid):
    snap = json.loads(one("SELECT snap FROM office_trash WHERE id=?", (tid,)) or "{}")
    return dict((t, r) for t, r in snap.get("rows") or [])


def sealed(v):
    return str(v).startswith(E)


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")  # the personal office comes with the first office call
PERS = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(PERS, "frida: a personal office")
WHO = [(A, "alice", ORG), (Fr, "frida", PERS)]
CL = {}
for s, who, oid in WHO:
    body = {"name": f"Kunde {who} GmbH", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}
    if who == "alice":
        body["org_id"] = oid
    r = s.post(B + "/api/clients", json=body)
    check(r.ok and r.json().get("id"), f"{who}: setup client {r.status_code} {r.text[:200]}")
    CL[who] = r.json().get("id")


def put_trash(s, who, tag):
    """A device and a draft invoice (purchase price 40 on its position) deleted into the office trash. -> (eid, tid_e, did, tid_d)"""
    r = s.post(B + O + "/equipment", json={"name": f"Kamera {who} {tag}", "serial_no": f"SN-{who}-{tag}", "purchase_net": 1234.5,
                                           "purchase_date": "2025-03-01"})
    check(r.status_code in (200, 201) and r.json().get("id"), f"{who} {tag}: setup device {r.status_code} {r.text[:200]}")
    eid = r.json()["id"]
    r = s.delete(B + O + f"/equipment/{eid}")
    tid_e = r.json().get("trash_id") if r.ok else None
    r = s.post(B + D, json={"kind": "invoice", "client_id": CL[who], "service_from": "2026-03-01", "service_to": "2026-03-02",
                            "items": [{"title": f"Schnitt {tag}", "qty": 1, "rate": 100, "cost": 40}]})
    check(r.status_code == 201, f"{who} {tag}: setup draft {r.status_code} {r.text[:200]}")
    did = r.json().get("id")
    r = s.delete(B + f"{D}/{did}")
    tid_d = r.json().get("trash_id") if r.ok else None
    if not tid_d:
        tid_d = one("SELECT id FROM office_trash WHERE ref_id=? AND kind LIKE '%doc%' ORDER BY id DESC", (did,))
    check(tid_e and tid_d, f"{who} {tag}: device and draft in the office trash {tid_e} {tid_d} {r.text[:200]}")
    return eid, tid_e, did, tid_d


def restore_reads(s, who, tag, eid, tid_e, did, tid_d):
    for tid in (tid_e, tid_d):
        r = s.post(B + O + f"/trash/{tid}/restore")
        check(r.ok, f"{who} {tag}: restore {tid} {r.status_code} {r.text[:200]}")
    d = s.get(B + O + f"/equipment/{eid}")
    j = d.json() if d.ok else {}
    j = j.get("item", j) if isinstance(j, dict) else {}
    check(d.ok and j.get("serial_no") == f"SN-{who}-{tag}" and float(j.get("purchase_net") or 0) == 1234.5,
          f"{who} {tag}: the device reads as before after the restore {d.status_code} {str(j)[:300]}")
    d = s.get(B + f"{D}/{did}")
    it = ((d.json().get("items") if d.ok else None) or [{}])[0]
    check(d.ok and str(it.get("cost")) in ("40", "40.0", "40.00"), f"{who} {tag}: the purchase price reads as before {it.get('cost')}")


def plain_cost_copy(s, who):
    """2.570.0 (#4716 review F6): a draft (purchase price 55) deleted into the trash, its copy rewritten so that its only
    protected value is a cost_enc left plain ("55.00", the state _cost_pass opens with oc_is_enc) and no value is sealed.
    -> the trash id"""
    r = s.post(B + D, json={"kind": "invoice", "client_id": CL[who], "items": [{"title": "Plain cost", "qty": 1, "rate": 100, "cost": 55}]})
    check(r.status_code == 201, f"{who}: setup plain-cost draft {r.status_code} {r.text[:200]}")
    did = r.json().get("id")
    r = s.delete(B + f"{D}/{did}")
    tid = (r.json().get("trash_id") if r.ok else None) or one("SELECT id FROM office_trash WHERE ref_id=? AND kind LIKE '%doc%' ORDER BY id DESC", (did,))
    snap = json.loads(one("SELECT snap FROM office_trash WHERE id=?", (tid,)) or "{}")
    def scrub(x):  # every value holding a sealed part (also inside a JSON column such as the totals) empty
        if isinstance(x, dict):
            return {k: scrub(v) for k, v in x.items()}
        if isinstance(x, list):
            return [scrub(v) for v in x]
        return None if isinstance(x, str) and E in x else x
    snap = scrub(snap)
    for table, rows in snap.get("rows") or []:
        for row in rows:
            if table == "office_doc_items":
                row["cost"], row["cost_enc"] = 0, "55.00"
    dbxm.q(os.path.join(DATA, "tasks.db"), "UPDATE office_trash SET snap=? WHERE id=?", (json.dumps(snap), tid))
    check(E not in (one("SELECT snap FROM office_trash WHERE id=?", (tid,)) or E), f"{who}: the plain-cost copy holds no sealed value")
    return tid


# ---- decrypt-all: the sealed copies in the trash plain again ----------------------------------------------------------------
BEFORE = {}
for s, who, oid in WHO:
    BEFORE[who] = put_trash(s, who, "a")
    BEFORE[who + " plain cost"] = plain_cost_copy(s, who)
    rows = snap_rows(BEFORE[who][1])
    eq = (rows.get("office_equipment") or [{}])[0]
    it = (snap_rows(BEFORE[who][3]).get("office_doc_items") or [{}])[0]
    check(sealed(eq.get("serial_no")) and sealed(it.get("cost_enc")), f"{who}: the copies keep the sealed values {str(eq)[:120]} {str(it)[:120]}")
N_TRASH = one("SELECT COUNT(*) FROM office_trash")
rc, out, err = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, f"decrypt-all finished {rc} {out[-400:]} {err[-600:]}")
line = next((x for x in out.splitlines() if "decrypt-all:" in x), "")
t = json.loads(line.split("decrypt-all:", 1)[1]) if line else {}
check(t.get("failed") == 0, f"decrypt-all: nothing failed {t}")
check(one("SELECT COUNT(*) FROM office_trash") == N_TRASH, "decrypt-all does not empty the office trash")
for s, who, oid in WHO:
    eid, tid_e, did, tid_d = BEFORE[who]
    eq = (snap_rows(tid_e).get("office_equipment") or [{}])[0]
    it = (snap_rows(tid_d).get("office_doc_items") or [{}])[0]
    check(eq.get("serial_no") == f"SN-{who}-a" and not sealed(eq.get("purchase_net")), f"{who}: the device's copy is plain after decrypt-all {str(eq)[:200]}")
    check(it.get("cost_enc") is None and str(it.get("cost")) in ("40", "40.0", "40.00"), f"{who}: the position's purchase price is plain in the copy {str(it)[:200]}")
    it = (snap_rows(BEFORE[who + " plain cost"]).get("office_doc_items") or [{}])[0]
    check(it.get("cost_enc") is None and str(it.get("cost")) in ("55", "55.0", "55.00"),  # 2.570.0 (#4716 review F6)
          f"{who}: a copy with only a plain cost_enc is opened too (cost back in cost) {str(it)[:200]}")
    restore_reads(s, who, "a", eid, tid_e, did, tid_d)
    check(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,)) == f"SN-{who}-a", f"{who}: the restored device is plain in the database")
    check(one("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (did,)) is None
          and float(one("SELECT cost FROM office_doc_items WHERE doc_id=?", (did,)) or 0) == 40, f"{who}: the restored position is plain in the database")

# ---- encrypt-all: plain copies in the trash sealed ------------------------------------------------------------------------
AFTER = {}
for s, who, oid in WHO:
    AFTER[who] = put_trash(s, who, "b")
    eq = (snap_rows(AFTER[who][1]).get("office_equipment") or [{}])[0]
    check(eq.get("serial_no") == f"SN-{who}-b", f"{who}: with encryption off the copy is plain {str(eq)[:120]}")
rc, out, err = cli("encrypt-all")
check(rc == 0, f"encrypt-all finished {rc} {out[-400:]} {err[-600:]}")
for s, who, oid in WHO:
    eid, tid_e, did, tid_d = AFTER[who]
    eq = (snap_rows(tid_e).get("office_equipment") or [{}])[0]
    it = (snap_rows(tid_d).get("office_doc_items") or [{}])[0]
    check(sealed(eq.get("serial_no")) and sealed(eq.get("purchase_net")), f"{who}: the device's copy is sealed after encrypt-all {str(eq)[:200]}")
    check(sealed(it.get("cost_enc")) and float(it.get("cost") or 0) == 0, f"{who}: the position's purchase price is sealed in the copy {str(it)[:200]}")
    restore_reads(s, who, "b", eid, tid_e, did, tid_d)
    check(sealed(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,))), f"{who}: the restored device is sealed in the database")
    check(sealed(one("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (did,))), f"{who}: the restored position is sealed in the database")

# ---- 2.570.0 (#4716 review F4): a copy whose purchase price is no number counts as failed and the organisation is not
# noted as done (migrated_at stays empty); the plain value stays as it is
_eid, _te, _did, tid_bad = put_trash(A, "alice", "c")
snap = json.loads(one("SELECT snap FROM office_trash WHERE id=?", (tid_bad,)) or "{}")
for table, rows in snap.get("rows") or []:
    if table == "office_doc_items":
        for row in rows:
            row["cost"], row["cost_enc"] = "keine Zahl", None
dbxm.q(os.path.join(DATA, "tasks.db"), "UPDATE office_trash SET snap=? WHERE id=?", (json.dumps(snap), tid_bad))
dbxm.q(os.path.join(DATA, "tasks.db"), "UPDATE org_keys SET migrated_at=NULL WHERE org_id=?", (ORG,))
rc, out, err = cli("encrypt-all")
line = next((x for x in out.splitlines() if "encrypt-all:" in x), "")
t = json.loads(line.split("encrypt-all:", 1)[1]) if line else {}
check(t.get("failed", 0) >= 1, f"encrypt-all: the copy with a cost that is no number counts as failed {t} {err[-400:]}")
check(one("SELECT migrated_at FROM org_keys WHERE org_id=?", (ORG,)) is None, "encrypt-all: Alpha is not noted as done while a trash copy failed")
it = (snap_rows(tid_bad).get("office_doc_items") or [{}])[0]
check(it.get("cost") == "keine Zahl" and it.get("cost_enc") is None, f"encrypt-all: the value that is no number stays as it is {str(it)[:200]}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
