#!/usr/bin/env python3
# kalmido-suite: after=p2294_pdf nodata
"""2.380 E (#3417): the number's label on the rights appendix of the office PDF follows the document (Rechnung Nr. / Gutschrift Nr. /
Mahnung Nr. / Angebot Nr.), not a match on the number's value (a draft number carries a suffix in the head).
No server, no container; invented figures only."""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
from kt import FAILS, OKS, check  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)


def model(label, shown):
    return {"kind": "invoice", "lang": "de", "currency": "EUR", "number": "TEST-003", "date": "2026-10-24", "date_text": "24.10.2026",
            "title": "Rechnung", "project_title": "Beispielprojekt",
            "company": {"name": "Beispielstudio GmbH", "lines": ["Beispielstudio GmbH", "Musterweg 1", "12345 Musterstadt"],
                        "contact_lines": ["kontakt@example.com"], "color": "#6b4fbb"},
            "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
            "meta": [[label, shown], ["Datum", "24.10.2026"]],
            "intro": "Sehr geehrte Damen und Herren,", "closing": "Vielen Dank.", "signature": "Mit freundlichen Grüßen",
            "lines": [{"kind": "item", "pos": 1, "title": "Leistung", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
                       "rate_text": "100,00 €", "tax_pct": 19, "total": 100, "total_text": "100,00 €"}],
            "totals": {"rows": [["Summe Netto", "100,00 €"], ["Gesamt", "119,00 €"]], "show_tax_lines": True, "vat_note": ""},
            "rights": {"title": "Rechteübertragung", "rows": [["Zeitliche Auswertung", "unbegrenzt"]], "exceptions": "", "exclusive": 0, "note": ""},
            "labels": {"offer_no": "Angebot Nr.", "rights": "Rechteübertragung"}}


def rights_text(m):
    r = PdfReader(io.BytesIO(pdf.office_pdf(m)))
    return next((p.extract_text() for p in r.pages if "Zeitliche Auswertung" in (p.extract_text() or "")), "")


for label in ("Rechnung Nr.", "Gutschrift Nr.", "Mahnung Nr.", "Angebot Nr."):
    for shown, what in (("TEST-003 · MUSTER", "draft"), ("TEST-003", "finalised")):
        t = rights_text(model(label, shown))
        check(f"{label} TEST-003" in t, f"#3417: rights page of a {what} document says '{label}' ({label} TEST-003 in {t[:80]!r})")
        if label != "Angebot Nr.":
            check("Angebot Nr. TEST-003" not in t, f"#3417: no quotation label on the {label} {what} rights page")

print(f"p2380r_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
