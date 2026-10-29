#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.433.0 API tests (#3604): number schemes of Office & finance, once in the personal office of a person without an
organisation (freelancer fixture; freelancer-matrix: office) and once in an organisation's office (its admin). Invented
companies and people only.
 - #3604 a client's short code (2-6 capitals / digits, saved in capitals, else 400) is the building block {kuerzel}:
   {seq}_{kuerzel}_{isodate}_R gives 1_TNP_<date>_R; without a code the first three letters of the name (Müller -> MUE);
   the scheme check and the preview know the block; numbers given before stay
 - #3597 the switch "invoice corrections count in the invoice series" (credit_shared, off for a new office): on = the
   correction scheme still at the pack's value becomes the invoice scheme with _RK, invoice / correction / invoice give
   4_R / 5_RK / 6_R (one counter, no double number, no gap), the number ranges show the corrections' row greyed (shared,
   not settable), the switch is in the office log; off again = the corrections' own counter continues above (never back)
usage: p2433_office_numbers_test.py <datadir>"""
import os
import re
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
COMPANY = {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

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
        r = S.post(B + "/api/clients", json=dict({"street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}, **kw))
        assert r.status_code == 201, r.text
        return r.json()

    def invoice(cl):
        r = S.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-10-01", "service_to": "2026-10-20",
                                "items": [{"title": "Schnitt", "qty": 1, "rate": 100, "unit": "piece"}]})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def finalize(did):
        r = S.post(B + f"{D}/{did}/finalize")
        ok(r.ok, f"finalised {r.text[:160]}")
        return r.json().get("number") or ""

    # ---------------------------------------------------------------- #3604 the client's short code
    tnp = client(name="Testkunde Nord Partner", short_code="tnp")
    ok(tnp.get("short_code") == "TNP", f"#3604: the short code is saved in capitals: {tnp.get('short_code')}")
    mue = client(name="Müller Film")
    ok(mue.get("short_code") == "", "#3604: a client without a short code")
    for bad in ("T", "TOOLONG", "T-P"):
        r = S.patch(B + f"/api/clients/{mue['id']}", json={"short_code": bad})
        ok(r.status_code == 400 and "2 to 6" in r.json().get("error", ""), f"#3604: short code {bad!r} refused " + r.text[:120])
    sch = "{seq}_{kuerzel}_{isodate}_R"
    pv = S.get(B + O + "/number-preview", params={"kind": "invoice", "scheme": sch}).json()
    ok(pv.get("valid") and "_ABC_" in pv.get("preview", ""), f"#3604: the scheme check knows {{kuerzel}}, preview with ABC: {pv}")
    r = S.put(B + O + "/settings", json={"invoice_scheme": sch})
    ok(r.ok, "#3604: invoice scheme with {kuerzel} saved " + r.text[:160])
    n1 = finalize(invoice(tnp["id"]))
    ok(re.fullmatch(r"1_TNP_\d{4}-\d{2}-\d{2}_R", n1), f"#3604: 1_TNP_<date>_R: {n1}")
    n2 = finalize(invoice(mue["id"]))
    ok(re.fullmatch(r"2_MUE_\d{4}-\d{2}-\d{2}_R", n2), f"#3604: without a code the first three letters, umlaut written out: {n2}")
    r = S.patch(B + f"/api/clients/{mue['id']}", json={"short_code": "MF"})
    ok(r.ok and r.json().get("short_code") == "MF", "#3604: short code set later " + r.text[:120])
    n3 = finalize(invoice(mue["id"]))
    ok(re.fullmatch(r"3_MF_\d{4}-\d{2}-\d{2}_R", n3), f"#3604: the new code, the counter goes on: {n3}")
    nums = [d["number"] for d in S.get(B + D + "?kind=invoice").json()["docs"]]
    ok(n2 in nums, f"#3604: the number given before stays: {nums}")

    # ---------------------------------------------------------------- #3597 corrections in the invoice series
    st = S.get(B + O + "/settings").json()["settings"]
    ok(st.get("credit_shared") == 0 and st.get("credit_scheme") == "GS-{yyyy}-{seq:03}", f"#3597: off for a new office, own scheme: {st.get('credit_shared')} {st.get('credit_scheme')}")
    r = S.put(B + O + "/settings", json={"credit_shared": 1})
    st = r.json().get("settings", {})
    ok(r.ok and st.get("credit_shared") == 1 and st.get("credit_scheme") == "{seq}_{kuerzel}_{isodate}_RK",
       f"#3597: switched on, the correction scheme becomes the invoice scheme with _RK: {st.get('credit_scheme')} " + r.text[:120])
    log = S.get(B + O + "/log").json().get("log", [])
    ok(any("credit_shared" in str(x.get("detail")) for x in log), "#3597: the switch is in the office log")
    rg = {x["kind"]: x for x in S.get(B + O + "/number-ranges").json()["ranges"]}
    ok(rg["credit"].get("shared") == "invoice" and rg["credit"]["next"] == 4 and rg["invoice"]["next"] == 4,
       f"#3597: the corrections' row shows the invoices' counter (shared): {rg['credit']}")
    r = S.post(B + O + "/number-ranges/credit", json={"next": 50, "reason": "Test des Sprungs"})
    ok(r.status_code == 400, "#3597: the corrections' next number is not set on its own while shared " + r.text[:120])
    pv = S.get(B + O + "/number-preview", params={"kind": "credit", "scheme": "{seq}_{kuerzel}_{isodate}_RK"}).json()
    ok(pv.get("preview", "").startswith("4_ABC_"), f"#3597: the preview of the corrections counts on the invoices: {pv}")
    i4 = invoice(tnp["id"])
    n4 = finalize(i4)
    r = S.post(B + f"{D}/{i4}/credit")
    ok(r.status_code == 201, "#3597: correction draft " + r.text[:160])
    n5 = finalize(r.json()["id"])
    i6 = invoice(tnp["id"])
    n6 = finalize(i6)
    ok(re.fullmatch(r"4_TNP_\S+_R", n4) and re.fullmatch(r"5_TNP_\S+_RK", n5) and re.fullmatch(r"6_TNP_\S+_R", n6),
       f"#3597: invoice, correction, invoice = 4_R / 5_RK / 6_R: {n4} {n5} {n6}")
    rg = {x["kind"]: x for x in S.get(B + O + "/number-ranges").json()["ranges"]}
    ok(rg["invoice"]["next"] == 7 and rg["credit"]["next"] == 7, f"#3597: one counter for both: {rg['invoice']['next']} {rg['credit']['next']}")
    # off again: the corrections' own counter continues above the shared numbers
    r = S.put(B + O + "/settings", json={"credit_shared": 0})
    ok(r.ok and r.json()["settings"]["credit_scheme"] == "{seq}_{kuerzel}_{isodate}_RK", "#3597: off again, the scheme stays " + r.text[:120])
    rg = {x["kind"]: x for x in S.get(B + O + "/number-ranges").json()["ranges"]}
    ok("shared" not in rg["credit"] and rg["credit"]["next"] == 7, f"#3597: the own counter goes on above the shared numbers: {rg['credit']}")
    r = S.post(B + f"{D}/{i6}/credit")
    n7 = finalize(r.json()["id"]) if r.status_code == 201 else ""
    ok(re.fullmatch(r"7_TNP_\S+_RK", n7), f"#3597: the next correction on its own counter, not back to 1: {n7}")
    allnums = [d["number"] for k in ("invoice", "credit") for d in S.get(B + D + f"?kind={k}").json()["docs"] if d["number"]]
    ok(len(allnums) == len(set(allnums)), f"#3597: no double number: {allnums}")


run(Fr, "freelancer")
run(A, "organisation")
print(f"p2433_office_numbers: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
