#!/usr/bin/env python3
# kalmido-suite:
"""2.355.0 A API tests (#2839, #2847): number series and small invoice fixes in the personal office of a person without an
organisation (freelancer fixture; freelancer-matrix: office), own container (start.sh, KALMIDO_SMTP_HOST set so a series
may auto-send). Invented companies, people and the test IBAN only.
 - #2839 a hand-set number in parallel to finalising (threads): the finalised invoice keeps the number of its stored files;
   a manual number of another year 409 (no counter moved); a numbered draft keeps its date within the number's year;
   inv_type final only from the quotation (PATCH 409), a copy of a final invoice is a plain one; undo keeps a number set since
 - #2847 status paid by hand books a payment of the open rest; payments + credit notes above the gross show "overpaid";
   a position rate "1.234.567" is 1234567 (was 400); a series whose auto-send fails after finalising leaves no stored files
usage: p2355_a_numbers_test.py <datadir>      (P2355A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import glob
import os
import subprocess
import sys
import threading
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"

if os.environ.get("P2355A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none"
               " -e KALMIDO_MAIL_FROM=kalmido@example.test")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
FID, Fr = freelancer(B, A)

r = Fr.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht"}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                      "company_fields": {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                         "country": "DE", "email": "hallo@nordlicht.example", "phone": "+49 40 000000",
                                                         "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                         "bank_name": "Beispielbank"}})
check(r.ok, "freelancer office settings " + r.text[:200])
ST = Fr.get(B + O + "/settings").json()["settings"]
SCHEME = ST.get("invoice_scheme") or ""
check("{yyyy}" in SCHEME and "{seq" in SCHEME, f"the invoice scheme holds the year and the counter ({SCHEME!r})")
YEAR = date.today().year


def client(**kw):
    r = Fr.post(B + "/api/clients", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


CL = client(name="Beispielkunde AG", street="Marktstraße 5", zip="50667", city="Köln", country="DE", email="rechnung@kunde.example.com")


def invoice(items=None, **kw):
    r = Fr.post(B + D, json=dict({"kind": "invoice", "client_id": CL, "service_from": f"{YEAR}-01-01", "service_to": f"{YEAR}-01-20",
                                  "items": items or [{"title": "Regie", "qty": 1, "rate": 100}]}, **kw))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doc(did):
    return Fr.get(B + f"{D}/{did}").json()


def num(seq, year=YEAR):
    return SCHEME.replace("{yyyy}", str(year)).replace("{seq:03}", f"{seq:03d}").replace("{seq}", str(seq))


def last_seq():
    """The highest counter of this year's finalised / numbered invoices."""
    out = 0
    for x in Fr.get(B + D, params={"kind": "invoice"}).json().get("docs", []):
        n = x.get("number") or ""
        for k in range(1, 400):
            if n == num(k):
                out = max(out, k)
                break
    return out


def stored(did):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA, "office", "*", f"doc{did}-*")))


# ---------------------------------------------------------------- #2839 finalising and a hand-set number in parallel (threads)
bad = []
for i in range(6):
    I = invoice()
    nxt = num(last_seq() + 2)  # one above the next: a gap with a reason, valid before and after finalising draws the next
    res = {}

    def fin():
        res["f"] = Fr.post(B + f"{D}/{I}/finalize")

    def setnum():
        res["n"] = Fr.post(B + f"{D}/{I}/number", json={"number": nxt, "reason": "Nummer aus dem Altsystem"})
    ts = [threading.Thread(target=fin), threading.Thread(target=setnum)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    d = doc(I)
    files = stored(I)
    want = f"doc{I}-invoice-{d.get('number')}.pdf"
    if not (res["f"].ok and d.get("locked") and want in files):
        bad.append((i, res["f"].status_code, res["n"].status_code, d.get("number"), files))
check(not bad, f"#2839: a finalised invoice keeps the number of its stored files, also with a parallel number change {bad}")
I = invoice()
check(Fr.post(B + f"{D}/{I}/finalize").ok, "finalised")
check(Fr.post(B + f"{D}/{I}/number", json={"number": num(last_seq() + 1)}).status_code == 409, "#2839: a finalised invoice: no new number (409)")

# ---------------------------------------------------------------- #2839 the year of a manual number
I = invoice(date=f"{YEAR}-01-15")
before = last_seq()
r = Fr.post(B + f"{D}/{I}/number", json={"number": num(before + 1, 1999)})  # the next counter value, only the year is wrong
check(r.status_code == 409 and "1999" in r.text, f"#2839: a number of 1999 on a draft of {YEAR}: 409 naming the year {r.status_code} {r.text[:160]}")
r = Fr.post(B + f"{D}/{I}/number", json={"number": num(before + 1)})
check(r.ok and r.json().get("number") == num(before + 1), f"#2839: ... no counter moved, the next number of {YEAR} still fits {r.text[:160]}")

# ---------------------------------------------------------------- #2839 a numbered draft keeps its date within the year
r = Fr.patch(B + f"{D}/{I}", json={"date": f"{YEAR - 1}-12-30"})
check(r.status_code == 409 and num(before + 1) in r.text, f"#2839: numbered draft, date into {YEAR - 1}: 409 {r.status_code} {r.text[:160]}")
r = Fr.patch(B + f"{D}/{I}", json={"date": f"{YEAR}-01-10"})
check(r.ok and r.json().get("date") == f"{YEAR}-01-10", "#2839: ... within the year the date may change " + r.text[:120])
U = invoice()
r = Fr.patch(B + f"{D}/{U}", json={"date": f"{YEAR - 1}-12-30"})
check(r.ok, "#2839: a draft without a number moves freely " + r.text[:120])

# ---------------------------------------------------------------- #2839 undo keeps a number set since
TOK = "ab2355" + "0" * 10
I2 = invoice()
n1 = num(last_seq() + 1)
check(Fr.post(B + f"{D}/{I2}/number", json={"number": n1}).ok, "a first number by hand")
r = Fr.patch(B + f"{D}/{I2}", json={"project_title": "Vorher"}, headers={"X-Kalmido-Undo": TOK})
check(r.ok, "an undo step " + r.text[:120])
n2 = num(last_seq() + 1)
check(Fr.post(B + f"{D}/{I2}/number", json={"number": n2}).ok, "number set by hand after the step")
r = Fr.post(B + f"{O}/undo/doc/{I2}", json={"sess": TOK, "op": "all"})
d = doc(I2)
check(r.ok and d.get("project_title") != "Vorher" and d.get("number") == n2,
      f"#2839: undo takes the step back and keeps the number set since ({r.status_code} {r.text[:120]}, {d.get('number')!r} vs {n2!r})")

# ---------------------------------------------------------------- #2839 inv_type: final only from the quotation, a copy is plain
X = invoice()
check(Fr.patch(B + f"{D}/{X}", json={"inv_type": "final"}).status_code == 409, "#2839: PATCH inv_type final on an invoice: 409")
check(doc(X).get("inv_type") == "", "... it stays a plain invoice")
r = Fr.patch(B + f"{D}/{X}", json={"inv_type": "progress"})
check(r.ok and r.json().get("inv_type") == "progress", "the type progress is still set by hand (head field of the editor) " + r.text[:120])
check(Fr.post(B + D, json={"kind": "invoice", "client_id": CL, "inv_type": "final"}).status_code == 409, "#2839: a new invoice as final: 409")
Q = Fr.post(B + D, json={"client_id": CL, "project_title": "Schluss"}).json()["id"]
Fr.put(B + f"{D}/{Q}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 1, "unit": "day", "rate": 1000}]})
Fr.post(B + f"{D}/{Q}/finalize")
Fr.post(B + f"{D}/{Q}/status", json={"status": "sent"})
Fr.post(B + f"{D}/{Q}/status", json={"status": "accepted"})
r = Fr.post(B + f"{D}/{Q}/invoice", json={"inv_type": "final"})
check(r.status_code == 201 and r.json().get("inv_type") == "final", "final invoice from the quotation " + r.text[:160])
FI = r.json()["id"]
r = Fr.patch(B + f"{D}/{FI}", json={"inv_type": "final", "project_title": "Schluss 2"})
check(r.ok, "a final invoice keeps its type on a save " + r.text[:120])
r = Fr.post(B + f"{D}/{FI}/duplicate")
check(r.ok and r.json().get("inv_type") == "", f"#2839: the copy of a final invoice is a plain invoice ({r.json().get('inv_type')!r})")

# ---------------------------------------------------------------- #2847 status paid by hand = a payment of the open rest
P = invoice([{"title": "Regie", "qty": 1, "rate": 1000}])
check(Fr.post(B + f"{D}/{P}/finalize").ok, "finalised")
check(Fr.post(B + f"{D}/{P}/payments", json={"amount": "190.00"}).status_code == 201, "a part payment")
r = Fr.post(B + f"{D}/{P}/status", json={"status": "paid"})
check(r.ok and r.json().get("status") == "paid" and r.json().get("paid_at"), "status paid by hand " + r.text[:160])
pay = Fr.get(B + f"{D}/{P}/payments").json()
amts = sorted(x.get("amount") for x in pay.get("payments") or [])
check(pay.get("open") == "0.00" and pay.get("paid") == "1190.00" and len(amts) == 2,
      f"#2847: paid by hand books the open rest 1000.00: status and open amount agree {pay.get('paid')} {pay.get('open')} {amts}")
check(Fr.post(B + f"{D}/{P}/status", json={"status": "sent"}).status_code == 409, "... taking it back needs the payments removed (409)")

# ---------------------------------------------------------------- #2847 overpaid: payment + credit note above the gross
V = invoice([{"title": "Regie", "qty": 1, "rate": 100}])
check(Fr.post(B + f"{D}/{V}/finalize").ok, "finalised")
check(Fr.post(B + f"{D}/{V}/payments", json={"amount": "119.00"}).status_code == 201, "paid in full")
r = Fr.post(B + f"{D}/{V}/credit")
check(r.status_code == 201, "credit note draft " + r.text[:120])
CR = r.json()["id"]
Fr.put(B + f"{D}/{CR}/items", json={"items": [{"kind": "service", "title": "Regie (Teil)", "qty": 1, "unit": "flat", "rate": 10}]})
check(Fr.post(B + f"{D}/{CR}/finalize").ok, "partial credit note finalised")
pay = Fr.get(B + f"{D}/{V}/payments").json()
check(pay.get("open") == "0.00" and pay.get("overpaid") == "11.90", f"#2847: overpaid 11.90 instead of a silent open 0 {pay}")
check(doc(V).get("overpaid") == "11.90", "... also in the document")
check(doc(P).get("overpaid") == "0.00", "... a plainly paid invoice: 0.00")

# ---------------------------------------------------------------- #2847 dec(): dotted groups
r = Fr.post(B + D, json={"kind": "invoice", "client_id": CL, "items": [{"title": "Groß", "qty": 1, "rate": "1.234.567"}]})
check(r.status_code == 201 and r.json().get("totals", {}).get("net") == "1234567.00", f"#2847: rate '1.234.567' = 1234567.00 {r.status_code} {r.text[:200]}")
r = Fr.post(B + D, json={"kind": "invoice", "client_id": CL, "items": [{"title": "Kaputt", "qty": 1, "rate": "1.2.3"}]})
check(r.status_code == 400, f"... '1.2.3' is no number (400) {r.status_code}")

# ---------------------------------------------------------------- #2847 no stored files of a finalising that was rolled back
Fr.put(B + O + "/settings", json={"datev_auto": 1, "datev_email": ""})  # the DATEV copy is due but has no inbox: fails after finalising
T = invoice()
r = Fr.post(B + O + "/series", json={"template_id": T, "every": "monthly", "start": date.today().isoformat(), "auto_send": True})
check(r.status_code == 201, "series with auto-send " + r.text[:160])
r = Fr.post(B + f"{O}/series/{r.json()['id']}/run")
j = r.json() if r.ok else {}
nd = j.get("doc_id")
check(r.ok and nd and not j.get("sent") and "DATEV" in (j.get("error") or ""), f"precondition: auto-send fails at the DATEV check after finalising {r.status_code} {r.text[:200]}")
check(nd and not doc(nd).get("locked") and stored(nd) == [], f"#2847: the series invoice stays a draft without stored files {stored(nd) if nd else ''}")
Fr.put(B + O + "/settings", json={"datev_auto": 0})

print(f"p2355_a_numbers: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
