#!/usr/bin/env python3
# kalmido-suite: after=office_einvoice nodata
"""2.354.0 A (#2831, #2833, #2835): invoice math and the e-invoice, pure Python, no server, no container.
 - #2831 a position is money(qty x exact rate) (in another currency money(qty x rate x fx)): 3 x 0.333 = 1.00,
   1000 x 0.125 = 125.00, 1.5 x 33.335 = 50.00 (was the rate rounded to cents first: 0.99 / 130.00 / 50.01) in the invoice
   calculator and the quotation calculator; the unit price is shown with its places ("0,125 €"); in the XML the price
   keeps up to 4 places and the module's check (ein_check, BR-CO-10/13/15) finds nothing; the PDF prints "0,125 €"
 - #2833 a taxed invoice whose print model still carries a reverse charge note key is category S with its tax (was AE
   with tax 0 next to a gross with tax: BR-CO-15); the XML files go to tests/.data/einvoice/ for KoSIT in CI
 - #2835 the quotation calculator names its discount per tax key (by_tax), the base for the invoice from a quotation
usage: p2354_a_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import os
import sys

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
pdf = load("pdf")
PACK = {"tax": {"standard": 19, "reduced": 7, "exempt": 0}}


def it(title, qty, rate, tax="standard"):
    return {"kind": "service", "title": title, "qty": qty, "rate": rate, "tax": tax, "unit": "piece", "intext": "intern"}


# ---------------------------------------------------------------- #2831 the exact rate, rounded once per position
CASES = [(3, "0.333", "1.00"), (1000, "0.125", "125.00"), (1.5, "33.335", "50.00")]
for q, rate, want in CASES:
    t = calc.inv_calc({"lang": "de", "currency": "EUR"}, [it("A", q, rate)], PACK)
    o = calc.office_calc({"lang": "de", "currency": "EUR", "raw_mode": "none", "producing_on": 0}, [it("A", q, rate)], PACK)
    check(t["lines"][0]["net"] == want and t["net"] == want, f"#2831 invoice: {q} x {rate} = {want}, got {t['lines'][0]['net']}")
    check(f"{o['lines'][0]['total']:.2f}" == want and f"{o['net']:.2f}" == want, f"#2831 quotation: {q} x {rate} = {want}, got {o['lines'][0]['total']}")
t = calc.inv_calc({"lang": "de", "currency": "EUR"}, [it("A", 1000, "0.125")], PACK)
check(t["lines"][0]["rate"] == 0.125 and t["lines"][0]["rate_text"] == "0,125 €" and t["tax"] == "23.75" and t["gross"] == "148.75",
      f"#2831: rate shown with its places, tax on 125.00: {t['lines'][0]['rate_text']} {t['tax']} {t['gross']}")
check(calc.inv_calc({"lang": "de"}, [it("A", 2, "100.5")], PACK)["lines"][0]["rate_text"] == "100,50 €", "#2831: two places stay two places")
check(calc.fmt_rate("0.3333", "en", "EUR") == "€0.3333" and calc.rate_places("12.30") == 2 and calc.rate_places("0.12345") == 4, "#2831: fmt_rate / rate_places")
u = calc.inv_calc({"lang": "de", "currency": "USD", "fx_rate": "1.085"}, [it("A", 1000, "0.125")], PACK)
check(u["lines"][0]["net"] == "135.63" and u["lines"][0]["rate"] == 0.1356, f"#2831 USD: money(1000 x 0.125 x 1.085) = 135.63 (was 140.00): {u['lines'][0]['net']} {u['lines'][0]['rate']}")
check(pdf.pdf_rate_places(0.125) == 3 and pdf.pdf_rate_places(12.5) == 2 and pdf.pdf_money(0.125, "de", "EUR", {}, 3) == "0,125 €",
      f"#2831 PDF: unit price with its places {pdf.pdf_money(0.125, 'de', 'EUR', {}, 3)!r}")

# ---------------------------------------------------------------- #2835 the quotation's discount per tax key
d = calc.office_calc({"lang": "de", "currency": "EUR", "raw_mode": "none", "producing_on": 0, "discount_pct": 10},
                     [it("Regie", 1, 1000), it("Lizenz", 1, 1000, tax="reduced")], PACK)
dl = [x for x in d["lines"] if x["kind"] == "discount"][0]
check(dl["by_tax"] == {"standard": 100, "reduced": 100} and d["tax_total"] == 234 and d["gross"] == 2034,
      f"#2835: discount per key 100 / 100, tax 234, gross 2034: {dl.get('by_tax')} {d['tax_total']} {d['gross']}")
inv = calc.inv_calc({"lang": "de"}, [it("Regie", 1, 1000), it("Lizenz", 1, 1000, tax="reduced"),
                                     {"kind": "discount", "qty": 1, "rate": 100, "tax": "standard"}, {"kind": "discount", "qty": 1, "rate": 100, "tax": "reduced"}], PACK)
check(inv["tax"] == "234.00" and inv["gross"] == "2034.00", f"#2835: the invoice of these positions = the quotation: {inv['tax']} {inv['gross']}")

# ---------------------------------------------------------------- e-invoice models (invented names)
SENDER = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
          "register_no": "HRB 00000", "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE999999999", "buyer_reference": "", "email_invoice": "rechnung@beispielkunde.example"}


def model(t, number, vat_note_key=""):
    tot = dict(t, paid="0.00", open=t["gross"])
    return {"kind": "invoice", "lang": "de", "currency": "EUR", "locked": True, "status": "issued", "number": number, "date": "2026-10-20",
            "service_from": "2026-10-01", "service_to": "2026-10-20", "due_date": "2026-11-03", "payment_days": 14, "order_ref": "",
            "vat_mode": t["vat_mode"], "vat_note_key": vat_note_key, "vat_note_text": "", "einvoice_format": "zugferd",
            "company": {"name": SENDER["name"]}, "sender_fields": dict(SENDER), "recipient": dict(RECIPIENT), "lines": t["lines"], "totals": tot,
            "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 03.11.2026 ohne Abzug."}}


os.makedirs(OUT, exist_ok=True)
# c01 / c05 of the audit: the three rounding cases in one invoice
t = calc.inv_calc({"lang": "de", "currency": "EUR"}, [it("Kleinteil", 3, "0.333"), it("Stückpreis", 1000, "0.125"), it("Stunde", 1.5, "33.335")], PACK)
check(t["net"] == "176.00" and t["tax"] == "33.44" and t["gross"] == "209.44", f"#2831: 1.00 + 125.00 + 50.00 = 176.00, tax 33.44: {t['net']} {t['tax']} {t['gross']}")
x = ein.ein_build(model(t, "RE-2026-2831"))
check(b"<ram:ChargeAmount>0.125</ram:ChargeAmount>" not in x and b"<ram:ChargeAmount>0.1250</ram:ChargeAmount>" in x and b"<ram:LineTotalAmount>125.00</ram:LineTotalAmount>" in x
      and b"<ram:ChargeAmount>33.3350</ram:ChargeAmount>" in x and b"<ram:GrandTotalAmount>209.44</ram:GrandTotalAmount>" in x,
      "#2831 XML: price with 4 places, line 125.00, total 209.44")
check(ein.ein_check(x) == [], f"#2831 XML: ein_check clean {ein.ein_check(x)}")
with open(os.path.join(OUT, "invoice-p2354-rounding.xml"), "wb") as fh:
    fh.write(x)
# c10 of the audit: a taxed invoice with a stale reverse charge key (4 h x 95 EUR)
t = calc.inv_calc({"lang": "de", "currency": "EUR", "vat_mode": "vat"}, [it("Beratung", 4, 95)], PACK)
x = ein.ein_build(model(t, "RE-2026-2833", vat_note_key="reverse"))
check(b"<ram:CategoryCode>S</ram:CategoryCode>" in x and b"<ram:CategoryCode>AE</ram:CategoryCode>" not in x and b"<ram:TaxTotalAmount currencyID=\"EUR\">72.20</ram:TaxTotalAmount>" in x
      and b"<ram:GrandTotalAmount>452.20</ram:GrandTotalAmount>" in x, "#2833 XML: category S with 72.20 tax (was AE, tax 0, total 452.20)")
check(ein.ein_check(x) == [], f"#2833 XML: ein_check clean (BR-CO-15) {ein.ein_check(x)}")
with open(os.path.join(OUT, "invoice-p2354-vat-rcnote.xml"), "wb") as fh:
    fh.write(x)

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
