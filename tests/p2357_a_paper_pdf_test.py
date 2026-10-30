#!/usr/bin/env python3
# kalmido-suite: after=p2296_a_footer nodata
"""2.357.0 A (#3156): the paper size of the office PDFs (A4 / US-Letter) in the writer kalmido/office/pdf.py of the source tree,
no server, no container. Invented companies and figures only; the letterhead is made here.
 - A4 stays the default and unchanged: no paper / "a4" gives the same bytes, MediaBox 595.28 x 841.89, fold + punch marks
 - US-Letter: MediaBox 612 x 792 on every page, text inside the 1 in margins, the footer under the body, fold marks on the
   thirds (3.67 in / 7.33 in) and no punch mark, the recipient inside the #10 window (about 2.1 in .. 3.2 in from the top)
 - page breaks with many positions in Letter: every page Letter, layout clean, the totals never alone (#3154 gap the same as
   in A4 for a short document), the draft watermark (#3155) centred on the Letter page
 - PDF/A-3b marks and the embedded e-invoice unchanged in Letter; a Letter letterhead (bp_layout) stays a form XObject
 - the module's globals stay A4 after Letter runs (two threads at once: each PDF its own size); pdf_paper_bind for modules
   that import the names at their top (mealpdf)
 - files for veraPDF in CI (tools/einvoice_validate.sh): tests/.data/einvoice/p2357-letter-*.pdf
usage: p2357_a_paper_pdf_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import datetime
import importlib.util
import io
import os
import re
import sys
import threading

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
IN = 72.0
OUT = os.path.join(N, ".data", "einvoice")
WHEN = {"when": datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)}
CO = {"name": "Beispielstudio LLC", "lines": ["Beispielstudio LLC", "100 Example Street", "Springfield, IL 62701"],
      "contact_lines": ["hello@example.com", "www.example.com"], "register_lines": ["EIN 00-0000000"],
      "bank_lines": ["Example Bank", "IBAN DE00 0000 0000 0000 0000 00"], "color": "#2f5d8a"}


def money(v):
    return f"${v:,.2f}"


def model(n_items=4, kind="invoice", **kw):
    lines = [{"kind": "item", "pos": i, "title": f"Service number {i}", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "day",
              "rate": 100, "rate_text": money(100), "tax_pct": 0, "total": 100, "total_text": money(100)} for i in range(1, n_items + 1)]
    net = 100.0 * n_items
    m = {"kind": kind, "lang": "en", "currency": "USD", "number": "INV-2026-357", "date": "2026-10-26", "date_text": "10/26/2026",
         "title": "Invoice", "company": dict(CO),
         "recipient": {"name": "Example Customer Inc.", "lines": ["Example Customer Inc.", "200 Sample Avenue", "Suite 4", "Portland, OR 97201"]},
         "meta": [["Invoice No.", "INV-2026-357"], ["Date", "10/26/2026"]],
         "intro": "Dear Sir or Madam,\nthank you for your order.", "lines": lines,
         "totals": {"net": net, "net_text": money(net), "tax_lines": [], "gross": net, "rows": [["Net total", money(net)]],
                    "vat_note": "", "show_tax_lines": False},
         "closing": "Payable within 14 days.", "signature": "Kind regards", "signature_name": "Jane Example"}
    m.update(kw)
    return m


def boxes(data):
    return [(round(float(p.mediabox.width), 2), round(float(p.mediabox.height), 2)) for p in PdfReader(io.BytesIO(data)).pages]


def marks(page):  # the short rules at the left edge (fold / punch marks), y from the top
    return sorted(round(r[1], 1) for r in page["rules"] if abs(r[1] - r[3]) < 0.01 and r[0] < 10 * MM and r[2] < 10 * MM)


def find(page, s):
    return [t for t in page["texts"] if s in t["s"]]


# ---------------------------------------------------------------- 1. the setting's values
check(pdf.pdf_paper("letter") == "letter" and pdf.pdf_paper("US-Letter") == "letter" and pdf.pdf_paper(None) == "a4"
      and pdf.pdf_paper("a4") == "a4" and pdf.pdf_paper("legal") == "a4", "pdf_paper: letter / anything else A4")
check(pdf.pdf_paper_ns("a4") is not None and pdf.pdf_paper_ns("letter").A4_W == 612 and pdf.pdf_paper_ns("letter").A4_H == 792,
      "pdf_paper_ns: Letter = 612 x 792 pt")

# ---------------------------------------------------------------- 2. A4 stays the default and unchanged
a4 = pdf.office_pdf(model(), meta=WHEN)
check(pdf.office_pdf(model(paper="a4"), meta=WHEN) == a4, "A4: paper 'a4' gives the same bytes as no paper (the default)")
check(set(boxes(a4)) == {(595.28, 841.89)}, f"A4: MediaBox 595.28 x 841.89 {boxes(a4)}")
la4 = pdfcheck.layout(a4)
check(marks(la4[0]) == [round(105 * MM, 1), round(148.5 * MM, 1), round(210 * MM, 1)], f"A4: fold + punch marks at 105 / 148.5 / 210 mm {marks(la4[0])}")
check(not pdfcheck.problems(a4), f"A4: layout clean {pdfcheck.problems(a4)[:3]}")

# ---------------------------------------------------------------- 3. US-Letter: size, margins, marks, window
let = pdf.office_pdf(model(paper="letter"), meta=WHEN)
check(set(boxes(let)) == {(612.0, 792.0)}, f"Letter: MediaBox 612 x 792 {boxes(let)}")
lay = pdfcheck.layout(let)
pr = pdfcheck.problems(let, right=1 * IN)
check(not pr, f"Letter: layout clean, nothing over the 1 in right margin {pr[:4]}")
check(all(t["x"] >= 1 * IN - 0.6 for t in lay[0]["texts"]), "Letter: no text left of the 1 in margin")
check(marks(lay[0]) == [264.0, 528.0], f"Letter: fold marks on the thirds (3.67 in, 7.33 in), no punch mark {marks(lay[0])}")
for s in ("Example Customer Inc.", "Portland, OR 97201"):
    t = find(lay[0], s)
    check(t and 2.0 * IN <= t[0]["y"] and t[0]["y"] + t[0]["size"] <= 3.2 * IN and t[0]["x"] + t[0]["w"] <= 0.875 * IN + 4.5 * IN,
          f"Letter: {s!r} inside the #10 window (2.0 .. 3.2 in from the top) {t[:1]}")
foot = lay[0]["foot"]
body = [t for t in lay[0]["texts"] if t["size"] > 7.2]
check(foot is not None and foot < 792 - 12 * MM and max(t["y"] + t["size"] for t in body) <= foot + 0.6,
      f"Letter: the footer rule under the body, above the bottom margin ({foot})")
check(all(t["y"] + t["size"] <= 792 - 5 * MM for t in lay[0]["texts"]), "Letter: no text in the bottom page margin")
fl = " ".join(pdfcheck.footer_lines(let)[0])
check("Example Bank" in fl and "hello@example.com" in fl, f"Letter: the footer columns are printed {fl[:120]}")

# ---------------------------------------------------------------- 4. page breaks, totals gap (#3154), watermark (#3155)
big = pdf.office_pdf(model(45, paper="letter"), meta=WHEN)
lb = pdfcheck.layout(big)
check(len(lb) >= 2 and set(boxes(big)) == {(612.0, 792.0)}, f"Letter: 45 positions over several Letter pages ({len(lb)})")
pr = pdfcheck.problems(big, right=1 * IN)
check(not pr, f"Letter: page breaks clean {pr[:4]}")
last = lb[-1]
check(find(last, "Net total") and find(last, "Service number 45"), "Letter: the totals never alone on a page (the last position comes along)")
check(all(p["foot"] is not None for p in lb), "Letter: the footer on every page")
for n, p in enumerate(lb, 1):
    b = [t for t in p["texts"] if t["size"] > 7.2]
    check(max(t["y"] + t["size"] for t in b) <= p["foot"] + 0.6, f"Letter page {n}: the body ends above the footer")
pdf_a4_big = pdf.office_pdf(model(45), meta=WHEN)
check(len(boxes(big)) >= len(boxes(pdf_a4_big)), f"Letter (shorter page) never needs fewer pages than A4 ({len(boxes(big))} / {len(boxes(pdf_a4_big))})")


def gap(data):  # #3154: from the last position's line to the totals label
    p = pdfcheck.layout(data)[-1]
    return round(find(p, "Net total")[0]["y"] - find(p, "Service number 4")[-1]["y"], 1)


# 2.434.0 (#3603): an invoice prints in look A now (totals at the bottom of the page, the papers differ in height): the #3154
# gap compared without that fill
fill, pdf.PDF_SUM_FILL = pdf.PDF_SUM_FILL, 0.0
g_let, g_a4 = gap(pdf.office_pdf(model(paper="letter"), meta=WHEN)), gap(pdf.office_pdf(model(), meta=WHEN))
pdf.PDF_SUM_FILL = fill
check(g_let == g_a4, f"#3154: the same totals gap in Letter as in A4 for a short document ({g_let} / {g_a4})")

dr = pdf.office_pdf(model(3, paper="letter", draft_mark="DRAFT"), meta=WHEN)
raw = PdfReader(io.BytesIO(dr)).pages[0].get_contents().get_data()
tm = re.search(rb"0\.7071 0\.7071 -0\.7071 0\.7071 (-?[\d.]+) (-?[\d.]+) Tm", raw)
w = pdf.pdf_text_width("DRAFT", 120, True)
want = ((612 - w * 0.7071) / 2 + 40, (792 - w * 0.7071) / 2 - 60)
check(tm and abs(float(tm.group(1)) - want[0]) < 0.02 and abs(float(tm.group(2)) - want[1]) < 0.02,
      f"#3155: the draft watermark centred on the Letter page {tm.groups() if tm else None} / {want}")

# ---------------------------------------------------------------- 5. PDF/A, e-invoice, letterhead
XML = b'<?xml version="1.0" encoding="UTF-8"?><rsm:CrossIndustryInvoice xmlns:rsm="urn:example"/>'
ei = pdf.office_pdf(model(paper="letter"), xml=XML, meta=WHEN)
check(b"pdfaid:part" in ei and b"/Metadata" in ei, "PDF/A marked in Letter (XMP)")
check(b"/AFRelationship /Alternative" in ei and b"factur-x.xml" in ei and b"/OutputIntents" in ei, "Letter: the embedded e-invoice + sRGB OutputIntent as in A4")
ef = PdfReader(io.BytesIO(ei)).attachments
check("factur-x.xml" in ef and ef["factur-x.xml"][0] == XML, "Letter: the e-invoice XML comes out unchanged")


def emit(objs, i):  # a Letter letterhead page made here: a coloured band on top (form XObject)
    content = b"0.184 0.365 0.541 rg 0 760 612 32 re f"
    objs.append(b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    return len(objs)


LH = {"m1": [50, 25, 30, 25], "m2": [35, 25, 30, 25], "hide_head": 1, "hide_footer": 0, "pages": 1, "emit": emit}
bl = pdf.office_pdf(model(30, paper="letter", letterhead=LH), meta=WHEN)
check(set(boxes(bl)) == {(612.0, 792.0)}, f"Letter + letterhead: Letter pages {boxes(bl)}")
xo = (PdfReader(io.BytesIO(bl)).pages[0].get("/Resources") or {}).get("/XObject") or {}
check(any(v.get_object().get("/Subtype") == "/Form" for v in xo.values()), "Letter + letterhead: the letterhead form on page 1")
pr = pdfcheck.problems(bl, right=25 * MM)
check(not pr, f"Letter + letterhead: layout clean {pr[:3]}")
g = pdf.pdf_paper_ns("letter").bp_geometry(LH)
check(abs(g["cw"] - (612 - 50 * MM)) < 0.01, f"bp_geometry in Letter: the text width from the Letter page ({g['cw']:.1f})")

os.makedirs(OUT, exist_ok=True)
for name, d in (("p2357-letter-invoice.pdf", ei), ("p2357-letter-letterhead.pdf", bl), ("p2357-letter-draft.pdf", dr)):
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(d)

# ---------------------------------------------------------------- 6. the module stays A4; parallel runs; pdf_paper_bind
check(pdf.A4_W == 595.28 and pdf.A4_H == 841.89 and pdf.PAPER == "a4" and pdf._Page.H == 841.89 and pdf.PDF_MARKS[1] == 148.5 * MM,
      "the module's globals stay A4 after the Letter runs")
res = {}


def run(k, paper):
    res[k] = [boxes(pdf.office_pdf(model(20, paper=paper), meta=WHEN)) for _ in range(3)]


ts = [threading.Thread(target=run, args=(k, p)) for k, p in (("a", "a4"), ("l", "letter"), ("a2", None), ("l2", "letter"))]
for t in ts:
    t.start()
for t in ts:
    t.join()
check(all(set(sum(res[k], [])) == {(595.28, 841.89)} for k in ("a", "a2")) and all(set(sum(res[k], [])) == {(612.0, 792.0)} for k in ("l", "l2")),
      f"two sizes at once in threads: each PDF its own size {res}")

PAPER, _Page, A4_W, PDF_CW = pdf.PAPER, pdf._Page, pdf.A4_W, pdf.PDF_CW  # as a module that imports them at its top (mealpdf)


def bind_f():
    return PAPER, _Page().H, A4_W, PDF_CW, bind_g()


def bind_g():
    return _Page.W


r = pdf.pdf_paper_bind(bind_f, "letter")()
check(r == ("letter", 792.0, 612.0, 612 - 2 * IN, 612.0), f"pdf_paper_bind: the imported names (in helpers too) from the Letter copy {r}")
check(bind_f() == ("a4", 841.89, 595.28, pdf.PDF_CW, 595.28) and pdf.pdf_paper_bind(bind_f, "a4") is bind_f, "pdf_paper_bind: A4 = the function itself")

sys.exit(done("p2357_a_paper_pdf"))
