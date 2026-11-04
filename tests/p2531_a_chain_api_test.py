#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.531.0 A API tests: the hash chain over finalised documents (#4497, office/chain.py) and the tax rates by the day of
service (#4498), own container in mode workspaces. Invented companies, people and the test IBAN only.
 - #4497 in the personal office of a person without an organisation (freelancer-matrix: office): finalising an invoice sets
   chain_seq 1 / chain_prev '' / chain_hash (sha256 hex), the second one points at the first; a finalised quotation stays
   outside; a credit note joins; a payment and a status change never break the chain (GET /api/office/log/chain ok); a
   field changed directly in the database (the date of the second invoice, a position of the first) is named as first_bad,
   exactly that document; taken back = intact again
 - migration: the chain columns emptied in the database = pending, not chained; a restart chains them again in the order
   they were finalised, with the same hashes (deterministic)
 - rights like the office log: the organisation's admin 200, a member 403
 - #4498: a draft invoice with its period of service in the second half of 2020 is computed with 16 %, one ending in 2021
   with 19 % (service_to wins over the invoice date); a finalised one keeps its rate (snapshot) when the date moves on
usage: p2531_a_chain_api_test.py <datadir>      (KMT_NOSTART=1 = the server already runs; then the restart part is skipped)"""
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx  # noqa: E402
from freelancer_fixture import freelancer, login, org_join  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, done, fresh, H, PASSWORD, sess  # noqa: E402,F401

MODE = {"KALMIDO_INSTANCE_MODE": "workspaces"}
fresh(MODE)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": PASSWORD}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
HEX = re.compile(r"^[0-9a-f]{64}$")


def sql(q, args=()):
    c = dbx.connect(DATA)
    return c.execute(q, args).fetchall() if q.lstrip().upper().startswith("SELECT") else c.execute(q, args)


def ok(r, what, codes=(200, 201, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def chain_row(did):
    r = sql("SELECT chain_key, chain_seq, chain_prev, chain_hash FROM office_docs WHERE id=?", (did,))
    return dict(r[0]) if r else {}


FID, Fr = freelancer(B, A)
ok(Fr.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht"}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                     "company_fields": {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "tax_number": "12/345/67890",
                                                        "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}}),
   "freelancer office settings")
CL = ok(Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                          "email": "rechnung@kunde.example.com"}), "a client", (201,)).get("id")


def invoice(items=None, **kw):
    body = {"kind": "invoice", "client_id": CL, "service_from": "2026-01-01", "service_to": "2026-01-20",
            "items": items or [{"title": "Regie", "qty": 1, "rate": 100}]}
    body.update(kw)
    body = {k: v for k, v in body.items() if v is not None}  # None = the key left out
    return ok(Fr.post(B + D, json=body), "a draft invoice", (201,)).get("id")


def check_chain(s=None):
    return ok((s or Fr).get(B + O + "/log/chain"), "GET the chain check")


# ---------------------------------------------------------------- #4497 finalising sets the hash, the second one links
I1 = invoice()
ok(Fr.post(B + f"{D}/{I1}/finalize"), "the first invoice finalised")
c1 = chain_row(I1)
check(c1.get("chain_seq") == 1 and c1.get("chain_prev") == "" and HEX.match(c1.get("chain_hash") or "") and c1.get("chain_key") == "invoice",
      f"#4497: the first finalised invoice: place 1, no hash before, its own sha256 {c1}")
I2 = invoice([{"title": "Schnitt", "qty": 2, "rate": 450}])
ok(Fr.post(B + f"{D}/{I2}/finalize"), "the second invoice finalised")
c2 = chain_row(I2)
check(c2.get("chain_seq") == 2 and c2.get("chain_prev") == c1.get("chain_hash") and HEX.match(c2.get("chain_hash") or "")
      and c2["chain_hash"] != c1["chain_hash"], f"#4497: the second one points at the first {c2}")
Q = ok(Fr.post(B + D, json={"client_id": CL, "project_title": "Angebot"}), "a quotation", (201,)).get("id")
ok(Fr.put(B + f"{D}/{Q}/items", json={"items": [{"title": "Kamera", "qty": 1, "unit": "day", "rate": 900}]}), "its positions")
ok(Fr.post(B + f"{D}/{Q}/finalize"), "the quotation finalised")
check(chain_row(Q).get("chain_seq") is None and chain_row(Q).get("chain_hash") == "", "#4497: a finalised quotation stays outside the chain")
I3 = invoice([{"title": "Ton", "qty": 1, "rate": 300}])
ok(Fr.post(B + f"{D}/{I3}/finalize"), "a third invoice finalised")
CR = ok(Fr.post(B + f"{D}/{I3}/credit"), "a credit note to the third invoice", (200, 201)).get("id")
ok(Fr.post(B + f"{D}/{CR}/finalize"), "the credit note finalised")
cc = chain_row(CR)
check(cc.get("chain_seq") and HEX.match(cc.get("chain_hash") or "") and cc.get("chain_key") in ("credit", "invoice"),
      f"#4497: a finalised credit note joins the chain of its counter {cc}")

# ---------------------------------------------------------------- a payment and a status change never break it
ok(Fr.post(B + f"{D}/{I1}/payments", json={"amount": "119.00"}), "a payment on the first invoice", (201,))
ok(Fr.post(B + f"{D}/{I2}/status", json={"status": "sent"}), "the second invoice marked sent")
k = check_chain()
check(k.get("ok") is True and k.get("count") == 4 and k.get("first_bad") is None and k.get("pending") == 0,
      f"#4497: after a payment, a status change and a credit note the chain is intact (4 documents) {k}")

# ---------------------------------------------------------------- a change in the database names exactly that document
dt = sql("SELECT date FROM office_docs WHERE id=?", (I2,))[0]["date"]
sql("UPDATE office_docs SET date=? WHERE id=?", ("2026-01-02" if dt != "2026-01-02" else "2026-01-03", I2))
k = check_chain()
check(k.get("ok") is False and (k.get("first_bad") or {}).get("id") == I2 and (k.get("first_bad") or {}).get("number"),
      f"#4497: the date of the second invoice changed in the database: it is named (id and number) {k}")
sql("UPDATE office_docs SET date=? WHERE id=?", (dt, I2))
check(check_chain().get("ok") is True, "#4497: taken back: intact again")
net = sql("SELECT net FROM office_doc_items WHERE doc_id=?", (I1,))[0]["net"]
sql("UPDATE office_doc_items SET net=? WHERE doc_id=?", ("99.00", I1))
k = check_chain()
check(k.get("ok") is False and (k.get("first_bad") or {}).get("id") == I1, f"#4497: a position of the first invoice changed: the first one is named {k}")
sql("UPDATE office_doc_items SET net=? WHERE doc_id=?", (net, I1))
la = sql("SELECT locked_at FROM office_docs WHERE id=?", (I2,))[0]["locked_at"]
sql("UPDATE office_docs SET locked_at=NULL WHERE id=?", (I2,))
k = check_chain()
check(k.get("ok") is False and (k.get("first_bad") or {}).get("id") == I2, f"#4497: unlocked in the database: named {k}")
sql("UPDATE office_docs SET locked_at=? WHERE id=?", (la, I2))
check(check_chain().get("ok") is True, "#4497: all taken back: intact")

# ---------------------------------------------------------------- #4498 the rates of the day of service (draft), the snapshot
R20 = invoice(service_from="2020-08-01", service_to="2020-08-31")
d20 = ok(Fr.get(B + f"{D}/{R20}"), "a draft with its service in 2020")
check(float(d20["totals"]["tax_lines"][0]["pct"]) == 16, f"#4498: service in the second half of 2020: 16 % {d20['totals'].get('tax_lines')}")
R21 = invoice(service_from="2020-12-15", service_to="2021-01-10")
d21 = ok(Fr.get(B + f"{D}/{R21}"), "a draft whose service ends in 2021")
check(float(d21["totals"]["tax_lines"][0]["pct"]) == 19, f"#4498: the end of the period of service decides (2021: 19 %) {d21['totals'].get('tax_lines')}")
R7 = invoice([{"title": "Lizenz", "qty": 1, "rate": 100, "tax": "reduced"}], service_from="2020-09-01", service_to="2020-09-30")
check(float(ok(Fr.get(B + f"{D}/{R7}"), "reduced 2020")["totals"]["tax_lines"][0]["pct"]) == 5, "#4498: the reduced rate of 2020: 5 %")
RN = invoice(service_from=None, service_to=None)
check(float(ok(Fr.get(B + f"{D}/{RN}"), "no period")["totals"]["tax_lines"][0]["pct"]) == 19, "#4498: without a period of service: the invoice date (today, 19 %)")
fin = Fr.post(B + f"{D}/{R20}/finalize")
check(fin.ok, f"#4498: the 2020 invoice finalised {fin.status_code} {fin.text[:200]}")
if fin.ok:
    snap = sql("SELECT tax_snapshot FROM office_docs WHERE id=?", (R20,))[0]["tax_snapshot"]
    check('"standard": 16' in snap and float(ok(Fr.get(B + f"{D}/{R20}"), "finalised 2020")["totals"]["tax_lines"][0]["pct"]) == 16,
          "#4498: the finalised one keeps 16 % in its snapshot and totals")
    ok(Fr.post(B + f"{D}/{RN}/finalize"), "today's invoice finalised")
    check(float(ok(Fr.get(B + f"{D}/{R20}"), "2020 again")["totals"]["tax_lines"][0]["pct"]) == 16, "#4498: ... unchanged after later documents")

# ---------------------------------------------------------------- migration: emptied chain columns are chained again at the start
before = {i: chain_row(i) for i in (I1, I2, I3, CR, R20, RN)}
k0 = check_chain()
OID = sql("SELECT org_id FROM office_docs WHERE id=?", (I1,))[0]["org_id"]
sql("UPDATE office_docs SET chain_key='', chain_seq=NULL, chain_prev='', chain_hash='' WHERE org_id=?", (OID,))
k = check_chain()
check(k.get("ok") is True and k.get("count") == 0 and k.get("pending") == k0.get("count"), f"#4497: emptied columns = pending, not broken {k} (was {k0})")
if fresh(MODE, keep=True):
    Fr = login(B, "frida")
    k = check_chain()
    check(k.get("ok") is True and k.get("count") == k0.get("count") and k.get("pending") == 0, f"#4497: the start chains them again {k}")
    after = {i: chain_row(i) for i in (I1, I2, I3, CR, R20, RN)}
    check(after == before, f"#4497: in the order they were finalised, with the same hashes {after} vs {before}")
    A = sess("alice")

# ---------------------------------------------------------------- rights like the office log: the organisation's admin, not a member
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
check(r.status_code == 201, "an organisation " + r.text[:160])
ORG = r.json().get("id")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": PASSWORD, "email": "bob@example.com"})
check(r.ok, "bob " + r.text[:160])
ok(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}), "bob a member")
check(org_join(B, "bob", ORG), "bob is in the organisation")
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients", "tour": "done", "workspace": f"org:{ORG}"})
ka = A.get(B + O + "/log/chain")
check(ka.status_code == 200 and ka.json().get("ok") is True and ka.json().get("count") == 0, f"#4497: the organisation's admin checks its (empty) chain {ka.status_code} {ka.text[:160]}")
check(Bo.get(B + O + "/log/chain").status_code == 403, "#4497: a member gets 403 (like the office log)")
check(Bo.get(B + O + "/log").status_code == 403, "... the same as the log itself")

sys.exit(done("p2531_a_chain_api"))
