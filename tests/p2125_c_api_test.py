#!/usr/bin/env python3
"""2.125.0 part C (#2121 #2122; own container, start.sh):
- GET /api/time/export.xlsx: a real .xlsx (zip with workbook, styles, one sheet); the same rows, columns, sums and visibility
  as /api/time/export.csv (an editor sees only their own entries, the list admin all of them, a stranger none, no login 401);
  numbers are numbers, start / end date-time cells, a sum row; a note that looks like a formula is defused
- GET /api/workload/export.xlsx: people x weeks (planned / capacity hours), only what the person sees (a stranger's tasks stay out),
  the module switch and the login are asked like /api/workload
- a person without an organisation exports both (freelancer-matrix: time, tasks)
- GET /manifest.json: the "Start / stop timer" shortcut only with the module "time" on for the signed-in person
usage: p2125_c_api_test.py <datadir>      (a fresh container; P2125C_NOSTART=1: the container runs already)"""
import csv
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(u=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": pw}).ok, u
    return s


def col_of(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx(resp):
    """-> (rows, kinds): rows[r][c] = value (float / str), kinds[r][c] = style id; the .xlsx must be a valid zip."""
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    for n in ("[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml"):
        z.getinfo(n)
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows, styles = [], []
    for row in root.iterfind(".//m:row", NS):
        vals, sts = {}, {}
        for c in row.iterfind("m:c", NS):
            i = col_of(c.get("r"))
            sts[i] = int(c.get("s") or 0)
            if c.get("t") == "inlineStr":
                vals[i] = "".join(t.text or "" for t in c.iterfind(".//m:t", NS))
            else:
                vals[i] = float(c.find("m:v", NS).text)
        w = max(vals) + 1 if vals else 0
        rows.append([vals.get(i) for i in range(w)])
        styles.append([sts.get(i) for i in range(w)])
    return rows, styles


if not os.environ.get("P2125C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,time,progress,workload"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
BOB = [u["id"] for u in A.get(B + "/api/users").json()["users"] if u["username"] == "bob"][0]
ALICE = 1
T0 = testclock.today()

# ================================================================== a shared list, entries of alice and bob
L = A.post(B + "/api/lists", json={"name": "Project X", "kind": "project", "time_tracking": True}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok, "bob is an editor of the list")
t1 = A.post(B + "/api/tasks", json={"title": "Design", "list_id": L, "assignee_id": ALICE, "duration": 90, "due": T0.isoformat()}).json()["id"]
t2 = A.post(B + "/api/tasks", json={"title": "Build", "list_id": L, "assignee_id": BOB, "duration": 30, "due": T0.isoformat()}).json()["id"]
now = datetime.now().astimezone()
# 2.144.0: a fixed midday start - "now - 3 h" crossed the Berlin midnight in the night CI run and an entry over midnight is one
# row per day since 2.125.0 B (#2120), so the row counts below were one too high
from datetime import time as _time, timezone as _tz
st0 = datetime.combine(T0 - timedelta(days=1), _time(10, 0), tzinfo=_tz.utc)
for s, tid, note, mins in ((A, t1, "alice one", 90), (A, t1, "=SUM(1+1)", 30), (Bo, t2, "bob one", 45)):
    r = s.post(B + "/api/time/entries", json={"task_id": tid, "start": st0.isoformat(), "minutes": mins, "note": note})
    assert r.ok, r.text
frm = (T0 - timedelta(days=1)).isoformat()
Q = {"scope": "all", "from": frm}

# ================================================================== times: XLSX = CSV
for who, s, n_entries in (("admin", A, 3), ("editor", Bo, 1)):
    rc = s.get(B + "/api/time/export.csv", params=Q)
    rx = s.get(B + "/api/time/export.xlsx", params=Q)
    check(rx.status_code == 200 and "spreadsheetml.sheet" in rx.headers["Content-Type"] and ".xlsx" in rx.headers["Content-Disposition"],
          f"{who}: xlsx answer {rx.status_code} {rx.headers.get('Content-Type')}")
    crows = list(csv.reader(io.StringIO(rc.text.lstrip("﻿")), delimiter=","))
    rows, styles = xlsx(rx)
    check(len(crows) == n_entries + 1 and len(rows) == n_entries + 2, f"{who}: {n_entries} entries + header (+ sum row) {len(crows)} {len(rows)}")
    check(rows[0] == crows[0], f"{who}: the same header as the CSV {rows[0]} {crows[0]}")
    for cr, xr in zip(crows[1:], rows[1:-1]):
        check(xr[0] == cr[0] and xr[1] == cr[1] and xr[2] == cr[2] and xr[6] == cr[6] and xr[9] == cr[9], f"{who}: row equals the CSV row {xr} {cr}")
        check(isinstance(xr[5], float) and abs(xr[5] - float(cr[5])) < 0.006 and abs(xr[7] - float(cr[7])) < 0.006, f"{who}: hours are numbers")
        check(isinstance(xr[3], float) and styles[rows.index(xr)][3] == 2, f"{who}: the start is a date-time cell")
    tot = rows[-1]
    check(tot[0] == "Total" and abs(tot[5] - sum(float(r[5]) for r in crows[1:])) < 0.02 and styles[-1][5] == 4, f"{who}: sum row {tot}")
rows, _ = xlsx(A.get(B + "/api/time/export.xlsx", params=Q))
notes = [r[9] for r in rows[1:-1] if len(r) > 9]
check("=SUM(1+1)" not in notes and "'=SUM(1+1)" in notes, f"a formula-like note is defused {notes}")
rows, _ = xlsx(Bo.get(B + "/api/time/export.xlsx", params=Q))
check([r[9] for r in rows[1:-1]] == ["bob one"], "the editor sees only the own entry")
rows, _ = xlsx(Ca.get(B + "/api/time/export.xlsx", params=Q))
check(len(rows) == 2 and rows[1][0] == "Total", "a stranger gets an empty sheet (header + sum)")
r = requests.get(B + "/api/time/export.xlsx", headers=H)
check(r.status_code in (401, 403), f"no login: {r.status_code}")
check(A.get(B + "/api/time/export.xlsx", params={"from": "2000-01-01", "to": "2000-01-02"}).ok, "an empty range is fine")

# 2.125.0 R (#2122, #2120): the person's time zone and an entry over midnight -- the XLSX has exactly the CSV's rows
check(Ca.patch(B + "/api/settings", json={"tz": "America/New_York"}).ok, "carol works in New York")
NY = ZoneInfo("America/New_York")
DNY = (datetime.now(NY) - timedelta(days=3)).date()
CLN = Ca.post(B + "/api/lists", json={"name": "Night shift", "time_tracking": True}).json()["id"]
check(Ca.patch(B + f"/api/lists/{CLN}", json={"rate": 90}).ok, "carol's hourly rate")
st = datetime(DNY.year, DNY.month, DNY.day, 23, 30, tzinfo=NY)
check(Ca.post(B + "/api/time/entries", json={"list_id": CLN, "start": st.isoformat(), "minutes": 60, "note": "overnight"}).ok, "an entry over midnight")
QN = {"from": DNY.isoformat(), "to": (DNY + timedelta(days=1)).isoformat()}
crows = [r for r in csv.reader(io.StringIO(Ca.get(B + "/api/time/export.csv", params=QN).text.lstrip("\ufeff"))) if r][1:]
rows, _ = xlsx(Ca.get(B + "/api/time/export.xlsx", params=QN))
xrows = rows[1:-1]


def xdt(v):
    return (datetime(1899, 12, 30) + timedelta(days=v) + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M")


check(len(crows) == 2 and len(xrows) == 2, f"two rows (one per day) in both {len(crows)} {len(xrows)}")
check([r[3] for r in crows] == [f"{DNY} 23:30", f"{DNY + timedelta(days=1)} 00:00"], f"CSV: New York times {crows}")
for cr, xr in zip(crows, xrows):
    check(xdt(xr[3]) == cr[3] and xdt(xr[4]) == cr[4], f"XLSX start / end = CSV {xdt(xr[3])} {xdt(xr[4])} {cr[3:5]}")
    check(xr[6] == cr[6] and abs(xr[5] - float(cr[5])) < 0.006, f"XLSX duration = CSV {xr[5:7]} {cr[5:7]}")
    check(cr[8] != "" and abs(xr[8] - float(cr[8])) < 0.006, f"XLSX amount = CSV {xr[8]} {cr[8]}")
check(abs(rows[-1][8] - 90.0) < 0.006, f"the sum row holds the whole amount {rows[-1]}")
Ca.patch(B + "/api/settings", json={"tz": ""})

# ================================================================== workload
rw = A.get(B + "/api/workload/export.xlsx", params={"weeks": 2})
check(rw.status_code == 200 and "spreadsheetml.sheet" in rw.headers["Content-Type"], f"workload xlsx {rw.status_code}")
rows, styles = xlsx(rw)
check(rows[0][0] == "Person" and len(rows[0]) == 1 + 2 * 2 + 1, f"workload header {rows[0]}")
a_row = next(r for r in rows if r[0] == "Alice")
check(any(isinstance(v, float) and abs(v - 1.5) < 0.01 for v in a_row[1:]), f"alice has 1.5 h planned {a_row}")
check(rows[-1][0] == "Total" and styles[-1][1] == 4, "workload: a sum row")


def same_as_view(s, who):
    """The sheet holds exactly the people and hours of /api/workload (what the person may see, no more)."""
    j = s.get(B + "/api/workload", params={"weeks": 2}).json()
    x, _ = xlsx(s.get(B + "/api/workload/export.xlsx", params={"weeks": 2}))
    want = [[p["display_name"]] + [v for w in p["weeks"] for v in (round(w["minutes"] / 60, 2), round(w["capacity_h"], 2))]
            + [round(p["nodate"]["minutes"] / 60, 2)] for p in j["people"]]
    check(x[1:-1] == want, f"{who}: the workload sheet equals the view {x[1:-1]} {want}")


same_as_view(A, "admin")
same_as_view(Bo, "editor")
same_as_view(Ca, "stranger")
rc_, _ = xlsx(Ca.get(B + "/api/workload/export.xlsx", params={"weeks": 2}))
check(all(v == 0.0 for r in rc_[1:-1] for v in r[1::2]), "a stranger sees no planned hours of the list")
check(A.get(B + "/api/workload/export.xlsx", params={"weeks": "x"}).status_code == 400, "a bad weeks value: 400")
check(requests.get(B + "/api/workload/export.xlsx", headers=H).status_code in (401, 403), "workload: no login")
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,time,progress"})
check(A.get(B + "/api/workload/export.xlsx").status_code == 409, "workload module off: 409 like the view")
A.patch(B + "/api/settings", json={"features": FEAT})

# ================================================================== a person without an organisation
# freelancer-matrix: time, tasks
FID, Fr = freelancer(B, A)
lid = Fr.post(B + "/api/lists", json={"name": "Own work", "time_tracking": True}).json()["id"]
r = Fr.post(B + "/api/time/entries", json={"list_id": lid, "start": st0.isoformat(), "minutes": 20, "note": "solo"})
check(r.ok, "freelancer: an own entry " + r.text[:200])
rows, _ = xlsx(Fr.get(B + "/api/time/export.xlsx", params=Q))
check([r[9] for r in rows[1:-1]] == ["solo"] and rows[-1][0] == "Total", f"freelancer: own entry in the xlsx {rows}")
rows, _ = xlsx(Fr.get(B + "/api/workload/export.xlsx"))
check(rows[0][0] == "Person" and rows[-1][0] == "Total", f"freelancer: workload xlsx {rows[:2]}")
same_as_view(Fr, "freelancer")

# ================================================================== the manifest shortcut
def timer_shortcut(s):
    m = s.get(B + "/manifest.json").json()
    return [x for x in m["shortcuts"] if "action=timer" in x["url"]]

sc = timer_shortcut(A)
check(len(sc) == 1 and sc[0]["url"] == "/?action=timer" and len(sc[0]["icons"]) == 2, f"timer shortcut with the module on {sc}")
for ic in sc[0]["icons"] if sc else []:
    check(requests.get(B + ic["src"]).status_code == 200, f"the icon {ic['src']} exists")
check(len(A.get(B + "/manifest.json").json()["shortcuts"]) == 6, "5 old shortcuts + the timer")
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,progress"})
check(timer_shortcut(A) == [] and len(A.get(B + "/manifest.json").json()["shortcuts"]) == 5, "module off: the five old shortcuts only")
check(timer_shortcut(requests.Session()) == [], "signed out: no timer shortcut")
A.patch(B + "/api/settings", json={"features": FEAT})

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
