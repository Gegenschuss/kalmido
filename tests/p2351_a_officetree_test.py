#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 A (#3312, #2823): the office's document areas as trees -- invented people, companies and figures only.
 (a) GET /api/office/docs/tree: no root before the first folder; "New folder" at the area makes the root ("Quotes &
     invoices") and the folder; a quotation in no folder is among the 20 newest, filed into the folder it lies under it
     (folder_id, its node) and leaves the newest; 25 quotations: 20 shown + more
 (b) a folder of the file store that holds a quotation (filed before 2.351 / elsewhere) stays in view: listed with its path
     (outside) and only the area's documents in it
 (c) the rights stay: bob (office group Staff, no quotations) gets 403 on the tree and cannot add a folder there; his own
     folder at the area is his until shared
 (d) generated documents / letters / receipts filed in folders (office_gendoc, office_letter, office_receipt): their trees,
     the folder gives bob read (the PDF over the file store's content route), withdrawn = nothing; a letter's node is named
     "Letter <date>" (its subject is encrypted at rest), the tree shows the subject; the receipts lock holds through a
     folder share (bob without the area Receipts never reads the receipt); a sent letter / finalised document stays when
     its folder goes into the trash
 (e) an agent: only through a share with exactly it AND the office's area -- the organisation's agent with the office
     switch but without a group for letters: hidden even with its share
 (f) a person without an organisation: her personal office's tree (private space), her folder, her quotation and
     document in it, her agent reads the document through its share
 (h) another organisation's admin: her own office's tree only, no folder in alpha's folders
 (g) folder rules (docs/store.py): a rule files only into a folder the uploading person may edit -- the accounting person's
     upload stays where it lands without the rule (rollback test: without the fix it went into the folder)
usage: p2351_a_officetree_test.py <datadir>
freelancer-matrix: office  tenant-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
USERS = {}
for name, role in (("bob", "member"), ("carl", "accounting")):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    USERS[name] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{name}@example.com", "role": role}).ok
BOB = USERS["bob"]
Bo, Ca = sess("bob"), sess("carl")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(A.put(B + f"{O}/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff")
CLI = A.post(B + "/api/clients", json={"name": "Example Client AG", "email": "client@example.com", "org_id": ORG}).json()["id"]


def tree(s, seg="docs"):
    r = s.get(B + f"{O}/{seg}/tree")
    return r.json() if r.ok else {"http": r.status_code}


def new_folder(s, name, seg="docs", parent=None):
    r = s.post(B + f"{O}/{seg}/tree/folders", json={"name": name, **({"parent_id": parent} if parent else {})})
    return r.json()["folder"]["id"] if r.status_code == 201 else None


def new_doc(s, title="Edit day"):
    r = s.post(B + O + "/docs", json={"kind": "offer", "items": [{"title": title, "qty": 1, "rate": 800}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def file_in(s, kind, rid, parent):
    r = s.post(B + "/api/files/refs", json={"ref_kind": kind, "ref_id": rid, "parent_id": parent})
    return r.status_code, (r.json().get("node") if r.ok else r.text[:200])


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doc_in(t, did):
    return next((d for d in t.get("docs", []) if d["id"] == did), None)


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
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, name, ws, text=None):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text or ("Doc " + name)), "application/pdf")})
    check(r.status_code == 201, f"upload {name}: {r.status_code} {r.text[:200]}")
    return r.json()["ids"][0] if r.status_code == 201 else None


# ---------------------------------------------------------------- (a) the quotations' tree
t = tree(A)
check(t.get("root") is None and t.get("folders") == [] and t.get("docs") == [] and t.get("space") == f"org:{ORG}" and t.get("can_add") is True,
      f"(a) an empty office: no root yet, nothing listed ({t})")
Q = new_doc(A)
t = tree(A)
check(doc_in(t, Q) and doc_in(t, Q)["folder_id"] is None and doc_in(t, Q)["open"] == f"office/offers/{Q}" and t["more"] is False,
      "(a) a quotation in no folder is among the newest")
F1 = new_folder(A, "Client Alpha")
t = tree(A)
f1 = next((f for f in t.get("folders", []) if f["id"] == F1), None)
check(F1 and t["root"] and f1 and f1["parent_id"] == t["root"] and f1["role"] == "owner" and not f1["outside"],
      f"(a) New folder at the area: the root is made, the folder lies below it ({t.get('folders')})")
root = A.get(B + f"/api/files/nodes/{t['root']}").json()
check(root.get("name") == "Quotes & invoices", f"(a) the root folder is named after the area ({root.get('name')})")
F2 = new_folder(A, "2026", parent=F1)
check(F2 and any(f["id"] == F2 and f["parent_id"] == F1 for f in tree(A)["folders"]), "(a) a subfolder")
check(file_in(A, "office_doc", Q, F2)[0] == 200, "(a) the quotation filed into the subfolder")
d = doc_in(tree(A), Q)
check(d and d["folder_id"] == F2 and d["fnode"], f"(a) it lies under its folder in the tree ({d})")
for i in range(25):
    new_doc(A, title=f"Day {i}")
t = tree(A)
loose = [x for x in t["docs"] if x["folder_id"] is None]
check(len(loose) == 20 and t["more"] is True and doc_in(t, Q)["folder_id"] == F2, f"(a) 26 quotations: 20 newest in no folder + more ({len(loose)}, {t['more']})")
check(loose[0]["id"] > loose[-1]["id"], "(a) newest first")

# ---------------------------------------------------------------- (b) a folder of the file store holding a quotation
OLD = A.post(B + "/api/files/folders", json={"name": "Old filing", "space": f"org:{ORG}"}).json()["id"]
OLD2 = A.post(B + "/api/files/folders", json={"name": "Inner", "parent_id": OLD}).json()["id"]
Q3 = new_doc(A, title="Old one")
check(file_in(A, "office_doc", Q3, OLD2)[0] == 200, "(b) setup: a quotation filed in the file store (as before 2.351)")
t = tree(A)
o = next((f for f in t["folders"] if f["id"] == OLD2), None)
check(o and o["outside"] and o["path"] == "Old filing / Inner" and doc_in(t, Q3)["folder_id"] == OLD2,
      f"(b) its folder stays in view with its path, the quotation under it ({o})")
check(not any(f["id"] == OLD for f in t["folders"]), "(b) a file store folder without the area's documents is not listed")

# ---------------------------------------------------------------- (c) the rights stay
check(tree(Bo).get("http") == 403 and Bo.post(B + f"{O}/docs/tree/folders", json={"name": "Bob's"}).status_code == 403,
      "(c) bob (Staff, no quotations): no tree, no folder at the area")
check(Ca.post(B + f"{O}/docs/tree/folders", json={"name": "Carl's"}).status_code == 403, "(c) the accounting person reads only (no folder)")

# ---------------------------------------------------------------- (d) documents, letters, receipts in folders
r = A.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": {
    "name": "Studio Example GmbH", "street": "Harbour Street 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hello@example.com",
    "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Example Bank"}, "payment_days": 14})
check(r.ok, "(d) setup: office settings " + r.text[:160])
r = A.post(B + O + "/gen-docs", json={"client_id": CLI, "title": "Usage agreement", "body": "We agree on an invented usage."})
check(r.status_code == 201, "(d) setup: a generated document " + r.text[:160])
GD = r.json().get("id")
GF = new_folder(A, "Agreements", seg="gen-docs")
st_, gn = file_in(A, "office_gendoc", GD, GF)
check(st_ == 200 and gn and gn["name"] == "Usage agreement", f"(d) the document filed into a folder of Documents ({st_} {gn})")
t = tree(A, "gen-docs")
check(doc_in(t, GD) and doc_in(t, GD)["folder_id"] == GF and doc_in(t, GD)["open"] == f"office/gendocs/{GD}", f"(d) the Documents tree lists it ({t.get('docs')})")
check(Bo.get(B + f"/api/files/nodes/{gn['id']}/content").status_code == 404, "(d) bob without a share: nothing")
S1 = share(A, GF, user_id=BOB, role="view")
r = Bo.get(B + f"/api/files/nodes/{gn['id']}/content")
check(r.ok and r.content[:5] == b"%PDF-", f"(d) share view: bob reads the document's PDF through the folder ({r.status_code})")
check(Bo.get(B + f"{O}/gen-docs/{GD}").status_code == 403, "(d) the office's own route stays closed to bob")
check(A.delete(B + f"/api/files/shares/{S1}").ok and Bo.get(B + f"/api/files/nodes/{gn['id']}/content").status_code == 404, "(d) withdrawn: nothing")
check(A.patch(B + f"{O}/gen-docs/{GD}", json={"title": "Usage agreement 2026"}).ok
      and A.get(B + f"/api/files/nodes/{gn['id']}").json().get("name") == "Usage agreement 2026", "(d) a new title renames its node")

r = A.post(B + O + "/letters", json={"client_id": CLI, "subject": "Confidential offer talk", "body": "Invented text."})
check(r.status_code == 201, "(d) setup: a letter " + r.text[:160])
LT = r.json().get("id")
LF = new_folder(A, "Talks", seg="letters")
st_, ln = file_in(A, "office_letter", LT, LF)
check(st_ == 200 and ln and ln["name"].startswith("Letter") and "Confidential" not in ln["name"], f"(d) the letter's node is named by its date ({ln})")
d = doc_in(tree(A, "letters"), LT)
check(d and d["title"] == "Confidential offer talk" and d["folder_id"] == LF, f"(d) the Correspondence tree shows the subject ({d})")
check(A.post(B + f"{O}/letters/{LT}/sent", json={"channel": "post"}).ok, "(d) setup: the letter sent")
r = A.delete(B + f"/api/files/nodes/{LF}")
kept = {k["id"]: k for k in (r.json().get("kept") or [])} if r.ok else {}
check(r.ok and ln["id"] in kept and "letter" in kept[ln["id"]]["reason"].lower(), f"(d) the sent letter stays when its folder goes into the trash ({r.text[:200]})")

RC = upload(A, "receipt-delta.pdf", f"org:{ORG}")
check(A.patch(B + f"/api/docs/{RC}", json={"amount": "119.00", "date": time.strftime("%Y-%m-%d")}).ok
      and A.put(B + f"/api/docs/{RC}/receipt", json={"category": "Material", "keep": True}).ok, "(d) setup: a receipt")
RF = new_folder(A, "Material", seg="receipts")
st_, rn = file_in(A, "office_receipt", RC, RF)
check(st_ == 200 and rn, f"(d) the receipt filed into a folder of Receipts ({st_} {rn})")
d = doc_in(tree(A, "receipts"), RC)
check(d and d["folder_id"] == RF and d["open"] == f"docs/{RC}", f"(d) the Receipts tree lists it ({d})")
share(A, RF, user_id=BOB, role="view")
kids = Bo.get(B + "/api/files", params={"parent": RF})
check(kids.ok and rn["id"] not in [x["id"] for x in kids.json().get("items", [])] and Bo.get(B + f"/api/files/nodes/{rn['id']}/content").status_code == 404,
      "(d) the receipts lock holds: bob (no area Receipts) neither sees nor reads the receipt through the shared folder")
check(A.get(B + f"/api/files/nodes/{rn['id']}/content").ok, "(d) alice reads it through the folder")

# ---------------------------------------------------------------- (e) an agent
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "files:read", "office"], "org_id": ORG})
check(r.ok, "(e) setup: the organisation's agent " + r.text[:160])
AG, AH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok and A.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "(e) setup: its office switch and the area's agents switch")
check(requests.get(B + f"/api/v1/files/{gn['id']}", headers=AH).status_code == 404, "(e) without a share: nothing")
share(A, GF, agent_id=AG, role="view")
check(requests.get(B + f"/api/v1/files/{gn['id']}", headers=AH).status_code == 404
      and requests.get(B + f"/api/v1/files/{gn['id']}/content", headers=AH).status_code == 404,
      "(e) with its share but no office group for Documents (the switch opens only the quotations): hidden")
check(requests.get(B + f"{O}/docs/tree", headers=AH).status_code in (401, 403), "(e) the tree is no agent route")

# ---------------------------------------------------------------- (f) a person without an organisation
FID, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private", "features": FEAT})
t = tree(Fr)
check(t.get("space") == "private" and t.get("root") is None and t.get("can_add") is True, f"(f) her personal office's tree ({t})")
FF = new_folder(Fr, "Customers")
FQ = new_doc(Fr)
check(FF and file_in(Fr, "office_doc", FQ, FF)[0] == 200 and doc_in(tree(Fr), FQ)["folder_id"] == FF, "(f) her folder at the area, her quotation in it")
froot = Fr.get(B + f"/api/files/nodes/{tree(Fr)['root']}").json()
check(froot.get("org_id") is None and froot.get("name") == "Quotes & invoices", f"(f) the root lies in her private tree ({froot})")
FCL = Fr.post(B + "/api/clients", json={"name": "Freelance Client", "email": "fc@example.com"}).json()["id"]
r = Fr.post(B + O + "/gen-docs", json={"client_id": FCL, "title": "Her agreement", "body": "Invented."})
check(r.status_code == 201, "(f) setup: her document " + r.text[:160])
FGD = r.json().get("id")
FGF = new_folder(Fr, "Papers", seg="gen-docs")
st_, fgn = file_in(Fr, "office_gendoc", FGD, FGF)
check(st_ == 200 and fgn and fgn["org_id"] is None and doc_in(tree(Fr, "gen-docs"), FGD), "(f) her document in her Documents folder")
check(A.get(B + f"/api/files/nodes/{fgn['id']}/content").status_code == 404 and tree(A, "gen-docs").get("docs") and not doc_in(tree(A, "gen-docs"), FGD),
      "(f) nobody else sees it (another office's tree, the file store)")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read", "office"]})
check(r.ok, "(f) setup: her agent " + r.text[:160])
FA, FH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
check(Fr.patch(B + f"{O}/agents/{FA}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "(f) setup: the switches of her personal office")
check(requests.get(B + f"/api/v1/files/{fgn['id']}", headers=FH).status_code == 404, "(f) her agent without a share: nothing")
share(Fr, FGF, agent_id=FA, role="view")
r = requests.get(B + f"/api/v1/files/{fgn['id']}/content", headers=FH)
check(r.ok and r.content[:5] == b"%PDF-", f"(f) her agent reads the document through its share ({r.status_code} {r.text[:120] if not r.ok else ''})")

# ---------------------------------------------------------------- (g) folder rules only into folders the uploader edits
D0 = upload(A, "setup-secret.pdf", f"org:{ORG}")
check(A.patch(B + f"/api/docs/{D0}", json={"folder": "Secret box"}).ok, "(g) setup: the documents folder Secret box")
SB = int(A.get(B + f"/api/docs/{D0}").json()["folder"]["id"])
check(A.put(B + "/api/docs/settings", json={"ws": f"org:{ORG}", "levels": {"folder": "rules"}}).ok
      and A.post(B + "/api/docs/rules", json={"ws": f"org:{ORG}", "kind": "any", "match": "Zebraprobe", "folder": "Secret box"}).status_code == 201,
      "(g) setup: a rule Zebraprobe -> Secret box")
DA = upload(A, "zebra-a.pdf", f"org:{ORG}", "Zebraprobe alpha")
DC = upload(Ca, "zebra-c.pdf", f"org:{ORG}", "Zebraprobe carl")


def folder_of(s, did):
    j = s.get(B + f"/api/docs/{did}").json()
    return (j.get("folder") or {}).get("id"), j.get("state")


got = None
for _ in range(120):  # the document reader runs after the upload: wait for alice's document to be sorted (a real state)
    got = folder_of(A, DA)
    if got[0] and int(got[0]) == SB:
        break
    time.sleep(0.25)
check(got and got[0] and int(got[0]) == SB, f"(g) the rule files alice's upload into Secret box ({got})")
done = None
for _ in range(120):
    done = folder_of(A, DC)
    if done[1] == got[1]:
        break
    time.sleep(0.25)
check(done[1] == got[1] and (done[0] is None or int(done[0]) != SB),
      f"(g) carl (accounting, reads the documents folder only) uploads the same: the rule does not file it into Secret box ({done})")

# ---------------------------------------------------------------- (h) another organisation
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga Other", "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
OORG = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": r.json()["id"]}).json()["id"]
Ol = sess("olga")
Ol.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{OORG}"})
t = tree(Ol)
check(t.get("space") == f"org:{OORG}" and not doc_in(t, Q) and not any(f["id"] in (F1, F2, OLD2) for f in t.get("folders", [])),
      f"(h) the other organisation's admin: her own office's tree, nothing of alpha ({t})")
check(Ol.post(B + f"{O}/docs/tree/folders", json={"name": "Intruder", "parent_id": F1}).status_code in (403, 404, 409),
      "(h) no folder inside alpha's folder")
check(file_in(Ol, "office_doc", Q, F1)[0] in (403, 404), "(h) nor files alpha's quotation")

print(f"p2351_a_officetree: {len(OKS)} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
