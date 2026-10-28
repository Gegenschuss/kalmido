#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.354.0 A API tests (#2831, #2833, #2834, #2835): invoice math and reverse charge of Office & finance, once in the
personal office of a person without an organisation (freelancer fixture; freelancer-matrix: office) and once in an
organisation's office (its admin). Invented companies, people and the test IBAN only.
 - #2831 a position is money(qty x exact rate): 3 x 0.333 + 1000 x 0.125 + 1.5 x 33.335 = 176.00 net (was 175.00 + 5 +
   0.01 with the rate rounded first); the print model shows "0,125 €"; the finalised XML has line 125.00, total 209.44
 - #2833 a taxed invoice keeps no VAT note (given at creation or left over when switching to VAT); the XML of such an
   invoice (audit case c10, 4 h x 95 EUR) is category S with 72.20 tax, never AE
 - #2834 reverse charge: the draft says when the client's VAT ID is missing (client_vat_id_missing, gone once the client
   has one); "abroad" without a register number needs the own VAT ID before finalising (e-invoice category G, BR-G-02)
 - #2835 an invoice from a quotation with 19 % and 7 % positions and 10 % discount takes the discount per rate: tax 234.00,
   gross 2034.00 like the quotation (was 222.00 / 2022.00)
usage: p2354_a_invoice_math_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import requests  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
COMPANY = {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
A.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
FID, Fr = freelancer(B, A)


def run(S, who):
    def ok(cond, what):
        check(cond, f"{who}: {what}")

    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                         "company_fields": COMPANY})
    ok(r.ok, "office settings " + r.text[:200])

    def client(**kw):
        r = S.post(B + "/api/clients", json=kw)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def invoice(cl, items, **kw):
        r = S.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": "2026-10-01", "service_to": "2026-10-20", "items": items}, **kw))
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def doc(did):
        return S.get(B + f"{D}/{did}").json()

    CDE = client(name="Beispielkunde AG", street="Marktstraße 5", zip="50667", city="Köln", country="DE")
    CES = client(name="Ejemplo SL", street="Calle Mayor 1", zip="28013", city="Madrid", country="ES")
    CCH = client(name="Beispiel AG Zürich", street="Bahnhofstrasse 3", zip="8001", city="Zürich", country="CH")

    # ---------------------------------------------------------------- #2831 the exact rate (audit c01 / c05)
    R = invoice(CDE, [{"title": "Kleinteil", "qty": 3, "rate": 0.333, "unit": "piece"}, {"title": "Stückpreis", "qty": 1000, "rate": 0.125, "unit": "piece"},
                      {"title": "Stunde", "qty": 1.5, "rate": 33.335, "unit": "hour"}])
    t = doc(R)["totals"]
    nets = [ln["net"] for ln in t["lines"] if ln["kind"] == "item"]
    ok(nets == ["1.00", "125.00", "50.00"] and t["net"] == "176.00" and t["tax"] == "33.44" and t["gross"] == "209.44",
       f"#2831: 1.00 / 125.00 / 50.00, net 176.00, gross 209.44 (was 0.99 / 130.00 / 50.01): {nets} {t['net']} {t['gross']}")
    rd = S.get(B + f"{D}/{R}/render").json()
    rates = [ln.get("rate_text") for ln in rd["lines"] if ln.get("kind") == "item"]
    ok(rates == ["0,333 €", "0,125 €", "33,335 €"] and rd["totals"]["gross"] == "209.44", f"#2831: the print model shows the exact unit price: {rates}")
    r = S.post(B + f"{D}/{R}/finalize")
    ok(r.ok, "#2831: finalised " + r.text[:200])
    x = S.get(B + f"{D}/{R}/xml")
    ok(x.ok and b"<ram:LineTotalAmount>125.00</ram:LineTotalAmount>" in x.content and b"<ram:ChargeAmount>0.1250</ram:ChargeAmount>" in x.content
       and b"<ram:GrandTotalAmount>209.44</ram:GrandTotalAmount>" in x.content, "#2831: the XML = view (line 125.00, price 0.1250, total 209.44)")
    ok(doc(R)["totals"]["gross"] == "209.44", "#2831: the finalised totals stay")

    # ---------------------------------------------------------------- #2833 no VAT note next to VAT (audit c10)
    V = invoice(CDE, [{"title": "Beratung", "qty": 4, "rate": 95, "unit": "hour"}], vat_note="reverse")
    ok(doc(V)["vat_note"] == "", f"#2833: a taxed invoice keeps no VAT note given at creation: {doc(V)['vat_note']!r}")
    W = invoice(CDE, [{"title": "Beratung", "qty": 4, "rate": 95, "unit": "hour"}], vat_mode="novat", vat_note="reverse")
    ok(doc(W)["vat_note"] == "reverse", "#2833: without VAT the note is kept")
    r = S.patch(B + f"{D}/{W}", json={"vat_mode": "vat"})
    ok(r.ok and r.json()["vat_note"] == "" and r.json()["vat_mode"] == "vat", "#2833: switching to VAT clears the note " + r.text[:160])
    r = S.patch(B + f"{D}/{W}", json={"vat_note": "reverse"})
    ok(r.ok and r.json()["vat_note"] == "", "#2833: a note on a taxed invoice is not stored " + r.text[:160])
    rd = S.get(B + f"{D}/{W}/render").json()
    ok(not rd.get("vat_note_text") and rd["totals"]["gross"] == "452.20" and rd["totals"]["tax"] == "72.20", "#2833: the PDF model: VAT 72.20, no section 13b text")
    r = S.post(B + f"{D}/{W}/finalize")
    ok(r.ok, "#2833: finalised " + r.text[:200])
    x = S.get(B + f"{D}/{W}/xml").content
    ok(b"<ram:CategoryCode>S</ram:CategoryCode>" in x and b"<ram:CategoryCode>AE</ram:CategoryCode>" not in x and b">72.20</ram:TaxTotalAmount>" in x
       and b"<ram:GrandTotalAmount>452.20</ram:GrandTotalAmount>" in x, "#2833: XML category S with 72.20 tax (BR-CO-15)")

    # ---------------------------------------------------------------- #2834 reverse charge needs the client's VAT ID (audit c08)
    RC = invoice(CES, [{"title": "Animation", "qty": 4, "rate": 95, "unit": "hour"}], vat_mode="novat", vat_note="reverse")
    d = doc(RC)
    ok(d.get("client_vat_id_missing") is True, f"#2834: the draft says the client's VAT ID is missing: {d.get('client_vat_id_missing')!r}")
    r = S.post(B + f"{D}/{RC}/finalize")
    ok(r.status_code == 400 and "client's VAT ID" in r.json().get("error", ""), "#2834: not finalised without the client's VAT ID " + r.text[:200])
    ok(S.patch(B + f"/api/clients/{CES}", json={"vat_id": "ESB12345674"}).ok, "the client gets a VAT ID")
    ok(doc(RC).get("client_vat_id_missing") is False, "#2834: the hint is gone once the client has a VAT ID")
    r = S.post(B + f"{D}/{RC}/finalize")
    ok(r.ok, "#2834: finalised with both VAT IDs " + r.text[:200])
    ok(doc(R).get("client_vat_id_missing") is None, "#2834: a finalised invoice carries no hint")
    # "abroad" without register number = category G, which needs the own VAT ID (BR-G-02); 2.357.0 (#3218): with the tax
    # number it is O, so the 400 needs neither VAT ID nor tax number
    S.put(B + O + "/settings", json={"company_fields": dict(COMPANY, vat_id="", tax_number="")})
    AB = invoice(CCH, [{"title": "Animation", "qty": 1, "rate": 500, "unit": "flat"}], vat_mode="novat", vat_note="abroad")
    r = S.post(B + f"{D}/{AB}/finalize")
    ok(r.status_code == 400 and "register number" in r.json().get("error", ""), "#2834: abroad without VAT ID / register number: 400 " + r.text[:200])
    S.put(B + O + "/settings", json={"company_fields": dict(COMPANY, tax_number="")})
    r = S.post(B + f"{D}/{AB}/finalize")
    ok(r.ok, "#2834: abroad with the own VAT ID finalised " + r.text[:200])
    x = S.get(B + f"{D}/{AB}/xml").content
    ok(b"<ram:CategoryCode>G</ram:CategoryCode>" in x and b"DE999999999" in x, "#2834: category G with the seller's VAT ID")
    S.put(B + O + "/settings", json={"company_fields": dict(COMPANY, vat_id="")})
    AO = invoice(CCH, [{"title": "Animation", "qty": 1, "rate": 500, "unit": "flat"}], vat_mode="novat", vat_note="abroad")
    r = S.post(B + f"{D}/{AO}/finalize")
    ok(r.ok, "#2834 + #3218: abroad with the tax number only finalised " + r.text[:200])
    x = S.get(B + f"{D}/{AO}/xml").content
    ok(b"<ram:CategoryCode>O</ram:CategoryCode>" in x and b"12/345/67890" in x, "#3218: category O with the seller's tax number")
    S.put(B + O + "/settings", json={"company_fields": COMPANY})

    # ---------------------------------------------------------------- #2835 the quotation's discount per tax rate
    r = S.post(B + D, json={"client_id": CDE, "project_title": "Imagefilm", "raw_mode": "none", "producing_on": 0, "discount_pct": 10,
                            "service_from": "2026-10-01", "service_to": "2026-10-20"})
    assert r.status_code == 201, r.text
    OF = r.json()["id"]
    r = S.put(B + f"{D}/{OF}/items", json={"items": [{"title": "Regie", "qty": 1, "rate": 1000, "unit": "flat"},
                                                       {"title": "Buchlizenz", "qty": 1, "rate": 1000, "unit": "flat", "tax": "reduced"}]})
    ot = r.json()["totals"]
    ok(r.ok and ot["tax_total"] == 234 and ot["gross"] == 2034, f"#2835: the quotation: tax 234, gross 2034: {ot.get('tax_total')} {ot.get('gross')}")
    r = S.post(B + f"{D}/{OF}/invoice")
    ok(r.status_code == 201, "#2835: invoice from the quotation " + r.text[:200])
    iv = r.json()
    disc = sorted((x["tax"], x["rate"]) for x in iv["items"] if x["kind"] == "discount")
    ok(disc == [("reduced", 100), ("standard", 100)], f"#2835: one discount position per rate: {disc}")
    ok(iv["totals"]["tax"] == "234.00" and iv["totals"]["gross"] == "2034.00" and iv["totals"]["net"] == "1800.00",
       f"#2835: the invoice = the quotation: net 1800.00, tax 234.00, gross 2034.00 (was 222.00 / 2022.00): {iv['totals']['tax']} {iv['totals']['gross']}")


run(Fr, "freelancer")
run(A, "organisation")
print(f"p2354_a_invoice_math: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
