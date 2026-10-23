#!/usr/bin/env python3
"""2.119.1 API tests, part C (#2298): framework contracts with their PDF files between the personal office and an
organisation's office (POST /api/office/move-space what=contracts), own container (start.sh). Invented names only.
 - a person without an organisation (freelancer-matrix: office): no other workspace (409); once admin of an organisation
   of their own: private -> organisation (dry run first), the PDF readable there, the rights text block copied along, the
   draft pointing at the contract loses the link; undo = all back (file readable in private again, the link back, the
   copied text block gone); the move again and back as a new move (organisation -> private)
 - a contract an issued invoice points at: stays archived in the old office (the invoice keeps it), a copy with copies
   of its files is created in the target; undo removes the copy and takes the archiving back
 - a plain member of the organisation may not move its contracts (403); somebody else's contract 404; an agent refused
usage: p21191_c_api_test.py <datadir>      (a fresh container; P21191C_NOSTART=1 = the server already runs)"""
import datetime
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "clients,office"
O = "/api/office"
D = O + "/docs"
MV = O + "/move-space"
YEAR = datetime.date.today().year


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def mv(s, **b):
    return s.post(B + MV, json=b)


def pdf(tag):
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n% " + tag.encode()
            + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def up(s, cid, data, name="Vertrag.pdf"):
    return s.post(B + f"{O}/contracts/{cid}/files", files={"file": (name, data, "application/pdf")})


def contracts(s):
    return {r["id"]: r for r in s.get(B + O + "/contracts?archived=1").json().get("items") or []}


def files(s, cid):
    r = s.get(B + f"{O}/contracts/{cid}/files")
    return r.json().get("items") if r.ok else None


def content(s, cid, fid):
    r = s.get(B + f"{O}/contracts/{cid}/files/{fid}")
    return r.content if r.ok else None


if not os.environ.get("P21191C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}

# ================================================================ a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
ws(Fr, "private")
r = Fr.post(B + O + "/texts", json={"kind": "rights_time", "key": "5y", "text_de": "Fuenf Jahre ab Abnahme.", "text_en": "Five years from acceptance."})
assert r.status_code in (200, 201), r.text
T1 = r.json()["id"]
r = Fr.post(B + O + "/contracts", json={"name": "Rahmenvertrag Agentur Nord", "rights_time_id": T1, "rates": {}})
assert r.status_code in (200, 201), r.text
CF = r.json()["id"]
check(up(Fr, CF, pdf("signed"), "Vertrag unterschrieben.pdf").status_code == 201, "setup: the PDF of the private contract")
FF = files(Fr, CF)[0]["id"]
r = Fr.post(B + D, json={"project_title": "Imagefilm", "contract_id": CF})
assert r.status_code == 201, r.text
DF = r.json()["id"]
check(Fr.get(B + f"{D}/{DF}").json().get("contract_id") == CF, "setup: the draft points at the contract")
r = mv(Fr, what="contracts", ids=[CF], to="org:999999", dry=1)
check(r.status_code == 409, "freelancer without an organisation: no other workspace 409 " + r.text[:200])

r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": FID})
assert r.status_code in (200, 201), r.text
GAM = r.json()["id"]
GS = f"org:{GAM}"
ws(Fr, "private")
r = mv(Fr, what="contracts", ids=[CF], to=GS, dry=1)
j = r.json()
check(r.ok and j["block"] is None and j["count"]["contracts"] == 1, "dry run: one contract " + r.text[:300])
check(any("framework contract moves" in n for n in j.get("notes", [])) and any("draft loses its framework contract" in n for n in j.get("notes", [])),
      "dry run: names the contract with its files and the draft that loses the link " + str(j.get("notes")))
check(CF in contracts(Fr), "dry run: nothing changed")
r = mv(Fr, what="contracts", ids=[CF], to=GS)
check(r.ok and r.json().get("ok") and r.json().get("space") == GS, "move: private -> organisation " + r.text[:300])
M1 = r.json().get("move_id")
check(CF not in contracts(Fr), "move: gone from the personal office")
ws(Fr, GS)
cg = contracts(Fr).get(CF)
check(cg is not None and cg["name"] == "Rahmenvertrag Agentur Nord", "move: the contract is in the organisation's office (same id)")
fl = files(Fr, CF) or []
check([f["id"] for f in fl] == [FF] and fl[0]["name"] == "Vertrag unterschrieben.pdf", "move: its PDF file goes along " + str(fl)[:200])
check(content(Fr, CF, FF) == pdf("signed"), "move: the PDF is readable in the organisation (sealed with its key)")
tg = {t["id"]: t for t in Fr.get(B + O + "/texts").json().get("items") or []}
check(cg and cg.get("rights_time_id") and cg["rights_time_id"] != T1 and tg.get(cg["rights_time_id"], {}).get("text_en") == "Five years from acceptance.",
      "move: the rights text block is copied into the organisation " + str(cg)[:300])
T1G = cg.get("rights_time_id") if cg else None
# 2.119.1 review F8: a PDF added in the target after the move goes back with the undo (readable in private again)
r = up(Fr, CF, pdf("added"), "Nachtrag.pdf")
check(r.status_code == 201, "F8: a PDF added in the organisation " + r.text[:200])
FN = r.json().get("id") if r.ok else 0
ws(Fr, "private")
check(Fr.get(B + f"{D}/{DF}").json().get("contract_id") is None, "move: the draft lost the link")
check(files(Fr, CF) is None, "move: the personal office no longer reaches the contract's files (404)")

r = mv(Fr, undo=M1)
check(r.ok and r.json().get("undone") == M1, "undo " + r.text[:300])
check(CF in contracts(Fr) and contracts(Fr)[CF].get("rights_time_id") == T1, "undo: the contract is back with its rights text block")
check(content(Fr, CF, FF) == pdf("signed"), "undo: the PDF is readable in private again")
check(FN in [f["id"] for f in files(Fr, CF) or []] and content(Fr, CF, FN) == pdf("added"), "undo F8: the PDF added since comes along " + str(files(Fr, CF))[:200])
check(Fr.get(B + f"{D}/{DF}").json().get("contract_id") == CF, "undo: the draft points at it again")
ws(Fr, GS)
check(CF not in contracts(Fr) and T1G not in {t["id"] for t in Fr.get(B + O + "/texts").json().get("items") or []},
      "undo: the organisation has neither the contract nor the copied text block")
check(mv(Fr, undo=M1).status_code == 409, "undo twice: 409")
ws(Fr, "private")
r = mv(Fr, what="contracts", ids=[CF], to=GS)
check(r.ok, "the move again " + r.text[:200])
ws(Fr, GS)
r = mv(Fr, what="contracts", ids=[CF], to="private")
check(r.ok and r.json().get("space") == "private", "and back as a new move: organisation -> private " + r.text[:300])
ws(Fr, "private")
check(CF in contracts(Fr) and content(Fr, CF, FF) == pdf("signed"), "back in private: the PDF readable")

# ================================================================ a contract with an issued invoice: stays archived, a copy moves
ws(A, "private")
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Nordlicht Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                     "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}})
assert r.ok, r.text
CA = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag Sued"}).json()["id"]
check(up(A, CA, pdf("sued")).status_code == 201, "setup: a PDF")
r = A.post(B + "/api/clients", json={"name": "Suedlicht AG", "org_id": None, "street": "Domplatz 2", "zip": "50667", "city": "Koeln", "country": "DE"})
CL = r.json()["id"]
r = A.post(B + D, json={"project_title": "Werbespot", "client_id": CL, "contract_id": CA, "service_from": f"{YEAR}-01-02", "service_to": f"{YEAR}-01-03"})
OFF = r.json()["id"]
A.put(B + f"{D}/{OFF}/items", json={"items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
r = A.post(B + f"{D}/{OFF}/invoice")
assert r.status_code == 201, r.text
INV = r.json()["id"]
A.patch(B + f"{D}/{INV}", json={"contract_id": CA})
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "setup: the invoice is issued " + r.text[:200])
INV_CT = A.get(B + f"{D}/{INV}").json().get("contract_id")
r = mv(A, what="contracts", ids=[CA], to=SP, dry=1)
check(r.ok and any("stays archived in the old workspace" in n for n in r.json().get("notes", [])), "dry run: stays archived, created anew " + r.text[:300])
r = mv(A, what="contracts", ids=[CA], to=SP)
check(r.ok, "move with an issued invoice " + r.text[:200])
M2 = r.json().get("move_id")
check(contracts(A).get(CA, {}).get("archived") == 1 and A.get(B + f"{D}/{INV}").json().get("contract_id") == INV_CT,
      "the source contract stays archived, the invoice keeps it")
ws(A, SP)
cp = [x for x in contracts(A).values() if x["name"] == "Rahmenvertrag Sued"]
check(len(cp) == 1 and cp[0]["id"] != CA and not cp[0]["archived"], "a copy in the organisation " + str(cp)[:200])
fl = files(A, cp[0]["id"]) if cp else []
check(len(fl or []) == 1 and content(A, cp[0]["id"], fl[0]["id"]) == pdf("sued"), "the copy has a readable copy of the PDF")
ws(A, "private")
check(content(A, CA, files(A, CA)[0]["id"]) == pdf("sued"), "the source keeps its PDF")
r = mv(A, undo=M2)
check(r.ok, "undo of the copy " + r.text[:200])
check(contracts(A).get(CA, {}).get("archived") == 0, "undo: the source contract is no longer archived")
ws(A, SP)
check(not [x for x in contracts(A).values() if x["name"] == "Rahmenvertrag Sued"], "undo: the copy is gone")

# ================================================================ rights
CO = A.post(B + O + "/contracts", json={"name": "Vertrag der Organisation"}).json()["id"]
ws(Bo, SP)
r = mv(Bo, what="contracts", ids=[CO], to="private", dry=1)
check(r.status_code == 403, "a plain member may not move the organisation's contracts " + str(r.status_code))
ws(Fr, "private")
r = mv(Fr, what="contracts", ids=[CO], to=GS, dry=1)
check(r.status_code == 404, "somebody else's contract 404 " + str(r.status_code))
r = requests.post(B + MV, json={"what": "contracts", "ids": [CO], "to": "private", "dry": 1}, headers=AGH)
check(r.status_code == 403, "an agent: refused " + str(r.status_code))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
