#!/usr/bin/env python3
# kalmido-suite: after=p2296_a_pdfa nodata
"""2.413.0 (#3500): the office PDF writer of kalmido/office/pdf.py of the source tree prints from ONE font size scale
(FS_FOOT 7, FS_SMALL 8, FS_BODY 9.6, FS_SUM 10.4, FS_TITLE 14, FS_BRAND 15) instead of 17 loose sizes between 6.8 and 16 pt.
No server, no container; invented companies and figures only. freelancer-matrix: n/a (the writer has no organisation in it)
 - every /F1 / /F2 size in the page streams of a delivery note, an invoice, a reminder and a quotation (look A since
   2.434.0 also for invoices / reminders: the scale 2 pt smaller, never below 6 pt) and a long quotation with the rights
   appendix is a step of the scale; the footer's own fitting sizes (6.5-6.9 pt) and
   the 120 pt draft mark stay allowed
 - no text call of the writer passes a bare number as its size (the named steps only)
usage: p2413_pdf_scale_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import ast
import importlib.util
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
PATH = os.path.join(SRC, "kalmido", "office", "pdf.py")
spec = importlib.util.spec_from_file_location("office_pdf", PATH)
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

CO = {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: kontakt@example.com"],
      "register_lines": ["Amtsgericht Musterstadt HRB 1"], "bank_lines": ["IBAN DE00 0000 0000 0000 0000 00"], "color": "#2f5d8a"}


def money(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def model(kind="invoice", n=3, title="Rechnung", number="RE-2026-413"):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung {i}", "detail": "Vorbereitung und Abstimmung", "qty": 2, "qty_text": "2",
              "unit_text": "Tage", "rate": 100, "rate_text": money(100), "tax_pct": 19, "total": 200, "total_text": money(200)} for i in range(1, n + 1)]
    return {"kind": kind, "lang": "de", "currency": "EUR", "number": number, "date": "2026-10-28", "date_text": "28.10.2026",
            "title": title, "project_title": "Imagefilm Hafenlichter", "company": dict(CO),
            "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
            "meta": [["Nr.", number], ["Datum", "28.10.2026"]], "lines": lines, "note": "Zahlbar innerhalb von 14 Tagen ohne Abzug.",
            "totals": {"rows": [["Summe netto", money(200 * n)], ["MwSt. 19 %", money(38 * n)], ["Gesamt", money(238 * n), True]], "show_tax_lines": True},
            "labels": {"pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt", "vat": "MwSt."}}


def offer(n=4):
    m = model("offer", n, "Kostenvoranschlag", "KVA-2026-413")
    m.update(intro="Sehr geehrte Damen und Herren,\nvielen Dank für Ihre Anfrage.", accept_on=1, signature="Mit freundlichen Grüßen",
             closing="Wir freuen uns auf die Zusammenarbeit.", terms_line="Es gelten unsere AGB, siehe Anhang.",
             rights={"title": "Rechteübertragung", "note": "Gilt nach vollständiger Zahlung.",
                     "rows": [["Zeitliche Auswertung", "unbegrenzt"], ["Räumliche Auswertung", "weltweit"]]})
    return m


TF = re.compile(rb"/F[12] ([\d.]+) Tf")


def sizes(data):
    from pypdf import PdfReader
    out = set()
    for page in PdfReader(__import__("io").BytesIO(data)).pages:
        c = page.get_contents()
        out |= {round(float(x), 2) for x in TF.findall(c.get_data() if c is not None else b"")}
    return out


SCALE = [pdf.FS_FOOT, pdf.FS_SMALL, pdf.FS_BODY, pdf.FS_SUM, pdf.FS_TITLE, pdf.FS_BRAND]
check(SCALE == [7, 8, 9.6, 10.4, 14, 15], f"#3500: the scale as decided ({SCALE})")
FOOT_FIT = {6.5, 6.6, 6.9, round(pdf.P3F_MIN_FS, 2)}
plain = {round(x, 2) for x in SCALE} | FOOT_FIT | {120.0}
look_a = {round(max(pdf.PDF_FS_MIN, x + pdf.PDF_FS_DELTA), 2) for x in SCALE} | {round(max(pdf.PDF_FS_MIN, x + pdf.PDF_FS_DELTA), 2) for x in FOOT_FIT} | FOOT_FIT | {120.0}
# 2.434.0 A (#3603): invoices and reminders print in look A as well, the delivery note keeps the plain scale
for name, data, ok in (("invoice", pdf.office_pdf(model()), look_a), ("reminder", pdf.office_pdf(model("reminder", 2, "Mahnung", "MA-2026-413")), look_a),
                       ("delivery note", pdf.office_pdf(model("delivery", 2, "Lieferschein", "LS-2026-413")), plain),
                       ("quotation", pdf.office_pdf(offer()), look_a), ("long quotation", pdf.office_pdf(offer(40)), look_a)):
    got = sizes(data)
    check(got and got <= ok, f"#3500: {name}: only sizes of the scale ({sorted(got)}; off the scale {sorted(got - ok)})")

# the source: no bare number as the size of a text call (the footer's fitting helpers excepted)
src = open(PATH, encoding="utf-8").read()
SZ = {"text": 3, "para": 3, "pdf_text_width": 1, "pdf_wrap": 1, "pb_wrap": 1, "pdf_sender_line": 4, "q3_line": 4}
fit = {n for f in ast.walk(ast.parse(src)) if isinstance(f, ast.FunctionDef) and f.name in ("p3f_w", "bwa_half", "bwa_wrap") for n in range(f.lineno, f.end_lineno + 1)}
bare = []
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.Call) and n.lineno not in fit:
        name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
        if name in SZ and len(n.args) > SZ[name]:
            a = n.args[SZ[name]]
            for x in (a.body, a.orelse) if isinstance(a, ast.IfExp) else (a,):
                if isinstance(x, ast.Constant) and isinstance(x.value, (int, float)) and x.value < 60:
                    bare.append(f"{n.lineno}:{x.value}")
check(not bare, f"#3500: text calls use the named steps, no bare sizes ({bare[:8]})")
sys.exit(done("p2413_pdf_scale"))
