#!/usr/bin/env python3
"""2.47.0 part C (#1216): the shoot calculation sheet (kalmido/office/sheet.py) and the industry pack Film & Video, pure
Python, no server. Invented figures (crew: Camera 650 intern, Director 800 intern, Lighting 350 extern):
 - staff: day rate x (shoot days + travel days x share + [prep] prep days x share + weekend surcharges) x people
 - producing = share of the crew sum; km x rate x trips; meals = people x (travel x small + shoot x large/small by nights);
   hotel = people x nights x price; set = days x day price x (1 - discount), days differ from the shoot days -> a note
 - discount rounded to whole units (half up); third-party costs = the extern rows without markup; markup only on the price
 - clean: a new crew row copies the role (a later change of the role leaves it), members cannot set markup / base rate /
   intern-extern (the stored value stays), the public sheet / calc hide markup and purchase from members
 - the print model has no intern / extern, purchase or markup; the pack check refuses broken packs
usage: python3 tests/p2470_c_sheet_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib
import json
import os
import sys
import types
from decimal import Decimal

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
# load kalmido/office/sheet.py (and calc.py, its only import) without the app package
pkg = types.ModuleType("dkoffice")
pkg.__path__ = [os.path.join(SRC, "kalmido", "office")]
sys.modules["dkoffice"] = pkg
S = importlib.import_module("dkoffice.sheet")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def eq(a, b, what):
    check(a == b, f"{what}: {a!r} != {b!r}")


def head(**kw):
    h = {"shoot_days": 1, "travel_days": 1, "travel_share": 1, "prep_days": 0.5, "prep_share": 1, "nights": 2, "night_rate": 100,
         "meal_large": 28, "meal_small": 14, "sat_days": 0, "sat_pct": 25, "sun_days": 0, "sun_pct": 75}
    h.update(kw)
    return h


def sheet(**kw):
    s = {"v": 1, "pack": "film", "head": head(),
         "staff": [{"uid": "cam", "name": "Kamera", "name_en": "Camera", "rate": 650, "intext": "intern", "qty": 1, "prep": 1},
                   {"uid": "dir", "name": "Regie", "name_en": "Director", "rate": 800, "intext": "intern", "qty": 1, "prep": 1},
                   {"uid": "lig", "name": "Beleuchter", "name_en": "Lighting", "rate": 350, "intext": "extern", "qty": 2, "prep": 0}],
         "producing": {"on": 1, "share": 0.2}, "km": {"km": 300, "rate": 0.35, "trips": 2}, "meals_on": 1,
         "set": {"set_id": 1, "name": "Interview", "days": None, "discount_pct": 20, "intext": "intern",
                 "items": [{"equipment_id": 1, "name": "Kamera-Set", "qty": 1, "rate": 400}, {"equipment_id": 2, "name": "Licht", "qty": 2, "rate": 100}]},
         "extras": [{"uid": "stu", "name": "Studio", "qty": 1, "rate": 500, "intext": "extern"}], "discount_pct": 5}
    s.update(kw)
    return s


def line(calc, uid):
    return next((ln for ln in calc["lines"] if ln["uid"] == uid), None)


# ---- the pack
pack = S.dk_pack("film")
check(pack is not None, "the pack film loads")
eq(S.dk_pack_codes(), ["film"], "pack codes")
with open(os.path.join(SRC, "kalmido", "office", "packs", "industry", "film.json"), encoding="utf-8") as f:
    raw = json.load(f)
eq(S.dk_pack_validate(raw), [], "film.json is valid")
eq(raw["defaults"]["meal_large"], 28, "meal large 28")
eq(raw["defaults"]["meal_small"], 14, "meal small 14")
eq((raw["defaults"]["sat_pct"], raw["defaults"]["sun_pct"]), (25, 75), "weekend surcharges")
eq((raw["defaults"]["producing_share"], raw["defaults"]["km_rate"]), (0.2, 0.35), "producing share / km rate")
bad = json.loads(json.dumps(raw))
bad["blocks"] = ["staff", "staff", "magic"]
del bad["labels"]["en"]["net"]
bad["labels"]["de"]["title"] = "<b>x</b>"
bad["defaults"]["km_rate"] = -1
probs = S.dk_pack_validate(bad)
check(any(p.startswith("blocks") for p in probs), "a broken block list is refused")
check(any("labels.en.net" in p for p in probs), "a missing label is refused")
check(any("markup" in p for p in probs), "markup in a pack is refused")
check(any("defaults.km_rate" in p for p in probs), "a negative default is refused")
eq(S.dk_pack_validate("x"), ["pack must be an object"], "not an object")
eq(S.dk_packs_clean(["film", "FILM", "nope", 3]), ["film"], "packs_clean keeps known codes once")
check(S.dk_enabled({"industry_packs": ["film"]}) and not S.dk_enabled({"industry_packs": []}) and not S.dk_enabled({}), "dk_enabled")

# ---- the main example
c = S.dk_sheet_calc(sheet(), None, "de", "EUR", 1)
eq(line(c, "cam")["total"], "1625.00", "camera 650 x (1 + 1 + 0.5)")
eq(line(c, "dir")["total"], "2000.00", "director 800 x 2.5")
eq(line(c, "lig")["rate"], "700.00", "lighting without prep 350 x 2 per person")
eq(line(c, "lig")["total"], "1400.00", "lighting 2 people")
eq(line(c, "lig")["cost"], "1400.00", "extern staff = purchase")
eq(line(c, "cam")["cost"], "0.00", "intern staff = no purchase")
eq(c["staff_sum"], "5025.00", "staff sum")
eq(line(c, "share")["total"], "1005.00", "producing 0.2 x staff sum")
eq(line(c, "km")["total"], "210.00", "km 300 x 0.35 x 2")
eq(line(c, "meals")["rate"], "42.00", "meals: 1 travel day x 14 + 1 shoot day x 28 (more than one night)")
eq(line(c, "meals")["total"], "168.00", "meals x 4 people")
eq(line(c, "hotel")["total"], "800.00", "hotel 4 people x 2 nights x 100")
eq(line(c, "set")["rate"], "600.00", "set price per day = sum of its equipment")
eq(line(c, "set")["total"], "480.00", "set 1 day x 600 x (1 - 20 %)")
eq(line(c, "set")["cost"], "0.00", "own set = intern")
eq(line(c, "stu")["total"], "500.00", "additional cost")
eq(c["sum"], "8188.00", "sum")
eq(c["discount"], "-409.00", "discount 5 % rounded to whole euros (409.40)")
eq(c["net"], "7779.00", "net")
eq(c["base"], {"standard": "7779.00", "reduced": "0.00", "exempt": "0.00"}, "tax base: everything standard")
eq(c["costs"], "3078.00", "third-party costs = extern rows")
eq(c["margin"], "4701.00", "surplus = net - costs")
eq(c["blocks"], ["staff", "share", "km", "meals", "hotel", "set", "free"], "print order from the pack")
eq([ln["block"] for ln in c["lines"]][:3], ["staff", "staff", "staff"], "staff first")

cp = S.dk_sheet_calc(sheet(), {"code": "DE", "tax": {"standard": 19}}, "de", "EUR", Decimal(1))
eq((cp["net"], cp["labels"].get("title")), ("7779.00", "Drehkostenkalkulation"), "a country pack passed in: the sheet's industry pack is used")

# meals with one night: the shoot day at the small rate too (the spreadsheet's rule)
c1 = S.dk_sheet_calc(sheet(head=head(nights=1)))
eq(line(c1, "meals")["rate"], "28.00", "one night: 14 + 14")
eq(line(c1, "hotel")["total"], "400.00", "one night x 4 people")
c0 = S.dk_sheet_calc(sheet(head=head(nights=0)))
check(line(c0, "hotel") is None, "no nights = no hotel row")
cm = S.dk_sheet_calc(sheet(meals_on=0))
check(line(cm, "meals") is None, "meals off")

# set days differ from the shoot days
s2 = sheet()
s2["set"]["days"] = 2
c2 = S.dk_sheet_calc(s2)
eq(line(c2, "set")["total"], "960.00", "2 days x 600 x 0.8")
check(line(c2, "set")["days_differ"], "days differ flag")
check("abweichend von 1 Drehtagen" in line(c2, "set")["detail"], "note: differs from 1 shooting day")
check(not line(c, "set").get("days_differ"), "default days: no note")
eq(line(S.dk_sheet_calc(s2, None, "en"), "set")["detail"].split(",")[0], "differs from 1 shooting days", "note in English")

# markup only on the price
s3 = sheet()
s3["staff"][2]["markup_pct"] = 10
c3 = S.dk_sheet_calc(s3)
eq(line(c3, "lig")["rate"], "770.00", "markup 10 % on the price")
eq(line(c3, "lig")["total"], "1540.00", "markup x 2 people")
eq(line(c3, "lig")["cost"], "1400.00", "purchase stays without markup")
s3["extras"][0]["markup_pct"] = 20
c3 = S.dk_sheet_calc(s3)
eq((line(c3, "stu")["total"], line(c3, "stu")["cost"]), ("600.00", "500.00"), "markup on an extern additional cost")

# Saturday / Sunday surcharges
c4 = S.dk_sheet_calc(sheet(head=head(shoot_days=2, travel_days=0, prep_days=0, sat_days=1, sun_days=1)))
eq(line(c4, "cam")["total"], "1950.00", "650 x (2 + 1 x 0.25 + 1 x 0.75)")
c5 = S.dk_sheet_calc(sheet(head=head(travel_days=1, travel_share=0.5, prep_days=1, prep_share=0.5)))
eq(line(c5, "cam")["total"], "1300.00", "travel share 0.5, prep share 0.5: 650 x 2")

# discount rounding half up to whole units
c6 = S.dk_sheet_calc({"v": 1, "pack": "film", "head": head(), "extras": [{"uid": "a", "name": "X", "qty": 1, "rate": 1010, "intext": "extern"}],
                      "producing": {"on": 0}, "meals_on": 0, "discount_pct": 5})
eq(c6["discount"], "-51.00", "5 % of 1010 = 50.50 -> 51")
eq(c6["net"], "959.00", "net after the rounded discount")

# USD: the rate converted first
c7 = S.dk_sheet_calc(sheet(), None, "en", "USD", "1.1")
eq(line(c7, "cam")["total"], "1787.50", "650 x 1.1 = 715 x 2.5")
eq(line(c7, "cam")["label"], "Camera", "English role name")
eq(c7["currency"], "USD", "currency")

# ---- public views for members
pub = S.dk_calc_public(c3, False)
check("costs" not in pub and "margin" not in pub, "members: no costs / margin")
check(all("cost" not in ln and "markup_pct" not in ln and "intext" not in ln for ln in pub["lines"]), "members: no purchase per row")
check(S.dk_calc_public(c3, True) is c3, "admins see everything")
sp = S.dk_sheet_public(s3, False)
check(all("markup_pct" not in r for r in sp["staff"] + sp["extras"]), "members: no markup in the sheet")
eq(sp["staff"][2]["rate"], 385.0, "members see the price including the markup")
eq(s3["staff"][2]["markup_pct"], 10, "the stored sheet is untouched")


# ---- clean with a fake database
class Row(dict):
    pass


class FakeConn:
    def __init__(self):
        self.roles = {7: Row(id=7, name_de="Maske", name_en="Make-up", rate_day=Decimal("600"), intext="extern", markup_pct=Decimal("15")),
                      8: Row(id=8, name_de="Kamera", name_en="Camera", rate_day=Decimal("650"), intext="intern", markup_pct=None)}
        self.services = {3: Row(id=3, name_de="Studio", name_en="Studio", daily_rate=Decimal("900"))}
        self.equipment = {1: Row(id=1, name="Kamera-Set", name_en="Camera kit", daily_rate=Decimal("400")),
                          2: Row(id=2, name="Licht", name_en="Light", daily_rate=Decimal("100"))}
        self.sets = {5: Row(id=5, name="Interview", discount_pct=Decimal("20"), items=json.dumps([{"equipment_id": 1, "qty": 1}, {"equipment_id": 2, "qty": 2}]))}

    def execute(self, sql, args):
        oid = args[1]
        hit = None
        if oid == 1:
            if "FROM office_roles" in sql:
                hit = self.roles.get(args[0])
            elif "FROM office_services" in sql:
                hit = self.services.get(args[0])
            elif "FROM office_equipment" in sql:
                hit = self.equipment.get(args[0])
            elif "FROM office_sets" in sql:
                hit = self.sets.get(args[0])
        return types.SimpleNamespace(fetchone=lambda: hit)


db = FakeConn()
new = S.dk_sheet_clean(db, 1, {}, {}, True)
eq(new["head"]["meal_large"], 28, "a new sheet takes the pack defaults")
eq(new["producing"], {"on": 1, "share": 0.2}, "producing default")
eq(new["km"]["rate"], 0.35, "km rate default")
eq(S.dk_sheet_new(pack)["head"]["sun_pct"], 75, "dk_sheet_new")

# a member adds a crew row: the role's rate, intext and markup are copied; a markup / rate the member sends is ignored
m1 = S.dk_sheet_clean(db, 1, {"staff": [{"role_id": 7, "qty": 2, "prep": 0, "markup_pct": 0, "rate": 1, "intext": "intern"}]}, new, False)
r = m1["staff"][0]
eq((r["name"], r["rate"], r["intext"], r["markup_pct"], r["qty"], r["prep"]), ("Maske", 600, "extern", 15, 2, 0), "member: role values copied")
check(r["uid"], "the row gets a uid")
# the role changes later: the row keeps its values
db.roles[7]["rate_day"] = Decimal("700")
m2 = S.dk_sheet_clean(db, 1, {"staff": [{"uid": r["uid"], "role_id": 7, "qty": 3, "markup_pct": 50, "rate": 9}]}, m1, False)
eq((m2["staff"][0]["rate"], m2["staff"][0]["markup_pct"], m2["staff"][0]["qty"]), (600, 15, 3), "member: stored rate / markup stay, qty changes")
# an admin may set markup, rate and intext
a1 = S.dk_sheet_clean(db, 1, {"staff": [{"uid": r["uid"], "markup_pct": 0, "rate": 550, "intext": "intern"}]}, m2, True)
eq((a1["staff"][0]["rate"], a1["staff"][0]["markup_pct"], a1["staff"][0]["intext"]), (550, 0, "intern"), "admin sets rate / markup / intext")
# a role of another organisation / unknown role is dropped; a member cannot add a row without a role
x = S.dk_sheet_clean(db, 2, {"staff": [{"role_id": 7}]}, new, True)
eq(x["staff"], [], "foreign organisation: no role")
x = S.dk_sheet_clean(db, 1, {"staff": [{"name": "Free", "rate": 5}]}, new, False)
eq(x["staff"], [], "member: no row without a role")
# shooting service as additional cost
e1 = S.dk_sheet_clean(db, 1, {"extras": [{"service_id": 3, "qty": 1}, {"name": "Fahrzeug", "qty": 1, "rate": 150}]}, new, False)
eq([(e["name"], e["rate"], e["intext"]) for e in e1["extras"]], [("Studio", 900, "extern"), ("Fahrzeug", 150, "extern")], "service row + free row")
e2 = S.dk_sheet_clean(db, 1, {"extras": [dict(e1["extras"][1], intext="intern", markup_pct=30)]}, e1, False)
eq((e2["extras"][0]["intext"], e2["extras"][0]["markup_pct"]), ("extern", 0), "member: intext / markup of a row stay")
# picking a set copies equipment + discount; the rows can be changed afterwards
s1 = S.dk_sheet_clean(db, 1, {"set": {"set_id": 5}}, new, False)
eq((s1["set"]["name"], s1["set"]["discount_pct"], [(i["name"], i["qty"], i["rate"]) for i in s1["set"]["items"]]),
   ("Interview", 20, [("Kamera-Set", 1, 400), ("Licht", 2, 100)]), "set copied")
s2c = S.dk_sheet_clean(db, 1, {"set": {"set_id": 5, "days": 3, "discount_pct": 10, "items": [{"equipment_id": 2, "qty": 4}]}}, s1, False)
eq((s2c["set"]["days"], s2c["set"]["discount_pct"], [(i["name"], i["qty"]) for i in s2c["set"]["items"]]), (3, 10, [("Licht", 4)]), "set adjusted in the sheet")
eq(json.loads(db.sets[5]["items"])[1]["qty"], 2, "the master set stays as it is")
s3c = S.dk_sheet_clean(db, 1, {"set": {"set_id": 5, "items": [{"equipment_id": 2, "qty": 4}, {"equipment_id": 1, "qty": 1}]}}, s2c, True)
eq([i["name"] for i in s3c["set"]["items"]], ["Licht", "Kamera-Set"], "equipment added")
eq(S.dk_sheet_clean(db, 1, {"set": None}, s3c, True)["set"], None, "set removed")
# junk input
j = S.dk_sheet_clean(db, 1, {"head": {"shoot_days": "-3", "nights": "abc", "night_rate": "1.234,50"}, "discount_pct": 500, "staff": "x"}, new, True)
eq((j["head"]["shoot_days"], j["head"]["nights"], j["head"]["night_rate"], j["discount_pct"]), (0, 0, 1234.5, 100), "clamped numbers")

# ---- print model
pr = S.dk_sheet_print(c3, "de")
eq(pr["title"], "Drehkostenkalkulation", "print title")
eq(pr["head"][0], ["Drehtage", "1"], "print head")
dump = json.dumps(pr)
check("extern" not in dump and "intern" not in dump and "1400" not in dump, "print: no intern / extern, no purchase")
eq(pr["rows"][0]["kind"], "group", "crew group heading")
eq(pr["totals"][-1], ["Summe Netto", "8.033,00 €"], "print net: 8456 - 423")
check(any(t[0].startswith("Rabatt 5") for t in pr["totals"]), "print discount")

print(f"p2470_c_sheet: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
