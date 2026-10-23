#!/usr/bin/env python3
"""2.122.0 API tests, part B: tags in the file store (#2099), the documents search with several filters, the search syntax,
the bulk change and the ZIP of a selection (#2294). Own container (start.sh, server key on: sealed files and labels).
Invented names and generated file contents only.
 - #2099: files and folders get tags of the documents' tag set of their workspace (one tag "Steuer" = one id for a document
   and a file); the list, the details and the tag routes show them; tags on plain files never show up in the documents'
   filters or hits; the tag filter of a space (with / every one / one of them / without); a move into the organisation takes
   the tags along by name; deleting a tag and its undo bring it back on the file too; rights: view = read only, another
   organisation / person 404, agents use the API v1
 - #2294: several tags (any / all / not), several senders, without tag / sender, both dates, folder, file type; the search
   syntax (tag:, absender:, sender:, typ:, type:, datum:, date:, eingang:, "phrase", -word, -tag:); the bulk change (tags
   added / removed, type, sender) with its undo, view-only documents are counted, not changed; the ZIP: only visible
   documents, the limit (KALMIDO_DOCS_ZIP_MAX_FILES=4 here) with its hint, a ticket once and only for its owner; the API v1
   list takes the new filters and the syntax (an agent: only shared documents)
 - freelancer-matrix: files (a person without an organisation: tags, tag filter, filters, bulk change, ZIP)
 - tenant-matrix: document, file (another organisation / person: nothing changed, nothing in a ZIP or a filter)
usage: p2122_b_api_test.py <datadir>      (a fresh container; P2122B_NOSTART=1: the container runs already)"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def folder(s, name, parent=None, space=None):
    b = {"name": name, **({"parent_id": parent} if parent else {}), **({"space": space} if space else {})}
    r = s.post(B + "/api/files/folders", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def fupload(s, name, data, parent=None, space=None):
    form = {"parent_id": str(parent)} if parent else {"space": space or "private"}
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def doc_new(s, name, text, ws="private", **fields):
    """A text document, recognised, then its fields set (date, sender, type, tags)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    if fields:
        r = s.patch(B + f"/api/docs/{nid}", json=fields)
        assert r.ok, r.text
    return nid


def ids(s, **params):
    r = s.get(B + "/api/docs", params={"facets": "0", **params})
    return sorted(d["id"] for d in r.json()["docs"]) if r.ok else (r.status_code, r.text[:200])


def put_tags(s, nid, tags):
    return s.put(B + f"/api/files/nodes/{nid}/tags", json={"tags": tags})


def tag_names(s, nid):
    r = s.get(B + f"/api/files/nodes/{nid}/tags")
    return [t["name"] for t in r.json()["tags"]] if r.ok else r.status_code


# ---- setup: alice (instance admin, admin of Alpha), bob (member of Alpha), carol (admin of Beta), a freelancer
if not os.environ.get("P2122B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_DOCS_ZIP_MAX_FILES=4")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob"), ("carol", "Carol")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, ALICE, BOB, ORG2, CAROL))
r = A.post(B + "/api/admin/agents", json={"username": "alicebot", "display_name": "Alicebot"})
assert r.status_code == 201, r.text
PAG, PAGT = r.json()["id"], r.json().get("token") or ""
dbx("DELETE FROM org_members WHERE user_id=?", (PAG,))
dbx("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (ALICE, PAG))  # alice's personal agent
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
FEAT = "files,docs,collab,comments"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
AGS = tok(PAGT)

# ================================================================ #2099 tags in the file store
P = folder(A, "Projekte", space="private")
F1 = fupload(A, "plan.txt", b"Projektplan Beispiel", parent=P)
r = put_tags(A, F1, ["Steuer", "Kunde A"])
check(r.ok and sorted(t["name"] for t in r.json()["tags"]) == ["Kunde A", "Steuer"], f"tags on a file ({r.status_code} {r.text[:200]})")
check(put_tags(A, P, ["Kunde A"]).ok, "tags on a folder")
lst = A.get(B + "/api/files", params={"space": "private"}).json()["items"]
check(any(x["id"] == P and [t["name"] for t in x["tags"]] == ["Kunde A"] for x in lst), "the list shows the tags of a row")
lst = A.get(B + "/api/files", params={"parent": P}).json()["items"]
check(any(x["id"] == F1 and len(x["tags"]) == 2 for x in lst), "the folder's list shows the file's tags")
check(sorted(t["name"] for t in A.get(B + f"/api/files/nodes/{F1}").json().get("tags", [])) == ["Kunde A", "Steuer"], "the details show the tags")
r = put_tags(A, F1, ["steuer"])  # the same tag (case-insensitive), no second one
check(r.ok and [t["name"] for t in r.json()["tags"]] == ["Steuer"], "an existing tag is found by name")
tg = A.get(B + f"/api/files/nodes/{F1}/tags").json()
STEUER = next(t["id"] for t in tg["tags"])
check(tg["ws"] == "private" and tg["can"] and {"Steuer", "Kunde A"} <= {t["name"] for t in tg["all"]}, "the tags of the workspace for the picker")
check(any(x["action"] == "tags" for x in A.get(B + f"/api/files/nodes/{F1}").json().get("log", [])), "the change is in the history")
check(put_tags(A, F1, "Steuer").status_code == 400, "tags must be a list")

# one tag world: the document's tag "Steuer" is the file's
D0 = doc_new(A, "brief.txt", "Ein Brief ohne Belang", date="2023-01-15", tags=["Steuer"])
check([t["id"] for t in A.get(B + f"/api/docs/{D0}").json()["tags"]] == [STEUER], "a document and a file share the tag (one id)")
fac = A.get(B + "/api/docs", params={"ws": "private"}).json()["facets"]
check([t["name"] for t in fac["tags"]] == ["Steuer"], f"the documents' filters list only tags used on documents ({[t['name'] for t in fac['tags']]})")
KUNDE = next(t["id"] for t in tg["all"] if t["name"] == "Kunde A")
check(ids(A, ws="private", tag=str(KUNDE)) == [], "a tag only on files finds no document")
check(D0 in ids(A, ws="private", tag=str(STEUER)) and F1 not in ids(A, ws="private", tag=str(STEUER)), "plain files are never documents")
# a document's tags set from the file store behave as in the documents area
r = put_tags(A, D0, ["Steuer", "Archiv"])
check(r.ok and sorted(t["name"] for t in A.get(B + f"/api/docs/{D0}").json()["tags"]) == ["Archiv", "Steuer"], "a document's tags from the file store")

# the tag filter of a space
r = A.get(B + "/api/files/tags", params={"space": "private"})
check(r.ok and {"Steuer", "Kunde A", "Archiv"} <= {t["name"] for t in r.json()["tags"]}, f"the tags used in the space ({r.text[:200]})")
F2 = fupload(A, "notiz.txt", b"Notiz", space="private")
put_tags(A, F2, ["Kunde A", "Steuer"])
hit = lambda s, **p: sorted(x["id"] for x in s.get(B + "/api/files/tagged", params=p).json().get("items", []))  # noqa: E731
check(hit(A, space="private", tag=str(STEUER)) == sorted([F1, F2, D0]), "filter: with Steuer")
check(hit(A, space="private", tag=[str(STEUER), str(KUNDE)], mode="all") == [F2], "filter: Steuer and Kunde A (every one)")
check(hit(A, space="private", tag=[str(STEUER), str(KUNDE)]) == sorted([P, F1, F2, D0]), "filter: Steuer or Kunde A (one of them)")
check(hit(A, space="private", tag=str(STEUER), **{"not": str(KUNDE)}) == sorted([F1, D0]), "filter: Steuer without Kunde A")
r = A.get(B + "/api/files/tagged", params={"space": "private", "tag": [str(STEUER), str(KUNDE)]}).json()["items"]
check(next(x for x in r if x["id"] == F1)["path"] == "Projekte" and next(x for x in r if x["id"] == P)["path"] == "", "the hits carry their path")
check(next(x for x in r if x["id"] == F1)["tags"][0]["name"] == "Steuer", "the hits carry their tags")
check(A.get(B + "/api/files/tagged", params={"space": "private"}).status_code == 400, "the tag filter needs a tag")

# rights: an organisation's folder, bob (member) with view, then edit; carol (Beta) nothing
OF = folder(A, "Verträge", space=f"org:{ORG}")
OF1 = fupload(A, "vertrag.txt", b"Vertrag Beispiel", parent=OF)
check(put_tags(A, OF1, ["Steuer"]).ok, "tags in the organisation")
OSTEUER = A.get(B + f"/api/files/nodes/{OF1}/tags").json()["tags"][0]["id"]
check(OSTEUER != STEUER, "the organisation has its own tag set (same name, another id)")
check(Bo.get(B + f"/api/files/nodes/{OF1}/tags").status_code == 404 and put_tags(Bo, OF1, ["X"]).status_code == 404, "member without access: 404")
A.patch(B + f"/api/files/nodes/{OF}", json={"org_access": "view"})
r = Bo.get(B + f"/api/files/nodes/{OF1}/tags")
check(r.ok and not r.json()["can"] and put_tags(Bo, OF1, ["X"]).status_code == 403, "member with view: reads, 403 on change")
check(hit(Bo, space=f"org:{ORG}", tag=str(OSTEUER)) == [OF1], "member with view: the tag filter of the organisation")
A.patch(B + f"/api/files/nodes/{OF}", json={"org_access": "edit"})
check(put_tags(Bo, OF1, ["Steuer", "Bob"]).ok, "member with edit: changes the tags")
check(put_tags(Bo, OF1, [STEUER]).ok and tag_names(A, OF1) == [], "a tag id of another workspace is dropped")
put_tags(A, OF1, ["Steuer"])
# tenant-matrix: file -- another organisation / person
check(Ca.get(B + f"/api/files/nodes/{OF1}/tags").status_code == 404, "carol (Beta): 404 on the tags of Alpha's file")
check(put_tags(Ca, OF1, ["Fremd"]).status_code == 404 and tag_names(A, OF1) == ["Steuer"], "carol: no change")
check(Ca.get(B + "/api/files/tagged", params={"space": f"org:{ORG}", "tag": str(OSTEUER)}).status_code == 404, "carol: no tag filter in Alpha")
check(hit(Ca, space="private", tag=str(STEUER)) == [] and hit(Ca, space="shared", tag=str(STEUER)) == [], "carol: alice's private files never hit")
check(Ca.get(B + "/api/files/tags", params={"space": f"org:{ORG}"}).status_code == 404, "carol: no tag names of Alpha")
check(Bo.get(B + f"/api/files/nodes/{F1}/tags").status_code == 404, "bob: 404 on alice's private file")
check(AGS.get(B + f"/api/files/nodes/{F1}/tags").status_code in (401, 403), "agents: not these routes (API v1)")

# a move into the organisation: the tags go along by name
r = A.post(B + "/api/files/move-space", json={"ids": [F2], "to": f"org:{ORG}", "parent": None})
check(r.ok, f"move into Alpha ({r.status_code} {r.text[:200]})")
t2 = A.get(B + f"/api/files/nodes/{F2}/tags").json()
check(sorted(x["name"] for x in t2["tags"]) == ["Kunde A", "Steuer"] and t2["ws"] == f"org:{ORG}"
      and all(x["id"] != STEUER for x in t2["tags"]), "the tags of the moved file are Alpha's now")

# deleting a tag and its undo: back on the file as well
r = A.delete(B + f"/api/docs/labels/tag/{KUNDE}")
check(r.ok and P in r.json()["ids"] and tag_names(A, P) == [], f"tag deleted: gone from the folder ({r.text[:200]})")
r = A.post(B + "/api/docs/labels/tag", json={"ws": "private", "name": "Kunde A", "ids": r.json()["ids"]})
check(r.status_code == 201 and tag_names(A, P) == ["Kunde A"], "undo: the tag is on the folder again")

# freelancer-matrix: files -- a person without an organisation
FID, Fr = freelancer(B, A)
FP = folder(Fr, "Aufträge", space="private")
check(put_tags(Fr, FP, ["Kunde B"]).ok and tag_names(Fr, FP) == ["Kunde B"], "freelancer: tags on the own folder")
FT = Fr.get(B + f"/api/files/nodes/{FP}/tags").json()["tags"][0]["id"]
check(hit(Fr, space="private", tag=str(FT)) == [FP], "freelancer: the tag filter")
check(Fr.get(B + "/api/files/tags", params={"space": f"org:{ORG}"}).status_code == 404, "freelancer: no organisation")
check(A.get(B + f"/api/files/nodes/{FP}/tags").status_code == 404, "the admin does not see the freelancer's private folder")

# ================================================================ #2294 the documents search
D1 = doc_new(A, "telekom.txt", "Rechnung Telekom Mobilfunk Maerz Beispielkunde", date="2025-03-10", sender="Telekom Deutschland", type="Rechnung", tags=["Steuer", "Privat"])
D2 = doc_new(A, "allianz.txt", "Vertrag Versicherung Hausrat Beispiel", date="2024-06-01", sender="Allianz Beispiel", type="Vertrag", tags=["Steuer"])
D3 = doc_new(A, "prospekt.txt", "Werbung Prospekt Angebot", date="2025-07-01")
dbx("UPDATE doc_meta SET sender_id=NULL, type_id=NULL WHERE node_id=?", (D3,))
dbx("DELETE FROM doc_node_tags WHERE node_id=?", (D3,))
ALL = sorted([D0, D1, D2, D3])
check(ids(A, ws="private") == ALL, "four private documents")
fac = A.get(B + "/api/docs", params={"ws": "private"}).json()["facets"]
tag_id = lambda name: ",".join(map(str, next(t["ids"] for t in fac["tags"] if t["name"] == name)))  # noqa: E731
snd = lambda name: ",".join(map(str, next(t["ids"] for t in fac["senders"] if t["name"] == name)))  # noqa: E731
check(fac.get("folders") and all(isinstance(x["ids"], list) for x in fac["folders"]), "the filters list the folders")
T_ST, T_PR = tag_id("Steuer"), tag_id("Privat")
check(ids(A, ws="private", tag=[T_ST, T_PR]) == sorted([D0, D1, D2]), "tags: one of them")
check(ids(A, ws="private", tag=[T_ST, T_PR], tag_mode="all") == [D1], "tags: every one")
check(ids(A, ws="private", tag=T_ST, not_tag=T_PR) == sorted([D0, D2]), "tags: Steuer, not Privat")
check(ids(A, ws="private", tag=f"{T_ST};{T_PR}", tag_mode="all") == [D1], "tags: two groups in one value (API v1 form)")
check(ids(A, ws="private", sender=[snd("Telekom Deutschland"), snd("Allianz Beispiel")]) == sorted([D1, D2]), "several senders")
check(ids(A, ws="private", no_tag="1") == [D3], "without tag")
check(D3 in ids(A, ws="private", no_sender="1") and D1 not in ids(A, ws="private", no_sender="1"), "without sender")
check(ids(A, ws="private", **{"from": "2025-01-01", "to": "2025-12-31"}) == sorted([D1, D3]), "document date from / to")
check(ids(A, ws="private", added_from="2099-01-01") == [] and ids(A, ws="private", added_to="2000-01-01") == [], "date of arrival")
check(ids(A, ws="private", ftype="text") == ALL and ids(A, ws="private", ftype="pdf") == [], "file type")
check(ids(A, ws="private", ftype="pdf,text") == ALL, "several file types")
DOCROOT = A.get(B + "/api/docs/settings", params={"ws": "private"}).json()["root_id"]
par = A.get(B + f"/api/docs/{D1}").json()["parent_id"]
check(D1 in ids(A, ws="private", folder=str(par)) and ids(A, ws="private", folder="999999") == [], "folder")
# the search syntax
for q, want, what in (("tag:steuer -tag:privat", [D0, D2], "tag: and -tag:"),
                      ("absender:telekom", [D1], "absender: (part of the name)"),
                      ("sender:\"Allianz Beispiel\"", [D2], "sender: with quotes"),
                      ("typ:vertrag", [D2], "typ:"), ("type:Rechnung", [D1], "type:"),
                      ("datum:2025-01..2025-04", [D1], "datum: range"), ("date:2024", [D2], "date: year"),
                      ("datum:03.2025", [D1], "datum: month German"), ("datum:>2025-06-30", [D3], "datum: after"),
                      ("\"Versicherung Hausrat\"", [D2], "exact phrase"), ("\"Hausrat Versicherung\"", [], "phrase in another order: no hit"),
                      ("rechnung -mobilfunk", [], "a word and an excluded word"), ("-werbung", [D0, D1, D2], "an excluded word alone"),
                      ("-\"Werbung Prospekt\"", [D0, D1, D2], "an excluded phrase"),
                      ("tag:unbekannt", [], "an unknown tag: no hit"), ("sender:Telekom type:Rechnung date:2025-03", [D1], "English keys combined"),
                      ("tag:steuer versicherung", [D2], "syntax + a word of the text"), ("eingang:2099", [], "eingang: (date of arrival)")):
    got = ids(A, ws="private", q=q)
    check(got == sorted(want), f"syntax {what}: {q!r} -> {got}")
check(ids(A, ws="private", q="tag:steuer", tag=T_PR) == [D1], "syntax and filters combine")
# tenant-matrix: document -- names of another workspace never match, other people's documents never hit
check(ids(Ca, q="absender:telekom") == [] and ids(Ca, q="tag:steuer") == [], "carol: alice's labels find nothing")
check(ids(Bo, ws="private", tag=T_ST) == [], "bob: nothing of alice's private documents")

# the bulk change
before = {d: A.get(B + f"/api/docs/{d}").json() for d in (D1, D2, D3)}
r = A.post(B + "/api/docs/bulk", json={"ids": [D1, D2, D3], "add_tags": ["Archiv"], "remove_tags": ["privat"], "type": "Beleg"})
j = r.json() if r.ok else {}
check(r.ok and sorted(j["changed"]) == sorted([D1, D2, D3]) and j["denied"] == 0 and len(j["before"]) == 3, f"bulk: three changed ({r.text[:200]})")
d1 = A.get(B + f"/api/docs/{D1}").json()
check(sorted(t["name"] for t in d1["tags"]) == ["Archiv", "Steuer"] and d1["type"]["name"] == "Beleg", "bulk: tags added / removed, type set")
check(A.get(B + f"/api/docs/{D3}").json()["type"]["name"] == "Beleg", "bulk: a document without type gets it")
check(any(str(r_[0] or "").startswith("bulk:") for r_ in dbx("SELECT detail FROM fs_log WHERE node_id=? AND action='edit'", (D1,))), "bulk: in the history")
r = A.post(B + "/api/docs/bulk", json={"restore": j.get("before", [])})
check(r.ok and len(r.json()["changed"]) == 3, f"bulk undo ({r.text[:200]})")
for d in (D1, D2, D3):
    x = A.get(B + f"/api/docs/{d}").json()
    check(sorted(t["name"] for t in x["tags"]) == sorted(t["name"] for t in before[d]["tags"]) and (x["type"] or {}).get("name") == (before[d]["type"] or {}).get("name"),
          f"bulk undo: document {d} as before")
r = A.post(B + "/api/docs/bulk", json={"ids": [D1], "sender": "Telekom Deutschland"})
check(r.ok and r.json()["changed"] == [], "bulk: the same value changes nothing")
check(A.post(B + "/api/docs/bulk", json={"ids": [D1]}).status_code == 400, "bulk: nothing to change = 400")
check(A.post(B + "/api/docs/bulk", json={"ids": list(range(1, 600)), "add_tags": ["X"]}).status_code == 413, "bulk: at most 500 per request")
r = Ca.post(B + "/api/docs/bulk", json={"ids": [D1, D2], "add_tags": ["Fremd"]})
check(r.ok and r.json()["changed"] == [] and "Fremd" not in [t["name"] for t in A.get(B + f"/api/docs/{D1}").json()["tags"]], "carol: alice's documents unchanged")
# a member with view only: counted, not changed
OD = doc_new(A, "alpha.txt", "Alpha Rechnung Beispiel", ws=f"org:{ORG}")
ROOT = A.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).json()["root_id"]
A.patch(B + f"/api/files/nodes/{ROOT}", json={"org_access": "view"})
r = Bo.post(B + "/api/docs/bulk", json={"ids": [OD], "type": "Fremd"})
check(r.ok and r.json()["changed"] == [] and r.json()["denied"] == 1, f"member with view: denied, not changed ({r.text[:200]})")
check(Bo.get(B + f"/api/docs/{OD}").ok and not (Bo.get(B + f"/api/docs/{OD}").json().get("type") or {}).get("name") == "Fremd", "the document is as it was")

# the ZIP
r = A.post(B + "/api/docs/zip", json={"ids": [D1, D2, D3]})
check(r.ok and r.json()["files"] == 3 and r.json()["url"].startswith("/api/docs/zip/"), f"ZIP: the check ({r.text[:200]})")
url = r.json().get("url", "")
check(Bo.get(B + url).status_code == 404, "ZIP: the ticket is not bob's")
z = A.get(B + url)
names = []
if z.ok:
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    names = sorted(zf.namelist())
    check(b"Mobilfunk" in zf.read("telekom.txt"), "ZIP: the plain content (the file was sealed at rest)")
check(z.ok and names == ["allianz.txt", "prospekt.txt", "telekom.txt"], f"ZIP: three documents ({z.status_code} {names})")
check(A.get(B + url).status_code == 404, "ZIP: a ticket works once")
D4 = doc_new(A, "zweite.txt", "Noch eine Rechnung Beispiel", folder="Ablage 2025", tags=[])  # (the learnt tags off)
r = A.patch(B + f"/api/docs/{D4}", json={"name": "telekom.txt"})
check(r.ok and r.json()["name"] == "telekom.txt", f"setup: a second telekom.txt in another folder ({r.text[:160]})")
r = A.post(B + "/api/docs/zip", json={"ids": [D1, D4]})
z = A.get(B + r.json()["url"]) if r.ok else None
check(z is not None and z.ok and sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == ["telekom (2).txt", "telekom.txt"], "ZIP: the same name twice")
r = A.post(B + "/api/docs/zip", json={"ids": [D0, D1, D2, D3, D4]})
check(r.status_code == 413 and "4" in r.text, f"ZIP: over the limit (4 here) = 413 with the hint ({r.status_code} {r.text[:200]})")
r = Ca.post(B + "/api/docs/zip", json={"ids": [D1, D2]})
check(r.status_code == 404, "carol: no ZIP of alice's documents")
r = A.post(B + "/api/docs/zip", json={"ids": [D1, F1]})
check(r.ok and r.json()["files"] == 1, "ZIP: a plain file is no document (left out)")
check(A.post(B + "/api/docs/zip", json={"ids": []}).status_code == 400, "ZIP: no ids = 400")
check(AGS.post(B + "/api/docs/zip", json={"ids": [D1]}).status_code in (401, 403), "ZIP: not for agents (API v1)")

# the API v1 list: the new filters and the syntax; an agent only shared documents
check(AGS.get(B + "/api/v1/documents", params={"q": "tag:steuer"}).json()["data"] == [], "agent: nothing unshared, also with the syntax")
r = A.post(B + f"/api/files/nodes/{DOCROOT}/shares", json={"agent_id": PAG, "role": "view"})
check(r.status_code == 201, f"share the documents folder with the agent ({r.text[:120]})")
v = lambda **p: sorted(x["id"] for x in AGS.get(B + "/api/v1/documents", params=p).json().get("data", []))  # noqa: E731
r = AGS.get(B + "/api/v1/documents", params={"q": "tag:steuer -tag:privat"})
check(v(q="tag:steuer -tag:privat") == sorted([D0, D2]), f"API v1: the search syntax ({r.status_code} {[x['id'] for x in r.json().get('data', [])] if r.ok else r.text[:200]} vs {sorted([D0, D2])}; all {v()})")
check(v(tag=f"{T_ST};{T_PR}", tag_mode="all") == [D1], f"API v1: tag groups, every one ({v(tag=f'{T_ST};{T_PR}', tag_mode='all')})")
check(v(no_tag="1") == sorted([D3, D4]), f"API v1: without tag ({v(no_tag='1')} vs {sorted([D3, D4])})")
check(AGS.get(B + "/api/v1/documents", params={"bogus": "1"}).status_code == 400, "API v1: unknown parameters still 400")

# freelancer-matrix: files -- the documents of a person without an organisation
E1 = doc_new(Fr, "honorar.txt", "Honorar Rechnung Beispiel", date="2025-05-05", sender="Kunde B GmbH", type="Rechnung", tags=["Steuer"])
E2 = doc_new(Fr, "miete.txt", "Miete Büro Beispiel", date="2024-02-01", tags=["Privat"])
check(ids(Fr, q="tag:steuer") == [E1] and ids(Fr, q="datum:2024") == [E2], "freelancer: the syntax")
check(ids(Fr, no_sender="1") == [E2], "freelancer: without sender")
r = Fr.post(B + "/api/docs/bulk", json={"ids": [E1, E2], "add_tags": ["2025"]})
check(r.ok and len(r.json()["changed"]) == 2, "freelancer: bulk change")
r = Fr.post(B + "/api/docs/zip", json={"ids": [E1, E2]})
z = Fr.get(B + r.json()["url"]) if r.ok else None
check(z is not None and z.ok and len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 2, "freelancer: ZIP")
check(ids(A, q="tag:2025") == [], "the admin never finds the freelancer's documents")

print(f"p2122_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
