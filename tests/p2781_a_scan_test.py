#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.781.0 part A (#5390): the scan mark of a document (docs/scanmark.py, doc_meta.auto["_scan"], doc_json "scan") -- it
decides whether the document view shows the archive number field for a document without a number (tests/p2497_a_docform_ui.js).
 (a) a digital PDF with vector text: no scan
 (b) a PDF of one page-filling picture (no text): a scan
 (c) a page-filling picture with an invisible OCR layer (text render mode 3), as a scanner writes it: a scan
 (d) the same picture with VISIBLE text drawn on top (a digital letter on a background picture): no scan
 (e) a picture (PNG): a scan
 (f) a scan inbox (the folder watcher's key): even a digital PDF counts as a scan
 (g) the mark is the app's: API v1 does not carry "scan", "auto" has no "_scan"
 (h) a document from before (no mark): the catch-up (docs/thumbfill.py p5390_scan_fill) sets it while the queue is idle
All as a person WITHOUT an organisation (freelancer). Invented names, pages and pictures only (made here).
usage: p2781_a_scan_test.py <datadir>
freelancer-matrix: docs"""
import base64
import io
import json
import os
import sys

import requests
from PIL import Image, ImageDraw

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, setup, until  # noqa: E402

fresh({"KALMIDO_DOCS_THUMB_FILL_S": "1"}, prefix="P2781A")
A = setup()
FID, Fr = freelancer(B, A, "frida", features="collab,files,docs")


def esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build(objs):
    """A PDF of the given objects (bytes or str each), object 1 the catalog."""
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n".encode() + (o if isinstance(o, bytes) else o.encode("latin1")) + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def stream(data, extra=""):
    data = data if isinstance(data, bytes) else data.encode("latin1")
    return f"<< /Length {len(data)}{extra} >>\nstream\n".encode() + data + b"\nendstream"


def text_pdf(lines):
    """A digital one-page PDF: vector text only."""
    st = "BT /F1 14 Tf 60 760 Td 18 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    return build(["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
                  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                  "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>",
                  stream(st)])


def page_jpeg(lines):
    """A 'photographed' page: grey paper with dark text drawn as pixels."""
    im = Image.new("RGB", (595, 842), (236, 234, 228))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((60, 80 + 22 * i), ln, fill=(20, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def picture_pdf(lines, mode=None):
    """One page filled by a JPEG picture; mode 3 = an invisible OCR text layer on top (as a scanner writes it), mode 0 = the
    text drawn visibly on top, None = no text."""
    jpg = page_jpeg(lines)
    st = "q 595 0 0 842 0 0 cm /Im0 Do Q"
    if mode is not None:
        st += f" BT {mode} Tr /F1 12 Tf 60 760 Td 22 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    return build(["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
                  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                  "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> /XObject << /Im0 6 0 R >> >> >>",
                  stream(st),
                  stream(jpg, " /Type /XObject /Subtype /Image /Width 595 /Height 842 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode")])


def picture_form_pdf(lines):
    """2.836.0 (#5390, review): like picture_pdf(lines, 3), but the invisible mode is set on the page and the OCR text is
    drawn inside a form XObject -- the text render mode is inherited into it, so this is still a scan."""
    jpg = page_jpeg(lines)
    form = "BT /F1 12 Tf 60 760 Td 22 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    st = "q 595 0 0 842 0 0 cm /Im0 Do Q 3 Tr /Fm0 Do"
    return build(["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
                  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                  "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> /XObject << /Im0 6 0 R /Fm0 7 0 R >> >> >>",
                  stream(st),
                  stream(jpg, " /Type /XObject /Subtype /Image /Width 595 /Height 842 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"),
                  stream(form, " /Type /XObject /Subtype /Form /BBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >>")])


def pillow_pdf(lines):
    """The PDF Pillow writes of a picture (like the phone scan, files/bulk.py abm_pdf)."""
    buf = io.BytesIO()
    Image.open(io.BytesIO(page_jpeg(lines))).save(buf, "PDF", resolution=72)
    return buf.getvalue()


def png(lines):
    buf = io.BytesIO()
    Image.open(io.BytesIO(page_jpeg(lines))).save(buf, "PNG")
    return buf.getvalue()


def wait(nid):
    until(lambda: Fr.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return Fr.get(B + f"/api/docs/{nid}").json()


def up_doc(name, data, mime):
    r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, data, mime)})
    assert r.ok, r.text
    return wait(r.json()["ids"][0])


LETTER = ["Muster Stadtwerke", "Rechnung Nr. 4711", "Datum 03.10.2026", "Betrag 119,00 EUR"]

# (a) .. (e)
cases = [("(a) a digital PDF with vector text", "digital.pdf", text_pdf(LETTER), "application/pdf", False),
         ("(b) a PDF of one page-filling picture", "picture.pdf", picture_pdf(LETTER), "application/pdf", True),
         ("(b) the PDF Pillow writes (phone scan)", "phonescan.pdf", pillow_pdf(LETTER), "application/pdf", True),
         ("(c) a picture + invisible OCR layer (mode 3)", "scanner-ocr.pdf", picture_pdf(LETTER, 3), "application/pdf", True),
         ("(c) the OCR layer's mode set on the page, its text in a form", "scanner-form.pdf", picture_form_pdf(LETTER), "application/pdf", True),
         ("(d) a picture + visible text on top", "background.pdf", picture_pdf(LETTER, 0), "application/pdf", False),
         ("(e) a PNG picture", "photo.png", png(LETTER), "image/png", True)]
D = {}
for what, name, data, mime, want in cases:
    d = up_doc(name, data, mime)
    D[name] = d
    check(d.get("state") == "done", f"{what}: recognised {d.get('state')} {d.get('error')}")
    check(d.get("scan") is want, f"{what}: scan {want} (got {d.get('scan')})")
    check("_scan" not in (d.get("auto") or {}), f"{what}: the mark is not listed under auto {d.get('auto')}")
# (c) the scanner's OCR text is read as the text layer (it is a PDF with text), still a scan
check("4711" in (Fr.get(B + f"/api/docs/{D['scanner-ocr.pdf']['id']}").json().get("text") or ""), "(c) the OCR layer is the document's text")
# the list says the same
lst = {x["id"]: x for x in Fr.get(B + "/api/docs?ws=private&facets=0").json().get("docs", [])}
check(lst.get(D["digital.pdf"]["id"], {}).get("scan") is False and lst.get(D["picture.pdf"]["id"], {}).get("scan") is True, "the list carries scan as well")


# (f) a scan inbox: a digital PDF through the folder watcher's key is a scan
def decode(code):
    raw = code.split(":", 2)[2]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner"})
check(r.status_code == 201, f"(f) a scan inbox {r.status_code} {r.text[:200]}")
key = decode(r.json().get("code", "kalmido-scan:1:e30")).get("key", "")
r = requests.post(B + "/api/v1/documents", headers={"Authorization": "Bearer " + key}, files={"file": ("inbox.pdf", text_pdf(LETTER), "application/pdf")})
check(r.status_code == 201, f"(f) upload through the inbox {r.status_code} {r.text[:200]}")
d = wait(r.json().get("id"))
check(d.get("source") == "scan" and d.get("scan") is True, f"(f) a document of a scan inbox is a scan {d.get('source')} {d.get('scan')}")

# (g) API v1 has no "scan" (a view flag of the app); documents need the scope files:read (#5390)
tok = Fr.post(B + "/api/me/tokens", json={"name": "p2781a", "scopes": ["read", "files:read"]})
if tok.ok and tok.json().get("token"):
    v = requests.get(B + f"/api/v1/documents/{D['picture.pdf']['id']}", headers={"Authorization": "Bearer " + tok.json()["token"]})
    check(v.ok and "scan" not in v.json() and "_scan" not in (v.json().get("auto") or {}), f"(g) API v1 carries no scan {v.status_code} {sorted(v.json())[:40]}")
else:
    check(False, f"(g) a token for API v1 {tok.status_code} {tok.text[:200]}")

# (h) the catch-up: the mark taken away (a document from before), the setting reset -> it comes back while the queue is idle
P = D["picture.pdf"]["id"]
auto = json.loads(dbx("SELECT auto FROM doc_meta WHERE node_id=?", (P,))[0][0] or "{}")
check(auto.get("_scan") == 1, f"(h) stored as auto._scan = 1 {auto}")
auto.pop("_scan", None)
dbx("UPDATE doc_meta SET auto=? WHERE node_id=?", (json.dumps(auto), P))
dbx("DELETE FROM settings WHERE key='docs_scan_fill'")
check(Fr.get(B + f"/api/docs/{P}").json().get("scan") is False, "(h) without the mark: no scan (the field stays hidden until it is known)")
check(until(lambda: Fr.get(B + f"/api/docs/{P}").json().get("scan") is True, 90), "(h) the catch-up sets the mark again")
check(until(lambda: '"done"' in (dbx("SELECT value FROM settings WHERE key='docs_scan_fill'") or [[""]])[0][0], 60), "(h) the catch-up ends with done")
check(Fr.get(B + f"/api/docs/{D['digital.pdf']['id']}").json().get("scan") is False, "(h) the digital one stays no scan")
sys.exit(done("p2781_a_scan"))
