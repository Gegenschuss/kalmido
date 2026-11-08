#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.750.0 API tests, part A (#4876): a document's own title apart from its file name, as a person WITHOUT an organisation
(tests/freelancer_fixture.py) and through API v1 with her token. Invented names only.
- the title is the file name without its ending while none is set ("Rechnung.pdf" -> "Rechnung", title_own false)
- PATCH title changes only the title (the file keeps its name); two documents of one folder may share a title, the file
  names stay unique ("x.pdf", "x (2).pdf" as before); title "" = the file name's again
- the list sorts by the title, the search finds the title; the CSV's column Title is the title, File name the file name
- download (documents and file store, both routes) and ZIP give the file name; a file name that lost its ending gets the
  one of its type back ("Rechnung" -> "Rechnung.pdf"), a fitting one is never doubled
- API v1: POST with title keeps the file name and sets the title; PATCH title writes the title; unknown fields still 400
freelancer-matrix: files
usage: p2750_a_title_test.py <datadir>      (a fresh container; P2750AT_NOSTART=1: the container runs already)"""
import base64
import io
import os
import subprocess
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, until  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, as tests/p2122_c_api_test.py)."""
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


if not os.environ.get("P2750AT_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, F = freelancer(B, A)
T = requests.Session()
T.headers.update({"Authorization": "Bearer " + F.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]})


def up(name, lines):
    r = F.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, text_pdf(lines), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: F.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 90)
    return nid


def doc(nid):
    return F.get(B + f"/api/docs/{nid}").json()


def dl_name(r):
    return r.headers.get("Content-Disposition", "")


def patch(nid, body):
    return F.patch(B + f"/api/docs/{nid}", json={**body, "expect_updated_at": doc(nid)["edited_at"]})


# ---- the title from the file name
D1 = up("Rechnung.pdf", ["Wasserwerk Beispielstadt", "Rechnung 1"])
D2 = up("Brief.pdf", ["Ein Brief"])
d = doc(D1)
check(d["name"] == "Rechnung.pdf" and d["title"] == "Rechnung" and d["title_own"] is False,
      f"no title yet: the file name without its ending ({d['name']!r} {d['title']!r} {d.get('title_own')!r})")

# ---- PATCH title changes only the title
r = patch(D1, {"title": "Wasser März"})
check(r.ok, f"PATCH title ({r.status_code} {r.text[:120]})")
d = doc(D1)
check(d["title"] == "Wasser März" and d["title_own"] is True and d["name"] == "Rechnung.pdf", f"the title changed, the file name stayed ({d['title']!r} {d['name']!r})")
# two documents with the same title: no "(2)" at the title, the file names stay their own
r = patch(D2, {"title": "Wasser März"})
d2 = doc(D2)
check(r.ok and d2["title"] == "Wasser März" and d2["name"] == "Brief.pdf", f"a second document may have the same title ({d2['title']!r} {d2['name']!r})")
# a file name that is taken in the folder still gets "(2)" (unchanged)
r = patch(D2, {"name": "Rechnung.pdf"})
check(r.ok and doc(D2)["name"] == "Rechnung (2).pdf" and doc(D2)["title"] == "Wasser März", f"the file name stays unique per folder ({doc(D2)['name']!r})")

# ---- search and sort by the title
q = F.get(B + "/api/docs", params={"q": "März", "ws": "private"}).json()
check({D1, D2} <= {x["id"] for x in q["docs"]}, f"the search finds the title ({[x['id'] for x in q['docs']]})")
patch(D2, {"title": "Anfang"})
srt = [x["id"] for x in F.get(B + "/api/docs", params={"ws": "private", "sort": "title", "dir": "asc"}).json()["docs"] if x["id"] in (D1, D2)]
check(srt == [D2, D1], f"sorted by the title: Anfang before Wasser März ({srt})")
srt = [x["id"] for x in F.get(B + "/api/docs", params={"ws": "private", "sort": "title", "dir": "desc"}).json()["docs"] if x["id"] in (D1, D2)]
check(srt == [D1, D2], f"... and the other way round ({srt})")

# ---- CSV: Title = the title, File name = the file name
txt = F.post(B + "/api/docs/export.csv", json={"ids": [D1]}).content.decode("utf-8-sig")
row = [x for x in txt.split("\r\n") if x][1]
check("Wasser März" in row and "Rechnung.pdf" in row, f"CSV: the title and the file name ({row[:160]!r})")

# ---- download: the file name, the ending back when it was lost
r = F.get(B + f"/api/docs/{D1}/file", params={"dl": "1"})
check(r.ok and "Rechnung.pdf" in dl_name(r) and "Rechnung.pdf.pdf" not in dl_name(r), f"documents: the file name, not doubled ({dl_name(r)!r})")
r = patch(D1, {"name": "Rechnung"})
check(r.ok and doc(D1)["name"] == "Rechnung" and doc(D1)["title"] == "Wasser März", f"the file name without ending; the title stays ({doc(D1)['name']!r})")
r = F.get(B + f"/api/docs/{D1}/file", params={"dl": "1"})
check(r.ok and "Rechnung.pdf" in dl_name(r), f"documents download: the ending of the type back ({dl_name(r)!r})")
r = F.get(B + f"/api/files/nodes/{D1}/content", params={"dl": "1"})
check(r.ok and "Rechnung.pdf" in dl_name(r), f"file store download: the same ({dl_name(r)!r})")
r = F.get(B + f"/api/files/nodes/{D1}/content")
check(r.ok and "Rechnung.pdf" in dl_name(r), f"file store inline: the same ({dl_name(r)!r})")
# ZIP: the file names
t = F.post(B + "/api/docs/zip", json={"ids": [D1, D2]})
check(t.ok, f"ZIP ticket ({t.status_code} {t.text[:100]})")
if t.ok:
    z = F.get(B + t.json()["url"])
    names = sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) if z.ok else []
    check(names == ["Rechnung (2).pdf", "Rechnung.pdf"], f"the ZIP holds the file names with their endings ({names})")
# title "" = the file name's again
r = patch(D1, {"title": ""})
d = doc(D1)
check(r.ok and d["title"] == "Rechnung" and d["title_own"] is False, f"an empty title: the file name's again ({d['title']!r})")

# ---- API v1 (her token)
r = T.post(B + "/api/v1/documents", json={"name": "scan-0042.pdf", "content_base64": base64.b64encode(text_pdf(["Vertrag"])).decode(), "title": "Mietvertrag"})
check(r.status_code == 201, f"v1 POST with title ({r.status_code} {r.text[:120]})")
V = r.json().get("id") if r.ok else 0
v = T.get(B + f"/api/v1/documents/{V}").json() if V else {}
check(v.get("name") == "scan-0042.pdf" and v.get("title") == "Mietvertrag", f"v1: the file keeps its name, the title is its own ({v.get('name')!r} {v.get('title')!r})")
r = T.post(B + "/api/v1/documents", json={"content_base64": base64.b64encode(text_pdf(["Ohne Namen"])).decode(), "mime": "application/pdf", "title": "Kaufvertrag"})
w = r.json() if r.ok else {}
check(r.status_code == 201 and w.get("name") == "Kaufvertrag.pdf" and w.get("title") == "Kaufvertrag", f"v1 without a name: named after the title + ending ({w.get('name')!r})")
if V:
    until(lambda: T.get(B + f"/api/v1/documents/{V}").json().get("state") in ("done", "failed"), 90)
    v = T.get(B + f"/api/v1/documents/{V}").json()
    r = T.patch(B + f"/api/v1/documents/{V}", json={"title": "Mietvertrag 2026", "expect_updated_at": v["updated_at"]})
    v = T.get(B + f"/api/v1/documents/{V}").json()
    check(r.ok and v.get("title") == "Mietvertrag 2026" and v.get("name") == "scan-0042.pdf", f"v1 PATCH title ({r.status_code} {v.get('title')!r} {v.get('name')!r})")
    check(T.patch(B + f"/api/v1/documents/{V}", json={"name": "x.pdf", "expect_updated_at": v["updated_at"]}).status_code == 400, "v1 PATCH name stays unknown (400)")
spec = T.get(B + "/api/v1/openapi.json")
if spec.ok:
    sch = spec.json().get("components", {}).get("schemas", {}).get("Document", {}).get("properties", {})
    check("title" in sch, "the API description names title")

print(f"p2750_a_title: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
