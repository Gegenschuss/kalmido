#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.525.0 (#4187) the office figures read less: the year filtered in SQL, only the needed columns, a short cache for the
tile Figures. Invented data only; as a person without an organisation (freelancer-matrix: office) plus a second one.
 - old against new: the same documents, the old queries (SELECT * of every document of every year) patched in -> the figures
   (/api/office/kpi), the cash flow and the income statement are the same to the cent; the edge cases are in the data: an
   open invoice of an earlier year, an invoice of two years ago paid this year, a payment last year, a cancelled invoice of
   last year with its credit note this year, a free credit note, a foreign currency, a trial invoice, a purchase of a
   quotation three years old, drafts and offers of old years
 - the figures read fewer rows than every document of the office (kpi_docs)
 - the client card: the month next to all time from one time report gives the same numbers as the two reports before,
   also with an entry just after midnight of the 1st in the person's time zone
 - the cache: a second call answers from it (fewer statements); a payment, a status changed in the database and a new time
   entry through the app show at once; another person never gets the first one's figures
 - the office list with a derived state / a sort reads the full rows only of the page (fewer columns, same rows)
usage: p2525_b_kpi_test.py <datadir>"""
# freelancer-matrix: office
import json
import re
import subprocess
import sys

import kt
from kt import B, CT, check, dbx
from freelancer_fixture import freelancer

kt.fresh(prefix="P2525B")
A = kt.setup()
FID, Fr = freelancer(B, A)
GID, Gr = freelancer(B, A, name="gerda")
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-1500:]


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


check(Fr.patch(B + "/api/settings", json={"tz": "Europe/Berlin"}).ok, "setup: frida's time zone")
r = Fr.get(B + "/api/office/docs?kind=invoice")
check(r.ok, "the own office answers " + r.text[:200])
OID = r.json()["org_id"]
OID_G = Gr.get(B + "/api/office/docs?kind=invoice").json()["org_id"]
TODAY = in_app("from kalmido.core.db import local_now\nprint(local_now().date().isoformat())")
check(re.fullmatch(r"\d{4}-\d\d-\d\d", TODAY), "the app's today " + TODAY)
Y = int(TODAY[:4])
MON = TODAY[:7]
r = Fr.post(B + "/api/clients", json={"name": "Example Studio", "budget_h": 40})
check(r.ok, "setup: a client " + r.text[:200])
CID = r.json()["id"]
r = Fr.post(B + "/api/lists", json={"name": "Example project"})
check(r.ok, "setup: a list " + r.text[:200])
LID = r.json()["id"]
check(Fr.patch(B + f"/api/lists/{LID}", json={"client_id": CID, "rate": 80}).ok, "setup: the list belongs to the client, a rate")
TS = "2020-01-01T00:00:00+00:00"


def doc(kind, number, status, date, net, gross, client=None, locked=True, trial=0, cancels=None, currency="EUR", fx=None, due="", oid=None):
    return dbx("INSERT INTO office_docs(org_id, kind, number, status, lang, currency, fx_rate, client_id, recipient, date, due_date, rights, fields, totals, "
               "created_by, created_at, updated_at, locked_at, trial, cancels_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
               (oid or OID, kind, number, status, "en", currency, fx, client, json.dumps({"name": "Example Studio"}), date, due, "{}", "[]",
                json.dumps({"net": str(net), "gross": str(gross)}), FID, TS, TS, TS if locked else None, trial, cancels))[0][0]


def pay(did, date, amount, oid=None):
    dbx("INSERT INTO office_payments(org_id, doc_id, date, amount, method, note, created_at) VALUES(?,?,?,?,?,?,?)", (oid or OID, did, date, amount, "transfer", "", TS))


# the edge cases of the figures (see the module text)
OLD_OPEN = doc("invoice", "RE-1", "issued", f"{Y - 1}-03-10", 100, 119, CID, due=f"{Y - 1}-04-10")
OLD_PAID = doc("invoice", "RE-2", "paid", f"{Y - 2}-11-02", 200, 238, CID)
pay(OLD_PAID, f"{Y}-01-15", "238.00")
LAST = doc("invoice", "RE-3", "paid", f"{Y - 1}-05-05", 50, 59.5, CID)
pay(LAST, f"{Y - 1}-06-01", "59.50")
THIS = doc("invoice", "RE-4", "issued", f"{Y}-01-20", 1000, 1190, CID, due=f"{Y}-02-20")
pay(THIS, f"{Y}-02-01", "500.00")
GONE = doc("invoice", "RE-5", "cancelled", f"{Y - 1}-12-20", 300, 357, CID)
doc("credit", "GS-1", "issued", f"{Y}-01-05", 300, 357, CID, cancels=GONE)
doc("credit", "GS-2", "issued", f"{Y}-02-05", 40, 47.6, CID)
USD = doc("invoice", "RE-6", "issued", f"{Y}-01-25", 500, 595, CID, currency="USD", fx="1.25", due=f"{Y}-02-25")
pay(USD, f"{Y}-02-10", "100.00")
doc("invoice", "RE-7", "issued", f"{Y}-01-26", 777, 924.63, CID, trial=1)
doc("invoice", "", "draft", f"{Y}-01-27", 10, 11.9, CID, locked=False)
OFFER = doc("offer", "AN-1", "accepted", f"{Y - 3}-07-01", 900, 1071, CID)
for i in range(12):
    doc("offer", f"AN-{10 + i}", "draft", f"{Y - 4}-0{1 + i % 9}-01", 10 + i, 11.9 + i, CID, locked=False)
    doc("invoice", f"RE-{20 + i}", "paid", f"{Y - 4}-0{1 + i % 9}-01", 10 + i, 11.9 + i, CID)
dbx("INSERT INTO office_purchases(org_id, doc_id, date, accepted_at, amount, currency, label, source, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (OID, OFFER, f"{Y}-03-01", f"{Y - 3}-07-02", "120.00", "EUR", "Studio rent", "item", TS))
# time: last month, this month and just after midnight of the 1st in Berlin (the day before in UTC)
first = f"{MON}-01"
prev_last = in_app(f"from datetime import date, timedelta\nprint((date.fromisoformat('{first}') - timedelta(days=1)).isoformat())")
for start, end, sec in ((f"{prev_last}T08:00:00+00:00", f"{prev_last}T10:00:00+00:00", 7200),
                        (f"{prev_last}T23:30:00+00:00", f"{prev_last}T23:59:00+00:00", 1740),
                        (f"{first}T09:00:00+00:00", f"{first}T10:30:00+00:00", 5400)):
    dbx("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (FID, LID, "Edit", start, end, sec, "", "manual", end, end))

OLD = '''
from flask import g
from kalmido.core.config import app as fa
from kalmido.core.db import db
from kalmido.office import kpi, cashflow, books
from kalmido.team import clients as cl
from kalmido.personal.timetrack import time_report
from datetime import date, timedelta
OID, UID, CID, Y, TODAY, MON = %r
def norm(x):
    return json.loads(json.dumps(x, default=str, sort_keys=True))
with fa.test_request_context('/'):
    c = db()
    g.user = c.execute("SELECT * FROM users WHERE id=?", (UID,)).fetchone()
    every = c.execute("SELECT COUNT(*) FROM office_docs WHERE org_id=?", (OID,)).fetchone()[0]
    rows = len(kpi.kpi_docs(c, OID, Y))
    new = [norm(kpi.kpi_build(c, UID, OID, y, TODAY)) for y in (Y, Y - 1)]
    ncf = norm(cashflow.rk_cashflow(c, OID, "%%d-01" %% Y, 12, TODAY))
    neu = [norm(books.bk_euer(c, OID, y)) for y in (Y, Y - 1)]
    lids = cl.client_lists(c, UID, CID)
    prev = (date.fromisoformat(MON + "-01") - timedelta(days=1)).strftime("%%Y-%%m")
    nst = [cl.client_stats(c, UID, CID, lids, m) for m in (MON, prev)]
    alld = lambda kinds: lambda c, oid, *a: c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind IN (%%s) AND trial=0" %% kinds, (oid,)).fetchall()
    kpi.kpi_docs = alld("'invoice', 'credit', 'offer'")
    kpi.kpi_doc_clients = lambda c, oid, ids: {r["id"]: r["client_id"] for r in alld("'invoice', 'credit', 'offer'")(c, oid)}
    cashflow.cf_docs = alld("'offer', 'invoice', 'credit'")
    books.bk_pay_docs = alld("'invoice', 'credit'")
    old = [norm(kpi.kpi_build(c, UID, OID, y, TODAY)) for y in (Y, Y - 1)]
    ocf = norm(cashflow.rk_cashflow(c, OID, "%%d-01" %% Y, 12, TODAY))
    oeu = [norm(books.bk_euer(c, OID, y)) for y in (Y, Y - 1)]
    ost = []
    csv = ",".join(str(x) for x in lids)
    for m in (MON, prev):
        d1 = date.fromisoformat(m + "-01")
        d2 = (d1.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        t = time_report(c, UID, {"scope": "all", "lists": csv})["total"]
        w = time_report(c, UID, {"scope": "all", "lists": csv, "from": d1.isoformat(), "to": d2.isoformat()})["total"]
        ost.append((t["seconds"], t["rounded"], t["amount"], w["seconds"], w["amount"]))
    nst = [(s["seconds"], s["rounded"], s["amount"], s["month_seconds"], s["month_amount"]) for s in nst]
    print(json.dumps({"every": every, "rows": rows, "kpi": new == old, "cf": ncf == ocf, "euer": neu == oeu, "stats": nst == [list(x) for x in ost] or nst == ost,
                      "nst": nst, "ost": ost, "new": new[0], "diff": [k for k in new[0] if new[0][k] != old[0].get(k)],
                      "cfdiff": [k for k in ncf if ncf[k] != ocf.get(k)]}))
'''
out = in_app(OLD % ((OID, FID, CID, Y, TODAY, MON),))
try:
    res = json.loads(out)
except ValueError:
    res = {}
check(res, "the comparison ran in the app: " + out[-1500:])
if res:
    check(res["kpi"], f"#4187 old against new: the figures of this year and last year are the same to the cent (differ: {res['diff']})")
    check(res["cf"], f"#4187 old against new: the cash flow is the same (differ: {res['cfdiff']})")
    check(res["euer"], "#4187 old against new: the income statement of this year and last year is the same")
    check(res["stats"], f"#4187 the client card: all time + the month from one report = the two reports before {res['nst']} / {res['ost']}")
    check(res["rows"] < res["every"] - 20, f"#4187 the figures read only the documents they need: {res['rows']} of {res['every']}")
    k = res["new"]
    # the data really reach every path (else old = new proves nothing)
    check(k["invoices"]["open"]["count"] == 3 and k["invoices"]["overdue"]["count"] >= 1, f"the open invoices of every year count {k['invoices']}")
    cli = [x for x in k["clients"] if x["id"] == CID]
    check(cli and cli[0]["costs"] == "120.00", f"the purchase of the old quotation counts as costs {cli[:1]}")
    # invoiced this year: 1000 + 500 / 1.25 - 40 (the credit note of the cancelled one is skipped, the trial and draft ones too)
    check(cli and cli[0]["invoiced"] == "1360.00", f"invoiced net this year {cli[0]['invoiced'] if cli else None}")
    check(k["revenue"]["year"] != "0.00", f"revenue this year from the old invoice paid this year {k['revenue']['year']}")

# the cache: the second call answers from it, a change shows at once
r1 = Fr.get(B + "/api/office/kpi")
r2 = Fr.get(B + "/api/office/kpi")
check(r1.ok and r2.ok and r1.json() == r2.json(), "the tile answers twice the same")
n1, n2 = nstmt(r1), nstmt(r2)
check(0 < n2 < n1, f"#4187 the second call comes from the short cache: {n1} -> {n2} statements")
print(f"PERF kpi statements first {n1}, cached {n2}")
open0 = r2.json()["invoices"]["open"]
pay(OLD_OPEN, TODAY, "19.00")
j = Fr.get(B + "/api/office/kpi").json()
check(j["invoices"]["open"]["amount"] != open0["amount"], f"#4187 a payment shows at once (no old figures) {open0} -> {j['invoices']['open']}")
dbx("UPDATE office_docs SET status='paid' WHERE id=?", (OLD_OPEN,))
j = Fr.get(B + "/api/office/kpi").json()
check(j["invoices"]["open"]["count"] == open0["count"] - 1, f"#4187 a status changed past the app shows at once {j['invoices']['open']}")
h0 = [x for x in j["clients"] if x["id"] == CID][0]["hours"]
r = Fr.post(B + "/api/time/entries", json={"list_id": LID, "start": f"{TODAY}T06:00:00Z", "minutes": 60})
check(r.ok, "a time entry through the app " + r.text[:200])
j = Fr.get(B + "/api/office/kpi").json()
h1 = [x for x in j["clients"] if x["id"] == CID][0]["hours"]
check(h1 > h0, f"#4187 a new time entry shows at once in the client's hours {h0} -> {h1}")
# another person, another office: never the first one's figures
gd = doc("invoice", "RE-1", "issued", f"{Y}-01-10", 10, 11.9, oid=OID_G)
check(gd, "setup: gerda's invoice")
jg = Gr.get(B + "/api/office/kpi").json()
check(jg["invoices"]["open"]["count"] == 1 and not [x for x in jg["clients"] if x["id"] == CID],
      f"#4187 gerda sees only her own office's figures {jg['invoices']}")

# the office list: a derived state / a sort reads the full rows only for the page (the same rows as before)
r = Fr.get(B + "/api/office/docs?kind=invoice&status=open")
check(r.ok and {x["id"] for x in r.json()["docs"]} == {THIS, USD}, f"the open invoices of the list {[x['number'] for x in r.json().get('docs', [])]}")
r = Fr.get(B + "/api/office/docs?kind=invoice&sort=amount&dir=desc&limit=3")
d = r.json()["docs"] if r.ok else []
check([x["number"] for x in d] == ["RE-4", "RE-7", "RE-6"] and r.json()["next_cursor"] == "@3" and "recipient" in json.dumps(d[0]),
      f"sorted by amount, the page of 3 with whole rows {[x['number'] for x in d]}")
r = Fr.get(B + "/api/office/docs?kind=invoice&sort=amount&dir=desc&limit=3&before=@3")
check(r.ok and r.json()["docs"][0]["number"] == "RE-5", "the next page goes on " + str([x["number"] for x in r.json().get("docs", [])]))

sys.exit(kt.done("p2525_b_kpi"))
