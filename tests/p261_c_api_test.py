#!/usr/bin/env python3
"""2.61.0 API tests (part C, #1820): text recognition of normal stored files in the background.
 - a PDF with a text layer as a task file: recognised in the background (file_text found), the task search finds the
   task by a word of the file (whole word and prefix) with file_hit = the file's name
 - an image with text (drawn here with Pillow) in an organisation's task and in the Ablage: recognised by OCR (only when
   the image has Tesseract), found in the task search and in the Ablage search (GET /api/files/search, hit "text")
 - a project file: found by the Ablage search (list_files)
 - the same content in the same workspace takes the text over; a HEIC file gets no mark (state skip)
 - the boundary: another person (no organisation) and a person of another organisation find nothing; the search route
   refuses a foreign organisation's space
 - agents: GET /api/v1/attachments/{id}/text of a scan brings the recognised text (source ocr)
 - deleting the file (attachment, project file, Ablage file for good) deletes its text row and index words; the trash
   hides it from the search
 - the catch-up: a file without a text row (stored before the release) is queued and recognised
Test files are made here (hand-written PDF, Pillow image); invented words only.
tenant-matrix: org
usage: p261_c_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
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


def until(fn, secs=120):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def text_png(lines):
    """A white picture with large black text (a photo of a note)."""
    font = None
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            font = ImageFont.truetype(p, 56)
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=56)
        except TypeError:
            font = ImageFont.load_default()
    im = Image.new("L", (1400, 200 + 110 * len(lines)), 255)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((80, 80 + i * 110), ln, fill=0, font=font)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def ft(kind, ref_id):
    r = dbx("SELECT state, error, method FROM file_text WHERE kind=? AND ref_id=?", (kind, ref_id))
    return tuple(r[0]) if r else None


def settled(kind, ref_id, secs=150):
    return until(lambda: (ft(kind, ref_id) or ("",))[0] in ("found", "none", "skip", "error") and ft(kind, ref_id), secs)


def tsearch(s, q):
    r = s.get(B + "/api/tasks", params={"scope": "search", "q": q})
    return {t["id"]: t for t in r.json().get("tasks", [])} if r.ok else {}


def fsearch(s, q, space=None):
    p = {"q": q}
    if space:
        p["space"] = space
    return s.get(B + "/api/files/search", params=p)


# ---------------------------------------------------------------------------------------------------------- setup
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123",
                                      "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Other Co"})
O2 = r.json()["id"] if r.ok else 0
check(r.status_code == 201, f"setup: a second organisation {r.status_code} {r.text[:120]}")
A.post(B + "/api/users", json={"username": "zoe", "display_name": "Zoe", "password": "password123", "orgs": [O2], "email": "zoe@example.com"})
Zo = sess("zoe")
A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin", "password": "password123", "orgs": [], "email": "erin@example.com"})
Er = sess("erin")
OCR = A.get(B + "/api/docs/settings", params={"ws": "private"}).json().get("ocr")
print("OCR in the image:", OCR, flush=True)

# ---------------------------------------------------------------------------------------------------------- task file, PDF text layer
L1 = Bo.post(B + "/api/lists", json={"name": "Private things"}).json()["id"]
T1 = Bo.post(B + "/api/tasks", json={"title": "Pay the bill", "list_id": L1}).json()["id"]
PDF = text_pdf(["Invoice 2026-17", "Wolkenkratzer Fensterputz", "Total 99 EUR"])
r = Bo.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("bill.pdf", PDF, "application/pdf")})
check(r.ok, f"#1820 upload of a task file {r.status_code} {r.text[:120]}")
A1 = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T1,))[0][0]
check(ft("att", A1) is not None, "#1820: the upload queues the file (a file_text row at once)")
st = settled("att", A1)
check(st and st[0] == "found" and st[2] == "pdf", f"#1820: the PDF's text layer is read in the background ({st})")
att = {x["name"]: x for x in Bo.get(B + f"/api/tasks/{T1}").json().get("attachments", [])}.get("bill.pdf") or {}
check((att.get("up") or {}).get("text") == "found", f"#1820 (with #1818's marks): the task file carries up.text found ({att.get('up')})")
n_words = dbx("SELECT COUNT(*) FROM file_words w JOIN file_text f ON f.id=w.ft_id WHERE f.kind='att' AND f.ref_id=?", (A1,))[0][0]
# 2.81.0 (#1856): the nightly boundary check counts a recognised text kept for another workspace than its file's list
dbx("UPDATE file_text SET org_id=? WHERE kind='att' AND ref_id=?", (ORG, A1), write=True)
bd = A.get(B + "/api/admin/orgs").json().get("boundary", {})
dbx("UPDATE file_text SET org_id=NULL WHERE kind='att' AND ref_id=?", (A1,), write=True)
check(bd.get("kinds", {}).get("file_text") == 1, "#1856: the boundary check counts file_text across the boundary " + str(bd.get("kinds")))
check(not A.get(B + "/api/admin/orgs").json().get("boundary", {}).get("kinds", {}).get("file_text"), "#1856: ... and nothing when it fits")
# 2.81.0 (#1856): a run of 35 minutes is not taken up again (the longest recognition, 30 pages x 60 s, is still going on)
old = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
dbx("UPDATE file_text SET state='run', updated_at=? WHERE kind='att' AND ref_id=?", (old, A1), write=True)
time.sleep(12)
st35 = ft("att", A1)
dbx("UPDATE file_text SET state='found' WHERE kind='att' AND ref_id=?", (A1,), write=True)
check(st35 and st35[0] == "run", f"#1856: a long run stays with its worker ({st35})")
check(n_words > 0, f"#1820: the words are in the keyed index ({n_words})")
hits = tsearch(Bo, "wolkenkratzer")
check(T1 in hits and hits[T1].get("file_hit") == "bill.pdf", f"#1820: the task search finds the task by its file's text, file_hit = the name ({hits.get(T1, {}).get('file_hit')})")
check(T1 in tsearch(Bo, "Fensterp"), "#1820: a prefix of 4+ letters finds it too")
check(T1 in tsearch(Bo, "fensterputz wolkenkratzer"), "#1820: several words: all must be in the text")
check(T1 not in tsearch(Bo, "fensterputz giraffe"), "#1820: a word that is not in the text: no hit")
check(T1 not in tsearch(Er, "wolkenkratzer") and T1 not in tsearch(A, "wolkenkratzer"),
      "#1820: another person (not in the private list) does not find the task")
hits = tsearch(Bo, "pay the")
check(T1 in hits and not hits[T1].get("file_hit"), "#1820: a title hit carries no file mark")

# the same content in the same workspace: the text is taken over (no second recognition)
T2 = Bo.post(B + "/api/tasks", json={"title": "Copy", "list_id": L1}).json()["id"]
Bo.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("copy.pdf", PDF, "application/pdf")})
A2 = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T2,))[0][0]
st = settled("att", A2)
check(st and st[0] == "found", f"#1820: the copy is found too ({st})")
sha = dbx("SELECT COUNT(DISTINCT sha256) FROM file_text WHERE kind='att' AND ref_id IN (?, ?)", (A1, A2))[0][0]
check(sha == 1 and T2 in tsearch(Bo, "wolkenkratzer"), "#1820: the same content shares its text (same sha256)")

# HEIC (not readable with the tools in the image): no mark
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 200
Bo.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("photo.heic", HEIC, "image/heic")})
AH = dbx("SELECT id FROM attachments WHERE task_id=? AND name='photo.heic'", (T2,))
st = settled("att", AH[0][0]) if AH else None
check(AH and (st is None or st[0] in ("skip", "error")), f"#1820: a HEIC file gets no text mark ({st})")
# a plain text file is not queued (not a recognition type)
Bo.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("note.txt", b"Wolkenkratzer as text", "text/plain")})
AT = dbx("SELECT id FROM attachments WHERE task_id=? AND name='note.txt'", (T2,))
check(AT and ft("att", AT[0][0]) is None, "#1820: other file types are not queued")

# ---------------------------------------------------------------------------------------------------------- organisation: image (OCR)
LO = Bo.post(B + "/api/lists", json={"name": "Team things", "org_id": ORG}).json()["id"]
TO = Bo.post(B + "/api/tasks", json={"title": "Harbour", "list_id": LO}).json()["id"]
PNG = text_png(["HAFENKRAN BERNSTEIN", "LIEFERUNG MONTAG"])
Bo.post(B + f"/api/tasks/{TO}/attachments", files={"file": ("crane.png", PNG, "image/png")})
AO = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TO,))[0][0]
st = settled("att", AO, 240)
if OCR:
    check(st and st[0] == "found" and st[2] == "ocr", f"#1820: the image is recognised with OCR ({st})")
    seen = (dbx("SELECT text FROM file_text WHERE kind='att' AND ref_id=?", (AO,)) or [[""]])[0][0][:120]
    check(TO in tsearch(Bo, "bernstein"), f"#1820: the task is found by the image's text (read: {seen!r})")
    check(TO in tsearch(Bo, "hafenkran lieferung"), "#1820: words of two lines of the image")
    check(TO not in tsearch(Zo, "bernstein") and TO not in tsearch(Er, "bernstein"), "#1820: another organisation / a person without one finds nothing")
    tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "attachments:read"]}).json()
    api = {"Authorization": "Bearer " + (tok.get("token") or tok.get("value") or "")}
    j = requests.get(B + f"/api/v1/attachments/{AO}/text", headers=api).json()
    check(j.get("source") == "ocr" and "BERNSTEIN" in (j.get("text") or "").upper(), f"#1820: agents get the recognised text of an image (source ocr) {str(j)[:200]}")
else:
    check(st and st[0] in ("error", "skip"), f"#1820: without Tesseract the image gets no mark and no 500 ({st})")

# ---------------------------------------------------------------------------------------------------------- Ablage + project files
r = Bo.post(B + "/api/files/upload", data={"space": f"org:{ORG}", "replace": "0"}, files={"file": ("contract.pdf", text_pdf(["Zitronenbaum Pachtvertrag"]), "application/pdf")})
check(r.status_code == 201, f"#1820 Ablage upload {r.status_code} {r.text[:120]}")
NF = r.json()["items"][0]["id"] if r.ok else 0
st = settled("fs", NF)
check(st and st[0] == "found", f"#1820: an Ablage file is recognised ({st})")
j = fsearch(Bo, "zitronenbaum").json()
check(any(x["id"] == NF and x["hit"] == "text" for x in j.get("items", [])), f"#1820: the Ablage search finds the file by its text {str(j)[:200]}")
j = fsearch(Bo, "contract").json()
check(any(x["id"] == NF and x["hit"] == "name" for x in j.get("items", [])), "#1820: the Ablage search finds a file by its name")
check(any(x["id"] == NF for x in fsearch(A, "zitronenbaum", f"org:{ORG}").json().get("items", [])), "#1820: the space filter keeps the organisation's file")
check(not any(x["id"] == NF for x in fsearch(Bo, "zitronenbaum", "private").json().get("items", [])), "#1820: the private space does not show it")
check(not fsearch(Zo, "zitronenbaum").json().get("items") and not fsearch(Er, "zitronenbaum").json().get("items"),
      "#1820: the Ablage search shows nothing of another organisation / to a person without it")
check(fsearch(Zo, "zitronenbaum", f"org:{ORG}").status_code == 404, "#1820: a foreign organisation's space: 404")
check(Bo.get(B + "/api/files/search").status_code == 400, "#1820: an empty query: 400")


def v1(s, path, scopes=("read", "files:read")):
    tok = s.post(B + "/api/me/tokens", json={"name": "s", "scopes": list(scopes)}).json()
    return requests.get(B + "/api/v1" + path, headers={"Authorization": "Bearer " + (tok.get("token") or tok.get("value") or "")})


j = v1(Bo, "/files/search?q=zitronenbaum").json()
check(any(x["id"] == NF and x["hit"] == "text" and x.get("url") for x in j.get("data", [])), f"#1820 API: GET /files/search finds the file by its text {str(j)[:200]}")
check(v1(Zo, "/files/search?q=zitronenbaum").json().get("data") == [], "#1820 API: another organisation finds nothing")
check(v1(Bo, "/files/search").status_code == 400, "#1820 API: q is needed")

P = Bo.post(B + "/api/lists", json={"name": "Site", "kind": "project", "org_id": ORG}).json()["id"]
r = Bo.post(B + f"/api/lists/{P}/files", files={"file": ("plan.pdf", text_pdf(["Kirschgarten Bauabschnitt"]), "application/pdf")})
check(r.ok, f"#1820 project file uploaded {r.status_code} {r.text[:120]}")
PF = dbx("SELECT id FROM list_files WHERE list_id=? ORDER BY id DESC LIMIT 1", (P,))[0][0]
st = settled("list", PF)
check(st and st[0] == "found", f"#1820: a project file is recognised ({st})")
j = fsearch(Bo, "kirschgarten").json()
check(any(x["id"] == PF and x["hit"] == "text" and x["list_id"] == P for x in j.get("list_files", [])), f"#1820: the Ablage search lists the project file {str(j)[:200]}")
check(not fsearch(Zo, "kirschgarten").json().get("list_files"), "#1820: another organisation does not see the project file")

# ---------------------------------------------------------------------------------------------------------- delete = clean up
check(Bo.delete(B + f"/api/attachments/{A2}").ok, "#1820: a task file deleted")
check(ft("att", A2) is None, "#1820: its text row goes with it")
check(not dbx("SELECT 1 FROM file_words w WHERE NOT EXISTS (SELECT 1 FROM file_text f WHERE f.id=w.ft_id)"), "#1820: no index words without their row")
check(Bo.delete(B + f"/api/list-files/{PF}").ok and ft("list", PF) is None, "#1820: a deleted project file takes its text row")
check(Bo.delete(B + f"/api/files/nodes/{NF}").ok, "#1820: an Ablage file into the trash")
check(not any(x["id"] == NF for x in fsearch(Bo, "zitronenbaum").json().get("items", [])), "#1820: a file in the trash is not found")
check(ft("fs", NF) is not None, "#1820: the trash keeps the text (restore brings it back)")
check(Bo.delete(B + f"/api/files/nodes/{NF}?purge=1").ok and ft("fs", NF) is None, "#1820: deleted for good: the text row goes")

# ---------------------------------------------------------------------------------------------------------- the catch-up
T3 = Bo.post(B + "/api/tasks", json={"title": "Old file", "list_id": L1}).json()["id"]
Bo.post(B + f"/api/tasks/{T3}/attachments", files={"file": ("old.pdf", text_pdf(["Pflaumenkuchen Rezept"]), "application/pdf")})
A3 = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T3,))[0][0]
settled("att", A3)
dbx("DELETE FROM file_text WHERE kind='att' AND ref_id=?", (A3,), write=True)  # as if stored before 2.61.0
dbx("DELETE FROM settings WHERE key='ts_backfill'", write=True)
check(T3 not in tsearch(Bo, "pflaumenkuchen"), "#1820 catch-up: without its row the file is not found")
st = until(lambda: (ft("att", A3) or ("",))[0] == "found" and ft("att", A3), 180)
check(st and st[0] == "found", f"#1820: the catch-up recognises a file stored before ({st})")
check(T3 in tsearch(Bo, "pflaumenkuchen"), "#1820: after the catch-up the task is found")
bf = dbx("SELECT value FROM settings WHERE key='ts_backfill'")
check(bf and str(A3) in bf[0][0], f"#1820: the catch-up keeps its position ({bf})")

# 2.61.0 review: a file whose workspace changed (list moved between organisations / private) is recognised again under
# the new one - simulated by a stale ws on the row; the app restarts with a fast sweep (data and sessions kept)
dbx("UPDATE file_text SET ws='u999999' WHERE kind='att' AND ref_id=?", (A3,), write=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_FILE_OCR_REHOME_S=1"),
                   capture_output=True, text=True)
check(r.returncode == 0, "restart with a fast workspace sweep " + (r.stdout + r.stderr)[-300:])
row = until(lambda: (lambda x: x and x[0][0] != "u999999" and x[0][1] == "found" and x[0])(
    dbx("SELECT ws, state FROM file_text WHERE kind='att' AND ref_id=?", (A3,))), 180)
check(bool(row), f"#1820: the sweep re-queues the file under its real workspace and it is found again ({row})")
check(T3 in tsearch(Bo, "pflaumenkuchen"), "#1820: after the sweep the task is found again")

print(f"{OKS[0]} checks ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
