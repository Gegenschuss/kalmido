#!/usr/bin/env python3
"""2.296.0 D (#3167, #3171, #3172, #3174): small office-PDF fixes, no server, no container. Invented companies and figures only.
 - #3167 a delivery note's standard closing is a receipt line (no "please transfer"), the intro no charge sentence; the
   office setting delivery_closing_de / _en wins; the text exists in every language
 - #3171 PDF text encoding (Info dictionary, NFC, invisible characters, transliteration)
 - #3172 16-bit logos, light company colour as text colour
 - #3174 reminders (texts without "Werktag", fee from level 2, label per level, table head repeated)
usage: p2296_d_fixes_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."))
sys.path.insert(0, SRC)
from kt import FAILS, OKS, check  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)

# ---------------------------------------------------------------- #3167 delivery note texts
import json  # noqa: E402

PK = os.path.join(SRC, "kalmido", "office", "packs")
for f in ("de.json", "xx.json"):
    tx = json.load(open(os.path.join(PK, f), encoding="utf-8"))["texts"]
    check(all(isinstance(tx.get(k), dict) and tx[k].get("de") and tx[k].get("en") for k in ("delivery_intro", "delivery_closing")),
          f"#3167: {f} has delivery_intro / delivery_closing in de and en")
    check("überweisen" not in tx["delivery_closing"]["de"] and "transfer" not in tx["delivery_closing"]["en"], f"#3167: {f} delivery closing asks for no payment")
for lg in ("de", "nl", "fr", "es", "it"):
    d = json.load(open(os.path.join(SRC, "static", "i18n", lg + ".json"), encoding="utf-8"))
    check(all(k in d for k in ("Goods or services received in full and in good condition.|pack", "The following goods or services have been delivered:|pack",
                               "Delivery note closing (German)", "Delivery note closing (English)")), f"#3167: i18n {lg} has the delivery texts")
import types  # noqa: E402

import ast  # noqa: E402


def lift(path, names, ns):
    """The named top-level functions of a source file, compiled on their own (the package needs the whole app's libraries)."""
    src = open(os.path.join(SRC, path), encoding="utf-8").read()
    mod = ast.parse(src)
    keep = [n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in keep} == set(names), (path, names)
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    return ns


LANGS = {lg: json.load(open(os.path.join(SRC, "static", "i18n", lg + ".json"), encoding="utf-8")) for lg in ("de", "nl", "fr", "es", "it")}
PACK = json.load(open(os.path.join(PK, "de.json"), encoding="utf-8"))
NS = {"LANGS": LANGS, "office_pack_for": lambda s: PACK, "tr": lambda s, *a, lg="de", **k: (LANGS.get(lg, {}).get(s) or s).format(*a), "json": json}
lift("kalmido/office/doclang.py", ["doc_lg", "_dpk", "doc_pack"], NS)
lift("kalmido/office/invoices.py", ["inv_default_texts", "inv_reminder_default_fee", "inv_reminder_no_label"], NS)
inv = types.SimpleNamespace(**NS)

for lg in ("de", "en", "nl"):
    intro, closing = inv.inv_default_texts(None, 1, {}, "delivery", lg)
    check(closing and "überweis" not in closing.lower() and "transfer" not in closing.lower() and "overmaken" not in closing.lower()
          and "bank" not in closing.lower(), f"#3167: delivery closing ({lg}) is a receipt line: {closing!r}")
    check(intro and "Rechnung" not in intro and "charges" not in intro, f"#3167: delivery intro ({lg}) is no charge sentence: {intro!r}")
_, cl = inv.inv_default_texts(None, 1, {"delivery_closing_de": "Eigener Text"}, "delivery", "de")
check(cl == "Eigener Text", "#3167: the office's delivery_closing_de wins")
_, cl = inv.inv_default_texts(None, 1, {"invoice_closing_de": "Nur Rechnung"}, "delivery", "de")
check(cl != "Nur Rechnung", "#3167: the invoice closing setting no longer reaches a delivery note")
_, cl = inv.inv_default_texts(None, 1, {"invoice_closing_de": "Nur Rechnung"}, "invoice", "de")
check(cl == "Nur Rechnung", "#3167: an invoice still takes its own setting")

# ---------------------------------------------------------------- #3171 characters
def one_page(m):
    return pdf.office_pdf(m)


def base_model(**kw):
    m = {"kind": "offer", "lang": "de", "currency": "EUR", "number": "A-1", "date": "2026-10-25", "date_text": "25.10.2026", "title": "Angebot",
         "company": {"name": "Studio Nordlicht GmbH", "lines": ["Studio Nordlicht GmbH", "Musterweg 1", "12345 Musterstadt"], "contact_lines": ["kontakt@example.com"],
                     "color": "#1f4e79"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2"]}, "intro": "Guten Tag", "lines": [],
         "totals": {"rows": [["Summe", "0,00 €"]], "show_tax_lines": False}, "closing": "Danke", "signature": "Gruß", "signature_name": "E. Beispiel"}
    m.update(kw)
    return m


T = "Angebot – „Relaunch“ €"
data = one_page(base_model(title=T, number=""))
r = PdfReader(io.BytesIO(data))
check(r.metadata.title == T, f"#3171: Info title is read correctly ({r.metadata.title!r})")
check(b"/Title <FEFF" in data, "#3171: Info title is a UTF-16BE text string")
check(T.encode("utf-8") in data, "#3171: XMP (uncompressed, UTF-8) holds the same title")

check(pdf.pdf_encode("u\u0308ber") == "über".encode("cp1252"), "#3171: NFD u + diaeresis becomes the one WinAnsi letter")
enc = pdf.pdf_encode("Łódź Ślą ı ş ő ř ẞ").decode("cp1252")
check("?" not in enc and enc.startswith("Lód"), f"#3171: Latin letters outside WinAnsi are transliterated ({enc!r})")
check(pdf.pdf_encode("so\u00adft") == b"soft" and pdf.pdf_encode("a\u200bb\ufeffc\u200dd") == b"abcd", "#3171: soft hyphen / ZWSP / BOM / ZWJ are invisible")
check(pdf.pdf_encode("a\x01b\x07") == b"ab", "#3171: control characters drop out (no .notdef box)")
check(pdf.pdf_encode("ø Œ •") == "ø Œ •".encode("cp1252"), "#3171: WinAnsi letters stay as they are")
check(pdf.pdf_text_width("so\u00adft", 10) == pdf.pdf_text_width("soft", 10), "#3171: width sees the same text as the drawing")
data = one_page(base_model(intro="Łódź Ślą u\u0308ber so\u00adft"))
txt = PdfReader(io.BytesIO(data)).pages[0].extract_text()
check("?" not in txt and "über" in txt, f"#3171: PDF text without '?' ({txt[:80]!r})")

# ---------------------------------------------------------------- #3172 16-bit logo, light company colour
import re  # noqa: E402
import zlib  # noqa: E402

from PIL import Image  # noqa: E402


def contrast(rgb):
    lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 1.05 / (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] + 0.05)


def hexrgb(h):
    return [int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]


def to_png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


g16 = Image.new("I;16", (8, 8), 40000)  # a mid grey stored with 16 bit
got = pdf.pdf_image_object(to_png(g16))
px = zlib.decompress(got[2])[:3] if got else b""
check(got is not None and 120 <= px[0] <= 190 and px[0] == px[1] == px[2], f"#3172: a 16-bit grey logo keeps its mid value ({list(px)}), not white")
dark16 = Image.new("I;16", (8, 8), 2560)
px = zlib.decompress(pdf.pdf_image_object(to_png(dark16))[2])[:3]
check(px[0] < 40, f"#3172: a dark 16-bit grey stays dark ({px[0]})")
i32 = Image.new("I", (4, 4), 30000)
check(100 <= pdf.pdf_to_8bit(i32).getpixel((0, 0)) <= 130, "#3172: mode I scaled, not clipped")
g8 = Image.new("L", (4, 4), 90)
check(zlib.decompress(pdf.pdf_image_object(to_png(g8))[2])[0] == 90, "#3172: an 8-bit logo is unchanged")

lite = pdf.pdf_text_color("#e8d44d")
check(lite != "#e8d44d" and contrast(hexrgb(lite)) >= 4.5, f"#3172: #e8d44d as text becomes {lite} (contrast {contrast(hexrgb(lite)):.2f})")
# same hue: the ratios of the channels stay
a, b = hexrgb("#e8d44d"), hexrgb(lite)
check(abs(a[0] / a[1] - b[0] / b[1]) < 0.05 and abs(a[0] / a[2] - b[0] / b[2]) < 0.3, "#3172: the darker text colour keeps the hue")
check(pdf.pdf_text_color("#1f4e79") == "#1f4e79" and pdf.pdf_text_color("#2f5d8a") == "#2f5d8a", "#3172: a dark company colour stays as it is")
check(pdf.pdf_text_color("") == "#2f5d8a" and pdf.pdf_text_color("zzz") == "#2f5d8a", "#3172: no / invalid colour -> the default")


def heading_color(col):
    m = base_model(lines=[{"kind": "heading", "title": "Kategorie Eins"},
                          {"kind": "item", "pos": 1, "title": "Leistung", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
                           "rate_text": "100,00 €", "tax_pct": 19, "total": 100, "total_text": "100,00 €"}])
    m["company"] = dict(m["company"], color=col)
    pg = PdfReader(io.BytesIO(pdf.office_pdf(m))).pages[0]
    ops = pg.get_contents().get_data().decode("latin-1")
    hit = re.search(r"BT ([\d.]+) ([\d.]+) ([\d.]+) rg /F2 8\.00 Tf 0\.80 Tc", ops)  # the category heading: 8 pt bold, spaced
    return [float(x) for x in hit.groups()] if hit else None


c = heading_color("#e8d44d")
check(c is not None and contrast(c) >= 4.4, f"#3172: the category heading of a light company colour is readable ({c})")
c = heading_color("#1f4e79")
check(c is not None and all(abs(x - y) < 0.002 for x, y in zip(c, hexrgb("#1f4e79"))), "#3172: a dark colour prints unchanged")

# ---------------------------------------------------------------- #3174 reminders
BAD = ("werktag", "working day", "werkdag", "jours ouvrables", "días hábiles", "giorni lavorativi")
for lg in ("de", "en", "nl", "fr", "es", "it"):
    for lv in (1, 2, 3):
        _, cl = inv.inv_default_texts(None, 1, {}, "reminder", lg, lv)
        check(cl and "{days}" in cl and not any(w in cl.lower() for w in BAD), f"#3174: reminder closing {lg} level {lv} counts plain days, no working days")
_, cl = inv.inv_default_texts(None, 1, {}, "reminder", "de", 1)
check("kompletten" not in cl, f"#3174: the level 1 text does not say 'kompletten Rechnungsbetrag' ({cl!r})")
check(inv.inv_reminder_default_fee({"reminder_fee": 5}, 1) == 0, "#3174: level 1 gets no fee by default")
check(inv.inv_reminder_default_fee({"reminder_fee": 5}, 2) == 5 and inv.inv_reminder_default_fee({"reminder_fee": 5}, 3) == 5,
      "#3174: the office's fee is the default from level 2 (the setting is respected)")
check(inv.inv_reminder_default_fee({}, 2) == 0, "#3174: no setting, no fee")
L = {"reminder_no": "Mahnung Nr."}
check(inv.inv_reminder_no_label(L, "de", "Zahlungserinnerung", 1) == "Zahlungserinnerung Nr.", "#3174: level 1 label is the payment reminder's")
check(inv.inv_reminder_no_label(L, "de", "Mahnung", 2) == "Mahnung Nr.", "#3174: level 2 label")
check(inv.inv_reminder_no_label(L, "de", "Letzte Mahnung", 3) == "Letzte Mahnung Nr.", "#3174: level 3 label")


def rem_model(n):
    rows = [{"id": i, "number": f"RE-2026-{i:03}", "date_text": "01.09.2026", "due_text": "15.09.2026", "open": 100, "open_text": "100,00 €"} for i in range(1, n + 1)]
    m = base_model(kind="reminder", title="Zahlungserinnerung", lines=[], closing="Bitte zahlen Sie innerhalb von 10 Tagen.",
                   totals={"rows": [["Offener Betrag", f"{100 * n},00 €"], ["Gesamtbetrag fällig", f"{100 * n},00 €"]], "show_tax_lines": False})
    m["reminder"] = {"level": 1, "title": "Zahlungserinnerung", "columns": ["Beleg", "Datum", "Fällig", "Betrag"], "rows": rows, "total_open_text": f"{100 * n},00 €"}
    return m


rd = PdfReader(io.BytesIO(pdf.office_pdf(rem_model(40))))
heads = [pg.extract_text().count("BELEG") for pg in rd.pages]
check(len(rd.pages) >= 2 and all(h == 1 for h in heads), f"#3174: the open invoices' head on every page (pages {len(rd.pages)}, heads {heads})")
rd = PdfReader(io.BytesIO(pdf.office_pdf(rem_model(3))))
check(len(rd.pages) == 1 and rd.pages[0].extract_text().count("BELEG") == 1 and "RE-2026-003" in rd.pages[0].extract_text(), "#3174: a short reminder still has its head and rows once")

print(f"p2296_d_fixes: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
