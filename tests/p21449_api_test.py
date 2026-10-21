#!/usr/bin/env python3
"""2.144.9 API tests (#2575, office PDF: number, rights page, quotation reference), own container (start.sh). Invented
companies, people and amounts only.
 - numbers: an empty block of the scheme takes its separator along -- "{project}-KV{seq:02}-{initials}" without a project
   gives "KV01-..." (no leading hyphen), "KV-{project}-{seq:02}" gives "KV-02" (no double hyphen); with a project as before;
   a duplicate of such a number ({version}) keeps its running number (the number is read back under the scheme)
 - an invoice made from a quotation names it in the head ("zu Angebot Nr." number + date); an invoice without one does not
 - the part's name is one source (decision 21.10.2026): renaming the part changes its title page line, changing the title page
   line renames the part; the spelling stays as typed
 - freelancer-matrix: office (a person without an organisation: numbers, invoice from a quotation, part names)
 - no server (kalmido/office/pdf.py of the source tree): the rights appendix and the part pages of an invoice name "Rechnung
   Nr.", not "Angebot Nr."; a part page shows the row "+ Optional ..." before "net total with option"; the part title is
   printed as typed
usage: p21449_api_test.py <datadir>      (P21449_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh;
       KALMIDO_SRC = the source tree for the PDF part, default ../ next to tests/)"""
import importlib.util
import os
import re
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
SET = "/api/office/settings"
FAILS, OKS = [], [0]
TEST_IBAN = "DE02120300000000202051"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}


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


def part_lines(doc, pid):
    return [it for it in doc.get("items") or [] if it.get("kind") == "part" and it.get("ref_part_id") == pid]


def body(items):
    keep = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "raw_fee", "producing", "intext", "cost", "discountable", "ref_part_id")
    return [{k: it.get(k) for k in keep} for it in items]


if not os.environ.get("P21449_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ids = {u: i for u, i in dbx("SELECT username, id FROM users")}
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def run(S, who):
    r = S.put(B + SET, json={"company_fields": COMPANY, "lang": "de", "currency": "EUR", "offer_counter": "org",
                             "offer_scheme": "{project}-KV{seq:02}-{initials}"})
    check(r.ok, f"{who}: settings {r.text[:200]}")
    # ---- 1. numbers: an empty block takes its separator along
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "date": "2030-03-01"})
    n1 = r.json().get("number") or ""
    check(r.status_code == 201 and re.fullmatch(r"KV\d\d(-[\w-]+)?", n1), f"{who}: no project: no leading hyphen {n1!r}")
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "date": "2030-03-01", "project_title": "Spot"})
    n2 = r.json().get("number") or ""
    check(r.status_code == 201 and n2.startswith("Spot-KV") and int(n2[7:9]) == int(n1[2:4]) + 1, f"{who}: with a project as before {n2!r}")
    S.put(B + SET, json={"offer_scheme": "KV-{project}-{seq:02}"})
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "date": "2030-03-01"})
    n3 = r.json().get("number") or ""
    check(re.fullmatch(r"KV-\d\d", n3) is not None, f"{who}: an empty block in the middle: no double hyphen {n3!r}")
    S.put(B + SET, json={"offer_scheme": "KV-{project}-{seq:02}-V{version}"})
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "date": "2030-03-01"})
    n4, root = r.json().get("number") or "", r.json().get("id")
    check(re.fullmatch(r"KV-\d\d-V1", n4) is not None, f"{who}: with a version block {n4!r}")
    r = S.post(B + f"{D}/{root}/duplicate")
    check(r.status_code == 201 and r.json().get("number") == n4[:-1] + "2", f"{who}: the duplicate keeps the running number, V2 {r.text[:200]}")
    S.put(B + SET, json={"offer_scheme": "{project}-KV{seq:02}-{initials}"})

    # ---- 2. an invoice from a quotation names it in the head
    r = S.post(B + "/api/clients", json={"name": "ACME", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                         "email_invoice": "billing@acme.example", "payment_terms_days": 14})
    cl = r.json().get("id")
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "date": "2030-03-02", "client_id": cl, "project_title": "Kampagne",
                            "items": [{"kind": "service", "title": "Konzept", "qty": 1, "unit": "day", "rate": 800}]})
    off = r.json()
    check(r.status_code == 201 and off.get("number"), f"{who}: a quotation {r.text[:200]}")
    r = S.post(B + f"{D}/{off['id']}/invoice")
    check(r.status_code in (200, 201), f"{who}: invoice from the quotation {r.status_code} {r.text[:200]}")
    inv = r.json().get("invoice") or r.json()
    rd = S.get(B + f"{D}/{inv['id']}/render").json()
    meta = dict((k, v) for k, v in rd.get("meta") or [])
    check(meta.get("zu Angebot Nr.") == f"{off['number']} (02.03.2030)", f"{who}: the invoice's head names the quotation {meta}")
    r = S.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
    rd = S.get(B + f"{D}/{r.json()['id']}/render").json()
    check(not any(k == "zu Angebot Nr." for k, _ in rd.get("meta") or []), f"{who}: an invoice without a quotation: no such row {rd.get('meta')}")
    r = S.get(B + f"{D}/{inv['id']}/pdf")
    check(r.ok and r.content[:5] == b"%PDF-", f"{who}: the invoice PDF {r.status_code}")

    # ---- 3. the part's name is one source, both ways
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "items": [{"kind": "service", "title": "Konzept", "qty": 1, "unit": "day", "rate": 800}]})
    did = r.json()["id"]
    r = S.post(B + f"{D}/{did}/parts", json={"title": "Test Teil 2"})
    pid = r.json()["part"]["id"]
    check([x["title"] for x in part_lines(r.json(), pid)] == ["Test Teil 2"], f"{who}: the part's line on the title page {part_lines(r.json(), pid)}")
    # part area -> title page
    r = S.patch(B + f"{D}/{did}/parts/{pid}", json={"title": "Test Teil 3"})
    check(r.ok and [x["title"] for x in part_lines(r.json(), pid)] == ["Test Teil 3"], f"{who}: rename in the part area -> the title page line follows")
    # title page -> part area
    items = body(r.json()["items"])
    for it in items:
        if it.get("ref_part_id") == pid:
            it["title"] = "Test teil 4"
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": [pid]})
    doc = r.json()
    pp = next((p for p in doc.get("parts") or [] if p["id"] == pid), {})
    check(r.ok and pp.get("title") == "Test teil 4", f"{who}: the title page line renamed -> the part follows, as typed {pp.get('title')!r}")
    check([x["title"] for x in part_lines(doc, pid)] == ["Test teil 4"], f"{who}: the title page line keeps the text")
    doc = S.get(B + f"{D}/{did}").json()
    pp = next((p for p in doc.get("parts") or [] if p["id"] == pid), {})
    check(pp.get("title") == "Test teil 4" and [x["title"] for x in part_lines(doc, pid)] == ["Test teil 4"], f"{who}: stored both ways")
    # an unchanged save (another position edited) keeps the name
    items = body(doc["items"])
    items[0]["qty"] = 2
    r = S.put(B + f"{D}/{did}/items", json={"items": items, "parts_known": [pid]})
    check(r.ok and [x["title"] for x in part_lines(r.json(), pid)] == ["Test teil 4"], f"{who}: another edit leaves the name alone")
    r = S.get(B + f"{D}/{did}/pdf")
    check(r.ok and r.content[:5] == b"%PDF-", f"{who}: the quotation PDF with the part {r.status_code}")


run(A, "org")
# ---- freelancer-matrix: office (a person without an organisation, its own admin)
FID, Fr = freelancer(B, A)
run(Fr, "freelancer")

# ================================================================ the PDF writer (no server)
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf_p21449", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
PAGES = []


class RecPage(pdf._Page):
    def __init__(self):
        super().__init__()
        self.rec = []
        PAGES.append(self)

    def text(self, x, y, s, size, bold=False, color=pdf.C_INK, align="l", spacing=0.0, width=None):
        if str(s or ""):
            self.rec.append({"y": y, "s": str(s), "size": size})
        return super().text(x, y, s, size, bold, color, align, spacing, width)


pdf._Page = RecPage


def render(model):
    PAGES.clear()
    data = pdf.office_pdf(model)
    check(data.startswith(b"%PDF-"), "a PDF")
    return list(PAGES)


def item(pos, title, rate=100):
    return {"kind": "item", "pos": str(pos), "title": title, "qty": 1, "qty_text": "1", "unit": "Tag", "rate": rate,
            "rate_text": f"{rate},00 €", "tax_pct": 19, "total": rate, "total_text": f"{rate},00 €"}


def model(kind="offer", parts=None, rights=True):
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "RE-2026-001", "date": "2026-10-21", "date_text": "21.10.2026",
         "title": "Rechnung" if kind == "invoice" else "Kostenvoranschlag", "project_title": "Beispielfilm",
         "company": {"name": "Beispielstudio GmbH", "lines": ["Musterweg 1"], "color": "#6b4fbb"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2"]},
         "lines": [item(1, "Dreh")], "totals": {"rows": [["Summe netto", "100,00 €"]]},
         "labels": {"offer_no": "Angebot Nr."}}
    if kind == "invoice":
        m["meta"] = [["Rechnung Nr.", "RE-2026-001"], ["zu Angebot Nr.", "KV02-M (20.10.2026)"], ["Datum", "21.10.2026"]]
    if rights:
        m["rights"] = {"title": "Rechteübertragung", "rows": [["Zeit", "unbegrenzt"], ["Gebiet", "weltweit"]]}
    if parts:
        m["parts"] = parts
    return m


# ---- the invoice's rights appendix and part page name "Rechnung Nr."
part = {"title": "Test Teil 2", "lines": [item(1, "Schnitt")], "totals": {"rows": [["Summe netto", "100,00 €"]]}}
pages = render(model("invoice", parts=[part]))
texts = [t["s"] for p in pages for t in p.rec]
check(any("Rechnung Nr. RE-2026-001" in s for s in texts), "the invoice's appendix / part page says Rechnung Nr.")
check(not any("Angebot Nr. RE-2026-001" in s for s in texts), "no 'Angebot Nr.' before the invoice's number")
check(any(s == "zu Angebot Nr." for s in texts) and any(s == "KV02-M (20.10.2026)" for s in texts), "the head names the quotation")
# a quotation keeps "Angebot Nr."
pages = render(model("offer", parts=[part]))
check(any("Angebot Nr. RE-2026-001" in t["s"] for p in pages for t in p.rec), "a quotation's part page still says Angebot Nr.")

# ---- the part title as typed
pp = next((p for p in pages[1:] if any(t["size"] == 14 for t in p.rec)), None)
check(pp is not None and [t["s"] for t in pp.rec if t["size"] == 14][:1] == ["Test Teil 2"], "the part title as typed (no upper case)")

# ---- the part page shows "+ Optional ..." before the net total with option
opt = {"kind": "raw", "optional": True, "title": "Optional: Bereitstellung der Rohdaten", "total": 250, "total_text": "250,00 €"}
part = {"title": "Teil mit Option", "lines": [item(1, "Schnitt"), opt],
        "totals": {"rows": [["Summe netto", "100,00 €"], ["Summe netto mit Option Rohdaten", "350,00 €"]]}}
pages = render(model("offer", parts=[part], rights=False))
pp = next((p for p in pages[1:] if any(t["s"] == "Teil mit Option" for t in p.rec)), None)
recs = pp.rec if pp else []
o = next((t for t in recs if t["s"].startswith("+ Optional: Bereitstellung der Rohdaten")), None)
inc = next((t for t in recs if t["s"] == "Summe netto mit Option Rohdaten"), None)
net = next((t for t in recs if t["s"] == "Summe netto"), None)
check(o is not None and any(t["s"] == "250,00 €" for t in recs), f"the part page has the option row with its amount {[t['s'] for t in recs]}")
check(o is not None and inc is not None and net is not None and net["y"] < o["y"] < inc["y"], "order: net, + option, net with option")
# without an option no such row
part = {"title": "Ohne Option", "lines": [item(1, "Schnitt")], "totals": {"rows": [["Summe netto", "100,00 €"]]}}
pages = render(model("offer", parts=[part], rights=False))
check(not any(t["s"].startswith("+ Optional") for p in pages for t in p.rec), "no option: no option row")

print(f"p21449_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
