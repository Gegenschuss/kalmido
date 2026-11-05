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
    r = s.delete(B + O + f"/equipment/{eid}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid and one("SELECT COUNT(*) FROM office_equipment WHERE id=?", (eid,)) == 0, f"{who}: the device goes into the office trash {r.text[:200]}")
    s1, p1 = snap_vals(tid)
    check(str(s1).startswith("kenc1:") and str(p1).startswith("kenc1:"), f"{who}: the copy keeps the sealed values {str(s1)[:12]} {str(p1)[:12]}")
    rc, out, err = cli("rotate", "--org", str(oid))
    check(rc == 0 and "R2-" in out, f"{who}: rotation finished {rc} {out[-300:]} {err[-800:]}")
    s2, p2 = snap_vals(tid)
    check(str(s2).startswith("kenc1:") and s2 != s1 and str(p2).startswith("kenc1:") and p2 != p1,
          f"{who}: the copy in the trash is re-encrypted with the new key")
    rc, out, err = cli("rotate", "--org", str(oid))
    s3, _ = snap_vals(tid)
    check(rc == 0 and str(s3).startswith("kenc1:") and s3 != s2, f"{who}: a second rotation re-encrypts the copy again {rc} {out[-200:]}")
    r = s.post(B + O + f"/trash/{tid}/restore")
    check(r.ok, f"{who}: restore after the rotations {r.status_code} {r.text[:200]}")
    d = s.get(B + O + f"/equipment/{eid}")
    j = d.json() if d.ok else {}
    j = j.get("item", j) if isinstance(j, dict) else {}
    check(d.ok and j.get("serial_no") == serial and float(j.get("purchase_net") or 0) == price,
          f"{who}: serial number and price readable after restore {d.status_code} {str(j)[:300]}")
    # 2.558.0 D (#4669, review F2): a copy sealed before an earlier rotation (old stock) opens with neither key: counted on
    # its own, the rotation still finishes (before the fix it stopped with "not finished" until --force)
    r = s.post(B + O + "/equipment", json={"name": f"Stativ {who}", "serial_no": f"SN-{who}-old", "purchase_date": "2025-03-01"})
    tid2 = s.delete(B + O + f"/equipment/{r.json()['id']}").json().get("trash_id")
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
