#!/usr/bin/env python3
"""2.269.0 A (#3012) API tests: office document positions without silent loss (audit L). Own container (start.sh, org
encryption on), invented companies and people only (@example.com / .example).
 - the audit's replay: GET a draft (positions L); PUT L + a new one; PUT L from the old state with expect_updated_at -> 409
   with the current document (both lines), without expect_updated_at -> 200 as before
 - positions keep their ids over two saves (UPDATE, no DELETE + INSERT); a new line gets one new id
 - a member (no purchase prices) saves the lines: the admin's purchase price stays
 - head PATCH: the same version check; two saves with the same base -> one 200, one 409 (also two at the same time)
 - travel costs billed on the document: an old list without the line (no expect_updated_at) keeps it, the receipt stays
   billed; with the current version and the line left out it goes and the receipt is open again; unbill by the receipt
   alone removes its kept position
 - parts of a quotation: the part's positions keep their ids, expect_updated_at of the document -> 409
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2269_a_docitems_test.py <datadir>      (a fresh container; P2269A_NOSTART=1 = the server already runs)"""
import base64
import os
import sys
import threading

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2269A")
D, O = "/api/office/docs", "/api/office"
FEAT = "cal,comments,collab,clients,office,docs,files,time,travel"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def setup_office(s):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
    check(r.ok, "office settings " + r.text[:200])
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def body_of(items):
    """The editor's list (ofdItemsBody): what the client sends back of the positions it holds."""
    keys = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "intext", "cost", "discountable")
    return [{k: it.get(k) for k in keys if k in it} for it in items]


def parallel(fns):
    out = [None] * len(fns)

    def go(i, f):
        out[i] = f()
    ts = [threading.Thread(target=go, args=(i, f)) for i, f in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def run(S, S2, who, M=None):
    """S = an office admin's session, S2 = a second session of the same person (another tab / the phone), M = a member."""
    cl = setup_office(S)
    r = S.post(B + D, json={"kind": "offer", "project_title": "Image film", "client_id": cl,
                            "items": [{"title": "Shoot day", "qty": 2, "unit": "day", "rate": 900, "cost": 300}]})
    check(r.status_code == 201, f"{who}: a quotation " + r.text[:200])
    did = r.json()["id"]
    # ------------------------------------------------ the audit's replay
    g = S.get(B + f"{D}/{did}").json()
    base, L = g.get("updated_at"), g.get("items") or []
    check(base and len(L) == 1, f"{who}: the draft with one line {base} {len(L)}")
    i1 = L[0]["id"]
    r = S.put(B + f"{D}/{did}/items", json={"items": body_of(L) + [{"title": "Edit day", "qty": 1, "unit": "day", "rate": 700}], "expect_updated_at": base})
    check(r.ok, f"{who}: tab A adds a line " + r.text[:200])
    a = r.json()
    ids = [x["id"] for x in a.get("items") or []]
    check(len(ids) == 2 and ids[0] == i1, f"{who}: the first line keeps its id {i1} -> {ids}")
    check(a.get("updated_at") and a["updated_at"] != base, f"{who}: a new version {base} -> {a.get('updated_at')}")
    r = S2.put(B + f"{D}/{did}/items", json={"items": body_of(L), "expect_updated_at": base})
    j = r.json()
    check(r.status_code == 409 and j.get("error") and len((j.get("doc") or {}).get("items") or []) == 2,
          f"{who}: tab B from the old state -> 409 with the current two lines {r.status_code} {r.text[:200]}")
    check([x["id"] for x in S.get(B + f"{D}/{did}").json()["items"]] == ids, f"{who}: nothing lost after the 409")
    # without expect_updated_at (API, older clients): as before, the list is taken as it is
    r = S2.put(B + f"{D}/{did}/items", json={"items": body_of(L)})
    check(r.ok and [x["id"] for x in r.json()["items"]] == [i1], f"{who}: without a version the list counts (as before) " + r.text[:200])
    # ------------------------------------------------ ids over two saves, a member keeps the purchase price
    cur = S.get(B + f"{D}/{did}").json()
    r1 = S.put(B + f"{D}/{did}/items", json={"items": body_of(cur["items"]) + [{"title": "Grading", "qty": 1, "unit": "flat", "rate": 400}],
                                              "expect_updated_at": cur["updated_at"]})
    r2 = S.put(B + f"{D}/{did}/items", json={"items": body_of(r1.json()["items"]), "expect_updated_at": r1.json()["updated_at"]})
    check(r1.ok and r2.ok and [x["id"] for x in r1.json()["items"]] == [x["id"] for x in r2.json()["items"]],
          f"{who}: ids the same over two saves " + r2.text[:200])
    if M is not None:
        m = M.get(B + f"{D}/{did}").json()
        check(m.get("items") and "cost" not in m["items"][0], f"{who}: the member sees no purchase price")
        lines = body_of(m["items"])
        lines[0]["qty"] = 3
        r = M.put(B + f"{D}/{did}/items", json={"items": lines, "expect_updated_at": m["updated_at"]})
        check(r.ok, f"{who}: the member changes the quantity " + r.text[:200])
        a = S.get(B + f"{D}/{did}").json()["items"][0]
        check(a["id"] == i1 and float(a.get("qty") or 0) == 3 and float(a.get("cost") or 0) == 300,
              f"{who}: the admin's purchase price stays after the member's save {a.get('id')} {a.get('qty')} {a.get('cost')}")
    # ------------------------------------------------ head PATCH
    cur = S.get(B + f"{D}/{did}").json()
    r = S.patch(B + f"{D}/{did}", json={"project_title": "Image film 2", "expect_updated_at": cur["updated_at"]})
    check(r.ok and r.json().get("updated_at") != cur["updated_at"], f"{who}: the head with the current version " + r.text[:200])
    r = S2.patch(B + f"{D}/{did}", json={"project_title": "Image film B", "expect_updated_at": cur["updated_at"]})
    check(r.status_code == 409 and (r.json().get("doc") or {}).get("project_title") == "Image film 2", f"{who}: the head from the old state 409 " + r.text[:200])
    r = S2.patch(B + f"{D}/{did}", json={"project_title": "Image film 3"})
    check(r.ok and r.json().get("project_title") == "Image film 3", f"{who}: the head without a version as before")
    # two saves at the same time with the same base: exactly one goes through
    cur = S.get(B + f"{D}/{did}").json()
    res = parallel([lambda: S.patch(B + f"{D}/{did}", json={"project_title": "Parallel A", "expect_updated_at": cur["updated_at"]}),
                    lambda: S2.put(B + f"{D}/{did}/items", json={"items": body_of(cur["items"])[:1], "expect_updated_at": cur["updated_at"]})])
    check(sorted(x.status_code for x in res) == [200, 409], f"{who}: two at once with one base: one 200, one 409 {[x.status_code for x in res]}")
    # ------------------------------------------------ travel costs on the document
    r = S.post(B + O + "/trips", json={"date_from": "2030-02-10", "dest": "Example location", "items": [{"date": "2030-02-10", "category": "taxi", "amount": 25}]})
    check(r.status_code == 201, f"{who}: a trip " + r.text[:200])
    ti = (r.json().get("items") or [{}])[0].get("id")
    old = S2.get(B + f"{D}/{did}").json()  # the other tab, open since before the billing
    r = S.post(B + O + "/trips/bill", json={"doc_id": did, "item_ids": [ti]})
    check(r.ok and len(r.json().get("positions") or []) == 1, f"{who}: the receipt billed " + r.text[:200])
    pid = (r.json().get("positions") or [0])[0]
    row = kt.dbx("SELECT billed_doc_id, billed_item_id FROM office_trip_items WHERE id=?", (ti,))
    check(row and row[0][0] == did and row[0][1] == pid, f"{who}: the receipt knows its position {row} {pid}")
    r = S2.put(B + f"{D}/{did}/items", json={"items": body_of(old["items"]), "expect_updated_at": old["updated_at"]})
    check(r.status_code == 409, f"{who}: the old tab with its version: 409 " + r.text[:200])
    r = S2.put(B + f"{D}/{did}/items", json={"items": body_of(old["items"])})
    check(r.ok and pid in [x["id"] for x in r.json()["items"]], f"{who}: the old list without a version keeps the travel line " + r.text[:200])
    check(kt.dbx("SELECT billed_doc_id FROM office_trip_items WHERE id=?", (ti,))[0][0] == did, f"{who}: the receipt stays billed")
    cur = S.get(B + f"{D}/{did}").json()
    r = S.put(B + f"{D}/{did}/items", json={"items": body_of([x for x in cur["items"] if x["id"] != pid]), "expect_updated_at": cur["updated_at"]})
    check(r.ok and pid not in [x["id"] for x in r.json()["items"]], f"{who}: left out on purpose with the current version: gone " + r.text[:200])
    row = kt.dbx("SELECT billed_doc_id, billed_item_id FROM office_trip_items WHERE id=?", (ti,))
    check(row and row[0][0] is None and row[0][1] is None, f"{who}: the receipt is open again {row}")
    # billed again, then unbilled by the receipt alone: the kept position goes
    r = S.post(B + O + "/trips/bill", json={"doc_id": did, "item_ids": [ti]})
    pid = (r.json().get("positions") or [0])[0]
    check(r.ok and pid, f"{who}: billed again " + r.text[:200])
    r = S.post(B + O + "/trips/unbill", json={"item_ids": [ti]})
    check(r.ok and r.json().get("removed") == 1, f"{who}: unbill without positions removes the linked one " + r.text[:200])
    check(pid not in [x["id"] for x in S.get(B + f"{D}/{did}").json()["items"]], f"{who}: the travel line is gone")
    # ------------------------------------------------ parts
    cur = S.get(B + f"{D}/{did}").json()
    r = S.post(B + f"{D}/{did}/parts", json={"kind": "items", "title": "Part one", "expect_updated_at": cur["updated_at"]})
    check(r.status_code == 201 and r.json().get("part"), f"{who}: a part " + r.text[:200])
    part = r.json()["part"]
    ver = r.json()["updated_at"]
    u = B + f"{D}/{did}/parts/{part['id']}/items"
    r1 = S.put(u, json={"items": [{"title": "Crew", "qty": 1, "unit": "day", "rate": 500}, {"title": "Gear", "qty": 1, "unit": "day", "rate": 200}], "expect_updated_at": ver})
    check(r1.ok, f"{who}: the part's lines " + r1.text[:200])
    p1 = (r1.json().get("part") or {}).get("items") or []
    r2 = S.put(u, json={"items": body_of(p1), "expect_updated_at": r1.json()["updated_at"]})
    p2 = (r2.json().get("part") or {}).get("items") or []
    check(r2.ok and len(p1) == 2 and [x["id"] for x in p1] == [x["id"] for x in p2], f"{who}: the part's lines keep their ids " + r2.text[:200])
    r = S2.put(u, json={"items": body_of(p1)[:1], "expect_updated_at": ver})
    check(r.status_code == 409 and r.json().get("doc"), f"{who}: a part save from the old state 409 " + r.text[:200])
    r = S2.patch(B + f"{D}/{did}/parts/{part['id']}", json={"title": "Old tab", "expect_updated_at": ver})
    check(r.status_code == 409, f"{who}: a part rename from the old state 409")
    # an invoice draft: the same route, the same rules
    r = S.post(B + D, json={"kind": "invoice", "client_id": cl, "items": [{"title": "Service", "qty": 1, "unit": "flat", "rate": 100}]})
    check(r.status_code == 201, f"{who}: an invoice draft " + r.text[:200])
    iv = r.json()
    r = S.put(B + f"{D}/{iv['id']}/items", json={"items": body_of(iv["items"]) + [{"title": "Extra", "qty": 1, "unit": "flat", "rate": 50}], "expect_updated_at": iv["updated_at"]})
    check(r.ok and r.json()["items"][0]["id"] == iv["items"][0]["id"], f"{who}: the invoice line keeps its id " + r.text[:200])
    r = S2.put(B + f"{D}/{iv['id']}/items", json={"items": body_of(iv["items"]), "expect_updated_at": iv["updated_at"]})
    check(r.status_code == 409, f"{who}: the invoice from the old state 409")


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, "create bob " + r.text[:200])
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A2 = sess("alice")
for s in (A, A2, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
run(A, A2, "organisation", Bo)

# ================================================================== a person without an organisation (freelancer-matrix: office)
FID, F = freelancer(B, A)
run(F, login(B, "frida"), "freelancer")

sys.exit(kt.done("p2269_a_docitems"))
