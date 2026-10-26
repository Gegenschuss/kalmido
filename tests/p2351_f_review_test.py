#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 F: the findings of the 2.351.0 review -- invented people, companies and figures only, the files are made here.
 (m1) #2823: the accounting role reads no letters: the Correspondence tree 403 and no base role on a letter (its PDF over the
      file store only through a share with exactly that person)
 (m2) #3246: an agent WITH an office group for quotations and a project restriction: the node of a quotation of another
      project in a folder shared with it is 404 (the base role no longer passes what a folder never opens)
 (m3) #2823: a receipt in the trash and an archived document / letter open through no folder; restored = back
 (m4) #2823: a save over the folder way keeps the version check (expect_updated_at: 409) and the 409 answer is cut down
 (m5) #2823: an outside folder's path stops at the first folder above it the person does not see
 (n2) #2749: hard-deleting contracts and contract PDFs after the trash period drops their folder nodes
 (n5) #2823: reading a document / letter through a folder is in the office log
 (n8) the passing-on rule (filing needs edit from the area itself) for documents and letters; a guest and a read-only member
      as folder recipients (guest nothing, read-only at most view)
 (f)  a person without an organisation: her archived document opens through no folder, her agent's share
usage: p2351_f_review_test.py <datadir>   (P2351F_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)
freelancer-matrix: office  tenant-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"

if not os.environ.get("P2351F_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_PURGE_TRASH=1")  # (n2): the trash run deletes
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
U = {}
for name, role in (("bob", "member"), ("carl", "accounting"), ("gina", "guest"), ("rita", "readonly")):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    U[name] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{name}@example.com", "role": role}).ok
Bo, Ca, Gi, Ri = sess("bob"), sess("carl"), sess("gina"), sess("rita")
for s in (A, Bo, Ca, Gi, Ri):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": SP})
check(A.put(B + f"{O}/rights/people/{U['bob']}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff")
COMPANY = {"name": "Studio Example GmbH", "street": "Harbour Street 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hello@example.com", "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Example Bank"}
check(A.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14, "agents_read": 1}).ok,
      "setup: office settings, agents may read office data")
CLI = A.post(B + "/api/clients", json={"name": "Example Client AG", "email": "client@example.com", "org_id": ORG}).json()["id"]


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(q, args)
        if write:
            c.commit()
            return None
        return cur.fetchall()
    finally:
        c.close()


def folder(s, name, space=None, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def file_in(s, kind, rid, parent):
    r = s.post(B + "/api/files/refs", json={"ref_kind": kind, "ref_id": rid, "parent_id": parent})
    return r.json()["node"]["id"] if r.ok and r.json().get("node") else -r.status_code


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def role(s, kind, rid):
    r = s.get(B + f"/api/files/refs/{kind}/{rid}")
    return r.json().get("role") if r.ok else None


def content(s, nid):
    return s.get(B + f"/api/files/nodes/{nid}/content").status_code


def new_doc(s, title="Edit day", lid=None):
    r = s.post(B + O + "/docs", json={"kind": "offer", "items": [{"title": title, "qty": 1, "rate": 800}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if lid:
        sql("UPDATE office_docs SET list_id=? WHERE id=?", (lid, did), write=True)
    return did


def new_gd(s, title, client):
    r = s.post(B + O + "/gen-docs", json={"client_id": client, "title": title, "body": "An invented text."})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def new_lt(s, subject, client):
    r = s.post(B + O + "/letters", json={"client_id": client, "subject": subject, "body": "An invented text."})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


# ---------------------------------------------------------------- (m1) the accounting role and the letters
LT = new_lt(A, "Confidential talk", CLI)
LF = folder(A, "Talks", SP)
NLT = file_in(A, "office_letter", LT, LF)
check(NLT > 0, f"(m1) setup: the letter filed ({NLT})")
r = Ca.get(B + f"{O}/letters")
check(r.status_code == 403, f"(m1) setup: the letters list is closed to carl (accounting) ({r.status_code})")
r = Ca.get(B + f"{O}/letters/tree")
check(r.status_code == 403, f"(m1) the Correspondence tree is closed to carl as well ({r.status_code} {r.text[:120]})")
check(role(Ca, "office_letter", LT) is None and content(Ca, NLT) == 404, "(m1) no base role: carl reads no letter's PDF without a share")
check(A.get(B + f"{O}/letters/tree").ok and role(A, "office_letter", LT) == "edit", "(m1) the admin as before")
S = share(A, LF, user_id=U["carl"], role="view")
check(role(Ca, "office_letter", LT) == "view" and content(Ca, NLT) == 200, "(m1) a share with carl: he reads it through the folder")
A.delete(B + f"/api/files/shares/{S}")
r = Ca.get(B + f"{O}/gen-docs/tree")
check(r.ok, f"(m1) the Documents tree stays readable for carl (only letters are not bookkeeping) ({r.status_code})")

# ---------------------------------------------------------------- (m2) an agent with an office group and a project restriction
L1 = A.post(B + "/api/lists", json={"name": "Project One", "org_id": ORG}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Project Two", "org_id": ORG}).json()["id"]
D1, D2 = new_doc(A, "Day one", L1), new_doc(A, "Day two", L2)
BOX = folder(A, "Agent box", SP)
N1, N2 = file_in(A, "office_doc", D1, BOX), file_in(A, "office_doc", D2, BOX)
r = A.post(B + "/api/my/agents", json={"username": "groupbot", "display_name": "Group Bot", "scopes": ["read", "files:read", "office"], "org_id": ORG})
check(r.status_code in (200, 201), "(m2) setup: the organisation's agent " + r.text[:160])
AG, AH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok and A.put(B + f"{O}/rights/people/{AG}", json={"groups": ["tpl:projects"]}).ok,
      "(m2) setup: its office switch and the office group Project management (quotations)")
share(A, BOX, agent_id=AG, role="view")
check(requests.get(V + f"/files/{N1}", headers=AH).status_code == 200 and requests.get(V + f"/files/{N2}", headers=AH).status_code == 200,
      "(m2) without a restriction: both nodes")
sql("UPDATE agents SET list_ids=? WHERE user_id=?", (str(L1), AG), write=True)
r2 = requests.get(V + f"/files/{N2}", headers=AH)
check(r2.status_code == 404, f"(m2) restricted to project one: the node of project two is 404 although the group gives quotations ({r2.status_code} {r2.text[:120]})")
check(requests.get(V + f"/files/{N1}", headers=AH).status_code == 200, "(m2) project one: as before")
r2 = requests.get(B + f"/api/fsref/office_doc/{D2}", headers=AH)
check(r2.status_code != 200, f"(m2) the office's folder way neither ({r2.status_code})")

# ---------------------------------------------------------------- (m3) trash and archive
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("receipt-m3.pdf", tiny_pdf("Receipt m3"), "application/pdf")})
check(r.status_code == 201, "(m3) setup: alice's private receipt " + r.text[:160])
RC = r.json()["ids"][0]
check(A.patch(B + f"/api/docs/{RC}", json={"amount": "19.00", "date": time.strftime("%Y-%m-%d")}).ok
      and A.put(B + f"/api/docs/{RC}/receipt", json={"category": "Material"}).ok, "(m3) setup: marked as a receipt")
PF = folder(A, "Private receipts", "private")
NRC = file_in(A, "office_receipt", RC, PF)
check(NRC > 0, f"(m3) setup: filed ({NRC})")
share(A, PF, user_id=U["bob"], role="view")
check(content(Bo, NRC) == 200, "(m3) bob reads the receipt through the shared folder")
r = A.delete(B + f"/api/files/nodes/{RC}")
check(r.ok, "(m3) setup: alice puts the receipt into the trash " + r.text[:160])
check(content(Bo, NRC) == 404 and role(Bo, "office_receipt", RC) is None, f"(m3) in the trash: nothing through the folder ({content(Bo, NRC)})")
A.patch(B + "/api/settings", json={"workspace": SP})
GD = new_gd(A, "Usage agreement", CLI)
GF = folder(A, "Agreements", SP)
NGD = file_in(A, "office_gendoc", GD, GF)
share(A, GF, user_id=U["bob"], role="view")
check(content(Bo, NGD) == 200, "(m3) bob reads the document through the folder")
check(A.delete(B + f"{O}/gen-docs/{GD}").ok and content(Bo, NGD) == 404 and role(Bo, "office_gendoc", GD) is None,
      f"(m3) archived (deleted with undo): nothing through the folder ({content(Bo, NGD)})")
check(A.post(B + f"{O}/gen-docs/{GD}/restore").ok and content(Bo, NGD) == 200, "(m3) restored: back")
LT2 = new_lt(A, "Second talk", CLI)
NLT2 = file_in(A, "office_letter", LT2, GF)
check(content(Bo, NLT2) == 200 and A.delete(B + f"{O}/letters/{LT2}").ok and content(Bo, NLT2) == 404,
      "(m3) an archived letter: nothing through the folder")

# ---------------------------------------------------------------- (n5) the office log
logs = A.get(B + f"{O}/log", params={"limit": 200}).json().get("log") or []
check(any(x.get("action") == "open" and x.get("target") == "gen_doc" and (x.get("detail") or {}).get("gen_doc") == GD and x.get("user_id") == U["bob"] for x in logs)
      and any(x.get("action") == "open" and x.get("target") == "letter" and (x.get("detail") or {}).get("letter") == LT2 for x in logs),
      "(n5) reading a document / letter through a folder is in the office log")

# ---------------------------------------------------------------- (m4) the folder way keeps the version check
DQ = new_doc(A, "Shared draft")
QF = folder(A, "Drafts", SP)
check(file_in(A, "office_doc", DQ, QF) > 0, "(m4) setup: a draft filed")
share(A, QF, user_id=U["bob"], role="edit")
j = Bo.get(B + f"/api/fsref/office_doc/{DQ}").json()
v0 = j.get("updated_at")
check(j.get("folder_role") == "edit" and v0, f"(m4) bob edits the draft through the folder ({j.get('folder_role')})")
r = Bo.patch(B + f"/api/fsref/office_doc/{DQ}", json={"project_title": "First", "expect_updated_at": v0})
check(r.ok and r.json().get("updated_at") and r.json().get("updated_at") != v0, f"(m4) a save with the current version ({r.status_code})")
r = Bo.patch(B + f"/api/fsref/office_doc/{DQ}", json={"project_title": "Stale", "expect_updated_at": v0})
d = (r.json() or {}).get("doc") or {} if r.status_code == 409 else {}
check(r.status_code == 409 and d.get("project_title") == "First", f"(m4) a save on an old version: 409 with the current state ({r.status_code} {r.text[:160]})")
check(d and not ({"client_id", "contract_id", "payments", "client_contacts"} & set(d)), f"(m4) the 409 answer is cut down like the folder way ({sorted(d)[:12]})")
its = Bo.get(B + f"/api/fsref/office_doc/{DQ}").json().get("items") or []
r = Bo.put(B + f"/api/fsref/office_doc/{DQ}/items", json={"items": its + [{"title": "Extra", "qty": 1, "rate": 10}], "expect_updated_at": v0})
check(r.status_code == 409, f"(m4) positions on an old version: 409 ({r.status_code})")

# ---------------------------------------------------------------- (m5) the path of an outside folder
P1 = folder(A, "Personnel", SP)
P2 = folder(A, "Notices 2026", parent=P1)
P3 = folder(A, "Example Person", parent=P2)
QP = new_doc(A, "Quote in a deep folder")
check(file_in(A, "office_doc", QP, P3) > 0, "(m5) setup: a quotation in Personnel / Notices 2026 / Example Person")
share(A, P3, user_id=U["carl"], role="view")
t = Ca.get(B + f"{O}/docs/tree").json()
f = next((x for x in t.get("folders", []) if x["id"] == P3), None)
check(f and f["outside"] and f["path"] == "Example Person", f"(m5) carl sees only the folder shared with him, not the names above it ({f})")
f = next((x for x in A.get(B + f"{O}/docs/tree").json().get("folders", []) if x["id"] == P3), None)
check(f and f["path"] == "Personnel / Notices 2026 / Example Person", f"(m5) alice sees the whole path ({f})")

# ---------------------------------------------------------------- (n8) passing on, guest, read-only
BF = folder(Bo, "Bob's own", SP)
S = share(A, GF, user_id=U["bob"], role="edit")
check(role(Bo, "office_gendoc", GD) in ("view", "edit") and file_in(Bo, "office_gendoc", GD, BF) in (-403, -404),
      "(n8) a folder share does not let bob file the document into an own folder (passing on needs edit from the area)")
LT3 = new_lt(A, "Third talk", CLI)
check(file_in(A, "office_letter", LT3, GF) > 0 and file_in(Bo, "office_letter", LT3, BF) in (-403, -404), "(n8) the same for a letter")
A.delete(B + f"/api/files/shares/{S}")
share(A, GF, user_id=U["gina"], role="edit")
check(role(Gi, "office_gendoc", GD) is None and content(Gi, NGD) in (403, 404), "(n8) a guest gets nothing through a share")
share(A, GF, user_id=U["rita"], role="edit")
check(role(Ri, "office_gendoc", GD) == "view" and content(Ri, NGD) == 200, f"(n8) a read-only member: view at most ({role(Ri, 'office_gendoc', GD)})")

# ---------------------------------------------------------------- (n2) hard delete after the trash period
r = A.post(B + O + "/agreements", json={"kind": "insurance", "name": "Old insurance", "task": 0})
check(r.status_code == 201, "(n2) setup: a contract " + r.text[:160])
AGR = r.json()["id"]
check(file_in(A, "office_agreement", AGR, GF) > 0 and A.delete(B + f"{O}/agreements/{AGR}").ok, "(n2) setup: filed, then deleted")
sql("UPDATE office_agreements SET updated_at=? WHERE id=?", ("2000-01-01T00:00:00Z", AGR), write=True)
check(A.get(B + O + "/agreements").ok, "(n2) the contracts list runs the trash")
left = sql("SELECT COUNT(*) FROM fs_nodes WHERE kind='ref' AND ref_kind='office_agreement' AND ref_id=?", (AGR,))[0][0]
check(not sql("SELECT 1 FROM office_agreements WHERE id=?", (AGR,)) and left == 0, f"(n2) the contract and its folder node are gone ({left})")
r = A.post(B + O + "/contracts", json={"name": "Frame 2026", "client_id": CLI})
CT = r.json()["id"]
r = A.post(B + O + f"/contracts/{CT}/files", files={"file": ("frame.pdf", tiny_pdf("Frame contract"), "application/pdf")})
check(r.status_code == 201, "(n2) setup: a framework contract's PDF " + r.text[:160])
CF = r.json()["id"]
check(file_in(A, "contract_file", CF, GF) > 0 and A.delete(B + O + f"/contracts/{CT}/files/{CF}").ok, "(n2) setup: filed, then deleted")
sql("UPDATE office_contract_files SET deleted_at=? WHERE id=?", ("2000-01-01T00:00:00Z", CF), write=True)
check(A.get(B + O + "/contracts").ok, "(n2) the framework contracts list runs the trash")
left = sql("SELECT COUNT(*) FROM fs_nodes WHERE kind='ref' AND ref_kind='contract_file' AND ref_id=?", (CF,))[0][0]
check(not sql("SELECT 1 FROM office_contract_files WHERE id=?", (CF,)) and left == 0, f"(n2) the PDF and its folder node are gone ({left})")

# ---------------------------------------------------------------- (f) a person without an organisation
FID, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private", "features": FEAT})
Fr.get(B + O + "/settings")
check(Fr.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": COMPANY, "agents_read": 1}).ok, "(f) setup: her office")
FCL = Fr.post(B + "/api/clients", json={"name": "Freelance Client", "email": "fc@example.com"}).json()["id"]
FGD = new_gd(Fr, "Her agreement", FCL)
FF = folder(Fr, "Papers", "private")
FN = file_in(Fr, "office_gendoc", FGD, FF)
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read", "office"]})
check(r.ok, "(f) setup: her agent " + r.text[:160])
FA, FH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(Fr.patch(B + f"{O}/agents/{FA}", json={"office_drafts": True}).ok, "(f) setup: her agent's switch")
share(Fr, FF, agent_id=FA, role="view")
check(requests.get(V + f"/files/{FN}/content", headers=FH).status_code == 200, "(f) her agent reads the document through its share")
check(Fr.delete(B + f"{O}/gen-docs/{FGD}").ok and requests.get(V + f"/files/{FN}/content", headers=FH).status_code == 404,
      "(f) archived: her agent gets nothing through the folder")
check(Fr.get(B + f"/api/files/nodes/{FN}/content").status_code == 200, "(f) she herself still reads it (her office's own role)")

print(f"p2351_f_review: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
