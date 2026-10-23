#!/usr/bin/env python3
"""2.144.10 API tests, part A (#2576): trial documents ("Nur zum Ausprobieren"), the core.
Own container (start.sh), invented companies and people only (@example.com / .example).
 - POST /api/office/docs with trial: true (quotation and invoice directly) -> TEST-001, TEST-002 ... from one own counter
   (office_numbers kind 'trial'); no real counter moves; a number by hand 400; PATCH never switches trial
 - follow-ups inherit trial: invoice from a trial quotation, credit note, copy, document from a template
 - finalising keeps the TEST number; the PDF says SAMPLE (MUSTER in German) and not DRAFT; no e-invoice XML (409)
 - no webhook event for trial invoices (a real one queues invoice.created)
 - an invoice series from a trial invoice: 409
 - the admin deletes a trial document at any time (finalised, sent, signed, with follow-ups; the follow-up stays, its
   link is emptied; the office log has the delete with trial: true); a member 403 (can_delete false); trip costs billed
   on it are free again (single delete and delete all)
 - the list: trial on every row, ?trial=1|0, trial_count, first {offer, invoice}, office_id
 - POST /api/office/trial/delete-all: member 403, counts, real documents and other areas stay, stored files and the
   filed PDF of a document from a template are gone, the TEST series starts again (tenant-matrix: office)
 - a person without an organisation (freelancer-matrix: office) does the same in the personal office
usage: p214410_a_api_test.py <datadir>      (a fresh container; P214410A_NOSTART=1 = the server already runs)"""
import glob
import io
import json
import os
import subprocess
import sys

import requests
from pypdf import PdfReader

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TEST_IBAN = "DE02120300000000202051"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pdf_text(data):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


if not os.environ.get("P214410A_NOSTART"):
    # webhooks may target the (absent) stub; the queue is not worked off during the run, so its rows can be read
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
                   env=dict(os.environ, EXTRA="-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=3600"))
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office,docs,files"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123",
                                       "email": "carol@example.com", "orgs": []}).json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": CAROL})
assert r.status_code == 201, r.text
OTHER = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{OTHER}"})
D = "/api/office/docs"
O = "/api/office"
DA = O + "/trial/delete-all"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def setup_office(s):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
    check(r.ok, "office settings " + r.text[:200])
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def make(s, cl, title, trial=True, kind="offer", final=False, **extra):
    r = s.post(B + D, json={"kind": kind, "project_title": title, "client_id": cl, "service_from": "2030-02-01", "service_to": "2030-02-28",
                            **({"trial": True} if trial else {}), **extra})
    check(r.status_code == 201, f"{title}: created " + r.text[:200])
    did = r.json()["id"]
    check(s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]}).ok, f"{title}: positions")
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok and r.json()["locked"] is True, f"{title}: finalised " + r.text[:300])
    return did


def counters(oid):
    return {(x["kind"], x["period"]): x["last"] for x in dbx("SELECT kind, period, last FROM office_numbers WHERE org_id=?", (oid,))}


def real(cnt):
    return {k: v for k, v in cnt.items() if k[0] != "trial"}


def lst(s, q=""):
    r = s.get(B + D + q)
    check(r.ok, "the list " + r.text[:200])
    return r.json()


def office_files(oid, did):
    return glob.glob(os.path.join(DATA, "office", str(int(oid)), f"doc{int(did)}-*"))


def run(S, oid, who, M=None, cl=None):
    """The core flow in office oid as admin session S (M = a member's session or None)."""
    first = lst(S)
    check(first.get("office_id") == oid, f"{who}: office_id {first.get('office_id')} == {oid}")
    check(first.get("first") == {"offer": True, "invoice": True} and first.get("trial_count") == 0, f"{who}: a fresh area {first.get('first')} {first.get('trial_count')}")
    before = real(counters(oid))
    # ------------------------------------------------ creating: TEST numbers, no real counter moves
    q1 = make(S, cl, "Trial film")
    d = S.get(B + f"{D}/{q1}").json()
    check(d.get("trial") is True and d.get("number") == "TEST-001", f"{who}: trial quotation TEST-001 {d.get('trial')} {d.get('number')}")
    i1 = make(S, cl, "Trial invoice", kind="invoice")
    d = S.get(B + f"{D}/{i1}").json()
    check(d.get("trial") is True and d.get("number") == "TEST-002", f"{who}: trial invoice directly TEST-002 {d.get('number')}")
    check(real(counters(oid)) == before, f"{who}: no real counter moved {real(counters(oid))} vs {before}")
    check(counters(oid).get(("trial", "")) == 2, f"{who}: the TEST counter at 2 {counters(oid)}")
    check(S.post(B + f"{D}/{q1}/number", json={"number": "X-77"}).status_code == 400, f"{who}: a number by hand for a trial one 400")
    # a trip cost billed on the trial quotation (freed again when it is deleted, below)
    r = S.post(B + O + "/trips", json={"date_from": "2030-02-10", "dest": "Example location", "items": [{"date": "2030-02-10", "category": "taxi", "amount": 25}]})
    check(r.status_code == 201, f"{who}: a trip " + r.text[:200])
    ti = (r.json().get("items") or [{}])[0].get("id")
    r = S.post(B + O + "/trips/bill", json={"doc_id": q1, "item_ids": [ti]})
    check(r.ok, f"{who}: the trip cost billed on the trial quotation " + r.text[:200])
    S.patch(B + f"{D}/{q1}", json={"trial": False, "project_title": "Trial film 2"})
    check(S.get(B + f"{D}/{q1}").json().get("trial") is True, f"{who}: PATCH never switches trial")
    q0 = make(S, cl, "Real film", trial=False)
    d = S.get(B + f"{D}/{q0}").json()
    check(d.get("trial") is False and d.get("number") and not d["number"].startswith("TEST"), f"{who}: a real quotation keeps its series {d.get('number')}")
    base = real(counters(oid))  # with the real quotation's number
    # ------------------------------------------------ the list: flags, filter, counts, first
    L = lst(S, "?kind=offer")
    rows = {x["id"]: x for x in L["docs"]}
    check(rows.get(q1, {}).get("trial") is True and rows.get(q0, {}).get("trial") is False, f"{who}: trial on each row")
    check(L.get("trial_count") == 2 and L.get("first") == {"offer": False, "invoice": True}, f"{who}: trial_count / first {L.get('trial_count')} {L.get('first')}")
    check([x["id"] for x in lst(S, "?kind=offer&trial=1")["docs"]] == [q1], f"{who}: ?trial=1 only the trial one")
    check(q1 not in [x["id"] for x in lst(S, "?kind=offer&trial=0")["docs"]] and q0 in [x["id"] for x in lst(S, "?kind=offer&trial=0")["docs"]], f"{who}: ?trial=0 only real ones")
    check(rows.get(q1, {}).get("can_delete") is True, f"{who}: the admin's row may delete the trial one")
    # ------------------------------------------------ finalise, accept, sign; follow-ups inherit
    r = S.post(B + f"{D}/{q1}/finalize")
    check(r.ok and r.json().get("number") == "TEST-001", f"{who}: finalised, the TEST number stays " + r.text[:200])
    check(S.post(B + f"{D}/{q1}/status", json={"status": "accepted"}).ok, f"{who}: accepted")
    dbx("INSERT INTO office_signoffs(org_id, kind, doc_id, title, token_hash, token, state, created_at) "
        "VALUES(?, 'offer', ?, 'x', ?, 'x', 'accepted', '2030-01-01T00:00:00Z')", (oid, q1, f"p214410a-{who}"))
    pdf = S.get(B + f"{D}/{q1}/pdf")
    check(pdf.ok and pdf.content.startswith(b"%PDF"), f"{who}: the PDF {pdf.status_code}")
    t = pdf_text(pdf.content)
    check("SAMPLE" in t and "DRAFT" not in t, f"{who}: the PDF says SAMPLE, not DRAFT")
    r = S.post(B + f"{D}/{q1}/invoice")
    check(r.status_code == 201, f"{who}: an invoice from the trial quotation " + r.text[:200])
    inv = r.json()["id"]
    d = S.get(B + f"{D}/{inv}").json()
    check(d.get("trial") is True and d.get("number") == "TEST-003", f"{who}: the invoice is trial, TEST-003 {d.get('trial')} {d.get('number')}")
    r = S.post(B + f"{D}/{inv}/finalize")
    check(r.ok and r.json().get("number") == "TEST-003", f"{who}: the trial invoice finalised " + r.text[:300])
    check(real(counters(oid)) == base, f"{who}: finalising trial documents moves no real counter {real(counters(oid))} vs {base}")
    check(S.get(B + f"{D}/{inv}/xml").status_code == 409, f"{who}: no e-invoice XML for a trial invoice")
    st = dbx("SELECT xml_sha256, pdf_sha256 FROM office_docs WHERE id=?", (inv,))[0]
    check(not st[0] and st[1], f"{who}: the stored PDF, no stored XML {tuple(st)}")
    check("SAMPLE" in pdf_text(S.get(B + f"{D}/{inv}/pdf").content), f"{who}: the finalised invoice PDF says SAMPLE")
    r = S.post(B + f"{D}/{inv}/credit")
    check(r.status_code == 201 and S.get(B + f"{D}/{r.json().get('id')}").json().get("trial") is True, f"{who}: a credit note of it is trial " + r.text[:200])
    r = S.post(B + f"{D}/{q0}/duplicate")
    check(r.status_code == 201 and r.json().get("trial") is False, f"{who}: a copy of a real one stays real")
    r = S.post(B + f"{D}/{q1}/duplicate")
    check(r.status_code == 201 and r.json().get("trial") is True and r.json().get("number", "").startswith("TEST-"), f"{who}: a copy of a trial one stays trial {r.json().get('number')}")
    r = S.post(B + O + "/series", json={"template_id": inv, "every": "monthly", "start": "2030-03-01"})
    check(r.status_code == 409, f"{who}: no invoice series from a trial invoice {r.status_code} {r.text[:200]}")
    # a document from a template, linked to the trial quotation: trial; its PDF says SAMPLE
    r = S.post(B + O + "/doc-templates", json={"starter": "contract"})
    check(r.status_code == 201, f"{who}: a template " + r.text[:200])
    r = S.post(B + O + "/gen-docs", json={"template_id": r.json().get("id"), "client_id": cl, "doc_id": q1})
    check(r.status_code == 201 and r.json().get("trial") is True, f"{who}: a document of the trial quotation is trial " + r.text[:200])
    gd = r.json()["id"]
    r = S.post(B + O + f"/gen-docs/{gd}/final")
    check(r.ok, f"{who}: the document finished " + r.text[:200])
    node = dbx("SELECT node_id FROM office_gen_docs WHERE id=?", (gd,))[0][0]
    check(bool(node), f"{who}: filed into the documents space")
    check("SAMPLE" in pdf_text(S.get(B + O + f"/gen-docs/{gd}/pdf").content), f"{who}: the document PDF says SAMPLE")
    gl = S.get(B + O + "/gen-docs?trial=1&brief=1").json()["docs"]
    check([x["id"] for x in gl] == [gd] and gl[0]["trial"] is True, f"{who}: gen-docs ?trial=1")
    check(lst(S).get("trial_count") == 6, f"{who}: trial_count = 5 documents + 1 document from a template {lst(S).get('trial_count')}")
    # ------------------------------------------------ delete at any time (finalised, accepted, signed, with follow-ups)
    if M is not None:
        check(M.get(B + f"{D}/{q1}").json().get("can_delete") is False, f"{who}: a member's can_delete false")
        check(M.delete(B + f"{D}/{q1}").status_code == 403, f"{who}: a member cannot delete a trial one")
        check(M.post(B + DA).status_code == 403, f"{who}: a member cannot delete all")
    check(S.get(B + f"{D}/{q1}").json().get("can_delete") is True, f"{who}: the admin's can_delete true (finalised, signed, invoiced)")
    r = S.delete(B + f"{D}/{q1}")
    check(r.ok, f"{who}: the admin deletes the finalised, signed, invoiced trial quotation " + r.text[:200])
    check(S.get(B + f"{D}/{q1}").status_code == 404, f"{who}: gone")
    d = S.get(B + f"{D}/{inv}").json()
    check(d.get("id") == inv and not d.get("source_doc_id"), f"{who}: the follow-up stays, its link emptied {d.get('source_doc_id')}")
    check(not dbx("SELECT 1 FROM office_signoffs WHERE token_hash=?", (f"p214410a-{who}",)), f"{who}: the signoff went with it")
    check(dbx("SELECT billed_doc_id FROM office_trip_items WHERE id=?", (ti,))[0][0] is None, f"{who}: the trip cost is free again")
    r = S.post(B + O + "/trips/bill", json={"doc_id": i1, "item_ids": [ti]})
    check(r.ok, f"{who}: the freed trip cost can be billed again (on the trial invoice) " + r.text[:200])
    ent = [x for x in S.get(B + O + "/log?limit=200").json().get("log") or [] if x.get("doc_id") == q1 and x.get("action") == "delete"]
    check(ent and ent[0]["detail"].get("trial") is True and ent[0]["detail"].get("number") == "TEST-001", f"{who}: the office log keeps the delete {ent[:1]}")
    # ------------------------------------------------ delete all
    files = office_files(oid, inv)
    check(files, f"{who}: the finalised trial invoice has its stored file")
    n_trial = len(lst(S, "?kind=offer&trial=1")["docs"]) + len(lst(S, "?kind=invoice&trial=1")["docs"]) + len(lst(S, "?kind=credit&trial=1")["docs"])
    r = S.post(B + DA)
    if r.status_code >= 500:  # the server's traceback into the suite log
        print(subprocess.run(["docker", "logs", "--tail", "60", CT], capture_output=True, text=True).stderr[-6000:], flush=True)
    check(r.ok and r.json().get("ok") is True and r.json().get("docs") == n_trial and r.json().get("gen_docs") == 1,
          f"{who}: delete all {r.text[:200]} (expected {n_trial} documents)")
    check(lst(S).get("trial_count") == 0, f"{who}: no trial document left")
    check(S.get(B + f"{D}/{q0}").ok, f"{who}: the real quotation stays")
    check(dbx("SELECT billed_doc_id FROM office_trip_items WHERE id=?", (ti,))[0][0] is None, f"{who}: delete all frees the trip cost too")
    check(not office_files(oid, inv), f"{who}: the stored file is gone {office_files(oid, inv)}")
    check(not dbx("SELECT 1 FROM fs_nodes WHERE id=?", (node,)), f"{who}: the filed document PDF is gone")
    check(not dbx("SELECT 1 FROM office_gen_docs WHERE id=?", (gd,)), f"{who}: the document from a template is gone")
    q2 = make(S, cl, "Trial again")
    check(S.get(B + f"{D}/{q2}").json().get("number") == "TEST-001", f"{who}: the TEST series starts again")
    return q2


CL = setup_office(A)
# tenant-matrix: office -- delete-all and the delete of a trial document across the boundary
CCL = setup_office(Ca)
CQ = make(Ca, CCL, "Other trial")
AQ = run(A, ORG, "org", Bo, CL)
check(Ca.get(B + f"{D}/{CQ}").ok, "the other organisation's trial document stayed after alice's delete all")
check(Ca.delete(B + f"{D}/{AQ}").status_code in (403, 404), "another organisation cannot delete alice's trial document")
r = Ca.post(B + DA)
check(r.ok and r.json().get("docs") == 1, "the other organisation deletes only its own " + r.text[:200])
check(A.get(B + f"{D}/{AQ}").ok, "alice's trial document stays")

# ------------------------------------------------ webhooks: a trial invoice never queues an event
r = A.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": "Hook", "url": "http://127.0.0.1:8097/org", "events": ["invoice.created", "invoice.sent", "invoice.paid"]})
check(r.status_code == 201, "an organisation webhook " + r.text[:200])
TI = make(A, CL, "Trial invoice for the hook", kind="invoice", final=True)
RI = make(A, CL, "Real invoice for the hook", trial=False, kind="invoice")
q = [json.loads(x[0]) for x in dbx("SELECT payload FROM webhook_queue")]
ids = [((p.get("data") or {}).get("invoice") or {}).get("id") for p in q]
check(RI in ids, f"a real invoice queues invoice.created {ids}")
check(TI not in ids, f"a trial invoice queues nothing {ids}")

# ------------------------------------------------ the German watermark word (once the language file has it)
de = json.load(open(os.path.join(N, "..", "static", "i18n", "de.json"), encoding="utf-8"))
if de.get("SAMPLE") == "MUSTER":
    DQ = make(A, CL, "Deutsches Muster", lang="de")
    check("MUSTER" in pdf_text(A.get(B + f"{D}/{DQ}/pdf").content), "a German trial PDF says MUSTER")

# freelancer-matrix: office
FID, F = freelancer(B, A)
FCL = setup_office(F)
FOID = F.get(B + D).json().get("office_id")
check(bool(FOID) and FOID != ORG, f"the personal office has its own id {FOID}")
run(F, FOID, "freelancer", None, FCL)
check(A.get(B + f"{D}/{AQ}").ok, "the freelancer's delete all leaves the organisation alone")

print(f"p214410_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
