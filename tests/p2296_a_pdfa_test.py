#!/usr/bin/env python3
"""2.296.0 A (#3164, #3178): the footer of the office PDF and the layout check (tests/pdfcheck.py) on kalmido/office/pdf.py of
the source tree, no server, no container. Invented companies and figures only; logo and letterhead are made here.
 - #3164 a company with a long footer (three name lines, four contact lines, shareholders + managing directors + court + IDs,
   bank name / IBAN / BIC / tax number / VAT id): every entry is in the footer of every page (nothing cut after six lines),
   the IBAN and the e-mail line stand whole on one line, the shareholders line below the columns, font at least 6.5 pt,
   no text below the page margin or across the footer rule, the body ends above the real footer height
 - #3164 a short footer stays one block of at most four lines and needs no line below the columns
 - #3178 pdfcheck finds a text over the right margin, one below the footer rule and two overlapping texts (made by hand)
 - #3178 PDF/A files for veraPDF in CI (tools/einvoice_validate.sh, written to tests/.data/einvoice/ after office_einvoice_test):
   quotation with a logo, with a 16-bit PNG logo (renders, the image is there), on a letterhead made here (form XObject),
   with the draft watermark and special characters in the title, with the long footer; each passes the layout check
usage: p2296_a_pdfa_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from kt import check, done  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

MM = pdf.MM
OUT = os.path.join(N, ".data", "einvoice")
IBAN = "IBAN DE89 3704 0044 0532 0130 00"
LONG = {"name": "Studio Nordlicht GmbH", "name_lines": ["Studio Nordlicht GmbH", "Film · Foto · Motion Design", "Niederlassung Hamburg-Altona"],
        "lines": ["Große Elbstraße 145b", "Hinterhaus, 3. OG", "20457 Hamburg"],
        "contact_lines": ["Tel. +49 40 12345678", "Mobil +49 171 2345678", "E-Mail: produktion@studio-nordlicht.example", "www.studio-nordlicht.example"],
        "register_lines": ["Gesellschafter: Jana Muster, Ole Petersen, Mette Sørensen, Henrik Lund", "Geschäftsführung: Jana Muster, Ole Petersen",
                           "Amtsgericht Hamburg HRB 123456", "USt-IdNr. DE123456789 · Steuernummer 12/345/67890"],
        "bank_lines": ["Hamburger Beispielbank", IBAN, "BIC COBADEFFXXX", "Steuernummer 12/345/67890", "USt-IdNr. DE123456789"], "color": "#2f5d8a"}
SHORT = {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: kontakt@example.com"],
         "register_lines": ["Amtsgericht Musterstadt HRB 1"], "bank_lines": ["IBAN DE00 0000 0000 0000 0000 00"], "color": "#2f5d8a"}


def money(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s + " €"


def model(company, n_items=6, title="Imagefilm Hafenlichter", **kw):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung Nummer {i}", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "Tag",
              "rate": 100, "rate_text": money(100), "tax_pct": 19, "total": 100, "total_text": money(100)} for i in range(1, n_items + 1)]
    net = 100.0 * n_items
    m = {"kind": "offer", "lang": "de", "currency": "EUR", "number": "KVA-2026-296", "date": "2026-10-25", "date_text": "25.10.2026",
         "title": "Angebot", "project_title": title, "company": dict(company),
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "meta": [["Angebot Nr.", "KVA-2026-296"], ["Datum", "25.10.2026"]],
         "intro": "Sehr geehrte Damen und Herren,\nvielen Dank für Ihre Anfrage.", "lines": lines,
         "totals": {"net": net, "net_text": money(net), "tax_lines": [], "gross": net * 1.19, "rows": [["Summe Netto", money(net)]],
                    "vat_note": "Alle Preise zuzüglich 19 % MwSt.", "show_tax_lines": False},
         "closing": "Wir freuen uns auf die Zusammenarbeit.", "signature": "Mit freundlichen Grüßen", "signature_name": "Jana Muster",
         "labels": {"offer_no": "Angebot Nr.", "pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt",
                    "net_total": "Summe Netto", "page_of": "Seite {x} von {y}"},
         "formats": {"date": "dd.mm.yyyy", "decimal": ",", "thousands": ".", "currency_pos": "after"}}
    m.update(kw)
    return m


def text_pages(data):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def png(w, h, mode="RGB"):
    from PIL import Image, ImageDraw
    if mode == "I;16":  # a 16-bit greyscale PNG (Pillow writes it as bit depth 16)
        im = Image.new("I;16", (w, h), 20000)
        for x in range(w // 4, w // 2):
            for y in range(h // 4, h // 2):
                im.putpixel((x, y), 60000)
    else:
        im = Image.new(mode, (w, h), (47, 93, 138))
        ImageDraw.Draw(im).rectangle([w // 8, h // 4, w // 2, h // 2], fill=(255, 255, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


# ---------------------------------------------------------------- 1. #3164: the long footer is never cut
cols = pdf.pdf_footer_cols(LONG)
fit = pdf.p3f_fit(cols)
check(fit[0] >= 6.5, f"#3164: footer font at least 6.5 pt ({fit[0]})")
check(any("Gesellschafter" in x for x in fit.full), f"#3164: the shareholders line below the columns {fit.full}")
check(pdf.p3f_foot_h(fit) >= pdf.p3f_lines(fit) * fit[0] * 1.39, "#3164: the footer height holds every line")
data = pdf.office_pdf(model(LONG, 40))
lay = pdfcheck.layout(data)
check(len(lay) >= 2, f"#3164: a long quotation has several pages ({len(lay)})")
probs = pdfcheck.problems(data)
check(not probs, f"#3164 / #3178: layout clean with the long footer {probs[:4]}")
feet = pdfcheck.footer_lines(data)
want = ["Studio Nordlicht GmbH", "Niederlassung Hamburg-Altona", "Große Elbstraße 145b", "20457 Hamburg", "Tel. +49 40 12345678", "Mobil +49 171 2345678",
        "E-Mail: produktion@studio-nordlicht.example", "www.studio-nordlicht.example", "Mette Sørensen", "Henrik Lund", "Amtsgericht", "HRB", "123456",
        "USt-IdNr. DE123456789", "Steuernummer 12/345/67890", "Hamburger Beispielbank", IBAN, "BIC COBADEFFXXX"]
for n, fl in enumerate(feet, 1):
    flat = "\n".join(fl)
    miss = [w for w in want if w not in flat.replace("\n", " ")]
    check(not miss, f"#3164: page {n}: every footer entry printed {miss}")
    check(any(IBAN in ln for ln in fl), f"#3164: page {n}: the IBAN whole on one line")
    check(any("E-Mail: produktion@studio-nordlicht.example" in ln for ln in fl), f"#3164: page {n}: the e-mail line whole on one line")
for n, p in enumerate(lay, 1):
    body = [t for t in p["texts"] if t["size"] > 7.2]
    check(p["foot"] is not None and body and max(t["y"] + t["size"] for t in body) <= p["foot"] + 0.6,
          f"#3164: page {n}: the body ends above the footer rule ({p['foot']})")
    check(all(t["y"] + t["size"] <= p["h"] - 5 * MM for t in p["texts"]), f"#3164: page {n}: no text in the bottom page margin")

# a short footer: as before, one block, nothing below the columns
fs = pdf.p3f_fit(pdf.pdf_footer_cols(SHORT))
check(not fs.full and max(len(c) for c in fs[2]) <= 4, f"#3164: a short footer stays in its columns {fs[2]} {fs.full}")
ds = pdf.office_pdf(model(SHORT, 3))
check(not pdfcheck.problems(ds), f"#3178: short quotation layout clean {pdfcheck.problems(ds)[:3]}")

# ---------------------------------------------------------------- 2. #3178: the check finds broken layouts (made by hand)
P = pdf._Page()
P.text(pdf.PDF_L, 100, "Ein viel zu langer Text " * 6, 10)  # over the right margin
pdf.pdf_draw_footer(P, pdf.pdf_footer_cols(SHORT))
P.text(pdf.PDF_L, pdf.A4_H - 14 * MM, "Rumpf unter der Fusslinie", 10)  # body text below the footer rule
P.text(pdf.PDF_L, 200, "Zeile A", 10)
P.text(pdf.PDF_L + 10, 202, "Zeile B", 10)  # overlaps A
bad = pdfcheck.problems(pdf.pdf_write([P], {}, title="Test"))
check(any("side margins" in x for x in bad) and any("below the footer rule" in x for x in bad) and any("overlaps" in x for x in bad),
      f"#3178: pdfcheck reports margin, footer and overlap problems {bad}")

# ---------------------------------------------------------------- 3. #3178: files for veraPDF (CI) + their layout
os.makedirs(OUT, exist_ok=True)


def emit(objs, i):  # a letterhead page made here: a coloured band on top, a thin rule at the bottom (form XObject)
    content = b"0.184 0.365 0.541 rg 0 800 595.28 41.89 re f 0.6 0.6 0.6 RG 0.5 w 70 30 m 525 30 l S"
    objs.append(b"<< /Type /XObject /Subtype /Form /BBox [0 0 595.28 841.89] /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    return len(objs)


files = {
    "p2296-offer-logo.pdf": pdf.office_pdf(model(SHORT, 8), logo_bytes=png(800, 200)),
    "p2296-offer-logo16.pdf": pdf.office_pdf(model(SHORT, 4), logo_bytes=png(400, 120, "I;16")),
    "p2296-offer-letterhead.pdf": pdf.bp_layout({"m1": [50, 20, 30, 25], "m2": [35, 20, 30, 25], "hide_head": 1, "hide_footer": 0, "pages": 1,
                                                 "emit": emit}, model(SHORT, 30)),
    "p2296-offer-draft-title.pdf": pdf.office_pdf(model(SHORT, 5, title="„Hafenlichter“ – Größe & Maß: ½ Tag, © Studio, 100 €",
                                                        draft_mark="ENTWURF")),
    "p2296-offer-footer-long.pdf": data,
}
for name, d in files.items():
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(d)
    rd = PdfReader(io.BytesIO(d))
    check(len(rd.pages) >= 1 and b"pdfaid:part" in d, f"#3178: {name} opens, PDF/A marked")
    pr = pdfcheck.problems(d)
    check(not pr, f"#3178: {name} layout clean {pr[:3]}")
for name in ("p2296-offer-logo.pdf", "p2296-offer-logo16.pdf"):
    xo = (PdfReader(io.BytesIO(files[name])).pages[0].get("/Resources") or {}).get("/XObject") or {}
    check(any(v.get_object().get("/Subtype") == "/Image" for v in xo.values()), f"#3178: {name}: the logo image on page 1")
xo = (PdfReader(io.BytesIO(files["p2296-offer-letterhead.pdf"])).pages[0].get("/Resources") or {}).get("/XObject") or {}
check(any(v.get_object().get("/Subtype") == "/Form" for v in xo.values()), "#3178: the letterhead form on page 1")
t = "\n".join(text_pages(files["p2296-offer-draft-title.pdf"]))
check("„Hafenlichter“" in t and "Größe" in t and "½" in t and "©" in t and "€" in t, "#3178: special characters in the title in the text layer")

sys.exit(done("p2296_a_pdfa"))
