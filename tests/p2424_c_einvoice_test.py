#!/usr/bin/env python3
# kalmido-suite: after=office_einvoice nodata
"""2.424.0 C (#3524): Kalmido's CII e-invoices against the ZUGFeRD 2.5.2 / Factur-X 1.09.2 points (CII D22B base, backwards
compatible to D16B; for EN 16931 only BR-CO-27 renamed to CII-SR-470), pure Python, no server.
 - five cases: invoice, credit note (381), progress invoice (326), final invoice (BMF letter, prepaid BT-113), reverse charge (AE)
 - each: the profile id (BT-24 EN 16931; the invoice also as XRechnung), no empty elements (deprecated since ZUGFeRD 2.4; the
   mandatory group BG-13 may stay empty), the service date machine readable (BG-14 start / end, format 102), ein_check clean
 - a client without postcode / street: no empty PostcodeCode / LineOne (they were written empty before 2.424.0)
 - the files go to tests/.data/einvoice/ for KoSIT in CI; with P2424_DUMP=1 they are printed base64 for a validator elsewhere
usage: p2424_c_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import base64
import importlib.util
import os
import re
import sys
import xml.etree.ElementTree as ET

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OUT = os.path.join(N, ".data", "einvoice")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


calc = load("calc")
ein = load("einvoice")
PACK = {"tax": {"standard": 19, "reduced": 7, "exempt": 0}}
NS = ein.NS


def it(title, qty, rate, tax="standard", kind="service"):
    return {"kind": kind, "title": title, "qty": qty, "rate": rate, "tax": tax, "unit": "flat", "intext": "intern"}


SENDER = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
          "register_no": "HRB 00000", "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE999999999", "buyer_reference": "04011000-12345-34", "email_invoice": "rechnung@beispielkunde.example"}
EU_CLIENT = {"name": "Voorbeeld B.V.", "street": "Kade 1", "zip": "1011 AA", "city": "Amsterdam", "country": "NL", "vat_id": "NL000099998B57",
             "email_invoice": "factuur@voorbeeld.example"}
POS = [it("Dreh", 2, 4000), it("Buch", 1, 2000, "reduced")]


def model(number, kind="invoice", items=POS, extra=None, recipient=None, **kw):
    t = calc.inv_calc({"lang": "de", "currency": "EUR", "vat_mode": kw.get("vat_mode") or "vat"}, items, PACK)
    m = {"kind": kind, "lang": "de", "currency": "EUR", "locked": True, "status": "issued", "number": number, "date": "2026-10-20",
         "service_from": "2026-10-01", "service_to": "2026-10-15", "due_date": "2026-11-03", "order_ref": "", "type_code": "380",
         "vat_mode": "vat", "vat_note_key": "", "vat_note_text": "", "project_title": "Imagefilm", "company": {"name": SENDER["name"]},
         "sender_fields": dict(SENDER), "recipient": dict(recipient or RECIPIENT), "lines": t["lines"], "totals": dict(t, paid="0.00"),
         "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 03.11.2026 ohne Abzug."}}
    m.update(extra or {}, **kw)
    return m


# the final invoice: the whole service 10000 + 2000 net, one progress invoice 3000 + 1000 net deducted (see p2408_a)
rest = calc.inv_calc({"lang": "de", "currency": "EUR"}, POS + [it("Abzüglich Abschlagsrechnung Nr. RE-2026-0101 vom 02.03.2026", 1, "3000.00", "standard", "discount"),
                                                             it("Abzüglich Abschlagsrechnung Nr. RE-2026-0101 vom 02.03.2026", 1, "1000.00", "reduced", "discount")], PACK)
full = calc.inv_calc({"lang": "de", "currency": "EUR"}, POS, PACK)
tls = {tl["rate_key"]: dict(tl) for tl in rest["tax_lines"]}
for k, a in (("standard", "3000.00"), ("reduced", "1000.00")):
    tls[k]["base"] = calc.dstr(calc.dec(tls[k]["base"]) + calc.dec(a))
    tls[k]["amount"] = calc.dstr(calc.dec(tls[k]["amount"]) + calc.money(calc.dec(a) * calc.dec(PACK["tax"][k]) / 100))
prepaid = calc.dec("3570.00") + calc.dec("1070.00")
FINAL = model("RE-2026-0115", inv_type="final", totals=dict(rest, paid="0.00"),
              abs_full={"net": full["net"], "gross": calc.dstr(calc.dec(rest["gross"]) + prepaid), "prepaid": calc.dstr(prepaid),
                        "tax_lines": [tls["standard"], tls["reduced"]], "note": "Abzüglich Abschlagsrechnung Nr. RE-2026-0101 vom 02.03.2026"},
              abs_prepaid=[{"gross": "3570.00"}, {"gross": "1070.00"}])
check(FINAL["abs_full"]["gross"] == full["gross"], f"fixture: the final invoice's whole service = the full gross {FINAL['abs_full']['gross']} {full['gross']}")

CASES = [("invoice", model("RE-2026-0110"), "380", ("zugferd", "xrechnung")),
         ("credit", model("GS-2026-0003", kind="credit", cancels={"id": 110, "number": "RE-2026-0110", "date": "2026-10-20"}), "381", ("zugferd",)),
         ("progress", model("RE-2026-0101", items=[it("Abschlag 1 Dreh", 1, "3000.00"), it("Abschlag 1 Buch", 1, "1000.00", "reduced")],
                            type_code="326", inv_type="progress"), "326", ("zugferd",)),
         ("final", FINAL, "380", ("zugferd", "xrechnung")),
         ("reverse", model("RE-2026-0111", recipient=EU_CLIENT, vat_mode="novat", vat_note_key="reverse"), "380", ("zugferd",))]

DLV = f"{{{NS['ram']}}}ApplicableHeaderTradeDelivery"


def empties(x):
    """the empty elements of an XML (no children, no text), the mandatory group BG-13 aside"""
    return [el.tag.rpartition("}")[2] for el in ET.fromstring(x).iter() if len(el) == 0 and not (el.text or "").strip() and el.tag != DLV]


os.makedirs(OUT, exist_ok=True)
for name, m, code, fmts in CASES:
    for fmt in fmts:
        xb = ein.ein_build(m, fmt)
        x = xb.decode("utf-8")
        root = ET.fromstring(xb)
        t = lambda p: (root.findtext(p, "", NS) or "").strip()  # noqa: E731
        check(t("rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == ein.EIN_PROFILE[fmt],
              f"{name}/{fmt}: profile id BT-24 {ein.EIN_PROFILE[fmt]}")
        check(t("rsm:ExchangedDocument/ram:TypeCode") == code, f"{name}/{fmt}: type code {code}")
        check(empties(xb) == [], f"{name}/{fmt}: no empty elements {empties(xb)}")
        bp = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/ram:BillingSpecifiedPeriod/"
        per = [root.find(bp + f"ram:{k}/udt:DateTimeString", NS) for k in ("StartDateTime", "EndDateTime")]
        check(all(p is not None and p.get("format") == "102" and re.fullmatch(r"\d{8}", p.text or "") for p in per)
              and [p.text for p in per] == ["20261001", "20261015"], f"{name}/{fmt}: the service period machine readable (BG-14, format 102)")
        check(t("rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString") == "20261020", f"{name}/{fmt}: the issue date BT-2")
        check(ein.ein_check(xb) == [], f"{name}/{fmt}: ein_check clean {ein.ein_check(xb)}")
        if name == "reverse":
            check("<ram:CategoryCode>AE</ram:CategoryCode>" in x and "VATEX-EU-AE" in x, "reverse: category AE with VATEX-EU-AE")
        if name == "credit":
            check(t("rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/ram:InvoiceReferencedDocument/ram:IssuerAssignedID") == "RE-2026-0110",
                  "credit: the cancelled invoice BT-25")
        if name == "final":
            check("<ram:TotalPrepaidAmount>4640.00</ram:TotalPrepaidAmount>" in x, "final: the progress invoices as BT-113")
        fn = f"invoice-p2424-{name}-{fmt}.xml"
        with open(os.path.join(OUT, fn), "wb") as fh:
            fh.write(xb)
        if os.environ.get("P2424_DUMP") or os.path.exists(os.path.join(N, ".p2424-dump")):
            print(f"p2424-xml {fn} {base64.b64encode(xb).decode()}")

# a client with only a city (no postcode, no street) and one without any address line: the empty parts are left out
for rc, want in (({"name": "Privatkunde Beispiel", "city": "Köln", "country": "DE"}, ["CityName", "CountryID"]),
                 ({"name": "Privatkunde Beispiel", "lines": ["Privatkunde Beispiel"]}, ["CountryID"])):
    xb = ein.ein_build(model("RE-2026-0112", recipient=rc))
    addr = ET.fromstring(xb).find("rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:PostalTradeAddress", NS)
    got = [el.tag.rpartition("}")[2] for el in addr]
    check(got == want and empties(xb) == [], f"a client without postcode / street: no empty address parts {got} {empties(xb)}")
# the module's check sees an empty element (a guard for the next builder change)
broken = ein.ein_build(CASES[0][1]).replace("<ram:LineOne>Marktstraße 5</ram:LineOne>".encode(), b"<ram:LineOne></ram:LineOne>")
check(b"<ram:LineOne></ram:LineOne>" in broken and "empty element LineOne" in ein.ein_check(broken), "ein_check reports an empty element")

print(f"p2424_c_einvoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
