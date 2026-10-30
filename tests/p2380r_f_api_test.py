#!/usr/bin/env python3
# kalmido-suite:
"""2.380 F API tests, own container (start.sh). Invented data only.
 - #3411: every country pack offers the five points of Money (money.cashflow, money.kpi, money.travel, money.meals,
   money.subs) as switches under Settings > Functions, on by default; switched off, their routes answer 404 (the
   bookkeeping's trips/bill-docs stays open) and the settings stay reachable; switched on again the data is back unchanged;
   an unknown key in features_off = 400
 - #3435: the folded sections of the task panel are one account setting (detail_fold, known keys only, each once; "" = none)
 - #3438: a new agency project gets only the field "Budget h"; the one-shot at the start removes the empty "Client" /
   "Kunde" text fields of agency projects, a "Client" field with a value stays, so does one in a list without the type
P4: a person without an organisation (tests/freelancer_fixture.py) gets the same (freelancer-matrix: office)
usage: p2380r_f_api_test.py <datadir>"""
import os
import sys

import dbx as dbxm
import kt
from kt import B, check, sess
from freelancer_fixture import FEATURES, freelancer

kt.fresh(prefix="P2380RF")
A = kt.setup()
O = B + "/api/office"
MONEY = ("money.cashflow", "money.kpi", "money.travel", "money.meals", "money.subs")
# one route per switch (GET), the first path segment decides
ROUTE = {"money.cashflow": "/cashflow", "money.kpi": "/kpi", "money.travel": "/trips", "money.meals": "/meals", "money.subs": "/subs"}

ME = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ME}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"})


def money_switches(s, who):
    j = s.get(O + "/settings").json()
    check(all(j["features"].get(k) is True for k in MONEY), f"{who}: #3411 the five points of Money are on by default {j['features']}")
    check(all(j["pack"]["offers"].get(k) == "ready" for k in MONEY), f"{who}: #3411 the country pack offers them {j['pack']['offers']}")
    for k, p in ROUTE.items():
        r = s.get(O + p)
        check(r.status_code == 200, f"{who}: {p} answers while {k} is on ({r.status_code} {r.text[:120]})")
    t = s.post(O + "/trips", json={"date_from": "2026-03-12", "dest": "Client Example", "items": [{"date": "2026-03-12", "category": "taxi", "amount": 25}]})
    check(t.status_code in (200, 201), f"{who}: a trip {t.status_code} {t.text[:160]}")
    tid = t.json().get("id") or (t.json().get("trip") or {}).get("id")
    r = s.put(O + "/settings", json={"features_off": list(MONEY)})
    check(r.ok and all(r.json()["features"].get(k) is False for k in MONEY), f"{who}: #3411 all five switched off {r.text[:200]}")
    for k, p in ROUTE.items():
        r = s.get(O + p)
        check(r.status_code == 404, f"{who}: #3411 {p} = 404 while {k} is off ({r.status_code})")
    r = s.post(O + "/trips", json={"date_from": "2026-03-13", "dest": "Off"})
    check(r.status_code == 404, f"{who}: #3411 no new trip while travel is off ({r.status_code})")
    check(s.get(O + "/kpi?year=2026").status_code == 404 and s.get(O + "/subs.csv").status_code == 404,
          f"{who}: #3411 also with a query / the csv of the subscriptions")
    check(s.get(O + "/trips/bill-docs").status_code == 200, f"{who}: #3411 the bookkeeping's bill-docs stays open")
    check(s.get(O + "/settings").ok and s.get(O + "/docs").ok, f"{who}: #3411 settings and documents unaffected")
    r = s.put(O + "/settings", json={"features_off": ["money.nope"]})
    check(r.status_code == 400, f"{who}: #3411 an unknown function = 400 ({r.status_code})")
    r = s.put(O + "/settings", json={"features_off": []})
    check(r.ok and all(r.json()["features"].get(k) is True for k in MONEY), f"{who}: #3411 on again")
    trips = s.get(O + "/trips").json()
    rows = trips.get("trips") if isinstance(trips, dict) else trips
    check(any(x.get("id") == tid for x in rows or []), f"{who}: #3411 the trip is still there after off / on ({tid})")
    check(all(s.get(O + p).status_code == 200 for p in ROUTE.values()), f"{who}: #3411 every route answers again")


money_switches(A, "alice (organisation)")
FID, Fr = freelancer(B, A)
money_switches(Fr, "frida (no organisation)")



# ---------------------------------------------------------------- #3435 the folded sections (account setting)
def fold(s, who):
    st = lambda: s.get(B + "/api/state").json()["settings"].get("detail_fold")
    check(st() == "", f"{who}: #3435 nothing folded at first ({st()!r})")
    r = s.patch(B + "/api/settings", json={"detail_fold": "subtasks,tags,subtasks,comments"})
    check(r.ok and st() == "subtasks,tags,comments", f"{who}: #3435 the folded sections saved, each once ({r.status_code} {st()!r})")
    check(s.patch(B + "/api/settings", json={"detail_fold": "subtasks,nope"}).status_code == 400 and st() == "subtasks,tags,comments",
          f"{who}: #3435 an unknown section = 400, nothing stored")
    check(s.patch(B + "/api/settings", json={"detail_fold": "x" * 300}).status_code == 400, f"{who}: #3435 too long = 400")
    check(s.patch(B + "/api/settings", json={"detail_fold": ""}).ok and st() == "", f"{who}: #3435 \"\" = everything open")


fold(A, "alice")
fold(Fr, "frida (no organisation)")


# ---------------------------------------------------------------- #3438 the agency type's "Client" field
def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        out = c.execute(sql, args).fetchall()
        c.commit()
        return [tuple(r) for r in out]
    finally:
        c.close()


def fields(s, lid):
    return [(f["name"], f["type"]) for f in s.get(B + "/api/state").json()["fields"] if f["list_id"] == lid]


for s, who in ((A, "alice"), (Fr, "frida (no organisation)")):
    lid = s.post(B + "/api/lists", json={"name": f"Agency {who[:5]}", "ptype": "agency"}).json()["id"]
    check(fields(s, lid) == [("Budget h", "number")], f"{who}: #3438 a new agency project has only Budget h {fields(s, lid)}")
# the state of before: agency projects with "Client" (empty / with a value) and "Kunde" (empty), a plain list with an empty "Client"
TS = "2026-10-01T00:00:00Z"
L_EMPTY = A.post(B + "/api/lists", json={"name": "Old agency", "ptype": "agency"}).json()["id"]
L_VAL = A.post(B + "/api/lists", json={"name": "Old agency with client", "ptype": "agency"}).json()["id"]
L_DE = Fr.post(B + "/api/lists", json={"name": "Alte Agentur", "ptype": "agency"}).json()["id"]
L_PLAIN = A.post(B + "/api/lists", json={"name": "Plain list"}).json()["id"]
ids = {}
for lid, name in ((L_EMPTY, "Client"), (L_VAL, "Client"), (L_DE, "Kunde"), (L_PLAIN, "Client")):
    ids[lid] = dbw("INSERT INTO list_fields(list_id, name, type, created_at) VALUES(?,?,?,?) RETURNING id", (lid, name, "text", TS))[0][0]
T_EMPTY = A.post(B + "/api/tasks", json={"title": "Edit", "list_id": L_EMPTY}).json()["id"]
dbw("INSERT INTO task_field_values(task_id, field_id, value) VALUES(?,?,?)", (T_EMPTY, ids[L_EMPTY], ""))  # an empty value counts as none
T_VAL = A.post(B + "/api/tasks", json={"title": "Grade", "list_id": L_VAL}).json()["id"]
dbw("INSERT INTO task_field_values(task_id, field_id, value) VALUES(?,?,?)", (T_VAL, ids[L_VAL], "Example Ltd"))
dbw("DELETE FROM settings WHERE key='migr_agcl2380'")
if kt.fresh(keep=True, prefix="P2380RF"):
    A, Fr = sess("alice"), sess("frida")
left = {r[0] for r in dbw("SELECT id FROM list_fields WHERE id IN (?,?,?,?)", tuple(ids.values()))}
check(ids[L_EMPTY] not in left and ids[L_DE] not in left, f"#3438: the empty Client / Kunde fields of agency projects are gone {left}")
check(ids[L_VAL] in left, "#3438: a Client field with a value stays")
check(ids[L_PLAIN] in left, "#3438: an empty Client field of a list without the type stays")
check(("Budget h", "number") in fields(A, L_EMPTY) and dbw("SELECT value FROM task_field_values WHERE task_id=?", (T_VAL,)) == [("Example Ltd",)],
      "#3438: Budget h and the value kept")
check([r[0] for r in dbw("SELECT value FROM settings WHERE key='migr_agcl2380'")] == ["1"], "#3438: the one-shot is marked done")

sys.exit(kt.done("p2380r_f_api"))
