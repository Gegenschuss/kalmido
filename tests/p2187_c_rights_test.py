#!/usr/bin/env python3
"""2.187.0 part C (#2476): the office rights (groups, levels per area) outside /api/office. Invented names only.
 - a member in the template "Staff": the contact history without quotations / invoices, a project's office documents
   {office: false}, the acceptance links of an own organisation project 403, another person's receipt file refused,
   the own receipt file 200; the disposition still lists the equipment (Staff reads equipment)
 - a member in an own group without any area: no equipment / sets in the disposition, no receipt file
 - a member without a group ("previous access"): everything exactly as before
 - agents (decision 6): without a group and with the switch office_drafts off no office access (403); the switch on and
   no group = the previous access (the rights page shows "Previous access"); in "Project management" a quotation draft
   works, payment suggestions 403 (Bank none); in "No office access" 403; never "Manage office rights" (400); an agent of a
   person in "Staff" gets nothing that person may not (403)
 - organisation export / import / move of a personal office know the new tables (groups + log go along, memberships stay)
 - a person without an organisation (freelancer-matrix: office): her own agent in her personal office starts without
   access, the group "Project management" lets it draft a quotation, payment suggestions stay 403
usage: p2187_c_rights_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
O, D, R, V = "/api/office", "/api/office/docs", "/api/office/rights", "/api/v1/office"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts,dispo,workload"


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def in_app(code):
    return subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)


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
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


if not os.environ.get("P2187C_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as member " + r.text[:200])
    uid[u] = r.json().get("id")
Bo, Ca, Da = sess("bob"), sess("carl"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
check(A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR", "agents_read": 1}).ok, "setup: office settings")

# ---- an address book contact, the client linked to it, a quotation; a project with the quotation (bob a member)
BK = A.post(B + "/api/books", json={"name": "Studio customers", "org_id": ORG}).json()["id"]
check(A.post(B + f"/api/books/{BK}/org", json={"org_role": "view"}).ok, "setup: the organisation owns the book")
r = A.post(B + "/api/contacts", json={"book_id": BK, "given": "Petra", "family": "Buyer", "emails": [{"value": "petra@example.com"}]})
CT1 = r.json()["id"]
r = A.post(B + "/api/clients", json={"name": "Example Client AG", "country": "DE", "org_id": ORG,
                                     "contacts": [{"name": "Petra Buyer", "is_default": True, "contact_id": CT1}]})
check(r.status_code == 201, "setup: the client " + r.text[:200])
CL = r.json().get("id")
r = A.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Image film"})
check(r.status_code == 201, "setup: a quotation " + r.text[:200])
OFF = r.json().get("id")
LP = A.post(B + "/api/lists", json={"name": "Image film", "org_id": ORG}).json()["id"]
check(A.post(B + f"{D}/{OFF}/project", json={"list_id": LP}).ok, "setup: the quotation belongs to the project")
for u in ("bob", "carl", "dave"):
    A.put(B + f"/api/lists/{LP}/members", json={"user_id": uid[u], "role": "edit"})
LB = Bo.post(B + "/api/lists", json={"name": "Bob's shoot", "org_id": ORG}).json()["id"]
# ---- equipment for the disposition, receipts (alice's and bob's) in the organisation's documents
check(A.post(B + O + "/equipment", json={"name": "Camera A", "category": "Camera"}).status_code in (200, 201), "setup: equipment")


def upload(s, name):
    r = s.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": (name, tiny_pdf("Receipt " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = A.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "keep": True})
    if not r.ok:  # the marking itself is not what this suite checks
        dbx("INSERT INTO rc_receipts(node_id, org_id, ws, category, set_by, set_at) VALUES(?,?,?,?,?,?)",
            (nid, ORG, f"o{ORG}", "Software", ALICE, "2026-10-01T00:00:00Z"), write=True)
    return nid


RA, RB = upload(A, "alice-receipt.pdf"), upload(Bo, "bob-receipt.pdf")
check(len(dbx("SELECT node_id FROM rc_receipts WHERE node_id IN (?,?)", (RA, RB))) == 2, "setup: both files are receipts")


def kinds(s):
    r = s.get(B + f"/api/contacts/{CT1}/history")
    return {(x["kind"], x["id"]) for x in r.json().get("items", [])} if r.ok else {("error", r.status_code)}


def dispo_eq(s):
    j = s.get(B + "/api/team/dispo", params={"org": ORG}).json()
    return [e["name"] for e in j.get("resources", {}).get("equipment", [])]


def office_docs(s):
    return s.get(B + f"/api/lists/{LP}/office-docs").json()


def status(s, path):
    return s.get(B + path).status_code


# what everybody sees before any group exists
before = {}
for name, s in (("bob", Bo), ("carl", Ca), ("dave", Da)):
    before[name] = (kinds(s), office_docs(s), dispo_eq(s), status(s, f"/api/docs/{RA}/file"), status(s, f"/api/docs/{RB}/file"))
check(("offer", OFF) in before["bob"][0], f"before: a member sees the client's quotation in the contact history {before['bob'][0]}")
check(before["bob"][1].get("office") is True and [d["id"] for d in before["bob"][1].get("docs", [])] == [OFF], "before: the project's documents")
check(before["bob"][2] == ["Camera A"], f"before: the disposition lists the equipment {before['bob'][2]}")
check(status(Bo, f"/api/lists/{LB}/signoffs") == 200, "before: bob reads the acceptance links of his project")

# ---- groups: bob = Staff, dave = an own group without any area, carl stays without a group
r = A.put(B + f"{R}/people/{uid['bob']}", json={"groups": ["tpl:staff"]})
check(r.ok, "alice puts bob into Staff " + r.text[:200])
r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Nothing yet"})
check(r.status_code == 201, "an own group " + r.text[:200])
GN = r.json().get("id")
check(A.put(B + f"{R}/people/{uid['dave']}", json={"groups": [f"g:{GN}"]}).ok, "alice puts dave into the own group")

k = kinds(Bo)
check(("offer", OFF) not in k and not any(x[0] in ("offer", "invoice", "credit") for x in k), f"staff: no quotations / invoices in the contact history {k}")
j = office_docs(Bo)
check(j.get("office") is False and j.get("docs") == [], f"staff: the project's office documents are hidden {j}")
check(status(Bo, f"/api/lists/{LB}/signoffs") == 403, "staff: the acceptance links of an organisation project 403")
check(status(Bo, f"/api/docs/{RA}/file") in (403, 404), "staff: another person's receipt file is refused")
check(status(Bo, f"/api/docs/{RB}/file") == 200, "staff: the own receipt file 200")
# 2.187.0 (#2476, review): the listing follows the same rule as the single file
def doc_ids(s):
    r = s.get(B + "/api/docs", params={"ws": f"org:{ORG}"})
    return {x.get("id") for x in (r.json().get("items") or r.json().get("docs") or [])} if r.ok else set()
lb, la = doc_ids(Bo), doc_ids(A)
check(RB in la and RA in la and RA not in lb, f"staff: the documents list leaves out another person's receipt {sorted(lb)} / {sorted(la)}")
check(dispo_eq(Bo) == ["Camera A"], "staff reads the equipment: the disposition still lists it")
check(dispo_eq(Da) == [], "own group without equipment: no equipment in the disposition")
check(status(Da, f"/api/docs/{RA}/file") in (403, 404) and status(Da, f"/api/docs/{RB}/file") in (403, 404), "own group without receipts: no receipt file")
check(office_docs(Da).get("office") is False, "own group without quotes & invoices: no project documents")
after = (kinds(Ca), office_docs(Ca), dispo_eq(Ca), status(Ca, f"/api/docs/{RA}/file"), status(Ca, f"/api/docs/{RB}/file"))
check(after == before["carl"], f"a member without a group: exactly as before {after} / {before['carl']}")
check(status(A, f"/api/docs/{RB}/file") == 200 and ("offer", OFF) in kinds(A), "the organisation admin as before")

# ---------------------------------------------------------------- agents
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.ok, "setup: alice's agent " + r.text[:200])
AG, AH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}


def ag(m, path, h=None, **kw):
    return requests.request(m, B + V + path, headers=h or AH, **kw)


def people(s=A):
    return {p["id"]: p for p in s.get(B + R).json().get("people", [])}


check(ag("GET", "").status_code == 403, "agent without a group, switch off: no office access")
check(ag("GET", "/docs").status_code == 403, "agent without a group, switch off: no documents")
check(people()[AG]["groups"] == ["tpl:none"], f"the rights page: a new agent has no office access {people().get(AG)}")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "the old switch on")
check(ag("GET", "").ok and ag("GET", "/docs").ok, "agent with the old switch and no group: the previous access")
check(people()[AG]["groups"] == ["tpl:legacy"], f"the rights page shows it as previous access {people().get(AG)}")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:orgadmin"]}).status_code == 400, "an agent never manages office rights")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "the agent into Project management")
body = {"client_id": CL, "title": "Image film 2", "items": [{"text": "Shoot", "qty": 1, "unit": "flat", "price": 900}]}
r = ag("POST", "/offers", json=body)
check(r.status_code == 201, f"Project management: the agent drafts a quotation ({r.status_code} {r.text[:200]})")
r = ag("GET", "/payment-suggestions")
check(r.status_code == 403, f"Project management: payment suggestions 403 (Bank none) ({r.status_code} {r.text[:200]})")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:none"]}).ok, "the agent into No office access")
check(ag("GET", "").status_code == 403 and ag("GET", "/docs").status_code == 403, "No office access: 403 also with the old switch on")

# an agent of a person in Staff never gets more than that person
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.ok, "setup: bob's agent " + r.text[:200])
BAG, BH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
check(A.put(B + f"{R}/people/{BAG}", json={"groups": ["tpl:projects"]}).ok, "bob's agent into Project management")
r = ag("POST", "/offers", h=BH, json=body)
check(r.status_code == 403, f"the agent acts for bob (Staff): no quotation draft ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- export, import, move of a personal office
r = in_app("import app\nfrom kalmido.admin.orgexport import OX_AREAS\nfrom kalmido.admin.orgimport import oi_specs\n"
           "from kalmido.office.pbtransfer import PBT_KEEP\n"
           "ex = {x[1] for x in OX_AREAS if isinstance(x, tuple) and len(x) > 1}\nim = {s.table for s in oi_specs()}\n"
           "print(sorted(t for t in ('office_rgroups', 'office_rgroup_members', 'office_rights_log') if t in ex), "
           "sorted(t for t in ('office_rgroups', 'office_rgroup_members', 'office_rights_log') if t in im), "
           "sorted(t for t in ('office_rgroups', 'office_rgroup_members') if t in PBT_KEEP))")
out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
check(out == "['office_rgroup_members', 'office_rgroups', 'office_rights_log'] ['office_rgroups', 'office_rights_log'] "
             "['office_rgroup_members', 'office_rgroups']", f"export: the three tables; import: groups + log; move: groups stay ({out})")

# ---------------------------------------------------------------- freelancer-matrix: office
FID, Fr = freelancer(B, A)
check(Fr.put(B + O + "/settings", json={"company_fields": {**COMPANY, "name": "Frida Photo"}, "lang": "en", "currency": "EUR",
                                        "agents_read": 1}).ok, "freelancer: her office")
FCL = Fr.post(B + "/api/clients", json={"name": "Frida's Client", "country": "DE", "org_id": None}).json().get("id")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "office"]})
check(r.ok, "freelancer: her agent " + r.text[:200])
FAG, FH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
check(ag("GET", "", h=FH).status_code == 403, "freelancer: her new agent has no office access")
check(people(Fr).get(FAG, {}).get("groups") == ["tpl:none"], f"freelancer: the rights page lists her agent {people(Fr)}")
check(Fr.put(B + f"{R}/people/{FAG}", json={"groups": ["tpl:projects"]}).ok, "freelancer: her agent into Project management")
r = ag("POST", "/offers", h=FH, json={**body, "client_id": FCL})
check(r.status_code == 201, f"freelancer: her agent drafts a quotation ({r.status_code} {r.text[:200]})")
check(ag("GET", "/payment-suggestions", h=FH).status_code == 403, "freelancer: payment suggestions 403 (Bank none)")
check(Fr.get(B + O + "/settings").ok and Fr.get(B + f"{R}").json().get("mine", {}).get("levels", {}).get("bank") == "manage",
      "freelancer: she herself keeps her whole office")

print(f"p2187_c: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
