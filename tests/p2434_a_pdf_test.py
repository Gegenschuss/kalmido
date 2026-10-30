#!/usr/bin/env python3
# kalmido-suite: fresh nodata
"""2.434.0 A (#3603): the invoice PDF in look A like the quotation, the GiroCode 2 x 2 cm, the bank details at the end.
Invented companies, figures and the test IBAN only. The PDFs are made by kalmido/office/pdf.py in the app container of the
group (the GiroCode needs segno there) and measured here; the PDF writer takes no organisation (a person without an
organisation gets the same PDF: the route around it is unchanged and covered by p21443_b_api's freelancer part).
 - look A for invoice, credit note (correction) and reminder: the texts 2 pt smaller (body 9.6 -> 7.6 pt); a delivery note
   keeps 9.6 pt
 - the GiroCode is 2 x 2 cm (56.7 pt, was about 2.7 cm), its labels stay within the right margin
 - the payment text (due date) stays right below the totals; the bank line (bank, IBAN, BIC) and the GiroCode form one
   block at the end of the document right above the footer (not below the totals any more), the code never over the footer
 - a long invoice (40 positions): the bank block on the last page above the footer, the layout clean
P2434A_SHOTS=<dir> (shots: 'P2434A_SHOTS'): the PDFs and, with pdftoppm, PNGs of their last page.
usage: p2434_a_pdf_test.py      (KALMIDO_TEST_CONTAINER)"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

N = os.path.dirname(os.path.abspath(__file__))
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

MM = pdfcheck.MM
IBAN = "DE02120300000000202051"
CO = {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: kontakt@example.com"],
      "register_lines": ["Amtsgericht Musterstadt HRB 1"], "bank_lines": ["Beispielbank", "IBAN DE02 1203 0000 0000 2020 51"], "color": "#2f5d8a"}
PAYTEXT = "Bitte überweisen Sie den Betrag bis zum 12.11.2026."

RUN = """import base64, json, sys
from kalmido.office import pdf
from kalmido.office.girocode import gcq_payload
for m in json.load(sys.stdin):
    pay = m.get("payment")
    if pay:
        pay["girocode"] = gcq_payload(m["company"]["name"], pay["iban"], pay.get("bic"), "1190.00", m["number"])
    print(base64.b64encode(pdf.office_pdf(m)).decode())
"""


def money(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def model(kind="invoice", n=3, pay=True):
    lines = [{"kind": "item", "pos": i, "title": f"Leistung {i}", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 100,
              "rate_text": money(100), "tax_pct": 19, "total": 100, "total_text": money(100)} for i in range(1, n + 1)]
    title = {"invoice": "Rechnung", "credit": "Rechnungskorrektur", "reminder": "Zahlungserinnerung", "delivery": "Lieferschein"}[kind]
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "RE-2026-434", "date": "2026-10-29", "date_text": "29.10.2026",
         "title": title, "company": CO, "sender_fields": {"name": CO["name"], "country": "DE"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "meta": [[title + " Nr.", "RE-2026-434"], ["Datum", "29.10.2026"]], "lines": lines,
         "totals": {"rows": [["Summe netto", money(100 * n)], ["Gesamt", money(119 * n), True]], "show_tax_lines": False},
         "closing": "Vielen Dank für Ihren Auftrag.", "signature": "Mit freundlichen Grüßen", "signature_name": "Erika Beispiel",
         "labels": {"pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt", "vat": "MwSt."}}
    if kind == "reminder":
        m["lines"] = []
        m["reminder"] = {"columns": ["Rechnung", "Datum", "Fällig", "Offen"],
                         "rows": [{"number": "RE-2026-400", "date_text": "01.10.2026", "due_text": "15.10.2026", "open_text": money(1190)}]}
    if pay:
        m["payment"] = {"text": PAYTEXT, "iban": IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
    return m


def render(models):
    out = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", RUN], input=json.dumps(models), capture_output=True, text=True)
    check(out.returncode == 0, f"the PDFs are made in the app container {out.stderr[-800:]}")
    return [base64.b64decode(x) for x in out.stdout.split()]


RECT = re.compile(rb"[\d.]+ [\d.]+ [\d.]+ rg (-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+) re f")


def code_box(data):
    """[(page no, left, top, right, bottom)] of the GiroCode (y from the top): the filled rectangles of the most common height
    (one module row) on a page."""
    from pypdf import PdfReader
    out = []
    for k, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1):
        ph = float(page.mediabox.height)
        raw = page.get_contents().get_data() if page.get_contents() is not None else b""
        rs = [tuple(float(v) for v in r) for r in RECT.findall(raw)]
        rs = [r for r in rs if r[3] < 5]
        if len(rs) < 40:
            continue
        h = Counter(round(r[3], 2) for r in rs).most_common(1)[0][0]
        rs = [r for r in rs if abs(r[3] - h) < 0.01]
        out.append((k, min(r[0] for r in rs), ph - max(r[1] + r[3] for r in rs), max(r[0] + r[2] for r in rs), ph - min(r[1] for r in rs)))
    return out


def find(pages, s, start=False):
    return [(n, t) for n, p in enumerate(pages, 1) for t in p["texts"] if (t["s"].startswith(s) if start else s == t["s"])]


def shot(name, data):
    d = os.environ.get("P2434A_SHOTS") or ""
    if not d or not data:
        return
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, name + ".pdf")
    with open(f, "wb") as fh:
        fh.write(data)
    if shutil.which("pdftoppm"):
        n = len(pdfcheck.layout(data))
        subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", str(n), "-l", str(n), "-singlefile", f, os.path.join(d, name)], check=False)


KINDS = ("invoice", "credit", "reminder")
pdfs = render([model(k) for k in KINDS] + [model("delivery", pay=False), model("invoice", 40)])
check(len(pdfs) == 5, f"five PDFs ({len(pdfs)})")
pdfs += [b""] * (5 - len(pdfs))
by = dict(zip(KINDS, pdfs[:3]))
dl, long_inv = pdfs[3], pdfs[4]
for name, data in (("p2434-rechnung", by["invoice"]), ("p2434-mahnung", by["reminder"]), ("p2434-rechnung-lang", long_inv)):
    shot(name, data)

for kind, data in by.items():
    if not data:
        continue
    pg = pdfcheck.layout(data)
    p1 = pg[0]
    pay = find(pg, PAYTEXT)
    # look A: 2 pt smaller (the payment text is body text on every kind, the reminder has no positions)
    check(pay and abs(pay[0][1]["size"] - 7.6) < 0.01, f"#3603 {kind}: look A, body text 7.6 pt ({pay[0][1]['size'] if pay else None})")
    if kind != "reminder":
        it = find(pg, "Leistung 1")
        check(it and abs(it[0][1]["size"] - 7.6) < 0.01, f"#3603 {kind}: the positions in look A ({it[0][1]['size'] if it else None})")
    # the GiroCode 2 x 2 cm
    cb = code_box(data)
    check(len(cb) == 1, f"#3603 {kind}: one GiroCode ({len(cb)})")
    if cb:
        k, x0, y0, x1, y1 = cb[0]
        check(abs((x1 - x0) - 56.7) < 1.0 and abs((y1 - y0) - 56.7) < 1.0, f"#3603 {kind}: the code is 2 x 2 cm ({(x1 - x0) / MM:.1f} x {(y1 - y0) / MM:.1f} mm)")
        check(abs(x1 - (p1["w"] - 20 * MM)) < 1.0, f"#3603 {kind}: the code ends at the right margin ({x1:.1f})")
        lab = [t for t in pg[k - 1]["texts"] if t["s"] in ("GiroCode", "Mit Banking-App scannen")]
        check(len(lab) == 2 and all(t["x"] + t["w"] <= p1["w"] - 20 * MM + 0.6 and t["y"] > y1 for t in lab),
              f"#3603 {kind}: the code's labels below it, within the right margin {[(t['s'], round(t['x'] + t['w'], 1)) for t in lab]}")
        foot = pg[k - 1]["foot"]
        check(foot and y1 < foot and max(t["y"] + t["size"] for t in lab) <= foot + 0.6, f"#3603 {kind}: the code above the footer ({y1:.0f} / {foot})")
    # the bank line at the end right above the footer, the due text right below the totals
    bank = find(pg, "Beispielbank · IBAN", True)
    gross = find(pg, "Gesamt") if kind != "reminder" else []
    check(len(bank) == 1, f"#3603 {kind}: one bank line ({len(bank)})")
    if bank and pay:
        n, bt = bank[0]
        foot = pg[n - 1]["foot"]
        check(foot and foot - bt["y"] < 30 * MM, f"#3603 {kind}: the bank line sits right above the footer ({(foot - bt['y']) / MM if foot else 0:.0f} mm above it)")
        check(bt["y"] - pay[0][1]["y"] > 15 * MM or n > pay[0][0], f"#3603 {kind}: the bank line no longer right below the due text "
              f"({(bt['y'] - pay[0][1]['y']) / MM:.0f} mm)")
        cl = find(pg, "Vielen Dank für Ihren Auftrag.")
        check(cl and (cl[0][0], cl[0][1]["y"]) < (n, bt["y"]), f"#3603 {kind}: the bank block comes after the closing")
        if cb:
            check(cb[0][0] == n and abs(cb[0][2] - bt["y"]) < 2, f"#3603 {kind}: code and bank line one block ({cb[0][2]:.0f} / {bt['y']:.0f})")
    if gross and pay:
        g = [t for t in gross if t[1]["bold"]] or gross
        check(pay[0][0] == g[-1][0] and 0 < pay[0][1]["y"] - g[-1][1]["y"] < 25 * MM, f"#3603 {kind}: the due text stays right below the totals "
              f"({(pay[0][1]['y'] - g[-1][1]['y']) / MM:.0f} mm)")
    check(not pdfcheck.problems(data), f"#3603 {kind}: the layout is clean {pdfcheck.problems(data)[:3]}")

if dl:
    pg = pdfcheck.layout(dl)
    it = find(pg, "Leistung 1")
    check(it and it[0][1]["size"] == 9.6, f"#3603: a delivery note keeps its look (9.6 pt: {it[0][1]['size'] if it else None})")

if long_inv:
    pg = pdfcheck.layout(long_inv)
    bank = find(pg, "Beispielbank · IBAN", True)
    cb = code_box(long_inv)
    check(len(pg) >= 2 and bank and bank[0][0] == len(pg) and cb and cb[0][0] == len(pg),
          f"#3603: a long invoice ({len(pg)} pages) has the bank block on its last page {bank[:1]} {cb[:1]}")
    if bank and cb:
        foot = pg[-1]["foot"]
        check(foot and cb[0][4] < foot and foot - bank[0][1]["y"] < 30 * MM, f"#3603: the long invoice's bank block right above the footer")
    check(not pdfcheck.problems(long_inv), f"#3603: the long invoice is clean {pdfcheck.problems(long_inv)[:3]}")

print(f"p2434_a_pdf: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
