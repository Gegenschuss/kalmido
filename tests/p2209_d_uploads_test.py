#!/usr/bin/env python3
"""2.209.0 API tests, part D (#1856): the remaining points of the upload review, own container (start.sh) with a virus
scanner configured but not reachable (every upload is "unchecked", not strict). Invented people and firms only (example.com).
freelancer-matrix: office
 - an archived office PDF (old invoice import) gets the unchecked mark, the later scan finds it, a lock blocks its PDF
   (also in the personal office of a person without an organisation)
 - the task search over file texts finds the same tasks with the word-index pre-filter (whole word, prefix, none)
 - text rows of files whose list left an organisation move along before the organisation is deleted
 - organisation and account exports leave out locked files and list them in the manifest
 - photo metadata: GIF comment / XMP blocks, the TIFF EXIF directory, HEIF Exif stored inside another item (method 2)
 - older files get the type their content shows (type column only; the file and its name stay)
usage: p2209_d_uploads_test.py <datadir>      (P2209D_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import json
import os
import struct
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, DATA, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,docs,files,events"
O = "/api/office"


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_app(code):
    """Runs python code inside the server container (the app loaded, c = a connection, system context); -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def box(t, payload):
    return struct.pack(">I", 8 + len(payload)) + t + payload


def heif_m2():
    """A tiny HEIF: item 1 (picture data, method 0 in mdat), item 2 (Exif) stored inside item 1 (construction method 2,
    iref 'iloc' 2 -> 1). -> (bytes, offset of the picture bytes, offset of the Exif bytes)."""
    exif = b"\x00\x00\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00" + b"SerienNr-4711" + b"\x00"
    pic = b"BILDDATEN0"
    payload = pic + exif
    ftyp = box(b"ftyp", b"heic" + b"\x00\x00\x00\x00" + b"mif1heic")
    infe = lambda iid, t: box(b"infe", b"\x02\x00\x00\x00" + struct.pack(">HH", iid, 0) + t + b"\x00")  # noqa: E731
    iinf = box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 2) + infe(1, b"hvc1") + infe(2, b"Exif"))
    iref = box(b"iref", b"\x00\x00\x00\x00" + box(b"iloc", struct.pack(">HHH", 2, 1, 1)))

    def iloc(p):
        it = lambda iid, m, off, ln: struct.pack(">HHHH", iid, m, 0, 1) + struct.pack(">II", off, ln)  # noqa: E731
        return box(b"iloc", b"\x01\x00\x00\x00" + bytes([0x44, 0x00]) + struct.pack(">H", 2)
                   + it(1, 0, p, len(payload)) + it(2, 2, len(pic), len(exif)))
    meta = lambda p: box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc(p) + iref)  # noqa: E731
    p = len(ftyp) + len(meta(0)) + 8
    data = ftyp + meta(p) + box(b"mdat", payload)
    assert data[p:p + len(pic)] == pic
    return data, p, p + len(pic)


def exif_tiff():
    """A little-endian TIFF: IFD0 (width, height, EXIF pointer) at 8, the EXIF IFD at 50 (a serial number as ASCII at 80)."""
    e = lambda tag, typ, cnt, val: struct.pack("<HHI", tag, typ, cnt) + val  # noqa: E731
    ifd0 = struct.pack("<H", 3) + e(256, 3, 1, struct.pack("<HH", 1, 0)) + e(257, 3, 1, struct.pack("<HH", 1, 0)) \
        + e(0x8769, 4, 1, struct.pack("<I", 50)) + struct.pack("<I", 0)
    ex = struct.pack("<H", 1) + e(0xA431, 2, 8, struct.pack("<I", 80)) + struct.pack("<I", 0)
    data = b"II*\x00" + struct.pack("<I", 8) + ifd0 + ex + b"\x00" * (80 - 50 - len(ex)) + b"SN123456"
    assert len(data) == 88 and data[50:52] == b"\x01\x00"
    return data


def gif():
    hdr = b"GIF89a" + bytes([1, 0, 1, 0, 0x80, 0, 0]) + b"\x00\x00\x00\xff\xff\xff"
    loop = b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    img = b"\x2c" + bytes([0, 0, 0, 0, 1, 0, 1, 0, 0]) + b"\x02\x02\x44\x01\x00"
    full = hdr + loop + b"\x21\xfe\x09Kommentar\x00" + b"\x21\xff\x0bXMP DataXMP\x04<x/>\x00" + img + b"\x3b"
    return full, hdr + loop + img + b"\x3b"


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY,
              "KALMIDO_CLAMD": "/nonexistent/clamd.sock", "KALMIDO_CLAMD_STRICT": "0"}, prefix="P2209D")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})


def arch(s, n):
    rid = s.post(B + O + "/legacy/archive/run").json()["run_id"]
    r = s.post(B + O + "/legacy/archive", data={"run_id": rid, "kind": "invoice", "number": f"ALT-{n}", "client_name": "Altkunde",
                                                "date": "2024-05-02", "amount": "100.00"},
               files={"file": (f"alt-{n}.pdf", tiny_pdf(f"Rechnung ALT-{n}"), "application/pdf")})
    return r


def mark(kind, ref):
    r = sql("SELECT state, why FROM upload_scan WHERE kind=? AND ref_id=?", (kind, ref))
    return tuple(r[0]) if r else None


# ---------------------------------------------------------------- 1. archived office PDF: unchecked mark, later scan, lock
r = arch(A, 1)
check(r.status_code == 201, "an old invoice is archived with the scanner unreachable " + r.text[:200])
AR1 = r.json().get("id") if r.ok else 0
check(mark("oar", AR1) == ("unchecked", ""), f"#1856: the archived PDF is marked unchecked ({mark('oar', AR1)})")
row = next((x for x in A.get(B + O + "/legacy/archive").json().get("items", []) if x["id"] == AR1), {})
check((row.get("up") or {}).get("scan") == "unchecked", f"#1856: the archive list shows the mark ({row.get('up')})")
check(A.get(B + O + f"/legacy/archive/{AR1}/pdf").ok, "#1856: not strict: the unchecked PDF still opens")
out = in_app(f"from kalmido.files.scan import _sc_file, _sc_uploader\nf = _sc_file(c, 'oar', {AR1}, 0)\n"
             f"print('scanfile', f[0], f[1].endswith('.pdf'), f[2] > 0, _sc_uploader(c, 'oar', {AR1}, 0)[0])")
check(f"scanfile alt-1.pdf True True {ALICE}" in out, "#1856: the later scan finds the archived PDF and its uploader " + out[-300:])
sql("UPDATE upload_scan SET state='infected', sig='Test-Signatur' WHERE kind='oar' AND ref_id=?", (AR1,), write=True)
r = A.get(B + O + f"/legacy/archive/{AR1}/pdf")
check(r.status_code == 403 and "Test-Signatur" in r.text, "#1856: a locked archived PDF does not open " + r.text[:200])
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
r = arch(Fr, 2)
check(r.status_code == 201 and mark("oar", r.json().get("id")) == ("unchecked", ""),
      f"freelancer #1856: the personal office's archived PDF is marked too {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- 2. task search over file texts with the word-index pre-filter
L1 = A.post(B + "/api/lists", json={"name": "Belege Alpha"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Ablage pruefen", "list_id": L1}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Anderes", "list_id": L1}).json()["id"]
r = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("beleg.pdf", tiny_pdf("Zauberwort Bananenkiste Lieferung"), "application/pdf")})
check(r.ok, "a task file " + r.text[:200])
A.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("andere.pdf", tiny_pdf("Gurkenglas Lieferung"), "application/pdf")})
AT1 = sql("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T1,))[0][0]
AT2 = sql("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T2,))[0][0]
ok = until(lambda: sql("SELECT COUNT(*) FROM file_text WHERE kind='att' AND ref_id IN (?,?) AND state='found'", (AT1, AT2))[0][0] == 2, 150)
check(ok, "the texts of both task files are recognised " + str(sql("SELECT ref_id, state, error FROM file_text WHERE kind='att'")))


def tsearch(q):
    r = A.get(B + "/api/tasks", params={"scope": "search", "q": q})
    return set(t["id"] for t in r.json().get("tasks", [])) if r.ok else {"error", r.status_code}


check(T1 in tsearch("bananenkiste") and T2 not in tsearch("bananenkiste"), f"#1856: a whole word finds its task only ({tsearch('bananenkiste')})")
check(T1 in tsearch("bananenk"), "#1856: a word beginning finds the task")
check({T1, T2} <= tsearch("lieferung"), "#1856: a word of both files finds both tasks")
check(T1 in tsearch("zauberwort lieferung") and T2 not in tsearch("zauberwort lieferung"), "#1856: every word must be in the file")
check(not ({T1, T2} & tsearch("nirgendwortx")), "#1856: an unknown word finds nothing")
out = in_app(f"from kalmido.files.textscan import ts_task_hits\nprint('hits', sorted(ts_task_hits(c, {ALICE}, 'bananenkiste').items()))")
check(f"hits [({T1}, 'beleg.pdf')]" in out, "#1856: ts_task_hits answers task id + file name " + out[-300:])
out = in_app(f"from kalmido.files.textscan import ts_task_hits\nprint('fhits', sorted(ts_task_hits(c, {FID}, 'bananenkiste').items()))")
check("fhits []" in out, "#1856: another person's search does not see the files " + out[-300:])

# ---------------------------------------------------------------- 3. text rows follow a list that left an organisation before its deletion
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Beta Liste"}).json()["id"]
sql("UPDATE lists SET org_id=? WHERE id=?", (ORG2, L2), write=True)
T3 = A.post(B + "/api/tasks", json={"title": "Beta Aufgabe", "list_id": L2}).json()["id"]
A.post(B + f"/api/tasks/{T3}/attachments", files={"file": ("beta.pdf", tiny_pdf("Wanderdüne Beta"), "application/pdf")})
AT3 = sql("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T3,))[0][0]
until(lambda: sql("SELECT 1 FROM file_text WHERE kind='att' AND ref_id=? AND state='found'", (AT3,)), 150)
check(sql("SELECT org_id FROM file_text WHERE kind='att' AND ref_id=?", (AT3,)) == [(ORG2,)], "the text row belongs to Beta")
sql("UPDATE lists SET org_id=NULL WHERE id=?", (L2,), write=True)  # the list left Beta just before (no sweep since)
out = in_app(f"from kalmido.files.textscan import ts_org_rehome\nts_org_rehome(c, {ORG2})\nc.commit()\n"
             f"print('rows', c.execute(\"SELECT org_id, ws, state FROM file_text WHERE kind='att' AND ref_id=?\", ({AT3},)).fetchall())")
check(f"'u{ALICE}'" in out and "None" in out, "#1856: the text row moved to the list's new space before the deletion " + out[-300:])
check(sql("SELECT org_id FROM file_text WHERE kind='att' AND ref_id=?", (AT1,)) == [(ORG,)], "#1856: rows of other organisations stay")

# ---------------------------------------------------------------- 4. exports leave out locked files and list them
sql("UPDATE upload_scan SET state='infected', sig='Test-Signatur' WHERE kind='att' AND ref_id=?", (AT2,), write=True)  # unchecked since its upload
out = in_app(f"import io, json, zipfile\nfrom kalmido.admin.orgexport import ox_build\nb = io.BytesIO()\nm = ox_build(c, {ORG}, b, None)\n"
             "z = zipfile.ZipFile(io.BytesIO(b.getvalue()))\n"
             "print('ox', json.dumps({'names': [n for n in z.namelist() if n.startswith('files/')], 'locked': m.get('locked_files')}))")
try:
    ox = json.loads(out.split("ox ", 1)[1].splitlines()[0])
except (IndexError, ValueError):
    ox = {"names": [], "locked": None}
check(any(n.startswith(f"files/attachments/{AT1}-") for n in ox["names"]), "#1856: the organisation export keeps the clean file " + out[-300:])
check(not any(n.startswith(f"files/attachments/{AT2}-") for n in ox["names"]), "#1856: ... and leaves out the locked one")
locked = {(x["area"], x["id"]): x for x in ox["locked"] or []}
check(("att", AT2) in locked and locked[("att", AT2)]["signature"] == "Test-Signatur" and locked[("att", AT2)]["name"] == "andere.pdf",
      f"#1856: the manifest lists the locked task file ({ox['locked']})")
check(("oar", AR1) in locked and not any("alt-1" in n or f"archive-{AR1}-" in n for n in ox["names"]),
      "#1856: the locked archived PDF is listed, not in the office folder of the export")
out = in_app(f"import io, zipfile\nfrom kalmido.admin.acctexport import umz_build\nb = io.BytesIO()\nm = umz_build(c, {ALICE}, b, 'x1')\n"
             "z = zipfile.ZipFile(io.BytesIO(b.getvalue()))\n"
             f"print('umz', any(n.startswith('files/attachments/{AT2}-') for n in z.namelist()), "
             f"any(n.startswith('files/attachments/{AT1}-') for n in z.namelist()), [(x['area'], x['id']) for x in m['locked_files']])")
check(f"umz False True [('attachments', {AT2})]" in out, "#1856: the account export leaves out the locked file and lists it " + out[-300:])

# ---------------------------------------------------------------- 5. photo metadata: GIF, TIFF EXIF directory, HEIF method 2
g, want = gif()
hf, pic_at, exif_at = heif_m2()
tf = exif_tiff()
out = in_app("import base64\nfrom kalmido.files.photometa import _pm_gif, _pm_tiff, _pm_heif, pm_kind\n"
             f"g = base64.b64decode('{base64.b64encode(g).decode()}')\nh = base64.b64decode('{base64.b64encode(hf).decode()}')\n"
             f"t = base64.b64decode('{base64.b64encode(tf).decode()}')\n"
             "print('pm', pm_kind(g), base64.b64encode(_pm_gif(g, True)[0] or b'').decode(), base64.b64encode(_pm_heif(h, True)[0] or b'').decode(), "
             "base64.b64encode(_pm_tiff(t, True)[0] or b'').decode(), _pm_gif(g, False)[0])")
parts = out.split("pm ", 1)[1].split() if "pm " in out else []
check(len(parts) == 5 and parts[0] == "gif" and base64.b64decode(parts[1]) == want, "#1856: a GIF loses comment and XMP, keeps loop and image " + out[-300:])
hout = base64.b64decode(parts[2]) if len(parts) == 5 else b""
check(len(hout) == len(hf) and b"SerienNr" not in hout and hout[pic_at:pic_at + 10] == b"BILDDATEN0" and hout[:exif_at] == hf[:exif_at],
      "#1856: HEIF Exif inside another item is emptied in place, the picture bytes stay")
tout = base64.b64decode(parts[3]) if len(parts) == 5 else b""
check(len(tout) == len(tf) and b"SN123456" not in tout and tout[:50] == tf[:50] and tout[50:52] == b"\x00\x00",
      "#1856: the TIFF EXIF directory is emptied, the image directory stays")
check(len(parts) == 5 and parts[4] == "None", "#1856: with the setting off a GIF stays as it is")
# 2.209.0 review (#1856): a GIF without a global colour table loses its comment too; a camera RAW keeps its EXIF directory
g2 = b"GIF89a" + bytes([1, 0, 1, 0, 0, 0, 0]) + b"\x21\xfe\x03abc\x00" + b"\x2c" + bytes([0, 0, 0, 0, 1, 0, 1, 0, 0]) + b"\x02\x02\x44\x01\x00\x3b"
_e = lambda tag, typ, cnt, val: struct.pack("<HHI", tag, typ, cnt) + val  # noqa: E731
dng = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 4) + _e(256, 3, 1, struct.pack("<HH", 1, 0)) \
    + _e(257, 3, 1, struct.pack("<HH", 1, 0)) + _e(0x8769, 4, 1, struct.pack("<I", 62)) + _e(0xC612, 1, 4, bytes([1, 4, 0, 0])) \
    + struct.pack("<I", 0) + struct.pack("<H", 1) + _e(0xA431, 2, 8, struct.pack("<I", 80)) + struct.pack("<I", 0) + b"SN123456"
assert len(dng) == 88
out = in_app("import base64\nfrom kalmido.files.photometa import _pm_gif, _pm_tiff\n"
             f"a = base64.b64decode('{base64.b64encode(g2).decode()}')\nr = base64.b64decode('{base64.b64encode(dng).decode()}')\n"
             "print('pm2', base64.b64encode(_pm_gif(a, True)[0] or b'').decode() or '-', b'SN123456' in (_pm_tiff(r, True)[0] or r))")
p2 = out.split("pm2 ", 1)[1].split() if "pm2 " in out else []
check(len(p2) == 2 and base64.b64decode(p2[0]) == g2[:13] + g2[20:], "#1856: a GIF without a global colour table loses its comment " + out[-300:])
check(len(p2) == 2 and p2[1] == "True", "#1856: a camera RAW (DNG version tag) keeps its EXIF directory")

# ---------------------------------------------------------------- 6. older files get the type their content shows
T4 = A.post(B + "/api/tasks", json={"title": "Altdatei", "list_id": L1}).json()["id"]
r = A.post(B + f"/api/tasks/{T4}/attachments", files={"file": ("bild.png", b"<html><body>kein Bild</body></html>", "text/html")})
AT4 = sql("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T4,))[0][0]
sql("UPDATE attachments SET mime='image/png' WHERE id=?", (AT4,), write=True)  # as stored before the type check
sql("DELETE FROM settings WHERE key='sc_mime_sweep'", write=True)
out = in_app("from kalmido.files.scan import sc_mime_sweep\nn = 0\nfor _ in range(10):\n    n += sc_mime_sweep(c, 500, force=True)\n"
             "c.commit()\nprint('swept', n)")
r4 = sql("SELECT mime, name, path FROM attachments WHERE id=?", (AT4,))[0]
check(r4[0] == "application/octet-stream" and r4[1] == "bild.png", f"#1856: the old file's type follows its content ({r4[0]}, {r4[1]}) " + out[-200:])
check(sql("SELECT mime FROM attachments WHERE id=?", (AT1,)) == [("application/pdf",)], "#1856: a matching type stays")
st = json.loads(sql("SELECT value FROM settings WHERE key='sc_mime_sweep'")[0][0] or "{}")
check(set(st.get("done") or []) == {"att", "list", "fs"}, f"#1856: the type check runs once and ends ({st})")
check(A.get(B + f"/api/tasks/{T4}").ok and any(x["id"] == AT4 for x in A.get(B + f"/api/tasks/{T4}").json().get("attachments", [])),
      "#1856: the file stays")

sys.exit(kt.done("p2209_d_uploads"))
