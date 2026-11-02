#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.477.0 (#3936): the cards of the file store show a small preview of a picture, never the original.
GET /api/files/nodes/<id>/thumb: a small JPEG of a picture file (made on request, ?v= cached by the browser).
 (a) a person WITHOUT an organisation: a picture in her own folder -> a JPEG, smaller than the original, cached with ?v=;
     the list carries the version the cards put into ?v=
 (b) no picture (a text file), a folder -> 404 (the card shows its icon)
 (c) another person -> 404 (as the content)
Invented names and pictures only (the PNG is made here).
usage: p2477_ablagethumb_test.py <datadir>
freelancer-matrix: files"""
import os
import struct
import subprocess
import sys
import time
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"lang": "en", "features": "collab,files,docs", "tour": "done"})


def png(w, h):
    """A noisy RGB picture (does not compress well, like a photo), hand-made without a library."""
    raw, x = b"", 12345
    for _y in range(h):
        row = bytearray([0])
        for _i in range(w * 3):
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF
            row.append(x >> 16 & 255)
        raw += bytes(row)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


FOLDER = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Holiday pictures"}).json()["id"]
BIG = png(480, 360)


def up(name, data, mime):
    r = Fr.post(B + "/api/files/upload", data={"parent_id": str(FOLDER)}, files={"file": (name, data, mime)})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["items"][0]["id"]


PIC = up("beach.png", BIG, "image/png")
TXT = up("packing-list.txt", b"Sun cream, hat", "text/plain")

# (a) a picture -> a small JPEG
r = Fr.get(B + f"/api/files/nodes/{PIC}/thumb?v=1")
check(r.status_code == 200, f"(a) the preview of a picture ({r.status_code})")
check(r.headers.get("Content-Type", "").startswith("image/jpeg") and r.content[:2] == b"\xff\xd8", "(a) the preview is a JPEG")
check(0 < len(r.content) < len(BIG) // 4, f"(a) the preview is small ({len(r.content)} of {len(BIG)} bytes)")
check("max-age" in r.headers.get("Cache-Control", ""), "(a) with ?v= the browser keeps it")
check("max-age" not in Fr.get(B + f"/api/files/nodes/{PIC}/thumb").headers.get("Cache-Control", ""), "(a) without ?v= no long cache")
items = Fr.get(B + f"/api/files?parent={FOLDER}").json().get("items", [])
check(any(n["id"] == PIC and n.get("version") for n in items), "(a) the list carries the version of the picture (the cards' ?v=)")

# (b) no picture -> 404
check(Fr.get(B + f"/api/files/nodes/{TXT}/thumb").status_code == 404, "(b) a text file: no preview (404)")
check(Fr.get(B + f"/api/files/nodes/{FOLDER}/thumb").status_code == 404, "(b) a folder: no preview (404)")

# (c) another person
check(A.get(B + f"/api/files/nodes/{PIC}/thumb").status_code == 404, "(c) another person: 404")
check(A.get(B + f"/api/files/nodes/{PIC}/content").status_code == 404, "(c) another person: 404 on the content too (same rule)")

print(f"p2477_ablagethumb: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
