#!/usr/bin/env python3
"""2.120.0 API tests, part A (#2087): progress and final invoices, cash discount (Skonto).
Own container (start.sh, org encryption on). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - cash discount: the office default (settings) lands on new invoices; PATCH per draft; the print model prints the line
   under the payment terms; the e-invoice carries #SKONTO#TAGE=n#PROZENT=p.pp# in BT-20; a payment of gross less discount
   within the period = paid (open 0.00), after the period the difference stays open
 - progress invoices from a quotation with 19 % and 7 % positions: by percentage and by amount, split onto the rates (cents
   exact), more than the quotation's net is refused, the list of the dialog; e-invoice type 326, title "Abschlagsrechnung"
 - final invoice: the whole quotation less the finalised progress invoices per rate (drafts are not deducted), the sums on
   the cent (progress + final = quotation gross), type 380 with negative lines; a progress invoice cancelled by a credit note
   after the final draft -> finalising refused, the new final invoice no longer deducts it
 - rights: a member without the office 403, another organisation 404, an agent token 403, an unknown inv_type 400; a
   person without organisation (personal office) does the same
usage: p2120_a_api_test.py <datadir>      (P2120A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
IBAN = "DE02120300000000202051"
TODAY = date.today()


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
    """A quotation: 2 x 4000 (19 %) + 1 x 2000 (7 %) = net 10000.00, gross 11660.00."""
    r = s.post(B + D, json={"project_title": "Imagefilm", "client_id": cl, "service_from": TODAY.replace(day=1).isoformat(), "service_to": TODAY.isoformat()})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    r = s.put(B + f"{D}/{oid}/items", json={"items": [{"title": "Dreh", "qty": 2, "unit": "day", "rate": 4000, "tax": "standard"},
                                                      {"title": "Buch", "qty": 1, "unit": "flat", "rate": 2000, "tax": "reduced"}]})
    assert r.ok, r.text
    return oid


def xml(s, did):
    return s.get(B + f"{D}/{did}/xml").content.decode("utf-8", "replace")


def type_code(x):
    m = re.search(r"<rsm:ExchangedDocument>.*?<ram:TypeCode>(\d+)</ram:TypeCode>", x, re.S)
    return m.group(1) if m else None


def progress_flow(s, label):
    """The whole flow in one office (organisation or personal): -> (offer id, [progress ids], final id)."""
    cl = client(s, "Kunde " + label + " GmbH")
    off = offer(s, cl)
    q = s.get(B + f"{D}/{off}").json()
    check(dd(q["totals"]["gross"]) == Decimal("11660.00"), f"{label}: quotation gross {q['totals'].get('gross')}")
    r = s.get(B + f"{D}/{off}/progress")
    check(r.ok and dd(r.json()["net"]) == Decimal("10000.00") and r.json()["progress"] == [], f"{label}: progress list empty " + r.text[:200])
    # progress 1: 33.33 % -> 3333.00 net, 2666.40 at 19 % + 666.60 at 7 %
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "pct": 33.33})
    check(r.status_code == 201, f"{label}: progress invoice by percentage " + r.text[:200])
    p1 = r.json()
    rows = [(dd(x["rate"]), x["tax"]) for x in p1["items"]]
    check(p1["inv_type"] == "progress" and rows == [(Decimal("2666.40"), "standard"), (Decimal("666.60"), "reduced")], f"{label}: split onto the rates {rows}")
    check(all("Abschlag Nr. 1" in x["title"] for x in p1["items"]), f"{label}: position text " + str([x["title"] for x in p1["items"]]))
    check(dd(p1["totals"]["net"]) == Decimal("3333.00") and dd(p1["totals"]["gross"]) == Decimal("3886.28"), f"{label}: progress 1 sums {p1['totals'].get('gross')}")
    rd = s.get(B + f"{D}/{p1['id']}/render").json()
    check(rd.get("title") == "Abschlagsrechnung" and rd.get("type_code") == "326", f"{label}: title / type code " + str((rd.get("title"), rd.get("type_code"))))
    r = s.post(B + f"{D}/{p1['id']}/finalize")
    check(r.ok, f"{label}: progress 1 finalised " + r.text[:200])
    x = xml(s, p1["id"])
    check(type_code(x) == "326", f"{label}: e-invoice type 326 ({type_code(x)})")
    # progress 2: 2000 net -> 1600 + 400
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "amount": 2000})
    check(r.status_code == 201 and [dd(x["rate"]) for x in r.json()["items"]] == [Decimal("1600.00"), Decimal("400.00")]
          and "Abschlag Nr. 2" in r.json()["items"][0]["title"], f"{label}: progress invoice by amount " + r.text[:200])
    p2 = r.json()["id"]
    check(s.post(B + f"{D}/{p2}/finalize").ok, f"{label}: progress 2 finalised")
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "amount": 4667.01})
    check(r.status_code == 400, f"{label}: more than the quotation's net is refused {r.status_code}")
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "pct": 10})  # a draft: listed, never deducted
    check(r.status_code == 201, f"{label}: a progress draft")
    p3 = r.json()["id"]
    r = s.get(B + f"{D}/{off}/progress").json()
    check([x["id"] for x in r["progress"]] == [p1["id"], p2, p3] and dd(r["remaining"]) == Decimal("3667.00"), f"{label}: the dialog list {r}")
    # final invoice: full quotation less progress 1 + 2
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "final"})
    check(r.status_code == 201, f"{label}: final invoice " + r.text[:200])
    f = r.json()
    neg = [(dd(x["rate"]), x["tax"]) for x in f["items"] if x["kind"] == "discount"]
    check(neg == [(Decimal("2666.40"), "standard"), (Decimal("666.60"), "reduced"), (Decimal("1600.00"), "standard"), (Decimal("400.00"), "reduced")],
          f"{label}: deductions per invoice and rate {neg}")
    check(dd(f["totals"]["net"]) == Decimal("4667.00") and dd(f["totals"]["gross"]) == Decimal("5441.72"), f"{label}: final sums {f['totals'].get('net')} {f['totals'].get('gross')}")
    g1, g2 = dd(p1["totals"]["gross"]), dd(s.get(B + f"{D}/{p2}").json()["totals"]["gross"])
    check(g1 + g2 + dd(f["totals"]["gross"]) == Decimal("11660.00"), f"{label}: progress + final = quotation gross ({g1} + {g2} + {f['totals']['gross']})")
    rd = s.get(B + f"{D}/{f['id']}/render").json()
    check(rd.get("title") == "Schlussrechnung" and any(r_[0] == "Restbetrag" for r_ in rd["totals"]["rows"]), f"{label}: final title / amount remaining")
    return off, [p1["id"], p2, p3], f["id"]


if os.environ.get("P2120A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
company(A, "Beispiel Studio GmbH")

# ================================================================== cash discount
r = A.put(B + O + "/settings", json={"skonto_pct": 2, "skonto_days": 10})
check(r.ok and float(r.json()["settings"]["skonto_pct"]) == 2 and int(r.json()["settings"]["skonto_days"]) == 10, "skonto: office default " + r.text[:200])
check(A.put(B + O + "/settings", json={"skonto_pct": 120}).status_code == 400, "skonto: a percentage above 99.99 is refused")
CL = client(A, "Kunde Skonto GmbH")
# the late payer first (an older date; the series stays in date order)
late = (TODAY - timedelta(days=30)).isoformat()
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "date": late, "service_from": late, "service_to": late,
                        "items": [{"title": "Schnitt", "qty": 1, "unit": "flat", "rate": 1000, "tax": "standard"}]})
check(r.status_code == 201 and float(r.json().get("skonto_pct") or 0) == 2 and r.json().get("skonto_days") == 10, "skonto: the default on a new invoice " + r.text[:300])
LATE = r.json()["id"]
check(A.post(B + f"{D}/{LATE}/finalize").ok, "skonto: late invoice finalised")
r = A.post(B + f"{D}/{LATE}/payments", json={"date": TODAY.isoformat(), "amount": "1166.20"})
d = A.get(B + f"{D}/{LATE}").json()
check(r.ok and d["state"] == "partial" and dd(d["open"]) == Decimal("23.80"), f"skonto: paid after the period -> the discount stays open ({d['state']}, {d.get('open')})")

r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": TODAY.isoformat(), "service_to": TODAY.isoformat(),
                        "items": [{"title": "Schnitt", "qty": 1, "unit": "flat", "rate": 1000, "tax": "standard"}]})
SK = r.json()["id"]
r = A.patch(B + f"{D}/{SK}", json={"skonto_pct": 3, "skonto_days": 7})
check(r.ok and float(r.json()["skonto_pct"]) == 3 and r.json()["skonto_days"] == 7, "skonto: PATCH per draft " + r.text[:200])
check(A.patch(B + f"{D}/{SK}", json={"skonto_pct": 100}).status_code == 400, "skonto: 100 % refused")
check(A.patch(B + f"{D}/{SK}", json={"inv_type": "bogus"}).status_code == 400, "an unknown inv_type 400")
A.patch(B + f"{D}/{SK}", json={"skonto_pct": 2, "skonto_days": 14})
rd = A.get(B + f"{D}/{SK}/render").json()
pt = (rd.get("payment") or {}).get("text") or ""
check("2 % Skonto (= 23,80 €), zahlbar 1.166,20 €" in pt, "skonto: the PDF line " + pt)
check(A.post(B + f"{D}/{SK}/finalize").ok, "skonto: finalised")
x = xml(A, SK)
check("#SKONTO#TAGE=14#PROZENT=2.00#\n" in x, "skonto: BT-20 line in the e-invoice " + (re.search(r"<ram:SpecifiedTradePaymentTerms>.*?</ram:SpecifiedTradePaymentTerms>", x, re.S) or [""])[0][:300])
check(A.patch(B + f"{D}/{SK}", json={"skonto_pct": 5}).status_code == 409, "skonto: a finalised invoice stays unchanged")
check(Bo.post(B + f"{D}/{SK}/payments", json={"amount": "1166.20"}).status_code == 403, "skonto: a member records no payment")
r = A.post(B + f"{D}/{SK}/payments", json={"date": TODAY.isoformat(), "amount": "1166.20"})
d = A.get(B + f"{D}/{SK}").json()
check(r.ok and d["status"] == "paid" and dd(d["open"]) == Decimal("0.00"), f"skonto: paid in time less the discount = paid ({d['status']}, {d.get('open')})")
pid = A.get(B + f"{D}/{SK}/payments").json()
pid = (pid.get("payments") or pid.get("items") or [{}])[0].get("id")
if pid:
    A.delete(B + f"{D}/{SK}/payments/{pid}")
    check(A.get(B + f"{D}/{SK}").json()["status"] != "paid", "skonto: the payment removed -> open again")

# ================================================================== progress / final invoices (organisation)
OFF, PS, FIN = progress_flow(A, "org")
check(type_code(xml(A, PS[0])) == "326", "org: stored XML of a progress invoice")
# cancel progress 2 by a full credit note -> the final draft is out of date
r = A.post(B + f"{D}/{PS[1]}/credit")
check(r.status_code == 201 and A.post(B + f"{D}/{r.json()['id']}/finalize").ok, "storno: credit note over progress 2 finalised")
check(A.get(B + f"{D}/{PS[1]}").json()["status"] == "cancelled", "storno: progress 2 cancelled")
r = A.post(B + f"{D}/{FIN}/finalize")
check(r.status_code == 400 and "progress" in r.text.lower(), "storno: the old final draft cannot be finalised " + r.text[:200])
r = A.post(B + f"{D}/{OFF}/invoice", json={"inv_type": "final"})
F2 = r.json()
neg = [dd(x["rate"]) for x in F2["items"] if x["kind"] == "discount"]
check(neg == [Decimal("2666.40"), Decimal("666.60")] and dd(F2["totals"]["net"]) == Decimal("6667.00"), f"storno: the new final invoice deducts progress 1 only {neg}")
check(A.post(B + f"{D}/{F2['id']}/finalize").ok, "final invoice finalised")
x = xml(A, F2["id"])
check(type_code(x) == "380" and re.search(r"<ram:LineTotalAmount>-2666\.40</ram:LineTotalAmount>", x) is not None, "final: type 380, negative lines")
check(re.search(r"<ram:DuePayableAmount>7773\.72</ram:DuePayableAmount>", x) is not None, "final: amount due 6667.00 + 1013.38 + 93.34 " +
      (re.search(r"<ram:DuePayableAmount>[^<]*", x) or [""])[0])
check(any(i.get("inv_type") == "final" for i in A.get(B + D, params={"kind": "invoice"}).json().get("docs", [])), "list: the type is in the list rows")

# ================================================================== rights
check(Ev.get(B + f"{D}/{OFF}/progress").status_code == 403, "rights: a member without the office 403")
check(Ev.post(B + f"{D}/{OFF}/invoice", json={"inv_type": "progress", "pct": 5}).status_code == 403, "rights: no progress invoice without the office")
check(Ca.get(B + f"{D}/{OFF}/progress").status_code == 404, "rights: another organisation 404")
check(Ca.post(B + f"{D}/{OFF}/invoice", json={"inv_type": "final"}).status_code == 404, "rights: another organisation cannot bill the quotation")
check(requests.get(B + f"{D}/{OFF}/progress", headers=AGH).status_code == 403, "rights: an agent token 403")
check(A.get(B + f"{D}/{PS[0]}/progress").status_code == 409, "an invoice has no progress list (409)")
check(A.post(B + f"{D}/{OFF}/invoice", json={"inv_type": "partial"}).status_code == 400, "an unknown inv_type 400")
r = Bo.post(B + f"{D}/{OFF}/invoice", json={"inv_type": "progress", "pct": 1})
check(r.status_code == 201, "rights: a member with the office drafts a progress invoice " + r.text[:200])

# ================================================================== a person without organisation (personal office)
FID, Fr = freelancer(B, A)
company(Fr, "Frida Film")
check(Fr.put(B + O + "/settings", json={"skonto_pct": 3, "skonto_days": 7}).ok, "freelancer: skonto default")
FOFF, FPS, FFIN = progress_flow(Fr, "freelancer")
check(Fr.post(B + f"{D}/{FFIN}/finalize").ok, "freelancer: final invoice finalised")
fx = xml(Fr, FFIN)
check(type_code(fx) == "380" and "#SKONTO#TAGE=7#PROZENT=3.00#" in fx, "freelancer: e-invoice of the final invoice with the discount")
check(A.get(B + f"{D}/{FOFF}/progress").status_code == 404, "freelancer: the organisation's admin does not reach the personal quotation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
