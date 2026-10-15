#!/usr/bin/env python3
"""2.48.0 part B (#1111): the recognition building blocks of the documents, pure Python, no server.
 - extract.py: document date, due date and amount from German / English text; traps: phone numbers, IBAN, postal
   codes, birthdays before 1990, dates far in the future, net / VAT lines are no total
 - rules.py: every kind of match (any / all / exact / regex / fuzzy), the first rule wins a single-value feature, tags
   add up; an evil regex is refused when saved and cannot hang the server when run
 - classify.py: learns from examples, needs enough examples and confidence, takes a corrected document out again, and two
   workspaces never share a model (each model only knows its own documents)
usage: python3 tests/p248_b_unit_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys
import time
from datetime import date

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
FAILS, OKS = [], [0]


def load(name):
    spec = importlib.util.spec_from_file_location("p248b_" + name, os.path.join(SRC, "kalmido", "docs", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL", what)


X = load("extract")
R = load("rules")
C = load("classify")
TODAY = date(2026, 10, 15)

# ---- extract: German invoice with traps ----------------------------------------------------------------------------
de = """Stadtwerke Beispiel GmbH
Musterweg 1, 12345 Musterstadt   Tel.: 0123 / 456 78 90   Fax 0123-45679
Kundennummer 4711    geb. 01.01.1975
Rechnung Nr. 2026-0042        Datum: 03.10.2026
Nettobetrag 100,00 €
MwSt 19 %      19,00 €
Gesamtbetrag 119,00 €
Zahlbar bis 17.10.2026
IBAN DE89 3704 0044 0532 0130 00"""
r = X.extract(de, TODAY)
check(r["date"] == "2026-10-03", f"de date {r}")
check(r["due"] == "2026-10-17", f"de due {r}")
check(r["amount"] == "119.00" and r["currency"] == "EUR", f"de amount {r}")

# English invoice, payment term in days, US date
en = "ACME Ltd\nInvoice date: Oct 1, 2026\nSubtotal $1,000.00\nVAT $234.56\nTotal due: $1,234.56\nPayment terms: net 30 days"
r = X.extract(en, TODAY)
check(r["date"] == "2026-10-01" and r["due"] == "2026-10-31", f"en dates {r}")
check(r["amount"] == "1234.56" and r["currency"] == "USD", f"en amount {r}")

# long German month, "innerhalb von 14 Tagen"
r = X.extract("Schreiben vom 15. Oktober 2026\nBitte überweisen Sie den Rechnungsbetrag von 45,50 EUR innerhalb von 14 Tagen.", TODAY)
check(r == {"date": "2026-10-15", "due": "2026-10-29", "amount": "45.50", "currency": "EUR"}, f"de long month {r}")

# ISO date, "fällig am" with an English month, total on the next line (table layout)
r = X.extract("Beleg 2026-09-30\nSumme\n1.234,00 EUR\nfällig am 14 November 2026", TODAY)
check(r["date"] == "2026-09-30" and r["due"] == "2026-11-14" and r["amount"] == "1234.00", f"iso + next line {r}")

# traps: only a phone number, a postal code, an IBAN, a birthday before 1990 and a date far ahead
r = X.extract("Telefon 030 12345678\n10115 Berlin\nIBAN DE02120300000000202051\ngeboren 01.01.1980\nVertrag bis 01.01.2035", TODAY)
check(r == {"date": None, "due": None, "amount": None, "currency": None}, f"traps {r}")
check(X.find_dates("Version 1.2.3.4 und 31.02.2026") == [], "no date from version numbers / 31 February")
check([d for _s, _e, d in X.find_dates("am 12/25/2025")] == [date(2025, 12, 25)], "US order when day-first is impossible")
check(X.parse_number("1.234,56") == "1234.56" and X.parse_number("1,234.56") == "1234.56" and X.parse_number("1 234,56") == "1234.56",
      "number formats")
check(X.parse_number("0,00") is None, "zero is no amount")
# without a total word: the largest amount with a currency, never a bare number
r = X.extract("Bestellung 12345\nArtikel A 9,99 €\nArtikel B 19,99 €", TODAY)
check(r["amount"] == "19.99", f"largest with currency {r}")

# ---- rules -----------------------------------------------------------------------------------------------------------
check(R.check_pattern("(a+)+$") == "nested", "nested quantifier refused")
check(R.check_pattern("(a|aa)*b") == "nested", "repeated alternation refused")
check(R.check_pattern(r"(\w)\1") == "backref", "back reference refused")
check(R.check_pattern("[") == "invalid", "broken regex refused")
check(R.check_pattern("x" * 300) == "long", "long regex refused")
check(R.check_pattern(r"Rechnung\s+Nr\.?\s*\d+") is None, "normal regex accepted")
try:
    R.clean_rule({"kind": "regex", "match": "(a+)+$", "type": "X"})
    check(False, "clean_rule must refuse an evil regex")
except R.RuleError:
    check(True, "")
try:
    R.clean_rule({"kind": "any", "match": "x"})
    check(False, "a rule must set something")
except R.RuleError:
    check(True, "")
rules = [R.clean_rule(x) for x in (
    {"kind": "any", "match": "Stadtwerke Energieversorger", "sender": "Stadtwerke"},
    {"kind": "all", "match": "Strom Abschlag", "type": "Abschlag", "tags": "Energie, Haus"},
    {"kind": "exact", "match": "Rechnung Nr", "type": "Rechnung", "tags": ["Finanzen"]},
    {"kind": "fuzzy", "match": "Kfz Versicherung", "tags": ["Auto"], "folder": "Versicherungen"},
    {"kind": "regex", "match": r"Vertrag\s+\d{6}", "sender": "Vertragspartner", "tags": ["Vertrag"]},
)]
out = R.apply_rules(rules, "Ihre STADTWERKE: Strom-Abschlag, Rechnung Nr. 5 zur Kfz-Versichcrung, Vertrag 123456")
check(out.get("sender") == "Stadtwerke", f"any + first rule wins the sender {out}")
check(out.get("type") == "Abschlag", f"all: first matching type {out}")
check(out.get("folder") == "Versicherungen", f"fuzzy match with an OCR typo {out}")
check(out["tags"] == ["Energie", "Haus", "Finanzen", "Auto", "Vertrag"], f"tags add up {out}")
out = R.apply_rules(rules, "Strom ohne das andere Wort; Rechnungsnummer")
check(out == {"tags": []}, f"all needs every word, exact needs the phrase {out}")
# an evil pattern stored by hand never hangs: refused before running
t0 = time.time()
evil = [{"kind": "regex", "match": "(a+)+$", "type": "X"}]
check(R.apply_rules(evil, "a" * 5000 + "b") == {"tags": []} and time.time() - t0 < 1, "stored evil regex is skipped")
t0 = time.time()
check(R.regex_hits(["(a+)+$"], "a" * 40 + "b") == [False] and time.time() - t0 < R.REGEX_SECONDS + 2, "regex child process time limit")
check(R.levels({"sender": "rules", "type": "bogus"}) == {"sender": "rules", "type": "learn", "tags": "learn", "folder": "learn"},
      "levels per feature with defaults")

# ---- classifier ------------------------------------------------------------------------------------------------------
docs = [("Stadtwerke Abschlag Strom Zaehler Kilowattstunden Verbrauch", "Stadtwerke"),
        ("Stadtwerke Strom Abschlag Jahresabrechnung Verbrauch", "Stadtwerke"),
        ("Versicherung Police Beitrag Kfz Haftpflicht", "Versicherung AG"),
        ("Versicherung Beitragsrechnung Police Haftpflicht Hausrat", "Versicherung AG"),
        ("Pizza Lieferung Quittung", "")]
m = C.new_model()
check(C.predict(m, C.tokens("Stadtwerke Strom")) == (None, 0.0), "an empty model predicts nothing")
for t, label in docs[:2]:
    C.learn(m, C.tokens(t), label)
check(C.predict(m, C.tokens("Stadtwerke Strom")) == (None, 0.0), "too few documents / one class: nothing")
for t, label in docs[2:]:
    C.learn(m, C.tokens(t), label)
lab, conf = C.predict(m, C.tokens("Ihre Stadtwerke: Abschlag Strom Oktober Verbrauch"))
check(lab == "Stadtwerke" and conf >= C.SURE, f"learns the sender ({lab}, {conf:.2f})")
lab, conf = C.predict(m, C.tokens("Police Versicherung neu"))
check(lab == "Versicherung AG" and conf >= C.MAYBE, f"second class ({lab}, {conf:.2f})")
check(C.predict(m, C.tokens("Bahn Fahrkarte Reise"))[0] is None, "unknown words: nothing")
# a single example of a label is not enough
m2 = C.new_model()
for t, label in docs[:4] + [("Arzt Praxis Rezept", "Arzt")]:
    C.learn(m2, C.tokens(t), label)
check(C.predict(m2, C.tokens("Arzt Praxis Rezept"))[0] is None, "a label with one example is never predicted")
# a correction: unlearn the old label, learn the new
C.unlearn(m, C.tokens(docs[0][0]), "Stadtwerke")
C.learn(m, C.tokens(docs[0][0]), "Energie Nord")
check(m["classes"]["Stadtwerke"]["n"] == 1 and m["classes"]["Energie Nord"]["n"] == 1 and m["docs"] == 5, f"correction {m['docs']}")
# workspaces apart: a model of another workspace knows none of these words
other = C.new_model()
for t, label in [("Mandant Akte Vertrag", "Kanzlei"), ("Mandant Akte Frist", "Kanzlei"), ("Lieferant Ware Bestellung", "Lager")]:
    C.learn(other, C.tokens(t), label)
check("stadtwerke" not in str(other) and "mandant" not in str(m), "models of two workspaces share nothing")
# tags: yes / no per tag
tm = {}
for t, tags in [("Strom Abschlag Stadtwerke", ["Energie"]), ("Strom Zaehler Stadtwerke", ["Energie"]), ("Gas Abschlag Stadtwerke", ["Energie"]),
                ("Police Kfz Beitrag", ["Auto"]), ("Werkstatt Kfz Reparatur", ["Auto"]), ("Pizza Quittung", [])]:
    C.learn_tags(tm, C.tokens(t), tags, ["Energie", "Auto"])
got = [t for t, _c in C.predict_tags(tm, C.tokens("Stadtwerke Strom Abschlag"))]
check(got == ["Energie"], f"tag prediction {got}")
check(C.tokens("Grüße für Müller und Straße 12 ÄÖÜ")[:3] == ["grusse", "muller", "strasse"], f"folding {C.tokens('Grüße für Müller und Straße')}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
