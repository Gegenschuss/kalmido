#!/usr/bin/env python3
"""2.189.0 B (#2475) API tests: the home currency in the books and the money flow, own container. Invented companies and
figures only.
 - an office on the base pack with home currency GBP (an organisation and a person without organisation): a payment on a
   GBP invoice counts 1:1 in the income statement, a payment on a USD invoice through the document's rate; a receipt in
   EUR through the office rate (fx_rates), a receipt in CHF without an office rate counts 1:1 and is named in the notes;
   the receipt list shows the original amount; cash flow, key figures, travel expenses (the office rate as default for
   a USD receipt), bank, cash book and logbook answer in GBP
 - a German office stays in EUR, also when new documents are made in USD: a USD receipt through fx_usd as before
tenant-matrix: office
freelancer-matrix: office
usage: p2189_b_books_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from decimal import Decimal

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients,docs,travel"


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def receipt(s, name, ws, amount, cur, day, vat="0"):
    """A receipt document in workspace ws with amount / currency / date set by hand."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(name), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    for _ in range(60):
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.5)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "currency": cur, "date": day})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, cl, rate, cur=None, fx=None):
    b = {"kind": "invoice", "client_id": cl, "project_title": f"Job {rate}", "service_from": TODAY,
         "items": [{"title": "Edit", "qty": 1, "rate": rate}]}
    if cur:
        b.update(currency=cur, fx_rate=fx)
    r = s.post(B + D, json=b)
    check(r.status_code == 201, "an invoice " + r.text[:200])
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"invoice {did} finalised " + r.text[:200])
    d = s.get(B + f"{D}/{did}").json()
    gross = d["totals"]["gross"]
    r = s.post(B + f"{D}/{did}/payments", json={"date": TODAY, "amount": gross, "method": "transfer"})
    check(r.ok, f"payment on {did} " + r.text[:200])
    return did, Decimal(str(gross)), d


def m2(x):
    return Decimal(x).quantize(Decimal("0.01"))


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
if not os.environ.get("P2189B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
FID, Fr = freelancer(B, A)
TODAY = testclock.today().isoformat()
Y = TODAY[:4]


def gbp_office(s, ws, who):
    """The GBP checks for one office (an organisation's or a personal one)."""
    r = s.put(B + O + "/settings", json={"pack": "XX", "home_currency": "GBP",
                                         "company_fields": {"name": f"{who} Studio Ltd", "street": "High Street 1", "zip": "EC1A 1AA",
                                                            "city": "London", "country": "GB", "vat_id": "GB999999973",
                                                            "iban": "GB33BUKB20201555555555", "bic": "BUKBGB22"}})
    check(r.ok, f"{who}: base pack with home currency GBP " + r.text[:200])
    r = s.put(B + O + "/settings", json={"fx_rates": {"EUR": "1.15", "USD": "1.25"}})
    check(r.ok, f"{who}: office rates for EUR and USD " + r.text[:200])
    st = s.get(B + O + "/settings").json()
    st = st.get("settings", st)
    check(st.get("home_currency") == "GBP" and st.get("currency") == "GBP", f"{who}: home currency and new documents in GBP {st.get('home_currency')} {st.get('currency')}")
    cl = s.post(B + "/api/clients", json={"name": f"{who} Client Ltd", "street": "Low Road 2", "zip": "M1 1AA", "city": "Manchester", "country": "GB"}).json()["id"]
    _, g1, d1 = invoice(s, cl, 400)
    check(d1.get("currency") == "GBP", f"{who}: the invoice is in GBP {d1.get('currency')}")
    _, g2, _ = invoice(s, cl, 250, "USD", 1.25)
    r1 = receipt(s, "material-eur.pdf", ws, "115.00", "EUR", TODAY)
    r2 = receipt(s, "material-chf.pdf", ws, "50.00", "CHF", TODAY)
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    inc = Decimal(eu["income_total"]["gross"])
    check(eu["currency"] == "GBP" and inc == m2(g1) + m2(g2 / Decimal("1.25")),
          f"{who}: income statement in GBP, the USD payment through its rate {eu.get('currency')} {inc} {g1} {g2}")
    check(Decimal(eu["expense_total"]["gross"]) == Decimal("150.00"),
          f"{who}: EUR receipt 115 / 1.15 = 100 GBP + CHF receipt without rate 50 = 150 {eu.get('expense_total')}")
    check(eu.get("unrated") == ["CHF"] and any("CHF" in n and "GBP" in n for n in eu["notes"]),
          f"{who}: the CHF receipt without rate is named {eu.get('unrated')} {eu.get('notes')}")
    rl = s.get(B + O + f"/books/receipts?from={Y}-01-01&to={Y}-12-31").json()
    it = {x["node_id"]: x for x in rl.get("rows", [])}
    check(rl.get("currency") == "GBP" and it.get(r1, {}).get("amount") == "100.00" and it.get(r1, {}).get("orig_amount") == "115.00"
          and it.get(r1, {}).get("orig_currency") == "EUR", f"{who}: the receipt list in GBP with the original amount {rl.get('currency')} {it.get(r1)}")
    check(it.get(r2, {}).get("orig_currency") == "CHF", f"{who}: the CHF receipt keeps its original currency {it.get(r2)}")
    cf = s.get(B + O + f"/cashflow?from={TODAY[:7]}&months=3").json()
    check(cf.get("currency") == "GBP", f"{who}: cash flow in GBP {cf.get('currency')}")
    rc = [e for e in cf.get("entries", []) if e.get("node_id") == r1]
    check(rc and rc[0]["amount"] == "100.00", f"{who}: the EUR receipt in the cash flow in GBP {rc}")
    kp = s.get(B + O + "/kpi").json()
    check(kp.get("currency") == "GBP", f"{who}: key figures in GBP {kp.get('currency')}")
    r = s.post(B + O + "/trips", json={"date_from": TODAY, "dest": "London - New York", "purpose": "job",
                                       "items": [{"date": TODAY, "category": "hotel", "amount": "125", "currency": "USD"},
                                                 {"date": TODAY, "category": "train", "amount": "40", "currency": "EUR", "fx_rate": "1.6"},
                                                 {"date": TODAY, "category": "taxi", "amount": "12"}]})
    check(r.status_code == 201, f"{who}: a trip " + r.text[:200])
    tr_ = r.json() if r.ok else {"items": []}
    by = {x["category"]: x for x in tr_["items"]}
    check(by.get("hotel", {}).get("amount_home") == "100.00" and by.get("train", {}).get("amount_home") == "25.00"
          and by.get("taxi", {}).get("currency") == "GBP" and tr_.get("total") == "137.00",
          f"{who}: travel receipts in GBP, USD through the office rate, EUR through its own rate {tr_.get('total')} {by}")
    check(s.get(B + O + "/trips").json().get("currency") == "GBP", f"{who}: the travel list in GBP")
    check(s.get(B + O + "/bank/tx").json().get("currency") == "GBP", f"{who}: the bank in GBP")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(Decimal(eu["expense_total"]["gross"]) == Decimal("287.00"), f"{who}: travel expenses count in GBP {eu.get('expense_total')}")
    r = s.get(B + O + f"/books/export?from={Y}-01-01&to={Y}-12-31")
    txt = r.content.decode("utf-8-sig") if r.ok else ""
    check(r.ok and "GBP" in txt and "EUR" not in txt.replace("material-eur", ""), f"{who}: the booking export in GBP " + txt[:300])


# ---------------------------------------------------------------- an organisation's office in GBP
gbp_office(Ca, f"org:{ORG2}", "Beta")
# ---------------------------------------------------------------- the personal office of a person without organisation (P4)
gbp_office(Fr, "private", "Frida")
check(A.get(B + O + "/settings").json().get("settings", {}).get("home_currency", "EUR") == "EUR", "the other office keeps EUR")

# ---------------------------------------------------------------- a German office stays in EUR
r = A.put(B + O + "/settings", json={"currency": "USD", "fx_usd": 1.25})
check(r.ok, "DE office: new documents in USD " + r.text[:200])
st = A.get(B + O + "/settings").json()
st = st.get("settings", st)
check(st.get("home_currency") == "EUR" and st.get("currency") == "USD", f"DE office: home EUR, new documents USD {st.get('home_currency')} {st.get('currency')}")
check(A.put(B + O + "/settings", json={"home_currency": "GBP"}).ok and (A.get(B + O + "/settings").json().get("settings") or {}).get("home_currency") == "EUR",
      "DE office: the home currency stays EUR")
receipt(A, "tool-usd.pdf", f"org:{ORG}", "125.00", "USD", TODAY)
eu = A.get(B + O + f"/books/euer?year={Y}").json()
check(eu["currency"] == "EUR" and Decimal(eu["expense_total"]["gross"]) == Decimal("100.00") and not eu.get("unrated"),
      f"DE office: the USD receipt through fx_usd (125 / 1.25 = 100 EUR) {eu.get('currency')} {eu.get('expense_total')}")
check(A.get(B + O + "/cashflow").json().get("currency") == "EUR" and A.get(B + O + "/kpi").json().get("currency") == "EUR",
      "DE office: cash flow and key figures in EUR")

print(f"p2189_b_books: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
