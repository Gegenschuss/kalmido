#!/usr/bin/env python3
"""2.59.0 API tests (part A).
 - #1735 a client's contact person linked to an address book contact (office_client_contacts.contact_id): only a contact
   of an address book the client's organisation owns (a freelancer's client without an organisation: the person's own
   books), never a private book, a member's book in the workspace or another organisation's; missing contact_id keeps the
   link, null drops it, a colleague who cannot see the book keeps it by sending it back; a token needs the scope contacts;
   the address book search of the client dialog (GET /api/clients/{id}/book-contacts) lists only allowed contacts; the
   contact card shows "contact person at" only to people who may open the client; deleting the contact or its book drops
   only the link (name, e-mail, phone stay); a client moving into another workspace loses its links; the nightly boundary
   check counts a link across the boundary and the repair drops it
tenant-matrix: client
usage: p259_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,collab,comments,events,contacts,clients"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def org_book(s, oid, name):
    r = s.post(B + "/api/books", json={"name": name, "org_id": oid})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    r = s.post(B + f"/api/books/{bid}/org", json={"org_role": "view"})
    assert r.ok, r.text
    return bid


def contact(s, bid, given, family, **kw):
    r = s.post(B + "/api/contacts", json={"book_id": bid, "given": given, "family": family, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def persons(s, cid):
    return s.get(B + f"/api/clients/{cid}").json()["contacts"]


def link_of(kid):
    return dbx("SELECT contact_id, name, email, phone FROM office_client_contacts WHERE id=?", (kid,))[0]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
ids = {}
for u in ("bob", "carol", "dave", "frank"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, FRANK = (ids[k] for k in ("bob", "carol", "dave", "frank"))
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, BOB, CAROL], "admins": [1]}).ok, "setup: Alpha members")
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
S = {u: sess(u) for u in ("alice", "bob", "carol", "dave", "frank")}
A = S["alice"]
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})

# ---- address books: Alpha's own (CT1, CT2), alice's private one, bob's personal book in Alpha's workspace, Beta's own,
# frank's own (no organisation)
BK = org_book(A, ALPHA, "Alpha customers")
CT1 = contact(A, BK, "Petra", "Buyer", title="Head of purchasing", emails=[{"value": "petra@example.com"}], phones=[{"value": "+49 30 1234"}])
CT2 = contact(A, BK, "Paul", "Second")
BK2 = org_book(A, ALPHA, "Alpha partners")
CT3 = contact(A, BK2, "Greta", "Gone")
PB = A.post(B + "/api/books", json={"name": "Private", "org_id": None}).json()["id"]
CTP = contact(A, PB, "Private", "Person")
WB = S["bob"].post(B + "/api/books", json={"name": "Bob in Alpha", "org_id": ALPHA}).json()["id"]
CTW = contact(S["bob"], WB, "Bobs", "Contact")
DB = org_book(S["dave"], BETA, "Beta customers")
CTB = contact(S["dave"], DB, "Beta", "Buyer")
FB = S["frank"].post(B + "/api/books", json={"name": "Frank", "org_id": None}).json()["id"]
CTF = contact(S["frank"], FB, "Fiona", "Freelance", emails=[{"value": "fiona@example.com"}])
check(dbx("SELECT owner_org_id FROM books WHERE id=?", (BK,))[0][0] == ALPHA, "setup: Alpha owns its book")

# ---- the client of Alpha with one contact person
r = A.post(B + "/api/clients", json={"name": "Acme", "org_id": ALPHA, "contacts": [{"name": "Typed Name"}]})
check(r.status_code == 201, f"setup: client in Alpha ({r.status_code} {r.text[:200]})")
CL = r.json()["id"]
K1 = r.json()["contacts"][0]["id"]
check(r.json()["contacts"][0].get("contact_id", "x") is None, "#1735: a new contact person is not linked (contact_id null)")


def put(s, items, cid=CL):
    return s.patch(B + f"/api/clients/{cid}", json={"contacts": items})


# ================================================================== linking
r = put(A, [{"id": K1, "name": "Petra Buyer", "role": "Head of purchasing", "email": "petra@example.com", "contact_id": CT1}])
check(r.ok, f"#1735: alice links the contact person to a contact of Alpha's book ({r.status_code} {r.text[:200]})")
check(persons(A, CL)[0]["contact_id"] == CT1, "#1735: the client answer carries contact_id")
check(link_of(K1)[0] == CT1 and link_of(K1)[1] == "Petra Buyer", "db: linked, the name is the copy that was sent")
for bad, why in ((CTP, "a private book"), (CTW, "a member's personal book in the workspace"), (CTB, "another organisation's book"),
                 (CTF, "a freelancer's book"), (999999, "an unknown contact"), ("7", "a string"), (True, "a boolean")):
    r = put(A, [{"id": K1, "name": "Petra Buyer", "contact_id": bad}])
    check(r.status_code == 400, f"#1735: {why}: 400 ({r.status_code})")
r = put(S["bob"], [{"id": K1, "name": "Petra Buyer", "contact_id": CTW}])
check(r.status_code == 400, f"#1735: bob cannot link his personal book in Alpha's workspace either ({r.status_code})")
check(link_of(K1)[0] == CT1, "#1735: ... and the link stayed")
check(put(S["dave"], [{"id": K1, "name": "x", "contact_id": CTB}]).status_code == 404, "#1735: Beta's admin does not see Alpha's client")

# missing contact_id keeps the link (old clients of the API), null drops it, a new person may come linked
check(put(A, [{"id": K1, "name": "Petra B."}]).ok and link_of(K1)[0] == CT1, "#1735: without contact_id the link stays")
r = A.patch(B + f"/api/clients/{CL}", json={"contact": "Petra Renamed"})
check(r.ok and link_of(K1)[0] == CT1, "#1735: the old field contact keeps the link")
r = put(A, [{"id": K1, "name": "Petra B.", "contact_id": CT1}, {"name": "Paul Second", "contact_id": CT2}])
check(r.ok, f"#1735: a new contact person linked at once ({r.status_code} {r.text[:200]})")
ks = persons(A, CL)
K2 = next(k["id"] for k in ks if k["name"] == "Paul Second")
check(link_of(K2)[0] == CT2, "db: the new one is linked")

# carol (Alpha member, reads the book through its org role) keeps a link without the contacts module by sending it back,
# but cannot set a new one
S["carol"].patch(B + "/api/settings", json={"features": "cal,collab,comments,events,clients"})
r = put(S["carol"], [{"id": K1, "name": "Petra B.", "contact_id": CT1}, {"id": K2, "name": "Paul Second", "contact_id": CT2}])
check(r.ok and link_of(K1)[0] == CT1, f"#1735: a colleague without the contacts module keeps the links ({r.status_code})")
r = put(S["carol"], [{"id": K1, "name": "Petra B.", "contact_id": CT2}, {"id": K2, "name": "Paul Second", "contact_id": CT2}])
check(r.status_code == 400 and link_of(K1)[0] == CT1, f"#1735: ... but cannot link a new contact ({r.status_code})")
S["carol"].patch(B + "/api/settings", json={"features": FEAT})

# a token: the scope contacts is needed for a new link (structure alone changes the client, not the link)
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "structure"]}).json().get("token")
TH = {"Authorization": "Bearer " + (tok or "")}
r = requests.patch(V + f"/clients/{CL}", headers=TH, json={"contacts": [{"id": K1, "name": "Petra B.", "contact_id": CT2}, {"id": K2, "name": "Paul Second"}]})
check(r.status_code == 403 and link_of(K1)[0] == CT1, f"#1735: a token without the scope contacts cannot link ({r.status_code} {r.text[:160]})")
r = requests.patch(V + f"/clients/{CL}", headers=TH, json={"contacts": [{"id": K1, "name": "Petra B.", "contact_id": CT1}, {"id": K2, "name": "Paul Second"}]})
check(r.ok and link_of(K2)[0] == CT2, f"#1735: ... it keeps the links it sends back unchanged ({r.status_code})")
tok2 = A.post(B + "/api/me/tokens", json={"name": "t2", "scopes": ["read", "structure", "contacts"]}).json().get("token")
r = requests.patch(V + f"/clients/{CL}", headers={"Authorization": "Bearer " + (tok2 or "")},
                   json={"contacts": [{"id": K1, "name": "Petra B.", "contact_id": CT1}, {"id": K2, "name": "Paul Second", "contact_id": None}]})
check(r.ok and link_of(K2)[0] is None, f"#1735: with the scope contacts null unlinks ({r.status_code} {r.text[:160]})")
check(any(k.get("contact_id") == CT1 for k in requests.get(V + f"/clients/{CL}", headers=TH).json().get("contacts", [])),
      "#1735: GET /api/v1/clients/{id} carries contact_id")

# ================================================================== the address book search of the client dialog
r = A.get(B + f"/api/clients/{CL}/book-contacts")
got = {x["id"] for x in r.json().get("contacts", [])} if r.ok else set()
check(r.ok and {CT1, CT2, CT3} <= got and not got & {CTP, CTW, CTB, CTF}, f"#1735: the search lists only Alpha's books ({r.status_code} {sorted(got)})")
x = next((x for x in r.json()["contacts"] if x["id"] == CT1), {})
check(x.get("email") == "petra@example.com" and x.get("title") == "Head of purchasing" and x.get("book") == "Alpha customers",
      "#1735: a hit brings e-mail, function and its book " + str(x))
r = A.get(B + f"/api/clients/{CL}/book-contacts?q=petra")
check([x["id"] for x in r.json()["contacts"]] == [CT1], "#1735: the search filters by q")
check(S["dave"].get(B + f"/api/clients/{CL}/book-contacts").status_code == 404, "#1735: another organisation's client: 404")
check(S["frank"].get(B + f"/api/clients/{CL}/book-contacts").status_code == 404, "#1735: a stranger: 404")

# ================================================================== the contact card
c = A.get(B + f"/api/contacts/{CT1}").json()
check([x["client_id"] for x in c.get("clients", [])] == [CL] and c["clients"][0]["name"] == "Acme", "#1735: the card shows the client " + str(c.get("clients")))
check("clients" not in A.get(B + f"/api/contacts/{CT3}").json(), "#1735: an unlinked contact has no field clients")
c = S["carol"].get(B + f"/api/contacts/{CT1}").json()
check([x["client_id"] for x in c.get("clients", [])] == [CL], "#1735: carol (sees the client) gets it too")
S["carol"].patch(B + "/api/settings", json={"features": "cal,collab,comments,events,contacts"})
c = S["carol"].get(B + f"/api/contacts/{CT1}")
check(c.ok and "clients" not in c.json(), "#1735: without the module clients the field is missing")
S["carol"].patch(B + "/api/settings", json={"features": FEAT})
c = requests.get(V + f"/contacts/{CT1}", headers={"Authorization": "Bearer " + (tok2 or "")})
check(c.ok, f"setup: the contact over the API ({c.status_code})")

# ================================================================== deleting the contact / its book drops only the link
check(A.delete(B + f"/api/contacts/{CT1}").ok, "setup: alice deletes the contact")
row = link_of(K1)
check(row[0] is None and row[1] == "Petra B.", "#1735: contact deleted -> link NULL, the contact person stays " + str(tuple(row)))
r = put(A, [{"id": K1, "name": "Petra B.", "contact_id": CT3}, {"id": K2, "name": "Paul Second"}])
check(r.ok and link_of(K1)[0] == CT3, "setup: linked to a contact of the second book")
check(A.delete(B + f"/api/books/{BK2}").ok, "setup: alice deletes the second book")
check(link_of(K1)[0] is None and link_of(K1)[1] == "Petra B.", "#1735: book deleted -> link NULL, the contact person stays")

# ================================================================== the freelancer (no organisation): his own books
r = S["frank"].post(B + "/api/clients", json={"name": "Frank's client", "contacts": [{"name": "Fiona"}]})
check(r.status_code == 201 and r.json()["org_id"] is None, f"setup: frank's client has no organisation ({r.status_code} {r.text[:160]})")
FCL, FK = r.json()["id"], r.json()["contacts"][0]["id"]
got = {x["id"] for x in S["frank"].get(B + f"/api/clients/{FCL}/book-contacts").json()["contacts"]}
check(got == {CTF}, f"#1735: the freelancer's search lists his own book ({sorted(got)})")
r = put(S["frank"], [{"id": FK, "name": "Fiona Freelance", "contact_id": CTF}], FCL)
check(r.ok and link_of(FK)[0] == CTF, f"#1735: a freelancer links his own contact ({r.status_code} {r.text[:160]})")
check(put(S["frank"], [{"id": FK, "name": "Fiona", "contact_id": CT2}], FCL).status_code == 400, "#1735: ... never an organisation's")
c = S["frank"].get(B + f"/api/contacts/{CTF}").json()
check([x["client_id"] for x in c.get("clients", [])] == [FCL], "#1735: the freelancer's card shows his client")

# ================================================================== moving the client into another workspace drops the links
r = put(A, [{"id": K1, "name": "Petra B."}, {"id": K2, "name": "Paul Second", "contact_id": CT2}])
check(link_of(K2)[0] == CT2, "setup: linked again")
r = A.patch(B + f"/api/clients/{CL}", json={"org_id": None})
check(r.ok and link_of(K2)[0] is None and link_of(K2)[1] == "Paul Second", f"#1735: client moved to private -> links dropped ({r.status_code})")
check(A.patch(B + f"/api/clients/{CL}", json={"org_id": ALPHA}).ok, "setup: back to Alpha")

# ================================================================== the boundary check counts a link across, the repair drops it
dbx("UPDATE office_client_contacts SET contact_id=? WHERE id=?", (CTP, K2), write=True)
bd = A.get(B + "/api/admin/orgs").json().get("boundary", {})
check(bd.get("kinds", {}).get("client_contact") == 1, "#1735: the boundary check counts the link to a private book " + str(bd.get("kinds")))
det = [x for x in bd.get("details", []) if x["kind"] == "client_contact"]
check(det and det[0]["type"] == "client" and det[0]["name"] == "Acme" and det[0]["fixable"], "#1735: the detail names the client " + str(det))
r = A.post(B + "/api/admin/orgs/boundary/repair", json={})
check(r.ok and r.json().get("kinds", {}).get("client_contact") == 1, f"#1735: the repair drops it ({r.status_code} {r.text[:200]})")
check(link_of(K2)[0] is None and link_of(K2)[1] == "Paul Second", "#1735: ... the contact person stays")
check(link_of(FK)[0] == CTF, "#1735: the freelancer's fitting link is untouched")

print(f"p259_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
