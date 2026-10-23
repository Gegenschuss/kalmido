#!/usr/bin/env python3
"""2.217.0 B (#2800): the PDF head with a long recipient name (kalmido/office/pdf.py), no server, no container.
 - page 1: a recipient name of 80+ characters wraps within the address field (85 mm) and never runs into the key data
   on the right ("Datum", number ...); the whole name stays in the text layer; the head grows, the title below the last line
 - a short recipient stays on one line, the body starts where it did (45 mm address field)
 - following pages: "title number · name" of the small head wraps / is cut left of the company name (and of the logo)
P2217B_SHOTS=<dir> (shots: 'P2217B_SHOTS'): the PDFs and, with pdftoppm, PNGs of page 1 and page 2.
usage: p2217_b_pdfhead_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
from kt import FAILS, OKS, check  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

SHOTS = os.environ.get("P2217B_SHOTS") or ""
LONG = "Stadtwerke Musterstadt Versorgungs- und Verkehrsgesellschaft mbH Niederlassung Beispielhausen"
CO = "Studio Nordlicht GmbH"


def item(i):
    return {"kind": "item", "pos": i, "title": f"Leistung Nr. {i}", "qty": 1, "qty_text": "1", "unit": "day", "unit_text": "Tage",
            "rate": 100, "rate_text": "100,00 €", "tax": "standard", "tax_pct": 19, "total": 100, "total_text": "100,00 €"}


def model(name, n=3):
    return {"kind": "offer", "lang": "de", "currency": "EUR", "vat_mode": "vat", "status": "draft", "number": "KVA-2026-099",
            "date": "2026-10-23", "date_text": "23.10.2026", "title": "Angebot",
            "company": {"name": CO, "lines": [CO, "Hafenstraße 12", "20457 Hamburg"], "sender_line": CO + " · Hafenstraße 12 · 20457 Hamburg"},
            "recipient": {"name": name, "lines": [name, "z. Hd. Erika Beispiel", "Marktstraße 5", "50667 Köln"]},
            "meta": [["Angebot Nr.", "KVA-2026-099"], ["Datum", "23.10.2026"], ["Gültig bis", "22.11.2026"]],
            "lines": [item(i) for i in range(1, n + 1)],
            "totals": {"net": 100.0 * n, "net_text": f"{100 * n},00 €", "rows": [["Summe Netto", f"{100 * n},00 €"]], "tax_lines": []}}


def frags(data, page_no):
    """[(x, top, width, text)] of one page (top = distance from the top edge, like the writer's y)."""
    out = []
    pg = PdfReader(io.BytesIO(data)).pages[page_no]

    def vis(t, cm, tm, font, size):
        if not t.strip():
            return
        bold = "Bold" in str((font or {}).get("/BaseFont", ""))
        out.append((tm[4], pdf.A4_H - tm[5] - size * 0.78, pdf.pdf_text_width(t, size, bold), t))
    pg.extract_text(visitor_text=vis)
    return out


def squash(s):
    return re.sub(r"\s+", "", s)


def shot(name, data, page_nos):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    p = os.path.join(SHOTS, name + ".pdf")
    with open(p, "wb") as fh:
        fh.write(data)
    for no in page_nos:
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", str(no), "-l", str(no), "-singlefile", p, os.path.join(SHOTS, f"{name}-p{no}")], check=False)
        else:
            sketch(data, no - 1, os.path.join(SHOTS, f"{name}-p{no}-sketch.png"))


def sketch(data, page_no, out, sc=2.2):
    """Without pdftoppm: the top 110 mm of a page drawn from the text layer with Pillow (a box per text piece)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    hh = 110 * pdf.MM
    im = Image.new("RGB", (int(pdf.A4_W * sc), int(hh * sc)), "white")
    dr = ImageDraw.Draw(im)
    dr.line([((pdf.PDF_L + pdf.PDF_ADDR_W) * sc, 0), ((pdf.PDF_L + pdf.PDF_ADDR_W) * sc, hh * sc)], fill=(200, 120, 120))
    for x, top, w, t in frags(data, page_no):
        if top > hh:
            continue
        dr.rectangle([x * sc, top * sc, (x + w) * sc, (top + 9) * sc], outline=(120, 150, 200))
        dr.text((x * sc + 1, top * sc + 2), t, fill=(20, 20, 20))
    im.save(out)


INFO_X = pdf.PDF_L + pdf.PDF_ADDR_W + 8 * pdf.MM
ADDR_R = pdf.PDF_L + pdf.PDF_ADDR_W

# ---- page 1: the long name wraps inside the address field
d = pdf.office_pdf(model(LONG))
shot("p2217b-long", d, [1])
f1 = frags(d, 0)
txt = "".join(t for *_, t in f1)
check(squash(LONG) in squash(txt), "#2800: the whole long recipient name is in the text layer")
ttl = [x for x in f1 if x[3].strip() == "ANGEBOT"]
check(bool(ttl), "the title line is there")
ttl_y = ttl[0][1] if ttl else pdf.PDF_ADDR_TOP + 80 * pdf.MM
head = [x for x in f1 if pdf.PDF_ADDR_TOP - 2 <= x[1] < ttl_y - 1]
left = [x for x in head if x[0] < INFO_X - 1]
right = [x for x in head if x[0] >= INFO_X - 1]
check(left and all(x[0] + x[2] <= ADDR_R + 0.5 for x in left), "#2800: every address line ends within the 85 mm address field "
      + str([(round(x[0] + x[2] - ADDR_R, 1), x[3]) for x in left if x[0] + x[2] > ADDR_R + 0.5]))
check(any(x[3].strip() == "Datum" for x in right), "#2800: the label Datum stands in the key data on the right")
over = [(a[3], b[3]) for a in left for b in right if a[0] + a[2] > b[0] and abs(a[1] - b[1]) < 9]
check(not over, f"#2800: no address line overlaps the key data {over}")
name_l = [x for x in left if x[3] and x[3] in LONG]
check(len(name_l) >= 2, f"#2800: the long name wraps over two or more lines {[x[3] for x in name_l]}")
last_addr = max(x[1] for x in left) if left else 0
check(ttl_y > last_addr + 8 and ttl_y > pdf.PDF_ADDR_TOP + pdf.PDF_ADDR_H, "#2800: the title stands below the last address line (the head grew)")

# ---- a short name: one line, the body where it was
ds = pdf.office_pdf(model("Beispielkunde AG"))
fs = frags(ds, 0)
check(sum(1 for x in fs if x[3].strip() == "Beispielkunde AG") == 1, "#2800: a short name stays one line")
ts = [x for x in fs if x[3].strip() == "ANGEBOT"]
check(ts and ts[0][1] >= pdf.PDF_ADDR_TOP + pdf.PDF_ADDR_H - 1, "#2800: the body starts below the 45 mm address field as before")

# ---- following pages: the small head stays left of the company name
d2 = pdf.office_pdf(model(LONG, 60))
shot("p2217b-next", d2, [2])
check(len(PdfReader(io.BytesIO(d2)).pages) >= 2, "#2800: 60 positions = a following page")
f2 = [x for x in frags(d2, 1) if x[1] < 24 * pdf.MM]
co = [x for x in f2 if x[3].strip() == CO]
sm = [x for x in f2 if x[0] < pdf.PDF_L + 1 and x[3].strip() != CO]
check(co and sm, f"#2800: page 2 has the small head (company + title line) {[x[3] for x in f2]}")
if co and sm:
    check(all(x[0] + x[2] <= co[0][0] - 3 * pdf.MM for x in sm), "#2800: title · name of the small head ends left of the company name "
          + str([(round(x[0] + x[2] - co[0][0], 1), x[3]) for x in sm]))
    check(len(sm) <= 2 and "KVA-2026-099" in "".join(x[3] for x in sm), f"#2800: at most two lines, the number stays {[x[3] for x in sm]}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
