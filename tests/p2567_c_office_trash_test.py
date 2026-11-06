#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.567.0 C API tests (#4707, #4711): office things that were deleted for good at once (the client's toast was their only
way back) now go through the office trash. Own container (kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - a fixed cost (with its reminder row): DELETE answers trash_id, the office trash lists it, the toast's undo
   (POST /api/office/trash/undo/fixed_cost/<id>) brings it back with the old id and its reminder; another office 404, a
   member 403, a second undo 404
 - a correction of the cash flow: the same through the undo route (cf_adjust)
 - the start balance (a table without an id): DELETE answers trash_id, the office trash restores it; set again meanwhile:
   409 and the new value stays
 - a letter's link to a document: DELETE answers trash_id, the undo writes the link back
 - an import of fixed costs taken back (POST .../fixed-costs/delete): ONE entry in the office trash, restore brings every
   row back and the import run counts as not undone again
 - an import of trips taken back (POST .../trips/delete): one entry, the undo brings the trips back; a month locked since:
   409 and nothing comes back
The same for a person without an organisation (freelancer_fixture: the personal office).
usage: p2567_c_office_trash_test.py <datadir>"""
import base64
import os
from datetime import timedelta

import kt
from kt import B, check, sess
import testclock
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
TODAY = testclock.today()
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10)  # the 10th of the previous month (it can be locked)
PM1, PM2 = PM.isoformat(), (PM + timedelta(days=2)).isoformat()
MONTH = TODAY.isoformat()[:7]
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def sql(q, args=()):
    return kt.dbx(q, args)


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Dokument " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    # the recognition runs after the upload: wait until it is through (a real state, no fixed time)
    kt.until(lambda: not sql("SELECT 1 FROM doc_meta WHERE node_id=? AND state='run'", (nid,)), 30)
    return nid


def in_trash(S, tid, kind):
    return any(x["id"] == tid and x["kind"] == kind for x in S.get(B + O + "/trash").json().get("items") or [])


def scenario(S, who, ws, other, member=None):
    # ------------------------------------------------------------ a fixed cost with its reminder row
    r = S.post(B + O + "/fixed-costs", json={"label": f"Software {who}", "amount": "49.90", "start": PM1, "repeat": "monthly"})
    check(r.status_code == 201, f"{who}: setup fixed cost {r.text[:200]}")
    fid = r.json()["id"]
    oid = sql("SELECT org_id FROM office_fixed_costs WHERE id=?", (fid,))[0][0]
    sql("INSERT INTO office_sub_reminders(org_id, fixed_id, due, created_at) VALUES(?,?,?,?)", (oid, fid, PM2, PM1))
    r = S.delete(B + f"{O}/fixed-costs/{fid}")
    tf = r.json().get("trash_id") if r.ok else None
    check(r.ok and tf and r.json().get("item", {}).get("id") == fid and not sql("SELECT 1 FROM office_fixed_costs WHERE id=?", (fid,)),
          f"{who}: the fixed cost goes with a copy in the office trash {r.text[:200]}")
    check(in_trash(S, tf, "fixed_cost"), f"{who}: the office trash lists the fixed cost")
    check(other.post(B + f"/api/office/trash/undo/fixed_cost/{tf}").status_code in (403, 404), f"{who}: another office: the undo 403 / 404")
    if member is not None:
        check(member.post(B + f"/api/office/trash/undo/fixed_cost/{tf}").status_code == 403, f"{who}: a member: the undo 403")
    check(S.post(B + f"/api/office/trash/undo/cf_adjust/{tf}").status_code == 404, f"{who}: the undo of another kind 404")
    r = S.post(B + f"/api/office/trash/undo/fixed_cost/{tf}")
    got = [x for x in S.get(B + O + "/fixed-costs").json().get("items") or [] if x["id"] == fid]
    check(r.ok and r.json().get("id") == fid and got and got[0]["amount"] == "49.90" and got[0]["label"] == f"Software {who}",
          f"{who}: the undo brings the fixed cost back (same id, amount readable) {r.text[:200]} {got}")
    check(sql("SELECT 1 FROM office_sub_reminders WHERE fixed_id=?", (fid,)), f"{who}: its reminder row came back with it")
    check(S.post(B + f"/api/office/trash/undo/fixed_cost/{tf}").status_code == 404, f"{who}: a second undo 404")

    # ------------------------------------------------------------ a correction of the cash flow
    r = S.post(B + O + "/cashflow/adjust", json={"month": MONTH, "dir": "out", "amount": "120", "note": f"Bar {who}"})
    check(r.status_code == 201, f"{who}: setup correction {r.text[:200]}")
    aid = r.json()["id"]
    r = S.delete(B + f"{O}/cashflow/adjust/{aid}")
    ta = r.json().get("trash_id") if r.ok else None
    check(r.ok and ta and not sql("SELECT 1 FROM office_cf_adjust WHERE id=?", (aid,)), f"{who}: the correction goes with a copy {r.text[:200]}")
    r = S.post(B + f"/api/office/trash/undo/cf_adjust/{ta}")
    check(r.ok and r.json().get("id") == aid and sql("SELECT 1 FROM office_cf_adjust WHERE id=?", (aid,)), f"{who}: the undo brings the correction back {r.text[:200]}")

    # ------------------------------------------------------------ the start balance (no id column)
    r = S.put(B + O + "/cashflow/start", json={"amount": "1500.00", "day": PM1})
    check(r.ok, f"{who}: setup start balance {r.text[:200]}")
    r = S.delete(B + O + "/cashflow/start")
    ts = r.json().get("trash_id") if r.ok else None
    check(r.ok and ts and S.get(B + O + "/cashflow/start").json().get("start") is None, f"{who}: the start balance goes with a copy {r.text[:200]}")
    check(in_trash(S, ts, "cf_start"), f"{who}: the office trash lists the start balance")
    r = S.post(B + f"{O}/trash/{ts}/restore")
    st = S.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "1500.00" and st.get("day") == PM1, f"{who}: the office trash restores the start balance {r.text[:200]} {st}")
    r = S.delete(B + O + "/cashflow/start")
    ts = r.json().get("trash_id")
    S.put(B + O + "/cashflow/start", json={"amount": "900.00", "day": PM2})
    r = S.post(B + f"/api/office/trash/undo/cf_start/{ts}")
    st = S.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.status_code == 409 and st.get("amount") == "900.00" and sql("SELECT 1 FROM office_trash WHERE id=?", (ts,)),
          f"{who}: set again meanwhile: 409, the new value and the copy stay {r.status_code} {r.text[:200]} {st}")

    # ------------------------------------------------------------ a letter's link
    nid = upload(S, ws, f"schreiben-{who}.pdf")
    r = S.post(B + O + "/letters", json={"subject": "Ihr Schreiben", "answers": nid})
    check(r.status_code == 201, f"{who}: setup a letter answering the document {r.text[:200]}")
    lid = r.json()["id"]
    link = sql("SELECT id FROM office_letter_links WHERE letter_id=? AND node_id=?", (lid, nid))
    r = S.delete(B + f"{O}/letters/{lid}/links/{nid}?kind=answers")
    tl = r.json().get("trash_id") if r.ok else None
    check(r.ok and tl and link and not sql("SELECT 1 FROM office_letter_links WHERE letter_id=?", (lid,)), f"{who}: the link goes with a copy {r.text[:200]}")
    r = S.post(B + f"/api/office/trash/undo/letter_link/{tl}")
    check(r.ok and r.json().get("ids") == [link[0][0]] and sql("SELECT 1 FROM office_letter_links WHERE id=?", (link[0][0],)),
          f"{who}: the undo writes the link back {r.text[:200]}")
    check(any(x["node_id"] == nid for x in S.get(B + f"{O}/letters/{lid}/links").json().get("links") or []), f"{who}: the letter shows the link again")

    # ------------------------------------------------------------ an import of fixed costs taken back
    items = [{"label": f"Miete {who}", "amount": "800", "repeat": "monthly", "start": PM1[:8] + "01"},
             {"label": f"Strom {who}", "amount": "60", "repeat": "monthly", "start": PM1[:8] + "01"}]
    r = S.post(B + O + "/fixed-costs/import", json={"items": items})
    check(r.status_code == 201 and r.json()["created"] == 2, f"{who}: setup fixed costs import {r.text[:200]}")
    fids = sorted(r.json()["ids"])
    r = S.post(B + O + "/fixed-costs/delete", json={"ids": fids})
    ti = r.json().get("trash_id") if r.ok else None
    check(r.ok and r.json().get("deleted") == 2 and ti and not sql("SELECT 1 FROM office_fixed_costs WHERE id IN (?,?)", tuple(fids)),
          f"{who}: the import taken back goes into the office trash {r.text[:200]}")
    n = sum(1 for x in S.get(B + O + "/trash").json()["items"] if x["kind"] == "fixed_import")
    check(n == 1, f"{who}: one entry for the import, not one per row ({n})")
    r = S.post(B + f"{O}/trash/{ti}/restore")
    back = sorted(x[0] for x in sql("SELECT id FROM office_fixed_costs WHERE id IN (?,?)", tuple(fids)))
    check(r.ok and back == fids, f"{who}: the office trash brings every imported row back {r.text[:200]} {back}")
    rr = sql("SELECT r.undone_at FROM office_import_runs r JOIN office_fixed_costs f ON f.import_run_id=r.id WHERE f.id=?", (fids[0],))
    check(rr and rr[0][0] is None, f"{who}: the import run counts as not undone again {rr}")

    # ------------------------------------------------------------ an import of trips taken back (last: it locks a month)
    me = S.get(B + "/api/state").json()["me"]["id"]
    trips = [{"date_from": PM1, "dest": f"Bonn {who}", "purpose": "job", "people": [{"id": me}]},
             {"date_from": PM2, "dest": f"Essen {who}", "purpose": "job", "people": [{"id": me}]}]
    r = S.post(B + O + "/trips/import", json={"trips": trips})
    check(r.status_code == 201 and r.json()["created"] == 2, f"{who}: setup trips import {r.text[:200]}")
    tids = sorted(r.json()["ids"])
    r = S.post(B + O + "/trips/delete", json={"ids": tids})
    tt = r.json().get("trash_id") if r.ok else None
    check(r.ok and r.json().get("deleted") == 2 and tt and in_trash(S, tt, "trip_import"), f"{who}: the trips import taken back: one entry {r.text[:200]}")
    r = S.post(B + f"/api/office/trash/undo/trip_import/{tt}")
    check(r.ok and sorted(r.json().get("ids") or []) == tids and len(sql("SELECT id FROM office_trips WHERE id IN (?,?)", tuple(tids))) == 2,
          f"{who}: the undo brings both trips back {r.text[:200]}")
    r = S.post(B + O + "/trips/delete", json={"ids": tids})
    tt = r.json().get("trash_id")
    # #3506 (CI red of 2.579.0): the trips the undo brought back are unchanged, so a second take-back takes them again
    check(r.ok and r.json().get("deleted") == 2 and tt, f"{who}: taken back again after the undo: one entry {r.text[:200]}")
    m = PM1[:7]
    lock = S.post(B + O + "/periods/lock", json={"through": m, "confirm": f"{m[5:7]}/{m[:4]}"})
    check(lock.ok, f"{who}: setup the month of the trips locked {lock.text[:200]}")
    r = S.post(B + f"/api/office/trash/undo/trip_import/{tt}")
    check(r.status_code == 409 and not sql("SELECT 1 FROM office_trips WHERE id IN (?,?)", tuple(tids)) and sql("SELECT 1 FROM office_trash WHERE id=?", (tt,)),
          f"{who}: a month locked since: 409, nothing comes back, the copy stays {r.status_code} {r.text[:200]}")


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office (the personal office, its own admin)
for s in (A, Fr):
    s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})

scenario(A, "alice", f"org:{ORG}", Ca, member=Bo)
scenario(Fr, "frida", "private", A)

raise SystemExit(kt.done("p2567_c_office_trash"))
