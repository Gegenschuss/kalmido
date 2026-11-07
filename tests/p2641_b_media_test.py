#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.641.0 part B API test (#4769): the approval (video sign-offs) also for images (JPG, PNG, WebP) and PDFs of the file
store, comments at a point. Own container (start.sh, workspaces). Invented companies, people and files only.
tenant-matrix: video
freelancer-matrix: videos
 - an upload (multipart "file") at a task: lands in the folder "Approvals" of the organisation's file store, kind image, the
   version names its file; the bytes come back through /api/videos/<id>/versions/<v>/file as image/png, sandboxed, nosniff
 - the type by CONTENT: SVG, HTML named .png, an empty file: 400, nothing stored; WebP and JPEG by their first bytes
 - comments at a point {x, y}: stored, numbered (mark 1, 2) per version; a point outside 0..1, a timecode or a page on an
   image: 400; a PDF from the file store (file_id) at a project: {page: 2, x, y}, {page} alone; a point without a page: 400
 - a new version (an upload / a file of the store) = v2; v1 keeps its comments and its own bytes (file_no pinned)
 - rights: another organisation's person: 404 on the review, the list, the bytes; a member who sees the task but NOT the
   file: no review (404, not listed) until the file is shared with her (then 200, the bytes too); a file of another
   workspace or a file the person cannot see as a version: 409 / 404; no customer link (409) and no move (409) with files
 - the agents' API: an agent with the project shared but not the file: 404; the file shared: the review with kind, pos and
   mark, a comment at {page, x, y} (201), the bytes through /api/v1/...; a video review stays as before (at_sec)
 - export: the page and the point's number instead of a timecode
 - a person without an organisation: upload at a private task (JPEG), comment at a point, the bytes; a stranger 404
usage: p2641_b_media_test.py <datadir>      (P2641B_NOSTART=1: a running server, no start.sh)"""
import base64
import os
import struct
import subprocess
import sys
import time
import zlib

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
import kt  # noqa: E402
from kt import check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,videos"
V = "/api/videos"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def png(w=2, h=1, rgb=(200, 30, 30)):
    """A real small PNG (no library)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def pdf2():
    """A plain two-page PDF."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()


JPG = base64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
                       "wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")
WEBP = b"RIFF" + struct.pack("<I", 26) + b"WEBPVP8L" + struct.pack("<I", 14) + b"\x2f\x00\x00\x00\x00\x07\x00\x00\x00\x00\x00\x00\x00\x00"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
PNG1, PNG2, PDF = png(), png(3, 2, (10, 120, 200)), pdf2()


def up(s, place, name, data, mime="application/octet-stream", vid=None, title=None):
    files = {"file": (name, data, mime)}
    form = {} if vid else {k: str(v) for k, v in place.items()}
    if title:
        form["title"] = title
    return s.post(B + (f"{V}/{vid}/versions" if vid else V), files=files, data=form)


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok, "X-Requested-With": "kalmido"})
    return s


if os.environ.get("P2641B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE, BOB, CAROL = (s.get(B + "/api/state").json()["me"]["id"] for s in (A, Bo, Ca))
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
L = A.post(B + "/api/lists", json={"name": "Logo Bäckerei Sonnig", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Logo Entwurf", "list_id": L}).json()["id"]
check(Bo.get(B + f"/api/tasks/{T}").ok, "bob sees the task (shared project)")

# ---- an upload at a task: an image in the folder "Approvals" of the organisation's file store
n_nodes = sql("SELECT COUNT(*) FROM fs_nodes")[0][0]
r = up(A, {"task_id": T}, "logo-v1.png", PNG1, "image/png", title="Logo")
if not r.ok:
    app_log()
check(r.ok, f"upload of a PNG at a task {r.status_code} {r.text[:300]}")
R = r.json() if r.ok else {}
V1 = (R.get("versions") or [{}])[0]
check(R.get("kind") == "image" and V1.get("kind") == "image" and V1.get("mime") == "image/png" and V1.get("file_id"),
      f"the review and its version are an image with its file {R.get('kind')} {V1}")
check(V1.get("embed") is None and V1.get("timed") is False, f"no player, no timecode {V1}")
FID1 = V1.get("file_id")
row = sql("SELECT n.org_id, p.name, n.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (FID1,))
check(row and row[0][0] == ORG and row[0][1] == "Approvals" and row[0][2] == "logo-v1.png",
      f"the file lies in the organisation's folder Approvals {row}")
r = A.get(B + V1.get("content", "/x"))
check(r.ok and r.headers.get("Content-Type", "").startswith("image/png") and r.content == PNG1, f"the bytes of v1 {r.status_code} {r.headers.get('Content-Type')}")
check("sandbox" in r.headers.get("Content-Security-Policy", "") and r.headers.get("X-Content-Type-Options") == "nosniff",
      f"served sandboxed, nosniff {dict(r.headers)}")
check(V1.get("content") == f"/api/videos/{R.get('id')}/versions/{V1.get('id')}/file", f"the route of the bytes {V1.get('content')}")
check(Ca.get(B + f"/api/videos/{R.get('id')}/versions/{V1.get('id')}/file").status_code == 404, "another organisation: the bytes 404")
r = A.get(B + V1.get("content", "/x") + "?dl=1")
check(r.ok and r.headers.get("Content-Disposition", "").startswith("attachment"), f"?dl=1 = a download {r.headers.get('Content-Disposition')}")

# ---- the type by content (not the name, not the browser's type)
for name, data, mime, what in (("bild.svg", SVG, "image/svg+xml", "an SVG"), ("tarn.png", b"<html><script>alert(1)</script></html>", "image/png", "HTML named .png"),
                               ("leer.png", b"", "image/png", "an empty file")):
    r = up(A, {"task_id": T}, name, data, mime)
    check(r.status_code == 400, f"{what} is refused {r.status_code} {r.text[:200]}")
check(sql("SELECT COUNT(*) FROM fs_nodes WHERE kind='file'")[0][0] == 1, "nothing refused was stored")
r = up(A, {"task_id": T}, "foto.webp", WEBP, "application/octet-stream")
check(r.ok and r.json()["versions"][0]["mime"] == "image/webp", f"WebP by its first bytes {r.status_code} {r.text[:200]}")
RW = r.json()["id"] if r.ok else None

# ---- comments at a point
RID = R.get("id")
c1 = A.post(B + f"{V}/{RID}/comments", json={"body": "Schrift größer", "pos": {"x": 0.25, "y": 0.5}})
c2 = A.post(B + f"{V}/{RID}/comments", json={"body": "Farbe wärmer", "pos": {"x": 0.9, "y": 0.1}})
c3 = A.post(B + f"{V}/{RID}/comments", json={"body": "Allgemein gut"})
check(c1.ok and c2.ok and c3.ok, f"three comments (two at a point) {c1.status_code} {c2.status_code} {c3.status_code} {c1.text[:200]}")
cm = {x["body"]: x for x in (c3.json().get("comments") or [])} if c3.ok else {}
check(cm.get("Schrift größer", {}).get("pos") == {"x": 0.25, "y": 0.5} and cm["Schrift größer"].get("mark") == 1,
      f"the first point: pos and number 1 {cm.get('Schrift größer')}")
check(cm.get("Farbe wärmer", {}).get("mark") == 2 and cm.get("Allgemein gut", {}).get("pos") is None and cm["Allgemein gut"].get("mark") is None,
      f"the second point number 2, the general comment none {cm.get('Farbe wärmer')} {cm.get('Allgemein gut')}")
db = sql("SELECT pos_x, pos_y, page, at_sec FROM video_comments WHERE id=?", (c1.json().get("comment_id"),))
check(db and abs(db[0][0] - 0.25) < 1e-6 and abs(db[0][1] - 0.5) < 1e-6 and db[0][2] is None and db[0][3] is None, f"stored as x / y {db}")
for b, what in (({"pos": {"x": 1.5, "y": 0.2}}, "x outside 0..1"), ({"pos": {"x": 0.5}}, "x without y"), ({"at_sec": 12}, "a timecode"),
                ({"pos": {"page": 1, "x": 0.1, "y": 0.1}}, "a page"), ({"pos": {"x": True, "y": 0.1}}, "a boolean"), ({"pos": "0.1,0.2"}, "a text")):
    r = A.post(B + f"{V}/{RID}/comments", json={"body": "falsch", **b})
    check(r.status_code == 400, f"on an image {what} is refused {r.status_code} {r.text[:200]}")
reply = A.post(B + f"{V}/{RID}/comments", json={"body": "Erledige ich", "parent_id": c1.json().get("comment_id")})
check(reply.ok and next((x for x in reply.json()["comments"] if x["id"] == reply.json()["comment_id"]), {}).get("pos") is None,
      f"an answer carries no point of its own {reply.status_code}")

# ---- a PDF from the file store at the project
r = A.post(B + "/api/files/upload", files={"file": ("entwurf.pdf", PDF, "application/pdf")}, data={"space": f"org:{ORG}"})
check(r.status_code == 201, f"a PDF in the organisation's file store {r.status_code} {r.text[:200]}")
FPDF = r.json()["items"][0]["id"] if r.status_code == 201 else 0
r = A.post(B + V, json={"list_id": L, "file_id": FPDF})
check(r.ok and r.json().get("kind") == "pdf" and r.json().get("title") == "entwurf.pdf", f"a review of a file of the store {r.status_code} {r.text[:200]}")
RP = r.json().get("id") if r.ok else 0
p1 = A.post(B + f"{V}/{RP}/comments", json={"body": "Seite 2 oben links", "pos": {"page": 2, "x": 0.1, "y": 0.2}})
p2 = A.post(B + f"{V}/{RP}/comments", json={"body": "Seite 1 ganz", "pos": {"page": 1}})
check(p1.ok and p2.ok, f"PDF comments at page 2 + point and at page 1 {p1.status_code} {p2.status_code} {p1.text[:200]}")
pc = {x["body"]: x for x in (p2.json().get("comments") or [])} if p2.ok else {}
check(pc.get("Seite 2 oben links", {}).get("pos") == {"page": 2, "x": 0.1, "y": 0.2} and pc["Seite 2 oben links"].get("page") == 2
      and pc["Seite 2 oben links"].get("mark") == 1, f"page 2 with its point {pc.get('Seite 2 oben links')}")
check(pc.get("Seite 1 ganz", {}).get("pos") == {"page": 1} and pc["Seite 1 ganz"].get("mark") is None, f"a page alone {pc.get('Seite 1 ganz')}")
for b, what in (({"pos": {"x": 0.5, "y": 0.5}}, "a point without a page"), ({"pos": {"page": 0}}, "page 0"), ({"pos": {"page": 1.5}}, "page 1.5"),
                ({"pos": {"t": 3}}, "a timecode")):
    r = A.post(B + f"{V}/{RP}/comments", json={"body": "falsch", **b})
    check(r.status_code == 400, f"on a PDF {what} is refused {r.status_code} {r.text[:200]}")
pv = A.get(B + f"{V}/{RP}").json()["versions"][0]
r = A.get(B + pv["content"])
check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.headers.get("Content-Security-Policy") == "sandbox",
      f"the PDF's bytes, sandboxed {r.status_code} {r.headers.get('Content-Type')} {r.headers.get('Content-Security-Policy')}")
ex = A.get(B + f"{V}/{RP}/export")
check(ex.ok and "Page 2 · 1" in ex.text and "Page 1" in ex.text, f"the export names page and point {ex.text[:400]}")

# ---- a new version keeps the old comments and the old bytes
r = up(A, {}, "logo-v2.png", PNG2, "image/png", vid=RID)
check(r.ok and r.json().get("version") == 2, f"an upload as v2 {r.status_code} {r.text[:200]}")
R2 = r.json() if r.ok else {}
V2 = next((v for v in R2.get("versions", []) if v["n"] == 2), {})
old = [x for x in R2.get("comments", []) if x["version_id"] == V1.get("id")]
check(len(old) == 4 and all(x["version_id"] == V1.get("id") for x in old), f"v1 keeps its comments {len(old)}")
check(A.get(B + V1["content"]).content == PNG1 and A.get(B + V2.get("content", "/x")).content == PNG2, "v1 and v2 each show their own bytes")
c = A.post(B + f"{V}/{RID}/comments", json={"body": "Neu: besser", "pos": {"x": 0.5, "y": 0.5}})
check(c.ok and next(x for x in c.json()["comments"] if x["id"] == c.json()["comment_id"])["mark"] == 1, "v2's first point is number 1 again")
# the same file of the store as a new version: its version number at that time stays (file_no pinned)
r = A.post(B + f"/api/files/nodes/{FID1}/versions", files={"file": ("logo-v1.png", PNG2, "image/png")})
check(r.ok, f"a new version of the file in the store {r.status_code} {r.text[:200]}")
check(A.get(B + V1["content"]).content == PNG1, "the approval's v1 still shows the file as it was")

# ---- rights
check(Ca.get(B + f"{V}/{RID}").status_code == 404 and Ca.get(B + V1["content"]).status_code == 404, "another organisation: 404 on the review and the bytes")
check((Ca.get(B + f"{V}?task_id={T}").json().get("reviews") or []) == [], "another organisation: no review listed")
check(Bo.get(B + f"{V}/{RID}").status_code == 404, "bob sees the task but not the file: no review (404)")
check(RID not in [x["id"] for x in Bo.get(B + f"{V}?task_id={T}").json().get("reviews", [])], "bob: not listed at the task")
check(Bo.get(B + V1["content"]).status_code == 404, "bob: no bytes")
check(Bo.post(B + f"{V}/{RID}/comments", json={"body": "x"}).status_code == 404, "bob: no comment")
fold = sql("SELECT parent_id FROM fs_nodes WHERE id=?", (FID1,))[0][0]
r = A.post(B + f"/api/files/nodes/{fold}/shares", json={"user_id": BOB, "role": "view"})
check(r.ok, f"alice shares the folder Approvals with bob {r.status_code} {r.text[:200]}")
check(Bo.get(B + f"{V}/{RID}").ok and Bo.get(B + V1["content"]).ok, "the folder shared: bob sees the review and the bytes")
check(Bo.get(B + f"{V}/{RP}").status_code == 404, "bob still does not see the PDF review (its file is not shared with him)")
# a file of another workspace, a file the person cannot see
fc = Ca.post(B + "/api/files/upload", files={"file": ("fremd.png", PNG1, "image/png")}, data={"space": f"org:{ORG2}"})
FC = fc.json()["items"][0]["id"] if fc.status_code == 201 else 0
check(A.post(B + f"{V}/{RID}/versions", json={"file_id": FC}).status_code == 404, "alice: another organisation's file is not there for her (404)")
fp = A.post(B + "/api/files/upload", files={"file": ("privat.png", PNG1, "image/png")}, data={"space": "private"})
FP = fp.json()["items"][0]["id"] if fp.status_code == 201 else 0
r = A.post(B + f"{V}/{RID}/versions", json={"file_id": FP})
check(r.status_code == 409, f"a file of her private space into the organisation's review: 409 {r.status_code} {r.text[:200]}")
r = A.post(B + f"{V}/{RID}/versions", json={"file_id": FPDF})
check(r.ok and r.json()["versions"][-1]["kind"] == "pdf", f"a PDF of the same workspace as a new version {r.status_code}")
check(A.post(B + f"{V}/{RID}/signoff", json={"expires": None}).status_code == 409, "no customer link for images / PDFs")
r = A.post(B + f"{V}/{RID}/move-space", json={"to": "private", "dry": 1})
check(r.status_code == 409, f"no move to another workspace with files {r.status_code} {r.text[:200]}")
# a video review stays as before
rv = A.post(B + V, json={"task_id": T, "url": "https://vimeo.com/123456789"})
check(rv.ok and rv.json().get("kind") == "video", f"a video link as before {rv.status_code}")
c = A.post(B + f"{V}/{rv.json()['id']}/comments", json={"body": "Schnitt", "at_sec": 12})
check(c.ok and next(x for x in c.json()["comments"] if x["id"] == c.json()["comment_id"])["pos"] == {"t": 12.0}, "a video comment: at_sec and pos {t}")
check(A.post(B + f"{V}/{rv.json()['id']}/comments", json={"body": "x", "pos": {"x": 0.1, "y": 0.1}}).status_code == 400, "a point on a video: 400")

# ---- the agents' API
ra = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "druckbot", "display_name": "Druckbot", "org_id": ORG})
check(ra.status_code in (200, 201), f"an agent {ra.status_code} {ra.text[:200]}")
AG, ag = ra.json()["id"], bearer(ra.json()["token"])
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
check(ag.get(B + f"/api/v1/videos/{RP}").status_code == 404, "the agent: project shared, file not: 404")
check(RP not in [x["id"] for x in ag.get(B + f"/api/v1/videos?list_id={L}").json().get("data", [])], "the agent: not listed")
r = A.post(B + f"/api/files/nodes/{FPDF}/shares", json={"agent_id": AG, "role": "view"})
check(r.ok, f"the PDF shared with the agent {r.status_code} {r.text[:200]}")
r = ag.get(B + f"/api/v1/videos/{RP}")
check(r.ok and r.json().get("kind") == "pdf" and r.json()["versions"][0].get("file_id") == FPDF, f"the agent reads the PDF review {r.status_code} {r.text[:300]}")
ac = (r.json().get("comments") or []) if r.ok else []
check(any(x.get("pos") == {"page": 2, "x": 0.1, "y": 0.2} and x.get("mark") == 1 for x in ac), f"the agent sees pos and mark {ac[:2]}")
r = ag.post(B + f"/api/v1/videos/{RP}/comments", json={"body": "Rand zu schmal", "pos": {"page": 2, "x": 0.8, "y": 0.9}})
check(r.status_code == 201 and r.json()["comment"]["pos"] == {"page": 2, "x": 0.8, "y": 0.9} and r.json()["comment"]["mark"] == 2,
      f"the agent comments at page 2 + point {r.status_code} {r.text[:300]}")
r = ag.get(B + f"/api/v1/videos/{RP}/versions/{pv['id']}/file")
check(r.ok and r.content == PDF, f"the agent reads the PDF's bytes {r.status_code}")
web = [ag.get(B + f"{V}/{RP}").status_code, ag.get(B + f"/api/videos/{RP}/versions/{pv['id']}/file").status_code]
check(all(x in (401, 403, 404) for x in web), f"the app's routes stay closed to agents {web}")
check(ag.get(B + f"/api/v1/videos/{RID}").status_code == 404, "the agent: the image review (its folder not shared) 404")

# ---- a person without an organisation
FRI, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes Projekt"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Flyer", "list_id": FL}).json()["id"]
r = up(Fr, {"task_id": FT}, "flyer.jpg", JPG, "image/jpeg")
check(r.ok and r.json().get("kind") == "image" and r.json()["versions"][0]["mime"] == "image/jpeg", f"frida: a JPEG at her private task {r.status_code} {r.text[:300]}")
FR = r.json() if r.ok else {"id": 0, "versions": [{"content": "/x"}]}
check(sql("SELECT org_id FROM fs_nodes WHERE id=?", (FR["versions"][0].get("file_id"),)) == [(None,)], "frida: the file in her own file store")
c = Fr.post(B + f"{V}/{FR['id']}/comments", json={"body": "Bild heller", "pos": {"x": 0.3, "y": 0.3}})
check(c.ok and c.json()["comments"][0]["mark"] == 1, f"frida: a comment at a point {c.status_code}")
check(Fr.get(B + FR["versions"][0]["content"]).ok, "frida: the bytes")
check(Ca.get(B + f"{V}/{FR['id']}").status_code == 404 and Ca.get(B + FR["versions"][0]["content"]).status_code == 404, "a stranger: 404")
check(A.get(B + f"{V}/{FR['id']}").status_code == 404, "the instance admin does not see frida's private review")
if RW:
    check(A.delete(B + f"{V}/{RW}").ok, "the WebP review to the trash")

sys.exit(kt.done("p2641_b_media"))
