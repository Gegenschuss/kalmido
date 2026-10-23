#!/usr/bin/env python3
"""2.185.0 API tests, part B (#2598), own container (start.sh). Invented companies and files only (the .xls files are written
here by a small BIFF8-in-OLE2 writer, no real documents).
tenant-matrix: office
freelancer-matrix: office
 - #2598 legacy import of an old Excel file (.xls): a contacts sheet gives the same clients as the same rows from a CSV file
   (address columns, umlauts, a postcode stored as text keeps its leading zero, a postcode stored as a number has no ".0");
   a services sheet in the same file: whole and decimal numbers; the import stores the clients; a broken .xls, a
   password-protected .xls and an .xls that is only the file signature answer 400 with a clear text; a text file named
   .xls (tab separated) is read as CSV
 - a person without an organisation (its own admin in the personal office) and an organisation's admin; a member 403
usage: p2185_b_xls_test.py <datadir>      (P2185B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import struct
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,contacts"
L = "/api/office/legacy"
XLS = "application/vnd.ms-excel"


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


# ---------------------------------------------------------------- a minimal .xls writer (BIFF8 workbook in an OLE2 file)
def _rec(op, data=b""):
    return struct.pack("<HH", op, len(data)) + data


def _bof(kind):  # BIFF8 BOF: 0x0005 workbook globals, 0x0010 worksheet
    return _rec(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 0x0006))


def _ustr16(s):  # XLUnicodeString with a 16-bit length, UTF-16LE
    return struct.pack("<HB", len(s), 1) + s.encode("utf-16-le")


def make_xls(sheets, encrypted=False):
    """sheets: [(name, rows)]; a cell is str (shared string), int / float (number), bool or None (empty)."""
    strings, sidx = [], {}
    for _n, rows in sheets:
        for row in rows:
            for v in row:
                if isinstance(v, str) and v not in sidx:
                    sidx[v] = len(strings)
                    strings.append(v)
    sst = _rec(0x00FC, struct.pack("<II", len(strings), len(strings)) + b"".join(_ustr16(s) for s in strings))
    font = _rec(0x0031, struct.pack("<HHHHHBBBB", 200, 0, 0x7FFF, 400, 0, 0, 0, 0, 0) + struct.pack("<BB", 5, 1) + "Arial".encode("utf-16-le"))
    xf = _rec(0x00E0, struct.pack("<HHHBBBBIiH", 0, 0, 0xFFF5, 0x20, 0, 0, 0, 0, 0, 0x20C0))  # style XF
    xf += _rec(0x00E0, struct.pack("<HHHBBBBIiH", 0, 0, 0x0001, 0x20, 0, 0, 0, 0, 0, 0x20C0))  # cell XF, format General
    head = _bof(0x0005) + (_rec(0x002F, struct.pack("<HHH", 1, 1, 1) + b"\x00" * 48) if encrypted else b"") + _rec(0x0042, struct.pack("<H", 1200)) + font + xf

    def boundsheets(offsets):
        return b"".join(_rec(0x0085, struct.pack("<IBB", off, 0, 0) + struct.pack("<BB", len(n), 1) + n.encode("utf-16-le"))
                        for off, (n, _r) in zip(offsets, sheets))
    tail = sst + _rec(0x000A)
    bodies = []
    for _n, rows in sheets:
        width = max((len(r) for r in rows), default=0)
        cells = []
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                if v is None or v == "":
                    continue
                if isinstance(v, bool):
                    cells.append(_rec(0x0205, struct.pack("<HHHBB", r, c, 1, int(v), 0)))
                elif isinstance(v, (int, float)):
                    cells.append(_rec(0x0203, struct.pack("<HHHd", r, c, 1, float(v))))
                else:
                    cells.append(_rec(0x00FD, struct.pack("<HHHI", r, c, 1, sidx[v])))
        bodies.append(_bof(0x0010) + _rec(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, width, 0)) + b"".join(cells) + _rec(0x000A))
    glob_len = len(head) + len(boundsheets([0] * len(sheets))) + len(tail)
    offsets, pos = [], glob_len
    for b in bodies:
        offsets.append(pos)
        pos += len(b)
    stream = head + boundsheets(offsets) + tail + b"".join(bodies)
    return ole2(stream + b"\x00" * max(0, 4096 - len(stream)))  # >= 4096 bytes: regular sectors, no mini stream


def ole2(stream):
    """An OLE2 compound file (version 3, 512-byte sectors) with the one stream "Workbook"."""
    stream += b"\x00" * (-len(stream) % 512)
    n = len(stream) // 512
    assert n + 2 <= 128, "one FAT sector only"
    free, end, fatsect = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
    fat = [i + 1 for i in range(n - 1)] + [end, end, fatsect]
    fat += [free] * (128 - len(fat))

    def entry(name, typ, child, start, size):
        nm = name.encode("utf-16-le") + b"\x00\x00" if name else b""
        return (nm.ljust(64, b"\x00") + struct.pack("<HBB", len(nm), typ, 1 if name else 0) + struct.pack("<III", free, free, child)
                + b"\x00" * 16 + struct.pack("<I", 0) + b"\x00" * 16 + struct.pack("<III", start, size, 0))
    directory = entry("Root Entry", 5, 1, end, 0) + entry("Workbook", 2, free, 0, len(stream)) + entry("", 0, free, 0, 0) * 2
    header = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16 + struct.pack("<HHHHH", 0x003E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
              + struct.pack("<IIIIIIIII", 0, 1, n, 0, 4096, end, 0, end, 0) + struct.pack("<I", n + 1) + struct.pack("<I", free) * 108)
    assert len(header) == 512 and len(directory) == 512
    return header + stream + directory + struct.pack("<128I", *fat)


def preview(s, name, data, ctype=XLS):
    return s.post(B + L + "/preview", files={"file": (name, data, ctype)})


def clients(s):
    return {c["name"]: c for c in s.get(B + "/api/clients").json()["clients"] if not c.get("archived")}


def norm(P):
    return sorted((c["name"], c.get("street"), c.get("zip"), c.get("city"), c.get("country"), c.get("contact"), tuple(c.get("flags") or []))
                  for c in P.get("clients", []))


# ---------------------------------------------------------------- setup
if not (os.environ.get("P2185B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)

# ================================================================ #2598 .xls = the same rows as CSV
ROWS = [["Firma", "Ansprechpartner", "Straße", "PLZ", "Ort", "Land"],
        ["Müller Ton KG", "Erika Muster", "Lindenallee 7", 50667, "Köln", ""],
        ["Schäfer Licht", "", "Hauptstraße 2", "01067", "Dresden", "DE"],
        [None, None, None, None, None, None],
        ["Alpenblick Studio", "", "Bergstraße 3", 6020, "Innsbruck", "Österreich"]]
CSV = "\r\n".join(";".join("" if v is None else str(v) for v in row) for row in ROWS).encode("cp1252") + b"\r\n"
SERV = [["Leistung", "Tagessatz", "Stundensatz", "Kategorie"], ["Kamera", 650, None, "Video"], ["Schnitt", None, 82.5, "Post"]]
X = make_xls([("Kontakte", ROWS), ("Leistungen", SERV)])
check(X.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), "the test file is an OLE2 .xls")
for who, s in (("freelancer", Fr), ("org admin", A)):
    r = preview(s, "kunden.xls", X)
    check(r.ok, f"{who}: preview of an .xls file ({r.status_code} {r.text[:300]})")
    P = r.json() if r.ok else {}
    check({"kontakte", "leistungen"} <= set(P.get("sheets", [])), f"{who}: both sheets are read {P.get('sheets')}")
    check(P.get("columns", {}).get("mode") == "columns" and P["columns"].get("head", [])[:3] == ["Firma", "Ansprechpartner", "Straße"],
          f"{who}: the columns are found from the header {P.get('columns')}")
    Pc = preview(s, "kunden.csv", CSV, ctype="text/csv").json()
    check(norm(P) == norm(Pc) and len(norm(P)) == 3, f"{who}: the .xls gives the same clients as the CSV\n  xls {norm(P)}\n  csv {norm(Pc)}")
    cl = {c["name"]: c for c in P.get("clients", [])}
    check(cl.get("Müller Ton KG", {}).get("zip") == "50667", f"{who}: a postcode stored as a number has no '.0' {cl.get('Müller Ton KG')}")
    check(cl.get("Schäfer Licht", {}).get("zip") == "01067", f"{who}: a postcode stored as text keeps its leading zero {cl.get('Schäfer Licht')}")
    sv = {x["name_de"]: x for x in P.get("services", [])}
    check(sv.get("Kamera", {}).get("daily_rate") == 650 and sv.get("Schnitt", {}).get("hourly_rate") == 82.5 and sv["Schnitt"].get("unit") == "hour",
          f"{who}: the services sheet: whole and decimal numbers {sv}")
    r = s.post(B + L + "/import", json={"clients": P.get("clients", []), "areas": ["clients"]})
    check(r.status_code == 201 and r.json().get("counts", {}).get("clients") == 3, f"{who}: import of the .xls clients ({r.status_code} {r.text[:200]})")
    k = clients(s).get("Müller Ton KG", {}).get("billing") or {}
    check((k.get("street"), k.get("zip"), k.get("city")) == ("Lindenallee 7", "50667", "Köln"), f"{who}: the client is stored {k}")

check(Bo.post(B + L + "/preview", files={"file": ("kunden.xls", X, XLS)}).status_code == 403, "rights: a member cannot preview an .xls (403)")

# broken, protected, only the signature, a text file named .xls
for what, data in (("broken", X[:1500]), ("only the signature", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600),
                   ("garbage after the signature", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + os.urandom(3000))):
    r = preview(Fr, "alt.xls", data)
    e = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
    check(r.status_code == 400 and ".xls" in e and "CSV" in e, f".xls {what}: 400 with a clear text ({r.status_code} {r.text[:200]})")
r = preview(Fr, "geheim.xls", make_xls([("Kontakte", ROWS)], encrypted=True))
e = r.json().get("error", "") if r.status_code == 400 else ""
check(r.status_code == 400 and "password" in e.lower(), f"a password-protected .xls: 400 that names the password ({r.status_code} {r.text[:200]})")
TSV = "\r\n".join("\t".join("" if v is None else str(v) for v in row) for row in ROWS).encode("cp1252") + b"\r\n"
r = preview(Fr, "export.xls", TSV)
P = r.json() if r.ok else {}
check(r.ok and {c["name"] for c in P.get("clients", [])} >= {"Müller Ton KG", "Schäfer Licht"}, f"a text file named .xls is read as CSV ({r.status_code} {r.text[:200]})")

print(f"p2185_b_xls: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
