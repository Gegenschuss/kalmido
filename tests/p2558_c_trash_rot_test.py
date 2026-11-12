#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.558.0 part C (#4669) API test: a key rotation re-encrypts the copies in the office trash too. Own container (start.sh,
org encryption on); invented names and numbers only.
freelancer-matrix: office
 - an organisation's device (office_equipment: serial number and purchase price sealed) is deleted into the office trash,
   the organisation's key is rotated (orgcrypt_cli rotate), the copy is restored: serial number and price read as before
   (before the fix the copy kept values of the earlier key, which is gone after the rotation)
 - the copy in office_trash.snap holds other ciphertext after the rotation, still sealed; the run reports nothing unreadable
 - a second rotation re-encrypts the copy again (no value left with a key that is gone)
 - 2.558.0 D (#4669, review F2): a copy sealed before an earlier rotation counts as trash_unreadable, the rotation finishes
 - a person without an organisation: the same in the personal office
 - 2.905.0 (#5414): a device goes into the core's trash now (its row stays, deleted_at): the rotation re-encrypts the row as
   any other, the restore (POST /api/office/trash/core/omd_equipment/<id>/restore) reads it; the copies above are made as
   before 2.905 (old_copy: the row as a copy in office_trash, the row deleted) - such old copies stay until their period ends
 - 2.1005.0 (#5415): such an old copy is written back as a row of the core's trash at the next start (the rotation's process
   starts the app): re-encrypted as a row, restored through the core; the copy cases above run on the start balance of the
   cash flow (the kind still kept as a copy, office/otrash.py OTB_KINDS)
 - 2.1050.0 (#5789): the start balance goes into the core's trash too (re-encrypted as a row, restored through the core); the
   unreadable copy case runs on an old copy of it that stays a copy (the start balance was set again meanwhile)
usage: p2558_c_trash_rot_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from obj_probe import in_app  # 2.1005.0 (#5415)
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: F401

N = os.path.dirname(os.path.abspath(__file__))
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"


def one(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        return r[0][0] if r else None
    finally:
        c.close()


def cli(*args):
    r = subprocess.run(["docker", "exec", "-i", "-e", "KALMIDO_ORGCRYPT_ROT_SETTLE=0", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def old_copy(oid, eid):
    """2.905.0 (#5414): device eid as a copy in office_trash and the row deleted, as office_delete did before 2.905 -> trash id."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        row = json.loads(c.execute("SELECT CAST(row_to_json(e) AS TEXT) FROM office_equipment e WHERE id=?", (eid,)).fetchall()[0][0])
        snap = json.dumps({"rows": [["office_equipment", [{k: v for k, v in row.items() if k not in ("deleted_at", "deleted_by", "rev", "created_by", "updated_by")}]]], "nulls": []})
        c.execute("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
                  (oid, "equipment", "", eid, row.get("name") or "", snap, None, "2026-11-09T10:00:00.000Z"))
        c.execute("DELETE FROM office_equipment WHERE id=?", (eid,))
        c.commit()
        return c.execute("SELECT MAX(id) FROM office_trash WHERE ref_id=? AND kind='equipment'", (eid,)).fetchall()[0][0]
    finally:
        c.close()


def cs_old_copy(oid):
    """2.1050.0 (#5789): the start balance of oid as a copy in office_trash, as cfstart.py made it before 2.1050 (key org_id).
    The row stays live, so the next start (okern.ofk_copies_back) keeps the copy (set again meanwhile) -> trash id."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        row = json.loads(c.execute("SELECT CAST(row_to_json(e) AS TEXT) FROM office_cf_start e WHERE org_id=?", (oid,)).fetchall()[0][0])
        snap = json.dumps({"rows": [["office_cf_start", [{k: v for k, v in row.items() if k not in ("id", "deleted_at", "deleted_by", "rev")}]]],
                           "nulls": [], "key": "org_id"})
        c.execute("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
                  (oid, "cf_start", "", oid, row.get("day") or "", snap, None, "2026-11-09T10:00:00.000Z"))
        c.commit()
        return c.execute("SELECT MAX(id) FROM office_trash WHERE org_id=? AND kind='cf_start'", (oid,)).fetchall()[0][0]
    finally:
        c.close()


def cs_copy_amount(tid):
    """2.1005.0 (#5415): the stored amount in the start balance's copy (office_trash.snap)."""
    snap = json.loads(one("SELECT snap FROM office_trash WHERE id=?", (tid,)) or "{}")
    rows = dict((t, r) for t, r in snap.get("rows") or [])
    return (rows.get("office_cf_start") or [{}])[0].get("amount")


def snap_vals(tid):
    snap = json.loads(one("SELECT snap FROM office_trash WHERE id=?", (tid,)) or "{}")
    rows = dict((t, r) for t, r in snap.get("rows") or [])
    eq = (rows.get("office_equipment") or [{}])[0]
    return eq.get("serial_no"), eq.get("purchase_net")


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


def case(s, who, oid):
    serial, price = f"SN-{who}-4711", 1234.5
    r = s.post(B + O + "/equipment", json={"name": f"Kamera {who}", "serial_no": serial, "purchase_net": price, "purchase_date": "2025-03-01"})
    check(r.status_code in (200, 201) and r.json().get("id"), f"{who}: setup device {r.status_code} {r.text[:200]}")
    eid = r.json()["id"]
    check(str(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,))).startswith("kenc1:"), f"{who}: the serial number is sealed at rest")
    # 2.905.0 (#5414): the core's trash - the row stays sealed, a rotation re-encrypts it, the restore reads it
    r = s.post(B + O + "/equipment", json={"name": f"Licht {who}", "serial_no": serial + "-K", "purchase_net": price, "purchase_date": "2025-03-01"})
    kid = r.json()["id"]
    r = s.delete(B + O + f"/equipment/{kid}")
    check(r.ok and (r.json().get("trash") or {}).get("id") == kid and one("SELECT deleted_at FROM office_equipment WHERE id=?", (kid,)),
          f"{who}: the device goes into the core's trash {r.text[:200]}")
    k1 = one("SELECT serial_no FROM office_equipment WHERE id=?", (kid,))
    rc, out, err = cli("rotate", "--org", str(oid))
    k2 = one("SELECT serial_no FROM office_equipment WHERE id=?", (kid,))
    check(rc == 0 and str(k2).startswith("kenc1:") and k2 != k1, f"{who}: the row in the trash is re-encrypted with the new key {rc} {out[-200:]}")
    r = s.post(B + O + f"/trash/core/omd_equipment/{kid}/restore")
    j = s.get(B + O + f"/equipment/{kid}").json()
    check(r.ok and j.get("serial_no") == serial + "-K", f"{who}: restored from the core's trash, readable {r.text[:200]} {str(j)[:200]}")
    # 2.1005.0 (#5415): an old copy of a device (made before 2.905) is written back into its table as a row of the core's trash
    # at the next start (okern.ofk_copies_back; orgcrypt_cli loads the app, its start runs it): the rotation re-encrypts the
    # row as any other, the core's restore reads it
    tid = old_copy(oid, eid)
    check(tid and one("SELECT COUNT(*) FROM office_equipment WHERE id=?", (eid,)) == 0, f"{who}: an old copy in the office trash")
    s1, p1 = snap_vals(tid)
    check(str(s1).startswith("kenc1:") and str(p1).startswith("kenc1:"), f"{who}: the copy keeps the sealed values {str(s1)[:12]} {str(p1)[:12]}")
    in_app("from kalmido.office.okern import ofk_copies_back\nprint(ofk_copies_back(c))\nc.commit()")  # what the next start does
    check(one("SELECT serial_no FROM office_equipment WHERE id=? AND deleted_at IS NOT NULL", (eid,)) == s1, f"{who}: written back as stored (sealed)")
    rc, out, err = cli("rotate", "--org", str(oid))
    check(rc == 0 and "R2-" in out, f"{who}: rotation finished {rc} {out[-300:]} {err[-800:]}")
    s2 = one("SELECT serial_no FROM office_equipment WHERE id=? AND deleted_at IS NOT NULL", (eid,))
    check(not one("SELECT 1 FROM office_trash WHERE id=?", (tid,)) and str(s2).startswith("kenc1:") and s2 != s1,
          f"{who}: the copy is a row of the core's trash now, re-encrypted with the new key {str(s2)[:12]}")
    r = s.post(B + O + f"/trash/core/omd_equipment/{eid}/restore")
    check(r.ok, f"{who}: restore after the rotation {r.status_code} {r.text[:200]}")
    d = s.get(B + O + f"/equipment/{eid}")
    j = d.json() if d.ok else {}
    j = j.get("item", j) if isinstance(j, dict) else {}
    check(d.ok and j.get("serial_no") == serial and float(j.get("purchase_net") or 0) == price,
          f"{who}: serial number and price readable after restore {d.status_code} {str(j)[:300]}")
    # 2.1050.0 (#5789): the start balance goes into the core's trash too (its row stays, deleted_at): the rotation re-encrypts
    # the row as any other (orgcrypt_cli FIELD_ORG_ROWS), the core's restore reads it
    check(s.put(B + O + "/cashflow/start", json={"amount": "1500.00", "day": "2026-01-02"}).ok, f"{who}: setup start balance")
    r = s.delete(B + O + "/cashflow/start")
    tcs = (r.json().get("trash") or {}).get("id") if r.ok else None
    a1 = one("SELECT amount FROM office_cf_start WHERE id=? AND deleted_at IS NOT NULL", (tcs,))
    check(tcs == oid and str(a1).startswith("kenc1:"), f"{who}: the start balance lies sealed in the core's trash {str(a1)[:12]} {r.text[:200]}")
    rc, out, err = cli("rotate", "--org", str(oid))
    a2 = one("SELECT amount FROM office_cf_start WHERE id=? AND deleted_at IS NOT NULL", (tcs,))
    check(rc == 0 and str(a2).startswith("kenc1:") and a2 != a1, f"{who}: the start balance in the trash is re-encrypted with the new key {rc} {out[-200:]}")
    r = s.post(B + O + f"/trash/core/ocfstart/{tcs}/restore")
    st = s.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "1500.00", f"{who}: the start balance is readable after restore {r.status_code} {r.text[:200]} {st}")
    # 2.558.0 D (#4669, review F2): a copy sealed before an earlier rotation (old stock) opens with neither key: counted on
    # its own, the rotation still finishes (before the fix it stopped with "not finished" until --force). 2.1050.0 (#5789):
    # an old copy of the start balance that stays a copy (the start balance was set again: ofk_copies_back keeps it)
    tid2 = cs_old_copy(oid)
    old = one("SELECT snap FROM office_trash WHERE id=?", (tid2,))
    rc, out, err = cli("rotate", "--org", str(oid))
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute("UPDATE office_trash SET snap=? WHERE id=?", (old, tid2))  # back to the values of the key that is gone now
        c.commit()
    finally:
        c.close()
    rc, out, err = cli("rotate", "--org", str(oid))
    line = next((x for x in out.splitlines() if x.split("rotate:", 1)[-1].strip().startswith("{")), "")
    t = json.loads(line.split("rotate:", 1)[1]) if line else {}
    check(rc == 0 and "R2-" in out and t.get("finished") and t.get("trash_unreadable", 0) >= 1 and t.get("unreadable") == 0,
          f"{who}: an unreadable old trash copy is counted on its own, the rotation finishes {rc} {t} {out[-300:]} {err[-300:]}")
    check(one("SELECT snap FROM office_trash WHERE id=?", (tid2,)) == old, f"{who}: the unreadable copy stays as it is")

case(A, "alice", ORG)
PERS = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
if not PERS:  # the personal office comes with the first office call
    Fr.get(B + O + "/settings")
    PERS = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(PERS, "frida: a personal office")
case(Fr, "frida", PERS)

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
