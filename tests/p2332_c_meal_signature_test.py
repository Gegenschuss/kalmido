#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.332.0 C (#3301): the signature picture of the person who approved an entertainment receipt stands on its signature line.
One picture per person (the letters profile, PUT /api/office/letters/profile), used for letters and receipts. Own container
(start.sh). Invented data only; the pictures are drawn here (a few strokes on a transparent PNG), never a real signature.
freelancer-matrix: office
 - GET /api/office/meals says my_sig (1 = the signed-in person has a picture in this area)
 - approved by a person with a picture, no choice sent: sign_image = 1, the PDF holds an image object on the confirmation page,
   "Confirmed digitally by ..." stays; someone else downloading the PDF gets the approver's picture too
 - approve with sign_image 0: no picture; a draft: no picture
 - only approved_by's picture: Alice has one, Bob (without one) approves Alice's receipt -> no picture, sign_image 0
 - undo the approval: the picture leaves the PDF (sign_image 0), the log keeps both entries
 - the approver removes the picture later: the PDF goes back to the text
 - a transparent, drawn PNG (RGBA) is accepted by the profile route (the drawing field saves through it)
 - a person without organisation (personal office): own picture on the own receipt
usage: p2332_c_meal_signature_test.py <datadir>"""
import base64
import io
import os
import struct
import sys
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, sess, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2332C")
O = "/api/office"
M = O + "/meals"
FEAT = "cal,comments,collab,office,clients,docs,files"


def png_strokes(w=220, h=70):
    """A transparent RGBA PNG with a dark zigzag stroke (like the drawing field's output)."""
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            on = abs(y - (h // 2 + int((h // 3) * (((x // 20) % 2) * 2 - 1) * ((x % 20) / 20)))) < 3
            row += bytes((27, 36, 48, 255)) if on else bytes((0, 0, 0, 0))
        rows.append(b"\x00" + bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


PIC = "data:image/png;base64," + base64.b64encode(png_strokes()).decode()

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Second", "password": "password123", "email": "bob@example.com"})
check(r.ok, f"bob created {r.text[:200]}")
BOB = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"}).ok, "bob is an admin of the organisation")
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office

r = A.put(B + O + "/letters/profile", json={"image": PIC})
check(r.ok and r.json().get("has_image"), f"a drawn transparent PNG is accepted as signature picture {r.status_code} {r.text[:200]}")
check(A.get(B + M).json().get("my_sig") == 1, "my_sig = 1 for Alice (picture set)")
check(Bo.get(B + M).json().get("my_sig") == 0, "my_sig = 0 for Bob (no picture)")


def meal(s, host):
    b = {"date": "2026-10-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}], "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "0"}
    r = s.post(B + M, json={})
    check(r.status_code == 201, f"meal created {r.status_code} {r.text[:200]}")
    mid = r.json().get("id")
    r = s.patch(B + f"{M}/{mid}", json=b)
    check(r.ok, f"meal saved {r.text[:200]}")
    return mid


def approve(s, mid, **kw):
    r = s.post(B + f"{M}/{mid}/approve", json=kw)
    check(r.ok and r.json().get("status") == "approved", f"meal {mid} approved {r.status_code} {r.text[:200]}")
    return r.json()


def pdf(s, mid):
    r = s.get(B + f"{M}/{mid}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"meal PDF {r.status_code}")
    return r.content


def images(d):
    """The number of image XObjects over all pages of PDF d."""
    n = 0
    for p in PdfReader(io.BytesIO(d)).pages:
        xo = (p.get("/Resources") or {}).get("/XObject") or {}
        n += sum(1 for k in xo if xo[k].get_object().get("/Subtype") == "/Image")
    return n


def text(d):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(d)).pages)


# a draft: no picture
m1 = meal(A, ALICE)
check(images(pdf(A, m1)) == 0, "a draft: no signature picture")
# approved by Alice (picture, the default): the picture, the confirmation text stays; Bob downloading sees the same
j = approve(A, m1)
check(j.get("sign_image") == 1, f"default on when the approver has a picture: sign_image {j.get('sign_image')}")
d = pdf(A, m1)
check(images(d) == 1, f"approved with the picture: one image in the PDF ({images(d)})")
check("Confirmed digitally by Alice Admin" in text(d) and "Place, date, signature" in text(d), "the digital confirmation and the line stay")
check(images(pdf(Bo, m1)) == 1, "another admin downloading the PDF: still the approver's picture")
# the switch off
m2 = meal(A, ALICE)
j = approve(A, m2, sign_image=0)
check(j.get("sign_image") == 0 and images(pdf(A, m2)) == 0, f"approved with the switch off: no picture ({j.get('sign_image')})")
# only approved_by: Bob (no picture) approves Alice's receipt -> never Alice's picture
m3 = meal(A, ALICE)
j = approve(Bo, m3, sign_image=1)
check(j.get("approved_by") == BOB and j.get("sign_image") == 0, f"Bob approves without a picture: sign_image 0 ({j.get('approved_by')}, {j.get('sign_image')})")
check(images(pdf(A, m3)) == 0 and images(pdf(Bo, m3)) == 0, "Bob approved: no picture of Alice on the receipt")
# undo: the picture leaves the PDF, the log stays
r = A.post(B + f"{M}/{m1}/unlock", json={"reason": "Typo in the occasion"})
check(r.ok and r.json().get("status") == "draft" and r.json().get("sign_image") == 0, f"approval undone {r.status_code} {r.text[:200]}")
d = pdf(A, m1)
check(images(d) == 0, "undone: the picture is gone from the PDF")
lg = [e["action"] for e in r.json().get("log") or []]
check(lg == ["approve", "unlock"] and "Approval undone" in text(d), f"undone: the log keeps approve + unlock {lg}")
# approved again, then the picture removed from the profile: back to the text
approve(A, m1)
check(images(pdf(A, m1)) == 1, "approved again: the picture is back")
check(A.delete(B + O + "/letters/profile/image").ok, "picture removed")
check(images(pdf(A, m1)) == 0, "the approver's picture removed: the receipt shows the text only")

# a person without organisation
r = Fr.put(B + O + "/letters/profile", json={"image": PIC})
check(r.ok and r.json().get("has_image"), f"freelancer: picture saved {r.status_code} {r.text[:200]}")
FR = Fr.get(B + "/api/state").json()["me"]["id"]
check(Fr.get(B + M).json().get("my_sig") == 1, "freelancer: my_sig = 1")
mf = meal(Fr, FR)
j = approve(Fr, mf)
check(j.get("sign_image") == 1 and images(pdf(Fr, mf)) == 1, "freelancer: the own picture on the own receipt")
mf2 = meal(Fr, FR)
approve(Fr, mf2, sign_image=False)
check(images(pdf(Fr, mf2)) == 0, "freelancer: switch off -> no picture")

sys.exit(done("p2332_c_meal_signature"))
