#!/usr/bin/env python3
"""2.93.0 API tests, part B (#1928): the logbook in the office. Invented companies, people and figures only.
tenant-matrix: office
 - vehicles (private car used for business | company car, plate encrypted at rest, archived instead of deleted)
 - drives: km from the odometer, the end below the start / negative km / unknown kind 400, a client / vehicle / driver of
   another area refused; a gap to the previous odometer is a warning (not a block); start / destination / purpose encrypted
 - change log: create, change (only the changed values before), delete (deleted_at, the row stays), restore; encrypted
 - take over into the travel expenses: a trip without receipts, exactly once (the second call answers the same trip);
   private drives refused
 - year report per vehicle (km total / business / private / commute, share, allowance for private cars), the rate per km
   (validated), CSV (semicolon, decimal comma, formula injection made harmless, change log) and PDF
 - EUeR: the line "Mileage allowance" exactly once (company car, private drives, deleted drives and drives without
   vehicle do not count), its note
 - rights: a member 403, an agent 403, another organisation / another person 404; a person without organisation
   (personal office) uses all of it
usage: p293_b_api_test.py <datadir>      (P293B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import csv
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
V, DR, LB = O + "/vehicles", O + "/drives", O + "/logbook"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def enc(v):
    return str(v or "").startswith("kenc1:")


if os.environ.get("P293B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erik")
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
BOB = ids["bob"]
READS = (V, DR + "?year=2026", LB + "/report?year=2026", LB + ".csv?year=2026", LB + ".pdf?year=2026")

# ---------------------------------------------------------------- rights first (empty office)
for path in READS:
    check(Bo.get(B + path).status_code == 403, f"member: 403 on {path}")
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path}")
check(Bo.post(B + V, json={"name": "x"}).status_code == 403 and requests.post(B + V, headers=AGH, json={"name": "x"}).status_code == 403, "member / agent: no new vehicle")
check(Bo.put(B + LB + "/settings", json={"km_rate": "1"}).status_code == 403, "member: cannot set the rate")

# ---------------------------------------------------------------- vehicles
j = A.get(B + V).json()
check(j["vehicles"] == [] and j["km_rate"] == "0.30" and [k["key"] for k in j["kinds"]] == ["business", "private", "commute"] and any(c["id"] == CL for c in j["clients"])
      and not any(c["id"] == CL2 for c in j["clients"]) and {p["id"] for p in j["people"]} >= {ALICE, BOB} and "No tax advice" in j["note"], f"the start: no vehicle, rate 0.30, kinds {j}")
r = A.post(B + V, json={"name": "Kombi", "plate": "HH-AB 123", "kind": "private", "odo_start": "10000"})
check(r.status_code == 201 and r.json()["kind"] == "private" and r.json()["last_odo"] == "10000.0" and r.json()["plate"] == "HH-AB 123", "a private car " + r.text[:200])
VP = r.json()["id"]
VC = A.post(B + V, json={"name": "Transporter", "kind": "company"}).json()["id"]
check(A.post(B + V, json={"name": "x", "kind": "boat"}).status_code == 400 and A.post(B + V, json={"name": ""}).status_code == 400
      and A.post(B + V, json={"name": "x", "odo_start": -5}).status_code == 400, "vehicle: unknown kind / no name / negative odometer 400")
check(enc(sql("SELECT plate FROM office_vehicles WHERE id=?", (VP,))[0][0]), "the plate encrypted at rest")

# ---------------------------------------------------------------- drives
r = A.post(B + DR, json={"vehicle_id": VP, "day": "2026-03-02", "start_place": "Hamburg", "dest": "Lübeck", "purpose": "Dreh Imagefilm", "odo_start": "10000",
                          "odo_end": "10120", "kind": "business", "client_id": CL, "project": "Imagefilm"})
check(r.status_code == 201 and r.json()["km"] == "120.0" and r.json()["user_id"] == ALICE and r.json()["driver"] == "Alice Admin" and not r.json()["warn"],
      "a drive by odometer -> km, driver = me " + r.text[:240])
D1 = r.json()["id"]
check(A.get(B + V).json()["vehicles"][0]["last_odo"] == "10120.0", "the next drive starts at the last end")
r = A.post(B + DR, json={"vehicle_id": VP, "day": "2026-03-05", "start_place": "Hamburg", "dest": "Supermarkt", "odo_start": "10150", "odo_end": "10200", "kind": "private",
                          "user_id": BOB})
check(r.status_code == 201 and r.json()["warn"] == {"kind": "gap", "km": "30.0"} and r.json()["km"] == "50.0" and r.json()["driver"] == "Bob Member",
      "a gap of 30 km is a warning, the drive is saved; another driver of the area " + r.text[:240])
D2 = r.json()["id"]
D3 = A.post(B + DR, json={"vehicle_id": VP, "day": "2026-03-06", "dest": "Büro", "km": "40", "kind": "commute"}).json()["id"]
D4 = A.post(B + DR, json={"vehicle_id": VP, "day": "2026-03-07", "dest": "Kunde", "km": 50, "kind": "business"}).json()["id"]
DC = A.post(B + DR, json={"vehicle_id": VC, "day": "2026-03-08", "dest": "Lager", "km": 80, "kind": "business"}).json()["id"]
DN = A.post(B + DR, json={"day": "2026-03-09", "dest": "Ohne Fahrzeug", "km": 25, "kind": "business"}).json()["id"]
for bad, what in (({"odo_start": 500, "odo_end": 400}, "the end below the start"), ({"km": -1}, "negative km"), ({"kind": "flight"}, "unknown kind"),
                  ({"client_id": CL2}, "a client of another organisation"), ({"user_id": ids["carol"]}, "a driver outside the area"), ({"day": "2026-13-01"}, "a wrong day"),
                  ({"km": "x"}, "km not a number")):
    b = dict({"vehicle_id": VP, "day": "2026-03-10"}, **bad)
    check(A.post(B + DR, json=b).status_code == 400, f"drive refused: {what}")
VX = Ca.post(B + V, json={"name": "Fremdauto"}).json()["id"]
check(A.post(B + DR, json={"vehicle_id": VX, "day": "2026-03-10"}).status_code == 404, "a vehicle of another organisation: 404")
ds = A.get(B + DR + f"?vehicle_id={VP}&year=2026").json()["drives"]
check([d["id"] for d in ds] == [D4, D3, D2, D1], f"the drives of the vehicle and year, newest first {[d['id'] for d in ds]}")
check(A.get(B + DR + f"?vehicle_id={VP}&year=2025").json()["drives"] == [], "another year: none")
row = sql("SELECT start_place, dest, purpose FROM office_drives WHERE id=?", (D1,))[0]
check(all(enc(x) for x in row), f"start / destination / purpose encrypted at rest {row}")

# ---------------------------------------------------------------- change log
r = A.patch(B + f"{DR}/{D1}", json={"purpose": "Dreh Imagefilm Tag 1", "odo_end": "10130"})
check(r.ok and r.json()["km"] == "130.0" and r.json()["purpose"] == "Dreh Imagefilm Tag 1", "a change: km follows the odometer " + r.text[:200])
check(A.patch(B + f"{DR}/{D1}", json={"odo_end": "9000"}).status_code == 400, "a change: the end below the start 400")
log = A.get(B + f"{DR}/{D1}/log").json()["log"]
check([x["action"] for x in log] == ["create", "change"] and log[1]["prev"] == {"purpose": "Dreh Imagefilm", "km": "120.0", "odo_end": "10120.0"} and log[1]["by"] == "Alice Admin"
      and log[0]["prev"]["dest"] == "Lübeck", f"the log: created + the values before the change {log}")
check(all(enc(x[0]) for x in sql("SELECT prev FROM office_drive_log WHERE drive_id=?", (D1,))), "the log values encrypted at rest")
r = A.patch(B + f"{DR}/{D1}", json={"purpose": "Dreh Imagefilm Tag 1"})
check(r.ok and len(A.get(B + f"{DR}/{D1}/log").json()["log"]) == 2, "saving without a change writes no log entry")
check(A.delete(B + f"{DR}/{D3}").ok and D3 not in [d["id"] for d in A.get(B + DR + f"?vehicle_id={VP}&year=2026").json()["drives"]], "delete: the drive leaves the list")
check(sql("SELECT deleted_at FROM office_drives WHERE id=?", (D3,))[0][0], "delete: the row stays (deleted_at)")
check(A.patch(B + f"{DR}/{D3}", json={"km": 1}).status_code == 404 and A.delete(B + f"{DR}/{D3}").status_code == 404, "a deleted drive cannot be changed / deleted again")
r = A.post(B + f"{DR}/{D3}/restore")
check(r.ok and r.json()["km"] == "40.0" and A.post(B + f"{DR}/{D3}/restore").status_code == 404, "restore (the undo), once")
check([x["action"] for x in A.get(B + f"{DR}/{D3}/log").json()["log"]] == ["create", "delete", "restore"], "the log: delete + restore")
check(A.delete(B + f"{DR}/{D4}").ok, "a business drive deleted (must not count)")

# ---------------------------------------------------------------- take over into the travel expenses
r = A.post(B + f"{DR}/{D1}/trip")
t = r.json().get("trip") or {}
check(r.status_code == 201 and t.get("date_from") == "2026-03-02" and t.get("dest") == "Lübeck" and t.get("purpose") == "job" and t.get("client_id") == CL
      and t.get("project") == "Imagefilm" and t.get("km") == "130.00" and t.get("items") == [] and t.get("note") == "Dreh Imagefilm Tag 1\nStart: Hamburg",
      "take over: a trip with day, destination, client, project, km, no receipt; start + purpose in the note " + r.text[:300])
# 2.93.0 B (#1928 review): office_trips.dest is plain text -> only the destination there, start / purpose only in the encrypted note
tr_ = sql("SELECT dest, note FROM office_trips WHERE id=?", (t.get("id"),))[0]
check(tr_[0] == "Lübeck" and enc(tr_[1]), f"take over: no start / purpose in plain text {tr_}")
r2 = A.post(B + f"{DR}/{D1}/trip")
check(r2.status_code == 200 and r2.json()["existing"] and r2.json()["trip"]["id"] == t.get("id"), "take over again: the same trip " + r2.text[:120])
check(sum(1 for x in A.get(B + O + "/trips?year=2026").json()["trips"] if x["dest"] == "Lübeck") == 1, "exactly one trip")
check(next(d for d in A.get(B + DR + f"?vehicle_id={VP}&year=2026").json()["drives"] if d["id"] == D1)["trip_id"] == t.get("id"), "the drive knows its trip")
check(A.post(B + f"{DR}/{D2}/trip").status_code == 400, "a private drive is not taken over")

# ---------------------------------------------------------------- report, rate, EUeR
rep = A.get(B + LB + "/report?year=2026").json()
kp = next(v for v in rep["vehicles"] if v["id"] == VP)
kc = next(v for v in rep["vehicles"] if v["id"] == VC)
check((kp["km_total"], kp["km_business"], kp["km_private"], kp["km_commute"], kp["business_pct"], kp["allowance"]) == ("220.0", "130.0", "50.0", "40.0", 59, "39.00")
      and kc["km_business"] == "80.0" and kc["allowance"] == "0.00" and rep["allowance"] == "39.00" and rep["km_rate"] == "0.30",
      f"the year report: private car 130 business km x 0.30, the company car no allowance {rep}")
for bad in ("6", "-1", "x", "", True):
    check(A.put(B + LB + "/settings", json={"km_rate": bad}).status_code == 400, f"the rate validated: {bad!r}")
r = A.put(B + LB + "/settings", json={"km_rate": "0,35"})
check(r.ok and r.json()["km_rate"] == "0.35" and A.get(B + V).json()["km_rate"] == "0.35", "the rate with a decimal comma " + r.text)
A.put(B + O + "/settings", json={"tax_reserve_pct": 0})
check(A.get(B + V).json()["km_rate"] == "0.35", "the office settings keep the rate")
# 2.93.0 B (#1928 review): the rate per year (a new rate never changes earlier years), every change in the office log
r = A.put(B + LB + "/settings", json={"km_rate": "0.50", "year": 2025})
check(r.ok and r.json() == {"km_rate": "0.50", "year": 2025} and A.get(B + LB + "/report?year=2025").json()["km_rate"] == "0.50"
      and A.get(B + LB + "/report?year=2026").json()["km_rate"] == "0.35", "the rate of 2025 leaves 2026 alone " + r.text)
check(A.put(B + LB + "/settings", json={"km_rate": "1", "year": "20x6"}).status_code == 400, "the year validated")
kl = [x for x in A.get(B + O + "/log?limit=200").json()["log"] if x["target"] == "km_rate"]
check(sorted((x["detail"]["year"], x["detail"]["before"]["km_rate"], x["detail"]["after"]["km_rate"]) for x in kl) == [(2025, "0.35", "0.50"), (2026, "0.30", "0.35")],
      f"the office log: every rate with the year, before and after {[x['detail'] for x in kl]}")
e = A.get(B + "/api/office/books/euer?year=2026").json()
km = [x for x in e["expenses"] if x["key"] == "km"]
check(len(km) == 1 and km[0]["gross"] == "45.50" and km[0]["net"] == "45.50" and km[0]["vat"] == "0.00" and km[0]["count"] == 1 and km[0]["label"] == "Mileage allowance",
      f"EUeR: the mileage allowance once (130 km x 0.35; company car, private, deleted, without vehicle not) {e['expenses']}")
check(any("logbook" in n for n in e["notes"]) and e["expense_total"]["gross"] == "45.50", f"EUeR: the note, the total {e['notes']} {e['expense_total']}")
check(not any(x["key"] == "km" for x in A.get(B + "/api/office/books/euer?year=2025").json()["expenses"]), "EUeR 2025: no line")
rows = list(csv.reader(io.StringIO(A.get(B + "/api/office/books/euer.csv?year=2026").content.decode("utf-8-sig")), delimiter=";"))
check(any(r_[:4] == ["Mileage allowance", "45,50", "0,00", "45,50"] for r_ in rows), f"EUeR CSV: the line {rows}")

# ---------------------------------------------------------------- CSV / PDF
A.patch(B + f"{DR}/{D2}", json={"purpose": "=HYPERLINK(1)"})
r = A.patch(B + f"{V}/{VP}", json={"kind": "company"})  # 2.93.0 B (#1928 review): a kind change is logged, shown in the export
check(r.ok and A.get(B + LB + "/report?year=2026").json()["allowance"] == "0.00", "a company car has no allowance")
vl = [x for x in A.get(B + O + "/log?limit=200").json()["log"] if x["target"] == "vehicle" and x["detail"].get("vehicle_id") == VP]
check([x["action"] for x in vl] == ["update", "create"] and vl[0]["detail"]["before"] == {"kind": "private"} and vl[0]["detail"]["after"] == {"kind": "company"},
      f"the office log: the vehicle created and its kind changed {[x['detail'] for x in vl]}")
r = A.get(B + LB + ".csv?year=2026")
check(r.ok and r.headers.get("Content-Type", "").startswith("text/csv") and "logbook-2026.csv" in r.headers.get("Content-Disposition", ""), "CSV: download")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
check(rows[0][0] == "Date" and rows[0][-1] == "km" and rows[1][0] == "2026-03-02" and rows[1][10:13] == ["10000,0", "10130,0", "130,0"], f"CSV: oldest first with odometer {rows[:2]}")
check(any(r_[6] == "'=HYPERLINK(1)" for r_ in rows if len(r_) > 6), "CSV: formula injection made harmless")
check(sum(1 for r_ in rows if len(r_) > 2 and r_[0] == "2026-03-09") == 1, "CSV: the drive without vehicle is listed")
check(not any(r_[:1] == ["2026-03-07"] for r_ in rows), "CSV: the deleted drive is not among the drives")
i = next(n for n, r_ in enumerate(rows) if r_[:1] == ["Change log"])
lg = [r_ for r_ in rows[i + 2:] if len(r_) == 5]
check(any(r_[2] == "Deleted" for r_ in lg) and any(r_[2] == "Changed" and "Purpose" in r_[4] for r_ in lg), f"CSV: the change log with the deleted drive {rows[i:i + 4]}")
check(any(r_[2] == "Changed" and r_[4] == "Vehicle Kombi: Kind: Private car used for business -> Company car" for r_ in lg)
      and any(r_[4] == "Mileage allowance per business km 2026: 0,30 -> 0,35" for r_ in lg) and not any("2025" in r_[4] for r_ in lg)
      and any(r_[2] == "Created" and r_[4].startswith("Vehicle Kombi: Name: Kombi") for r_ in lg), f"CSV: the vehicle and rate changes of the year in the log {lg}")
check(A.patch(B + f"{V}/{VP}", json={"kind": "private"}).ok, "the kind back")
r = A.get(B + LB + ".pdf?year=2026")
check(r.ok and r.headers.get("Content-Type") == "application/pdf" and r.content[:5] == b"%PDF-", "PDF: content type + PDF bytes")
check(A.get(B + LB + f".pdf?year=2026&vehicle_id={VX}").status_code == 404, "PDF: a vehicle of another organisation 404")

# ---------------------------------------------------------------- vehicles: archive
r = A.patch(B + f"{V}/{VC}", json={"archived": 1})
check(r.ok and r.json()["archived"] == 1, "a vehicle archived (not deleted)")
check(A.patch(B + f"{V}/{VC}", json={"archived": 0}).json()["archived"] == 0, "and back (the undo)")

# ---------------------------------------------------------------- another organisation
check([v["id"] for v in Ca.get(B + V).json()["vehicles"]] == [VX], "another organisation: only its own vehicle")
check(Ca.get(B + DR + f"?vehicle_id={VP}&year=2026").status_code == 404 and Ca.get(B + DR + "?year=2026").json()["drives"] == [], "another organisation: no drives, a foreign vehicle 404")
for m, p in (("patch", f"{V}/{VP}"), ("patch", f"{DR}/{D1}"), ("delete", f"{DR}/{D1}"), ("post", f"{DR}/{D3}/restore"), ("get", f"{DR}/{D1}/log"), ("post", f"{DR}/{D1}/trip")):
    check(getattr(Ca, m)(B + p, json={} if m != "get" else None).status_code == 404, f"another organisation: {m} {p} 404")
check([v["id"] for v in Ca.get(B + LB + "/report?year=2026").json()["vehicles"]] == [VX] and not any(x["key"] == "km" for x in Ca.get(B + "/api/office/books/euer?year=2026").json()["expenses"]),
      "another organisation: only its own vehicle in the report, no EUeR line")
for path in (f"{DR}/{D1}/log", f"{V}"):
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path} (with data)")

# ---------------------------------------------------------------- personal office (person without organisation)
check(Do.get(B + O + "/settings").json().get("role") == "admin", "a person without organisation is admin of their own office")
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde"}).json()["id"]
r = Do.post(B + V, json={"name": "Eigenes Auto", "plate": "B-XY 42", "odo_start": 5000})
check(r.status_code == 201, "personal office: a vehicle " + r.text[:120])
PV = r.json()["id"]
r = Do.post(B + DR, json={"vehicle_id": PV, "day": "2026-04-01", "dest": "Kunde", "purpose": "Besprechung", "odo_start": 5000, "odo_end": 5100, "client_id": CLP})
check(r.status_code == 201 and r.json()["km"] == "100.0", "personal office: a drive " + r.text[:160])
PD = r.json()["id"]
check(enc(sql("SELECT dest FROM office_drives WHERE id=?", (PD,))[0][0]) and enc(sql("SELECT plate FROM office_vehicles WHERE id=?", (PV,))[0][0]), "personal office: encrypted at rest")
check(Do.patch(B + f"{DR}/{PD}", json={"dest": "Kunde Nord"}).ok and len(Do.get(B + f"{DR}/{PD}/log").json()["log"]) == 2, "personal office: change + log")
check(Do.post(B + f"{DR}/{PD}/trip").status_code == 201 and Do.post(B + f"{DR}/{PD}/trip").status_code == 200, "personal office: take over once")
check(Do.put(B + LB + "/settings", json={"km_rate": "0.30"}).ok and Do.get(B + LB + "/report?year=2026").json()["allowance"] == "30.00", "personal office: report + rate")
pk = [x for x in Do.get(B + "/api/office/books/euer?year=2026").json()["expenses"] if x["key"] == "km"]
check(len(pk) == 1 and pk[0]["gross"] == "30.00", f"personal office: the EUeR line {pk}")
check(Do.get(B + LB + ".csv?year=2026").ok and Do.get(B + LB + ".pdf?year=2026").content[:5] == b"%PDF-", "personal office: CSV + PDF")
check(Do.delete(B + f"{DR}/{PD}").ok and Do.post(B + f"{DR}/{PD}/restore").ok, "personal office: delete + restore")
check(Do.patch(B + f"{V}/{PV}", json={"archived": 1}).ok, "personal office: archive the vehicle")
check(Do.post(B + DR, json={"vehicle_id": VP, "day": "2026-04-02"}).status_code == 404 and Do.post(B + DR, json={"day": "2026-04-02", "client_id": CL}).status_code == 400,
      "personal office: no vehicle / client of an organisation")
check(Er.get(B + V).json()["vehicles"] == [] and Er.get(B + DR + "?year=2026").json()["drives"] == [], "another person sees nothing")
for m, p in (("patch", f"{V}/{PV}"), ("patch", f"{DR}/{PD}"), ("delete", f"{DR}/{PD}"), ("get", f"{DR}/{PD}/log"), ("post", f"{DR}/{PD}/trip")):
    check(getattr(Er, m)(B + p, json={} if m != "get" else None).status_code == 404, f"another person: {m} {p} 404")
check(A.get(B + f"{DR}/{PD}/log").status_code == 404 and not any(v["id"] == PV for v in A.get(B + V).json()["vehicles"]), "the organisation does not reach the personal office")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
