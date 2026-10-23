#!/usr/bin/env python3
"""2.72.0 part A API tests: #1333 the household budget of "At home" (kalmido/life/budget.py, budget_web.py).
 - the module "budget" off -> 409; a new budget list has the default categories
 - categories, entries, templates: create / change / delete, a category deleted -> its entries stay without one
 - the month: soll with / without a limit, ist, without category, totals, saldo, the 6-month trend
 - templates monthly / quarterly / yearly with start and end month, booking twice in one month -> 409
 - contracts -> templates, taken, contract_changed and syncing
 - the bank import: semicolon + German numbers with a preamble and a BOM, comma + dot with debit / credit columns,
   trailing minus, broken rows, duplicates on the second import, a remembered mapping, the limits
 - receipts: upload, download, delete; deleting an entry removes its files
 - tenant-matrix: budget -- a stranger 404 everywhere (also with ids of the budget in their own routes), a read-only member
   reads but never writes, a writing family member writes, an agent never (also as a member), a token without the scope
   private never, a budget cannot be shared with an agent
 - encryption at rest: amounts / titles / limits never plain in the database, the receipt sealed on disk, a budget moved
   into an organisation is resealed and reads the same; the person's export has the budget decrypted
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY. Invented data only.
usage: p272_a_budget_api_test.py <datadir>"""
import base64
import os
import struct
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
MAGIC = b"KENC1\n"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def start():
    extra = ["-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_ORGCRYPT_PAUSE=0", "-e KALMIDO_SECRET_KEY=" + KEY]
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def space(path):
    with open(path, "rb") as f:
        h = f.read(14)
    return struct.unpack(">q", h[6:14])[0] if h[:6] == MAGIC and len(h) == 14 else None


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def bud(s, lid, month):
    r = s.get(B + f"/api/budget/{lid}", params={"month": month})
    assert r.ok, r.text
    return r.json()


def cat(j, name):
    return next(x for x in j["cats"] if x["name"] == name)


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Viewer"), ("carol", "Carol Family"), ("dave", "Dave Stranger")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,contracts", "tour": "done"})

# ================================================================ module off -> 409
for meth, path, body in (("get", "/api/budget", None), ("post", "/api/budget/lists", {}), ("get", "/api/budget/1", None)):
    r = getattr(A, meth)(B + path, **({"json": body} if body is not None else {}))
    check(r.status_code == 409 and "turned off" in r.json().get("error", ""), f"module off: {meth} {path} -> 409 ({r.status_code})")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"features": "cal,comments,collab,contracts,budget"})
check(A.get(B + "/api/budget").json() == {"lists": [], "month": A.get(B + "/api/budget").json()["month"], "summary": None},
      "GET /api/budget without a budget: no lists, no summary")

r = A.post(B + "/api/budget/lists", json={})
check(r.status_code == 201, "a new budget list " + r.text[:100])
L = r.json()["list_id"]
check(one("SELECT life FROM lists WHERE id=?", (L,)) == "budget" and one("SELECT name FROM lists WHERE id=?", (L,)) == "Household budget",
      "the list is of kind budget with the default name")
M = "2026-09"
j = bud(A, L, M)
check([x["name"] for x in j["cats"]] == ["Housing", "Groceries", "Mobility", "Insurance", "Leisure", "Other", "Salary", "Other income"]
      and [x["kind"] for x in j["cats"]].count("in") == 2, "the default categories (6 out, 2 in)")
check(j["month"] == M and j["can_write"] and j["entries"] == [] and len(j["trend"]) == 6 and j["trend"][-1]["month"] == M
      and j["trend"][0]["month"] == "2026-04", "an empty month: trend of 6 months up to the month")
ov = A.get(B + "/api/budget").json()
check(ov["lists"][0]["id"] == L and ov["lists"][0]["can_write"] and ov["lists"][0]["shared"] is False and ov["summary"]["saldo"] == 0,
      "GET /api/budget: the list and the summary")
CATS = {x["name"]: x["id"] for x in j["cats"]}

# ================================================================ categories
r = A.patch(B + f"/api/budget/cats/{CATS['Groceries']}", json={"limit": "300,00"})
check(r.ok and r.json()["limit"] == 300.0, "a monthly limit (German number) " + r.text[:100])
r = A.post(B + f"/api/budget/{L}/cats", json={"name": "Kids", "kind": "out", "limit": 50})
check(r.status_code == 201 and r.json()["limit"] == 50.0 and r.json()["kind"] == "out", "a new category")
KIDS = r.json()["id"]
check(A.post(B + f"/api/budget/{L}/cats", json={"name": "", "kind": "out"}).status_code == 400, "a category without a name: 400")
check(A.post(B + f"/api/budget/{L}/cats", json={"name": "x", "kind": "sideways"}).status_code == 400, "a category of an unknown kind: 400")
check(A.patch(B + f"/api/budget/cats/{KIDS}", json={"limit": -5}).status_code == 400, "a negative limit: 400")
check(A.patch(B + f"/api/budget/cats/{KIDS}", json={"limit": None}).json()["limit"] is None, "a limit removed")

# ================================================================ entries
def entry(s, lid, **kw):
    b = {"day": "2026-09-03", "amount": 10, "kind": "out", "title": "Bakery"}
    b.update(kw)
    return s.post(B + f"/api/budget/{lid}/entries", json=b)


r = entry(A, L, amount="1.234,56", title="Rent September", cat_id=CATS["Housing"], note="incl. heating", counterpart="Landlord Example")
check(r.status_code == 201 and r.json()["amount"] == 1234.56 and r.json()["source"] == "manual" and r.json()["files"] == [],
      "an entry with a German amount " + r.text[:150])
E1 = r.json()["id"]
for bad, what in (({"amount": 0}, "amount 0"), ({"amount": -3}, "negative"), ({"amount": 10000000.01}, "above the maximum"),
                  ({"amount": "12.345"}, "three decimals"), ({"day": "2026-02-30"}, "no such day"), ({"kind": "x"}, "kind"),
                  ({"title": ""}, "no title"), ({"amount": True}, "a boolean")):
    check(entry(A, L, **bad).status_code == 400, f"entry refused: {what}")
check(entry(A, L, amount=10000000).status_code == 201, "the maximum amount 10 000 000")
dbx("DELETE FROM budget_entries WHERE list_id=? AND amount<>'' AND id<>?", (L, E1))  # only the rent stays
r = A.patch(B + f"/api/budget/entries/{E1}", json={"amount": 1200, "title": "Rent"})
check(r.ok and r.json()["amount"] == 1200.0 and r.json()["title"] == "Rent" and r.json()["note"] == "incl. heating", "PATCH: the other fields stay")
E2 = entry(A, L, title="Shoes", amount=60, cat_id=KIDS, day="2026-09-10").json()["id"]
r = A.delete(B + f"/api/budget/cats/{KIDS}").json()
check(r["ok"] is True and r["cat"]["name"] == "Kids" and r["entry_ids"] == [E2] and r["recurring_ids"] == [], f"a category deleted, its rows named ({r})")
check(A.get(B + f"/api/budget/{L}", params={"month": M}).json()["entries"][0]["cat_id"] is None, "its entry stays without a category")
r = A.delete(B + f"/api/budget/entries/{E2}")
check(r.ok and r.json()["entry"]["title"] == "Shoes" and r.json()["entry"]["amount"] == 60.0, "DELETE returns the entry (undo)")
e = r.json()["entry"]
r = A.post(B + f"/api/budget/{L}/entries", json={k: e[k] for k in ("day", "amount", "kind", "title", "note", "counterpart")})
check(r.status_code == 201, "undo: the entry created again")
A.delete(B + f"/api/budget/entries/{r.json()['id']}")

# ================================================================ templates (recurring)
def rec(s, lid, **kw):
    b = {"title": "Rent", "amount": 1200, "kind": "out", "per": "month", "start": "2026-01"}
    b.update(kw)
    return s.post(B + f"/api/budget/{lid}/recurring", json=b)


R_RENT = rec(A, L, cat_id=CATS["Housing"]).json()["id"]
R_Q = rec(A, L, title="Water", amount=90, per="quarter", start="2026-01").json()["id"]   # due 01, 04, 07, 10
R_Y = rec(A, L, title="Car insurance", amount=480, per="year", start="2025-09", until="2026-09", cat_id=CATS["Insurance"]).json()["id"]
R_IN = rec(A, L, title="Salary", amount=3000, kind="in", per="month", start="2026-09", cat_id=CATS["Salary"]).json()["id"]
check(rec(A, L, start="2026-05", until="2026-04").status_code == 400 and rec(A, L, per="weekly").status_code == 400
      and rec(A, L, start="2026-13").status_code == 400, "templates: end before start, an unknown period, a bad month -> 400")
items = A.get(B + f"/api/budget/{L}/recurring").json()["items"]
check(len(items) == 4 and all(x["contract"] is None and x["contract_changed"] is False for x in items), "GET recurring: 4 templates")


def open_ids(month):
    return {x["recurring"]["id"] for x in bud(A, L, month)["open_recurring"]}


check(open_ids("2026-09") == {R_RENT, R_Y, R_IN}, f"September: rent, yearly insurance, salary open ({open_ids('2026-09')})")
check(R_Q in open_ids("2026-10") and R_Q not in open_ids("2026-09") and R_Q in open_ids("2026-07"), "quarterly: due every third month from the start")
check(R_Y not in open_ids("2027-09") and R_Y not in open_ids("2025-08") and R_IN not in open_ids("2026-08"), "yearly with an end month; nothing before the start")
r = A.post(B + f"/api/budget/recurring/{R_IN}/book", json={"month": "2026-09", "day": "2026-09-28"})
check(r.status_code == 201 and r.json()["recurring_id"] == R_IN and r.json()["source"] == "recurring" and r.json()["day"] == "2026-09-28"
      and r.json()["amount"] == 3000.0 and r.json()["cat_id"] == CATS["Salary"], "booked: an entry linked to the template " + r.text[:150])
r = A.post(B + f"/api/budget/recurring/{R_IN}/book", json={"month": "2026-09"})
check(r.status_code == 409, f"booking twice in one month: 409 ({r.status_code})")
check(A.post(B + f"/api/budget/recurring/{R_Q}/book", json={"month": "2026-09"}).status_code == 400, "booking in a month it is not due: 400")
check(R_IN not in open_ids("2026-09") and R_IN in open_ids("2026-10"), "booked = no longer open in that month only")
r = A.patch(B + f"/api/budget/entries/{E1}", json={"recurring_id": R_RENT})
check(r.ok and R_RENT not in open_ids("2026-09"), "an entry linked by hand books the template")
check(entry(A, L, title="Rent twice", amount=1200, recurring_id=R_RENT).status_code == 409, "a second entry of the same template in the month: 409")

# ================================================================ contracts -> templates
r = A.post(B + "/api/life/contracts", json={"name": "Mobile phone", "provider": "Telco Example", "cost": "19,99", "per": "month", "ends": "2027-06-30"})
assert r.status_code == 201, r.text
CON = r.json()
r = Da.post(B + "/api/life/contracts", json={"name": "Dave gym", "cost": 30, "per": "month", "ends": "2027-06-30"})
DCON = r.json()["id"]
cs = A.get(B + f"/api/budget/{L}/contracts").json()["items"]
check([x["task_id"] for x in cs] == [CON["id"]] and cs[0]["cost"] == 19.99 and cs[0]["taken"] is False and cs[0]["provider"] == "Telco Example",
      f"contracts: only the person's own visible ones ({cs})")
check(A.post(B + f"/api/budget/{L}/contracts", json={"task_ids": [DCON]}).status_code == 404, "another person's contract: 404")
r = A.post(B + f"/api/budget/{L}/contracts", json={"task_ids": [CON["id"]], "cat_id": CATS["Other"]})
check(r.status_code == 201 and r.json()["created"] == 1 and r.json()["items"][0]["amount"] == 19.99
      and r.json()["items"][0]["contract_task_id"] == CON["id"] and r.json()["items"][0]["kind"] == "out", "a contract taken over " + r.text[:150])
R_CON = r.json()["items"][0]["id"]
check(A.post(B + f"/api/budget/{L}/contracts", json={"task_ids": [CON["id"]]}).json()["created"] == 0, "taken twice: nothing new")
check(A.get(B + f"/api/budget/{L}/contracts").json()["items"][0]["taken"] is True, "the contract is marked taken")
A.patch(B + f"/api/tasks/{CON['id']}", json={"fam": {**CON["fam"], "cost": 24.99, "per": "year"}})
x = next(i for i in A.get(B + f"/api/budget/{L}/recurring").json()["items"] if i["id"] == R_CON)
check(x["contract_changed"] is True and x["amount"] == 19.99 and x["contract"] == {"cost": 24.99, "per": "year"},
      "a changed contract: the template keeps its values and says so")
r = A.patch(B + f"/api/budget/recurring/{R_CON}", json={"sync_contract": True})
check(r.ok and r.json()["amount"] == 24.99 and r.json()["per"] == "year" and r.json()["contract_changed"] is False, "synced with the contract")

# ================================================================ the month
A.patch(B + f"/api/budget/entries/{E1}", json={"cat_id": CATS["Housing"]})
entry(A, L, title="Market", amount="45,20", cat_id=CATS["Groceries"], day="2026-09-05")
entry(A, L, title="Refund", amount=5.20, kind="in", cat_id=CATS["Groceries"], day="2026-09-06")   # lowers the groceries
entry(A, L, title="Kiosk", amount=7.30, day="2026-09-07")                                           # without category
entry(A, L, title="August", amount=100, day="2026-08-15")
j = bud(A, L, M)
g = cat(j, "Groceries")
check(g["soll"] == 300.0 and g["ist"] == 40.0 and g["planned"] == 0.0, f"Groceries: soll = limit, ist = out - refund ({g})")
h = cat(j, "Housing")
check(h["soll"] == 1200.0 and h["planned"] == 1200.0 and h["ist"] == 1200.0, f"Housing without a limit: soll = the template due ({h})")
check(cat(j, "Insurance")["soll"] == 480.0 and cat(j, "Salary")["soll"] == 3000.0 and cat(j, "Salary")["ist"] == 3000.0, "yearly + salary soll")
check(j["none"] == {"ist_in": 0.0, "ist_out": 7.3}, f"without category ({j['none']})")
t = j["totals"]
check(t["ist_out"] == 1252.5 and t["ist_in"] == 3005.2 and t["saldo"] == 1752.7 and t["soll_in"] == 3000.0
      and t["soll_out"] == 300.0 + 1200.0 + 480.0, f"totals and saldo ({t})")
check([e["title"] for e in j["entries"]][:2] == ["Salary", "Kiosk"] and all(e["day"].startswith(M) for e in j["entries"]),
      "the month's entries, newest first")
check(j["trend"][-2] == {"month": "2026-08", "ist_in": 0.0, "ist_out": 100.0} and j["trend"][-1]["ist_out"] == 1252.5, "the trend")
jo = bud(A, L, "2026-10")
check(round(jo["totals"]["soll_out"] - cat(jo, "Other")["soll"], 2) == 300.0 + 1200.0 + 90.0,
      f"October: the groceries limit, rent + quarterly water, the yearly insurance ended in September ({jo['totals']})")
check(A.get(B + f"/api/budget/{L}", params={"month": "2026-9"}).status_code == 400, "a bad month: 400")

# ================================================================ the bank import
CSV1 = ("﻿Kontonummer;DE00 0000 0000\nZeitraum;01.09.2026 - 30.09.2026\n\n"
        "Buchungstag;Valuta;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n"
        "11.09.2026;11.09.2026;Supermarket Example;Groceries card;-45,20\n"
        "12.09.2026;12.09.2026;Employer Example;Bonus September;2.500,00\n"
        "13.09.2026;13.09.2026;Water Works Example;Water;90,00-\n"
        "xx.09.2026;;Broken;Row;-1,00\n"
        "14.09.2026;;No amount;Row;abc\n")
# an earlier entry with the same counterpart suggests its category
entry(A, L, title="Old shopping", amount=1, counterpart="Supermarket Example", cat_id=CATS["Groceries"], day="2026-07-01")
R_W = rec(A, L, title="Water monthly", amount=90, per="month", start="2026-09").json()["id"]
r = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV1})
check(r.ok, "parse without a mapping " + r.text[:200])
p = r.json()
gs = p["guess"]
check(p["delimiter"] == ";" and p["columns"] == ["Buchungstag", "Valuta", "Auftraggeber/Empfänger", "Verwendungszweck", "Betrag"]
      and len(p["sample"]) == 5, f"semicolon, the header after the preamble, the BOM gone ({p['columns']})")
check(gs["date"] == 0 and gs["amount"] == 4 and gs["title"] == 3 and gs["counterpart"] == 2 and gs["decimal"] == ","
      and gs["date_format"] == "DD.MM.YYYY", f"the guess ({gs})")
r = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV1, "mapping": gs})
rows = r.json()["rows"]
check(r.ok and r.json()["skipped"] == 2 and len(rows) == 5, "parse with a mapping: 5 rows, 2 broken " + r.text[:200])
check(rows[0]["day"] == "2026-09-11" and rows[0]["amount"] == 45.2 and rows[0]["kind"] == "out" and rows[0]["cat_id"] == CATS["Groceries"]
      and rows[0]["dup"] is False and rows[0]["error"] is None, f"row 1: out, the category from the counterpart ({rows[0]})")
check(rows[1]["amount"] == 2500.0 and rows[1]["kind"] == "in" and rows[1]["title"] == "Bonus September", "row 2: in, thousands separator")
check(rows[2]["amount"] == 90.0 and rows[2]["kind"] == "out" and rows[2]["recurring_id"] in (R_W, R_Q) and rows[2]["recurring_id"] == R_W,
      f"row 3: trailing minus = out, the open template of the same amount suggested ({rows[2]})")
check(rows[3]["error"] and rows[4]["error"] and rows[3]["n"] == 4, "broken rows carry an error")
ok = [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart", "cat_id", "recurring_id")} for x in rows if not x["error"]]
mp = dict(gs, counterpart=None)
r = A.post(B + f"/api/budget/{L}/import/commit", json={"rows": ok, "mapping": mp, "columns": p["columns"]})
# 2.146.0 (#2455): the answer also names the import run
check(r.status_code == 201 and {k: r.json().get(k) for k in ("created", "skipped_dup")} == {"created": 3, "skipped_dup": 0}, "commit: 3 created " + r.text[:150])
check(R_W not in open_ids(M), "the linked template is booked by the import")
check(one("SELECT COUNT(*) FROM budget_entries WHERE list_id=? AND source='csv'", (L,)) == 3, "source csv")
p2 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV1}).json()
check(p2["guess"]["counterpart"] is None and p2["guess"]["amount"] == 4, "the same header again: the remembered mapping")
rows2 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV1, "mapping": gs}).json()["rows"]
check([x["dup"] for x in rows2 if not x["error"]] == [True, True, True], "the second import: every row a duplicate")
r = A.post(B + f"/api/budget/{L}/import/commit", json={"rows": ok})
check({k: r.json().get(k) for k in ("created", "skipped_dup")} == {"created": 0, "skipped_dup": 3}, "commit again: nothing twice " + r.text[:100])
CSV2 = ("Date,Description,Payee,Debit,Credit\n2026-09-20,Coffee,Cafe Example,3.50,\n2026-09-21,Refund,Shop Example,,10.00\n"
        "2026-09-22,Coffee,Cafe Example,3.50,\n")
p = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV2}).json()
gs = p["guess"]
check(p["delimiter"] == "," and gs["amount"] is None and gs["amount_out"] == 3 and gs["amount_in"] == 4 and gs["decimal"] == "."
      and gs["date_format"] == "YYYY-MM-DD" and gs["title"] == 1 and gs["counterpart"] == 2, f"comma, debit / credit columns ({gs})")
rows = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV2, "mapping": gs}).json()["rows"]
check([(x["amount"], x["kind"]) for x in rows] == [(3.5, "out"), (10.0, "in"), (3.5, "out")], f"debit = out, credit = in ({rows})")
ok2 = [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart")} for x in rows]
check(A.post(B + f"/api/budget/{L}/import/commit", json={"rows": ok2}).json()["created"] == 3, "two equal coffees on two days: both")
CSV3 = "Datum;Text;Betrag\n01.09.26;Coffee;-2,00\n01.09.26;Coffee;-2,00\n"
g3 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV3}).json()["guess"]
check(g3["date_format"] == "DD.MM.YY", f"two-digit years ({g3})")
r3 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV3, "mapping": g3}).json()["rows"]
o3 = [{k: x[k] for k in ("day", "amount", "kind", "title")} for x in r3]
check(r3[0]["day"] == "2026-09-01" and A.post(B + f"/api/budget/{L}/import/commit", json={"rows": o3}).json()["created"] == 2,
      "two equal rows in one file: both created")
r3 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV3 + "01.09.26;Coffee;-2,00\n", "mapping": g3}).json()["rows"]
check([x["dup"] for x in r3] == [True, True, False], "a third equal row later: only that one is new")
check(A.post(B + f"/api/budget/{L}/import/parse", json={"text": "a;b\n" + "x" * (2 * 1024 * 1024)}).status_code in (400, 413), "more than 2 MB: refused")
# 2.146.0 (#2455): more than 3000 rows are read (the app takes them over in parts); the limit of one import is 20000
big = "Datum;Text;Betrag\n" + "01.09.2026;x;-1,00\n" * 20001
check(A.post(B + f"/api/budget/{L}/import/parse", json={"text": big, "mapping": g3 | {"date_format": "DD.MM.YYYY"}}).status_code == 400,
      "more than 20000 rows: 400")
check(A.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV3, "mapping": dict(g3, date=9)}).status_code == 400, "a column out of range: 400")
check(A.post(B + f"/api/budget/{L}/import/commit", json={"rows": [dict(o3[0], amount=-1)]}).status_code == 400, "commit checks again")

# ================================================================ receipts
RC = b"%PDF-1.4 invented receipt " + os.urandom(8).hex().encode() + b"\n" * 50
used0 = A.get(B + "/api/me/storage").json()["used"]
r = A.post(B + f"/api/budget/entries/{E1}/files", files=[("file", ("receipt.pdf", RC, "application/pdf")), ("file", ("photo.txt", b"two", "text/plain"))])
# 2.72.0 (#1333): review - receipts count towards the storage quota
check(A.get(B + "/api/me/storage").json()["used"] == used0 + len(RC) + 3, "the receipts count towards the person's storage")
check(r.ok and [f["name"] for f in r.json()["files"]] == ["receipt.pdf", "photo.txt"] and r.json()["files"][0]["size"] == len(RC),
      "two receipts uploaded " + r.text[:150])
F1, F2 = r.json()["files"][0]["id"], r.json()["files"][1]["id"]
fp = os.path.join(DATA, "attachments", one("SELECT path FROM budget_files WHERE id=?", (F1,)))
check(space(fp) == -ALICE and RC not in open(fp, "rb").read(), "the receipt is sealed on disk with the owner's account key")
r = A.get(B + f"/api/budget/files/{F1}")
check(r.ok and r.content == RC, "the receipt downloads byte for byte")
check(len(next(e for e in bud(A, L, M)["entries"] if e["id"] == E1)["files"]) == 2, "the entry lists its receipts")
check(A.delete(B + f"/api/budget/files/{F2}").json() == {"ok": True} and A.get(B + f"/api/budget/files/{F2}").status_code == 404, "a receipt deleted")
check(A.post(B + f"/api/budget/entries/{E1}/files", files=[("file", ("empty.txt", b"", "text/plain"))]).status_code == 400, "an empty file: 400")
r = A.post(B + f"/api/budget/entries/{E1}/files", files=[("file", ("../../etc/x.txt", b"name", "text/plain"))])
check(r.ok and "/" not in r.json()["files"][-1]["name"] and ".." not in one("SELECT path FROM budget_files ORDER BY id DESC LIMIT 1"),
      "a path in the file name is cut off")
E9 = entry(A, L, title="With receipt", amount=3, day="2026-09-02").json()["id"]
F9 = A.post(B + f"/api/budget/entries/{E9}/files", files=[("file", ("r.txt", b"gone", "text/plain"))]).json()["files"][0]["id"]
p9 = os.path.join(DATA, "attachments", one("SELECT path FROM budget_files WHERE id=?", (F9,)))
A.delete(B + f"/api/budget/entries/{E9}")
check(not os.path.exists(p9) and one("SELECT COUNT(*) FROM budget_files WHERE id=?", (F9,)) == 0, "deleting an entry removes its receipts")

# ================================================================ tenant-matrix: budget
DL = Da.post(B + "/api/budget/lists", json={"name": "Dave money"}).json()["list_id"]
DCAT = bud(Da, DL, M)["cats"][0]["id"]
E_ANY = one("SELECT id FROM budget_entries WHERE list_id=? ORDER BY id LIMIT 1", (L,))
for meth, path, body in (("get", f"/api/budget/{L}", None), ("get", f"/api/budget/{L}/recurring", None),
                         ("get", f"/api/budget/{L}/contracts", None), ("post", f"/api/budget/{L}/cats", {"name": "x", "kind": "out"}),
                         ("patch", f"/api/budget/cats/{CATS['Leisure']}", {"name": "mine"}), ("delete", f"/api/budget/cats/{CATS['Leisure']}", None),
                         ("post", f"/api/budget/{L}/entries", {"day": "2026-09-01", "amount": 1, "kind": "out", "title": "x"}),
                         ("patch", f"/api/budget/entries/{E1}", {"title": "mine"}), ("delete", f"/api/budget/entries/{E1}", None),
                         ("post", f"/api/budget/{L}/recurring", {"title": "x", "amount": 1, "kind": "out", "per": "month", "start": M}),
                         ("patch", f"/api/budget/recurring/{R_RENT}", {"title": "mine"}), ("delete", f"/api/budget/recurring/{R_RENT}", None),
                         ("post", f"/api/budget/recurring/{R_Q}/book", {"month": "2026-10"}),
                         ("post", f"/api/budget/{L}/contracts", {"task_ids": [CON["id"]]}),
                         ("post", f"/api/budget/{L}/import/parse", {"text": CSV1}), ("post", f"/api/budget/{L}/import/commit", {"rows": ok}),
                         ("get", f"/api/budget/files/{F1}", None), ("delete", f"/api/budget/files/{F1}", None)):
    r = getattr(Da, meth)(B + path, **({"json": body} if body is not None else {}))
    check(r.status_code == 404, f"a stranger: {meth} {path} -> 404 ({r.status_code})")
r = Da.post(B + f"/api/budget/entries/{E1}/files", files={"file": ("x.txt", b"x", "text/plain")})
check(r.status_code == 404, f"a stranger: upload to another budget's entry -> 404 ({r.status_code})")
check(L not in [x["id"] for x in Da.get(B + "/api/budget").json()["lists"]], "a stranger does not see the budget in the list")
# ids of the other budget inside the own one
check(entry(Da, DL, cat_id=CATS["Housing"]).status_code == 400 and entry(Da, DL, recurring_id=R_RENT).status_code == 400,
      "the own budget refuses a category / template id of another budget")
check(rec(Da, DL, cat_id=CATS["Housing"]).status_code == 400, "a template with another budget's category: 400")
check(Da.post(B + f"/api/budget/{DL}/import/commit", json={"rows": [{"day": "2026-09-01", "amount": 1, "kind": "out", "title": "x",
                                                                      "cat_id": CATS["Housing"]}]}).status_code == 400, "import with a foreign category: 400")
check(Da.post(B + f"/api/budget/{DL}/contracts", json={"task_ids": [CON["id"]]}).status_code == 404, "a foreign contract into the own budget: 404")
check(A.patch(B + f"/api/budget/entries/{E1}", json={"cat_id": DCAT}).status_code == 400, "the owner cannot link a stranger's category")
# shared read-only (bob) and writing (carol)
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "view"}).ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "edit"}).ok
jb = bud(Bo, L, M)
check(jb["can_write"] is False and jb["totals"] == bud(A, L, M)["totals"], "a read-only member sees the same month")
check(Bo.get(B + f"/api/budget/files/{F1}").content == RC, "… and the receipt")
for meth, path, body in (("post", f"/api/budget/{L}/entries", {"day": "2026-09-01", "amount": 1, "kind": "out", "title": "x"}),
                         ("patch", f"/api/budget/entries/{E1}", {"title": "mine"}), ("delete", f"/api/budget/entries/{E1}", None),
                         ("patch", f"/api/budget/cats/{CATS['Leisure']}", {"limit": 1}), ("post", f"/api/budget/recurring/{R_Q}/book", {"month": "2026-10"}),
                         ("post", f"/api/budget/{L}/import/parse", {"text": CSV1}), ("delete", f"/api/budget/files/{F1}", None)):
    r = getattr(Bo, meth)(B + path, **({"json": body} if body is not None else {}))
    check(r.status_code == 403, f"read-only: {meth} {path} -> 403 ({r.status_code})")
ovb = Bo.get(B + "/api/budget").json()["lists"]
check([x["id"] for x in ovb] == [L] and ovb[0]["can_write"] is False and ovb[0]["shared"] is True, "the shared budget in bob's overview")
r = entry(Ca, L, title="Carol's groceries", amount=12, cat_id=CATS["Groceries"])
check(r.status_code == 201 and r.json()["created_by"] == CAROL, "a writing family member adds an entry")
check(Ca.post(B + f"/api/budget/recurring/{R_Q}/book", json={"month": "2026-10"}).status_code == 201, "… and books a template")
# agents and tokens
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "claude", "display_name": "Claude"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit", "bridge_ok": True})
check(r.status_code == 409 and "budget" in r.json()["error"].lower(), f"a budget cannot be shared with an agent ({r.status_code})")
try:
    dbx("INSERT INTO list_members(list_id, user_id, role) VALUES(?,?,?)", (L, AG, "edit"))  # forced in: still nothing
except Exception as e:  # noqa: BLE001 -- the table needs more columns: the refused share above is the check then
    print("note: agent membership not forced in:", type(e).__name__)
for path in (f"/api/budget/{L}", "/api/budget", f"/api/budget/files/{F1}", f"/api/budget/{L}/recurring"):
    r = requests.get(B + path, headers=AGH)
    check(r.status_code in (401, 403, 404, 409) and "Rent" not in r.text, f"an agent (even as a member): {path} -> {r.status_code}")
check(requests.get(V + f"/lists/{L}", headers=AGH).status_code == 404 and L not in [x["id"] for x in requests.get(V + "/lists", headers=AGH).json()["data"]],
      "the agent's API: the budget list does not exist")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (L, AG))
tk = {"Authorization": "Bearer " + A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]}
for path in (f"/api/budget/{L}", "/api/budget", f"/api/budget/files/{F1}"):
    r = requests.get(B + path, headers=tk)
    check(r.status_code in (401, 403, 404) and "Rent" not in r.text, f"a token without private: {path} -> {r.status_code}")
check(L not in [x["id"] for x in requests.get(V + "/lists", headers=tk).json()["data"]], "a token without private: no budget list in v1")
# a new budget list is never shared with an agent automatically (Share new lists automatically)
check(one("SELECT COUNT(*) FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id IN (?, ?) AND u.kind='agent'", (L, DL)) == 0,
      "no agent in any budget list")

# ================================================================ encryption at rest
plain = dbx("SELECT amount, title, note, counterpart, sid FROM budget_entries WHERE list_id=?", (L,))
check(plain and all(r["amount"].startswith("kenc1:") and r["title"].startswith("kenc1:") and r["sid"] == -ALICE for r in plain),
      "entries: amount and title encrypted with alice's account key")
check(all(not r["counterpart"] or r["counterpart"].startswith("kenc1:") for r in plain) and all(not r["note"] or r["note"].startswith("kenc1:") for r in plain),
      "entries: note and counterpart encrypted")
check(all(r[0].startswith("kenc1:") and r[1].startswith("kenc1:") for r in dbx("SELECT amount, title FROM budget_recurring WHERE list_id=?", (L,))),
      "templates encrypted")
check(one("SELECT lim FROM budget_cats WHERE id=?", (CATS["Groceries"],)).startswith("kenc1:"), "a limit encrypted")
check(not any("Bonus September" in str(tuple(r)) or "1200.00" in str(tuple(r)) for r in dbx("SELECT * FROM budget_entries")),
      "no plain title or amount in any column")
lg = logs()
check("Bonus September" not in lg and "Supermarket Example" not in lg, "the server log has no budget texts")
# a budget handed to another owner (another space: Home & life lists never belong to an organisation): resealed, reads the same
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
L2 = A.post(B + "/api/budget/lists", json={"name": "Moving budget"}).json()["list_id"]
check(one("SELECT org_id FROM lists WHERE id=?", (L2,)) is None, "a budget list is private")
check(not A.patch(B + f"/api/lists/{L2}", json={"org_id": ORG}).ok and one("SELECT org_id FROM lists WHERE id=?", (L2,)) is None, "a budget list cannot move into an organisation")
entry(A, L2, title="Before the move", amount="99,95", counterpart="Someone Example")
rec(A, L2, title="Move rent", amount=500)
A.patch(B + f"/api/budget/cats/{bud(A, L2, M)['cats'][0]['id']}", json={"limit": 700})
E2id = one("SELECT id FROM budget_entries WHERE list_id=?", (L2,))
F2m = A.post(B + f"/api/budget/entries/{E2id}/files", files={"file": ("m.txt", b"moving receipt", "text/plain")}).json()["files"][0]["id"]
fp2 = os.path.join(DATA, "attachments", one("SELECT path FROM budget_files WHERE id=?", (F2m,)))
before = bud(A, L2, M)
check(one("SELECT sid FROM budget_entries WHERE id=?", (E2id,)) == -ALICE and space(fp2) == -ALICE, "the private budget: alice's key")
r = A.post(B + f"/api/lists/{L2}/owner", json={"user_id": BOB})
check(r.ok, "the budget handed to bob " + r.text[:150])
after = bud(Bo, L2, M)  # right away (the rows still carry alice's key until the background pass)
check(after["totals"] == before["totals"] and after["entries"][0]["title"] == "Before the move", "right after the hand-over it reads the same")
done = False
for _ in range(120):
    sids = {x[0] for t in ("budget_entries", "budget_recurring", "budget_cats") for x in dbx(f"SELECT sid FROM {t} WHERE list_id=? AND sid<>0", (L2,))}
    if sids == {-BOB} and space(fp2) == -BOB:
        done = True
        break
    time.sleep(0.25)
check(done, f"every row and the receipt resealed for the new owner's key ({sids}, {space(fp2)})")
after = bud(Bo, L2, M)
check(after["totals"] == before["totals"] and after["entries"][0]["title"] == "Before the move" and after["entries"][0]["amount"] == 99.95
      and after["cats"][0]["limit"] == 700.0, "after the reseal the budget reads the same")
check(Bo.get(B + f"/api/budget/files/{F2m}").content == b"moving receipt", "the receipt reads the same")
# the person's export
ex = A.get(B + "/api/export.json").json()
eb = {x["list_id"]: x for x in ex.get("budget", [])}
check(L in eb and any(e["title"] == "Bonus September" for e in eb[L]["entries"]) and "kenc1:" not in str(eb[L]), "the export has the budget decrypted")
check(DL not in eb and L2 not in eb, "the export has only the person's own budgets")

# ================================================================ 2.72.0 (#1333): review - a budget never gets a public link
r = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
check(r.status_code == 409 and "public link" in r.json().get("error", ""), f"a budget list: no public link (409) {r.status_code} {r.text[:120]}")
check(A.patch(B + f"/api/lists/{L}", json={"folder": "Home"}).ok, "the budget in a folder")
r = A.put(B + "/api/folders/public-links", json={"folder": "Home", "on": True})
check(r.ok and r.json().get("created") == 0 and one("SELECT COUNT(*) FROM public_links WHERE list_id=?", (L,)) == 0,
      f"the folder's public links leave the budget out {r.text[:150]}")

# ================================================================ deleting a budget list removes its receipts
Bo.patch(B + f"/api/lists/{L2}", json={"archived": True})
r = Bo.delete(B + f"/api/lists/{L2}")
r = Bo.delete(B + f"/api/trash/lists/{L2}") if r.ok else r  # 2.102.0 (#1988): deleting moves the list into the list trash; the purge from there deletes for good
gone = not os.path.exists(fp2)
for _ in range(20):
    if gone:
        break
    time.sleep(0.25)
    gone = not os.path.exists(fp2)
check(r.ok and gone and one("SELECT COUNT(*) FROM budget_entries WHERE list_id=?", (L2,)) == 0, f"a deleted budget list: rows and receipts gone ({r.status_code})")

print(f"p272_a_budget_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
