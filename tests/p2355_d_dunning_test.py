#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.355.0 D (#2846): dunning. Own container (start.sh, mode workspaces). Invented companies, people and figures only.
freelancer-matrix: office
 - only invoices past their due date can be reminded of: due in 14 days or due today = 409 naming the invoice, due
   yesterday = 201, an old invoice without a due date = 201; a reminder mixing a due and a not yet due invoice = 409
 - the open fee of a finalised reminder is cancelled with its invoice (full credit note): fee_state "cancelled", no
   open fee on the reminder or the invoice, the office log line, waiving / opening it again = 409; a reminder over two
   invoices keeps its fee until both are cancelled; a waived fee stays waived
 - default interest + 40 EUR flat fee: off by default (totals 0, total = open + fee); on: open x (base rate + 5) x
   days / 365 for a consumer, + 9 points and 40 EUR per invoice for a business (VAT ID or the setting); the editor's
   totals, the print model's rows and the GiroCode show the same total; a finalised reminder keeps its figures when the
   settings change; settings checks (base rate -10..30, client kind auto / business / consumer)
 - a person without an organisation: the same in the own personal office
usage: p2355_d_dunning_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests

import dbx as dbxm
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients"
IBAN = "DE02120300000000202051"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

if not os.environ.get("P2355D_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
TODAY = testclock.today()
ago = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
# the watchdog's suggestions off: only the drafts made here
assert A.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": COMPANY}).ok


def due(did, n):
    """The due date of invoice did n days back (None = no due date, like an old import)."""
    dbxm.q(DATA, "UPDATE office_docs SET due_date=? WHERE id=?", (ago(n) if n is not None else None, did))


def client(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE", **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def invoice(s, cl, rate=500, due_ago=None):
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": "Schnitt", "service_from": "2026-05-01",
                            "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    f = s.post(B + f"{D}/{did}/finalize")
    check(f.ok, f"setup: invoice {did} finalised " + f.text[:200])
    if due_ago is not None:
        due(did, due_ago)
    return did


def remind(s, ids, level=1, fee=None):
    return s.post(B + D + "/reminder", json={"doc_ids": ids, "level": level, **({"fee": fee} if fee is not None else {})})


def cancel(s, did):
    """A full credit note: the invoice becomes cancelled."""
    r = s.post(B + f"{D}/{did}/credit")
    check(r.status_code == 201, f"setup: credit note draft of {did} " + r.text[:200])
    f = s.post(B + f"{D}/{r.json()['id']}/finalize")
    check(f.ok and s.get(B + f"{D}/{did}").json()["status"] == "cancelled", f"setup: invoice {did} cancelled by the credit note " + f.text[:200])


def m2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interest(open_, rate, days):
    return m2(m2(Decimal(open_)) * Decimal(rate) / 100 * days / 365)


def run(s, who):
    cl = client(s, f"Kunde {who}")
    clb = client(s, f"Firma {who} GmbH", vat_id="DE987654321")

    # ---------------------------------------------------------------- only overdue invoices
    early = invoice(s, cl)  # due in 14 days
    num = s.get(B + f"{D}/{early}").json()["number"]
    r = remind(s, [early])
    check(r.status_code == 409 and num in r.text, f"{who}: an invoice not yet due cannot be reminded of: 409 naming it ({r.status_code} {r.text[:200]})")
    due(early, 0)
    check(remind(s, [early]).status_code == 409, f"{who}: due today: still 409")
    late = invoice(s, cl, due_ago=1)
    check(remind(s, [late, early]).status_code == 409, f"{who}: a due and a not yet due invoice together: 409")
    r = remind(s, [late])
    check(r.status_code == 201, f"{who}: due yesterday: the reminder draft " + r.text[:200])
    if r.ok:
        s.delete(B + f"{D}/{r.json()['id']}")
    due(early, None)
    r = remind(s, [early])
    check(r.status_code == 201, f"{who}: without a due date (old import): allowed " + r.text[:200])
    if r.ok:
        s.delete(B + f"{D}/{r.json()['id']}")

    # ---------------------------------------------------------------- the fee is cancelled with the invoice
    i1 = invoice(s, cl, due_ago=20)
    r = remind(s, [i1], level=2, fee=5)
    rm1 = r.json()["id"]
    check(s.post(B + f"{D}/{rm1}/finalize").ok, f"{who}: the reminder with a fee finalised")
    d = s.get(B + f"{D}/{rm1}").json()
    check(d.get("fee_state") == "" and d.get("fee_open") == "5.00", f"{who}: the fee is open {d.get('fee_state')!r} {d.get('fee_open')}")
    cancel(s, i1)
    d = s.get(B + f"{D}/{rm1}").json()
    check(d.get("fee_state") == "cancelled" and d.get("fee_open") == "0.00", f"{who}: the fee is cancelled with the invoice {d.get('fee_state')!r} {d.get('fee_open')}")
    inv = s.get(B + f"{D}/{i1}").json()
    check(not inv.get("fee_reminders") and not float(inv.get("fee_open") or 0), f"{who}: the cancelled invoice shows no open fee {inv.get('fee_reminders')}")
    lg = [x for x in s.get(B + O + "/log", params={"limit": 500}).json()["log"] if x.get("doc_id") == rm1 and x.get("action") == "reminder_fee"]
    check(lg and (lg[0].get("detail") or {}).get("after") == "cancelled", f"{who}: the office log has the change {lg[:1]}")
    for st in ("waived", "paid", ""):
        r = s.post(B + f"{D}/{rm1}/fee", json={"state": st})
        check(r.status_code == 409, f"{who}: a cancelled fee stays cancelled ({st!r}: {r.status_code})")
    # two invoices: the fee stays until both are cancelled
    i2, i3 = invoice(s, cl, due_ago=20), invoice(s, cl, due_ago=20)
    rm2 = remind(s, [i2, i3], level=2, fee=5).json()["id"]
    s.post(B + f"{D}/{rm2}/finalize")
    cancel(s, i2)
    check(s.get(B + f"{D}/{rm2}").json().get("fee_state") == "", f"{who}: one of two invoices cancelled: the fee stays open")
    cancel(s, i3)
    check(s.get(B + f"{D}/{rm2}").json().get("fee_state") == "cancelled", f"{who}: both cancelled: the fee is cancelled")
    # a waived fee stays waived
    i4 = invoice(s, cl, due_ago=20)
    rm4 = remind(s, [i4], level=2, fee=5).json()["id"]
    s.post(B + f"{D}/{rm4}/finalize")
    check(s.post(B + f"{D}/{rm4}/fee", json={"state": "waived"}).ok, f"{who}: the fee waived")
    cancel(s, i4)
    check(s.get(B + f"{D}/{rm4}").json().get("fee_state") == "waived", f"{who}: a waived fee stays waived after the cancellation")

    # ---------------------------------------------------------------- default interest + flat fee
    st = s.get(B + O + "/settings").json()["settings"]
    check((st.get("dunning_interest"), st.get("dunning_flat_fee"), st.get("base_rate"), st.get("dunning_client_kind")) == (0, 0, 1.52, "auto"),
          f"{who}: defaults: interest + flat fee off, base rate 1.52, auto {st.get('dunning_interest')} {st.get('dunning_flat_fee')} {st.get('base_rate')} {st.get('dunning_client_kind')}")
    i5 = invoice(s, cl, due_ago=30)  # 595.00 gross
    t = s.get(B + f"{D}/{remind(s, [i5], level=2, fee=5).json()['id']}").json()["totals"]
    check(t.get("interest") == "0.00" and t.get("flat_fee") == "0.00" and t.get("gross") == "600.00", f"{who}: off: no interest, no flat fee {t.get('interest')} {t.get('flat_fee')} {t.get('gross')}")
    for bad in ({"base_rate": 31}, {"base_rate": "x"}, {"dunning_client_kind": "x"}):
        check(s.put(B + O + "/settings", json=bad).status_code == 400, f"{who}: settings check {bad}")
    check(s.put(B + O + "/settings", json={"dunning_interest": 1, "dunning_flat_fee": 1, "base_rate": "1,52"}).ok, f"{who}: interest + flat fee on")
    r = remind(s, [i5], level=2, fee=5)
    rm5 = r.json()["id"]
    t = s.get(B + f"{D}/{rm5}").json()["totals"]
    want = interest("595.00", "6.52", 30)
    ln = [x for x in t.get("lines", []) if x.get("kind") == "ref"]
    check(t.get("interest") == str(want) and t.get("interest_rate") == "6.52" and ln and ln[0].get("interest_days") == 30,
          f"{who}: a consumer: base rate + 5 for 30 days = {want} ({t.get('interest')} {t.get('interest_rate')} {ln[:1]})")
    check(t.get("flat_fee") == "0.00" and t.get("gross") == str(Decimal("600.00") + want), f"{who}: no flat fee for a consumer, total {t.get('gross')}")
    rv = s.get(B + f"{D}/{rm5}/render").json()
    rows = json.dumps((rv.get("totals") or {}).get("rows") or [], ensure_ascii=False)
    check("Verzugszinsen" in rows and str(want).replace(".", ",") in rows and "Pauschale" not in rows, f"{who}: the print model has the interest row {rows[:300]}")
    gc = ((rv.get("payment") or {}).get("girocode") or "").split("\n")
    check(len(gc) > 7 and gc[7] == f"EUR{Decimal('600.00') + want}", f"{who}: the GiroCode asks for the same total {gc[7:8]}")
    # a business (VAT ID): + 9 points and 40 EUR
    i6 = invoice(s, clb, due_ago=30)
    t = s.get(B + f"{D}/{remind(s, [i6], level=1).json()['id']}").json()["totals"]
    want6 = interest("595.00", "10.52", 30)
    check(t.get("interest") == str(want6) and t.get("flat_fee") == "40.00" and t.get("gross") == str(Decimal("635.00") + want6),
          f"{who}: a business: + 9 points and 40 EUR ({t.get('interest')} {t.get('flat_fee')} {t.get('gross')})")
    check(s.put(B + O + "/settings", json={"dunning_client_kind": "consumer"}).ok, f"{who}: all clients consumers")
    rmc = remind(s, [i6], level=1).json()["id"]
    t = s.get(B + f"{D}/{rmc}").json()["totals"]
    check(t.get("interest") == str(interest("595.00", "6.52", 30)) and t.get("flat_fee") == "0.00", f"{who}: the setting overrides the VAT ID {t.get('interest')} {t.get('flat_fee')}")
    check(s.put(B + O + "/settings", json={"dunning_client_kind": "business"}).ok, f"{who}: all clients businesses")
    # a finalised reminder keeps its figures
    check(s.post(B + f"{D}/{rm5}/finalize").ok, f"{who}: the reminder with interest finalised")
    t0 = s.get(B + f"{D}/{rm5}").json()["totals"]
    check(s.put(B + O + "/settings", json={"dunning_interest": 0, "dunning_flat_fee": 0, "dunning_client_kind": "auto"}).ok, f"{who}: switched off again")
    t1 = s.get(B + f"{D}/{rm5}").json()["totals"]
    check(t1.get("interest") == t0.get("interest") == str(want) and t1.get("gross") == t0.get("gross"), f"{who}: the finalised reminder keeps interest and total (GoBD) {t1.get('interest')} {t1.get('gross')}")


run(A, "Alpha")
# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A, "dave")
check(Fr.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": dict(COMPANY, name="Dave Schnitt")}).ok, "freelancer: own office settings")
run(Fr, "freelancer")

print(f"p2355_d_dunning: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
