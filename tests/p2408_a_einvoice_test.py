#!/usr/bin/env python3
# kalmido-suite: after=office_einvoice nodata
"""2.408.0 A (#3520): the e-invoice of a final invoice after the BMF letter of 15.10.2026 (no. 3), pure Python, no server.
 - the print model of a final invoice (abschlag.abs_prepaid_view) has the full positions in its lines, the remaining amount
   in its totals and the whole service in abs_full; the XML (CII and UBL) carries the full sums, the progress invoices' gross
   as BT-113 (paid amount, with a real payment on top), DuePayable = the remaining amount, the details in one note (BT-22)
 - the module's checks (ein_check, ein_ubl_check) find nothing; the files go to tests/.data/einvoice/ for KoSIT in CI
usage: p2408_a_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import os
import re
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
PACK = {"tax": {"standard": 19, "reduced": 7, "exempt": 0}}


def it(title, qty, rate, tax="standard", kind="service"):
    return {"kind": kind, "title": title, "qty": qty, "rate": rate, "tax": tax, "unit": "flat", "intext": "intern"}


SENDER = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
          "register_no": "HRB 00000", "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE999999999", "buyer_reference": "04011000-12345-34", "email_invoice": "rechnung@beispielkunde.example"}

# a quotation 2 x 4000 (19 %) + 2000 (7 %); progress 1 = 33.33 % per rate (2666.40 / 666.60), progress 2 = 1600.00 / 400.00
POS = [it("Dreh", 2, 4000), it("Buch", 1, 2000, "reduced")]
DED = [("RE-2026-0101", "02.03.2026", "2666.40", "standard"), ("RE-2026-0101", "02.03.2026", "666.60", "reduced"),
       ("RE-2026-0107", "06.04.2026", "1600.00", "standard"), ("RE-2026-0107", "06.04.2026", "400.00", "reduced")]
rest = calc.inv_calc({"lang": "de", "currency": "EUR"}, POS + [it(f"Abzüglich Abschlagsrechnung Nr. {n} vom {d}", 1, a, k, "discount") for n, d, a, k in DED], PACK)
full = calc.inv_calc({"lang": "de", "currency": "EUR"}, POS, PACK)
check(rest["net"] == "4667.00" and rest["gross"] == "5441.72", f"the remaining amount 4667.00 net, 5441.72 gross: {rest['net']} {rest['gross']}")
# what abs_prepaid_view adds: each deduction's VAT = net x rate, the rest's tax lines + the deductions
pre, tls = [], {tl["rate_key"]: dict(tl) for tl in rest["tax_lines"]}
for n, d, a, k in DED:
    net = calc.dec(a)
    vat = calc.money(net * calc.dec(PACK["tax"][k]) / 100)
    pre.append(net + vat)
    tls[k]["base"] = calc.dstr(calc.dec(tls[k]["base"]) + net)
    tls[k]["amount"] = calc.dstr(calc.dec(tls[k]["amount"]) + vat)
prepaid = sum(pre, calc.dec(0))
note = "Abzüglich bereits berechneter Abschläge\n" + "\n".join(f"Abzüglich Abschlagsrechnung Nr. {n} vom {d}: Netto {a} €, USt {PACK['tax'][k]} %" for n, d, a, k in DED)
abs_full = {"net": full["net"], "gross": calc.dstr(calc.dec(rest["gross"]) + prepaid), "prepaid": calc.dstr(prepaid), "tax_lines": [tls["standard"], tls["reduced"]], "note": note}
check(abs_full["gross"] == full["gross"] == "11660.00" and abs_full["prepaid"] == "6218.28", f"the whole service 11660.00, the progress invoices 6218.28: {abs_full}")
M = {"kind": "invoice", "lang": "de", "currency": "EUR", "locked": True, "status": "issued", "number": "RE-2026-0115", "date": "2026-10-20",
     "service_from": "2026-03-01", "service_to": "2026-10-20", "due_date": "2026-11-03", "payment_days": 14, "order_ref": "", "type_code": "380",
     "inv_type": "final", "vat_mode": "vat", "vat_note_key": "", "vat_note_text": "", "einvoice_format": "xrechnung", "project_title": "Imagefilm",
     "company": {"name": SENDER["name"]}, "sender_fields": dict(SENDER), "recipient": dict(RECIPIENT), "lines": full["lines"],
     "totals": dict(rest, paid="100.00", open=calc.dstr(calc.dec(rest["gross"]) - 100)), "abs_full": abs_full, "abs_prepaid": [{"gross": calc.dstr(g)} for g in pre],
     "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "text": "Zahlbar bis 03.11.2026 ohne Abzug."}}

os.makedirs(OUT, exist_ok=True)
for fmt in ("zugferd", "xrechnung"):
    x = ein.ein_build(M, fmt).decode("utf-8")
    check("<ram:LineTotalAmount>-" not in x and "<ram:LineTotalAmount>10000.00</ram:LineTotalAmount>" in x and "<ram:GrandTotalAmount>11660.00</ram:GrandTotalAmount>" in x
          and '<ram:TaxTotalAmount currencyID="EUR">1660.00</ram:TaxTotalAmount>' in x, f"{fmt}: the whole service, no negative lines")
    check("<ram:TotalPrepaidAmount>6318.28</ram:TotalPrepaidAmount>" in x and "<ram:DuePayableAmount>5341.72</ram:DuePayableAmount>" in x,
          f"{fmt}: BT-113 = progress invoices + the payment, due = the remaining amount less the payment " + str(re.findall(r"<ram:(?:TotalPrepaid|DuePayable)Amount>[^<]*", x)))
    notes = re.findall(r"<ram:IncludedNote>\s*<ram:Content>([^<]*)</ram:Content>", x)
    check(any("RE-2026-0101" in n and "RE-2026-0107" in n for n in notes), f"{fmt}: BT-22 lists the progress invoices {notes}")
    check(ein.ein_check(x.encode()) == [], f"{fmt}: ein_check clean {ein.ein_check(x.encode())}")
    with open(os.path.join(OUT, f"invoice-p2408-final-{fmt}.xml"), "wb") as fh:
        fh.write(x.encode())
u = ein.ein_ubl_build(M, "peppol").decode("utf-8")
check('<cbc:PrepaidAmount currencyID="EUR">6318.28</cbc:PrepaidAmount>' in u and '<cbc:PayableAmount currencyID="EUR">5341.72</cbc:PayableAmount>' in u
      and '<cbc:TaxInclusiveAmount currencyID="EUR">11660.00</cbc:TaxInclusiveAmount>' in u and "RE-2026-0107" in u, "UBL: the same sums and the note")
check(ein.ein_ubl_check(u.encode()) == [], f"UBL: ein_ubl_check clean {ein.ein_ubl_check(u.encode())}")
with open(os.path.join(OUT, "ubl-invoice-p2408-final.xml"), "wb") as fh:
    fh.write(u.encode())
# an ordinary invoice keeps the strict BR-CO-17 check (the tolerance is only for a paid amount)
bad = ein.ein_build({**M, "abs_full": None, "abs_prepaid": None, "totals": dict(full, paid="0.00", tax_lines=[dict(full["tax_lines"][0], amount="1520.02"), full["tax_lines"][1]])})
check(any("BR-CO-17" in f for f in ein.ein_check(bad)), "BR-CO-17 stays exact without a paid amount")

print(f"p2408_a_einvoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
