#!/usr/bin/env python3
"""2.81.0 API tests, part B: correct an archived document of the office afterwards (#1834) and the DATEV debtor of a locked
invoice (#1867). Own container (start.sh), invented companies, people and numbers only.
 - #1834: a quotation archived without a client gets one afterwards -> listed under that client (?client_id=);
   net + tax lines 19 % + 7 % -> the gross is added up by the server (amount), tax and net in the answer; reverse charge
   = no tax; the history of the entry has when, who, the old and the new value; a member may correct (decision
   16.10.2026), a person of another organisation gets 404, an agent 403; number and file never change; paid only for
   invoices; bad tax lines 400; an amount alone = gross, tax unknown (tax_lines null)
 - #1867: an invoice locked under customer number 10042 stays on debtor 10042 in the DATEV export after the client's
   number changed to 10043; an invoice locked afterwards takes 10043; a snapshot without a customer number reads it live
usage: p281_b_api_test.py <datadir>      (P281B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys

import requests

import dbx as dbxm

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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def mini_pdf(tag):
    """A tiny invented PDF; tag makes it unique."""
    content = f"BT /F1 12 Tf 72 720 Td (Archiv {tag}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


FEAT = "cal,comments,collab,office,clients,time"
if os.environ.get("P281B_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
L = "/api/office/legacy"

# ================================================================ #1834: correct an archived document
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "org_id": ORG, "customer_no": "10042"}).json()["id"]
RUN = A.post(B + L + "/archive/run").json()["run_id"]


def up(meta, tag):
    return A.post(B + L + "/archive", files={"file": (tag + ".pdf", mini_pdf(tag), "application/pdf")},
                  data={k: ("" if v is None else str(v)) for k, v in dict(meta, run_id=RUN).items()})


r = up({"kind": "offer", "number": "AN-0815", "date": "2026-02-01", "amount": ""}, "an0815")
check(r.status_code == 201 and r.json()["client_id"] is None and r.json()["amount"] is None, "offer archived without client and amount " + r.text[:200])
OF = r.json().get("id")
r = up({"kind": "invoice", "number": "RE-0816", "date": "2026-02-02", "amount": "1190", "paid": 1}, "re0816")
check(r.status_code == 201 and r.json()["tax_lines"] is None and r.json()["tax"] is None, "invoice archived with a gross only: tax unknown " + r.text[:200])
IV = r.json().get("id")

# a member sets the client of the quotation afterwards -> listed under the client
r = Bo.patch(B + L + f"/archive/{OF}", json={"client_id": C1})
check(r.ok and r.json()["client_id"] == C1, "member sets the client afterwards " + r.text[:200])
r = A.get(B + L + f"/archive?client_id={C1}")
check(r.ok and [x["id"] for x in r.json()["items"]] == [OF] and r.json()["items"][0]["client"] == "Beispielkunde AG", "the quotation is listed under its client " + r.text[:200])

# tax lines 19 % + 7 % -> gross added up by the server; reverse charge has no tax
r = A.patch(B + L + f"/archive/{IV}", json={"tax_lines": [{"net": "1.000,00", "tax": "19"}, {"net": 100, "tax": "7"}]})
j = r.json() if r.ok else {}
check(r.ok and j["amount"] == 1297 and j["net"] == 1100 and j["tax"] == 197 and [x["tax"] for x in j["tax_lines"]] == ["19", "7"],
      "19 % + 7 %: gross 1297.00, net 1100, tax 197 " + r.text[:300])
r = Bo.patch(B + L + f"/archive/{OF}", json={"tax_lines": [{"net": "500", "tax": "rc"}]})
check(r.ok and r.json()["amount"] == 500 and r.json()["tax"] == 0, "reverse charge: gross = net " + r.text[:200])
for bad in ([], [{"net": "abc", "tax": "19"}], [{"net": "10", "tax": "16"}], [{"net": "1", "tax": "19"}] * 11, "19", [["10", "19"]]):
    r = A.patch(B + L + f"/archive/{IV}", json={"tax_lines": bad})
    check(r.status_code == 400 or (bad == [] and r.ok and r.json()["amount"] == 1297), f"bad tax lines refused / ignored: {bad!r} -> {r.status_code}")

# paid: invoices only; number and file never change
r = A.patch(B + L + f"/archive/{IV}", json={"paid": 0, "number": "X-1", "file_name": "other.pdf"})
check(r.ok and r.json()["paid"] == 0 and r.json()["number"] == "RE-0816" and r.json()["file_name"] == "re0816.pdf", "paid off; number and file stay " + r.text[:200])
r = A.patch(B + L + f"/archive/{OF}", json={"paid": 1})
check(r.ok and r.json()["paid"] == 0, "a quotation is never paid " + r.text[:200])

# the history: newest first, who, old and new value
r = A.get(B + L + f"/archive/{IV}")
h = r.json().get("history") if r.ok else []
check(r.ok and [x["field"] for x in h] == ["paid", "amount"], f"history of the invoice: paid, amount: {[x['field'] for x in h or []]}")
if len(h) == 2:
    check(h[0]["old"] == 1 and h[0]["new"] == 0 and h[0]["user_name"] == "Alice Admin" and h[0]["at"], "history: paid 1 -> 0 by Alice with time " + str(h[0]))
    check(h[1]["old"] == {"gross": 1190, "lines": None} and h[1]["new"]["gross"] == 1297 and len(h[1]["new"]["lines"]) == 2,
          "history: amount gross 1190 (tax unknown) -> 1297 with two tax lines " + str(h[1]))
h = Bo.get(B + L + f"/archive/{OF}").json().get("history") or []
check([x["field"] for x in h] == ["amount", "client"] and h[1]["old"] is None and h[1]["new"] == {"id": C1, "name": "Beispielkunde AG"}
      and h[1]["user_name"] == "Bob Member", "history of the quotation: the client set by Bob " + str(h)[:300])
n = len(dbx("SELECT id FROM office_archive_log WHERE archive_id=?", (IV,)))
A.patch(B + L + f"/archive/{IV}", json={"paid": 0, "client_id": None})
check(len(dbx("SELECT id FROM office_archive_log WHERE archive_id=?", (IV,))) == n, "no change = no history row")

# an amount alone = gross, tax unknown again
r = A.patch(B + L + f"/archive/{IV}", json={"amount": "1.190,00"})
check(r.ok and r.json()["amount"] == 1190 and r.json()["tax_lines"] is None, "an amount alone: gross, tax unknown " + r.text[:200])

# other organisation / agent
check(Ca.patch(B + L + f"/archive/{IV}", json={"paid": 1}).status_code == 404, "tenant-matrix: another organisation cannot correct (404)")
check(Ca.get(B + L + f"/archive/{IV}").status_code == 404, "tenant-matrix: another organisation cannot read the history (404)")
C2 = Ca.post(B + "/api/clients", json={"name": "Beta Fremdkunde", "org_id": ORG2}).json()["id"]
check(A.patch(B + L + f"/archive/{IV}", json={"client_id": C2}).status_code == 400, "a client of another organisation is refused (400)")
check(requests.patch(B + L + f"/archive/{IV}", json={"paid": 1}, headers=AGH).status_code in (401, 403), "an agent cannot correct")
check(requests.get(B + L + f"/archive/{IV}", headers=AGH).status_code in (401, 403), "an agent cannot read the history")
check(A.get(B + L + "/archive/999999").status_code == 404, "unknown entry 404")

# ================================================================ #1867: DATEV keeps the customer number of a locked invoice
O, D, X = "/api/office", "/api/office/docs", "/api/office/datev/extf"
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"},
                                     "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok, "company + DATEV settings " + r.text[:200])
A.patch(B + f"/api/clients/{C1}", json={"street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"})


def invoice(title, date):
    r = A.post(B + D, json={"kind": "invoice", "client_id": C1, "service_from": "2026-03-01", "service_to": "2026-03-04", "items": [{"title": title, "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = A.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    dbx("UPDATE office_docs SET date=? WHERE id=?", (date, did))
    return did, r.json()["number"]


def debtors():
    r = A.get(B + X + "?from=2026-03-01&to=2026-03-31")
    assert r.ok, r.text
    lines = r.content.decode("cp1252").split("\r\n")
    cols = lines[1].split(";")
    k, bf = cols.index("Konto"), cols.index("Belegfeld 1")
    return {f.split(";")[bf].strip('"'): f.split(";")[k] for f in lines[2:] if f}


I1, N1 = invoice("Schnitt", "2026-03-05")
r = A.patch(B + f"/api/clients/{C1}", json={"customer_no": "10043"})
check(r.ok, "the client's customer number changes to 10043 " + r.text[:200])
I2, N2 = invoice("Ton", "2026-03-06")
DRAFT = A.post(B + D, json={"kind": "invoice", "client_id": C1, "service_from": "2026-03-01", "service_to": "2026-03-04", "items": [{"title": "Entwurf", "qty": 1, "rate": 50}]}).json()["id"]
deb = debtors()
check(deb.get(N1) == "10042", f"#1867: the invoice locked before keeps debtor 10042: {deb}")
check(deb.get(N2) == "10043", f"#1867: the invoice locked afterwards takes 10043: {deb}")
r = A.post(B + f"{D}/{DRAFT}/finalize")
check(r.ok, "the draft is locked now " + r.text[:120])
NDR = r.json().get("number")
dbx("UPDATE office_docs SET date='2026-03-07' WHERE id=?", (DRAFT,))
check(debtors().get(NDR) == "10043", "#1867: a draft locked after the change takes the new number")
# an old snapshot without the field reads the live client (fallback)
snap = dbx("SELECT recipient_snapshot FROM office_docs WHERE id=?", (I1,))[0][0]
dbx("UPDATE office_docs SET recipient_snapshot=? WHERE id=?", (snap.replace('"customer_no"', '"customer_nr_old"'), I1))
check(debtors().get(N1) == "10043", "#1867: a snapshot without a customer number reads it live")

print(f"p281_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
