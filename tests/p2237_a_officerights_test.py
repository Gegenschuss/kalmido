#!/usr/bin/env python3
"""2.237.0 A (#2861): office rights (groups) on routes beside the office gate. Invented names only.
freelancer-matrix: office
 - receipts outside /api/office (PUT /api/docs/<id>/receipt, /receipt/einvoice, the suggestions' accept / reject,
   POST /api/docs/<id>/extracted): "Staff" (receipts own) 403, a group with receipts edit 200, the admin and a member
   without a group as before; reading the receipt: own upload 200
 - send with datev: a group without the special export: the mail goes, the DATEV copy does not (datev_skipped); the admin's
   copy goes
 - the meals / travel reports as a file need the special export (the JSON view stays); the files are no-store
 - letters: clients in the recipients only with quotes view; a letter only from a letter template (404 else); save as
   template needs documents edit
 - bank matching with an invoice needs quotes edit, the open invoices quotes view; invoice from times needs times view
 - DATEV master data import: debtors skipped without quotes edit, the undo of a run with clients 403
 - procedure documentation: a member without a group 403, a group with books, the admin, the freelancer 200
 - a person without an organisation (personal office): every one of these works as before
usage: p2237_a_officerights_test.py <datadir>"""
import json
import os
import socket
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, until  # noqa: E402
import testclock  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
O, D, R = "/api/office", "/api/office/docs", "/api/office/rights"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts,travel"
MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else None
        if write:
            c.execute(sql, args)
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
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def head16():
    f = ['"EXTF"', "700", "16", '"Debitoren/Kreditoren"', "5", "20260101120000000", "", '"RE"', '""', '""', "1234567", "12345", "20260101", "4"]
    return ";".join(f + [""] * (31 - len(f)))


def extf16(rows):
    cols = ("Konto", "Name (Adressatentyp Unternehmen)", "Ort")
    lines = [head16(), ";".join(f'"{c}"' for c in cols)] + [";".join(f'"{v}"' for v in r) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def smtp_up():
    try:
        socket.create_connection(("127.0.0.1", 1025), timeout=1).close()
        return True
    except OSError:
        return subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                              capture_output=True).returncode == 0


if os.environ.get("P2237A_NOSTART") != "1":
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    until(smtp_up, 20)

# ---------------------------------------------------------------- setup: alice admin, bob Staff, carl "Sales" (no times),
# erin "Letters only", gus "Bank + books" (no quotes), dave without a group (previous access)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid, S = {}, {}
for u in ("bob", "carl", "dave", "erin", "gus"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
for s in (A, *S.values()):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
Bo, Ca, Da, Er, Gu = S["bob"], S["carl"], S["dave"], S["erin"], S["gus"]
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
DATEV = {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}
r = A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR", "datev_email": "inbox@example.com", "datev_extf": DATEV})
check(r.ok, "setup: office settings " + r.text[:200])
CL = A.post(B + "/api/clients", json={"name": "Example Client AG", "org_id": ORG, "email": "buyer@example.com", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]


def group(src, name, levels):
    r = A.post(B + f"{R}/groups", json={"from": src, "name": name})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    if levels:
        r = A.patch(B + f"{R}/groups/{gid}", json={"levels": levels})
        assert r.ok, r.text
    return f"g:{gid}"


for who, ref in (("bob", "tpl:staff"), ("carl", group("tpl:projects", "Sales", {"time": "none"})),
                 ("erin", group("tpl:none", "Letters only", {"letters": "edit"})),
                 ("gus", group("tpl:bookkeeping", "Bank and books", {"offers": "none"}))):
    r = A.put(B + f"{R}/people/{uid[who]}", json={"groups": [ref]})
    check(r.ok, f"setup: {who} into {ref} " + r.text[:200])


def upload(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Receipt " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def suggestion(nid, ws, org):
    dbx("INSERT INTO rc_suggest(node_id, org_id, ws, agent_id, category, note, state, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (nid, org, ws, ALICE, "Travel", "", "open", "2026-10-01T00:00:00Z"), write=True)
    return dbx("SELECT MAX(id) FROM rc_suggest WHERE node_id=?", (nid,))[0][0]


def extracted(nid):
    dbx("UPDATE doc_meta SET extracted=? WHERE node_id=?", (json.dumps({"gross": "11.90", "currency": "EUR", "vat_pct": "19"}), nid), write=True)


def code(r):
    return r.status_code


# ---------------------------------------------------------------- 1. receipts outside /api/office
WS = f"org:{ORG}"
RB, RC, RD = upload(Bo, WS, "bob.pdf"), upload(Ca, WS, "carl.pdf"), upload(Da, WS, "dave.pdf")
RCPT = {"category": "Software", "vat_pct": "19", "keep": True}
check(code(Bo.put(B + f"/api/docs/{RB}/receipt", json=RCPT)) == 403, "1 staff (receipts own): own document as receipt 403")
check(not dbx("SELECT 1 FROM rc_receipts WHERE node_id=?", (RB,)), "1 staff: no receipt row written")
check(code(Bo.get(B + f"/api/docs/{RB}/receipt")) == 200, "1 staff: reads the receipt state of the own upload")
check(code(Bo.post(B + f"/api/docs/{RB}/receipt/einvoice")) == 403, "1 staff: e-invoice as receipt 403")
extracted(RB)
check(code(Bo.post(B + f"/api/docs/{RB}/extracted", json={"do": "apply"})) == 403, "1 staff: taking over the VAT rate 403")
check(code(Bo.post(B + f"/api/docs/{RB}/extracted", json={"do": "dismiss"})) == 200, "1 staff: hiding the suggestion (no receipt) 200")
SB = suggestion(RB, f"o{ORG}", ORG)
check(code(Bo.post(B + f"/api/receipt-suggestions/{SB}/accept", json={})) == 403, "1 staff: accepting a suggestion 403")
check(code(Bo.post(B + f"/api/receipt-suggestions/{SB}/reject")) == 403, "1 staff: rejecting a suggestion 403")
check(dbx("SELECT state FROM rc_suggest WHERE id=?", (SB,))[0][0] == "open", "1 staff: the suggestion stays open")
r = Ca.put(B + f"/api/docs/{RC}/receipt", json=RCPT)
check(r.ok and r.json()["can_edit"] is True, "1 group with receipts edit: receipt 200 " + r.text[:200])
check(Bo.get(B + f"/api/docs/{RB}/receipt").json().get("can_edit") is False, "1 staff: the sheet shows no edit")
SC = suggestion(RC, f"o{ORG}", ORG)
check(Ca.post(B + f"/api/receipt-suggestions/{SC}/reject").ok, "1 group with receipts edit: reject 200")
check(Ca.post(B + f"/api/receipt-suggestions/{SC}/reopen").ok, "1 group with receipts edit: reopen 200")
extracted(RC)
check(Ca.post(B + f"/api/docs/{RC}/extracted", json={"do": "apply"}).ok, "1 group with receipts edit: take over 200")
check(Da.put(B + f"/api/docs/{RD}/receipt", json=RCPT).ok, "1 member without a group: as before 200")
check(A.put(B + f"/api/docs/{RB}/receipt", json=RCPT).ok, "1 the admin: another person's document as receipt 200")
check(A.post(B + f"/api/receipt-suggestions/{SB}/accept", json={}).ok, "1 the admin: accepts 200")

# ---------------------------------------------------------------- 2. send with the DATEV copy
def final_invoice(s):
    r = s.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "items": [{"title": "Edit", "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


I1 = final_invoice(Ca)
r = Ca.post(B + f"{D}/{I1}/send", json={"to": "buyer@example.com", "datev": True})
check(r.ok and r.json().get("datev_skipped") is True and r.json().get("datev_error"), f"2 no export: sent, no DATEV copy {code(r)} {r.text[:200]}")
check(dbx("SELECT datev_sent_at, status FROM office_docs WHERE id=?", (I1,))[0] in ((None, "sent"), ("", "sent")), "2 no export: datev_sent_at empty, status sent")
I2 = final_invoice(A)
r = A.post(B + f"{D}/{I2}/send", json={"to": "buyer@example.com", "datev": True})
check(r.ok and not r.json().get("datev_skipped") and not r.json().get("datev_error"), f"2 the admin: sent with the copy {r.text[:200]}")
check(bool(dbx("SELECT datev_sent_at FROM office_docs WHERE id=?", (I2,))[0][0]), "2 the admin: datev_sent_at set")

# ---------------------------------------------------------------- 3. the reports as files
for path, q in (("/meals/report", {"year": "2026"}), ("/trips/report", {"by": "month"})):
    check(Bo.get(B + O + path, params=q).ok, f"3 staff: {path} as JSON 200")
    check(code(Bo.get(B + O + path, params={**q, "format": "csv"})) == 403, f"3 staff: {path} as CSV needs export 403")
    r = A.get(B + O + path, params={**q, "format": "csv"})
    check(r.ok and r.headers.get("Cache-Control") == "no-store", f"3 the admin: {path} CSV, no-store {code(r)} {r.headers.get('Cache-Control')}")
check(code(Bo.get(B + O + "/meals/report", params={"year": "2026", "format": "pdf"})) == 403, "3 staff: meals PDF 403")
check(Ca.get(B + O + "/meals/report", params={"year": "2026"}).ok and code(Ca.get(B + O + "/meals/report", params={"year": "2026", "format": "csv"})) == 403,
      "3 sales (meals edit, no export): JSON yes, CSV 403")

# ---------------------------------------------------------------- 4. letters
TN = A.post(B + O + "/doc-templates", json={"kind": "nda", "name": "NDA example", "lang": "en", "body": "Secret clause", "sign": 0}).json()["id"]
TL = A.post(B + O + "/doc-templates", json={"kind": "letter", "name": "Hello letter", "lang": "en", "body": "Dear client", "sign": 0}).json()["id"]
check(code(Er.post(B + O + "/letters", json={"template_id": TN})) == 404, "4 a letter from a non-letter template 404")
r = Er.post(B + O + "/letters", json={"template_id": TL})
check(r.status_code == 201 and "Dear client" in r.json().get("body", ""), "4 a letter from the letter template 201 " + r.text[:200])
LID = r.json().get("id")
rc = Er.get(B + O + "/letters/recipients").json().get("recipients", [])
check(not any(x["kind"] == "client" for x in rc), f"4 letters only: no clients in the recipients {rc[:2]}")
check(any(x["kind"] == "client" for x in A.get(B + O + "/letters/recipients").json().get("recipients", [])), "4 the admin: clients in the recipients")
check(code(Er.post(B + O + f"/letters/{LID}/template", json={"name": "Copy"})) == 403, "4 letters only: save as template 403")
check(Ca.post(B + O + f"/letters/{LID}/template", json={"name": "Copy"}).status_code == 201, "4 sales (documents edit): save as template 201")

# ---------------------------------------------------------------- 5. bank, 6. invoice from times
I3 = final_invoice(A)
dbx("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
    (ORG, testclock.today().isoformat(), "100.00", "EUR", "Example Client AG", "Invoice", "p2237a-1", "2026-05-02T10:00:00Z"), write=True)
TX = dbx("SELECT id FROM office_bank_tx WHERE org_id=? AND hash='p2237a-1'", (ORG,))[0][0]
r = Gu.get(B + O + "/bank/tx")
check(r.ok and not any(s.get("kind") == "invoice" for t in r.json()["items"] for s in t.get("suggestions") or []), f"5 no quotes: no invoice suggestions {r.text[:200]}")
r = Gu.get(B + O + f"/bank/tx/{TX}/candidates")
check(r.ok and r.json()["items"] == [], f"5 no quotes: no open invoices as candidates {r.text[:200]}")
check(code(Gu.post(B + O + f"/bank/tx/{TX}/match", json={"kind": "invoice", "id": I3})) == 403, "5 no quotes: matching with an invoice 403")
check(any(x["kind"] == "invoice" for x in A.get(B + O + f"/bank/tx/{TX}/candidates").json()["items"]), "5 the admin: open invoices as candidates")
check(A.post(B + O + f"/bank/tx/{TX}/match", json={"kind": "invoice", "id": I3}).ok, "5 the admin: matching 200")
FT = {"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"}
check(code(Ca.post(B + D + "/from-time", json=FT)) == 403, "6 sales without times: invoice from times 403")
check(code(A.post(B + D + "/from-time", json=FT)) != 403, "6 the admin: not refused by the rights")

# ---------------------------------------------------------------- 7. DATEV master data import
F16 = extf16([("10001", "Debtor Example GmbH", "Köln"), ("70001", "Supplier Example GmbH", "Berlin")])
r = Gu.post(B + O + "/datev/import/check", files={"file": ("extf.csv", F16, "text/csv")})
check(r.ok and r.json()["counts"].get("debtors") == 0 and r.json()["counts"].get("creditors") == 1, f"7 no quotes: the preview skips the debtor {r.text[:300]}")
r = Gu.post(B + O + "/datev/import", files={"file": ("extf.csv", F16, "text/csv")})
check(r.status_code == 201 and r.json()["counts"].get("new") == 1, "7 no quotes: only the supplier taken over " + r.text[:200])
check(not dbx("SELECT 1 FROM clients WHERE name='Debtor Example GmbH'"), "7 no quotes: no client created")
r = A.post(B + O + "/datev/import", files={"file": ("extf.csv", extf16([("10002", "Debtor Two GmbH", "Bonn")]), "text/csv")})
check(r.status_code == 201 and dbx("SELECT 1 FROM clients WHERE name='Debtor Two GmbH'"), "7 the admin: the debtor becomes a client " + r.text[:200])
RUN = r.json().get("run_id")
check(code(Gu.post(B + O + f"/datev/import/{RUN}/undo")) == 403, "7 no quotes: undo of a run with clients 403")
check(dbx("SELECT 1 FROM clients WHERE name='Debtor Two GmbH'"), "7 the client stays")
check(A.post(B + O + f"/datev/import/{RUN}/undo").ok, "7 the admin: undo 200")

# ---------------------------------------------------------------- 9. procedure documentation
check(code(Da.get(B + O + "/procdoc")) == 403 and code(Da.get(B + O + "/procdoc.md")) == 403, "9 a member without a group: 403")
check(Gu.get(B + O + "/procdoc").ok, "9 a group with books: 200")
check(code(Bo.get(B + O + "/procdoc")) == 403, "9 staff: 403")
check(A.get(B + O + "/procdoc").ok, "9 the admin: 200")

# ---------------------------------------------------------------- freelancer-matrix: office (personal office, own admin)
FID, Fr = freelancer(B, A)
check(Fr.put(B + O + "/settings", json={"company_fields": {**COMPANY, "name": "Frida Photo"}, "lang": "en", "currency": "EUR",
                                        "datev_extf": DATEV}).ok, "freelancer: her office")
FR = upload(Fr, "private", "frida.pdf")
check(Fr.put(B + f"/api/docs/{FR}/receipt", json=RCPT).ok and Fr.get(B + f"/api/docs/{FR}/receipt").json()["can_edit"], "freelancer: receipt 200")
fws = dbx("SELECT ws FROM doc_meta WHERE node_id=?", (FR,))[0][0]
FS = suggestion(FR, fws, None)
check(Fr.post(B + f"/api/receipt-suggestions/{FS}/reject").ok, "freelancer: rejects a suggestion")
extracted(FR)
check(Fr.post(B + f"/api/docs/{FR}/extracted", json={"do": "apply"}).ok, "freelancer: takes the values over")
for path, q in (("/meals/report", {"year": "2026"}), ("/trips/report", {"by": "month"})):
    check(Fr.get(B + O + path, params={**q, "format": "csv"}).ok, f"freelancer: {path} CSV 200")
FCL = Fr.post(B + "/api/clients", json={"name": "Frida's Client", "country": "DE", "org_id": None}).json().get("id")
check(any(x["kind"] == "client" for x in Fr.get(B + O + "/letters/recipients").json().get("recipients", [])), "freelancer: her clients in the recipients")
FTL = Fr.post(B + O + "/doc-templates", json={"kind": "letter", "name": "Hi", "lang": "en", "body": "Hi", "sign": 0}).json()["id"]
r = Fr.post(B + O + "/letters", json={"template_id": FTL})
check(r.status_code == 201 and Fr.post(B + O + f"/letters/{r.json()['id']}/template", json={}).status_code == 201, "freelancer: letter + save as template")
check(code(Fr.post(B + D + "/from-time", json={"client_id": FCL, "from": "2026-05-01", "to": "2026-05-31"})) != 403, "freelancer: invoice from times not refused")
r = Fr.post(B + O + "/datev/import/check", files={"file": ("extf.csv", F16, "text/csv")})
check(r.ok and r.json()["counts"].get("debtors") == 1, "freelancer: the debtor in the preview " + r.text[:200])
check(Fr.get(B + O + "/procdoc").ok, "freelancer: procedure documentation 200")
PB = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
dbx("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
    (PB, testclock.today().isoformat(), "10.00", "EUR", "Someone", "x", "p2237a-2", "2026-05-02T10:00:00Z"), write=True)
FTX = dbx("SELECT id FROM office_bank_tx WHERE org_id=? AND hash='p2237a-2'", (PB,))[0][0]
check(Fr.get(B + O + "/bank/tx").ok and Fr.get(B + O + f"/bank/tx/{FTX}/candidates").ok, "freelancer: bank list + candidates")

print(f"p2237_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
