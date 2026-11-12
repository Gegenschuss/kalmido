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
 - 2.905.0 (#5414): a device goes into the core's trash now (the row stays and is migrated as any other); the device's copy
   here is made as before 2.905 (old_copy) - such old copies stay in office_trash until their period ends
 - 2.1005.0 (#5415): a draft goes into the core's trash now too (the row stays and is migrated as any other); the draft's
   copy here is made as before 2.1005 (old_doc_copy)
 - 2.1005.0 (#5415, part E): such old copies (device, draft) are written back into their tables as rows of the core's trash at
   the next start (okern.ofk_copies_back; run here by hand, as the start does): encrypt-all / decrypt-all migrate them as rows,
   the core's restore reads them. The copies still made (the start balance of the cash flow, office/otrash.py OTB_KINDS) are
   migrated in office_trash.snap as before. 2.1050.0 (#5789): the start balance goes into the core's trash too (its row is
   migrated as any other), no copy is made any more. The copy cases of a draft's positions (review F6 / F4) left with the copies of drafts.
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
from obj_probe import in_app  # 2.1005.0 (#5415)
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


def old_copy(oid, eid):
    """2.905.0 (#5414): device eid as a copy in office_trash and the row deleted, as office_delete did before 2.905 -> trash id."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    row = json.loads(c.execute("SELECT CAST(row_to_json(e) AS TEXT) FROM office_equipment e WHERE id=?", (eid,)).fetchall()[0][0])
    snap = json.dumps({"rows": [["office_equipment", [{k: v for k, v in row.items() if k not in ("deleted_at", "deleted_by", "rev", "created_by", "updated_by")}]]], "nulls": []})
    c.execute("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
              (oid, "equipment", "", eid, row.get("name") or "", snap, None, "2026-11-09T10:00:00.000Z"))
    c.execute("DELETE FROM office_equipment WHERE id=?", (eid,))
    return c.execute("SELECT MAX(id) FROM office_trash WHERE ref_id=? AND kind='equipment'", (eid,)).fetchall()[0][0]


def old_doc_copy(oid, did):
    """2.1005.0 (#5415): draft did with its positions as a copy in office_trash and the row deleted, as odoc_delete did before
    2.1005 -> trash id."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    new = ("deleted_at", "deleted_by", "rev", "updated_by", "trash_refs")
    row = json.loads(c.execute("SELECT CAST(row_to_json(d) AS TEXT) FROM office_docs d WHERE id=?", (did,)).fetchall()[0][0])
    its = [json.loads(x[0]) for x in c.execute("SELECT CAST(row_to_json(i) AS TEXT) FROM office_doc_items i WHERE doc_id=? ORDER BY id", (did,)).fetchall()]
    snap = json.dumps({"rows": [["office_docs", [{k: v for k, v in row.items() if k not in new}]], ["office_doc_items", its]], "nulls": []})
    c.execute("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
              (oid, "doc", row.get("kind") or "", did, row.get("project_title") or "", snap, None, "2026-11-09T10:00:00.000Z"))
    c.execute("DELETE FROM office_docs WHERE id=?", (did,))
    return c.execute("SELECT MAX(id) FROM office_trash WHERE ref_id=? AND kind='doc'", (did,)).fetchall()[0][0]


def copies_back():
    """2.1005.0 (#5415): what the next start does: the old copies of office_trash back as rows of the core's trash."""
    out = in_app("from kalmido.office.okern import ofk_copies_back\nprint('BACK', ofk_copies_back(c))\nc.commit()")
    check("BACK" in out, f"the old copies written back {out[-300:]}")


def cfs_copy(s, who, amount):
    """2.1005.0 (#5415): the start balance of the cash flow deleted -> the trash id. 2.1050.0 (#5789): into the core's trash
    (kind ocfstart, its row stays with deleted_at; id = the office's org_id), no copy any more."""
    check(s.put(B + O + "/cashflow/start", json={"amount": amount, "day": "2026-01-02"}).ok, f"{who}: setup start balance")
    r = s.delete(B + O + "/cashflow/start")
    tr0 = (r.json().get("trash") or {}) if r.ok else {}
    check(tr0.get("kind") == "ocfstart" and tr0.get("id"), f"{who}: the start balance goes into the core's trash {r.text[:200]}")
    return tr0.get("id")


def cfs_snap(tid):
    """2.1050.0 (#5789): the stored amount of the start balance in the core's trash (was: in the copy's snap)."""
    return one("SELECT amount FROM office_cf_start WHERE id=? AND deleted_at IS NOT NULL", (tid,))


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
    tid_e = old_copy({"alice": ORG, "frida": PERS}[who], eid)  # 2.905.0 (#5414): an old copy (the core's trash keeps the row itself)
    r = s.post(B + D, json={"kind": "invoice", "client_id": CL[who], "service_from": "2026-03-01", "service_to": "2026-03-02",
                            "items": [{"title": f"Schnitt {tag}", "qty": 1, "rate": 100, "cost": 40}]})
    check(r.status_code == 201, f"{who} {tag}: setup draft {r.status_code} {r.text[:200]}")
    did = r.json().get("id")
    tid_d = old_doc_copy({"alice": ORG, "frida": PERS}[who], did)  # 2.1005.0 (#5415): an old copy (the core's trash keeps the row itself)
    check(tid_e and tid_d, f"{who} {tag}: device and draft in the office trash {tid_e} {tid_d}")
    return eid, tid_e, did, tid_d


def restore_reads(s, who, tag, eid, tid_e, did, tid_d):
    for kind, rid in (("omd_equipment", eid), ("odoc", did)):  # 2.1005.0 (#5415): rows of the core's trash (written back)
        r = s.post(B + O + f"/trash/core/{kind}/{rid}/restore")
        check(r.ok, f"{who} {tag}: restore {kind} {rid} {r.status_code} {r.text[:200]}")
    d = s.get(B + O + f"/equipment/{eid}")
    j = d.json() if d.ok else {}
    j = j.get("item", j) if isinstance(j, dict) else {}
    check(d.ok and j.get("serial_no") == f"SN-{who}-{tag}" and float(j.get("purchase_net") or 0) == 1234.5,
          f"{who} {tag}: the device reads as before after the restore {d.status_code} {str(j)[:300]}")
    d = s.get(B + f"{D}/{did}")
    it = ((d.json().get("items") if d.ok else None) or [{}])[0]
    check(d.ok and str(it.get("cost")) in ("40", "40.0", "40.00"), f"{who} {tag}: the purchase price reads as before {it.get('cost')}")


# ---- decrypt-all: the sealed rows of the trash and the sealed copies plain again ----------------------------------------
BEFORE, CFS = {}, {}
for s, who, oid in WHO:
    BEFORE[who] = put_trash(s, who, "a")
    rows = snap_rows(BEFORE[who][1])
    eq = (rows.get("office_equipment") or [{}])[0]
    it = (snap_rows(BEFORE[who][3]).get("office_doc_items") or [{}])[0]
    check(sealed(eq.get("serial_no")) and sealed(it.get("cost_enc")), f"{who}: the copies keep the sealed values {str(eq)[:120]} {str(it)[:120]}")
    CFS[who] = cfs_copy(s, who, "1500.00")
    check(sealed(cfs_snap(CFS[who])), f"{who}: the start balance in the trash keeps its amount sealed")
copies_back()
for s, who, oid in WHO:
    eid, tid_e, did, tid_d = BEFORE[who]
    check(not one("SELECT 1 FROM office_trash WHERE id IN (?, ?)", (tid_e, tid_d)) and one("SELECT deleted_at FROM office_equipment WHERE id=?", (eid,))
          and one("SELECT deleted_at FROM office_docs WHERE id=?", (did,)) and sealed(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,))),
          f"{who}: device and draft are rows of the core's trash now, sealed as stored")
N_TRASH = one("SELECT COUNT(*) FROM office_trash")
rc, out, err = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, f"decrypt-all finished {rc} {out[-400:]} {err[-600:]}")
line = next((x for x in out.splitlines() if "decrypt-all:" in x), "")
t = json.loads(line.split("decrypt-all:", 1)[1]) if line else {}
check(t.get("failed") == 0, f"decrypt-all: nothing failed {t}")
check(one("SELECT COUNT(*) FROM office_trash") == N_TRASH, "decrypt-all does not empty the office trash")
for s, who, oid in WHO:
    eid, tid_e, did, tid_d = BEFORE[who]
    check(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,)) == f"SN-{who}-a", f"{who}: the device in the trash is plain after decrypt-all")
    check(one("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (did,)) is None
          and float(one("SELECT cost FROM office_doc_items WHERE doc_id=?", (did,)) or 0) == 40, f"{who}: the draft's purchase price in the trash is plain")
    check(cfs_snap(CFS[who]) == "1500.00", f"{who}: the start balance in the trash is plain after decrypt-all {cfs_snap(CFS[who])}")
    restore_reads(s, who, "a", eid, tid_e, did, tid_d)
    r = s.post(B + O + f"/trash/core/ocfstart/{CFS[who]}/restore")  # 2.1050.0 (#5789): the core's trash
    st = s.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "1500.00", f"{who}: the start balance reads as before after the restore {r.text[:200]} {st}")

# ---- encrypt-all: plain rows of the trash and plain copies sealed ---------------------------------------------------------
AFTER = {}
for s, who, oid in WHO:
    AFTER[who] = put_trash(s, who, "b")
    eq = (snap_rows(AFTER[who][1]).get("office_equipment") or [{}])[0]
    check(eq.get("serial_no") == f"SN-{who}-b", f"{who}: with encryption off the copy is plain {str(eq)[:120]}")
    CFS[who] = cfs_copy(s, who, "900.00")
    check(cfs_snap(CFS[who]) == "900.00", f"{who}: with encryption off the start balance in the trash is plain")
copies_back()
rc, out, err = cli("encrypt-all")
check(rc == 0, f"encrypt-all finished {rc} {out[-400:]} {err[-600:]}")
for s, who, oid in WHO:
    eid, tid_e, did, tid_d = AFTER[who]
    check(sealed(one("SELECT serial_no FROM office_equipment WHERE id=?", (eid,))), f"{who}: the device in the trash is sealed after encrypt-all")
    check(sealed(one("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (did,))), f"{who}: the draft's purchase price in the trash is sealed")
    check(sealed(cfs_snap(CFS[who])), f"{who}: the start balance in the trash is sealed after encrypt-all")
    restore_reads(s, who, "b", eid, tid_e, did, tid_d)
    r = s.post(B + O + f"/trash/core/ocfstart/{CFS[who]}/restore")  # 2.1050.0 (#5789): the core's trash
    st = s.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "900.00", f"{who}: the start balance reads as before after the restore {r.text[:200]} {st}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
