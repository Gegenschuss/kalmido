#!/usr/bin/env python3
"""2.199.0 B (#2742): folders for the office -- invented people, companies and figures only.
 (a) the documents view: the whole folder tree below the documents folder (path, depth), a document into "A / B" makes the
     subfolders, its folder is the deep one (path), ?under= lists a folder with its subfolders, the inbox stays out
 (b) a quotation filed in a folder (reference node office_doc): nothing without the folder for a member of the group
     "Staff"; a share view = read it and its PDF, not change it; edit = change the draft; the special steps (finalise,
     delete, number) stay with the office groups; taken out of the folder = nothing again
 (c) deleting a folder: a numbered invoice and a booked receipt inside it stay (one level up, kept with the reason), the
     quotation draft goes along into the trash and comes back with the folder
 (d) the receipts lock: bob with a share on a folder holding a receipt does not see it (no office group "Receipts")
 (e) an agent: only through a share with exactly it, reads the node (never changes the document)
 (f) a person without an organisation: her personal office's quotation in her private folder, shared with her agent
 (g) another organisation's admin: 404 on the folder routes
usage: p2199_b_office_test.py <datadir>
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
REF = "/api/fsref/office_doc"

if not (os.environ.get("P2199B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Staff", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(A.put(B + f"{O}/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff")


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


def upload(s, name, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Doc " + name), "application/pdf")})
    check(r.status_code == 201, f"upload {name}: {r.status_code} {r.text[:200]}")
    return r.json()["ids"][0] if r.status_code == 201 else None


def folder(s, name, parent=None, space=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space or f"org:{ORG}"})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def file_in(s, did, parent):
    r = s.post(B + "/api/files/refs", json={"ref_kind": "office_doc", "ref_id": did, "parent_id": parent})
    return r.status_code, (r.json().get("node") if r.ok else r.text[:200])


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def new_doc(s, kind="offer", title="Edit day"):
    r = s.post(B + O + "/docs", json={"kind": kind, "items": [{"title": title, "qty": 1, "rate": 800}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- (a) the documents view: the whole tree
D1 = upload(A, "contract-alpha.pdf", f"org:{ORG}")
r = A.patch(B + f"/api/docs/{D1}", json={"folder": "Client Alpha / 2026"})
check(r.ok, "(a) a document into the path Client Alpha / 2026 " + r.text[:200])
d = A.get(B + f"/api/docs/{D1}").json()
check((d.get("folder") or {}).get("name") == "2026" and d["folder"].get("path") == "Client Alpha / 2026",
      f"(a) its folder is the deep one, with its path ({d.get('folder')})")
st = A.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).json()
paths = [(f["path"], f["depth"]) for f in st["folders"]]
check(("Client Alpha", 0) in paths and ("Client Alpha / 2026", 1) in paths and not any(p.lower().startswith("eingang") for p, _ in paths),
      f"(a) settings list the whole tree with path and depth, not the inbox ({paths})")
SUB = next(f["id"] for f in st["folders"] if f["path"] == "Client Alpha / 2026")
TOP = next(f["id"] for f in st["folders"] if f["path"] == "Client Alpha")
check(all(f.get("role") in ("owner", "edit", "view") for f in st["folders"]), "(a) every folder with the asker's role (the panel's menu)")
D2 = upload(A, "letter-beta.pdf", f"org:{ORG}")
check(A.patch(B + f"/api/docs/{D2}", json={"folder": TOP}).ok, "(a) a document into the upper folder by id")
ids = [x["id"] for x in A.get(B + "/api/docs", params={"ws": f"org:{ORG}", "under": TOP}).json()["docs"]]
check(sorted(ids) == sorted([D1, D2]), f"(a) ?under= the upper folder: both, also the one in the subfolder ({ids})")
ids = [x["id"] for x in A.get(B + "/api/docs", params={"ws": f"org:{ORG}", "under": SUB}).json()["docs"]]
check(ids == [D1], f"(a) ?under= the subfolder: only its document ({ids})")
check(A.patch(B + f"/api/docs/{D2}", json={"folder": SUB}).ok and A.get(B + f"/api/docs/{D2}").json()["folder"]["id"] == SUB,
      "(a) a document into the subfolder by id (any depth)")

# ---------------------------------------------------------------- (b) a quotation filed in a folder
Q = new_doc(A)
OFF = folder(A, "Office")
CL = folder(A, "Clients", OFF)
ELSE = folder(A, "Elsewhere")
st_, node = file_in(A, Q, CL)
check(st_ == 200 and node and node["kind"] == "ref" and node["ref_kind"] == "office_doc" and node["open"] == f"office/offers/{Q}",
      f"(b) alice files the quotation into Office / Clients ({st_} {node})")
QN = node["id"] if isinstance(node, dict) else 0
check(node and node["name"].startswith("Quotation"), f"(b) the node is named after the document ({node and node['name']})")
check(Bo.get(B + f"{O}/docs/{Q}").status_code == 403 and Bo.get(B + f"{REF}/{Q}").status_code == 404,
      "(b) bob (Staff): neither the office nor the folder way")
check(file_in(Bo, Q, CL)[0] in (403, 404), "(b) bob cannot file it")
S1 = share(A, OFF, user_id=BOB, role="view")
r = Bo.get(B + f"{REF}/{Q}")
check(r.ok and r.json().get("folder_role") == "view" and r.json().get("id") == Q, f"(b) share view on the folder above: bob reads it ({r.status_code} {r.text[:160]})")
r = Bo.get(B + f"{REF}/{Q}/pdf")
check(r.ok and r.content[:5] == b"%PDF-" and r.headers.get("Content-Type", "").startswith("application/pdf"), f"(b) bob reads its PDF ({r.status_code})")
check(Bo.patch(B + f"{REF}/{Q}", json={"intro": "changed by bob"}).status_code == 403, "(b) view: no change")
check(Bo.get(B + f"{O}/docs/{Q}").status_code == 403, "(b) the office's own route stays closed to bob (his groups)")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok, "(b) setup: the share becomes edit")
r = Bo.patch(B + f"{REF}/{Q}", json={"intro": "Changed through the folder"})
check(r.ok and A.get(B + f"{O}/docs/{Q}").json().get("intro") == "Changed through the folder", f"(b) edit: bob changes the draft ({r.status_code} {r.text[:160]})")
r = Bo.put(B + f"{REF}/{Q}/items", json={"items": [{"title": "Two edit days", "qty": 2, "rate": 800}]})
check(r.ok and [i["title"] for i in A.get(B + f"{O}/docs/{Q}").json()["items"]] == ["Two edit days"], f"(b) edit: bob changes the positions ({r.status_code})")
check(Bo.post(B + f"{O}/docs/{Q}/finalize").status_code == 403 and Bo.delete(B + f"{O}/docs/{Q}").status_code == 403
      and Bo.post(B + f"{O}/docs/{Q}/number", json={}).status_code == 403, "(b) the special steps (finalise, delete, number) stay closed")
Q2 = new_doc(A, title="Later")
check(file_in(A, Q2, CL)[0] == 200 and Bo.get(B + f"{REF}/{Q2}").json().get("folder_role") == "edit", "(b) filed later: bob edits that one too")
check(file_in(A, Q, ELSE)[0] == 200 and Bo.get(B + f"{REF}/{Q}").status_code == 404, "(b) moved out of the folder: bob nothing")
check(file_in(Bo, Q2, ELSE)[0] in (403, 404), "(b) bob cannot move it into a folder he does not edit")
check(file_in(A, Q, None)[0] == 200 and A.get(B + f"/api/files/nodes/{QN}").status_code == 404 and A.get(B + f"{O}/docs/{Q}").ok,
      "(b) into no folder: the node goes, the document stays")
check(file_in(A, Q, CL)[0] == 200, "(b) filed again")
PRIV = folder(A, "Mine", space="private")
check(file_in(A, Q, PRIV)[0] == 409, "(b) an organisation's quotation never into a private folder")
check(A.delete(B + f"/api/files/shares/{S1}").ok and Bo.get(B + f"{REF}/{Q2}").status_code == 404, "(b) the share withdrawn: bob nothing")

# ---------------------------------------------------------------- (c) deleting a folder keeps what the law keeps
INV = new_doc(A, kind="invoice", title="Shoot")
r = A.post(B + f"{O}/docs/{INV}/number", json={})
check(r.ok, "(c) setup: the invoice gets its number " + r.text[:160])
check(file_in(A, INV, CL)[0] == 200, "(c) the numbered invoice filed in Office / Clients")
RC = upload(A, "receipt-gamma.pdf", f"org:{ORG}")
check(A.patch(B + f"/api/docs/{RC}", json={"amount": "119.00", "date": time.strftime("%Y-%m-%d")}).ok, "(c) setup: the receipt's amount")
r = A.put(B + f"/api/docs/{RC}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True})
check(r.ok, "(c) setup: a booked receipt " + r.text[:160])
check(A.patch(B + f"/api/files/nodes/{RC}", json={"parent_id": CL}).ok, "(c) setup: the receipt into Office / Clients")
r = A.delete(B + f"/api/files/nodes/{OFF}")
kept = {k["id"]: k for k in (r.json().get("kept") or [])} if r.ok else {}
INVN = (A.get(B + f"/api/files/refs/office_doc/{INV}").json().get("node") or {}).get("id")
check(r.ok and INVN in kept and RC in kept, f"(c) Office into the trash: the invoice and the receipt stay ({r.status_code} {r.text[:240]})")
check(INVN in kept and "invoice" in kept[INVN]["reason"].lower() and RC in kept and "retention" in kept[RC]["reason"].lower(),
      f"(c) each with its reason ({list(kept.values())})")
check(A.get(B + f"/api/files/nodes/{INVN}").json().get("parent_id") is None, "(c) the invoice moved one level up (the top of the tree)")
check(A.get(B + f"{REF}/{Q}").ok and Bo.get(B + f"{REF}/{Q}").status_code == 404, "(c) the quotation draft went along: its node gives nothing in the trash")
check(A.post(B + f"/api/files/nodes/{OFF}/restore").ok and (A.get(B + f"/api/files/refs/office_doc/{Q}").json().get("node") or {}).get("deleted_at") in (None, ""),
      "(c) the folder back: the quotation is filed again")

# ---------------------------------------------------------------- (d) the receipts lock holds with a folder share
BOX = folder(A, "Shared box")
check(A.patch(B + f"/api/files/nodes/{RC}", json={"parent_id": BOX}).ok, "(d) setup: the receipt into a shared box")
share(A, BOX, user_id=BOB, role="view")
kids = Bo.get(B + "/api/files", params={"parent": BOX})
check(kids.ok and RC not in [x["id"] for x in kids.json().get("items", [])], "(d) bob does not see the receipt in the shared folder")
check(Bo.get(B + f"/api/files/nodes/{RC}").status_code in (403, 404), "(d) nor opens it")

# ---------------------------------------------------------------- (e) an agent: only with its own share, read only
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "files:read"], "org_id": ORG})
check(r.ok, "(e) setup: the organisation's agent " + r.text[:160])
AG, AH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}
QN = A.get(B + f"/api/files/refs/office_doc/{Q}").json()["node"]["id"]
check(requests.get(B + f"/api/v1/files/{QN}", headers=AH).status_code == 404, "(e) the agent without a share: nothing")
share(A, CL, agent_id=AG, role="edit")
r = requests.get(B + f"/api/v1/files/{QN}", headers=AH)
check(r.ok and r.json().get("ref_kind") == "office_doc" and r.json().get("open") == f"office/offers/{Q}", f"(e) with its share: the agent sees the node ({r.status_code})")
check(requests.patch(B + f"{REF}/{Q}", headers=AH, json={"intro": "agent"}).status_code in (401, 403, 404), "(e) the agent never changes the document")

# ---------------------------------------------------------------- (f) a person without an organisation
FID, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private", "features": FEAT})
FQ = new_doc(Fr)
FF = folder(Fr, "Customers", space="private")
st_, fn = file_in(Fr, FQ, FF)
check(st_ == 200 and fn and fn["org_id"] is None, f"(f) the freelancer files her quotation into her private folder ({st_} {fn})")
check(Fr.get(B + f"{REF}/{FQ}").json().get("folder_role") == "edit" and Fr.get(B + f"{REF}/{FQ}/pdf").ok, "(f) she reads it the folder way, PDF too")
check(file_in(Fr, FQ, OFF)[0] in (404, 409), "(f) never into the organisation's folder")
check(Bo.get(B + f"{REF}/{FQ}").status_code == 404 and A.get(B + f"{REF}/{FQ}").status_code == 404, "(f) nobody else without a share")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read"]})
check(r.ok, "(f) setup: her agent " + r.text[:160])
FH = {**H, "Authorization": "Bearer " + r.json().get("token", "")}
check(requests.get(B + f"/api/v1/files/{fn['id']}", headers=FH).status_code == 404, "(f) her agent without a share: nothing")
share(Fr, FF, agent_id=r.json()["id"], role="view")
check(requests.get(B + f"/api/v1/files/{fn['id']}", headers=FH).ok, "(f) her agent with its share: sees the node")

# ---------------------------------------------------------------- (g) another organisation
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga Other", "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": r.json()["id"]}).ok, "(g) setup: another organisation")
Ol = sess("olga")
check(Ol.get(B + f"{REF}/{Q}").status_code == 404 and Ol.get(B + f"{REF}/{Q}/pdf").status_code == 404
      and Ol.patch(B + f"{REF}/{Q}", json={"intro": "x"}).status_code == 404, "(g) the other organisation's admin: 404 on the folder routes")

print(f"p2199_b_office: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
