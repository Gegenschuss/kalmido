#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.372.0 (#3316): the own signature picture for entertainment receipts without the right to the correspondence, and the
snapshot of the picture at approving. Own container (start.sh). Invented people and data only; the pictures are drawn here
(a few strokes on a transparent PNG), never a real signature.
freelancer-matrix: office
 - a staff member (office group "Staff": entertainment receipts on the level "own", no correspondence): the letters profile
   stays 403, GET / PUT / DELETE /api/office/meals/signature work on the person's OWN picture; my_sig follows it
 - another person never reaches it: a user_id in the body is ignored, Bob's GET shows Bob's (empty) picture
 - a member on "Previous access" (no entertainment receipts at all): 403
 - the staff member approves as host with the picture: on the PDF
 - snapshot: removing or replacing the profile picture later leaves the approved receipt's picture as it was; undoing the
   approval drops the snapshot (approved again without a picture: none)
 - the admin's letters profile and the receipts' route are the one picture
 - a person without organisation: own picture through the route, snapshot on the own receipt
usage: p2372_meal_sig_test.py <datadir>"""
import base64
import io
import os
import struct
import sys
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, sess, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2372")
O = "/api/office"
M = O + "/meals"
SIG = M + "/signature"
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"


def png_strokes(w, h):
    """A transparent RGBA PNG of w x h with a dark zigzag stroke (like the drawing field's output)."""
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


PIC1 = "data:image/png;base64," + base64.b64encode(png_strokes(220, 70)).decode()
PIC2 = "data:image/png;base64," + base64.b64encode(png_strokes(120, 40)).decode()

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ids, S = {}, {}
for u, n in (("sam", "Sam Staff"), ("bob", "Bob Other"), ("carl", "Carl Member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"{u} created {r.text[:200]}")
    ids[u] = r.json()["id"]
    check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok, f"{u} is a member")
    S[u] = sess(u)
for s in (A, *S.values()):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
Sa, Bo, Ca = S["sam"], S["bob"], S["carl"]
SAM, BOB = ids["sam"], ids["bob"]
for u in ("sam", "bob"):
    r = A.put(B + f"{O}/rights/people/{ids[u]}", json={"groups": ["tpl:staff"]})
    check(r.ok, f"{u} in the group Staff {r.status_code} {r.text[:200]}")
TD = testclock.today().isoformat()
FID, Fr = freelancer(B, A)  # freelancer-matrix: office


def meal(s, host):
    b = {"date": TD, "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}], "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "0"}
    r = s.post(B + M, json=b)
    check(r.status_code == 201, f"meal created {r.status_code} {r.text[:200]}")
    return r.json().get("id")


def approve(s, mid, **kw):
    r = s.post(B + f"{M}/{mid}/approve", json=kw)
    check(r.ok and r.json().get("status") == "approved", f"meal {mid} approved {r.status_code} {r.text[:200]}")
    return r.json()


def widths(s, mid):
    """The widths of the image XObjects over all pages of the meal's PDF (the signature picture's size tells which one)."""
    r = s.get(B + f"{M}/{mid}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"meal PDF {r.status_code}")
    out = []
    for p in PdfReader(io.BytesIO(r.content)).pages:
        xo = (p.get("/Resources") or {}).get("/XObject") or {}
        out += [int(xo[k].get_object().get("/Width")) for k in xo if xo[k].get_object().get("/Subtype") == "/Image"]
    return out


# ---------------------------------------------------------------- the rights: own picture without the correspondence
check(Sa.get(B + O + "/letters/profile").status_code == 403, "staff: the letters profile stays closed (no correspondence)")
check(Sa.put(B + O + "/letters/profile", json={"image": PIC1}).status_code == 403, "staff: no write through the letters profile")
r = Sa.get(B + SIG)
check(r.ok and r.json().get("has_image") is False, f"staff: GET own picture (none yet) {r.status_code} {r.text[:200]}")
r = Sa.put(B + SIG, json={"image": PIC1, "user_id": BOB})
check(r.ok and r.json().get("has_image") and r.json().get("image", "").startswith("data:image/png;base64,"), f"staff: picture saved {r.status_code} {r.text[:200]}")
check(set(r.json()) == {"has_image", "image"}, f"the route answers only the picture, nothing of the letters {sorted(r.json())}")
check(Sa.get(B + M).json().get("my_sig") == 1, "staff: my_sig = 1")
check(Bo.get(B + SIG).json().get("has_image") is False, "Bob: his own (empty) picture, never Sam's; the user_id in the body was ignored")
check(Bo.get(B + M).json().get("my_sig") == 0, "Bob: my_sig = 0")
check(Sa.put(B + SIG, json={}).status_code == 400, "PUT without a picture: 400")
check(Sa.put(B + SIG, json={"image": "data:image/png;base64," + base64.b64encode(b"not a picture").decode()}).status_code == 400, "not a PNG / JPEG: 400")
for meth in ("get", "put", "delete"):
    rr = getattr(Ca, meth)(B + SIG, **({"json": {"image": PIC1}} if meth == "put" else {}))
    check(rr.status_code == 403, f"a member without entertainment receipts: {meth.upper()} 403 ({rr.status_code})")
check(Sa.get(B + SIG).json().get("has_image"), "Sam's picture is still there")

# ---------------------------------------------------------------- the staff member approves as host; the snapshot
m1 = meal(A, SAM)
j = approve(Sa, m1)
check(j.get("approved_by") == SAM and j.get("sign_image") == 1, f"staff approves as host with the picture ({j.get('approved_by')}, {j.get('sign_image')})")
check(widths(Sa, m1) == [220], f"the picture on the PDF {widths(Sa, m1)}")
r = Sa.put(B + SIG, json={"image": PIC2})
check(r.ok, "staff replaces the picture")
check(widths(Sa, m1) == [220] and widths(A, m1) == [220], f"snapshot: the approved receipt keeps the picture of the approval {widths(A, m1)}")
m2 = meal(A, SAM)
approve(Sa, m2)
check(widths(Sa, m2) == [120], f"a new approval takes the new picture {widths(Sa, m2)}")
r = Sa.delete(B + SIG)
check(r.ok and r.json().get("has_image") is False, f"staff removes the picture {r.status_code}")
check(Sa.get(B + M).json().get("my_sig") == 0, "staff: my_sig = 0 after removing")
check(widths(Sa, m1) == [220] and widths(Sa, m2) == [120], "snapshot: removing the profile picture leaves both approved receipts as they were")
r = A.post(B + f"{M}/{m1}/unlock", json={"reason": "Typo in the occasion"})
check(r.ok and r.json().get("sign_image") == 0, f"approval undone {r.status_code} {r.text[:200]}")
check(widths(Sa, m1) == [], "undone: the snapshot is gone")
j = approve(Sa, m1)
check(j.get("sign_image") == 0 and widths(Sa, m1) == [], "approved again without a picture: none (the old snapshot did not come back)")

# ---------------------------------------------------------------- the admin: the one picture of letters and receipts
r = A.put(B + O + "/letters/profile", json={"image": PIC1, "greeting": "Best regards"})
check(r.ok and r.json().get("has_image"), "admin: picture through the letters profile")
check(A.get(B + SIG).json().get("has_image"), "admin: the receipts' route shows the same picture")
check(A.delete(B + SIG).ok and not A.get(B + O + "/letters/profile").json().get("has_image"), "admin: removed through the receipts' route = gone from the letters profile")
check(A.get(B + O + "/letters/profile").json().get("greeting") == "Best regards", "the greeting of the letters stays")

# ---------------------------------------------------------------- a person without organisation
r = Fr.put(B + SIG, json={"image": PIC1})
check(r.ok and r.json().get("has_image"), f"freelancer: own picture through the receipts' route {r.status_code} {r.text[:200]}")
mf = meal(Fr, FID)
j = approve(Fr, mf)
check(j.get("sign_image") == 1 and widths(Fr, mf) == [220], "freelancer: the own picture on the own receipt")
check(Fr.delete(B + SIG).ok and widths(Fr, mf) == [220], "freelancer: snapshot stays after removing the picture")

sys.exit(done("p2372_meal_sig"))
