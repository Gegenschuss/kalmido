#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.414.0 (#3502) API tests: the booking archive of past DATEV years (office/bookarch.py), own container (kt.fresh, org
encryption on). Invented companies, accounts and figures only: every DATEV file is written here. freelancer-matrix: office
tenant-matrix: office
 - the check of an upload (two booking batches of two years, account labels, debtors / creditors, a ZIP with a ZIP of the
   receipts: document.xml + PDF) is a preview only: counts per year, the debit = credit control (a line without counter
   account makes it differ), the kinds of the files, receipts linked / without booking / missing; nothing is written
 - the import keeps EVERY line (raw columns by name, texts encrypted at rest), the original files with their SHA-256, the
   receipt image by the GUID of its Beleglink; the debtors become clients by the DATEV import's own run
 - the archive never reaches the EUeR / VAT figures (also: books.py, kpi.py, cashflow.py ... never name its tables)
 - view: years, bookings with every filter, paging, sums of the matches, one booking with all its columns, sums per account,
   the receipt (unchanged, sandboxed), the original file
 - the same file / the same batch content again is recognised (preview + import leave it out)
 - GoBD export: the archive's lines of the period (and the labels), nothing when the period has none
 - undo per run removes rows, files and the DATEV run of its master data (also by the import page's run list)
 - rights: a member 403, another organisation sees nothing / 404, a person without organisation has an archive of its own
 - retention: a year past its 10 years goes with the switch on (counted with it off), younger ones stay
 - performance: a year with 20,000 lines imports, pages, sums and searches within budget
usage: p2414_api_test.py <datadir>"""
import base64
import csv
import hashlib
import io
import os
import subprocess
import time
import uuid
import zipfile

import kt
from kt import B, CT, FAILS, OKS, check, sess
import testclock
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
time.sleep(0.5)
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
BA = O + "/books/archive"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Er = freelancer(B, A, "erin")  # freelancer-matrix: office (the personal office, its own admin)
assert A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4,
                                                     "chart": "SKR03"}}).ok
NOW = testclock.today().year
Y1, Y2, YOLD = NOW - 7, NOW - 6, NOW - 12  # two archived years; YOLD is past its 10 years


def sql(q, args=()):
    return kt.dbx(q, args)


def head(cat, name, ver, fy, frm="", to=""):
    f = ['"EXTF"', "700", str(cat), f'"{name}"', str(ver), "20260101120000000", "", '"RE"', '""', '""', "1234567", "12345", fy, "4", frm, to]
    return ";".join(f + [""] * (31 - len(f)))


def q(v):
    return '"' + str(v).replace('"', '""') + '"' if v != "" else ""


COLS21 = ("Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Kurs", "Konto", "Gegenkonto (ohne BU-Schlüssel)",
          "BU-Schlüssel", "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Buchungstext", "Kostenstelle", "Beleglink")


def extf21(year, rows, bom=True):
    """A booking batch of year: rows = (amount, S/H, account, counter, DDMM, receipt field 1, text, link)."""
    lines = [head(21, "Buchungsstapel", 13, f"{year}0101", f"{year}0101", f"{year}1231"), ";".join(q(c) for c in COLS21)]
    for a, sh, k, g, d, b1, t, ln in rows:
        lines.append(";".join([a, q(sh), q("EUR"), "", k, g, "", d, q(b1), "", q(t), q("KST1"), q(ln)]))
    raw = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    return (b"\xef\xbb\xbf" + raw) if bom else raw


def extf20(year, labels):
    lines = [head(20, "Kontenbeschriftungen", 3, f"{year}0101"), '"Konto";"Kontenbeschriftung";"Sprach-ID"']
    lines += [f'{a};{q(t)};"de-DE"' for a, t in labels]
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def extf16(rows):
    lines = [head(16, "Debitoren/Kreditoren", 5, "20190101"), '"Konto";"Name (Adressatentyp Unternehmen)";"Ort"']
    lines += [f"{a};{q(n)};{q(o)}" for a, n, o in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
G1, G2, G3, G4 = str(uuid.uuid4()).upper(), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def docs_zip(entries, files):
    """The DATEV XML interface: document.xml + files, packed into an outer ZIP (as Kalmido's own DATEV export does)."""
    # review F5: written in Windows-1252 as declared (an umlaut in a file name)
    xml = ('<?xml version="1.0" encoding="windows-1252"?>\n<archive xmlns="http://xml.datev.de/bedi/tps/document/v05.0" version="5.0">\n'
           '  <content>\n' + "".join(f'    <document guid="{g}"><description>Beleg</description>'
                                     f'<extension xsi:type="File" name="{n}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/></document>\n'
                                     for g, n in entries) + "  </content>\n</archive>\n")
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("document.xml", xml.encode("cp1252"))
        for n, data in files:
            z.writestr(n, data)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr(f"Belege_{Y1}.zip", inner.getvalue())
    return outer.getvalue()


def up(s, path, files):
    return s.post(B + path, files=[("file", (n, d, "application/octet-stream")) for n, d in files])


ROWS1 = [("1190,00", "S", "1200", "8400", "1501", "RE-1", "Honorar Beispiel GmbH", f'BEDI "{G1}"'),
         ("-200,00", "S", "4210", "1200", "0102", "M-02", "Miete Februar", ""),  # negative: credit 4210
         ("300,50", "H", "1200", "4930", "2003", "B-7", "Buerobedarf", f"BEDI {G2}"),  # its receipt is missing in the ZIP
         ("50,00", "S", "4970", "", "3112", "K-1", "Nebenkosten ohne Gegenkonto", f'BEDI "{G4}"'),  # no counter account: debit != credit
         ("abc", "S", "1200", "8400", "0101", "X", "kaputt", "")]  # not readable: only in the original file
ROWS2 = [("100,00", "S", "1200", "8400", "1001", "RE-9", "Honorar Zwei", ""),
         ("100,00", "H", "1200", "4930", "1101", "B-9", "Material", ""),
         ("10,00", "S", "1200", "8400", "9999", "D-0", "Ohne lesbares Datum", "")]  # no valid date: kept, day empty
F1, F2 = extf21(Y1, ROWS1), extf21(Y2, ROWS2)
F20 = extf20(Y1, [("1200", "Bank"), ("8400", "Erlöse 19 % USt"), ("4210", "Miete")])
F16 = extf16([("10001", "Archiv Kunde GmbH", "Köln"), ("70001", "Archiv Lieferant KG", "Bonn")])
FZ = docs_zip([(G1, "re1-ä.pdf"), (G2, "lost.pdf"), (G3, "nobooking.pdf"), (G4, "fake.pdf")],
             [("re1-ä.pdf", PDF), ("nobooking.pdf", PDF), ("fake.pdf", b"no receipt at all")])
UPLOAD = [(f"EXTF_Buchungsstapel_{Y1}.csv", F1), (f"EXTF_Buchungsstapel_{Y2}.csv", F2), ("EXTF_Kontenbeschriftungen.csv", F20),
          ("EXTF_Debitoren.csv", F16), ("Belege.zip", FZ), ("notes.txt", b"just a note")]

# ---------------------------------------------------------------- the check: a preview, nothing written
r = A.get(B + BA)
check(r.ok and r.json()["years"] == [] and "tax advisor" in r.json()["note"], "an empty archive with the note " + r.text[:200])
euer0 = A.get(B + O + f"/books/euer?year={Y1}").json()
r = up(A, BA + "/check", UPLOAD)
check(r.ok, "check " + r.text[:300])
j = r.json()
ys = {y["year"]: y for y in j["years"]}
check(sorted(ys) == [Y1, Y2], f"two years {sorted(ys)}")
check(ys[Y1]["bookings"] == 4 and ys[Y1]["bad"] == 1 and ys[Y1]["no_counter"] == 1 and not ys[Y1]["balanced"]
      and ys[Y1]["debit"] == "1740.50" and ys[Y1]["credit"] == "1690.50" and ys[Y1]["lines_debit"] == "1240.00" and ys[Y1]["lines_credit"] == "500.50",
      f"{Y1}: 4 lines, 1 unreadable, the line without counter account breaks debit = credit, the S / H lines apart {ys[Y1]}")
check(ys[Y2]["balanced"] and ys[Y2]["debit"] == ys[Y2]["credit"] == "210.00", f"{Y2}: debit = credit {ys[Y2]}")
kinds = {f["name"]: f["kind"] for f in j["files"]}
check(kinds.get(f"EXTF_Buchungsstapel_{Y1}.csv") == "batch" and kinds.get("EXTF_Kontenbeschriftungen.csv") == "labels"
      and kinds.get("EXTF_Debitoren.csv") == "master" and kinds.get("document.xml") == "docs" and kinds.get("notes.txt") == "unknown",
      f"the kinds of the files {kinds}")
c = j["counts"]
check(c["docs"] == 2 and c["docs_no_booking"] == 1 and c["docs_missing"] == 1 and j["docs_missing"] == ["lost.pdf"]
      and j["docs_no_booking"] == ["nobooking.pdf"], f"receipts: 2 linked (a Windows-1252 document.xml), 1 without booking, 1 missing {c} {j['docs_missing']}")
check(j["ok"] and c["bookings"] == 7 and c["labels"] == 3 and c["masters"] == 1, f"counts {c}")
check(not sql("SELECT 1 FROM office_bookarch") and not sql("SELECT 1 FROM office_bookarch_files")
      and not sql("SELECT 1 FROM office_import_runs WHERE kind='datev_archive'"), "the check writes nothing")

# ---------------------------------------------------------------- the import
nclients = len(A.get(B + "/api/clients").json()["clients"])
r = up(A, BA + "/import", UPLOAD)
check(r.status_code == 201, "import " + r.text[:300])
RUN = r.json().get("run_id")
check(r.json().get("counts", {}).get("bookings") == 7 and r.json()["counts"].get("docs") == 1 and r.json()["counts"].get("docs_skipped") == 1
      and r.json().get("docs_skipped") == ["fake.pdf"], f"import counts: a receipt that is no PDF / picture is left out and named {r.json()}")
rows = sql("SELECT year, line, account, counter, side, amount, text, raw, doc1, link FROM office_bookarch WHERE org_id=? ORDER BY year, line", (ORG,))
check(len(rows) == 7, f"7 lines kept {len(rows)}")
check([tuple(x) for x in sql("SELECT day FROM office_bookarch WHERE org_id=? AND year=? AND line=5", (ORG, Y2))] == [("",)],
      "a line without a valid date is kept (day empty)")
check(all(str(x[6]).startswith("kenc1:") and str(x[7]).startswith("kenc1:") and str(x[8]).startswith("kenc1:") for x in rows),
      "text, raw and receipt field encrypted at rest")
neg = [x for x in rows if x[2] == "4210"]
check(neg and neg[0][4] == "H" and float(neg[0][5]) == 200, f"a negative amount: the other side, positive {neg}")
check(any(x[9] == G1.lower() for x in rows), "the GUID of the Beleglink in lower case")
files = sql("SELECT kind, year, sha256, file, nrows FROM office_bookarch_files WHERE org_id=? ORDER BY id", (ORG,))
fk = sorted(x[0] for x in files)
check(fk == ["batch", "batch", "docs", "labels", "master"], f"the original files kept {fk}")
check(any(x[2] == hashlib.sha256(F1).hexdigest() for x in files), "the SHA-256 of the original batch")
check(all(str(x[0]).startswith("kenc1:") for x in sql("SELECT file_name FROM office_bookarch_files WHERE org_id=? "
                                                      "UNION ALL SELECT file_name FROM office_bookarch_docs WHERE org_id=?", (ORG, ORG))),
      "review F8: the names of the original files / receipts encrypted at rest")
docs = sql("SELECT guid, mime, year FROM office_bookarch_docs WHERE org_id=?", (ORG,))
check(docs == [(G1.lower(), "application/pdf", Y1)] or [tuple(d) for d in docs] == [(G1.lower(), "application/pdf", Y1)], f"the receipt image {docs}")
cl = {(x.get("customer_no") or (x.get("billing") or {}).get("customer_no")): x for x in A.get(B + "/api/clients").json()["clients"]}
check("10001" in cl and len(cl) >= nclients + 1, "the debtor became a client (the DATEV import's run)")
mr = sql("SELECT id FROM office_import_runs WHERE org_id=? AND kind='datev' AND undone_at IS NULL", (ORG,))
check(len(mr) == 1, f"one DATEV run of the master data {mr}")

# never in the EUeR / VAT figures
euer1 = A.get(B + O + f"/books/euer?year={Y1}").json()
check({k: v for k, v in euer1.items() if "at" not in k} == {k: v for k, v in euer0.items() if "at" not in k},
      "the EUeR of an archived year is unchanged by the archive")
for f in ("books.py", "kpi.py", "cashflow.py", "bkexport.py", "datev.py", "taxdates.py", "cfbank.py", "homecur.py"):
    p = os.path.join(ROOT, "kalmido", "office", f)
    if os.path.exists(p):
        check("office_bookarch" not in open(p, encoding="utf-8").read(), f"office/{f} never reads the booking archive")

# ---------------------------------------------------------------- the view
ov = A.get(B + BA).json()
check(ov["runs"] and {f["name"] for f in ov["runs"][0]["files"]} >= {"document.xml", f"EXTF_Buchungsstapel_{Y1}.csv"},
      "the file names readable in the view (decrypted)")
check([y["year"] for y in ov["years"]] == [Y2, Y1] and ov["years"][1]["docs"] == 1 and ov["years"][1]["keep_until"] == f"{Y1 + 10}-12-31",
      f"years, newest first, with receipts and the end of keeping {ov['years']}")
check(ov["runs"] and ov["runs"][0]["id"] == RUN and len(ov["runs"][0]["files"]) == 5 and ov["runs"][0]["user_name"] == "Alice Admin",
      f"the run with its files {ov['runs'][:1]}")


def bk(s, **p):
    return s.get(B + BA + "/bookings", params={"year": Y1, **p})


j = bk(A).json()
check(j["total"] == 4 and j["debit"] == "1240.00" and j["credit"] == "500.50", f"all lines of {Y1} with the sums of the matches {j['total']} {j['debit']} {j['credit']}")
it = {x["doc1"]: x for x in j["items"]}
check(it["RE-1"]["account_label"] == "Bank" and it["RE-1"]["counter_label"] == "Erlöse 19 % USt" and it["RE-1"]["doc_id"]
      and it["RE-1"]["day"] == f"{Y1}-01-15", f"labels, receipt, date of the line {it.get('RE-1')}")
check([x["doc1"] for x in j["items"]] == ["RE-1", "M-02", "B-7", "K-1"], "sorted by day")
check(bk(A, account="1200").json()["total"] == 2 and bk(A, counter="1200").json()["total"] == 1 and bk(A, any="1200").json()["total"] == 3,
      "filter account / counter account / either side")
check(bk(A, **{"from": f"{Y1}-02-01", "to": f"{Y1}-03-31"}).json()["total"] == 2, "filter period")
check(bk(A, min="250", max="1000,00").json()["total"] == 1, "filter amount")
check(bk(A, doc="re-").json()["total"] == 1 and bk(A, q="miete").json()["total"] == 1 and bk(A, q="beispiel").json()["total"] == 1,
      "filter receipt field and text (encrypted, case-insensitive)")
check(bk(A, q="nichts-da").json()["total"] == 0, "a text no line has")
p = bk(A, limit=2, offset=2).json()
check(p["total"] == 4 and [x["doc1"] for x in p["items"]] == ["B-7", "K-1"], "paging")
check(bk(A, year="abc").status_code == 400 and A.get(B + BA + "/bookings").status_code == 400, "a year is needed")
one = A.get(B + BA + f"/bookings/{it['RE-1']['id']}").json()
check(one["raw"].get("Buchungstext") == "Honorar Beispiel GmbH" and one["raw"].get("Kostenstelle") == "KST1" and one["year"] == Y1,
      f"one booking with every column of its line {one.get('raw')}")
acc = {x["account"]: x for x in A.get(B + BA + "/accounts", params={"year": Y1}).json()["items"]}
check(acc["1200"]["debit"] == "1390.00" and acc["1200"]["credit"] == "300.50" and acc["1200"]["balance"] == "1089.50"
      and acc["1200"]["side"] == "S" and acc["1200"]["count"] == 3 and acc["1200"]["label"] == "Bank",
      f"sums of account 1200: its lines and those with it as counter account {acc.get('1200')}")
check(acc["4210"]["credit"] == "200.00" and acc["4210"]["debit"] == "0.00" and acc["4210"]["label"] == "Miete",
      f"the negative line on the credit side {acc.get('4210')}")
d = A.get(B + BA + f"/docs/{it['RE-1']['doc_id']}")
check(d.ok and d.content == PDF and "sandbox" in d.headers.get("Content-Security-Policy", "") and d.headers.get("Content-Type", "").startswith("application/pdf"),
      "the receipt unchanged, sandboxed")
fid = ov["runs"][0]["files"][0]["id"]
f = A.get(B + BA + f"/files/{fid}")
check(f.ok and f.content in (F1, F2, F20, F16) and "attachment" in f.headers.get("Content-Disposition", ""), "an original file unchanged (download)")

# ---------------------------------------------------------------- the same again
BIG16 = extf16([(str(10000 + i), f"Firma {i}", "Ort") for i in range(20001)])  # over the DATEV import's 20,000 rows
r = up(A, BA + "/check", [("again.csv", F1), ("nobom.csv", extf21(Y2, ROWS2, bom=False)), ("other.xml", b"<root><x/></root>"),
                          ("big16.csv", BIG16)])
j = r.json()
check(r.ok and [f["kind"] for f in j["files"]] == ["duplicate", "duplicate", "unknown", "unknown"] and not j["ok"] and j["counts"]["duplicates"] == 2,
      f"the same file and the same batch content (other bytes) are recognised; an XML without documents and a master data file "
      f"over the limits are unknown files, not a refused upload (review F10, F3) {j.get('files')}")
r = up(A, BA + "/import", [("again.csv", F1)])
check(r.status_code == 400 and sql("SELECT COUNT(*) FROM office_bookarch WHERE org_id=?", (ORG,))[0][0] == 7, "nothing is taken twice")

# ---------------------------------------------------------------- GoBD export: the archive's lines of the period
r = A.get(B + O + "/gobd/export", params={"from": f"{Y1}-01-01", "to": f"{Y2}-12-31"})
check(r.ok, "GoBD export " + str(r.status_code))
z = zipfile.ZipFile(io.BytesIO(r.content))
names = z.namelist()
check("archive_bookings.csv" in names and b"archive_bookings.csv" in z.read("index.xml") and "archive_accounts.csv" in names,
      f"the archive in the GoBD export {names}")
if "archive_bookings.csv" in names:
    lines = list(csv.reader(io.StringIO(z.read("archive_bookings.csv").decode("utf-8"), newline=""), delimiter=";"))
    check(len(lines) == 7 and any("Honorar Beispiel GmbH" in x for x in lines) and any("1.190,00" in x or "1190,00" in x for x in lines)
          and any("Ohne lesbares Datum" in x for x in lines), f"its lines (also the one without date, review F7), decrypted, decimal comma {lines[:2]}")
r = A.get(B + O + "/gobd/export", params={"from": f"{NOW - 1}-01-01", "to": f"{NOW - 1}-12-31"})
check(r.ok and "archive_bookings.csv" not in zipfile.ZipFile(io.BytesIO(r.content)).namelist(), "a period without archive lines: no table")

# ---------------------------------------------------------------- rights and the boundary
for path in (BA, BA + f"/bookings?year={Y1}", BA + f"/accounts?year={Y1}"):
    check(Bo.get(B + path).status_code == 403, f"a member: 403 {path}")
check(up(Bo, BA + "/check", [("a.csv", F2)]).status_code == 403, "a member cannot import")
check(Ca.get(B + BA).json()["years"] == [] and Ca.get(B + BA + "/bookings", params={"year": Y1}).json()["total"] == 0,
      "another organisation sees no year and no line")
for path in (f"/bookings/{it['RE-1']['id']}", f"/docs/{it['RE-1']['doc_id']}", f"/files/{fid}"):
    check(Ca.get(B + BA + path).status_code == 404, f"another organisation: 404 {path}")
check(Ca.post(B + BA + f"/runs/{RUN}/undo").status_code == 404, "another organisation cannot undo the run")
r = up(Er, BA + "/import", [("own.csv", extf21(Y2, [("42,00", "S", "1000", "8400", "0505", "E-1", "Eigenes", "")]))])
check(r.status_code == 201, "freelancer: imports into the personal office " + r.text[:200])
ej = Er.get(B + BA + "/bookings", params={"year": Y2}).json()
check(ej["total"] == 1 and ej["items"][0]["text"] == "Eigenes", "freelancer: sees its own line only")
check(A.get(B + BA + "/bookings", params={"year": Y2}).json()["total"] == 3, "Alpha does not see the freelancer's line")
ERUN = r.json().get("run_id")
check(Er.post(B + BA + f"/runs/{RUN}/undo").status_code == 404, "freelancer: 404 on Alpha's run")

# ---------------------------------------------------------------- retention: 10 years after the end of the year
r = up(A, BA + "/import", [("old.csv", extf21(YOLD, [("10,00", "S", "1200", "8400", "0101", "O-1", "Uralt", "")]))])
check(r.status_code == 201, "an old year " + r.text[:200])
OLDRUN = r.json().get("run_id")
OLDFILE = sql("SELECT file FROM office_bookarch_files WHERE run_id=?", (OLDRUN,))[0][0]


def box(code, on=False):
    e = ["-e", "KALMIDO_PURGE_TRASH=1"] if on else []
    out = subprocess.run(["docker", "exec", *e, CT, "python", "-c", "import app\nc = app.connect()\ntry:\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "finally:\n    c.close()"], capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-800:]}")
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""


TICK = "from kalmido.office.bookarch import ba_retention_tick\nprint(ba_retention_tick(c, force=True))"
box(TICK)
check(sql("SELECT COUNT(*) FROM office_bookarch WHERE year=?", (YOLD,))[0][0] == 1, "switch off: the old year stays (counted)")
last = sql("SELECT value FROM settings WHERE key='ret_last_trash.bookarch'")
check(last and '"archive_bookings": 1' in last[0][0] and '"purged": false' in last[0][0], f"the dry run is reported {last}")
box(TICK, on=True)
check(sql("SELECT COUNT(*) FROM office_bookarch WHERE year=?", (YOLD,))[0][0] == 0 and not sql("SELECT 1 FROM office_bookarch_files WHERE run_id=?", (OLDRUN,)),
      "switch on: the year past its 10 years goes with its original file")
ls = box(f"import os\nfrom kalmido.core.config import OFFICE_DIR\nprint(' '.join(os.listdir(os.path.join(OFFICE_DIR, '{ORG}'))))")
check(OLDFILE not in ls and "bka-" in ls, f"the old file is gone from the disk, the others stay {OLDFILE}")
check(sql("SELECT COUNT(*) FROM office_bookarch WHERE org_id=?", (ORG,))[0][0] == 7, "the younger years stay")

# ---------------------------------------------------------------- undo
r = A.post(B + BA + f"/runs/{RUN}/undo")
check(r.ok and r.json()["removed"]["bookings"] == 7 and r.json()["removed"]["docs"] == 1 and r.json()["removed"]["master"] == 1,
      "undo: lines, receipt and the DATEV run of the master data " + r.text[:300])
check(not sql("SELECT 1 FROM office_bookarch WHERE run_id=?", (RUN,)) and not sql("SELECT 1 FROM office_bookarch_files WHERE run_id=?", (RUN,)),
      "undo: nothing of the run is left")
check(A.get(B + BA + f"/files/{fid}").status_code == 404 and A.get(B + BA + f"/docs/{it['RE-1']['doc_id']}").status_code == 404, "undo: files 404")
check("10001" not in {x.get("customer_no") or (x.get("billing") or {}).get("customer_no") for x in A.get(B + "/api/clients").json()["clients"]},
      "undo: the client of the master data is gone")
check(A.post(B + BA + f"/runs/{RUN}/undo").status_code == 409, "a second undo 409")
runs = {x["id"]: x for x in A.get(B + O + "/legacy/runs").json()["runs"]}
check(runs.get(RUN, {}).get("kind") == "datev_archive" and runs[RUN]["undone_at"], "the import page lists the run as undone")
r = Er.post(B + O + f"/legacy/runs/{ERUN}/undo")  # the import page's undo hands the kind over
check(r.ok and not sql("SELECT 1 FROM office_bookarch WHERE run_id=?", (ERUN,)), "the undo of the import page works for an archive run " + r.text[:200])
r = up(A, BA + "/import", [("again.csv", F1)])
check(r.status_code == 201, "after the undo the same file can come in again")

# ---------------------------------------------------------------- performance: one year with 20,000 lines
YP = NOW - 3
big = [(f"{(i % 997) + 1},{i % 100:02d}", "S" if i % 2 else "H", str(1200 + i % 40), str(8400 + i % 7), f"{(i % 28) + 1:02d}{(i % 12) + 1:02d}",
        f"P-{i}", f"Buchung Nummer {i}", "") for i in range(20000)]
FB = extf21(YP, big)
t0 = time.time()
r = up(A, BA + "/import", [("big.csv", FB)])
ti = time.time() - t0
check(r.status_code == 201 and r.json()["counts"]["bookings"] == 20000, "20,000 lines imported " + r.text[:200])
check(ti < 120, f"import of 20,000 lines within 120 s ({ti:.1f} s)")
t0 = time.time()
j = A.get(B + BA + "/bookings", params={"year": YP, "limit": 200, "offset": 10000}).json()
tl = time.time() - t0
check(j["total"] == 20000 and len(j["items"]) == 200 and tl < 5, f"a page in the middle within 5 s ({tl:.2f} s)")
t0 = time.time()
n = len(A.get(B + BA + "/accounts", params={"year": YP}).json()["items"])
ta = time.time() - t0
check(n == 47 and ta < 5, f"the sums per account within 5 s ({n} accounts, {ta:.2f} s)")
t0 = time.time()
j = A.get(B + BA + "/bookings", params={"year": YP, "q": "nummer 1999"}).json()
tq = time.time() - t0
check(j["total"] == 11 and tq < 15, f"a text search over the encrypted lines within 15 s ({j['total']} hits, {tq:.2f} s)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
raise SystemExit(1 if FAILS else 0)
