#!/usr/bin/env python3
"""2.56.1 part A API tests: #1813 the archive import finds the recipient's address of an old PDF on the whole first page:
the recipient behind 45+ lines of positions and totals; the walk up stops at the organisation's own block right above it
(its name on two lines, " ," before the comma, eGbR); the own block with its city in another language ("/ Germany") and a
split BIC above it is no recipient; US ("City ST 12345") and UK ("EC1A 1BB London") postcode lines; amounts are no
postcode lines; a PDF with only the own block = no proposal; review: a client in the own street of another town, a client
named like one word of the own name, quantities ("10000 Stück") are no postcode lines.
Invented companies, people, addresses and bank data only; the PDFs are generated here (a one-page text layer).
usage: p2561_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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


def text_pdf(lines, tag=""):
    """A one-page PDF whose text layer holds lines top to bottom (small type, so 70+ lines fit on the page)."""
    ops, y = [], 830
    for t in lines:
        t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 8 Tf 40 {y} Td ({t}) Tj ET")
        y -= 11
    content = ("\n".join(ops) + f"\n% {tag}").encode("cp1252")  # WinAnsiEncoding: the euro sign too
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


# ---------------------------------------------------------------- setup
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,time", "tour": "done", "workspace": f"org:{ORG}"})
L = "/api/office/legacy"
OWN = {"name": "MUSTERWERK Probe, Beispiel & Muster GbR", "street": "Beispielstraße 12", "zip": "12345", "city": "Musterstadt", "country": "DE"}
r = A.put(B + "/api/office/settings", json={"company": {"name": OWN["name"]}, "lang": "de", "currency": "EUR", "company_fields": OWN, "payment_days": 14})
check(r.ok, "office settings " + r.text[:160])

# the template: a one-line sender on top, 45+ lines of positions / totals / terms, the salutation, then the blocks
HEAD = ["KOSTENVORANSCHLAG KVADE", "MUSTERWERK audiovisual, Beispielstr. 12, D-12345 Musterstadt", "Datum: 01.02.26", "x PREIS % GESAMT"]
POS = [f"{n} 980,00 € {n * 980},00 €" for n in range(1, 31)] + [
    "4.045,00 €", "SUMME NETTO: 21.990,00 €", "inklusive Rohdaten: 26.035,00 €", "Alle Preise zuzüglich 7% bzw. 19% MwSt.",
    "12345 Stück Flyer 0,10 €", "Mediale Auswertung:intern, web, unpaid media", "Im Übrigen gelten unsere AGBs.",
    "Zeitliche Auswertung:unbegrenzt", "Producing", "Optional: Bereitstellung der Rohdaten", "LEISTUNG", "Konzeption / Beratung",
    "Animation 2D / Motion Design", "Sound Design", "Tonschnitt & Mischung"]
SALUTE = ["Sehr geehrte Damen und Herren,", "für das oben genannte Projekt bieten wir Ihnen folgende Leistungen an:"]
OWNBLOCK = ["MUSTERWERK", "Probe , Beispiel & Muster eGbR", "Beispielstraße 12", "12345 Musterstadt"]
VALUES = ["+4940000000000", "hallo@musterwerk.example", "musterwerk.example", "12/345/67890", "DE123456789", "Sparkasse Musterstadt",
          "DE89370400440532013000", "COB ADE33"]
TAIL = ["Angebot Nr.: X-001", "Projekttitel: Beispielfilm"]


def addr(pdf):
    r = A.post(B + L + "/archive/address", files={"file": ("a.pdf", pdf, "application/pdf")}, data={"client_id": ""})
    j = r.json() if r.ok else {}
    return j.get("status"), j.get("address") or {}, j


def got(a):
    return tuple(a.get(k) for k in ("name", "contact", "street", "zip", "city", "country"))


def own_in(a):
    t = (a.get("address") or "").lower()
    return any(x in t for x in ("musterwerk", "beispielstra", "12345"))


# (1) + (2) + (3): recipient after line 45, the own block (name on two lines, " ,", eGbR) right above it
st, a, j = addr(text_pdf(HEAD + POS + SALUTE + OWNBLOCK + ["Kunde Alpha GmbH", "Lea Test", "Hauptweg 9", "54321 Andersstadt", "Deutschland"]
                         + VALUES + TAIL, "t1"))
check(st == "ok" and got(a) == ("Kunde Alpha GmbH", "Lea Test", "Hauptweg 9", "54321", "Andersstadt", "DE") and not own_in(a),
      f"#1813: the recipient behind the positions, without the own block right above it {j}")
check(len(HEAD + POS + SALUTE + OWNBLOCK) > 45, "#1813: the test template puts the recipient after line 45")

# the recipient first, the own block below the bank values (the other variant of the template)
st, a, j = addr(text_pdf(HEAD + POS + SALUTE + ["Kunde Beta KG", "Ben Probe", "Ringweg 3", "54322 Andersdorf", "Angebot Nr.: X-002"]
                         + VALUES + OWNBLOCK, "t2"))
check(st == "ok" and got(a)[:5] == ("Kunde Beta KG", "Ben Probe", "Ringweg 3", "54322", "Andersdorf"), f"#1813: recipient above, own block below {j}")

# (4): the own block with its city in English + "/ Germany" and a split BIC above it comes first; then the UK recipient (5)
st, a, j = addr(text_pdf(HEAD + ["DE89370400440532013000", "COB ADE33", "MUSTERWERK", "Probe , Beispiel & Muster eGbR", "Beispielstraße 12",
                                 "12345 Sampletown / Germany"] + POS + ["Dear Sir/Madam,", "Sample Partners Ltd.", "Mia Example",
                                                                         "10 Sample Road", "EC1A 1BB London", "United Kingdom"] + TAIL, "t3"))
check(st == "ok" and got(a) == ("Sample Partners Ltd.", "Mia Example", "10 Sample Road", "EC1A 1BB", "London", "GB") and not own_in(a),
      f"#1813: own block with an English city name is skipped, a UK postcode line is read {j}")

# (5): a US address "City ST 12345" right below the bank values
st, a, j = addr(text_pdf(HEAD + POS + SALUTE + OWNBLOCK + VALUES + ["Example Corp. Springfield", "100 Sample Avenue", "Springfield IL 62701",
                                                                    "United States"] + TAIL, "t4"))
check(st == "ok" and got(a) == ("Example Corp. Springfield", "", "100 Sample Avenue", "62701", "Springfield, IL", "US") and not own_in(a),
      f"#1813: a US postcode line (city, state, ZIP) {j}")
st, a, j = addr(text_pdf(HEAD + SALUTE + ["Example Labs Inc.", "200 Sample Street", "Austin TX 73301-0001"] + TAIL, "t4b"))
check(st == "ok" and a.get("zip") == "73301-0001" and a.get("country") == "US", f"#1813: a ZIP+4 code {j}")

# a client in the organisation's own town (same postcode) stays a recipient
st, a, j = addr(text_pdf(HEAD + SALUTE + OWNBLOCK + ["Nachbar KG", "Andere Straße 3", "12345 Musterstadt"] + VALUES + TAIL, "t5"))
check(st == "ok" and got(a)[:5] == ("Nachbar KG", "", "Andere Straße 3", "12345", "Musterstadt"), f"#1813: a client in the own town {j}")

# counter tests: only the own block (+ the ", Germany" variant) and positions -> no proposal; amounts are no postcode lines
st, a, j = addr(text_pdf(HEAD + POS + SALUTE + OWNBLOCK + VALUES + ["MUSTERWERK", "Probe , Beispiel & Muster eGbR", "Beispielstraße 12",
                                                                     "12345 Sampletown, Germany"] + TAIL, "t6"))
check(st == "none", f"#1813: a PDF without a foreign address = no proposal {j}")

# review: a client in the own street of another town stays a recipient; a client named like one word of the own name too;
# a quantity of a line item ("10000 Stück Flyer") is no postcode line
st, a, j = addr(text_pdf(HEAD + SALUTE + OWNBLOCK + VALUES + ["Kunde Gamma AG", "Beispielstr. 12", "54333 Fernstadt"] + TAIL, "t8"))
check(st == "ok" and got(a)[:5] == ("Kunde Gamma AG", "", "Beispielstr. 12", "54333", "Fernstadt"), f"#1813: a client in the own street elsewhere {j}")
st, a, j = addr(text_pdf(HEAD + SALUTE + OWNBLOCK + VALUES + ["Beispiel", "Lindenweg 3", "54334 Weitweg"] + TAIL, "t9"))
check(st == "ok" and got(a)[0] == "Beispiel" and got(a)[2:5] == ("Lindenweg 3", "54334", "Weitweg"), f"#1813: a client named like a word of the own name {j}")
st, a, j = addr(text_pdf(HEAD + SALUTE + OWNBLOCK + VALUES + ["Pos Leistung", "10000 Stück Flyer"] + TAIL, "t10"))
check(st == "none", f"#1813: a quantity is no postcode line {j}")

# the own company only in the free lines of the settings (no structured fields): its block is still the sender
r = A.put(B + "/api/office/settings", json={"company": {"name": OWN["name"], "lines": ["Beispielstraße 12, 12345 Musterstadt"]},
                                           "company_fields": {k: "" for k in OWN}})
check(r.ok, "office settings without fields " + r.text[:160])
st, a, j = addr(text_pdf(HEAD + POS + SALUTE + OWNBLOCK + ["Kunde Alpha GmbH", "Hauptweg 9", "54321 Andersstadt"] + VALUES + TAIL, "t7"))
check(st == "ok" and got(a)[:5] == ("Kunde Alpha GmbH", "", "Hauptweg 9", "54321", "Andersstadt") and not own_in(a),
      f"#1813: own block known from the free company lines {j}")

print(f"p2561_a_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
