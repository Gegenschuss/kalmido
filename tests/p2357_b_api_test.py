#!/usr/bin/env python3
# kalmido-suite:
"""2.357.0 B (#3180, #3181) API tests: the print model and PDF of invoices and reminders, own container (start.sh). Invented
companies, people and figures only. freelancer-matrix: office
 - #3180 the printed company: tax number and VAT ID in the register column (not the bank column), every word label with a
   colon ("Steuernummer:", "E-Mail:"), an abbreviation without one ("Tel.", "USt-IdNr."); in the PDF footer whole
 - #3181 an invoice names its project title once: bold below the title, no "Betreff" row in the head's key data; one rate =
   no VAT column; a reminder without a fee ends with the outstanding amount (no "Gesamtbetrag" with the same value), one
   with a fee keeps fee and total
 - each for an organisation's admin and for a person without organisation (personal office)
usage: p2357_b_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import pdfcheck  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, B, H, DATA  # noqa: E402,F401

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
PROJECT = "Imagefilm Hafenlichter"


def pdf_text(data):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


for who, S in (("org admin", A), ("freelancer", F)):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "reminder_fee": 5, "reminder_deadline_days": 10,
                                         "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                            "country": "DE", "email": "kontakt@example.com", "phone": "+49 40 1234567",
                                                            "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
                                                            "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: office settings " + r.text[:160])
    r = S.post(B + D, json={"kind": "invoice", "project_title": PROJECT, "recipient": {"name": "Beispielkunde AG", "lines": ["Marktplatz 2", "54321 Beispielort"]},
                            "service_from": "2026-05-01", "items": [{"title": "Kamera", "qty": 1, "rate": 500}, {"title": "Schnitt", "qty": 2, "rate": 400}]})
    check(r.status_code == 201, f"{who}: invoice draft " + r.text[:160])
    IID = r.json()["id"]
    r = S.post(B + f"{D}/{IID}/finalize")
    check(r.ok and r.json().get("number"), f"{who}: invoice finalised " + r.text[:160])
    rd = S.get(B + f"{D}/{IID}/render").json()
    co = rd["company"]
    # ---- #3180 the footer columns
    check(any(x == "Steuernummer: 12/345/67890" for x in co["register_lines"]) and any(x == "USt-IdNr. DE999999999" for x in co["register_lines"])
          and not any("12/345/67890" in x or "DE999999999" in x for x in co["bank_lines"]), f"{who}: #3180 tax lines in the register column {co}")
    check("E-Mail: kontakt@example.com" in co["contact_lines"] and any(x.startswith("Tel. +49") for x in co["contact_lines"]),
          f"{who}: #3180 colon after a word, none after an abbreviation {co['contact_lines']}")
    # ---- #3181 the project title once
    check(rd["project_title"] == PROJECT and not any(PROJECT == str(v) for _, v in rd["meta"]), f"{who}: #3181 no Betreff row in the key data {rd['meta']}")
    r = S.get(B + f"{D}/{IID}/pdf")
    check(r.ok and r.content[:5] == b"%PDF-", f"{who}: invoice PDF {r.status_code}")
    t = pdf_text(r.content)
    check(t.count(PROJECT) == 1 and "Betreff" not in t, f"{who}: #3181 the project title printed once ({t.count(PROJECT)})")
    lay = pdfcheck.layout(r.content)
    check(not any(x["s"] == "MWST." for p in lay for x in p["texts"]), f"{who}: #3181 one rate, no VAT column")
    check(not pdfcheck.problems(r.content), f"{who}: invoice layout clean {pdfcheck.problems(r.content)[:3]}")
    feet = "\n".join(ln for fl in pdfcheck.footer_lines(r.content) for ln in fl)
    check("Steuernummer: 12/345/67890" in feet and "USt-IdNr. DE999999999" in feet, f"{who}: #3180 tax lines whole in the PDF footer")
    # ---- #3181 reminders: the total only with a fee (2.355.0 D #2846: only an overdue invoice gets a reminder)
    dbxm.q(DATA, "UPDATE office_docs SET due_date=? WHERE id=?", ("2026-01-15", IID))
    r = S.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 1})
    check(r.status_code == 201 and r.json()["totals"]["fee"] in ("0.00", "0"), f"{who}: level 1 reminder without a fee " + r.text[:160])
    R1 = r.json()["id"]
    rows = S.get(B + f"{D}/{R1}/render").json()["totals"]["rows"]
    check(len(rows) == 1 and rows[0][1] == "1.547,00 €", f"{who}: #3181 a reminder without a fee: only the outstanding amount {rows}")
    t = pdf_text(S.get(B + f"{D}/{R1}/pdf").content)
    check("1.547,00 €" in t and "Gesamtbetrag" not in t, f"{who}: #3181 no 'Gesamtbetrag' in the PDF without a fee")
    r = S.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 2, "fee": 5})
    check(r.status_code == 201, f"{who}: level 2 reminder with a fee " + r.text[:160])
    rows = S.get(B + f"{D}/{r.json()['id']}/render").json()["totals"]["rows"]
    check(len(rows) == 3 and rows[1][1] == "5,00 €" and rows[-1] == ["Gesamtbetrag", "1.552,00 €"], f"{who}: #3181 with a fee: fee and total stay {rows}")

sys.exit(done("p2357_b_api"))
