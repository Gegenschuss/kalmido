#!/usr/bin/env python3
# kalmido-suite:
"""2.356.0 D (#3129, #3006, #3007): the office for members - receipts handed in to the bookkeeping, the open items.
Invented companies, people and figures only (@example.com, PDFs made here). freelancer-matrix: office  tenant-matrix: office, receipt
 - #3129: a member (no bookkeeping) hands in two receipts (POST /api/office/receipts/submit): stored in the office's documents
   as her own, marked rc_receipts.submitted_by; "My receipts handed in" (GET /api/office/receipts/mine) lists only hers with
   the status submitted -> processed (the bookkeeping saved the receipt) / removed (deleted); she sees no other receipt, no
   bookkeeping, no cash book, not the list of handed-in receipts; another member does not see her files; read-only 403; a
   group "Staff" may hand in, a group "Read only" not; the admin sees the receipts handed in (with "by") and in the receipts
   list (submitted_by); a person of another organisation sees nothing of it; GET /api/office/settings submit only for the
   people who may hand in and do not see the bookkeeping
 - the freelancer (personal office, her own admin): submit works and is a normal receipt of her bookkeeping, submit flag off
 - #3007: the invoice list's status open = the open items (finalised, open amount > 0, overdue included; no draft, no paid
   invoice); its sum is the figure "Open invoices" of /api/office/kpi; the same for the freelancer
usage: p2356_d_members_test.py <datadir>   (P2356D_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import os
import sys
from decimal import Decimal

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
SUB, MINE, INB = O + "/receipts/submit", O + "/receipts/mine", O + "/receipts/submitted"
RL = O + "/books/receipts"
P = {"from": "2000-01-01", "to": "2099-12-31"}


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


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def submit(s, *names):
    return s.post(B + SUB, files=[("files", (n, tiny_pdf("Beleg " + n), "application/pdf")) for n in names])


def mine(s):
    r = s.get(B + MINE)
    return {x["node_id"]: x for x in r.json()["rows"]} if r.ok else None


kt.fresh(prefix="P2356D")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids, S = {}, {}
for u, n in (("bob", "Bob Member"), ("sam", "Sam Staff"), ("rita", "Rita Reader"), ("gus", "Gus Group"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta Werkstatt", "admin_id": ids["carol"]}).json()["id"]
for u, role in (("bob", "member"), ("sam", "member"), ("rita", "readonly"), ("gus", "member")):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": role}).ok
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
for u in ids:
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG2 if u == 'carol' else ORG}"})
Bo, Sa, Ri, Gu, Ca = S["bob"], S["sam"], S["rita"], S["gus"], S["carol"]
BOB = ids["bob"]
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office: its owner is its admin)

# ---------------------------------------------------------------- schema
cols = {r[0] for r in kt.dbx("SELECT column_name FROM information_schema.columns WHERE table_name='rc_receipts' AND column_name LIKE 'submitted%'")}
check(cols == {"submitted_by", "submitted_at"}, f"rc_receipts.submitted_by / submitted_at added ({cols})")

# ---------------------------------------------------------------- the flag for the menu
flag = lambda s: s.get(B + O + "/settings").json().get("submit")  # noqa: E731
check(flag(Bo) is True, "settings: a member may hand in receipts (submit true)")
check(flag(A) is False and flag(Ri) is False and flag(Fr) is False, "settings: admin, read-only and the freelancer: submit false")

# ---------------------------------------------------------------- the admin's own receipt (the member must never see it)
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": ("admin-beleg.pdf", tiny_pdf("Admin Beleg"), "application/pdf")})
assert r.status_code == 201, r.text
RA = r.json()["ids"][0]
assert A.patch(B + f"/api/docs/{RA}", json={"amount": "119.00", "date": "2026-03-02"}).ok
assert A.put(B + f"/api/docs/{RA}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True}).ok

# ---------------------------------------------------------------- a member hands in two receipts
r = submit(Bo, "taxi-bob.pdf", "hotel-bob.pdf")
check(r.status_code == 201 and len(r.json().get("ids") or []) == 2, f"member: submit two receipts 201 ({r.status_code} {r.text[:200]})")
R1, R2 = (r.json().get("ids") or [0, 0])[:2]
row = kt.dbx("SELECT submitted_by, submitted_at, ws FROM rc_receipts WHERE node_id=?", (R1,))
check(row and row[0][0] == BOB and row[0][1] and row[0][2] == f"o{ORG}", f"stored as a receipt of the office, handed in by Bob ({row})")
own = kt.dbx("SELECT owner_id, created_by, org_id FROM fs_nodes WHERE id=?", (R1,))
check(own and own[0][2] == ORG and BOB in (own[0][0], own[0][1]), f"the file lies in the organisation's documents as Bob's own ({own})")
m = mine(Bo)
check(m is not None and set(m) == {R1, R2} and all(x["status"] == "submitted" for x in m.values()), f"member: My receipts handed in = her two, submitted ({m})")
check(submit(Bo, "taxi-bob.pdf").status_code == 200, "the same file again: no second receipt (200, dups)")
check(Bo.post(B + SUB).status_code == 400, "no file: 400")

# ---------------------------------------------------------------- what the member does NOT see
check(Bo.get(B + f"/api/docs/{RA}").status_code in (403, 404), "member: the admin's receipt 403/404")
check(Bo.get(B + RL, params=P).status_code == 403, "member: the receipts list of the bookkeeping 403")
check(Bo.get(B + O + "/books").status_code == 403 and Bo.get(B + O + "/cashbooks").status_code == 403, "member: bookkeeping and cash book 403")
check(Bo.get(B + INB).status_code == 403, "member: the list of receipts handed in (bookkeeping) 403")
check(Sa.get(B + f"/api/docs/{R1}").status_code in (403, 404), "another member does not see Bob's receipt")
check(mine(Sa) == {}, "another member: My receipts handed in is empty")
check(Ca.get(B + f"/api/docs/{R1}").status_code in (403, 404), "tenant-matrix: a person of another organisation: Bob's receipt 403/404")
check(mine(Ca) == {}, "tenant-matrix: another organisation's admin: nothing of Bob's in her list")

# ---------------------------------------------------------------- read-only and the office groups
r = submit(Ri, "rita.pdf")
check(r.status_code == 403, f"read-only member: submit 403 ({r.status_code})")
assert A.put(B + O + f"/rights/people/{ids['sam']}", json={"groups": ["tpl:staff"]}).ok
assert A.put(B + O + f"/rights/people/{ids['gus']}", json={"groups": ["tpl:readonly"]}).ok
r = submit(Sa, "sam.pdf")
check(r.status_code == 201, f"group Staff (receipts: own): submit 201 ({r.status_code} {r.text[:160]})")
check(mine(Sa) is not None and len(mine(Sa)) == 1, "group Staff: sees the own receipt handed in")
check(flag(Sa) is True, "group Staff: submit flag on")
check(submit(Gu, "gus.pdf").status_code == 403, "group Read only (receipts: view): submit 403")

# ---------------------------------------------------------------- the admin works on them
r = A.get(B + INB)
inb = {x["node_id"]: x for x in r.json().get("rows", [])} if r.ok else {}
check(r.ok and {R1, R2} <= set(inb) and inb.get(R1, {}).get("by", {}).get("name") == "Bob Member", f"admin: the receipts handed in, with the person ({r.status_code} {r.text[:200]})")
check(A.get(B + f"/api/docs/{R1}").ok, "admin opens Bob's receipt")
assert A.patch(B + f"/api/docs/{R1}", json={"amount": "42.50", "date": "2026-03-04"}).ok
r = A.put(B + f"/api/docs/{R1}/receipt", json={"category": "Travel", "vat_pct": "7", "keep": True})
check(r.ok, "admin saves the receipt " + r.text[:120])
check(mine(Bo).get(R1, {}).get("status") == "processed", "member: the receipt the bookkeeping saved shows processed")
inb = {x["node_id"] for x in A.get(B + INB).json()["rows"]}
check(R1 not in inb and R2 in inb, "admin: a receipt worked on leaves the list of handed-in ones")
# 2.356.0 (#3129, review M1): a receipt the bookkeeping took over stays as booked -- its submitter cannot trash or replace it
r = Bo.delete(B + f"/api/files/nodes/{R1}")
check(r.status_code == 409 and "taken over" in r.text, f"member: the receipt the bookkeeping took over cannot go into the trash ({r.status_code} {r.text[:120]})")
r = Bo.post(B + f"/api/files/nodes/{R1}/versions", files={"file": ("taxi-bob.pdf", tiny_pdf("other image"), "application/pdf")})
check(r.status_code == 409, f"member: no new version of a taken-over receipt ({r.status_code} {r.text[:120]})")
SR = next(iter(mine(Sa) or {0: None}))
check(Sa.delete(B + f"/api/files/nodes/{SR}").ok and mine(Sa).get(SR, {}).get("status") == "removed",
      "a member takes back a receipt the bookkeeping has not taken over yet (status removed)")
rl = {x["node_id"]: x for x in A.get(B + RL, params=P).json()["rows"]}
check(rl.get(R1, {}).get("submitted_by") == "Bob Member" and rl.get(RA, {}).get("submitted_by") is None,
      f"receipts list: handed in by Bob marked, the admin's own not ({rl.get(R1)}, {rl.get(RA)})")
check(A.delete(B + f"/api/files/nodes/{R2}").ok, "admin deletes the second receipt")
check(mine(Bo).get(R2, {}).get("status") == "removed", "member: the deleted receipt shows removed")
check(Ca.get(B + INB).status_code == 200 and Ca.get(B + INB).json()["rows"] == [], "tenant-matrix: another organisation's admin: no receipt of Alpha")

# ---------------------------------------------------------------- the freelancer: her own admin, the same upload is a normal receipt
r = submit(Fr, "fiona-beleg.pdf")
check(r.status_code == 201, f"freelancer: submit 201 ({r.status_code} {r.text[:160]})")
FR1 = (r.json().get("ids") or [0])[0]
row = kt.dbx("SELECT ws, org_id FROM rc_receipts WHERE node_id=?", (FR1,))
check(row and row[0][0] == f"u{FID}" and row[0][1] is None, f"freelancer: a receipt of her private documents ({row})")
check(Fr.get(B + f"/api/docs/{FR1}").ok and Fr.get(B + RL, params=P).ok, "freelancer: opens it, her receipts list 200")
check(Fr.get(B + INB).status_code == 200, "freelancer: the list of handed-in receipts of her own office 200")
check(A.get(B + f"/api/docs/{FR1}").status_code in (403, 404), "tenant-matrix: the admin of Alpha does not see the freelancer's receipt")

# ---------------------------------------------------------------- #3007 the open items
D = O + "/docs"


def invoice(s, cl, due, finalize=True, pay=False):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-05-01", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    i = r.json()["id"]
    if finalize:
        r = s.post(B + f"{D}/{i}/finalize")
        assert r.ok, r.text
    dbw("UPDATE office_docs SET due_date=? WHERE id=?", (due, i))  # (an overdue one without waiting)
    if pay:
        amt = s.get(B + f"{D}/{i}").json()["open"]
        assert s.post(B + f"{D}/{i}/payments", json={"amount": amt}).ok
    return i


def open_items(s):
    r = s.get(B + D, params={"kind": "invoice", "status": "open"})
    assert r.ok, r.text
    return {x["id"]: x for x in r.json()["docs"]}


for who, s, org in (("org", A, ORG), ("freelancer", Fr, None)):
    r = s.put(B + O + "/settings", json={"company_fields": {"name": "Studio Beispiel", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                           "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}})
    assert r.ok, r.text
    cl = s.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                          **({"org_id": org} if org else {})}).json()["id"]
    i_open = invoice(s, cl, "2099-12-31")
    i_over = invoice(s, cl, "2025-01-15")
    i_draft = invoice(s, cl, "2099-12-31", finalize=False)
    i_paid = invoice(s, cl, "2099-12-31", pay=True)
    op = open_items(s)
    check(set(op) == {i_open, i_over}, f"{who}: status open = the open items: open + overdue, no draft, no paid ({sorted(op)} vs {[i_open, i_over]})")
    k = s.get(B + O + "/kpi").json()["invoices"]
    tot = sum((Decimal(str(x["open"])) for x in op.values()), Decimal(0))
    check(k["open"]["count"] == len(op) and Decimal(k["open"]["amount"]) == tot, f"{who}: the figure equals the list ({k['open']} vs {tot})")
    check(all(s.get(B + D, params={"kind": "invoice", "status": st}).ok for st in ("overdue", "partial", "")), f"{who}: the other filters still answer")
check(Bo.get(B + D, params={"kind": "invoice", "status": "open"}).ok, "member (reads invoices): the open items filter answers")

sys.exit(kt.done("p2356_d_members"))
