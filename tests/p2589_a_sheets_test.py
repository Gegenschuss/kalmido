#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.589.0 part A API test (#4825): merged cells and formats of tables -- the two server parts.
Invented names only, the .xlsx is made by the export here.
 - xlsx import: an empty cell that only carries a format (<c r="B3" s="5"/>, as the export writes it) comes in as a cell
   with its format (before 2.589 it was dropped); the import's limits still count it
 - the print view (POST /api/sheets/<id>/print.pdf) takes a cell's bold, italic (the slanted text matrix), alignment and
   fill (the palette's fill colour as a rectangle under the text)
All as a person without an organisation (frida).
freelancer-matrix: sheets
usage: p2589_a_sheets_test.py <datadir>      (a fresh container; P2589AS_NOSTART=1 = the server already runs)"""
import io
import os
import re
import sys
import zipfile
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check  # noqa: E402

kt.fresh(prefix="P2589AS")
A = kt.setup()
FID, Fr = freelancer(B, A)


def get(sid):
    return Fr.get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def put(sid, cells):
    return Fr.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def pdf_text(raw):
    """The page contents of a PDF from shprint, unpacked (FlateDecode streams)."""
    out = b""
    for m in re.finditer(rb"stream\n(.*?)\nendstream", raw, re.S):
        try:
            out += zlib.decompress(m.group(1)) + b"\n"
        except zlib.error:
            pass
    return out


def hx(s):
    return ("<" + s.encode("cp1252").hex() + ">").encode()


def op_of(txt, s):
    """The text operation (BT ... ET) that draws s."""
    m = re.search(rb"BT [^\n]*?" + re.escape(hx(s)) + rb" Tj ET", txt)
    return m.group(0) if m else b""


def x_of(op):
    m = re.search(rb"([\d.]+) [\d.]+ T[dm] <", op)
    return float(m.group(1)) if m else None


r = Fr.post(B + "/api/sheets", json={"title": "Formats", "space": "private"})
check(r.status_code == 201, "a private table " + r.text[:200])
SID = r.json()["id"]
r = put(SID, [{"cell": "A1", "raw": "Name"}, {"cell": "B1", "raw": "Note"}, {"cell": "A2", "raw": "Fett"}, {"cell": "A3", "raw": "Schief"},
              {"cell": "A4", "raw": "Rechts"}, {"cell": "A5", "raw": "Links"}, {"cell": "A6", "raw": "Farbe"}, {"cell": "B6", "raw": "Ende"}, {"cell": "A7", "raw": "Eine deutlich breitere Zeile"}])  # A7: the column wider than "Rechts"
check(r.ok, "values " + r.text[:200])
r = put(SID, [{"cell": "A2", "fmt": {"bold": True}}, {"cell": "A3", "fmt": {"italic": True}}, {"cell": "A4", "fmt": {"align": "right"}},
              {"cell": "A6", "fmt": {"fill": "a2"}}, {"cell": "B3", "fmt": {"bold": True, "fill": "a"}}])
check(r.ok, "formats, one on the empty B3 " + r.text[:200])
check(cell(get(SID), "B3").get("fmt") == {"bold": True, "fill": "a"}, "the empty B3 keeps its format " + str(cell(get(SID), "B3")))

# ---- xlsx: the empty formatted cell goes out and comes back
r = Fr.get(B + f"/api/sheets/{SID}/export.xlsx")
check(r.ok and r.content[:2] == b"PK", "export .xlsx")
ws = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
check(re.search(r'<c r="B4" s="\d+"/>', ws), "the export writes the empty formatted cell without a value " + ws[ws.find('<row r="4"'):][:160])
r = Fr.post(B + "/api/sheets/import", data={"space": "private", "title": "Back"}, files={"file": ("back.xlsx", r.content)})
check(r.status_code == 201, "the file imports " + r.text[:200])
IM = get(r.json()["sheet"]["id"]) if r.status_code == 201 else {"cells": []}
check(cell(IM, "B3").get("fmt") == {"bold": True, "fill": "a"} and not cell(IM, "B3").get("raw"),
      "import: the empty cell with only a format is there again " + str(cell(IM, "B3")))
check(cell(IM, "A2").get("fmt") == {"bold": True} and cell(IM, "A2").get("raw") == "Fett", "import: a filled formatted cell as before")

# ---- the print view takes bold, italic, alignment and fill
r = Fr.post(B + f"/api/sheets/{SID}/print.pdf", json={"head": True, "numbers": False})
check(r.ok and r.content.startswith(b"%PDF"), "print: a PDF " + (r.text[:200] if not r.ok else ""))
txt = pdf_text(r.content)
o_bold, o_it, o_r, o_l = op_of(txt, "Fett"), op_of(txt, "Schief"), op_of(txt, "Rechts"), op_of(txt, "Links")
check(b"/F2 " in o_bold and b"/F1 " in o_l, "print: the bold cell in the bold font, a plain one in the regular " + o_bold.decode("latin-1")[:120])
check(re.search(rb"1 0 0\.21 1 [\d.]+ [\d.]+ Tm", o_it) and b"/F1 " in o_it and b" Tm " not in o_l, "print: the italic cell slanted " + o_it.decode("latin-1")[:120])
check(x_of(o_r) is not None and x_of(o_l) is not None and x_of(o_r) > x_of(o_l) + 5, f"print: the right-aligned cell further right ({x_of(o_r)} / {x_of(o_l)})")
check(b"0.886 0.949 0.957 rg" in txt and b"0.749 0.890 0.910 rg" in txt, "print: the fills (light accent E2F2F4, accent BFE3E8) as rectangles")
check(txt.index(b"0.886 0.949 0.957 rg") < txt.index(hx("Farbe")), "print: the fill under the text")

print(f"p2589_a_sheets: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
