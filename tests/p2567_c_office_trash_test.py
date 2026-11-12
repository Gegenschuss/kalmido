#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.567.0 C API tests (#4707, #4711): office things that were deleted for good at once (the client's toast was their only
way back) now go through the office trash. Own container (kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - a fixed cost (with its reminder row): DELETE answers trash_id, the office trash lists it, the toast's undo
   (POST /api/office/trash/undo/fixed_cost/<id>) brings it back with the old id and its reminder; another office 404, a
   member 403, a second undo 404
 - a correction of the cash flow: the same through the undo route (cf_adjust); 2.905.0 (#5414): the core's trash (oadjust)
 - the start balance (a table without an id): DELETE answers trash_id, the office trash restores it; set again meanwhile:
   409 and the new value stays. 2.1050.0 (#5789): the core's trash (kind ocfstart): DELETE answers trash {kind, id}; set again
   meanwhile: the one in the trash goes for good (the undo 404), the new value stays
 - a letter's link to a document: DELETE answers trash_id, the undo writes the link back; 2.905.0 (#5414): the core's
   trash (oletlink); linked again after a removal: the row of the trash is the link again
 - an import of fixed costs taken back (POST .../fixed-costs/delete): ONE entry in the office trash, restore brings every
   row back and the import run counts as not undone again
   2.905.0 (#5414): a fixed cost and the rows of an import taken back lie in the core's trash (kind ofixed, deleted_at): the
   toast's undo is POST /api/office/trash/core/ofixed/<id>/restore?undo=1, the office trash lists each row (core = ofixed)
 - an import of trips taken back (POST .../trips/delete): 2.1005.0 (#5415) each trip in the core's trash (kind otrip), the
   office trash brings them back unchanged (the run not undone again); a month locked since: 409 and nothing comes back
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
    # 2.905.0 (#5414): the core's trash (the row stays with deleted_at), the toast's undo through core/ofixed ?undo=1
    tf = (r.json().get("trash") or {}).get("id") if r.ok else None
    check(r.ok and tf == fid and r.json().get("item", {}).get("id") == fid and sql("SELECT 1 FROM office_fixed_costs WHERE id=? AND deleted_at IS NOT NULL", (fid,))
          and not [x for x in S.get(B + O + "/fixed-costs").json().get("items") or [] if x["id"] == fid],
          f"{who}: the fixed cost goes into the trash, gone from the list {r.text[:200]}")
    check(in_trash(S, tf, "fixed_cost"), f"{who}: the office trash lists the fixed cost")
    check(other.post(B + f"/api/office/trash/core/ofixed/{tf}/restore?undo=1").status_code in (403, 404), f"{who}: another office: the undo 403 / 404")
    if member is not None:
        check(member.post(B + f"/api/office/trash/core/ofixed/{tf}/restore?undo=1").status_code == 403, f"{who}: a member: the undo 403")
    check(S.post(B + f"/api/office/trash/core/oadjust/{tf}/restore?undo=1").status_code == 404, f"{who}: the undo of another kind 404")
    r = S.post(B + f"/api/office/trash/core/ofixed/{tf}/restore?undo=1")
    got = [x for x in S.get(B + O + "/fixed-costs").json().get("items") or [] if x["id"] == fid]
    check(r.ok and r.json().get("id") == fid and got and got[0]["amount"] == "49.90" and got[0]["label"] == f"Software {who}",
          f"{who}: the undo brings the fixed cost back (same id, amount readable) {r.text[:200]} {got}")
    check(sql("SELECT 1 FROM office_sub_reminders WHERE fixed_id=?", (fid,)), f"{who}: its reminder row came back with it")
    check(S.post(B + f"/api/office/trash/core/ofixed/{tf}/restore?undo=1").status_code == 404, f"{who}: a second undo 404")

    # ------------------------------------------------------------ a correction of the cash flow
    r = S.post(B + O + "/cashflow/adjust", json={"month": MONTH, "dir": "out", "amount": "120", "note": f"Bar {who}"})
    check(r.status_code == 201, f"{who}: setup correction {r.text[:200]}")
    aid = r.json()["id"]
    r = S.delete(B + f"{O}/cashflow/adjust/{aid}")
    # 2.905.0 (#5414): the core's trash (kind oadjust, the row stays with deleted_at)
    ta = (r.json().get("trash") or {}).get("id") if r.ok else None
    check(r.ok and ta == aid and sql("SELECT 1 FROM office_cf_adjust WHERE id=? AND deleted_at IS NOT NULL", (aid,)), f"{who}: the correction goes into the trash {r.text[:200]}")
    check(in_trash(S, ta, "cf_adjust"), f"{who}: the office trash lists the correction")
    r = S.post(B + f"/api/office/trash/core/oadjust/{ta}/restore?undo=1")
    check(r.ok and r.json().get("id") == aid and sql("SELECT 1 FROM office_cf_adjust WHERE id=? AND deleted_at IS NULL", (aid,)), f"{who}: the undo brings the correction back {r.text[:200]}")

    # ------------------------------------------------------------ the start balance (one row per office)
    # 2.1050.0 (#5789): the core's trash (kind ocfstart, id = the office's org_id) instead of a copy in office_trash; the undo
    # is the core's restore ?undo=1; set again meanwhile: the one in the trash goes for good, the undo 404
    r = S.put(B + O + "/cashflow/start", json={"amount": "1500.00", "day": PM1})
    check(r.ok, f"{who}: setup start balance {r.text[:200]}")
    r = S.delete(B + O + "/cashflow/start")
    tr0 = (r.json().get("trash") or {}) if r.ok else {}
    ts = tr0.get("id")
    check(r.ok and tr0.get("kind") == "ocfstart" and ts and "trash_id" not in r.json() and S.get(B + O + "/cashflow/start").json().get("start") is None
          and sql("SELECT 1 FROM office_cf_start WHERE id=? AND deleted_at IS NOT NULL", (ts,)) and not sql("SELECT 1 FROM office_trash WHERE kind='cf_start'"),
          f"{who}: the start balance goes into the core's trash {r.text[:200]}")
    check(in_trash(S, ts, "cf_start"), f"{who}: the office trash lists the start balance")
    r = S.post(B + f"{O}/trash/core/ocfstart/{ts}/restore")
    st = S.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.ok and st.get("amount") == "1500.00" and st.get("day") == PM1, f"{who}: the office trash restores the start balance {r.text[:200]} {st}")
    r = S.delete(B + O + "/cashflow/start")
    ts = (r.json().get("trash") or {}).get("id")
    # 2.1005.0 (#5415): the stranger's probe of the undo route moved here from the trips import (trips are on the core's trash)
    check(other.post(B + f"/api/office/trash/core/ocfstart/{ts}/restore?undo=1").status_code in (403, 404), f"{who}: another office: the undo 403 / 404")
    if member is not None:
        check(member.post(B + f"/api/office/trash/core/ocfstart/{ts}/restore?undo=1").status_code == 403, f"{who}: a member: the undo 403")
    r = S.put(B + O + "/cashflow/start", json={"amount": "900.00", "day": PM2})
    check(r.ok and r.json().get("prev") is None, f"{who}: a new start balance while one is in the trash {r.text[:200]}")
    r = S.post(B + f"/api/office/trash/core/ocfstart/{ts}/restore?undo=1")
    st = S.get(B + O + "/cashflow/start").json().get("start") or {}
    check(r.status_code == 404 and st.get("amount") == "900.00" and st.get("day") == PM2 and not in_trash(S, ts, "cf_start"),
          f"{who}: set again meanwhile: the old one left the trash, the undo 404, the new value stays {r.status_code} {r.text[:200]} {st}")

    # ------------------------------------------------------------ a letter's link
    nid = upload(S, ws, f"schreiben-{who}.pdf")
    r = S.post(B + O + "/letters", json={"subject": "Ihr Schreiben", "answers": nid})
    check(r.status_code == 201, f"{who}: setup a letter answering the document {r.text[:200]}")
    lid = r.json()["id"]
    link = sql("SELECT id FROM office_letter_links WHERE letter_id=? AND node_id=?", (lid, nid))
    r = S.delete(B + f"{O}/letters/{lid}/links/{nid}?kind=answers")
    # 2.905.0 (#5414): the core's trash (kind oletlink, the row stays with deleted_at)
    tl = (r.json().get("trash") or {}).get("id") if r.ok else None
    check(r.ok and link and tl == link[0][0] and not sql("SELECT 1 FROM office_letter_links WHERE letter_id=? AND deleted_at IS NULL", (lid,))
          and not r.json().get("links"), f"{who}: the link goes into the trash {r.text[:200]}")
    check(in_trash(S, tl, "letter_link"), f"{who}: the office trash lists the link")
    r = S.post(B + f"/api/office/trash/core/oletlink/{tl}/restore?undo=1")
    check(r.ok and r.json().get("ids") == [link[0][0]] and sql("SELECT 1 FROM office_letter_links WHERE id=?", (link[0][0],)),
          f"{who}: the undo writes the link back {r.text[:200]}")
    check(any(x["node_id"] == nid for x in S.get(B + f"{O}/letters/{lid}/links").json().get("links") or []), f"{who}: the letter shows the link again")
    # 2.905.0 (#5414): removed again and linked again: the row of the trash is the link again (one link per letter / document / kind)
    check(S.delete(B + f"{O}/letters/{lid}/links/{nid}?kind=answers").ok, f"{who}: removed again")
    r = S.post(B + f"{O}/letters/{lid}/links", json={"node_id": nid, "kind": "answers"})
    check(r.status_code == 201 and any(x["node_id"] == nid for x in r.json().get("links") or [])
          and sql("SELECT id FROM office_letter_links WHERE letter_id=? AND node_id=? AND deleted_at IS NULL", (lid, nid)) == link,
          f"{who}: linked again: the same row, live {r.status_code} {r.text[:200]}")

    # ------------------------------------------------------------ an import of fixed costs taken back
    items = [{"label": f"Miete {who}", "amount": "800", "repeat": "monthly", "start": PM1[:8] + "01"},
             {"label": f"Strom {who}", "amount": "60", "repeat": "monthly", "start": PM1[:8] + "01"}]
    r = S.post(B + O + "/fixed-costs/import", json={"items": items})
    check(r.status_code == 201 and r.json()["created"] == 2, f"{who}: setup fixed costs import {r.text[:200]}")
    fids = sorted(r.json()["ids"])
    r = S.post(B + O + "/fixed-costs/delete", json={"ids": fids})
    # 2.905.0 (#5414): every row into the core's trash (one step of the person), the office trash lists each (core = ofixed)
    check(r.ok and r.json().get("deleted") == 2 and len(sql("SELECT 1 FROM office_fixed_costs WHERE id IN (?,?) AND deleted_at IS NOT NULL", tuple(fids))) == 2,
          f"{who}: the import taken back goes into the trash {r.text[:200]}")
    n = sorted(x["id"] for x in S.get(B + O + "/trash").json()["items"] if x.get("core") == "ofixed" and x["id"] in fids)
    check(n == fids, f"{who}: the office trash lists its rows ({n})")
    rs = [S.post(B + f"{O}/trash/core/ofixed/{x}/restore") for x in fids]
    back = sorted(x[0] for x in sql("SELECT id FROM office_fixed_costs WHERE id IN (?,?) AND deleted_at IS NULL", tuple(fids)))
    check(all(x.ok for x in rs) and back == fids, f"{who}: the office trash brings every imported row back {[x.text[:100] for x in rs]} {back}")
    rr = sql("SELECT r.undone_at FROM office_import_runs r JOIN office_fixed_costs f ON f.import_run_id=r.id WHERE f.id=?", (fids[0],))
    check(rr and rr[0][0] is None, f"{who}: the import run counts as not undone again {rr}")

    # ------------------------------------------------------------ an import of trips taken back (last: it locks a month)
    me = S.get(B + "/api/state").json()["me"]["id"]
    trips = [{"date_from": PM1, "dest": f"Bonn {who}", "purpose": "job", "people": [{"id": me}]},
             {"date_from": PM2, "dest": f"Essen {who}", "purpose": "job", "people": [{"id": me}]}]
    r = S.post(B + O + "/trips/import", json={"trips": trips})
    check(r.status_code == 201 and r.json()["created"] == 2, f"{who}: setup trips import {r.text[:200]}")
    tids = sorted(r.json()["ids"])
    # 2.1005.0 (#5415): each trip of the import taken back lies in the core's trash (kind otrip); the office trash lists them
    # one by one and its restore brings each back unchanged with its run counting as not undone again
    live = "SELECT id FROM office_trips WHERE id IN (?,?) AND deleted_at IS NULL"
    r = S.post(B + O + "/trips/delete", json={"ids": tids})
    check(r.ok and r.json().get("deleted") == 2 and r.json().get("trash") == {"kind": "otrip", "ids": tids} and not sql(live, tuple(tids)),
          f"{who}: the trips import taken back: both in the trash {r.text[:200]}")
    n = sorted(x["id"] for x in S.get(B + O + "/trash").json()["items"] if x.get("core") == "otrip" and x["id"] in tids)
    check(n == tids, f"{who}: the office trash lists both trips ({n})")
    check(other.post(B + f"{O}/trash/core/otrip/{tids[0]}/restore").status_code in (403, 404), f"{who}: another office: the restore 403 / 404")
    rs = [S.post(B + f"{O}/trash/core/otrip/{x}/restore") for x in tids]
    check(all(x.ok for x in rs) and len(sql(live, tuple(tids))) == 2, f"{who}: the office trash brings both trips back {[x.text[:100] for x in rs]}")
    rr = sql("SELECT r.undone_at FROM office_import_runs r JOIN office_trips t ON t.import_run_id=r.id WHERE t.id=?", (tids[0],))
    check(rr and rr[0][0] is None, f"{who}: the import run counts as not undone again {rr}")
    r = S.post(B + O + "/trips/delete", json={"ids": tids})
    # #3506 (CI red of 2.579.0): the trips the restore brought back are unchanged, so a second take-back takes them again
    check(r.ok and r.json().get("deleted") == 2, f"{who}: taken back again after the restore {r.text[:200]}")
    m = PM1[:7]
    lock = S.post(B + O + "/periods/lock", json={"through": m, "confirm": f"{m[5:7]}/{m[:4]}"})
    check(lock.ok, f"{who}: setup the month of the trips locked {lock.text[:200]}")
    r = S.post(B + f"{O}/trash/core/otrip/{tids[0]}/restore")
    check(r.status_code == 409 and not sql(live, tuple(tids)) and sql("SELECT 1 FROM office_trips WHERE id=?", (tids[0],)),
          f"{who}: a month locked since: 409, nothing comes back, it stays in the trash {r.status_code} {r.text[:200]}")


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
