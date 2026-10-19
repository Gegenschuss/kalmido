#!/usr/bin/env python3
"""2.120.0 API tests, part D: delivery notes / proofs of service (#2089) and the timesheet of an invoice (#2089).
Own container (start.sh). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - delivery note = document kind "delivery": made from a quotation / an invoice (positions without prices, no discounts, source
   noted) or free; own number series (LS-{yyyy}-{seq:03}, settings delivery_scheme, number at finalising); title "Lieferschein" /
   "Leistungsnachweis" (delivery_title); the print model has noprice, no totals, no payment info; own list, not in the invoice list;
   finalising needs recipient and one position only (no tax, bank data or period); status sent, never paid; no e-invoice XML
 - timesheet of an invoice: PDF of the time entries of the client's lists in the period of service; 400 without client / period /
   entries and for other kinds; the part of a member without the office module 403; another organisation 404
 - a person without organisation (personal office) does everything
usage: p2120_d_api_test.py <datadir>      (P2120D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import re
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time"
O = "/api/office"
D = O + "/docs"


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def item(title, qty, rate, unit="day"):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


def entry(user_id, list_id, start, end, secs, note):
    sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, list_id, "Schnitt", start, end, secs, note, "manual", end, end), write=True)


if os.environ.get("P2120D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("eve", "Eve Nooffice")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Ev = sess("bob"), sess("carol"), sess("eve")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Ev.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,clients,docs", "tour": "done"})  # no office
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for em in ("bob@example.com", "eve@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": em, "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ev, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]

# ================================================================ a delivery note from a quotation
r = A.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Filmprojekt", "items": [item("Kamera", 2, 500), item("Schnitt", 3, 400),
                                                                                                    {"kind": "heading", "title": "Nachbereitung"}]})
OFF = r.json()["id"]
A.put(B + f"{D}/{OFF}/items", json={"items": [item("Kamera", 2, 500), item("Schnitt", 3, 400), {"kind": "heading", "title": "Nachbereitung"},
                                              {"kind": "discount", "title": "Rabatt", "qty": 1, "unit": "flat", "rate": 50, "tax": "standard"}]})
r = A.post(B + f"{D}/{OFF}/delivery", json={})
check(r.status_code == 201 and r.json()["kind"] == "delivery" and r.json()["status"] == "draft", "delivery from a quotation " + r.text[:200])
LS = r.json()["id"]
d = r.json()
titles = [(x["kind"], x["title"]) for x in d["items"]]
check(titles == [("service", "Kamera"), ("service", "Schnitt"), ("heading", "Nachbereitung")], f"positions without the discount: {titles}")
check(all(float(x["rate"]) == 0 for x in d["items"] if x["kind"] == "service") and float(d["items"][0]["qty"]) == 2, "no prices, quantities kept")
check(d["client_id"] == CL and d["project_title"] == "Filmprojekt" and d["number"] == "" and d["number_at_finalize"], "client / project taken over, number at finalising")
check(sql("SELECT source_doc_id FROM office_docs WHERE id=?", (LS,))[0][0] == OFF, "source noted")
check(A.post(B + f"{D}/{LS}/delivery", json={}).status_code == 409, "no delivery note from a delivery note")
cr = A.post(B + D, json={"kind": "credit"}).json()["id"]
check(A.post(B + f"{D}/{cr}/delivery", json={}).status_code == 409, "no delivery note from a credit note")
# lists
check([x["id"] for x in A.get(B + D + "?kind=delivery").json()["docs"]] == [LS], "own list")
check(all(x["kind"] != "delivery" for k in ("offer", "invoice", "credit", "reminder") for x in A.get(B + D + f"?kind={k}").json()["docs"]), "not in the other lists")
# title choice
check(A.patch(B + f"{D}/{LS}", json={"delivery_title": "bogus"}).status_code == 400, "title choice validated")
rd = A.get(B + f"{D}/{LS}/render").json()
check(rd["title"] == "Lieferschein" and rd["noprice"] is True and rd["totals"]["rows"] == [] and rd["payment"] is None and rd["signature"] == "", f"print model {rd['title']}")
check(rd["receipt_label"], "receipt label")
check(A.patch(B + f"{D}/{LS}", json={"delivery_title": "service"}).json()["delivery_title"] == "service", "proof of service")
check(A.get(B + f"{D}/{LS}/render").json()["title"] == "Leistungsnachweis", "title Leistungsnachweis")
pdf = A.get(B + f"{D}/{LS}/pdf")
check(pdf.ok and pdf.content[:5] == b"%PDF-", "draft PDF")
# finalising: own number series
r = A.post(B + f"{D}/{LS}/finalize")
check(r.status_code == 200 and re.fullmatch(r"LS-\d{4}-001", r.json()["number"]) and r.json()["locked"] and r.json()["status"] == "issued", "finalised with LS number " + r.text[:200])
check(A.get(B + f"{D}/{LS}/pdf").content[:5] == b"%PDF-", "stored PDF")
check(A.get(B + f"{D}/{LS}/xml").status_code == 409, "no e-invoice XML")
check(A.patch(B + f"{D}/{LS}", json={"project_title": "x"}).status_code == 409, "finalised: no change")
check(A.post(B + f"{D}/{LS}/status", json={"status": "paid"}).status_code in (400, 409), "never paid")
check(A.post(B + f"{D}/{LS}/send", json={"to": "kunde@example.com"}).status_code == 409, "sending without SMTP: 409")
check(A.post(B + f"{D}/{LS}/status", json={"status": "sent"}).json()["status"] == "sent", "status sent")
check(A.post(B + f"{D}/{LS}/payments", json={"amount": 1}).status_code in (400, 404, 409), "no payments")
# free delivery note: only recipient + one position needed, no company data
r = A.post(B + D, json={"kind": "delivery", "client_id": CL, "items": [item("Lieferung", 1, 0, "flat")]})
check(r.status_code == 201 and r.json()["kind"] == "delivery", "free delivery note " + r.text[:120])
LS2 = r.json()["id"]
r = A.post(B + f"{D}/{LS2}/finalize")
check(r.ok and r.json()["number"].endswith("-002"), "second number " + r.text[:160])
EM = A.post(B + D, json={"kind": "delivery"}).json()["id"]
r = A.post(B + f"{D}/{EM}/finalize")
check(r.status_code == 400 and "position" in r.json().get("error", ""), "an empty delivery note cannot be finalised " + r.text[:160])
# number scheme in the settings
r = A.put(B + O + "/settings", json={"delivery_scheme": "LSN-{yy}-{seq:04}"})
check(r.ok and r.json()["settings"]["delivery_scheme"] == "LSN-{yy}-{seq:04}", "delivery_scheme saved " + r.text[:120])
pv = A.get(B + O + "/number-preview", params={"scheme": "LSN-{yy}-{seq:04}", "kind": "delivery"}).json()
check(pv["valid"] and re.fullmatch(r"LSN-\d\d-0001", pv["preview"]), f"preview {pv}")
check(A.get(B + O + "/settings").json()["settings"]["invoice_scheme"].startswith("RE-"), "other schemes unchanged")
# from an invoice
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "service_to": "2026-05-31", "items": [item("Beratung", 4, 100, "hour")]})
INV = r.json()["id"]
r = A.post(B + f"{D}/{INV}/delivery", json={"title": "service"})
check(r.status_code == 201 and r.json()["delivery_title"] == "service" and len(r.json()["items"]) == 1, "from an invoice as proof of service " + r.text[:160])
check(A.post(B + f"{D}/999999/delivery", json={}).status_code == 404, "unknown document 404")

# ================================================================ rights / other organisation
check(Bo.post(B + f"{D}/{OFF}/delivery", json={}).status_code == 201, "a member of the office makes one")
check(Ev.post(B + f"{D}/{OFF}/delivery", json={}).status_code == 403 and Ev.get(B + f"{D}/{LS}/timesheet.pdf").status_code == 403, "a member without the office module 403")
check(Ca.post(B + f"{D}/{OFF}/delivery", json={}).status_code == 404 and Ca.get(B + f"{D}/{LS}/pdf").status_code == 404, "another organisation 404")
check(Ca.get(B + f"{D}/{INV}/timesheet.pdf").status_code == 404, "timesheet of another organisation's invoice 404")
check(all(x["id"] != LS for x in Ca.get(B + D + "?kind=delivery").json()["docs"]), "other organisation's list")

# ================================================================ the timesheet of an invoice
LID = A.post(B + "/api/lists", json={"name": "Projekt Film"}).json()["id"]
A.patch(B + f"/api/lists/{LID}", json={"client_id": CL})
sql("UPDATE lists SET client_id=?, org_id=? WHERE id=?", (CL, ORG, LID), write=True)
entry(ALICE, LID, "2026-05-04T08:00:00Z", "2026-05-04T10:30:00Z", 9000, "Schnitt Akt 1")
entry(ALICE, LID, "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z", 3600, "Farbkorrektur")
entry(ALICE, LID, "2026-06-02T08:00:00Z", "2026-06-02T09:00:00Z", 3600, "ausserhalb")
r = A.get(B + f"{D}/{INV}/timesheet.pdf")
check(r.status_code == 200 and r.content[:5] == b"%PDF-" and "timesheet-" in r.headers.get("Content-Disposition", ""), "timesheet PDF " + r.text[:160] if r.status_code != 200 else "ok")
check(A.get(B + f"{D}/{INV}").json()["timesheet_ok"] is True, "timesheet_ok on the invoice")
check(A.get(B + f"{D}/{INV}/timesheet.pdf?inline=1").headers.get("Content-Disposition", "").startswith("inline"), "inline")
INV2 = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-07-01", "service_to": "2026-07-31", "items": [item("x", 1, 1)]}).json()["id"]
r = A.get(B + f"{D}/{INV2}/timesheet.pdf")
check(r.status_code == 400 and "time entries" in r.json().get("error", ""), "no entries in the period: 400 " + r.text[:120])
INV3 = A.post(B + D, json={"kind": "invoice", "items": [item("x", 1, 1)]}).json()["id"]
check(A.get(B + f"{D}/{INV3}").json()["timesheet_ok"] is False and A.get(B + f"{D}/{INV3}/timesheet.pdf").status_code == 400, "without client / period: 400")
check(A.get(B + f"{D}/{OFF}/timesheet.pdf").status_code == 400 and A.get(B + f"{D}/{LS}/timesheet.pdf").status_code == 400, "only invoices: 400")
check("timesheet_ok" not in A.get(B + f"{D}/{OFF}").json(), "no flag on a quotation")
check(Bo.get(B + f"{D}/{INV}/timesheet.pdf").status_code in (200, 400), "a member: what they see only (no error 500)")

# ================================================================ a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
FC = Fr.post(B + "/api/clients", json={"name": "Privatkunde", "street": "Weg 1", "zip": "20000", "city": "Hamburg", "country": "DE"}).json()["id"]
r = Fr.post(B + D, json={"kind": "offer", "client_id": FC, "items": [item("Beratung", 2, 100)]})
check(r.status_code == 201, "freelancer: quotation " + r.text[:120])
FO = r.json()["id"]
r = Fr.post(B + f"{D}/{FO}/delivery", json={})
check(r.status_code == 201 and r.json()["kind"] == "delivery", "freelancer: delivery note " + r.text[:160])
FL = r.json()["id"]
r = Fr.post(B + f"{D}/{FL}/finalize")
check(r.ok and re.fullmatch(r"LS-\d{4}-001", r.json()["number"]), "freelancer: finalised " + r.text[:160])
check(Fr.get(B + f"{D}/{FL}/pdf").content[:5] == b"%PDF-", "freelancer: PDF")
check([x["id"] for x in Fr.get(B + D + "?kind=delivery").json()["docs"]] == [FL], "freelancer: only the own")
check(A.get(B + f"{D}/{FL}").status_code == 404, "freelancer: the organisation's admin does not reach it")
FLID = Fr.post(B + "/api/lists", json={"name": "Privatprojekt"}).json()["id"]
Fr.patch(B + f"/api/lists/{FLID}", json={"client_id": FC})
entry(FID, FLID, "2026-05-04T08:00:00Z", "2026-05-04T09:30:00Z", 5400, "Konzept")
FI = Fr.post(B + D, json={"kind": "invoice", "client_id": FC, "service_from": "2026-05-01", "service_to": "2026-05-31", "items": [item("Konzept", 1.5, 80, "hour")]}).json()["id"]
r = Fr.get(B + f"{D}/{FI}/timesheet.pdf")
check(r.status_code == 200 and r.content[:5] == b"%PDF-", "freelancer: timesheet " + r.text[:160] if r.status_code != 200 else "ok")
check(Fr.get(B + f"{D}/{INV}/timesheet.pdf").status_code == 404, "freelancer: an organisation's invoice 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
