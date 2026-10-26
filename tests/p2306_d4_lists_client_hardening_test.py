#!/usr/bin/env python3
"""2.306.0 D4 (#2875): hardening of lists / collaboration / life (audit D) and the server side of three client findings.
freelancer-matrix: lists, budget, reading, contacts (a person without an organisation keeps every function in the own private space)
 - section templates: the sections of an organisation's list go into a private / other template only through the organisation's admin
 - budget: an import run of somebody else is taken back only by the list's owner / admin (the own run by its author)
 - read later: without an own project an entry never lands in a project somebody shared (an own one is made)
 - address books: the right to the book is checked before an import file is unpacked
 - public links: read later (private and the organisation's) and an organisation's trips stay private (409)
 - confirmed, no change: an approval card is decided only by an approver (choice_can, tests p21445_a / p2410_f), a trip somebody
   else entered for a person on the level "own" is read only on every write route (p2187_1_b_own), the recovery key step-up
   checks auth_time on the server (p21445_a)
usage: p2306_d4_lists_client_hardening_test.py <datadir>      (KMT_NOSTART=1 / P2306D4_NOSTART=1: a running server)"""
import io
import os
import re
import sys
import zipfile

import kt
from kt import B, check, done, fresh, sess, setup
from freelancer_fixture import FEATURES, freelancer, org_join

FEAT = FEATURES + ",sheets"
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido")

fresh({}, prefix="P2306D4")
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
assert org_join(B, "bob", ORG)
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"})
assert org_join(B, "carol", ORG)
SP = f"org:{ORG}"
FID, Fr = freelancer(B, A, "frida", features=FEAT)

# ================================================================ section templates: out of an organisation only through its admin
def org_list(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": ORG})
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]
    r = s.post(B + "/api/sections", json={"list_id": lid, "name": "Todo"})
    assert r.status_code in (200, 201), r.text
    return lid


BL, AL = org_list(Bo, "Bob board"), org_list(A, "Alice board")
r = Bo.post(B + "/api/section-templates", json={"name": "Out", "space": "private", "list_id": BL})
check(r.status_code == 403, f"#2875 a member cannot take an organisation list's sections into a private template {r.status_code} {r.text[:150]}")
r = Bo.post(B + "/api/section-templates", json={"name": "In", "space": SP, "list_id": BL})
check(r.status_code in (200, 201), f"#2875 ... into the organisation's own template it goes {r.status_code} {r.text[:150]}")
r = A.post(B + "/api/section-templates", json={"name": "Admin out", "space": "private", "list_id": AL})
check(r.status_code in (200, 201), f"#2875 the organisation's admin may {r.status_code} {r.text[:150]}")
r = Bo.post(B + "/api/section-templates", json={"name": "Names", "space": "private", "sections": ["A", "B"]})
check(r.status_code in (200, 201), f"#2875 a template from typed names is as before {r.status_code} {r.text[:150]}")
FL = Fr.post(B + "/api/lists", json={"name": "Frida list"}).json()["id"]
Fr.post(B + "/api/sections", json={"list_id": FL, "name": "Todo"})
r = Fr.post(B + "/api/section-templates", json={"name": "Mine", "space": "private", "list_id": FL})
check(r.status_code in (200, 201), f"#2875 freelancer: the own list's sections into a template {r.status_code} {r.text[:150]}")

# ================================================================ budget: somebody else's import run
r = A.post(B + "/api/budget/lists", json={})
check(r.status_code in (200, 201), f"#2875 setup: a budget {r.status_code} {r.text[:150]}")
BU = r.json()["list_id"]
r = A.put(B + f"/api/lists/{BU}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, f"#2875 setup: the budget shared with an editor {r.status_code} {r.text[:150]}")


def commit(s, lid, title, label):
    r = s.post(B + f"/api/budget/{lid}/import/commit", json={"rows": [{"day": "2026-09-01", "amount": 5.0, "kind": "out", "title": title}], "label": label})
    check(r.status_code == 201, f"#2875 setup: an import ({title}) {r.status_code} {r.text[:150]}")
    return r.json().get("run")


RA = commit(A, BU, "Owner row", "owner")
RB = commit(Bo, BU, "Editor row", "editor")
r = Bo.post(B + f"/api/budget/{BU}/import/runs/{RA}/undo", json={"edited": "delete"})
check(r.status_code == 403, f"#2875 an editor cannot take back the owner's import {r.status_code} {r.text[:150]}")
r = Bo.post(B + f"/api/budget/{BU}/import/runs/{RB}/undo", json={})
check(r.ok and r.json().get("deleted") == 1, f"#2875 the editor takes back the own import {r.status_code} {r.text[:150]}")
RB2 = commit(Bo, BU, "Editor row 2", "editor 2")
r = A.post(B + f"/api/budget/{BU}/import/runs/{RB2}/undo", json={})
check(r.ok and r.json().get("deleted") == 1, f"#2875 the owner takes back an editor's import {r.status_code} {r.text[:150]}")
r = A.post(B + f"/api/budget/{BU}/import/runs/{RA}/undo", json={})
check(r.ok and r.json().get("deleted") == 1, f"#2875 the owner takes back the own import {r.status_code} {r.text[:150]}")
FB = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
RF = commit(Fr, FB, "Frida row", "frida")
r = Fr.post(B + f"/api/budget/{FB}/import/runs/{RF}/undo", json={})
check(r.ok and r.json().get("deleted") == 1, f"#2875 freelancer: the own import taken back {r.status_code} {r.text[:150]}")

# ================================================================ read later: never into a shared project
r = Bo.post(B + "/api/reading", json={"url": "https://example.com/bob/1", "title": "Bob's"})
check(r.status_code == 201, f"#2875 setup: Bob's read later {r.status_code} {r.text[:150]}")
BRL = r.json()["list_id"]
r = Bo.put(B + f"/api/lists/{BRL}/members", json={"user_id": CAROL, "role": "edit"})
check(r.ok, f"#2875 setup: Bob's read later shared with Carol {r.status_code} {r.text[:150]}")
r = Ca.post(B + "/api/reading", json={"url": "https://example.com/carol/1", "title": "Carol's"})
check(r.status_code == 201 and r.json()["list_id"] != BRL, f"#2875 Carol's entry goes to a project of her own, not Bob's shared one {r.status_code} {r.text[:150]}")
CRL = r.json()["list_id"] if r.ok else 0
r = Ca.post(B + "/api/reading", json={"url": "https://example.com/carol/2", "title": "Carol's 2"})
check(r.status_code == 201 and r.json()["list_id"] == CRL, f"#2875 the next entry goes to the same own project {r.status_code} {r.text[:150]}")
r = Fr.post(B + "/api/reading", json={"url": "https://example.com/frida/1", "title": "Frida's"})
check(r.status_code == 201, f"#2875 freelancer: read later as before {r.status_code} {r.text[:150]}")
FRL = r.json()["list_id"]

# ================================================================ public links: read later and an organisation's trips stay private
for who, lid, label in ((Bo, BRL, "read later"), (Fr, FRL, "the freelancer's read later")):
    r = who.put(B + f"/api/lists/{lid}/public-link", json={"mode": "view"})
    check(r.status_code == 409, f"#2875 {label}: no public link {r.status_code} {r.text[:150]}")
r = Bo.post(B + "/api/reading", json={"url": "https://example.com/bob/org", "title": "Bob's org", "space": SP})
check(r.status_code == 201, f"#2875 setup: the organisation's read later {r.status_code} {r.text[:150]}")
ORL = r.json().get("list_id")
r = Bo.put(B + f"/api/lists/{ORL}/public-link", json={"mode": "view"})  # 2.306.0 Fix-2a (#2875): the organisation's read later project is caught too
check(r.status_code == 409, f"#2875 the organisation's read later (its owner): no public link {r.status_code} {r.text[:150]}")
r = A.post(B + "/api/life/trips", json={"name": "Fair", "from": "2026-11-02", "to": "2026-11-03", "packing": "", "space": SP})
check(r.status_code == 201, f"#2875 setup: an organisation trip {r.status_code} {r.text[:150]}")
r = A.put(B + f"/api/lists/{r.json().get('list_id')}/public-link", json={"mode": "view"})
check(r.status_code == 409, f"#2875 an organisation's trip: no public link {r.status_code} {r.text[:150]}")
r = Fr.post(B + "/api/life/trips", json={"name": "Holiday", "from": "2026-11-02", "to": "2026-11-03", "packing": ""})
check(r.status_code == 201, f"#2875 freelancer: a private trip {r.status_code} {r.text[:150]}")
r = Fr.put(B + f"/api/lists/{r.json().get('list_id')}/public-link", json={"mode": "view"})
check(r.status_code == 200, f"#2875 a private trip keeps its public link {r.status_code} {r.text[:150]}")
NL = Fr.post(B + "/api/lists", json={"name": "Plain"}).json()["id"]
check(Fr.put(B + f"/api/lists/{NL}/public-link", json={"mode": "view"}).status_code == 200, "#2875 a normal project keeps its public link")

# ================================================================ address books: the right first, then the file
bk = A.post(B + "/api/books", json={"name": "Private book", "org_id": None})
check(bk.status_code in (200, 201), f"#2875 setup: an address book {bk.status_code} {bk.text[:150]}")
BK = bk.json()["id"]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("none.vcf", "not a contact file")
zbytes = buf.getvalue()
r = Bo.post(B + f"/api/books/{BK}/import", files={"file": ("c.zip", zbytes, "application/zip")})
check(r.status_code in (403, 404), f"#2875 no right to the book: refused before the file is read {r.status_code} {r.text[:150]}")
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("c.zip", zbytes, "application/zip")})
check(r.status_code == 400, f"#2875 the owner's bad ZIP is still read and reported {r.status_code} {r.text[:150]}")
FK = Fr.post(B + "/api/books", json={"name": "Frida book", "org_id": None}).json()["id"]
vcf = "BEGIN:VCARD\nVERSION:3.0\nFN:Test Person\nN:Person;Test;;;\nEND:VCARD\n"
r = Fr.post(B + f"/api/books/{FK}/import", files={"file": ("c.vcf", vcf.encode(), "text/vcard")})
check(r.ok, f"#2875 freelancer: an import into the own book {r.status_code} {r.text[:150]}")

# ================================================================ confirmed: every write route of a trip checks the level "own"
src = open(os.path.join(SRC, "office", "travel.py"), encoding="utf-8").read()
blocks = re.split(r"\n(?=@app\.)", src)
bad = []
for b in blocks:
    m = re.match(r'@app\.(post|patch|delete)\("(/api/office/trips/<int:tid>[^"]*)"\)', b)
    if m and "_trip(" not in b:
        bad.append(m.group(2))
check(not bad, f"#2875 every write route of a single trip goes through _trip (the level 'own' read-only check): {bad}")

sys.exit(done("p2306_d4_lists_client_hardening"))
