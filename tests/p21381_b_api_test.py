#!/usr/bin/env python3
"""2.138.2 API tests, part B (office PDF layout), no server (kalmido/office/pdf.py of the source tree). Invented data only.
 - #2388: quotation rights appendix: rows 10 pt (label = value), note 8.5 pt, project line top right not larger than the body text;
   the order confirmation after the appendix is a section of its own (>= 28 pt air, bold 10 pt heading) and is not cut off
 - #2397: footer with a two-line company name: both name lines bold, the address below normal; one-line name unchanged
 - freelancer-matrix: office (no route is added; the PDF writer is the same for a person without an organisation)
usage: p21381_b_api_test.py [datadir]      (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf_p21381b", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)

from pypdf import PdfReader  # noqa: E402 (tests/requirements.txt)

# ---------------------------------------------------------------- recorder: every text / line call per page
PAGES = []
_Base = pdf._Page


class RecPage(_Base):
    def __init__(self):
        super().__init__()
        self.rec, self.rules = [], []
        PAGES.append(self)

    def text(self, x, y, s, size, bold=False, color=pdf.C_INK, align="l", spacing=0.0, width=None):
        s = str(s or "")
        if s:
            w = pdf.pdf_text_width(s, size, bold, spacing)
            x0 = (x + (width or 0) - w if width else x - w) if align == "r" else (x + ((width or 0) - w) / 2 if align == "c" else x)
            self.rec.append({"x": x0, "y": y, "w": w, "size": size, "s": s, "bold": bold})
        return super().text(x, y, s, size, bold, color, align, spacing, width)

    def line(self, x1, y1, x2, y2, w=0.5, color=pdf.C_RULE, dash=None):
        self.rules.append((x1, y1, x2, y2, w))
        return super().line(x1, y1, x2, y2, w, color, dash)


pdf._Page = RecPage


def render(model):
    PAGES.clear()
    data = pdf.office_pdf(model)
    r = PdfReader(io.BytesIO(data))
    return data, r, list(PAGES)


def overlap(a, b):
    """Two recorded text boxes overlap (x span and the line box from y to y + size)."""
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["size"] and b["y"] < a["y"] + a["size"]


def money(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s + " €"


def item(pos, title, rate=100, detail=""):
    return {"kind": "item", "pos": pos, "title": title, "detail": detail, "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": rate,
            "rate_text": money(rate), "tax_pct": 19, "total": rate, "total_text": money(rate)}


def model(name="Beispielstudio GmbH", rights=True, accept=True):
    m = {"kind": "offer", "lang": "de", "currency": "EUR", "number": "KVA-2026-077", "date": "2026-10-19", "date_text": "19.10.2026",
         "title": "Kostenvoranschlag", "project_title": "Serie Beispielprojekt", "accept_on": 1 if accept else 0,
         "company": {"name": name, "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["kontakt@example.com"], "color": "#6b4fbb"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "intro": "Sehr geehrte Damen und Herren,\nwir bieten Ihnen an:",
         "lines": [{"kind": "item", "pos": 1, "title": "Leistung", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
                    "rate_text": "100,00 EUR", "tax_pct": 19, "total": 100, "total_text": "100,00 EUR"}],
         "totals": {"rows": [["Summe Netto", "100,00 EUR"], ["Gesamt", "119,00 EUR"]], "show_tax_lines": True, "vat_note": "Alle Preise zuzueglich MwSt."},
         "labels": {"offer_no": "Angebot Nr.", "net_total": "Summe Netto", "page_of": "Seite {x} von {y}", "order": "Auftragserteilung"},
         "closing": "Wir freuen uns auf die Zusammenarbeit.", "signature": "Mit freundlichen Grüßen", "signature_name": "Erika Beispiel"}
    if rights:
        m["rights"] = {"title": "Rechteübertragung", "rows": [["Zeitliche Auswertung", "unbegrenzt"], ["Räumliche Auswertung", "weltweit"],
                                                              ["Mediale Auswertung", "intern, web, unpaid media"]],
                       "exceptions": "", "exclusive": 0, "note": "Im Übrigen gelten unsere AGB."}
    return m


# ---------------------------------------------------------------- 1. #2388 rights appendix
data, r, pages = render(model())
check(data.startswith(b"%PDF"), "the PDF renders")
rp = next((p for p in pages if any(t["s"] == "Zeitliche Auswertung" for t in p.rec)), None)
check(rp is not None, "the rights appendix page exists")
if rp is not None:
    rows = [t for t in rp.rec if t["s"] in ("Zeitliche Auswertung", "Räumliche Auswertung", "Mediale Auswertung", "unbegrenzt", "weltweit")]
    check(rows and all(t["size"] == 10 for t in rows), "rights rows: label and value both 10 pt " + str([t["size"] for t in rows]))
    note = next((t for t in rp.rec if t["s"].startswith("Im Übrigen")), None)
    check(note is not None and note["size"] == 8.5, "rights note 8.5 pt")
    sub = next((t for t in rp.rec if "Serie Beispielprojekt" in t["s"]), None)
    check(sub is not None and sub["size"] <= 9, "project line top right not larger than the body text")
    head = next((t for t in rp.rec if t["s"] == "RECHTEÜBERTRAGUNG"), None)
    check(head is not None and head["size"] == 14 and head["bold"], "appendix heading 14 pt bold")
    acc = next((t for t in rp.rec if t["s"] == "AUFTRAGSERTEILUNG"), None)
    check(acc is not None, "the order confirmation heading stands on the appendix page (not cut off)")
    if acc is not None and note is not None:
        gap = acc["y"] - (note["y"] + note["size"])
        check(gap >= 28, f"air between rights block and order confirmation >= 28 pt ({gap:.1f})")
        check(acc["bold"] and acc["size"] == 10, "order confirmation heading bold 10 pt")
        caps = [t for t in rp.rec if t["s"] in ("Ort, Datum", "Unterschrift, Stempel Auftraggeber")]
        check(len(caps) == 2 and all(t["size"] >= 8.5 for t in caps), "captions under the lines are one step larger")
        check(any(ru[1] > acc["y"] for ru in rp.rules), "the signature lines are on the same page")

# without an appendix the order confirmation keeps its old small heading
data, r, pages = render(model(rights=False))
oc = [t for p in pages for t in p.rec if t["size"] == 7.4 and t["bold"]]
check(len(oc) >= 1, "no rights appendix: the order confirmation heading stays 7.4 pt")

# ---------------------------------------------------------------- 2. #2397 footer, two-line company name
data, r, pages = render(model(name="FIRMA\nName & Name GbR", rights=False))
p1 = pages[0]
f1 = [t for t in p1.rec if t["s"] == "FIRMA" and t["size"] < 8]
f2 = [t for t in p1.rec if t["s"] == "Name & Name GbR" and t["size"] < 8]
ad = [t for t in p1.rec if t["s"].startswith("Musterweg 1") and t["size"] < 8]
check(f1 and f1[-1]["bold"], "footer: name line 1 bold")
check(f2 and f2[-1]["bold"], "footer: name line 2 bold as well")
check(ad and not ad[-1]["bold"], "footer: the address below is normal")
cols = pdf.pdf_footer_cols({"name": "FIRMA\nName & Name GbR", "lines": ["Musterweg 1"]})
check(getattr(cols, "n_name", 0) == 2, "pdf_footer_cols reports two name lines")
data, r, pages = render(model(name="Beispielstudio GmbH", rights=False))
f = [t for t in pages[0].rec if t["s"] == "Beispielstudio GmbH" and t["size"] < 8]
ad = [t for t in pages[0].rec if t["s"].startswith("Musterweg 1") and t["size"] < 8]
check(f and f[-1]["bold"] and ad and not ad[-1]["bold"], "footer: one-line name bold, address normal")

print(f"p21381_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
