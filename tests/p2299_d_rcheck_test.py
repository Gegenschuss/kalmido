#!/usr/bin/env python3
"""2.299.0 D (#3193): the fixed check of a receipt (kalmido/docs/rcheck.py rck_check) -- pure Python, no app, no server.
Invented companies, addresses and figures only (example.com); the receipts are texts made here.
 - a complete invoice above 250 EUR: no hint; a small amount receipt (section 33 UStDV): no tax id / number / recipient asked
 - the arithmetic: net + VAT != gross (also when ex_details drops the figures), rate * net != VAT (one cent is fine), the nets
   per rate != the net total
 - rates: 20 % = a foreign rate?, 0 % without its reason, reverse charge (section 13b) named
 - required details: "Missing" only when the text has not even the label, else "Please check ... not found" (hint)
 - the VAT id per country (DE with its check digit), the German tax number, an entertainment receipt, an e-invoice (fields only)
usage: p2299_d_rcheck_test.py   (KALMIDO_SRC=<dir with kalmido/>)"""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("p2299d_rcheck", os.path.join(SRC, "kalmido", "docs", "rcheck.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
EX = R.EX
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402  shared helpers (tests/kt.py)


def codes(fields, text=None):
    return [x["code"] for x in R.rck_check(fields, text)]


def run(text, **extra):
    return codes({**EX.ex_details(text), **extra}, text)


def de_vatid(base8):
    """A fictitious German VAT id with a fitting check digit (DE + 8 digits + check digit)."""
    for d in "0123456789":
        if R.rck_de_vatid_ok(base8 + d):
            return "DE" + base8 + d
    raise AssertionError(base8)


VID = de_vatid("27364519")
FULL = f"""Muster Werkstatt GmbH
Industrieweg 12
12345 Beispielstadt
USt-IdNr.: {VID}

Rechnung an:
Beispiel Agentur
Hauptstraße 7
54321 Musterdorf

Rechnungsnummer: RE-2026-501
Rechnungsdatum: 12.10.2026
Leistungsdatum: 10.10.2026

Pos  Menge  Leistung                 Preis
1    4 h    Wartung Druckmaschine    320,00 EUR
2    1 Stk  Ersatzteil Walze          80,00 EUR

Nettobetrag                          400,00 EUR
zzgl. 19 % MwSt                       76,00 EUR
Gesamtbetrag                         476,00 EUR
"""

# ---- a complete invoice above 250 EUR: nothing to say
check(run(FULL) == [], f"complete invoice: no hint {run(FULL)}")
check(R.rck_check(None) == [] or isinstance(R.rck_check(None), list), "no fields: a list, no error")

# ---- the arithmetic
bad = FULL.replace("Gesamtbetrag                         476,00", "Gesamtbetrag                         496,00")
check(EX.ex_details(bad)["net"] is None, "setup: ex_details drops the figures that do not add up")
r = R.rck_check(EX.ex_details(bad), bad)
x = next((i for i in r if i["code"] == "calc_sum"), None)
check(x and x["level"] == "warn" and x["args"] == ["400.00", "76.00", "476.00", "496.00"], f"net + VAT != gross from the text {r}")
check(x and x["text"] == "Please check: net 400.00 + VAT 76.00 gives 476.00, the receipt says 496.00", f"the sentence {x}")
check(r and r[0]["level"] == "warn", "warnings first")
f = {"supplier": "X", "vat_rates": [{"pct": "19", "net": "100.00", "vat": "20.00"}], "net": "100.00", "vat": "20.00", "gross": "120.00"}
check("calc_rate" in codes(f), f"19 % of 100.00 is not 20.00 {codes(f)}")
check("calc_sum" not in codes(f), "120.00 = 100.00 + 20.00")
f = {"supplier": "X", "vat_rates": [{"pct": "19", "net": "100.00", "vat": "19.01"}], "net": "100.00", "vat": "19.01", "gross": "119.01"}
check("calc_rate" not in codes(f), "one cent of rounding is fine")
f = {"supplier": "X", "vat_rates": [{"pct": "19", "net": "300.00", "vat": "57.00"}, {"pct": "7", "net": "20.00", "vat": "1.40"}],
     "net": "330.00", "vat": "58.40", "gross": "388.40"}
check("calc_nets" in codes(f), f"nets per rate 320.00 != 330.00 {codes(f)}")
f = {"supplier": "X", "net": "abc", "vat": None, "gross": "12,5x", "vat_rates": [{"pct": "x"}, "y"]}
check(isinstance(R.rck_check(f), list), "unreadable figures: no error")

# ---- rates
hotel = FULL.replace("zzgl. 19 % MwSt                       76,00", "zzgl. 20 % VAT                        80,00").replace("476,00", "480,00")
check("rate_foreign" in run(hotel), f"20 % = a foreign rate? {run(hotel)}")
zero = FULL.replace("zzgl. 19 % MwSt                       76,00 EUR\n", "").replace("476,00", "400,00")
check("zero_note" in codes({**EX.ex_details(zero), "vat_pct": "0"}, zero), "0 % (set by a person) without a reason on the receipt")
check("rate" in run(zero), f"no rate, no VAT word, no exemption: Missing {run(zero)}")
rc = zero.replace("Nettobetrag", "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)\nNettobetrag")
check("reverse" in run(rc) and "zero_note" not in run(rc) and "rate" not in run(rc), f"reverse charge named, no other rate hint {run(rc)}")
k19 = zero.replace("Nettobetrag", "Kein Ausweis der Umsatzsteuer, Kleinunternehmer gemäß § 19 UStG\nNettobetrag")
check(not {"rate", "zero_note", "rate_read"} & set(run(k19)), f"small business note: fine {run(k19)}")

# ---- required details: "Missing" only without the label, else "Please check"
noid = FULL.replace(f"USt-IdNr.: {VID}\n", "")
r = R.rck_check(EX.ex_details(noid), noid)
x = next((i for i in r if i["code"].startswith("taxid")), None)
check(x and x["code"] == "taxid" and x["level"] == "warn" and x["text"].startswith("Missing:"), f"no tax id, no label: Missing {x}")
blur = FULL.replace(f"USt-IdNr.: {VID}", "USt-IdNr.: D? 27?6 4??")
x = next((i for i in R.rck_check(EX.ex_details(blur), blur) if i["code"].startswith("taxid")), None)
check(x and x["code"] == "taxid_read" and x["level"] == "hint" and x["text"].startswith("Please check:"), f"label but unreadable: Please check {x}")
nonum = FULL.replace("Rechnungsnummer: RE-2026-501\n", "")
check("number" in run(nonum), f"no invoice number: Missing {run(nonum)}")
blurno = FULL.replace("Rechnungsnummer: RE-2026-501", "Rechnungsnummer: ---")
check("number_read" in run(blurno) and "number" not in run(blurno), f"label without a value: Please check {run(blurno)}")
nodate = FULL.replace("Rechnungsdatum: 12.10.2026\n", "").replace("Leistungsdatum: 10.10.2026\n", "")
check("date" in run(nodate), f"no date at all: Missing {run(nodate)}")
check("date" not in codes({**EX.ex_details(nodate), "date": "2026-10-12"}, nodate), "a date typed in by a person: fine")
noaddr = FULL.replace("Industrieweg 12\n12345 Beispielstadt\n", "").replace("Hauptstraße 7\n54321 Musterdorf\n", "")
check("address" in run(noaddr), f"no address: Please check {run(noaddr)}")
norcp = FULL.replace("Rechnung an:\nBeispiel Agentur\nHauptstraße 7\n54321 Musterdorf\n", "")
check("recipient" in run(norcp), f"above 250 EUR without a recipient: Please check {run(norcp)}")
nosrv = """Muster Werkstatt GmbH
Industrieweg 12, 12345 Beispielstadt
Rechnungsnummer: RE-1
Datum 12.10.2026
Nettobetrag 100,00 EUR
zzgl. 19 % MwSt 19,00 EUR
Gesamtbetrag 119,00 EUR
"""
check("service" in run(nosrv), f"no service line: Please check {run(nosrv)}")
check(all(x["level"] == "hint" for x in R.rck_check(EX.ex_details(nosrv), nosrv) if x["code"] in ("service", "address", "supplier")),
      "what the text may only not show is a hint, never a warning")

# ---- a small amount receipt (section 33 UStDV): name, address, date, service, gross, rate -- no tax id / number / recipient
BAKERY = """Bäckerei Musterkorn
Marktplatz 3
12345 Beispielstadt
13.10.2026 08:12
2 x Brötchen        1,20
1 x Kaffee          2,50
Summe EUR           3,70
enthaltene MwSt 7 %  0,24
"""
check(run(BAKERY) == [], f"small receipt: nothing to say {run(BAKERY)}")
nr = BAKERY.replace("enthaltene MwSt 7 %  0,24\n", "")
check("rate_small" in run(nr) and not {"taxid", "number", "recipient"} & set(run(nr)), f"small receipt without rate: only the rate {run(nr)}")

# ---- VAT id per country, tax number
check(R.rck_de_vatid_ok("136695976") and not R.rck_de_vatid_ok("136695977"), "DE check digit (MOD 11,10)")
check(R.rck_vatid("DE123456789") == ("vatid_digit", ["DE123456789"]), f"DE: a wrong check digit {R.rck_vatid('DE123456789')}")
check(R.rck_vatid(VID) is None and R.rck_vatid("DE 136 695 976") is None, "DE: fitting ids (spaces ignored)")
check(R.rck_vatid("DE12345678") == ("vatid_fmt", ["DE12345678", "DE"]), "DE: 8 digits")
check(R.rck_vatid("ATU1234567")[0] == "vatid_fmt" and R.rck_vatid("ATU12345678") is None, "AT: U + 8 digits")
check(R.rck_vatid("NL123456789B01") is None and R.rck_vatid("NL123456789")[0] == "vatid_fmt", "NL: B01")
check(R.rck_vatid("FR12345678901") is None and R.rck_vatid("FRIO345678901")[0] == "vatid_fmt", "FR: two keys + 9 digits")
check(R.rck_vatid("XX12345") is None, "an unknown prefix: no claim")
check("vatid_fmt" in codes({"supplier": "X", "vat_id": "ATU1234567", "gross": "10.00"}), "the format hint in the result")
check(R.rck_taxno_ok("12/345/67890") and R.rck_taxno_ok("123/4567/89012") and R.rck_taxno_ok("1234567890123"), "tax numbers that fit")
check(not R.rck_taxno_ok("1234") and "taxno_fmt" in codes({"supplier": "X", "tax_no": "12-34", "gross": "10.00"}), "a tax number that does not fit")

# ---- an entertainment receipt; an e-invoice (fields only, no text checks)
MEAL = BAKERY.replace("Bäckerei Musterkorn", "Restaurant Beispielhof")
check("meal" in run(MEAL, meal=True) and "meal" not in run(MEAL), f"entertainment: occasion + participants {run(MEAL, meal=True)}")
ok_meal = MEAL + "Anlass: Projektbesprechung\nTeilnehmer: A. Beispiel, B. Muster\n"
check("meal" not in run(ok_meal, meal=True), "occasion and participants on the receipt: fine")
einv = {"supplier": "Muster Werkstatt GmbH", "vat_id": VID, "invoice_no": "RE-9", "vat_pct": "19", "net": "100.00", "vat": "19.00",
        "gross": "119.00", "einvoice": True, "date": "2026-10-12"}
check(codes(einv, "anything") == [], f"an e-invoice: its fields fit, the text is not read {codes(einv, 'anything')}")
check("calc_sum" in codes({**einv, "gross": "130.00"}), "an e-invoice whose figures do not add up")

# ---- every message is in the table, every level hint | warn
check(all(lv in ("hint", "warn") for lv, _m in R.RCK_MSG.values()), "levels")
check(all(m.startswith(("Missing:", "Please check:", "Reverse charge", "Entertainment:")) for _l, m in R.RCK_MSG.values()), "sentences: Missing / Please check")
check(all(m.startswith("Missing:") == (lv == "warn" and not m.startswith("Please")) for lv, m in R.RCK_MSG.values() if m.startswith("Missing:")),
      "Missing only as a warning")

print(f"p2299_d_rcheck: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
