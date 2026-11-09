#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.777.0 B (#4874): pages of a PDF document deleted / turned as a NEW VERSION of its file (kalmido/docs/pages.py).
Own container (start.sh). Invented names only; the PDFs are drawn in the test container (Pillow) like p2580_c_autosplit.
freelancer-matrix: files
 - GET .../pages: the page count, the file's version, the blank page the stack scan found (page 2 of 3: white), receipt false
 - page 2 of 3 deleted: 201, a new version with 2 pages (the file itself read back), version 1 still there with 3 pages;
   the document keeps its id, archive number, tags and sender; the recognition ran again (pages 2); the blank mark gone
 - page 1 turned by 90 degrees: the new version's page 1 carries /Rotate 90, the others not
 - undo = "Restore version" of the file store: the version before on top again (3 pages); 2.777.0 (#5254): the save is a step
   of the undo list too (GET /api/undo), taken back there the file points at its version before (no copy), redo forward
 - refused: invalid indices (0, past the end, twice, a bool, a wrong angle, every page deleted, nothing changed) 400; a stale
   expect_version 409 with nothing stored; read only (shared to view) 403; somebody else's document unseen 404; a plain
   text document 409
 - everything as a person without organisation (frida), the share / foreign cases with alice
Red without the feature: the routes answer 404/405.
usage: p2777_b_docpages_test.py <datadir>   (P2777B_NOSTART=1: the container runs already)"""
import base64
import json
import subprocess
import sys

import kt
from kt import B, CT, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P2777B")
A = kt.setup()
FEAT = "docs,files,office"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, features=FEAT)
GID, Gr = freelancer(B, A, name="gustav", features=FEAT)

PDF_CODE = r"""
import base64, io, json, sys
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=44)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(spec.split('\n') if spec else []):
        d.text((150, 400 + i * 90), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
"""

# the pages of a PDF and their /Rotate, read with pypdf in the container
READ_CODE = r"""
import base64, io, json, sys
from pypdf import PdfReader
r = PdfReader(io.BytesIO(base64.b64decode(sys.stdin.read())))
print(json.dumps([int(p.get('/Rotate', 0) or 0) % 360 for p in r.pages]))
"""


def make_pdf(pages):
    out = subprocess.run(["docker", "exec", CT, "python", "-c", PDF_CODE, json.dumps(pages)], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


def rotations(data):
    out = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", READ_CODE], input=base64.b64encode(data).decode(),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def up(s, name, data, mime="application/pdf"):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, mime))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid, secs=180):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def content(s, nid, v=None):
    r = s.get(B + f"/api/files/nodes/{nid}/content" + (f"?v={v}" if v else ""))
    assert r.ok, r.text
    return r.content


def node(s, nid):
    return s.get(B + f"/api/files/nodes/{nid}").json()


THREE = ["Rechnung Beispiel GmbH\nSeite eins\nSumme 42,00 EUR", "", "Seite drei\nKontakt Beispielweg 1"]

# ================================================================ GET: pages, version, blank page (a person without organisation)
D = up(Fr, "drei-seiten.pdf", make_pdf(THREE))
d0 = done(Fr, D)
check(d0 and d0["state"] == "done" and d0["pages"] == 3, f"setup: a three-page PDF recognised ({d0 and (d0['state'], d0['pages'])})")
r = Fr.patch(B + f"/api/docs/{D}", json={"asn": "next", "tags": ["Strom", "Wichtig"], "sender": "Beispiel GmbH"})
check(r.ok, f"setup: archive number, tags and sender set ({r.status_code} {r.text[:200]})")
before = doc(Fr, D)
ASN, TAGS, SENDER = before["asn"], sorted(t["name"] for t in before["tags"]), (before["sender"] or {}).get("name")
check(ASN and TAGS == ["Strom", "Wichtig"] and SENDER == "Beispiel GmbH", f"setup: the values are there ({ASN} {TAGS} {SENDER})")
g = until(lambda: (lambda j: j if j.get("blank") else None)(Fr.get(B + f"/api/docs/{D}/pages").json()), 60)
check(g and g["pages"] == 3 and g["version"] == 1 and g["blank"] == [2] and g["receipt"] is False and g["write"] is True,
      f"GET pages: 3 pages, version 1, page 2 marked blank (a suggestion) {g}")
check(len(content(Fr, D)) > 0 and rotations(content(Fr, D)) == [0, 0, 0], "the original: three pages, none turned")

# ================================================================ refused: invalid indices 400, nothing stored
for bad, what in (({"delete": [0]}, "page 0"), ({"delete": [4]}, "past the end"), ({"delete": [2, 2]}, "a page twice"),
                  ({"delete": [True]}, "a bool"), ({"delete": "2"}, "not a list"), ({"rotate": {"1": 45}}, "45 degrees"),
                  ({"rotate": {"x": 90}}, "a page that is no number"), ({"rotate": {"5": 90}}, "rotate past the end"),
                  ({"delete": [1, 2, 3]}, "every page"), ({}, "nothing changed"), ({"rotate": {"1": 360}}, "a full turn only")):
    r = Fr.post(B + f"/api/docs/{D}/pages", json={**bad, "expect_version": 1})
    check(r.status_code == 400, f"invalid ({what}) -> 400 ({r.status_code} {r.text[:120]})")
check(node(Fr, D)["version"] == 1, "... nothing stored: still version 1")

# a stale version: 409 with the file as it is now, nothing stored
r = Fr.post(B + f"/api/docs/{D}/pages", json={"delete": [2], "expect_version": 7})
check(r.status_code == 409 and r.json().get("current"), f"a stale expect_version -> 409 with the current file ({r.status_code})")
check(node(Fr, D)["version"] == 1, "... nothing stored")

# ================================================================ rights: unseen 404, read only 403
r = Gr.post(B + f"/api/docs/{D}/pages", json={"delete": [2]})
check(r.status_code in (403, 404) and Gr.get(B + f"/api/docs/{D}/pages").status_code in (403, 404),
      f"somebody else's document (not shared): refused, unseen ({r.status_code})")
r = Fr.post(B + f"/api/files/nodes/{D}/shares", json={"user_id": GID, "role": "view"})
check(r.ok, f"setup: shared with gustav to view ({r.status_code} {r.text[:120]})")
r = Gr.post(B + f"/api/docs/{D}/pages", json={"delete": [2], "expect_version": 1})
check(r.status_code == 403, f"read only: 403 ({r.status_code})")
g2 = Gr.get(B + f"/api/docs/{D}/pages")
check(g2.ok and g2.json()["write"] is False, f"read only: GET tells the strip it cannot write ({g2.status_code})")
check(node(Fr, D)["version"] == 1, "... nothing stored")

# ================================================================ page 2 of 3 deleted -> a new version with 2 pages
r = Fr.post(B + f"/api/docs/{D}/pages", json={"delete": [2], "expect_version": 1})
check(r.status_code == 201 and r.json().get("version") == 2 and r.json().get("was") == 1 and r.json().get("pages") == 2,
      f"page 2 deleted: 201, version 2 with 2 pages ({r.status_code} {r.text[:200]})")
n = node(Fr, D)
check(n["version"] == 2 and [v["no"] for v in n["versions"]] == [2, 1], f"the file: version 2 on top, version 1 kept {[v['no'] for v in n['versions']]}")
check(rotations(content(Fr, D)) == [0, 0], "the new version has 2 pages")
check(rotations(content(Fr, D, 1)) == [0, 0, 0], "version 1 can still be fetched with its 3 pages")
d2 = until(lambda: (lambda d: d if d and d["state"] == "done" and d["pages"] == 2 else None)(doc(Fr, D)), 180)
check(d2 and d2["pages"] == 2, f"recognised again: the page count says 2 ({d2 and d2['pages']})")
d2 = d2 or doc(Fr, D)
check(d2["id"] == D and d2["asn"] == ASN and sorted(t["name"] for t in d2["tags"]) == TAGS and (d2["sender"] or {}).get("name") == SENDER,
      f"the document keeps id, archive number, tags and sender ({d2['asn']} {[t['name'] for t in d2['tags']]} {d2['sender']})")
g = Fr.get(B + f"/api/docs/{D}/pages").json()
check(g["pages"] == 2 and g["version"] == 2 and g["blank"] == [], f"GET pages after: 2 pages, version 2, the blank page gone {g}")

# ================================================================ turned: page 1 by 90 degrees
r = Fr.post(B + f"/api/docs/{D}/pages", json={"rotate": {"1": 90}, "expect_version": 2})
check(r.status_code == 201 and r.json().get("version") == 3, f"page 1 turned: version 3 ({r.status_code} {r.text[:200]})")
check(rotations(content(Fr, D)) == [90, 0], f"the new version: page 1 turned by 90, page 2 not {rotations(content(Fr, D))}")
until(lambda: (lambda d: d and d["state"] == "done")(doc(Fr, D)), 180)
r = Fr.post(B + f"/api/docs/{D}/pages", json={"rotate": {"1": -90, "2": 270}, "expect_version": 3})
check(r.status_code == 201 and rotations(content(Fr, D)) == [0, 270], f"turned back left and page 2 by 270 ({r.status_code})")
until(lambda: (lambda d: d and d["state"] == "done")(doc(Fr, D)), 180)

# ================================================================ 2.777.0 (#5254): the save is a step of the undo list (all devices)
st = (Fr.get(B + "/api/undo").json().get("items") or [{}])[0]
check(st.get("kind") == "fs_node" and st.get("ref_id") == D and st.get("undo"), f"#5254: the pages save is the newest step of the list {st}")
r = Fr.post(B + f"/api/undo/to/{st.get('id')}")
check(r.ok and node(Fr, D)["version"] == 3 and rotations(content(Fr, D)) == [90, 0],
      f"#5254: taken back from the list: the file points at version 3 again, no copy ({r.status_code} {r.text[:200]})")
until(lambda: (lambda d: d and d["state"] == "done")(doc(Fr, D)), 180)
r = Fr.post(B + f"/api/undo/{st.get('id')}/redo")
check(r.ok and node(Fr, D)["version"] == 4 and rotations(content(Fr, D)) == [0, 270], f"#5254: redo: version 4 again ({r.status_code})")
until(lambda: (lambda d: d and d["state"] == "done")(doc(Fr, D)), 180)

# ================================================================ undo: the file store's "Restore version" (one step)
r = Fr.post(B + f"/api/files/nodes/{D}/versions/1/restore", json={"expect_version": 4})
check(r.ok and node(Fr, D)["version"] == 5 and rotations(content(Fr, D)) == [0, 0, 0], f"undo: version 1 on top again with 3 pages ({r.status_code})")
d5 = until(lambda: (lambda d: d if d and d["state"] == "done" and d["pages"] == 3 else None)(doc(Fr, D)), 180)
check(d5 and d5["asn"] == ASN and sorted(t["name"] for t in d5["tags"]) == TAGS, "... recognised again with 3 pages, the values stay")

# ================================================================ not a PDF: 409 (the strip does not show)
T = up(Fr, "notiz.txt", b"Eine Notiz ohne Seiten\n", "text/plain")
done(Fr, T)
check(Fr.get(B + f"/api/docs/{T}/pages").status_code == 409 and Fr.post(B + f"/api/docs/{T}/pages", json={"delete": [1]}).status_code == 409,
      "a text document: 409 (only PDFs)")

# ================================================================ alice (the instance admin) too: a one-page PDF turned
D1 = up(A, "eine-seite.pdf", make_pdf(["Brief Beispiel Verein\nEine Seite"]))
check(done(A, D1) and A.get(B + f"/api/docs/{D1}/pages").json().get("pages") == 1, "alice: a one-page PDF")
check(A.post(B + f"/api/docs/{D1}/pages", json={"delete": [1]}).status_code == 400, "... its only page cannot be deleted (400)")
r = A.post(B + f"/api/docs/{D1}/pages", json={"rotate": {"1": 180}})
check(r.status_code == 201 and rotations(content(A, D1)) == [180], f"... turned by 180 without expect_version (old clients) ({r.status_code})")
check(Fr.get(B + f"/api/docs/{D1}/pages").status_code == 404, "frida never sees alice's document (404)")

sys.exit(kt.done("p2777_b_docpages"))
