#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.429.0 (#3580): the file store ("Ablage") shows only its own folders (freelancer-matrix: files)
 - the root folders of the other areas (knowledge, tables, office, projects, address book) are not at the top of a space, a
   folder of an area shared with a person is not in "Shared with me", the search and the file store's "Move to…" (?ablage=1)
   leave them out; opening an area's folder by its id still works (the areas' panels, the share dialog)
 - the collections "From <area>" at the top of the space (only when they hold something): the files of knowledge pages per
   page, the project files per project, files lying in an area's folders per folder; read-only, through their own routes
 - a page in the trash takes its files out of the collection; a space of another person / organisation is 404, an unknown key 404
 - a person without an organisation (the fixture): everything in the private workspace
usage: p2429_a_ablage_view_test.py <datadir>      (KMT_NOSTART=1 / P2429A_NOSTART=1: a running server)"""
import sys
import base64

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, check, done, fresh, setup

FEAT = FEATURES + ",sheets"  # the tables are not among the fixture's modules
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

fresh(prefix="P2429A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
FID, Fr = freelancer(B, A, features=FEAT)


def top(s, space="private"):
    r = s.get(B + "/api/files", params={"space": space})
    assert r.ok, (space, r.status_code, r.text)
    return r.json()


def names(j):
    return [x["name"] for x in j.get("items", [])]


def coll(s, key, space="private"):
    return s.get(B + f"/api/files/collections/{key}", params={"space": space})


def upload(s, name, parent=None, space=None, data=None, mime="text/plain"):
    r = s.post(B + "/api/files/upload", data={"parent_id": parent} if parent else {"space": space or "private"},
               files={"file": (name, data or f"content of {name}".encode(), mime)})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["items"][0]["id"]


# ================================================================== a person without an organisation: the private workspace
OWN = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Receipts 2026"}).json()["id"]
r = Fr.post(B + "/api/wiki/folders", json={"space": "private", "name": "Handbook"})
check(r.status_code == 201, f"setup: a knowledge folder (makes the area's root) {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Handbook/Start", "body": "Welcome"})
check(r.status_code == 201, f"setup: a knowledge page {r.status_code} {r.text[:160]}")
PAGE = r.json().get("id")
r = Fr.post(B + f"/api/wiki/pages/{PAGE}/files", files={"file": ("plan.png", PNG, "image/png")})
check(r.ok, f"setup: a file on the page {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/sheets/folders", json={"space": "private", "name": "Customers"})
check(r.status_code == 201, f"setup: a folder of the tables (makes the area's root) {r.status_code} {r.text[:160]}")
SHF = r.json()["folder"]["id"]
WROOT = Fr.get(B + "/api/wiki", params={"space": "private"}).json().get("root")

j = top(Fr)
check("Receipts 2026" in names(j), f"#3580: the file store's own folder stays at the top {names(j)}")
check(not ({"Knowledge", "Tables"} & set(names(j))), f"#3580: no root folder of the knowledge pages / tables at the top {names(j)}")
check([c["key"] for c in j.get("collections", [])] == ["wiki"], f"#3580: one collection 'From Knowledge' (the tables hold no file yet) {j.get('collections')}")
check(j["collections"][0]["name"] == "From Knowledge", f"#3580: its name {j['collections']}")

r = coll(Fr, "wiki")
g = r.json().get("groups", []) if r.ok else []
check(r.ok and len(g) == 1 and g[0]["title"] == "Start" and g[0]["open"] == f"wiki/{PAGE}", f"#3580: the page's files grouped by the page {r.status_code} {g}")
f0 = g[0]["items"][0] if g and g[0]["items"] else {}
check(f0.get("name") == "plan.png" and f0.get("kind") == "wiki" and f0.get("url", "").startswith("/api/wiki/files/"), f"#3580: the file with its own route {f0}")
check(Fr.get(B + f0.get("url", "/x")).ok, "#3580: the file opens through the knowledge route")

# the search and the move targets
hits = [x["name"] for x in Fr.get(B + "/api/files/search", params={"q": "Start"}).json().get("items", [])]
check("Start" not in hits, f"#3580: the search shows no reference to the knowledge page {hits}")
hits = [x["id"] for x in Fr.get(B + "/api/files/search", params={"q": "Customers"}).json().get("items", [])]
check(SHF not in hits, f"#3580: the search shows no folder of the tables {hits}")
fs = [x["id"] for x in Fr.get(B + "/api/files/folders", params={"ablage": "1"}).json()["folders"]]
check(OWN in fs and SHF not in fs, f"#3580: 'Move to…' of the file store lists only its own folders {fs}")
fs = [x["id"] for x in Fr.get(B + "/api/files/folders").json()["folders"]]
check(SHF in fs, "#3580: without ?ablage=1 (the office's 'Move to folder') the list is as before")
if WROOT:
    check(Fr.get(B + "/api/files", params={"parent": WROOT}).ok, "#3580: an area's folder still opens by its id")

# a file lying in a folder of the tables (an older version could put it there): read-only in "From Tables", never lost
LOST = upload(Fr, "old-offer.txt", parent=SHF)
j = top(Fr)
check([c["key"] for c in j.get("collections", [])] == ["wiki", "sheets"], f"#3580: + 'From Tables' {j.get('collections')}")
g = coll(Fr, "sheets").json().get("groups", [])
check(len(g) == 1 and g[0]["title"].endswith("/ Customers") and g[0]["open"] is None and [x["id"] for x in g[0]["items"]] == [LOST],
      f"#3580: the file grouped by its folder {g}")
check(Fr.get(B + g[0]["items"][0]["url"]).ok if g and g[0]["items"] else False, "#3580: it opens through the file store's content route")

# project files
r = Fr.post(B + "/api/lists", json={"name": "Garden", "kind": "project"})
check(r.ok, f"setup: a project {r.status_code} {r.text[:160]}")
LID = r.json().get("id")
r = Fr.post(B + f"/api/lists/{LID}/files", files={"file": ("sketch.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")})
check(r.ok, f"setup: a project file {r.status_code} {r.text[:160]}")
check("lists" in [c["key"] for c in top(Fr).get("collections", [])], "#3580: + 'From Projects'")
g = coll(Fr, "lists").json().get("groups", [])
check(len(g) == 1 and g[0]["title"] == "Garden" and g[0]["open"] == f"l/{LID}" and g[0]["items"][0]["name"] == "sketch.pdf",
      f"#3580: the project files grouped by the project {g}")

# the knowledge module off for her: no collection of it (the area's own routes refuse too)
Fr.patch(B + "/api/settings", json={"features": FEAT.replace("wiki,", "")})
check("wiki" not in [c["key"] for c in top(Fr).get("collections", [])] and coll(Fr, "wiki").json().get("groups") == [],
      "#3580: the knowledge module off: no 'From Knowledge'")
Fr.patch(B + "/api/settings", json={"features": FEAT})
check("wiki" in [c["key"] for c in top(Fr).get("collections", [])], "#3580: on again: 'From Knowledge' is back")

# the page into the trash: its files leave the collection
check(Fr.delete(B + f"/api/wiki/pages/{PAGE}").ok, "setup: the page into the trash")
check("wiki" not in [c["key"] for c in top(Fr).get("collections", [])], "#3580: no 'From Knowledge' without a readable file")
check(coll(Fr, "wiki").json().get("groups") == [], "#3580: the collection is empty")

# boundaries
check(coll(Fr, "nope").status_code == 404, "#3580: an unknown collection 404")
check(coll(Fr, "wiki", f"org:{ORG}").status_code == 404, "#3580: an organisation the person is not in 404")
check(coll(Bo, "sheets").json().get("groups") == [], "#3580: bob's private workspace shows nothing of hers")

# ================================================================== an organisation: shared folders of an area
r = A.post(B + "/api/sheets/folders", json={"space": f"org:{ORG}", "name": "Team tables"})
check(r.status_code == 201, f"setup: alice's folder of the organisation's tables {r.status_code} {r.text[:160]}")
TT = r.json()["folder"]["id"]
check(A.post(B + f"/api/files/nodes/{TT}/shares", json={"user_id": BOB, "role": "view"}).ok, "setup: shared with bob")
PLAIN = A.post(B + "/api/files/folders", json={"space": "private", "name": "For Bob"}).json()["id"]
check(A.post(B + f"/api/files/nodes/{PLAIN}/shares", json={"user_id": BOB, "role": "view"}).ok, "setup: a file store folder shared with bob")
sh = [x["id"] for x in top(Bo, "shared").get("items", [])]
check(PLAIN in sh and TT not in sh, f"#3580: 'Shared with me' shows the file store's folder, not the tables' one {sh}")
check(not ({"Tables"} & set(names(top(A, f"org:{ORG}")))), "#3580: the organisation's top shows no root of the tables")
check(Bo.get(B + "/api/files", params={"parent": TT}).ok, "#3580: bob still opens the shared folder by its id (the tables' panel)")
sys.exit(done("p2429_a_ablage_view"))
