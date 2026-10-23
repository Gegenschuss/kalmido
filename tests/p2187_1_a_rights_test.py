#!/usr/bin/env python3
"""2.187.1 part A (#2735): follow-ups of the office rights review. Invented names only.
 - clients' invoicing fields (VAT ID, customer number, buyer reference, invoice e-mail, payment terms, Peppol ID) belong to
   "Quotes & invoices": Staff (offers none) gets them left out and cannot set them (create / update ignore them), an own group
   with offers "view" reads them but does not change them; a member without a group and the admin as before; the address stays
 - sets / freelancer roles / crew belong to the equipment area: Staff reads sets (equipment view) but does not add one, an own
   group with only offers "view" gets 403, "Project management" adds crew (equipment edit); undo of a set = equipment
 - an agent with a share on an organisation's receipt but without the area receipts: 404 and missing from the listings (top,
   a shared folder's children); with
   a group that has receipts: readable; a shared file that is no receipt stays readable
 - organisation import: the rights log's group refs map to the target's groups, a group that did not come along = g:0
 - a person without an organisation (freelancer-matrix: clients): her private client shows the invoicing fields
usage: p2187_1_a_rights_test.py <datadir>"""
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
from kt import FAILS, OKS, check, sess  # 2.206.0 (#2762): shared helpers (tests/kt.py)
O, R = "/api/office", "/api/office/rights"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts,dispo"
GATED = ("vat_id", "customer_no", "buyer_reference", "email_invoice", "payment_terms_days", "peppol_id")


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


if not os.environ.get("P21871A_NOSTART"):
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
for u in ("bob", "carl", "dave", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as member " + r.text[:200])
    uid[u] = r.json().get("id")
Bo, Ca, Da, Er = sess("bob"), sess("carl"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
check(A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR", "agents_read": 1}).ok, "setup: office settings")

BILL = {"street": "Kundenweg 2", "zip": "10115", "city": "Berlin", "country": "DE", "vat_id": "DE123456789", "customer_no": "K-100",
        "buyer_reference": "04011000-12345-67", "email_invoice": "invoices@client.example", "payment_terms_days": 14}
r = A.post(B + "/api/clients", json={"name": "Example Client AG", "org_id": ORG, **BILL})
check(r.status_code == 201, "setup: the organisation's client " + r.text[:200])
CL = r.json().get("id")

# ---- groups: bob = Staff, dave = own group with only offers "view", erin = Project management, carl without a group
check(A.put(B + f"{R}/people/{uid['bob']}", json={"groups": ["tpl:staff"]}).ok, "alice puts bob into Staff")
r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Quotes read only"})
check(r.status_code == 201, "an own group " + r.text[:200])
GN = r.json().get("id")
check(A.patch(B + f"{R}/groups/{GN}", json={"levels": {"offers": "view"}}).ok, "the own group reads quotes & invoices")
check(A.put(B + f"{R}/people/{uid['dave']}", json={"groups": [f"g:{GN}"]}).ok, "alice puts dave into the own group")
check(A.put(B + f"{R}/people/{uid['erin']}", json={"groups": ["tpl:projects"]}).ok, "alice puts erin into Project management")


# ---------------------------------------------------------------- 1. clients' invoicing fields
def bill(s, cid=CL):
    r = s.get(B + f"/api/clients/{cid}")
    return r.json() if r.ok else {"error": r.status_code}


j = bill(A)
check(j.get("billing", {}).get("vat_id") == "DE123456789" and j.get("bill_edit") is True, f"admin: the invoicing fields as before {j.get('billing')}")
j = bill(Ca)
check(j.get("billing", {}).get("customer_no") == "K-100" and j.get("bill_edit") is True, f"member without a group: as before {j.get('billing')}")
j = bill(Bo)
b = j.get("billing", {})
check(not any(k in b for k in GATED) and b.get("city") == "Berlin" and j.get("bill_edit") is False,
      f"staff: the invoicing fields are left out, the address stays {b}")
r = Bo.get(B + "/api/clients")
row = next((x for x in r.json().get("clients", []) if x["id"] == CL), {}) if r.ok else {}
check(row and "vat_id" not in row.get("billing", {}), f"staff: the client list leaves them out too {row.get('billing')}")
r = Bo.patch(B + f"/api/clients/{CL}", json={"vat_id": "DE000000000", "payment_terms_days": 60, "note": "Called on Monday"})
check(r.ok, f"staff: saving the client works ({r.status_code} {r.text[:200]})")
b = bill(A).get("billing", {})
check(b.get("vat_id") == "DE123456789" and b.get("payment_terms_days") == 14 and bill(A).get("note") == "Called on Monday",
      f"staff: the invoicing fields are ignored, the note is saved {b}")
r = Bo.post(B + "/api/clients", json={"name": "Bob's Client", "org_id": ORG, "vat_id": "DE111111111", "city": "Köln"})
check(r.status_code == 201, "staff: a new client " + r.text[:200])
b = bill(A, r.json().get("id")).get("billing", {})
check(b.get("vat_id") == "" and b.get("city") == "Köln", f"staff: a new client without the invoicing fields {b}")
j = bill(Da)
check(j.get("billing", {}).get("vat_id") == "DE123456789" and j.get("bill_edit") is False, f"offers view: reads them, cannot change {j.get('billing')}")
Da.patch(B + f"/api/clients/{CL}", json={"customer_no": "K-999"})
check(bill(A).get("billing", {}).get("customer_no") == "K-100", "offers view: the change is ignored")
r = Ca.patch(B + f"/api/clients/{CL}", json={"customer_no": "K-101"})
check(r.ok and bill(A).get("billing", {}).get("customer_no") == "K-101", "member without a group: changes them as before")

# ---------------------------------------------------------------- 7. sets / roles / crew = equipment
r = in_app("import app\nfrom kalmido.office.rights import ofr_area_of, TEMPLATES\n"
           "print([ofr_area_of('/api/office/' + p) for p in ('sets', 'sets/3', 'crew', 'roles/2', 'undo/sets/3', 'undo/doc/3', 'undo/client/1', 'clients')],"
           " TEMPLATES['projects'][2]['equipment'], TEMPLATES['staff'][2]['equipment'], TEMPLATES['projects'][2]['offers'])")
out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
check(out == "['equipment', 'equipment', 'equipment', 'equipment', 'equipment', 'offers', 'offers', 'offers'] edit view edit",
      f"areas: sets / crew / roles = equipment, undo follows the row ({out})")
r = A.post(B + O + "/sets", json={"name": "Interview kit", "discount_pct": 10})
check(r.status_code in (200, 201), "setup: a set " + r.text[:200])
SET = r.json().get("id")
check(Bo.get(B + O + "/sets").ok, "staff (equipment view): reads the sets")
check(Bo.post(B + O + "/sets", json={"name": "Bob's kit"}).status_code == 403, "staff: adds no set")
check(Da.get(B + O + "/sets").status_code == 403 and Da.get(B + O + "/crew").status_code == 403, "only offers view: no sets / crew any more")
r = Er.post(B + O + "/crew", json={"name_de": "Kamera", "rate_day": 500})
check(r.status_code in (200, 201), f"Project management (equipment edit): adds crew ({r.status_code} {r.text[:200]})")
r = Er.patch(B + O + f"/sets/{SET}", json={"discount_pct": 12})
check(r.ok, f"Project management: changes a set ({r.status_code} {r.text[:200]})")
r = Er.get(B + O + "/roles")
check(r.ok and all("cost_day" not in x for x in r.json().get("items", [])), "Project management: roles without purchase prices (manage only)")

# ---------------------------------------------------------------- 5. agent + share on a receipt
def upload(s, name, receipt=True):
    r = s.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": (name, tiny_pdf("Receipt " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    if receipt and not A.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "keep": True}).ok:
        dbx("INSERT INTO rc_receipts(node_id, org_id, ws, category, set_by, set_at) VALUES(?,?,?,?,?,?)",
            (nid, ORG, f"o{ORG}", "Software", ALICE, "2026-10-01T00:00:00Z"), write=True)
    return nid


RA, NA = upload(A, "alice-receipt.pdf"), upload(A, "alice-notes.pdf", receipt=False)
check(len(dbx("SELECT node_id FROM rc_receipts WHERE node_id IN (?,?)", (RA, NA))) == 1, "setup: one receipt, one plain file")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "filebot", "display_name": "File Bot", "scopes": ["read", "office", "files:read"], "org_id": ORG})
check(r.ok, "setup: alice's agent " + r.text[:200])
AG, AH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
for nid in (RA, NA):
    r = A.post(B + f"/api/files/nodes/{nid}/shares", json={"agent_id": AG, "role": "view"})
    check(r.ok, f"alice shares {nid} with the agent " + r.text[:200])


def agst(nid):
    return requests.get(B + f"/api/v1/files/{nid}", headers=AH).status_code


def ag_list(parent=None):
    r = requests.get(B + "/api/v1/files", headers=AH, params={"parent_id": parent} if parent else None)
    return {x.get("id") for x in r.json().get("data", [])} if r.ok else {"error", r.status_code}


check(agst(NA) == 200, "agent without a group: the shared plain file stays readable")
check(agst(RA) == 404, f"agent without a group: the shared receipt is refused ({agst(RA)})")
check(RA not in ag_list() and NA in ag_list(), f"agent without a group: the listing leaves the receipt out {ag_list()}")
FOLDER = dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (RA,))[0][0]
check(dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (NA,))[0][0] == FOLDER, "setup: both files in the same folder")
r = A.post(B + f"/api/files/nodes/{FOLDER}/shares", json={"agent_id": AG, "role": "view"})
check(r.ok, "alice shares the folder with the agent " + r.text[:200])
lf = ag_list(FOLDER)
check(RA not in lf and NA in lf, f"agent without a group: the folder's listing leaves the receipt out {lf}")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "the agent into Project management (receipts edit)")
check(agst(RA) == 200 and RA in ag_list(FOLDER), f"agent with the area receipts: the shared receipt is readable ({agst(RA)})")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:none"]}).ok, "the agent into No office access")
check(agst(RA) == 404 and agst(NA) == 200, "No office access: receipt refused, plain file readable")

# ---------------------------------------------------------------- 6. organisation import: the rights log's group refs
r = in_app("import app, json\nfrom kalmido.admin.oi_office import _p_rights_log\n"
           "class Run:\n    def m(self, kind, v):\n        return {5: 41}.get(v) if kind == 'office_rgroups' else None\n"
           "class Ctx:\n    who = staticmethod(lambda v: {7: 70}.get(v))\n"
           "a = _p_rights_log(None, Run(), {}, {'group_ref': '', 'before': json.dumps(['g:5', 'g:6', 'tpl:staff']), 'after': json.dumps(['g:5'])}, Ctx())\n"
           "b = _p_rights_log(None, Run(), {}, {'group_ref': 'g:6', 'before': json.dumps({'name': 'X', 'members': [7, 8]}), 'after': ''}, Ctx())\n"
           "print(json.loads(a['before']), json.loads(a['after']), b['group_ref'], json.loads(b['before'])['members'], repr(b['after']))")
out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
check(out == "['g:41', 'g:0', 'tpl:staff'] ['g:41'] g:0 [70] ''", f"import: the log names the target's groups ({out})")

# ---------------------------------------------------------------- freelancer-matrix: clients
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/clients", json={"name": "Frida's Client", "org_id": None, "vat_id": "DE222222222", "payment_terms_days": 30})
check(r.status_code == 201, "freelancer: her private client " + r.text[:200])
j = bill(Fr, r.json().get("id"))
check(j.get("billing", {}).get("vat_id") == "DE222222222" and j.get("billing", {}).get("payment_terms_days") == 30 and j.get("bill_edit") is True,
      f"freelancer: her own client shows the invoicing fields {j.get('billing')}")

print(f"p2187_1_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
