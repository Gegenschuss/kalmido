#!/usr/bin/env python3
"""2.146.0 API tests, part D (#2468, the retention export before deleting an account / an organisation), own container
(start.sh, org encryption on). Invented companies, clients, receipts and figures only (files made here).
freelancer-matrix: office  tenant-matrix: org
 - a person without organisation (personal office, its own admin): a finalised invoice, a receipt with its file, a cash book
   entry -> GET /api/retention/me names them; the ZIP has the index (the 8 / 10 years note), the manifest (SHA-256 of every
   file), the invoice PDF with its e-invoice inside, the receipt file byte for byte, the cash book as CSV + PDF, the office
   log and the documents as CSV; an API token gets nothing (401 / 403)
 - the instance admin deleting that account: delete-info says needed without counts and without a download (only the person
   may export); DELETE without ?retention= 409, ?retention=exported without a finished export 409, after the person's
   download it goes; another person deleted with ?retention=waived (noted in retention_log); an account without records
   deletes as before (no step)
 - an organisation: its admin gets the info + ZIP; a member and another organisation's admin 404, an agent 403; deleting
   the organisation (instance admin) 409 without the step, with a waiver / after an export it goes
 - self-hosting stays: a list with project receipts is still only handed over (409 with lists), also with a waiver
 - hosted (restart with KALMIDO_HOSTED=1, KEEP): with the waiver the account goes with its list of receipts, files included
usage: p2146_d_api_test.py <datadir>"""
import base64
import hashlib
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,files,budget"
O = "/api/office"
CBS = O + "/cashbooks"
RX = "/api/retention"


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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
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


def company(s, name):
    r = s.put(B + O + "/settings", json={"company_fields": {"name": name, "street": "Teststrasse 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                            "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}})
    assert r.ok, r.text


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"})
    assert r.ok, r.text
    return r.json()["id"]


def invoice(s, cl, title="Schnitt"):
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "service_from": "2026-03-01", "service_to": "2026-03-02",
                                      "items": [{"title": title, "qty": 1, "rate": 120}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + O + f"/docs/{did}/finalize")
    assert r.ok, r.text
    return did


def receipt(s, ws, name, data, amount="11.90", day="2026-03-06"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, data, "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    assert s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True}).ok
    return nid


def cash(s, text="Barverkauf Markt"):
    j = s.get(B + CBS).json()
    bk = j["books"][0]["id"]
    r = s.post(B + f"{CBS}/{bk}/entries", json={"day": j["today"], "dir": "in", "amount": "15", "text": text, "vat_pct": "7"})
    assert r.status_code == 201, r.text
    return bk


def unzip(r):
    return zipfile.ZipFile(io.BytesIO(r.content))


if not (os.environ.get("P2146D_NOSTART") or os.environ.get("KMT_NOSTART")):
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
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
company(Fr, "Frida Film")
FINV = invoice(Fr, client(Fr, "Private Client Ltd"))
RPDF = tiny_pdf("Beleg Farbe")
FREC = receipt(Fr, "private", "farbe.pdf", RPDF)
cash(Fr)
r = Fr.get(B + RX + "/me")
j = r.json() if r.ok else {}
check(r.ok and j.get("needed") and j.get("can_export") and j.get("counts", {}).get("documents") == 1 and j["counts"].get("receipts") == 1
      and j["counts"].get("cash") == 1 and j.get("exported_at") is None and j.get("years") == {"documents": 8, "books": 10}
      and "8 years" in j.get("note", "") and j.get("url") == RX + "/me/export.zip", "freelancer: the own records " + r.text[:400])
r1, r2 = requests.get(B + RX + "/me", headers=AGH), requests.get(B + RX + "/me/export.zip", headers=AGH)
check(r1.status_code in (401, 403) and r2.status_code in (401, 403) and not r2.content.startswith(b"PK"), f"agent token: no retention export {r1.status_code} {r2.status_code}")

# the instance admin wants to delete the account: the step first; only the person may download
r = A.get(B + f"/api/users/{FID}/delete-info")
ri = r.json().get("retention", {}) if r.ok else {}
check(r.ok and ri.get("needed") and not ri.get("can_export") and "counts" not in ri and "url" not in ri, "delete-info: needed, no counts, no download for the admin " + r.text[:300])
check(A.get(B + RX + f"/org/{ORG}").ok and A.get(B + f"{RX}/me").json().get("needed") is False, "setup: the admin has no own records")
r = A.delete(B + f"/api/users/{FID}")
check(r.status_code == 409 and r.json().get("code") == "retention" and r.json().get("retention", {}).get("needed"), "delete without the step: 409 " + r.text[:200])
r = A.delete(B + f"/api/users/{FID}", params={"retention": "exported"})
check(r.status_code == 409 and r.json().get("code") == "retention", "exported claimed without a finished export: 409 " + r.text[:200])
check(Fr.get(B + "/api/me").ok, "409: the account is still there")

r = Fr.get(B + RX + "/me/export.zip")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip") and "attachment" in r.headers.get("Content-Disposition", "")
      and "no-store" in r.headers.get("Cache-Control", ""), f"freelancer: the ZIP {r.status_code} {r.headers}")
z = unzip(r) if r.ok else zipfile.ZipFile(io.BytesIO(b"PK\x05\x06" + b"\0" * 18))
names = z.namelist()
idx = z.read("00-index.txt").decode() if "00-index.txt" in names else ""
check("8 years" in idx and "10 years" in idx and "invoices/" in idx and "receipts/" in idx and "cashbook/" in idx, "index: note + sections\n" + idx[:600])
man = __import__("json").loads(z.read("manifest.json")) if "manifest.json" in names else {}
check(man.get("subject") == f"user:{FID}" and all(hashlib.sha256(z.read(n)).hexdigest() == man["files"][n]["sha256"] for n in man.get("files", {})),
      "manifest: subject + SHA-256 of every file")
pdfs = [n for n in names if n.startswith("invoices/") and n.endswith(".pdf")]
check(len(pdfs) == 1 and z.read(pdfs[0]).startswith(b"%PDF") and b"/EmbeddedFile" in z.read(pdfs[0]), f"the invoice PDF with its e-invoice inside {pdfs}")
rec = [n for n in names if n.startswith(f"receipts/{FREC}-")]
check(len(rec) == 1 and z.read(rec[0]) == RPDF, f"the receipt file byte for byte {rec}")
rc = z.read("receipts/receipts.csv").decode("utf-8-sig") if "receipts/receipts.csv" in names else ""
check("11.90" in rc and "Material" in rc, "receipts.csv: amount + category (decrypted)\n" + rc[:300])
check(any(n.startswith("cashbook/") and n.endswith(".csv") for n in names) and any(n.startswith("cashbook/") and n.endswith(".pdf") for n in names)
      and "Barverkauf Markt" in next((z.read(n).decode("utf-8-sig") for n in names if n.startswith("cashbook/") and n.endswith(".csv") and "-" in n.split("/")[1]), ""),
      f"the cash book as CSV + PDF (text decrypted) {[n for n in names if n.startswith('cashbook/')]}")
log = z.read("logs/office-log.csv").decode("utf-8-sig") if "logs/office-log.csv" in names else ""
check("finalize" in log or "store" in log, "the office log (GoBD) as CSV\n" + log[:300])
docs = z.read("invoices/documents.csv").decode("utf-8-sig") if "invoices/documents.csv" in names else ""
check("invoice" in docs and "Private Client Ltd" in (docs + (z.read("invoices/clients.csv").decode("utf-8-sig") if "invoices/clients.csv" in names else "")),
      "documents + clients as CSV")
check(not any(".." in n or n.startswith("/") for n in names), "no path parts in the ZIP")
check(sql("SELECT COUNT(*) FROM retention_log WHERE subject=? AND kind='export' AND by_user=?", (f"user:{FID}", FID))[0][0] == 1, "the finished export is noted")
check(Fr.get(B + RX + "/me").json().get("exported_at"), "info: exported_at")
check(A.get(B + f"/api/users/{FID}/delete-info").json()["retention"].get("exported_at"), "the admin sees that the person exported")
r = A.delete(B + f"/api/users/{FID}", params={"retention": "exported"})
check(r.ok, "after the export: the account goes " + r.text[:200])
check(not sql("SELECT 1 FROM users WHERE id=?", (FID,)) and not sql("SELECT 1 FROM orgs WHERE personal_of=?", (FID,)), "account + personal office gone")

# a waiver (another person); an account without records: no step
GID, Gr = freelancer(B, A, "gina")
company(Gr, "Gina Grafik")
invoice(Gr, client(Gr, "Another Client Ltd"))
check(A.delete(B + f"/api/users/{GID}").status_code == 409, "gina: 409 without the step")
r = A.delete(B + f"/api/users/{GID}", params={"retention": "waived"})
check(r.ok, "gina: deleted with the waiver " + r.text[:200])
check(sql("SELECT kind, by_user FROM retention_log WHERE subject=?", (f"user:{GID}",)) == [("waiver", ALICE)], "the waiver is noted with who")
HID, _Hr = freelancer(B, A, "hanna")
r = A.get(B + f"/api/users/{HID}/delete-info")
check(r.ok and r.json()["retention"]["needed"] is False, "hanna: nothing to keep")
check(A.delete(B + f"/api/users/{HID}").ok, "an account without records: deleted as before")

# ---------------------------------------------------------------- an organisation  # tenant-matrix: org
company(A, "Alpha Studio")
company(Ca, "Beta AG")
invoice(A, client(A, "Kunde Eins GmbH"))
APDF = tiny_pdf("Beleg Alpha")
AREC = receipt(A, f"org:{ORG}", "alpha.pdf", APDF)
r = A.get(B + RX + f"/org/{ORG}")
check(r.ok and r.json()["can_export"] and r.json()["counts"].get("documents") == 1 and r.json()["counts"].get("receipts") == 1, "org admin: the info " + r.text[:300])
for who, s in (("member", Bo), ("another organisation's admin", Ca)):
    check(s.get(B + RX + f"/org/{ORG}").status_code == 404 and s.get(B + RX + f"/org/{ORG}/export.zip").status_code == 404, f"{who}: 404")
r = requests.get(B + RX + f"/org/{ORG}/export.zip", headers=AGH)
check(r.status_code in (401, 403, 404) and not r.content.startswith(b"PK"), f"agent: no organisation export {r.status_code}")
z = unzip(A.get(B + RX + f"/org/{ORG}/export.zip"))
check(any(n.startswith(f"receipts/{AREC}-") for n in z.namelist()) and not any("farbe" in n for n in z.namelist()), "org ZIP: its receipt, nothing of the person")
check(Ca.get(B + RX + f"/org/{ORG2}").json().get("needed") is False, "Beta: no records yet")

# deleting organisations (instance admin; an organisation without lists / files)
for name, how in (("Gamma", "waived"), ("Delta", "exported")):
    G = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE}).json()["id"]
    A.patch(B + "/api/settings", json={"workspace": f"org:{G}"})
    company(A, name + " GmbH")
    cash(A, "Kasse " + name)
    check(A.delete(B + f"/api/admin/orgs/{G}").status_code == 409, f"{name}: 409 without the step")
    if how == "exported":
        check(A.delete(B + f"/api/admin/orgs/{G}", params={"retention": "exported"}).status_code == 409, f"{name}: exported without an export 409")
        zz = unzip(A.get(B + RX + f"/org/{G}/export.zip"))
        check(any(n.startswith("cashbook/") for n in zz.namelist()), f"{name}: the cash book in its ZIP")
    r = A.delete(B + f"/api/admin/orgs/{G}", params={"retention": how})
    check(r.ok and not sql("SELECT 1 FROM orgs WHERE id=?", (G,)), f"{name}: deleted ({how}) " + r.text[:200])
    check(sql("SELECT kind FROM retention_log WHERE subject=? ORDER BY id DESC LIMIT 1", (f"org:{G}",)) == [("export" if how == "exported" else "waiver",)], f"{name}: noted")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.delete(B + f"/api/admin/orgs/{ORG2}").ok, "an organisation without records: deleted as before")

# ---------------------------------------------------------------- self-hosting: project receipts are still only handed over
r = A.post(B + "/api/users", json={"orgs": [], "username": "rosa", "display_name": "Rosa Example", "password": "password123"})
RID = r.json()["id"]
Ro = sess("rosa")
Ro.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,budget"})
BL = Ro.post(B + "/api/budget/lists", json={}).json().get("list_id")
e = Ro.post(B + f"/api/budget/{BL}/entries", json={"day": "2026-09-03", "amount": 10, "kind": "out", "title": "Paint"}).json()
check(Ro.post(B + f"/api/budget/entries/{e['id']}/files", files=[("file", ("receipt.txt", b"paid", "text/plain"))]).ok, "setup: a project receipt")
r = A.get(B + f"/api/users/{RID}/delete-info")
check(r.ok and r.json()["retention"]["needed"] is False and r.json()["retention"]["needed_along"] is True, "rosa: only the lists' receipts " + r.text[:300])
r = A.delete(B + f"/api/users/{RID}", params={"lists": "delete", "confirm": "rosa", "retention": "waived"})
check(r.status_code == 409 and r.json().get("lists") == [BL], "self-hosting: a list with receipts is not deleted along, also with a waiver " + r.text[:200])
z = unzip(Ro.get(B + RX + "/me/export.zip"))
check(any(n.startswith("project-receipts/") and z.read(n) == b"paid" for n in z.namelist()), "rosa: the project receipt in her ZIP")

# ---------------------------------------------------------------- hosted (KALMIDO_HOSTED=1, the same data): after the step the
# lists' receipts go along with the account, files included (the keeping lies with the person)
BP = sql("SELECT path FROM budget_files WHERE list_id=?", (BL,))[0][0]
BFULL = os.path.join(DATA, "attachments", BP)
check(os.path.isfile(BFULL), "setup: the project receipt file is on the disk")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**os.environ, "KEEP": "1", "EXTRA": os.environ.get("EXTRA", "") + f" -e KALMIDO_HOSTED=1 -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"})
for _ in range(80):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.25)
A = sess("alice")
r = A.get(B + f"/api/users/{RID}/delete-info")
check(r.ok and r.json()["retention"]["hosted"] is True and r.json()["retention"]["needed_along"] is True, "hosted: delete-info " + r.text[:300])
r = A.delete(B + f"/api/users/{RID}", params={"lists": "delete", "confirm": "rosa"})
check(r.status_code == 409, "hosted: without the step still 409 " + r.text[:200])
r = A.delete(B + f"/api/users/{RID}", params={"lists": "delete", "confirm": "rosa", "retention": "waived"})
check(r.ok, "hosted: with the waiver the account goes with its list of receipts " + r.text[:200])
check(not sql("SELECT 1 FROM lists WHERE id=?", (BL,)) and not sql("SELECT 1 FROM budget_files WHERE list_id=?", (BL,)), "hosted: list + receipt rows gone")
check(not os.path.exists(BFULL), "hosted: the receipt file is gone from the disk")

print(f"p2146_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
