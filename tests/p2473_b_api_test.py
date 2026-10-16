#!/usr/bin/env python3
"""2.47.3 API tests, part B (office: travel expenses + cash flow), own container (start.sh, org encryption on). Invented
companies, people and figures only.
 - #1022: a trip with participants (people of the area + free names), purpose, client, project and receipts (categories,
   foreign currency with its rate -> amount in the office currency); edit, delete and post back (the undo); the receipts
   not ticked "in DATEV" (count, filter of the evaluation); the evaluation by month / year / person (shared equally) /
   project / client / category and as CSV; billing receipts on to a draft quotation (purchase = amount, markup), never
   twice, the undo takes the positions back out, a finalised document refuses; amounts / participants encrypted at rest
 - #1652: payments (actual), the open rest of a finalised invoice on its due day, the rest of an accepted quotation after a
   part invoice at the end of its period of service, purchases of accepted quotations, travel receipts and fixed costs
   (once / monthly / quarterly / yearly, end date) land in the right month as actual or planned; 3 / 6 months; fixed costs
   CRUD + encrypted
 - rights: a member gets 403 everywhere, another organisation sees nothing and reaches nothing (404)
usage: p2473_b_api_test.py <datadir>"""
import base64
import csv
import datetime
import io
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

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


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
O = "/api/office"
D = O + "/docs"
T = O + "/trips"
TODAY = datetime.date.today().isoformat()
M0 = TODAY[:7]
M1, M2, M3 = ym_add(M0, 1), ym_add(M0, 2), ym_add(M0, 3)
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                     "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]

# ---------------------------------------------------------------- #1022 trips and receipts
j = A.get(B + T).json()
check(j["trips"] == [] and j["missing"] == 0 and {p["id"] for p in j["people"]} >= {ALICE, BOB} and [c["key"] for c in j["categories"]][:3] == ["car", "train", "flight"]
      and any(c["id"] == CL for c in j["clients"]) and not any(c["id"] == CL2 for c in j["clients"]), f"#1022: the empty list with people, clients, categories {j.get('people')}")
r = A.post(B + T, json={"date_from": "2025-09-03", "date_to": "2025-09-05", "dest": "Hamburg - Berlin", "overnight": True, "people": [{"id": ALICE}, {"id": BOB}, {"name": "Externe Person"}],
                        "purpose": "job", "client_id": CL, "project": "Film eins", "km": 12, "note": "Drehreise",
                        "items": [{"date": "2025-09-03", "category": "train", "amount": "129,90", "text": "ICE"},
                                  {"date": "2025-09-04", "category": "hotel", "amount": 330, "currency": "USD", "fx_rate": "1.10"}]})
check(r.status_code == 201, "#1022: a trip with receipts " + r.text[:200])
TR = r.json()
check(TR["total"] == "429.90" and TR["items"][1]["amount_home"] == "300.00" and TR["items"][1]["currency"] == "USD" and TR["missing"] == 2 and TR["overnight"] == 1
      and [p.get("name") for p in TR["people"]] == ["Alice Admin", "Bob Member", "Externe Person"] and TR["km"] == "12.00",
      f"#1022: amounts in the office currency (330 USD / 1.10 = 300), participants with names {TR.get('total')} {TR.get('people')}")
check(A.post(B + T, json={"date_from": "2025-09-01", "people": [{"id": CAROL}]}).status_code == 400, "#1022: a person outside the area is refused")
check(A.post(B + T, json={"date_from": "2025-09-01", "client_id": CL2}).status_code == 400, "#1022: a client of another organisation is refused")
check(A.post(B + T, json={"date_from": "2025-09-05", "date_to": "2025-09-01"}).status_code == 400, "#1022: the end before the start is refused")
check(A.post(B + f"{T}/{TR['id']}/items", json={"amount": 10, "currency": "GBP"}).status_code == 400, "#1022: a foreign currency without its rate is refused")
check(A.post(B + f"{T}/{TR['id']}/items", json={"amount": 10, "category": "spaceship"}).status_code == 400, "#1022: an unknown category is refused")
r = A.post(B + f"{T}/{TR['id']}/items", json={"date": "2025-09-05", "category": "meals", "amount": "40.00", "currency": "GBP", "amount_home": "46.50"})
check(r.status_code == 201 and r.json()["items"][-1]["amount_home"] == "46.50", "#1022: a foreign amount with the amount from the bank statement " + r.text[:160])
IT3 = r.json()["item_id"]
r = A.patch(B + f"{T}/{TR['id']}/items/{TR['items'][0]['id']}", json={"datev": 1, "datev_no": "BN-0815"})
check(r.ok and r.json()["missing"] == 2 and r.json()["items"][0]["datev_no"] == "BN-0815", "#1022: the tick in DATEV + number")
check(A.get(B + T).json()["missing"] == 2, "#1022: the count of receipts not in DATEV")
r = A.patch(B + T + f"/{TR['id']}", json={"dest": "Hamburg - Berlin - Hamburg"})
check(r.ok and r.json()["dest"] == "Hamburg - Berlin - Hamburg" and r.json()["client_id"] == CL and len(r.json()["people"]) == 3, "#1022: editing one field keeps the others")
r = A.patch(B + f"{T}/{TR['id']}/items/{TR['items'][1]['id']}", json={"fx_rate": "1.20"})
check(r.ok and r.json()["items"][1]["amount_home"] == "275.00", "#1022: a new rate recomputes the amount (330 / 1.20) " + r.text[:120])
r = A.delete(B + f"{T}/{TR['id']}/items/{IT3}")
check(r.ok and r.json()["item"]["amount_home"] == "46.50" and len(r.json()["trip"]["items"]) == 2, "#1022: deleting a receipt answers it for the undo")
TR2 = A.post(B + T, json={"date_from": "2025-10-01", "dest": "Recherche Köln", "purpose": "acquisition", "people": [{"name": "Externe Person"}],
                          "items": [{"date": "2025-10-01", "category": "car", "amount": 60}]}).json()
# evaluation
rep = lambda by, q="": A.get(B + f"{T}/report?by={by}{q}").json()
j = rep("month")
check([(g["key"], g["amount"]) for g in j["rows"]] == [("2025-09", "404.90"), ("2025-10", "60.00")] and j["total"] == "464.90", f"#1022: sums by month {j['rows']}")
check([(g["key"], g["amount"]) for g in rep("year")["rows"]] == [("2025", "464.90")], "#1022: sums by year")
j = rep("person")
pp = {g["label"]: g["amount"] for g in j["rows"]}
check(pp == {"Alice Admin": "134.97", "Bob Member": "134.97", "Externe Person": "194.97"}, f"#1022: by person, shared equally {pp}")
j = rep("client")
check({g["label"]: g["amount"] for g in j["rows"]} == {"Kunde Eins GmbH": "404.90", "Acquisition / research": "60.00"}, f"#1022: by client {j['rows']}")
check({g["label"]: g["amount"] for g in rep("project")["rows"]} == {"Film eins": "404.90", "Acquisition / research": "60.00"}, "#1022: by project")
j = rep("category")
check([(g["key"], g["amount"]) for g in j["rows"]] == [("hotel", "275.00"), ("train", "129.90"), ("car", "60.00")], f"#1022: by category {j['rows']}")
check(rep("category", "&missing=1")["total"] == "335.00", "#1022: only the receipts not in DATEV")
check(rep("month", "&from=2025-10-01&to=2025-10-31")["total"] == "60.00", "#1022: a period")
check(A.get(B + f"{T}/report?by=nonsense").status_code == 400, "#1022: an unknown grouping is refused")
r = A.get(B + f"{T}/report?by=category&format=csv")
rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿")), delimiter=";"))
check(r.ok and "text/csv" in r.headers.get("Content-Type", "") and rows[0][0] == "Category" and rows[1] == ["Hotel", "1", "275,00"] and rows[-1] == ["Total", "3", "464,90"],
      f"#1022: the CSV {rows}")
# billing on
Q = A.post(B + D, json={"project_title": "Film eins", "client_id": CL}).json()
docs = A.get(B + f"{T}/bill-docs?client_id={CL}").json()["docs"]
check(docs and docs[0]["id"] == Q["id"], "#1022: the client's draft quotation is offered first")
ids = [x["id"] for x in TR["items"]]
r = A.post(B + f"{T}/bill", json={"doc_id": Q["id"], "item_ids": ids, "markup_pct": 10})
check(r.ok and len(r.json()["positions"]) == 2, "#1022: billed on " + r.text[:160])
BJ = r.json()
d = A.get(B + f"{D}/{Q['id']}").json()
its = [(i["title"], i["rate"], i.get("cost"), i["intext"], i["unit"]) for i in d["items"]]
check(its == [("Bahn: ICE", 142.89, 129.9, "extern", "flat"), ("Hotel", 302.5, 275, "extern", "flat")], f"#1022: positions in the document's language (German) with purchase = amount, rate + 10 % {its}")
check(A.post(B + f"{T}/bill", json={"doc_id": Q["id"], "item_ids": [ids[0]]}).status_code == 409, "#1022: a receipt is never billed twice")
check(all(i["billed"] and i["billed"]["id"] == Q["id"] for i in A.get(B + T).json()["trips"][1]["items"]), "#1022: the receipts show where they were billed")
r = A.post(B + f"{T}/unbill", json={"item_ids": BJ["items"], "positions": BJ["positions"]})
check(r.ok and r.json()["removed"] == 2 and A.get(B + f"{D}/{Q['id']}").json()["items"] == [], "#1022: the undo takes the positions back out")
r = A.post(B + f"{T}/bill", json={"doc_id": Q["id"], "item_ids": ids, "one": 1})
d = A.get(B + f"{D}/{Q['id']}").json()
check(r.ok and len(d["items"]) == 1 and d["items"][0]["title"] == "Reisekosten" and d["items"][0]["cost"] == 404.9, f"#1022: one position for all {d['items']}")
check(A.post(B + f"{T}/bill", json={"doc_id": 999999, "item_ids": [TR2["items"][0]["id"]]}).status_code == 404, "#1022: an unknown document is 404")
# delete + post back (undo)
r = A.delete(B + T + f"/{TR['id']}")
old = r.json()["trip"]
check(r.ok and not any(t["id"] == TR["id"] for t in A.get(B + T).json()["trips"]), "#1022: a trip is deleted with its receipts")
r = A.post(B + T, json=old)
check(r.status_code == 201 and r.json()["total"] == "404.90" and all(i["billed"] and i["billed"]["id"] == Q["id"] for i in r.json()["items"]),
      "#1022: posting the deleted trip back restores it (still billed) " + r.text[:160])
TRB = r.json()
# encrypted at rest
rows = sql("SELECT amount, amount_home FROM office_trip_items WHERE trip_id=?", (TRB["id"],))
check(rows and all(str(a).startswith("kenc1:") and str(b).startswith("kenc1:") for a, b in rows), "#1022: amounts encrypted at rest")
rows = sql("SELECT people, note FROM office_trips WHERE id=?", (TRB["id"],))
check(str(rows[0][0]).startswith("kenc1:") and str(rows[0][1]).startswith("kenc1:"), "#1022: participants and note encrypted at rest")
# rights
check(all(x.status_code == 403 for x in (Bo.get(B + T), Bo.post(B + T, json={"date_from": "2025-09-01"}), Bo.patch(B + T + f"/{TRB['id']}", json={"dest": "x"}),
                                          Bo.get(B + f"{T}/report?by=month"), Bo.post(B + f"{T}/bill", json={"doc_id": Q["id"], "item_ids": [1]}))),
      "#1022: a member gets 403 (admins only)")
check(Ca.get(B + T).json()["trips"] == [], "#1022: another organisation sees no trips")
check(Ca.patch(B + T + f"/{TRB['id']}", json={"dest": "x"}).status_code == 404 and Ca.delete(B + T + f"/{TRB['id']}").status_code == 404
      and Ca.post(B + f"{T}/{TRB['id']}/items", json={"amount": 1}).status_code == 404, "#1022: another organisation reaches nothing (404)")
check(Ca.post(B + f"{T}/bill", json={"doc_id": Q["id"], "item_ids": [TRB["items"][0]["id"]]}).status_code == 404, "#1022: another organisation cannot bill foreign receipts")
# the same trip flow in a personal office (person without organisation, part A) + a second person sees nothing
for u, n in (("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Do, Er = sess("dora"), sess("erik")
for s in (Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
DORA = Do.get(B + "/api/state").json()["me"]["id"]
check(Do.get(B + O + "/settings").json().get("role") == "admin", "#1360: a person without organisation is admin of their own office")
Do.put(B + O + "/settings", json={"company_fields": {"name": "Dora Film", "street": "Musterweg 2", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins"}).json()["id"]
r = Do.post(B + T, json={"date_from": "2025-09-03", "dest": "Hamburg", "people": [{"id": DORA}, {"name": "Externe Person"}], "purpose": "job", "client_id": CLP,
                         "items": [{"date": "2025-09-03", "category": "train", "amount": "100,00"},
                                   {"date": "2025-09-03", "category": "hotel", "amount": 220, "currency": "USD", "fx_rate": "1.10"}]})
check(r.status_code == 201 and r.json()["total"] == "300.00", "#1360/#1022: a trip in the personal office " + r.text[:200])
PT = r.json()
check(Do.post(B + T, json={"date_from": "2025-09-01", "people": [{"id": ALICE}]}).status_code == 400, "#1360/#1022: a person outside the area is refused (personal office)")
check(Do.post(B + T, json={"date_from": "2025-09-01", "client_id": CL}).status_code == 400, "#1360/#1022: a client of an organisation is refused (personal office)")
j = Do.get(B + f"{T}/report?by=person").json()
check({g["label"]: g["amount"] for g in j["rows"]} == {"Dora Frei": "150.00", "Externe Person": "150.00"}, f"#1360/#1022: by person in the personal office {j['rows']}")
Pq = Do.post(B + D, json={"project_title": "Privatfilm", "client_id": CLP}).json()
r = Do.post(B + f"{T}/bill", json={"doc_id": Pq["id"], "item_ids": [x["id"] for x in PT["items"]], "markup_pct": 0})
check(r.ok and len(r.json()["positions"]) == 2, "#1360/#1022: billed on to a quotation of the personal office " + r.text[:160])
PB = r.json()
check(Do.post(B + f"{T}/bill", json={"doc_id": Pq["id"], "item_ids": [PT["items"][0]["id"]]}).status_code == 409, "#1360/#1022: never billed twice (personal office)")
r = Do.post(B + f"{T}/unbill", json={"item_ids": PB["items"], "positions": PB["positions"]})
check(r.ok and r.json()["removed"] == 2, "#1360/#1022: the undo takes the positions back out (personal office)")
r = Do.delete(B + T + f"/{PT['id']}")
old = r.json()["trip"]
r = Do.post(B + T, json=old)
check(r.status_code == 201 and r.json()["total"] == "300.00", "#1360/#1022: delete + post back (personal office)")
PT = r.json()
rows = sql("SELECT amount FROM office_trip_items WHERE trip_id=?", (PT["id"],))
check(rows and all(str(r_[0]).startswith("kenc1:") for r_ in rows), "#1360/#1022: amounts encrypted at rest (personal office)")
# nobody else reaches it: another person without organisation, a member of an organisation, an organisation admin
check(Er.get(B + T).json()["trips"] == [] and Ca.get(B + T).json()["trips"] == [] and A.get(B + T).json()["trips"] != [], "#1360/#1022: the trips of a personal office stay private")
check(all(x.status_code == 404 for x in (Er.patch(B + T + f"/{PT['id']}", json={"dest": "x"}), Er.delete(B + T + f"/{PT['id']}"), Ca.post(B + f"{T}/{PT['id']}/items", json={"amount": 1}))),
      "#1360/#1022: other people reach nothing of a personal office (404)")
check(Er.post(B + f"{T}/bill", json={"doc_id": Pq["id"], "item_ids": [PT["items"][0]["id"]]}).status_code == 404, "#1360/#1022: others cannot bill foreign receipts")
check(not any(t["id"] == PT["id"] for t in A.get(B + T).json()["trips"]), "#1360/#1022: not even an admin of an organisation sees it")

# ---------------------------------------------------------------- #1652 cash flow
F = O + "/fixed-costs"
r = A.post(B + F, json={"label": "Miete", "amount": "1200", "start": M0 + "-01", "repeat": "monthly"})
check(r.status_code == 201 and r.json()["amount"] == "1200.00", "#1652: a fixed cost " + r.text[:120])
FM = r.json()["id"]
A.post(B + F, json={"label": "Software", "amount": "600", "start": M1 + "-15", "repeat": "yearly"})
A.post(B + F, json={"label": "Steuerberatung", "amount": "300", "start": M2 + "-05", "repeat": "once"})
A.post(B + F, json={"label": "Versicherung", "amount": "90", "start": M0 + "-01", "repeat": "quarterly", "until": M3 + "-28"})
check(A.post(B + F, json={"label": "x", "amount": "-5", "start": M0 + "-01"}).status_code == 400 and A.post(B + F, json={"label": "x", "amount": "5", "start": M0 + "-01", "repeat": "weekly"}).status_code == 400,
      "#1652: a negative amount / unknown repeat is refused")
check(str(sql("SELECT amount FROM office_fixed_costs WHERE id=?", (FM,))[0][0]).startswith("kenc1:"), "#1652: fixed costs encrypted at rest")
# an accepted quotation, a part invoice from it (finalised, part paid)
Q2 = A.post(B + D, json={"project_title": "Film zwei", "client_id": CL, "service_from": M1 + "-02", "service_to": M1 + "-20"}).json()
G = A.put(B + f"{D}/{Q2['id']}/items", json={"items": [{"kind": "service", "title": "Dreh", "qty": 2, "unit": "day", "rate": 1000, "cost": 300, "intext": "extern"}]}).json()["totals"]["gross"]
for st in ("sent", "accepted"):
    A.post(B + f"{D}/{Q2['id']}/status", json={"status": st})
INV = A.post(B + f"{D}/{Q2['id']}/invoice").json()
G1 = A.put(B + f"{D}/{INV['id']}/items", json={"items": [{"kind": "service", "title": "Dreh Teil 1", "qty": 1, "unit": "day", "rate": 1000}]}).json()["totals"]["gross"]
A.patch(B + f"{D}/{INV['id']}", json={"recipient": {"name": "Kunde Eins GmbH", "lines": ["Weg 2", "10115 Berlin"]}, "service_from": M0 + "-01", "service_to": M0 + "-02"})
r = A.post(B + f"{D}/{INV['id']}/finalize")
check(r.ok, "the part invoice is finalised " + r.text[:200])
DUE = r.json().get("due_date") or TODAY
check(A.post(B + f"{D}/{INV['id']}/payments", json={"date": TODAY, "amount": 500}).status_code == 201, "a part payment")
# travel receipts: today (actual) and in two months (planned)
A.post(B + T, json={"date_from": TODAY, "dest": "Kurztrip", "items": [{"date": TODAY, "category": "taxi", "amount": 25}, {"date": M2 + "-10", "category": "flight", "amount": 410}]})

cf = A.get(B + O + f"/cashflow?from={M0}&months=6").json()
check([x["month"] for x in cf["rows"]] == [ym_add(M0, i) for i in range(6)] and cf["rows"][0]["current"] and cf["currency"] == "EUR", "#1652: six months from this one")
E = cf["entries"]
by = lambda k: [e for e in E if e["kind"] == k]
check([(e["month"], e["state"], e["amount"], e["dir"]) for e in by("payment")] == [(M0, "actual", "500.00", "in")], f"#1652: the payment is actual in this month {by('payment')}")
inv_e = by("invoice")
check(len(inv_e) == 1 and inv_e[0]["state"] == "plan" and inv_e[0]["month"] == max(DUE, TODAY)[:7] and float(inv_e[0]["amount"]) == round(float(G1) - 500, 2),
      f"#1652: the open rest of the invoice on its due day {inv_e} due {DUE}")
off = by("offer")
check(len(off) == 1 and off[0]["month"] == M1 and off[0]["date"] == M1 + "-20" and float(off[0]["amount"]) == round(float(G) - float(G1), 2) and off[0]["partial"],
      f"#1652: the accepted quotation: only the rest after the part invoice, at the end of the period of service {off}")
pur = by("purchase")
check([(e["month"], e["state"], e["amount"]) for e in pur] == [(M1, "plan", "600.00")], f"#1652: the purchase of the accepted quotation {pur}")
tr_ = by("trip")
check(sorted((e["month"], e["state"], e["amount"]) for e in tr_) == sorted([(M0, "actual", "25.00"), (M2, "plan", "410.00")]), f"#1652: travel receipts actual / planned {tr_}")
fx = by("fixed")
rent = [e for e in fx if e["label"] == "Miete"]
check([e["month"] for e in rent] == [ym_add(M0, i) for i in range(6)] and rent[0]["state"] == "actual" and all(e["state"] == "plan" for e in rent[1:]),
      f"#1652: the monthly rent in every month, this month's (day 1) actual {[(e['month'], e['state']) for e in rent]}")
check([e["month"] for e in fx if e["label"] == "Software"] == [M1], "#1652: yearly once within six months")
check([e["month"] for e in fx if e["label"] == "Steuerberatung"] == [M2], "#1652: once")
check([e["month"] for e in fx if e["label"] == "Versicherung"] == [M0, M3], "#1652: quarterly until its end")
row1 = cf["rows"][1]
exp_out = 1200 + 600 + 600
check(float(row1["out"]["plan"]) == exp_out and float(row1["in"]["plan"]) == round(float(G) - float(G1), 2) + (float(inv_e[0]["amount"]) if inv_e[0]["month"] == M1 else 0),
      f"#1652: the sums of next month {row1}")
row0 = cf["rows"][0]
check(float(row0["in"]["actual"]) == 500 and float(row0["out"]["actual"]) == 1200 + 90 + 25 and
      float(row0["balance"]) == round(float(row0["in"]["actual"]) + float(row0["in"]["plan"]) - float(row0["out"]["actual"]) - float(row0["out"]["plan"]), 2),
      f"#1652: actual and balance of this month {row0}")
check(len(A.get(B + O + f"/cashflow?from={M0}&months=3").json()["rows"]) == 3 and len(A.get(B + O + "/cashflow").json()["rows"]) == 3, "#1652: three months (also the default)")
check(A.get(B + O + "/cashflow?months=13").status_code == 400 and A.get(B + O + "/cashflow?from=2026-13").status_code == 400, "#1652: a bad period is refused")
# fixed costs: edit, delete answers it for the undo
r = A.patch(B + f"{F}/{FM}", json={"until": M1 + "-28"})
check(r.ok and r.json()["until"] == M1 + "-28" and [e["month"] for e in A.get(B + O + f"/cashflow?from={M0}&months=6").json()["entries"] if e.get("fixed_id") == FM] == [M0, M1],
      "#1652: an end date stops the repeat")
r = A.delete(B + f"{F}/{FM}")
check(r.ok and r.json()["item"]["label"] == "Miete" and not any(f["id"] == FM for f in A.get(B + F).json()["items"]), "#1652: delete answers the entry")
# rights
check(Bo.get(B + O + "/cashflow").status_code == 403 and Bo.get(B + F).status_code == 403 and Bo.post(B + F, json={"label": "x", "amount": 1, "start": TODAY}).status_code == 403,
      "#1652: a member gets 403")
cf2 = Ca.get(B + O + f"/cashflow?from={M0}&months=6").json()
check(cf2["entries"] == [] and Ca.get(B + F).json()["items"] == [], "#1652: another organisation sees nothing")
check(Ca.patch(B + f"{F}/{FM + 1}", json={"label": "x"}).status_code == 404, "#1652: another organisation cannot change fixed costs")
# the cash flow of a personal office (person without organisation, part A) + a second person sees nothing
PF = Do.post(B + F, json={"label": "Atelier", "amount": "400", "start": M0 + "-01", "repeat": "monthly"})
check(PF.status_code == 201 and PF.json()["amount"] == "400.00", "#1360/#1652: a fixed cost in the personal office " + PF.text[:120])
PFI = PF.json()["id"]
Pq2 = Do.post(B + D, json={"project_title": "Privatfilm zwei", "client_id": CLP, "service_from": M1 + "-02", "service_to": M1 + "-20"}).json()
PG = Do.put(B + f"{D}/{Pq2['id']}/items", json={"items": [{"kind": "service", "title": "Dreh", "qty": 1, "unit": "day", "rate": 1000, "cost": 200, "intext": "extern"}]}).json()["totals"]["gross"]
for st in ("sent", "accepted"):
    Do.post(B + f"{D}/{Pq2['id']}/status", json={"status": st})
Do.post(B + T, json={"date_from": TODAY, "dest": "Kurztrip", "items": [{"date": TODAY, "category": "taxi", "amount": 20}]})
pcf = Do.get(B + O + f"/cashflow?from={M0}&months=6").json()
PE = pcf["entries"]
pby = lambda k: [e for e in PE if e["kind"] == k]
check(len(pcf["rows"]) == 6 and pcf["rows"][0]["current"], "#1360/#1652: six months (personal office)")
check([(e["month"], e["state"]) for e in pby("fixed")][:2] == [(M0, "actual"), (M1, "plan")] and len(pby("fixed")) == 6, f"#1360/#1652: the monthly fixed cost {pby('fixed')}")
check(len(pby("offer")) == 1 and pby("offer")[0]["month"] == M1 and float(pby("offer")[0]["amount"]) == float(PG), f"#1360/#1652: the accepted quotation lands in its month {pby('offer')}")
check([(e["month"], e["amount"]) for e in pby("purchase")] == [(M1, "200.00")], f"#1360/#1652: its purchase {pby('purchase')}")
check([(e["month"], e["state"], e["amount"]) for e in pby("trip")] == [(M0, "actual", "20.00")], f"#1360/#1652: the travel receipt {pby('trip')}")
check(str(sql("SELECT amount FROM office_fixed_costs WHERE id=?", (PFI,))[0][0]).startswith("kenc1:"), "#1360/#1652: fixed cost encrypted at rest (personal office)")
ecf = Er.get(B + O + f"/cashflow?from={M0}&months=6").json()
check(ecf["entries"] == [] and Er.get(B + F).json()["items"] == [], "#1360/#1652: another person sees none of it")
check(Ca.get(B + F).json()["items"] == [] or all(i["label"] != "Atelier" for i in Ca.get(B + F).json()["items"]), "#1360/#1652: nor does a person of an organisation")
check(Er.patch(B + f"{F}/{PFI}", json={"label": "x"}).status_code == 404 and Er.delete(B + f"{F}/{PFI}").status_code == 404, "#1360/#1652: others cannot change or delete it (404)")
check(not any(e["label"] == "Atelier" for e in A.get(B + O + f"/cashflow?from={M0}&months=6").json()["entries"] if e["kind"] == "fixed"), "#1360/#1652: not in the cash flow of an organisation")
check(Do.delete(B + f"{F}/{PFI}").status_code == 200, "#1360/#1652: the owner deletes it")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
