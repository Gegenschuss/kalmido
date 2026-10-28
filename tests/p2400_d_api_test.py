#!/usr/bin/env python3
"""2.40.0 API tests, part D (office documents and invoices), own container (start.sh). Invented companies, people and the
test IBAN only.
 - #1368 1: the buyer address of the e-invoice XML from free address lines (2, 3 and 4 lines): the last line with a
   postcode = PostcodeCode + CityName, the line before = LineOne, the lines before that LineTwo / LineThree
 - #1368 2: the standard invoice closing says nothing about the due date; credit notes have their own closing; the
   credit note XML has no "payable on receipt" terms
 - #1368 4 + 6: reminder intro / closing per level 1-3; the reminder's last sum row is "Gesamtbetrag"; English
   quantity column "Qty"
 - #1368 5: a credit note keeps the XRechnung format of its invoice (client with a buyer reference)
 - #1368 8 + 9: the fee of a finalised reminder stays open after the invoice is paid (reminder and invoice list), the
   organisation's admin waives it or marks it paid (members 403), the invoice stays "paid"; a reminder whose invoices are
   all paid shows state "done"
 - #1381 / #1363: switching the language of a draft swaps unchanged standard texts (intro, closing, rights, position
   titles), keeps texts changed by hand (note), notes a missing English text, never touches a finalised document;
   the reminder level swaps the reminder texts
 - #1364 / #1366: the PDF route answers inline with ?inline=1 and as a download without it; the archive PDF route of the
   legacy import likewise (?download=1)
 - #1336: the index office_doc_log_action exists
usage: p2400_d_api_test.py <datadir>"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
DBC = os.environ.get("KALMIDO_TEST_DB_CONTAINER", CT + "-db")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
import dbx as dbxm  # noqa: E402  # 2.355.0 D (#2846)
TEST_IBAN = "DE02120300000000202051"


if os.environ.get("P2400D_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
# 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
FEAT = "cal,comments,collab,office,clients,time"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
O = "/api/office"
D = O + "/docs"
r = A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "payment_days": 14, "reminder_deadline_days": 10,
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "phone": "040 1234567", "tax_number": "12/345/67890",
                                                        "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "setup: office settings " + r.text[:160])
check(A.get(B + O + "/settings").json()["settings"].get("reminder_fee") in (0, 0.0, "0", None), "#1368 8: no reminder fee preset")


def inv(lines=None, **kw):
    b = {"kind": "invoice", "recipient": {"name": "Beispiel GmbH", "lines": lines or ["Weg 1", "10115 Berlin"]}, "service_from": "2026-05-01",
         "items": [{"title": "Beratung", "qty": 1, "rate": 100}]}
    b.update(kw)
    r = A.post(B + D, json=b)
    assert r.status_code == 201, r.text
    return r.json()


def fin(did):
    r = A.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"finalise {did} " + r.text[:200])
    return r.json()


def buyer(xml):
    m = re.search(r"<ram:BuyerTradeParty>.*?<ram:PostalTradeAddress>(.*?)</ram:PostalTradeAddress>", xml, re.S)
    return dict(re.findall(r"<ram:(\w+)>([^<]*)</ram:\1>", m.group(1))) if m else {}


# ---------------------------------------------------------------- #1368 1: the buyer address from free lines
for lines, want in ((["Schröderstr. 513", "12952 Berlin"], {"LineOne": "Schröderstr. 513", "PostcodeCode": "12952", "CityName": "Berlin"}),
                    (["Frau Test", "Schröderstr. 513", "12952 Berlin"], {"LineOne": "Schröderstr. 513", "LineTwo": "Frau Test", "PostcodeCode": "12952", "CityName": "Berlin"}),
                    (["z. Hd. Buchhaltung", "Frau Test", "Schröderstr. 513", "12952 Berlin"],
                     {"LineOne": "Schröderstr. 513", "LineTwo": "z. Hd. Buchhaltung", "LineThree": "Frau Test", "PostcodeCode": "12952", "CityName": "Berlin"}),
                    (["Bahnhofstrasse 1", "CH-8000 Zürich"], {"LineOne": "Bahnhofstrasse 1", "PostcodeCode": "8000", "CityName": "Zürich", "CountryID": "CH"})):
    d = inv(lines)
    fin(d["id"])
    got = buyer(A.get(B + f"{D}/{d['id']}/xml").text)
    check(all(got.get(k) == v for k, v in want.items()) and ("LineTwo" in want or "LineTwo" not in got), f"#1368 1: address of {len(lines)} lines {lines}: {got}")
LAST = d

# ---------------------------------------------------------------- #1368 2: closing texts, credit note
d = inv()
check("fällig" not in d["closing"] and d["closing"].startswith("Bitte überweisen Sie den Gesamtbetrag"), "#1368 2: invoice closing without a due statement: " + d["closing"][:80])
fin(d["id"])
r = A.post(B + f"{D}/{d['id']}/credit")
cr = r.json()
# 2.296.0 B (#3175): the credit note prints as "Rechnungskorrektur" (was "Gutschrift")
check(r.status_code == 201 and cr["closing"].startswith("Den Korrekturbetrag") and cr["closing"] != d["closing"], "#1368 2: credit note has its own closing: " + cr.get("closing", "")[:80])
fin(cr["id"])
x = A.get(B + f"{D}/{cr['id']}/xml").text
check("Zahlbar sofort" not in x and "<ram:TypeCode>381</ram:TypeCode>" in x and "erstattet oder verrechnet" in x, "#1368 2: credit note XML without 'Zahlbar sofort ohne Abzug'")
d = inv(lang="en")
check(d["closing"].startswith("Please transfer the total amount"), "#1368 2: English invoice closing: " + d["closing"][:60])
m = A.get(B + f"{D}/{d['id']}/render").json()
check((m.get("labels") or {}).get("qty") == "Qty", f"#1368 6: English quantity column 'Qty': {(m.get('labels') or {}).get('qty')}")

# ---------------------------------------------------------------- #1368 5: XRechnung credit note
r = A.post(B + "/api/clients", json={"name": "Amt Beispielstadt", "street": "Rathausplatz 1", "zip": "10115", "city": "Berlin", "country": "DE",
                                     "buyer_reference": "991-12345-67", "email_invoice": "rechnung@amt.example"})
assert r.status_code == 201, r.text
CLX = r.json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": CLX, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
XI = r.json()
check(XI["einvoice_format"] == "xrechnung", "setup: invoice to a client with a buyer reference is XRechnung")
fin(XI["id"])
cr = A.post(B + f"{D}/{XI['id']}/credit").json()
check(cr["einvoice_format"] == "xrechnung", "#1368 5: the credit note keeps XRechnung: " + str(cr.get("einvoice_format")))
# 2.354.0 (#2838): an empty credit note no longer exists (409); the credit note above already keeps XRechnung
check(A.post(B + D, json={"kind": "credit", "client_id": CLX}).status_code == 409, "#2838: no empty credit note to that client (409)")

# ---------------------------------------------------------------- #1368 4 + 6 + 8 + 9: reminders
RI = inv(recipient={"name": "Mahn GmbH", "lines": ["Weg 2", "10115 Berlin"]})
fin(RI["id"])
dbxm.overdue(DATA, [RI["id"]])  # 2.355.0 D (#2846): reminders only for overdue invoices
rem = {}
for lv in (1, 2, 3):
    r = A.post(B + D + "/reminder", json={"doc_ids": [RI["id"]], "level": lv, "fee": 5 if lv == 2 else 0})
    check(r.status_code == 201, f"reminder level {lv} " + r.text[:120])
    rem[lv] = r.json()
check(len({rem[lv]["intro"] for lv in rem}) == 3 and len({rem[lv]["closing"] for lv in rem}) == 3, "#1368 4: intro and closing differ per level")
check("letztmalig" in rem[3]["closing"] and "rechtliche Schritte" in rem[3]["closing"], "#1368 4: level 3 has a clear tone")
r = A.patch(B + f"{D}/{rem[1]['id']}", json={"reminder_level": 3})
check(r.ok and r.json()["closing"] == rem[3]["closing"] and r.json()["intro"] == rem[3]["intro"], "#1368 4: changing the level swaps unchanged reminder texts")
M = rem[2]
fin(M["id"])
rows = A.get(B + f"{D}/{M['id']}/render").json()["totals"]["rows"]
check(rows[-1][0] == "Gesamtbetrag" and rows[-1][1] == "124,00 €", f"#1368 6: the reminder's sum row is 'Gesamtbetrag': {rows}")
g = A.get(B + f"{D}/{M['id']}").json()
check(g.get("fee_open") == "5.00" and g.get("fee_state") == "" and g.get("settled") is False, f"#1368 8: fee open on the finalised reminder: {g.get('fee_open')} {g.get('settled')}")
r = A.post(B + f"{D}/{RI['id']}/payments", json={"amount": 119})
check(r.status_code == 201 and r.json()["state"] == "paid", "#1368 8: the invoice is paid in full (the fee does not block 'paid') " + r.text[:120])
L = {x["id"]: x for x in A.get(B + D + "?kind=reminder").json()["docs"]}
check(L[M["id"]]["state"] == "done" and L[M["id"]]["settled"] is True and L[M["id"]]["fee_open"] == "5.00", f"#1368 9 + 8: settled reminder, fee still open: {L[M['id']]}")
check(L[rem[3]["id"]]["state"] == "draft" and not L[rem[3]["id"]]["settled"], "#1368 9: a draft reminder is not settled")
LI = {x["id"]: x for x in A.get(B + D + "?kind=invoice").json()["docs"]}
check(LI[RI["id"]].get("fee_open") == "5.00" and LI[RI["id"]]["state"] == "paid", f"#1368 8: the invoice list shows the open fee: {LI[RI['id']].get('fee_open')}")
Bo = sess("bob")
check(Bo.post(B + f"{D}/{M['id']}/fee", json={"state": "waived"}).status_code in (403, 404), "#1368 8: no admin, no waiving")
check(A.post(B + f"{D}/{M['id']}/fee", json={"state": "nope"}).status_code == 400, "#1368 8: fee state validated")
check(A.post(B + f"{D}/{rem[3]['id']}/fee", json={"state": "waived"}).status_code == 409, "#1368 8: a draft reminder: 409")
r = A.post(B + f"{D}/{M['id']}/fee", json={"state": "waived"})
check(r.ok and r.json()["fee_open"] == "0.00" and r.json()["fee_state"] == "waived", "#1368 8: fee waived " + r.text[:120])
check(all(x.get("fee_open") in (None, "0.00") for x in A.get(B + D + "?kind=invoice").json()["docs"] if x["id"] == RI["id"]), "#1368 8: after waiving the invoice list shows no open fee")
log = A.get(B + f"{D}/{M['id']}/log")
check(log.ok and "reminder_fee" in log.text, "#1368 8: the waiving is logged")
r = A.post(B + f"{D}/{M['id']}/fee", json={"state": "paid"})
check(r.ok and r.json()["fee_state"] == "paid" and r.json()["fee_open"] == "0.00", "#1368 8: fee marked paid")
check(A.get(B + f"{D}/{M['id']}/render").json()["totals"]["rows"] == rows, "#1368 8: the finalised reminder itself stays unchanged")

# ---------------------------------------------------------------- #1381 / #1363: switching the language of a draft
SV = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "daily_rate": 500}).json()["id"]
SV2 = A.post(B + O + "/services", json={"name_de": "Farbkorrektur", "daily_rate": 500}).json()["id"]
RT = A.post(B + O + "/texts", json={"kind": "rights_time", "key": "u", "text_de": "unbegrenzt", "text_en": "in perpetuity"}).json()["id"]
RM = A.post(B + O + "/texts", json={"kind": "rights_media", "key": "m", "text_de": "alle Medien", "text_en": ""}).json()["id"]
r = A.post(B + D, json={"project_title": "Film", "rights": {"time": {"id": RT}, "media": {"id": RM}}})
OF = r.json()
check(r.status_code == 201 and OF["lang"] == "de" and OF["rights"]["time"]["text"] == "unbegrenzt", "setup: German quotation")
A.put(B + f"{D}/{OF['id']}/items", json={"items": [{"service_id": SV, "qty": 1}, {"service_id": SV2, "qty": 1}, {"service_id": SV, "title": "Eigener Titel"}]})
r = A.patch(B + f"{D}/{OF['id']}", json={"lang": "en"})
e = r.json()
check(r.ok and e["intro"].startswith("Dear Sir or Madam") and e["closing"].startswith("We look forward"), "#1381: DE -> EN swaps intro and closing: " + e.get("intro", "")[:40])
check(e["rights"]["time"]["text"] == "in perpetuity" and e["rights"]["media"]["text"] == "alle Medien", f"#1381: rights texts swapped, no English stays German: {e['rights']}")
check([x["title"] for x in e["items"]] == ["Editing", "Farbkorrektur", "Eigener Titel"], f"#1363: position titles in English, own title kept: {[x['title'] for x in e['items']]}")
notes = " | ".join(e.get("lang_notes") or [])
check("no English text stored" in notes and "Farbkorrektur" in notes and "changed by hand" in notes, "#1381: notes for missing English / own titles: " + notes)
A.patch(B + f"{D}/{OF['id']}", json={"intro": "Hallo Team, hier unser Angebot."})
e = A.patch(B + f"{D}/{OF['id']}", json={"lang": "de"}).json()
check(e["intro"] == "Hallo Team, hier unser Angebot." and e["closing"].startswith("Wir freuen uns") and e["rights"]["time"]["text"] == "unbegrenzt",
      "#1381: EN -> DE keeps the own intro, swaps the rest")
check(any("Introduction" in n for n in e.get("lang_notes") or []), "#1381: note for the intro changed by hand: " + str(e.get("lang_notes")))
d = inv()
e = A.patch(B + f"{D}/{d['id']}", json={"lang": "en"}).json()
check(e["intro"].startswith("Dear Sir or Madam") and e["closing"].startswith("Please transfer the total amount"), "#1368 3: invoice texts swapped to English")
fin(d["id"])
check(A.patch(B + f"{D}/{d['id']}", json={"lang": "de"}).status_code == 409, "#1381: a finalised document is never changed")

# ---------------------------------------------------------------- #1364 / #1366: PDF inline and as a download
r = A.get(B + f"{D}/{OF['id']}/pdf?inline=1")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.headers.get("Content-Disposition", "").startswith("inline"),
      "#1364/#1366: ?inline=1 shows the PDF in the browser: " + r.headers.get("Content-Disposition", ""))
r = A.get(B + f"{D}/{OF['id']}/pdf")
check(r.ok and r.headers.get("Content-Disposition", "").startswith("attachment"), "#1366: without inline the PDF downloads: " + r.headers.get("Content-Disposition", ""))
src = open(os.path.join(N, "..", "static", "js", "office_docs.js"), encoding="utf-8").read()
check("tr('Preview (PDF)')" in src and "/render`, '_blank'" not in src, "#1364: the menu entry opens the PDF, not the JSON print model")
check("ofdPdfUrl(d.id, true)" in src and "class=\"btn sm ofddl\"" in src, "#1366: PDF button inline + own download button")
src = open(os.path.join(N, "..", "static", "js", "office_import.js"), encoding="utf-8").read()
check("/pdf?download=1" in src, "#1366: archive PDFs have a download button too")

# ---------------------------------------------------------------- #1336: the index for the own-text mail count
try:  # start.sh names "<db container> <database>" in <datadir>/.kalmido-db
    DBC, DBN = open(os.path.join(DATA, ".kalmido-db")).read().split()[:2]
except (OSError, ValueError):
    DBN = "kalmido"
r = subprocess.run(["docker", "exec", DBC, "psql", "-U", "kalmido", "-d", DBN, "-Atc",
                    "SELECT indexdef FROM pg_indexes WHERE indexname='office_doc_log_action'"], capture_output=True, text=True)
if r.returncode == 0 and r.stdout.strip():
    check("org_id, action, at" in r.stdout, "#1336: index office_doc_log(org_id, action, at): " + r.stdout.strip()[:120])
else:  # the database container has another name here: the index is checked through the schema text
    src = open(os.path.join(N, "..", "kalmido", "core", "schema.py"), encoding="utf-8").read()
    check("office_doc_log_action ON office_doc_log(org_id, action, at)" in src, "#1336: index office_doc_log_action in the schema")

print(f"p2400_d_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
