#!/usr/bin/env python3
"""2.95.0 B (#1932) API tests: the import of a per diem spreadsheet into the travel expenses (own container, org encryption
on). The spreadsheet is built here (zipfile, invented people / places / figures): one sheet = one person, a row = a trip,
cell comments = note + the split by country.
 - preview: the person of a sheet (the title "... Arbeitsliste <name> - <year>" -> a person of the office, else a free
   name from the sheet's name), Excel date numbers and DD.MM.YYYY, times as a fraction of a day, the occasion (research /
   acquisition vs. a job with the project), the comment -> note (the author's prefix and the per diem block taken out) and
   the countries of the days, the recalculated per diem vs. the spreadsheet (new / warn / error), the sheet's sum; a broken
   file and a too large file 400; nothing stored
 - import: the kept rows become trips (encrypted at rest, the per diem as calculated), a second preview marks them dup,
   a bad row / a person outside the office 400; the undo (POST /trips/delete) removes them
 - rights (tenant-matrix: office): a member 403, another organisation reaches nothing (its delete removes nothing); a person
   without an organisation (freelancer-matrix: office) imports into the own personal office, nobody else sees it
usage: p295_b_api_test.py <datadir>      (P295B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from p295_b_xlsx import SAMPLE, xlsx

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


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


RAW = xlsx(SAMPLE)


def up(s, raw, name="reisen.xlsx"):
    return s.post(B + T + "/import/preview", files={"file": (name, raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def kept(prev, person_of=None):
    """The trips of the preview's kept rows, as the client sends them (person_of: sheet index -> people entry)."""
    out = []
    for si, sh in enumerate(prev["sheets"]):
        p = (person_of or {}).get(si) or ({"id": sh["person"]["id"]} if sh["person"].get("id") else {"name": sh["person"]["name"]})
        for r in sh["rows"]:
            if r["sel"] and r["status"] != "error":
                out.append({k: r[k] for k in ("date_from", "date_to", "dest", "overnight", "purpose", "project", "note", "country", "place", "t_start", "t_end", "vma_days")}
                           | {"people": [p]})
    return out


if os.environ.get("P295B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erik")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
T = "/api/office/trips"

# ---------------------------------------------------------------- preview
r = up(A, RAW)
check(r.ok, "#1932: the preview " + r.text[:300])
P = r.json()
check(len(P["sheets"]) == 2 and P["sheets"][0]["person"].get("id") == ALICE and P["sheets"][1]["person"] == {"name": "Tom Beispiel"},
      f"#1932: a sheet = a person (title -> the office's person, else the sheet's name as a free name) {[s['person'] for s in P.get('sheets', [])]}")
rows = {x["row"]: x for x in P["sheets"][0]["rows"]}
check([rows[n]["status"] for n in (4, 5, 6, 7, 8)] == ["new", "warn", "new", "new", "error"], f"#1932: the statuses {[(x['row'], x['status'], x['reasons']) for x in rows.values()]}")
check(rows[4]["date_from"] == "2025-02-26" and rows[4]["date_to"] == "2025-02-27" and rows[4]["overnight"] == 1 and rows[4]["purpose"] == "job"
      and rows[4]["project"] == "Dreh Beispiel" and rows[4]["amount"] == "28.00" and rows[4]["excel"] == "28.00" and rows[4]["country"] == "",
      f"#1932: Excel date numbers, a job with its project, Germany 2 x 14 {rows[4]}")
check(rows[5]["purpose"] == "acquisition" and rows[5]["project"] == "" and rows[5]["country"] == "NL" and rows[5]["amount"] is None and rows[5]["excel"] is None
      and rows[5]["note"] == "Nur ein Beleg. Zeiten bitte ergänzen." and rows[5]["sel"] and rows[5]["reasons"],
      f"#1932: one day without times: no amount, a hint, the country from the place's brackets, the comment as note {rows[5]}")
check(rows[6]["t_start"] == "06:00" and rows[6]["t_end"] == "18:00" and rows[6]["amount"] == "14.00" and rows[6]["purpose"] == "acquisition",
      f"#1932: times as a fraction of a day, more than 8 hours = 14 {rows[6]}")
check(rows[7]["amount"] == "131.00" and rows[7]["country"] == "CZ" and rows[7]["vma_days"] == [{"date": "2025-04-17", "country": "DE"}]
      and rows[7]["note"] == "Hinweis frei.", f"#1932: the comment's block -> the countries of the days, the rest -> note (author prefix gone) {rows[7]}")
check(rows[8]["reasons"] and not rows[8]["sel"], "#1932: an unreadable date is an error, not selected")
check(P["sheets"][0]["sum_excel"] == "173.00" and P["sheets"][0]["sum_calc"] == "173.00", f"#1932: the sheet's sum = the spreadsheet's {P['sheets'][0]['sum_excel']} {P['sheets'][0]['sum_calc']}")
t2 = P["sheets"][1]["rows"][0]
check(t2["date_from"] == "2025-06-12" and t2["date_to"] == "2025-06-14" and t2["amount"] == "128.00" and t2["status"] == "new" and t2["purpose"] == "job"
      and t2["country"] == "CH" and t2["vma_days"] == [{"date": "2025-06-13", "country": "IT"}], f"#1932: DD.MM.YYYY, two countries (partial days at both ends) {t2}")
check(P["counts"] == {"new": 4, "warn": 1, "dup": 0, "error": 1} and {p["id"] for p in P["people"]} >= {ALICE}, f"#1932: the counts {P['counts']}")
check(A.get(B + T + "?year=2025").json()["trips"] == [], "#1932: the preview stores nothing")
check(up(A, b"not a spreadsheet").status_code == 400, "#1932: a broken file is 400")
check(up(A, b"PK" + b"0" * (2 * 1024 * 1024)).status_code == 400, "#1932: a file over 2 MB is 400")
check(up(A, xlsx([("Leer", [["Name", "Betrag"]], {})])).status_code == 400, "#1932: a file without the header row is 400")
check(A.post(B + T + "/import/preview").status_code == 400, "#1932: no file is 400")

# ---------------------------------------------------------------- import + undo
TRIPS = kept(P)
check(len(TRIPS) == 5, f"#1932: five kept rows {len(TRIPS)}")
check(A.post(B + T + "/import", json={"trips": [dict(TRIPS[0], date_from="x")]}).status_code == 400, "#1932: a bad row is refused")
check(A.post(B + T + "/import", json={"trips": [dict(TRIPS[0], people=[{"id": CAROL}])]}).status_code == 400, "#1932: a person outside the office is refused")
check(A.post(B + T + "/import", json={"trips": []}).status_code == 400, "#1932: nothing to import is 400")
r = A.post(B + T + "/import", json={"trips": TRIPS})
check(r.status_code == 201 and r.json()["created"] == 5, "#1932: the import " + r.text[:200])
IDS = r.json()["ids"]
got = {t["id"]: t for t in A.get(B + T + "?year=2025").json()["trips"]}
check(set(IDS) <= set(got), "#1932: the imported trips are in the list")
cz = next(t for t in got.values() if t["dest"] == "Beispielort (Tschechien)")
check(cz["vma"]["amount"] == "131.00" and cz["note"] == "Hinweis frei." and cz["people"] == [{"id": ALICE, "name": "Alice Admin"}] and cz["purpose"] == "acquisition",
      f"#1932: a trip as imported, its per diem calculated {cz.get('vma', {}).get('amount')} {cz.get('people')}")
ch = next(t for t in got.values() if t["dest"].startswith("Beispielberg"))
check(ch["people"] == [{"name": "Tom Beispiel"}] and ch["vma"]["amount"] == "128.00", f"#1932: the second sheet's free name {ch.get('people')}")
enc = sql("SELECT people, note FROM office_trips WHERE id=?", (cz["id"],))
check(enc and all(str(x).startswith("kenc1:") for x in enc[0]), "#1932: participants and note encrypted at rest")
P2 = up(A, RAW).json()
check(P2["counts"] == {"new": 0, "warn": 0, "dup": 5, "error": 1} and not any(x["sel"] for s in P2["sheets"] for x in s["rows"]),
      f"#1932: the second preview marks them as already there, not selected {P2['counts']}")
# rights (tenant-matrix: office): a member 403, another organisation reaches nothing
check(all(x.status_code == 403 for x in (up(Bo, RAW), Bo.post(B + T + "/import", json={"trips": TRIPS}), Bo.post(B + T + "/delete", json={"ids": IDS}))),
      "#1932: a member gets 403")
r = Ca.post(B + T + "/delete", json={"ids": IDS})
check(r.ok and r.json()["deleted"] == 0 and len(A.get(B + T + "?year=2025").json()["trips"]) == 5, "#1932: another organisation deletes nothing of it")
check(Ca.get(B + T + "?year=2025").json()["trips"] == [], "#1932: another organisation sees none of it")
check(A.post(B + T + "/delete", json={"ids": ["x"]}).status_code == 400, "#1932: the undo checks its ids")
r = A.post(B + T + "/delete", json={"ids": IDS})
check(r.ok and r.json()["deleted"] == 5 and len(r.json()["trips"]) == 5 and A.get(B + T + "?year=2025").json()["trips"] == [], "#1932: the undo removes the imported trips " + r.text[:160])
check(up(A, RAW).json()["counts"]["new"] == 4, "#1932: after the undo the rows are new again")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
r = up(Do, RAW)
check(r.ok and r.json()["sheets"][0]["person"] == {"name": "Alice Admin"}, "#1932: the personal office: a name of nobody there stays a free name " + r.text[:200])
DORA = Do.get(B + "/api/state").json()["me"]["id"]
r = Do.post(B + T + "/import", json={"trips": kept(r.json(), {0: {"id": DORA}})})
check(r.status_code == 201 and r.json()["created"] == 5, "#1932: the personal office imports " + r.text[:200])
DIDS = r.json()["ids"]
check(len(Do.get(B + T + "?year=2025").json()["trips"]) == 5 and Er.get(B + T + "?year=2025").json()["trips"] == []
      and A.get(B + T + "?year=2025").json()["trips"] == [], "#1932: the trips of a personal office stay private")
check(Er.post(B + T + "/delete", json={"ids": DIDS}).json()["deleted"] == 0 and len(Do.get(B + T + "?year=2025").json()["trips"]) == 5,
      "#1932: another person deletes nothing of a personal office")
check(Do.post(B + T + "/delete", json={"ids": DIDS}).json()["deleted"] == 5, "#1932: the owner's undo")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
