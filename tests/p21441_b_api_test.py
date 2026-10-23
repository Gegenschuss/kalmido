#!/usr/bin/env python3
"""2.144.1 API tests, part B (#2450, office: several bank statements or a ZIP in one import), own container (start.sh, org
encryption on). Invented companies, accounts and figures only (statements made here). freelancer-matrix: office  tenant-matrix: office
 - a person without organisation (personal office, its own admin): a ZIP with three CAMT.053 files (one with a balance) ->
   one preview sorted by day, entries with a path show only their name, .exe / .pdf / a nested ZIP skipped, the packing
   system's hidden files ignored, nothing written anywhere; the import is one row (one undo step), undo takes every booking
   back, restore brings them back; several files without a ZIP; a booking in two files counts once, two equal bookings of one
   file stay two; CSV files with different columns refused, equal ones share the mapping (CAMT + CSV mixed); MT940 refused
   with a clear message; a DOCTYPE in a ZIP refused (the other files go), an encrypted entry named; limits: an entry
   unpacked beyond 2 MB, too many entries, too many files -> 400, the server keeps answering; the JSON way {text} unchanged
 - an organisation: bookings encrypted at rest; a member without the admin role 403, an agent 403, another organisation 404
   on a foreign import and sees none of its bookings
usage: p21441_b_api_test.py <datadir>"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
K = O + "/bank"
IBAN1, IBAN2 = "DE02120300000000202051", "DE89370400440532013000"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def enc(v):
    return str(v or "").startswith("kenc1:")


if not (os.environ.get("P21441B_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
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
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)

TODAY = testclock.today()
P0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of the month before: every day used lies in the past


def d(n):
    return (P0 + timedelta(days=n - 1)).isoformat()


def de(day):
    return f"{day[8:10]}.{day[5:7]}.{day[:4]}"


def ntry(amt, ind, day, ref, name):
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt>'
            f'<AcctSvcrRef>{ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>{name}</Nm></Pty></Dbtr></RltdPties>'
            f'<RmtInf><Ustrd>Zahlung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def camt(acct, entries, bals=()):
    b = "".join(f'<Bal><Tp><CdOrPrtry><Cd>{cd}</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>'
                for cd, amt, ind, day in bals)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>STMT-{acct[-4:]}</Id>
<Acct><Id><IBAN>{acct}</IBAN></Id><Ccy>EUR</Ccy></Acct>{b}{''.join(entries)}</Stmt></BkToCstmrStmt></Document>"""


def zipped(entries, method=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", method) as z:
        for name, data in entries:
            if name.endswith("/"):
                z.writestr(name, "")  # a folder entry
            else:
                z.writestr(zipfile.ZipInfo(name), data, compress_type=method)  # the name as it is (a path, "../")
    return b.getvalue()


def up(s, path, files, **form):
    """multipart: files = [(name, bytes|str)]"""
    fl = [("files", (n, v.encode() if isinstance(v, str) else v, "application/octet-stream")) for n, v in files]
    return s.post(B + K + path, files=fl, data=form)


def all_tx(s):
    return s.get(B + K + "/tx?state=all").json().get("items") or []


# three daily statements (one with its closing balance), packed with a few things that are no statement
X1 = camt(IBAN1, [ntry("120.00", "CRDT", d(5), "R-501", "Kunde Fuenf")])
X2 = camt(IBAN1, [ntry("80.00", "CRDT", d(3), "R-301", "Kunde Drei"), ntry("3.50", "DBIT", d(3), "K-301", "Cafe Beispiel")],
          bals=[("CLBD", "1500.00", "CRDT", d(3))])
X3 = camt(IBAN1, [ntry("40.00", "DBIT", d(4), "K-401", "Laden Beispiel")])
Z = zipped([("auszuege/", ""), ("auszuege/tag5.XML", X1), ("auszuege/tag3.xml", X2), ("../../tag4.xml", X3), ("__MACOSX/auszuege/._tag5.XML", "junk"),
            ("auszuege/._tag3.xml", "junk"), ("tool.exe", "MZ"), ("brief.pdf", "%PDF-1.4"), ("inner.zip", zipped([("a.xml", X1)]))])

# ---------------------------------------------------------------- the personal office: a ZIP
check(Fr.get(B + O + "/settings").json().get("role") == "admin", "personal office: the person is its admin")
r = up(Fr, "/import/preview", [("auszuege.zip", Z)])
check(r.ok, "zip preview " + r.text[:300])
p = r.json()
days = [x["day"] for x in p.get("rows") or []]
check(p.get("fmt") == "camt" and p.get("files") == 3 and len(days) == 4 and days == sorted(days) and days[0] == d(3) and days[-1] == d(5),
      f"one preview of three files sorted by day {p.get('fmt')} {p.get('files')} {days}")
check(p.get("count") == 4 and p.get("dup_count") == 0, f"four new {p.get('count')} {p.get('dup_count')}")
check(sorted(p.get("skipped_files") or []) == ["brief.pdf", "inner.zip", "tool.exe"], f"exe, pdf and a nested zip skipped, hidden files ignored {p.get('skipped_files')}")
check({x["file"] for x in p["rows"]} == {"tag5.XML", "tag3.xml", "tag4.xml"} and not any("/" in x["file"] or ".." in x["file"] for x in p["rows"]),
      f"only the file names are shown {sorted({x['file'] for x in p['rows']})}")
check([b for b in p.get("balances") or [] if b["kind"] == "close"] == [{"account": IBAN1, "day": d(3), "amount": "1500.00", "kind": "close"}], f"the balance of the file that has one {p.get('balances')}")
r = up(Fr, "/import", [("auszuege.zip", Z)])
check(r.status_code == 201 and r.json()["count"] == 4 and r.json()["balances"] == 1, "zip import " + r.text[:300])
IZ = r.json()["import"]["id"] if r.status_code == 201 else 0
imps = Fr.get(B + K + "/imports").json()["items"]
check(len(imps) == 1 and imps[0]["filename"] == "auszuege.zip (3 files)" and imps[0]["count"] == 4, f"one import row {imps}")
check(len(all_tx(Fr)) == 4, "four bookings")
check(not any(f in ("tag4.xml", "tag5.XML", "tool.exe", "inner.zip") for _r, _d, fs in os.walk(DATA) for f in fs), "nothing unpacked into the data folder")
r = up(Fr, "/import/preview", [("auszuege.zip", Z)])
check(r.ok and r.json()["count"] == 0 and r.json()["dup_count"] == 4, "the same zip again: all already there")
r = Fr.post(B + K + f"/imports/{IZ}/undo")
check(r.ok and all_tx(Fr) == [], "one undo takes every booking of the zip back " + r.text[:200])
r = Fr.post(B + K + f"/imports/{IZ}/restore")
check(r.ok and len(all_tx(Fr)) == 4, "restore brings them back " + r.text[:200])

# several files without a ZIP; a booking in a day and a month statement counts once, two equal coffees in one file stay two
DAY = camt(IBAN2, [ntry("250.00", "CRDT", d(10), "R-1001", "Kunde Zehn")])
MON = camt(IBAN2, [ntry("250.00", "CRDT", d(10), "R-1001", "Kunde Zehn"), ntry("2.80", "DBIT", d(11), "", "Kaffee Beispiel"),
                   ntry("2.80", "DBIT", d(11), "", "Kaffee Beispiel")], bals=[("CLBD", "900.00", "CRDT", d(11))])
r = up(Fr, "/import/preview", [("tag10.xml", DAY), ("monat.xml", MON)])
p = r.json()
check(r.ok and p["files"] == 2 and p["count"] == 3 and p["dup_count"] == 1, f"two files: the shared booking once, both coffees {r.text[:300]}")
check(r.ok and [x["day"] for x in p["rows"]] == [d(10), d(10), d(11), d(11)] and [x["file"] for x in p["rows"]][:2] == ["tag10.xml", "monat.xml"], "sorted: day, then file")
r = up(Fr, "/import", [("tag10.xml", DAY), ("monat.xml", MON)])
check(r.status_code == 201 and r.json()["count"] == 3 and r.json()["import"]["filename"] == "2 files: tag10.xml, monat.xml", "two files imported " + r.text[:300])
check(sum(1 for t in all_tx(Fr) if t.get("amount") == "-2.80") == 2, "two equal coffees of one file are two bookings")
r = up(Fr, "/import/preview", [("monat.xml", MON)])
check(r.ok and r.json()["count"] == 0 and r.json()["dup_count"] == 3, "the month statement again: all three there")

# CSV: equal columns share the mapping (with a CAMT file: mixed), different columns refused
HD = "Buchungstag;Name;Verwendungszweck;Betrag\n"
CS1 = HD + f"{de(d(14))};Laden Eins;Einkauf;-12,00\n"
CS2 = HD + f"{de(d(12))};Laden Zwei;Einkauf;-7,50\n"
X14 = camt(IBAN2, [ntry("60.00", "CRDT", d(13), "R-1301", "Kunde Dreizehn")])
r = up(Fr, "/import/preview", [("a.csv", CS1), ("b.csv", CS2), ("c.xml", X14)])
p = r.json()
check(r.ok and p.get("columns") == ["Buchungstag", "Name", "Verwendungszweck", "Betrag"] and p.get("files") == 3, "CSV without a mapping: the columns of the first file " + r.text[:300])
MAP = {"date": 0, "amount": 3, "title": 2, "counterpart": 1, "decimal": ",", "date_format": "DD.MM.YYYY"}
r = up(Fr, "/import/preview", [("a.csv", CS1), ("b.csv", CS2), ("c.xml", X14)], mapping=json.dumps(MAP))
p = r.json()
check(r.ok and p.get("fmt") == "mixed" and [x["day"] for x in p["rows"]] == [d(12), d(13), d(14)] and p["count"] == 3, "the mapping holds for every CSV, CAMT mixed in " + r.text[:300])
r = up(Fr, "/import", [("a.csv", CS1), ("b.csv", CS2), ("c.xml", X14)])
check(r.status_code == 400, "import of CSV files without a mapping: 400")
r = up(Fr, "/import", [("a.csv", CS1), ("b.csv", CS2), ("c.xml", X14)], mapping=json.dumps(MAP))
check(r.status_code == 201 and r.json()["import"]["fmt"] == "mixed" and r.json()["count"] == 3, "mixed import " + r.text[:300])
r = up(Fr, "/import/preview", [("a.csv", CS1), ("x.csv", "Datum;Betrag;Text\n01.01.2026;1,00;x\n")])
check(r.status_code == 400 and "different columns" in r.text, "CSV files with different columns: 400 " + r.text[:200])

# MT940, DOCTYPE, an encrypted entry
MT = ":20:STARTUMS\n:25:12030000/0000202051\n:28C:1/1\n:60F:C261001EUR100,00\n:61:2610011001CR10,00NTRFNONREF\n:62F:C261001EUR110,00\n"
r = up(Fr, "/import/preview", [("konto.sta", MT)])
check(r.status_code == 400 and "MT940" in r.text and "CAMT.053" in r.text, "MT940: a clear message " + r.text[:200])
r = Fr.post(B + K + "/import/preview", json={"text": MT, "filename": "konto.txt"})
check(r.status_code == 400 and "MT940" in r.text, "MT940 on the JSON way too " + r.text[:200])
EVIL = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x "y">]>' + X1.split("?>", 1)[1]
r = up(Fr, "/import/preview", [("e.zip", zipped([("evil.xml", EVIL)]))])
check(r.status_code == 400 and "DOCTYPE" in r.text, "a DOCTYPE in a zip is refused " + r.text[:200])
X20 = camt(IBAN2, [ntry("33.00", "CRDT", d(20), "R-2001", "Kunde Zwanzig")])
r = up(Fr, "/import/preview", [("e.zip", zipped([("evil.xml", EVIL), ("gut.xml", X20)]))])
p = r.json()
check(r.ok and p["count"] == 1 and [e["file"] for e in p["file_errors"]] == ["evil.xml"] and "DOCTYPE" in p["file_errors"][0]["error"], "the other file goes, the refused one is named " + r.text[:300])
zb = bytearray(zipped([("geheim.xml", X20)], zipfile.ZIP_STORED))
zb[6] |= 1
zb[zb.find(b"PK\x01\x02") + 8] |= 1
r = up(Fr, "/import/preview", [("g.zip", bytes(zb))])
check(r.status_code == 400 and "encrypted" in r.text, "an encrypted entry: a clear message " + r.text[:200])

# limits (the sizes in the ZIP's header are never trusted)
BIG = X20.replace("</Document>", "<!--" + " " * (3 * 1024 * 1024) + "--></Document>")
zbig = zipped([("gross.xml", BIG)])
check(len(zbig) < 100 * 1024, f"the bomb is small packed ({len(zbig)} bytes)")
r = up(Fr, "/import/preview", [("bombe.zip", zbig)])
check(r.status_code == 400 and "too large" in r.text, "an entry beyond 2 MB unpacked: 400 " + r.text[:200])
r = up(Fr, "/import/preview", [("bombe.zip", zipped([("gross.xml", BIG), ("gut.xml", X20)]))])
check(r.ok and r.json()["count"] == 1 and r.json()["file_errors"][0]["file"] == "gross.xml", "the big one named, the other goes " + r.text[:200])
r = up(Fr, "/import/preview", [("viele.zip", zipped([(f"n{i}.txt", "") for i in range(2001)], zipfile.ZIP_STORED))])
check(r.status_code == 400 and "too many entries" in r.text, "more than 2000 entries: 400 " + r.text[:200])
r = up(Fr, "/import/preview", [("viele.zip", zipped([(f"t{i}.xml", X20) for i in range(401)]))])
check(r.status_code == 400 and "400 files" in r.text, "more than 400 files: 400 " + r.text[:200])
r = up(Fr, "/import/preview", [("kaputt.zip", b"PK\x03\x04 not a zip at all")])
check(r.status_code == 400, "a broken zip: 400 " + r.text[:200])
# 2.144.1 (review): a file picked or dropped directly that is no statement is named, never read as a CSV
r = up(Fr, "/import/preview", [("brief.pdf", b"%PDF-1.4 junk"), ("gut.xml", X20)])
check(r.ok and r.json()["count"] == 1 and any(e["file"] == "brief.pdf" and "Not a bank statement" in e["error"] for e in r.json()["file_errors"]),
      "a direct pdf named as no statement " + r.text[:200])
check(Fr.get(B + K + "/imports").ok, "the server keeps answering")

# the JSON way stays as it was
X25 = camt(IBAN2, [ntry("44.00", "CRDT", d(25), "R-2501", "Kunde Fuenfundzwanzig")])
r = Fr.post(B + K + "/import/preview", json={"text": X25, "filename": "einzeln.xml"})
check(r.ok and r.json()["count"] == 1 and r.json()["fmt"] == "camt", "JSON preview as before " + r.text[:200])
r = Fr.post(B + K + "/import", json={"text": X25, "filename": "einzeln.xml"})
check(r.status_code == 201 and r.json()["import"]["filename"] == "einzeln.xml", "JSON import as before " + r.text[:200])
check(Fr.post(B + K + "/import", json={"text": CS1, "filename": "a.csv"}).status_code == 400, "JSON CSV without a mapping: 400 as before")

# ---------------------------------------------------------------- an organisation: encrypted at rest, rights
r = up(A, "/import", [("alpha.zip", Z)])
check(r.status_code == 201 and r.json()["count"] == 4, "organisation: zip import " + r.text[:200])
IA = r.json()["import"]["id"] if r.status_code == 201 else 0
tx = sql("SELECT amount, counterpart FROM office_bank_tx WHERE import_id=?", (IA,))
check(len(tx) == 4 and all(enc(x[0]) for x in tx) and all(enc(x[1]) for x in tx if x[1]), "bookings encrypted at rest")
check(up(Bo, "/import/preview", [("alpha.zip", Z)]).status_code == 403 and up(Bo, "/import", [("alpha.zip", Z)]).status_code == 403, "a member without the admin role: 403")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "bankbot", "display_name": "Bank Bot"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(x.status_code in (401, 403) for x in (requests.post(B + K + "/import/preview", headers=AG, files=[("files", ("a.zip", Z))]),
                                                 requests.post(B + K + "/import", headers=AG, files=[("files", ("a.zip", Z))]))), "an agent gets 403")
check(Ca.post(B + K + f"/imports/{IA}/undo").status_code == 404, "another organisation: 404 on a foreign import")
r = up(Ca, "/import/preview", [("alpha.zip", Z)])
check(r.ok and r.json()["count"] == 4 and r.json()["dup_count"] == 0 and all_tx(Ca) == [], "another organisation sees none of the bookings")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
