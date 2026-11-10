#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.530.0 C API tests (#4315, #4316): office things that were deleted for good at once now go through the office trash,
and two locks of the documents space hold. Own container (kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - #4315 B13: a finalised quotation that was never sent: deleting it puts a copy into the office trash, restore brings it
   back with its number, positions and the lock
 - #4315 B17: a trip with receipts and a single travel receipt: deleting puts a copy into the office trash (trash_id), the
   undo (POST /api/office/trips/trash/<id>/restore) and the office trash bring it back with the old ids; another
   organisation 404, a member 403, a month locked since: 409 and nothing comes back
 - #4316 B14: "no receipt" (assignment emptied) of an open receipt in an office: the row goes as before, the lock from its
   arrival stays (doc_meta.kept_until): deleting for good 409, the trash period run leaves the file in the trash
 - #4316 B31: a received business letter (linked to a letter of the office) is kept like a receipt: deleting for good 409,
   the run leaves it; a document without link next to it goes (the run works)
The same for a person without an organisation (freelancer_fixture: the personal office).
usage: p2530_c_office_trash_test.py <datadir>"""
import base64
import os
import subprocess
from datetime import timedelta, timezone

import kt
from kt import B, CT, check, sess
import testclock
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
D, T = O + "/docs", O + "/trips"
TODAY = testclock.today()
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10)  # the 10th of the previous month (it can be locked)
PM1, PM2 = PM.isoformat(), (PM + timedelta(days=1)).isoformat()
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def old_iso():
    return (testclock.now() - timedelta(days=40)).astimezone(timezone.utc).isoformat(timespec="seconds")


def tick():
    """The trash period run of the file store with the switch on (tp_tick, forced)."""
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_RETENTION_PURGE=1", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.files.trashpurge import tp_tick\n"
                          # 2.809.0 (#5365): file-store nodes go through the core's run (files/fskern.py)
                          "from kalmido.core.writes import obj_trash_tick\n"
                          "c = connect()\nprint('counts', tp_tick(c, True), obj_trash_tick(c, True))\nc.close()"], capture_output=True, text=True)
    check("counts" in out.stdout and "Traceback" not in out.stderr, "the trash run ran " + (out.stdout + out.stderr)[-600:])


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


def to_trash_old(s, nid, who, what):
    check(s.delete(B + f"/api/files/nodes/{nid}").ok, f"{who}: {what} into the trash")
    sql("UPDATE fs_nodes SET deleted_at=? WHERE id=?", (old_iso(), nid))


def scenario(S, who, ws, other, member=None):
    # ------------------------------------------------------------ #4315 B13: a finalised quotation, never sent
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    r = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Imagefilm {who}", "client_id": cl,
                            "items": [{"title": "Concept", "qty": 1, "rate": 800}]})
    check(r.status_code == 201, f"{who}: setup quotation {r.text[:200]}")
    did = r.json()["id"]
    r = S.post(B + f"{D}/{did}/finalize")
    check(r.ok and r.json().get("locked") is True and r.json().get("number"), f"{who}: finalised {r.text[:200]}")
    num = r.json().get("number")
    r = S.delete(B + f"{D}/{did}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid and not sql("SELECT 1 FROM office_docs WHERE id=?", (did,)),
          f"{who} B13: the finalised quotation goes with a copy in the office trash {r.text[:200]}")
    lst = S.get(B + O + "/trash").json()
    check(any(x["id"] == tid and x["kind"] == "doc" and x["sub"] == "offer" for x in lst["items"]), f"{who}: the office trash lists it {lst}")
    check(other.post(B + f"{O}/trash/{tid}/restore").status_code in (403, 404), f"{who}: another office cannot restore it")
    # 2.530.0 (#4315, review K1): its number was given again meanwhile -> 409, never a locked quotation without a number
    d2 = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": f"Spot {who}", "client_id": cl}).json()["id"]
    sql("UPDATE office_docs SET number=? WHERE id=?", (num, d2))
    r = S.post(B + f"{O}/trash/{tid}/restore")
    check(r.status_code == 409 and not sql("SELECT 1 FROM office_docs WHERE id=?", (did,)) and sql("SELECT 1 FROM office_trash WHERE id=?", (tid,)),
          f"{who} K1: the number is taken: 409, the copy stays {r.status_code} {r.text[:200]}")
    sql("UPDATE office_docs SET number='' WHERE id=?", (d2,))
    r = S.post(B + f"{O}/trash/{tid}/restore")
    d = S.get(B + f"{D}/{did}").json()
    check(r.ok and d.get("number") == num and d.get("locked") is True and [x["title"] for x in d.get("items") or []] == ["Concept"],
          f"{who} B13: restored with its number, position and lock {r.text[:200]} {d.get('number')} {d.get('locked')}")

    # ------------------------------------------------------------ #4315 B17: a trip with receipts, a single receipt
    r = S.post(B + T, json={"date_from": PM1, "date_to": PM2, "dest": f"Hamburg {who}", "overnight": True,
                            "items": [{"date": PM1, "category": "train", "amount": "59.90", "currency": "EUR"},
                                      {"date": PM2, "category": "hotel", "amount": "120.00", "currency": "EUR"}]})
    check(r.status_code == 201 and len(r.json().get("items") or []) == 2, f"{who}: setup trip with two receipts {r.text[:200]}")
    trip = r.json()["id"]
    items = sorted(x["id"] for x in r.json()["items"])
    r = S.delete(B + f"{T}/{trip}")
    tt = r.json().get("trash_id") if r.ok else None
    check(r.ok and tt and r.json().get("trip", {}).get("id") == trip and not sql("SELECT 1 FROM office_trips WHERE id=?", (trip,)),
          f"{who} B17: the trip goes with a copy in the office trash {r.text[:200]}")
    check(any(x["id"] == tt and x["kind"] == "trip" and "Hamburg" in x["label"] for x in S.get(B + O + "/trash").json()["items"]),
          f"{who}: the office trash lists the trip")
    check(other.post(B + f"/api/office/trips/trash/{tt}/restore").status_code in (403, 404), f"{who}: another office: the undo 403 / 404")
    if member is not None:
        check(member.post(B + f"/api/office/trips/trash/{tt}/restore").status_code == 403, f"{who}: a member: the undo 403")
    r = S.post(B + f"/api/office/trips/trash/{tt}/restore")
    check(r.ok and r.json().get("id") == trip and sorted(x["id"] for x in r.json().get("items") or []) == items,
          f"{who} B17: the undo brings the trip back with its receipts (same ids) {r.text[:200]}")
    check(S.post(B + f"/api/office/trips/trash/{tt}/restore").status_code == 404, f"{who}: a second undo 404")
    # a single receipt
    r = S.delete(B + f"{T}/{trip}/items/{items[0]}")
    ti = r.json().get("trash_id") if r.ok else None
    check(r.ok and ti and len(r.json()["trip"]["items"]) == 1, f"{who} B17: a receipt goes with a copy {r.text[:200]}")
    r = S.post(B + f"{O}/trash/{ti}/restore")
    check(r.ok and r.json().get("kind") == "trip_item", f"{who}: the office trash restores the receipt {r.text[:200]}")
    check(sorted(x[0] for x in sql("SELECT id FROM office_trip_items WHERE trip_id=?", (trip,))) == items, f"{who}: both receipts again (same ids)")
    # 2.603.0 A (#4555): a trip in an open month with a receipt paid ahead in the month that gets locked
    t0 = TODAY.isoformat()
    r = S.post(B + T, json={"date_from": t0, "date_to": t0, "dest": f"Bremen {who}", "overnight": False,
                            "items": [{"date": PM1, "category": "train", "amount": "39.90", "currency": "EUR"},
                                      {"date": t0, "category": "taxi", "amount": "18.50", "currency": "EUR"}]})
    check(r.status_code == 201 and len(r.json().get("items") or []) == 2, f"{who}: setup trip with a receipt ahead {r.text[:200]}")
    trip2 = r.json()["id"]
    early, late = (next(x["id"] for x in r.json()["items"] if x["date"] == d) for d in (PM1, t0))
    r = S.post(B + T, json={"date_from": t0, "date_to": t0, "dest": f"Kiel {who}", "overnight": False,
                            "items": [{"date": PM1, "category": "train", "amount": "29.90", "currency": "EUR"}]})
    trip3 = r.json()["id"] if r.status_code == 201 else None
    r = S.delete(B + f"{T}/{trip3}")
    t3 = r.json().get("trash_id") if r.ok else None
    check(trip3 and t3, f"{who}: setup a whole trip with a receipt ahead in the trash {r.text[:200]}")
    # a month locked since the delete: nothing comes back
    r = S.delete(B + f"{T}/{trip}")
    tt = r.json().get("trash_id")
    m = PM1[:7]
    lock = S.post(B + O + "/periods/lock", json={"through": m, "confirm": f"{m[5:7]}/{m[:4]}"})
    check(lock.ok, f"{who}: setup the month of the trip locked {lock.text[:200]}")
    r = S.post(B + f"/api/office/trips/trash/{tt}/restore")
    check(r.status_code == 409 and not sql("SELECT 1 FROM office_trips WHERE id=?", (trip,)) and sql("SELECT 1 FROM office_trash WHERE id=?", (tt,)),
          f"{who}: a month locked since: the undo 409, the copy stays {r.text[:200]}")
    r = S.post(B + f"{O}/trash/{tt}/restore")
    check(r.status_code == 409 and not sql("SELECT 1 FROM office_trips WHERE id=?", (trip,)), f"{who}: the office trash 409 as well {r.text[:200]}")
    # 2.603.0 A (#4555): a single receipt in an open month comes back although another receipt of its trip lies in the
    # locked month - over both routes; the whole trip with that receipt stays 409
    for how, route in (("the undo", "/api/office/trips/trash/{}/restore"), ("the office trash", O + "/trash/{}/restore")):
        r = S.delete(B + f"{T}/{trip2}/items/{late}")
        tl = r.json().get("trash_id") if r.ok else None
        check(r.ok and tl, f"{who} #4555: the open receipt goes to the trash {r.text[:200]}")
        r = S.post(B + route.format(tl))
        check(r.ok and sql("SELECT 1 FROM office_trip_items WHERE id=?", (late,)),
              f"{who} #4555: {how} brings the open receipt back next to a locked one {r.status_code} {r.text[:200]}")
    check(sorted(x[0] for x in sql("SELECT id FROM office_trip_items WHERE trip_id=?", (trip2,))) == sorted((early, late)),
          f"{who} #4555: both receipts of the trip there")
    for how, route in (("the undo", "/api/office/trips/trash/{}/restore"), ("the office trash", O + "/trash/{}/restore")):
        r = S.post(B + route.format(t3))
        check(r.status_code == 409 and not sql("SELECT 1 FROM office_trips WHERE id=?", (trip3,)),
              f"{who} #4555: {how} of a whole trip with a receipt in the locked month stays 409 {r.status_code} {r.text[:200]}")

    # ------------------------------------------------------------ #4316 B14: "no receipt" keeps the lock from its arrival
    n1 = upload(S, ws, f"beleg-{who}.pdf")
    r = S.put(B + f"/api/docs/{n1}/receipt", json={"category": "Software", "keep": True})
    check(r.ok and r.json()["receipt"]["is_receipt"], f"{who}: setup an open receipt {r.text[:200]}")
    r = S.put(B + f"/api/docs/{n1}/receipt", json={"category": "", "vat_pct": None, "project_id": None})
    check(r.ok and not r.json()["receipt"]["is_receipt"], f"{who}: no receipt any more (the row goes as before) {r.text[:200]}")
    ku = sql("SELECT kept_until FROM doc_meta WHERE node_id=?", (n1,))
    check(ku and ku[0][0], f"{who} B14: the lock from its arrival stays (kept_until) {ku}")
    to_trash_old(S, n1, who, "the former receipt")
    r = S.delete(B + f"/api/files/nodes/{n1}?purge=1")
    check(r.status_code == 409 and "Kept by law until" in r.text, f"{who} B14: deleting it for good 409 {r.text[:200]}")

    # ------------------------------------------------------------ #4316 B31: a received business letter
    n2 = upload(S, ws, f"brief-{who}.pdf")
    r = S.post(B + O + "/letters", json={"subject": "Ihr Schreiben", "answers": n2})
    check(r.status_code == 201, f"{who}: a letter answering the document {r.text[:200]}")
    check(sql("SELECT 1 FROM office_letter_links WHERE node_id=?", (n2,)), f"{who}: the link")
    to_trash_old(S, n2, who, "the received letter")
    r = S.delete(B + f"/api/files/nodes/{n2}?purge=1")
    check(r.status_code == 409 and "Kept by law until" in r.text, f"{who} B31: deleting the received letter for good 409 {r.text[:200]}")
    n3 = upload(S, ws, f"anderes-{who}.pdf")  # without link: the run deletes it (the control)
    to_trash_old(S, n3, who, "a plain document")
    return n1, n2, n3


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

alice = scenario(A, "alice", f"org:{ORG}", Ca, member=Bo)
frida = scenario(Fr, "frida", "private", A)

tick()
for who, (n1, n2, n3) in (("alice", alice), ("frida", frida)):
    check(sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (n1,)), f"{who} B14: the run leaves the former receipt in the trash")
    check(sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (n2,)), f"{who} B31: the run leaves the received letter in the trash")
    check(not sql("SELECT 1 FROM fs_nodes WHERE id=?", (n3,)), f"{who}: the plain document goes (the run deletes)")

raise SystemExit(kt.done("p2530_c_office_trash"))
