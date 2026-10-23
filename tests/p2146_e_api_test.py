#!/usr/bin/env python3
"""2.146.0 API tests, part E (#2456 #2457), own container (start.sh). Invented companies, people and files only (made here).
tenant-matrix: office, contacts
freelancer-matrix: office, contacts
 - #2456 legacy import: a client sheet with the address in separate columns (Firma | Straße | Hausnummer | PLZ | Ort | Land) is
   found from the header (mode columns): street + house number, postcode, city, country (name or code; a 5-digit postcode
   without a country = DE); the import stores the fields; the one-cell address stays as before (mode one); a CSV file
   (semicolon, Windows-1252) is read like a sheet; the person's column choice (form field map) wins, bad indexes are
   left out; an old .xls file and a binary file answer 400 with a clear text; a client already there is a duplicate
 - #2457 contacts: several .vcf files in one request (field files), the same card twice (same UID) = one contact; a file
   that is no vCard is named, the others are imported; a ZIP (Google Takeout) with vCards + a text file + __MACOSX + a
   nested ZIP: only the vCards, the rest skipped; the same ZIP again creates nothing new; a vCard over the size limit in
   the ZIP is an error entry, the others go in; a ZIP without vCards = 400; one .vcf and the CSV preview as before;
   another person's book is refused
 - a person without an organisation: all of it in the personal office / own address book; an organisation's admin too,
   a member 403 on the legacy preview
usage: p2146_e_api_test.py <datadir>      (P2146E_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from xml.sax.saxutils import escape

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,contacts"
L = "/api/office/legacy"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows, table="Services"):
    """One sheet + table Services (str -> shared string, int / float -> number)."""
    strings, sidx = [], {}

    def si(v):
        if v not in sidx:
            sidx[v] = len(strings)
            strings.append(v)
        return sidx[v]
    x = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows, 1):
        x.append(f'<row r="{r}">')
        for ci, v in enumerate(row):
            if v is None or v == "":
                continue
            ref = f"{_col(ci)}{r}"
            x.append(f'<c r="{ref}"><v>{v}</v></c>' if isinstance(v, (int, float)) else f'<c r="{ref}" t="s"><v>{si(v)}</v></c>')
        x.append("</row>")
    width = max(len(r) for r in rows)
    x.append('</sheetData><tableParts count="1"><tablePart xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdT1"/></tableParts></worksheet>')
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
                   '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        f.writestr("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        f.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{rel}">'
                   f'<sheets><sheet name="{table}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        f.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
                   f'<Relationship Id="rIdS" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
        f.writestr("xl/worksheets/sheet1.xml", "".join(x))
        f.writestr("xl/worksheets/_rels/sheet1.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rIdT1" Type="{rel}/table" Target="../tables/table1.xml"/></Relationships>')
        f.writestr("xl/tables/table1.xml", f'<?xml version="1.0" encoding="UTF-8"?><table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   f'id="1" name="{table}" displayName="{table}" ref="A1:{_col(width - 1)}{len(rows)}"/>')
        f.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + "</sst>")
    return z.getvalue()



def preview(s, name, data, amap=None, ctype=XLSX):
    return s.post(B + L + "/preview", files={"file": (name, data, ctype)}, data={"map": json.dumps(amap)} if amap is not None else {})


def clients(s):
    return {c["name"]: c for c in s.get(B + "/api/clients").json()["clients"] if not c.get("archived")}


def card(uid, fn, email=""):
    return (f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{fn}\r\nN:{fn.split()[-1]};{fn.split()[0]};;;\r\n"
            + (f"EMAIL:{email}\r\n" if email else "") + "END:VCARD\r\n")


def zipped(entries):
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for n, d in entries:
            f.writestr(n, d)
    return z.getvalue()


def book(s, name):
    r = s.post(B + "/api/books", json={"name": name, "org_id": None})
    assert r.ok, r.text
    return r.json()["id"]


def total(s, bid):
    return s.get(B + "/api/contacts", params={"book_id": bid, "limit": 500}).json()["total"]


def fns(s, bid):
    return sorted(c["fn"] for c in s.get(B + "/api/contacts", params={"book_id": bid, "limit": 500}).json()["items"])


# ---------------------------------------------------------------- setup
if not (os.environ.get("P2146E_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office, contacts (the personal office, its own admin; its own address book)

# ================================================================ #2456 address columns
COLS = make_xlsx([["Firma", "Ansprechpartner", "Straße", "Hausnummer", "PLZ", "Ort", "Land"],
                  ["Beispiel Film GmbH", "Erika Muster", "Musterweg", "12", "10115", "Berlin", ""],
                  ["Alpenblick Studio", "", "Bergstraße 3", "", "6020", "Innsbruck", "Österreich"],
                  ["Nordlicht Medien", "", "Hafenkai 1", "", "20457", "Hamburg", "DE"],
                  ["", "", "", "", "", "", ""],
                  ["Ohne Adresse AG", "", "", "", "", "", "Atlantis"]], table="Kunden")
for who, s in (("freelancer", Fr), ("org admin", A)):
    r = preview(s, "kunden.xlsx", COLS)
    check(r.ok, f"{who}: preview of an address-column sheet ({r.status_code} {r.text[:200]})")
    P = r.json() if r.ok else {}
    cl = {c["name"]: c for c in P.get("clients", [])}
    check(P.get("columns", {}).get("mode") == "columns", f"{who}: the columns are found from the header {P.get('columns')}")
    check(P.get("columns", {}).get("head", [])[:3] == ["Firma", "Ansprechpartner", "Straße"], f"{who}: the header as written {P.get('columns')}")
    b = cl.get("Beispiel Film GmbH", {})
    check((b.get("street"), b.get("zip"), b.get("city"), b.get("country"), b.get("contact")) == ("Musterweg 12", "10115", "Berlin", "DE", "Erika Muster"),
          f"{who}: street + house number, postcode, city, DE from the 5-digit postcode, contact {b}")
    check(not b.get("flags"), f"{who}: a complete row has no doubts {b.get('flags')}")
    a = cl.get("Alpenblick Studio", {})
    check((a.get("street"), a.get("zip"), a.get("city"), a.get("country")) == ("Bergstraße 3", "6020", "Innsbruck", "AT") and "foreign" in a.get("flags", []),
          f"{who}: a country name -> code, abroad flagged {a}")
    check(cl.get("Nordlicht Medien", {}).get("country") == "DE", f"{who}: a country code is taken")
    o = cl.get("Ohne Adresse AG", {})
    check({"no_zip", "no_street", "country"} <= set(o.get("flags", [])), f"{who}: missing parts and an unknown country are reasons {o.get('flags')}")
    check(len(cl) == 4, f"{who}: the empty row is left out ({len(cl)})")
    sel = [c for c in P.get("clients", []) if c["name"] != "Ohne Adresse AG"]
    r = s.post(B + L + "/import", json={"clients": sel, "areas": ["clients"]})
    check(r.status_code == 201 and r.json().get("counts", {}).get("clients") == 3, f"{who}: import of the column clients ({r.status_code} {r.text[:200]})")
    k = clients(s).get("Beispiel Film GmbH", {}).get("billing") or {}
    check((k.get("street"), k.get("zip"), k.get("city"), k.get("country")) == ("Musterweg 12", "10115", "Berlin", "DE"), f"{who}: the client has street, postcode, city {k}")
    # the same file again: the stored clients are duplicates
    P2 = preview(s, "kunden.xlsx", COLS).json()
    d = {c["name"]: c for c in P2.get("clients", [])}
    check((d.get("Beispiel Film GmbH", {}).get("dup") or {}).get("kind") == "existing" and d["Beispiel Film GmbH"]["action"] == "skip",
          f"{who}: a client already there is a duplicate {d.get('Beispiel Film GmbH')}")

check(Bo.post(B + L + "/preview", files={"file": ("kunden.xlsx", COLS, XLSX)}).status_code == 403, "rights: a member cannot preview (403)")

# the one-cell address stays as it was
ONE = make_xlsx([["Adresse"], ["Einzel Zelle GmbH\nZellweg 5\n80331 München"]], table="Kontakte")
P = preview(Fr, "alt.xlsx", ONE).json()
c0 = (P.get("clients") or [{}])[0]
check(P.get("columns", {}).get("mode") == "one" and (c0.get("name"), c0.get("street"), c0.get("zip"), c0.get("city")) == ("Einzel Zelle GmbH", "Zellweg 5", "80331", "München"),
      f"the one-cell address is split as before {P.get('columns')} {c0}")

# CSV (semicolon, Windows-1252, a sheet without a sheet name)
CSV = "Firma;Straße;PLZ;Ort\r\nMüller Ton KG;Lindenallee 7;50667;Köln\r\nSchäfer Licht;Hauptstraße 2;01067;Dresden\r\n".encode("cp1252")
r = preview(Fr, "kunden.csv", CSV, ctype="text/csv")
P = r.json() if r.ok else {}
cl = {c["name"]: c for c in P.get("clients", [])}
check(r.ok and P.get("columns", {}).get("mode") == "columns", f"CSV: read like a sheet ({r.status_code} {r.text[:200]})")
check((cl.get("Müller Ton KG", {}).get("street"), cl.get("Müller Ton KG", {}).get("city")) == ("Lindenallee 7", "Köln"), f"CSV: Windows-1252 umlauts {cl.get('Müller Ton KG')}")
check(cl.get("Schäfer Licht", {}).get("zip") == "01067", f"CSV: a postcode keeps its leading zero {cl.get('Schäfer Licht')}")
U8 = "\ufeffcompany,street,zip,city,country\nExample Ltd,1 High Street,EC4M 7RB,London,United Kingdom\n".encode()
cl = {c["name"]: c for c in preview(Fr, "clients.csv", U8, ctype="text/csv").json().get("clients", [])}
check(cl.get("Example Ltd", {}).get("country") == "GB" and cl["Example Ltd"].get("zip") == "EC4M 7RB", f"CSV: English headers, UTF-8 with BOM {cl}")

# the person's column choice
ODD = "K1;K2;K3;K4\r\nWahl Firma;Wahlweg 9;04109;Leipzig\r\n".encode()
P = preview(Fr, "x.csv", ODD, ctype="text/csv").json()
check(P.get("columns", {}).get("mode") == "one", f"unknown headers: the one-cell way as before {P.get('columns')}")
P = preview(Fr, "x.csv", ODD, {"name": 0, "street": 1, "zip": 2, "city": 3, "country": 99, "contact": "1", "address": True}, ctype="text/csv").json()
c0 = (P.get("clients") or [{}])[0]
check(P.get("columns", {}).get("map") == {"name": 0, "street": 1, "zip": 2, "city": 3}, f"the choice is taken, bad indexes left out {P.get('columns')}")
check((c0.get("name"), c0.get("street"), c0.get("zip"), c0.get("city")) == ("Wahl Firma", "Wahlweg 9", "04109", "Leipzig"), f"the chosen columns are read {c0}")
check(preview(Fr, "x.csv", ODD, ctype="text/csv").status_code == 200 and Fr.post(B + L + "/preview", files={"file": ("x.csv", ODD)}, data={"map": "{nope"}).status_code == 400,
      "a broken map = 400")

# .xls and binary files
r = preview(Fr, "alt.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, ctype="application/vnd.ms-excel")
check(r.status_code == 400 and ".xlsx" in r.json().get("error", "") and "CSV" in r.json().get("error", ""), f".xls: a clear message ({r.status_code} {r.text[:200]})")
r = preview(Fr, "bild.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00" + os.urandom(200), ctype="image/png")
check(r.status_code == 400, f"a binary file = 400 ({r.status_code})")
r = preview(Fr, "rechnung.csv", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", ctype="text/csv")
check(r.status_code == 400 and "CSV" in r.json().get("error", ""), f"a PDF named .csv = 400 ({r.status_code})")

# ================================================================ #2457 several vCards / ZIP
for who, s in (("freelancer", Fr), ("org admin", A)):
    BK = book(s, "Import " + who)
    files = [("files", ("a.vcf", card("u-anna", "Anna Beispiel", "anna@example.com").encode(), "text/vcard")),
             ("files", ("b.vcf", card("u-ben", "Ben Beispiel").encode("cp1252"), "text/vcard")),
             ("files", ("a-again.vcf", card("u-anna", "Anna Beispiel", "anna@example.com").encode(), "text/vcard")),
             ("files", ("notes.txt", b"just a note", "text/plain"))]
    r = s.post(B + f"/api/books/{BK}/import", files=files)
    j = r.json() if r.ok else {}
    check(r.ok and total(s, BK) == 2, f"{who}: several .vcf files: the same card twice = one contact ({r.status_code} {r.text[:200]} {total(s, BK)})")
    check(j.get("files", {}).get("files") == 3 and [e["file"] for e in j.get("files", {}).get("errors", [])] == ["notes.txt"],
          f"{who}: the file that is no vCard is named {j.get('files')}")
    ZB = book(s, "Takeout " + who)
    big = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Gross Datei\r\nNOTE:" + "x" * (21 * 1024 * 1024) + "\r\nEND:VCARD\r\n"
    Z = zipped([("Takeout/Contacts/Alle/Carla Beispiel.vcf", card("u-carla", "Carla Beispiel")),
                ("Takeout/Contacts/Alle/Dora Beispiel.VCF", card("u-dora", "Dora Beispiel")),
                ("Takeout/archive_browser.html", "<html></html>"), ("Takeout/readme.txt", "hello"),
                ("__MACOSX/Takeout/._Carla Beispiel.vcf", "junk"), ("Takeout/inner.zip", zipped([("e.vcf", card("u-emil", "Emil Beispiel"))])),
                ("Takeout/huge.vcard", big)])
    r = s.post(B + f"/api/books/{ZB}/import", files={"file": ("takeout.zip", Z, "application/zip")})
    j = r.json() if r.ok else {}
    check(r.ok and fns(s, ZB) == ["Carla Beispiel", "Dora Beispiel"], f"{who}: ZIP: only the vCards ({r.status_code} {r.text[:200]} {fns(s, ZB)})")
    sk = j.get("files", {}).get("skipped", [])
    check(set(sk) == {"archive_browser.html", "readme.txt", "inner.zip"}, f"{who}: ZIP: other files and nested ZIPs skipped, __MACOSX left out {sk}")
    er = j.get("files", {}).get("errors", [])
    check(len(er) == 1 and "huge.vcard" in er[0]["file"] and "MB" in er[0]["error"], f"{who}: ZIP: a vCard over the limit is an error entry {er}")
    r = s.post(B + f"/api/books/{ZB}/import", files={"file": ("takeout.zip", Z, "application/zip")})
    check(r.ok and r.json().get("created") == 0 and total(s, ZB) == 2, f"{who}: the same ZIP again creates nothing new ({r.text[:200]})")
    r = s.post(B + f"/api/books/{ZB}/import", files={"file": ("leer.zip", zipped([("readme.txt", "x")]), "application/zip")})
    check(r.status_code == 400 and r.json().get("error"), f"{who}: a ZIP without vCards = 400 ({r.status_code} {r.text[:200]})")
    r = s.post(B + f"/api/books/{ZB}/import", files=[("files", ("z1.zip", zipped([("f.vcf", card("u-finn", "Finn Beispiel"))]), "application/zip")),
                                                    ("files", ("g.vcf", card("u-gina", "Gina Beispiel").encode(), "text/vcard"))])
    check(r.ok and "Finn Beispiel" in fns(s, ZB) and "Gina Beispiel" in fns(s, ZB), f"{who}: a ZIP and a .vcf together ({r.text[:200]})")
    # one file as before
    r = s.post(B + f"/api/books/{ZB}/import", files={"file": ("h.vcf", card("u-hans", "Hans Beispiel").encode(), "text/vcard")})
    check(r.ok and r.json().get("created") == 1 and "files" not in r.json(), f"one .vcf as before ({r.text[:200]})")
    r = s.post(B + f"/api/books/{ZB}/import", params={"preview": 1}, files={"file": ("c.csv", b"First Name;Last Name;E-mail Address\r\nIda;Beispiel;ida@example.com\r\n", "text/csv")})
    check(r.ok and r.json().get("format") == "csv", f"the CSV preview as before ({r.text[:200]})")
    if who == "freelancer":
        r = Ca.post(B + f"/api/books/{ZB}/import", files=[("files", ("x.vcf", card("u-x", "Xaver Fremd").encode(), "text/vcard")),
                                                         ("files", ("y.vcf", card("u-y", "Yara Fremd").encode(), "text/vcard"))])
        check(r.status_code in (403, 404) and "Xaver Fremd" not in fns(s, ZB), f"another person's book is refused ({r.status_code})")

print(f"p2146_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
