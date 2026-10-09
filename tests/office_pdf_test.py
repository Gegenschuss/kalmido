#!/usr/bin/env python3
"""2.36.1 (#1021, part D): the PDF writer of Office & finance (kalmido/office/pdf.py), no server, no container.
 - a quotation from an invented print model (the structure of office.docs' odoc_render): a valid PDF 1.4 that pypdf
   opens; the text layer carries the number, the recipient, every position, the net total, the raw data option, the
   rights texts (umlauts, sharp s, euro sign through WinAnsiEncoding) and "Seite 1 von n"
 - 40 positions: several pages, every following page with the small head (title + number) and the repeated table head,
   the totals never alone on a page (the page with the net total has a position), a category heading never the last
   thing on a page, "Page x of y" on every page, the footer columns on every page
 - with a logo (a PNG made here with Pillow, also with transparency, and a JPEG): an image XObject on page 1 and on the
   following pages; without a logo the company name stands in the letterhead
 - English document in USD: English labels, "Page 1 of", the amounts as formatted by the model, the exchange rate note
 - the width tables: a long word is cut, a line never exceeds the column; the money / date formats of the writer
usage: office_pdf_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
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
office_pdf = pdf.office_pdf
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)


# ---------------------------------------------------------------- fixture: invented company, client and figures (KV02 totals)
def money_de(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s + " €"


def item(pos, title, qty, rate, unit="Tage", detail="", tax=19):
    tot = round(qty * rate, 2)
    return {"kind": "item", "pos": pos, "title": title, "detail": detail, "qty": qty, "qty_text": str(qty).replace(".5", ",5").replace(".0", ""),
            "unit": "day", "unit_text": unit, "rate": rate, "rate_text": money_de(rate), "tax": "standard", "tax_pct": tax,
            "total": tot, "total_text": money_de(tot)}


def fixture(n_items=12, lang="de", currency="EUR", logo_path=None, raw="optional", with_text=True):
    de = lang == "de"
    lines = [{"kind": "heading", "title": "Video"},
             item(1, "Storyboard-Erstellung (inklusive Nach-Nutzung als reference images für Generative Video)", 3, 980,
                  detail="(enthält Generative Medienherstellung Image -> Reference Frames für Produktion)"),
             item(2, "Generative Medienherstellung (Video)", 4, 960), item(3, "Generative Medienherstellung (Audio)", 1, 960),
             item(4, "Animation 2D / Motion Design", 4.5, 1080), item(5, "Schnitt", 2, 980),
             {"kind": "heading", "title": "Stock"}, item(6, "Stockfootage HD", 10, 75, "Stk."),
             {"kind": "heading", "title": "Audio"}, item(7, "Musikschnitt", 0.5, 980),
             item(8, "Musik-Track inkl. Auswahl und Lizenzierung", 1, 300, "Stk."), item(9, "Sound Design", 1, 980),
             item(10, "Tonschnitt & Mischung", 0.5, 580)]
    if with_text:
        lines.append({"kind": "text", "text": "Die Untertitel liefern wir als SRT-Datei in Deutsch; weitere Sprachen auf Anfrage."})
    lines += [{"kind": "heading", "title": "Office"}, item(11, "Untertitel, Grundgebühr", 1, 210, "pauschal"),
              item(12, "Untertitel (ohne Transskript), Minutenpreis", 2, 50, "Min.")]
    net = 17680.0
    for i in range(13, n_items + 1):  # more positions for the multi-page case (round figures)
        if i % 6 == 1:
            lines.append({"kind": "heading", "title": f"Kategorie {i // 6 + 1}"})
        lines.append(item(i, f"Zusatzleistung Nr. {i} mit etwas längerem Titel", 1, 100, "Tage", detail="Erläuterung zur Position" if i % 4 == 0 else ""))
        net += 100
    lines.append({"kind": "producing", "title": "Producing", "qty": 4.5, "qty_text": "4,5", "unit": "day", "unit_text": "Tage", "rate": 600,
                  "rate_text": money_de(600), "tax_pct": 19, "total": 2700, "total_text": money_de(2700),
                  "detail": "4,5 Tage = 14 Produktionstage / 3, auf halbe Tage gerundet"})
    net += 2700
    raw_amount = 3422.5
    if raw == "optional":
        lines.append({"kind": "raw", "optional": True, "title": "Optional: Bereitstellung der Rohdaten" if de else "Optional: Delivery of raw data",
                      "qty": None, "qty_text": "", "unit_text": "", "rate": raw_amount, "total": raw_amount, "total_text": money_de(raw_amount),
                      "detail": "25 % der Positionen mit Rohdaten"})
        rows = [["Summe Netto" if de else "Net Total", money_de(net)], ["inklusive Rohdaten" if de else "including raw data", money_de(net + raw_amount)]]
    elif raw == "included":
        lines.append({"kind": "raw", "optional": False, "title": "Bereitstellung der Rohdaten", "qty": 1, "qty_text": "1", "unit_text": "pauschal",
                      "rate": raw_amount, "rate_text": money_de(raw_amount), "tax_pct": 19, "total": raw_amount, "total_text": money_de(raw_amount)})
        rows = [["Summe Netto", money_de(net + raw_amount)], ["ohne Rohdaten", money_de(net)]]
    else:
        rows = [["Summe Netto", money_de(net)]]
    m = {
        "kind": "offer", "lang": lang, "currency": currency, "fx_rate": 1.09 if currency == "USD" else None,
        "fx_note": ("Exchange rate €1: $1.09" if currency == "USD" else ""), "vat_mode": "vat", "raw_mode": raw, "status": "draft",
        "number": "KVA-2026-031", "date": "2026-10-09", "date_text": "09.10.2026", "valid_until": "2026-11-08", "valid_until_text": "08.11.2026",
        "title": "Kostenvoranschlag" if de else "Quotation", "project_title": "Imagefilm Herbstkampagne", "project_ref": "PO-4711",
        "company": {"name": "Studio Nordlicht GmbH", "lines": ["Studio Nordlicht GmbH", "Hafenstraße 12", "20457 Hamburg"],
                    "contact_lines": ["Tel. +49 40 000000", "post@beispiel-studio.example", "www.beispiel-studio.example"],
                    "register_lines": ["Geschäftsführung: Jana Muster", "Amtsgericht Hamburg HRB 00000", "USt-IdNr. DE000000000"],
                    "bank_lines": ["Beispielbank", "IBAN DE00 0000 0000 0000 0000 00", "BIC XXXXDEXXXXX"],
                    "sender_line": "Studio Nordlicht GmbH · Hafenstraße 12 · 20457 Hamburg", "logo_path": logo_path, "color": "#2f5d8a"},
        "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "z. Hd. Max Mustermann", "Marktstraße 5", "50667 Köln"]},
        "meta": [["Angebot Nr." if de else "Quotation No.", "KVA-2026-031"], ["Datum" if de else "Date", "09.10.2026"],
                 ["Kunde" if de else "Client", "Beispielkunde AG"], ["Ref./PO-Nr.", "PO-4711"], ["Gültig bis" if de else "Valid until", "08.11.2026"]],
        "intro": ("Sehr geehrte Damen und Herren,\nfür das oben genannte Projekt bieten wir Ihnen folgende Leistungen an:" if de
                  else "Dear Sir or Madam,\nfor the project referenced above we offer the following services:"),
        "lines": lines,
        "totals": {"net": net, "net_text": money_de(net), "tax_lines": [{"rate_key": "standard", "pct": 19, "base": net, "amount": round(net * 0.19, 2), "label": "MwSt. 19 %"}],
                   "gross": round(net * 1.19, 2), "net_incl_raw": net + raw_amount, "net_incl_raw_text": money_de(net + raw_amount), "rows": rows,
                   "vat_note": "Alle Preise zuzüglich 7 % bzw. 19 % MwSt." if de else "All prices plus 7 % or 19 % VAT.", "show_tax_lines": False},
        "rights": {"title": "Rechteübertragung" if de else "Transfer of rights",
                   "rows": ([["Zeitliche Auswertung", "unbegrenzt"], ["Räumliche Auswertung", "weltweit außer Musik auf Messe/Event (DE)"],
                             ["Mediale Auswertung", "intern, web, unpaid media"]] if de else
                            [["Duration of License", "in perpetuity"], ["Territorial Rights", "worldwide except music on trade shows / live events (DE)"],
                             ["Rights by Medium", "internal use, web, unpaid media"]]),
                   "exceptions": "", "exclusive": 0, "note": "Im Übrigen gelten unsere AGB." if de else "Otherwise, our general terms and conditions apply."},
        "closing": "Wir freuen uns auf die Zusammenarbeit und stehen für Rückfragen gerne zur Verfügung.",
        "signature": "Mit freundlichen Grüßen" if de else "With best regards", "signature_name": "Jana Muster",
        "valid_note": "Dieses Angebot ist gültig bis 08.11.2026." if de else "This quotation is valid until 8 November 2026.",
        "fields": [{"name": "Leistungszeitraum", "value": "November 2026"}],
        "labels": ({"offer_no": "Angebot Nr.", "pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "vat": "MwSt.", "total": "Gesamt",
                    "net_total": "Summe Netto", "incl_raw": "inklusive Rohdaten", "excl_raw": "ohne Rohdaten", "rights": "Rechteübertragung",
                    "page_of": "Seite {x} von {y}", "order": "Auftragserteilung"} if de else
                   {"offer_no": "Quotation No.", "pos": "No.", "title": "Title", "qty": "x", "unit_price": "Unit Price", "vat": "VAT", "total": "Total",
                    "net_total": "Net Total", "incl_raw": "including raw data", "excl_raw": "excluding raw data", "rights": "Transfer of rights",
                    "page_of": "Page {x} of {y}", "order": "Order confirmation"}),
        "formats": {"date": "dd.mm.yyyy", "decimal": ",", "thousands": ".", "currency_pos": "after"},
        "internal": {"costs": 3750, "margin": 16630},
    }
    return m


def texts(data):
    r = PdfReader(io.BytesIO(data))
    return r, [p.extract_text() or "" for p in r.pages]


def squash(s):
    return re.sub(r"\s+", "", s)


def has_image(page):
    try:
        xo = page["/Resources"].get("/XObject") or {}
        return any(xo[k].get_object().get("/Subtype") == "/Image" for k in xo)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 1. the standard quotation (12 positions, DE, EUR)
data = office_pdf(fixture())
check(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"), "a PDF 1.4 file with a trailer")
r, T = texts(data)
n = len(r.pages)
check(2 >= n >= 1, f"12 positions fit on one or two pages ({n})")
all_t = "\n".join(T)
for want in ("KVA-2026-031", "Beispielkunde AG", "z. Hd. Max Mustermann", "50667 Köln", "KOSTENVORANSCHLAG", "Imagefilm Herbstkampagne",
             "Storyboard-Erstellung", "Tonschnitt & Mischung", "Untertitel, Grundgebühr", "2.940,00 €", "20.380,00 €", "23.802,50 €",
             "Optional: Bereitstellung der Rohdaten", "3.422,50 €", "Zeitliche Auswertung", "unbegrenzt",
             "weltweit außer Musik auf Messe/Event (DE)", "intern, web, unpaid media", "Im Übrigen gelten unsere AGB.",
             "Alle Preise zuzüglich 7 % bzw. 19 % MwSt.", "Mit freundlichen Grüßen", "Jana Muster", "Leistungszeitraum", "November 2026",
             "Ort, Datum", "Geschäftsführung: Jana Muster", "IBAN DE00 0000", "Die Untertitel liefern wir als SRT-Datei"):
    check(want in all_t, f"text layer has {want!r}")
check(squash("Seite 1 von " + str(n)) in squash(T[0]), f"page 1 says 'Seite 1 von {n}'")
check(all(squash(f"Seite {i + 1} von {n}") in squash(t) for i, t in enumerate(T)), "every page carries 'Seite x von y'")
check(all("Studio Nordlicht GmbH" in t and "Hafenstraße 12" in t and "Beispielbank" in t for t in T), "the footer columns on every page")
check(squash("RECHTEÜBERTRAGUNG") in squash(all_t) and squash("AUFTRAGSERTEILUNG") in squash(all_t), "section headings (umlauts in the bold font)")
check(squash("POS.LEISTUNGMENGEPREISMWST.GESAMT") in squash(T[0]), "the table head on page 1")
check("3750" not in all_t and "16630" not in all_t and "16.630" not in all_t, "internal costs / margin are never printed")
check(not has_image(r.pages[0]) and "Studio Nordlicht GmbH" in T[0].split("\n")[0], "without a logo: the company name in the letterhead, no image")
check(r.metadata.title == "Kostenvoranschlag KVA-2026-031" and r.metadata.author == "Studio Nordlicht GmbH", f"document info: {r.metadata}")

# ---------------------------------------------------------------- 2. 40 positions: several pages
data40 = office_pdf(fixture(40))
r40, T40 = texts(data40)
n40 = len(r40.pages)
check(n40 >= 3, f"40 positions need several pages ({n40})")
for i, t in enumerate(T40):
    check(squash(f"Seite {i + 1} von {n40}") in squash(t), f"page {i + 1}: 'Seite {i + 1} von {n40}'")
    if i > 0:
        check(t.lstrip().startswith("Studio Nordlicht GmbH") or "Kostenvoranschlag KVA-2026-031" in t.split("\n")[0] + t.split("\n")[1],
              f"page {i + 1}: the small head with title and number")
        if re.search(r"^\d+ Zusatzleistung|^\d+ [A-ZÄÖÜ]", t, re.M):
            check(squash("POS.LEISTUNGMENGEPREISMWST.GESAMT") in squash(t), f"page {i + 1}: the table head is repeated")
    # a category heading (upper case line of a category) is never the last line before the footer
    body_lines = [x for x in t.split("\n") if x.strip()]
    foot_at = next((k for k, x in enumerate(body_lines) if x.startswith("Studio Nordlicht GmbH") and k > 2), len(body_lines))
    last = body_lines[foot_at - 1] if foot_at > 0 else ""
    check(not re.fullmatch(r"(VIDEO|STOCK|AUDIO|OFFICE|KATEGORIE \d+)", last.strip()), f"page {i + 1}: no category heading alone at the page end ({last!r})")
sum_page = next((i for i, t in enumerate(T40) if "Summe Netto" in t), None)
check(sum_page is not None, "the totals are printed")
if sum_page is not None:
    check(re.search(r"^\d+ (Zusatzleistung|Untertitel)", T40[sum_page], re.M) or "Producing" in T40[sum_page],
          f"page {sum_page + 1}: the totals come with at least one position (never alone)")
    check("Zeitliche Auswertung" in T40[sum_page] or sum_page + 1 < n40, "the rights follow the totals")
rights_page = next((t for t in T40 if "Zeitliche Auswertung" in t), "")
check("Räumliche Auswertung" in rights_page and "Mediale Auswertung" in rights_page, "the rights block is not torn across pages")
check("Übertrag" not in "\n".join(T40), "no carry-over lines")
check(all(f"Zusatzleistung Nr. {i}" in "\n".join(T40) for i in range(13, 41)), "every one of the 40 positions is printed")

# ---------------------------------------------------------------- 3. logos: PNG with transparency, JPEG; the small head on following pages
from PIL import Image, ImageDraw  # noqa: E402  (tests/requirements.txt)

def png_logo(mode="RGBA"):
    im = Image.new(mode, (900, 300), (255, 255, 255, 0) if mode == "RGBA" else (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 880, 280], fill=(47, 93, 138, 255) if mode == "RGBA" else (47, 93, 138))
    d.ellipse([60, 60, 240, 240], fill=(255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()

jpg = io.BytesIO()
Image.new("RGB", (640, 200), (180, 40, 40)).save(jpg, "JPEG")
tmp = os.path.join(N, ".office_pdf_logo.png")
with open(tmp, "wb") as fh:
    fh.write(png_logo())
try:
    dl = office_pdf(fixture(40, logo_path=tmp))
    rl, Tl = texts(dl)
    check(all(has_image(p) for p in rl.pages), "with a logo file: an image on page 1 and on every following page")
    check(Tl[0].split("\n")[0].strip() != "Studio Nordlicht GmbH", "with a logo: no text company name in the letterhead")
    check("KVA-2026-031" in Tl[1], "with a logo: the number still stands in the small head")
    dj = office_pdf(fixture(), logo_bytes=jpg.getvalue())
    rj, _ = texts(dj)
    check(has_image(rj.pages[0]) and len(dj) < 200_000, f"logo bytes (JPEG) are embedded as a FlateDecode RGB image ({len(dj)} bytes)")
    dbad = office_pdf(fixture(), logo_bytes=b"not an image at all")
    rb, Tb = texts(dbad)
    check(not has_image(rb.pages[0]) and "KVA-2026-031" in Tb[0], "an unreadable logo is left out, the PDF still comes")
    dmissing = office_pdf(fixture(logo_path=os.path.join(N, "no-such-logo.png")))
    check(texts(dmissing)[1][0].startswith("Studio Nordlicht GmbH"), "a missing logo file: the company name instead")
finally:
    os.remove(tmp)

# ---------------------------------------------------------------- 4. English in USD, raw data included, no raw line
den = office_pdf(fixture(lang="en", currency="USD"))
ren, Ten = texts(den)
all_en = "\n".join(Ten)
for want in ("QUOTATION", "Quotation No.", "Valid until", "Net Total", "including raw data", "TRANSFER OF RIGHTS", "Duration of License",
             "in perpetuity", "worldwide except music on trade shows / live events (DE)", "Exchange rate €1: $1.09", "With best regards",
             "ORDER CONFIRMATION", "Place, date", "All prices plus 7 % or 19 % VAT."):
    check(squash(want) in squash(all_en), f"EN: text layer has {want!r}")
check(squash("Page 1 of " + str(len(ren.pages))) in squash(Ten[0]), "EN: 'Page 1 of n'")
check(squash("NO.TITLEXUNITPRICEVATTOTAL") in squash(Ten[0]), "EN: the pack's column labels")
dinc = office_pdf(fixture(raw="included"))
_, Tinc = texts(dinc)
check("Bereitstellung der Rohdaten" in "\n".join(Tinc) and "ohne Rohdaten" in "\n".join(Tinc) and "Optional" not in "\n".join(Tinc),
      "raw data included: a position + 'ohne Rohdaten' total, no option box")
dnone = office_pdf(fixture(raw="none"))
check("Rohdaten" not in "\n".join(texts(dnone)[1]).replace("Positionen mit Rohdaten", ""), "raw mode none: no raw data line at all")

# ---------------------------------------------------------------- 5. the writer's own helpers
check(abs(pdf.pdf_text_width("Hello", 10) - 22.78) < 0.05, f"Helvetica widths (Hello = 722+556+222+222+556 = 22.78 pt at 10 pt): {pdf.pdf_text_width('Hello', 10):.2f}")
check(abs(pdf.pdf_text_width("Hello", 10, bold=True) - 24.45) < 0.05, "Helvetica-Bold widths")
check(pdf.pdf_text_width("ÄÖÜäöüß€", 10) > 0 and pdf.pdf_encode("ÄÖÜäöüß€") == "ÄÖÜäöüß€".encode("cp1252"), "umlauts, sharp s and euro in WinAnsi")
check(pdf.pdf_encode("a → b ≥ c") == b"a -> b >= c", "arrows and comparison signs get an ASCII fallback")
w = pdf.pdf_wrap("Donaudampfschifffahrtsgesellschaftskapitänsmützenhersteller und mehr", 9.6, 80)
check(len(w) >= 3 and all(pdf.pdf_text_width(x, 9.6) <= 80 for x in w), f"a long word is cut to the column: {w}")
check(pdf.pdf_wrap("Zeile eins\nZeile zwei", 9.6, 300) == ["Zeile eins", "Zeile zwei"], "explicit line breaks are kept")
check(pdf.pdf_money(1234.5, "de", "EUR") == "1.234,50 €" and pdf.pdf_money(1234.5, "en", "USD") == "1,234.50 USD" and pdf.pdf_money(-12, "de", "EUR") == "-12,00 €",
      "money formats by language")
check(pdf.pdf_num(4.5, "de") == "4,5" and pdf.pdf_num(3, "en") == "3" and pdf.pdf_num(0.25, "en") == "0.25", "quantity formats")
check(pdf.pdf_date("2026-10-09", "de") == "09.10.2026" and pdf.pdf_date("2026-10-09", "en") == "9 October 2026" and pdf.pdf_date("", "de") == "", "date formats")
dempty = office_pdf({})
check(dempty.startswith(b"%PDF-1.4") and len(texts(dempty)[0].pages) == 1, "an empty model still gives a one-page PDF")

print(f"office_pdf: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
