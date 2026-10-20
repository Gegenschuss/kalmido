#!/usr/bin/env python3
"""2.138.0 API tests, part A (quotation editor), own container (start.sh). Invented services and amounts only.
(taken over from the 2.112.0 A / B suites, only the cases of #2236 #2239 #2240)
 - #2239: renaming a part updates its title page lines that still carry the old name (or none); a line with an own text
   stays; an empty name leaves the lines alone
 - #2239: a title page save whose list was built before a part was added (parts_known without the new part) keeps the
   part's line; a save that knew the part removes it as before; without parts_known (API) the list is taken as it is
 - #2236: a percent position switched back to a unit counts qty x rate again
 - rights: a member of another organisation gets 404 on the rename; a sent quotation answers 409
 - freelancer-matrix: office (a person without an organisation: parts, rename, kept line)
 - #2240 (no server, kalmido/office/pdf.py of the source tree): a long part title wraps over two or more lines, the small
   "number · project" line stands above it (no overlap); a long document title on the title page wraps over the full
   width; the accent line sits below the last title line
usage: p2138_a_api_test.py <datadir>      (P2138A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh;
       KALMIDO_SRC = the source tree for the PDF part, default ../ next to tests/)"""
import importlib.util
import io
import os
import subprocess
import sys

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
D = "/api/office/docs"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def svc(title, qty, rate, unit="day"):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


def body(items):
    """the title page list as the editor sends it (office_docs.js ofdItemsBody)"""
    keep = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "raw_fee", "producing", "intext", "cost", "discountable", "ref_part_id")
    return [{k: it.get(k) for k in keep} for it in items]


def part_lines(doc, pid):
    return [it for it in doc.get("items") or [] if it.get("kind") == "part" and it.get("ref_part_id") == pid]


if not os.environ.get("P2138A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
ids = {u: i for u, i in dbx("SELECT username, id FROM users")}
Ca = sess("carol")
for s_ in (A, Ca):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})


def run(S, who):
    r = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Campaign", "items": [svc("Concept", 1, 800)]})
    check(r.status_code == 201, f"{who}: a quotation {r.status_code} {r.text[:200]}")
    doc = r.json()
    did = doc["id"]
    # ---- #2239: rename follows on the title page
    r = S.post(B + f"{D}/{did}/parts", json={"title": "Part 3"})
    check(r.status_code == 201, f"{who}: a part {r.status_code}")
    p1 = r.json()["part"]["id"]
    check([x["title"] for x in part_lines(r.json(), p1)] == ["Part 3"], f"{who}: the new part is on the title page {part_lines(r.json(), p1)}")
    r = S.patch(B + f"{D}/{did}/parts/{p1}", json={"title": "Module web"})
    check(r.ok and [x["title"] for x in part_lines(r.json(), p1)] == ["Module web"], f"{who}: #2239 rename -> title page line follows {r.text[:200]}")
    # a second line of the same part with an own text, one with an empty title
    cur = r.json()
    items = body(cur["items"]) + [{"kind": "part", "ref_part_id": p1, "title": "Own text", "qty": 2},
                                  {"kind": "part", "ref_part_id": p1, "title": "", "qty": 1}]
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": [p1]})
    check(r.ok and sorted(x["title"] for x in part_lines(r.json(), p1)) == ["Module web", "Module web", "Own text"],
          f"{who}: the empty title takes the part's name {[x['title'] for x in part_lines(r.json(), p1)]}")
    r = S.patch(B + f"{D}/{did}/parts/{p1}", json={"title": "Module app"})
    check(r.ok and sorted(x["title"] for x in part_lines(r.json(), p1)) == ["Module app", "Module app", "Own text"],
          f"{who}: #2239 rename: lines with the old name follow, the own text stays {[x['title'] for x in part_lines(r.json(), p1)]}")
    r = S.patch(B + f"{D}/{did}/parts/{p1}", json={"title": ""})
    check(r.ok and sorted(x["title"] for x in part_lines(r.json(), p1)) == ["Module app", "Module app", "Own text"],
          f"{who}: an empty part name leaves the title page lines alone")
    S.patch(B + f"{D}/{did}/parts/{p1}", json={"title": "Module app"})
    # ---- #2239: a stale title page save keeps the line of a part it did not know
    stale = S.get(B + f"{D}/{did}").json()
    r = S.post(B + f"{D}/{did}/parts", json={})
    p2 = r.json()["part"]["id"]
    check(len(part_lines(r.json(), p2)) == 1, f"{who}: part 2 on the title page")
    items = body(stale["items"])
    items[0]["qty"] = 3  # the edit that was saved while the part was created
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": [p["id"] for p in stale.get("parts") or []]})
    after = r.json()
    check(r.ok and len(part_lines(after, p2)) == 1 and after["items"][0]["qty"] == 3,
          f"{who}: #2239 the stale save keeps the new part's line and the edit {r.text[:300]}")
    pp = next((p for p in after.get("parts") or [] if p["id"] == p2), {})
    check(pp.get("used") == 1, f"{who}: part 2 counts (used 1) {pp.get('used')}")
    # a save that knew the part removes its line (on purpose)
    items = [x for x in body(after["items"]) if x.get("ref_part_id") != p2]
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": [p1, p2]})
    check(r.ok and not part_lines(r.json(), p2), f"{who}: a save that knew the part removes its line")
    # without parts_known (API v1 / agents): the list as it is
    r = S.post(B + f"{D}/{did}/parts", json={})
    p3 = r.json()["part"]["id"]
    items = [x for x in body(r.json()["items"]) if x.get("ref_part_id") != p3]
    r = S.put(B + f"{D}/{did}/items", json={"items": items})
    check(r.ok and not part_lines(r.json(), p3), f"{who}: without parts_known the list is taken as it is")
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": "x"})
    check(r.ok, f"{who}: a broken parts_known is ignored {r.status_code}")
    # ---- #2236: a percent position switched back
    r = S.put(B + f"{D}/{did}/items", json={"items": [svc("Insurance", 0, 5, unit="percent")]})
    check(r.ok, f"{who}: a percent position {r.text[:200]}")
    r = S.put(B + f"{D}/{did}/items", json={"items": [svc("Insurance", 1, 500, unit="day")]})
    check(r.ok and r.json()["totals"]["net"] == 500 and r.json()["items"][0]["unit"] == "day", f"{who}: #2236 back to day: 1 x 500 {r.text[:200]}")
    # ---- rights: a sent quotation is locked (rename 409)
    r = S.post(B + f"{D}/{did}/finalize", json={})
    check(r.ok, f"{who}: finalise {r.status_code} {r.text[:200]}")
    r = S.post(B + f"{D}/{did}/status", json={"status": "sent"})
    check(r.ok and r.json().get("status") == "sent", f"{who}: mark as sent {r.text[:200]}")
    r = S.patch(B + f"{D}/{did}/parts/{p1}", json={"title": "Late"})
    check(r.status_code == 409, f"{who}: sent quotation: rename 409 {r.status_code}")
    return did, p1


did, p1 = run(A, "org")
# ---- another organisation: 404
r = Ca.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Other"})
r2 = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Mine"})
mine = r2.json()["id"]
pm = A.post(B + f"{D}/{mine}/parts", json={"title": "Secret"}).json()["part"]["id"]
r = Ca.patch(B + f"{D}/{mine}/parts/{pm}", json={"title": "Taken"})
check(r.status_code == 404, f"another organisation: rename 404 {r.status_code}")
r = Ca.put(B + f"{D}/{mine}/items", json={"items": [], "parts_known": []})
check(r.status_code == 404, f"another organisation: title page save 404 {r.status_code}")
check([x["title"] for x in part_lines(A.get(B + f"{D}/{mine}").json(), pm)] == ["Secret"], "the foreign attempts changed nothing")

# ---- freelancer-matrix: office (a person without an organisation, its own admin)
FID, Fr = freelancer(B, A)
run(Fr, "freelancer")

# ================================================================ #2240: page layout of the document PDF (no server)
# the text calls of every page are recorded (x, y, size, text) by wrapping the page class of the writer; pypdf opens each PDF.
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf_p2138a", os.path.join(SRC, "kalmido", "office", "pdf.py"))
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


def pmodel(n_items=3, parts=None, title="Kostenvoranschlag", kind="offer", heading_every=0, closing=True):
    lines = []
    for i in range(1, n_items + 1):
        if heading_every and i % heading_every == 1:
            lines.append({"kind": "heading", "title": f"Gruppe {i // heading_every + 1}"})
        lines.append(item(i, f"Leistung Nummer {i}"))
    net = 100.0 * n_items
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "KVA-2026-077", "date": "2026-10-19", "date_text": "19.10.2026",
         "title": title, "project_title": "Serie Beispielprojekt",
         "company": {"name": "Beispielstudio GmbH", "lines": ["Beispielstudio GmbH", "Musterweg 1", "12345 Musterstadt"],
                     "contact_lines": ["kontakt@example.com"], "color": "#6b4fbb"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "intro": "Sehr geehrte Damen und Herren,\nwir bieten Ihnen an:",
         "lines": lines,
         "totals": {"rows": [["Summe Netto", money(net)], ["MwSt. 19 %", money(net * 0.19)], ["Gesamt", money(net * 1.19)]], "show_tax_lines": True,
                    "vat_note": "Alle Preise zuzüglich MwSt."},
         "labels": {"offer_no": "Angebot Nr.", "net_total": "Summe Netto", "page_of": "Seite {x} von {y}", "order": "Auftragserteilung"}}
    if closing:
        m["closing"] = "Wir freuen uns auf die Zusammenarbeit und stehen für Rückfragen gerne zur Verfügung."
        m["signature"] = "Mit freundlichen Grüßen"
        m["signature_name"] = "Erika Beispiel"
    if parts:
        m["parts"] = parts
    return m


# ---------------------------------------------------------------- 1. #2240: a long part title wraps, the number line above it
LONG = "Hauptepisoden (3 Stück je ca 120 Sekunden) mit Sprecher, Musik und zwei Korrekturschleifen"
check(len(LONG) >= 60, "the part title has 60+ characters")
part = {"title": LONG, "lines": [item(1, "Dreh"), item(2, "Schnitt")], "totals": {"rows": [["Summe Teil", money(200)]]}}
data, r, pages = render(pmodel(parts=[part]))
# 2.138.0: the writer may build helper pages (measuring) beyond the printed ones
check(data.startswith(b"%PDF-1.7") and len(r.pages) >= 2 and len(pages) >= len(r.pages), f"the PDF with a part renders ({len(r.pages)} pages, {len(pages)} recorded)")
pp = next((p for p in pages[1:] if any(t["size"] == 14 for t in p.rec)), None)
check(pp is not None, "the part page carries the part title (14 pt)")
if pp is not None:
    tl = [t for t in pp.rec if t["size"] == 14 and t["bold"]]
    sub = [t for t in pp.rec if "Angebot Nr. KVA-2026-077" in t["s"]]
    check(len(tl) >= 2, f"the long part title stands in 2+ lines ({len(tl)})")
    check(" ".join(t["s"] for t in tl) == LONG.upper(), "the title lines together give the whole title (upper case)")
    check(all(t["x"] + t["w"] <= pdf.PDF_L + pdf.PDF_CW + 0.5 for t in tl), "no title line runs past the right margin")
    check(len(sub) == 1 and "Serie Beispielprojekt" in sub[0]["s"], "the number + project line is printed once on the part page")
    if sub and tl:
        check(abs(sub[0]["x"] - pdf.PDF_L) < 0.5 and sub[0]["y"] + sub[0]["size"] <= min(t["y"] for t in tl),
              "the number line stands left above the title")
        check(not any(overlap(sub[0], t) for t in tl), "the number line and the title never overlap")
        accents = [ru for ru in pp.rules if ru[4] == 1.6]
        check(accents and accents[0][1] > max(t["y"] for t in tl) + 14, "the accent line sits below the last title line")
        first_row = min((t["y"] for t in pp.rec if t["s"] == "Dreh"), default=0)
        check(first_row > accents[0][1] if accents else False, "the first position comes below the part head")

# a short part title stays on one line
data, r, pages = render(pmodel(parts=[dict(part, title="Trailer")]))
pp = next((p for p in pages[1:] if any(t["size"] == 14 for t in p.rec)), None)
check(pp is not None and [t["s"] for t in pp.rec if t["size"] == 14] == ["TRAILER"], "a short part title: one line")

# ---------------------------------------------------------------- 2. #2240: the title page heading wraps over the full width
LONG_T = "Kostenvoranschlag für die Herbstkampagne mit drei Filmen und Social Media Schnittfassungen"
data, r, pages = render(pmodel(title=LONG_T))
p1 = pages[0]
tl = [t for t in p1.rec if t["size"] == 16]
pg = [t for t in p1.rec if t["s"].startswith("Seite 1 von")]
check(len(tl) >= 2 and " ".join(t["s"] for t in tl) == LONG_T.upper(), f"a long document title wraps ({len(tl)} lines)")
check(all(t["x"] + t["w"] <= pdf.PDF_L + pdf.PDF_CW + 0.5 for t in tl), "no title line runs past the right margin")
check(not any(overlap(x, t) for x in pg for t in tl), "a page count never overlaps the title")  # 2.138.0: the page count sits in the footer
intro = next((t for t in p1.rec if t["s"].startswith("Sehr geehrte")), None)
check(intro is not None and tl and intro["y"] > max(t["y"] for t in tl) + 16, "the text below starts under the last title line")

print(f"p2138_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
