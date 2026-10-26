#!/usr/bin/env python3
"""2.238.0 A (#2863): the folder way (reference nodes, files/fsref.py) keeps the locks of the area -- invented people,
companies and figures only.
 (a) content gate: a person's token with files:read reaches no filed office document (hidden, the token cannot have the scope
     office), an agent only with the scope office and the office's agent switches; bob's session reads it and the read is in
     the office log; the office turned off / a kid's account: 403 on the content route too
 (b) sheets: a token without sheets:read gets no filed table's CSV, with it the CSV
 (c) the cap: a guest gets nothing through an edit share, accounting only reads (no change of the draft), a member edits
 (d) passing on: a reader (view share above his own folder) cannot share his folder with filed documents, not even to read;
     with an edit share he can
 (e) extending a share's expiry needs the same; shortening it stays free
 (f) restoring a folder with filed documents needs edit on them from the office (like moving), the bulk restore too
 (g) the accepted quotation with the signer's record only for who reads it in the office; a folder reader gets it as sent
 (h) the admin and a person without an organisation: everything as before
usage: p2238_a_fsref_gate_test.py <datadir>
freelancer-matrix: office  freelancer-matrix: files"""
import os
import re
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
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,office,clients,docs,files,sheets"
O = "/api/office"
REF = "/api/fsref/office_doc"

if not (os.environ.get("P2238A_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
uid = {}
for u, role in (("bob", "member"), ("gina", "guest"), ("anna", "accounting"), ("dora", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Gi, An, Do = sess("bob"), sess("gina"), sess("anna"), sess("dora")
for s in (A, Bo, Gi, An, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(A.put(B + f"{O}/rights/people/{uid['bob']}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff (no quotations)")
COMPANY = {"name": "Studio Example GmbH", "street": "Harbour Street 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hello@example.com", "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Example Bank"}
check(A.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14}).ok, "setup: office settings")


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def bearer(tok):
    return {**H, "Authorization": "Bearer " + tok}


def token(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "p2238a", "scopes": list(scopes)})
    assert r.ok, r.text
    return bearer(r.json()["token"])


def folder(s, name, parent=None, space=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space or f"org:{ORG}"})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def file_in(s, did, parent, kind="office_doc"):
    r = s.post(B + "/api/files/refs", json={"ref_kind": kind, "ref_id": did, "parent_id": parent})
    return r.json()["node"]["id"] if r.ok and r.json().get("node") else -r.status_code


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    return r.json()["id"] if r.status_code == 201 else r.status_code


def new_doc(s, kind="offer", title="Edit day", **kw):
    r = s.post(B + O + "/docs", json={"kind": kind, "items": [{"title": title, "qty": 1, "rate": 800}], **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def content(s, nid, h=None):
    return (requests.get(B + f"/api/v1/files/{nid}/content", headers=h) if h else s.get(B + f"/api/files/nodes/{nid}/content"))


# ---------------------------------------------------------------- (a) the content gate of the office
Q = new_doc(A)
BOX = folder(A, "Office box")
QN = file_in(A, Q, BOX)
check(QN > 0, f"setup: the quotation filed ({QN})")
check(isinstance(share(A, BOX, user_id=uid["bob"], role="view"), int), "setup: bob reads the box")
r = content(Bo, QN)
check(r.ok and r.content[:5] == b"%PDF-", f"(a) bob's session reads the quotation's PDF through the folder ({r.status_code})")
log = sql("SELECT user_id FROM office_doc_log WHERE doc_id=? AND action='open'", (Q,))
check(any(x[0] == uid["bob"] for x in log), f"(a) the read through the file store is in the office log ({log})")
BT = token(Bo, ["read", "files:read"])
check(requests.get(B + f"/api/v1/files/{QN}", headers=BT).status_code == 404 and content(None, QN, BT).status_code == 404
      and requests.get(B + f"/api/v1/files/{QN}/text", headers=BT).status_code == 404,
      "(a) bob's token with files:read: the filed quotation stays hidden (node, content, text)")
kids = requests.get(B + "/api/v1/files", params={"parent_id": BOX}, headers=BT)
check(kids.ok and QN not in [x["id"] for x in kids.json().get("data", [])], f"(a) nor listed for the token ({kids.status_code})")
check(Bo.patch(B + "/api/settings", json={"features": FEAT.replace("office,", "")}).ok, "setup: bob turns the office off")
r = content(Bo, QN)
check(r.status_code == 403, f"(a) office off: the file store's content route is closed as well ({r.status_code})")
Bo.patch(B + "/api/settings", json={"features": FEAT})
check(content(Bo, QN).ok, "(a) office on again: open")
r = A.post(B + "/api/my/agents", json={"username": "filebot", "display_name": "File Bot", "scopes": ["read", "files:read"], "org_id": ORG})
check(r.ok, "setup: an agent with files:read only " + r.text[:160])
AG1, AH1 = r.json()["id"], bearer(r.json()["token"])
share(A, BOX, agent_id=AG1, role="view")
check(content(None, QN, AH1).status_code == 404 and requests.get(B + f"/api/v1/files/{QN}/text", headers=AH1).status_code == 404,
      "(a) the agent with a share but without the scope office: no content, no text")
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "files:read", "office"], "org_id": ORG})
check(r.ok, "setup: an agent with the scope office " + r.text[:160])
AG2, AH2 = r.json()["id"], bearer(r.json()["token"])
share(A, BOX, agent_id=AG2, role="view")
check(content(None, QN, AH2).status_code == 404, "(a) scope office, but the office's agent switches off: nothing")
check(A.patch(B + f"{O}/agents/{AG2}", json={"office_drafts": True}).ok, "setup: the agent's office switch on")
check(content(None, QN, AH2).status_code == 404, "(a) the area's switch \"Agents may read office data\" still off: nothing")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: the area's agents switch on")
r = content(None, QN, AH2)
check(r.ok and r.content[:5] == b"%PDF-", f"(a) with the scope and both switches: the agent reads the PDF ({r.status_code})")
check(content(None, QN, AH1).status_code == 404, "(a) the agent without the scope still nothing")
# a kid's account: alice's personal office, a private folder shared with the kid
r = A.post(B + "/api/users", json={"username": "tim", "display_name": "Tim", "password": "password123", "kid": True, "parents": [ALICE]})
check(r.ok, "setup: a kid's account " + r.text[:160])
KID = r.json().get("id")
Ki = sess("tim")
Ki.patch(B + "/api/settings", json={"lang": "en", "features": "files", "tour": "done"})
A.patch(B + "/api/settings", json={"workspace": "private"})
PQ = new_doc(A, title="Private day")
PF = folder(A, "Family box", space="private")
PQN = file_in(A, PQ, PF)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
sk = share(A, PF, user_id=KID, role="view")
check(PQN > 0 and isinstance(sk, int), f"setup: the private quotation filed and shared with the kid ({PQN} {sk})")
r = Ki.get(B + f"/api/files/nodes/{PQN}")
check(r.ok, f"(a) setup check: the kid sees the node in the shared folder ({r.status_code})")
check(content(Ki, PQN).status_code == 403, f"(a) the kid's account: the content route refuses ({content(Ki, PQN).status_code})")

# ---------------------------------------------------------------- (b) sheets: the token's sheets:read
r = A.post(B + "/api/sheets/folders", json={"name": "Shared tables", "space": f"org:{ORG}"})
assert r.status_code == 201, r.text
TF = r.json()["folder"]["id"]
r = A.post(B + "/api/sheets", json={"title": "Budget sheet", "space": f"org:{ORG}"})
assert r.status_code == 201, r.text
SID = r.json()["id"]
SN = file_in(A, SID, TF, kind="sheet")
check(SN > 0 and isinstance(share(A, TF, user_id=uid["bob"], role="view"), int), f"setup: a table filed and shared with bob ({SN})")
check(content(None, SN, BT).status_code in (403, 404), f"(b) bob's token without sheets:read: no CSV ({content(None, SN, BT).status_code})")
BTS = token(Bo, ["read", "files:read", "sheets:read"])
r = content(None, SN, BTS)
check(r.ok and r.content, f"(b) with sheets:read: the CSV ({r.status_code} {r.text[:80]})")
check(content(Bo, SN).ok, "(b) bob's session reads it as before")

# ---------------------------------------------------------------- (c) the cap by the organisation role
Q3 = new_doc(A, title="Grading")
EBOX = folder(A, "Edit box")
file_in(A, Q3, EBOX)
for who in ("gina", "anna", "bob"):
    share(A, EBOX, user_id=uid[who], role="edit")
check(Gi.get(B + f"{REF}/{Q3}").status_code == 404 and Gi.patch(B + f"{REF}/{Q3}", json={"intro": "guest"}).status_code == 404,
      "(c) a guest with an edit share: nothing (the office gives guests nothing)")
r = An.get(B + f"{REF}/{Q3}")
check(r.ok and r.json().get("folder_role") == "view", f"(c) accounting with an edit share: reads, role view ({r.status_code} {r.text[:120]})")
check(An.patch(B + f"{REF}/{Q3}", json={"intro": "accounting"}).status_code == 403
      and An.put(B + f"{REF}/{Q3}/items", json={"items": [{"title": "x", "qty": 1, "rate": 1}]}).status_code == 403,
      "(c) accounting: no change of the draft, no positions")
r = Bo.patch(B + f"{REF}/{Q3}", json={"intro": "Changed by a member"})
check(r.ok, f"(c) a member with the edit share still changes the draft ({r.status_code})")

# ---------------------------------------------------------------- (d) passing on, (e) the expiry
BF = folder(Bo, "Bob's own")
Q4 = new_doc(A, title="Pass on")
check(file_in(A, Q4, BF) > 0, "setup: alice (admin) files a quotation into bob's own folder")
SO = share(A, BF, user_id=uid["bob"], role="edit")
check(isinstance(SO, int), f"setup: alice gives bob an explicit edit share on it ({SO})")
r = Bo.post(B + f"/api/files/nodes/{BF}/shares", json={"user_id": uid["dora"], "role": "view", "expires_at": "2099-01-10"})
check(r.status_code == 201, f"(d) with edit on the quotation: bob shares his folder to read ({r.status_code} {r.text[:120]})")
SD = r.json().get("id") if r.status_code == 201 else 0
check(A.patch(B + f"/api/files/shares/{SO}", json={"role": "view"}).ok, "setup: bob's share becomes view")
r = Bo.post(B + f"/api/files/nodes/{BF}/shares", json={"user_id": uid["anna"], "role": "view"})
check(r.status_code == 403, f"(d) a reader cannot pass the filed quotation on, not even to read ({r.status_code} {r.text[:120]})")
r = Bo.patch(B + f"/api/files/shares/{SD}", json={"expires_at": "2099-06-30"})
check(r.status_code == 403, f"(e) a reader cannot extend the share ({r.status_code})")
r = Bo.patch(B + f"/api/files/shares/{SD}", json={"expires_at": None})
check(r.status_code == 403, f"(e) nor drop its end ({r.status_code})")
r = Bo.patch(B + f"/api/files/shares/{SD}", json={"expires_at": "2099-01-05"})
check(r.ok, f"(e) shortening it stays free ({r.status_code} {r.text[:120]})")
r = A.patch(B + f"/api/files/shares/{SD}", json={"expires_at": "2099-12-31"})
check(r.ok, f"(h) the admin extends it ({r.status_code})")

# ---------------------------------------------------------------- (f) restoring a folder with filed documents
check(A.put(B + f"{O}/rights/people/{uid['dora']}", json={"groups": ["tpl:projects"]}).ok, "setup: dora in Project management (edits quotations)")
DF = folder(Do, "Dora's quotes")
DQ = new_doc(Do, title="Dora's draft")
DQ2 = new_doc(Do, title="Dora's second")
DF2 = folder(Do, "Dora's second box")
check(file_in(Do, DQ, DF) > 0 and file_in(Do, DQ2, DF2) > 0, "setup: dora files her drafts into her folders")
check(Do.delete(B + f"/api/files/nodes/{DF}").ok and Do.post(B + "/api/files/trash", json={"ids": [DF2]}).ok, "setup: both folders into the trash")
check(A.put(B + f"{O}/rights/people/{uid['dora']}", json={"groups": ["tpl:staff"]}).ok, "setup: dora moves to Staff (no quotations)")
r = Do.post(B + f"/api/files/nodes/{DF}/restore")
check(r.status_code == 403, f"(f) dora cannot bring the folder back with a quotation she may not edit ({r.status_code} {r.text[:120]})")
r = Do.post(B + "/api/files/restore", json={"ids": [DF2]})
check(r.status_code == 403, f"(f) nor through the bulk restore ({r.status_code})")
check(A.post(B + f"/api/files/nodes/{DF}/restore").ok and A.post(B + "/api/files/restore", json={"ids": [DF2]}).ok,
      "(h) the admin restores both")
check(A.get(B + f"/api/files/refs/office_doc/{DQ}").json().get("node", {}).get("deleted_at") in (None, ""), "(h) the quotation is filed again")

# ---------------------------------------------------------------- (g) the accepted quotation
CLI = A.post(B + "/api/clients", json={"name": "Example Client AG", "street": "Market Street 5", "zip": "50667", "city": "Cologne",
                                        "country": "DE", "email": "client@example.com", "org_id": ORG}).json()["id"]
QA = new_doc(A, title="Shoot", client_id=CLI)
check(A.post(B + f"{O}/docs/{QA}/finalize").ok and A.post(B + f"{O}/docs/{QA}/status", json={"status": "sent"}).ok, "setup: finalised and sent")
r = A.post(B + f"{O}/docs/{QA}/signoff", json={})
check(r.ok, "setup: the approval link " + r.text[:160])
TOK = r.json()["url"].split("/s/q/")[1] if r.ok else ""
pg = requests.get(B + "/s/q/" + TOK)
m = re.search(r'name="f" value="([0-9a-f]+)"', pg.text)
r = requests.post(B + "/s/q/" + TOK, data={"f": m.group(1) if m else "", "name": "Max Example", "ok": "1", "do": "accept"}, allow_redirects=False)
check(r.status_code in (200, 302, 303), f"setup: the client accepts online ({r.status_code})")
file_in(A, QA, BOX)  # bob reads the box (view share, no quotations in the office)
ra, rb = A.get(B + f"{REF}/{QA}/pdf"), Bo.get(B + f"{REF}/{QA}/pdf")
check(ra.ok and "-accepted" in ra.headers.get("Content-Disposition", ""), f"(h) alice gets the accepted version ({ra.headers.get('Content-Disposition')})")
check(rb.ok and rb.content[:5] == b"%PDF-" and "-accepted" not in rb.headers.get("Content-Disposition", ""),
      f"(g) bob through the folder: the quotation as sent, without the signer's record ({rb.status_code} {rb.headers.get('Content-Disposition')})")

# ---------------------------------------------------------------- (h) a person without an organisation
FID, Fr = freelancer(B, A, "frida", features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private", "features": FEAT})
FQ = new_doc(Fr)
FF = folder(Fr, "Customers", space="private")
FN = file_in(Fr, FQ, FF)
check(FN > 0 and content(Fr, FN).ok, f"(h) the freelancer reads her filed quotation through the file store ({FN})")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read"]})
check(r.ok, "setup: her agent " + r.text[:160])
FS = share(Fr, FF, agent_id=r.json().get("id"), role="view", expires_at="2099-01-10")
check(isinstance(FS, int) and Fr.patch(B + f"/api/files/shares/{FS}", json={"expires_at": "2099-12-31"}).ok, f"(h) she shares with her agent and extends ({FS})")
check(Fr.delete(B + f"/api/files/nodes/{FF}").ok and Fr.post(B + f"/api/files/nodes/{FF}/restore").ok, "(h) she deletes and restores her folder")
FT = token(Fr, ["read", "files:read"])
# 2.351.0 F (#3246, review M2): a token's hidden (no scope office) now outranks her own base role too: the node is not found (404)
check(content(None, FN, FT).status_code == 404, "(h) her own token without the scope office: no content (people's tokens never have it)")

print(f"p2238_a_fsref_gate: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
