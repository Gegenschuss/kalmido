#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.351.0 C: office rights found in the 2.305 review -- invented people, companies and figures only, the files are made here.
 (a) #3246: an agent with a project restriction (agents.list_ids) reads through a folder shared with it only the office
     documents of its projects (and those without a project) -- like the office's own agent routes (ofa_need_in_lists):
     content, text, node 404 and not listed for a document of another project; without a restriction everything as before
 (b) #3247: receipt_read -- the person's receipts right is asked again when taking over and undoing (granted when asking):
     taken away in between -> 403 / skipped, nothing changed; given back -> works; the card shows Take over closed
 (c) a person without an organisation: the same in the personal office (freelancer-matrix: office)
usage: p2351_c_officerights_test.py <datadir>   (P2351C_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
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
R = O + "/rights"

if not (os.environ.get("P2351C_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Example GmbH", "street": "Harbour Street 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hello@example.com", "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Example Bank"}
check(A.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14, "agents_read": 1}).ok,
      "setup: office settings, agents may read office data")


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


def bearer(t):
    return {**H, "Authorization": "Bearer " + t}


def folder(s, name, space):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def file_in(s, did, parent):
    r = s.post(B + "/api/files/refs", json={"ref_kind": "office_doc", "ref_id": did, "parent_id": parent})
    return r.json()["node"]["id"] if r.ok and r.json().get("node") else -r.status_code


def new_doc(s, title, lid=None):
    r = s.post(B + O + "/docs", json={"kind": "offer", "items": [{"title": title, "qty": 1, "rate": 800}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if lid:
        sql("UPDATE office_docs SET list_id=? WHERE id=?", (lid, did), write=True)
    return did


def reach(h, nid):
    """(node, content, text) status codes of a filed document for an agent's token."""
    return (requests.get(V + f"/files/{nid}", headers=h).status_code, requests.get(V + f"/files/{nid}/content", headers=h).status_code,
            requests.get(V + f"/files/{nid}/text", headers=h).status_code)


def listed(h, parent):
    r = requests.get(V + "/files", params={"parent_id": parent}, headers=h)
    return [x["id"] for x in r.json().get("data", [])] if r.ok else None


def restriction_case(s, owner_label, space, ag_body, set_switch):
    """(a) / (c): two projects, a document in each and one without a project, filed into one folder shared with the agent."""
    l1 = s.post(B + "/api/lists", json={"name": "Project One", **({"org_id": ORG} if space != "private" else {})}).json()["id"]
    l2 = s.post(B + "/api/lists", json={"name": "Project Two", **({"org_id": ORG} if space != "private" else {})}).json()["id"]
    d1, d2, d0 = new_doc(s, "Day one", l1), new_doc(s, "Day two", l2), new_doc(s, "No project")
    box = folder(s, "Agent box", space)
    n1, n2, n0 = file_in(s, d1, box), file_in(s, d2, box), file_in(s, d0, box)
    check(min(n1, n2, n0) > 0, f"{owner_label}: setup: three documents filed ({n1} {n2} {n0})")
    r = s.post(B + "/api/my/agents", json=ag_body)
    check(r.status_code in (200, 201), f"{owner_label}: setup: an agent with the scope office " + r.text[:160])
    ag, ah = r.json()["id"], bearer(r.json()["token"])
    set_switch(ag)
    check(isinstance(s.post(B + f"/api/files/nodes/{box}/shares", json={"agent_id": ag, "role": "view"}).json().get("id"), int),
          f"{owner_label}: setup: the box shared with the agent")
    check(all(reach(ah, n)[:2] == (200, 200) for n in (n1, n2, n0)), f"{owner_label}: no restriction: the agent reads all three "
          f"{[reach(ah, n) for n in (n1, n2, n0)]}")
    sql("UPDATE agents SET list_ids=? WHERE user_id=?", (str(l1), ag), write=True)
    check(reach(ah, n2) == (404, 404, 404), f"{owner_label}: #3246 restricted to project one: the document of project two "
          f"is not found (node, content, text) {reach(ah, n2)}")
    kids = listed(ah, box)
    check(kids is not None and n2 not in kids and n1 in kids and n0 in kids,
          f"{owner_label}: #3246 the listing leaves it out, keeps project one and the one without a project {kids} ({n1} {n2} {n0})")
    check(all(reach(ah, n)[:2] == (200, 200) for n in (n1, n0)), f"{owner_label}: project one and no project: read as before")
    check(requests.get(B + f"/api/fsref/office_doc/{d2}", headers=ah).status_code != 200,
          f"{owner_label}: #3246 the folder way of the office (fsref) does not open it either")
    sql("UPDATE agents SET list_ids=? WHERE user_id=?", (f"{l1},{l2}", ag), write=True)
    check(reach(ah, n2)[:2] == (200, 200), f"{owner_label}: both projects in the restriction: read again {reach(ah, n2)}")
    return ag, ah


# ---------------------------------------------------------------- (a) #3246 an organisation's agent
def org_switch(ag):
    check(A.patch(B + f"{O}/agents/{ag}", json={"office_drafts": True}).ok, "org: setup: the agent's office switch")


restriction_case(A, "org", f"org:{ORG}", {"username": "projbot", "display_name": "Project Bot", "scopes": ["read", "files:read", "office"],
                                          "org_id": ORG}, org_switch)

# ---------------------------------------------------------------- (b) #3247 receipt_read: the receipts right at take-over
RECEIPT = ("Beispiel Buerobedarf GmbH\nMusterweg 3, 12345 Musterstadt\nRechnung Nr. RE-2026-17\nDatum 05.10.2026\n"
           "Netto 100,00 EUR\nMwSt 19 % 19,00 EUR\nGesamt 119,00 EUR\n")


def upload(s, ws, name, text):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, text.encode(), "text/plain")})
    assert r.ok, r.text
    nid = (r.json().get("ids") or [x["id"] for x in r.json().get("docs") or r.json().get("items") or []])[0]
    for _ in range(200):  # the recognition run: wait for its state, not for a time
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.2)
    return nid


def amount(s, nid):
    return s.get(B + f"/api/docs/{nid}").json().get("amount")


def read_job(s, ah, ag, doc):
    r = s.post(B + "/api/proposals", json={"kind": "receipt_read", "agent_id": ag, "doc_id": doc})
    check(r.status_code == 201, "setup: the person asks the agent to read the receipt " + r.text[:200])
    jid = r.json().get("id")
    r = requests.post(V + f"/agent/jobs/{jid}/proposal", headers=ah, json={"gross": "119.00", "date": "2026-10-05"})
    check(r.status_code == 201, "setup: the agent answers " + r.text[:200])
    return jid


check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:projects"]}).ok, "setup: bob in Project management (receipts edit)")
r = Bo.post(B + "/api/my/agents", json={"username": "rcbot", "display_name": "Receipt Bot", "scopes": ["read", "office", "files:read"], "org_id": ORG})
check(r.status_code == 201, "setup: bob's own agent in the organisation " + r.text[:160])
RAG, RAH = r.json()["id"], bearer(r.json()["token"])
check(A.patch(B + f"{O}/agents/{RAG}", json={"office_drafts": True}).ok and A.put(B + f"{R}/people/{RAG}", json={"groups": ["tpl:projects"]}).ok,
      "setup: the agent's office switch and office group")
DOC = upload(Bo, f"org:{ORG}", "beleg.txt", RECEIPT)
check(Bo.patch(B + f"/api/docs/{DOC}", json={"amount": "1.00", "date": "2026-10-01"}).ok, "setup: bob's receipt, amount by hand")
check(Bo.post(B + f"/api/files/nodes/{DOC}/shares", json={"agent_id": RAG, "role": "view"}).ok, "setup: bob shares it with the agent")
r = Bo.get(B + "/api/proposals/agents", params={"kind": "receipt_read", "doc_id": DOC})
check(r.ok and RAG in [a["id"] for a in r.json().get("agents", [])], f"setup: bob may ask the agent ({r.status_code} {r.text[:160]})")
J = read_job(Bo, RAH, RAG, DOC)
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:none"]}).ok, "setup: alice takes bob's office rights away (No office access)")
v = Bo.get(B + f"/api/proposals/{J}").json()
check((v.get("target") or {}).get("editable") is False, f"#3247 the card: Take over closed without the receipts right {str(v.get('target'))[:160]}")
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]})
check(r.status_code == 403 and amount(Bo, DOC) == "1.00", f"#3247 taking over without the receipts right: 403, nothing changed ({r.status_code} {amount(Bo, DOC)})")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:projects"]}).ok, "setup: the receipts right back")
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]})
check(r.ok and amount(Bo, DOC) == "119.00", f"with the receipts right again: taken over ({r.status_code} {r.text[:120]})")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:none"]}).ok, "setup: the right taken away again")
r = Bo.post(B + f"/api/proposals/{J}/undo")
check(r.ok and r.json().get("undone") == 0 and amount(Bo, DOC) == "119.00", f"#3247 undo without the receipts right: skipped, nothing changed ({r.text[:120]})")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:projects"]}).ok, "setup: the right back")
# a skipped undo uses up the step (as a value changed since, p2299_e): the taken-over values stay
r = Bo.post(B + f"/api/proposals/{J}/undo")
check(r.status_code in (200, 409) and amount(Bo, DOC) == "119.00", f"after the skipped undo the values stay ({r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- (c) a person without an organisation
# freelancer-matrix: office
FID, Fr = freelancer(B, A, features=FEAT)
Fr.get(B + O + "/settings")
check(Fr.put(B + O + "/settings", json={"lang": "en", "currency": "EUR", "company_fields": COMPANY, "agents_read": 1}).ok,
      "freelancer: setup: office settings, agents may read office data")


def fr_switch(ag):
    check(Fr.patch(B + f"{O}/agents/{ag}", json={"office_drafts": True}).ok, "freelancer: setup: her agent's office switch")


FAG, FAH = restriction_case(Fr, "freelancer", "private", {"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read", "office"]},
                 fr_switch)
FD = upload(Fr, "private", "hotel.txt", "Hotel Beispiel\nRechnung 4711\n2 Naechte 240,00 EUR\nMwSt 7 %\n")
check(Fr.post(B + f"/api/files/nodes/{FD}/shares", json={"agent_id": FAG, "role": "view"}).ok, "freelancer: setup: shared with her agent")
FJ = read_job(Fr, FAH, FAG, FD)
r = Fr.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0"]})
check(r.ok and amount(Fr, FD) == "119.00", f"freelancer: #3247 her own office (no office groups): taken over as before ({r.status_code} {r.text[:120]})")
r = Fr.post(B + f"/api/proposals/{FJ}/undo")
check(r.ok and r.json().get("undone") == 1, f"freelancer: undo as before ({r.text[:120]})")
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
