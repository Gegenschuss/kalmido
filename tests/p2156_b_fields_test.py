#!/usr/bin/env python3
"""2.156.0 B API tests (list fields), own container (start.sh). Invented names and amounts only.
 - #2069 field types multiselect (option ids joined by ",", a list accepted, option order, a removed option leaves the values,
   search by an option name), currency (ISO code, default EUR, number values), rating (max 3-10, "1".."max", 0 clears),
   task (only a task the person may see; the title reaches only those who may see it: /api/fields/task-refs, CSV export),
   rules cannot set multiselect / task fields, key figures over a currency field, list templates keep the options
 - #2070 formula fields with the functions of tables: WENN/IF, SUMME/SUM, RUNDEN/ROUND, MIN, MAX, comparisons, ";" or ",";
   currency / rating as numbers; errors when saved (unknown function, ranges, brackets) = 400 with a clear message, never 500;
   a failed calculation = "#div0" (empty while nothing is entered); the old syntax keeps working
 - a person without an organisation (freelancer-matrix: lists): the same in the own private list; an organisation's task
   cannot be linked and its title is not answered
usage: p2156_b_fields_test.py <datadir>      (a fresh container; P2156B_NOSTART=1 = the server already runs)"""
import csv
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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


def rows(r):
    t = r.content.decode("utf-8").lstrip("﻿")
    first = t.split("\r\n", 1)[0]
    return list(csv.reader(io.StringIO(t), delimiter=";" if first.count(";") > first.count(",") else ","))


if not os.environ.get("P2156B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "fields"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
for u in ("bob",):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,fields"}).ok

L = A.post(B + "/api/lists", json={"name": "Purchases", "kind": "project", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"}).ok
P = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]  # only Alice sees it


def field(s, lid, name, typ, **kw):
    return s.post(B + f"/api/lists/{lid}/fields", json={"name": name, "type": typ, **kw})


def mk(s, title, lid, fields=None):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **({"fields": fields} if fields else {})})
    assert r.ok, r.text
    return r.json()


def setf(s, tid, fid, v):
    return s.patch(B + f"/api/tasks/{tid}", json={"fields": {str(fid): v}})


# ================================================================== #2069: field definitions
r = field(A, L, "Colours", "multiselect", options={"options": [{"name": "Red"}, {"name": "Green"}, {"name": "Blue"}]})
MS = r.json()
check(r.ok and MS["type"] == "multiselect" and len(MS["options"]["options"]) == 3, f"#2069: a multiselect field {r.status_code} {r.text[:200]}")
RED, GREEN, BLUE = (o["id"] for o in MS["options"]["options"])
check(field(A, L, "Empty", "multiselect", options={"options": []}).status_code == 400, "#2069: a multiselect needs an option")
r = field(A, L, "Price", "currency", options={"currency": "usd"})
CU = r.json()
check(r.ok and CU["options"].get("currency") == "USD", f"#2069: a currency field keeps its code {r.text[:200]}")
r = field(A, L, "Cost", "currency", options={"currency": "€€"})
check(r.ok and r.json()["options"].get("currency") == "EUR", f"#2069: an unknown currency = EUR {r.text[:200]}")
r = field(A, L, "Stars", "rating", options={"max": 12})
RT = r.json()
check(r.ok and RT["options"].get("max") == 10, f"#2069: a rating has at most 10 stars {r.text[:200]}")
r = field(A, L, "Score", "rating")
check(r.ok and r.json()["options"].get("max") == 5, f"#2069: a rating has 5 stars by default {r.text[:200]}")
r = field(A, L, "Depends on", "task")
TK = r.json()
check(r.ok and TK["type"] == "task", f"#2069: a task field {r.text[:200]}")
check(field(A, L, "Nope", "matrix").status_code == 400, "#2069: an unknown type is still refused")

# ================================================================== #2069: values
T1 = mk(A, "Laptop", L)
T2 = mk(A, "Dock", L)
S1 = mk(A, "Secret plan", P)
r = setf(Bo, T1["id"], MS["id"], [GREEN, RED])
check(r.ok and r.json()["fields"].get(str(MS["id"])) == f"{RED},{GREEN}", f"#2069: multiselect stored in the order of the options {r.text[:200]}")
r = setf(Bo, T2["id"], MS["id"], f"{BLUE}")
check(r.ok and r.json()["fields"].get(str(MS["id"])) == BLUE, f"#2069: multiselect as text {r.text[:200]}")
check(setf(Bo, T2["id"], MS["id"], ["nope"]).status_code == 400, "#2069: an unknown option = 400")
check(setf(Bo, T2["id"], MS["id"], {"a": 1}).status_code == 400, "#2069: an object = 400")
r = setf(Bo, T2["id"], MS["id"], [])
check(r.ok and str(MS["id"]) not in r.json()["fields"], "#2069: an empty list clears it")
r = setf(Bo, T1["id"], CU["id"], "199,5")
check(r.ok and r.json()["fields"].get(str(CU["id"])) == "199.5", f"#2069: currency stored as a number {r.text[:200]}")
check(setf(Bo, T1["id"], CU["id"], "a lot").status_code == 400, "#2069: currency needs a number")
r = setf(Bo, T1["id"], RT["id"], "3")
check(r.ok and r.json()["fields"].get(str(RT["id"])) == "3", f"#2069: rating 3 {r.text[:200]}")
for bad in ("11", "-1", "x", "2.5"):
    check(setf(Bo, T2["id"], RT["id"], bad).status_code == 400, f"#2069: rating {bad!r} = 400")
setf(Bo, T2["id"], RT["id"], "4")
r = setf(Bo, T2["id"], RT["id"], "0")
check(r.ok and str(RT["id"]) not in r.json()["fields"], "#2069: rating 0 clears it")
r = setf(Bo, T1["id"], TK["id"], str(T2["id"]))
check(r.ok and r.json()["fields"].get(str(TK["id"])) == str(T2["id"]), f"#2069: a task link {r.text[:200]}")
check(setf(Bo, T2["id"], TK["id"], str(S1["id"])).status_code == 400, "#2069: Bob cannot link a task he cannot see")
check(setf(Bo, T2["id"], TK["id"], "999999").status_code == 400, "#2069: a task that does not exist = 400")
r = setf(A, T2["id"], TK["id"], f"#{S1['id']}")
check(r.ok and r.json()["fields"].get(str(TK["id"])) == str(S1["id"]), f"#2069: Alice links her private task {r.text[:200]}")

# the linked task's title only for those who may see it
r = Bo.get(B + f"/api/fields/task-refs?ids={S1['id']},{T2['id']}")
got = {x["id"]: x["title"] for x in r.json().get("tasks", [])} if r.ok else None
check(got == {T2["id"]: "Dock"}, f"#2069: task-refs answers Bob only what he may see {r.status_code} {r.text[:200]}")
r = A.get(B + f"/api/fields/task-refs?ids={S1['id']}")
check(r.ok and [x["title"] for x in r.json()["tasks"]] == ["Secret plan"], f"#2069: … Alice sees her title {r.text[:200]}")
check(A.get(B + "/api/fields/task-refs?ids=x").status_code == 400, "#2069: task-refs with a bad id = 400")
check("Secret plan" not in Bo.get(B + "/api/state").text, "#2069: Bob's state has no title of the hidden task")
check("Secret plan" not in Bo.get(B + f"/api/tasks/{T2['id']}").text, "#2069: … nor the task that links it")
hdr, *body = rows(Bo.get(B + f"/api/lists/{L}/export.csv"))
col = hdr.index("Depends on") if "Depends on" in hdr else -1
byt = {x[0]: x for x in body}
check(col > 0 and byt["Dock"][col] == "" and byt["Laptop"][col] == "Dock", f"#2069: Bob's export shows only the visible title {hdr} {body}")
hdr, *body = rows(A.get(B + f"/api/lists/{L}/export.csv"))
byt = {x[0]: x for x in body}
ci, cm, cc = hdr.index("Depends on"), hdr.index("Colours"), hdr.index("Price")
check(byt["Dock"][ci] == "Secret plan" and byt["Laptop"][cm] == "Red, Green" and byt["Laptop"][cc] == "199.5",
      f"#2069: Alice's export: titles, option names, numbers {hdr} {body}")

# search by an option name, removing an option
hits = [h["task"]["id"] for h in Bo.get(B + "/api/search", params={"q": "Green"}).json().get("hits", [])]
check(T1["id"] in hits, f"#2069: search finds a multiselect option {hits}")
opts = [o for o in MS["options"]["options"] if o["id"] != RED]
r = A.patch(B + f"/api/fields/{MS['id']}", json={"options": {"options": opts}})
check(r.ok, f"#2069: an option removed {r.text[:200]}")
check(Bo.get(B + f"/api/tasks/{T1['id']}").json()["fields"].get(str(MS["id"])) == GREEN, "#2069: the removed option leaves the value")

# key figures, templates
r = A.patch(B + f"/api/lists/{L}", json={"kpis": [{"title": "Spent", "agg": "sum", "field": CU["id"]}]})
k = A.get(B + f"/api/lists/{L}/kpis").json().get("data", [{}])[0] if r.ok else {}
check(r.ok and k.get("value") == 199.5 and k.get("unit") == "USD", f"#2069: a key figure over a currency field {r.text[:200]} {k}")
tp = A.post(B + "/api/templates", json={"kind": "list", "list_id": L, "name": "Purchases template"})
ap = A.post(B + f"/api/templates/{tp.json().get('id')}/apply", json={"name": "Purchases 2"}) if tp.ok else tp
L2 = (ap.json().get("list_id") or ap.json().get("id")) if ap.ok else None
f2 = {f["name"]: f for f in A.get(B + "/api/state").json()["fields"] if f["list_id"] == L2}
check(f2.get("Colours", {}).get("type") == "multiselect" and len(f2["Colours"]["options"]["options"]) == 2
      and f2.get("Price", {}).get("options", {}).get("currency") == "USD" and f2.get("Stars", {}).get("options", {}).get("max") == 10
      and f2.get("Depends on", {}).get("type") == "task", f"#2069: a list template keeps the new types {tp.status_code} {ap.status_code} {f2}")

# ================================================================== #2070: formulas with the functions of tables
r = field(A, L, "Net", "formula", formula="WENN({Price} > 100; RUNDEN({Price} * 0,9; 2); {Price})")
FX = r.json()
check(r.ok and FX["options"]["expr"] == f"WENN({{#{CU['id']}}} > 100; RUNDEN({{#{CU['id']}}} * 0,9; 2); {{#{CU['id']}}})"
      and FX["options"]["formula"] == "WENN({Price} > 100; RUNDEN({Price} * 0,9; 2); {Price})", f"#2070: WENN / RUNDEN stored with ids {r.text[:300]}")
FS = field(A, L, "Total", "formula", formula="SUM(Price, Stars) + MAX(1, 2) - MIN(5; 4)").json()
FD = field(A, L, "Per star", "formula", formula="{Price} / {Stars}").json()
FC = field(A, L, "Big", "formula", formula="IF(Price >= 150, 1, 0) + (Stars = 3)").json()
check(all(x.get("id") for x in (FS, FD, FC)), f"#2070: SUM / MAX / MIN / IF / comparisons {FS} {FD} {FC}")
for bad, want in [("pow(2; 3)", "pow"), ("HEUTE()", "HEUTE"), ("SUMME(A1:B2)", "“:”"), ("WENN(1; 2", "character"), ("{Colours} + 1", "Colours"),
                  ("{Depends on} * 2", "Depends on"), ("2 +", "ends too early"), ("round(1, 9)", "digits"), ("-" * 300 + "1", "")]:
    r = field(A, L, "Bad", "formula", formula=bad)
    check(r.status_code == 400 and want in r.json().get("error", ""), f"#2070: {bad[:20]!r} refused clearly {r.status_code} {r.text[:200]}")
T3 = mk(Bo, "Cable", L, {str(CU["id"]): "50"})
T4 = mk(Bo, "Nothing yet", L)
tt = {t["id"]: t["fields"] for t in Bo.get(B + "/api/state").json()["tasks"]}
f1, f3, f4 = tt[T1["id"]], tt[T3["id"]], tt[T4["id"]]
fx, fs, fd, fc = (str(x["id"]) for x in (FX, FS, FD, FC))
check(f1.get(fx) == "179.55" and f1.get(fs) == "200.5" and f1.get(fd) == "66.5" and f1.get(fc) == "2", f"#2070: values of the first task {f1}")
check(f3.get(fx) == "50" and f3.get(fd) == "#div0" and f3.get(fc) == "0", f"#2070: division by 0 = #div0 {f3}")
check(fd not in f4 and f4.get(fx) == "0", f"#2070: nothing entered yet = empty, no error {f4}")
r = setf(Bo, T1["id"], fx, "5")
check(r.status_code == 400 and "calculated" in r.json().get("error", ""), "#2070: a formula cannot be written")
r = A.patch(B + f"/api/fields/{FX['id']}", json={"formula": "{Net} + 1"})
check(r.status_code == 400 and "itself" in r.json().get("error", ""), "#2070: a formula cannot use itself")
r = A.patch(B + f"/api/fields/{FS['id']}", json={"formula": "WENN({Net} > 0; {Net}; 0)"})
check(r.ok, f"#2070: a formula may read another one {r.text[:200]}")
r = A.patch(B + f"/api/fields/{FX['id']}", json={"formula": "{Total} * 2"})
check(r.status_code == 400 and "circular" in r.json().get("error", ""), f"#2070: circular reference refused {r.text[:200]}")
r = A.patch(B + f"/api/fields/{CU['id']}", json={"name": "Price net"})
fsd = {f["id"]: f for f in A.get(B + "/api/state").json()["fields"]}
check(fsd[FX["id"]]["options"]["formula"] == "WENN({Price net} > 100; RUNDEN({Price net} * 0,9; 2); {Price net})", f"#2070: renaming follows {fsd[FX['id']]['options']}")
r = field(A, L, "Old style", "formula", formula="round({Price net} / 3, 1) + {Stars} * 2")
check(r.ok and r.json()["options"]["formula"] == "round({Price net} / 3, 1) + {Stars} * 2", f"#2070: the old syntax still works {r.text[:200]}")
check(mk(A, "Probe", L, {str(CU["id"]): "30", str(RT["id"]): "2"})["fields"].get(str(r.json()["id"])) == "14", "#2070: … and computes")

# rules (after the formulas: the rating rule fires on new tasks)
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "ms", "trigger": {"kind": "created"}, "action": {"kind": "field", "field_id": MS["id"], "value": GREEN}})
check(r.status_code == 400, f"#2069: a rule cannot set a multiselect {r.status_code}")
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "tk", "trigger": {"kind": "created"}, "action": {"kind": "field", "field_id": TK["id"], "value": str(T2["id"])}})
check(r.status_code == 400, f"#2069: … nor a task link {r.status_code}")
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "rt", "trigger": {"kind": "created"}, "action": {"kind": "field", "field_id": RT["id"], "value": "5"}})
check(r.status_code == 201, f"#2069: a rule sets a rating {r.status_code} {r.text[:200]}")

# ================================================================== a person without an organisation (freelancer-matrix: lists)
FID, Fl = freelancer(B, A)
PL = Fl.post(B + "/api/lists", json={"name": "Own work", "org_id": None}).json()["id"]
fm = field(Fl, PL, "Tags", "multiselect", options={"options": [{"name": "Quick"}, {"name": "Paid"}]}).json()
fcu = field(Fl, PL, "Fee", "currency", options={"currency": "CHF"}).json()
frt = field(Fl, PL, "Mood", "rating", options={"max": 3}).json()
ftk = field(Fl, PL, "Next", "task").json()
ffx = field(Fl, PL, "With tax", "formula", formula="RUNDEN(WENN({Mood} >= 2; {Fee} * 1,081; {Fee}); 2)").json()
check(all(x.get("id") for x in (fm, fcu, frt, ftk, ffx)), f"freelancer: the new field types in the own list {fm} {ffx}")
O1 = mk(Fl, "Website", PL)
O2 = mk(Fl, "Logo", PL, {str(fm["id"]): [o["id"] for o in fm["options"]["options"]], str(fcu["id"]): "100", str(frt["id"]): "3",
                         str(ftk["id"]): str(O1["id"])})
check(O2["fields"].get(str(ffx["id"])) == "108.1" and O2["fields"].get(str(ftk["id"])) == str(O1["id"]), f"freelancer: values + formula {O2['fields']}")
check(setf(Fl, O1["id"], ftk["id"], str(T1["id"])).status_code == 400, "freelancer: an organisation's task cannot be linked")
r = Fl.get(B + f"/api/fields/task-refs?ids={O1['id']},{T1['id']}")
check(r.ok and [x["id"] for x in r.json()["tasks"]] == [O1["id"]], f"freelancer: task-refs only the own task {r.text[:200]}")
check(Bo.get(B + f"/api/fields/task-refs?ids={O1['id']}").json().get("tasks") == [], "the organisation does not see the freelancer's title")
check(field(Fl, L, "Intruder", "rating").status_code in (403, 404), "freelancer: no field in an organisation's list")
# 2.156.0 review: ROUND of a value beyond the decimal precision is an error in the field, the list still loads
fbig = field(Fl, PL, "Huge", "formula", formula="RUNDEN({Fee} * {Fee} * {Fee}; 2)").json()
O3 = mk(Fl, "Big fee", PL, {str(fcu["id"]): "100000000000"})
check(O3.get("fields", {}).get(str(fbig.get("id"))) in ("#type", None) and Fl.get(B + "/api/state").ok,
      f"#2070 review: a huge ROUND does not break the list {O3.get('fields')}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
