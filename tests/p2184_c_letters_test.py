#!/usr/bin/env python3
"""2.184.0 API tests, part C (#2581 #2582): the own letterhead under letters, the PDF filed for a refused mail removed.
Own container (start.sh, org encryption on; the mail server is a closed port so every mail is refused). Invented data only;
the letterhead PDF is made here.
tenant-matrix: office
freelancer-matrix: office
 - without a letterhead the letter PDF has no letterhead form (own head, fold marks as before)
 - with a letterhead: page 1 carries BP1, the following pages BP2 (a long letter), the letterhead is drawn first; the PDF stays PDF/A
   (XMP part 3 / conformance B); the margins move the address field; "hide head" leaves out the fold marks
 - a refused mail (409/5xx): the letter stays a draft and no new file stays in the files folder
 - a person without organisation (personal office): the letter PDF has the personal letterhead
usage: p2184_c_letters_test.py <datadir>      (P2184C_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
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

from pypdf import PdfReader  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
O = "/api/office"
LH = O + "/letterhead"
L = O + "/letters"
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


def forms(rd, i):
    xo = (rd.pages[i].get("/Resources") or {}).get("/XObject") or {}
    return sorted(k for k, v in xo.items() if v.get_object().get("/Subtype") == "/Form")


def files_count():
    n = 0
    for root, _d, fs in os.walk(os.path.join(DATA, "attachments", "files")):
        n += len(fs)
    return n


def letter(s, subject, paragraphs=1):
    r = s.post(B + L, json={"rcpt_name": "Amt fuer Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt",
                            "rcpt_email": "amt@example.com", "subject": subject,
                            "body": "\n\n".join(("Sehr geehrte Damen und Herren, dies ist ein Absatz mit etwas Text. " * 6) for _ in range(paragraphs))})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def lpdf(s, lid):
    r = s.get(B + f"{L}/{lid}/pdf")
    assert r.ok, r.text
    return r.content




if not os.environ.get("P2184C_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789"}
for s, name in ((A, "Beispiel Studio GmbH"), (Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text

# ---------------------------------------------------------------- without a letterhead: as before
L1 = letter(A, "Antrag 7/2026")
p0 = lpdf(A, L1)
check(p0.startswith(b"%PDF") and forms(PdfReader(io.BytesIO(p0)), 0) == [], "no letterhead: no letterhead form on the letter")
check(b"pdfaid:conformance>B<" in p0 or b"conformance=\"B\"" in p0 or b"<pdfaid:conformance>B" in p0, "no letterhead: PDF/A-3b marker")

# ---------------------------------------------------------------- with a letterhead
r = A.post(B + LH, files={"file": ("Briefpapier.pdf", mk_pdf(["LH-ONE", "LH-TWO"]), "application/pdf")})
assert r.ok, r.text
p1 = lpdf(A, L1)
rd = PdfReader(io.BytesIO(p1))
check(forms(rd, 0) == ["/BP1"], f"letterhead: page 1 has BP1 ({forms(rd, 0)})")
check(b"conformance>B<" in p1 or b"conformance=\"B\"" in p1, "letterhead: still PDF/A-3b")
c0 = rd.pages[0].get_contents().get_data()
check(c0.lstrip().startswith(b"q /BP1 Do Q"), "letterhead: drawn first, the letter on top")
LONG = letter(A, "Langer Brief", paragraphs=14)
rl = PdfReader(io.BytesIO(lpdf(A, LONG)))
check(len(rl.pages) >= 2 and forms(rl, 0) == ["/BP1"] and forms(rl, 1) == ["/BP2"], f"letterhead: later pages carry BP2 ({len(rl.pages)} pages)")
# the address field follows the top margin of the letterhead
def first_y(data):
    m = re.search(rb"([\d.]+) ([\d.]+) Td", data)
    return float(m.group(2)) if m else None
check(A.put(B + LH, json={"m1": [70, 20, 32, 25], "hide_head": 0}).ok, "letterhead: margins set, own head on")
c1 = PdfReader(io.BytesIO(lpdf(A, L1))).pages[0].get_contents().get_data()
check(c1 != c0, "letterhead: the top margin moves the letter content")
check(A.put(B + LH, json={"m1": [70, 20, 32, 25], "hide_head": 1}).ok, "letterhead: hide head")
c2 = PdfReader(io.BytesIO(lpdf(A, L1))).pages[0].get_contents().get_data()
check(c1.count(b"0.40 w") >= 3 and c2.count(b"0.40 w") == 0, "letterhead: hide head leaves out the own head and the fold marks")

# ---------------------------------------------------------------- a refused mail leaves no file
L3 = letter(A, "Abgelehnte Mail")
n0 = files_count()
r = A.post(B + f"{L}/{L3}/send-mail", json={})
check(r.status_code >= 400, f"refused mail answers an error ({r.status_code} {r.text[:120]})")
check(A.get(B + f"{L}/{L3}").json()["status"] == "draft", "refused mail: the letter stays a draft")
check(files_count() == n0, f"refused mail: no file left behind ({n0} -> {files_count()})")
# a letter marked sent keeps its filed file
n1 = files_count()
r = A.post(B + f"{L}/{L3}/sent", json={})
check(r.ok and files_count() == n1 + 1, "marked sent: the PDF is filed (one file)")

# ---------------------------------------------------------------- a person without organisation (freelancer-matrix: office)
FL = letter(Fr, "Brief Frida")
check(forms(PdfReader(io.BytesIO(lpdf(Fr, FL))), 0) == [], "freelancer: no letterhead before")
r = Fr.post(B + LH, files={"file": ("Briefpapier.pdf", mk_pdf(["FRIDA-ONE", "FRIDA-TWO"]), "application/pdf")})
check(r.ok, "freelancer: upload " + r.text[:120])
check(forms(PdfReader(io.BytesIO(lpdf(Fr, FL))), 0) == ["/BP1"], "freelancer: the letter PDF has the personal letterhead")
check(forms(PdfReader(io.BytesIO(lpdf(A, L1))), 0) == ["/BP1"], "the organisation keeps its own letterhead")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
