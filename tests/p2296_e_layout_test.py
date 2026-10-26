#!/usr/bin/env python3
"""2.296.0 E (#3166, #3170): the block layout and the columns of the office PDF (kalmido/office/pdf.py of the source tree), no
server, no container. Every PDF goes through the layout check (tests/pdfcheck.py). Invented companies and figures only.
 - #3166 blocks longer than a page break by lines (never over the footer or the page edge): intro of 70 lines, closing of 60
   lines, a text row of 100 lines (also on a letterhead with a 150 mm top margin on the following pages), a position with a
   detail of 90 lines, 60 rights rows, a payment text of 80 lines; every line printed
 - #3166 an intro of 35 lines starts on page 1 under the title (page 1 was left without a body)
 - #3166 a quotation without signature with a rights appendix: no page with only the reference lines or only the appendix
   heading, the heading keeps the first rights row, three pages
 - #3170 "12,5 Personentage" stays in the quantity column (left of it ends the service text), a quantity wider than the widest
   column puts its unit on a second line; an English timesheet date stays in the date column
 - #3170 a company name of three lines: the sender line keeps street and town, the signature prints every name line
 - #3170 eleven address lines are all printed; a long table heading, a long head label and a long number / project line
   above the rights appendix wrap (no overlap, nothing over the margin)
usage: p2296_e_layout_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."))
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from kt import check, done  # noqa: E402

try:
    from pypdf import PdfReader  # noqa: F401
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

MM = pdf.MM
CO = {"name": "Studio Nordlicht GmbH", "lines": ["Große Elbstraße 145b", "20457 Hamburg"], "contact_lines": ["E-Mail: info@example.com"],
      "register_lines": ["Amtsgericht Hamburg HRB 123456"], "bank_lines": ["IBAN DE89 3704 0044 0532 0130 00"], "color": "#2f5d8a"}
SENT = "Dies ist ein Satz mit einigen Wörtern, der die Zeile füllt und umbricht, damit der Absatz wächst."


def item(i, detail="", **kw):
    d = {"kind": "item", "pos": i, "title": f"Leistung {i}", "detail": detail, "qty": 1, "qty_text": "1", "unit_text": "Tag",
         "rate": 100, "rate_text": "100,00 €", "tax_pct": 19, "total": 100, "total_text": "100,00 €"}
    d.update(kw)
    return d


def model(**kw):
    m = {"kind": "offer", "lang": "de", "currency": "EUR", "number": "KVA-2026-296", "date": "2026-10-25", "title": "Angebot",
         "project_title": "Imagefilm", "company": dict(CO), "recipient": {"name": "Beispielkunde AG", "lines": ["Marktplatz 2", "54321 Beispielort"]},
         "meta": [["Angebot Nr.", "KVA-2026-296"], ["Datum", "25.10.2026"]], "intro": "Sehr geehrte Damen und Herren,\nvielen Dank.",
         "lines": [item(i) for i in range(1, 4)], "totals": {"rows": [["Summe Netto", "300,00 €"]], "vat_note": "zzgl. MwSt."},
         "closing": "Wir freuen uns.", "signature": "Mit freundlichen Grüßen", "signature_name": "Jana Muster",
         "labels": {"page_of": "Seite {x} von {y}"}}
    m.update(kw)
    return m


def para(n, word="Zeile"):
    return "\n".join(f"{word} {i + 1}: kurz" for i in range(n))


def texts(data):
    return [t["s"] for p in pdfcheck.layout(data) for t in p["texts"]]


def body_texts(p):
    return [t for t in p["texts"] if t["size"] > 7.2 and (p["foot"] is None or t["y"] < p["foot"])]


def clean(who, data, **kw):
    pr = pdfcheck.problems(data, **kw)
    check(not pr, f"{who}: layout clean {pr[:4]}")


# ---------------------------------------------------------------- 1. #3166 blocks longer than a page
LH = {"m1": [45, 20, 32, 25], "m2": [150, 20, 32, 25], "hide_head": 0, "hide_footer": 0, "pages": 0}
cases = [("intro 70 lines", model(intro=para(70)), 70),
         ("closing 60 lines", model(closing=para(60)), 60),
         ("text row 100 lines", model(lines=[item(1), {"kind": "text", "text": para(100)}, item(2)]), 100),
         ("text row 100 lines, letterhead 150 mm", model(lines=[item(1), {"kind": "text", "text": para(100)}, item(2)], letterhead=LH), 100),
         ("intro 70 lines, letterhead 150 mm", model(intro=para(70), letterhead=LH), 70),
         ("detail 90 lines", model(lines=[item(1, detail=para(90)), item(2)]), 90),
         ("detail 90 lines, letterhead 150 mm", model(lines=[item(1, detail=para(90)), item(2)], letterhead=LH), 90),
         ("payment text 80 lines", model(kind="invoice", payment={"text": para(80), "iban": "DE89370400440532013000"}), 80)]
for who, m, n in cases:
    data = pdf.office_pdf(m)
    clean(f"#3166 {who}", data)
    allt = texts(data)
    check(all(f"Zeile {i}: kurz" in allt for i in range(1, n + 1)), f"#3166 {who}: every line printed")
    lay = pdfcheck.layout(data)
    check(len(lay) >= 2, f"#3166 {who}: breaks over pages ({len(lay)})")
    for k, p in enumerate(lay, 1):
        if p["foot"] is not None:
            check(all(t["y"] + t["size"] <= p["foot"] + 0.6 for t in body_texts(p)), f"#3166 {who}: page {k}: the body ends above the footer rule")

m = model(rights={"title": "Rechteübertragung", "rows": [[f"Recht {i}", SENT] for i in range(1, 61)], "note": "Ein kleiner Hinweis zu den Rechten."})
data = pdf.office_pdf(m)
clean("#3166 60 rights rows", data)
allt = texts(data)
check(all(f"Recht {i}" in allt for i in range(1, 61)) and "Ein kleiner Hinweis zu den Rechten." in allt, "#3166 60 rights rows: every row and the note printed")
lay = pdfcheck.layout(data)
head = [k for k, p in enumerate(lay) if any(t["s"] == "RECHTEÜBERTRAGUNG" for t in p["texts"])]
check(len(head) == 1 and any(t["s"] == "Recht 1" for t in lay[head[0]]["texts"]), f"#3166: the appendix heading keeps the first rights row ({head})")

# an intro of 35 lines: page 1 has the title and the first intro lines (was: the whole group moved to page 2)
data = pdf.office_pdf(model(intro=para(35)))
clean("#3166 intro 35 lines", data)
p1 = [t["s"] for t in pdfcheck.layout(data)[0]["texts"]]
check("ANGEBOT" in p1 and "Zeile 1: kurz" in p1 and "Zeile 2: kurz" in p1, "#3166: an intro of 35 lines starts on page 1 under the title")

# a quotation without signature with a rights appendix: the reference line ("see appendix") was chained over the appendix
# heading (a new page) to the whole rights block -> the last position, the totals and the reference moved to a page of their
# own before the appendix (3 pages for one page of positions + one appendix page)
m = model(signature="", signature_name="", lines=[item(i) for i in range(1, 6)],
          rights={"title": "Rechteübertragung", "rows": [[f"Recht {i}", "weltweit, zeitlich unbegrenzt"] for i in range(1, 16)]})
data = pdf.office_pdf(m)
clean("#3166 no signature + appendix", data)
lay = pdfcheck.layout(data)
p1 = [t["s"] for t in lay[0]["texts"]]
check(all(f"Leistung {i}" in p1 for i in range(1, 6)) and "Summe Netto" in p1, "#3166 no signature + appendix: positions and totals stay on page 1")
check(len(lay) == 2 and any(t["s"] == "Recht 1" for t in lay[1]["texts"]), f"#3166 no signature + appendix: two pages, the appendix on page 2 ({len(lay)})")

# ---------------------------------------------------------------- 2. #3170 columns
QW = "12,5 Personentage"
LW = "Konzeptionsdrehbuchregiekameralichttonschnittfarbemischunggrafikuntertitelmusiklizenzen"  # cut by characters: fills the column
m = model(lines=[item(1, qty_text="12,5", unit_text="Personentage", title=LW),
                 item(2, qty_text="1.234,50", unit_text="Stunden", title="Postproduktion"),
                 item(3, qty_text="3", unit_text="Pauschalen nach besonderer Vereinbarung", title="Lizenz")])
data = pdf.office_pdf(m)
clean("#3170 quantities", data)
p = pdfcheck.layout(data)[0]
q = next((t for t in p["texts"] if t["s"] == QW), None)
title_right = max(t["x"] + t["w"] for t in p["texts"] if t["size"] == 9.6 and abs(t["x"] - (pdf.PDF_L + 25)) < 1)  # the service column
check(q is not None and q["x"] >= title_right + 2, f"#3170: {QW!r} stays in the quantity column (x {q and round(q['x'], 1)}, the service text ends at {title_right:.1f})")
rate = next((t for t in p["texts"] if t["s"] == "100,00 €"), None)
check(q is not None and rate is not None and q["x"] + q["w"] <= rate["x"] - 2, "#3170: the quantity ends left of the price")
q3 = next((t for t in p["texts"] if t["s"] == "3" and t["size"] == 8.8), None)
u3 = next((t for t in p["texts"] if t["s"].startswith("Pauschalen")), None)
check(q3 is not None and u3 is not None and u3["y"] > q3["y"] + 5 and u3["x"] >= title_right, "#3170: a quantity wider than the widest column: the unit on its own line")

ts = model(lang="en", kind="delivery", noprice=True, pos_w=62, totals={"rows": [["Total hours", "3,0 h"]]},
           lines=[item("9 September 2026", title="Jana Muster: Schnitt und Farbkorrektur", qty_text="1,5 h", unit_text=""),
                  item("30 September 2026", title="Ole Petersen: Tonmischung", qty_text="1,5 h", unit_text="")])
data = pdf.office_pdf(ts)
clean("#3170 English timesheet", data)
p = pdfcheck.layout(data)[0]
dt = [t for t in p["texts"] if t["s"].endswith("September 2026")]
nm = [t for t in p["texts"] if t["s"].startswith(("Jana Muster:", "Ole Petersen:"))]
check(len(dt) == 2 and nm and max(t["x"] + t["w"] for t in dt) <= min(t["x"] for t in nm) - 2, "#3170: the English date stays in the date column")

# ---------------------------------------------------------------- 3. #3170 company name of three lines, address, headings, labels
CO3 = dict(CO, name="Studio Nordlicht GmbH Film · Foto · Motion Design Niederlassung Hamburg-Altona",
           name_lines=["Studio Nordlicht GmbH", "Film · Foto · Motion Design", "Niederlassung Hamburg-Altona"],
           lines=["Große Elbstraße 145b", "Hinterhaus, 3. OG", "20457 Hamburg"])
data = pdf.office_pdf(model(company=CO3))
clean("#3170 three name lines", data)
p = pdfcheck.layout(data)[0]
snd = [t["s"] for t in p["texts"] if t["size"] == 7 and abs(t["y"] - pdf.PDF_ADDR_TOP) < 1]
check(len(snd) == 1 and "Große Elbstraße 145b" in snd[0] and "20457 Hamburg" in snd[0], f"#3170: the sender line keeps street and town {snd}")
check(len(snd) == 1 and pdf.pdf_text_width(snd[0], 7) <= pdf.PDF_ADDR_W + 0.1, "#3170: the sender line fits the address field")
sig = [t["s"] for t in p["texts"] if t["size"] == 9.6]
i = sig.index("Jana Muster") if "Jana Muster" in sig else -1
check(i >= 0 and sig[i + 1:i + 4] == CO3["name_lines"], f"#3170: the signature prints every name line under the name ({sig[i:i + 4]})")
# one part alone too long: shortened, the address stays
lone = pdf.pdf_sender_line("Stadtwerke Musterstadt Versorgungs- und Verkehrsgesellschaft mbH Niederlassung Beispielhausen · Marktstraße 5 · 50667 Köln",
                           "Stadtwerke Musterstadt Versorgungs- und Verkehrsgesellschaft mbH Niederlassung Beispielhausen")
check(lone.endswith("· Marktstraße 5 · 50667 Köln") and "…" in lone and pdf.pdf_text_width(lone, 7) <= pdf.PDF_ADDR_W, f"#3170: a long name gives way to the address ({lone})")

addr = [f"Adresszeile {i}" for i in range(1, 12)]
data = pdf.office_pdf(model(recipient={"name": "Beispielkunde AG", "lines": addr}))
clean("#3170 eleven address lines", data)
allt = texts(data)
check(all(a in allt for a in addr), "#3170: every address line printed (was cut after eight)")

hd = "Leistungsblock mit einer sehr langen Überschrift, die über die ganze Breite der Tabelle hinaus reichen würde und noch weiter"
data = pdf.office_pdf(model(lines=[{"kind": "heading", "title": hd}, item(1)]))
clean("#3170 long heading", data)
check("".join(t["s"] for t in pdfcheck.layout(data)[0]["texts"] if t["bold"] and t["size"] == 8).replace(" ", "") == hd.upper().replace(" ", ""),
      "#3170: the long heading wraps, every word printed")

lab = "Ein sehr langes eigenes Feld mit vielen Wörtern im Namen"
data = pdf.office_pdf(model(fields=[{"name": lab, "value": "Wert 4711-0815"}, {"name": "Kurz", "value": "Ein langer Wert, der umbricht und umbricht und umbricht"}]))
clean("#3170 long head label", data)
allt = texts(data)
check("Wert 4711-0815" in allt and any(s.startswith("Ein sehr langes") for s in allt), "#3170: label and value of the long field printed")

data = pdf.office_pdf(model(project_title="Langzeitdokumentation über die Ausbildungsförderung im Landkreis Vorpommern-Greifswald inklusive aller Teilprojekte",
                            rights={"title": "Rechteübertragung", "rows": [["Zeit", "unbegrenzt"]]}))
clean("#3170 long line above the rights appendix", data)

sys.exit(done("p2296_e_layout"))  # bundle 2.305: the exit code (was 0 with failures)
