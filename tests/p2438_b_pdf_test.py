#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.438.0 B (#3622): quotations and invoices of two pages or more carry an overview of the part totals on page 1, behind every
part name a small "SEITE n" that jumps to the part. Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - the writer (kalmido/office/pdf.py of the source tree): a one-page document stays without overview, hint and links; documents
   without two parts, with positions before the first heading, whose rows do not add up to the net total, a delivery note:
   none; a page shift of an own letterhead moves the links with the page; printed parts: the part rows of the title page carry
   the tag; US-Letter
 - through the API (organisation and a person without organisation): a long quotation (with a discount as a row of its own), an
   invoice with its embedded e-invoice, a progress invoice with parts, a final invoice (the progress invoices stay out of the
   overview); the tags name the pages the parts really start on, the link targets are those pages, the rows add up
P2438B_SHOTS=<dir> (shots: 'P2438B_SHOTS'): the PDFs and PNGs of the first page.
usage: p2438_b_pdf_test.py <datadir>"""
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
IBAN = "DE02120300000000202051"
HINT2 = "Die Einzelpositionen je Teil stehen ab Seite 2."
CO = {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: kontakt@example.com"],
      "bank_lines": ["IBAN DE00 0000 0000 0000 0000 00"], "color": "#2f5d8a"}


def euro(v):
    return f"{Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def amount(s):
    return Decimal(s.replace(" €", "").replace(".", "").replace(",", "."))


def links(data):
    """Per page [(rect, flags, has an action, target page no, target y from the top)] of the link annotations."""
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    at = {p.indirect_reference.idnum: n for n, p in enumerate(rd.pages, 1)}
    out = []
    for p in rd.pages:
        row = []
        for a in p.get("/Annots") or []:
            a = a.get_object()
            d = a["/Dest"]
            row.append(([float(v) for v in a["/Rect"]], int(a["/F"]), "/A" in a, at[d[0].idnum], float(p.mediabox.height) - float(d[3])))
        out.append(row)
    return out


def tags(pages):
    """[(page no, text box)] of the small page tags."""
    return [(n, t) for n, p in enumerate(pages, 1) for t in p["texts"] if t["s"].startswith("SEITE ") and t["s"][6:].isdigit()]


def texts(pages, s):
    return [n for n, p in enumerate(pages, 1) for t in p["texts"] if t["s"] == s]


def overview_ok(data, label, parts, net, first=2):
    """parts = {name: heading text as printed}: the overview on page 1 names every part with the right page and link."""
    pages = pdfcheck.layout(data)
    check(len(pages) >= 2, f"{label}: two pages or more ({len(pages)})")
    check(pdfcheck.problems(data) == [], f"{label}: the layout is clean {pdfcheck.problems(data)[:3]}")
    check(texts(pages, "ÜBERSICHT") == [1], f"{label}: the overview on page 1")
    check(texts(pages, f"Die Einzelpositionen je Teil stehen ab Seite {first}.") == [1], f"{label}: the hint below it")
    lk = links(data)
    tg = tags(pages)
    check(len(tg) == len(lk[0]) >= len(parts) and all(n == 1 for n, _ in tg) and not any(lk[1:]), f"{label}: one tag + link per row, all on page 1 ({len(tg)}, {[len(x) for x in lk]})")
    rows = []
    for name, head in parts.items():
        y = next((t["y"] for t in pages[0]["texts"] if t["s"] == name), None)
        check(y is not None, f"{label}: {name} in the overview")
        if y is None:
            continue
        tag = next(((n, t) for n, t in tg if abs(t["y"] - y) < 3), None)
        real = [n for n in texts(pages, head) if n >= first]
        check(tag is not None and bool(real) and tag[1]["s"] == f"SEITE {real[0]}", f"{label}: {name} tag = the page of its heading ({tag and tag[1]['s']}, {real})")
        if tag and real:
            h = float(pages[0]["h"])
            hit = [x for x in lk[0] if x[0][0] <= tag[1]["x"] and tag[1]["x"] + tag[1]["w"] <= x[0][2] and x[0][1] <= h - tag[1]["y"] - 2 <= x[0][3]]
            check(len(hit) == 1 and hit[0][3] == real[0] and hit[0][1] == 4 and not hit[0][2], f"{label}: {name} link to page {real[0]}, print flag, no action {hit}")
            top = next(t["y"] for t in pages[real[0] - 1]["texts"] if t["s"] == head)
            check(hit and abs(hit[0][4] - top) < 25, f"{label}: {name} the link lands at the heading ({hit and hit[0][4]}, {top})")
        am = [t for t in pages[0]["texts"] if abs(t["y"] - y) < 3 and t["s"].endswith(" €")]
        if am:
            rows.append(amount(am[0]["s"]))
    return rows, pages


def shot(name, data):
    d = os.environ.get("P2438B_SHOTS") or ""
    if not d:
        return
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, name + ".pdf")
    with open(f, "wb") as fh:
        fh.write(data)
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "90", "-f", "1", "-l", "1", "-singlefile", f, os.path.join(d, name)], check=False)


# ---------------------------------------------------------------- the writer on its own
def line(i, total=100, **kw):
    return {"kind": "item", "pos": i, "title": f"Leistung {i}", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": total,
            "rate_text": euro(total), "tax_pct": 19, "total": total, "total_text": euro(total), **kw}


def model(kind="offer", parts=3, per=20, lead=0, net=None, **kw):
    lines = [line(i) for i in range(1, lead + 1)]
    for p in range(1, parts + 1):
        lines.append({"kind": "heading", "title": f"Teil {p}"})
        lines += [line(len(lines) + 1) for _ in range(per)]
    n = sum(x.get("total", 0) for x in lines)
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "A-2026-438", "date": "2026-10-30", "date_text": "30.10.2026",
         "title": "Kostenvoranschlag", "company": CO, "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "meta": [["Nr.", "A-2026-438"], ["Datum", "30.10.2026"]], "lines": lines,
         "totals": {"net": n if net is None else net, "rows": [["Summe netto", euro(n)], ["Gesamt", euro(n * Decimal("1.19"))]], "show_tax_lines": False},
         "labels": {"pos": "Pos.", "title": "Leistung", "qty": "Menge", "unit_price": "Preis", "total": "Gesamt", "vat": "MwSt."}}
    m.update(kw)
    return m


def no_overview(m, label, min_pages=1):
    data = pdf.office_pdf(m)
    pages = pdfcheck.layout(data)
    check(len(pages) >= min_pages and not texts(pages, "ÜBERSICHT") and not tags(pages) and not any(links(data))
          and not any("Einzelpositionen" in t["s"] for p in pages for t in p["texts"]), f"{label}: no overview, tag, hint or link ({len(pages)} pages)")
    return pages


pg = no_overview(model(parts=2, per=3), "one page", 1)
check(len(pg) == 1, f"one page stays one page ({len(pg)})")
no_overview(model(parts=1, per=60), "one part only", 2)
no_overview(model(parts=0, lead=60), "no heading", 2)
no_overview(model(parts=3, lead=2), "positions before the first heading", 2)
no_overview(model(net=1), "rows differ from the net total", 2)
no_overview(model("delivery", noprice=True), "delivery note", 2)
no_overview(model("reminder"), "reminder", 2)

data = pdf.office_pdf(model())
rows, pg = overview_ok(data, "model", {"Teil 1": "TEIL 1", "Teil 2": "TEIL 2", "Teil 3": "TEIL 3"}, 6000)
check(rows[:3] == [Decimal("2000.00")] * 3, f"model: the part totals {rows}")
check(set(texts(pg, "Leistung 2")) == {2}, f"model: the positions start on page 2 {texts(pg, 'Leistung 2')}")
check(len(texts(pg, "Summe netto")) == 2, "model: the totals on page 1 and at the end of the positions")
empty = model()
empty["lines"].insert(0, {"kind": "heading", "title": "Nur ein Zwischentitel"})
check(not texts(pdfcheck.layout(pdf.office_pdf(empty)), "Nur ein Zwischentitel"), "a heading without positions is no part")

# a long part name wraps and keeps its tag; many parts run over page 1 and the hint names the real first page
lg = model(parts=45, per=1)
d2 = pdf.office_pdf(lg)
p2 = pdfcheck.layout(d2)
first = next(n for n, p in enumerate(p2, 1) if any(t["s"] == "TEIL 1" for t in p["texts"]))
check(first >= 2 and texts(p2, f"Die Einzelpositionen je Teil stehen ab Seite {first}.") and pdfcheck.problems(d2) == [],
      f"45 parts: the overview runs on, the hint names page {first} {pdfcheck.problems(d2)[:3]}")
check(sum(len(x) for x in links(d2)) == 45 and len(tags(p2)) == 45, "45 parts: a tag and a link each")

# an own letterhead: the following pages move by the difference of the left margins, so do the links on them
bp = model(parts=45, per=1, letterhead={"m1": [45, 20, 32, 25], "m2": [30, 20, 32, 35], "hide_head": 0, "hide_footer": 0, "pages": 0})
d3 = pdf.office_pdf(bp)
lk3, p3 = links(d3), pdfcheck.layout(d3)
tg3 = [(n, t) for n, t in tags(p3) if n > 1]
if tg3:
    check(all(any(x[0][0] <= t["x"] and t["x"] + t["w"] <= x[0][2] for x in lk3[n - 1]) for n, t in tg3), "letterhead: a link on a moved page covers its tag")
else:
    check(False, "letterhead: the overview reaches page 2")

ltr = pdf.office_pdf(model(paper="letter"))
check(any(links(ltr)) and links(ltr)[0][0][3] >= 2, "US-Letter: the links work too")

# printed parts: the title page already lists them: no second overview, the part rows carry the tag and link to the part's page
pt = model(parts=0)
pt["lines"] = [line(1, 900, part_id=7, title="Dreh"), line(2, 300, part_id=8, title="Schnitt"), line(3, 50, title="Fahrt")]
pt["totals"]["net"] = 1250
pt["parts"] = [{"id": i, "kind": "items", "title": t, "head": [], "lines": [line(j, 10) for j in range(1, 40)], "totals": {"rows": [["Summe", euro(390)]]}}
               for i, t in ((7, "Dreh"), (8, "Schnitt"))]
d4 = pdf.office_pdf(pt)
p4 = pdfcheck.layout(d4)
l4 = links(d4)
starts = {t: next(n for n in texts(p4, t) if n > 1) for t in ("Dreh", "Schnitt")}
check(not texts(p4, "ÜBERSICHT") and [t["s"] for _, t in tags(p4)] == [f"SEITE {starts['Dreh']}", f"SEITE {starts['Schnitt']}"], f"printed parts: the rows carry the tag {[t['s'] for _, t in tags(p4)]}")
check([x[3] for x in l4[0]] == [starts["Dreh"], starts["Schnitt"]], f"printed parts: the links go to the parts' pages {l4[0]}")
check(texts(p4, f"Die Einzelpositionen je Teil stehen ab Seite {starts['Dreh']}.") == [1], "printed parts: the hint on the title page")
check(pdfcheck.problems(d4) == [], f"printed parts: clean layout {pdfcheck.problems(d4)[:3]}")
# review: the title page may name the parts in another order than they are printed: the hint names the first part printed
pr = dict(pt, lines=list(reversed(pt["lines"][:2])) + pt["lines"][2:])
pr5 = pdfcheck.layout(pdf.office_pdf(pr))
first5 = min(n for t in ("Dreh", "Schnitt") for n in texts(pr5, t) if n > 1)
check(texts(pr5, f"Die Einzelpositionen je Teil stehen ab Seite {first5}.") == [1], "printed parts: the hint names the first part printed, not the first row")
# 2.484.0 (#3738): a part row higher than a page (a long detail text) takes the line-by-line way and still carries its tag
ph = dict(pt, lines=[line(1, 900, part_id=7, title="Dreh", detail="\n".join(f"Drehtag {i}: Kamera, Licht und Ton am Set" for i in range(1, 121)))] + pt["lines"][1:])
d6 = pdf.office_pdf(ph)
p6 = pdfcheck.layout(d6)
tg6 = [t["s"] for _, t in tags(p6)]
check(len(tg6) == 2 and tg6[0].startswith("SEITE ") and tg6[1] == f"SEITE {next(n for n in texts(p6, 'Schnitt') if n > 1)}", f"tall part row: both rows carry their tag {tg6}")
check(len(texts(p6, "Drehtag 120: Kamera, Licht und Ton am Set")) == 1 and texts(p6, "Drehtag 120: Kamera, Licht und Ton am Set")[0] > 1, "tall part row: the detail really runs over page 1")


# ---------------------------------------------------------------- through the API
if os.environ.get("P2438B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
assert A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).ok


def items(parts=("Planung", "Elektro", "Akustik"), per=18):
    out = []
    for p, name in enumerate(parts):
        out.append({"kind": "heading", "title": name})
        out += [{"title": f"{name} Position {i}", "qty": 2, "unit": "day", "rate": 100 * (p + 1), "tax": "standard"} for i in range(per)]
    return out


PARTS = {"Planung": "PLANUNG", "Elektro": "ELEKTRO", "Akustik": "AKUSTIK"}


def flow(s, who):
    r = s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {
        "name": "Beispielfilm", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "tax_number": "12/345/67890",
        "iban": IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    assert r.ok, r.text
    r = s.post(B + "/api/clients", json={"name": "Kunde AG", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"})
    assert r.status_code == 201, r.text
    cl = r.json()["id"]
    r = s.post(B + D, json={"project_title": "Umbau", "client_id": cl, "raw_mode": "none", "producing_on": 0, "service_from": "2026-10-01", "service_to": "2026-10-30"})
    assert r.status_code == 201, r.text
    off = r.json()["id"]
    assert s.put(B + f"{D}/{off}/items", json={"items": items()}).ok
    pdf_ = s.get(B + f"{D}/{off}/pdf")
    check(pdf_.ok, f"{who}: quotation PDF")
    shot("p2438-kv", pdf_.content)
    rows, _ = overview_ok(pdf_.content, f"{who} quotation", PARTS, 0)
    check(rows[:3] == [Decimal("3600.00"), Decimal("7200.00"), Decimal("10800.00")], f"{who} quotation: the part totals {rows}")

    # a discount of the quotation stands as a row of its own: the parts keep their own totals, the rows add up to the net total
    assert s.patch(B + f"{D}/{off}", json={"discount_pct": 10}).ok
    data = s.get(B + f"{D}/{off}/pdf").content
    rows, pg = overview_ok(data, f"{who} discount", PARTS, 0)
    net = Decimal(str(s.get(B + f"{D}/{off}").json()["totals"]["net"]))
    am = [amount(t["s"]) for t in pg[0]["texts"] if t["s"].startswith("-") and t["s"].endswith(" €")]
    check(net == Decimal("19440.00") and am[:1] == [Decimal("-2160.00")] and sum(rows[:3]) + am[0] == net, f"{who} discount: rows {rows} {am} = net {net}")
    assert s.patch(B + f"{D}/{off}", json={"discount_pct": 0}).ok

    # a short quotation of the same parts: one page, nothing of it
    r = s.post(B + D, json={"project_title": "Klein", "client_id": cl, "raw_mode": "none", "producing_on": 0})
    short = r.json()["id"]
    assert s.put(B + f"{D}/{short}/items", json={"items": items(("Planung", "Elektro"), per=1)}).ok
    pg = pdfcheck.layout(s.get(B + f"{D}/{short}/pdf").content)
    check(len(pg) == 1 and not texts(pg, "ÜBERSICHT"), f"{who}: a one-page quotation has no overview ({len(pg)}, {texts(pg, 'ÜBERSICHT')}, {[t['s'] for t in pg[-1]['texts']][:12]})")

    # an invoice of the same positions, finalised: the e-invoice stays embedded, the XML has no part of it
    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "pct": 10})
    check(r.status_code == 201, f"{who}: progress invoice {r.text[:200]}")
    prog = r.json()["id"]
    plain = s.get(B + f"{D}/{prog}/pdf").content
    check(not texts(pdfcheck.layout(plain), "ÜBERSICHT"), f"{who}: a progress invoice of one summary position has no parts, no overview")
    assert s.put(B + f"{D}/{prog}/items", json={"items": items()}).ok, "progress positions"
    rows, _ = overview_ok(s.get(B + f"{D}/{prog}/pdf").content, f"{who} progress", PARTS, 0)
    check(rows[:3] == [Decimal("3600.00"), Decimal("7200.00"), Decimal("10800.00")], f"{who} progress: the part totals {rows}")
    assert s.put(B + f"{D}/{prog}/items", json={"items": [{"title": "Abschlag", "qty": 1, "unit": "flat", "rate": 2160, "tax": "standard"}]}).ok
    r = s.post(B + f"{D}/{prog}/finalize")
    check(r.ok, f"{who}: progress invoice finalised {r.text[:200]}")

    r = s.post(B + f"{D}/{off}/invoice", json={"inv_type": "final"})
    check(r.status_code == 201, f"{who}: final invoice {r.text[:200]}")
    fin = r.json()["id"]
    r = s.post(B + f"{D}/{fin}/finalize")
    check(r.ok, f"{who}: final invoice finalised {r.text[:200]}")
    data = s.get(B + f"{D}/{fin}/pdf").content
    shot("p2438-schluss", data)
    rows, pg = overview_ok(data, f"{who} final", PARTS, 0)
    check(rows[:3] == [Decimal("3600.00"), Decimal("7200.00"), Decimal("10800.00")], f"{who} final: the parts without the deduction {rows}")
    check(any("Restbetrag" == t["s"] for t in pg[0]["texts"]), f"{who} final: the totals of page 1 end with the amount remaining")
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    check(any(n.endswith(".xml") for n in rd.attachments), f"{who} final: the e-invoice stays embedded {list(rd.attachments)}")


flow(A, "organisation")
FID, Fr = freelancer(B, A)
flow(Fr, "freelancer")
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
