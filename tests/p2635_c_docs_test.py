#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.635.0 part C (#4807): small Paperless gaps of the documents. Invented words and files only (made here with zipfile).
 (a) Office files as documents: a .docx / .xlsx / .odt / .ods gets its text in the recognition (method office, no longer
     'none'), a preview image (from the preview model) and is found by a word of it; the OpenDocument files open in the
     preview (GET /api/files/nodes/{id}/preview: the same small model, never the XML); an ODF part with a DOCTYPE is
     refused (failed, never a 500), a sheet with a million repeated empty rows reads quickly; .rtf / .pptx stay files
     without text (done, method none - the document view shows the hint)
 - a person without an organisation (freelancer-matrix: docs): the same for an .odt in the own space
usage: p2635_c_docs_test.py <datadir>"""
import io
import sys
import zipfile

import kt
from kt import B, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P2635C")
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

# freelancer-matrix: docs
nid = upload(Fr, "eigen.odt", odt("Bernsteinfuchs"), ODT_MIME)
d = done(Fr, nid)
check(d.get("method") == "office" and nid in (found(Fr, "bernsteinfuchs") or []), f"#4807 (a) freelancer: an .odt is read and found {d.get('method')}")
check(nid not in (found(A, "bernsteinfuchs") or []), "#4807 (a) ... and only in her own space")

sys.exit(kt.done("p2635_c_docs"))
