#!/usr/bin/env python3
# kalmido-suite: after=p2296_a_pdfa nodata
"""2.406.0 (#3501): the office PDF writer of kalmido/office/pdf.py of the source tree, no server, no container. Invented
companies and figures only; every logo is made here. freelancer-matrix: office (the writer has no organisation in it: the
API part with a person without organisation is p2406_lead_api_test.py)
 - #3501 the logo frame per size (small 30 x 14, medium 45 x 22, large 60 x 30 mm) and side (left on the left margin, right
   on the right margin); no choice = medium, right (as before); large ends above the address field (45 mm from the top)
usage: p2406_lead_pdf_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from kt import check, done  # noqa: E402

MM = pdf.MM
CO = {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: kontakt@example.com"],
      "register_lines": ["Amtsgericht Musterstadt HRB 1"], "bank_lines": ["IBAN DE00 0000 0000 0000 0000 00"], "color": "#2f5d8a"}


def money(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def model(kind="invoice", n=2, co=None, title="Rechnung"):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung {i}", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
              "rate_text": money(100), "tax_pct": 19, "total": 100, "total_text": money(100)} for i in range(1, n + 1)]
    return {"kind": kind, "lang": "de", "currency": "EUR", "number": "RE-2026-406", "date": "2026-10-28", "date_text": "28.10.2026",
            "title": title, "project_title": "Imagefilm Hafenlichter", "company": dict(CO, **(co or {})),
            "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
            "meta": [["Rechnung Nr.", "RE-2026-406"], ["Datum", "28.10.2026"]], "lines": lines,
            "totals": {"rows": [["Summe netto", money(100 * n)], ["Gesamt", money(119 * n)]], "show_tax_lines": False},
            "labels": {"pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt", "vat": "MwSt."}}


def png(w, h):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (47, 93, 138)).save(b, "PNG")
    return b.getvalue()


LOGO_RE = re.compile(rb"q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /Logo Do Q")


def logos(data):
    """(width, height, x, top) in pt of the logo on every page (top from the page's upper edge)."""
    from pypdf import PdfReader
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        m = LOGO_RE.search(p.get_contents().get_data())
        ph = float(p.mediabox.height)
        out.append((float(m.group(1)), float(m.group(2)), float(m.group(3)), ph - float(m.group(4)) - float(m.group(2))) if m else None)
    return out


tmp = os.path.join(N, ".data", "p2406lead")
os.makedirs(tmp, exist_ok=True)
WIDE, TALL = os.path.join(tmp, "wide.png"), os.path.join(tmp, "tall.png")
with open(WIDE, "wb") as fh:
    fh.write(png(1600, 400))  # 4:1 - fills the frame's width
with open(TALL, "wb") as fh:
    fh.write(png(400, 1600))  # 1:4 - fills the frame's height

# ---------------------------------------------------------------- #3501 logo size and side
check({k: (round(w / MM), round(h / MM)) for k, (w, h) in pdf.PDF_LOGO_SIZES.items()} == {"s": (30, 14), "m": (45, 22), "l": (60, 30)},
      f"#3501: the three frames 30 x 14 / 45 x 22 / 60 x 30 mm {pdf.PDF_LOGO_SIZES}")
check(pdf.pdf_logo_frame({}) == (pdf.PDF_LOGO_MAX_W, pdf.PDF_LOGO_MAX_H, False), "#3501: no choice = medium, right (the look before)")
check(pdf.pdf_logo_frame({"logo_size": "x", "logo_pos": "?"})[2] is False, "#3501: an unknown value falls back to medium, right")
right_edge = pdf.A4_W - pdf.PDF_R
for size, (fw, fh) in (("s", (30, 14)), ("m", (45, 22)), ("l", (60, 30))):
    for pos in ("l", "r"):
        co = {"logo_size": size, "logo_pos": pos}
        d = pdf.office_pdf(model(co=dict(co, logo_path=WIDE)))
        lw, lh, x, top = logos(d)[0]
        check(abs(lw - fw * MM) < 0.05, f"#3501 {size}/{pos}: a wide logo fills the frame's width {fw} mm ({lw / MM:.1f} mm)")
        want_x = pdf.PDF_L if pos == "l" else right_edge - lw
        check(abs(x - want_x) < 0.05, f"#3501 {size}/{pos}: the logo sits on the {'left' if pos == 'l' else 'right'} margin (x {x:.1f}, want {want_x:.1f})")
        lw, lh, x, top = logos(pdf.office_pdf(model(co=dict(co, logo_path=TALL))))[0]
        check(abs(lh - fh * MM) < 0.05, f"#3501 {size}/{pos}: an upright logo fills the frame's height {fh} mm ({lh / MM:.1f} mm)")
        check(top + lh <= pdf.PDF_ADDR_TOP - 2 * MM, f"#3501 {size}/{pos}: the logo ends above the address field ({(top + lh) / MM:.1f} mm)")
        check(not pdfcheck.problems(d), f"#3501 {size}/{pos}: layout clean {pdfcheck.problems(d)[:3]}")
# no choice: exactly the frame and side of before
lw, lh, x, top = logos(pdf.office_pdf(model(co={"logo_path": WIDE})))[0]
check(abs(lw - 45 * MM) < 0.05 and abs(x - (right_edge - lw)) < 0.05, f"#3501: without a choice 45 mm on the right as before ({lw / MM:.1f} mm, x {x:.1f})")
# the following pages keep their small head (32 x 11 mm, right) whatever the choice
sz = logos(pdf.office_pdf(model(n=40, co={"logo_size": "l", "logo_pos": "l", "logo_path": WIDE})))
check(len(sz) >= 2 and all(s and s[0] <= 32 * MM + 0.05 and abs(s[2] + s[0] - right_edge) < 0.05 for s in sz[1:]),
      f"#3501: the following pages' small head is unchanged {sz[1:3]}")
# US-Letter: the same frames
P = pdf.pdf_paper_ns("letter")
lw, lh, x, top = logos(P.office_pdf(dict(model(co={"logo_size": "l", "logo_pos": "l", "logo_path": WIDE}), paper="letter")))[0]
check(abs(lw - 60 * MM) < 0.05 and abs(x - P.PDF_L) < 0.05, f"#3501: Letter, large left ({lw / MM:.1f} mm, x {x:.1f})")

sys.exit(done("p2406_lead_pdf"))
