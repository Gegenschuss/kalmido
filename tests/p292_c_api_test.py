#!/usr/bin/env python3
"""2.92.0 API tests (part C, #1926): preview and text of Word / Excel files, "Summarise" by an agent.
 - GET /api/attachments/{id}/preview of a .docx: the JSON model (headings from the style names, bold / italic runs, bullet
   and numbered list items, a table), never the file's XML; of an .xlsx: sheets with their names, row numbers, shared
   strings, numbers, a date and a percentage as text, a formula's stored result
 - refused cleanly (422 + code, never a 500): a zip bomb (too_large), an XML part with a DOCTYPE (unsafe), a broken archive
   (unreadable), an old .doc (old); a PDF: 415 (it has its own viewer); the result is cached per content
 - the same for project files (GET /api/list-files/{id}/preview) and Ablage files (GET /api/files/nodes/{id}/preview)
 - rights as the download: another organisation, a person without it, an unknown id -> 404
 - agents: GET /api/v1/attachments/{id}/text of a .docx / .xlsx brings its text; the search finds a task by a word of its
   .docx (the background text queue)
 - GET /api/attachments/{id}/agents: only active agents that see the task with its files (none without collaboration
   partner, a paused agent or one limited to other lists is missing); the comment that mentions the agent ("Summarise")
   brings it a mention event with the attachment id in the text
 - a person without an organisation (personal space) with her own agent: preview, text and the summarise list work
Test files are made here with zipfile; invented words only.
tenant-matrix: attachment, file
usage: p292_c_api_test.py <datadir>"""
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
V = B + "/api/v1"
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def zipped(parts, big=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
        if big:
            z.writestr(big[0], b"\0" * big[1])
    return b.getvalue()


def run(text, b=False, i=False):
    pr = ("<w:b/>" if b else "") + ("<w:i/>" if i else "")
    return f'<w:r>{"<w:rPr>" + pr + "</w:rPr>" if pr else ""}<w:t xml:space="preserve">{text}</w:t></w:r>'


def para(runs, style=None, num=None):
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + (f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr>' if num else "")
    return f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}{runs}</w:p>'


def make_docx(body_xml, doctype=False):
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    if doctype:
        head += '<!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;">]>'
    return zipped({
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "word/document.xml": f'{head}<w:document {W_NS}><w:body>{body_xml}</w:body></w:document>',
        # a German Word: the style ids are translated, the names stay English
        "word/styles.xml": f'<?xml version="1.0"?><w:styles {W_NS}><w:style w:type="paragraph" w:styleId="berschrift1"><w:name w:val="heading 1"/></w:style>'
                           f'<w:style w:type="paragraph" w:styleId="berschrift2"><w:name w:val="heading 2"/></w:style></w:styles>',
        "word/numbering.xml": f'<?xml version="1.0"?><w:numbering {W_NS}>'
                              '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                              '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
                              '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>',
    })


DOCX_BODY = (para(run("Projektauftrag Leuchtturm"), "berschrift1")
             + para(run("Der Auftrag ") + run("Möwenfutter", b=True) + run(" kommt ") + run("pünktlich", i=True) + run("."))
             + para(run("Erster Punkt"), num=1) + para(run("Zweiter Punkt"), num=1)
             + para(run("Schritt eins"), num=2)
             + para(run("Kosten"), "berschrift2")
             + f'<w:tbl><w:tr><w:tc>{para(run("Posten"))}</w:tc><w:tc>{para(run("Betrag"))}</w:tc></w:tr>'
               f'<w:tr><w:tc>{para(run("Laterne"))}</w:tc><w:tc>{para(run("120"))}</w:tc></w:tr></w:tbl>'
             + para(run("&lt;script&gt;alert(1)&lt;/script&gt; bleibt Text")))
DOCX = make_docx(DOCX_BODY)
SERIAL = 46000
DAY = (date(1899, 12, 30) + timedelta(days=SERIAL)).isoformat()


def make_xlsx():
    wb = (f'<?xml version="1.0"?><workbook {S_NS} {R_NS}><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/>'
          f'<sheet name="Notizen" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
    ss = f'<?xml version="1.0"?><sst {S_NS}><si><t>Posten</t></si><si><t>Betrag</t></si><si><r><t>Kompass</t></r><r><t>nadel</t></r></si></sst>'
    styles = (f'<?xml version="1.0"?><styleSheet {S_NS}><cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="9"/></cellXfs></styleSheet>')
    s1 = (f'<?xml version="1.0"?><worksheet {S_NS}><sheetData>'
          '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
          '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>12.5</v></c><c r="C2" s="1"><v>%d</v></c></row>'
          '<row r="4"><c r="A4" t="inlineStr"><is><t>Summe</t></is></c><c r="B4"><f>SUM(B2:B3)</f><v>12.5</v></c><c r="D4" s="2"><v>0.19</v></c></row>'
          '</sheetData></worksheet>') % SERIAL
    s2 = f'<?xml version="1.0"?><worksheet {S_NS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Zweites Blatt</t></is></c></row></sheetData></worksheet>'
    return zipped({"[Content_Types].xml": "<Types/>", "xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels,
                   "xl/sharedStrings.xml": ss, "xl/styles.xml": styles, "xl/worksheets/sheet1.xml": s1, "xl/worksheets/sheet2.xml": s2})


XLSX = make_xlsx()
BOMB = zipped({"word/document.xml": f'<w:document {W_NS}><w:body/></w:document>'}, big=("word/media/x.bin", 80 * 1024 * 1024))
UNSAFE = make_docx(para(run("&b;")), doctype=True)
BROKEN = b"PK\x03\x04" + b"\x01" * 300
OLD_DOC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600

# ---------------------------------------------------------------------------------------------------------- setup
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/orgs", json={"name": "Other Co"})
O2 = r.json()["id"] if r.ok else 0
A.post(B + "/api/users", json={"username": "zoe", "display_name": "Zoe", "password": "password123", "orgs": [O2], "email": "zoe@example.com"})
Zo = sess("zoe")
ERIN = A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin", "password": "password123", "orgs": [],
                                       "email": "erin@example.com"}).json()["id"]
Er = sess("erin")
Er.patch(B + "/api/settings", json={"lang": "en"})


def agent(name, scopes, **kw):
    r = A.post(B + "/api/admin/agents", json={"scopes": scopes, "username": name, "display_name": name.title(), **kw})
    check(r.ok, f"setup: agent {name} " + r.text[:200])
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


L = Bo.post(B + "/api/lists", json={"name": "Lighthouse", "kind": "project"}).json()["id"]
T = Bo.post(B + "/api/tasks", json={"title": "Order", "list_id": L}).json()["id"]


def upload(s, tid, name, data, mime):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, mime)})
    check(r.ok, f"setup: upload {name} {r.status_code} " + r.text[:200])
    return dbx("SELECT id FROM attachments WHERE task_id=? AND name=? ORDER BY id DESC LIMIT 1", (tid, name))[0][0]


F_DOCX = upload(Bo, T, "auftrag.docx", DOCX, DOCX_MIME)
F_XLSX = upload(Bo, T, "budget.xlsx", XLSX, XLSX_MIME)
F_BOMB = upload(Bo, T, "bomb.docx", BOMB, DOCX_MIME)
F_UNSAFE = upload(Bo, T, "entities.docx", UNSAFE, DOCX_MIME)
F_BROKEN = upload(Bo, T, "broken.xlsx", BROKEN, XLSX_MIME)
F_OLD = upload(Bo, T, "old.doc", OLD_DOC, "application/msword")
F_PDF = upload(Bo, T, "plain.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")


def pv(s, aid):
    return s.get(B + f"/api/attachments/{aid}/preview")


# ---------------------------------------------------------------------------------------------------------- docx model
r = pv(Bo, F_DOCX)
j = r.json() if r.ok else {}
check(r.status_code == 200 and j.get("type") == "docx" and j.get("name") == "auftrag.docx", f"#1926: docx preview {r.status_code} {r.text[:300]}")
bl = j.get("blocks") or []
kinds = [b["t"] for b in bl]
check(kinds[:1] == ["h"] and bl[0]["l"] == 1 and bl[0]["r"][0]["x"] == "Projektauftrag Leuchtturm",
      f"#1926: a heading from the style name (German style id) {bl[:1]}")
p1 = bl[1]["r"] if len(bl) > 1 else []
check(any(x["x"] == "Möwenfutter" and x.get("b") == 1 for x in p1) and any(x["x"] == "pünktlich" and x.get("i") == 1 for x in p1)
      and "".join(x["x"] for x in p1) == "Der Auftrag Möwenfutter kommt pünktlich.", f"#1926: bold / italic runs {p1}")
lis = [b for b in bl if b["t"] == "li"]
check(len(lis) == 3 and lis[0]["o"] == 0 and lis[2]["o"] == 1, f"#1926: bullet and numbered list items {lis}")
check(any(b["t"] == "h" and b["l"] == 2 for b in bl), "#1926: a second-level heading")
tb = next((b for b in bl if b["t"] == "tbl"), {})
check(tb.get("rows") == [["Posten", "Betrag"], ["Laterne", "120"]], f"#1926: the table's cells {tb}")
check("<script>" in json.dumps(bl, ensure_ascii=False) and "w:document" not in r.text and "text" not in j,
      "#1926: text stays text (the client escapes it), no XML of the file, no plain text field in the preview")
check(r.headers.get("Cache-Control", "").startswith("private"), "#1926: the preview is not cached by proxies")
cache = os.path.join(DATA, "textcache")
check(os.path.isdir(cache) and any(n.endswith(".json") for n in os.listdir(cache)), "#1926: the model is cached per content")
check(pv(Bo, F_DOCX).json().get("blocks") == bl, "#1926: the second call (cache) gives the same model")

# ---------------------------------------------------------------------------------------------------------- xlsx model
r = pv(Bo, F_XLSX)
j = r.json() if r.ok else {}
check(r.status_code == 200 and j.get("type") == "xlsx" and [s["name"] for s in j.get("sheets", [])] == ["Budget", "Notizen"]
      and j.get("sheets_total") == 2, f"#1926: xlsx preview with both sheets {r.text[:300]}")
rows = (j.get("sheets") or [{}])[0].get("rows") or []
check([x["n"] for x in rows] == [1, 2, 4], f"#1926: row numbers kept (an empty row is skipped) {rows}")
check(rows and rows[0]["c"] == ["Posten", "Betrag"], "#1926: shared strings")
check(len(rows) > 1 and rows[1]["c"] == ["Kompassnadel", "12.5", DAY], f"#1926: rich text, a number, a date as text {rows[1:2]} {DAY}")
check(len(rows) > 2 and rows[2]["c"] == ["Summe", "12.5", "", "19 %"], f"#1926: inline string, a formula's result, a gap, a percentage {rows[2:3]}")
check((j.get("sheets") or [{}])[0].get("cols") == 4, "#1926: the sheet's width")

# ---------------------------------------------------------------------------------------------------------- refused cleanly
for aid, code, what in ((F_BOMB, "too_large", "a zip bomb"), (F_UNSAFE, "unsafe", "a DOCTYPE / ENTITY"),
                        (F_BROKEN, "unreadable", "a broken archive"), (F_OLD, "old", "an old .doc")):
    r = pv(Bo, aid)
    check(r.status_code == 422 and r.json().get("code") == code and r.json().get("error"), f"#1926: {what} -> 422 {code} {r.status_code} {r.text[:200]}")
check(pv(Bo, F_PDF).status_code == 415, "#1926: a PDF has its own viewer (415)")
check(pv(Bo, 999999).status_code == 404, "#1926: an unknown id: 404")
check(Bo.get(B + f"/api/attachments/{F_BOMB}").ok, "#1926: the refused file can still be downloaded")

# ---------------------------------------------------------------------------------------------------------- the boundary
for s, who in ((Zo, "another organisation"), (Er, "a person without an organisation"), (A, "the instance admin outside the list")):
    check(pv(s, F_DOCX).status_code == 404, f"#1926: {who}: preview 404")
    check(s.get(B + f"/api/attachments/{F_DOCX}/agents").status_code == 404, f"#1926: {who}: summarise list 404")

# ---------------------------------------------------------------------------------------------------------- agents read the text
CL, CLH = agent("claude", ["read", "tasks:write", "comments", "attachments:read"])
r = requests.get(V + f"/attachments/{F_DOCX}/text", headers=CLH)
check(r.status_code == 404, f"#1926: an agent outside the list gets 404 {r.status_code}")
check(Bo.get(B + f"/api/attachments/{F_DOCX}/agents").json().get("agents") == [], "#1926: no agent in the list: no summarise button")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "edit"}).ok or
      A.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the list")
r = requests.get(V + f"/attachments/{F_DOCX}/text", headers=CLH)
j = r.json() if r.ok else {}
check(r.ok and j.get("kind") == "docx" and "Möwenfutter" in (j.get("text") or "") and "Laterne | 120" in j.get("text", "")
      and j["text"].startswith("# Projektauftrag Leuchtturm"), f"#1926: an agent reads the text of a .docx {r.text[:300]}")
r = requests.get(V + f"/attachments/{F_XLSX}/text", headers=CLH)
j = r.json() if r.ok else {}
check(r.ok and j.get("kind") == "xlsx" and "## Budget" in (j.get("text") or "") and "Kompassnadel | 12.5" in j.get("text", "")
      and "Zweites Blatt" in j.get("text", "") and j.get("sheets") == 2, f"#1926: an agent reads the text of an .xlsx {r.text[:300]}")
j = requests.get(V + f"/attachments/{F_BOMB}/text", headers=CLH).json()
check(j.get("error") == "too_large" and j.get("message"), f"#1926: the agent gets the reason for a refused file {j}")

# ---------------------------------------------------------------------------------------------------------- the search
st = until(lambda: (lambda x: x if x and x[0] in ("found", "none", "error", "skip") else None)(
    (dbx("SELECT state, method FROM file_text WHERE kind='att' AND ref_id=?", (F_DOCX,)) or [None])[0]), 120)
check(st and st[0] == "found" and st[1] == "office", f"#1926: the text queue reads the .docx ({st})")
hits = {t["id"]: t for t in Bo.get(B + "/api/tasks", params={"scope": "search", "q": "möwenfutter"}).json().get("tasks", [])}
check(T in hits and hits[T].get("file_hit") == "auftrag.docx", f"#1926: the search finds the task by a word of its .docx {list(hits)}")
hits = {t["id"] for t in Zo.get(B + "/api/tasks", params={"scope": "search", "q": "möwenfutter"}).json().get("tasks", [])}
check(T not in hits, "#1926: another organisation finds nothing")

# ---------------------------------------------------------------------------------------------------------- summarise
j = Bo.get(B + f"/api/attachments/{F_DOCX}/agents").json()
check([a["id"] for a in j.get("agents", [])] == [CL] and j["agents"][0]["name"] == "Claude" and j.get("task_id") == T,
      f"#1926: the agent of the list can summarise {j}")
cur = dbx("SELECT COALESCE(MAX(id), 0) FROM agent_events WHERE agent_id=?", (CL,))[0][0]
body = f"<@{CL}> Please summarize the attachment “auftrag.docx” (attachment_id {F_DOCX}) and post the summary as a comment."
r = Bo.post(B + f"/api/tasks/{T}/comments", json={"body": body})
check(r.ok and f"<@{CL}>" in r.json().get("body", ""), f"#1926: the comment keeps the mention {r.text[:200]}")
ev = dbx("SELECT event, payload FROM agent_events WHERE agent_id=? AND id>? ORDER BY id", (CL, cur))
m = [json.loads(p) for e, p in ev if e == "mention"]
check(m and f"attachment_id {F_DOCX}" in json.dumps(m[0], ensure_ascii=False), f"#1926: the agent hears the mention with the attachment id {ev[:2]}")
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(L + 1000), CL), write=True)
check(Bo.get(B + f"/api/attachments/{F_DOCX}/agents").json().get("agents") == [], "#1926: an agent limited to other lists is missing")
dbx("UPDATE agents SET list_ids='' WHERE user_id=?", (CL,), write=True)
dbx("UPDATE agents SET enabled=0 WHERE user_id=?", (CL,), write=True)
check(Bo.get(B + f"/api/attachments/{F_DOCX}/agents").json().get("agents") == [], "#1926: a paused agent is missing")
dbx("UPDATE agents SET enabled=1 WHERE user_id=?", (CL,), write=True)

# ---------------------------------------------------------------------------------------------------------- project + Ablage files
r = Bo.post(B + f"/api/lists/{L}/files", files={"file": ("plan.xlsx", XLSX, XLSX_MIME)})
check(r.ok, f"setup: project file {r.status_code} {r.text[:200]}")
LF = dbx("SELECT id FROM list_files WHERE list_id=? ORDER BY id DESC LIMIT 1", (L,))[0][0]
r = Bo.get(B + f"/api/list-files/{LF}/preview")
check(r.ok and r.json().get("type") == "xlsx", f"#1926: a project file's preview {r.status_code} {r.text[:200]}")
check(Zo.get(B + f"/api/list-files/{LF}/preview").status_code == 404, "#1926: a project file of another organisation: 404")
r = Bo.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("brief.docx", DOCX, DOCX_MIME)})
check(r.status_code == 201, f"setup: Ablage upload {r.status_code} {r.text[:200]}")
NF = r.json()["items"][0]["id"] if r.ok else 0
r = Bo.get(B + f"/api/files/nodes/{NF}/preview")
check(r.ok and r.json().get("type") == "docx" and r.json()["blocks"][0]["t"] == "h", f"#1926: an Ablage file's preview {r.status_code} {r.text[:200]}")
check(Zo.get(B + f"/api/files/nodes/{NF}/preview").status_code == 404 and Er.get(B + f"/api/files/nodes/{NF}/preview").status_code == 404,
      "#1926: an Ablage file of someone else: 404")

# ---------------------------------------------------------------------------------------------------------- without an organisation (Brief-P4)
EA, EAH = agent("erinbot", ["read", "comments", "attachments:read"], owner_id=ERIN)
EL = Er.post(B + "/api/lists", json={"name": "Freelance"}).json()["id"]
ET_ = Er.post(B + "/api/tasks", json={"title": "Client brief", "list_id": EL}).json()["id"]
EF = upload(Er, ET_, "angebot.docx", DOCX, DOCX_MIME)
r = pv(Er, EF)
check(r.ok and r.json().get("type") == "docx", f"#1926 P4: a person without an organisation sees the preview {r.status_code} {r.text[:200]}")
check(Er.get(B + f"/api/attachments/{EF}/agents").json().get("agents") == [], "#1926 P4: her agent not yet in the list: no button")
r = Er.put(B + f"/api/lists/{EL}/members", json={"user_id": EA, "role": "edit"})
check(r.ok, f"setup P4: her own agent in her list {r.status_code} {r.text[:200]}")
j = Er.get(B + f"/api/attachments/{EF}/agents").json()
check([a["id"] for a in j.get("agents", [])] == [EA], f"#1926 P4: her own agent can summarise {j}")
r = requests.get(V + f"/attachments/{EF}/text", headers=EAH)
check(r.ok and "Möwenfutter" in r.json().get("text", ""), f"#1926 P4: her agent reads the .docx {r.status_code}")
check(pv(Bo, EF).status_code == 404 and requests.get(V + f"/attachments/{EF}/text", headers=CLH).status_code == 404,
      "#1926 P4: another person and another agent: 404")
r = Er.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("liste.xlsx", XLSX, XLSX_MIME)})
EN = r.json()["items"][0]["id"] if r.status_code == 201 else 0
check(EN and Er.get(B + f"/api/files/nodes/{EN}/preview").json().get("type") == "xlsx", "#1926 P4: her Ablage file's preview")

# ---------------------------------------------------------------------------------------------------------- collaboration off
r = A.patch(B + "/api/admin/settings", json={"collab_all": False})
check(r.ok and Bo.get(B + f"/api/attachments/{F_DOCX}/agents").json().get("agents") == [], f"#1926: collaboration off: nobody to summarise {r.status_code}")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

print(f"p292_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
