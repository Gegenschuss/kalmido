#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.583.0 part E (#4812): the sharper preview of big cards (800 px) next to the small one (320 px).
 (a) a person WITHOUT an organisation uploads a PDF and a photo as documents: both get doc_meta.thumb_l, the list / the
     document say thumb_l; /api/docs/<id>/thumb?size=l is a JPEG 800 px wide, the small one at most 320 px; its file lies
     beside the small one and is sealed the same way (both JPEG on disk, or both sealed)
 (b) another person gets 404 for ?size=l (as for the small one) -- no own route, the rights of the document
 (c) no sharp one yet: ?size=l answers with the small one; the catch-up (docs/thumbfill.py) fills it in while the queue is
     idle, the small one stays as it was
 (d) a plain picture of the file store: /api/files/nodes/<id>/thumb?size=l 800 px wide, the default 320; another person 404
 (e) the card size per person (dc_tile_d / dc_tile_m): a number 7..28 or '' (standard), anything else 400
Invented names, pages and pictures only (made here).
usage: p2583_e_thumb_test.py <datadir>
freelancer-matrix: docs, files"""
import os
import struct
import sys
import time
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, setup, until  # noqa: E402

fresh({"KALMIDO_DOCS_THUMB_FILL_S": "1"}, prefix="P2583E")
time.sleep(0.3)
A = setup()
FID, Fr = freelancer(B, A, "frida", features="collab,files,docs")
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,files,docs", "tour": "done"})


def pdf(lines):
    """A one-page PDF written by hand (A4 portrait)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    st = "BT /F1 14 Tf 60 760 Td 18 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>",
            f"<< /Length {len(st)} >>\nstream\n{st}\nendstream"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n"
    return out.encode("latin1")


def png(w, h):
    """An RGB picture with stripes, hand-made without a library."""
    raw = b"".join(b"\x00" + bytes((x * 7 + y) & 255 for x in range(w) for _ in range(3)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def jpeg_w(b):
    """The width of a JPEG (its SOF marker), 0 when it is none."""
    if b[:2] != b"\xff\xd8":
        return 0
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            return 0
        m, ln = b[i + 1], struct.unpack(">H", b[i + 2:i + 4])[0]
        if m in (0xC0, 0xC1, 0xC2):
            return struct.unpack(">H", b[i + 7:i + 9])[0]
        i += 2 + ln
    return 0


def up_doc(name, data, mime):
    r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, data, mime)})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: Fr.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 90)
    return nid


PDF = up_doc("water-bill.pdf", pdf(["Wasserwerk Beispielstadt", "Abrechnung 2026", "Datum 02.10.2026", "Betrag 48,20 EUR"]), "application/pdf")
PIC = up_doc("receipt-photo.png", png(1200, 900), "image/png")

# (a) both previews, the sharp one 800 px wide
for nid, what in ((PDF, "PDF"), (PIC, "photo")):
    d = Fr.get(B + f"/api/docs/{nid}").json()
    check(d.get("thumb") and d.get("thumb_l") is True, f"(a) {what}: the document has the small and the sharp preview {d.get('thumb')}/{d.get('thumb_l')}")
    s, l = Fr.get(B + f"/api/docs/{nid}/thumb?v=1"), Fr.get(B + f"/api/docs/{nid}/thumb?v=1&size=l")
    check(s.status_code == 200 and 0 < jpeg_w(s.content) <= 320, f"(a) {what}: the small preview at most 320 px ({s.status_code}, {jpeg_w(s.content)})")
    check(l.status_code == 200 and jpeg_w(l.content) == 800, f"(a) {what}: ?size=l a JPEG 800 px wide ({l.status_code}, {jpeg_w(l.content)})")
    check("max-age" in l.headers.get("Cache-Control", ""), f"(a) {what}: with ?v= the browser keeps the sharp one too")
    row = dbx("SELECT thumb, thumb_l FROM doc_meta WHERE node_id=?", (nid,))[0]
    check(row[1] and row[1] != row[0] and row[1].startswith("docthumbs/"), f"(a) {what}: its own file beside the small one {list(row)}")
    fs, fl = (os.path.join(DATA, "attachments", x) for x in row)
    if os.path.exists(fs) and os.path.exists(fl):
        with open(fs, "rb") as f1, open(fl, "rb") as f2:
            check((f1.read(2) == b"\xff\xd8") == (f2.read(2) == b"\xff\xd8"), f"(a) {what}: sealed like the small one")
listed = {x["id"]: x for x in Fr.get(B + "/api/docs?ws=private").json().get("docs", [])}
check(listed.get(PDF, {}).get("thumb_l") is True, "(a) the list carries thumb_l (the cards ask for the sharp one only then)")

# (b) another person: no preview of either size
check(A.get(B + f"/api/docs/{PDF}/thumb?size=l").status_code in (403, 404), "(b) another person: ?size=l is refused")
check(A.get(B + f"/api/docs/{PDF}/thumb").status_code in (403, 404), "(b) ... like the small one")

# (c) no sharp one yet: the small one answers; the catch-up makes it while the queue is idle
small0 = dbx("SELECT thumb FROM doc_meta WHERE node_id=?", (PDF,))[0][0]
dbx("UPDATE doc_meta SET thumb_l=NULL WHERE node_id=?", (PDF,))
dbx("INSERT INTO settings(key, value) VALUES('docs_thumb_l_fill', '{\"done\": 1}') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
check(Fr.get(B + f"/api/docs/{PDF}").json().get("thumb_l") is False, "(c) without the sharp one: thumb_l false")
r = Fr.get(B + f"/api/docs/{PDF}/thumb?size=l")
check(r.status_code == 200 and 0 < jpeg_w(r.content) <= 320, f"(c) ?size=l answers with the small one while it is missing ({r.status_code}, {jpeg_w(r.content)})")
dbx("DELETE FROM settings WHERE key='docs_thumb_l_fill'")  # as after the update: the catch-up has not run yet
got = until(lambda: (dbx("SELECT thumb_l FROM doc_meta WHERE node_id=?", (PDF,))[0][0] or ""), 90)
check(bool(got), "(c) the catch-up made the sharp preview again")
check(jpeg_w(Fr.get(B + f"/api/docs/{PDF}/thumb?size=l").content) == 800, "(c) ... 800 px wide")
check(dbx("SELECT thumb FROM doc_meta WHERE node_id=?", (PDF,))[0][0] == small0, "(c) the small preview stayed as it was")
check(until(lambda: '"done"' in (dbx("SELECT value FROM settings WHERE key='docs_thumb_l_fill'") or [[""]])[0][0], 30), "(c) the catch-up ends with done")

# (d) a plain picture of the file store (made on request, never stored)
FOLDER = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Garden"}).json()["id"]
r = Fr.post(B + "/api/files/upload", data={"parent_id": str(FOLDER)}, files={"file": ("pond.png", png(1000, 750), "image/png")})
assert r.status_code == 201, r.text
FILE = r.json()["items"][0]["id"]
s, l = Fr.get(B + f"/api/files/nodes/{FILE}/thumb?v=1"), Fr.get(B + f"/api/files/nodes/{FILE}/thumb?v=1&size=l")
check(s.status_code == 200 and jpeg_w(s.content) == 320, f"(d) a picture of the file store: 320 px by default ({s.status_code}, {jpeg_w(s.content)})")
check(l.status_code == 200 and jpeg_w(l.content) == 800, f"(d) ... ?size=l 800 px ({l.status_code}, {jpeg_w(l.content)})")
check(A.get(B + f"/api/files/nodes/{FILE}/thumb?size=l").status_code == 404, "(d) another person: 404")

# (e) the card size, a computer and a phone each their own
check(Fr.patch(B + "/api/settings", json={"dc_tile_d": "14.5"}).ok and Fr.patch(B + "/api/settings", json={"dc_tile_m": 8}).ok, "(e) the card size is saved")
st = Fr.get(B + "/api/state").json().get("settings", {})
check(st.get("dc_tile_d") == "14.5" and st.get("dc_tile_m") == "8", f"(e) ... each device kind its own {st.get('dc_tile_d')}/{st.get('dc_tile_m')}")
for bad in ("40", "3", "abc", "nan"):
    check(Fr.patch(B + "/api/settings", json={"dc_tile_d": bad}).status_code == 400, f"(e) {bad!r} is refused")
check(Fr.patch(B + "/api/settings", json={"dc_tile_d": ""}).ok and Fr.get(B + "/api/state").json()["settings"].get("dc_tile_d") == "", "(e) '' = the standard size again")

sys.exit(done("p2583_e_thumb"))
