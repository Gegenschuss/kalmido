#!/usr/bin/env python3
"""2.120.0 API tests, part E: the own letterhead PDF behind the office documents (#2091).
Own container (start.sh, org encryption on). Invented companies and figures only; the letterhead PDFs are made here.
tenant-matrix: office
freelancer-matrix: office
 - upload: a two page PDF (classic xref table) and a one page PDF with an xref stream + object stream (PNG predictor);
   rubbish, an encrypted PDF, a landscape page -> 400, more than 10 MB -> 413; the file is sealed at rest
 - documents: page 1 carries letterhead page 1 (BP1), the following pages letterhead page 2 (BP2), a one page letterhead
   goes behind all pages; the letterhead is drawn first (the document on top) and its own text comes along
 - margins: the left margin moves the address field, the top margin of page 1 moves it down, following pages are moved
   by the difference of the left margins; the switches leave out the fold marks / logo head and the footer
 - without a letterhead the PDF is the same as before (bytes equal apart from the dates and the file id)
 - finalising: the ZUGFeRD invoice keeps its factur-x.xml next to the letterhead; the stored file stays when the
   letterhead changes or is removed later
 - preview, undo (restore of the previous file, the removal and its undo)
 - rights: a member reads (state, preview) but cannot write (403); a member without the office 403; an agent 403;
   another organisation never sees or gets the letterhead; a person without organisation (personal office) uses everything
usage: p2120_e_api_test.py <datadir>      (P2120E_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import re
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
O = "/api/office"
LH = O + "/letterhead"
MM = 72 / 25.4
A4 = (595.28, 841.89)


# ---------------------------------------------------------------- letterhead PDFs made here
def _content(mark):
    return (f"BT /F1 16 Tf 40 800 Td ({mark}) Tj ET 0.36 0.25 0.82 rg 0 0 595 28 re f").encode()


def mk_pdf(marks, size=A4, encrypt=False):
    """A plain PDF 1.4: one page per mark (Helvetica, a coloured bar), classic xref table, Flate content."""
    w, h = size
    n = len(marks)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(n)) + f"] /Count {n} >>").encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for i, m in enumerate(marks):
        data = zlib.compress(_content(m))
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        objs.append(f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode() + data + b"\nendstream")
    if encrypt:
        objs.append(b"<< /Filter /Standard /V 1 /R 2 /O <00> /U <00> /P -4 >>")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    enc = f" /Encrypt {len(objs)} 0 R /ID [<00> <00>]" if encrypt else ""
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{enc} >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def mk_bomb(datas):
    """2.120.0 (review H1): one A4 page whose /Contents are the given decoded stream data (Flate), classic xref."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Contents [" + " ".join(f"{4 + i} 0 R" for i in range(len(datas))) + "] >>").encode()]
    for d in datas:
        z = zlib.compress(d, 9)
        objs.append(f"<< /Length {len(z)} /Filter /FlateDecode >>\nstream\n".encode() + z + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def mk_pdf_xrefstm(mark):
    """A PDF 1.5 with one page: catalog, pages, font and page in an object stream, the cross-reference as an xref
    stream (W [1 4 2], FlateDecode with the PNG Up predictor) -- how many office programs write today."""
    content = zlib.compress(_content(mark))
    inner = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"), (2, b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>"),
             (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
             (4, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>".encode())]
    body, head, pos = b"", [], 0
    for num, o in inner:
        head.append(f"{num} {pos}")
        body += o + b"\n"
        pos = len(body)
    hd = (" ".join(head) + "\n").encode()
    stm = zlib.compress(hd + body)
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    off5 = len(out)
    out += f"5 0 obj\n<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream\nendobj\n"
    off6 = len(out)
    out += f"6 0 obj\n<< /Type /ObjStm /N 4 /First {len(hd)} /Length {len(stm)} /Filter /FlateDecode >>\nstream\n".encode() + stm + b"\nendstream\nendobj\n"
    off7 = len(out)
    rows = [(0, 0, 65535)] + [(2, 6, i) for i in range(4)] + [(1, off5, 0), (1, off6, 0), (1, off7, 0)]
    raw = [bytes([t]) + o.to_bytes(4, "big") + g.to_bytes(2, "big") for t, o, g in rows]
    prev, enc = bytes(7), b""
    for r in raw:  # PNG predictor 2 (Up) on every row
        enc += b"\x02" + bytes((a - b) & 0xFF for a, b in zip(r, prev))
        prev = r
    xs = zlib.compress(enc)
    out += (f"7 0 obj\n<< /Type /XRef /Size 8 /W [1 4 2] /Root 1 0 R /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 7 >> "
            f"/Length {len(xs)} >>\nstream\n").encode() + xs + b"\nendstream\nendobj\n"
    out += f"startxref\n{off7}\n%%EOF\n".encode()
    return bytes(out)


def up(s, data, name="Briefpapier.pdf"):
    return s.post(B + LH, files={"file": (name, data, "application/pdf")})


def norm(pdf):
    """The PDF without what changes on every rendering (dates, file id)."""
    pdf = re.sub(rb"D:\d{14}[^)]*", b"D:", pdf)
    pdf = re.sub(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^<\"]*", b"T", pdf)
    return re.sub(rb"/ID \[<[0-9a-f]+> <[0-9a-f]+>\]", b"/ID", pdf)


def reader(data):
    return PdfReader(io.BytesIO(data))


def page_ops(rd, i):
    return rd.pages[i].get_contents().get_data()


def page_forms(rd, i):
    res = rd.pages[i].get("/Resources") or {}
    xo = res.get("/XObject") or {}
    return {k: v.get_object() for k, v in xo.items() if v.get_object().get("/Subtype") == "/Form"}


def x(v):
    return f"{v:.2f}"

def foot_rule(ops):
    """2.120.0 (2.114.5 #2300): the footer rule's height follows the footer lines now (12 mm .. 22 mm above the bottom
    margin): a line starting at the left margin that low."""
    for m in re.finditer(rb"(\d+(?:\.\d+)?) (\d+(?:\.\d+)?) m ", ops):  # any left margin (letterhead margins move it)
        if float(m.group(1)) <= 45 * MM and 24 * MM - 0.5 <= float(m.group(2)) <= 34 * MM + 0.5:
            return True
    return False



if not (os.environ.get("P2120E_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("eve", "Eve Nooffice")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Ev = sess("bob"), sess("carol"), sess("eve")
FEAT = "cal,comments,collab,office,clients,docs,files"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Ev.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,clients,docs", "tour": "done"})  # no office
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for em in ("bob@example.com", "eve@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": em, "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ev, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
for s, name in ((A, "Beispiel Studio GmbH"), (Ca, "Andere Firma GmbH"), (Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text


def invoice(s, n_items=3, finalize=False):
    cl = s.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "service_from": "2026-01-15",
                                      "items": [{"title": f"Schnitt {i}", "qty": 1, "rate": 100} for i in range(n_items)]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if finalize:
        r = s.post(B + f"{O}/docs/{did}/finalize")
        assert r.ok, r.text
    return did


def pdf(s, did):
    r = s.get(B + f"{O}/docs/{did}/pdf")
    assert r.ok and r.content[:5] == b"%PDF-", (r.status_code, r.text[:200])
    return r.content


# ================================================================ no letterhead: as before
st = A.get(B + LH).json()["letterhead"]
check(st["on"] is False and st["m1"] == [45, 20, 32, 25] and st["m2"] == [30, 20, 32, 25] and st["hide_head"] == 1 and st["hide_footer"] == 1,
      f"#2091: no letterhead, the default margins = today's layout {st}")
D1 = invoice(A, 40)
P0 = pdf(A, D1)
r0 = reader(P0)
check(len(r0.pages) >= 2 and not page_forms(r0, 0) and not page_forms(r0, 1), "#2091: without a letterhead no form XObject")
ops0 = page_ops(r0, 0)
check(f"{x(5 * MM)} {x(A4[1] - 105 * MM)} m".encode() in ops0, "#2091: without a letterhead the fold marks stay")
check(f"{x(25 * MM)} ".encode() in ops0 and foot_rule(ops0), "#2091: the normal left margin and footer rule")

# ================================================================ upload: refused files
for data, what in ((b"not a pdf at all", "rubbish"), (b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF", "no pages"),
                   (mk_pdf(["X"], encrypt=True), "encrypted"), (mk_pdf(["X"], size=(841.89, 595.28)), "landscape"),
                   # 2.120.0 (review H1): a zlib bomb (20 MB of spaces from ~20 KB) and too many content streams
                   (mk_bomb([b" " * (20 * 1024 * 1024)]), "zlib bomb"), (mk_bomb([b"q Q %d" % i for i in range(70)]), "70 content streams")):
    r = up(A, data)
    check(r.status_code == 400 and r.json().get("error"), f"#2091: {what} -> 400 {r.status_code} {r.text[:200]}")
r = up(A, b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 10))
check(r.status_code == 413, f"#2091: more than 10 MB -> 413 {r.status_code}")
check(A.get(B + LH).json()["letterhead"]["on"] is False, "#2091: a refused upload leaves no letterhead")

# ================================================================ rights
L2 = mk_pdf(["LH-PAGE-ONE", "LH-PAGE-TWO"])
r = up(Bo, L2)
check(r.status_code == 403, f"#2091: a member cannot upload {r.status_code}")
for meth, url, js in (("PUT", LH, {"hide_head": 0}), ("DELETE", LH, None), ("POST", LH + "/restore", {"file": ""})):
    check(Bo.request(meth, B + url, json=js).status_code == 403, f"#2091: a member {meth} {url} 403")
check(Ev.get(B + LH).status_code == 403 and Ev.get(B + LH + "/preview").status_code == 403, "#2091: member without the office 403")
check(requests.get(B + LH, headers=AGH).status_code in (401, 403), "#2091: an agent 403")

# ================================================================ upload a two page letterhead
r = up(A, L2, "Briefbogen 2026.pdf")
check(r.ok and r.json()["letterhead"]["on"] and r.json()["letterhead"]["pages"] == 2 and r.json()["letterhead"]["name"] == "Briefbogen 2026.pdf",
      "#2091: two page letterhead uploaded " + r.text[:300])
F1 = r.json()["letterhead"]["file"]
check(re.fullmatch(r"letterhead-[0-9a-f]{16}\.pdf", F1 or ""), f"#2091: content-addressed file name {F1}")
try:
    p = os.path.join(DATA, "office", str(ORG), F1)
    if os.path.exists(p):
        with open(p, "rb") as fh:
            check(not fh.read(5).startswith(b"%PDF"), "#2091: the letterhead is sealed at rest")
except PermissionError:
    pass
check(Bo.get(B + LH).json()["letterhead"]["on"] is True, "#2091: a member reads the state")
check(Ca.get(B + LH).json()["letterhead"]["on"] is False, "#2091: the other organisation has no letterhead")

P1 = pdf(A, D1)
r1 = reader(P1)
f0, f1 = page_forms(r1, 0), page_forms(r1, 1)
check(list(f0) == ["/BP1"] and list(f1) == ["/BP2"], f"#2091: page 1 -> letterhead page 1, page 2 -> page 2 {list(f0)} {list(f1)}")
check(b"(LH-PAGE-ONE)" in f0["/BP1"].get_data() and b"(LH-PAGE-TWO)" in f1["/BP2"].get_data(), "#2091: the letterhead's own content comes along")
check("/F1" in (f0["/BP1"].get("/Resources") or {}).get("/Font", {}), "#2091: the letterhead's fonts come along")
ops1, ops1b = page_ops(r1, 0), page_ops(r1, 1)
check(ops1.startswith(b"q /BP1 Do Q") and ops1b.startswith(b"q /BP2 Do Q"), "#2091: the letterhead is drawn first (the document on top)")
check(f"{x(5 * MM)} {x(A4[1] - 105 * MM)} m".encode() not in ops1, "#2091: hide_head: no fold marks of our own")
check(not foot_rule(ops1), "#2091: hide_footer: no footer of our own")
txt = r1.pages[0].extract_text() or ""
check("Kunde Eins GmbH" in txt, "#2091: the document's text is still there")
check(Ca.get(B + f"{O}/docs/{D1}/pdf").status_code == 404, "#2091: the other organisation does not get the document")
D2 = invoice(Ca, 2)
rc = reader(pdf(Ca, D2))
check(not page_forms(rc, 0), "#2091: the other organisation's documents have no letterhead")

# ================================================================ margins and switches
r = A.put(B + LH, json={"m1": [60, 20, 40, 35], "m2": [40, 20, 40, 30], "hide_head": 0, "hide_footer": 0})
check(r.ok and r.json()["letterhead"]["m1"] == [60, 20, 40, 35] and r.json()["letterhead"]["hide_head"] == 0, "#2091: margins saved " + r.text[:200])
r2 = reader(pdf(A, D1))
ops2, ops2b = page_ops(r2, 0), page_ops(r2, 1)
sender_y = A4[1] - 60 * MM - 7 * 0.78
check(f"{x(35 * MM)} {x(sender_y)} Td".encode() in ops2, "#2091: page 1: left 35 mm, the address field 60 mm from the top")
check(f"q 1 0 0 1 {x(-5 * MM)} 0 cm".encode() in ops2b, "#2091: following pages moved by the left margin difference")
check(f"{x(5 * MM)} {x(A4[1] - 105 * MM)} m".encode() in ops2, "#2091: hide_head off: the fold marks again")
check(foot_rule(ops2), "#2091: hide_footer off: our footer again")
for bad in ({"m1": [60, 80, 40, 80]}, {"m1": [1, 2, 3]}, {"m2": [10, 10, -1, 10]}, {"m2": ["x", 1, 1, 1]}, {"m1": [200, 20, 20, 20]}):
    check(A.put(B + LH, json=bad).status_code == 400, f"#2091: invalid margins 400 {bad}")
check(A.get(B + LH).json()["letterhead"]["m1"] == [60, 20, 40, 35], "#2091: an invalid value changes nothing")
check(A.put(B + LH, json={"m1": [45, 20, 32, 25], "m2": [30, 20, 32, 25], "hide_head": 1, "hide_footer": 1}).ok, "#2091: margins back")

# ================================================================ preview
r = A.get(B + LH + "/preview")
check(r.ok and r.content[:5] == b"%PDF-" and r.headers.get("Content-Disposition", "").startswith("inline"), "#2091: preview PDF")
rp = reader(r.content)
check(len(rp.pages) >= 2 and list(page_forms(rp, 0)) == ["/BP1"] and list(page_forms(rp, 1)) == ["/BP2"], "#2091: the preview shows both letterhead pages")
check(Bo.get(B + LH + "/preview").ok, "#2091: a member sees the preview")

# ================================================================ finalising: ZUGFeRD stays valid, the stored file stays
D3 = invoice(A, 2, finalize=True)
P3 = pdf(A, D3)
r3 = reader(P3)
check(list(page_forms(r3, 0)) == ["/BP1"], "#2091: the finalised invoice has the letterhead")
att = r3.attachments
check("factur-x.xml" in att and b"CrossIndustryInvoice" in att["factur-x.xml"][0], f"#2091: factur-x.xml still embedded {list(att)}")
check(b"pdfaid:part" in P3 and b"fx:DocumentFileName" in P3, "#2091: the PDF/A + Factur-X metadata stay")

# ================================================================ undo: replace, restore, remove, restore
L1b = mk_pdf_xrefstm("LH-XREFSTREAM")
r = up(A, L1b, "neu.pdf")
check(r.ok and r.json()["letterhead"]["pages"] == 1 and r.json()["letterhead"]["prev"] == F1, "#2091: xref stream + object stream accepted " + r.text[:200])
F2 = r.json()["letterhead"]["file"]
r4 = reader(pdf(A, D1))
check(list(page_forms(r4, 0)) == ["/BP1"] and list(page_forms(r4, 1)) == ["/BP1"], "#2091: a one page letterhead goes behind all pages")
check(b"(LH-XREFSTREAM)" in page_forms(r4, 1)["/BP1"].get_data(), "#2091: the content from the object stream PDF")
check(pdf(A, D3) == P3, "#2091: the stored finalised PDF stays as it was")
r = A.post(B + LH + "/restore", json={"file": F1})
check(r.ok and r.json()["letterhead"]["file"] == F1 and r.json()["letterhead"]["pages"] == 2 and r.json()["letterhead"]["prev"] == F2,
      "#2091: undo of the replacement " + r.text[:200])
check(A.post(B + LH + "/restore", json={"file": "letterhead-0000000000000000.pdf"}).status_code == 404, "#2091: restore of an unknown file 404")
check(A.post(B + LH + "/restore", json={"file": "../logo.png"}).status_code == 404, "#2091: restore of a foreign path 404")
check(Ca.post(B + LH + "/restore", json={"file": F2}).status_code == 404, "#2091: the other organisation cannot restore our file")
r = A.delete(B + LH)
check(r.ok and r.json()["letterhead"]["on"] is False and r.json()["letterhead"]["prev"] == F1, "#2091: removed")
P5 = pdf(A, D1)
check(not page_forms(reader(P5), 0), "#2091: after the removal no letterhead")
check(norm(P5) == norm(P0), "#2091: without a letterhead the PDF is the same as before the upload (bytes, apart from dates / id)")
check(pdf(A, D3) == P3, "#2091: the stored finalised PDF stays after the removal")
r = A.post(B + LH + "/restore", json={"file": F1})
check(r.ok and r.json()["letterhead"]["on"] and r.json()["letterhead"]["file"] == F1, "#2091: undo of the removal")
check(A.post(B + LH + "/restore", json={"file": ""}).json()["letterhead"]["on"] is False, "#2091: undo of an upload onto none")
check(A.delete(B + LH).ok, "#2091: remove (nothing there) stays fine")

# ================================================================ a person without organisation (freelancer-matrix: office)
r = up(Fr, mk_pdf(["FRIDA-ONE", "FRIDA-TWO"]))  # own bytes: the file name is content-addressed (per office folder)
check(r.ok and r.json()["letterhead"]["pages"] == 2, "freelancer: upload " + r.text[:200])
FF = r.json()["letterhead"]["file"]
check(Fr.put(B + LH, json={"m1": [50, 20, 32, 25]}).ok and Fr.get(B + LH).json()["letterhead"]["m1"] == [50, 20, 32, 25], "freelancer: margins")
FD = invoice(Fr, 2)
check(list(page_forms(reader(pdf(Fr, FD)), 0)) == ["/BP1"], "freelancer: the document has the letterhead")
check(Fr.get(B + LH + "/preview").ok, "freelancer: preview")
check(Fr.delete(B + LH).ok and Fr.post(B + LH + "/restore", json={"file": FF}).json()["letterhead"]["on"], "freelancer: remove + undo")
check(A.get(B + LH).json()["letterhead"]["on"] is False, "freelancer: the organisation does not get the personal letterhead")
check(A.post(B + LH + "/restore", json={"file": FF}).status_code == 404, "freelancer: the organisation's admin cannot take it")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
