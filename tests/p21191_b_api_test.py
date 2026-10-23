#!/usr/bin/env python3
"""2.119.1 API tests (part B, the contact card).
 - #2082 "Create as client" from the contact card: the client goes in with the contact as its linked default contact
   person (an organisation's book -> a client of that organisation, a freelancer's own book -> a private client); the
   card then lists the client ("Open client"); the undo (DELETE) drops the client and the card's link
 - #2083 the contact history (GET /api/contacts/{id}/history): filed mails from / to the contact's addresses, quotations /
   invoices / credit notes of its linked clients, its events, newest first, 20 per page with "more"; only what the person
   sees: no mail of somebody else's inbox, no mail of a health list, no documents without the module Office, 404 for a
   contact of an address book the person cannot see (another organisation, a freelancer's), 403 for a kid account
   freelancer-matrix: pim (a person without an organisation: own book, private client, personal office)
tenant-matrix: contact
usage: p21191_b_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,collab,comments,events,contacts,clients,office"
D = "2026-09-14"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def contact(s, bid, given, family, **kw):
    r = s.post(B + "/api/contacts", json={"book_id": bid, "given": given, "family": family, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mail(org, owner, frm, subject, to="", client=None, lst=None, at="2026-09-10T09:00:00+00:00"):
    ws = f"o{org}" if org else f"u{owner}"
    n = len(dbx("SELECT id FROM hub_mails"))
    dbx("INSERT INTO hub_mails(org_id, owner_id, client_id, list_id, ws, message_id, from_addr, from_name, to_addrs, subject, sent_at, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (org, owner, client, lst, ws, f"<p21191b-{n}@example.com>", frm, "", to, subject, at, at), write=True)
    return dbx("SELECT id FROM hub_mails WHERE message_id=?", (f"<p21191b-{n}@example.com>",))[0][0]


def hist(s, kid, offset=0):
    return s.get(B + f"/api/contacts/{kid}/history", params={"offset": offset} if offset else None)


def kinds(r):
    return [(x["kind"], x["id"]) for x in r.json()["items"]] if r.ok else []


if not os.environ.get("P21191B_NOSTART"):
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
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = (ids[k] for k in ("bob", "carol", "dave"))
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, BOB, CAROL], "admins": [1]}).ok, "setup: Alpha members")
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
S = {u: sess(u) for u in ("alice", "bob", "carol", "dave")}
A, Bo, Ca, Da = S["alice"], S["bob"], S["carol"], S["dave"]
for u, s in S.items():
    feat = FEAT.replace(",office", "") if u == "carol" else FEAT  # carol: a member without the module Office
    s.patch(B + "/api/settings", json={"lang": "en", "features": feat, "tour": "done", "workspace": f"org:{BETA if u == 'dave' else ALPHA}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: pim
Fr.patch(B + "/api/settings", json={"workspace": "private"})

# ---- address books: Alpha's own (petra), frida's own (fiona)
r = A.post(B + "/api/books", json={"name": "Alpha customers", "org_id": ALPHA})
BK = r.json()["id"]
check(A.post(B + f"/api/books/{BK}/org", json={"org_role": "view"}).ok, "setup: Alpha owns its book")
CT1 = contact(A, BK, "Petra", "Buyer", org="Acme GmbH", title="Head of purchasing", emails=[{"value": "Petra@example.com", "type": ["work"]}],
              phones=[{"value": "+49 30 1234"}], addresses=[{"type": ["work"], "street": "Hauptstr. 1", "code": "10115", "city": "Berlin", "country": "Germany"}])
FB = Fr.post(B + "/api/books", json={"name": "Mine", "org_id": None}).json()["id"]
CTF = contact(Fr, FB, "Fiona", "Freelance", emails=[{"value": "fiona@example.com"}])

# ================================================================== #2082 create a client from the contact
body = {"name": "Acme GmbH", "email": "petra@example.com", "phone": "+49 30 1234", "street": "Hauptstr. 1", "zip": "10115", "city": "Berlin",
        "country": "DE", "org_id": ALPHA, "contacts": [{"name": "Petra Buyer", "role": "Head of purchasing", "email": "petra@example.com",
                                                        "phone": "+49 30 1234", "is_default": True, "contact_id": CT1}]}
r = A.post(B + "/api/clients", json=body)
check(r.status_code == 201, f"#2082: the client from the contact ({r.status_code} {r.text[:200]})")
ACME = r.json()["id"] if r.ok else 0
check(r.ok and r.json()["contacts"][0]["contact_id"] == CT1, "#2082: the contact is the client's linked contact person")
cl = A.get(B + f"/api/contacts/{CT1}").json().get("clients") or []
check([x["client_id"] for x in cl] == [ACME], f"#2082: the card lists the client (Open client) {cl}")
# the freelancer: own book -> a private client, linked; the undo deletes it again
r = Fr.post(B + "/api/clients", json={"name": "Fiona Freelance", "email": "fiona@example.com", "org_id": None,
                                      "contacts": [{"name": "Fiona Freelance", "is_default": True, "contact_id": CTF}]})
check(r.status_code == 201 and r.json()["contacts"][0]["contact_id"] == CTF, f"#2082 freelancer: private client, linked ({r.status_code} {r.text[:200]})")
FCL = r.json()["id"] if r.ok else 0
check([x["client_id"] for x in (Fr.get(B + f"/api/contacts/{CTF}").json().get("clients") or [])] == [FCL], "#2082 freelancer: the card lists it")
r = Fr.delete(B + f"/api/clients/{FCL}")
check(r.ok, f"#2082: the undo deletes the client ({r.status_code})")
check(not Fr.get(B + f"/api/contacts/{CTF}").json().get("clients"), "#2082: ... and the card's link is gone")
# a private book cannot be linked to an organisation's client (the card's menu then makes the client without the link)
PB = A.post(B + "/api/books", json={"name": "Private", "org_id": None}).json()["id"]
CTP = contact(A, PB, "Private", "Person")
r = A.post(B + "/api/clients", json={"name": "Wrong", "org_id": ALPHA, "contacts": [{"name": "Private Person", "contact_id": CTP}]})
check(r.status_code == 400 and r.json().get("code") == "contact_gone", f"#2082: a private book never links to an organisation's client ({r.status_code})")
r = Fr.post(B + "/api/clients", json={"name": "Fiona Freelance", "org_id": None, "contacts": [{"name": "Fiona Freelance", "is_default": True, "contact_id": CTF}]})
FCL = r.json()["id"] if r.ok else 0  # again, for the history below

# ================================================================== #2083 the history
# documents: alice in Alpha's office, frida in her personal office
r = A.post(B + "/api/office/docs", json={"kind": "offer", "client_id": ACME, "project_title": "Image film", "date": "2026-09-01"})
check(r.status_code in (200, 201), f"setup: Alpha's quotation ({r.status_code} {r.text[:200]})")
OFF = r.json().get("id")
r = A.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": ACME, "project_title": "Image film", "date": "2026-09-05"})
check(r.status_code in (200, 201), f"setup: Alpha's invoice ({r.status_code} {r.text[:200]})")
INV = r.json().get("id")
r = Fr.post(B + "/api/office/docs", json={"kind": "offer", "client_id": FCL, "project_title": "Logo"})
check(r.status_code in (200, 201), f"setup: frida's quotation ({r.status_code} {r.text[:200]})")
FOFF = r.json().get("id")
# mails: the client's (from petra, from somebody else), alice's inbox (to petra), bob's inbox (from petra), a health list's
M1 = mail(ALPHA, 1, "petra@example.com", "Re: quotation", client=ACME, at="2026-09-12T08:00:00+00:00")
M2 = mail(ALPHA, 1, "other@example.com", "Unrelated", client=ACME)
M3 = mail(None, 1, "alice@example.com", "To petra", to="Petra Buyer <petra@example.com>", at="2026-09-11T08:00:00+00:00")
M4 = mail(ALPHA, BOB, "petra@example.com", "Bob's inbox")
HL = A.post(B + "/api/lists", json={"name": "Health"}).json()["id"]
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,), write=True)
M5 = mail(None, 1, "petra@example.com", "Health", lst=HL)
# an event with petra
r = A.post(B + "/api/events", json={"title": "Kick-off", "start": f"{D}T10:00", "attendees": [{"contact_id": CT1}]})
check(r.status_code in (200, 201), f"setup: an event with petra ({r.status_code} {r.text[:200]})")
EV = r.json().get("id")

r = hist(A, CT1)
check(r.ok, f"#2083: alice reads the history ({r.status_code} {r.text[:200]})")
k = kinds(r)
check(("mail", M1) in k and ("mail", M3) in k, f"#2083: the client's mail from petra + alice's own mail to petra {k}")
check(("mail", M2) not in k, "#2083: a mail from another address is not the contact's")
check(("mail", M4) not in k, "#2083: bob's inbox stays bob's")
check(("mail", M5) not in k, "#2083: a mail of a health list never shows")
check(("offer", OFF) in k and ("invoice", INV) in k, f"#2083: the client's quotation and invoice {k}")
check(("event", EV) in k, f"#2083: the event {k}")
ats = [x["at"] for x in r.json()["items"]] if r.ok else []
check(ats == sorted(ats, reverse=True), f"#2083: newest first {ats}")
check(k and k[0] == ("event", EV), f"#2083: the newest (the event of {D}) on top {k[:2]}")
check(r.ok and r.json()["more"] is False, "#2083: one page")
it = {(x["kind"], x["id"]): x for x in r.json()["items"]} if r.ok else {}
check(it.get(("mail", M1), {}).get("title") == "Re: quotation" and it.get(("mail", M1), {}).get("incoming") is True, "#2083: a mail shows its subject")
check("Image film" in it.get(("offer", OFF), {}).get("sub", ""), "#2083: a document shows its project")

# 2.119.1 review F6: whole recipient addresses, no substrings; F1: only reachable mails are scanned (a list with a role
# counts, a foreign organisation's mail never)
M6 = mail(None, 1, "alice@example.com", "To xpetra", to="xpetra@example.com; petra@example.com.au")
WL = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
M7 = mail(ALPHA, 1, "petra@example.com", "In a list", lst=WL)  # the list is Alpha's (alice's workspace)
M8 = mail(BETA, DAVE, "petra@example.com", "Beta's inbox")
k = kinds(hist(A, CT1))
check(("mail", M6) not in k, f"#2083 F6: a similar address is not the contact's {k}")
check(("mail", M7) in k, f"#2083 F1: a mail of alice's own list {k}")
check(("mail", M8) not in k, f"#2083 F1: another organisation's mail never {k}")

k = kinds(hist(Bo, CT1))  # bob: Alpha member with Office, sees the client
check(("mail", M1) in k and ("mail", M4) in k and ("mail", M3) not in k, f"#2083 bob: the client's mail + his own inbox, not alice's {k}")
check(("offer", OFF) in k, f"#2083 bob: a member of Alpha's office sees its documents {k}")
k = kinds(hist(Ca, CT1))  # carol: member without the module Office
check(("mail", M1) in k, f"#2083 carol: the client's mail {k}")
check(not any(x[0] in ("offer", "invoice", "credit") for x in k), f"#2083 carol: no documents without the module Office {k}")
check(hist(Da, CT1).status_code == 404, "#2083: another organisation's person: 404")
check(hist(Fr, CT1).status_code == 404, "#2083: the freelancer cannot read Alpha's contact: 404")
check(hist(A, CTF).status_code == 404, "#2083: alice cannot read the freelancer's contact: 404")
check(hist(A, 999999).status_code == 404, "#2083: an unknown contact: 404")

# the freelancer: her own contact, private client, personal office, own inbox; pages of 20
FM = [mail(None, FID, "fiona@example.com", f"Mail {i}", at=f"2026-08-{i + 1:02d}T08:00:00+00:00") for i in range(24)]
r = hist(Fr, CTF)
k = kinds(r)
check(r.ok and len(k) == 20 and r.json()["more"] is True, f"#2083 freelancer: a page of 20 with more ({r.status_code} {len(k)})")
check(("offer", FOFF) in k, f"#2083 freelancer: the private client's quotation from the personal office {k[:3]}")
r2 = hist(Fr, CTF, 20)
k2 = kinds(r2)
check(r2.ok and len(k2) == 5 and r2.json()["more"] is False and not set(k) & set(k2), f"#2083 freelancer: the second page {len(k2)}")
check(("mail", FM[0]) in k2, "#2083 freelancer: the oldest mail on the last page")

# a kid account gets 403 (people only)
r = A.post(B + "/api/users", json={"username": "kiddo", "display_name": "Kiddo", "password": "password123", "kid": True})
if r.ok:
    K = sess("kiddo")
    check(hist(K, CT1).status_code in (403, 404), "#2083: a kid account gets nothing")

print(f"p21191_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
