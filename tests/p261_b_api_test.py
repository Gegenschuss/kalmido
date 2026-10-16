#!/usr/bin/env python3
"""2.61.0 API tests (part B, #1819): photo metadata (GPS, camera, capture time) removed on upload.
 - JPEG with EXIF (GPS, camera, serial number, capture time), XMP, IPTC and a comment: stored without them, the colour
   profile kept; without a turn byte for byte the original minus the cut segments; with orientation 6 turned upright
   (pixels) and without any EXIF -- on the ways file store, task attachment, project file and documents
 - PNG (eXIf / tEXt / tIME cut, the rest byte for byte; orientation 6 turned), WebP (EXIF / XMP chunks cut, VP8X flags and
   RIFF size right), HEIC (a hand-built ISOBMFF: the Exif and XMP items emptied in place, same length, structure intact)
 - the setting: account off -> the private file stays as uploaded; an organisation's file follows the organisation (its
   switch beats the account's both ways); only an organisation's admin changes it (member 403, wrong value 400)
 - documents: the capture date (taken_at) read before the removal, also with the setting off; the document's date from
   it when the text has none ("automatic" = photo), a date set by hand drops the mark
 - a broken JPEG / something that only looks like one is stored unchanged (the upload never fails here)
Test pictures are made here with Pillow (tests/requirements.txt); invented names only.
tenant-matrix: org
usage: p261_b_api_test.py <datadir>"""
import io
import os
import struct
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

try:
    from PIL import Image, features
except ImportError:  # pragma: no cover
    print("pillow is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=90):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


# ---------------------------------------------------------------------------------------------------------- test pictures
ICC = b"\x00" * 120 + b"TESTICC-PROFILE"
SECRETS = (b"TestCam", b"Model-X1", b"SN-0042", b"xmpmeta", b"Photoshop 3.0", b"GPS-COMMENT", b"52.5163")


def picture(w=64, h=32):
    """Left half red, right half blue: a turn shows in the pixels."""
    im = Image.new("RGB", (w, h), (0, 0, 255))
    im.paste((255, 0, 0), (0, 0, w // 2, h))
    return im


def exif(orient=1):
    e = Image.Exif()
    e[0x010F] = "TestCam"
    e[0x0110] = "Model-X1"
    e[0x0112] = orient
    e[0x0132] = "2026:05:01 08:00:00"
    sub = e.get_ifd(0x8769)
    sub[0x9003] = "2026:05:04 13:14:15"
    sub[0xA431] = "SN-0042"
    gps = e.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (52.0, 30.0, 58.68)
    gps[3] = "E"
    gps[4] = (13.0, 22.0, 39.0)
    return e.tobytes()  # b"Exif\0\0" + TIFF


def seg(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


XMP = b'http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><exif:GPSLatitude>52.5163N</exif:GPSLatitude></rdf:RDF></x:xmpmeta>'
IPTC = b"Photoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x0c\x1c\x02\x78\x00\x08Berlin!!"


def jpeg(orient=1, meta=True):
    """(stored bytes, the same picture without any metadata segment = what must come back without a turn)."""
    out = io.BytesIO()
    picture().save(out, "JPEG", quality=95, icc_profile=ICC)
    base = out.getvalue()
    if not meta:
        return base, base
    extra = seg(0xE1, exif(orient)) + seg(0xE1, XMP) + seg(0xED, IPTC) + seg(0xFE, b"GPS-COMMENT")
    return base[:2] + extra + base[2:], base


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)


def png(orient=1):
    out = io.BytesIO()
    picture().save(out, "PNG")
    base = out.getvalue()
    p = base.index(b"IDAT") - 4
    extra = (chunk(b"eXIf", exif(orient)[6:]) + chunk(b"tEXt", b"Comment\x00GPS-COMMENT 52.5163")
             + chunk(b"tIME", struct.pack(">HBBBBB", 2026, 5, 4, 13, 14, 15)))
    return base[:p] + extra + base[p:], base


def heic():
    """A small ISOBMFF HEIC: ftyp, meta (hdlr, iinf with a picture, an Exif and an XMP item, iloc), mdat."""
    def box(t, d):
        return struct.pack(">I", 8 + len(d)) + t + d

    def full(t, v, d):
        return box(t, bytes([v, 0, 0, 0]) + d)
    pic = b"\x00\x00\x00\x10HEVC-FAKE-DATA!!"
    ex = b"\x00\x00\x00\x06Exif\x00\x00" + exif(1)[6:]
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><exif:GPSLatitude>52.5163N</exif:GPSLatitude></x:xmpmeta>'
    infe = lambda iid, typ, extra=b"": full(b"infe", 2, struct.pack(">HH", iid, 0) + typ + b"\x00" + extra)  # noqa: E731
    iinf = full(b"iinf", 0, struct.pack(">H", 3) + infe(1, b"hvc1") + infe(2, b"Exif") + infe(3, b"mime", b"application/rdf+xml\x00"))
    hdlr = full(b"hdlr", 0, b"\x00\x00\x00\x00pict" + b"\x00" * 12 + b"\x00")
    ftyp = box(b"ftyp", b"heic\x00\x00\x00\x00mif1heic")

    def build(off):
        iloc = full(b"iloc", 0, bytes([0x44, 0x00]) + struct.pack(">H", 3) + b"".join(
            struct.pack(">HHHII", iid, 0, 1, o, ln) for iid, o, ln in ((1, off, len(pic)), (2, off + len(pic), len(ex)), (3, off + len(pic) + len(ex), len(xmp)))))
        meta = full(b"meta", 0, hdlr + iinf + iloc)
        return ftyp + meta
    head = build(0)
    off = len(head) + 8
    return build(off) + box(b"mdat", pic + ex + xmp), off, len(pic), len(ex), len(xmp)


def webp(orient=1):
    out = io.BytesIO()
    picture().save(out, "WEBP", lossless=True, exif=exif(orient), xmp=XMP[29:])
    return out.getvalue()


def clean(b, what):
    hits = [s for s in SECRETS if s in b]
    check(not hits, f"{what}: no metadata left ({hits})")
    try:
        im = Image.open(io.BytesIO(b))
        ex = im.getexif()
        check(not ex.get_ifd(0x8825) and 0x010F not in ex and not ex.get(0x0112, 1) != 1, f"{what}: no EXIF (GPS / camera / orientation) ({dict(ex)})")
        return im
    except Exception as e:  # noqa: BLE001
        check(False, f"{what}: the stored picture opens ({e})")
        return None


def upright(im, what):
    """Orientation 6 = the stored 64x32 picture is shown turned 90 degrees clockwise: 32x64, red on top, blue below."""
    if not im:
        return
    im = im.convert("RGB")
    check(im.size == (32, 64), f"{what}: turned upright ({im.size})")
    if im.size == (32, 64):
        t, b = im.getpixel((16, 4)), im.getpixel((16, 60))
        check(t[0] > 180 and t[2] < 80 and b[2] > 180 and b[0] < 80, f"{what}: the pixels follow the turn ({t}, {b})")


# ---------------------------------------------------------------------------------------------------------- setup
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE username='alice')", (ORG,), write=True)
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, BOB), write=True)


def put_fs(s, name, data, space="private"):
    r = s.post(B + "/api/files/upload", data={"space": space, "replace": "0"}, files={"file": (name, data, "application/octet-stream")})
    check(r.status_code == 201, f"upload {name} into {space}: {r.status_code} {r.text[:160]}")
    nid = r.json()["items"][0]["id"] if r.ok else 0
    return nid, s.get(B + f"/api/files/nodes/{nid}/content").content


# ---------------------------------------------------------------------------------------------------------- JPEG
orig, base = jpeg(1)
check(all(x in orig for x in SECRETS[:4]), "setup: the test JPEG carries camera, serial, GPS text and XMP")
nid, got = put_fs(Bo, "holiday.jpg", orig)
check(got == base, f"#1819 JPEG without a turn: the original minus the metadata segments, byte for byte ({len(got)} vs {len(base)})")
clean(got, "#1819 JPEG (file store)")
check(ICC in got, "#1819 JPEG: the colour profile stays")
size = dbx("SELECT size FROM fs_nodes WHERE id=?", (nid,))[0][0]
check(size == len(got), f"#1819: the stored size is the size after the removal ({size} / {len(got)})")

orig6, _ = jpeg(6)
_, got = put_fs(Bo, "turned.jpg", orig6)
upright(clean(got, "#1819 JPEG orientation 6 (file store)"), "#1819 JPEG orientation 6 (file store)")
check(ICC in got, "#1819 JPEG turned: the colour profile stays")

# a task attachment (private list) and a project file (organisation list)
lid = Bo.post(B + "/api/lists", json={"name": "Photos private"}).json()["id"]
tid = Bo.post(B + "/api/tasks", json={"title": "With a photo", "list_id": lid}).json()["id"]
r = Bo.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("att.jpg", orig6, "image/jpeg")})
check(r.ok, f"#1819 attachment uploaded {r.status_code} {r.text[:120]}")
aid = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid,))
got = Bo.get(B + f"/api/attachments/{aid[0][0]}").content if aid else b""
upright(clean(got, "#1819 JPEG (task attachment)"), "#1819 JPEG (task attachment)")

P = Bo.post(B + "/api/lists", json={"name": "Photo project", "kind": "project", "org_id": ORG}).json()["id"]
r = Bo.post(B + f"/api/lists/{P}/files", files={"file": ("site.jpg", orig, "image/jpeg")})
check(r.ok, f"#1819 project file uploaded {r.status_code} {r.text[:120]}")
fid = dbx("SELECT id FROM list_files WHERE list_id=? ORDER BY id DESC LIMIT 1", (P,))
got = Bo.get(B + f"/api/list-files/{fid[0][0]}").content if fid else b""
check(got == base, "#1819 JPEG (project file): the original minus the metadata, byte for byte")

# broken / fake: stored as it came
fake = b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00GPS-COMMENT-but-truncated"
_, got = put_fs(Bo, "broken.jpg", fake)
check(got == fake, "#1819: a broken JPEG is stored unchanged (no failed upload)")
txt = b"\xff\xd8 just text named .jpg"
_, got = put_fs(Bo, "text.jpg", txt)
check(got == txt, "#1819: something that is no picture stays as it is")

# ---------------------------------------------------------------------------------------------------------- PNG
p1, pbase = png(1)
_, got = put_fs(Bo, "screen.png", p1)
check(got == pbase, f"#1819 PNG: eXIf / tEXt / tIME cut, the rest byte for byte ({len(got)} vs {len(pbase)})")
clean(got, "#1819 PNG")
p6, _ = png(6)
_, got = put_fs(Bo, "screen6.png", p6)
upright(clean(got, "#1819 PNG orientation 6"), "#1819 PNG orientation 6")

# ---------------------------------------------------------------------------------------------------------- WebP
if features.check("webp"):
    w1 = webp(1)
    check(b"EXIF" in w1 and b"XMP " in w1, "setup: the WebP has EXIF and XMP chunks")
    _, got = put_fs(Bo, "pic.webp", w1)
    check(b"EXIF" not in got and b"XMP " not in got, "#1819 WebP: EXIF / XMP chunks gone")
    check(got[:4] == b"RIFF" and struct.unpack("<I", got[4:8])[0] == len(got) - 8, "#1819 WebP: the RIFF size fits")
    if b"VP8X" in got:
        check(got[got.index(b"VP8X") + 8] & 0x0C == 0, "#1819 WebP: VP8X flags without EXIF / XMP")
    im = clean(got, "#1819 WebP")
    check(im is not None and im.size == (64, 32) and im.convert("RGB").getpixel((2, 2))[0] > 200, "#1819 WebP: the picture unchanged")
    _, got = put_fs(Bo, "pic6.webp", webp(6))
    upright(clean(got, "#1819 WebP orientation 6"), "#1819 WebP orientation 6")
else:
    print("NOTE: this Pillow has no WebP -- the WebP cases are skipped")

# ---------------------------------------------------------------------------------------------------------- HEIC
hc, off, lpic, lex, lxmp = heic()
check(b"TestCam" in hc and b"GPSLatitude" in hc, "setup: the HEIC carries EXIF and XMP")
_, got = put_fs(Bo, "phone.heic", hc)
check(len(got) == len(hc) and got[:off] == hc[:off] and got[off:off + lpic] == hc[off:off + lpic],
      "#1819 HEIC: same length, boxes and picture data untouched")
check(b"TestCam" not in got and b"SN-0042" not in got and b"GPSLatitude" not in got, "#1819 HEIC: the Exif and XMP items are emptied")
check(got[off + lpic + 4:off + lpic + 8] == b"MM\x00*", "#1819 HEIC: the Exif item is an empty but valid TIFF")

# ---------------------------------------------------------------------------------------------------------- the setting
r = Bo.patch(B + "/api/settings", json={"photo_meta_strip": "0"})
check(r.ok and Bo.get(B + "/api/state").json().get("settings", {}).get("photo_meta_strip") == "0", f"#1819: the account switch off ({r.status_code})")
_, got = put_fs(Bo, "keep.jpg", orig)
check(got == orig, "#1819: account off -> a private photo stays exactly as uploaded")
_, got = put_fs(Bo, "org-on.jpg", orig, f"org:{ORG}")
check(got == base, "#1819: ... but a photo into the organisation follows the organisation (on)")

orgs = A.get(B + "/api/orgs").json()["orgs"]
check(any(o["id"] == ORG and o.get("photo_meta_strip") is True for o in orgs), "#1819: GET /api/orgs shows the switch (on by default)")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"photo_meta_strip": False}).status_code == 403, "#1819: a plain member cannot change the organisation's switch")
check(A.patch(B + f"/api/orgs/{ORG}", json={"photo_meta_strip": "no"}).status_code == 400, "#1819: a wrong value: 400")
r = A.patch(B + f"/api/orgs/{ORG}", json={"photo_meta_strip": False})
check(r.ok and r.json().get("photo_meta_strip") is False, f"#1819: the organisation's admin switches it off {r.status_code} {r.text[:120]}")
check(Bo.patch(B + "/api/settings", json={"photo_meta_strip": "1"}).ok, "#1819: account on again")
_, got = put_fs(Bo, "org-off.jpg", orig, f"org:{ORG}")
check(got == orig, "#1819: organisation off beats the account (on): the organisation's photo stays as uploaded")
_, got = put_fs(Bo, "priv-on.jpg", orig)
check(got == base, "#1819: ... while the private photo loses its metadata")
check(A.patch(B + f"/api/orgs/{ORG}", json={"photo_meta_strip": True}).ok, "#1819: the organisation's switch on again")

# ---------------------------------------------------------------------------------------------------------- documents
def doc_up(s, name, data, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, data, "image/jpeg")})
    check(r.status_code == 201, f"document {name}: {r.status_code} {r.text[:160]}")
    return (r.json().get("ids") or [0])[0]


def doc_done(s, nid):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")))


D1 = doc_up(Bo, "receipt-photo.jpg", orig)
d = doc_done(Bo, D1) or {}
check(d.get("taken_at") == "2026-05-04T13:14:15", f"#1819 documents: the capture date is kept ({d.get('taken_at')})")
check(d.get("date") == "2026-05-04" and (d.get("auto") or {}).get("date") == "photo", f"#1819 documents: no date in the text -> the capture day, marked automatic ({d.get('date')}, {d.get('auto')})")
got = Bo.get(B + f"/api/docs/{D1}/file").content
check(got == base, "#1819 documents: the stored photo has no metadata")
check("52.5" not in str(dbx("SELECT * FROM doc_meta WHERE node_id=?", (D1,))), "#1819 documents: no place stored with the document")
r = Bo.patch(B + f"/api/docs/{D1}", json={"date": "2026-06-01"})
d = Bo.get(B + f"/api/docs/{D1}").json()
check(r.ok and d.get("date") == "2026-06-01" and "date" not in (d.get("auto") or {}) and d.get("taken_at") == "2026-05-04T13:14:15",
      f"#1819 documents: a date set by hand drops the mark, the capture date stays ({d.get('auto')})")

Bo.patch(B + "/api/settings", json={"photo_meta_strip": "0"})
D2 = doc_up(Bo, "kept.jpg", orig)
d = doc_done(Bo, D2) or {}
check(d.get("taken_at") == "2026-05-04T13:14:15", "#1819 documents: the capture date also with the setting off")
check(Bo.get(B + f"/api/docs/{D2}/file").content == orig, "#1819 documents: setting off -> the photo as uploaded")
Bo.patch(B + "/api/settings", json={"photo_meta_strip": "1"})
D3 = doc_up(Bo, "plain.jpg", jpeg(1, meta=False)[0])
d = doc_done(Bo, D3) or {}
check(d.get("taken_at") is None and "date" not in (d.get("auto") or {}), "#1819 documents: a photo without EXIF has no capture date")

print(f"{OKS[0]} checks ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
