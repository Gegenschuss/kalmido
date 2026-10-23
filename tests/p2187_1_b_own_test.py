#!/usr/bin/env python3
"""2.187.1 API tests, part B (#2735, office rights: the level "own" usable), own container (start.sh). Invented people,
companies and figures only. Sam = template Staff, Bob = a second Staff member ("somebody else"), Alice = the admin.
 (2a) times to bill: without a client the own open hours per client (names only, no billing data of the client)
 (2b) trips / entertainment receipts the admin entered FOR the person (traveller / host) are listed, read only (403 on
      change / delete / a receipt); an entry of somebody else without the person stays 404
 (2c) the own reports (travel, per diem, entertainment, logbook) answer, only with the own entries
 (3)  logbook: odometer hints only between two own drives (somebody else's drive in between: none), the start value of a
      new drive from the own drives
 (4)  confirming an entertainment receipt on the level "own": only as its host (403 else)
 (f)  a person without an organisation: all of it as the admin of the personal office
usage: p2187_1_b_own_test.py <datadir>      (KMT_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
O = "/api/office"


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


def made(r, what):
    assert r.status_code == 201, (what, r.status_code, r.text[:300])
    return r.json()["id"]


def meal_body(host, **kw):
    b = {"date": TD, "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": host,
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}], "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}]}
    b.update(kw)
    return b


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ids, S = {}, {}
for u, n in (("sam", "Sam Staff"), ("bob", "Bob Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
    S[u] = sess(u)
for s in (A, *S.values()):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
Sa, Bo = S["sam"], S["bob"]
SAM, BOB = ids["sam"], ids["bob"]
TD = testclock.today().isoformat()
Y = TD[:4]
for u in ("sam", "bob"):
    r = A.put(B + f"{O}/rights/people/{ids[u]}", json={"groups": ["tpl:staff"]})
    assert r.ok, r.text

# ---------------------------------------------------------------- (2a) times to bill without a client choice
C1 = made(A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "org_id": ORG, "city": "Köln", "country": "DE"}), "client")
LID = A.post(B + "/api/lists", json={"name": "Projekt Hafen", "org_id": ORG, "time_tracking": True}).json()["id"]
A.patch(B + f"/api/lists/{LID}", json={"client_id": C1})
assert A.put(B + f"/api/lists/{LID}/members", json={"user_id": SAM, "role": "edit"}).ok
assert A.post(B + "/api/time/entries", json={"list_id": LID, "start": TD + "T08:00:00Z", "minutes": 120}).ok
r = Sa.post(B + "/api/time/entries", json={"list_id": LID, "start": TD + "T10:00:00Z", "minutes": 30})
check(r.ok, "(2a) setup: an own time entry " + r.text[:160])
P = {"from": TD, "to": TD}
r = Sa.get(B + O + "/time-open", params=P)
j = r.json() if r.ok else {}
cl = j.get("clients") or []
check(r.ok and j.get("open_seconds") == 1800, f"(2a) staff without a client: the own open hours {r.status_code} {r.text[:200]}")
check(len(cl) == 1 and cl[0]["id"] == C1 and cl[0]["name"] == "Beispielkunde AG" and cl[0]["open_seconds"] == 1800,
      f"(2a) staff: the own hours per client {cl}")
check(all(set(x) <= {"id", "name", "open_seconds", "billed_seconds", "unbillable_seconds"} for x in cl), f"(2a) the client by name only {cl}")
r = Sa.get(B + O + "/time-open", params={"client_id": C1, **P})
check(r.ok and r.json().get("open_seconds") == 1800 and "clients" not in r.json(), "(2a) with the client as before " + r.text[:160])
r = A.get(B + O + "/time-open", params=P)
check(r.ok and r.json().get("open_seconds") == 9000, "(2a) the admin without a client: all hours " + r.text[:160])
check(Sa.get(B + "/api/clients").status_code in (200, 403), "(2a) the client list stays as it is")

# ---------------------------------------------------------------- (2b) trips entered for the person
T_FOR = made(A.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Messe Beispiel", "country": "DE",
                                             "people": [{"id": SAM}]}), "trip for sam")
assert A.post(B + O + f"/trips/{T_FOR}/items", json={"date": TD, "category": "train", "amount": 50}).status_code == 201
T_ADM = made(A.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Kunde Beispiel", "country": "DE",
                                             "people": [{"id": ALICE}]}), "trip of alice")
assert A.post(B + O + f"/trips/{T_ADM}/items", json={"date": TD, "category": "train", "amount": 70}).status_code == 201
T_BOB = made(Bo.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Lager", "country": "DE"}), "trip of bob")
T_OWN = made(Sa.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Studio", "country": "DE",
                                              "people": [{"id": SAM}]}), "own trip")
check(Sa.post(B + O + f"/trips/{T_OWN}/items", json={"date": TD, "category": "taxi", "amount": 12}).status_code == 201, "(2b) a receipt on the own trip")
r = Sa.get(B + O + "/trips")
tl = {t["id"]: t for t in (r.json().get("trips", []) if r.ok else [])}
check(set(tl) == {T_FOR, T_OWN}, f"(2b) staff: the own trip and the one entered for them {sorted(tl)}")
check(tl.get(T_FOR, {}).get("own_ro") == 1 and tl.get(T_OWN, {}).get("own_ro") == 0, f"(2b) read only marked {[(k, v.get('own_ro')) for k, v in tl.items()]}")
check(r.ok and r.json().get("missing") == 2, f"(2b) the receipts not in DATEV of the own trips {r.json().get('missing') if r.ok else r.text[:100]}")
check(Sa.patch(B + O + f"/trips/{T_FOR}", json={"dest": "X"}).status_code == 403, "(2b) a trip entered for them: change 403")
check(Sa.delete(B + O + f"/trips/{T_FOR}").status_code == 403, "(2b) a trip entered for them: delete 403")
check(Sa.post(B + O + f"/trips/{T_FOR}/items", json={"date": TD, "category": "taxi", "amount": 5}).status_code == 403,
      "(2b) a trip entered for them: a receipt 403")
check(Sa.patch(B + O + f"/trips/{T_ADM}", json={"dest": "X"}).status_code == 404, "(2b) somebody else's trip 404")
check(Sa.patch(B + O + f"/trips/{T_BOB}", json={"dest": "X"}).status_code == 404, "(2b) a colleague's trip 404")
check(A.get(B + O + "/trips").json()["trips"][0].get("own_ro") is None, "(2b) the admin: no read-only mark")

# ---------------------------------------------------------------- (2b, 4) entertainment receipts with the person as host
M_FOR = made(A.post(B + O + "/meals", json=meal_body({"id": SAM})), "meal hosted by sam")
M_ADM = made(A.post(B + O + "/meals", json=meal_body({"id": ALICE})), "meal of alice")
M_OWN = made(Sa.post(B + O + "/meals", json=meal_body({"id": ALICE})), "sam's meal hosted by alice")
r = Sa.get(B + O + "/meals")
ml = {m["id"]: m for m in (r.json().get("meals", []) if r.ok else [])}
check(set(ml) == {M_FOR, M_OWN}, f"(2b) staff: the own receipt and the one with them as host {sorted(ml)}")
check(ml.get(M_FOR, {}).get("own_ro") == 1 and ml.get(M_FOR, {}).get("own_host") == 1 and ml.get(M_OWN, {}).get("own_ro") == 0,
      f"(2b) marks {[(k, v.get('own_ro'), v.get('own_host')) for k, v in ml.items()]}")
check(Sa.get(B + O + f"/meals/{M_FOR}").ok, "(2b) the receipt with them as host: read")
check(Sa.get(B + O + f"/meals/{M_FOR}/pdf").status_code == 200, "(2b) the receipt with them as host: PDF")
check(Sa.patch(B + O + f"/meals/{M_FOR}", json={"note": "x"}).status_code == 403, "(2b) the receipt with them as host: change 403")
check(Sa.delete(B + O + f"/meals/{M_FOR}").status_code == 403, "(2b) the receipt with them as host: delete 403")
check(Sa.get(B + O + f"/meals/{M_ADM}").status_code == 404, "(2b) somebody else's receipt 404")
# (4) confirming: only as the host
r = Sa.post(B + O + f"/meals/{M_OWN}/approve")
check(r.status_code == 403, f"(4) the own receipt with somebody else as host: confirm 403 {r.status_code} {r.text[:160]}")
check(Sa.post(B + O + f"/meals/{M_ADM}/approve").status_code == 404, "(4) somebody else's receipt: confirm 404")
r = Sa.post(B + O + f"/meals/{M_FOR}/approve")
check(r.ok and r.json().get("locked") and r.json().get("approved_by") == SAM, f"(4) the host confirms {r.status_code} {r.text[:160]}")
check(A.post(B + O + f"/meals/{M_OWN}/approve").ok, "(4) the admin still confirms any receipt")
assert A.post(B + O + f"/meals/{M_ADM}/approve").ok

# ---------------------------------------------------------------- (3) logbook: odometer hints within the own drives
VEH = made(A.post(B + O + "/vehicles", json={"name": "Van", "plate": "B-XX 1", "kind": "company", "odo_start": "1000"}), "vehicle")


def drive(s, a, b):  # all on one day (the year stays this year): the odometer orders them
    return made(s.post(B + O + "/drives", json={"vehicle_id": VEH, "day": TD, "dest": "Lager", "purpose": "Material",
                                                "odo_start": str(a), "odo_end": str(b), "kind": "business"}), f"drive {a}-{b}")


drive(A, 1000, 1030)
S1 = drive(Sa, 1030, 1040)
drive(Bo, 1040, 1100)
S2 = drive(Sa, 1120, 1130)  # 20 km after Bob's end: nothing about Bob's drive for Sam
S3 = drive(Sa, 1150, 1160)  # 20 km after the own previous drive: the hint stays
drive(Bo, 1160, 1300)
r = Sa.get(B + O + "/drives", params={"year": Y})
dl = {d["id"]: d for d in (r.json().get("drives", []) if r.ok else [])}
check(set(dl) == {S1, S2, S3}, f"(3) staff: the own drives {sorted(dl)}")
check(dl.get(S2, {}).get("warn") is None, f"(3) no hint against somebody else's drive {dl.get(S2, {}).get('warn')}")
check((dl.get(S3, {}).get("warn") or {}).get("kind") == "gap", f"(3) the hint between two own drives {dl.get(S3, {}).get('warn')}")
r = A.get(B + O + "/drives", params={"year": Y})
ad = {d["id"]: d for d in r.json().get("drives", [])}
check((ad.get(S2, {}).get("warn") or {}).get("kind") == "gap", f"(3) the admin sees every hint {ad.get(S2, {}).get('warn')}")
v = {x["id"]: x for x in Sa.get(B + O + "/vehicles").json().get("vehicles", [])}.get(VEH, {})
check(v.get("last_odo") not in ("1300", "1300.0") and str(v.get("last_odo", "")).startswith("1160"), f"(3) start value from the own drives {v.get('last_odo')}")
v = {x["id"]: x for x in A.get(B + O + "/vehicles").json().get("vehicles", [])}.get(VEH, {})
check(str(v.get("last_odo", "")).startswith("1300"), f"(3) the admin: the vehicle's last odometer {v.get('last_odo')}")

# ---------------------------------------------------------------- (2c) own reports
r = Sa.get(B + O + "/trips/report", params={"by": "month"})
check(r.ok and r.json().get("count") == 2 and r.json().get("total") == "62.00", f"(2c) the travel report: own trips only {r.status_code} {r.text[:200]}")
r = Sa.get(B + O + "/trips/report", params={"by": "month", "format": "csv"})
check(r.ok and "62,00" in r.text and "120,00" not in r.text, f"(2c) the travel report as CSV {r.status_code}")
r = A.get(B + O + "/trips/report", params={"by": "month"})
check(r.ok and r.json().get("total") == "132.00", f"(2c) the admin: every trip {r.text[:160]}")
r = Sa.get(B + O + "/trips/vma", params={"year": Y})
check(r.ok and [p["key"] for p in r.json().get("people", [])] in ([], [f"u{SAM}"]), f"(2c) per diem: only the own person {r.text[:200]}")
# 2.187.1 (#2735, review): an own trip without participants counts as the person's own per diem
T_NOP = made(Sa.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Werkstatt", "country": "DE"}), "own trip without people")
r = Sa.get(B + O + "/trips/vma", params={"year": Y})
pv = r.json().get("people", []) if r.ok else []
check([p["key"] for p in pv] == [f"u{SAM}"] and T_NOP in [t["id"] for t in pv[0]["trips"]], f"(2c) per diem: the own trip without people under the person {r.text[:200]}")
check(Sa.delete(B + O + f"/trips/{T_NOP}").status_code in (200, 204), "cleanup: the trip without people")
r = Sa.get(B + O + "/trips/vma", params={"year": Y, "person": f"u{ALICE}"})
check(r.ok and all(p["key"] == f"u{SAM}" for p in r.json().get("people", [])), "(2c) per diem: no other person by parameter")
check(Sa.get(B + O + "/trips/vma.csv", params={"year": Y}).status_code == 403, "(2c) the per diem file for the tax adviser keeps the special 403")
r = Sa.get(B + O + "/meals/report", params={"year": Y})
check(r.ok and sorted(m["id"] for m in r.json().get("meals", [])) == sorted([M_FOR, M_OWN]), f"(2c) the entertainment report: own only {r.text[:200]}")
r = Sa.get(B + O + "/meals/report", params={"year": Y, "format": "csv"})
check(r.ok and r.text.count("Trattoria Esempio") == 2, f"(2c) the entertainment report as CSV (not the admin's) {r.status_code}")
r = Sa.get(B + O + "/logbook/report", params={"year": Y})
vs = {x["id"]: x for x in (r.json().get("vehicles", []) if r.ok else [])}
check(r.ok and vs.get(VEH, {}).get("drives") == 3 and str(vs.get(VEH, {}).get("km_total")).startswith("30"),
      f"(2c) the logbook report: own drives only {r.status_code} {vs.get(VEH)}")
check(Sa.get(B + O + "/logbook.csv", params={"year": Y}).status_code == 403, "(2c) the logbook file keeps the special 403")
r = A.get(B + O + "/logbook/report", params={"year": Y})
check(r.ok and {x["id"]: x for x in r.json()["vehicles"]}[VEH]["drives"] == 6, "(2c) the admin: every drive")

# ---------------------------------------------------------------- (f) a person without an organisation (own admin)
FID, Fr = freelancer(B, A, "erin", features=FEAT)
FC = made(Fr.post(B + "/api/clients", json={"name": "Privatkunde GmbH", "city": "Bonn", "country": "DE"}), "freelancer client")
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes Projekt", "time_tracking": True}).json()["id"]
Fr.patch(B + f"/api/lists/{FL}", json={"client_id": FC})
assert Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": TD + "T09:00:00Z", "minutes": 60}).ok
r = Fr.get(B + O + "/time-open", params=P)
check(r.ok and r.json().get("open_seconds") == 3600 and [c["id"] for c in r.json().get("clients", [])] == [FC], f"freelancer: own times without a client {r.text[:200]}")
FT = made(Fr.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Dreh", "country": "DE"}), "freelancer trip")
check(Fr.patch(B + O + f"/trips/{FT}", json={"dest": "Dreh 2"}).ok and Fr.get(B + O + "/trips/report").ok, "freelancer: trips and the report as before")
FM = made(Fr.post(B + O + "/meals", json=meal_body({"id": FID})), "freelancer meal")
check(Fr.post(B + O + f"/meals/{FM}/approve").ok, "freelancer: confirms the own receipt (own admin)")
check(Fr.get(B + O + "/logbook/report").ok and Fr.get(B + O + "/meals/report").ok, "freelancer: the reports")
check(FT not in [t["id"] for t in Sa.get(B + O + "/trips").json()["trips"]] and Sa.patch(B + O + f"/trips/{FT}", json={"dest": "X"}).status_code == 404,
      "tenant: the freelancer's trip is not Alpha's")

print(f"\np2187_1_b_own: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
