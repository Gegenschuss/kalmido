#!/usr/bin/env python3
"""2.509.0 (#4331) API test, own container: a part payment on a finalised invoice without a stored file (an older document): the
rebuilt PDF has no paid / outstanding rows, like its XML; the preview (/render) keeps them. A person without an organisation.
freelancer-matrix: office"""
# kalmido-suite: fresh
import io
import subprocess

from pypdf import PdfReader

import kt
from kt import B, check, sess

kt.fresh()
A = kt.setup()
r = A.post(B + "/api/users", json={"username": "frida", "display_name": "Frida", "password": "password123", "email": "frida@example.com", "orgs": []})
check(r.ok, "a person without an organisation " + r.text[:120])
Fr = sess("frida")
Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "office,clients"})
r = Fr.put(B + "/api/office/settings", json={"lang": "en", "company_fields": {
    "name": "Studio Nordlicht", "street": "Weg 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@nordlicht.example",
    "phone": "040 123456", "vat_id": "DE123456789", "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "office settings " + r.text[:160])
CL = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktweg 5", "zip": "50667", "city": "Koeln", "country": "DE", "email": "kunde@example.com"}).json()["id"]
D = B + "/api/office/docs"
r = Fr.post(D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-10-01", "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
check(r.ok, "an invoice " + r.text[:160])
DID = r.json()["id"]
check(Fr.post(f"{D}/{DID}/finalize").ok, "finalised")


def pdf_text():
    r = Fr.get(f"{D}/{DID}/pdf")
    check(r.status_code == 200, f"the PDF: {r.status_code}")
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(r.content)).pages)


stored = pdf_text()
# 2.523.0 (#4082): a typed payment is not dated before the invoice (finalised today) - the invoice's own date
r = Fr.post(f"{D}/{DID}/payments", json={"amount": 100, "date": str(Fr.get(f"{D}/{DID}").json()["date"])[:10]})
check(r.status_code == 201, "a part payment " + r.text[:160])
rd = Fr.get(f"{D}/{DID}/render").json()
paid, due = rd["totals"]["rows"][-2:]
check(rd["totals"]["paid"] == "100.00" and "1,090" in due[1] and paid[0] and due[0], f"the preview shows the payment state: {rd['totals']['rows']}")
check(paid[0] not in stored and due[0] not in stored, "the stored PDF never had them")
check(pdf_text() == stored, "the stored PDF is served unchanged after the payment")

# an older finalised document: no stored file, no checksum: the PDF is rebuilt
subprocess.run(["docker", "exec", kt.CT, "sh", "-c", f"find /data -type f -name 'doc{DID}-*' -delete"], check=True)
kt.dbx("UPDATE office_docs SET pdf_sha256='', xml_sha256='' WHERE id=?", (DID,))
built = pdf_text()
check(rd["totals"]["gross_text"] in built, "the rebuilt PDF shows the invoice total")
check(paid[0] not in built, f"the rebuilt PDF has no row {paid[0]}: {built[-300:]}")
check(due[0] not in built, f"the rebuilt PDF has no row {due[0]}")
rd2 = Fr.get(f"{D}/{DID}/render").json()
check(paid in rd2["totals"]["rows"] and due in rd2["totals"]["rows"], "the preview keeps them")
raise SystemExit(kt.done("p2509_b_paidrows"))
