#!/usr/bin/env python3
"""2.296.0 B (#3168, #3169, #3173, #3175): invoices and e-invoices of the office (kalmido/office/calc.py, pdf.py, einvoice.py of
the source tree), no server, no container. Invented companies and figures only. The parts with the database (print model,
finalise checks, GiroCode, settings) are in p2296_b_api_test.py.
 - #3175 one money format per document language: fr "1 234,50 €" (no-break space), nl "€ 1.234,50", de / en as before;
   pdf_money writes the same (en "$1,234.50", was "1,234.50 USD"); the pack's own format only for German documents
 - #3169 a taxed invoice with a 0 % position: the line is category E (was S at 0 % -> BR-S-05), one tax breakdown per
   category and rate (S 19 % + E 0 %), the invoice's exemption reason (BT-120) or a standard text; the same in UBL; the
   own check (ein_check) now names BR-S-05; the PDF prints the reason (totals.exempt_note) beside the sums
 - #3173 vat_note "abroad" = O (not subject to VAT) without VAT ids and line rate (BR-O-02 / BR-O-05), the breakdown rate
   0 stays (XRechnung BR-DE-14); without a register number of the seller it stays G (BR-CO-26); a credit note carries the
   date of the corrected invoice (BT-26) in CII and UBL; a surcharge line printed with its translated unit, never "flat"
 - #3168 ein_check names a reverse charge invoice without the buyer's VAT id (BR-AE-02)
 (the exempt and the abroad invoice for the validators in CI: office_einvoice_test.py writes them)
usage: p2296_b_invoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import copy
import importlib.util
import os
import sys
from xml.etree import ElementTree as ET

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)


def load(name):
    spec = importlib.util.spec_from_file_location("p2296b_" + name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


calc = load("calc")
pdf = load("pdf")
ein = load("einvoice")
from kt import FAILS, OKS, check  # noqa: E402

NB = " "

# ---------------------------------------------------------------- #3175 money formats by language
check(calc.fmt_money(1234.5, "de") == "1.234,50 €" and calc.fmt_money(1234.5, "en") == "€1,234.50", "de / en as before")
check(calc.fmt_money(1234.5, "fr") == f"1{NB}234,50 €" and calc.fmt_money(-1234567.891, "fr") == f"-1{NB}234{NB}567,89 €",
      f"fr groups with a no-break space: {calc.fmt_money(1234.5, 'fr')!r}")
check(calc.fmt_money(1234.5, "nl") == "€ 1.234,50" and calc.fmt_money(1234.5, "it") == "1.234,50 €" and calc.fmt_money(1234.5, "es") == "1.234,50 €",
      f"nl sign first, it / es like de: {calc.fmt_money(1234.5, 'nl')!r}")
check(calc.fmt_money(1234.5, "en", "USD") == "$1,234.50" and calc.fmt_money(1234.5, "en", "CHF") == "CHF 1,234.50"
      and calc.fmt_money(1234.5, "fr", "USD") == f"1{NB}234,50 $", "other currencies keep their sign / code")
for lg in ("de", "en", "fr", "nl", "it", "es"):
    check(pdf.pdf_money(1234.5, lg, "EUR") == calc.fmt_money(1234.5, lg, "EUR"), f"pdf_money = calc.fmt_money ({lg})")
check(pdf.pdf_money(1234.5, "en", "USD") == "$1,234.50", f"pdf_money USD like the model's texts: {pdf.pdf_money(1234.5, 'en', 'USD')!r}")
check(pdf.pdf_money(1234.5, "de", "EUR", {"decimal": ".", "thousands": ","}) == "1,234.50 €"
      and pdf.pdf_money(1234.5, "en", "EUR", {"decimal": ",", "thousands": "."}) == "€1,234.50", "the pack's format only for German documents")
check(pdf.pdf_encode(f"1{NB}234,50 €") in (b"1\xa0234,50 \x80", b"1 234,50 \x80") and f"1{NB}234,50" in pdf.pdf_wrap(f"Summe 1{NB}234,50 €", 9, 40),
      "the no-break space prints as a space and never breaks the amount")

# #3173: a markup line of a quotation carries its translated unit and word (was unit_text "" -> "1 flat", "Markup" in German)
q = calc.office_calc({"lang": "de", "markup_pct": 10}, [{"kind": "service", "title": "Schnitt", "qty": 2, "unit": "day", "rate": 500, "in_markup": 1}],
                     {"tax": {"standard": 19}})
sur = [x for x in q["lines"] if x["kind"] == "surcharge"]
check(sur and sur[0]["unit_text"] == "pauschal" and sur[0]["title"] == "Aufschlag", f"markup line: unit 'pauschal', title 'Aufschlag': {sur}")
q_en = calc.office_calc({"lang": "en", "markup_pct": 10}, [{"kind": "service", "title": "Edit", "qty": 2, "unit": "day", "rate": 500, "in_markup": 1}], {})
check([x["unit_text"] for x in q_en["lines"] if x["kind"] == "surcharge"] == ["flat"], "markup line in English: unit 'flat' (the English word)")

# ---------------------------------------------------------------- e-invoice fixture (invented)
SENDER = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@studio.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
          "register_no": "HRB 00000", "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE987654321", "customer_no": "K-0042", "buyer_reference": "04011000-12345-03",
             "email_invoice": "rechnung@beispielkunde.example"}


def line(pos, title, net, pct, tax="standard"):
    return {"kind": "item", "pos": pos, "title": title, "qty": 1, "qty_text": "1", "unit": "flat", "unit_text": "pauschal", "rate": net,
            "rate_text": calc.fmt_money(net), "tax": tax, "tax_pct": pct, "total": net, "total_text": calc.fmt_money(net), "net": f"{net:.2f}"}


def model(lines, tax_lines, gross, kind="invoice", vat_note_key="", exempt_reason="", recipient=None):
    net = sum(x["total"] for x in lines)
    tax = sum(float(t["amount"]) for t in tax_lines)
    return {"kind": kind, "lang": "de", "currency": "EUR", "locked": True, "status": "issued", "number": "RE-2026-296" if kind == "invoice" else "GS-2026-296",
            "date": "2026-10-24", "date_text": "24.10.2026", "title": "Rechnung", "project_title": "Imagefilm", "order_ref": "PO-296",
            "service_from": "2026-10-01", "service_to": "2026-10-20", "due_date": "" if kind == "credit" else "2026-11-07",
            "vat_mode": "novat" if vat_note_key else "vat", "vat_note_key": vat_note_key, "vat_note_text": "", "exempt_reason": exempt_reason,
            "sender_fields": dict(SENDER), "recipient": dict(recipient or RECIPIENT), "company": {"name": SENDER["name"]},
            "lines": lines, "totals": {"net": f"{net:.2f}", "tax_lines": tax_lines, "tax": f"{tax:.2f}", "gross": f"{gross:.2f}", "paid": "0.00"},
            "cancels": {"id": 1, "number": "RE-2026-200", "date": "2026-09-30", "date_text": "30.09.2026"} if kind == "credit" else None,
            "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 07.11.2026 ohne Abzug."}}


def root(x):
    return ET.fromstring(x)


S = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"


def breakdown(x):
    out = []
    for t in root(x).findall(S + "ram:ApplicableTradeTax", ein.NS):
        g = lambda p: (t.find(p, ein.NS).text if t.find(p, ein.NS) is not None else None)  # noqa: E731
        out.append((g("ram:CategoryCode"), g("ram:RateApplicablePercent"), g("ram:BasisAmount"), g("ram:CalculatedAmount"),
                    g("ram:ExemptionReason"), g("ram:ExemptionReasonCode")))
    return out


def line_cats(x):
    r = root(x)
    return [(li.find("ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode", ein.NS).text,
             li.find("ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent", ein.NS) is not None)
            for li in r.findall("rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem", ein.NS)]


def vat_ids(x):
    return [i.text for i in root(x).iter("{%s}ID" % ein.NS["ram"]) if i.get("schemeID") == "VA"]


# ---------------------------------------------------------------- #3169 exempt positions of a taxed invoice
EX_LINES = [line(1, "Regie", 1900.0, 19), line(2, "Schnitt", 2340.0, 19), line(3, "Kursgebühr Schulung", 380.0, 0, "exempt")]
EX_TAX = [{"rate_key": "standard", "pct": "19", "base": "4240.00", "amount": "805.60"}, {"rate_key": "exempt", "pct": "0", "base": "380.00", "amount": "0.00"}]
mx = model(EX_LINES, EX_TAX, 5425.60, exempt_reason="Steuerfreie Leistung nach § 4 Nr. 21 UStG")
xx = ein.ein_build(mx, "zugferd")
check(line_cats(xx) == [("S", True), ("S", True), ("E", True)], f"the 0 % line is category E: {line_cats(xx)}")
bd = breakdown(xx)
check(("E", "0", "380.00", "0.00", "Steuerfreie Leistung nach § 4 Nr. 21 UStG", None) in bd and ("S", "19", "4240.00", "805.60", None, None) in bd and len(bd) == 2,
      f"one breakdown per category and rate, E with the invoice's reason: {bd}")
check(ein.ein_check(xx) == [], f"own check clean: {ein.ein_check(xx)}")
mx2 = copy.deepcopy(mx)
mx2["exempt_reason"] = ""
bd2 = breakdown(ein.ein_build(mx2, "zugferd"))
check(any(b[0] == "E" and b[4] == "Steuerfrei." for b in bd2), f"without a reason a standard text (BR-E-10): {bd2}")
xr = ein.ein_build(dict(mx, recipient=dict(RECIPIENT)), "xrechnung")
check(ein.ein_check(xr) == [] and ("E", True) in line_cats(xr), f"XRechnung: E line, own check clean {ein.ein_check(xr)}")
u = ein.ein_ubl_build(mx, "xrechnung")
ur = root(u)
UQ = {"cac": ein.UBL_NS["cac"], "cbc": ein.UBL_NS["cbc"]}
subs = [(s.find("cac:TaxCategory/cbc:ID", UQ).text, s.find("cac:TaxCategory/cbc:Percent", UQ).text,
         (s.find("cac:TaxCategory/cbc:TaxExemptionReason", UQ).text if s.find("cac:TaxCategory/cbc:TaxExemptionReason", UQ) is not None else None))
        for s in ur.findall("cac:TaxTotal/cac:TaxSubtotal", UQ)]
check(("E", "0", "Steuerfreie Leistung nach § 4 Nr. 21 UStG") in subs and ("S", "19", None) in subs, f"UBL: subtotals S 19 / E 0 with reason: {subs}")
check([c.text for c in ur.findall("cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:ID", UQ)] == ["S", "S", "E"], "UBL: line categories S S E")
check(ein.ein_ubl_check(u) == [], f"UBL own check clean: {ein.ein_ubl_check(u)}")
# regression: the old builder wrote S at 0 % -- the own check names it now
old = xx.replace(b"<ram:CategoryCode>E</ram:CategoryCode>", b"<ram:CategoryCode>S</ram:CategoryCode>")
check(any("BR-S-05" in f for f in ein.ein_check(old)), f"ein_check names BR-S-05 for S at 0 %: {ein.ein_check(old)}")

# ---------------------------------------------------------------- #3173 not taxable (O / G), BT-26
NV_LINES = [line(1, "Regie", 1900.0, 0), line(2, "Schnitt", 2340.0, 0)]
CH = dict(RECIPIENT, country="CH", vat_id="CHE-123.456.789", lines=["Beispiel AG", "Bahnhofstrasse 3", "8001 Zürich"], street="Bahnhofstrasse 3",
          zip="8001", city="Zürich")
mo = model(NV_LINES, [], 4240.0, vat_note_key="abroad", recipient=CH)
xo = ein.ein_build(mo, "zugferd")
bo = breakdown(xo)
check(line_cats(xo) == [("O", False), ("O", False)], f"abroad: lines O without a rate (BR-O-05): {line_cats(xo)}")
check(bo == [("O", "0", "4240.00", "0.00", bo[0][4], "VATEX-EU-O")] and bo[0][4], f"abroad: one breakdown O, rate 0 (BR-DE-14), VATEX-EU-O: {bo}")
check(vat_ids(xo) == [], f"abroad: no VAT id of seller or buyer (BR-O-02): {vat_ids(xo)}")
check(ein.ein_check(xo) == [] and ein.ein_check(ein.ein_build(dict(mo, recipient=dict(CH, buyer_reference="04011000-1-03")), "xrechnung")) == [],
      f"abroad: own check clean (CII, XRechnung): {ein.ein_check(xo)}")
uo = ein.ein_ubl_build(mo, "peppol")
check(b"<cbc:ID>O</cbc:ID>" in uo and b"DE123456789" not in uo and ein.ein_ubl_check(uo) == [], "abroad UBL: O, no seller VAT id")
mg = copy.deepcopy(mo)
mg["sender_fields"]["register_no"] = ""
xg = ein.ein_build(mg, "zugferd")
check({c for c, _ in line_cats(xg)} == {"G"} and "DE123456789" in vat_ids(xg) and ein.ein_check(xg) == [],
      f"abroad without a register number: G as before (BR-CO-26), seller VAT id kept: {line_cats(xg)} {vat_ids(xg)}")
check(any("BR-O-02" in f for f in ein.ein_check(xg.replace(b">G<", b">O<"))), "ein_check names BR-O-02 (O with a VAT id)")
mc = model([line(1, "Regie", 500.0, 19)], [{"rate_key": "standard", "pct": "19", "base": "500.00", "amount": "95.00"}], 595.0, kind="credit")
xc = ein.ein_build(mc, "zugferd")
check(b'<qdt:DateTimeString format="102">20260930</qdt:DateTimeString>' in xc and ein.ein_check(xc) == [], "credit note: BT-26 date of the corrected invoice (CII)")
check(b"<cbc:IssueDate>2026-09-30</cbc:IssueDate>" in ein.ein_ubl_build(mc, "peppol"), "credit note: BT-26 in UBL")

# ---------------------------------------------------------------- #3168 reverse charge needs both VAT ids
mr = model(NV_LINES, [], 4240.0, vat_note_key="reverse", recipient=dict(RECIPIENT, country="NL", vat_id="NL123456789B01"))
xr2 = ein.ein_build(mr, "zugferd")
check({c for c, _ in line_cats(xr2)} == {"AE"} and ein.ein_check(xr2) == [], f"reverse charge with both VAT ids: AE, clean {ein.ein_check(xr2)}")
xr3 = ein.ein_build(dict(mr, recipient=dict(mr["recipient"], vat_id="")), "zugferd")
check(any("BR-AE-02" in f and "buyer" in f for f in ein.ein_check(xr3)), f"ein_check names the missing buyer VAT id: {ein.ein_check(xr3)}")

# 2.296.0 F (#3168): domestic reverse charge -- the seller's tax number (BT-32, FC) satisfies BR-AE-02 (was: VAT id only)
mf = copy.deepcopy(mr)
mf["sender_fields"]["vat_id"] = ""
xf = ein.ein_build(mf, "zugferd")
check(b'schemeID="FC"' in xf and not any("seller" in f for f in ein.ein_check(xf)), f"F #3168: seller with tax number only: no BR-AE-02 seller finding {ein.ein_check(xf)}")
mf["sender_fields"]["tax_number"] = ""
check(any("BR-AE-02" in f and "seller" in f for f in ein.ein_check(ein.ein_build(mf, "zugferd"))), "F #3168: neither VAT id nor tax number: BR-AE-02 seller")
# (countries.fk_reverse_case: domestic / EU / CH through the print model in p2296_b_api_test.py)

# ---------------------------------------------------------------- PDF: exempt note, surcharge unit (#3169, #3173)
TEXTS = []
_Base = pdf._Page


class RecPage(_Base):
    def text(self, x, y, s, size, bold=False, color=pdf.C_INK, align="l", spacing=0.0, width=None):
        if str(s or ""):
            TEXTS.append(str(s))
        return super().text(x, y, s, size, bold, color, align, spacing, width)


pdf._Page = RecPage
pm = dict(mx, company={"name": "Studio Nordlicht GmbH", "lines": ["Hafenstraße 12", "20457 Hamburg"], "color": "#2f5d8a"},
          recipient={"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"]},
          meta=[["Rechnung Nr.", "RE-2026-296"], ["Datum", "24.10.2026"]], intro="Sehr geehrte Damen und Herren,", closing="", signature="",
          labels={"units": {"flat": "pauschal", "day": "Tage"}})
pm["lines"] = [dict(x, unit="day", unit_text="Tag") for x in EX_LINES] + [{"kind": "surcharge", "slot": "markup", "pos": 4, "title": "Aufschlag", "qty": 1, "qty_text": "1", "unit": "flat", "unit_text": "",
                           "rate": 100, "rate_text": "100,00 €", "tax_pct": 19, "total": 100, "total_text": "100,00 €"}]
pm["totals"] = {"rows": [["Zwischensumme", "4.720,00 €"], ["MwSt. 19 % auf 4.340,00 €", "824,60 €"], ["steuerfrei auf 380,00 €", "0,00 €"],
                         ["Rechnungsbetrag", "5.544,60 €"]], "show_tax_lines": True, "exempt_note": "Steuerfreie Leistung nach § 4 Nr. 21 UStG"}
data = pdf.office_pdf(pm)
check(data[:4] == b"%PDF" and any("Steuerfreie Leistung nach § 4 Nr. 21 UStG" in t for t in TEXTS), "PDF: the exemption reason beside the sums")
check("1 pauschal" in TEXTS and "1 flat" not in TEXTS, f"PDF: the surcharge line with its translated unit (was '1 flat'): {[t for t in TEXTS if t.startswith('1 ')]}")
check(any(t == "MwSt. 19 % auf 4.340,00 €" for t in TEXTS), "PDF: the tax row with its taxable amount as the model gives it")
pdf._Page = _Base

print(f"p2296_b_invoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
