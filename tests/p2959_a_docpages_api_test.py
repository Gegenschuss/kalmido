#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.959.0 A (#4805): pages of a PDF document reordered (POST /api/docs/<id>/pages order) and several PDF documents merged
into one (POST /api/docs/merge, kalmido/docs/docmerge.py). Own container (start.sh). Invented names only; the PDFs are drawn in
the test container (Pillow) with a different page width each, so the order of the pages can be read back (pypdf, mediabox).
freelancer-matrix: files
 - reorder: a permutation of the pages that stay (with a deleted page too) -> 201, a new version in that order, the old
   version kept; refused 400: a page missing / twice / past the end / a deleted page in it / not numbers / only the same order
 - merge: [D1 (2 pages), D3, D2] -> 201, D1 has a new version with all pages in that order, its archive number stays, version
   1 kept, it is recognised again (4 pages); D2 / D3 in the trash (404, listed in the trash)
 - undo (the person's step list, GET /api/undo): ONE step group takes it all back - D1 on its original version, D2 / D3 out
   of the trash again
 - refused: one id 400, a text document 409, a read-only share 403 (nothing changed), somebody else's unshared document 404,
   documents of two workspaces (another person's private document shared to edit; alice's organisation + her private one) 403
 - GoBD: a receipt of a locked month (office_period_locks) - reorder 409, merge as the first or as one of the others 409,
   nothing changed, nothing in the trash
 - everything as a person without organisation (frida), the share / workspace cases with gustav and alice
Red without the feature: POST /api/docs/merge answers 404/405, order is ignored (400 "Nothing to change").
usage: p2959_a_docpages_api_test.py <datadir>   (P2959A_NOSTART=1: the container runs already)"""
import base64
import json
import subprocess
import sys

import kt
from kt import B, CT, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P2959A")
A = kt.setup()
FEAT = "docs,files,office"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, features=FEAT)
GID, Gr = freelancer(B, A, name="gustav", features=FEAT)

# one page per width (pixels at 200 dpi -> the page's width in points = w * 72 / 200), a short text on each
PDF_CODE = r"""
import base64, io, json, sys
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=40)
pages = []
for w in json.loads(sys.argv[1]):
    im = Image.new('L', (w, 1400), 255)
    ImageDraw.Draw(im).text((60, 300), 'Seite Breite %d' % w, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
"""

READ_CODE = r"""
import base64, io, json, sys
from pypdf import PdfReader
r = PdfReader(io.BytesIO(base64.b64decode(sys.stdin.read())))
print(json.dumps([round(float(p.mediabox.width) * 200 / 72) for p in r.pages]))
"""


def make_pdf(widths):
    out = subprocess.run(["docker", "exec", CT, "python", "-c", PDF_CODE, json.dumps(widths)], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


def widths(data):
    out = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", READ_CODE], input=base64.b64encode(data).decode(),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def up(s, name, data, mime="application/pdf", ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, data, mime))])
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
    r = s.get(B + f"/api/files/nodes/{nid}")
    return r.json() if r.ok else None


def ver(s, nid):
    n = node(s, nid)
    return n and n["version"]


# ================================================================ reorder (a person without organisation)
D = up(Fr, "drei-seiten.pdf", make_pdf([600, 700, 800]))
check(done(Fr, D) and doc(Fr, D)["pages"] == 3, "setup: a three-page PDF recognised")
check(widths(content(Fr, D)) == [600, 700, 800], f"setup: the pages in their order {widths(content(Fr, D))}")
for bad, what in (({"order": [1, 2]}, "a page missing"), ({"order": [1, 1, 2, 3]}, "a page twice"), ({"order": [1, 2, 4]}, "past the end"),
                  ({"order": [3, 1, 2], "delete": [2]}, "a deleted page in the order"), ({"order": ["3", "1", "2"]}, "not numbers"),
                  ({"order": [True, 2, 3]}, "a bool"), ({"order": "3,1,2"}, "not a list"), ({"order": [1, 2, 3]}, "the same order only"),
                  # 2.976.0 (#5657): a superscript digit as the page key ("²".isdigit() is True) was a 500
                  ({"rotate": {"\u00b2": 90}}, "a superscript page number")):
    r = Fr.post(B + f"/api/docs/{D}/pages", json={**bad, "expect_version": 1})
    check(r.status_code == 400, f"reorder invalid ({what}) -> 400 ({r.status_code} {r.text[:120]})")
check(ver(Fr, D) == 1, "... nothing stored: still version 1")

r = Fr.post(B + f"/api/docs/{D}/pages", json={"order": [3, 1, 2], "expect_version": 1})
check(r.status_code == 201 and r.json().get("version") == 2 and r.json().get("pages") == 3, f"reorder 3,1,2: 201, version 2 ({r.status_code} {r.text[:200]})")
check(widths(content(Fr, D)) == [800, 600, 700], f"... the new version in the new order {widths(content(Fr, D))}")
check(widths(content(Fr, D, 1)) == [600, 700, 800], "... version 1 kept in the old order")
check(until(lambda: (lambda d: d and d["state"] == "done" and d["pages"] == 3)(doc(Fr, D)), 180), "... recognised again")
r = Fr.post(B + f"/api/docs/{D}/pages", json={"delete": [2], "order": [3, 1], "rotate": {"3": 90}, "expect_version": 2})
check(r.status_code == 201 and r.json().get("pages") == 2 and widths(content(Fr, D)) == [700, 800],
      f"delete + reorder + turn at once: the pages that stay in the new order ({r.status_code} {widths(content(Fr, D))})")
until(lambda: (lambda d: d and d["state"] == "done")(doc(Fr, D)), 180)

# ================================================================ merge
D1 = up(Fr, "teil-eins.pdf", make_pdf([500, 510]))
D2 = up(Fr, "teil-zwei.pdf", make_pdf([520]))
D3 = up(Fr, "teil-drei.pdf", make_pdf([530]))
for x in (D1, D2, D3):
    done(Fr, x)
r = Fr.patch(B + f"/api/docs/{D1}", json={"asn": "next", "tags": ["Vertrag"]})
check(r.ok, f"setup: archive number and a tag on the first ({r.status_code})")
ASN = doc(Fr, D1)["asn"]
check(ASN, f"setup: the first has archive number {ASN}")

r = Fr.post(B + "/api/docs/merge", json={"ids": [D1]})
check(r.status_code == 400, f"one document only: 400 ({r.status_code})")
T = up(Fr, "notiz.txt", b"Eine Notiz ohne Seiten\n", "text/plain")
done(Fr, T)
r = Fr.post(B + "/api/docs/merge", json={"ids": [D1, T]})
check(r.status_code == 409 and ver(Fr, D1) == 1 and doc(Fr, T), f"with a text document: 409, nothing changed ({r.status_code} {r.text[:160]})")

r = Fr.post(B + "/api/docs/merge", json={"ids": [D1, D3, D2], "expect_version": 1})
check(r.status_code == 201 and r.json().get("id") == D1 and r.json().get("version") == 2 and r.json().get("was") == 1 and r.json().get("pages") == 4
      and r.json().get("trashed") == [D3, D2], f"merge D1, D3, D2: 201, a new version of D1 with 4 pages ({r.status_code} {r.text[:200]})")
check(widths(content(Fr, D1)) == [500, 510, 530, 520], f"... all pages in the chosen order {widths(content(Fr, D1))}")
check(widths(content(Fr, D1, 1)) == [500, 510] and [v["no"] for v in node(Fr, D1)["versions"]] == [2, 1], "... the original stays as version 1")
check(doc(Fr, D2) is None and doc(Fr, D3) is None, "... the other two are gone from the documents (404)")
tr_ids = [x["id"] for x in Fr.get(B + "/api/files", params={"space": "trash"}).json().get("items", [])]
check(D2 in tr_ids and D3 in tr_ids, f"... and lie in the trash {tr_ids}")
dm = until(lambda: (lambda d: d if d and d["state"] == "done" and d["pages"] == 4 else None)(doc(Fr, D1)), 180)
check(dm and dm["asn"] == ASN and [t["name"] for t in dm["tags"]] == ["Vertrag"], f"... recognised again: 4 pages, archive number and tag stay {dm and (dm['pages'], dm['asn'])}")

# ================================================================ undo: ONE step of the person's list takes it all back
st = (Fr.get(B + "/api/undo").json().get("items") or [{}])[0]
check(st.get("id"), f"the merge is the newest step of the list {st}")
r = Fr.post(B + f"/api/undo/to/{st.get('id')}")
check(r.ok, f"undo the merge ({r.status_code} {r.text[:200]})")
check(ver(Fr, D1) == 1 and widths(content(Fr, D1)) == [500, 510], f"... D1 on its original again (2 pages) v{ver(Fr, D1)}")
check(doc(Fr, D2) and doc(Fr, D3), "... D2 and D3 back out of the trash")
check(until(lambda: (lambda d: d and d["state"] == "done" and d["pages"] == 2)(doc(Fr, D1)), 180), "... D1 recognised again with 2 pages")

# ================================================================ rights and workspaces
G1 = up(Gr, "gustav.pdf", make_pdf([540]))
done(Gr, G1)
r = Gr.post(B + "/api/docs/merge", json={"ids": [G1, D2]})
check(r.status_code == 404 and doc(Fr, D2), f"somebody else's document (not shared): 404, nothing changed ({r.status_code})")
check(Fr.post(B + f"/api/files/nodes/{D2}/shares", json={"user_id": GID, "role": "view"}).ok, "setup: D2 shared with gustav to view")
r = Gr.post(B + "/api/docs/merge", json={"ids": [G1, D2]})
check(r.status_code == 403 and ver(Gr, G1) == 1 and doc(Fr, D2), f"read only: 403, nothing changed ({r.status_code})")
r = Gr.post(B + "/api/docs/merge", json={"ids": [D2, G1]})
check(r.status_code == 403, f"read only as the first: 403 ({r.status_code})")
check(Fr.post(B + f"/api/files/nodes/{D3}/shares", json={"user_id": GID, "role": "edit"}).ok, "setup: D3 shared with gustav to edit")
r = Gr.post(B + "/api/docs/merge", json={"ids": [G1, D3]})
check(r.status_code == 403 and "workspace" in r.text and ver(Gr, G1) == 1 and doc(Fr, D3), f"another person's private area (shared to edit): 403 one workspace ({r.status_code} {r.text[:160]})")
ORG = A.post(B + "/api/orgs", json={"name": "Beispiel Verein"}).json().get("id")
if ORG:
    AO = up(A, "org.pdf", make_pdf([550]), ws=f"org:{ORG}")
    AP = up(A, "privat.pdf", make_pdf([560]))
    done(A, AO)
    done(A, AP)
    r = A.post(B + "/api/docs/merge", json={"ids": [AO, AP]})
    check(r.status_code == 403 and "workspace" in r.text and ver(A, AO) == 1 and doc(A, AP), f"alice: organisation + private: 403 one workspace ({r.status_code} {r.text[:160]})")
else:
    check(False, "setup: alice has an organisation")

# ================================================================ GoBD: a receipt of a locked month cannot be changed
check(Fr.put(B + "/api/office/settings", json={"pack": "DE"}).status_code == 200, "setup: frida's office has its country")
R = up(Fr, "beleg.pdf", make_pdf([570, 580]))
done(Fr, R)
r = Fr.put(B + f"/api/docs/{R}/receipt", json={"category": "Travel", "vat_pct": "19", "keep": True})
check(r.status_code == 200, f"setup: a receipt of the office ({r.status_code} {r.text[:200]})")
OFF = kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(OFF, "setup: frida's personal office")
kt.dbx("UPDATE doc_meta SET doc_date='2020-01-15' WHERE node_id=?", (R,))
kt.dbx("INSERT INTO office_period_locks(org_id, period, locked_by, locked_at) VALUES(?, '2020-01', ?, '2020-02-01T00:00:00Z')", (OFF[0][0], FID))
r = Fr.post(B + f"/api/docs/{R}/pages", json={"order": [2, 1]})
check(r.status_code == 409 and ver(Fr, R) == 1, f"locked receipt: reorder 409, nothing changed ({r.status_code} {r.text[:160]})")
r = Fr.post(B + "/api/docs/merge", json={"ids": [R, D1]})
check(r.status_code == 409 and ver(Fr, R) == 1 and doc(Fr, D1), f"locked receipt as the first: merge 409 ({r.status_code})")
r = Fr.post(B + "/api/docs/merge", json={"ids": [D1, R]})
check(r.status_code == 409 and ver(Fr, D1) == 1 and doc(Fr, R), f"locked receipt as one of the others: 409, not in the trash ({r.status_code} {r.text[:160]})")
g = Fr.get(B + f"/api/docs/{R}/pages").json()
check(g.get("write") is False, f"... the strip is told it cannot write {g}")

# ================================================================ 2.976.0 (#5657, review 2.959 F8): the merge's child process
# counts the pages itself (no dp_count per document): unknown counts (0) are counted there, more than the limit together is
# 413, a result over the output budget gets its own message "too large to merge" (413). Red before: _merge took
# [(bytes, pages)] and every count came from dp_count.
MERGE_PROBE = r"""
import io, json
from pypdf import PdfWriter
from kalmido.core.config import app as kapp
from kalmido.core.access import Denied
from kalmido.docs import docmerge as dm


def pdf(n):
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(200, 200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


res = {}
a, b = pdf(2), pdf(3)
with kapp.test_request_context('/api/docs/merge'):
    out, pages = dm._merge(bytearray(a + b), [len(a), len(b)], [0, 3])
    res['pages'], res['pdf'] = pages, out[:4].decode()
    try:
        dm._merge(bytearray(a + b), [len(a), len(b)], [2, 4])
    except Denied as e:
        res["mismatch"] = e.code
    dm.DP_PAGES = 4
    try:
        dm._merge(bytearray(a + b), [len(a), len(b)], [0, 0])
    except Denied as e:
        res["many"] = e.code
    dm.DP_PAGES, dm.MERGE_WORKER = 1000, dm.MERGE_WORKER.replace("2 * len(src) + (32 << 20)", "1")
    try:
        dm._merge(bytearray(a + b), [len(a), len(b)], [0, 0])
    except Denied as e:
        res['big'] = [e.code, e.msg]
res['no_dp_count'] = not hasattr(dm, 'dp_count')
print(json.dumps(res))
"""
r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + MERGE_PROBE],
                   capture_output=True, text=True)
pr = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1] or "{}") if r.returncode == 0 else {}
check(pr.get("pages") == 5 and pr.get("pdf") == "%PDF", f"#5657: the merge's child process counts the pages, an unknown count too {pr} {r.stderr[-300:]}")
check(pr.get("mismatch") == 409, f"#5657: a count other than the recognised one: 409 {pr}")
check(pr.get("many") == 413, f"#5657: more pages together than the limit, counted in the child process: 413 {pr}")
check((pr.get("big") or [0])[0] == 413 and "too large to merge" in str((pr.get("big") or ["", ""])[1]),
      f"#5657: a result over the budget: its own message 'too large to merge' (413) {pr}")
check(pr.get("no_dp_count") is True, "#5657: no child process per document any more (docmerge does not use dp_count)")

sys.exit(kt.done("p2959_a_docpages_api"))
