#!/usr/bin/env python3
"""2.47.3 API tests (part A): Office & finance without an organisation (#1360), own container (start.sh).

 - a freelancer on a server without any organisation: the personal office (a hidden area, the person is its admin):
   settings, company fields, private clients, a quotation, an invoice from it, finalised with its number, PDF and e-invoice
 - small business (section 19 UStG): new documents without VAT, the note on the quotation, the e-invoice with category E
   and the exemption reason; also for an organisation's office (one setting of the area)
 - the hidden area never shows as an organisation (admin list, own workspaces, agent workspace, client workspace)
 - a second person sees nothing of it (every route 404 / empty; row-level security with the second person's context)
 - a person with one organisation: "Private" = the personal office, the organisation's workspace = its office, separate
   clients (no silent fallback to the only organisation); the empty personal office points to the organisation's office
 - agents never reach it; the move into a new organisation (one way: confirmation, only the owner, instance admin) keeps
   documents, numbers and clients; afterwards "Private" is a new, empty personal office
 - mode shared (no organisations): the personal office, strictly per person
usage: p2473_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "clients,office"
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"


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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def user(name, orgs=None):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", **({"orgs": orgs} if orgs else {})})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    return r.json()["id"], s


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


if not os.environ.get("KMT_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"]})  # no organisation: a freelancer's server
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
BOB, Bo = user("bob")

# ================================================================== a freelancer without any organisation
r = A.get(B + O + "/settings")
check(r.ok, "freelancer: the office opens without an organisation " + r.text[:200])
S0 = r.json() if r.ok else {}
PA = S0.get("org_id")
check(S0.get("personal") == 1 and S0.get("role") == "admin" and S0.get("org_offices") == [], "freelancer: the personal office, its own admin " + str({k: S0.get(k) for k in ("personal", "role", "org_offices")}))
check(dbx("SELECT personal_of FROM orgs WHERE id=?", (PA,))[0][0] == ALICE, "freelancer: a hidden area of alice")
check(dbx("SELECT COUNT(*) FROM org_members WHERE org_id=?", (PA,))[0][0] == 0, "freelancer: the hidden area has no members")
check(A.get(B + "/api/admin/orgs").json()["orgs"] == [], "hidden: not in the admin's organisation list")
check(A.get(B + "/api/me").json().get("workspaces") in ([], None), "hidden: not among the own workspaces")
check(A.post(B + "/api/admin/orgs", json={"name": "private-" + str(ALICE)}).status_code == 201, "hidden: its name does not block an organisation of that name")
NAMED = A.get(B + "/api/admin/orgs").json()["orgs"]
check(len(NAMED) == 1 and all(o["id"] != PA for o in NAMED), "hidden: the admin list shows only the real organisation")
check(A.patch(B + f"/api/admin/orgs/{PA}", json={"name": "x"}).status_code == 404 and A.delete(B + f"/api/admin/orgs/{PA}").status_code == 404,
      "hidden: the admin cannot rename or delete it as an organisation")
check(A.post(B + "/api/clients", json={"name": "x", "org_id": PA}).status_code == 400, "hidden: no client can be put into it by id")
A.delete(B + f"/api/admin/orgs/{NAMED[0]['id']}")
check(A.get(B + "/api/me").json().get("workspaces") in ([], None), "setup: alice has no organisation again")

r = A.put(B + O + "/settings", json={"lang": "de", "company_fields": {"name": "Nordlicht Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                                     "country": "DE", "tax_number": "12/345/67890", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                                     "bank_name": "Beispielbank"}})
check(r.ok and r.json()["company_fields"]["tax_number"] == "12/345/67890", "freelancer: company fields (tax number, bank) " + r.text[:200])
r = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
assert r.status_code == 201, r.text
CL = r.json()["id"]
check(r.json().get("org_id") is None, "freelancer: the client is a private client")
check(A.post(B + O + "/services", json={"name_de": "Schnitt", "unit": "day", "rate": 600}).status_code == 201, "freelancer: master data (a service)")
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": CL, "service_from": "2026-09-01", "service_to": "2026-09-30"})
check(r.status_code == 201, "freelancer: a quotation for the private client " + r.text[:200])
OFF = r.json()["id"]
check(A.put(B + f"{D}/{OFF}/items", json={"items": [{"title": "Dreh", "qty": 2, "rate": 1000}]}).ok, "freelancer: positions")
q = A.get(B + f"{D}/{OFF}").json()
check(q["totals"]["net"] == 2000 and q["totals"]["gross"] == 2380, "freelancer: 19 % VAT by default " + str(q["totals"].get("gross")))
r = A.post(B + f"{D}/{OFF}/invoice")
check(r.status_code == 201, "freelancer: an invoice from the quotation " + r.text[:200])
INV = r.json()["id"]
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json()["number"].startswith("RE-"), "freelancer: finalised with its number " + r.text[:200])
r = A.get(B + f"{D}/{INV}/pdf")
check(r.ok and r.content[:4] == b"%PDF", "freelancer: the PDF " + str(r.status_code))
r = A.get(B + f"{D}/{INV}/xml")
check(r.ok and b"CrossIndustryInvoice" in r.content and b"Nordlicht Film" in r.content, "freelancer: the e-invoice " + str(r.status_code))
check(any(x["action"] in ("pdf", "open", "render", "xml") for x in A.get(B + f"{D}/{INV}/log").json().get("items", A.get(B + f"{D}/{INV}/log").json().get("log", []))),
      "freelancer: the access log records the reads")

# ---- small business (section 19 UStG)
check(A.put(B + O + "/settings", json={"small_business": 1}).ok, "section 19: switched on")
check(A.get(B + O + "/settings").json()["settings"]["small_business"] == 1, "section 19: stored")
r = A.post(B + D, json={"project_title": "Kleinunternehmer", "client_id": CL, "service_from": "2026-09-01", "service_to": "2026-09-30"})
SB = r.json()["id"]
A.put(B + f"{D}/{SB}/items", json={"items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
q = A.get(B + f"{D}/{SB}").json()
check(q["vat_mode"] == "novat" and q["totals"]["gross"] == 500 and q["totals"].get("tax_total", 0) == 0, "section 19: a new quotation without VAT " + str(q["totals"]))
check("§ 19 UStG" in (q["totals"].get("vat_note") or ""), "section 19: the note on the quotation " + str(q["totals"].get("vat_note")))
r = A.post(B + f"{D}/{SB}/invoice")
SBI = r.json()["id"]
i = A.get(B + f"{D}/{SBI}").json()
check(i["vat_mode"] == "novat" and i.get("vat_note") == "small", "section 19: the invoice has the exemption note " + str((i.get("vat_mode"), i.get("vat_note"))))
r = A.post(B + f"{D}/{SBI}/finalize")
check(r.ok, "section 19: the invoice finalises " + r.text[:200])
x = A.get(B + f"{D}/{SBI}/xml").content.decode("utf-8", "replace")
check("<ram:CategoryCode>E</ram:CategoryCode>" in x and "§ 19 UStG" in x, "section 19: e-invoice with category E and the reason")
check(A.get(B + f"{D}/{SBI}/pdf").ok, "section 19: the PDF")
A.put(B + O + "/settings", json={"small_business": 0})

# ================================================================== a second person sees nothing of it
r = Bo.get(B + O + "/settings")
PB = r.json().get("org_id")
check(r.ok and r.json()["personal"] == 1 and PB and PB != PA, "second person: an own personal office")
check(Bo.get(B + D).json().get("docs") == [], "second person: no documents")
check(Bo.get(B + O + "/services").json()["items"] == [], "second person: no master data")
for path in (f"{D}/{OFF}", f"{D}/{INV}/pdf", f"{D}/{INV}/xml", f"{D}/{INV}/log", f"{D}/{INV}/payments"):
    check(Bo.get(B + path).status_code == 404, "second person: 404 on " + path)
check(Bo.patch(B + f"{D}/{OFF}", json={"project_title": "x"}).status_code == 404 and Bo.delete(B + f"{D}/{OFF}").status_code == 404, "second person: no writes")
check(Bo.post(B + D, json={"client_id": CL}).status_code == 404, "second person: alice's private client is not usable")
check(all(c["id"] != CL for c in Bo.get(B + "/api/clients").json()["clients"]), "second person: alice's client is not listed")
# row-level security: bob's context reads none of alice's office rows (the app role, as every request does)


def as_ctx(uid, oids, sql):
    q = (f"BEGIN; SET LOCAL ROLE kalmido_app; SELECT set_config('app.role','user',true), set_config('app.user_id','{uid}',true), "
         f"set_config('app.org_ids','{oids}',true); {sql}; COMMIT;")
    p = subprocess.run(["docker", "exec", open(os.path.join(DATA, ".kalmido-db")).read().split()[0], "psql", "-U", "kalmido", "-d",
                        open(os.path.join(DATA, ".kalmido-db")).read().split()[1], "-Atqc", q], capture_output=True, text=True)
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr


check(as_ctx(BOB, PB, "SELECT COUNT(*) FROM office_docs") == "0", "RLS: bob's context sees no office document")
check(as_ctx(ALICE, PA, "SELECT COUNT(*) FROM office_docs") not in ("0", ""), "RLS: alice's context sees hers")
check(as_ctx(BOB, PB, f"SELECT COUNT(*) FROM orgs WHERE id={PA}") == "0", "RLS: bob does not see alice's hidden area")

# ---- agents never reach it
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "claude", "display_name": "Claude"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(requests.get(B + O + "/settings", headers=AG).status_code in (401, 403), "agent: no office")
AGID = r.json()["id"]
r = A.patch(B + f"/api/admin/agents/{AGID}", json={"org_id": PA})
check(dbx("SELECT org_id FROM agents WHERE user_id=?", (AGID,))[0][0] is None, f"agent: never in a personal office's workspace {r.status_code}")

# ================================================================== one organisation: Private and the organisation are separate
r = A.post(B + "/api/admin/orgs", json={"name": "Studio", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
CAROL, Ca = user("carol", [ORG])
r = A.patch(B + f"/api/admin/agents/{AGID}", json={"org_id": PA})
check(r.status_code == 400 and dbx("SELECT org_id FROM agents WHERE user_id=?", (AGID,))[0][0] is None, f"agent: a personal office is no workspace for an agent {r.status_code}")
ws(A, "private")
check(A.get(B + O + "/settings").json()["org_id"] == PA, "private: alice keeps her personal office (no fallback to the only organisation)")
ws(A, f"org:{ORG}")
r = A.get(B + O + "/settings")
check(r.json()["org_id"] == ORG and r.json()["personal"] == 0 and r.json()["role"] == "admin", "organisation: its office")
r = A.post(B + "/api/clients", json={"name": "Studio-Kunde GmbH", "org_id": ORG})
OCL = r.json()["id"]
check(A.post(B + D, json={"client_id": CL}).status_code == 404, "organisation: alice's private client is not a client of the organisation")
r = A.post(B + D, json={"client_id": OCL, "project_title": "Org"})
check(r.status_code == 201, "organisation: a quotation for the organisation's client")
ODOC = r.json()["id"]
check({d["id"] for d in A.get(B + D).json()["docs"]} == {ODOC}, "organisation: only its documents")
ws(A, "private")
check(A.post(B + D, json={"client_id": OCL}).status_code == 404, "private: the organisation's client is not usable")
check(ODOC not in {d["id"] for d in A.get(B + D).json()["docs"]} and A.get(B + f"{D}/{ODOC}").status_code == 404, "private: no document of the organisation")
ws(A, "all")
check(A.get(B + O + "/settings").json()["org_id"] == ORG, "all: with one organisation its office (as before)")
# carol (member, nothing personal yet) in Private: the hint to the organisation's office
ws(Ca, "private")
r = Ca.get(B + O + "/settings")
check(r.ok and r.json()["personal"] == 1 and r.json()["org_offices"] == [{"id": ORG, "name": "Studio"}], "hint: the empty personal office names the organisation " + r.text[-200:])
ws(Ca, f"org:{ORG}")
check(Ca.get(B + O + "/settings").json()["role"] == "member", "carol: a member of the organisation's office")
check(Ca.get(B + f"{D}/{OFF}").status_code == 404, "carol: nothing of alice's personal office")
check(Ca.post(B + O + "/move", json={"name": "x", "confirm": True}).status_code in (403, 409), "move: not from an organisation's office")
# small business is a setting of an organisation's office too
ws(A, f"org:{ORG}")
check(A.put(B + O + "/settings", json={"small_business": 1}).ok, "section 19: also an organisation's setting")
r = A.post(B + D, json={"client_id": OCL})
check(A.get(B + f"{D}/{r.json()['id']}").json()["vat_mode"] == "novat", "section 19: the organisation's new quotation without VAT")
A.put(B + O + "/settings", json={"small_business": 0})

# ================================================================== the move into a new organisation (one way)
ws(Bo, "private")
check(Bo.post(B + O + "/move", json={"name": "Bobs Firma", "confirm": True}).status_code == 403, "move: only where organisations can be created (instance admin)")
ws(A, "private")
INV_NO = A.get(B + f"{D}/{INV}").json()["number"]
check(A.post(B + O + "/move", json={"name": "Nordlicht"}).status_code == 400, "move: needs the confirmation")
check(A.post(B + O + "/move", json={"name": "Studio", "confirm": True}).status_code == 409, "move: the name of an existing organisation is refused")
r = A.post(B + O + "/move", json={"name": "Nordlicht", "confirm": True})
check(r.ok and r.json()["org_id"] == PA, "move: the area becomes the organisation " + r.text[:200])
check(dbx("SELECT personal_of FROM orgs WHERE id=?", (PA,))[0][0] is None and dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (PA, ALICE))[0][0] == "admin",
      "move: a real organisation with alice as its admin")
check(any(o["id"] == PA for o in A.get(B + "/api/admin/orgs").json()["orgs"]), "move: listed as an organisation now")
r = A.get(B + O + "/settings")
check(r.json()["org_id"] == PA and r.json()["personal"] == 0, "move: alice works in it at once")
check(A.get(B + f"{D}/{INV}").json()["number"] == INV_NO, "move: the invoice keeps its number")
check(dbx("SELECT org_id FROM clients WHERE id=?", (CL,))[0][0] == PA, "move: the private client moved with it")
check(A.get(B + f"{D}/{INV}/xml").ok, "move: the e-invoice still opens (same keys)")
ws(A, "private")
r = A.get(B + O + "/settings")
check(r.json()["personal"] == 1 and r.json()["org_id"] not in (PA, ORG) and A.get(B + D).json()["docs"] == [], "move: Private is a new, empty personal office")

# ================================================================== mode shared: no organisations, strictly per person
if os.environ.get("KMT_NOSTART"):  # a quick local check against a running app: no restart
    print(f"{OKS[0]} ok, {len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)
restart("-e KALMIDO_INSTANCE_MODE=shared")
A, Bo = sess("alice"), sess("bob")
ra, rb = A.get(B + O + "/settings"), Bo.get(B + O + "/settings")
check(ra.ok and rb.ok and ra.json()["personal"] == 1 and rb.json()["personal"] == 1 and ra.json()["org_id"] != rb.json()["org_id"], "shared: everyone has their own office")
check(rb.json()["org_id"] == PB and Bo.get(B + f"{D}/{OFF}").status_code == 404, "shared: bob's office stays his, nothing of others")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
