#!/usr/bin/env python3
"""2.138.3 API tests, part B (#2371): a truth-value criterion (WAHR / FALSCH, TRUE / FALSE, "WAHR" as text) in SUMMEWENN /
ZÄHLENWENN (SUMIF / COUNTIF) hits the ticks of a checkbox column (stored 1 / 0, 1 / 0 in formulas), own container (start.sh).
Invented names only. freelancer-matrix: sheets
 - SUMMEWENN(C;WAHR;B), SUMIF(C;TRUE;B), ZÄHLENWENN(C;"WAHR"), ZÄHLENWENN(C;FALSCH) (an empty box is no FALSCH, as in
   other spreadsheets), "<>WAHR"
 - other figures stay: WAHR does not hit 5 / 10 / 3 / 7, a 1 counts for the criterion 1 as before, real truth values
   (=1>0) still hit WAHR
 - the same in the own table of a person without an organisation (private space)
usage: p21383_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "sheets,collab,comments"
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


def put(s, sid, cells):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def table(s, space, who):
    """A table: text, numbers, formulas and a checkbox column; ticks in rows 1 and 3, row 2 unticked ("0"), row 4 empty."""
    r = s.post(B + "/api/sheets", json={"title": "Ticks", "space": space})
    check(r.status_code == 201, f"{who}: a table " + r.text[:200])
    sid = r.json()["id"]
    have = len(r.json().get("columns") or [])
    for _ in range(max(0, 3 - have)):
        s.post(B + f"/api/sheets/{sid}/columns", json={"title": "", "kind": "text"})
    r = s.post(B + f"/api/sheets/{sid}/columns", json={"title": "Done", "kind": "checkbox"})
    check(r.ok, f"{who}: a checkbox column " + r.text[:200])
    cols = s.get(B + f"/api/sheets/{sid}").json()["columns"]
    cb = next((c for c in cols if c["kind"] == "checkbox"), None)
    check(cb is not None, f"{who}: a checkbox column " + json.dumps(cols)[:300])
    L = cb["letter"] if cb else "C"
    nb = next(c["letter"] for c in cols if c["kind"] != "checkbox" and c["letter"] not in ("A", L))
    fx = next(c["letter"] for c in cols if c["kind"] != "checkbox" and c["letter"] not in ("A", L, nb))
    r = put(s, sid, [{"cell": a, "raw": v} for a, v in (
        ("A1", "Tent"), ("A2", "Stove"), ("A3", "Lamp"), ("A4", "Rope"),
        (f"{nb}1", "5"), (f"{nb}2", "10"), (f"{nb}3", "3"), (f"{nb}4", "7"),
        (f"{L}1", "1"), (f"{L}2", "0"), (f"{L}3", "1"))])
    check(r.ok, f"{who}: the values " + r.text[:200])
    return sid, L, nb, fx


def run(s, space, who):
    sid, c, b, f = table(s, space, who)
    rc, rb = f"{c}1:{c}4", f"{b}1:{b}4"
    F = {  # formula -> expected value
        f"=SUMMEWENN({rc};WAHR;{rb})": 8,
        f"=SUMIF({rc};TRUE;{rb})": 8,
        f'=ZÄHLENWENN({rc};"WAHR")': 2,
        f'=COUNTIF({rc};"true")': 2,
        f"=ZÄHLENWENN({rc};FALSCH)": 1,
        f"=SUMMEWENN({rc};FALSCH;{rb})": 10,
        f'=ZÄHLENWENN({rc};"<>WAHR")': 2,
        # unchanged: other figures are no truth values, a 1 is still a 1
        f"=ZÄHLENWENN({rb};WAHR)": 0,
        f"=ZÄHLENWENN({rc};1)": 2,
        f"=SUMME({rc})": 2,
    }
    cells = [{"cell": f"{f}{i}", "raw": x} for i, x in enumerate(F, 1)]
    cells.append({"cell": f"{f}{len(F) + 1}", "raw": "=1>0"})
    cells.append({"cell": f"{f}{len(F) + 2}", "raw": f"=ZÄHLENWENN({f}{len(F) + 1};WAHR)"})
    r = put(s, sid, cells)
    check(r.ok, f"{who}: the formulas " + r.text[:300])
    d = s.get(B + f"/api/sheets/{sid}").json()
    for i, (x, want) in enumerate(F.items(), 1):
        got = cell(d, f"{f}{i}")
        check(got.get("value") == want and not got.get("error"), f"{who}: {x} = {want!r} " + json.dumps(got)[:200])
    got = cell(d, f"{f}{len(F) + 2}")
    check(got.get("value") == 1, f"{who}: a real truth value still hits WAHR " + json.dumps(got)[:200])
    # ticking row 2 changes the sum at once
    r = put(s, sid, [{"cell": f"{c}2", "raw": "1"}])
    d = s.get(B + f"/api/sheets/{sid}").json()
    check(r.ok and cell(d, f"{f}1").get("value") == 18, f"{who}: a new tick counts in SUMMEWENN " + json.dumps(cell(d, f"{f}1"))[:200])
    return sid


if not os.environ.get("P21383B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
run(A, f"org:{ORG}", "org")

FID, Fr = freelancer(B, A)  # freelancer-matrix: sheets (the own table in the private space)
FS = run(Fr, "private", "freelancer")
check(A.get(B + f"/api/sheets/{FS}").status_code in (403, 404), "someone else: the freelancer's table 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
