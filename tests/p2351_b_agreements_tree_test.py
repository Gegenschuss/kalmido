#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 B (#2749): contracts in folders (office/agrref.py). Invented names, generated PDFs only.
 - a framework contract's PDF (contract_file) and a contract / insurance (office_agreement) are filed into a folder of
   the office's file tree (POST /api/files/refs): they show in the file store; nothing moves (the PDF stays the office's)
 - filing needs the office's own right (admins); a member / guest cannot file
 - a folder share gives READING only (the PDF / the contract as text): the office's own routes stay closed (the
   agreements: admins only), a folder edit share gives no more than view (cap)
 - a guest of the organisation never gets anything through a share; a deleted contract gives nothing
 - agents: only with a share on exactly them AND the office's agent switches for the area (an organisation's agent
   without an office group for it: nothing)
 - freelancer-matrix: office (the personal office: her private folder, her own agent with the switches)
usage: p2351_b_agreements_tree_test.py <datadir>      (P2351B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
O = "/api/office"
FEAT = "comments,collab,files,docs,office,clients"


def pdf(text):
    """A tiny valid PDF made here (no real document)."""
    body = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


if not os.environ.get("P2351B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update({"X-Requested-With": "kalmido"})
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u, rl in (("bob", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rl}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Gi = sess("bob"), sess("gina")
for s in (A, Bo, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": SP})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def folder(s, ws, name):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": ws})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def place(s, kind, rid, parent):
    return s.post(B + "/api/files/refs", json={"ref_kind": kind, "ref_id": rid, "parent_id": parent})


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def content(s, nid):
    r = s.get(B + f"/api/files/nodes/{nid}/content")
    return r.content if r.ok else r.status_code


# ================================================================ a framework contract's PDF
CL = A.post(B + "/api/clients", json={"name": "Example Client Ltd"}).json()["id"]
r = A.post(B + O + "/contracts", json={"name": "Frame 2026", "client_id": CL})
check(r.status_code in (200, 201), "a framework contract " + r.text[:200])
CT = r.json()["id"]
r = A.post(B + O + f"/contracts/{CT}/files", files={"file": ("frame-2026.pdf", pdf("Frame contract test"), "application/pdf")})
check(r.status_code == 201, "its PDF " + r.text[:200])
CF = r.json()["id"]
FD = folder(A, SP, "Contracts")
check(place(Bo, "contract_file", CF, FD).status_code in (403, 404), "bob (member, no admin) cannot file the PDF")
r = place(A, "contract_file", CF, FD)
check(r.ok, "alice files the PDF into Contracts " + r.text[:200])
NCF = r.json()["node"]["id"]
check(content(A, NCF)[:5] == b"%PDF-", "the file store gives the PDF (decrypted)")
check(A.get(B + O + f"/contracts/{CT}/files").ok and len(A.get(B + O + f"/contracts/{CT}/files").json()["items"]) == 1,
      "the PDF stays where it is (the contract still lists it)")
SG = fshare(A, FD, user_id=uid["gina"], role="view")
check(content(Gi, NCF) in (403, 404), "a guest gets nothing through a share")
A.delete(B + f"/api/files/shares/{SG}")

# ================================================================ a contract & insurance (admins only in the office)
r = A.post(B + O + "/agreements", json={"kind": "insurance", "name": "Liability insurance", "provider": "Example Insurer",
                                         "number": "LI-123", "cost": "40", "per": "month", "task": 0})
check(r.status_code == 201, "a contract " + r.text[:200])
AG1 = r.json()["id"]
r = place(A, "office_agreement", AG1, FD)
check(r.ok, "alice files the contract " + r.text[:200])
NAG = r.json()["node"]["id"]
check(Bo.get(B + O + "/agreements").status_code in (403, 404) and content(Bo, NAG) in (403, 404), "bob: nothing before a share")
S1 = fshare(A, FD, user_id=uid["bob"], role="edit")
t = content(Bo, NAG)
check(isinstance(t, bytes) and b"Liability insurance" in t and b"LI-123" in t, f"bob reads the contract as text through the folder {t!r}"[:300])
check(content(Bo, NCF)[:5] == b"%PDF-", "bob reads the PDF through the folder")
r = Bo.get(B + f"/api/files/refs/office_agreement/{AG1}")
check(r.ok and r.json()["role"] == "view", "a folder edit share gives no more than view (the office keeps the changes)")
check(Bo.get(B + O + f"/agreements/{AG1}").status_code in (403, 404) and Bo.patch(B + O + f"/agreements/{AG1}", json={"name": "x"}).status_code in (403, 404),
      "the office's own routes stay closed to bob")
check(place(Bo, "office_agreement", AG1, None).status_code in (403, 404), "bob cannot take it out of the folder")
check(A.delete(B + O + f"/agreements/{AG1}").ok and content(Bo, NAG) in (403, 404), "a deleted contract gives nothing")
check(A.post(B + O + f"/agreements/{AG1}/restore").ok and isinstance(content(Bo, NAG), bytes), "restored: back")
check(A.delete(B + f"/api/files/shares/{S1}").ok and content(Bo, NAG) in (403, 404), "share withdrawn = nothing")

# ================================================================ an organisation's agent: share + the office's switches
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "files:read", "office"], "username": "clerk", "display_name": "Clerk", "org_id": ORG})
assert r.status_code == 201, r.text
AGT, ag = r.json()["id"], bearer(r.json()["token"])
check(A.patch(B + O + f"/agents/{AGT}", json={"office_drafts": True}).ok and A.put(B + O + "/settings", json={"agents_read": 1}).ok, "agent switches on")
check(ag.get(V + f"/files/{NAG}/content").status_code in (403, 404), "agent: nothing without a share")
fshare(A, FD, agent_id=AGT, role="view")
check(ag.get(V + f"/files/{NAG}/content").status_code in (403, 404),
      "agent with a share but no office group for contracts & insurance: still nothing (the office's switches rule)")

# ================================================================ a person without an organisation: her personal office
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + O + "/agreements", json={"kind": "rent", "name": "Studio rent", "provider": "Example Landlord", "cost": "900", "per": "month", "task": 0})
check(r.status_code == 201, "freelancer: a contract in her personal office " + r.text[:200])
FAG = r.json()["id"]
FF = folder(Fr, "private", "Office papers")
r = place(Fr, "office_agreement", FAG, FF)
check(r.ok, "freelancer: filed into her private folder " + r.text[:200])
FN = r.json()["node"]["id"]
check(b"Studio rent" in content(Fr, FN), "freelancer: reads it in her file store")
r = Fr.post(B + "/api/my/agents", json={"username": "fridaclerk", "display_name": "Fridaclerk", "scopes": ["read", "files:read", "office"]})
check(r.ok, "freelancer: her own agent " + r.text[:200])
FA, fa = r.json()["id"], bearer(r.json()["token"])
check(Fr.patch(B + O + f"/agents/{FA}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok, "her agent's switches on")
check(fa.get(V + f"/files/{FN}/content").status_code in (403, 404), "her agent: nothing without a share")
fshare(Fr, FF, agent_id=FA, role="view")
r = fa.get(V + f"/files/{FN}/content")
check(r.ok and b"Studio rent" in r.content, f"her agent with a share reads the contract {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
