#!/usr/bin/env python3
"""2.46.2 part D API tests: #1472 a client without lists still answers with its month (the page showed "Invalid Date");
#1646 the recipient block of an old PDF stops at bank / contact VALUES that a template prints without their labels above the
address (IBAN, BIC, tax / VAT number, phone, bare domain, bank name), and a person above the company becomes the contact.
Invented companies, people, addresses and bank data only; the PDFs are generated here (a one-page text layer).
usage: p2462_d_api_test.py <datadir>"""
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
    """A one-page PDF whose text layer holds lines (top to bottom; (y, size, text) or text); no lines = like a scan."""
    ops, y = [], 800
    for ln in lines:
        if isinstance(ln, tuple):
            y, size, t = ln
        else:
            size, t = 11, ln
        t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 {size} Tf 60 {y} Td ({t}) Tj ET")
        y -= 16
    content = ("\n".join(ops) + f"\n% {tag}").encode("latin-1")
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
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,time", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
L = "/api/office/legacy"
r = A.put(B + "/api/office/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                           "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstra\u00dfe 12", "zip": "20457", "city": "Hamburg",
                                                              "country": "DE", "email": "hallo@nordlicht.example", "phone": "+49 40 000000"}, "payment_days": 14})
check(r.ok, "office settings " + r.text[:160])

# ---------------------------------------------------------------- #1472 a client without lists
r = A.post(B + "/api/clients", json={"name": "Leerlauf KG", "org_id": ORG})
CID = r.json()["id"]
st = A.get(B + f"/api/clients/{CID}").json().get("stats") or {}
check(r.status_code == 201 and len(st.get("month", "")) == 7 and st["month"][4] == "-", f"#1472: a client without lists answers with its month {st}")
st = A.get(B + f"/api/clients/{CID}?month=2026-02").json().get("stats") or {}
check(st.get("month") == "2026-02" and st["month_seconds"] == 0, f"#1472: the asked month comes back {st}")
check(A.get(B + f"/api/clients/{CID}?month=nonsense").status_code == 400, "#1472: a bad month is refused also without lists")
check(r.json().get("stats", {}).get("month"), "#1472: the create answer has the month too")

# ---------------------------------------------------------------- #1646 the recipient block of an old PDF
SENDER = (790, 7, "Studio Nordlicht GmbH \u00b7 Hafenstra\u00dfe 12 \u00b7 20457 Hamburg")
LABELS = ["FON:", "FAX:", "MAIL:", "WEB:", "MwSt.Nr:", "Ust.-ID:", "BANK:", "IBAN:", "BIC:"]
VALUES = ["+49 40 000 000 00", "+49 40 000 000 01", "hallo@nordlicht.example", "nordlicht.example", "12/345/67890", "DE 123 456 789",
          "SPARKASSE BEISPIELSTADT", "DE89 3704 0044 0532 0130 00", "COBADEFFXXX"]


def template(recipient, tag):
    """Labels in a column of their own, the values right above the recipient (the layout of an old template)."""
    return text_pdf([SENDER, "Kostenvoranschlag", "Sehr geehrte Damen und Herren,", "Studio Nordlicht GmbH", "Hafenstra\u00dfe 12, 20457 Hamburg"]
                    + LABELS + VALUES + recipient + ["Angebot Nr.: X-001"], tag)


def addr(pdf):
    r = A.post(B + L + "/archive/address", files={"file": ("a.pdf", pdf, "application/pdf")}, data={"client_id": ""})
    j = r.json()
    return r.ok and j.get("status") == "ok", j.get("address") or {}, j


def got(a):
    return tuple(a.get(k) for k in ("name", "contact", "street", "zip", "city"))


ok, a, j = addr(template(["Beispiel Energie GmbH", "Testweg 6", "50676 K\u00f6ln"], "t1"))
check(ok and got(a) == ("Beispiel Energie GmbH", "", "Testweg 6", "50676", "K\u00f6ln") and not j.get("unsure"),
      f"#1646: bank and contact values above the recipient are not part of it {j}")
ok, a, j = addr(template(["Lena Muster", "Musterversicherung Aktiengesellschaft", "Allee 10-20", "51067 K\u00f6ln"], "t2"))
# 2.46.2 (#1646, review): the swap without "Frau"/"Herr" is a guess -> marked unsure with its reason
check(ok and got(a) == ("Musterversicherung Aktiengesellschaft", "Lena Muster", "Allee 10-20", "51067", "K\u00f6ln") and j.get("unsure")
      and "person_swap" in (a.get("flags") or []), f"#1646: the person above the company (legal form on the second line) is the contact {j}")
ok, a, j = addr(template(["Theater Beispiel e.V.", "Lindenstra\u00dfe 72", "50679 K\u00f6ln"], "t3"))
check(ok and got(a) == ("Theater Beispiel e.V.", "", "Lindenstra\u00dfe 72", "50679", "K\u00f6ln"), f"#1646: a club (e.V.) is no value line {j}")
# the newer template: the address under the salutation, firm / person / street / city, nothing bank-like above it
P = text_pdf([SENDER, "Rechnung", "Sehr geehrte Damen und Herren,", "Beispiel Partner GmbH", "Jana Probe", "Kreisweg 6-20 (Haus 2.13)", "51063 K\u00f6ln",
              "Ref./PO-Nr.: PRO-1", "+4922100000000", "hallo@nordlicht.example", "nordlicht.example"], "t4")
ok, a, j = addr(P)
check(ok and got(a) == ("Beispiel Partner GmbH", "Jana Probe", "Kreisweg 6-20 (Haus 2.13)", "51063", "K\u00f6ln") and not j.get("unsure"),
      f"#1646: the newer template still reads firm, person, street, city {j}")
# a bank as the recipient keeps its name (it has a legal form)
ok, a, j = addr(template(["Beispiel Bank AG", "Kontorstra\u00dfe 1", "60311 Frankfurt"], "t5"))
check(ok and got(a)[0] == "Beispiel Bank AG" and got(a)[2] == "Kontorstra\u00dfe 1", f"#1646: a recipient that is a bank (with its legal form) keeps its name {j}")

# 2.46.2 (#1646, review): a company name on two lines stays one name; a savings bank without bank values around it is the
# recipient; a company name starting with a greeting word is no salutation
ok, a, j = addr(text_pdf([SENDER, "Rechnung", "Musterfirma", "GmbH & Co. KG", "Hauptweg 3", "50667 K\u00f6ln"], "t6"))
check(ok and got(a)[:2] == ("Musterfirma GmbH & Co. KG", ""), f"#1646: a company name on two lines is not split into person + company {j}")
ok, a, j = addr(text_pdf([SENDER, "Rechnung", "Sparkasse Beispielstadt", "Hahnenweg 57", "50667 K\u00f6ln"], "t7"))
check(ok and got(a)[0] == "Sparkasse Beispielstadt" and got(a)[2] == "Hahnenweg 57", f"#1646: a savings bank as the recipient keeps its name {j}")
ok, a, j = addr(text_pdf([SENDER, "Rechnung", "Hallo Pizza GmbH", "Testweg 9", "50667 K\u00f6ln"], "t8"))
check(ok and got(a)[0] == "Hallo Pizza GmbH", f"#1646: a company named with a greeting word is no salutation {j}")

print(f"p2462_d_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
