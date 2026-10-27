#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.357.0 A (#3156): the paper size per company (office settings "paper": "a4" | "letter") through the API. Own container
(start.sh). Invented companies and figures only; the letterhead PDFs are made here with the app's own writer.
freelancer-matrix: office
 - the setting: default "a4", "letter" saved and read back, anything else 400
 - an invoice, a letter and a document from a template in US-Letter: MediaBox 612 x 792, layout clean inside the 1 in
   margins, fold marks on the thirds and no punch mark; the EUeR list in Letter too; back to A4: A4 again (the default)
 - a finalised invoice keeps the size it was finalised with (frozen with the sender data) when the setting changes later
 - letterhead upload: in Letter an A4 letterhead is refused with a plain sentence, a Letter one is taken
 - a person without organisation (personal office): the same setting and the same Letter PDFs
usage: p2357_a_paper_test.py <datadir>      (P2357A_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

fresh(prefix="P2357A")
O = "/api/office"
D = O + "/docs"
MM = 72 / 25.4
IN = 72.0
A4, LETTER = (595.28, 841.89), (612.0, 792.0)
CO = {"name": "Beispielstudio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
      "email": "kontakt@example.com", "phone": "+49 30 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
      "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office

# the app's own writer for the letterheads made here (a Letter and an A4 page, PDF/A)
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(N, "..", "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)


def head_pdf(paper):
    P = pdf.pdf_paper_ns(paper)
    p = P._Page()
    p.rect(0, 0, P.A4_W, 20 * MM, "#2f5d8a")
    p.text(P.PDF_L, 8 * MM, "Beispielstudio Briefbogen", 12, True, "#ffffff")
    return P.pdf_write([p], {}, title="Briefbogen", author="Beispielstudio GmbH")


def boxes(data):
    return {(round(float(p.mediabox.width), 2), round(float(p.mediabox.height), 2)) for p in PdfReader(io.BytesIO(data)).pages}


def marks(data):
    p = pdfcheck.layout(data)[0]
    return sorted(round(r[1], 1) for r in p["rules"] if abs(r[1] - r[3]) < 0.01 and r[0] < 10 * MM and r[2] < 10 * MM)


def get_pdf(s, url, what):
    r = s.get(B + url)
    check(r.ok and r.content.startswith(b"%PDF"), f"{what}: PDF {r.status_code} {r.text[:120] if not r.ok else ''}")
    return r.content if r.ok else b""


def letter_ok(who, what, data, folds=True, right=1 * IN):
    check(boxes(data) == {LETTER}, f"#3156 {who}: {what} in US-Letter {boxes(data)}")
    pr = pdfcheck.problems(data, right=right)
    check(not pr, f"#3156 {who}: {what} layout clean in Letter {pr[:3]}")
    if folds:
        check(marks(data) == [264.0, 528.0], f"#3156 {who}: {what}: fold marks on the thirds, no punch mark {marks(data)}")


for who, s, name in (("org", A, "Beispielstudio GmbH"), ("freelancer", Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": dict(CO, name=name)})
    check(r.ok, f"{who}: company data saved {r.text[:200]}")
    st = s.get(B + O + "/settings").json()["settings"]
    check(st.get("paper") == "a4", f"#3156 {who}: the paper size defaults to A4 ({st.get('paper')!r})")
    r = s.put(B + O + "/settings", json={"paper": "legal"})
    check(r.status_code == 400, f"#3156 {who}: an unknown paper size is refused {r.status_code}")
    cl = s.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktplatz 2", "zip": "54321", "city": "Beispielort",
                                          "country": "DE"}).json().get("id")

    def invoice(n=3):
        r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-10-01", "service_to": "2026-10-20",
                                "items": [{"title": f"Leistung {i}", "qty": 1, "rate": 100} for i in range(1, n + 1)]})
        check(r.status_code == 201, f"{who}: invoice created {r.status_code} {r.text[:200]}")
        return r.json().get("id")

    a4inv = invoice()
    d = get_pdf(s, f"{D}/{a4inv}/pdf", f"{who} invoice A4")
    check(boxes(d) == {A4} and marks(d) == [round(105 * MM, 1), round(148.5 * MM, 1), round(210 * MM, 1)],
          f"#3156 {who}: A4 by default with fold + punch marks {boxes(d)} {marks(d)}")

    r = s.put(B + O + "/settings", json={"paper": "letter"})
    check(r.ok and s.get(B + O + "/settings").json()["settings"].get("paper") == "letter", f"#3156 {who}: Letter saved and read back {r.text[:120]}")
    letter_ok(who, "draft invoice", get_pdf(s, f"{D}/{a4inv}/pdf", f"{who} invoice Letter"))
    big = invoice(40)
    d = get_pdf(s, f"{D}/{big}/pdf", f"{who} long invoice")
    check(len(PdfReader(io.BytesIO(d)).pages) >= 2, f"#3156 {who}: 40 positions break over Letter pages")
    letter_ok(who, "long invoice", d)

    # a finalised invoice keeps its size
    fin = invoice()
    r = s.post(B + f"{D}/{fin}/finalize")
    check(r.ok and r.json().get("locked"), f"{who}: invoice finalised in Letter {r.text[:200]}")
    s.put(B + O + "/settings", json={"paper": "a4"})
    check(boxes(get_pdf(s, f"{D}/{fin}/pdf", f"{who} finalised invoice")) == {LETTER}, f"#3156 {who}: a finalised invoice stays Letter after the switch to A4")
    check(boxes(get_pdf(s, f"{D}/{a4inv}/pdf", f"{who} draft back to A4")) == {A4}, f"#3156 {who}: a draft follows the setting back to A4")
    s.put(B + O + "/settings", json={"paper": "letter"})

    # a letter, a document from a template, the EUeR
    r = s.post(B + O + "/letters", json={"rcpt_name": "Amt für Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt", "rcpt_email": "amt@example.com",
                                         "subject": "Antrag 7/2026", "body": "\n\n".join(["Sehr geehrte Damen und Herren, ein Absatz mit etwas Text. " * 6] * 12)})
    check(r.status_code == 201, f"{who}: letter created {r.status_code} {r.text[:200]}")
    d = get_pdf(s, O + f"/letters/{r.json().get('id')}/pdf", f"{who} letter")
    check(len(PdfReader(io.BytesIO(d)).pages) >= 2, f"#3156 {who}: a long letter over several Letter pages")
    letter_ok(who, "letter", d)
    r = s.post(B + O + "/doc-templates", json={"starter": "contract"})
    check(r.status_code == 201, f"{who}: a template {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/gen-docs", json={"template_id": r.json().get("id"), "client_id": cl})
    check(r.status_code == 201, f"{who}: a document {r.status_code} {r.text[:200]}")
    letter_ok(who, "document from a template", get_pdf(s, O + f"/gen-docs/{r.json().get('id')}/pdf", f"{who} template document"))
    r = s.get(B + O + "/books/euer.pdf?year=2026")
    if r.status_code != 404:  # the EUeR only where the country pack offers it
        check(r.ok and boxes(r.content) == {LETTER} and not pdfcheck.problems(r.content, foot=False, right=0),
              f"#3156 {who}: the EUeR list in Letter {r.status_code} {boxes(r.content) if r.ok else r.text[:120]}")

    # an entertainment receipt and the cash book
    host = s.get(B + "/api/state").json()["me"]["id"]
    r = s.post(B + O + "/meals", json={})
    check(r.status_code == 201, f"{who}: meal created {r.status_code} {r.text[:200]}")
    mid = r.json().get("id")
    r = s.patch(B + O + f"/meals/{mid}", json={"date": "2026-10-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
                                               "occasion": "Follow-up order", "host": {"id": host}, "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}],
                                               "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "0"})
    check(r.ok, f"{who}: meal saved {r.text[:200]}")
    letter_ok(who, "entertainment receipt", get_pdf(s, O + f"/meals/{mid}/pdf", f"{who} meal"), folds=False)
    r = s.post(B + O + "/cashbooks", json={"name": "Kasse", "opening": "10", "opening_day": "2026-03-01"})
    check(r.status_code == 201, f"{who}: cash box {r.status_code} {r.text[:200]}")
    d = get_pdf(s, O + f"/cashbook.pdf?book_id={r.json().get('id')}&year=2026", f"{who} cash book")
    check(boxes(d) == {LETTER} and not pdfcheck.problems(d, foot=False, right=0), f"#3156 {who}: the cash book in Letter {boxes(d)}")

    # letterhead upload in the chosen size
    r = s.post(B + O + "/letterhead", files={"file": ("a4.pdf", head_pdf("a4"), "application/pdf")})
    check(r.status_code == 400 and "US-Letter" in r.json().get("error", ""), f"#3156 {who}: an A4 letterhead is refused in Letter {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/letterhead", files={"file": ("letter.pdf", head_pdf("letter"), "application/pdf")})
    check(r.ok and r.json()["letterhead"]["on"], f"#3156 {who}: a Letter letterhead is taken {r.status_code} {r.text[:200]}")
    d = get_pdf(s, f"{D}/{big}/pdf", f"{who} invoice on the letterhead")
    check(boxes(d) == {LETTER}, f"#3156 {who}: the invoice on the Letter letterhead stays Letter {boxes(d)}")
    s.delete(B + O + "/letterhead")
    s.put(B + O + "/settings", json={"paper": "a4"})
    check(boxes(get_pdf(s, f"{D}/{big}/pdf", f"{who} back to A4")) == {A4}, f"#3156 {who}: back to A4")

sys.exit(done("p2357_a_paper"))
