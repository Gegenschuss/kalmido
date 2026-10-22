#!/usr/bin/env python3
"""2.168.0 A (#2665) API tests: quotations, invoices and credit notes bound to a project. Own container (start.sh),
invented companies and people only (@example.com / .example).
 - POST /api/office/docs/<id>/project: pick a project, take it off, create one ("Client - title": the office area's
   workspace, the document's client, only its maker a member); a project the person does not see 404, one of another
   workspace 400, an unknown body / a reminder 400; also on a finalised document (number, totals unchanged), office log
   "project"
 - inherit: invoice from the quotation, progress + final invoice, a new quotation version, a credit note, an invoice from
   the hours of one project; a copy of an invoice does not
 - pipeline: a deal's quotation gets the deal's project; a project created on a deal's quotation goes to the deal too
 - GET /api/lists/<id>/office-docs: office people see the documents with amounts; a project member without the office
   module, a guest of the organisation (office_allowed refuses) and a member of another office: office false, no documents
 - a person without an organisation (freelancer-matrix: office): the same with the personal office and private projects
usage: p2168_a_docproject_test.py <datadir>      (a fresh container; P2168A_NOSTART=1 = the server already runs)"""
import base64
import os
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
TODAY = testclock.today()
T0, Y5 = TODAY.isoformat(), (TODAY - timedelta(days=5)).isoformat()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P2168A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office,docs,files,time"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("carl", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"create {u} as {role}: " + r.text[:200])
    uid[u] = r.json().get("id")
Bo, Ca, Gi = sess("bob"), sess("carl"), sess("gina")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
Ca.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,comments,collab,clients"})  # no office
Gi.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
for s in (A, Bo, Ca, Gi):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D, O = "/api/office/docs", "/api/office"
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


def make(s, cl, title, kind="offer", final=False, rate=1000):
    r = s.post(B + D, json={"kind": kind, "project_title": title, "client_id": cl, "service_from": Y5, "service_to": T0})
    check(r.status_code == 201, f"{title}: created " + r.text[:200])
    did = r.json()["id"]
    check(s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": rate}]}).ok, f"{title}: positions")
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok and r.json().get("locked") is True, f"{title}: finalised " + r.text[:300])
    return did


def lst(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    check(r.status_code in (200, 201), f"list {name} " + r.text[:200])
    return r.json()["id"]


def proj(s, did, body):
    return s.post(B + f"{D}/{did}/project", json=body)


def lid_of(s, did):
    return s.get(B + f"{D}/{did}").json().get("list_id")


CL = setup_office(A)
LP = lst(A, "Film project", ORG)  # an organisation project of Alice
LX = lst(Bo, "Bob's own", ORG)  # an organisation project Alice does not see
LPRIV = lst(A, "Alice private", None)  # a private project: another workspace than the organisation's office
check(A.patch(B + f"/api/lists/{LP}", json={"client_id": CL}).ok, "the project has the client")

# ================================================================== pick / take off / refuse
Q = make(A, CL, "Film")
r = proj(A, Q, {"list_id": LP})
check(r.ok and r.json().get("list_id") == LP and r.json().get("list_name") == "Film project", "the project picked " + r.text[:200])
check(proj(A, Q, {"list_id": LX}).status_code == 404, "a project Alice does not see: 404")
check(proj(A, Q, {"list_id": LPRIV}).status_code == 400, "a private project for the organisation's office: 400")
check(proj(A, Q, {"list_id": 999999}).status_code == 404, "an unknown project: 404")
check(proj(A, Q, {}).status_code == 400, "no list_id / create: 400")
check(proj(A, Q, {"create": {"name": "  "}}).status_code == 400, "an empty name: 400")
check(lid_of(A, Q) == LP, "a refused change keeps the project")
r = proj(A, Q, {"list_id": None})
check(r.ok and r.json().get("list_id") is None and lid_of(A, Q) is None, "the project taken off " + r.text[:200])
check(proj(A, Q, {"list_id": LP}).ok, "picked again")
log = A.get(B + f"{D}/{Q}/log").json()
log = log.get("log", log) if isinstance(log, dict) else log
check(any(x.get("action") == "project" for x in log or []), "the office log says 'project'")

# ---- a finalised document: still settable, the document itself unchanged
QF = make(A, CL, "Frozen", final=True)
before = A.get(B + f"{D}/{QF}").json()
r = proj(A, QF, {"list_id": LP})
after = A.get(B + f"{D}/{QF}").json()
check(r.ok and after.get("list_id") == LP, "a finalised quotation gets a project " + r.text[:200])
check(after.get("number") == before.get("number") and after.get("totals") == before.get("totals") and after.get("locked") is True
      and after.get("locked_at") == before.get("locked_at"), "number, totals and the lock unchanged")
check(Bo.post(B + f"{D}/{QF}/project", json={"list_id": None}).ok, "a member of the office may change it too")
check(proj(A, QF, {"list_id": LP}).ok, "set again")

# ---- create a project: name, client, only its maker a member, the organisation's workspace
r = proj(A, Q, {"create": {"name": "  Example Client AG  –  Film  "}})
check(r.status_code == 201, "a new project created " + r.text[:200])
NL = r.json().get("list_id")
check(isinstance(r.json().get("modules_on"), list), "modules_on in the answer")
row = dbx("SELECT name, org_id, client_id, owner_id, ptype FROM lists WHERE id=?", (NL,))
check(row and row[0][0] == "Example Client AG – Film" and row[0][1] == ORG and row[0][2] == CL and row[0][3] == ALICE
      and row[0][4] == "agency", f"the new project: name, organisation, client, owner, type {row}")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id<>?", (NL, ALICE)), "nobody else is a member")
check(Bo.get(B + f"/api/lists/{NL}/office-docs").status_code == 404, "Bob does not see the new project")
check(lid_of(A, Q) == NL, "the quotation is in the new project")

# ================================================================== inherit
check(proj(A, Q, {"list_id": LP}).ok, "back to the film project")
r = A.post(B + f"{D}/{Q}/invoice")
check(r.status_code == 201 and r.json().get("list_id") == LP, "invoice from the quotation keeps the project " + r.text[:200])
r = A.post(B + f"{D}/{QF}/invoice", json={"inv_type": "progress", "pct": 30})
check(r.status_code == 201 and r.json().get("list_id") == LP, "a progress invoice keeps the project " + r.text[:200])
PI = r.json().get("id")
check(A.post(B + f"{D}/{PI}/finalize").ok, "the progress invoice finalised")
r = A.post(B + f"{D}/{QF}/invoice", json={"inv_type": "final"})
check(r.status_code == 201 and r.json().get("list_id") == LP, "the final invoice keeps the project " + r.text[:200])
r = A.post(B + f"{D}/{QF}/duplicate")
check(r.status_code == 201 and r.json().get("list_id") == LP and r.json().get("version_of") == QF, "a new quotation version keeps it " + r.text[:200])
r = A.post(B + f"{D}/{PI}/credit")
check(r.status_code == 201 and r.json().get("list_id") == LP, "a credit note keeps the project " + r.text[:200])
r = A.post(B + f"{D}/{PI}/duplicate")
check(r.status_code == 201 and r.json().get("list_id") is None, "a copy of an invoice has no project " + r.text[:200])
# an invoice from the hours of one project
dbx("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?)", (ALICE, LP, "Edit", T0 + "T08:00:00Z", T0 + "T10:00:00Z", 7200, "", "manual", T0 + "T10:00:00Z", T0 + "T10:00:00Z"))
r = A.post(B + D + "/from-time", json={"client_id": CL, "from": Y5, "to": T0})
check(r.status_code == 201 and r.json().get("list_id") == LP, "an invoice from one project's hours belongs to it " + r.text[:200])
# a reminder never gets one
REM = A.post(B + D + "/reminder", json={"doc_ids": [PI], "level": 1}).json().get("id")
check(REM and proj(A, REM, {"list_id": LP}).status_code == 400, "a reminder: 400")

# ================================================================== pipeline
r = A.post(B + O + "/deals", json={"title": "Campaign", "client_id": CL, "stage": "inquiry", "list_id": LP})
check(r.status_code == 201, "a deal with a project " + r.text[:200])
DL = r.json().get("id")
r = A.post(B + O + f"/deals/{DL}/offer")
check(r.status_code == 201 and lid_of(A, r.json().get("doc_id")) == LP, "the deal's quotation has the deal's project " + r.text[:200])
r = A.post(B + O + "/deals", json={"title": "Spot", "client_id": CL, "stage": "inquiry"})
DL2 = r.json().get("id")
DQ = A.post(B + O + f"/deals/{DL2}/offer").json().get("doc_id")
check(lid_of(A, DQ) is None, "a deal without a project: its quotation has none")
r = proj(A, DQ, {"create": {"name": "Example Client AG – Spot"}})
NL2 = r.json().get("list_id")
deal = next((x for x in A.get(B + O + "/deals").json().get("items", []) if x["id"] == DL2), {})
check(r.status_code == 201 and deal.get("list_id") == NL2, f"the deal got the new project {deal.get('list_id')} / {NL2}")
r = proj(A, DQ, {"create": {"name": "Another"}})
deal = next((x for x in A.get(B + O + "/deals").json().get("items", []) if x["id"] == DL2), {})
check(r.status_code == 201 and deal.get("list_id") == NL2, "a deal with a project keeps it")

# ================================================================== the project's documents
j = A.get(B + f"/api/lists/{LP}/office-docs").json()
kinds = {x["kind"] for x in j.get("docs", [])}
check(j.get("office") is True and {"offer", "invoice", "credit"} <= kinds, f"Alice sees the documents {kinds}")
d0 = next((x for x in j.get("docs", []) if x["id"] == QF), {})
check(d0.get("gross_text") and d0.get("number") and d0.get("status_text"), f"a row with number, status, amount {d0}")
check(not any(x["kind"] == "reminder" for x in j.get("docs", [])), "no reminders")
check(set(d0) <= {"id", "kind", "number", "status", "state", "status_text", "date", "gross_text", "project_title", "trial"},
      f"only the brief fields {sorted(d0)}")
# members of the project: Bob (office), Carl (no office module), Gina (guest)
for u in ("bob", "carl", "gina"):
    r = A.post(B + f"/api/lists/{LP}/members", json={"user_id": uid[u], "role": "edit"})
    check(r.ok, f"{u} a member of the project " + r.text[:200])
j = Bo.get(B + f"/api/lists/{LP}/office-docs").json()
check(j.get("office") is True and len(j.get("docs", [])) >= 5, "Bob (office member) sees them too")
for nm, s in (("Carl without the office module", Ca), ("Gina the guest", Gi)):
    r = s.get(B + f"/api/lists/{LP}/office-docs")
    check(r.status_code == 200 and r.json() == {"office": False, "docs": []}, f"{nm}: office false, nothing " + r.text[:200])
check(Ca.get(B + f"/api/lists/{LX}/office-docs").status_code == 404, "a project one does not see: 404")
check(Bo.post(B + f"{D}/{Q}/project", json={"list_id": LX}).ok, "Bob puts the quotation into his own project")
j = A.get(B + f"/api/lists/{LP}/office-docs").json()
check(not any(x["id"] == Q for x in j.get("docs", [])), "it left the film project")

# ================================================================== a person without an organisation (freelancer-matrix: office)
FID, F = freelancer(B, A)
FCL = setup_office(F)
FL = lst(F, "Frida's film")
FQ = make(F, FCL, "Portrait", final=True)
r = F.post(B + f"{D}/{FQ}/project", json={"list_id": FL})
check(r.ok and r.json().get("list_id") == FL, "the freelancer picks a private project " + r.text[:200])
check(F.post(B + f"{D}/{FQ}/project", json={"list_id": LP}).status_code == 404, "the freelancer: an organisation's project 404")
r = F.post(B + f"{D}/{FQ}/project", json={"create": {"name": "Portrait series"}})
FNL = r.json().get("list_id")
row = dbx("SELECT org_id, owner_id, client_id FROM lists WHERE id=?", (FNL,))
check(r.status_code == 201 and row and row[0][0] is None and row[0][1] == FID and row[0][2] == FCL, f"a new private project {row}")
r = F.post(B + f"{D}/{FQ}/invoice")
check(r.status_code == 201 and r.json().get("list_id") == FNL, "the freelancer's invoice keeps the project " + r.text[:200])
j = F.get(B + f"/api/lists/{FNL}/office-docs").json()
check(j.get("office") is True and {x["kind"] for x in j.get("docs", [])} == {"offer", "invoice"}, f"the freelancer's project shows them {j}")
check(F.get(B + f"/api/lists/{LP}/office-docs").status_code == 404, "the freelancer: the organisation's project 404")
check(A.post(B + f"{D}/{FQ}/project", json={"list_id": None}).status_code == 404, "Alice: the freelancer's document 404")
# a private project shared with Alice: she sees it, but it is not her personal office's -> office false
check(F.post(B + f"/api/lists/{FNL}/members", json={"user_id": ALICE, "role": "view"}).ok, "the freelancer shares the project")
r = A.get(B + f"/api/lists/{FNL}/office-docs")
check(r.status_code == 200 and r.json() == {"office": False, "docs": []}, "another person's private project: office false " + r.text[:200])

print(f"p2168_a_docproject: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
