#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.355.0 C (#2844): the e-invoice categories of goods (no server, office/einvoice.py loaded on its own). Invented names only.
 - vat_note eu_goods = category K (intra-Community supply), exemption code VATEX-EU-IC, both VAT ids, the deliver-to
   country (BT-80, BR-IC-12) in CII (ShipToTradeParty) and UBL (Delivery/DeliveryLocation)
 - vat_note export = category G, VATEX-EU-G, the seller's VAT id (BR-G-02); abroad (a service) stays O with a register number
 - writes p2355c-*.xml to tests/.data/einvoice/ for the KoSIT validator (CI job einvoice: tools/einvoice_validate.sh)
usage: p2355_c_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
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
from kt import FAILS, OKS, check  # noqa: E402

SENDER = {"name": "Studio Beispiel GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@studio.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_no": "HRB 00000",
          "managing_directors": "Jana Muster"}
EU = {"name": "Beispielkunde GmbH", "lines": ["Beispielkunde GmbH", "Marktgasse 5", "1010 Wien"], "street": "Marktgasse 5", "zip": "1010",
      "city": "Wien", "country": "AT", "vat_id": "ATU12345675", "customer_no": "K-0042", "buyer_reference": "PO-REF-77",
      "email_invoice": "rechnung@kunde.example"}
US = {"name": "Example Inc", "lines": ["Example Inc", "1 Main Street", "Springfield 12345"], "street": "1 Main Street", "zip": "12345",
      "city": "Springfield", "country": "US", "vat_id": "", "customer_no": "K-0043", "buyer_reference": "PO-REF-78",
      "email_invoice": "billing@example.com"}


def fixture(note, rc):
    lines = [{"kind": "item", "pos": 1, "title": "Kamera-Zubehör", "qty": 2, "unit": "piece", "rate": "450.00", "tax_pct": 0, "net": "900.00"}]
    tot = {"net": "900.00", "tax": "0.00", "gross": "900.00", "paid": "0.00", "tax_lines": []}
    return {"kind": "invoice", "lang": "de", "currency": "EUR", "locked": True, "number": "RE-2026-200", "date": "2026-10-01",
            "due_date": "2026-10-15", "service_from": "2026-09-28", "service_to": "2026-09-28", "project_title": "", "order_ref": "",
            "vat_mode": "novat", "vat_note_key": note, "vat_note_text": "", "sender_fields": dict(SENDER), "recipient": dict(rc),
            "lines": lines, "totals": tot, "cancels": None,
            "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 15.10.2026 ohne Abzug."}}


C = dict(ein.NS)
U = {"cac": ein.UBL_NS["cac"], "cbc": ein.UBL_NS["cbc"]}


def ct(x, path):
    e = ET.fromstring(x).find(path, C)
    return (e.text or "").strip() if e is not None else None


def ut(x, path):
    e = ET.fromstring(x).find(path, U)
    return (e.text or "").strip() if e is not None else None


os.makedirs(OUT, exist_ok=True)


def write(name, data):
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(data)


TT = "rsm:SupplyChainTradeTransaction/"
# ---------------------------------------------------------------- K: goods to a business in another EU state
for fmt in ("zugferd", "xrechnung"):
    x = ein.ein_build(fixture("eu_goods", EU), fmt)
    tax = TT + "ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/"
    check(ct(x, tax + "ram:CategoryCode") == "K" and ct(x, tax + "ram:ExemptionReasonCode") == "VATEX-EU-IC" and ct(x, tax + "ram:RateApplicablePercent") == "0.00"
          and Decimal(ct(x, tax + "ram:CalculatedAmount")) == 0, f"CII {fmt}: category K, VATEX-EU-IC, 0 %")
    check(ct(x, TT + "ram:ApplicableHeaderTradeDelivery/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID") == "AT",
          f"CII {fmt}: deliver-to country AT (BR-IC-12)")
    ag = TT + "ram:ApplicableHeaderTradeAgreement/"
    check(ct(x, ag + "ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") == "DE123456789"
          and ct(x, ag + "ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") == "ATU12345675", f"CII {fmt}: both VAT ids (BR-IC-02)")
    check(ct(x, TT + "ram:ApplicableHeaderTradeSettlement/ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString") == "20260928",
          f"CII {fmt}: the delivery date as the period (BR-IC-11)")
    check(ein.ein_check(x) == [], f"CII {fmt}: own check {ein.ein_check(x)}")
    write(f"p2355c-k-{fmt}.xml", x)
xu = ein.ein_ubl_build(fixture("eu_goods", EU), "xrechnung")
check(ut(xu, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == "K" and ut(xu, "cac:Delivery/cac:DeliveryLocation/cac:Address/cac:Country/cbc:IdentificationCode") == "AT",
      "UBL: category K, deliver-to country AT")
kids = [e.tag.split("}")[1] for e in ET.fromstring(xu)]
check(kids.index("Delivery") == kids.index("AccountingCustomerParty") + 1 and kids.index("Delivery") < kids.index("PaymentMeans"), f"UBL: Delivery in schema order {kids}")
check(ein.ein_ubl_check(xu) == [], f"UBL: own check {ein.ein_ubl_check(xu)}")
write("p2355c-k-ubl.xml", xu)

# ---------------------------------------------------------------- G: export of goods to a third country
x = ein.ein_build(fixture("export", US), "zugferd")
tax = TT + "ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/"
check(ct(x, tax + "ram:CategoryCode") == "G" and ct(x, tax + "ram:ExemptionReasonCode") == "VATEX-EU-G", "CII: export = G, VATEX-EU-G")
check(ct(x, TT + "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") == "DE123456789", "CII: G keeps the seller's VAT id (BR-G-02)")
check(ct(x, TT + "ram:ApplicableHeaderTradeDelivery/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID") is None, "CII: no deliver-to party for G")
write("p2355c-g-zugferd.xml", x)
write("p2355c-g-ubl.xml", ein.ein_ubl_build(fixture("export", US), "en16931"))

# ---------------------------------------------------------------- O: a service to a third country (2.296) stays O
x = ein.ein_build(fixture("abroad", US), "zugferd")
check(ct(x, tax + "ram:CategoryCode") == "O", "CII: a service abroad stays O")
write("p2355c-o-zugferd.xml", x)

print(f"p2355_c_einvoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
