#!/usr/bin/env python3
"""2.461.0 (#3773): public holidays per country: data files, translatable names, the picker's data. Own container. Invented data only.
freelancer-matrix: hub
 - every country file is valid and every name has a translation in every language
 - the dates of each country in a known year, German states unchanged, the nationwide choice "DE"
 - a French reader gets countries first and French names; a person without an organisation can choose a country
usage: p2461_holidays_test.py <datadir>"""
# kalmido-suite: fresh
import glob
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sp = importlib.util.spec_from_file_location("holidays", os.path.join(ROOT, "kalmido", "hub", "holidays.py"))
H = importlib.util.module_from_spec(sp)
sp.loader.exec_module(H)

check(list(H.HOL_PACKS) == ["DE", "AT", "CH", "FR", "ES", "IT", "NL"], "the seven countries, Germany first " + str(list(H.HOL_PACKS)))
for lg in ("de", "fr", "es", "it", "nl"):
    d = json.load(open(os.path.join(ROOT, "static", "i18n", lg + ".json"), encoding="utf-8"))
    for p in glob.glob(os.path.join(ROOT, "kalmido", "office", "packs", "holidays", "*.json")):
        f = json.load(open(p, encoding="utf-8"))
        names = [f["name"], *(f.get("regions") or {}).values(), *(h["name"] for h in f["holidays"])]
        check(all(d.get(n) for n in names), f"{lg}: every name of {f['code']} translated")


def days(code, y=2027):
    return H.hol_year(y, code)


check(len(days("FR")) == 11 and days("FR")["2027-07-14"] == "National Day|France", "France: 11 days, 14 July")
check(len(days("ES")) == 10 and days("ES")["2027-03-26"] == "Good Friday", "Spain: 10 days, Good Friday")
check(len(days("IT")) == 13 and "2027-10-04" in days("IT") and "2025-10-04" not in days("IT", 2025), "Italy: 4 October from 2026 on")
check(days("NL")["2027-04-27"] == "King's Day" and days("NL", 2025)["2025-04-26"] == "King's Day", "the Netherlands: King's Day moves off a Sunday")
check("2027-05-05" not in days("NL") and "2030-05-05" in days("NL", 2030), "the Netherlands: Liberation Day every five years")
check(len(days("CH")) == 8 and "2027-08-01" in days("CH"), "Switzerland: nationwide only, 1 August")
check(len(days("DE")) == 9 and "2027-11-01" not in days("DE") and "2027-11-01" in days("BY"), "Germany: nationwide only, Bavaria keeps All Saints")
check(days("SN")["2027-11-17"] == "Day of Repentance and Prayer", "Saxony: Wednesday before 23 November")
check("2022-03-08" in days("BE", 2022) and "2022-03-08" not in days("MV", 2022) and "2023-03-08" in days("MV", 2023), "a region's own first year")
check(days("") == {} and days("XX") == {}, "nothing chosen, unknown code: none")

fresh()
A = setup()
FID, Fr = freelancer(B, A)
assert Fr.patch(B + "/api/settings", json={"lang": "fr"}).ok
j = Fr.get(B + "/api/team/absences/feed").json()
c = {x["code"]: x for x in j["countries"]}
check(c["FR"]["name"] == "France" and c["FR"]["regions"] == {} and c["DE"]["regions"]["BY"] == "Bavière", "countries first, French names " + str(c["DE"]["name"]))
check(Fr.patch(B + "/api/settings", json={"holiday_state": "FR"}).ok, "a person without an organisation picks France")
hol = [e["title"] for e in Fr.get(B + "/api/calendars/events", params={"from": "2027-07-13", "to": "2027-07-15"}).json().get("events", []) if e.get("holiday")]
check(hol == ["Fête nationale"], "the French holiday in French " + str(hol))
j = Fr.get(B + "/api/team/absences").json()
check(len(j["countries"]) == 7, "the Absences answer carries the countries")
check(Fr.put(B + "/api/team/absences/holidays", json={"state": "DE"}).ok, "the personal area takes the nationwide choice")
done()
