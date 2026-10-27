#!/usr/bin/env python3
# kalmido-suite: after=p2296_b_invoice nodata
"""2.357.0 (#3217, #3218): tax categories of the e-invoice (kalmido/office/einvoice.py of the source tree), no server, no
container. Invented companies and figures only.
 - #3217 a line of the standard / reduced rate set to 0 % by the office (a true zero rate, e.g. UK) is category Z without
   an exemption reason (BR-Z-10), in CII and UBL; the key exempt stays E with its reason; ein_check names a Z breakdown
   with a reason
 - #3218 vat_note "abroad" without a register number but with a tax number: O (was G) with the tax number as seller
   identifier (BT-29, BR-CO-26), still no VAT ids (BR-O-02); without register and tax number it stays G
usage: p2357_l_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import copy
import importlib.util
import os
import sys
from xml.etree import ElementTree as ET

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)


def load(name):
    spec = importlib.util.spec_from_file_location("p2357l_" + name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ein = load("einvoice")
from kt import FAILS, OKS, check  # noqa: E402

SENDER = {"name": "Studio Nordlicht Ltd", "street": "1 Harbour Road", "zip": "EC1A 1AA", "city": "London", "country": "GB",
          "email": "post@studio.example", "phone": "+44 20 0000000", "tax_number": "12/345/67890", "vat_id": "GB999999973",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_no": "HRB 00000",
          "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE987654321", "customer_no": "K-0042", "buyer_reference": "04011000-12345-03",
             "email_invoice": "rechnung@beispielkunde.example"}


def line(pos, title, net, pct, tax="standard"):
    return {"kind": "item", "pos": pos, "title": title, "qty": 1, "unit": "flat", "rate": net, "tax": tax, "tax_pct": pct,
            "total": net, "net": f"{net:.2f}"}


def model(lines, tax_lines, gross, vat_note_key="", exempt_reason="", recipient=None, sender=None):
    net = sum(x["total"] for x in lines)
    tax = sum(float(t["amount"]) for t in tax_lines)
    return {"kind": "invoice", "lang": "en", "currency": "EUR", "locked": True, "status": "issued", "number": "RE-2026-357",
            "date": "2026-10-26", "title": "Invoice", "project_title": "Imagefilm", "order_ref": "PO-357",
            "service_from": "2026-10-01", "service_to": "2026-10-20", "due_date": "2026-11-09",
            "vat_mode": "novat" if vat_note_key else "vat", "vat_note_key": vat_note_key, "vat_note_text": "", "exempt_reason": exempt_reason,
            "sender_fields": dict(sender or SENDER), "recipient": dict(recipient or RECIPIENT), "company": {"name": SENDER["name"]},
            "lines": lines, "totals": {"net": f"{net:.2f}", "tax_lines": tax_lines, "tax": f"{tax:.2f}", "gross": f"{gross:.2f}", "paid": "0.00"},
            "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Payable by 9 November 2026."}}


S = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"


def breakdown(x):
    out = []
    for t in ET.fromstring(x).findall(S + "ram:ApplicableTradeTax", ein.NS):
        g = lambda p: (t.find(p, ein.NS).text if t.find(p, ein.NS) is not None else None)  # noqa: E731
        out.append((g("ram:CategoryCode"), g("ram:RateApplicablePercent"), g("ram:BasisAmount"), g("ram:ExemptionReason")))
    return out


def line_cats(x):
    return [li.find("ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode", ein.NS).text
            for li in ET.fromstring(x).findall("rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem", ein.NS)]


def seller_id(x):
    s = ET.fromstring(x).find("rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:ID", ein.NS)
    return s.text if s is not None else None


# ---------------------------------------------------------------- #3217 a true zero rate = Z, exempt stays E
check(ein._line_cat("S", 0, "standard") == "Z" and ein._line_cat("S", 0, "reduced") == "Z", "#3217: standard / reduced at 0 % = Z")
check(ein._line_cat("S", 0, "exempt") == "E" and ein._line_cat("S", 0) == "E", "#3217: exempt (and a line without key) stays E")
check(ein._line_cat("S", 19, "standard") == "S" and ein._line_cat("AE", 0, "standard") == "AE", "#3217: other categories unchanged")
mz = model([line(1, "Edit", 1000.0, 0), line(2, "Books", 200.0, 0, "reduced")],
           [{"rate_key": "standard", "pct": "0", "base": "1200.00", "amount": "0.00"}], 1200.0)
xz = ein.ein_build(mz, "zugferd")
bz = breakdown(xz)
check(line_cats(xz) == ["Z", "Z"], f"#3217: the zero rated lines are Z (was E): {line_cats(xz)}")
check(bz == [("Z", "0", "1200.00", None)], f"#3217: one breakdown Z 0 % without exemption reason (BR-Z-10): {bz}")
check(ein.ein_check(xz) == [], f"#3217: own check clean: {ein.ein_check(xz)}")
uz = ein.ein_ubl_build(mz, "peppol")
check(b"<cbc:ID>Z</cbc:ID>" in uz and b"TaxExemptionReason" not in uz and b"<cbc:ID>E</cbc:ID>" not in uz and ein.ein_ubl_check(uz) == [],
      f"#3217: UBL Z without exemption reason: {ein.ein_ubl_check(uz)}")
# a mixed invoice: Z for the zero rated line, E with the invoice's reason for the exempt one, S for the taxed one
mm = model([line(1, "Edit", 1000.0, 20), line(2, "Books", 200.0, 0, "reduced"), line(3, "Course", 300.0, 0, "exempt")],
           [{"rate_key": "standard", "pct": "20", "base": "1000.00", "amount": "200.00"}, {"rate_key": "reduced", "pct": "0", "base": "200.00", "amount": "0.00"},
            {"rate_key": "exempt", "pct": "0", "base": "300.00", "amount": "0.00"}], 1700.0, exempt_reason="Exempt education service")
xm = ein.ein_build(mm, "zugferd")
bm = breakdown(xm)
check(line_cats(xm) == ["S", "Z", "E"], f"#3217: mixed: S, Z, E per line: {line_cats(xm)}")
check(("Z", "0", "200.00", None) in bm and ("E", "0", "300.00", "Exempt education service") in bm and len(bm) == 3,
      f"#3217: mixed: Z without reason, E with the invoice's reason: {bm}")
check(ein.ein_check(xm) == [], f"#3217: mixed: own check clean: {ein.ein_check(xm)}")
um = ein.ein_ubl_build(mm, "peppol")
check(um.count(b"<cbc:TaxExemptionReason>") == 1 and ein.ein_ubl_check(um) == [], "#3217: mixed UBL: one exemption reason (the E subtotal)")
bad = xz.replace(b"<ram:BasisAmount>", b"<ram:ExemptionReason>x</ram:ExemptionReason><ram:BasisAmount>", 1)
check(any("BR-Z-10" in f for f in ein.ein_check(bad)), f"#3217: ein_check names a Z breakdown with an exemption reason: {ein.ein_check(bad)}")
ubad = uz.replace(b"<cbc:ID>Z</cbc:ID>", b"<cbc:ID>Z</cbc:ID><cbc:TaxExemptionReason>x</cbc:TaxExemptionReason>", 1)
check(any("BR-Z-10" in f for f in ein.ein_ubl_check(ubad)), f"review N3: ein_ubl_check names a Z subtotal with a reason: {ein.ein_ubl_check(ubad)}")
check(any("BR-E-10" in f for f in ein.ein_ubl_check(um.replace(b"<cbc:TaxExemptionReason>Exempt education service</cbc:TaxExemptionReason>", b"", 1))),
      "review N3: ein_ubl_check names an E subtotal without a reason")

# ---------------------------------------------------------------- #3218 O with the tax number as seller identifier
CH = dict(RECIPIENT, country="CH", vat_id="CHE-123.456.789", lines=["Beispiel AG", "Bahnhofstrasse 3", "8001 Zürich"], street="Bahnhofstrasse 3",
          zip="8001", city="Zürich")
DE_SELLER = dict(SENDER, country="DE", city="Hamburg", zip="20457", street="Hafenstraße 12", vat_id="DE123456789", register_no="")
mo = model([line(1, "Regie", 1900.0, 0), line(2, "Schnitt", 2340.0, 0)], [], 4240.0, vat_note_key="abroad", recipient=CH, sender=DE_SELLER)
xo = ein.ein_build(mo, "zugferd")
check(set(line_cats(xo)) == {"O"}, f"#3218: abroad without register but with tax number: O (was G): {line_cats(xo)}")
check(seller_id(xo) == "12/345/67890", f"#3218: the tax number as seller identifier BT-29: {seller_id(xo)!r}")
check(b'schemeID="VA"' not in xo, "#3218: no VAT id of seller or buyer (BR-O-02)")
check(ein.ein_check(xo) == [], f"#3218: own check clean: {ein.ein_check(xo)}")
xox = ein.ein_build(dict(mo, recipient=dict(CH, buyer_reference="04011000-1-03")), "xrechnung")
check(ein.ein_check(xox) == [] and seller_id(xox) == "12/345/67890", f"#3218: XRechnung clean: {ein.ein_check(xox)}")
uo = ein.ein_ubl_build(mo, "peppol")
check(b"<cac:PartyIdentification>" in uo and b"12/345/67890" in uo and b"DE123456789" not in uo and ein.ein_ubl_check(uo) == [],
      f"#3218: UBL O with PartyIdentification (BT-29): {ein.ein_ubl_check(uo)}")
mr = copy.deepcopy(mo)
mr["sender_fields"]["register_no"] = "HRB 00000"
xr = ein.ein_build(mr, "zugferd")
check(set(line_cats(xr)) == {"O"} and seller_id(xr) is None, "#3218: with a register number: O as before, no extra BT-29")
mg = copy.deepcopy(mo)
mg["sender_fields"]["tax_number"] = ""
xg = ein.ein_build(mg, "zugferd")
check(set(line_cats(xg)) == {"G"} and seller_id(xg) is None and ein.ein_check(xg) == [], f"#3218: neither register nor tax number: G as before {line_cats(xg)}")

# the files for the validators in CI (tools/einvoice_validate.sh reads tests/.data/einvoice/*.xml)
OUT = os.path.join(N, ".data", "einvoice")
os.makedirs(OUT, exist_ok=True)
for name, x in (("invoice-zerorated-RE-2026-357.xml", xz), ("invoice-mixed-RE-2026-357.xml", xm), ("invoice-abroad-taxno-RE-2026-357.xml", xo),
                ("xrechnung-abroad-taxno-RE-2026-357.xml", xox)):
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(x)

print(f"p2357_l_einvoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
