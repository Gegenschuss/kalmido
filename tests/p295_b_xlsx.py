#!/usr/bin/env python3
"""2.95.0 B (#1932): the per diem spreadsheet of the import tests (p295_b_api_test.py, p295_b_ui.js), built with zipfile:
invented people, places and figures; one sheet = one person, a row = a trip, cell comments = note + the split by country.
usage: python3 -I tests/p295_b_xlsx.py      (prints the sample .xlsx as base64, for the UI test)"""
import base64
import io
import sys
import zipfile
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org"


def _cell(ref, v):
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'


def xlsx(sheets):
    """sheets: [(name, rows [[cell, ...]], comments {"G7": text})] -> .xlsx bytes (inline strings, a comments part per sheet
    with its relation, the comment author "Tester" in front of the text as Excel writes it)."""
    ct = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
    parts, sh_xml, wb_rels = {}, [], []
    for i, (name, rows, comments) in enumerate(sheets, 1):
        data = "".join(f'<row r="{r + 1}">' + "".join(_cell(f"{chr(65 + j)}{r + 1}", v) for j, v in enumerate(row) if v != "") + "</row>"
                       for r, row in enumerate(rows))
        parts[f"xl/worksheets/sheet{i}.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS}/spreadsheetml/2006/main"><sheetData>{data}</sheetData></worksheet>'
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        sh_xml.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
        wb_rels.append(f'<Relationship Id="rId{i}" Type="{NS}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        if comments:
            cl = "".join(f'<comment ref="{ref}" authorId="0"><text><r><rPr><b/></rPr><t>Tester:</t></r><r><t xml:space="preserve">\r\n{escape(t)}</t></r></text></comment>'
                         for ref, t in comments.items())
            parts[f"xl/comments{i}.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><comments xmlns="{NS}/spreadsheetml/2006/main"><authors><author>Tester</author></authors><commentList>{cl}</commentList></comments>'
            ct.append(f'<Override PartName="/xl/comments{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
            parts[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS}/package/2006/relationships">'
                                                                f'<Relationship Id="rId1" Type="{NS}/officeDocument/2006/relationships/comments" Target="../comments{i}.xml"/></Relationships>')
    parts["[Content_Types].xml"] = f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{NS}/package/2006/content-types">{"".join(ct)}</Types>'
    parts["_rels/.rels"] = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS}/package/2006/relationships">'
                            f'<Relationship Id="rId1" Type="{NS}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{NS}/spreadsheetml/2006/main" xmlns:r="{NS}/officeDocument/2006/relationships">'
                                f'<sheets>{"".join(sh_xml)}</sheets></workbook>')
    parts["xl/_rels/workbook.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS}/package/2006/relationships">{"".join(wb_rels)}</Relationships>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


HEAD = ["Vom", "bis", "Start", "Ende", "Ort", "Anlass", "MVA"]
BLOCK = ("Auslandspauschalen 2025 (BMF v. 2.12.2024), Land = wo man vor 24 Uhr war:\n"
         "Inland: 1 × 14 € = 14 €\nTschechien: 1 × 21 € + 3 × 32 € = 117 €")
SHEET1 = ("Alice", [
    ["Reise – Arbeitsliste Alice Admin – 2025"], ["Hinweise stehen als Kommentar."], HEAD,
    [45714, 45715, "", "", "Musterstadt", "Dreh Beispiel", 28],                      # row 4: 2025-02-26..27, Germany, a job
    [45808, 45808, "", "", "Testdorf (Niederlande)", "Recherche/Akquise", ""],       # row 5: one day without times -> warn
    [45810, 45810, 0.25, 0.75, "Beispielstadt", "Akquise", 14],                     # row 6: 06:00-18:00 -> 14
    [45764, 45768, "", "", "Beispielort (Tschechien)", "Recherche", 131],           # row 7: the block: Germany + Czechia
    ["kaputt", "", "", "", "Nirgendwo", "Akquise", 5],                               # row 8: no date -> error
    ["", "", "", "", "", "Summe", 173]],                                             # row 9: the sheet's sum
    {"E5": "Nur ein Beleg. Zeiten bitte ergänzen.", "E7": "Hinweis frei.", "G7": BLOCK})
SHEET2 = ("Tom Beispiel", [
    HEAD,
    ["12.06.2025", "14.06.2025", "", "", "Beispielberg (Schweiz) / Italien", "Messe", 128]],  # CH 43 + IT 42 + CH 43
    {"G2": "Schweiz: 2 × 43 € = 86 €\nItalien: 1 × 42 € = 42 €"})
SAMPLE = [SHEET1, SHEET2]

if __name__ == "__main__":
    sys.stdout.write(base64.b64encode(xlsx(SAMPLE)).decode())
