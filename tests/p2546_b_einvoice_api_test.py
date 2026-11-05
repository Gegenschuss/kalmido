#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.546.0 B (#4289): e-invoices from the real finalising, for the validators. Invented companies and figures only.
freelancer-matrix: office
The other writers of tests/.data/einvoice/ build their files from hand-made print models (pure Python); this suite makes
the invoices through the server's own routes (office settings, client, document, positions, finalise) and takes the files
the server stored: GET /api/office/docs/<id>/pdf (PDF/A-3, ZUGFeRD with the embedded XML) and .../xml (CII, ZUGFeRD or
XRechnung). The CI job "E-invoice validators" runs it and checks every file with veraPDF and the KoSIT validator, with a
minimum number of these files (MIN_FILES) so that a case lost here cannot pass as "nothing to check".
 - cases: 19 % + 7 % (ZUGFeRD and XRechnung with the buyer reference), discount (a discount position at 19 % as
   ZUGFeRD, one at 7 % as XRechnung; an invoice has no discount percentage of its own), reverse charge to a client in
   another EU country (AE, both VAT ids), a credit note (381) on the first invoice, and the 19 % + 7 % case once more
   as a person without an organisation (personal office)
 - each: finalised with a number, the own check (einvoice.ein_check) finds nothing, the PDF is PDF/A-3 (ZUGFeRD: with the
   XML embedded; XRechnung: without), the tax lines of the XML are the ones of the case (19 / 7, AE 0)
 - the files: tests/.data/einvoice/real-<case>.pdf / .xml (the data dir of the server is another one: start.sh wipes it)
usage: p2546_b_einvoice_api_test.py <datadir>      (P2546E_NOSTART=1 / KMT_NOSTART=1: a running server)"""
import importlib.util
import os
import sys
import xml.etree.ElementTree as ET

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OUT = os.path.join(N, ".data", "einvoice")
MIN_FILES = 14  # 7 cases x (PDF + XML); the CI step checks the same number
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
spec = importlib.util.spec_from_file_location("einvoice", os.path.join(SRC, "kalmido", "office", "einvoice.py"))
ein = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ein)
AG = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"

fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2546E")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.startswith("real-"):
        os.remove(os.path.join(OUT, f))
WRITTEN = []


def office(S, who):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                         "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                            "country": "DE", "email": "kontakt@example.com", "phone": "+49 30 000000",
                                                            "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
                                                            "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: office settings + company fields " + r.text[:160])
    out = {}
    for key, body in (("de", {"name": "Beispielkunde AG", "street": "Marktplatz 2", "zip": "54321", "city": "Beispielort", "country": "DE",
                              "vat_id": "DE987654321", "buyer_reference": "04011000-12345-03", "email_invoice": "rechnung@example.com"}),
                      ("fr", {"name": "Exemple SARL", "street": "1 rue Exemple", "zip": "75001", "city": "Paris", "country": "FR",
                              "vat_id": "FR12345678901", "email_invoice": "compta@example.com"})):
        r = S.post(B + "/api/clients", json=body)
        check(r.status_code == 201, f"{who}: client {key} " + r.text[:160])
        out[key] = r.json().get("id")
    return out


ITEMS = [{"title": "Filmherstellung", "qty": 3, "unit": "day", "rate": 1000}, {"title": "Begleitbuch", "qty": 10, "unit": "piece", "rate": 12.5, "tax": "reduced"}]


def make(S, who, name, client, fmt, items, **head):
    """An invoice through the routes, finalised; its stored files into OUT -> (id, xml bytes)."""
    body = {"kind": "invoice", "project_title": "Imagefilm 2026", "client_id": client, "order_ref": "PO-77", "service_from": "2026-05-01",
            "service_to": "2026-05-31", "date": "2026-05-08", "payment_days": 14, "einvoice_format": fmt, **head}
    r = S.post(B + D, json=body)
    check(r.status_code == 201, f"{who} {name}: the invoice draft " + r.text[:160])
    did = r.json()["id"]
    r = S.put(B + f"{D}/{did}/items", json={"items": items})
    check(r.ok, f"{who} {name}: its positions " + r.text[:160])
    return did, finalise(S, who, name, did, fmt)


def finalise(S, who, name, did, fmt):
    r = S.post(B + f"{D}/{did}/finalize")
    check(r.ok and r.json().get("number"), f"{who} {name}: finalised with a number " + r.text[:160])
    pdf, xml = S.get(B + f"{D}/{did}/pdf"), S.get(B + f"{D}/{did}/xml")
    check(pdf.ok and pdf.content.startswith(b"%PDF-") and b"<pdfaid:part>3</pdfaid:part>" in pdf.content, f"{who} {name}: the stored PDF is PDF/A-3")
    check((b"/EmbeddedFile" in pdf.content) == (fmt == "zugferd"), f"{who} {name}: the XML embedded in the PDF only for ZUGFeRD")
    check(xml.ok and xml.content.lstrip().startswith(b"<?xml"), f"{who} {name}: the stored XML {xml.status_code}")
    probs = ein.ein_check(xml.content) if xml.ok else ["no XML"]
    check(probs == [], f"{who} {name}: the own check finds nothing {probs}")
    for ext, res in (("pdf", pdf), ("xml", xml)):
        if res.ok:
            p = os.path.join(OUT, f"real-{name}.{ext}")
            with open(p, "wb") as fh:
                fh.write(res.content)
            WRITTEN.append(p)
    return xml.content if xml.ok else b""


def tax_lines(xml):
    """[(category, percent)] of the XML's tax breakdown (BG-23)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for t in root.findall(AG + "ram:ApplicableTradeTax", ein.NS):
        cat, pct = t.find("ram:CategoryCode", ein.NS), t.find("ram:RateApplicablePercent", ein.NS)
        out.append(((cat.text or "") if cat is not None else "", float(pct.text) if pct is not None and pct.text else 0.0))
    return sorted(out)


def text(xml, path):
    try:
        x = ET.fromstring(xml).find(path, ein.NS)
    except ET.ParseError:
        return None
    return (x.text or "").strip() if x is not None else None


# ---------------------------------------------------------------- the organisation's office
CL = office(A, "org")
I1, x = make(A, "org", "01-std-zugferd", CL["de"], "zugferd", ITEMS)
check(tax_lines(x) == [("S", 7.0), ("S", 19.0)], f"01: 19 % and 7 % {tax_lines(x)}")
_, x = make(A, "org", "02-std-xrechnung", CL["de"], "xrechnung", ITEMS)
check(tax_lines(x) == [("S", 7.0), ("S", 19.0)] and text(x, "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/ram:BuyerReference") == "04011000-12345-03",
      f"02: XRechnung, 19 % and 7 %, the buyer reference {tax_lines(x)}")
_, x = make(A, "org", "03-discount-line-zugferd", CL["de"], "zugferd",
            ITEMS + [{"kind": "discount", "title": "Rabatt", "qty": 1, "unit": "flat", "rate": 100}])
basis = text(x, AG + "ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount")
check(tax_lines(x) == [("S", 7.0), ("S", 19.0)] and basis is not None and abs(float(basis) - 3025) < 0.005,
      f"03: a discount position of 100 (3125.00 -> 3025.00 net: {basis}) {tax_lines(x)}")
# an invoice has no discount percentage of its own (calc.inv_calc: a discount is a position): here one at 7 %, as XRechnung
_, x = make(A, "org", "04-discount-reduced-xrechnung", CL["de"], "xrechnung",
            ITEMS + [{"kind": "discount", "title": "Mengenrabatt Buch", "qty": 1, "unit": "flat", "rate": 25, "tax": "reduced"}])
basis = text(x, AG + "ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount")
check(tax_lines(x) == [("S", 7.0), ("S", 19.0)] and basis is not None and abs(float(basis) - 3100) < 0.005,
      f"04: a discount position at 7 % (3125.00 -> 3100.00 net: {basis}) {tax_lines(x)}")
_, x = make(A, "org", "05-reverse-charge", CL["fr"], "zugferd", [ITEMS[0]], vat_mode="novat", vat_note="reverse")
check(tax_lines(x) == [("AE", 0.0)], f"05: reverse charge AE 0 % {tax_lines(x)}")
r = A.post(B + f"{D}/{I1}/credit")
check(r.status_code == 201, "06: a credit note draft on invoice 01 " + r.text[:160])
if r.status_code == 201:
    x = finalise(A, "org", "06-credit-note", r.json()["id"], "zugferd")
    check(text(x, "rsm:ExchangedDocument/ram:TypeCode") == "381", f"06: type 381 ({text(x, 'rsm:ExchangedDocument/ram:TypeCode')})")

# ---------------------------------------------------------------- a person without an organisation
FC = office(F, "freelancer")
_, x = make(F, "freelancer", "07-freelancer-zugferd", FC["de"], "zugferd", ITEMS)
check(tax_lines(x) == [("S", 7.0), ("S", 19.0)], f"07: the personal office, 19 % and 7 % {tax_lines(x)}")

check(len(WRITTEN) >= MIN_FILES, f"at least {MIN_FILES} files from the real finalising in {OUT} ({len(WRITTEN)})")
print(f"p2546_b_einvoice_api: {len(WRITTEN)} files in {OUT}", flush=True)
sys.exit(done("p2546_b_einvoice_api"))
