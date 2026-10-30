#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.417.0 C API tests, own container (kt.fresh). Invented companies and people only (@example.com / .example).
 - #3445 test mode: the setting trial_mode (["<office id>"], per person and office) is stored as a whole value and by
   set_delta (add / remove of one office, another office stays); wrong values (no list, not digits) 400; a colleague's
   setting stays empty (the test mode is personal); GET /api/office/trial answers trial_count / office_id for the admin
   and a member; a trial document made while the test mode is on counts, "Delete all" in the settings empties it
 - the server rules stay: a trial document is created only when the request says trial (no server side test mode),
   a real one without it
 - freelancer-matrix: office (a person without an organisation: own office id, the same setting and counts)
 - #2604: a finalised invoice stays for the admin and the person without an organisation (409 naming GoBD, also with
   confirm_number), a draft without a number and a trial invoice still go (tests/p2162_a_invoice_delete_test.py has the rest)
usage: p2417_c_api_test.py <datadir>"""
import json
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
FEAT = "clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D, O = "/api/office/docs", "/api/office"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}


def setting(s, k="trial_mode"):
    v = s.get(B + "/api/state").json().get("settings", {}).get(k)
    try:
        return json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return v


def setup_office(s):
    check(s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"}).ok, "office settings")
    r = s.post(B + "/api/clients", json={"name": "Example Client AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln",
                                         "country": "DE", "email_invoice": "billing@client.example"})
    check(r.status_code in (200, 201), "a client " + r.text[:160])
    return r.json().get("id")


def office_id(s):
    return s.get(B + O + "/settings").json().get("org_id")


def invoice(s, cl, title, final=True, trial=False):
    r = s.post(B + D, json={"kind": "invoice", "project_title": title, "client_id": cl, "service_from": "2030-01-01",
                            "service_to": "2030-01-31", **({"trial": True} if trial else {})})
    check(r.status_code == 201, f"{title}: created " + r.text[:160])
    did = r.json()["id"]
    check(s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 400}]}).ok, f"{title}: positions")
    if final:
        check(s.post(B + f"{D}/{did}/finalize").ok, f"{title}: finalised")
    return did


def mode_case(s, who, oid, other):
    """#3445: the setting of person s for office oid (other = a second office id that must survive)."""
    k = str(oid)
    check(setting(s) in ([], None), f"{who}: test mode off by default {setting(s)}")
    r = s.patch(B + "/api/settings", json={"trial_mode": json.dumps([k])})
    check(r.ok and setting(s) == [k], f"{who}: a whole value ({r.status_code} {r.text[:120]}) {setting(s)}")
    r = s.patch(B + "/api/settings", json={"set_delta": {"trial_mode": {"add": [other]}}})
    check(r.ok and setting(s) == [k, other], f"{who}: set_delta add of another office ({r.status_code}) {setting(s)}")
    r = s.patch(B + "/api/settings", json={"set_delta": {"trial_mode": {"remove": [k]}}})
    check(r.ok and setting(s) == [other], f"{who}: set_delta remove: the other office stays {setting(s)}")
    r = s.patch(B + "/api/settings", json={"set_delta": {"trial_mode": {"add": [k]}}})
    check(r.ok and setting(s) == [other, k], f"{who}: set_delta add again {setting(s)}")
    for bad in ('{"a": 1}', '["x1"]', '[12]', "not json"):
        r = s.patch(B + "/api/settings", json={"trial_mode": bad})
        check(r.status_code == 400, f"{who}: a wrong value {bad!r} -> 400 ({r.status_code})")
    check(setting(s) == [other, k], f"{who}: the wrong values changed nothing {setting(s)}")


# ================================================================== #3445 the organisation's office
CL = setup_office(A)
OID = office_id(A)
check(OID, f"the office id {OID}")
mode_case(A, "admin", OID, "999999")
check(setting(Bo) in ([], None), f"the colleague notices nothing (own setting empty) {setting(Bo)}")
j = A.get(B + O + "/trial").json()
check(j.get("trial_count") == 0 and j.get("office_id") == OID, f"GET /api/office/trial: none yet {j}")
# the server keeps its rule: trial only when the request says so (the client sends it in the test mode)
REAL = invoice(A, CL, "Real one", final=False)
check(A.get(B + f"{D}/{REAL}").json().get("trial") is False, "without trial: a real draft (no server side test mode)")
TRI = invoice(A, CL, "Trial one", trial=True)
td = A.get(B + f"{D}/{TRI}").json()
check(td.get("trial") is True and str(td.get("number") or "").startswith("TEST"), f"with trial: a trial invoice {td.get('trial')} {td.get('number')}")
check(A.get(B + O + "/trial").json().get("trial_count") == 1, "GET /api/office/trial: one")
jb = Bo.get(B + O + "/trial")
check(jb.ok and jb.json().get("trial_count") == 1, f"a member reads the count too ({jb.status_code})")
check(Bo.post(B + O + "/trial/delete-all", json={}).status_code == 403, "a member cannot delete all trial documents (403)")
r = A.post(B + O + "/trial/delete-all", json={})
check(r.ok and r.json().get("docs") == 1, "the admin deletes all trial documents " + r.text[:160])
check(A.get(B + O + "/trial").json().get("trial_count") == 0 and A.get(B + f"{D}/{REAL}").ok, "none left, the real draft stays")

# ================================================================== #2604 quickly: the strict rule (details: p2162_a)
FIN = invoice(A, CL, "Final one")
num = A.get(B + f"{D}/{FIN}").json().get("number")
r = A.delete(B + f"{D}/{FIN}?confirm_number={num}")
check(r.status_code == 409 and "GoBD" in r.text and A.get(B + f"{D}/{FIN}").ok, f"#2604 admin: a finalised invoice stays ({r.status_code} {r.text[:120]})")
check(A.delete(B + f"{D}/{REAL}").ok, "#2604 admin: a draft without a number goes")
# #2574: a quotation that is not finalised but accepted / sent stays too (can_delete false, DELETE 409); a draft goes
for st in ("accepted", "sent"):
    q = A.post(B + D, json={"kind": "offer", "project_title": "Open " + st, "client_id": CL}).json()
    check(A.post(B + f"{D}/{q['id']}/status", json={"status": st}).ok, f"#2574: an open quotation {st}")
    qd = A.get(B + f"{D}/{q['id']}").json()
    row = next((x for x in A.get(B + D + "?kind=offer").json().get("docs", []) if x["id"] == q["id"]), {})
    check(qd.get("can_delete") is False and row.get("can_delete") is False, f"#2574 {st}: no can_delete (view + list row) {qd.get('can_delete')} {row.get('can_delete')}")
    check(A.delete(B + f"{D}/{q['id']}").status_code == 409 and A.get(B + f"{D}/{q['id']}").ok, f"#2574 {st}: DELETE 409, it stays")
q = A.post(B + D, json={"kind": "offer", "project_title": "Open draft", "client_id": CL}).json()
check(A.get(B + f"{D}/{q['id']}").json().get("can_delete") is True and A.delete(B + f"{D}/{q['id']}").ok, "#2574: a quotation draft goes")

# review F1: "undo finalising" of an invoice names the finalised rule, not the delete text
r = A.post(B + f"{D}/{FIN}/unlock")
check(r.status_code == 409 and "finalised" in r.text and "GoBD" not in r.text, f"review F1: unlock of an invoice 409, finalised text ({r.text[:120]})")
# review F2: an open quotation past draft is kept as sent (not "finalised")
q = A.post(B + D, json={"kind": "offer", "project_title": "Open accepted F2", "client_id": CL}).json()
A.post(B + f"{D}/{q['id']}/status", json={"status": "accepted"})
r = A.delete(B + f"{D}/{q['id']}")
check(r.status_code == 409 and "sent to the client" in r.text, f"review F2: open accepted quotation, the sent text ({r.text[:120]})")
# review F3: a quotation draft something was made from: the list row offers no delete
q = A.post(B + D, json={"kind": "offer", "project_title": "Draft invoiced F3", "client_id": CL}).json()
A.put(B + f"{D}/{q['id']}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 400}]})
r = A.post(B + f"{D}/{q['id']}/invoice")
if r.status_code == 201:
    row = next((x for x in A.get(B + D + "?kind=offer").json().get("docs", []) if x["id"] == q["id"]), {})
    check(row.get("can_delete") is False, f"review F3: an invoice from the draft: the row offers no delete {row.get('can_delete')}")
    check(A.delete(B + f"{D}/{q['id']}").status_code == 409, "review F3: and the server keeps it")
else:
    check(r.status_code in (400, 409), f"review F3: an invoice from a draft refused ({r.status_code}) -- nothing to show")

# ================================================================== freelancer-matrix: office (a person without an organisation)
FID, F = freelancer(B, A, "frida", features=FEAT)
FCL = setup_office(F)
FOID = office_id(F)
check(FOID and FOID != OID, f"freelancer: an own office id {FOID}")
mode_case(F, "freelancer", FOID, "888888")
check(F.get(B + O + "/trial").json().get("office_id") == FOID, "freelancer: GET /api/office/trial for the own office")
FT = invoice(F, FCL, "Solo trial", trial=True)
check(F.get(B + O + "/trial").json().get("trial_count") == 1, "freelancer: the trial invoice counts")
# tenant-matrix: office -- GET /api/office/trial counts the office open now only: frida's trial invoice is not in alice's count
check(A.get(B + O + "/trial").json().get("trial_count") == 0, "tenant: another tenant's trial invoice is not counted")
FF = invoice(F, FCL, "Solo final")
r = F.delete(B + f"{D}/{FF}")
check(r.status_code == 409 and "GoBD" in r.text, f"#2604 freelancer: the finalised invoice stays ({r.status_code})")
check(F.delete(B + f"{D}/{FT}").ok, "#2604 freelancer: a finalised trial invoice goes at any time")
check(setting(A) == ["999999", str(OID)], f"alice's setting untouched by frida's {setting(A)}")

sys.exit(kt.done("p2417_c_api"))
