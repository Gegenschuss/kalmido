#!/usr/bin/env python3
"""2.296.0 C (#3177): own letterhead checked for PDF/A at the upload, stored office files checked against their SHA-256,
own container (start.sh, mode workspaces). Invented companies only; every letterhead PDF is written here by hand.
freelancer-matrix: office
 - the upload refuses what makes the documents invalid PDF/A-3b (checked with veraPDF when it was built): a named font
   without its program (Type 1 Helvetica, TrueType with a descriptor but no FontFile2), DeviceCMYK (colour operator k,
   a CMYK picture), LZW compression -- 400 with a sentence naming what is wrong and "PDF/A"
 - accepted: plain RGB graphics, an embedded TrueType font (Liberation Sans of the source tree), a picture with a soft
   mask, constant opacity with a transparency group, optional content (all valid PDF/A-3b)
 - a letterhead stored before the check (written into the office folder + the setting, without the stored result):
   GET /api/office/letterhead names the problem (pdfa_hint), the letterhead stays and still prints
 - a finalised invoice: PDF / XML served while they match pdf_sha256 / xml_sha256; a changed stored PDF or a hash that
   no longer matches the XML answers 409 (no file) and logs store_mismatch; a row without a hash (older) is served as before
 - the same for a person without organisation (personal office, tests/freelancer_fixture.py)
usage: p2296_c_letterhead_test.py <datadir>      (KALMIDO_SRC = the source tree for the font, default ../ next to tests/)"""
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
import zlib

import dbx as dbxm
import requests

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import CT, FAILS, OKS, check, sess, su_get  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
FEAT = "cal,comments,collab,office,clients"
O = "/api/office"
LH = O + "/letterhead"
D = O + "/docs"
W_, H_ = 595.28, 841.89


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def sh(cmd, data=None):
    return subprocess.run(["docker", "exec", "-i", CT, "sh", "-c", cmd], input=data, capture_output=True, timeout=60)


# ---------------------------------------------------------------- hand-written letterheads (one A4 page)
def build(objs, content, res, extra_page=b""):
    """objs {number: body} from 4 on; 1 catalog, 2 pages, 3 the page, the content stream last; classic xref."""
    cnum = max(objs) + 1 if objs else 4
    allo = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s /Contents %d 0 R %s>>" % (W_, H_, res, cnum, extra_page)}
    allo.update(objs)
    z = zlib.compress(content)
    allo[cnum] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream"
    out, offs = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"), {}
    for n in sorted(allo):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + allo[n] + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (cnum + 1) + b"".join(b"%010d 00000 n \n" % offs[n] for n in range(1, cnum + 1))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (cnum + 1, x)
    return bytes(out)


def img(cs=b"/DeviceRGB", lzw=False, extra=b""):
    n = 4 if b"CMYK" in cs else 3
    data = b"\x80\x0b\x60\x50\x22\x0c\x0c\x85\x01" if lzw else zlib.compress(b"\x10\x60\xa0\x00"[:n] * 4)
    return (b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace %s /BitsPerComponent 8 /Filter /%s %s /Length %d >>\nstream\n"
            % (cs, b"LZWDecode" if lzw else b"FlateDecode", extra, len(data)) + data + b"\nendstream")


BAND = b"0.06 0.23 0.37 rg 0 800 595.28 41.89 re f\n"
TXT = b"BT /F1 18 Tf 1 1 1 rg 40 815 Td (STUDIO NORDLICHT) Tj ET\n"
PIC = b"q 50 0 0 50 40 760 cm /Im1 Do Q\n"
TTF = open(os.path.join(SRC, "kalmido", "office", "fonts", "LiberationSans-Regular.ttf"), "rb").read()
TTZ = zlib.compress(TTF)
SM = zlib.compress(b"\xff\x80\x40\x00")
BAD = {  # code -> (letterhead, the words the refusal names)
    "helvetica": (build({4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"}, BAND + TXT,
                        b"<< /Font << /F1 4 0 R >> >>"), "font"),
    "no_fontfile": (build({4: b"<< /Type /Font /Subtype /TrueType /BaseFont /Arial /FirstChar 32 /LastChar 32 /Widths [278] /FontDescriptor 5 0 R >>",
                           5: b"<< /Type /FontDescriptor /FontName /Arial /Flags 32 /FontBBox [-665 -325 2000 1006] /ItalicAngle 0 /Ascent 905 "
                              b"/Descent -212 /CapHeight 716 /StemV 80 >>"}, BAND + TXT, b"<< /Font << /F1 4 0 R >> >>"), "font"),
    "cmyk_op": (build({}, b"0.9 0.5 0 0.2 k 0 800 595.28 41.89 re f\n", b"<< >>"), "CMYK"),
    "cmyk_img": (build({4: img(b"/DeviceCMYK")}, BAND + PIC, b"<< /XObject << /Im1 4 0 R >> >>"), "CMYK"),
    "lzw": (build({4: img(lzw=True)}, BAND + PIC, b"<< /XObject << /Im1 4 0 R >> >>"), "LZW"),
    # 2.296.0 F (#3177): DeviceCMYK set by name in the content ("/DeviceCMYK cs ... sc", no k operator) -- was let through
    "cmyk_cs": (build({}, b"/DeviceCMYK cs 0.9 0.5 0 0.2 sc 0 800 595.28 41.89 re f\n", b"<< >>"), "CMYK"),
}
GOOD = {
    "rgb": build({}, BAND, b"<< >>"),
    "embedded_font": build({4: b"<< /Type /Font /Subtype /TrueType /BaseFont /LiberationSans /FirstChar 32 /LastChar 32 /Widths [278] "
                               b"/FontDescriptor 5 0 R /Encoding /WinAnsiEncoding >>",
                            5: b"<< /Type /FontDescriptor /FontName /LiberationSans /Flags 32 /FontBBox [-543 -303 1301 979] /ItalicAngle 0 "
                               b"/Ascent 905 /Descent -212 /CapHeight 729 /StemV 80 /FontFile2 6 0 R >>",
                            6: b"<< /Length %d /Length1 %d /Filter /FlateDecode >>\nstream\n" % (len(TTZ), len(TTF)) + TTZ + b"\nendstream"},
                           BAND + TXT, b"<< /Font << /F1 4 0 R >> >>"),
    "soft_mask": build({4: img(extra=b"/SMask 5 0 R"),
                        5: b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
                           b"/Length %d >>\nstream\n" % len(SM) + SM + b"\nendstream"}, BAND + PIC, b"<< /XObject << /Im1 4 0 R >> >>"),
    "opacity_group": build({4: b"<< /Type /ExtGState /ca 0.5 /CA 0.5 >>"}, b"/GS1 gs " + BAND, b"<< /ExtGState << /GS1 4 0 R >> >>",
                           b"/Group << /S /Transparency /CS /DeviceRGB >> "),
    # 2.296.0 F (#3177): an ICCBased CMYK picture (the profile's Alternate /DeviceCMYK is no device colour used) and a Type 3
    # font (its FontDescriptor has no font program by design) are valid PDF/A-3b -- were refused as CMYK / font
    "icc_cmyk": build({4: img(b"[/ICCBased 5 0 R]"), 5: b"<< /N 4 /Alternate /DeviceCMYK /Length 8 >>\nstream\nICCDUMMY\nendstream"},
                      BAND + PIC, b"<< /XObject << /Im1 4 0 R >> >>"),
    "type3_font": build({4: b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] /FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /a 6 0 R >> "
                            b"/Encoding << /Type /Encoding /Differences [97 /a] >> /FirstChar 97 /LastChar 97 /Widths [1000] /FontDescriptor 5 0 R "
                            b"/Resources << >> >>",
                         5: b"<< /Type /FontDescriptor /FontName /Glyphs /Flags 4 /ItalicAngle 0 /FontBBox [0 0 1000 1000] >>",
                         6: b"<< /Length 42 >>\nstream\n1000 0 0 0 1000 1000 d1 0 0 1000 1000 re f\nendstream"},
                        BAND + b"BT /F1 18 Tf 40 815 Td (a) Tj ET\n", b"<< /Font << /F1 4 0 R >> >>"),
    "optional_content": build({4: b"<< /Type /OCG /Name (Druck) >>"}, b"/OC /OC1 BDC " + BAND + b"EMC\n", b"<< /Properties << /OC1 4 0 R >> >>"),
}


def up(S, data, name="Briefpapier.pdf"):
    return S.post(B + LH, files={"file": (name, data, "application/pdf")})


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                   env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"))
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def run(S, who, rx):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                         "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                            "country": "DE", "email": "post@example.com", "tax_number": "12/345/67890",
                                                            "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: office settings {r.status_code} {r.text[:200]}")
    # ---- the upload check
    for code, (data, word) in BAD.items():
        r = up(S, data)
        e = r.json().get("error", "") if r.headers.get("Content-Type", "").startswith("application/json") else ""
        check(r.status_code == 400 and "PDF/A" in e and word in e, f"{who}: {code} refused with a reason ({r.status_code} {e[:160]})")
    check(not S.get(B + LH).json()["letterhead"]["on"], f"{who}: nothing refused was stored")
    for code, data in GOOD.items():
        r = up(S, data)
        lh = r.json().get("letterhead") or {} if r.ok else {}
        check(r.ok and lh.get("on") and lh.get("pdfa_hint") == "" and lh.get("pdfa_issues") == [], f"{who}: {code} accepted ({r.status_code} {r.text[:160]})")
    # ---- a letterhead stored before the check: named in the settings, kept, still printed
    ok_sha = hashlib.sha256(GOOD["optional_content"]).hexdigest()
    p = sh(f"ls /data/office/*/letterhead-{ok_sha[:16]}.pdf").stdout.decode().strip()
    old = BAD["cmyk_op"][0]
    osha = hashlib.sha256(old).hexdigest()
    dst = os.path.dirname(p) + f"/letterhead-{osha[:16]}.pdf"
    w = sh(f"cat > {dst}", old)
    rows = [x for x in dbx("SELECT org_id, data FROM office_settings") if f"letterhead-{ok_sha[:16]}" in str(x[1])]
    check(p and w.returncode == 0 and len(rows) == 1, f"{who}: the old letterhead written into the office folder ({p} {w.stderr[:120]})")
    if rows:
        s = json.loads(rows[0][1])
        s["letterhead"].update(file=f"letterhead-{osha[:16]}.pdf", sha256=osha, bytes=len(old), pages=1)
        s["letterhead"].pop("pdfa", None)  # as stored before 2.296.0
        dbx("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(s), rows[0][0]), write=True)
    lh = S.get(B + LH).json()["letterhead"]
    check(lh["on"] and lh["pdfa_issues"] == ["cmyk"] and "PDF/A" in lh["pdfa_hint"] and "CMYK" in lh["pdfa_hint"],
          f"{who}: an old letterhead with CMYK is named in the settings {lh.get('pdfa_issues')} {lh.get('pdfa_hint', '')[:120]}")
    if rows:  # 2.296.0 F (#3177): a letterhead file that cannot be decrypted -> GET still answers (no hint), never 500
        bsha = "ab" * 32
        sh(f"cat > {os.path.dirname(p)}/letterhead-{bsha[:16]}.pdf", b"KENC1\n\x00\x00")
        s2 = dict(s, letterhead=dict(s["letterhead"], file=f"letterhead-{bsha[:16]}.pdf", sha256=bsha))
        dbx("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(s2), rows[0][0]), write=True)
        r = S.get(B + LH)
        check(r.ok and r.json()["letterhead"]["pdfa_issues"] == [], f"{who}: F an unreadable letterhead file: GET answers ({r.status_code})")
        dbx("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(s), rows[0][0]), write=True)
    pv = S.get(B + LH + "/preview")
    xo = PdfReader(io.BytesIO(pv.content)).pages[0]["/Resources"].get("/XObject") or {} if pv.ok else {}
    check(pv.ok and "/BP1" in xo, f"{who}: ... it stays and still prints ({pv.status_code} {list(xo)})")
    check(S.delete(B + LH).ok, f"{who}: letterhead off")
    # ---- stored files against their hashes
    cl = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
    r = S.post(B + D, json={"kind": "invoice", "client_id": cl, "project_title": "Imagefilm", "payment_days": 14, "einvoice_format": "zugferd",
                               "service_from": "2026-04-01", "service_to": "2026-05-31", "date": "2026-05-08"})
    did = r.json()["id"]
    S.put(B + f"{D}/{did}/items", json={"items": [{"title": "Schnitt", "qty": 2, "rate": 500}]})
    r = S.post(B + f"{D}/{did}/finalize")
    j = r.json() if r.ok else {}
    check(r.ok and len(j.get("pdf_sha256") or "") == 64 and len(j.get("xml_sha256") or "") == 64, f"{who}: finalised with hashes {r.status_code} {r.text[:200]}")
    pdf, xml = S.get(B + f"{D}/{did}/pdf"), S.get(B + f"{D}/{did}/xml")
    check(pdf.ok and hashlib.sha256(pdf.content).hexdigest() == j.get("pdf_sha256") and xml.ok, f"{who}: the stored files served while they match")
    p = sh(f"ls /data/office/*/doc{did}-*.pdf | grep -v accepted").stdout.decode().strip()
    w = sh(f"cat > {p}", b"%PDF-1.7\n% changed underneath\n%%EOF\n")
    check(p and w.returncode == 0, f"{who}: the stored PDF changed underneath ({p})")
    r = S.get(B + f"{D}/{did}/pdf")
    e = r.json().get("error", "") if r.status_code == 409 else ""
    check(r.status_code == 409 and "checksum" in e and not r.content.startswith(b"%PDF"), f"{who}: a changed stored PDF: 409, no file ({r.status_code} {e[:120]})")
    n = dbx("SELECT COUNT(*) FROM office_doc_log WHERE doc_id=? AND action='store_mismatch'", (did,))[0][0]
    check(n >= 1, f"{who}: ... logged as store_mismatch ({n})")
    # 2.296.0 F (#3177): the retention export hands the stored bytes out, names the mismatch in its index and logs it
    z = su_get(S, B + rx)  # 2.223.2 C (#2871): the retention ZIP needs the step-up (bundle 2.305)
    zf = zipfile.ZipFile(io.BytesIO(z.content)) if z.ok and z.content[:2] == b"PK" else None
    idx = zf.read("00-index.txt").decode() if zf and "00-index.txt" in zf.namelist() else ""
    inv = [x for x in (zf.namelist() if zf else []) if x.startswith("invoices/") and x.endswith(".pdf")]
    check("(checksum mismatch)" in idx and inv and any(b"changed underneath" in zf.read(x) for x in inv),
          f"{who}: F retention export: the file exported, the mismatch named ({z.status_code} {inv})")
    n2 = dbx("SELECT COUNT(*) FROM office_doc_log WHERE doc_id=? AND action='store_mismatch'", (did,))[0][0]
    check(n2 > n, f"{who}: F ... and logged as store_mismatch ({n} -> {n2})")
    dbx("UPDATE office_docs SET xml_sha256=? WHERE id=?", ("0" * 64, did), write=True)
    check(S.get(B + f"{D}/{did}/xml").status_code == 409, f"{who}: an XML that does not match its hash: 409")
    dbx("UPDATE office_docs SET pdf_sha256='' WHERE id=?", (did,), write=True)
    r = S.get(B + f"{D}/{did}/pdf")
    check(r.ok and b"changed underneath" in r.content, f"{who}: a row without a hash (stored before) is served as before ({r.status_code})")
    # 2.296.0 F (#3177): a quotation taken back to a draft renders anew, no stored file nor checksum left (quotations get no
    # stored files at finalising today; the unlock clears them anyway, epdf_stored reads none for a draft)
    r = S.post(B + D, json={"kind": "offer", "client_id": cl, "project_title": "Imagefilm", "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    of = r.json()["id"]
    r = S.post(B + f"{D}/{of}/finalize")
    check(r.ok and r.json().get("locked"), f"{who}: F quotation finalised ({r.status_code} {r.text[:160]})")
    r = S.post(B + f"{D}/{of}/unlock")
    check(r.ok and not r.json().get("pdf_sha256") and not r.json().get("locked"), f"{who}: F quotation taken back, no checksum ({r.status_code} {r.text[:160]})")
    r = S.get(B + f"{D}/{of}/pdf")
    check(r.ok and r.content[:5] == b"%PDF-", f"{who}: F ... its PDF rendered as a draft ({r.status_code})")
    check(sh(f"ls /data/office/*/doc{of}-*.pdf").stdout.strip() == b"", f"{who}: F ... no stored PDF")


run(A, "org admin", f"/api/retention/org/{ORG}/export.zip")
FID, Fr = freelancer(B, A)
run(Fr, "freelancer", "/api/retention/me/export.zip")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
