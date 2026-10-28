#!/usr/bin/env python3
# kalmido-suite: after=p2357_a_paper_pdf nodata
"""2.390.0 A (#3349, #3350): office wording and PDF info block on the source tree, no server, no container. Invented data only.
 - #3349 the sentence after the salutation starts with a capital in en / it / nl (pack intros, attachment mails, letter mail,
   privacy-sheet mail); the old lower-case standard texts stay recognised as standard on a language switch (doclang._defaults)
 - #3350 the info block of the head (date, number, ...) begins 125 mm from the sheet edge on A4 and US-Letter and ends at the
   right margin; a long value still wraps under its label; nothing runs into the margin
usage: p2390_0_a_office_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import json
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

import datetime  # noqa: E402

WHEN = {"when": datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)}
CO = {"name": "Beispielstudio LLC", "lines": ["Beispielstudio LLC", "100 Example Street", "Springfield, IL 62701"],
      "contact_lines": ["hello@example.com"], "register_lines": [], "bank_lines": ["Example Bank"], "color": "#2f5d8a"}


def model(**kw):
    lines = [{"kind": "item", "pos": 1, "title": "Service", "detail": "", "qty": 1, "qty_text": "1", "unit_text": "day", "rate": 100,
              "rate_text": "100.00", "tax_pct": 0, "total": 100, "total_text": "100.00"}]
    m = {"kind": "invoice", "lang": "en", "currency": "USD", "number": "INV-2026-357", "date": "2026-10-26", "date_text": "10/26/2026",
         "title": "Invoice", "company": dict(CO),
         "recipient": {"name": "Example Customer Inc.", "lines": ["Example Customer Inc.", "200 Sample Avenue", "Portland, OR 97201"]},
         "intro": "Dear Sir or Madam,\nThank you for your order.", "lines": lines,
         "totals": {"net": 100.0, "net_text": "100.00", "tax_lines": [], "gross": 100.0, "rows": [["Net total", "100.00"]],
                    "vat_note": "", "show_tax_lines": False},
         "closing": "Payable within 14 days.", "signature": "Kind regards", "signature_name": "Jane Example"}
    m.update(kw)
    return m

MM = 72 / 25.4


def src(*p):
    with open(os.path.join(SRC, *p), encoding="utf-8") as fh:
        return fh.read()


def i18n(lg):
    return json.loads(src("static", "i18n", lg + ".json"))


# ---------------------------------------------------------------- #3349 wording
START = ("Regarding", "Thank you for your enquiry", "The following goods", "It may have", "Despite our")
for lg in ("de", "fr", "es", "it", "nl"):
    t = i18n(lg)
    keys = [k for k in t if k.endswith("|pack") and k.startswith(START)]
    check(len(keys) >= 8, f"#3349 {lg}: the capitalised pack intro keys exist {len(keys)}")
    check(not [k for k in t if k.endswith("|pack") and k.startswith(tuple(s.lower() for s in START[:1] + START[2:]) + ("thank you for your enquiry",))],
          f"#3349 {lg}: no lower-case intro key left")
    if lg in ("it", "nl", "fr", "es"):
        bad = [k[:30] for k in keys if not t[k][:1].isupper()]
        check(not bad, f"#3349 {lg}: every intro starts with a capital {bad}")
        mail = [v for k, v in t.items() if k.startswith("Dear Sir or Madam,\n\nPlease find attached")]
        check(len(mail) == 1 and re.search(r"\n\n[A-ZÀ-Ý]", mail[0]), f"#3349 {lg}: the attachment mail has a capital after the salutation {mail}")
        lm = [v for k, v in t.items() if k.startswith("Hello,\n\nPlease find attached our letter")]
        check(len(lm) == 1 and re.search(r"\n\n[A-ZÀ-Ý]", lm[0]), f"#3349 {lg}: the letter mail the same {lm}")
        check(t.get("Please find attached our document “{0}”.", "")[:1].isupper(), f"#3349 {lg}: the privacy-sheet mail the same")
for code in ("de", "xx"):
    en = json.loads(src("kalmido", "office", "packs", code + ".json"))["texts"]
    intros = [k for k, v in en.items() if (k == "intro" or "_intro" in k) and isinstance(v, dict) and "en" in v]
    check(len(intros) >= 7, f"#3349 pack {code}: the intro texts found {intros}")
    for k in intros:
        if True:
            check(en[k]["en"][:1].isupper(), f"#3349 pack {code}: English {k} starts with a capital {en[k]['en'][:30]!r}")
check('"Dear Sir or Madam,\\n\\nPlease find attached {0} {1}.' in src("kalmido", "office", "invoices.py"), "#3349 INV_MAIL_TEXT: capital after the salutation")
check('tr("Please find attached our document' in src("kalmido", "office", "privacy.py"), "#3349 privacy mail: capital")
check("Hello,\\n\\nPlease find attached our letter" in src("kalmido", "office", "lettermail.py"), "#3349 letter mail: capital")
dl = src("kalmido", "office", "doclang.py")
check('if doc_lg(lang) != "de":' in dl and "x[:1].lower() + x[1:]" in dl, "#3349 old lower-case standard intros still count as standard in every language but German")
check('doc_lg(lang) in ("fr", "es")' not in dl, "#3349 the fr / es-only switch is gone")

# ---------------------------------------------------------------- #3350 info block at 125 mm
check(abs(pdf.PDF_INFO_X - 125 * MM) < 0.01, f"#3350 PDF_INFO_X = 125 mm {pdf.PDF_INFO_X / MM}")
for fn in ("doctpl.py", "letters.py"):
    check("PDF_INFO_X" in src("kalmido", "office", fn) and "PDF_ADDR_W + 8" not in src("kalmido", "office", fn), f"#3350 {fn} uses the shared constant")
LONG = "Bestellung 2026-10-4711 der Einkauf Nord, Kostenstelle 4711"
for paper, right in (("a4", 20 * MM), ("letter", 72.0)):
    m = model(paper=paper, meta=[["Invoice No.", "INV-2026-357"], ["Date", "10/26/2026"], ["Your reference", LONG]])
    data = pdf.office_pdf(m, meta=WHEN)
    page = pdfcheck.layout(data)[0]
    pw = page["w"]
    lab = [t for t in page["texts"] if t["s"].startswith("Invoice No.")]
    check(lab and abs(lab[0]["x"] - 125 * MM) < 1.0, f"#3350 {paper}: the info labels start at 125 mm {[round(t['x'] / MM, 1) for t in lab]}")
    val = [t for t in page["texts"] if t["s"] == "INV-2026-357" and t["y"] < 100 * MM]
    check(val and abs(val[0]["x"] + val[0]["w"] - (pw - right)) < 1.5, f"#3350 {paper}: the values end at the right margin {[round((t['x'] + t['w']) / MM, 1) for t in val]}")
    head = [t for t in page["texts"] if 125 * MM - 1 <= t["x"] and t["y"] < 100 * MM]
    check(head and all(t["x"] + t["w"] <= pw - right + 1.5 for t in head), f"#3350 {paper}: nothing over the right margin")
    lp = [t for t in page["texts"] if t["bold"] and t["s"] and t["s"].split(" ")[0] in LONG and t["y"] < 100 * MM
          and t["s"] not in ("INV-2026-357", "10/26/2026")]
    lab_p = [t for t in page["texts"] if t["s"] == "Your reference"]
    check(lab_p and len(lp) == 2 and min(t["y"] for t in lp) > lab_p[0]["y"], f"#3350 {paper}: a long value wraps under its label")
    check(not pdfcheck.problems(data, right=right), f"#3350 {paper}: layout clean {pdfcheck.problems(data, right=right)[:3]}")
sys.exit(done("p2390_0_a_office"))
