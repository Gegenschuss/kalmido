#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.635.0 part C (#4807): small Paperless gaps of the documents. Invented words and files only (made here with zipfile).
 (a) Office files as documents: a .docx / .xlsx / .odt / .ods gets its text in the recognition (method office, no longer
     'none'), a preview image (from the preview model) and is found by a word of it; the OpenDocument files open in the
     preview (GET /api/files/nodes/{id}/preview: the same small model, never the XML); an ODF part with a DOCTYPE is
     refused (failed, never a 500), a sheet with a million repeated empty rows reads quickly; .rtf / .pptx stay files
     without text (done, method none - the document view shows the hint)
 (d) notes on a document: several with author and time, seen by everybody who sees the document (also in its view), written
     with edit (403 with view, 404 without any right), sealed with the area key, found by a word / a prefix and gone from the
     index when deleted; deleted by someone with edit or by the author (also after the right fell to view); db.bump
 (c) custom field types long text and link to documents: a long text keeps its lines, is indexed; a link only to documents
     of the same workspace the person sees (refused: not seen, other workspace, itself, a Paperless reference, more than 20),
     shown only to who sees the linked document, a link one cannot see stays when another is set / cleared
 (b) the text recognition languages of an area (Settings > Documents): the installed ones (no osd), deu+eng by default,
     KALMIDO_OCR_LANGS the cap (ocr.py loaded as a single file); a language not installed / too many are refused, only the
     area's admins change it, none = the default again
 - a person without an organisation (the documents' area "files" of the freelancer matrix): the same for an .odt in the own space
usage: p2635_c_docs_test.py <datadir>"""
import importlib.util
import io
import os
import sys
import zipfile

import kt
from kt import B, check, sess, until
from freelancer_fixture import freelancer, org_join

kt.fresh(env={"KALMIDO_SECRET_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="}, prefix="P2635C")  # a server key: values are sealed
A = kt.setup()
FID, Fr = freelancer(B, A)

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
O_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ODT_MIME = "application/vnd.oasis.opendocument.text"
ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"


def zipped(parts, mime=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        if mime:
            z.writestr(zipfile.ZipInfo("mimetype"), mime)
        for k, v in parts.items():
            z.writestr(k, v)
    return b.getvalue()


def docx(word):
    return zipped({"word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document {W_NS}><w:body>'
                   f'<w:p><w:r><w:t>Vertrag {word} Wolkenschloss</w:t></w:r></w:p></w:body></w:document>'})


def xlsx(word):
    return zipped({
        "xl/workbook.xml": f'<workbook {S_NS} {R_NS}><sheets><sheet name="Plan" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst {S_NS}><si><t>{word}</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {S_NS}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></row></sheetData></worksheet>'})


def odt(word, doctype=False):
    head = '<?xml version="1.0" encoding="UTF-8"?>' + ('<!DOCTYPE x [<!ENTITY e "boom">]>' if doctype else '')
    return zipped({"content.xml": f'{head}<office:document-content {O_NS}><office:body><office:text>'
                   f'<text:h text:outline-level="2">Kapitel Nebelhorn</text:h>'
                   f'<text:p>Brief <text:span>{word}</text:span><text:s text:c="2"/>Ende</text:p>'
                   f'<text:list><text:list-item><text:p>Punkt Eins</text:p></text:list-item></text:list>'
                   f'<table:table table:name="T"><table:table-row><table:table-cell><text:p>Zelle Morgentau</text:p></table:table-cell></table:table-row></table:table>'
                   f'</office:text></office:body></office:document-content>'}, ODT_MIME)


def ods(word):
    return zipped({"content.xml": f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {O_NS}><office:body><office:spreadsheet>'
                   f'<table:table table:name="Kasse"><table:table-row><table:table-cell office:value-type="string"><text:p>{word}</text:p></table:table-cell>'
                   f'<table:table-cell table:number-columns-repeated="16000"/><table:table-cell office:value-type="float" office:value="7.5"><text:p>7,5</text:p></table:table-cell></table:table-row>'
                   f'<table:table-row table:number-rows-repeated="1048570"><table:table-cell table:number-columns-repeated="1024"/></table:table-row>'
                   f'<table:table-row><table:table-cell><text:p>Schluss</text:p></table:table-cell></table:table-row>'
                   f'</table:table></office:spreadsheet></office:body></office:document-content>'}, ODS_MIME)


def upload(s, name, data, mime):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, mime))])
    check(r.ok and r.json().get("ids"), f"{name}: uploaded {r.status_code} {r.text[:160]}")
    return r.json()["ids"][0] if r.ok and r.json().get("ids") else 0


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs) or {}


def found(s, q):
    r = s.get(B + "/api/docs", params={"facets": "0", "q": q})
    return [d["id"] for d in r.json()["docs"]] if r.ok else None


# ---- (a) Office files get their text, a preview image and are found
for name, data, mime, word in (("vertrag.docx", docx("Quarzsplitter"), DOCX_MIME, "quarzsplitter"),
                               ("plan.xlsx", xlsx("Kupferamsel"), XLSX_MIME, "kupferamsel"),
                               ("brief.odt", odt("Zinnober"), ODT_MIME, "zinnober"),
                               ("kasse.ods", ods("Lavendelweg"), ODS_MIME, "lavendelweg")):
    nid = upload(A, name, data, mime)
    d = done(A, nid)
    check(d.get("state") == "done" and d.get("method") == "office", f"#4807 (a) {name}: read as an Office file (was method none) {d.get('state')} {d.get('method')} {d.get('error')}")
    full = A.get(B + f"/api/docs/{nid}").json()
    check(word in (full.get("text") or "").lower(), f"#4807 (a) {name}: its text is the document's text {(full.get('text') or '')[:120]!r}")
    check(d.get("thumb") is True, f"#4807 (a) {name}: a preview image was made")
    r = A.get(B + f"/api/docs/{nid}/thumb")
    check(r.ok and r.content[:2] == b"\xff\xd8", f"#4807 (a) {name}: the preview image is a JPEG {r.status_code}")
    check(nid in (found(A, word) or []), f"#4807 (a) {name}: found by a word of it")
    if name == "brief.odt":
        p = A.get(B + f"/api/files/nodes/{nid}/preview").json()
        kinds = [b.get("t") for b in p.get("blocks") or []]
        check(p.get("type") == "odt" and kinds[:1] == ["h"] and "li" in kinds and "tbl" in kinds and "<" not in str(p),
              f"#4807 (a) the .odt preview model: heading, list, table, no XML {str(p)[:200]}")
        check("Zinnober  Ende" in (full.get("text") or ""), "#4807 (a) <text:s c=2/> keeps its two spaces")
    if name == "kasse.ods":
        p = A.get(B + f"/api/files/nodes/{nid}/preview").json()
        sh = (p.get("sheets") or [{}])[0]
        rows = sh.get("rows") or []
        check(p.get("type") == "ods" and sh.get("name") == "Kasse" and len(rows) == 2 and rows[1]["n"] == 1048572,
              f"#4807 (a) the .ods: repeated empty rows only counted, the last row keeps its number {str(rows)[:200]}")
        check(sh.get("truncated") is True, "#4807 (a) a value behind 16000 empty columns is cut, not made")

bad = upload(A, "falle.odt", odt("Giftzahn", doctype=True), ODT_MIME)
d = done(A, bad)
check(d.get("state") == "failed" and d.get("error") == "unreadable", f"#4807 (a) an ODF part with a DOCTYPE is refused {d.get('state')} {d.get('error')}")
check(bad not in (found(A, "giftzahn") or []), "#4807 (a) ... and its words are not indexed")
for name, data, mime in (("alt.rtf", b"{\\rtf1\\ansi Rosenquarz}", "application/rtf"),
                         ("folien.pptx", zipped({"ppt/presentation.xml": "<p/>"}), "application/vnd.openxmlformats-officedocument.presentationml.presentation")):
    nid = upload(A, name, data, mime)
    d = done(A, nid)
    check(d.get("state") == "done" and d.get("method") == "none", f"#4807 (a) {name} stays a file without text {d.get('state')} {d.get('method')}")
check(found(A, "rosenquarz") == [], "#4807 (a) the RTF is not read as plain text")

# freelancer-matrix: files
nid = upload(Fr, "eigen.odt", odt("Bernsteinfuchs"), ODT_MIME)
d = done(Fr, nid)
check(d.get("method") == "office" and nid in (found(Fr, "bernsteinfuchs") or []), f"#4807 (a) freelancer: an .odt is read and found {d.get('method')}")
check(nid not in (found(A, "bernsteinfuchs") or []), "#4807 (a) ... and only in her own space")

# ---- (d) notes on a document: several, author + time, seen by all who see it, written with edit, sealed, searchable
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
ORG = r.json()["id"]
Bo = sess("bob")
for u in ("carol", "dave"):
    Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"})
    org_join(B, u, ORG)
Ca, Da, Er = sess("carol"), sess("dave"), sess("erin")
for s_ in (Bo, Ca, Da, Er):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = Bo.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("akte.docx", docx("Aktenzeichen"), DOCX_MIME))])
DN = r.json()["ids"][0] if r.ok else 0
done(Bo, DN)
check(Bo.post(B + f"/api/files/nodes/{DN}/shares", json={"user_id": ids["carol"], "role": "view"}).ok, "setup: shared with carol (view)")
check(Bo.post(B + f"/api/files/nodes/{DN}/shares", json={"user_id": ids["dave"], "role": "edit"}).ok, "setup: shared with dave (edit)")
NB = f"/api/docs/{DN}/notes"
ver0 = int(kt.dbx("SELECT value FROM settings WHERE key='version'")[0][0])
r = Da.post(B + NB, json={"text": "Rueckruf bei Hummelwiese\nzweite Zeile"})
check(r.status_code == 201 and r.json()["note"]["author"]["name"] == "Dave" and r.json()["note"]["created_at"], f"#4807 (d) dave (edit) writes a note {r.status_code} {r.text[:160]}")
NOTE1 = r.json()["note"]["id"] if r.status_code == 201 else 0
check(int(kt.dbx("SELECT value FROM settings WHERE key='version'")[0][0]) > ver0, "#4807 (d) other devices learn of it (db.bump)")
check(Ca.post(B + NB, json={"text": "nope"}).status_code == 403, "#4807 (d) carol (view) writes none")
# tenant-matrix: document
check(Er.get(B + NB).status_code == 404 and Er.post(B + NB, json={"text": "x"}).status_code == 404, "#4807 (d) erin (no right) sees none, writes none")
check(Er.delete(B + f"{NB}/{NOTE1}").status_code == 404, "#4807 (d) erin deletes none of another organisation's notes")
r = Bo.post(B + NB, json={"text": "Frist pruefen Kiefernzapfen"})
check(r.status_code == 201, "#4807 (d) bob (owner) writes a second one")
NOTE2 = r.json()["note"]["id"] if r.status_code == 201 else 0
j = Ca.get(B + NB).json()
check([n["text"] for n in j["notes"]] == ["Rueckruf bei Hummelwiese\nzweite Zeile", "Frist pruefen Kiefernzapfen"]
      and [n["author"]["name"] for n in j["notes"]] == ["Dave", "Bob"] and not any(n["can_delete"] for n in j["notes"]),
      f"#4807 (d) carol sees both, oldest first, with their authors, deletes none {j}")
full = Ca.get(B + f"/api/docs/{DN}").json()
check(len(full.get("notes") or []) == 2, "#4807 (d) the document view brings its notes")
raw = [x[0] for x in kt.dbx("SELECT text FROM doc_notes WHERE node_id=? ORDER BY id", (DN,))]
check(len(raw) == 2 and all(x.startswith("kenc1:") and "Hummelwiese" not in x for x in raw), f"#4807 (d) the texts are sealed with the area key {[x[:12] for x in raw]}")
check(DN in (found(Ca, "hummelwiese") or []) and DN in (found(Ca, "kiefernz") or []), "#4807 (d) found by a word / a prefix of a note")
check(Da.post(B + NB, json={"text": "x" * 5001}).status_code == 400 and Da.post(B + NB, json={"text": "  "}).status_code == 400,
      "#4807 (d) an empty or too long note is refused")
check(Ca.delete(B + f"{NB}/{NOTE1}").status_code == 403, "#4807 (d) carol (view) deletes no one else's note")
r = Da.delete(B + f"{NB}/{NOTE2}")
check(r.ok and [n["id"] for n in r.json()["notes"]] == [NOTE1], "#4807 (d) dave (edit) deletes bob's note")
check(DN not in (found(Ca, "kiefernzapfen") or []), "#4807 (d) ... and its words leave the index")
sid = kt.dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (DN, ids["dave"]))[0][0]
check(Bo.patch(B + f"/api/files/shares/{sid}", json={"role": "view"}).ok, "setup: dave only views now")
check(Da.post(B + NB, json={"text": "y"}).status_code == 403, "#4807 (d) dave (view now) writes none")
check(Da.delete(B + f"{NB}/{NOTE1}").ok and Ca.get(B + NB).json()["notes"] == [], "#4807 (d) the author deletes his own note with view")
check(Bo.delete(B + f"{NB}/999999").status_code == 404, "#4807 (d) an unknown note: 404")

# freelancer-matrix: files
r = Fr.post(B + f"/api/docs/{nid}/notes", json={"text": "Eigene Notiz Ringelblume"})
check(r.status_code == 201 and r.json()["note"]["can_delete"], f"#4807 (d) freelancer: a note on her own document {r.status_code}")
check(nid in (found(Fr, "ringelblume") or []) and Fr.get(B + f"/api/docs/{nid}/notes").json()["notes"][0]["author"]["id"] == FID,
      "#4807 (d) freelancer: found by it, she is its author")
check(A.get(B + f"/api/docs/{nid}/notes").status_code == 404, "#4807 (d) freelancer: nobody else sees her notes")
check(Fr.delete(B + f"/api/docs/{nid}/notes/{r.json()['note']['id']}").ok, "#4807 (d) freelancer: deletes it")

# ---- (b) the text recognition languages of an area: from the installed ones, deu+eng by default, KALMIDO_OCR_LANGS the cap
def ocr_mod(cap=None):
    old = os.environ.pop("KALMIDO_OCR_LANGS", None)
    if cap:
        os.environ["KALMIDO_OCR_LANGS"] = cap
    spec = importlib.util.spec_from_file_location("ocr_p2635", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido", "docs", "ocr.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    os.environ.pop("KALMIDO_OCR_LANGS", None)
    if old is not None:
        os.environ["KALMIDO_OCR_LANGS"] = old
    return m


HAVE = {"List", "of", "available", "languages", "in", "/usr/share/tessdata", "(5):", "deu", "eng", "fra", "ita", "osd"}  # as --list-langs answers
o1 = ocr_mod()
check(o1.ocr_choices(HAVE) == ["deu", "eng", "fra", "ita"], f"#4807 (b) the choice: the installed languages, no osd {o1.ocr_choices(HAVE)}")
check(o1.ocr_langs("fr", HAVE, base=["ita", "deu"]) == ("ita+deu", []), "#4807 (b) the area's languages are taken as they are (no app language)")
check(o1.ocr_langs("de", HAVE, base=["ita", "xyz"]) == ("ita", ["xyz"]), "#4807 (b) a language that is not installed is left out and reported")
check(o1.ocr_langs("fr", HAVE) == ("fra+deu+eng", []), "#4807 (b) without a choice: as before (app language + deu+eng)")
o2 = ocr_mod("deu+fra")
check(o2.ocr_choices(HAVE) == ["deu", "fra"] and o2.ocr_langs(None, HAVE, base=["ita", "fra"]) == ("fra", []),
      "#4807 (b) KALMIDO_OCR_LANGS is the cap of the choice")

st = A.get(B + "/api/docs/settings", params={"ws": "private"}).json()
ol = st.get("ocr_langs") or {}
if st.get("ocr"):
    check([x["code"] for x in ol.get("choices") or []] == ["deu", "eng", "fra", "ita", "nld", "spa"] and ol.get("chosen") == ["deu", "eng"]
          and ol.get("custom") is False and {"code": "fra", "name": "Français"} in ol["choices"], f"#4807 (b) settings: the installed languages, deu+eng by default {ol}")
    r = A.put(B + "/api/docs/settings", json={"ws": "private", "ocr_langs": ["fra", "deu"]})
    check(r.ok and r.json()["ocr_langs"]["chosen"] == ["fra", "deu"] and r.json()["ocr_langs"]["custom"] is True, f"#4807 (b) French + German chosen {r.text[:200]}")
    for bad in (["xyz"], ["osd"], ["deu", "eng", "fra", "ita", "nld"], "deu"):
        check(A.put(B + "/api/docs/settings", json={"ws": "private", "ocr_langs": bad}).status_code == 400, f"#4807 (b) refused: {bad}")
    check(A.get(B + "/api/docs/settings", params={"ws": "private"}).json()["ocr_langs"]["chosen"] == ["fra", "deu"], "#4807 (b) ... and the choice stays")
    check(A.put(B + "/api/docs/settings", json={"ws": "private", "ocr_langs": []}).json()["ocr_langs"] == {**ol}, "#4807 (b) none = the default again")
    check(Ca.put(B + "/api/docs/settings", json={"ws": f"org:{ORG}", "ocr_langs": ["eng"]}).status_code in (403, 404), "#4807 (b) a member who is no admin changes nothing")
    check(Bo.put(B + "/api/docs/settings", json={"ws": f"org:{ORG}", "ocr_langs": ["eng"]}).ok, "#4807 (b) the organisation's admin chooses for it")
    # freelancer-matrix: files
    r = Fr.put(B + "/api/docs/settings", json={"ws": "private", "ocr_langs": ["nld"]})
    check(r.ok and r.json()["ocr_langs"]["chosen"] == ["nld"], f"#4807 (b) freelancer: her own area's languages {r.text[:160]}")
else:
    print("NOTE: no Tesseract in this image -- the settings checks of (b) are skipped", flush=True)

# ---- (c) field types long text and link to documents (only documents of the same workspace the person sees, checked
# when set and when shown; a click opens it: the client links #docs/<id>)
def fld(s_, ws, name, typ):
    r = s_.post(B + "/api/docs/fields", json={"ws": ws, "name": name, "type": typ})
    check(r.status_code == 201, f"#4807 (c) a field {name} ({typ}) {r.status_code} {r.text[:120]}")
    return r.json().get("id") if r.status_code == 201 else 0


def cfv(s_, did, fid):
    return next((x for x in s_.get(B + f"/api/docs/{did}").json().get("custom_fields") or [] if x["id"] == fid), {})


FL, FD = fld(Bo, f"org:{ORG}", "Vermerk", "longtext"), fld(Bo, f"org:{ORG}", "Bezug", "documentlink")
LONG = "Lange Zeile mit Feuerlilie\n" + "x" * 3000
check(Bo.patch(B + f"/api/docs/{DN}", json={"custom_fields": {str(FL): LONG}}).ok and cfv(Bo, DN, FL).get("value") == LONG,
      "#4807 (c) a long text keeps its lines and 3000+ characters")
check(DN in (found(Ca, "feuerlilie") or []), "#4807 (c) the long text is in the word index")
r = Bo.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("anlage.docx", docx("Anlage"), DOCX_MIME))])
D2 = r.json()["ids"][0] if r.ok else 0
r = Bo.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("vertraulich.docx", docx("Geheim"), DOCX_MIME))])
D4 = r.json()["ids"][0] if r.ok else 0  # bob's, not linked, dave does not see it
r = Da.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("dave.docx", docx("Dave"), DOCX_MIME))])
D3 = r.json()["ids"][0] if r.ok else 0
done(Bo, D2), done(Da, D3)
r = Bo.patch(B + f"/api/docs/{DN}", json={"custom_fields": {str(FD): str(D2)}})
v = cfv(Bo, DN, FD)
check(r.ok and v.get("type") == "documentlink" and v.get("links") == [{"id": D2, "name": "anlage.docx"}] and v.get("value") == str(D2),
      f"#4807 (c) bob links a document he sees {r.status_code} {v}")
v = cfv(Ca, DN, FD)
check(v.get("links") == [] and v.get("value") is None and v.get("hidden") == 1, f"#4807 (c) carol does not see the linked document: not shown {v}")
check(Bo.patch(B + f"/api/files/shares/{sid}", json={"role": "edit"}).ok, "setup: dave edits again")
for bad, what in ((str(D4), "a document he cannot see"), (f"{D2},{D4}", "a document he cannot see beside one linked already"), (str(nid), "a document of another workspace"), (str(DN), "the document itself"),
                  ("pl:12", "a Paperless reference"), ("abc", "no id"), (",".join(str(D3 + i) for i in range(21)), "more than 20")):
    check(Da.patch(B + f"/api/docs/{DN}", json={"custom_fields": {str(FD): bad}}).status_code == 400, f"#4807 (c) dave links no {what}")
r = Da.patch(B + f"/api/docs/{DN}", json={"custom_fields": {str(FD): str(D3)}})
check(r.ok and [x["id"] for x in cfv(Da, DN, FD).get("links") or []] == [D3], f"#4807 (c) dave links his own document {r.status_code} {r.text[:120]}")
check(sorted(x["id"] for x in cfv(Bo, DN, FD).get("links") or []) == sorted([D2, D3]), "#4807 (c) ... the one he cannot see stays linked")
check(Da.patch(B + f"/api/docs/{DN}", json={"custom_fields": {str(FD): None}}).ok and [x["id"] for x in cfv(Bo, DN, FD).get("links") or []] == [D2],
      "#4807 (c) dave clears the field: only his link goes")

# freelancer-matrix: files
FF = fld(Fr, "private", "Siehe auch", "documentlink")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("zweit.odt", odt("Zweit"), ODT_MIME))])
N2 = r.json()["ids"][0] if r.ok else 0
done(Fr, N2)
r = Fr.patch(B + f"/api/docs/{nid}", json={"custom_fields": {str(FF): str(N2)}})
check(r.ok and [x["id"] for x in cfv(Fr, nid, FF).get("links") or []] == [N2], f"#4807 (c) freelancer: a link between her own documents {r.status_code}")
check(Fr.patch(B + f"/api/docs/{nid}", json={"custom_fields": {str(FF): str(DN)}}).status_code == 400, "#4807 (c) freelancer: no link to another organisation's document")

sys.exit(kt.done("p2635_c_docs"))
