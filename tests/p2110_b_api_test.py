#!/usr/bin/env python3
"""2.153.0 API tests, part B (#2055): the receipts list of the bookkeeping over all months and the export for the tax
adviser. Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - GET /api/office/books/receipts: period (default this year), by=doc (document date) vs by=paid (payment day), each filter
   alone (status, category, supplier, project, novat, q) and combined, the sums, paging (limit / offset, more), the
   choices of the filters only from the receipts of the period, bad values 400
 - receipts.csv: BOM, semicolon, decimal comma, DD.MM.YYYY, all columns, formula injection made harmless, the filters
 - receipts.zip: belege.csv + exactly the filtered files, bytes = original (SHA-256), file names cleaned (no path parts)
 - rights: an organisation member 403, an agent 403, another organisation sees nothing of Alpha, a receipt the person
   does not see and one in the trash are missing in list and export; a person without organisation uses it fully
usage: p2110_b_api_test.py <datadir>      (P2110B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import csv
import hashlib
import io
import os
import subprocess
import sys
import zipfile
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
RL = O + "/books/receipts"
Y = date.today().year


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


HASH = {}


def receipt(s, ws, name, amount, day, category="", vat=None, sender=None, project=None, currency=None):
    """A receipt: a document (upload) with amount + date (+ sender, currency) and its assignment (category, VAT rate, project)."""
    data = tiny_pdf("Beleg " + name)
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, data, "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    HASH[nid] = hashlib.sha256(data).hexdigest()
    body = {"date": day}
    if amount:
        body["amount"] = amount
    if sender:
        body["sender"] = sender
    if currency:
        body["currency"] = currency
    r = s.patch(B + f"/api/docs/{nid}", json=body)
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "project_id": project, "keep": True})
    assert r.ok, r.text
    return nid


def get(s, q=""):
    r = s.get(B + RL + ("?" + q if q else ""))
    assert r.ok, (q, r.status_code, r.text[:300])
    return r.json()


def ids(j):
    return [x["node_id"] for x in j["rows"]]


if os.environ.get("P2110B_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
uids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR"})

# ---------------------------------------------------------------- rights first
for path in (RL, RL + ".csv", RL + ".zip"):
    check(Bo.get(B + path).status_code == 403, f"member: 403 on {path}")
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path}")
for bad in ("from=2026-13-01", "from=x", "to=2026-02-30", f"from={Y}-05-01&to={Y}-04-01", "by=due", "status=late", "supplier=abc",
            "project=-1", "limit=x"):
    check(A.get(B + RL + "?" + bad).status_code == 400, f"bad filter 400: {bad}")
j = get(A)
check(j["rows"] == [] and j["total"] == {"gross": "0.00", "net": "0.00", "vat": "0.00", "count": 0} and j["from"] == f"{Y}-01-01"
      and j["to"] == f"{Y}-12-31" and j["by"] == "doc", f"empty office: nothing, the default period is this year {j}")

# ---------------------------------------------------------------- receipts of Alpha over several months and years
WSO = f"org:{ORG}"
P1 = A.post(B + "/api/lists", json={"name": "Kundenfilm", "kind": "project"}).json()["id"]
R1 = receipt(A, WSO, "software.pdf", "119.00", "2025-02-10", "Software", "19", sender="Softhaus GmbH")
R2 = receipt(A, WSO, "buch.pdf", "107.00", "2025-11-20", "Books", "7", sender="Buchladen KG", project=P1)
R3 = receipt(A, WSO, "kasse.pdf", "50.00", "2026-01-05", "Material", None, sender="Baumarkt AG")
R4 = receipt(A, WSO, "cloud.pdf", "23.80", "2026-03-02", "Software", "19", sender="Softhaus GmbH")
R5 = receipt(A, WSO, "=HYPERLINK(evil).pdf", "10.00", "2026-03-15", "=cmd|calc", "19", sender="=SUM(A1)")
R6 = receipt(A, WSO, "flug.pdf", "109.00", "2026-04-01", "Travel", "0", sender="../Böse/Firma", project=P1, currency="USD")
R7 = receipt(A, WSO, "papierkorb.pdf", "99.00", "2026-04-02", "Material", "19")
NOAMT = receipt(A, WSO, "ohne-betrag.pdf", "", "2026-04-03", "Material", "19")
check(A.delete(B + f"/api/files/nodes/{R7}").ok, "a receipt into the trash")
dbx("UPDATE rc_receipts SET paid_at=? WHERE node_id=?", ("2026-01-10", R2), write=True)  # paid in the next year
dbx("UPDATE rc_receipts SET paid_at=? WHERE node_id=?", ("2026-03-20", R4), write=True)
fx = A.get(B + O + "/settings").json()["settings"].get("fx_usd") or "1.09"

j = get(A, "from=2025-01-01&to=2026-12-31")
check(ids(j) == [R6, R5, R4, R3, R2, R1], f"all receipts of two years, newest first, not the trash, not without amount {ids(j)}")
check(j["total"]["count"] == 6 and j["more"] is False, f"count {j['total']}")
row6 = next(x for x in j["rows"] if x["node_id"] == R6)
exp6 = round(109 / float(fx), 2)
check(abs(float(row6["amount"]) - exp6) < 0.011 and row6["orig_amount"] == "109.00" and row6["orig_currency"] == "USD"
      and row6["currency"] == "EUR", f"foreign currency: converted, the original kept {row6}")
row2 = next(x for x in j["rows"] if x["node_id"] == R2)
check(row2["supplier"] == "Buchladen KG" and row2["project"] == {"id": P1, "name": "Kundenfilm"} and row2["paid_at"] == "2026-01-10"
      and row2["doc_date"] == "2025-11-20" and row2["date"] == "2025-11-20" and row2["vat_pct"] == "7" and row2["net"] == "100.00"
      and row2["vat"] == "7.00" and row2["einvoice"] is False, f"a row: supplier, project, both days, VAT split {row2}")
tot = sum(float(x["amount"]) for x in j["rows"])
check(abs(float(j["total"]["gross"]) - tot) < 0.001, f"sum gross {j['total']} vs {tot}")
check(abs(float(j["total"]["net"]) + float(j["total"]["vat"]) - float(j["total"]["gross"])) < 0.001, "net + VAT = gross")
check(j["categories"] == ["=cmd|calc", "Books", "Material", "Software", "Travel"], f"categories of the period {j['categories']}")
check([x["name"] for x in j["suppliers"]] == ["../Böse/Firma", "=SUM(A1)", "Baumarkt AG", "Buchladen KG", "Softhaus GmbH"]
      or sorted(x["name"] for x in j["suppliers"]) == sorted(["../Böse/Firma", "=SUM(A1)", "Baumarkt AG", "Buchladen KG", "Softhaus GmbH"]),
      f"suppliers of the period {j['suppliers']}")
check(j["projects"] == [{"id": P1, "name": "Kundenfilm"}], f"projects of the period {j['projects']}")
SOFT = next(x["id"] for x in j["suppliers"] if x["name"] == "Softhaus GmbH")

# period + day basis
j = get(A, "from=2025-01-01&to=2025-12-31")
check(ids(j) == [R2, R1], f"2025 by document date {ids(j)}")
check(get(A, "from=2025-01-01&to=2025-12-31&by=paid")["rows"] and ids(get(A, "from=2025-01-01&to=2025-12-31&by=paid")) == [R1],
      "2025 by payment day: R2 paid in 2026 moves out")
j = get(A, "from=2026-01-01&to=2026-01-31&by=paid")
check(ids(j) == [R2, R3], f"January 2026 by payment day: R2 (paid 10.01.) and R3 (document date, unpaid) {ids(j)}")
j = get(A, "from=2026-03-01&to=2026-03-31")
check([x["name"] for x in j["suppliers"]] == ["=SUM(A1)", "Softhaus GmbH"] and j["categories"] == ["=cmd|calc", "Software"]
      and j["projects"] == [], f"choices only from the period {j['suppliers']} {j['categories']}")
# each filter alone
ALL = "from=2025-01-01&to=2026-12-31"
check(ids(get(A, ALL + "&status=paid")) == [R4, R2], "status paid")
check(ids(get(A, ALL + "&status=open")) == [R6, R5, R3, R1], "status open")
check(ids(get(A, ALL + "&category=software")) == [R4, R1], "category (case-insensitive)")
check(ids(get(A, ALL + f"&supplier={SOFT}")) == [R4, R1], "supplier")
check(ids(get(A, ALL + f"&project={P1}")) == [R6, R2], "project")
check(ids(get(A, ALL + "&novat=1")) == [R3], "only without VAT rate")
check(ids(get(A, ALL + "&q=bauMARKT")) == [R3], "search in the supplier")
check(ids(get(A, ALL + "&q=cloud")) == [R4], "search in the title")
# combined
j = get(A, ALL + f"&category=Software&status=paid&supplier={SOFT}")
check(ids(j) == [R4] and j["total"] == {"gross": "23.80", "net": "20.00", "vat": "3.80", "count": 1}, f"combined + sums {j['total']}")
check(ids(get(A, ALL + "&category=Software&novat=1")) == [], "combined: nothing")
# paging
p1, p2 = get(A, ALL + "&limit=4"), get(A, ALL + "&limit=4&offset=4")
check(ids(p1) == [R6, R5, R4, R3] and p1["more"] is True and ids(p2) == [R2, R1] and p2["more"] is False
      and p1["total"]["count"] == 6 == p2["total"]["count"], f"paging {ids(p1)} {ids(p2)}")

# ---------------------------------------------------------------- CSV
r = A.get(B + RL + ".csv?" + ALL)
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "attachment" in r.headers.get("Content-Disposition", ""), "CSV: a download")
t = r.content.decode("utf-8")
check(t.startswith("﻿"), "CSV: BOM")
rows = list(csv.reader(io.StringIO(t.lstrip("﻿")), delimiter=";"))
head = rows[0]
check(head == ["Receipt date", "Paid on", "Supplier", "VAT ID", "Invoice number", "E-invoice", "Title", "Category", "Project", "Net",
               "VAT rate", "VAT", "Gross", "Currency", "Original amount", "Original currency", "File name in the ZIP", "Kalmido ID"],
      f"CSV: all columns {head}")
body = {int(x[-1]): dict(zip(head, x)) for x in rows[1:]}
check(list(body) == [R1, R2, R3, R4, R5, R6], f"CSV: the filtered receipts oldest first {list(body)}")
b2 = body[R2]
check(b2["Receipt date"] == "20.11.2025" and b2["Paid on"] == "10.01.2026" and b2["Net"] == "100,00" and b2["VAT"] == "7,00"
      and b2["Gross"] == "107,00" and b2["VAT rate"] == "7" and b2["Project"] == "Kundenfilm" and b2["Supplier"] == "Buchladen KG"
      and b2["Currency"] == "EUR" and b2["E-invoice"] == "no", f"CSV: a row (DD.MM.YYYY, decimal comma) {b2}")
b5 = body[R5]
check(b5["Title"].startswith("'=") and b5["Category"] == "'=cmd|calc" and b5["Supplier"] == "'=SUM(A1)", f"CSV: formulas made harmless {b5}")
check(body[R6]["Original amount"] == "109,00" and body[R6]["Original currency"] == "USD", "CSV: the original amount")
check(all(not v[:1] in ("=", "+", "-", "@") for x in rows[1:] for v in x), "CSV: no cell starts a formula")
r = A.get(B + RL + ".csv?" + ALL + "&category=Books")
check(len(list(csv.reader(io.StringIO(r.content.decode("utf-8").lstrip("﻿")), delimiter=";"))) == 2, "CSV: follows the filters")
lang_de = A.get(B + RL + ".csv?" + ALL, headers={"Accept-Language": "de"})
check(lang_de.ok, "CSV in another language works")

# ---------------------------------------------------------------- ZIP
r = A.get(B + RL + ".zip?" + ALL + f"&project={P1}")
check(r.ok and r.headers["Content-Type"] == "application/zip", f"ZIP: a download {r.status_code} {r.text[:200] if not r.ok else ''}")
z = zipfile.ZipFile(io.BytesIO(r.content))
names = z.namelist()
files = [n for n in names if n.startswith("belege/")]
check("belege.csv" in names and len(files) == 2, f"ZIP: belege.csv + the 2 filtered files {names}")
for n in files:
    tail = n[len("belege/"):]
    check("/" not in tail and "\\" not in tail and ".." not in tail and len(tail) <= 120 and not any(ord(ch) < 32 for ch in tail),
          f"ZIP: clean file name {n!r}")
    nid = int(tail.rsplit("_", 1)[1].split(".")[0])
    check(hashlib.sha256(z.read(n)).hexdigest() == HASH[nid], f"ZIP: bytes = original {n}")
check(any(n.startswith(f"belege/2025-11-20_Buchladen-KG_107.00_{R2}.pdf") for n in files), f"ZIP: name date_supplier_gross_id.ext {files}")
zc = list(csv.reader(io.StringIO(z.read("belege.csv").decode("utf-8").lstrip("﻿")), delimiter=";"))
check(sorted(x[16] for x in zc[1:]) == sorted(files), f"ZIP: the CSV names the files in the ZIP {[x[16] for x in zc[1:]]} {files}")
r = A.get(B + RL + ".zip?" + ALL + "&q=nichtvorhanden")
check(r.ok and zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["belege.csv"], "ZIP: empty filter = only the CSV")
# 2.153.0 (#2055, review): a file lost on the disk does not break the whole ZIP, its CSV row stays
lost = dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no DESC LIMIT 1", (R2,))[0][0]
dbx("UPDATE fs_versions SET path=? WHERE node_id=?", ("files/0/lost-on-disk.pdf", R2), write=True)
r = A.get(B + RL + ".zip?" + ALL + f"&project={P1}")
check(r.ok and len([n for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist() if n.startswith("belege/")]) == 1,
      f"ZIP: a lost file is skipped, the rest comes ({r.status_code})")
dbx("UPDATE fs_versions SET path=? WHERE node_id=?", (lost, R2), write=True)
logs = dbx("SELECT detail FROM office_doc_log WHERE org_id=? AND action='export' AND target='books'", (ORG,))
check(sum(1 for x in logs if "receipts.zip" in str(x[0])) == 3 and any("receipts.csv" in str(x[0]) for x in logs), f"export log entries {logs}")

# ---------------------------------------------------------------- rights with data
check(get(Ca, ALL)["rows"] == [], "another organisation (its own office) sees nothing of Alpha")
r = Ca.get(B + RL + ".zip?" + ALL)
check(r.ok and zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["belege.csv"], "another organisation: its ZIP has no Alpha file")
check(Bo.get(B + RL + "?" + ALL).status_code == 403 and requests.get(B + RL + ".csv?" + ALL, headers=AGH).status_code == 403,
      "member / agent 403 with data")

# ---------------------------------------------------------------- a person without organisation (personal office)
# freelancer-matrix: office
FID, Fr = freelancer(B, A, "frida")
F1 = receipt(Fr, "private", "eigen.pdf", "59.50", f"{Y}-02-01", "Office", "19", sender="Papierhaus")
F2 = receipt(Fr, "private", "fremd.pdf", "11.90", f"{Y}-02-02", "Office", "19")
j = get(Fr)
check(ids(j) == [F2, F1] and j["total"]["gross"] == "71.40", f"freelancer: the own receipts, default period this year {ids(j)}")
dbx("UPDATE fs_nodes SET owner_id=? WHERE id=?", (uids["erik"], F2), write=True)  # a document she does not see any more
j = get(Fr)
check(ids(j) == [F1], f"freelancer: a receipt she does not see is missing {ids(j)}")
r = Fr.get(B + RL + ".csv")
check(r.ok and str(F2) not in r.content.decode("utf-8").split("\r\n", 1)[1] and str(F1) in r.text, "freelancer: CSV without the unseen receipt")
r = Fr.get(B + RL + ".zip")
zn = zipfile.ZipFile(io.BytesIO(r.content)).namelist() if r.ok else []
check(r.ok and len(zn) == 2 and any(n.endswith(f"_{F1}.pdf") for n in zn), f"freelancer: ZIP only the own receipt {zn}")
check(get(A, ALL)["total"]["count"] == 6, "Alpha unchanged by the freelancer")
check(F1 not in ids(get(A, f"from={Y}-01-01&to={Y}-12-31")), "Alpha does not see the freelancer's receipt")

# 2.153.0 (#2055): the export follows the country pack's switch books.export_csv (as the booking list, #2460); the list stays
r = A.put(B + O + "/settings", json={"features_off": ["books.export_csv"]})
check(r.ok, "switch the export off " + r.text[:160])
check(A.get(B + RL + ".csv?" + ALL).status_code == 404 and A.get(B + RL + ".zip?" + ALL).status_code == 404, "export switched off: CSV / ZIP 404")
check(get(A, ALL)["total"]["count"] == 6, "export switched off: the list stays")
A.put(B + O + "/settings", json={"features_off": []})
check(A.get(B + RL + ".csv?" + ALL).ok, "export on again")

print(f"p2110_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
