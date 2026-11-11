#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.925.0 (#5454): one thing, one word in the office (German) -- static, reads static/i18n/de.json, no server.
 - Briefpapier (never Briefkopf), Textbaustein (never Textblock), Geräte (never Ausrüstung / Büro-Ausstattung)
 - own documents carry a Dokumentnummer (Belegnummer only for DATEV), card refunds are an Erstattung (not Gutschrift)
 - Anfrage only for leads (the next pipeline stage has its own word), Reisen (travel expenses) apart from Fahrten (logbook)
 - the contract menu points have four different names; the office settings are "Einstellungen > Firma & Büro" everywhere
 - an office deletion into the trash says so: "Moved to the trash" in all five languages"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402  shared helpers (tests/kt.py)

de = json.load(open(os.path.join(R, "static", "i18n", "de.json"), encoding="utf-8"))
vals = [(k, v if isinstance(v, str) else " ".join(v)) for k, v in de.items()]
bad = lambda word: [k for k, v in vals if word in v]  # noqa: E731

check(not bad("Briefkopf"), f"no Briefkopf {bad('Briefkopf')}")
check(not bad("Textblock"), f"no Textblock {bad('Textblock')}")
check(not bad("Ausrüstung") and not bad("Büro-Ausstattung"), f"Geräte only {bad('Ausrüstung') + bad('Büro-Ausstattung')}")
check(not bad("Büro-Einstellungen"), f"one place for the office settings {bad('Büro-Einstellungen')}")
check(de["Document number"] == "Dokumentnummer" and [k for k in bad("Belegnummer")] == ["DATEV receipt number"], f"Belegnummer only for DATEV {bad('Belegnummer')}")
check(de["Money back"] == "Erstattung", "card refunds: Erstattung")
check(de["Leads"] != de["Enquiry"] and "Anfrage" not in de["Enquiry"], "Anfrage only for leads")
check(de["Trips"] != de["Drives"], f"trips and drives apart: {de['Trips']} / {de['Drives']}")
menu = [de[k] for k in ("Framework contracts", "Letters & contracts", "Contracts & subscriptions", "Subscriptions & tools")]
check(len(set(menu)) == 4 and sum("Verträge" in m for m in menu) <= 2, f"the contract menu points told apart {menu}")
check("Muster" not in de["Use sample"], "Beispiel, not Muster")
for lang in ("de", "es", "fr", "it", "nl"):
    t = json.load(open(os.path.join(R, "static", "i18n", f"{lang}.json"), encoding="utf-8"))
    check(bool(t.get("Moved to the trash")), f"{lang}: Moved to the trash")

print(f"p2925_a_words: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
