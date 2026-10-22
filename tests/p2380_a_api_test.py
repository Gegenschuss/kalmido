#!/usr/bin/env python3
"""2.38.0 API tests, part A: invoices, credit notes, payments and reminders of Office & finance (#1021 stage 2, F1), own
container in mode workspaces (start.sh). Invented companies, people and the test IBAN only.
 - 2.39.0 (#1209, mini audit): control characters dropped (client, document title), a sent quotation never back to draft,
   the instance admin sees / moves only clients of own organisations (mode workspaces)
 - an invoice from a quotation: every quotation line becomes a position (producing / raw data / discount condensed),
   rights, framework contract text, recipient, project, PO number and period of service taken over, source_doc_id
 - the parity example (invoice 663 of the template): net 34422.90, 19 % 6540.35, gross 40963.25 as exact strings
 - numbers only with finalising (the draft has none), one series per organisation and kind (RE-/GS-/MA-), a manual
   number only above the series' last value and only in the draft, UNIQUE per organisation
 - required fields before finalising: 400 with the list (recipient, period of service, positions, company data, VAT note)
 - after finalising / sending: head, positions, number and deleting answer 409; status issued only by finalising, never
   back to draft; a sent quotation is locked as well (decision 2026-10-10)
 - credit note: positions copied, cancels_id; finalised over the full amount -> the invoice is cancelled; a partial one
   lowers the open amount
 - payments: part -> state partial, the rest -> paid + paid_at; deleting (admin only) reverts; member cannot delete
 - reminder over open invoices: level / fee / deadline, totals = open amounts + fee, finalised with its own number
 - sending without SMTP: 409 with a readable reason; DATEV route likewise
 - tenant-matrix: office -- the second organisation and a private person: 404 / 400 on every new route; agent 403
usage: p2380_a_api_test.py <datadir>      (P2380_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import dbx as dbxm
import subprocess
import sys

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TEST_IBAN = "DE02120300000000202051"


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


FEAT = "cal,comments,collab,office,clients,time"
if os.environ.get("P2380_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"

# ---------------------------------------------------------------- settings, company, client (invented data)
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"},
                                     "payment_days": 14, "reminder_fee": 5, "reminder_deadline_days": 10, "datev_email": "belege@kanzlei.example"})
check(r.ok, "settings with company fields and invoice defaults " + r.text[:200])
st = A.get(B + O + "/settings").json()["settings"]
check(st.get("invoice_scheme") == "RE-{yyyy}-{seq:03}" and st.get("credit_scheme") == "GS-{yyyy}-{seq:03}" and st.get("reminder_scheme") == "MA-{yyyy}-{seq:03}",
      f"number schemes per kind from the pack: {st.get('invoice_scheme')} {st.get('credit_scheme')} {st.get('reminder_scheme')}")
check(st.get("datev_email") == "belege@kanzlei.example" and st.get("payment_days") == 14 and st.get("einvoice_format") == "zugferd", "invoice settings stored")
check(A.put(B + O + "/settings", json={"datev_email": "nope"}).status_code == 400, "settings: DATEV address validated")
check(A.put(B + O + "/settings", json={"einvoice_format": "pdf"}).status_code == 400, "settings: e-invoice format validated")
r = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "address": "Marktstraße 5\n50667 Köln", "street": "Marktstraße 5", "zip": "50667",
                                     "city": "Köln", "country": "DE", "vat_id": "DE123456789", "customer_no": "K-1001", "payment_terms_days": 30, "rate": 90})
assert r.status_code == 201, r.text
CL = r.json()["id"]
RT = A.post(B + O + "/texts", json={"kind": "rights_time", "key": "unlimited", "text_de": "unbegrenzt", "text_en": "in perpetuity"}).json()["id"]
CT = A.post(B + O + "/contracts", json={"name": "RV Beispielkunde", "client_id": CL, "raw_included": 1, "rights_time_id": RT,
                                        "rights_note_de": "Im Übrigen bleibt es bei den Regelungen unter §3 des RV.",
                                        "rights_note_en": "Otherwise, the provisions set forth in Section 3 of the Agreement (RV) shall remain in effect."}).json()["id"]

# ---------------------------------------------------------------- the quotation that becomes invoice 663 (parity example)
r = A.post(B + D, json={"project_title": "Interaktiver Film (5 Module + Intro)", "client_id": CL, "contract_id": CT, "project_ref": "PO-2026-0001",
                        "service_from": "2026-04-01", "service_to": "2026-05-31", "apply_contract": True,
                        "raw_mode": "none", "prod_quotient": 3, "producing_rate": 600})
assert r.status_code == 201, r.text
OFF = r.json()["id"]
r = A.put(B + f"{D}/{OFF}/items", json={"items": [
    {"kind": "heading", "title": "FILMHERSTELLUNG OHNE ANKAUF VON ROH- UND PROJEKTDATEN"},
    {"title": "Filmherstellung", "qty": 1, "rate": 32840.40, "raw_fee": 0, "producing": 0},
    {"kind": "heading", "title": "Zusatzkosten:"},
    {"title": "Sprachfassung EN", "qty": 1, "rate": 1215},
    {"title": "Cube-Integration in UI", "qty": 1, "rate": 262.5},
    {"title": "Webhosting (3 Monate)", "qty": 1, "rate": 105}]})
check(r.ok and r.json()["totals"]["net"] == 34422.9, "quotation positions " + r.text[:120])
OFFER = A.get(B + f"{D}/{OFF}").json()
check(OFFER["rights"]["time"]["text"] == "unbegrenzt" and "§3 des RV" in OFFER["rights"]["note"], "quotation carries the contract's rights")

# ---------------------------------------------------------------- invoice from the quotation
check(Ca.post(B + f"{D}/{OFF}/invoice").status_code in (400, 404) and Da.post(B + f"{D}/{OFF}/invoice").status_code in (400, 404),
      "tenant-matrix: office -- invoice from a foreign quotation: 404 / 400")
check(requests.post(B + f"{D}/{OFF}/invoice", headers=AGH).status_code == 403, "agent: 403 on invoice creation")
r = Bo.post(B + f"{D}/{OFF}/invoice")
check(r.status_code == 201, "invoice from the quotation " + r.text[:200])
INV = r.json()
IID = INV["id"]
check(INV["kind"] == "invoice" and INV["status"] == "draft" and INV["number"] == "" and INV["number_at_finalize"] is True, "invoice: draft without number")
check(INV["source_doc_id"] == OFF and INV["order_ref"] == "PO-2026-0001" and INV["client_id"] == CL and INV["project_title"] == OFFER["project_title"]
      and INV["service_from"] == "2026-04-01" and INV["service_to"] == "2026-05-31" and INV["contract_id"] == CT, "invoice: head taken over from the quotation")
check(INV["rights"] == OFFER["rights"], "invoice: rights and framework contract text identical")
check(INV["payment_days"] == 30, "invoice: payment days from the client")
check([x["kind"] for x in INV["items"]] == ["heading", "service", "heading", "service", "service", "service"], f"invoice: every quotation line is a position: {[x['kind'] for x in INV['items']]}")
t = INV["totals"]
check(t["net"] == "34422.90" and t["gross"] == "40963.25" and t["tax"] == "6540.35" and t["tax_lines"] == [{"rate_key": "standard", "pct": "19", "base": "34422.90", "amount": "6540.35",
      "base_text": "34.422,90 €", "amount_text": "6.540,35 €", "label": "MwSt. 19 %"}] or (t["net"] == "34422.90" and t["gross"] == "40963.25" and t["tax_lines"][0]["amount"] == "6540.35"),
      f"parity invoice 663: net 34422.90 / 19 % 6540.35 / gross 40963.25 as strings: {t['net']} {t.get('tax')} {t['gross']}")
check(INV["intro"].startswith("Sehr geehrte Damen und Herren,") and "in Rechnung zu stellen" in INV["intro"], f"invoice intro text (DE): {INV['intro'][:60]}")
check("open" in INV and INV["open"] == "40963.25" and INV["paid"] == "0.00", f"invoice: open amount = gross: {INV.get('open')}")
# listing by kind, the quotation list stays as it was
L = A.get(B + D + "?kind=invoice").json()["docs"]
check(len(L) == 1 and L[0]["id"] == IID and L[0]["open"] == "40963.25" and L[0]["state"] == "draft", f"list of invoices with open amount: {L}")
check(all(x["kind"] == "offer" for x in A.get(B + D).json()["docs"]), "list without kind = quotations only")
# a quotation with the producing / raw data / discount automation condenses into positions
# (2.40.1: since 2.40.0 (#1379) a new organisation starts with both rules off: switched on here first)
check(A.put(B + "/api/office/settings", json={"producing_on": 1, "raw_on": 1}).ok, "producing / raw data switched on (#1379)")
r = A.post(B + D, json={"project_title": "Automatik", "client_id": CL, "raw_mode": "included", "discount_pct": 10, "prod_quotient": 3, "producing_rate": 600, "producing_on": 1})  # 2.113.1 (#2251): the office setting no longer switches producing on for a new quotation (only a pack option does); the document does
AUTO = r.json()["id"]
A.put(B + f"{D}/{AUTO}/items", json={"items": [{"title": "Schnitt", "qty": 3, "rate": 1000, "raw_fee": 1, "producing": 1}]})
at = A.get(B + f"{D}/{AUTO}").json()["totals"]
r = A.post(B + f"{D}/{AUTO}/invoice")
ai = r.json()
kinds = [x["kind"] for x in ai["items"]]
check(r.status_code == 201 and kinds == ["service", "service", "service", "discount"], f"automatic lines become positions (producing, raw data, discount): {kinds}")
check(ai["totals"]["net"] == f"{at['net']:.2f}", f"condensed invoice has the quotation's net: {ai['totals']['net']} vs {at['net']}")
A.delete(B + f"{D}/{ai['id']}")

# ---------------------------------------------------------------- editing the draft, required fields, number rules
r = A.patch(B + f"{D}/{IID}", json={"order_ref": "PO-2026-0001-A", "due_date": "2027-06-07", "vat_note": "reverse"})
check(r.ok and r.json()["order_ref"] == "PO-2026-0001-A" and r.json()["due_date"] == "2027-06-07" and r.json()["vat_note"] == "reverse", "invoice head fields " + r.text[:120])
check(A.patch(B + f"{D}/{IID}", json={"vat_note": "x"}).status_code == 400 and A.patch(B + f"{D}/{IID}", json={"payment_days": 999}).status_code == 400, "invoice fields validated")
check(A.post(B + f"{D}/{IID}/status", json={"status": "issued"}).status_code == 409, "status issued only by finalising (409)")
check(A.post(B + f"{D}/{IID}/status", json={"status": "sent"}).status_code == 409, "draft invoice cannot be sent by status (409)")
check(A.post(B + f"{D}/{IID}/status", json={"status": "accepted"}).status_code == 400, "quotation statuses are not invoice statuses (400)")
# manual numbers: scheme + above the series' last value
r = A.post(B + f"{D}/{IID}/number", json={"number": "X-1"})
check(r.status_code == 400 and "scheme" in r.json().get("error", ""), "manual invoice number must follow the scheme " + r.text[:120])
r = A.post(B + f"{D}/{IID}/number", json={"number": "RE-2026-000"})
check(r.status_code == 400 and "above" in r.json().get("error", ""), "manual invoice number must be above the last one " + r.text[:120])
# required fields: an empty invoice draft
r = A.post(B + D, json={"kind": "invoice"})
check(r.status_code == 201 and r.json()["kind"] == "invoice" and r.json()["number"] == "" and r.json()["raw_mode"] == "none", "an empty invoice draft " + r.text[:120])
EMPTY = r.json()["id"]
r = A.post(B + f"{D}/{EMPTY}/finalize")
e = r.json().get("error", "")
check(r.status_code == 400 and "recipient" in e and "period of service" in e and "position" in e, "required fields: 400 with the list " + e[:200])
check(A.post(B + D, json={"kind": "credit"}).status_code == 201 and A.post(B + D, json={"kind": "reminder"}).status_code == 201, "empty credit note / reminder drafts")
check(A.post(B + D, json={"kind": "nope"}).status_code == 400, "unknown kind: 400")
# the VAT note is required for novat invoices
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "vat_mode": "novat", "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
NOVAT = r.json()["id"]
r = A.post(B + f"{D}/{NOVAT}/finalize")
check(r.status_code == 400 and "VAT note" in r.json().get("error", ""), "novat without a VAT note: 400 " + r.text[:120])
A.patch(B + f"{D}/{NOVAT}", json={"vat_note": "reverse"})
r = A.post(B + f"{D}/{NOVAT}/finalize")
check(r.ok and r.json()["number"] == "RE-2026-001" and r.json()["status"] == "issued" and r.json()["locked"] is True, "novat invoice finalised with the first number " + r.text[:160])
rd = A.get(B + f"{D}/{NOVAT}/render").json()
check(rd["vat_note_key"] == "reverse" and "Reverse" in rd["vat_note_text"] and rd["totals"]["tax_lines"] == [] and rd["totals"]["gross"] == "100.00",
      f"novat render: VAT note text, no tax lines: {rd.get('vat_note_text')}")

# ---------------------------------------------------------------- finalising the parity invoice
r = A.post(B + f"{D}/{IID}/number", json={"number": "RE-2026-005", "reason": "numbers 2-4 used in the old program"})  # 2.39.1 (#1210 N2): a gap needs a reason
check(r.ok and r.json()["number"] == "RE-2026-005", "manual number above the last one accepted " + r.text[:120])
r = Bo.post(B + f"{D}/{IID}/finalize")
check(r.ok and r.json()["number"] == "RE-2026-005" and r.json()["status"] == "issued" and r.json()["state"] == "issued" and r.json()["locked"] is True, "member finalises the invoice " + r.text[:160])
check(r.json()["due_date"] == "2027-06-07", "finalised invoice keeps its due date")
for what, rr in (("PATCH", A.patch(B + f"{D}/{IID}", json={"order_ref": "x"})), ("PUT items", A.put(B + f"{D}/{IID}/items", json={"items": []})),
                 ("number", A.post(B + f"{D}/{IID}/number", json={"number": "RE-2026-009"})), ("delete", A.delete(B + f"{D}/{IID}"))):
    check(rr.status_code == 409, f"finalised invoice: {what} = 409")
rd = A.get(B + f"{D}/{IID}/render").json()
meta = dict((k, v) for k, v in rd["meta"])
check(rd["title"] == "Rechnung" and meta.get("Rechnung Nr.") == "RE-2026-005" and meta.get("Bestellnr. / Referenz") == "PO-2026-0001-A" and meta.get("Leistungszeitraum") == "01.04.2026 – 31.05.2026"
      and meta.get("Fällig am") == "07.06.2027" and meta.get("Kunden-Nr.") == "K-1001", f"invoice print model meta: {meta}")
check(rd["totals"]["show_tax_lines"] is True and rd["totals"]["rows"][-1] == ["Rechnungsbetrag", "40.963,25 €"] and rd["totals"]["rows"][0] == ["Zwischensumme", "34.422,90 €"]
      and rd["totals"]["rows"][1][1] == "6.540,35 €", f"invoice print model totals rows: {rd['totals']['rows']}")
check(rd["payment"]["iban"] == TEST_IBAN and "07.06.2027" in rd["payment"]["text"] and rd["sender_fields"]["vat_id"] == "DE999999999", f"payment info and sender fields: {rd['payment']}")
check(rd["recipient"]["street"] == "Marktstraße 5" and rd["recipient"]["customer_no"] == "K-1001" and rd["einvoice_format"] == "zugferd", f"recipient fields in the print model: {rd['recipient']}")
check("Im Übrigen bleibt es bei den Regelungen unter §3 des RV." == rd["rights"]["note"], "framework contract closing printed on the invoice")
r = A.get(B + f"{D}/{IID}/pdf")
check(r.ok and r.content[:5] == b"%PDF-" and "RE-2026-005" in r.headers.get("Content-Disposition", ""), "invoice PDF")
# the next automatic number continues after the manual one
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 2, "rate": 100}]})
INV2 = r.json()["id"]
r = A.post(B + f"{D}/{INV2}/finalize")
check(r.ok and r.json()["number"] == "RE-2026-006", "the series continues after the manual number: " + r.json().get("number", r.text[:80]))
d2 = r.json()
check(d2["due_date"] and d2["payment_days"] == 30, f"due date computed from the client's payment days at finalising: {d2['due_date']} / {d2['payment_days']}")
# a second organisation has its own series and sees nothing of the first
Ca.put(B + O + "/settings", json={"company_fields": {"name": "Beta Studio", "street": "Weg 1", "zip": "10115", "city": "Berlin", "tax_number": "1/2/3", "iban": TEST_IBAN}})
r = Ca.post(B + D, json={"kind": "invoice", "recipient": {"name": "Kunde Zwei", "lines": ["Straße 2", "10115 Berlin"]}, "service_from": "2026-05-01",
                         "items": [{"title": "Leistung", "qty": 1, "rate": 10}]})
B1 = r.json()["id"]
r = Ca.post(B + f"{D}/{B1}/finalize")
check(r.ok and r.json()["number"] == "RE-2026-001", "second organisation: own series starts at 001 " + r.text[:120])
for path in (f"{D}/{IID}", f"{D}/{IID}/payments", f"{D}/{IID}/render", f"{D}/{IID}/pdf"):
    check(Ca.get(B + path).status_code == 404 and Da.get(B + path).status_code in (400, 404), f"tenant-matrix: office -- GET {path.replace(str(IID), '<id>')} foreign = 404")
for path in (f"{D}/{IID}/credit", f"{D}/{IID}/payments", f"{D}/{IID}/send", f"{D}/{IID}/datev", f"{D}/{IID}/finalize"):
    check(Ca.post(B + path, json={"to": "a@b.example", "amount": 1}).status_code == 404 and Da.post(B + path, json={}).status_code in (400, 404),
          f"tenant-matrix: office -- POST {path.replace(str(IID), '<id>')} foreign = 404")
    check(requests.post(B + path, headers=AGH, json={}).status_code == 403, f"agent: POST {path.replace(str(IID), '<id>')} = 403")
check(Ca.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 1}).status_code == 404, "tenant-matrix: office -- reminder over a foreign invoice = 404")
check(Ca.post(B + f"{D}/from-time", json={"client_id": CL, "from": "2026-01-01", "to": "2026-01-31"}).status_code == 404, "tenant-matrix: office -- from-time with a foreign client = 404")
check(requests.get(B + f"{D}?kind=invoice", headers=AGH).status_code == 403, "agent: no invoice list")
check(len(Ca.get(B + D + "?kind=invoice").json()["docs"]) == 1, "second organisation lists only its own invoice")
# UNIQUE per organisation: a manual number that exists already
r = A.post(B + D, json={"kind": "invoice"})
check(A.post(B + f"{D}/{r.json()['id']}/number", json={"number": "RE-2026-005"}).status_code == 400, "a used number is refused (400)")
A.delete(B + f"{D}/{r.json()['id']}")

# ---------------------------------------------------------------- payments
check(A.post(B + f"{D}/{EMPTY}/payments", json={"amount": 10}).status_code == 409, "payment on a draft: 409")
check(A.post(B + f"{D}/{IID}/payments", json={"amount": -5}).status_code == 400 and A.post(B + f"{D}/{IID}/payments", json={"amount": 5, "method": "gold"}).status_code == 400,
      "payment validated")
check(Bo.post(B + f"{D}/{IID}/payments", json={"date": "2026-06-01", "amount": "10000.00"}).status_code == 403, "2.39.1 (#1210 N3): a member cannot record a payment (403)")
r = A.post(B + f"{D}/{IID}/payments", json={"date": "2026-06-01", "amount": "10000.00", "method": "transfer", "note": "Abschlag"})
check(r.status_code == 201 and r.json()["state"] == "partial" and r.json()["status"] == "issued" and r.json()["paid"] == "10000.00" and r.json()["open"] == "30963.25",
      "the admin records a part payment -> partial " + r.text[:160])
check(r.json()["status_text"] == "Partly paid", f"state text: {r.json()['status_text']}")
PAY1 = r.json()["payments"][0]["id"]
r = A.post(B + f"{D}/{IID}/payments", json={"date": "2026-06-10", "amount": 30963.25, "method": "transfer"})
check(r.status_code == 201 and r.json()["status"] == "paid" and r.json()["state"] == "paid" and r.json()["paid_at"] and r.json()["open"] == "0.00", "the rest -> paid with paid_at " + r.text[:160])
PAY2 = r.json()["payments"][1]["id"]
check(A.get(B + f"{D}/{IID}/payments").json()["payments"][1]["created_by_name"] == "Alice Admin", "payments list with names")
check(Bo.delete(B + f"{D}/{IID}/payments/{PAY2}").status_code == 403, "member cannot delete a payment (403)")
r = A.delete(B + f"{D}/{IID}/payments/{PAY2}")
check(r.ok and r.json()["status"] == "issued" and r.json()["state"] == "partial" and r.json()["paid_at"] is None, "admin deletes the payment -> partial again " + r.text[:160])
check(A.delete(B + f"{D}/{IID}/payments/99999").status_code == 404, "unknown payment: 404")
rd = A.get(B + f"{D}/{IID}/render").json()
check(rd["totals"]["paid"] == "10000.00" and rd["totals"]["open"] == "30963.25" and ["Bereits bezahlt", "10.000,00 €"] in rd["totals"]["rows"], f"print model shows paid / open: {rd['totals']['rows']}")
# overdue: a finalised invoice whose due date passed
dbx("UPDATE office_docs SET due_date='2020-01-01' WHERE id=?", (INV2,), write=True)
L = {x["id"]: x for x in A.get(B + D + "?kind=invoice").json()["docs"]}
check(L[INV2]["state"] == "overdue" and L[INV2]["status"] == "issued" and L[IID]["state"] == "partial", f"derived states in the list: {L[INV2]['state']} / {L[IID]['state']}")
check([x["id"] for x in A.get(B + D + "?kind=invoice&status=overdue").json()["docs"]] == [INV2], "list filter by the derived state overdue")
# sending by status (manual) once finalised; never back to draft
r = A.post(B + f"{D}/{INV2}/status", json={"status": "sent"})
check(r.ok and r.json()["status"] == "sent" and r.json()["sent_at"], "finalised invoice: status sent by hand")
check(A.post(B + f"{D}/{INV2}/status", json={"status": "draft"}).status_code == 409, "never back to draft (409)")
check(A.post(B + f"{D}/{INV2}/status", json={"status": "cancelled"}).status_code == 409, "cancelled only by a credit note (409)")
r = A.post(B + f"{D}/{INV2}/status", json={"status": "paid"})
check(r.ok and r.json()["status"] == "paid" and r.json()["paid_at"], "status paid by hand sets paid_at")

# ---------------------------------------------------------------- credit notes
check(A.post(B + f"{D}/{EMPTY}/credit").status_code == 409, "credit note needs a finalised invoice (409)")
check(A.post(B + f"{D}/{OFF}/credit").status_code == 409, "credit note of a quotation: 409")
r = A.post(B + f"{D}/{IID}/credit")
check(r.status_code == 201 and r.json()["kind"] == "credit" and r.json()["cancels_id"] == IID and r.json()["cancels"]["number"] == "RE-2026-005" and r.json()["number"] == "", "credit note draft to the invoice " + r.text[:160])
CR = r.json()
check(len(CR["items"]) == 6 and CR["totals"]["gross"] == "40963.25" and CR["recipient"] == INV["recipient"], "credit note: positions and recipient copied")
# a partial credit note: shorten it to one position
r = A.put(B + f"{D}/{CR['id']}/items", json={"items": [{"title": "Webhosting (3 Monate)", "qty": 1, "rate": 105}]})
check(r.ok and r.json()["totals"]["gross"] == "124.95", "partial credit note " + r.text[:100])
r = A.post(B + f"{D}/{CR['id']}/finalize")
check(r.ok and r.json()["number"] == "GS-2026-001" and r.json()["status"] == "issued", "credit note finalised with its own series " + r.text[:120])
inv = A.get(B + f"{D}/{IID}").json()
check(inv["status"] == "issued" and inv["credits"] == "124.95" and inv["open"] == "30838.30" and inv["credits_of"][0]["number"] == "GS-2026-001",
      f"partial credit note lowers the open amount: {inv['open']} credits {inv['credits']}")
rd = A.get(B + f"{D}/{CR['id']}/render").json()
meta = dict((k, v) for k, v in rd["meta"])
check(rd["title"] == "Gutschrift" and meta.get("Gutschrift Nr.") == "GS-2026-001" and meta.get("zu Rechnung Nr.", "").startswith("RE-2026-005") and rd["cancels"]["number"] == "RE-2026-005",
      f"credit note print model: {rd['title']} {meta}")
# a full credit note cancels the invoice (INV2 is paid -> make a fresh one)
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 500}]})
INV3 = r.json()["id"]
A.post(B + f"{D}/{INV3}/finalize")
r = A.post(B + f"{D}/{INV3}/credit")
CR2 = r.json()["id"]
r = A.post(B + f"{D}/{CR2}/finalize")
check(r.ok and r.json()["number"] == "GS-2026-002", "second credit note numbered 002")
inv3 = A.get(B + f"{D}/{INV3}").json()
check(inv3["status"] == "cancelled" and inv3["state"] == "cancelled" and inv3["open"] == "0.00" and inv3["status_text"] == "Cancelled", f"full credit note cancels the invoice: {inv3['status']} open {inv3['open']}")
check(A.post(B + f"{D}/{INV3}/credit").status_code == 409, "no credit note on a cancelled invoice")
check(A.post(B + f"{D}/{INV3}/payments", json={"amount": 1}).status_code == 409, "no payment on a cancelled invoice")
check(A.get(B + D + "?kind=credit").json()["docs"][0]["kind"] == "credit", "list of credit notes")

# ---------------------------------------------------------------- reminders
r = A.post(B + f"{D}/reminder", json={"doc_ids": [INV2], "level": 1})
check(r.status_code == 400, "a paid invoice cannot be reminded of (400)")
r = A.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 9})
check(r.status_code == 400, "reminder level 1..3")
r = Bo.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 2, "fee": 7.5, "deadline_days": 14})
check(r.status_code == 201 and r.json()["kind"] == "reminder" and r.json()["reminder_level"] == 2 and r.json()["ref_doc_ids"] == [IID] and r.json()["recipient"]["name"] == "Beispielkunde AG",
      "reminder draft over the open invoice " + r.text[:160])
RM = r.json()
check(RM["totals"]["net"] == "30838.30" and RM["totals"]["fee"] == "7.50" and RM["totals"]["gross"] == "30845.80" and RM["totals"]["lines"][0]["number"] == "RE-2026-005",
      f"reminder totals = open amount + fee: {RM['totals']['net']} + {RM['totals']['fee']} = {RM['totals']['gross']}")
r = A.patch(B + f"{D}/{RM['id']}", json={"reminder_level": 3, "reminder_fee": 10})
check(r.ok and r.json()["reminder_level"] == 3 and r.json()["totals"]["gross"] == "30848.30", "reminder level / fee changed " + r.text[:100])
check(A.post(B + f"{D}/{RM['id']}/status", json={"status": "paid"}).status_code == 400, "reminder has no status paid")
r = A.post(B + f"{D}/{RM['id']}/finalize")
check(r.ok and r.json()["number"] == "MA-2026-001" and r.json()["status"] == "issued", "reminder finalised with its own series " + r.text[:120])
rd = A.get(B + f"{D}/{RM['id']}/render").json()
check(rd["title"] == "Letzte Mahnung" and rd["reminder"]["level"] == 3 and rd["reminder"]["rows"][0]["number"] == "RE-2026-005" and rd["reminder"]["rows"][0]["open_text"] == "30.838,30 €"
      and rd["reminder"]["fee_text"] == "10,00 €" and rd["reminder"]["deadline_text"] and rd["reminder"]["columns"] == ["Rechnung", "Datum", "Fällig", "Betrag"]
      and rd["totals"]["rows"][-1] == ["Gesamtbetrag", "30.848,30 €"], f"reminder print model: {rd['title']} {rd['reminder']}")  # 2.40.0 (#1368): Gesamtbetrag
# the reminder keeps its snapshot after a payment on the invoice
A.post(B + f"{D}/{IID}/payments", json={"amount": 100})
check(A.get(B + f"{D}/{RM['id']}").json()["totals"]["net"] == "30838.30", "finalised reminder keeps the amounts of its day")
check("{days}" not in rd["closing"] and "14" in rd["closing"], f"reminder closing fills the deadline days: {rd['closing'][:80]}")
check(A.get(B + f"{D}/{RM['id']}/pdf").content[:5] == b"%PDF-", "reminder PDF")
check(A.get(B + D + "?kind=reminder").json()["docs"][0]["number"] == "MA-2026-001", "list of reminders")

# ---------------------------------------------------------------- sending and DATEV without SMTP
r = A.post(B + f"{D}/{IID}/send", json={"to": "rechnung@beispielkunde.example"})
check(r.status_code == 409 and "SMTP" in r.json().get("error", ""), "sending without SMTP: 409 with a reason " + r.text[:120])
check(A.post(B + f"{D}/{IID}/datev").status_code == 409, "DATEV without SMTP: 409")
check(A.post(B + f"{D}/{EMPTY}/send", json={"to": "a@b.example"}).status_code == 409, "sending a draft: 409")
ms = A.get(B + O + "/mail-status").json()
check(ms["smtp"] is False and ms["datev_email"] == "belege@kanzlei.example", f"mail status for the dialog: {ms}")

# ---------------------------------------------------------------- a sent quotation is locked (decision 2026-10-10)
r = A.post(B + f"{D}/{OFF}/status", json={"status": "sent"})
check(r.ok and r.json()["can_edit"] is False, "sent quotation: can_edit false")
r = A.patch(B + f"{D}/{OFF}", json={"project_title": "x"})
check(r.status_code == 409 and "sent" in r.json().get("error", ""), "sent quotation: PATCH 409 " + r.text[:100])
check(A.put(B + f"{D}/{OFF}/items", json={"items": []}).status_code == 409, "sent quotation: items 409")
check(A.get(B + f"{D}/{OFF}").json()["can_delete"] is False and A.delete(B + f"{D}/{OFF}").status_code == 409,
      "sent quotation an invoice was made from: delete 409 (also in the 2.144.8 #2573 test phase)")
r = A.post(B + f"{D}/{OFF}/duplicate")
check(r.status_code == 201 and r.json()["can_edit"] is True and r.json()["status"] == "draft", "sent quotation: duplicate = a new editable draft")
check(A.post(B + f"{D}/{OFF}/invoice").status_code == 201, "an invoice can still be made from the sent quotation")

# ---------------------------------------------------------------- an invoice from time entries
r = A.post(B + "/api/lists", json={"name": "Projekt Film"})
LID = r.json()["id"]
A.patch(B + f"/api/lists/{LID}", json={"client_id": CL})
dbx("UPDATE lists SET client_id=?, org_id=? WHERE id=?", (CL, ORG, LID), write=True)
r = A.post(B + "/api/time/entries", json={"list_id": LID, "start": "2026-05-04T08:00:00Z", "end": "2026-05-04T10:30:00Z", "note": "Schnitt"})
if not r.ok:
    dbx("INSERT INTO time_entries(user_id, list_id, start, \"end\", seconds, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (ALICE, LID, "2026-05-04T08:00:00", "2026-05-04T10:30:00", 9000, "2026-05-04T10:30:00", "2026-05-04T10:30:00"), write=True)
r = A.post(B + f"{D}/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201 and r.json()["kind"] == "invoice" and r.json()["service_from"] == "2026-05-01" and r.json()["client_id"] == CL, "invoice from time entries " + r.text[:160])
its = r.json()["items"]
check(len(its) == 1 and its[0]["unit"] == "hour" and float(its[0]["qty"]) == 2.5 and float(its[0]["rate"]) == 90 and its[0]["title"] == "Projekt Film",
      f"one position per list with hours and the client's rate: {[(x['title'], x['qty'], x['unit'], x['rate']) for x in its]}")
check(A.post(B + f"{D}/from-time", json={"client_id": CL, "from": "2026-05-31", "to": "2026-05-01"}).status_code == 400, "from-time: period validated")

# ---------------------------------------------------------------- review fixes 2.38.0: back-dating, reminders, credits, payments, sending
import ast
import datetime as _dt
TODAY = testclock.today()
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "date": f"{TODAY.year}-01-01", "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
BD = r.json()["id"]
if TODAY.month > 1 or TODAY.day > 1:
    r = A.post(B + f"{D}/{BD}/finalize")
    check(r.status_code == 400 and "series" in r.json().get("error", ""), "back-dating before the last finalised invoice of the series: 400 " + r.text[:160])
r = A.patch(B + f"{D}/{BD}", json={"date": (TODAY + _dt.timedelta(days=3)).isoformat()})
r = A.post(B + f"{D}/{BD}/finalize")
check(r.status_code == 400 and "future" in r.json().get("error", ""), "an invoice dated in the future: 400 " + r.text[:160])
r = A.patch(B + f"{D}/{BD}", json={"date": TODAY.isoformat(), "due_date": (TODAY - _dt.timedelta(days=1)).isoformat()})
check(r.status_code == 400 and "due date" in r.json().get("error", ""), "due date before the date: 400 " + r.text[:120])
A.delete(B + f"{D}/{BD}")
# a reminder covers one client only
r = A.post(B + "/api/clients", json={"name": "Zweitkunde KG", "street": "Allee 3", "zip": "20095", "city": "Hamburg", "country": "DE"})
CLX = r.json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": CLX, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 10, "rate": 100}]})
INVX = r.json()["id"]
check(A.post(B + f"{D}/{INVX}/finalize").ok, "invoice of a second client finalised")
r = A.post(B + f"{D}/reminder", json={"doc_ids": [IID, INVX], "level": 1})
check(r.status_code == 400 and "one client" in r.json().get("error", ""), "reminder over invoices of two clients: 400 " + r.text[:120])
check(A.post(B + f"{D}/reminder", json={"doc_ids": [INVX], "level": 1}).status_code == 201, "reminder over one client's invoice: 201")
# a duplicated credit note is a fresh one, bound to no invoice; credit notes never exceed the invoice
r = A.post(B + f"{D}/{CR['id']}/duplicate")
check(r.status_code == 201 and r.json()["kind"] == "credit" and r.json()["cancels_id"] is None and r.json()["status"] == "draft", "duplicated credit note: no cancels_id " + r.text[:120])
A.delete(B + f"{D}/{r.json()['id']}")
r = A.post(B + f"{D}/{INVX}/credit")
CRA = r.json()["id"]
A.put(B + f"{D}/{CRA}/items", json={"items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
check(A.post(B + f"{D}/{CRA}/finalize").ok, "partial credit note (119.00) on the second client's invoice")
r = A.post(B + f"{D}/{INVX}/credit")
CRB = r.json()["id"]
r = A.post(B + f"{D}/{CRB}/finalize")
check(r.status_code == 409 and "exceed" in r.json().get("error", ""), "a second full credit note would exceed the invoice: 409 " + r.text[:120])
check(A.get(B + f"{D}/{CRB}").json()["locked"] is False and A.get(B + f"{D}/{INVX}").json()["status"] == "issued", "... nothing finalised, the invoice stays open")
A.delete(B + f"{D}/{CRB}")
# payments: no overpayment, no future date, nothing on a paid invoice, paid -> sent only without payments
open_x = A.get(B + f"{D}/{INVX}").json()["open"]
check(open_x == "1071.00", f"open amount after the partial credit note: {open_x}")
r = A.post(B + f"{D}/{INVX}/payments", json={"amount": "1071.01"})
check(r.status_code == 409 and "exceeds" in r.json().get("error", ""), "overpayment: 409 " + r.text[:120])
r = A.post(B + f"{D}/{INVX}/payments", json={"amount": "10", "date": (TODAY + _dt.timedelta(days=2)).isoformat()})
check(r.status_code == 400 and "future" in r.json().get("error", ""), "payment dated in the future: 400 " + r.text[:120])
r = A.post(B + f"{D}/{INVX}/payments", json={"amount": open_x})
check(r.status_code == 201 and r.json()["status"] == "paid", "the open amount -> paid " + r.text[:120])
check(A.post(B + f"{D}/{INVX}/payments", json={"amount": "1"}).status_code == 409, "payment on a paid invoice: 409")
r = A.post(B + f"{D}/{INVX}/status", json={"status": "sent"})
check(r.status_code == 409 and "Payments" in r.json().get("error", ""), "paid -> sent by hand with payments recorded: 409 " + r.text[:120])
r = A.post(B + f"{D}/{INV2}/status", json={"status": "sent"})
check(r.ok and r.json()["status"] == "sent", "paid by hand without payments -> sent again " + r.text[:120])
# sending: a subject with a line break is cleaned (pure function), without SMTP the 409 comes first
src = open(os.path.join(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."), "kalmido", "office", "invoices.py"), encoding="utf-8").read()
fn = next(x for x in ast.parse(src).body if isinstance(x, ast.FunctionDef) and x.name == "inv_clean_subject")
ns = {"re": __import__("re")}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "invoices.py", "exec"), ns)
check(ns["inv_clean_subject"]("Rechnung\r\nBcc: x@y.example") == "Rechnung Bcc: x@y.example" and len(ns["inv_clean_subject"]("x" * 500)) == 200
      and ns["inv_clean_subject"](None) == "", "subject: line breaks become a space, at most 200 characters")
r = A.post(B + f"{D}/{IID}/send", json={"to": "rechnung@beispielkunde.example", "subject": "Rechnung\nBcc: x@y.example", "text": "x" * 9000})
check(r.status_code == 409, "sending with a line break in the subject (no SMTP): 409, not 500 " + r.text[:120])
check(A.post(B + f"{D}/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31", "project_id": "abc"}).status_code == 400, "from-time: invalid project_id 400")

# ---------------------------------------------------------------- the office log knows the new actions
log = A.get(B + f"{D}/{IID}/log").json()["log"]
acts = {x["action"] for x in log}
check({"create", "finalize", "payment", "payment_delete"} <= acts, f"office log: invoice actions {sorted(acts)}")

# ---------------------------------------------------------------- 2.39.0 (#1209): fixes from the mini audit of 2.38
# M2: control characters never reach a document or a client (they would break the e-invoice XML); tab / line break stay
r = A.post(B + "/api/clients", json={"name": "Steuer\x01zeichen\x0b KG", "address": "Weg 1\n12345 Ort\x07"})
check(r.status_code == 201 and r.json()["name"] == "Steuerzeichen KG" and r.json()["address"] == "Weg 1\n12345 Ort",
      "#1209 M2: control characters dropped from client data " + r.text[:120])
r = A.post(B + D, json={"project_title": "Titel\x0bmit\x00Steuerzeichen", "client_id": CL})
check(r.status_code == 201, "#1209 M2: a NUL byte in a title is no 500 " + r.text[:120])
if r.status_code == 201:
    OFF9 = r.json()["id"]
    check(A.get(B + f"{D}/{OFF9}").json().get("project_title") == "TitelmitSteuerzeichen", "#1209 M2: control characters dropped from the title")
    # N1: a sent quotation never goes back to draft (decision 2026-10-10: sent = locked; Duplicate for changes)
    check(A.post(B + f"{D}/{OFF9}/status", json={"status": "sent"}).ok, "#1209 N1: quotation -> sent")
    check(A.post(B + f"{D}/{OFF9}/status", json={"status": "draft"}).status_code == 409, "#1209 N1: sent quotation -> draft = 409")
    check(A.post(B + f"{D}/{OFF9}/status", json={"status": "accepted"}).ok, "#1209 N1: sent quotation -> accepted still works")
# M3: mode workspaces -- the instance admin sees and moves only the clients of their own organisations
r = Ca.post(B + "/api/clients", json={"name": "Beta-Kunde"})
check(r.status_code == 201, "setup: client of the second organisation " + r.text[:120])
CLB = r.json().get("id")
r = A.get(B + "/api/clients")  # 2.126.0: the answer in the message when it is no JSON
check(r.ok and all(x["id"] != CLB for x in r.json()["clients"]), f"#1209 M3: the instance admin does not list a foreign organisation's client {r.status_code} {r.text[:300]}")
check(A.get(B + f"/api/clients/{CLB}").status_code == 404, "#1209 M3: a foreign organisation's client = 404 for the instance admin")
check(A.patch(B + f"/api/clients/{CL}", json={"org_id": ORG2}).status_code == 400, "#1209 M3: the instance admin cannot move a client into a foreign organisation")

print(f"p2380_a_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
