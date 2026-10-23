#!/usr/bin/env python3
"""2.95.0 API tests, part A (#1932): the per diem (Verpflegungsmehraufwand) of a trip and its report per person and year,
own container (start.sh, org encryption on). Invented companies, people and figures only; the expected rates come from the
tables in kalmido/office/vma.py (Germany 28 / 14, Greece outside Athens 2025 36 / 24, Czechia 2025 32 / 21).
 - the trip answers vma {amount per participant, total, lines, hints, source}: Germany over several days, a single day with
   times (more than 8 hours = 14), without times (no amount, hint "times"), 8 hours or less (0, hint "short"), abroad with
   days in two countries, meals provided cut the rate (breakfast 20 %, lunch 40 %), 2027 = no table (no amount + hint
   "year"), "no per diem" (0, hint "off"), several participants (total = amount x participants), a trip over the turn of
   the year counts its days per year; invalid fields are refused
 - GET /api/office/trips/vma-rates: countries and cities of a year, 2027 = none + hint
 - GET /api/office/trips/vma: the sums per person (one entry per participant, "No person" for a trip without), open trips
   listed but not summed, "no per diem" left out, ?person= filters; vma.pdf / vma.xlsx (one sheet per person) / vma.csv
 - rights: a member gets 403, another organisation sees none of the trips and gets 404 on them; a person without an
   organisation (the personal office, its own admin) gets 200 everywhere -- freelancer-matrix: office -- tenant-matrix: office
usage: p295_a_api_test.py <datadir>      (P295A_NOSTART=1: use a running server)"""
import base64
import csv
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P295A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
A.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
T = "/api/office/trips"


def trip(s, **kw):
    r = s.post(B + T, json=kw)
    check(r.status_code == 201, f"trip {kw.get('dest')}: {r.status_code} {r.text[:200]}")
    return r.json()


# ---------------------------------------------------------------- the per diem of a trip
t1 = trip(A, date_from="2025-03-10", date_to="2025-03-12", dest="Hamburg", overnight=True, people=[{"id": ALICE}, {"id": BOB}], project="Film eins")
v = t1["vma"]
check(v["amount"] == "56.00" and v["persons"] == 2 and v["total"] == "112.00" and t1["country"] == "" and t1["vma_off"] == 0,
      f"Germany, three days: 14 + 28 + 14 = 56 per person, 112 for two {v}")
check([(x["kind"], x["n"], x["rate"]) for x in v["lines"]] == [("partial", 2, "14.00"), ("full", 1, "28.00")] and v["source"] and "BMF" in v["source"][0],
      f"the lines per rate and the source {v['lines']} {v['source']}")
# meals provided on the full day: breakfast 20 % + lunch 40 % of 28 = 16.80
r = A.patch(B + f"{T}/{t1['id']}", json={"vma_days": [{"date": "2025-03-11", "b": 1, "l": 1}]})
check(r.ok and r.json()["vma"]["amount"] == "39.20" and r.json()["vma"]["cut"] == "16.80" and r.json()["vma_days"] == [{"date": "2025-03-11", "b": 1, "l": 1}],
      "meals provided cut the rate (56 - 5.60 - 11.20 = 39.20) " + r.text[:300])
r = A.patch(B + f"{T}/{t1['id']}", json={"vma_days": [{"date": "2025-03-11", "b": 1, "l": 1}, {"date": "2025-03-12"}]})
check(r.ok and len(r.json()["vma_days"]) == 1, "a day without a difference is not stored")
check(A.patch(B + f"{T}/{t1['id']}", json={"vma_days": [{"date": "11.03.2025", "b": 1}]}).status_code == 400, "a day with an invalid date is refused")
check(A.patch(B + f"{T}/{t1['id']}", json={"t_start": "25:00"}).status_code == 400, "an invalid time is refused")
check(A.patch(B + f"{T}/{t1['id']}", json={"country": "XX"}).status_code == 400, "an invalid country is refused")
# a single day
t2 = trip(A, date_from="2025-06-02", dest="Lübeck", t_start="08:00", t_end="17:30", people=[{"id": ALICE}])
check(t2["vma"]["amount"] == "14.00" and t2["t_start"] == "08:00", f"a single day of 9.5 hours = 14 {t2['vma']}")
t3 = trip(A, date_from="2025-06-03", dest="Kiel", people=[{"id": ALICE}])
check(t3["vma"]["amount"] is None and t3["vma"]["total"] is None and {"key": "times"} in t3["vma"]["hints"], f"a single day without times: no amount, hint {t3['vma']}")
t4 = trip(A, date_from="2025-06-04", dest="Bremen", t_start="08:00", t_end="15:00", people=[{"id": ALICE}])
check(t4["vma"]["amount"] == "0.00" and {"key": "short"} in t4["vma"]["hints"], f"8 hours or less: 0 and hint {t4['vma']}")
# 2.95.0 (#1932 review): two days without an overnight stay: the hours together, on the day with the most of them
t9 = trip(A, date_from="2026-12-31", date_to="2027-01-01", dest="Nachtfahrt", t_start="14:00", t_end="02:00", people=[{"id": ALICE}])
check(t9["vma"]["amount"] == "14.00" and t9["vma"]["days"][0]["kind"] == "partial", f"10 h on 31.12. + 2 h: 14 on the first day (2026 table) {t9['vma']}")
t10 = trip(A, date_from="2025-06-05", date_to="2025-06-06", dest="Ohne Zeiten", people=[{"id": ALICE}])
check(t10["vma"]["amount"] is None and {"key": "times"} in t10["vma"]["hints"], f"two days without a stay and without times: hint {t10['vma']}")
for x in (t9, t10):
    check(A.delete(B + f"{T}/{x['id']}").ok, "cleanup")
# abroad, the last two days in another country
t5 = trip(A, date_from="2025-05-01", date_to="2025-05-04", dest="Thessaloniki - Prag", overnight=True, country="GR", people=[{"name": "Externe Person"}],
          purpose="acquisition", vma_days=[{"date": "2025-05-03", "country": "CZ"}, {"date": "2025-05-04", "country": "CZ"}])
check(t5["country"] == "GR" and t5["vma"]["amount"] == "113.00", f"Greece 24 + 36, Czechia 32 + 21 = 113 {t5['vma']}")
check([x["country"] for x in t5["vma"]["lines"]] == ["GR", "GR", "CZ", "CZ"], "the lines follow the days")
# 2027 has no table: no amount, a hint, never an estimate
t6 = trip(A, date_from="2027-03-01", date_to="2027-03-02", dest="Köln", overnight=True, people=[{"id": ALICE}])
check(t6["vma"]["amount"] is None and {"key": "year", "year": 2027} in t6["vma"]["hints"], f"2027: no amount, hint year {t6['vma']}")
# no per diem for this trip
t7 = trip(A, date_from="2025-07-01", date_to="2025-07-03", dest="Dresden", overnight=True, people=[{"id": BOB}], vma_off=1)
check(t7["vma"]["amount"] == "0.00" and {"key": "off"} in t7["vma"]["hints"] and t7["vma_off"] == 1, "no per diem: 0 and hint off")
# over the turn of the year: 14 + 28 in 2025, 28 + 14 in 2026
t8 = trip(A, date_from="2025-12-30", date_to="2026-01-02", dest="Berlin", overnight=True, people=[{"id": BOB}])
check(t8["vma"]["amount"] == "84.00" and len(t8["vma"]["source"]) == 2, f"over the turn of the year: 84, two sources {t8['vma']}")
# a trip without participants
trip(A, date_from="2025-08-05", date_to="2025-08-06", dest="Rostock", overnight=True)
# the list carries the same
j = A.get(B + T + "?year=2025").json()
check(next(x for x in j["trips"] if x["id"] == t5["id"])["vma"]["amount"] == "113.00", "the trip list carries the per diem")

# ---------------------------------------------------------------- the rates of a year
j = A.get(B + T + "/vma-rates?year=2025").json()
gr = next((c for c in j["countries"] if c["code"] == "GR"), None)
check(j["years"] == [2025, 2026] and j["home"] == {"full": 28, "partial": 14} and gr and gr["places"][0] == "" and "Athen" in gr["places"] and gr["full"] == 36 and gr["partial"] == 24
      and "BMF" in j["source"], f"the rates of 2025 {gr}")
j = A.get(B + T + "/vma-rates?year=2027").json()
check(j["countries"] == [] and j["hint"] == {"key": "year", "year": 2027}, f"2027: no rates, a hint {j}")
check(A.get(B + T + "/vma-rates?year=20x5").status_code == 400, "an invalid year is refused")

# ---------------------------------------------------------------- the report
rep = A.get(B + T + "/vma?year=2025").json()
pp = {g["label"]: g for g in rep["people"]}
check(set(pp) == {"Alice Admin", "Bob Member", "Externe Person", "No person"} and rep["people"][-1]["label"] == "No person",
      f"one entry per participant, no person last {[g['label'] for g in rep['people']]}")
# Alice: t1 39.20 + t2 14 + t4 0 = 53.20, t3 open; Bob: t1 39.20 + t8 (2025 part) 42 = 81.20; t7 (off) left out
check(pp["Alice Admin"]["total"] == "53.20" and pp["Alice Admin"]["open"] == 1 and len(pp["Alice Admin"]["trips"]) == 4, f"Alice: sums and the open trip {pp['Alice Admin']}")
check(pp["Bob Member"]["total"] == "81.20" and not any(x["id"] == t7["id"] for x in pp["Bob Member"]["trips"]), f"Bob: the 2025 part of the turn of the year, no 'no per diem' {pp['Bob Member']}")
check(pp["Externe Person"]["total"] == "113.00" and pp["No person"]["total"] == "28.00", "a free name and no person (14 + 14)")
check(rep["total"] == "275.40" and rep["currency"] == "EUR" and rep["open"] == 1 and rep["rates"] and "BMF" in rep["source"][0], f"the total of the year {rep['total']}")
x5 = pp["Externe Person"]["trips"][0]
check(x5["purpose"] == "Acquisition / research" and x5["breakdown"] == ["Greece: 1 × 24 € + 1 × 36 € = 60 €", "Czechia: 1 × 32 € + 1 × 21 € = 53 €"],
      f"the breakdown like the spreadsheet {x5}")
x1 = next(x for x in pp["Alice Admin"]["trips"] if x["id"] == t1["id"])
check(x1["purpose"] == "Film eins" and x1["breakdown"][0] == "Germany: 2 × 14 € + 1 × 28 € = 56 €" and "16.80" in x1["breakdown"][-1], f"the cut for meals as a line {x1['breakdown']}")
x3 = next(x for x in pp["Alice Admin"]["trips"] if x["id"] == t3["id"])
check(x3["amount"] is None and x3["hints"] == [{"key": "times"}], "the open trip with its hint")
rep26 = A.get(B + T + "/vma?year=2026").json()
check([(g["label"], g["total"]) for g in rep26["people"]] == [("Bob Member", "42.00")], f"2026: the rest of the turn of the year {rep26['people']}")
rep27 = A.get(B + T + "/vma?year=2027").json()
check(rep27["total"] == "0.00" and rep27["open"] == 1 and not rep27["rates"], "2027: listed as open, nothing summed")
j = A.get(B + T + f"/vma?year=2025&person=u{BOB}").json()
check([g["label"] for g in j["people"]] == ["Bob Member"] and j["total"] == "81.20", "?person= filters one person")
# files
r = A.get(B + T + "/vma.pdf?year=2025")
check(r.ok and r.content[:4] == b"%PDF" and "attachment" in r.headers.get("Content-Disposition", ""), "the PDF")
r = A.get(B + T + "/vma.xlsx?year=2025")
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
sheets = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/")) if z else []
wb = z.read("xl/workbook.xml").decode() if z else ""
check(len(sheets) == 4 and "Alice Admin" in wb and "Externe Person" in wb, f"the Excel: one sheet per person {sheets}")
s1 = z.read("xl/worksheets/sheet1.xml").decode() if z else ""
check("10.03.2025" in s1 and "<v>39.2</v>" in s1 and "<v>53.2</v>" in s1, "the sheet: dates as text, amounts as numbers, a total")
r = A.get(B + T + "/vma.csv?year=2025")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")) if r.ok else []
check(rows and rows[0][0] == "Person" and rows[-1][7] == "275,40" and any(x[0] == "Bob Member" and x[6] == "Total" and x[7] == "81,20" for x in rows),
      f"the CSV with totals per person and overall {rows[-2:]}")
log = A.get(B + "/api/office/log?limit=10").json().get("log", [])
check(any(x["action"] == "export" and x["target"] == "travel" for x in log), "the export is in the office log")

# ---------------------------------------------------------------- rights
for p in ("/vma?year=2025", "/vma-rates?year=2025", "/vma.pdf?year=2025", "/vma.xlsx?year=2025", "/vma.csv?year=2025"):
    check(Bo.get(B + T + p).status_code == 403, f"a member gets 403: {p}")
j = Ca.get(B + T + "/vma?year=2025").json()
check(j["people"] == [] and j["total"] == "0.00", "another organisation sees none of the trips")
check(Ca.patch(B + f"{T}/{t1['id']}", json={"vma_days": []}).status_code == 404, "another organisation cannot change the days of a trip (404)")
# freelancer-matrix: office -- a person without an organisation: the personal office, its own admin
FID, Fr = freelancer(B, A)
r = Fr.post(B + T, json={"date_from": "2025-04-07", "date_to": "2025-04-08", "dest": "Prag", "overnight": True, "country": "CZ", "people": [{"id": FID}]})
check(r.status_code == 201 and r.json()["vma"]["amount"] == "42.00", "a trip with a per diem in the personal office (2 x 21) " + r.text[:200])
for p in ("/vma?year=2025", "/vma-rates?year=2025", "/vma.pdf?year=2025", "/vma.xlsx?year=2025", "/vma.csv?year=2025"):
    check(Fr.get(B + T + p).status_code == 200, f"the personal office gets 200: {p}")
j = Fr.get(B + T + "/vma?year=2025").json()
check([(g["label"], g["total"]) for g in j["people"]] == [("Frida", "42.00")], f"only the own trip {j['people']}")
check(A.get(B + T + f"/vma?year=2025&person=u{FID}").json()["people"] == [], "an organisation never sees the personal office's trips")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
