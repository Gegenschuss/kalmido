#!/usr/bin/env python3
"""2.294.0 (#3154, #3155): air around the totals and below the intro of the office PDF, the draft watermark
(kalmido/office/pdf.py of the source tree), no server, no container. Invented companies and figures only.
 - #3154 a short quotation / invoice: the wished gap (~11 mm) between the last position's rule and the line above the
   totals, a little more air below the totals, the same wished air between the intro and the table head
 - #3154 every length from 1 to 45 positions (quotation, invoice with payment info, closing text one to three lines):
   never more pages than without the air (the old gaps), the totals gap never below the old one of that length; at least one nearly full
   page sets the gap between minimum and wish or at the minimum (~4 mm) instead of breaking, a multi-page document keeps
   the wished gap on its last page when there is room
 - #3154 a delivery note (no prices) prints no totals and no totals air
 - #3155 _Page.mark: the watermark is bold (F2), outlined as well (2 Tr) and darker than before, drawn first; an office
   PDF with draft_mark carries it on every page
P2294_SHOTS=<dir> (shots: 'P2294_SHOTS'): the PDFs and, with pdftoppm, PNGs of page 1 (short, nearly full, draft).
usage: p2294_pdf_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
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

SHOTS = os.environ.get("P2294_SHOTS") or ""
MM = pdf.MM
PAGES = []
_Base = pdf._Page


class RecPage(_Base):  # every text / line call per page (y from the top)
    def __init__(self):
        super().__init__()
        self.rec, self.rules = [], []
        PAGES.append(self)

    def text(self, x, y, s, size, bold=False, color=pdf.C_INK, align="l", spacing=0.0, width=None):
        if str(s or ""):
            self.rec.append({"y": y, "s": str(s), "size": size})
        return super().text(x, y, s, size, bold, color, align, spacing, width)

    def line(self, x1, y1, x2, y2, w=0.5, color=pdf.C_RULE, dash=None):
        self.rules.append((x1, y1, x2, y2, w))
        return super().line(x1, y1, x2, y2, w, color, dash)


pdf._Page = RecPage
NEW = (pdf.PDF_SUM_GAP, pdf.PDF_SUM_GAP_MIN, pdf.PDF_SUM_AFTER)


def old_gaps(on):  # on = False: the layout before 2.294.0 (8 pt in draw_sum, no air; the intro air is then 0 as well)
    pdf.PDF_SUM_GAP, pdf.PDF_SUM_GAP_MIN, pdf.PDF_SUM_AFTER = (8.0, 8.0, 0.0) if not on else NEW


def money(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s + " €"


def model(n_items=3, kind="offer", closing_lines=1, noprice=False):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung Nummer {i}", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "Tag",
              "rate": 100, "rate_text": money(100), "tax_pct": 19, "total": 100, "total_text": money(100)} for i in range(1, n_items + 1)]
    net = 100.0 * n_items
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "KVA-2026-294", "date": "2026-10-24", "date_text": "24.10.2026",
         "title": "Rechnung" if kind == "invoice" else "Kostenvoranschlag",
         "company": {"name": "Beispielstudio GmbH", "lines": ["Beispielstudio GmbH", "Musterweg 1", "12345 Musterstadt"],
                     "contact_lines": ["kontakt@example.com"], "color": "#6b4fbb"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "intro": "Sehr geehrte Damen und Herren,\nvielen Dank für Ihre Anfrage. Gerne unterbreiten wir Ihnen folgendes Angebot:",
         "lines": lines,
         "totals": {"rows": [["Summe Netto", money(net)], ["MwSt. 19 %", money(net * 0.19)], ["Gesamt", money(net * 1.19)]], "show_tax_lines": True,
                    "vat_note": "Alle Preise zuzüglich MwSt."},
         "closing": " ".join(["Wir freuen uns auf die Zusammenarbeit und stehen für Rückfragen gerne zur Verfügung."] * closing_lines),
         "signature": "Mit freundlichen Grüßen", "signature_name": "Erika Beispiel"}
    if kind == "invoice":
        m["payment"] = {"text": "Bitte überweisen Sie den Betrag bis zum 07.11.2026.", "iban": "DE00000000000000000000", "bic": "XXXXDEXXXXX"}
    if noprice:
        m.update(noprice=True, kind="delivery", title="Lieferschein", totals={})
    return m


def render(m):
    PAGES.clear()
    data = pdf.office_pdf(m)
    return data, list(PAGES)


def sum_gap(pages):
    """(page index, gap in pt) between the last table rule (0.5 pt, full width) above the totals and the line above them."""
    for k, p in enumerate(pages):
        net = [t for t in p.rec if t["s"] == "Summe Netto"]
        if not net:
            continue
        top = [r for r in p.rules if r[4] == 1.1 and r[0] > pdf.PDF_L + 1 and r[1] <= net[0]["y"] + 0.1]  # the line above "Summe Netto"
        rows = [r for r in p.rules if r[4] == 0.5 and abs(r[0] - pdf.PDF_L) < 0.1 and r[1] < net[0]["y"]]
        if top and rows:
            return k, top[-1][1] - (max(r[1] for r in rows) + 0.5)  # the row's rule sits 0.5 pt above its block end
    return None, None


def intro_gap(pages):  # from the top of the intro's last line to the top of the table head text
    p = pages[0]
    last = [t for t in p.rec if t["s"].startswith("vielen Dank") or t["s"].endswith("folgendes Angebot:")]
    head = [t for t in p.rec if t["s"] == "POS."]
    return (head[0]["y"] - max(t["y"] for t in last)) if last and head else None


def shot(name, data):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    f = os.path.join(SHOTS, name + ".pdf")
    with open(f, "wb") as fh:
        fh.write(data)
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "90", "-f", "1", "-l", "1", "-singlefile", f, os.path.join(SHOTS, name)], check=False)


LH = 9.6 * 1.42
INTRO_OLD = LH + 12  # before 2.294.0: one line box + 8 + the head's 4 pt
INTRO_WISH = INTRO_OLD + (pdf.PDF_SUM_GAP - (LH + 12 - 9.6))

# ---------------------------------------------------------------- 1. short documents: the wished gaps
for kind in ("offer", "invoice"):
    data, pages = render(model(3, kind))
    k, g = sum_gap(pages)
    check(len(pages) == 1 and k == 0 and g is not None and abs(g - pdf.PDF_SUM_GAP) < 0.6,
          f"{kind}, 3 positions: the wished gap ~11 mm before the totals ({g and round(g / MM, 1)} mm)")
    ig = intro_gap(pages)
    check(ig is not None and abs(ig - INTRO_WISH) < 0.6, f"{kind}: the wished air between intro and table ({ig and round(ig, 1)} pt, want {INTRO_WISH:.1f})")
    old_gaps(False)
    _, op = render(model(3, kind))
    old_gaps(True)
    sy = [t["y"] for t in pages[0].rec if t["s"].startswith("Wir freuen uns")]
    so = [t["y"] for t in op[0].rec if t["s"].startswith("Wir freuen uns")]
    ny = [t["y"] for t in pages[0].rec if t["s"] == "Summe Netto"]
    no = [t["y"] for t in op[0].rec if t["s"] == "Summe Netto"]
    check(sy and so and ny and no and (sy[0] - ny[0]) - (so[0] - no[0]) > pdf.PDF_SUM_AFTER - 0.6, f"{kind}: a little more air below the totals")
    if kind == "offer":
        shot("p2294-kurz", data)
        old_gaps(False)
        shot("p2294-kurz-vorher", render(model(3, kind))[0])
        old_gaps(True)

# ---------------------------------------------------------------- 2. every length: never an extra page, the gap shrinks before a break
squeezed, at_min, multi_wish, worse = [], [], [], []
for kind in ("offer", "invoice"):
    for cl in (1, 2, 3):
        for n in range(1, 46):
            m = model(n, kind, cl)
            data, pages = render(m)
            old_gaps(False)
            _, op = render(model(n, kind, cl))
            old_gaps(True)
            tag = f"{kind} {n}/{cl}"
            if len(pages) != len(op):
                worse.append(f"{tag}: {len(op)} -> {len(pages)}")
            k, g = sum_gap(pages)
            if g is None:
                continue
            go = sum_gap(op)[1]  # before 2.294.0: 8 pt, a tight page took up to 4 of them (2.138.0 E #2238)
            if go is not None and g < go - 0.3:
                worse.append(f"{tag}: gap {g:.1f} pt below the old {go:.1f} pt")
            if k == len(pages) - 1 and len(pages) == len(op):
                if pdf.PDF_SUM_GAP_MIN + 0.3 < g < pdf.PDF_SUM_GAP - 0.3:
                    squeezed.append((tag, round(g / MM, 1)))
                elif abs(g - pdf.PDF_SUM_GAP_MIN) <= 0.3:
                    at_min.append((tag, len(pages), data))
                elif len(pages) > 1 and abs(g - pdf.PDF_SUM_GAP) < 0.6:
                    multi_wish.append(tag)
            if data[:8] != b"%PDF-1.7" or len(PdfReader(io.BytesIO(data)).pages) != len(pages):
                worse.append(f"{tag}: the PDF does not open")
check(not worse, f"never more pages than before, the gap never below the old one ({worse[:4]})")
check(len(squeezed) >= 1, f"a nearly full page sets the gap between minimum and wish ({squeezed[:4]})")
check(len(at_min) >= 1, f"a nearly full page sets the minimum ~4 mm instead of a page break ({[a[:2] for a in at_min[:4]]})")
check(len(multi_wish) >= 1, f"a multi-page document keeps the wished gap on its last page ({multi_wish[:3]})")
if at_min:
    shot("p2294-fast-voll", at_min[0][2])

# ---------------------------------------------------------------- 3. delivery note: no totals, no totals air
data, pages = render(model(4, noprice=True))
check(data[:8] == b"%PDF-1.7" and not any(t["s"] == "Summe Netto" for p in pages for t in p.rec) and sum_gap(pages) == (None, None),
      "a delivery note prints no totals")

# ---------------------------------------------------------------- 4. #3155: the draft watermark
pg = _Base()
pg.text(pdf.PDF_L, 100, "Inhalt", 10)
pg.mark("ENTWURF")
op0 = pg.ops[0]
check(pg.ops[0].startswith("q ") and "/F2" in op0 and " 2 Tr " in op0 and pdf.PDF_MARK_GREY + " rg" in op0 and pdf.PDF_MARK_GREY + " RG" in op0
      and op0.endswith("ET Q") and "Inhalt".encode("cp1252").hex() in pg.ops[1], f"#3155: mark() bold, outlined, darker, drawn first ({op0[:80]})")
check(float(pdf.PDF_MARK_GREY.split()[0]) < 0.88, "#3155: darker than the old 0.88")
data, pages = render(dict(model(45), draft_mark="ENTWURF"))
hx = "ENTWURF".encode("cp1252").hex()
check(len(pages) >= 2 and all(p.ops[0].startswith("q ") and hx in p.ops[0] for p in pages), f"#3155: the watermark on every page of a draft ({len(pages)} pages)")
shot("p2294-entwurf", render(dict(model(3), draft_mark="ENTWURF"))[0])

print(f"p2294_pdf: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
