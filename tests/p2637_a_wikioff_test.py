#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.637.0 (#4745) API: GET /api/wiki/space-files?space= -- every file of a knowledge space for the device's offline copy
("Offline available", static/js/wikioff.js). Invented names only.
 - the list: id, page, name, type, size, version (the content's sha256), address; the total in bytes
 - only with the space's right: a member reads the organisation's, another organisation / an unknown one 404, a guest 404
 - files in the trash and the files of pages in the trash are missing; back from the trash = listed again
 - the version follows the content (a new upload = a new file); the files of another space never come
 - a person without an organisation (freelancer-matrix: wiki): her private space's files, nobody else's
usage: p2637_a_wikioff_test.py <datadir>"""
import base64
import hashlib
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
L = "/api/wiki/space-files"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2637A")
A = kt.setup()
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("gina", "Gina Guest")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Gi = sess("bob"), sess("carol"), sess("gina")
for s in (A, Bo, Ca, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "wiki,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
rg = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "gina@example.com", "role": "guest"})
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"


def page(s, sp, path):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": "Text of " + path})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def attach(s, pid, name, data, mime):
    r = s.post(B + f"/api/wiki/pages/{pid}/files", files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


def lst(s, sp):
    return s.get(B + L, params={"space": sp})


def ids(r):
    return sorted(f["id"] for f in r.json().get("files", [])) if r.ok else None


# ---------------------------------------------------------------- an organisation's space
P1, P2 = page(A, SP, "Handbook/Start"), page(A, SP, "Handbook/Old")
F1 = attach(A, P1, "plan.png", PNG, "image/png")
F2 = attach(A, P1, "manual.pdf", PDF, "application/pdf")
F3 = attach(A, P2, "old.pdf", PDF + b"%old\n", "application/pdf")
PB = page(Ca, SP2, "Beta page")
FB = attach(Ca, PB, "beta.pdf", PDF, "application/pdf")

r = lst(Bo, SP)
check(r.status_code == 200 and ids(r) == sorted([F1, F2, F3]), f"a member lists the organisation's files {r.status_code} {r.text[:300]}")
j = r.json() if r.ok else {}
f1 = next((f for f in j.get("files", []) if f["id"] == F1), {})
check(f1.get("page_id") == P1 and f1.get("name") == "plan.png" and f1.get("mime") == "image/png" and f1.get("size") == len(PNG)
      and f1.get("v") == hashlib.sha256(PNG).hexdigest() and f1.get("url", "").startswith(f"/api/wiki/files/{F1}/"),
      f"a file: page, name, type, size, version = sha256, address {f1}")
check(j.get("bytes") == len(PNG) + len(PDF) + len(PDF) + 6 and j.get("space") == SP and j.get("more") is False and j.get("e2e") is False,
      f"the total in bytes, the space, more / e2e false {j.get('bytes')} {j.get('space')}")
check(Bo.get(B + f1.get("url", "/x")).content == PNG, "the listed address gives the file (the device fetches it there)")
check(FB not in (ids(r) or []), "another organisation's file is never listed")

# rights
check(lst(Ca, SP).status_code == 404, "another organisation: 404")
check(lst(Bo, SP2).status_code == 404, "a member of Alpha asks for Beta: 404")
check(lst(Bo, "org:999999").status_code == 404, "an unknown organisation: 404")
if rg.ok:
    check(lst(Gi, SP).status_code == 404, "a guest of the organisation (no knowledge area): 404 like the index")
check(lst(Bo, "org:abc").status_code == 400, "a malformed space: 400")

# the trash
check(Bo.delete(B + f"/api/wiki/files/{F2}").status_code == 403, "setup: a member without write right cannot delete a file")
check(A.delete(B + f"/api/wiki/files/{F2}").ok, "setup: Alice deletes manual.pdf (trash)")
check(ids(lst(Bo, SP)) == sorted([F1, F3]), "a file in the trash is missing")
check(A.delete(B + f"/api/wiki/pages/{P2}").ok, "setup: the page Handbook/Old into the trash")
check(ids(lst(Bo, SP)) == [F1], "the file of a page in the trash is missing")
check(A.post(B + "/api/wiki/restore", json={"ids": [P2], "files": [F2]}).ok, "setup: the page and the file back")
check(ids(lst(Bo, SP)) == sorted([F1, F2, F3]), "back from the trash: listed again")
# a new content is a new file with its own version
F4 = attach(A, P1, "plan.png", PNG + b"\x00", "image/png")
j = lst(Bo, SP).json()
v = {f["id"]: f["v"] for f in j["files"]}
check(F4 in v and v[F4] != v[F1], "a new upload of the same name is another file with another version")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A)
_, Fo = freelancer(B, A, "fiona")
for s in (Fr, Fo):
    s.patch(B + "/api/settings", json={"features": "wiki,files"})
FP = page(Fr, "private", "Notes/Receipts")
FF = attach(Fr, FP, "receipt.pdf", PDF, "application/pdf")
r = lst(Fr, "private")
check(r.ok and ids(r) == [FF] and r.json().get("space") == "private", f"freelancer: her private space's file {r.status_code} {r.text[:200]}")
check(ids(lst(Fo, "private")) == [], "another person's private space: only her own (none)")
check(ids(lst(A, "private")) == [], "Alice's private space has none of the freelancer's files")
check(lst(Fr, SP).status_code == 404, "freelancer: an organisation she is not in 404")
check(Fr.get(B + L).ok and ids(Fr.get(B + L)) == [FF], "no space given = the private one (like the index)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
