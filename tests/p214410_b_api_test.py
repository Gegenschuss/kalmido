#!/usr/bin/env python3
"""2.144.10 API tests, part B (#2576): trial documents never reach anything financial.
Own container (start.sh), invented companies and people only (@example.com / .example).
 - an office with real documents (invoice finalised + paid, invoice + credit note, an overdue and an open invoice, an
   accepted quotation): the income statement, the VAT return figures, the DATEV booking batch (check + CSV), the booking
   export (check + CSV), the cash flow, the figures (KPI) and the cash book choice are taken as a snapshot
 - the same kinds again as trial documents (office_docs.trial = 1; set in the database here, part A makes them over the
   API): every snapshot stays exactly the same, the trial numbers appear in no CSV
 - the automatic dunning run suggests a reminder for the overdue real invoice, never for the overdue trial invoice;
   a reminder cannot mix trial and real invoices (400)
 - the bank: a booking naming the trial invoice gets no trial suggestion / candidate, matching it is refused (409)
 - no invoice series from a trial invoice (409), no deal bound to a trial quotation (400), no DATEV copy of it (409)
 - chronology: a trial invoice dated today does not keep a real one dated yesterday from being finalised
 - a person without an organisation (freelancer-matrix: office) gets the same in the personal office
usage: p214410_b_api_test.py <datadir>      (a fresh container; P214410B_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import testclock  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TEST_IBAN = "DE02120300000000202051"
TODAY = testclock.today()  # 2.180.0 B (#2693): the Berlin day of the test clock
YDAY = (TODAY - timedelta(days=1)).isoformat()
# 2.180.0 B (#2693): never last year - the exports below cover YEAR-01-01..today (Jan 1-5 they missed the documents)
EARLY = max(TODAY - timedelta(days=5), TODAY.replace(month=1, day=1)).isoformat()


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P214410B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D = "/api/office/docs"
O = "/api/office"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def setup_office(s):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR", "datev_email": "inbox@example.com",
                                         "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
    check(r.ok, "office settings " + r.text[:200])
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def trial(did):
    dbx("UPDATE office_docs SET trial=1 WHERE id=?", (did,))


def doc(s, cl, kind="invoice", rate=1000, is_trial=False, final=True, day=None):
    b = {"kind": kind, "client_id": cl, "project_title": f"{kind} {rate}", "service_from": (day or TODAY.isoformat()),
         "items": [{"title": "Edit", "qty": 1, "rate": rate}]}
    r = s.post(B + D, json=b)
    check(r.status_code == 201, f"a {kind} " + r.text[:200])
    did = r.json()["id"]
    if is_trial:
        trial(did)
    if day:
        check(s.patch(B + f"{D}/{did}", json={"date": day, "service_from": day}).ok, f"{kind} {did}: date {day}")
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok and r.json().get("locked") is True, f"{kind} {did} finalised " + r.text[:200])
    return did


def number(s, did):
    return s.get(B + f"{D}/{did}").json().get("number") or ""


def pay(s, did, amount):
    r = s.post(B + f"{D}/{did}/payments", json={"date": TODAY.isoformat(), "amount": amount, "method": "transfer"})
    check(r.ok, f"payment on {did} " + r.text[:200])


def credit(s, did, is_trial=False):
    r = s.post(B + f"{D}/{did}/credit")
    check(r.status_code == 201, "a credit note " + r.text[:200])
    cid = r.json()["id"]
    if is_trial:
        trial(cid)
    check(s.post(B + f"{D}/{cid}/finalize").ok, "credit note finalised")
    return cid


def strip(x):
    """A response without what changes on its own between two calls."""
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in ("generated_at", "now", "at")}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


YEAR, MON = TODAY.year, TODAY.month
P = f"?from={YEAR}-01-01&to={TODAY.isoformat()}"
VIEWS = (("income statement", f"{O}/books/euer?year={YEAR}"), ("VAT return figures", f"{O}/books/ustva?year={YEAR}&period=m{MON:02d}"),
         ("VAT return figures (year)", f"{O}/books/ustva?year={YEAR}&period=y"),
         ("DATEV check", f"{O}/datev/extf{P}&check=1"), ("booking export check", f"{O}/books/export{P}&check=1"),
         ("cash flow", f"{O}/cashflow?from={TODAY.isoformat()[:7]}&months=3"), ("figures", f"{O}/kpi"),
         ("cash book choice", f"{O}/cashbooks/links"))
CSVS = (("DATEV batch", f"{O}/datev/extf{P}"), ("booking export", f"{O}/books/export{P}"))


def snapshot(s, who):
    out = {}
    for name, url in VIEWS:
        r = s.get(B + url)
        check(r.ok, f"{who}: {name} answers " + r.text[:200])
        out[name] = strip(r.json()) if r.ok else None
    return out


def csvs(s):
    out = {}
    for name, url in CSVS:
        r = s.get(B + url)
        out[name] = r.content.decode("cp1252", "replace") if r.ok else ""
    return out


def reminders_of(did):
    out = []
    for (refs,) in dbx("SELECT ref_doc_ids FROM office_docs WHERE kind='reminder'"):
        try:
            ids = [int(i) for i in json.loads(refs or "[]")]
        except (TypeError, ValueError):
            ids = []
        if did in ids:
            out.append(ids)
    return out


def area(s, who):
    """The whole check for one office area (an organisation's or a person's own)."""
    cl = setup_office(s)
    # ---------------------------------------------------------------- the real documents
    r1 = doc(s, cl, rate=1000)
    pay(s, r1, "1190.00")
    r2 = doc(s, cl, rate=400)
    credit(s, r2)
    r3 = doc(s, cl, rate=300)  # overdue below
    r4 = doc(s, cl, rate=250)  # open
    qr = doc(s, cl, kind="offer", rate=2000)
    check(s.post(B + f"{D}/{qr}/status", json={"status": "accepted"}).ok, f"{who}: real quotation accepted")
    dbx("UPDATE office_docs SET date=? WHERE id IN (?, ?, ?, ?) OR cancels_id=?", (EARLY, r1, r2, r3, r4, r2))
    dbx("UPDATE office_docs SET due_date=? WHERE id=?", ((TODAY - timedelta(days=20)).isoformat(), r3))
    before, csv0 = snapshot(s, who), csvs(s)
    check(before["DATEV check"] and before["DATEV check"].get("count", 0) >= 3, f"{who}: the DATEV batch has the real documents {before['DATEV check']}")
    check(before["booking export check"] and before["booking export check"].get("documents") == 5,
          f"{who}: the booking export has the four real invoices + the credit note {before['booking export check']}")
    real_inv = {x["id"] for x in (before["cash book choice"] or {}).get("invoices") or []}
    check({r1, r2, r3, r4} <= real_inv, f"{who}: the cash book offers the real invoices {real_inv}")

    # ---------------------------------------------------------------- the same as trial documents
    t1 = doc(s, cl, rate=777, is_trial=True)
    pay(s, t1, "924.63")
    t2 = doc(s, cl, rate=444, is_trial=True)
    tc = credit(s, t2, is_trial=True)
    t3 = doc(s, cl, rate=333, is_trial=True)
    t4 = doc(s, cl, rate=222, is_trial=True)
    qt = doc(s, cl, kind="offer", rate=5000, is_trial=True)
    check(s.post(B + f"{D}/{qt}/status", json={"status": "accepted"}).ok, f"{who}: trial quotation accepted")
    dbx("UPDATE office_docs SET due_date=? WHERE id=?", ((TODAY - timedelta(days=20)).isoformat(), t3))
    check(all(x[0] == 1 for x in dbx("SELECT trial FROM office_docs WHERE id IN (?, ?, ?, ?, ?, ?)", (t1, t2, tc, t3, t4, qt))),
          f"{who}: the trial documents are marked")
    after, csv1 = snapshot(s, who), csvs(s)
    for name, _ in VIEWS:
        a, b = before.get(name), after.get(name)
        check(a == b, f"{who}: {name} unchanged by trial documents\n  before {json.dumps(a)[:600]}\n  after  {json.dumps(b)[:600]}")
    nums = [number(s, x) for x in (t1, t2, tc, t3, t4)]
    for name, _ in CSVS:
        check(csv1[name] and csv1[name] == csv0[name] or (csv1[name] and not any(n and n in csv1[name] for n in nums)),
              f"{who}: {name}: no trial number {nums} " + csv1[name][:300])
    check(t3 not in {x["id"] for x in after["cash book choice"].get("invoices") or []}, f"{who}: the cash book never offers a trial invoice")

    # ---------------------------------------------------------------- dunning
    got = until(lambda: reminders_of(r3), 60)
    check(got, f"{who}: the automatic dunning run suggests a reminder for the overdue real invoice")
    time.sleep(1)
    check(not reminders_of(t3), f"{who}: and never for the overdue trial invoice {reminders_of(t3)}")
    r = s.post(B + D + "/reminder", json={"doc_ids": [r4, t4], "level": 1})
    check(r.status_code == 400, f"{who}: a reminder cannot mix real and trial invoices " + r.text[:200])

    # ---------------------------------------------------------------- bank
    gross4 = s.get(B + f"{D}/{t4}").json()["totals"]["gross"]
    de = TODAY.strftime("%d.%m.%Y")
    amount = f"{float(gross4):.2f}".replace(".", ",")
    csv_text = ("Buchungstag;Valuta;Auftraggeber/Empfänger;Verwendungszweck;IBAN;Betrag\n"
                f"{de};{de};Example Client AG;Rechnung {number(s, t4)};DE89370400440532013000;{amount}\n"
                f"{de};{de};Example Shop;Paper;;-4,50\n")
    mp = {"date": 0, "amount": 5, "amount_in": None, "amount_out": None, "title": 3, "counterpart": 2, "decimal": ",", "date_format": "DD.MM.YYYY"}
    r = s.post(B + O + "/bank/import", json={"text": csv_text, "filename": "account.csv", "mapping": mp})
    check(r.status_code == 201 and r.json().get("count") == 2, f"{who}: bank bookings imported " + r.text[:200])
    tx = next((x for x in s.get(B + O + "/bank/tx").json().get("items") or [] if x.get("purpose", "").startswith("Rechnung")), {})
    check(tx.get("id") and t4 not in [x.get("id") for x in tx.get("suggestions") or [] if x.get("kind") == "invoice"],
          f"{who}: the bank suggests no trial invoice {tx.get('suggestions')}")
    r = s.get(B + O + f"/bank/tx/{tx.get('id')}/candidates")
    cand = (r.json().get("items") or []) if r.ok else []
    check(not any(x["kind"] == "invoice" and x["id"] in (t1, t2, t3, t4) for x in cand), f"{who}: no trial invoice among the candidates {cand}")
    check(any(x["kind"] == "invoice" and x["id"] == r4 for x in cand), f"{who}: the real open invoice is a candidate {cand}")
    r = s.post(B + O + f"/bank/tx/{tx.get('id')}/match", json={"kind": "invoice", "id": t4})
    check(r.status_code == 409, f"{who}: matching a trial invoice is refused " + r.text[:200])

    # ---------------------------------------------------------------- series, deal, DATEV copy
    sr = {"every": "monthly", "start": (TODAY + timedelta(days=40)).isoformat()}
    r = s.post(B + O + "/series", json=dict(sr, template_id=r4))
    check(r.status_code == 201, f"{who}: a series from a real invoice " + r.text[:200])
    r = s.post(B + O + "/series", json=dict(sr, template_id=t4))
    check(r.status_code == 409, f"{who}: no series from a trial invoice " + r.text[:200])
    r = s.post(B + O + "/deals", json={"title": "Example deal"})
    check(r.status_code == 201, f"{who}: a deal " + r.text[:200])
    dl = r.json().get("id")
    check(s.patch(B + O + f"/deals/{dl}", json={"offer_id": qt}).status_code == 400, f"{who}: a deal cannot be bound to a trial quotation")
    check(s.patch(B + O + f"/deals/{dl}", json={"offer_id": qr}).ok, f"{who}: but to a real one")
    check(s.post(B + f"{D}/{t1}/datev").status_code == 409, f"{who}: no DATEV copy of a trial invoice")

    # ---------------------------------------------------------------- chronology
    check(s.get(B + f"{D}/{t1}").json().get("date") == TODAY.isoformat(), f"{who}: the trial invoice is dated today")
    rc = doc(s, cl, rate=111, final=False, day=YDAY)
    r = s.post(B + f"{D}/{rc}/finalize")
    check(r.ok, f"{who}: a real invoice dated yesterday is finalised although a trial one is dated today " + r.text[:200])
    tcy = doc(s, cl, rate=112, final=False, day=YDAY, is_trial=True)
    r = s.post(B + f"{D}/{tcy}/finalize")
    check(r.status_code == 400, f"{who}: the trial series keeps its own order " + r.text[:200])


# ================================================================== an organisation
area(A, "org")

# ================================================================== a person without an organisation (freelancer-matrix: office)
FID, F = freelancer(B, A)
area(F, "freelancer")

print(f"p214410_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
