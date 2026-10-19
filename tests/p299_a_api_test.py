#!/usr/bin/env python3
"""2.99.0 A (#2182) API tests: files of knowledge pages and the ZIP import / export with PDFs and pictures (own container,
org encryption on). The ZIP is built here like a SilverBullet export (pages in folders, pictures in _attachments/, a PDF
next to its page; invented names and contents only).
 - import: pages + files; the type from the content (a PNG named .pdf and a program are skipped with their reason, also
   system files); [[file.pdf]], ![[_attachments/pic.png]], ![](../_attachments/pic.png), [label](file.pdf) and URL-encoded
   names point at the stored file; a file linked by two pages is stored once (the first page's, no copy); a file nobody
   links lands on "Imported files" of its folder; a too large file is skipped; the old field skipped keeps the names
 - files: the right bytes and type, SVG cleaned (no script / event attribute) and served in a sandbox, sealed at rest;
   upload to a page (type checked by content), delete + Undo, the page's trash hides its files, Undo brings them back;
   the Undo of an import (trash {ids, files})
 - export: the files under _attachments/<page>/, the links as [[_attachments/…]]; a re-import gives the same structure
 - rights (tenant-matrix: wiki): a member of the organisation reads and uploads, another organisation 404 (read, upload,
   delete, trash); a person without an organisation (freelancer-matrix: wiki) imports into the own private space, nobody
   else reaches its files; a locked space (encrypted in the browser) takes no file and cannot be locked while files exist
usage: p299_a_api_test.py <datadir>      (P299A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import re
import subprocess
import sys
import time
import zipfile

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


# ---- the files of the archive (made here)
def picture(fmt):
    try:
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (2, 2), (120, 60, 200)).save(b, fmt)
        return b.getvalue()
    except ImportError:  # without Pillow: the smallest valid files of the type
        return {"PNG": base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="),
                "JPEG": base64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////"
                                         "////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="),
                "WEBP": b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"}[fmt]


PNG, JPG, WEBP = picture("PNG"), picture("JPEG"), picture("WEBP")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
SVGX = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10" '
        b'height="10" onload="alert(1)"><script>alert(2)</script><a xlink:href="javascript:alert(3)"><rect width="10" height="10" '
        b'fill="#7c3aed"/></a><image href="https://example.com/x.png" width="1" height="1"/></svg>')
PLAN = ("---\ntags: [projekt]\n---\n# Plan\n\n![[_attachments/skizze.png]]\n\nSiehe [[Vertrag.pdf]] und [Vertrag als Link](Vertrag.pdf), "
        "das Logo ![[logo.svg]] und [[Projekte/Notizen]].\n")
NOTES = "Noch einmal: ![Skizze](../_attachments/skizze.png) und ![x](bild%20mit%20leer.webp)\n"


def sb_zip(big=False):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Projekte/Plan.md", PLAN)
        z.writestr("Projekte/Notizen.md", NOTES)
        z.writestr("Projekte/Vertrag.pdf", PDF)
        z.writestr("_attachments/skizze.png", PNG)
        z.writestr("Projekte/extra.jpg", JPG)
        z.writestr("Projekte/bild mit leer.webp", WEBP)
        z.writestr("logo.svg", SVGX)
        z.writestr("boese.pdf", PNG)  # a picture that calls itself a PDF
        z.writestr("tool.exe", b"MZ\x90\x00" + b"\x00" * 60)
        z.writestr("__MACOSX/Projekte/._Plan.md", b"\x00\x05\x16\x07")
        if big:
            z.writestr("Projekte/riesig.pdf", b"%PDF-1.4\n" + b"0" * (26 * 1024 * 1024))
    return b.getvalue()


def imp(s, space, raw, **params):
    return s.post(B + "/api/wiki/import", params={"space": space, **params}, files={"file": ("export.zip", raw, "application/zip")})


def tree(s, space):
    """{page path: sorted file names} of a space."""
    out = {}
    for p in s.get(B + "/api/wiki", params={"space": space}).json()["pages"]:
        out[p["path"]] = sorted(f["name"] for f in s.get(B + f"/api/wiki/pages/{p['id']}").json().get("files", []))
    return out


if os.environ.get("P299A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,wiki"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"
FID, Fr = freelancer(B, A)
_, Fo = freelancer(B, A, "fiona")

# ---------------------------------------------------------------- import
r = imp(A, SP, sb_zip(big=True))
check(r.ok, "#2182: the import " + r.text[:300])
J = r.json()
why = {s["name"]: s["reason"] for s in J.get("skipped_detail", [])}
check("boese.pdf" in why and "does not match" in why["boese.pdf"], f"#2182: a PNG named .pdf is skipped by its content {why}")
check("tool.exe" in why and "Only PDF" in why["tool.exe"], f"#2182: a program is skipped with its reason {why}")
check(any("__MACOSX" in n for n in why), f"#2182: system files are skipped {why}")
check("Projekte/riesig.pdf" in why and "25 MB" in why["Projekte/riesig.pdf"], f"#2182: a file above 25 MB is skipped {why}")
check({"boese.pdf", "tool.exe"} <= set(J.get("skipped", [])) and all(isinstance(x, str) for x in J["skipped"]),
      "#2182: skipped stays the list of names (older callers)")
check(J.get("files_n") == 5 and len(J.get("files", [])) == 5, f"#2182: five files taken over {J.get('files_n')} {J.get('files')}")
pages = {p["path"]: p["id"] for p in A.get(B + "/api/wiki", params={"space": SP}).json()["pages"]}
check({"Projekte/Plan", "Projekte/Notizen", "Projekte/Imported files"} <= set(pages) and len(J["created"]) == 3,
      f"#2182: the pages and the page of the unlinked files {sorted(pages)}")
plan = A.get(B + f"/api/wiki/pages/{pages['Projekte/Plan']}").json()
pf = {f["name"]: f for f in plan.get("files", [])}
check(set(pf) == {"skizze.png", "Vertrag.pdf", "logo.svg"}, f"#2182: the files of the page that links them first {sorted(pf)}")
sk, vt = pf.get("skizze.png", {}), pf.get("Vertrag.pdf", {})
check(f"![skizze.png](/api/wiki/files/{sk.get('id')}/skizze.png)" in plan["body"], "#2182: ![[_attachments/pic.png]] -> the stored picture " + plan["body"])
check(f"[Vertrag.pdf](/api/wiki/files/{vt.get('id')}/Vertrag.pdf)" in plan["body"]
      and f"[Vertrag als Link](/api/wiki/files/{vt.get('id')}/Vertrag.pdf)" in plan["body"], "#2182: [[file.pdf]] and [label](file.pdf) -> the stored PDF")
check("[[Projekte/Notizen]]" in plan["body"] and plan["attrs"].get("tags") == ["projekt"], "#2182: page links and the frontmatter stay")
notes = A.get(B + f"/api/wiki/pages/{pages['Projekte/Notizen']}").json()
nf = {f["name"]: f for f in notes.get("files", [])}
check(f"![Skizze](/api/wiki/files/{sk.get('id')}/skizze.png)" in notes["body"], "#2182: a second page links the same file (no copy) " + notes["body"])
check(set(nf) == {"bild mit leer.webp"} and f"/api/wiki/files/{nf.get('bild mit leer.webp', {}).get('id')}/bild%20mit%20leer.webp" in notes["body"],
      f"#2182: a URL-encoded relative name is found {sorted(nf)} {notes['body']}")
imp_pg = A.get(B + f"/api/wiki/pages/{pages['Projekte/Imported files']}").json()
check([f["name"] for f in imp_pg.get("files", [])] == ["extra.jpg"] and "/extra.jpg)" in imp_pg["body"],
      f"#2182: the unlinked file is on 'Imported files' of its folder {imp_pg.get('files')} {imp_pg['body']}")
check(sql("SELECT COUNT(*) FROM wiki_files WHERE name='skizze.png'")[0][0] == 1, "#2182: a file linked twice is stored once")

# ---------------------------------------------------------------- the files themselves
r = Bo.get(B + vt["url"])
check(r.ok and r.content == PDF and r.headers.get("Content-Type", "").startswith("application/pdf") and "sandbox" in r.headers.get("Content-Security-Policy", ""),
      f"#2182: a member reads the PDF (same bytes, its type, sandbox) {r.status_code} {r.headers.get('Content-Type')}")
r = Bo.get(B + sk["url"])
check(r.ok and r.content[:8] == b"\x89PNG\r\n\x1a\n" and r.headers.get("Content-Type") == "image/png", "#2182: the picture with its type")
r = Bo.get(B + f"/api/wiki/files/{sk.get('id')}")
check(r.ok, "#2182: the address without the name works as well")
r = Bo.get(B + pf.get("logo.svg", {}).get("url", "/x"))
check(r.ok and b"<script" not in r.content and b"onload" not in r.content and b"javascript:" not in r.content and b"example.com" not in r.content
      and b"<rect" in r.content and r.headers.get("Content-Type", "").startswith("image/svg+xml") and "sandbox" in r.headers.get("Content-Security-Policy", ""),
      f"#2182: the SVG cleaned, served in a sandbox {r.status_code} {r.content[:300]}")
row = sql("SELECT path, org_id, size FROM wiki_files WHERE id=?", (vt.get("id"),))[0]
check(row[1] == ORG and row[2] == len(PDF), "#2182: the file lies in the page's organisation")
try:
    with open(os.path.join(DATA, "attachments", row[0]), "rb") as fh:
        disk = fh.read()
    check(not disk.startswith(b"%PDF"), "#2182: the file is sealed at rest (org encryption)")
except OSError as e:  # the data folder of the container may not be readable from here
    print("note: stored file not readable here:", e)
r = A.get(B + "/api/admin/storage-check")
check(r.ok and not [x for x in r.json().get("problems", r.json().get("files", [])) if x.get("kind") == "wiki_file"], "#2182: the storage check knows the page files " + r.text[:200])

# ---------------------------------------------------------------- upload, delete, Undo, trash of the page
PID = pages["Projekte/Plan"]
r = Bo.post(B + f"/api/wiki/pages/{PID}/files", files=[("file", ("Angebot.pdf", PDF, "application/pdf")), ("file", ("foto.png", PNG, "image/png"))])
check(r.status_code == 201 and [f["name"] for f in r.json()["files"]] == ["Angebot.pdf", "foto.png"], "#2182: a member uploads to the page " + r.text[:200])
UP = [f["id"] for f in r.json().get("files", [])]
r = Bo.post(B + f"/api/wiki/pages/{PID}/files", files={"file": ("fake.png", b"just text", "image/png")})
check(r.status_code == 400 and "does not match" in r.json().get("error", ""), "#2182: the upload checks the content " + r.text[:200])
r = Bo.post(B + f"/api/wiki/pages/{PID}/files", files={"file": ("run.exe", b"MZ\x00\x00", "application/octet-stream")})
check(r.status_code == 400, "#2182: no programs on a page")
check(Ca.post(B + f"/api/wiki/pages/{PID}/files", files={"file": ("x.pdf", PDF, "application/pdf")}).status_code == 404, "#2182: another organisation cannot upload (404)")
check(Ca.get(B + vt["url"]).status_code == 404 and Ca.get(B + f"/api/wiki/files/{vt['id']}").status_code == 404, "#2182: another organisation cannot read (404)")
check(Ca.delete(B + f"/api/wiki/files/{vt['id']}").status_code == 404, "#2182: another organisation cannot delete (404)")
r = Ca.post(B + "/api/wiki/trash", json={"ids": [], "files": [vt["id"]]})
check(r.ok and r.json()["files"] == [] and r.json()["files_skipped"] == [vt["id"]] and Bo.get(B + vt["url"]).ok, "#2182: another organisation's trash call changes nothing")
r = Bo.delete(B + f"/api/wiki/files/{UP[0]}")
check(r.ok and Bo.get(B + f"/api/wiki/files/{UP[0]}").status_code == 404, "#2182: delete = to the trash")
r = Bo.post(B + "/api/wiki/restore", json={"ids": [], "files": [UP[0]]})
check(r.ok and r.json()["files"] == [UP[0]] and Bo.get(B + f"/api/wiki/files/{UP[0]}").ok, "#2182: Undo brings the file back")
check(Bo.delete(B + f"/api/wiki/pages/{PID}").ok and Bo.get(B + sk["url"]).status_code == 404, "#2182: a page in the trash hides its files")
check(Bo.post(B + "/api/wiki/restore", json={"ids": [PID]}).ok and Bo.get(B + sk["url"]).ok and len(Bo.get(B + f"/api/wiki/pages/{PID}").json()["files"]) == 5,
      "#2182: Undo of the page brings its files back")

# ---------------------------------------------------------------- export and re-import (round trip)
r = A.get(B + "/api/wiki/export", params={"space": SP})
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip"), "#2182: the export")
Z = zipfile.ZipFile(io.BytesIO(r.content))
names = set(Z.namelist())
check({"Projekte/Plan.md", "_attachments/Projekte/Plan/skizze.png", "_attachments/Projekte/Plan/Vertrag.pdf", "_attachments/Projekte/Plan/logo.svg",
       "_attachments/Projekte/Notizen/bild mit leer.webp", "_attachments/Projekte/Imported files/extra.jpg"} <= names, f"#2182: the files in the ZIP {sorted(names)}")
check(Z.read("_attachments/Projekte/Plan/Vertrag.pdf") == PDF, "#2182: the exported PDF has its bytes")
eplan = Z.read("Projekte/Plan.md").decode()
check("![[_attachments/Projekte/Plan/skizze.png]]" in eplan and "[[_attachments/Projekte/Plan/Vertrag.pdf|Vertrag als Link]]" in eplan
      and "/api/wiki/files/" not in eplan, "#2182: the exported links are relative again " + eplan)
check("![[_attachments/Projekte/Plan/skizze.png]]" in Z.read("Projekte/Notizen.md").decode(), "#2182: the second page links the same exported file")
before = tree(A, SP)
r = imp(Fr, "private", r.content)
check(r.ok and not r.json().get("skipped"), "#2182: a person without an organisation imports the export " + r.text[:300])
after = tree(Fr, "private")
check(after == before, f"#2182: the re-import gives the same structure\n{before}\n{after}")
fp = {p["path"]: p["id"] for p in Fr.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}
ff = {f["name"]: f for f in Fr.get(B + f"/api/wiki/pages/{fp['Projekte/Plan']}").json()["files"]}
check(Fr.get(B + ff["Vertrag.pdf"]["url"]).content == PDF, "#2182: the freelancer reads its file")
check(Fo.get(B + ff["Vertrag.pdf"]["url"]).status_code == 404 and A.get(B + ff["Vertrag.pdf"]["url"]).status_code == 404,
      "#2182: nobody else reaches a private page's file (also not the instance admin)")
check(tuple(sql("SELECT org_id, owner_id FROM wiki_files WHERE id=?", (ff["Vertrag.pdf"]["id"],))[0]) == (None, FID), "#2182: a private file has no organisation")
r = Fr.post(B + f"/api/wiki/pages/{fp['Projekte/Plan']}/files", files={"file": ("privat.pdf", PDF, "application/pdf")})
check(r.status_code == 201, "#2182: the freelancer uploads to its own page " + r.text[:200])
r2 = imp(Fr, "private", sb_zip(), replace="1")
check(r2.ok and len(r2.json().get("updated", [])) >= 2, "#2182: replace=1 overwrites the pages " + r2.text[:200])

# ---------------------------------------------------------------- Undo of an import
r = imp(Ca, SP2, sb_zip())
check(r.ok and r.json()["files_n"] == 5, "#2182: another organisation imports into its own space " + r.text[:200])
U = r.json()
some = U["files"][0]
r = Ca.post(B + "/api/wiki/trash", json={"ids": U["created"], "files": U["files"]})
check(r.ok and sorted(r.json()["ids"]) == sorted(U["created"]) and Ca.get(B + f"/api/wiki/files/{some}").status_code == 404, "#2182: Undo of the import " + r.text[:200])
r = Ca.post(B + "/api/wiki/restore", json={"ids": U["created"], "files": U["files"]})
check(r.ok and Ca.get(B + f"/api/wiki/files/{some}").ok, "#2182: Redo of the import " + r.text[:200])

# ---------------------------------------------------------------- 2.96.0 move between spaces: the files go along
mp = {p["path"]: p["id"] for p in Ca.get(B + "/api/wiki", params={"space": SP2}).json()["pages"]}["Projekte/Plan"]
mf = Ca.get(B + f"/api/wiki/pages/{mp}").json()["files"]
before = {f["id"]: Ca.get(B + f["url"]).content for f in mf}
r = Ca.post(B + "/api/wiki/move-space", json={"pages": [mp], "space": SP2, "to": "private"})
check(r.ok and mf, "#2182: a page with files moves to the private space " + r.text[:200])
check(all(Ca.get(B + f["url"]).content == before[f["id"]] for f in mf), "#2182: its files are readable after the move")
check(all(tuple(x) == (None, CAROL) for x in sql(f"SELECT org_id, owner_id FROM wiki_files WHERE page_id={int(mp)}")),
      "#2182: the file rows follow the page (private, owner)")
r = Ca.post(B + "/api/wiki/move-space", json={"pages": [mp], "space": "private", "to": SP2})
check(r.ok and all(Ca.get(B + f["url"]).content == before[f["id"]] for f in mf), "#2182: and back into the organisation " + r.text[:200])

# ---------------------------------------------------------------- a locked space (encrypted in the browser)
r = Ca.post(B + "/api/wiki/e2e/start", json={"space": SP2, "keys": []})
check(r.status_code == 409 and "have files" in r.json().get("error", ""), "#2182: a space with files cannot be locked yet " + r.text[:200])
# review M2: files in the trash do not block the lock (they are deleted for good when it is switched on)
allf = [f["id"] for p in Ca.get(B + "/api/wiki", params={"space": SP2}).json()["pages"]
        for f in Ca.get(B + f"/api/wiki/pages/{p['id']}").json().get("files", [])]
r = Ca.post(B + "/api/wiki/trash", json={"ids": [], "files": allf})
r2 = Ca.post(B + "/api/wiki/e2e/start", json={"space": SP2, "keys": []})
check(r.ok and allf and r2.status_code == 409 and "have files" not in r2.json().get("error", ""), "#2182: trashed files do not block the lock " + r2.text[:200])
Ca.post(B + "/api/wiki/restore", json={"ids": [], "files": allf})
cpages = {p["path"]: p["id"] for p in Ca.get(B + "/api/wiki", params={"space": SP2}).json()["pages"]}
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG2,), write=True)
r = Ca.post(B + f"/api/wiki/pages/{cpages['Projekte/Plan']}/files", files={"file": ("x.pdf", PDF, "application/pdf")})
check(r.status_code == 403 and r.json().get("error"), "#2182: a locked space refuses an upload with a clear text " + r.text[:200])
check(Ca.get(B + f"/api/wiki/files/{some}").status_code == 404 and Ca.get(B + f"/api/wiki/pages/{cpages['Projekte/Plan']}").json().get("files") == [],
      "#2182: no file of a locked space is served")
check(imp(Ca, SP2, sb_zip()).status_code == 409 and Ca.get(B + "/api/wiki/export", params={"space": SP2}).status_code == 409,
      "#2182: import / export of a locked space run in the browser (409)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
