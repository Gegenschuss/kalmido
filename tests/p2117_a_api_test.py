#!/usr/bin/env python3
"""2.117.0 API tests, part A (#2287 #2291 #2292): travel expenses, own container (start.sh, org encryption on). Invented
companies, people and figures only.
 - #2292 own purposes: GET / POST / PATCH / DELETE /api/office/trips/purposes (same name = the one there, the built-in keys
   and empty names refused, a removed one comes back with the same id = the undo), a trip keeps its text when the purpose
   is renamed or removed, GET /api/office/trips lists them, the evaluation by=purpose, by=project keeps own purposes apart
   from acquisition, the per diem report names the own purpose, the import adopts unknown purposes, a move between offices
   takes them along
 - #2291 ?person=u<id>|n:<name> on the evaluation (only that person's trips, each receipt with the person's share; CSV
   named after the person), an invalid key = 400
 - #2287 a trip posted again with the same data (the client's "Duplicate") comes without receipts
 - rights: a member gets 403, another organisation sees none of the purposes and gets 404 on them; a person without an
   organisation (the personal office, its own admin) has an own list -- freelancer-matrix: office -- tenant-matrix: office
usage: p2117_a_api_test.py <datadir>      (P2117A_NOSTART=1: use a running server)"""
import base64
import csv
import io
import os
import subprocess
import sys
import time

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2117A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
T = "/api/office/trips"
P = T + "/purposes"


def trip(s, **kw):
    r = s.post(B + T, json=kw)
    check(r.status_code == 201, f"trip {kw.get('dest')}: {r.status_code} {r.text[:200]}")
    return r.json()


def trips(s, year="2025"):
    return {t["id"]: t for t in s.get(B + T + f"?year={year}").json()["trips"]}


# ---------------------------------------------------------------- #2292 own purposes
check(A.get(B + P).json() == {"purposes": []}, "no own purposes at first")
r = A.post(B + P, json={"name": "  Messe  "})
check(r.status_code == 201 and r.json()["name"] == "Messe", "a new own purpose (trimmed) " + r.text[:200])
MESSE = r.json().get("id")
r = A.post(B + P, json={"name": "messe"})
check(r.status_code == 200 and r.json()["id"] == MESSE, "the same name again = the one there " + r.text[:200])
for bad in ("job", "Acquisition", "", "   ", "x" * 121, 5):
    check(A.post(B + P, json={"name": bad}).status_code == 400, f"refused: {bad!r}")
check(A.post(B + P, json={"name": "Workshop"}).status_code == 201, "a second own purpose")
check([p["name"] for p in A.get(B + T).json()["purposes"]] == ["Messe", "Workshop"], "the trips list carries the own purposes by name")
t1 = trip(A, date_from="2025-05-05", dest="Hannover", purpose="Messe", people=[{"id": ALICE}, {"id": BOB}],
          items=[{"date": "2025-05-05", "category": "train", "amount": 100}])
check(t1["purpose"] == "Messe", "a trip with an own purpose keeps it as text")
t2 = trip(A, date_from="2025-05-12", dest="Berlin", purpose="acquisition", people=[{"id": ALICE}],
          items=[{"date": "2025-05-12", "category": "taxi", "amount": 50}])
t3 = trip(A, date_from="2025-05-20", dest="Leipzig", purpose="Kongress", people=[{"name": "Externe Person"}], project="Film eins",
          items=[{"date": "2025-05-20", "category": "hotel", "amount": 30}])
check(t3["purpose"] == "Kongress", "a purpose not in the list is kept as text (an old text of a trip stays editable)")
check(A.post(B + T, json={"date_from": "2025-05-21", "purpose": "y" * 130}).status_code == 400, "an over-long purpose is refused")
check(A.patch(B + f"{T}/{t1['id']}", json={"purpose": "job"}).ok and A.patch(B + f"{T}/{t1['id']}", json={"purpose": "Messe"}).json()["purpose"] == "Messe",
      "a trip switches between a built-in and an own purpose")
# rename / remove: the trips keep their text
r = A.patch(B + f"{P}/{MESSE}", json={"name": "Fachmesse"})
check(r.ok and r.json()["name"] == "Fachmesse", "renamed " + r.text[:200])
check(A.patch(B + f"{P}/{MESSE}", json={"name": "workshop"}).status_code == 400, "renaming onto another purpose's name is refused")
check(trips(A)[t1["id"]]["purpose"] == "Messe", "the trip keeps its text after the rename")
r = A.delete(B + f"{P}/{MESSE}")
check(r.ok and r.json()["purpose"] == {"id": MESSE, "name": "Fachmesse"}, "removed " + r.text[:200])
check([p["name"] for p in A.get(B + P).json()["purposes"]] == ["Workshop"], "a removed purpose is no longer offered")
check(trips(A)[t1["id"]]["purpose"] == "Messe", "the trip keeps its text after the removal")
check(A.delete(B + f"{P}/{MESSE}").status_code == 404 and A.patch(B + f"{P}/{MESSE}", json={"name": "Neu"}).status_code == 404, "a removed purpose: 404")
r = A.post(B + P, json={"name": "Fachmesse"})
check(r.status_code == 201 and r.json()["id"] == MESSE, "the undo posts the name again: the same purpose comes back " + r.text[:200])
# the evaluation by purpose; by project / client own purposes are not mixed with acquisition
rep = A.get(B + T + "/report?by=purpose&from=2025-01-01&to=2025-12-31").json()
got = {g["label"]: (g["key"], g["amount"]) for g in rep["rows"]}
check(got == {"Messe": ("Messe", "100.00"), "Acquisition / research": ("acquisition", "50.00"), "Kongress": ("Kongress", "30.00")},
      f"the evaluation by purpose {got}")
r = A.get(B + T + "/report?by=purpose&from=2025-01-01&to=2025-12-31&format=csv")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")) if r.ok else []
check(rows and rows[0][0] == "Purpose" and rows[-1][2] == "180,00", f"the CSV by purpose {rows[:1]} {rows[-1:]}")
rep = A.get(B + T + "/report?by=project&from=2025-01-01&to=2025-12-31").json()
got = {g["label"]: g["amount"] for g in rep["rows"]}
check(got == {"No project": "100.00", "Acquisition / research": "50.00", "Film eins": "30.00"}, f"by project: an own purpose is no acquisition {got}")
vr = A.get(B + T + "/vma?year=2025").json()
check(any(x["purpose"] == "Kongress · Film eins" for g in vr["people"] for x in g["trips"]), "the per diem report names the own purpose (+ project)")
# the import adopts an unknown purpose
r = A.post(B + T + "/import", json={"trips": [{"date_from": "2025-07-01", "dest": "Bonn", "purpose": "Recherche vor Ort", "people": [{"id": ALICE}]}]})
check(r.status_code == 201, "an import with an own purpose " + r.text[:200])
check("Recherche vor Ort" in [p["name"] for p in A.get(B + P).json()["purposes"]], "the import adds the unknown purpose to the own ones")
IMP = r.json().get("ids", [])
A.post(B + T + "/delete", json={"ids": IMP})

# ---------------------------------------------------------------- #2291 the person filter
q = "/report?by=month&from=2025-01-01&to=2025-12-31"
rep = A.get(B + T + q + f"&person=u{ALICE}").json()
check(rep["total"] == "100.00" and rep["count"] == 2, f"Alice: her share of the Hannover trip (50) + Berlin (50) {rep}")
rep = A.get(B + T + q + f"&person=u{BOB}").json()
check(rep["total"] == "50.00" and rep["count"] == 1, f"Bob: his share of the Hannover trip {rep}")
rep = A.get(B + T + q + "&person=n:externe%20person").json()
check(rep["total"] == "30.00", f"a free name {rep}")
rep = A.get(B + T + f"/report?by=person&from=2025-01-01&to=2025-12-31&person=u{BOB}").json()
check([(g["label"], g["amount"]) for g in rep["rows"]] == [("Bob Member", "50.00")], f"by person + filter: only that person {rep['rows']}")
rep = A.get(B + T + f"/report?by=purpose&from=2025-01-01&to=2025-12-31&person=u{ALICE}").json()
check({g["label"]: g["amount"] for g in rep["rows"]} == {"Messe": "50.00", "Acquisition / research": "50.00"}, f"by purpose + filter {rep['rows']}")
r = A.get(B + T + q + f"&person=u{BOB}&format=csv")
check(r.ok and f"u{BOB}" in r.headers.get("Content-Disposition", ""), "the CSV is named after the person " + r.headers.get("Content-Disposition", ""))
for bad in ("x", "u", "uabc", "n:", "u1" + "0" * 20):
    check(A.get(B + T + q + "&person=" + bad).status_code == 400, f"an invalid person key is refused: {bad}")
check(A.get(B + T + f"/vma.csv?year=2025&person=u{BOB}").ok, "the per diem export takes the person")

# ---------------------------------------------------------------- #2287 duplicate (the client posts the trip's data again)
src = trips(A)[t1["id"]]
keep = ("date_from", "date_to", "dest", "overnight", "people", "purpose", "client_id", "project", "km", "note", "country", "place", "t_start", "t_end", "vma_days", "vma_off")
d = trip(A, **{k: src[k] for k in keep})
check(d["dest"] == "Hannover" and d["purpose"] == "Messe" and d["items"] == [] and len(d["people"]) == 2, "the copy: same data, no receipts")
check(A.delete(B + f"{T}/{d['id']}").ok, "the undo of the copy deletes it")

# ---------------------------------------------------------------- rights
for m, u, kw in (("get", P, {}), ("post", P, {"json": {"name": "Bob"}}), ("patch", f"{P}/{MESSE}", {"json": {"name": "Bob"}}), ("delete", f"{P}/{MESSE}", {})):
    check(getattr(Bo, m)(B + u, **kw).status_code == 403, f"a member gets 403: {m} {u}")
check(Ca.get(B + P).json()["purposes"] == [], "another organisation sees none of the purposes")
check(Ca.patch(B + f"{P}/{MESSE}", json={"name": "Fremd"}).status_code == 404 and Ca.delete(B + f"{P}/{MESSE}").status_code == 404,
      "another organisation cannot rename or remove them (404)")
check(Ca.get(B + T + q + f"&person=u{ALICE}").json()["total"] == "0.00", "another organisation's evaluation never contains these trips")
# freelancer-matrix: office -- a person without an organisation: the personal office, its own list
FID, Fr = freelancer(B, A)
check(Fr.get(B + P).json() == {"purposes": []}, "the personal office starts without own purposes")
r = Fr.post(B + P, json={"name": "Dreh"})
check(r.status_code == 201, "the personal office adds an own purpose " + r.text[:200])
FP = r.json().get("id")
check(Fr.patch(B + f"{P}/{FP}", json={"name": "Drehtag"}).ok, "and renames it")
ft = trip(Fr, date_from="2025-08-01", dest="Potsdam", purpose="Drehtag", people=[{"id": FID}], items=[{"date": "2025-08-01", "category": "car", "amount": 20}])
check(Fr.get(B + T + f"/report?by=purpose&from=2025-01-01&to=2025-12-31&person=u{FID}").json()["rows"][0]["label"] == "Drehtag", "its evaluation by purpose + person")
check("Drehtag" not in [p["name"] for p in A.get(B + P).json()["purposes"]], "an organisation never sees the personal office's purposes")
check(A.delete(B + f"{P}/{FP}").status_code == 404, "an organisation cannot remove them")
check(Fr.delete(B + f"{P}/{FP}").ok and Fr.post(B + P, json={"name": "Drehtag"}).status_code == 201, "remove + undo in the personal office")

# ---------------------------------------------------------------- a move takes the own purposes along
A.patch(B + "/api/settings", json={"workspace": "private"})
check(A.post(B + P, json={"name": "Privat-Zweck"}).status_code == 201, "Alice's personal office has its own list")
pt = trip(A, date_from="2025-09-01", dest="Rostock", purpose="Privat-Zweck")
r = A.post(B + "/api/office/move-space", json={"what": "travel", "ids": [pt["id"]], "to": f"org:{ORG}"})
check(r.ok, "the trip moves into the organisation " + r.text[:200])
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check("Privat-Zweck" in [p["name"] for p in A.get(B + P).json()["purposes"]], "the organisation now offers the moved trip's purpose")
check(trips(A)[pt["id"]]["purpose"] == "Privat-Zweck", "the moved trip keeps its purpose")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
