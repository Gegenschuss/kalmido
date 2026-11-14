#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1151.0 D (#5524): one knowledge page as a PDF or a Word file (GET /api/wiki/pages/<id>/export?format=pdf|docx&style=,
kalmido/wiki/wkdoc.py). Invented names only.
 - PDF: a real PDF (%PDF-1.7, PDF/A metadata of the office writer) that carries the page's name and its text; a web link
   becomes a link (URI action); a picture uploaded to the page is embedded (an image XObject)
 - .docx: a ZIP with [Content_Types].xml, word/document.xml (title, heading as Heading1, bold run, a numbered list, a table,
   the link as w:hyperlink with an external relationship), styles.xml / numbering.xml, the picture under word/media
 - the reading style: an unknown one 400; Book gives the serif and the wider margin in Word; without ?style= the space's
   default (PUT /api/wiki/style) counts
 - rights: another person of the organisation without a share 404 on a private page; a member reads (and exports) the
   organisation's page; the read-only member too; an unknown format 400; a page in the trash 404
 - a space with the lock: 409 wiki_e2e (the browser makes the file)
 - freelancer: a person without an organisation exports her private page
usage: p21151_d_wiki_export_test.py <datadir>"""
import base64
import io
import os
import re
import sys
import zipfile
import zlib

import kt
from kt import B, check, sess
import dbx as dbxm
from freelancer_fixture import freelancer

DATA = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KALMIDO_TEST_DATA", "")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
FEAT = "wiki,files,collab,comments"

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
assert r.ok, r.text
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
WS = A.get(B + "/api/state").json()["me"].get("workspaces") or []
assert WS, "the organisation of the setup " + str(WS)
ORG = WS[0]["id"]
SP = f"org:{ORG}"
for name, role in (("bert", "member"), ("rita", "readonly")):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": [{"id": ORG, "role": role}]})
    assert r.ok, r.text
Bs, Rs = sess("bert"), sess("rita")
for s in (Bs, Rs):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def page(s, path, text, space=SP):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def export(s, pid, fmt, **kw):
    return s.get(B + f"/api/wiki/pages/{pid}/export", params={"format": fmt, **kw})


def pdf_text(data):
    """Every text shown in the PDF (the office writer draws <hex> Tj in Flate streams, WinAnsi)."""
    out = []
    for m in re.finditer(rb"stream\n(.*?)\nendstream", data, re.S):
        try:
            raw = zlib.decompress(m.group(1))
        except zlib.error:
            continue
        out += [bytes.fromhex(h.decode()).decode("cp1252", "replace") for h in re.findall(rb"<([0-9a-f]+)> Tj", raw)]
    return " ".join(out)


TEXT = """# Offer for Lindenhof

Dear **Mr Sample**, here is the *plan* with ~~old~~ new dates.

1. Visit the site
2. Write the report

- [x] Contract signed
- [ ] Invoice sent

| Item | Price |
| --- | ---: |
| Survey | 120 |

> A quote that stays.

See [the website](https://example.com/plan) and [[Other page]].

```
code line
```
"""
P1 = page(A, "Projects/Lindenhof letter", TEXT)
r = A.post(B + f"/api/wiki/pages/{P1}/files", files=[("file", ("dot.png", PNG, "image/png"))])
check(r.status_code == 201, "a picture uploaded to the page " + r.text[:200])
FID = r.json()["files"][0]["id"]
r = A.patch(B + f"/api/wiki/pages/{P1}", json={"body": TEXT + f"\n![dot](/api/wiki/files/{FID}/dot.png)\n"})
check(r.ok, "the picture linked in the page " + r.text[:200])

# ---- PDF
r = export(A, P1, "pdf")
check(r.status_code == 200 and r.content.startswith(b"%PDF-1.7"), f"#5524: a PDF comes ({r.status_code}) {r.content[:20]!r}")
check(r.headers.get("Content-Type", "").startswith("application/pdf"), "#5524: the PDF's type " + r.headers.get("Content-Type", ""))
check("Lindenhof letter.pdf" in r.headers.get("Content-Disposition", ""), "#5524: the file is named after the page " + r.headers.get("Content-Disposition", ""))
t = pdf_text(r.content)
check("Offer" in t and "Lindenhof" in t, "#5524: the heading of the page is in the PDF: " + t[:200])
check("Mr" in t and "Sample" in t and "Visit" in t and "Survey" in t and "120" in t and "quote" in t, "#5524: paragraph, list, table and quote text in the PDF")
check(b"/URI (https://example.com/plan)" in r.content, "#5524: the web link is a link in the PDF")
check(b"/Subtype /Image" in r.content, "#5524: the page's picture is embedded in the PDF")
check(b"pdfaid" in r.content, "#5524: the office writer's PDF/A metadata")

# ---- .docx
r = export(A, P1, "docx")
check(r.status_code == 200 and r.content[:2] == b"PK", f"#5524: a .docx comes ({r.status_code})")
check("wordprocessingml" in r.headers.get("Content-Type", ""), "#5524: the type of a Word file " + r.headers.get("Content-Type", ""))
z = zipfile.ZipFile(io.BytesIO(r.content))
names = set(z.namelist())
check({"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/numbering.xml", "word/_rels/document.xml.rels"} <= names,
      f"#5524: the parts of a Word file {sorted(names)}")
doc = z.read("word/document.xml").decode()
check("Offer for Lindenhof" in doc and 'w:val="Heading1"' in doc, "#5524: the heading as Heading1 in document.xml")
check('w:val="Title"' in doc and "Lindenhof letter" in doc, "#5524: the page's name as the title above a different first heading")
check("<w:b/>" in doc and "Mr Sample" in doc and "<w:i/>" in doc and "<w:strike/>" in doc, "#5524: bold / italic / struck runs")
check("Visit the site" in doc and "<w:numId" in doc and "<w:tbl>" in doc and "Survey" in doc, "#5524: list and table")
check("☒" in doc and "☐" in doc, "#5524: the ticks of a task list")
check("<w:hyperlink" in doc and "https://example.com/plan" in z.read("word/_rels/document.xml.rels").decode(), "#5524: the web link is a hyperlink")
check("Other page" in doc, "#5524: a [[page]] link as its text")
check(any(n.startswith("word/media/") for n in names) and "<w:drawing>" in doc, "#5524: the page's picture is in the Word file")
check("Arial" in z.read("word/styles.xml").decode(), "#5524: the Clear style's font")

# ---- a text that starts with the page's own name as its heading gets no second title
P3 = page(A, "Notes/Plan Oak", "# Plan Oak\n\nTwo rooms.")
doc = zipfile.ZipFile(io.BytesIO(export(A, P3, "docx").content)).read("word/document.xml").decode()
check('w:val="Title"' not in doc and doc.count("Plan Oak") == 1 and 'w:val="Heading1"' in doc, "#5524: no second title when the text starts with the page's name")
check(pdf_text(export(A, P3, "pdf").content).count("Plan Oak") == 1, "#5524: ... also in the PDF")

# ---- title when the text has no heading of the page's name; the reading style
P2 = page(A, "Notes/Short memo", "Just one line with a [link](javascript:alert(1)).")
r = export(A, P2, "docx", style="book")
z = zipfile.ZipFile(io.BytesIO(r.content))
doc, sty = z.read("word/document.xml").decode(), z.read("word/styles.xml").decode()
check('w:val="Title"' in doc and "Short memo" in doc, "#5524: the page's name as the title")
check("Georgia" in sty and 'w:left="1814"' in doc, "#5524: Book = serif + the wider margin")
check("javascript" not in z.read("word/_rels/document.xml.rels").decode() and "<w:hyperlink" not in doc, "#5524: only web / mail addresses become links")
check(export(A, P2, "pdf", style="fancy").status_code == 400, "#5524: an unknown reading style 400")
check(export(A, P2, "odt").status_code == 400, "#5524: an unknown format 400")
r = A.put(B + "/api/wiki/style", json={"space": SP, "style": "compact"})
check(r.ok, "the space's default style " + r.text[:100])
z = zipfile.ZipFile(io.BytesIO(export(A, P2, "docx").content))
check('w:left="907"' in z.read("word/document.xml").decode(), "#5524: without ?style= the space's default (Compact: narrow margin)")
r = export(A, P2, "pdf", style="notepad")
check(r.ok and "Short memo" in pdf_text(r.content), "#5524: Notepad style PDF with the title")

# ---- rights
PRIV = page(A, "Private draft", "secret plan", space="private")
check(export(Bs, PRIV, "pdf").status_code == 404, "#5524: another person's private page 404")
check(export(A, PRIV, "pdf").status_code == 200, "#5524: the own private page")
check(export(Bs, P1, "docx").status_code == 200, "#5524: a member exports the organisation's page")
check(export(Rs, P1, "pdf").status_code == 200, "#5524: a read-only member exports too (reading is enough)")
r = A.delete(B + f"/api/wiki/pages/{P2}")
check(r.ok, "page to the trash")
check(export(A, P2, "pdf").status_code == 404, "#5524: a page in the trash 404")

# ---- a space with the lock: the browser makes the file
if sql("SELECT 1 FROM wiki_spaces WHERE org_id=?", (ORG,)):
    sql("UPDATE wiki_spaces SET e2e='on', e2e_gen=1 WHERE org_id=?", (ORG,), write=True)
else:
    sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG,), write=True)
r = export(A, P1, "pdf")
check(r.status_code == 409 and "wiki_e2e" in r.text, f"#5524: a space with the lock 409 wiki_e2e ({r.status_code}) {r.text[:200]}")
sql("UPDATE wiki_spaces SET e2e=NULL WHERE org_id=?", (ORG,), write=True)

# ---- freelancer parity  (freelancer-matrix: wiki)
FID2, Fr = freelancer(B, A)
FP = page(Fr, "Invoice letter", "## Payment\n\nPlease pay **soon**.", space="private")
r = export(Fr, FP, "pdf")
check(r.status_code == 200 and "Invoice letter" in pdf_text(r.content) and "Payment" in pdf_text(r.content), "#5524: a freelancer exports her private page as PDF")
r = export(Fr, FP, "docx")
check(r.status_code == 200 and "Please pay" in zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode(), "#5524: ... and as Word")
check(export(A, FP, "pdf").status_code == 404, "#5524: the admin of the instance does not read the freelancer's page")

sys.exit(kt.done("p21151_d_wiki_export"))
