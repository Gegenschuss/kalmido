#!/usr/bin/env python3
# kalmido-suite: after=p2296_a_pdfa nodata
"""2.357.0 B (#3179, #3180, #3181): the design of the office PDF on kalmido/office/pdf.py of the source tree, no server, no
container. Invented companies and figures only; every logo is made here. freelancer-matrix: office (the writer has no
organisation in it: the API part with a person without organisation is p2357_b_api_test.py)
 - #3179 the logo box is 45 x 22 mm: an upright logo gets 22 mm height (was 16), a wide one 45 mm width; a small logo is
   drawn at 200 dpi at most (100 px = 36 pt, never blown up to the box); a picture with a colour profile is converted (and
   one with a broken profile still prints)
 - #3180 a spaced title wraps in one pass: no line could take the next word (the old two-pass wrap left "ÜBER" alone), every
   line fits with its spacing; a word cut between letters gets a hyphen (an IBAN / digits none); a long value in the head's
   key data goes below its label (at most two lines, was four right-aligned)
 - #3181 the VAT column: one rate on an invoice (also 0 % of section 19) prints none, mixed rates keep it
usage: p2357_b_pdf_design_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
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


def model(kind="invoice", rates=(19, 19), meta=None, logo=None, title="Rechnung"):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung {i}", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
              "rate_text": money(100), "tax_pct": r, "total": 100, "total_text": money(100)} for i, r in enumerate(rates, 1)]
    return {"kind": kind, "lang": "de", "currency": "EUR", "number": "RE-2026-357", "date": "2026-10-26", "date_text": "26.10.2026",
            "title": title, "project_title": "Imagefilm Hafenlichter", "company": dict(CO, **({"logo_path": logo} if logo else {})),
            "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
            "meta": meta or [["Rechnung Nr.", "RE-2026-357"], ["Datum", "26.10.2026"]], "lines": lines,
            "totals": {"rows": [["Summe netto", money(100 * len(lines))], ["Gesamt", money(119 * len(lines))]], "show_tax_lines": True},
            "labels": {"pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt", "vat": "MwSt."}}


def png(w, h, icc=None):
    from PIL import Image
    im = Image.new("RGB", (w, h), (47, 93, 138))
    b = io.BytesIO()
    im.save(b, "PNG", **({"icc_profile": icc} if icc else {}))
    return b.getvalue()


LOGO_RE = re.compile(rb"q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /Logo Do Q")


def logo_sizes(data):
    """(width, height) in pt of the logo on every page (from the writer's "q w 0 0 h x y cm /Logo Do Q")."""
    from pypdf import PdfReader
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        m = LOGO_RE.search(p.get_contents().get_data())
        out.append((float(m.group(1)), float(m.group(2))) if m else None)
    return out


# ---------------------------------------------------------------- 1. #3179 logo box and resolution
check(abs(pdf.PDF_LOGO_MAX_H - 22 * MM) < 0.01 and abs(pdf.PDF_LOGO_MAX_W - 45 * MM) < 0.01, "#3179: the logo box is 45 x 22 mm")
for (w, h), want, what in (((400, 1600), (None, 22 * MM), "an upright logo gets 22 mm height"),
                           ((1600, 400), (45 * MM, None), "a wide logo gets 45 mm width"),
                           ((100, 40), (36.0, 14.4), "a 100 px logo is drawn at 200 dpi (36 pt), not blown up")):
    lw, lh = pdf.pdf_logo_fit((w, h), pdf.PDF_LOGO_MAX_W, pdf.PDF_LOGO_MAX_H)
    check((want[0] is None or abs(lw - want[0]) < 0.05) and (want[1] is None or abs(lh - want[1]) < 0.05)
          and lw <= pdf.PDF_LOGO_MAX_W + 0.01 and lh <= pdf.PDF_LOGO_MAX_H + 0.01, f"#3179: {what} ({lw:.2f} x {lh:.2f} pt)")
tmp = os.path.join(N, ".data", "p2357b")
os.makedirs(tmp, exist_ok=True)
for (w, h), want, what in (((300, 1200), 22 * MM, "upright logo 22 mm high on page 1"), ((100, 40), 14.4, "small logo at 200 dpi on page 1")):
    fn = os.path.join(tmp, f"logo_{w}x{h}.png")
    with open(fn, "wb") as fh:
        fh.write(png(w, h))
    data = pdf.office_pdf(model(logo=fn))
    sz = logo_sizes(data)
    check(sz and sz[0] and abs(sz[0][1] - want) < 0.05, f"#3179: {what} {sz}")
    check(not pdfcheck.problems(data), f"#3179: layout clean with the logo {pdfcheck.problems(data)[:3]}")
# a long invoice: the following pages' small logo stays inside the small head (above its rule at 24.5 mm)
fn = os.path.join(tmp, "logo_300x1200.png")
m40 = model(logo=fn, rates=(19,) * 40)
sz = logo_sizes(pdf.office_pdf(m40))
check(len(sz) >= 2 and all(s and 12 * MM + s[1] <= 24.5 * MM for s in sz[1:]), f"#3179: the small head's logo above its rule {sz}")
try:
    from PIL import Image, ImageCms
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
except Exception:  # noqa: BLE001  (no littlecms in this Pillow)
    srgb = None
if srgb:
    obj = pdf.pdf_image_object(png(60, 20, srgb))
    check(obj and obj[0] == 60 and obj[1] == 20 and len(obj[2]) > 0, "#3179: a logo with an embedded profile is converted and printed")
    im = Image.open(io.BytesIO(png(4, 4, srgb)))
    out = pdf.pdf_to_srgb(im)
    check(out.mode == "RGB" and max(abs(a - b) for a, b in zip(out.getpixel((0, 0)), (47, 93, 138))) <= 2, f"#3179: sRGB to sRGB keeps the colour {out.getpixel((0, 0))}")
    cm = Image.new("CMYK", (4, 4), (0, 0, 0, 0))
    cm.info["icc_profile"] = b"not a profile"
    check(pdf.pdf_to_srgb(cm) is cm, "#3179: a broken profile leaves the picture as it was (printed as before)")
else:
    print("SKIP #3179 colour profile: ImageCms not available")

# ---------------------------------------------------------------- 2. #3180 spaced titles, hyphens, key data
W = pdf.PDF_CW
for t in ("ANGEBOT FÜR DIE PRODUKTION EINES IMAGEFILMS ÜBER DEN HAMBURGER HAFEN UND SEINE MENSCHEN",
          "RECHNUNG ZUR PRODUKTION EINES ERKLÄRFILMS FÜR DIE STADTWERKE BEISPIELSTADT GMBH UND CO KG",
          "AUFTRAGSBESTÄTIGUNG IMAGEFILM HAFENLICHTER MIT DREHARBEITEN AN DREI TAGEN UND SCHNITT"):
    ls = pdf.pb_wrap(t, 16, W, True, 1.0)
    alone = [ls[i] for i in range(len(ls) - 1) if pdf.pdf_text_width(ls[i] + " " + ls[i + 1].split(" ")[0], 16, True, 1.0) <= W]
    check(not alone and all(pdf.pdf_text_width(x, 16, True, 1.0) <= W for x in ls) and " ".join(ls) == t,
          f"#3180: spaced title wrapped in one pass, no word left alone {ls}")
w = pdf.pdf_wrap("Donaudampfschifffahrtsgesellschaftskapitänsmützenhersteller", 9.6, 80)
check(len(w) >= 3 and all(x.endswith("-") for x in w[:-1]) and all(pdf.pdf_text_width(x, 9.6) <= 80 for x in w)
      and "".join(x[:-1] for x in w[:-1]) + w[-1] == "Donaudampfschifffahrtsgesellschaftskapitänsmützenhersteller", f"#3180: a cut word gets hyphens {w}")
w = pdf.pdf_wrap("DE02120300000000202051", 9.6, 50)
check(len(w) >= 2 and not any(x.endswith("-") for x in w) and "".join(w) == "DE02120300000000202051", f"#3180: digits are cut without a hyphen {w}")
w = pdf.pdf_wrap("Kamera", 9.6, 1)
check(w and "".join(x.rstrip("-") for x in w) == "Kamera", f"#3180: a very narrow column still keeps every letter {w}")
LONGREF = "Bestellung 2026-10-4711 der Einkaufsabteilung Standort Nord, Kostenstelle 4711"  # beside the label: three lines
data = pdf.office_pdf(model(meta=[["Rechnung Nr.", "RE-2026-357"], ["Datum", "26.10.2026"], ["Ihre Referenz", LONGREF]]))
p1 = pdfcheck.layout(data)[0]
lab = next((t for t in p1["texts"] if t["s"] == "Ihre Referenz"), None)
vals = sorted((t for t in p1["texts"] if t["bold"] and abs(t["size"] - 8.6) < 0.01 and t["s"] and t["s"].split(" ")[0] in LONGREF
               and t["y"] < 100 * MM and t["s"] not in ("RE-2026-357", "26.10.2026")), key=lambda t: t["y"])
check(lab and vals and vals[0]["y"] > lab["y"] + 4 and len(vals) <= 2, f"#3180: a long reference below its label in at most two lines "
      f"{[v['s'] for v in vals]}")
check(not pdfcheck.problems(data), f"#3180: layout clean with the long reference {pdfcheck.problems(data)[:3]}")
short = pdf.office_pdf(model(meta=[["Rechnung Nr.", "RE-2026-357"], ["Ihre Referenz", "PO-4711"]]))
p1 = pdfcheck.layout(short)[0]
lab = next(t for t in p1["texts"] if t["s"] == "Ihre Referenz")
val = next(t for t in p1["texts"] if t["s"] == "PO-4711")
check(abs(val["y"] - lab["y"]) < 0.5, "#3180: a short value stays beside its label")


# ---------------------------------------------------------------- 3. #3181 the VAT column
def head_has_vat(data):
    return any(t["s"] == "MWST." for p in pdfcheck.layout(data) for t in p["texts"])


check(not head_has_vat(pdf.office_pdf(model(rates=(19, 19)))), "#3181: an invoice with one rate prints no VAT column")
check(not head_has_vat(pdf.office_pdf(model(rates=(0, 0)))), "#3181: a section 19 invoice (0 %) prints no VAT column")
check(head_has_vat(pdf.office_pdf(model(rates=(19, 7)))), "#3181: mixed rates keep the VAT column")
check(not head_has_vat(pdf.office_pdf(model(rates=("19", "19.0", 19)))), "review N4: '19', '19.0' and 19 are one rate (no VAT column)")
check(not head_has_vat(pdf.office_pdf(model(kind="credit", rates=(19,), title="Gutschrift"))), "#3181: a credit note with one rate likewise")

sys.exit(done("p2357_b_pdf_design"))
