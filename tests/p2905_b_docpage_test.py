#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.905.0 (#5393): the first page's size of a document (doc_json "page"): the document view's preview picture takes the full
first page's size and place before the file is loaded. Kept in doc_meta.auto["_pg"] by the recognition (docs/store.py
process -> docs/pagesize.py pg_of), documents from before get it from the catch-up (docs/thumbfill.py p5393_page_fill).
Rebuilt on main from the template of job/3917 (tests/p2889_b_docpage_test.py there).
 (a) a PDF: [w, h, widest] in points as pdf.js shows it at scale 1 (A4, a crop box, a page turned by /Rotate 90, a second
     page wider than the first)
 (b) a picture: its pixels as the browser shows it (PNG; a JPEG with EXIF orientation 6 turned)
 (c) a view value of the app: not under "auto", not in API v1
 (d) the catch-up: a document from before (no size) gets it while the queue is idle
 (e) review F1 (job/3684): a PNG's size is read from its header only, never decoded in the app process; a WebP's from its RIFF
     header (never through Pillow; a forged huge canvas gives no size)
 (f) 2.990.0 (#5571): no free PDF slot during a recognition run keeps the stored size
All as a person WITHOUT an organisation (freelancer). Invented pages and pictures only (made here).
usage: p2905_b_docpage_test.py <datadir>
freelancer-matrix: docs"""
import io
import json
import os
import subprocess
import sys

import requests
from PIL import Image

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, dbx, done, fresh, setup, until  # noqa: E402

fresh({"KALMIDO_DOCS_THUMB_FILL_S": "1"}, prefix="P2905B")
A = setup()
FID, Fr = freelancer(B, A, "frida", features="collab,files,docs")


def build(objs):
    """A PDF of the given objects (str each), object 1 the catalog."""
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n".encode() + o.encode("latin1") + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def pdf(page, page2=None):
    st = "BT /F1 14 Tf 60 500 Td (Muster Stadtwerke Rechnung 4711) Tj ET"
    two = page2 is not None
    return build(["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [4 0 R{' 6 0 R' if two else ''}] /Count {2 if two else 1} >>",
                  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                  f"<< /Type /Page /Parent 2 0 R {page} /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>",
                  f"<< /Length {len(st)} >>\nstream\n{st}\nendstream"]
                 + ([f"<< /Type /Page /Parent 2 0 R {page2} /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>"] if two else []))


def picture(fmt, w, h, orient=None):
    im = Image.new("RGB", (w, h), (236, 234, 228))
    buf = io.BytesIO()
    if orient:
        ex = Image.Exif()
        ex[0x0112] = orient
        im.save(buf, fmt, exif=ex.tobytes())
    else:
        im.save(buf, fmt)
    return buf.getvalue()


def wait(nid):
    until(lambda: Fr.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return Fr.get(B + f"/api/docs/{nid}").json()


def up_doc(name, data, mime):
    r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, data, mime)})
    assert r.ok, r.text
    return wait(r.json()["ids"][0])


cases = [("(a) an A4 PDF", "a4.pdf", pdf("/MediaBox [0 0 595 842]"), "application/pdf", [595, 842, 595]),
         ("(a) a PDF with a crop box", "crop.pdf", pdf("/MediaBox [0 0 600 800] /CropBox [50 40 550 740]"), "application/pdf", [500, 700, 500]),
         ("(a) a page turned by /Rotate 90", "turned.pdf", pdf("/MediaBox [0 0 612 792] /Rotate 90"), "application/pdf", [792, 612, 792]),
         ("(a) a second page wider than the first", "wide2.pdf", pdf("/MediaBox [0 0 595 842]", "/MediaBox [0 0 842 595]"), "application/pdf", [595, 842, 842]),
         ("(b) a PNG", "photo.png", picture("PNG", 300, 200), "image/png", [300, 200]),
         ("(b) a JPEG with EXIF orientation 6", "phone.jpg", picture("JPEG", 400, 300, 6), "image/jpeg", [300, 400])]
D = {}
for what, name, data, mime, want in cases:
    d = up_doc(name, data, mime)
    D[name] = d
    check(d.get("state") == "done", f"{what}: recognised {d.get('state')} {d.get('error')}")
    check(d.get("page") == want, f"{what}: the first page's size {want} (got {d.get('page')})")
    check("_pg" not in (d.get("auto") or {}), f"{what}: the size is not listed under auto {d.get('auto')}")
lst = {x["id"]: x for x in Fr.get(B + "/api/docs?ws=private&facets=0").json().get("docs", [])}
check(lst.get(D["a4.pdf"]["id"], {}).get("page") == [595, 842, 595], "the list carries the size as well (the view opens from it)")

# (c) API v1 has no "page" (a view value of the app, like thumb)
tok = Fr.post(B + "/api/me/tokens", json={"name": "p2905b", "scopes": ["files:read"]})
if tok.ok and tok.json().get("token"):
    v = requests.get(B + f"/api/v1/documents/{D['a4.pdf']['id']}", headers={"Authorization": "Bearer " + tok.json()["token"]})
    check(v.ok and "page" not in v.json() and "_pg" not in (v.json().get("auto") or {}), f"(c) API v1 carries no page {v.status_code} {sorted(v.json())[:40]}")
else:
    check(False, f"(c) a token for API v1 {tok.status_code} {tok.text[:200]}")

# (d) the catch-up: the size taken away (a document from before), the setting reset -> it comes back while the queue is idle
P = D["turned.pdf"]["id"]
auto = json.loads(dbx("SELECT auto FROM doc_meta WHERE node_id=?", (P,))[0][0] or "{}")
check(auto.get("_pg") == [792, 612, 792], f"(d) stored as auto._pg {auto}")
auto.pop("_pg", None)
dbx("UPDATE doc_meta SET auto=? WHERE node_id=?", (json.dumps(auto), P))
dbx("DELETE FROM settings WHERE key='docs_page_fill'")
check(Fr.get(B + f"/api/docs/{P}").json().get("page") is None, "(d) without the size: none (the view sizes the preview from its proportions)")
check(until(lambda: Fr.get(B + f"/api/docs/{P}").json().get("page") == [792, 612, 792], 120), "(d) the catch-up sets the size again")
check(until(lambda: '"done"' in (dbx("SELECT value FROM settings WHERE key='docs_page_fill'") or [[""]])[0][0], 60), "(d) the catch-up ends with done")

# (e) review F1: a PNG without an eXIf chunk is never decoded in the app process (getexif() would load it) -- run in the app's
# container, where the module and its imports are
F1 = r"""
import io
from PIL import Image, PngImagePlugin
from kalmido.docs.pagesize import pg_of as dp_page1
n, load = [], PngImagePlugin.PngImageFile.load
PngImagePlugin.PngImageFile.load = lambda self: (n.append(1), load(self))[1]
b = io.BytesIO()
Image.new("RGB", (300, 200), "white").save(b, "PNG")
print(dp_page1(b.getvalue(), "image"), dp_page1(b"<svg/>", "image"), dp_page1(b"x", "docx"), len(n))
# a WebP never through Pillow (its animation decoder reserves the canvas): the size from the RIFF header;
# a forged VP8X canvas of 16777216 x 16777216 gives no size, at once and without memory
import time, tracemalloc
w = io.BytesIO()
Image.new("RGB", (321, 123)).save(w, "WEBP")
huge = b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8X" + (10).to_bytes(4, "little") + bytes([0x12, 0, 0, 0]) + (2 ** 24 - 1).to_bytes(3, "little") * 2 + b"ANIM" + bytes(64)
tracemalloc.start(); t0 = time.monotonic()
big = dp_page1(huge, "image")
print("WEBP", dp_page1(w.getvalue(), "image"), big, time.monotonic() - t0 < 1, tracemalloc.get_traced_memory()[1] < 8 << 20)
# a TIFF is not read in the app process (its IFD tags may each point at the whole file), a PNG's eXIf chunk is
# never parsed (getexif() not called), a JPEG keeps its EXIF orientation
t = io.BytesIO()
Image.new("RGB", (40, 30)).save(t, "TIFF")
ex = Image.Exif(); ex[0x0112] = 6
pe, je = io.BytesIO(), io.BytesIO()
Image.new("RGB", (40, 30)).save(pe, "PNG", exif=ex.tobytes())
Image.new("RGB", (40, 30)).save(je, "JPEG", exif=ex.tobytes())
g, getexif = [], Image.Image.getexif
Image.Image.getexif = lambda self: (g.append(self.format), getexif(self))[1]
print("TIFF", dp_page1(t.getvalue(), "image"), dp_page1(pe.getvalue(), "image"), dp_page1(je.getvalue(), "image"), sorted(set(g)))  # Pillow may call getexif() more than once
"""
r = subprocess.run(["docker", "exec", CT, "python3", "-c", F1], capture_output=True, text=True, timeout=120)
out = r.stdout.strip().splitlines()
check(bool(out) and out[0].endswith("[300, 200] None None 0"), f"(e) the PNG's size read from its header only {r.stdout.strip()!r} {r.stderr[-300:]!r}")
check(len(out) > 1 and out[1] == "WEBP [321, 123] None True True", f"(e) a WebP's size from its header, a huge canvas gives none at once {out[1:]!r} {r.stderr[-300:]!r}")
check(len(out) > 2 and out[2] == "TIFF None [40, 30] [30, 40] ['JPEG']", f"(e) no TIFF, no PNG eXIf parsed, a JPEG turned by its EXIF {out[2:]!r} {r.stderr[-300:]!r}")

# (f) 2.990.0 (#5571): a recognition run that finds no free PDF slot keeps the stored size (the catch-up is done already, it
# would not ask again); content without a size (no slot problem) still drops it. Run in the app's container (S.pg_of replaced).
F5571 = r"""
import sys
sys.path.insert(0, "/app")
from kalmido.docs import store as S
from kalmido.docs.pagesize import PgBusy
from kalmido.core.db import connect
def busy(data, kind, wait=2, strict=False):
    if strict:
        raise PgBusy()
    return None
for name, f in (("busy", busy), ("none", lambda *a, **k: None)):
    S.pg_of = f
    c = connect()
    st = S.process(c, %d)
    c.commit()
    pg = S.meta_json(c, S.meta_row(c, %d), "auto", {}).get("_pg")
    print(name, st, [round(x) for x in pg] if pg else None)
    c.close()
"""
r = subprocess.run(["docker", "exec", "-i", "-w", "/app", CT, "python", "-"], input=F5571 % (P, P), capture_output=True, text=True, timeout=180)
out = r.stdout.strip().splitlines()
check(len(out) > 0 and out[0] == "busy done [792, 612, 792]", f"(f) no free PDF slot: the stored size stays (was: dropped) {out!r} {r.stderr[-400:]!r}")
check(len(out) > 1 and out[1] == "none done None", f"(f) content without a size: the old size goes {out[1:]!r} {r.stderr[-300:]!r}")
sys.exit(done("p2905_b_docpage"))
