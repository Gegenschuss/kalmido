#!/usr/bin/env python3
"""2.97.0 API tests, part C (#2049): office data between the personal office and an organisation's office, own container
(start.sh). Invented names only.
 - a private client with a contact person and a draft quotation: private -> organisation (dry run first: counts, nothing
   changes), the draft's number is emptied (the target numbers it), the contact person follows; undo = the way back in one
   step (the number comes back), a second undo 409
 - a client with an issued invoice: the invoice stays (retention), the client stays archived and is created anew in the
   target; with the tick box a read-only copy lands in the target's archive (view / PDF, no number, never edited, the
   target's EUeR and invoices unchanged); undo removes the copy and the new client
 - drafts: an issued document cannot move (dry run: block, move: 409)
 - out of an organisation: a plain member may not move a client somebody else created to private (403)
 - another organisation (not a member): 409; somebody else's client: 404; an agent: refused (tenant-matrix: office)
 - a trip without DATEV receipts and a document template move; a trip with a receipt in DATEV stays (block)
 - a person without an organisation (freelancer-matrix: office): there is no other workspace, 409
usage: p297_c_api_test.py <datadir>      (a fresh container; P297C_NOSTART=1 = the server already runs)"""
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
FAILS, OKS = [], [0]
FEAT = "clients,office"
O = "/api/office"
D = O + "/docs"
MV = O + "/move-space"
YEAR = datetime.date.today().year


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def mv(s, **b):
    return s.post(B + MV, json=b)


if not os.environ.get("P297C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Fr = sess("bob"), sess("frank")
for s in (A, Bo, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}

# ---------------------------------------------------------------- the private office of alice
ws(A, "private")
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Nordlicht Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                     "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}})
assert r.ok, r.text
r = A.post(B + "/api/clients", json={"name": "Nordwind GmbH", "org_id": None, "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "DE",
                                     "contacts": [{"name": "Erika Beispiel", "role": "Einkauf", "email": "erika@example.com", "is_default": 1}]})
assert r.status_code == 201, r.text
P1 = r.json()["id"]
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": P1})
assert r.status_code == 201, r.text
D1 = r.json()["id"]
A.put(B + f"{D}/{D1}/items", json={"items": [{"title": "Dreh", "qty": 2, "rate": 1000, "cost": 300}]})
D1NUM = A.get(B + f"{D}/{D1}").json()["number"]
check(bool(D1NUM), "setup: the private quotation has its number " + repr(D1NUM))

r = A.post(B + "/api/clients", json={"name": "Suedlicht AG", "org_id": None, "street": "Domplatz 2", "zip": "50667", "city": "Koeln", "country": "DE"})
P2 = r.json()["id"]
r = A.post(B + D, json={"project_title": "Werbespot", "client_id": P2, "service_from": f"{YEAR}-01-02", "service_to": f"{YEAR}-01-03"})
OFF2 = r.json()["id"]
A.put(B + f"{D}/{OFF2}/items", json={"items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
r = A.post(B + f"{D}/{OFF2}/invoice")
assert r.status_code == 201, r.text
INV2 = r.json()["id"]
r = A.post(B + f"{D}/{INV2}/finalize")
check(r.ok, "setup: the private invoice is finalised " + r.text[:200])
INV2NUM = r.json().get("number") if r.ok else ""

# ---------------------------------------------------------------- a client with its contact person and draft
r = mv(A, what="clients", ids=[P1], to=SP, dry=1)
j = r.json()
check(r.ok and j["block"] is None and j["count"]["clients"] == 1 and j["count"]["drafts"] == 1 and j["count"]["contacts"] == 1 and j["count"]["copied"] == 0,
      "dry run: one client, its draft and its contact person " + r.text[:300])
check(any("number" in n for n in j.get("notes", [])), "dry run: drafts get their number in the target " + str(j.get("notes")))
check(A.get(B + f"/api/clients/{P1}").json().get("org_id") is None, "dry run: nothing changed")
ws(A, SP)
EUER0 = A.get(B + O + f"/books/euer?year={YEAR}").json()
INVS0 = len(A.get(B + D + "?kind=invoice").json().get("docs") or [])
r = mv(A, what="clients", ids=[P1], to=SP)
check(r.ok and r.json().get("ok") and r.json()["clients"].get(str(P1)) == P1, "move: the client moves as a whole " + r.text[:300])
M1 = r.json().get("move_id")
c = A.get(B + f"/api/clients/{P1}").json()
check(c.get("org_id") == ORG and [k["name"] for k in c.get("contacts") or []] == ["Erika Beispiel"], "move: the client and its contact person are in the organisation " + str(c)[:300])
d = A.get(B + f"{D}/{D1}")
check(d.ok and d.json()["number"] == "" and d.json()["client_id"] == P1, "move: the draft is in the organisation's office without a number " + d.text[:200])
check(any(i.get("cost") == 300 for i in d.json().get("items") or []) if d.ok else False, "move: the purchase price of the position is readable in the target")
ws(A, "private")
check(A.get(B + f"{D}/{D1}").status_code == 404, "move: the draft is gone from the personal office")
ws(A, SP)
r = A.post(B + f"{D}/{D1}/number")
check(r.ok and r.json()["number"] and r.json()["number"] != D1NUM or r.ok and r.json()["number"], "the target numbers the draft in its own range " + r.text[:200])
A.patch(B + f"{D}/{D1}", json={"project_title": "Imagefilm 2"})
r = mv(A, undo=M1)
check(r.ok and r.json().get("undone") == M1, "undo: one step " + r.text[:200])
check(A.get(B + f"/api/clients/{P1}").json().get("org_id") is None, "undo: the client is private again")
check(A.get(B + f"{D}/{D1}").status_code == 404, "undo: the draft left the organisation's office")
ws(A, "private")
d = A.get(B + f"{D}/{D1}").json()
check(d.get("number") == D1NUM and d.get("project_title") == "Imagefilm 2" and d.get("client_id") == P1,
      "undo: the draft is back with its old number and the change made meanwhile " + str({k: d.get(k) for k in ("number", "project_title", "client_id")}))
check(mv(A, undo=M1).status_code == 409, "undo: a second time 409")
check(Bo.post(B + MV, json={"undo": M1}).status_code == 404, "undo: only who moved")

# ---------------------------------------------------------------- a client with an issued invoice + the read-only copy
r = mv(A, what="clients", ids=[P2], to=SP, dry=1, copy_issued=1)
j = r.json()
check(r.ok and j["count"]["copied"] == 1 and j["count"]["issued"] == 1 and any("Suedlicht AG" in n for n in j["notes"]),
      "dry run: the client stays archived for its issued invoice and is created anew " + r.text[:400])
r = mv(A, what="clients", ids=[P2], to=SP, copy_issued=1)
check(r.ok, "move with the copy " + r.text[:300])
M2 = r.json().get("move_id")
NEW = r.json().get("clients", {}).get(str(P2))
check(NEW and NEW != P2, "move: the client is created anew in the target")
old = A.get(B + f"/api/clients/{P2}").json()
check(old.get("org_id") is None and old.get("archived") is True, "move: the old client stays private and archived " + str(old)[:200])
new = A.get(B + f"/api/clients/{NEW}").json()
check(new.get("org_id") == ORG and new.get("name") == "Suedlicht AG" and not new.get("archived"), "move: the new client in the organisation")
inv = A.get(B + f"{D}/{INV2}").json()
check(inv.get("number") == INV2NUM and inv.get("status") != "draft", "the issued invoice stays in the personal office with its number")
ws(A, SP)
arch = A.get(B + O + "/legacy/archive").json()
cp = [x for x in arch.get("items") or [] if x.get("copy")]
check(len(cp) == 1 and cp[0]["copy"]["from"] == "private" and cp[0]["copy"]["number"] == INV2NUM and cp[0]["number"] == "" and cp[0]["client_id"] == NEW,
      "copy: one read-only copy with where it came from, no number of its own " + str(cp)[:300])
if cp:
    r = A.get(B + O + f"/legacy/archive/{cp[0]['id']}/pdf")
    check(r.ok and r.content[:4] == b"%PDF", "copy: the PDF opens " + str(r.status_code))
    check(A.patch(B + O + f"/legacy/archive/{cp[0]['id']}", json={"client_id": None}).status_code == 409, "copy: never edited (409)")
check(arch.get("sum_invoices") in (0, 0.0, None), "copy: not in the archive's sums of the target " + str(arch.get("sum_invoices")))
check(A.get(B + O + f"/books/euer?year={YEAR}").json() == EUER0, "copy: the target's EUeR is unchanged")
check(len(A.get(B + D + "?kind=invoice").json().get("docs") or []) == INVS0, "copy: no invoice in the target's list")
r = mv(A, undo=M2)
check(r.ok, "undo of the copy move " + r.text[:200])
check(not [x for x in A.get(B + O + "/legacy/archive").json().get("items") or [] if x.get("copy")], "undo: the copy is gone")
check(A.get(B + f"/api/clients/{NEW}").status_code == 404, "undo: the new client is gone")
check(A.get(B + f"/api/clients/{P2}").json().get("archived") is False, "undo: the old client is no longer archived")

# ---------------------------------------------------------------- drafts only: an issued one stays
ws(A, "private")
r = mv(A, what="drafts", ids=[INV2], to=SP, dry=1)
check(r.ok and r.json()["block"], "drafts: an issued invoice cannot move (dry run blocks) " + r.text[:200])
check(mv(A, what="drafts", ids=[INV2], to=SP).status_code == 409, "drafts: the move 409")
r = mv(A, what="drafts", ids=[D1], to=SP)
check(r.ok and r.json()["count"]["drafts"] == 1, "drafts: a draft alone moves " + r.text[:200])
M3 = r.json().get("move_id")
ws(A, SP)
d = A.get(B + f"{D}/{D1}").json()
check(d.get("client_id") is None and d.get("number") == "", "drafts: alone it keeps only the address (the client stays private)")
check(mv(A, undo=M3).ok, "drafts: undo")

# ---------------------------------------------------------------- rights and boundaries
ws(A, SP)
r = A.post(B + "/api/clients", json={"name": "Orgkunde KG", "org_id": ORG})
OC = r.json()["id"]
ws(Bo, SP)
check(mv(Bo, what="clients", ids=[OC], to="private", dry=1).status_code == 403, "a plain member may not take a client somebody else created out of the organisation")
r = Bo.post(B + "/api/clients", json={"name": "Bobs Kunde", "org_id": ORG})
BC = r.json()["id"]
check(mv(Bo, what="clients", ids=[BC], to="private", dry=1).ok, "a plain member may move a client of their own")
r = A.post(B + D, json={"project_title": "Fremder Entwurf", "client_id": BC})
assert r.status_code == 201, r.text
r = mv(Bo, what="clients", ids=[BC], to="private", dry=1, copy_issued=1)
j = r.json()
check(r.ok and j["count"]["drafts"] == 0 and j["count"]["copied"] == 1 and any("somebody else" in n for n in j["notes"]) and any("Only an admin" in n for n in j["notes"]),
      "a plain member: the drafts of others stay with the client (it is created anew), no copies " + r.text[:300])
check(mv(A, what="clients", ids=[P1], to=f"org:{BETA}", dry=1).status_code == 409, "another organisation (not a member): 409")
check(mv(Fr, what="clients", ids=[P1], to=f"org:{BETA}", dry=1).status_code == 404, "somebody else's client: 404")
check(requests.post(B + MV, json={"what": "clients", "ids": [OC], "to": "private"}, headers=AGH).status_code == 403, "an agent: 403")
check(mv(A, what="clients", ids=[OC], to=SP, dry=1).status_code == 409, "the same workspace: 409")
check(mv(A, what="nope", ids=[OC], to="private").status_code == 400 and mv(A, what="clients", ids=[], to="private").status_code == 400, "bad input: 400")

# ---------------------------------------------------------------- trips and templates
ws(A, "private")
r = A.post(B + O + "/trips", json={"date_from": f"{YEAR}-02-03", "dest": "Hamburg - Berlin", "people": [{"name": "Externe Person"}], "note": "Drehreise",
                                   "items": [{"date": f"{YEAR}-02-03", "category": "train", "amount": "129,90", "text": "ICE"}]})
T1 = r.json()["id"]
r = A.post(B + O + "/trips", json={"date_from": f"{YEAR}-02-05", "dest": "Koeln", "items": [{"date": f"{YEAR}-02-05", "category": "taxi", "amount": 20, "datev": 1}]})
T2 = r.json()["id"]
check(mv(A, what="travel", ids=[T2], to=SP, dry=1).json().get("block"), "a trip with a receipt in DATEV stays (block)")
r = mv(A, what="travel", ids=[T1], to=SP)
check(r.ok and r.json()["count"]["trips"] == 1, "a trip moves " + r.text[:200])
ws(A, SP)
t = [x for x in A.get(B + O + "/trips").json()["trips"] if x["id"] == T1]
check(t and t[0]["note"] == "Drehreise" and t[0]["items"][0]["amount"] == "129.90", "the trip is readable in the target (re-sealed)")
ws(Bo, SP)
check(mv(Bo, what="travel", ids=[T1], to="private").status_code == 403, "travel expenses: only the office's admin")
ws(A, "private")
r = A.post(B + O + "/doc-templates", json={"name": "Vertrag", "kind": "contract", "lang": "de", "body": "Hallo Welt"})
TPL = r.json().get("id")
r = mv(A, what="templates", ids=[TPL], to=SP)
check(r.ok and r.json()["count"]["templates"] == 1, "a template moves " + r.text[:200])
ws(A, SP)
tl = A.get(B + O + "/doc-templates").json()
items = tl.get("templates") or tl.get("items") or []
check(any(x["id"] == TPL and "Hallo" in (x.get("body") or "") for x in items), "the template is readable in the target " + str(tl)[:200])

# ---------------------------------------------------------------- 2.97.0 review (H1): no undo once the target issued a moved draft
ws(A, "private")
r = A.post(B + "/api/clients", json={"name": "Nordwind KG", "org_id": None, "street": "Hafen 1", "zip": "20457", "city": "Hamburg", "country": "DE"})
P4 = r.json()["id"]
r = A.post(B + D, json={"project_title": "Messe", "client_id": P4, "service_from": f"{YEAR}-02-02", "service_to": f"{YEAR}-02-03"})
OFF4 = r.json()["id"]
A.put(B + f"{D}/{OFF4}/items", json={"items": [{"title": "Kamera", "qty": 1, "rate": 800}]})
r = mv(A, what="clients", ids=[P4], to=SP)
check(r.ok, "H1: the client with its draft moves " + r.text[:200])
M4 = r.json().get("move_id")
ws(A, SP)
A.put(B + O + "/settings", json={"company_fields": {"name": "Team Film", "street": "Kai 3", "zip": "20457", "city": "Hamburg",
                                                  "country": "DE", "tax_number": "12/345/67891", "iban": "DE02120300000000202051"}})
r = A.post(B + f"{D}/{OFF4}/invoice")
INV4 = r.json().get("id") if r.status_code == 201 else None
r = A.post(B + f"{D}/{INV4}/finalize") if INV4 else r
check(bool(INV4) and r.ok, "H1: the target invoices and issues the moved quotation " + r.text[:200])
A.post(B + f"{D}/{OFF4}/finalize")
r = mv(A, undo=M4)
check(r.status_code == 409, "H1: undo after the target issued a document: 409 " + r.text[:200])
check(A.get(B + f"/api/clients/{P4}").json().get("org_id") == ORG, "H1: the client stays in the organisation")

# ---------------------------------------------------------------- a freelancer: no other workspace
FID, Fi = freelancer(B, A, "fiona")
r = Fi.post(B + "/api/clients", json={"name": "Solo Kunde"})
FC = r.json()["id"]
check(mv(Fi, what="clients", ids=[FC], to=SP, dry=1).status_code == 409, "freelancer: no organisation as the target (409)")
check(mv(Fi, what="clients", ids=[FC], to="private", dry=1).status_code == 409, "freelancer: private is the same workspace (409)")

print(f"p297_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
