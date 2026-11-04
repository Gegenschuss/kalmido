#!/usr/bin/env python3
# kalmido-suite: now=wed10:00
"""2.354.0 B API tests (#2836, #2842): progress / final invoices with credit notes, the key figure revenue per client.
Own container (start.sh). Invented companies, people and figures only.
freelancer-matrix: office
 - #2836 1: a partial credit note on a progress invoice lowers the final invoice's deduction per tax rate (quotation 10000,
   progress 1000 = 800 at 19 % + 200 at 7 %, credit 200 at 19 % -> the final invoice deducts 600 + 200 = 800); the
   dialog's "not yet billed" grows by the credit; a final draft made before the credit note is not finalised (400)
 - #2836 2: an invoice from the quotation without a type is refused (409) once a progress invoice is finalised; a
   progress draft alone does not block it
 - #2836 3: a credit note on a progress invoice that a finalised final invoice deducts: 409 on the draft route and on
   finalising a credit draft made before the final invoice was finalised
 - #2842 revenue per client: an invoice of 1000 with a full credit note counts 0 (was -1000, margin too); a partial
   credit note of 200 on another invoice still counts 800
 - 2.523.0 (#4082) final invoice in a foreign currency: the deduction = what the progress invoice billed in that currency
   (its own rate), also after the final draft's rate changed
 Each flow runs for an organisation's admin and for a person without organisation (personal office).
usage: p2354_b_abschlag_test.py <datadir>      (P2354B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time
from decimal import Decimal

import requests
from freelancer_fixture import freelancer
import testclock  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
IBAN = "DE02120300000000202051"
TODAY = testclock.today()


def dd(v):
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def company(s, name):
    r = s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {
        "name": name, "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "tax_number": "12/345/67890",
        "iban": IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    assert r.ok, r.text


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def offer(s, cl):
    """A quotation: 2 x 4000 (19 %) + 1 x 2000 (7 %) = net 10000.00."""
    r = s.post(B + D, json={"project_title": "Imagefilm", "client_id": cl, "service_from": TODAY.replace(day=1).isoformat(), "service_to": TODAY.isoformat()})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    r = s.put(B + f"{D}/{oid}/items", json={"items": [{"title": "Dreh", "qty": 2, "unit": "day", "rate": 4000, "tax": "standard"},
                                                      {"title": "Buch", "qty": 1, "unit": "flat", "rate": 2000, "tax": "reduced"}]})
    assert r.ok, r.text
    return oid


def deductions(doc):
    return [(dd(x["rate"]), x["tax"]) for x in doc["items"] if x["kind"] == "discount"]


def dnets(doc, kind):
    """{tax key: abs(net)} of the calculated lines of a kind (the amounts in the document currency)"""
    out = {}
    for ln in doc["totals"]["lines"]:
        if ln.get("kind") == kind:
            out[ln["tax"]] = out.get(ln["tax"], Decimal(0)) + abs(dd(ln["net"]))
    return out


def fx_final(s, cl, label):
    """2.523.0 (#4082): a quotation in USD (rate 1.10), its progress invoice of 1000 USD finalised with rate 1.20 (its own
    rate): the final invoice deducts the USD net per rate the progress invoice billed (727.27 EUR x 1.20 = 872.72 + the 7 % part), not the EUR net x
    the final invoice's rate 1.10 (800 + 200); a rate changed on the final draft keeps the billed amounts and finalises."""
    q = offer(s, cl)
    check(s.patch(B + f"{D}/{q}", json={"currency": "USD", "fx_rate": "1.1"}).ok, f"{label} #4082: quotation in USD")
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "progress", "amount": 1000})
    check(r.status_code == 201, f"{label} #4082: progress 1000 USD " + r.text[:200])
    P = r.json()["id"]
    check(s.patch(B + f"{D}/{P}", json={"fx_rate": "1.2"}).ok and s.post(B + f"{D}/{P}/finalize").ok, f"{label} #4082: progress finalised at rate 1.20")
    billed = dnets(s.get(B + f"{D}/{P}").json(), "item")
    check(billed.get("standard") == Decimal("872.72") and sum(billed.values()) > Decimal("1090"), f"{label} #4082: the progress invoice billed at 1.20 {billed}")
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "final"})
    check(r.status_code == 201, f"{label} #4082: final draft " + r.text[:200])
    F = r.json()["id"]
    got = dnets(r.json(), "discount")
    check(got == billed, f"{label} #4082: the final invoice deducts what was billed in USD (was EUR x 1.10 = 800 + 200) {got}")
    r = s.patch(B + f"{D}/{F}", json={"fx_rate": "1.15"})
    got = dnets(r.json(), "discount") if r.ok else {}
    check(got == billed, f"{label} #4082: a new rate on the final draft keeps the billed deduction {got}")
    r = s.post(B + f"{D}/{F}/finalize")
    check(r.ok, f"{label} #4082: the final draft with a changed rate finalises (no stale-deduction 400) {r.status_code} " + r.text[:200])


def flow(s, label):
    cl = client(s, "Kunde " + label + " GmbH")
    # ---- #2836 2: a progress draft does not block the full invoice, a finalised one does
    q0 = offer(s, cl)
    r = s.post(B + f"{D}/{q0}/invoice", json={"inv_type": "progress", "pct": 10})
    check(r.status_code == 201, f"{label}: progress draft " + r.text[:200])
    r = s.post(B + f"{D}/{q0}/invoice", json={})
    check(r.status_code == 201, f"{label} #2836 2: a progress draft alone keeps the full invoice possible {r.status_code}")
    q = offer(s, cl)
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "progress", "amount": 1000})
    check(r.status_code == 201 and [(dd(x["rate"]), x["tax"]) for x in r.json()["items"]] == [(Decimal("800.00"), "standard"), (Decimal("200.00"), "reduced")],
          f"{label}: progress 1000 = 800 + 200 " + r.text[:200])
    P = r.json()["id"]
    check(s.post(B + f"{D}/{P}/finalize").ok, f"{label}: progress finalised")
    r = s.post(B + f"{D}/{q}/invoice", json={})
    check(r.status_code == 409 and ("final invoice" in r.text or "Schlussrechnung" in r.text),
          f"{label} #2836 2: an invoice without type after a finalised progress invoice 409 " + f"{r.status_code} " + r.text[:200])
    r = s.post(B + f"{D}/{q}/invoice", json={"parts_mode": "summary"})
    check(r.status_code == 409, f"{label} #2836 2: ... also with a parts mode {r.status_code}")
    # ---- #2836 1: a final draft, then a partial credit note on the progress invoice
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "final"})
    check(r.status_code == 201 and deductions(r.json()) == [(Decimal("800.00"), "standard"), (Decimal("200.00"), "reduced")],
          f"{label}: final draft before the credit note deducts 1000 " + str(deductions(r.json())))
    F0 = r.json()["id"]
    r = s.post(B + f"{D}/{P}/credit")
    check(r.status_code == 201, f"{label}: credit draft on the progress invoice " + r.text[:200])
    CR = r.json()["id"]
    r = s.put(B + f"{D}/{CR}/items", json={"items": [{"title": "Teilgutschrift", "qty": 1, "unit": "flat", "rate": 200, "tax": "standard"}]})
    check(r.ok, f"{label}: credit of 200 at 19 % " + r.text[:200])
    check(s.post(B + f"{D}/{CR}/finalize").ok, f"{label}: partial credit note finalised")
    check(s.get(B + f"{D}/{P}").json()["status"] != "cancelled", f"{label}: the progress invoice stays (partial credit)")
    pr = s.get(B + f"{D}/{q}/progress").json()
    check(dd(pr["billed"]) == Decimal("800.00") and dd(pr["remaining"]) == Decimal("9200.00"), f"{label} #2836 1: billed less the credit {pr.get('billed')} / {pr.get('remaining')}")
    r = s.post(B + f"{D}/{F0}/finalize")
    check(r.status_code == 400, f"{label} #2836 1: the final draft from before the credit note is not finalised {r.status_code} " + r.text[:200])
    s.delete(B + f"{D}/{F0}")
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "final"})
    f = r.json()
    check(r.status_code == 201 and deductions(f) == [(Decimal("600.00"), "standard"), (Decimal("200.00"), "reduced")],
          f"{label} #2836 1: the final invoice deducts 800 (600 + 200) " + str(deductions(f)))
    check(dd(f["totals"]["net"]) == Decimal("9200.00"), f"{label} #2836 1: final net 9200 ({f['totals'].get('net')})")
    # ---- #2836 3: a credit draft made now, the final invoice finalised, then no credit note on the progress invoice
    CR2 = s.post(B + f"{D}/{P}/credit").json()["id"]
    s.put(B + f"{D}/{CR2}/items", json={"items": [{"title": "Teil", "qty": 1, "unit": "flat", "rate": 100, "tax": "standard"}]})  # under the rest: no "exceeds" 409
    check(s.post(B + f"{D}/{f['id']}/finalize").ok, f"{label}: final invoice finalised")
    r = s.post(B + f"{D}/{P}/credit")
    check(r.status_code == 409, f"{label} #2836 3: no credit note on a deducted progress invoice {r.status_code} " + r.text[:200])
    r = s.post(B + f"{D}/{CR2}/finalize")
    check(r.status_code == 409, f"{label} #2836 3: an older credit draft is not finalised either {r.status_code} " + r.text[:200])
    check(s.get(B + f"{D}/{P}").json()["status"] != "cancelled", f"{label} #2836 3: the progress invoice stays")
    fx_final(s, cl, label)
    # ---- #2842 revenue per client
    year = TODAY.year
    for name, credit in (("Voll", None), ("Teil", 200)):
        k = client(s, f"Kunde {name} {label} GmbH")
        r = s.post(B + D, json={"kind": "invoice", "client_id": k, "service_from": TODAY.isoformat(), "service_to": TODAY.isoformat(),
                                "items": [{"title": "Schnitt", "qty": 1, "unit": "flat", "rate": 1000, "tax": "standard"}]})
        inv = r.json()["id"]
        check(s.post(B + f"{D}/{inv}/finalize").ok, f"{label}: invoice {name} finalised")
        c_ = s.post(B + f"{D}/{inv}/credit").json()["id"]
        if credit:
            s.put(B + f"{D}/{c_}/items", json={"items": [{"title": "Teil", "qty": 1, "unit": "flat", "rate": credit, "tax": "standard"}]})
        check(s.post(B + f"{D}/{c_}/finalize").ok, f"{label}: credit {name} finalised")
        row = [x for x in s.get(B + O + f"/kpi?year={year}").json()["clients"] if x["id"] == k]
        if credit:
            check(row and dd(row[0]["invoiced"]) == Decimal("800.00") and dd(row[0]["margin"]) == Decimal("800.00"),
                  f"{label} #2842: partial credit 200 -> 800 {row}")
        else:
            check(not row or (dd(row[0]["invoiced"]) == 0 and dd(row[0]["margin"]) == 0), f"{label} #2842: full credit -> 0, not -1000 {row}")


if os.environ.get("P2354B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
company(A, "Beispiel Studio GmbH")
flow(A, "org")

FID, Fr = freelancer(B, A)
company(Fr, "Frida Film")
flow(Fr, "freelancer")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
