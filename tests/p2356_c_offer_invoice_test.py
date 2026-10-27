#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.356.0 C API tests (#3003 #3005): a quotation and the invoices made from it. Own container (start.sh), invented
companies and people only.
 - an invoice made from a quotation names it (source_offer: id, number, status); the quotation lists its invoices
   (offer_invoices: id, number, state, status text, gross)
 - "Create invoice" again on a quotation with a full invoice that is not cancelled: 409 code invoice_exists with that
   invoice, nothing made; force=true makes the second one; the same client_ref again still answers the first draft;
   progress invoices are several per quotation on purpose (no question)
 - the quotation list marks the quotations with a full invoice (invoiced; "New invoice > From a quotation…")
 - another organisation sees neither the quotation nor its invoices
 - the agents' route (v1): 409 invoice_exists in the API's error format (error.code, error.invoices), force=true makes
   it; the agent's document answer carries source_offer / offer_invoices without the internal list_id
 - a person without an organisation (personal office, own agent) works the same
freelancer-matrix: office
usage: p2356_c_offer_invoice_test.py <datadir>      (P2356C_NOSTART=1: the container runs already)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients,time"

kt.fresh(prefix="P2356C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.get(B + O + "/settings")
Ca.get(B + O + "/settings")


def quote(s, cl, title):
    q = s.post(B + D, json={"client_id": cl, "project_title": title}).json()["id"]
    r = s.put(B + f"{D}/{q}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 2, "unit": "day", "rate": 800}]})
    assert r.ok, r.text
    return q


def doc(s, did):
    return s.get(B + f"{D}/{did}").json()


def flow(s, who):
    """The person's routes in the area s works in; -> (quotation id, first invoice id)."""
    cl = s.post(B + "/api/clients", json={"name": f"Beispiel {who} GmbH", "address": "Weg 2\n10115 Berlin"}).json()["id"]
    q = quote(s, cl, f"Imagefilm {who}")
    r = s.post(B + f"{D}/{q}/invoice", json={"client_ref": f"ref-{who}-1"})
    check(r.status_code == 201, f"{who}: an invoice from the quotation {r.status_code} {r.text[:200]}")
    inv = r.json()["id"]
    so = doc(s, inv).get("source_offer") or {}
    check(so.get("id") == q and "number" in so and so.get("status") == "draft",
          f"#3003 {who}: the invoice names its quotation {so}")
    oi = doc(s, q).get("offer_invoices") or []
    check([x["id"] for x in oi] == [inv] and oi[0].get("state") == "draft" and oi[0].get("status_text") and oi[0].get("gross_text"),
          f"#3003 {who}: the quotation lists its invoice with state {oi}")
    n0 = len(s.get(B + D, params={"kind": "invoice"}).json()["docs"])
    r = s.post(B + f"{D}/{q}/invoice", json={})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == 409 and j.get("code") == "invoice_exists" and [x["id"] for x in j.get("invoices") or []] == [inv] and j.get("error"),
          f"#3003 {who}: a second full invoice asks first (409 invoice_exists) {r.status_code} {r.text[:200]}")
    check(len(s.get(B + D, params={"kind": "invoice"}).json()["docs"]) == n0, f"#3003 {who}: ... and makes nothing")
    r = s.post(B + f"{D}/{q}/invoice", json={"client_ref": f"ref-{who}-1"})
    check(r.status_code == 200 and r.json()["id"] == inv, f"#3003 {who}: the first request sent again still answers its draft {r.status_code}")
    r = s.post(B + f"{D}/{q}/invoice", json={"force": True})
    check(r.status_code == 201 and r.json()["id"] != inv, f"#3003 {who}: force makes the second invoice {r.status_code} {r.text[:200]}")
    r = s.post(B + f"{D}/{q}/invoice", json={"inv_type": "progress", "pct": 30})
    check(r.status_code == 201, f"#3003 {who}: a progress invoice is not asked about {r.status_code} {r.text[:200]}")
    check(len(doc(s, q).get("offer_invoices") or []) == 3, f"#3003 {who}: the quotation lists all three")
    q2 = quote(s, cl, f"Spot {who}")
    rows = {x["id"]: x for x in s.get(B + D, params={"kind": "offer"}).json()["docs"]}
    check(rows[q].get("invoiced") is True and rows[q2].get("invoiced") is False, f"#3005 {who}: the quotation list marks invoiced ones")
    return q, inv


# ================================================================== an organisation
Q, INV = flow(A, "org")
check(Ca.get(B + f"{D}/{Q}").status_code in (403, 404) and Ca.get(B + f"{D}/{INV}").status_code in (403, 404),
      "#3003: another organisation sees neither the quotation nor its invoice")
check(all(x["id"] != Q for x in Ca.get(B + D, params={"kind": "offer"}).json()["docs"]), "#3003: ... nor lists it")
check(Ca.post(B + f"{D}/{Q}/invoice", json={"force": True}).status_code in (403, 404), "#3003: ... nor makes an invoice from it")

# ================================================================== freelancer: personal office + own agent
# freelancer-matrix: office
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
FQ, FINV = flow(Fr, "freelancer")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "office"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "setup: both office switches of the personal office")
FCL = Fr.post(B + "/api/clients", json={"name": "Agentur Beispiel"}).json()["id"]
AQ = quote(Fr, FCL, "Agenten-Angebot")
check(Fr.post(B + f"{D}/{AQ}/status", json={"status": "accepted"}).ok, "setup: the quotation accepted")
r = requests.post(V + f"/office/offers/{AQ}/invoice", headers=FH, json={})
check(r.status_code == 201, f"#3003 agent: the first invoice draft {r.status_code} {r.text[:200]}")
AINV = r.json().get("id") or (r.json().get("doc") or {}).get("id")
r = requests.post(V + f"/office/offers/{AQ}/invoice", headers=FH, json={})
e = (r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else None) or {}
check(r.status_code == 409 and isinstance(e, dict) and e.get("code") == "invoice_exists" and [x["id"] for x in e.get("invoices") or []] == [AINV]
      and all("list_id" not in x for x in e.get("invoices") or []), f"#3003 agent: 409 invoice_exists in the API's error format {r.status_code} {r.text[:300]}")
r = requests.post(V + f"/office/offers/{AQ}/invoice", headers=FH, json={"force": True})
check(r.status_code == 201, f"#3003 agent: force makes the second one {r.status_code} {r.text[:200]}")
j = requests.get(V + f"/office/docs/{AQ}", headers=FH).json()
check(len(j.get("offer_invoices") or []) == 2 and all("list_id" not in x for x in j["offer_invoices"]), f"#3003 agent: the quotation lists its invoices {j.get('offer_invoices')}")
j = requests.get(V + f"/office/docs/{AINV}", headers=FH).json()
check((j.get("source_offer") or {}).get("id") == AQ and "list_id" not in j["source_offer"], f"#3003 agent: the invoice names its quotation {j.get('source_offer')}")
check(A.get(B + f"{D}/{FQ}").status_code in (403, 404), "#3003: the freelancer's quotation stays hers (the organisation's admin gets nothing)")

sys.exit(kt.done("p2356_c_offer_invoice"))
