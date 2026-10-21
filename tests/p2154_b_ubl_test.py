#!/usr/bin/env python3
"""2.154.0 B (#1960): the UBL 2.1 e-invoice (kalmido/office/einvoice.py ein_ubl_build) -- Peppol BIS Billing 3.0, XRechnung
UBL and plain EN 16931 from the same print model as the CII, no server, no container.
 - Peppol invoice: CustomizationID / ProfileID of Peppol BIS 3.0, EndpointID with the Peppol ids (9930 / 0208), one note,
   one tax total with subtotals, amounts with currency, BT-10 (or the customer number when neither BT-10 nor BT-13 exists);
   ein_ubl_check finds nothing
 - round trip: UBL -> office/einvoice_in.py ei_parse -> the same number, date, net / tax / gross and lines as the CII
 - credit note (CreditNote, type 381, BT-25), USD (BT-6 + the second TaxTotal in EUR), reverse charge (AE + reason),
   a discount line (negative quantity, positive price) and a line whose rate does not give its net (price 4 places / qty 1)
 - XRechnung UBL without a buyer reference is refused like the CII; without Peppol ids the e-mail is the address (EM)
 - writes the EN 16931 / XRechnung variants to tests/.data/einvoice/ubl-*.xml for the KoSIT validator (CI job einvoice:
   the XRechnung configuration) and the Peppol variants ubl-*-peppol.xml (the OpenPeppol rules on top, scenarios added by
   tools/kosit_peppol_scenarios.py); ein_ubl_check is the quick check of the Peppol points without Java
usage: p2154_b_ubl_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import os
import sys
from decimal import Decimal
from xml.etree import ElementTree as ET

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OUT = os.path.join(N, ".data", "einvoice")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ein = load("einvoice")
ein_in = load("einvoice_in")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


SENDER = {"name": "Studio Beispiel GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@studio.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_no": "HRB 00000",
          "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde NV", "lines": ["Beispielkunde NV", "Marktstraat 5", "1000 Brussel"], "street": "Marktstraat 5", "zip": "1000",
             "city": "Brussel", "country": "BE", "vat_id": "BE0123456749", "customer_no": "K-0042", "buyer_reference": "PO-REF-77",
             "email_invoice": "invoices@kunde.example"}


def item(pos, title, rate, qty=1, net=None, pct=21):
    net = net if net is not None else f"{qty * float(rate):.2f}"
    return {"kind": "item", "pos": pos, "title": title, "qty": qty, "unit": "hour", "rate": rate, "tax_pct": pct, "net": net}


def fixture(kind="invoice", currency="EUR", vat_note_key="", lines=None, tax_lines=None, rc=None):
    lines = lines or [{"kind": "heading", "title": "Leistungen"}, item(1, "Konzept", "95.00", 8), item(2, "Schnitt", "80.00", 12.5)]
    net = sum(Decimal(x["net"]) for x in lines if x.get("kind") != "heading")
    tax = Decimal("0") if vat_note_key else (net * Decimal("0.21")).quantize(Decimal("0.01"))
    tot = {"net": f"{net:.2f}", "tax": f"{tax:.2f}", "gross": f"{net + tax:.2f}", "paid": "0.00",
           "tax_lines": tax_lines if tax_lines is not None else ([] if vat_note_key else [{"pct": "21", "base": f"{net:.2f}", "amount": f"{tax:.2f}"}])}
    if currency == "USD":
        tot["tax_eur"] = f"{tax / Decimal('1.09'):.2f}"
    return {"kind": kind, "lang": "de", "currency": currency, "locked": True, "number": "RE-2026-100" if kind == "invoice" else "GS-2026-007",
            "date": "2026-10-01", "due_date": "2026-10-15" if kind == "invoice" else "", "service_from": "2026-09-01", "service_to": "2026-09-30",
            "project_title": "Imagefilm", "order_ref": "", "vat_mode": "novat" if vat_note_key else "vat", "vat_note_key": vat_note_key,
            "vat_note_text": "", "sender_fields": dict(SENDER), "recipient": dict(rc if rc is not None else RECIPIENT), "lines": lines, "totals": tot,
            "cancels": {"number": "RE-2026-099", "date": "2026-09-20"} if kind == "credit" else None,
            "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 15.10.2026 ohne Abzug."}}


Q = {"cac": ein.UBL_NS["cac"], "cbc": ein.UBL_NS["cbc"]}


def tx(xml, path):
    x = ET.fromstring(xml).find(path, Q)
    return (x.text or "").strip() if x is not None else None


def el(xml, path):
    return ET.fromstring(xml).find(path, Q)


os.makedirs(OUT, exist_ok=True)
for fn in os.listdir(OUT):
    if fn.startswith("ubl-"):
        os.remove(os.path.join(OUT, fn))


def write(name, data):
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------- 1. Peppol BIS 3.0 invoice with Peppol ids
m = fixture()
x = ein.ein_ubl_build(m, "peppol", sender_id="9930:DE123456789", receiver_id="0208:0123456749")
check(x.startswith(b'<?xml version="1.0" encoding="UTF-8"?>') and b"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" in x, "a UBL Invoice")
check(tx(x, "cbc:CustomizationID") == "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0", "Peppol BIS 3.0 CustomizationID")
check(tx(x, "cbc:ProfileID") == "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0", "Peppol ProfileID")
ep = el(x, "cac:AccountingSupplierParty/cac:Party/cbc:EndpointID")
check(ep is not None and ep.text == "DE123456789" and ep.get("schemeID") == "9930", "seller EndpointID 9930")
ep = el(x, "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID")
check(ep is not None and ep.text == "0123456749" and ep.get("schemeID") == "0208", "buyer EndpointID 0208")
check(tx(x, "cbc:InvoiceTypeCode") == "380" and tx(x, "cbc:IssueDate") == "2026-10-01" and tx(x, "cbc:DueDate") == "2026-10-15", "type, dates")
check(tx(x, "cbc:BuyerReference") == "PO-REF-77", "BT-10")
check(tx(x, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount") == "1760.00" and tx(x, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount") == "2129.60"
      and tx(x, "cac:LegalMonetaryTotal/cbc:PayableAmount") == "2129.60" and tx(x, "cac:TaxTotal/cbc:TaxAmount") == "369.60", "sums")
check(tx(x, "cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName") == "Studio Beispiel GmbH", "BT-27")
check(tx(x, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID") == "DE02120300000000202051", "IBAN")
check(len(ET.fromstring(x).findall("cac:InvoiceLine", Q)) == 2, "two lines (the heading is no line)")
check(ein.ein_ubl_check(x) == [], f"ein_ubl_check: {ein.ein_ubl_check(x)}")
write("ubl-invoice-peppol.xml", x)

# round trip through the reader of incoming e-invoices
inv = ein_in.ei_parse(x)
check(inv["format"] == "ubl" and inv["number"] == "RE-2026-100" and inv["date"] == "2026-10-01", f"round trip head: {inv['number']} {inv['date']}")
check((inv["net"], inv["vat"], inv["gross"], inv["payable"]) == ("1760.00", "369.60", "2129.60", "2129.60"), f"round trip sums: {inv['net']} {inv['vat']} {inv['gross']}")
check(len(inv["lines"]) == 2 and inv["lines"][0]["net"] == "760.00", f"round trip lines: {inv['lines']}")
check(inv["seller"].get("vat_id") == "DE123456789" and inv["buyer"].get("vat_id") == "BE0123456749", "round trip VAT ids")
xc = ein.ein_build(m, "zugferd")
ic = ein_in.ei_parse(xc)
check((ic["net"], ic["vat"], ic["gross"]) == (inv["net"], inv["vat"], inv["gross"]), "UBL and CII carry the same sums")

# without Peppol ids: the e-mail addresses (EM); EN 16931 variant for KoSIT
x2 = ein.ein_ubl_build(m, "en16931")
ep = el(x2, "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID")
check(ep is not None and ep.get("schemeID") == "EM" and ep.text == "invoices@kunde.example", "buyer EndpointID EM")
check(tx(x2, "cbc:CustomizationID") == "urn:cen.eu:en16931:2017", "EN 16931 CustomizationID")
write("ubl-invoice-en16931.xml", x2)

# PEPPOL-EN16931-R003: no BT-10 and no BT-13 -> the customer number stands in
m3 = fixture(rc={**RECIPIENT, "buyer_reference": ""})
x3 = ein.ein_ubl_build(m3, "peppol", "9930:DE123456789", "0208:0123456749")
check(tx(x3, "cbc:BuyerReference") == "K-0042" and ein.ein_ubl_check(x3) == [], "customer number as BT-10")
m3["recipient"]["customer_no"] = ""
x3 = ein.ein_ubl_build(m3, "peppol", "9930:DE123456789", "0208:0123456749")
check(any("R003" in f for f in ein.ein_ubl_check(x3)), "ein_ubl_check names R003 without any reference")

# ---------------------------------------------------------------- 2. XRechnung UBL
try:
    ein.ein_ubl_build(fixture(rc={**RECIPIENT, "buyer_reference": ""}), "xrechnung")
    check(False, "XRechnung UBL without a buyer reference is refused")
except ein.BadInput:
    check(True, "")
rde = {**RECIPIENT, "country": "DE", "zip": "50667", "city": "Köln", "street": "Marktstraße 5", "vat_id": "DE987654321", "buyer_reference": "04011000-12345-03"}
mx = fixture(rc=rde)
for ln in mx["lines"]:
    if ln.get("kind") == "item":
        ln["tax_pct"] = 19
mx["totals"]["tax_lines"] = [{"pct": "19", "base": "1760.00", "amount": "334.40"}]
mx["totals"]["gross"] = "2094.40"
xx = ein.ein_ubl_build(mx, "xrechnung")
check(tx(xx, "cbc:CustomizationID") == ein.UBL_PROFILES["xrechnung"] and tx(xx, "cbc:BuyerReference") == "04011000-12345-03", "XRechnung UBL head")
check(tx(xx, "cac:AccountingSupplierParty/cac:Party/cac:Contact/cbc:Telephone") == "+49 40 000000", "seller contact (BR-DE-2)")
write("ubl-invoice-xrechnung.xml", xx)

# ---------------------------------------------------------------- 3. credit note, USD, reverse charge, discount, odd rate
cn = fixture("credit")
xcn = ein.ein_ubl_build(cn, "peppol", "9930:DE123456789", "0208:0123456749")
check(b"urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2" in xcn and tx(xcn, "cbc:CreditNoteTypeCode") == "381", "CreditNote 381")
check(tx(xcn, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID") == "RE-2026-099", "BT-25")
check(len(ET.fromstring(xcn).findall("cac:CreditNoteLine", Q)) == 2 and ein.ein_ubl_check(xcn) == [], f"credit lines + check: {ein.ein_ubl_check(xcn)}")
check(ein_in.ei_parse(xcn)["kind"] == "credit_note", "the reader sees a credit note")
write("ubl-credit-peppol.xml", xcn)
write("ubl-credit-en16931.xml", ein.ein_ubl_build(cn, "en16931"))

mu = fixture(currency="USD")
xu = ein.ein_ubl_build(mu, "peppol", "9930:DE123456789", "0208:0123456749")
tts = ET.fromstring(xu).findall("cac:TaxTotal", Q)
check(tx(xu, "cbc:TaxCurrencyCode") == "EUR" and len(tts) == 2 and tts[1].find("cbc:TaxAmount", Q).get("currencyID") == "EUR", "USD: BT-6 + BT-111")
check(ein.ein_ubl_check(xu) == [], f"USD check: {ein.ein_ubl_check(xu)}")
write("ubl-invoice-usd-peppol.xml", xu)
write("ubl-invoice-usd-en16931.xml", ein.ein_ubl_build(mu, "en16931"))

mr = fixture(vat_note_key="reverse")
xr = ein.ein_ubl_build(mr, "peppol", "9930:DE123456789", "0208:0123456749")
check(tx(xr, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == "AE" and tx(xr, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode") == "VATEX-EU-AE"
      and tx(xr, "cac:TaxTotal/cbc:TaxAmount") == "0.00", "reverse charge AE")
write("ubl-invoice-reverse-peppol.xml", xr)
write("ubl-invoice-reverse-en16931.xml", ein.ein_ubl_build(mr, "en16931"))

lines = [item(1, "Konzept", "95.00", 8), {"kind": "discount", "pos": 2, "title": "Rabatt", "qty": 1, "rate": "-60.00", "tax_pct": 21, "net": "-60.00"},
         item(3, "Pauschale", "33.333", 3, net="100.00")]
md = fixture(lines=lines)
xd = ein.ein_ubl_build(md, "peppol", "9930:DE123456789", "0208:0123456749")
dl = ET.fromstring(xd).findall("cac:InvoiceLine", Q)
check(dl[1].find("cbc:InvoicedQuantity", Q).text == "-1" and dl[1].find("cac:Price/cbc:PriceAmount", Q).text == "60.00", "discount: quantity -1, price positive")
check(ein.ein_ubl_check(xd) == [], f"discount + odd rate check (R120): {ein.ein_ubl_check(xd)}")
check(tx(xd, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount") == "800.00", "discount sums")
write("ubl-invoice-discount-peppol.xml", xd)
write("ubl-invoice-discount-en16931.xml", ein.ein_ubl_build(md, "en16931"))

check(ein.ein_ubl_endpoint("0088:4000001000005") == ("0088", "4000001000005") and ein.ein_ubl_endpoint("DE123") is None, "endpoint parse")
# the CII builder is unchanged by the UBL one
check(ein.ein_check(ein.ein_build(fixture(), "zugferd")) == [], "CII still fine")

print("files for the validators:", sorted(f for f in os.listdir(OUT) if f.startswith("ubl-")))
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
