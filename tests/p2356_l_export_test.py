#!/usr/bin/env python3
# kalmido-suite: now=wed10:00
"""2.356.0 API tests, leader part (#3097): the bookkeeping export and the GoBD export leave nothing out silently.
Invented people, firms and figures only (example.com).
freelancer-matrix: office
 - GoBD export: no trial invoice in invoices.csv / positions.csv / payments.csv (as DATEV and the bookkeeping export);
   receipts without a date or an amount are counted (check: left_out) and named in missing.txt, index.xml says so
 - bookkeeping export: check names the receipts left out (no_date, no_amount); the list's "File" column is the name
   inside the ZIP; an invoice file that does not match its checksum is named in missing.txt and its list rows have
   no file instead of a path to nothing
 - the books page counts the receipts of the year the exports leave out (incomplete)
 - all of it in a personal office (a person without an organisation, its own admin)
usage: p2356_l_export_test.py <datadir>"""
import csv
import io
import os
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, B, DATA, check, done, fresh, setup, until  # noqa: E402,F401

O = "/api/office"
D = O + "/docs"
TODAY = testclock.today().isoformat()
MONTH = TODAY[:7]
P = f"?from={MONTH}-01&to={TODAY}"
COMPANY = {"name": "Frida Film", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def dbx(q, args=()):
    """A write in the suite's database."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


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


fresh()
A = setup()
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
assert Fr.put(B + O + "/settings", json={"lang": "en", "company_fields": COMPANY}).ok
CL = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktweg 5", "zip": "50667", "city": "Köln", "country": "DE",
                                       "email_invoice": "billing@kunde.example", "payment_terms_days": 14}).json()["id"]


def invoice(title, is_trial=False):
    r = Fr.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": title, "service_from": TODAY,
                             "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if is_trial:
        dbx("UPDATE office_docs SET trial=1 WHERE id=?", (did,))
    r = Fr.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    assert Fr.post(B + f"{D}/{did}/payments", json={"date": TODAY, "amount": 100, "method": "transfer"}).ok
    return did, Fr.get(B + f"{D}/{did}").json()["number"]


I1, N1 = invoice("Echte Rechnung")
I2, N2 = invoice("Probe Rechnung", is_trial=True)
UWS = Fr.get(B + O + "/books").json()["upload_ws"]


def receipt(name, amount="119.00"):
    r = Fr.post(B + "/api/docs", data={"ws": UWS}, files={"files": (name + ".pdf", tiny_pdf(name), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: (lambda x: x.ok and x.json()["state"] in ("done", "failed"))(Fr.get(B + f"/api/docs/{nid}")), 90)
    assert Fr.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": TODAY, "name": name}).ok
    assert Fr.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True}).ok
    return nid


R1, R2, R3 = receipt("Beleg Komplett"), receipt("Beleg Ohne Betrag"), receipt("Beleg Ohne Datum")
dbx("UPDATE doc_meta SET amount='' WHERE node_id=?", (R2,))
dbx("UPDATE doc_meta SET doc_date='' WHERE node_id=?", (R3,))
dbx("UPDATE rc_receipts SET paid_at='' WHERE node_id=?", (R3,))

# ---------------------------------------------------------------- GoBD
r = Fr.get(B + O + "/gobd/export" + P + "&check=1")
j = r.json() if r.ok else {}
check(r.ok and j["counts"]["invoices.csv"] == 1 and j["counts"]["payments.csv"] == 1,
      f"GoBD check: the trial invoice and its payment are not in the auditor export {r.status_code} {j}")
check(j.get("left_out") == 2, f"GoBD check: two receipts left out (no amount, no date) {j.get('left_out')}")
r = Fr.get(B + O + "/gobd/export" + P)
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
inv = z.read("invoices.csv").decode("utf-8") if z else ""
check(N1 in inv and N2 not in inv, f"GoBD invoices.csv: the real invoice, not the trial one ({N1} / {N2})")
pos = z.read("positions.csv").decode("utf-8") if z else ""
check(f"{I1};" in pos and f";{I2};" not in pos, "GoBD positions.csv: no positions of the trial invoice")
miss = z.read("missing.txt").decode("utf-8") if z and "missing.txt" in z.namelist() else ""
check("Beleg Ohne Betrag" in miss and "Beleg Ohne Datum" in miss and "Beleg Komplett" not in miss, f"GoBD missing.txt names the two receipts: {miss!r}")
idx = z.read("index.xml").decode("utf-8") if z else ""
check("2 Belege ohne Datum oder Betrag" in idx and "Formelschutz" in idx, "GoBD index.xml: the receipts left out and the formula guard are named")

# ---------------------------------------------------------------- bookkeeping export
r = Fr.get(B + O + "/books/export" + P + "&check=1")
j = r.json() if r.ok else {}
check(j.get("no_date") == 1 and j.get("no_amount") == 1 and j.get("receipts") == 1 and j.get("documents") == 1,
      f"books export check: one receipt in, one without date, one without amount, no trial invoice {j}")


def bx_zip():
    r = Fr.get(B + O + "/books/export" + P + "&zip=1")
    assert r.ok, r.text[:200]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if n.endswith(".csv"))
    rows = list(csv.reader(io.StringIO(z.read(name).decode("utf-8-sig")), delimiter=";" if ";" in z.read(name).decode("utf-8-sig")[:200] else ","))
    files = {x[2]: x[-1] for x in rows[1:] if x[2] == N1 and x[0] == "Invoice"}  # not the payment row
    miss = next((z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".txt")), "")
    return z.namelist(), files, miss


names, files, miss = bx_zip()
check(files.get(N1) in names, f"books export: the list's file column is the name inside the ZIP ({files} / {names})")
check("Beleg Ohne Betrag" in miss and "Beleg Ohne Datum" in miss, f"books export: missing.txt names the receipts left out {miss!r}")
dbx("UPDATE office_docs SET pdf_sha256=? WHERE id=?", ("0" * 64, I1))  # the stored PDF no longer matches its checksum
names, files, miss = bx_zip()
check(N1 in miss and files.get(N1) == "" and not any(N1 in n for n in names if n.startswith("documents/")),
      f"books export: a damaged invoice file is named in missing.txt, its row has no file ({files} {miss!r})")

# ---------------------------------------------------------------- the books page
j = Fr.get(B + O + f"/books?year={TODAY[:4]}").json()
check(j.get("incomplete") == 2, f"books page: two receipts of the year are not in the exports ({j.get('incomplete')})")

sys.exit(done("p2356_l_export"))
