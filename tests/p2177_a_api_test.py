#!/usr/bin/env python3
"""2.177.0 (#2685) API tests: the ZIP import of knowledge pages for large archives -- uploaded in pieces, unpacked in the
background with progress (own container with small limits: KALMIDO_WIKI_IMPORT_MAX_MB=8, KALMIDO_WIKI_FILE_MAX_MB=1, a
server key so the upload is sealed at rest). The archive is made here: pages that link PDFs, PDFs of invented bytes (stored,
not compressible), two of them above the per-file limit -- never real documents.
 - limits: GET /api/wiki/import/upload names chunk / max_mb / file_mb; a ZIP above max_mb is refused before any byte (413,
   the limit in MB in the text); an agent's token cannot use the route (403)
 - upload in pieces: a wrong offset answers 409 with the bytes received; the last piece starts the background run; the
   state goes running (progress {done, total}) -> done with the report of the single POST: pages created, files taken
   over, the two large PDFs skipped with "Larger than 1 MB", the links in the pages point at the stored files
 - cancel: DELETE of an upload removes it (404 afterwards); after the end DELETE clears the result
 - the old single POST /api/wiki/import keeps working for small ZIPs
 - rights (tenant-matrix: wiki): another organisation's space 404 at the start, another person's upload 404 (read, piece,
   delete); a member of the organisation imports into it. A person without an organisation (freelancer-matrix: wiki)
   imports into the own private space.
usage: p2177_a_api_test.py <datadir>"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
U = B + "/api/wiki/import/upload"


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


def pdf(n, seed):
    """A small valid-looking PDF with n bytes of invented, incompressible filler."""
    head = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n%" + seed.encode() + b"\n")
    return head + os.urandom(n) + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def big_zip():
    """7 pages linking PDFs, 14 PDFs of 300 KB, 2 above the 1 MB limit (one of them linked)."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k in range(7):
            links = " ".join(f"[[Handbuch {k * 2 + j}.pdf]]" for j in range(2))
            extra = " und ![[_attachments/Gross 1.pdf]]" if k == 0 else ""
            z.writestr(f"Handbuecher/Seite {k}.md", f"# Seite {k}\n\nSiehe {links}{extra}.\n")
        for i in range(14):
            z.writestr(f"Handbuecher/Handbuch {i}.pdf", pdf(300 * 1024, f"h{i}"), compress_type=zipfile.ZIP_STORED)
        for i in range(2):
            z.writestr(f"_attachments/Gross {i + 1}.pdf", pdf(1200 * 1024, f"g{i}"), compress_type=zipfile.ZIP_STORED)
    return b.getvalue()


def small_zip(name="Klein"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{name}/Start.md", "# Start\n\n[[Datei.pdf]]\n")
        z.writestr(f"{name}/Datei.pdf", pdf(2000, name), compress_type=zipfile.ZIP_STORED)
    return b.getvalue()


def upload(s, space, data, replace=False, stop_after=None):
    """-> (POST answer, last answer). Sends the pieces like the app; stop_after = only that many pieces."""
    r = s.post(U, json={"size": len(data), "name": "wiki.zip", "space": space, "replace": replace})
    if not r.ok:
        return r, None
    j = r.json()
    off, n, last = 0, 0, None
    while off < len(data):
        if stop_after is not None and n >= stop_after:
            break
        part = data[off:off + j["chunk"]]
        last = s.put(f"{U}/{j['id']}", params={"offset": off}, data=part, headers={"Content-Type": "application/octet-stream"})
        if not last.ok:
            break
        off += len(part)
        n += 1
    return r, last


def wait_end(s, iid, seen=None, t=90):
    end = time.time() + t
    while time.time() < end:
        j = s.get(f"{U}/{iid}").json()
        if seen is not None and j.get("state") == "running":
            seen.append(j.get("progress") or {})
        if j.get("state") != "running":
            return j
        time.sleep(0.3)
    return {"state": "timeout"}


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
           " -e KALMIDO_WIKI_IMPORT_MAX_MB=8 -e KALMIDO_WIKI_FILE_MAX_MB=1")
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
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"
FID, Fr = freelancer(B, A)

# ---------------------------------------------------------------- limits, before any byte
j = Bo.get(U).json()
check(j.get("max_mb") == 8 and j.get("file_mb") == 1 and j.get("chunk", 0) >= 1 << 20 and j.get("current") is None,
      f"#2685: the limits of the route {j}")
CHUNK = j.get("chunk", 1 << 20)
r = Bo.post(U, json={"size": 8 * 1024 * 1024 + 1, "name": "gross.zip", "space": SP})
check(r.status_code == 413 and "8 MB" in r.json().get("error", ""), f"#2685: a ZIP above the limit is refused before the upload {r.status_code} {r.text[:200]}")
r = Bo.post(U, json={"size": "viel", "space": SP})
check(r.status_code == 400, f"#2685: a size that is no number {r.status_code}")
r = Ca.post(U, json={"size": 1000, "name": "x.zip", "space": SP})
check(r.status_code == 404, f"#2685: another organisation's space is not even there {r.status_code}")
tok = Bo.post(B + "/api/me/tokens", json={"name": "t2177", "scopes": ["read", "write"]})
if tok.ok and tok.json().get("token"):
    r = requests.post(U, json={"size": 1000, "space": SP}, headers={"Authorization": "Bearer " + tok.json()["token"]})
    check(r.status_code in (401, 403), f"#2685: a token cannot use the upload route {r.status_code}")

# ---------------------------------------------------------------- the large import (member of the organisation)
DATA_ZIP = big_zip()
check(len(DATA_ZIP) > 2 * CHUNK, f"#2685: the test ZIP needs several pieces {len(DATA_ZIP)} {CHUNK}")
r = Bo.post(U, json={"size": len(DATA_ZIP), "name": "handbuecher.zip", "space": SP})
check(r.ok, "#2685: the upload starts " + r.text[:200])
IID = r.json()["id"]
first = DATA_ZIP[:CHUNK]
r = Bo.put(f"{U}/{IID}", params={"offset": CHUNK}, data=first)
check(r.status_code == 409 and r.json().get("received") == 0, f"#2685: a wrong offset names the bytes received {r.status_code} {r.text[:120]}")
r = Bo.put(f"{U}/{IID}", params={"offset": 0}, data=first)
check(r.ok and r.json().get("state") == "upload" and r.json().get("received") == CHUNK, f"#2685: the first piece {r.text[:200]}")
for who in (Ca, A):  # another person: not there (A is the organisation's admin, still not her upload)
    check(who.get(f"{U}/{IID}").status_code == 404, "#2685: another person's upload is not there (read)")
    check(who.put(f"{U}/{IID}", params={"offset": CHUNK}, data=DATA_ZIP[CHUNK:2 * CHUNK]).status_code == 404, "#2685: (piece)")
    check(who.delete(f"{U}/{IID}").status_code == 404, "#2685: (delete)")
check(Bo.get(U).json().get("current", {}).get("id") == IID, "#2685: the current upload is picked up again after a reload")
off = CHUNK
while off < len(DATA_ZIP):
    part = DATA_ZIP[off:off + CHUNK]
    r = Bo.put(f"{U}/{IID}", params={"offset": off}, data=part)
    if not r.ok:
        check(False, f"#2685: piece at {off} {r.status_code} {r.text[:200]}")
        break
    off += len(part)
check(r.ok and r.json().get("state") in ("running", "done"), f"#2685: the last piece starts the run {r.text[:200]}")
seen = []
J = wait_end(Bo, IID, seen)
check(J.get("state") == "done", f"#2685: the import ends {J.get('state')} {J.get('error')}")
res = J.get("result") or {}
check(len(res.get("created", [])) == 7, f"#2685: seven pages {res.get('created')}")
check(res.get("files_n") == 14, f"#2685: fourteen PDFs taken over {res.get('files_n')}")
why = {s["name"]: s["reason"] for s in res.get("skipped_detail", [])}
check(all("Larger than 1 MB" in why.get(f"_attachments/Gross {i}.pdf", "") for i in (1, 2)), f"#2685: files above the limit are skipped with the reason {why}")
pg = J.get("progress") or {}
check(pg.get("total") == 7 + 14 + 2 and pg.get("done") == pg.get("total"), f"#2685: the progress counts every entry {pg}")
check(all(isinstance(p.get("done"), int) and p.get("done") <= p.get("total", 0) for p in seen), f"#2685: progress while running {seen[:5]}")
pages = {p["path"]: p["id"] for p in Bo.get(B + "/api/wiki", params={"space": SP}).json()["pages"]}
p0 = Bo.get(B + f"/api/wiki/pages/{pages.get('Handbuecher/Seite 0')}").json()
check("/api/wiki/files/" in (p0.get("body") or "") and "[[Handbuch 0.pdf]]" not in (p0.get("body") or ""), f"#2685: the links point at the stored files {(p0.get('body') or '')[:300]}")
check("Gross 1.pdf" in (p0.get("body") or ""), "#2685: the link of a skipped file stays as it was")
check(len(p0.get("files") or []) == 2, f"#2685: the page has its two PDFs {[f['name'] for f in p0.get('files') or []]}")
fid = (p0.get("files") or [{}])[0].get("id")
r = Bo.get(B + f"/api/wiki/files/{fid}")
check(r.ok and r.content.startswith(b"%PDF"), f"#2685: a stored PDF is served {r.status_code}")
check(Bo.get(B + f"/api/wiki/files/{fid}").ok and Ca.get(B + f"/api/wiki/files/{fid}").status_code == 404, "#2685: another organisation does not reach the files")
check(not os.path.exists(os.path.join(DATA, "exports", "wiki-import", str(Bo.get(B + "/api/state").json()["me"]["id"]), IID, "upload.bin")),
      "#2685: the uploaded ZIP is removed after the run")
r = Bo.delete(f"{U}/{IID}")
check(r.ok and Bo.get(f"{U}/{IID}").status_code == 404 and Bo.get(U).json().get("current") is None, "#2685: the result is cleared once seen")
# Undo of the import (the app's step: pages + files to the trash)
r = Bo.post(B + "/api/wiki/trash", json={"ids": res.get("created", []), "files": res.get("files", [])})
check(r.ok, "#2685: the Undo of the import " + r.text[:200])

# ---------------------------------------------------------------- cancel, again, the old route
r, last = upload(Bo, SP, DATA_ZIP, stop_after=1)
iid = r.json()["id"]
check(last is not None and last.ok and last.json().get("state") == "upload", "#2685: an upload half way")
r = Bo.delete(f"{U}/{iid}")
check(r.ok and Bo.get(f"{U}/{iid}").status_code == 404, f"#2685: cancel removes the upload {r.status_code}")
r = Bo.post(B + "/api/wiki/import", params={"space": SP}, files={"file": ("k.zip", small_zip("Alt"), "application/zip")})
check(r.ok and len(r.json().get("created", [])) == 1 and r.json().get("files_n") == 1, "#2685: the single POST still imports small ZIPs " + r.text[:200])

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: wiki)
r, last = upload(Fr, "private", small_zip("Frei"))
check(r.ok and last is not None and last.ok, "#2685: a freelancer uploads into the private space " + (last.text[:200] if last is not None else r.text[:200]))
if r.ok:
    J = wait_end(Fr, r.json()["id"])
    check(J.get("state") == "done" and len((J.get("result") or {}).get("created", [])) == 1 and (J.get("result") or {}).get("files_n") == 1,
          f"#2685: the freelancer's import {J}")
    fp = {p["path"] for p in Fr.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}
    check("Frei/Start" in fp, f"#2685: the page is in the freelancer's private space {fp}")
    check("Frei/Start" not in {p["path"] for p in A.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}, "#2685: nobody else sees it")
r = Fr.post(U, json={"size": 1000, "space": SP})
check(r.status_code == 404, f"#2685: the freelancer cannot import into an organisation {r.status_code}")

print(f"p2177_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
