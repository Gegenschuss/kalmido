#!/usr/bin/env python3
"""2.112.1 API tests, part A (#2058): several nodes of the file store at once, the ZIP download and the phone scan.
Invented names only, generated file contents (pictures drawn here as PNG, no library).
 - POST /api/files/trash {ids}: all into the trash in one go (a chosen node inside a chosen folder rides along); a foreign
   id (404) or an id with only "view" (403) refuses ALL, nothing is deleted; POST /api/files/restore {ids} = the undo
 - GET /api/files/zip?ids=: the folder structure kept, a doubled name -> "name (2).ext", the trash left out, a single
   folder -> "<folder>.zip"; &check=1 only counts; the limit (KALMIDO_FILES_ZIP_MAX_FILES small for this container) -> 413
   before anything is written; only what the person may see (a share across the organisation: the colleague gets the
   shared folder, someone of another organisation 404)
 - POST /api/files/scan: two pictures (one turned) -> ONE PDF with two pages in the chosen folder; out=pdf only answers
   the PDF (the documents file it themselves); too many pages / not a picture / a folder with "view" only -> refused
 - a person without an organisation (freelancer fixture): the same in the private space
tenant-matrix: file
freelancer-matrix: files
usage: p21121_a_api_test.py <datadir>      (a fresh container; P21121A_NOSTART=1: the container runs already)"""
import io
import os
import re
import struct
import subprocess
import sys
import zipfile
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
ZIP_MAX_FILES = 6  # the container's KALMIDO_FILES_ZIP_MAX_FILES
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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def folder(s, name, parent=None, space=None):
    b = {"name": name, **({"parent_id": parent} if parent else {}), **({"space": space} if space else {})}
    r = s.post(B + "/api/files/folders", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, name, data, parent=None, space=None):
    form = {"parent_id": str(parent)} if parent else {"space": space or "private"}
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def deleted(nid):
    r = dbx("SELECT deleted_at FROM fs_nodes WHERE id=?", (nid,))
    return bool(r and r[0][0])


def names(resp):
    try:
        return sorted(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())
    except zipfile.BadZipFile:
        return None


def png(w, h, rgb):
    """A plain PNG of one colour (no library)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def pages(pdf):
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf))


def scan(s, imgs, form):
    files = [("page", (f"p{i}.png", d, "image/png")) for i, d in enumerate(imgs)]
    return s.post(B + "/api/files/scan", data=form, files=files)


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol + erin, Beta = dave; a small ZIP limit
if not os.environ.get("P21121A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_FILES_ZIP_MAX_FILES={ZIP_MAX_FILES}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
for u in ("carol", "erin"):
    check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG)), f"setup: {u} joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, BOB, CAROL, ERIN, ORG2, DAVE))
Ca, Da, Er = sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- carol's private tree: Proj/{a.txt, b.txt, d.txt (trash), Unter/c.txt}, Other/a.txt
PROJ = folder(Ca, "Proj")
UNTER = folder(Ca, "Unter", parent=PROJ)
A1 = upload(Ca, "a.txt", b"Alpha eins", parent=PROJ)
B1 = upload(Ca, "b.txt", b"Beta zwei", parent=PROJ)
C1 = upload(Ca, "c.txt", b"Gamma drei", parent=UNTER)
D1 = upload(Ca, "d.txt", b"Delta weg", parent=PROJ)
OTHER = folder(Ca, "Other")
A2 = upload(Ca, "a.txt", b"Alpha anders", parent=OTHER)
check(Ca.delete(B + f"/api/files/nodes/{D1}").ok, "setup: d.txt into the trash")
DAVEF = upload(Da, "fremd.txt", b"Dave privat")

# ---- the ZIP: a folder keeps its structure, the trash stays out, the name is the folder's
r = Ca.get(B + f"/api/files/zip?ids={PROJ}")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/zip"), f"ZIP of a folder ({r.status_code} {r.text[:200] if not r.ok else ''})")
check(names(r) == ["Proj/", "Proj/Unter/", "Proj/Unter/c.txt", "Proj/a.txt", "Proj/b.txt"], f"the folder structure, no trash ({names(r)})")
check("Proj.zip" in r.headers.get("Content-Disposition", ""), f"the ZIP is named after the folder ({r.headers.get('Content-Disposition')})")
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
check(z is not None and z.read("Proj/Unter/c.txt") == b"Gamma drei", "the content in the ZIP is the plain file")
# two chosen files of the same name -> "a (2).txt"; a chosen file inside a chosen folder is not doubled
r = Ca.get(B + f"/api/files/zip?ids={A1},{A2}")
check(names(r) == ["a (2).txt", "a.txt"], f"a doubled name gets ' (2)' ({r.status_code} {names(r)})")
check("Kalmido-Dateien-" in r.headers.get("Content-Disposition", ""), f"several items: Kalmido-Dateien-<date>.zip ({r.headers.get('Content-Disposition')})")
r = Ca.get(B + f"/api/files/zip?ids={PROJ},{C1}")
check(names(r) == ["Proj/", "Proj/Unter/", "Proj/Unter/c.txt", "Proj/a.txt", "Proj/b.txt"], f"a file inside a chosen folder comes once ({names(r)})")
r = Ca.get(B + f"/api/files/zip?ids={PROJ}&check=1")
check(r.ok and r.json().get("files") == 3, f"check=1 counts the files ({r.status_code} {r.text[:200]})")
# the limit: 7 files > KALMIDO_FILES_ZIP_MAX_FILES -> 413 with a message, also in the check
BIG = folder(Ca, "Viele")
for i in range(ZIP_MAX_FILES + 1):
    upload(Ca, f"f{i}.txt", f"Datei {i}".encode(), parent=BIG)
r = Ca.get(B + f"/api/files/zip?ids={BIG}")
check(r.status_code == 413 and "ZIP" in (r.json().get("error") or ""), f"over the limit: 413 with a message ({r.status_code} {r.text[:200]})")
r = Ca.get(B + f"/api/files/zip?ids={BIG}&check=1")
check(r.status_code == 413, f"the check refuses it as well ({r.status_code})")
# rights: someone else's file 404, the trash 404, bad ids 400
check(Ca.get(B + f"/api/files/zip?ids={DAVEF}").status_code == 404, "someone else's file: 404")
check(Da.get(B + f"/api/files/zip?ids={PROJ}").status_code == 404, "someone else's folder: 404")
check(Ca.get(B + f"/api/files/zip?ids={D1}").status_code == 404, "a file in the trash: 404")
check(Ca.get(B + "/api/files/zip?ids=x").status_code == 400, "bad ids: 400")
check(Ca.get(B + "/api/files/zip").status_code == 400, "no ids: 400")

# ---- shared across the organisation: carol's Alpha folder shared with erin (view)
SHF = folder(Ca, "Team", space=f"org:{ORG}")
S1 = upload(Ca, "plan.txt", b"Teamplan", parent=SHF)
SECRET = folder(Ca, "Geheim", space=f"org:{ORG}")
upload(Ca, "geheim.txt", b"nur carol", parent=SECRET)
r = Ca.post(B + f"/api/files/nodes/{SHF}/shares", json={"user_id": ERIN, "role": "view"})
check(r.status_code == 201, f"setup: carol shares Team with erin ({r.status_code} {r.text[:200]})")
r = Er.get(B + f"/api/files/zip?ids={SHF}")
check(names(r) == ["Team/", "Team/plan.txt"], f"erin gets the shared folder ({r.status_code} {names(r)})")
check(Er.get(B + f"/api/files/zip?ids={SECRET}").status_code == 404, "erin: an Alpha folder not shared with her 404")
check(Er.get(B + f"/api/files/zip?ids={SHF},{SECRET}").status_code == 404, "erin: one hidden id refuses the ZIP")
check(Da.get(B + f"/api/files/zip?ids={SHF}").status_code == 404, "dave (Beta) does not get Alpha's folder")
r = Bo.get(B + f"/api/files/zip?ids={SECRET}")
check(names(r) == ["Geheim/", "Geheim/geheim.txt"], f"bob (admin of Alpha) gets every Alpha folder ({names(r)})")

# ---- the trash, several at once: all or nothing
r = Er.post(B + "/api/files/trash", json={"ids": [S1]})
check(r.status_code == 403 and not deleted(S1), f"erin with 'view' only: 403, nothing deleted ({r.status_code})")
r = Ca.post(B + "/api/files/trash", json={"ids": [A1, DAVEF]})
check(r.status_code == 404 and not deleted(A1) and not deleted(DAVEF), f"a foreign id refuses all: 404, nothing deleted ({r.status_code})")
check(Ca.post(B + "/api/files/trash", json={"ids": []}).status_code == 400, "no ids: 400")
r = Ca.post(B + "/api/files/trash", json={"ids": [A1, B1, UNTER]})
check(r.ok and all(deleted(x) for x in (A1, B1, UNTER)) and not deleted(PROJ), f"three into the trash at once ({r.status_code} {r.text[:200]})")
tr = Ca.get(B + "/api/files?space=trash").json()
check({A1, B1, UNTER} <= {x["id"] for x in tr.get("items", [])}, "they are in carol's trash")
r = Ca.post(B + "/api/files/restore", json={"ids": [A1, B1, UNTER]})
check(r.ok and not any(deleted(x) for x in (A1, B1, UNTER)), f"the undo brings all back ({r.status_code} {r.text[:200]})")
check(Ca.get(B + f"/api/files/nodes/{C1}/content").content == b"Gamma drei", "the file inside the restored folder reads again")
r = Ca.post(B + "/api/files/trash", json={"ids": [PROJ, A1]})
check(r.ok and r.json().get("ids") == [PROJ] and deleted(PROJ) and not deleted(A1), f"a chosen file inside a chosen folder rides along ({r.text[:200]})")
check(Ca.get(B + f"/api/files/nodes/{A1}/content").status_code == 404, "... and cannot be opened while the folder is in the trash")
r = Da.post(B + "/api/files/restore", json={"ids": [PROJ]})
check(r.status_code == 404 and deleted(PROJ), f"dave cannot restore carol's folder ({r.status_code})")
check(Ca.post(B + "/api/files/restore", json={"ids": [PROJ]}).ok and not deleted(PROJ), "carol restores the folder")

# ---- the scan: two pictures -> one PDF with two pages in Proj
IMG1, IMG2 = png(30, 20, (200, 40, 40)), png(20, 30, (40, 40, 200))
r = scan(Ca, [IMG1, IMG2], [("parent_id", str(PROJ)), ("name", "Scan Test"), ("bw", "1"), ("rot", "90"), ("rot", "0")])
check(r.status_code == 201, f"scan stored ({r.status_code} {r.text[:300]})")
it = (r.json().get("items") or [{}])[0] if r.status_code == 201 else {}
check(it.get("name") == "Scan Test.pdf" and it.get("mime") == "application/pdf", f"one PDF named after the form ({it.get('name')}, {it.get('mime')})")
check(dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (it.get("id") or 0,)) == [(PROJ,)] if it else False, "the PDF lies in the chosen folder")
pdf = Ca.get(B + f"/api/files/nodes/{it.get('id')}/content").content if it else b""
check(pdf[:5] == b"%PDF-" and pages(pdf) == 2, f"a PDF with two pages ({pdf[:8]!r}, {pages(pdf)} pages)")
check(b"Exif" not in pdf, "no EXIF data in the PDF")
r = scan(Ca, [IMG1], [("space", "private"), ("bw", "0")])
check(r.status_code == 201 and (r.json()["items"][0]["name"] or "").startswith("Scan "), f"without a name: 'Scan <date> <time>' ({r.text[:200]})")
n0 = dbx("SELECT COUNT(*) FROM fs_nodes")[0][0]
r = scan(Ca, [IMG1, IMG2, IMG1], [("out", "pdf"), ("name", "Beleg")])
check(r.ok and r.content[:5] == b"%PDF-" and pages(r.content) == 3, f"out=pdf answers the PDF ({r.status_code} {pages(r.content) if r.ok else r.text[:200]})")
check(dbx("SELECT COUNT(*) FROM fs_nodes")[0][0] == n0, "out=pdf stores nothing")
r = scan(Ca, [IMG1] * 31, [("space", "private")])
check(r.status_code == 400, f"31 pages: refused ({r.status_code})")
r = scan(Ca, [b"no picture at all"], [("space", "private")])
check(r.status_code == 400 and "Page 1" in (r.json().get("error") or ""), f"not a picture: 400 with the page ({r.status_code} {r.text[:200]})")
r = scan(Er, [IMG1], [("parent_id", str(SHF))])
check(r.status_code == 403, f"erin with 'view' on the folder cannot scan into it ({r.status_code})")
r = scan(Da, [IMG1], [("parent_id", str(PROJ))])
check(r.status_code == 404, f"dave cannot scan into carol's folder ({r.status_code})")
check(Ca.post(B + "/api/files/scan", data={"space": "private"}).status_code == 400, "no page: 400")

# ---- a person without an organisation: the same in the private space
# freelancer-matrix: files
FID, Fr = freelancer(B, A)
FF = folder(Fr, "Kunde")
F1 = upload(Fr, "angebot.txt", b"Angebot", parent=FF)
F2 = upload(Fr, "notiz.txt", b"Notiz", parent=FF)
r = Fr.get(B + f"/api/files/zip?ids={FF}")
check(names(r) == ["Kunde/", "Kunde/angebot.txt", "Kunde/notiz.txt"], f"freelancer: ZIP of a folder ({r.status_code} {names(r)})")
check(Fr.get(B + f"/api/files/zip?ids={FF}&check=1").ok, "freelancer: the ZIP check")
r = Fr.post(B + "/api/files/trash", json={"ids": [F1, F2]})
check(r.ok and deleted(F1) and deleted(F2), f"freelancer: two into the trash ({r.status_code})")
r = Fr.post(B + "/api/files/restore", json={"ids": [F1, F2]})
check(r.ok and not deleted(F1) and not deleted(F2), f"freelancer: and back ({r.status_code})")
r = scan(Fr, [IMG1, IMG2], [("parent_id", str(FF)), ("name", "Vertrag")])
check(r.status_code == 201 and r.json()["items"][0]["name"] == "Vertrag.pdf", f"freelancer: scan into the folder ({r.status_code} {r.text[:200]})")
check(Fr.get(B + f"/api/files/zip?ids={PROJ}").status_code == 404, "freelancer: carol's folder 404")

print(f"p21121_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
