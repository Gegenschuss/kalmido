#!/usr/bin/env python3
"""2.306.0 API tests, part D2 (#2875): hardening of the office (audit D, office), own container (start.sh).
Invented people, firms and figures only (example.com).
tenant-matrix: office
freelancer-matrix: office
 - an own Peppol endpoint: an internal host only for an instance admin (or KALMIDO_PEPPOL_ALLOW_HOSTS); an organisation
   admin and a person without an organisation get 400, public https addresses stay; the allow list at send time follows
   the person who saved the connection
 - the calendar fetcher (cal_http) follows a redirect with credentials / a body only on the same origin (scheme, host, port)
 - the number scheme parse stays fast for any scheme and still reads normal numbers
 - a DATEV duplicate stays out only when its original is a receipt itself
 - no-store on the DATEV ZIP, the GoBD ZIP, the meals CSV and the equipment value CSV
 - the books export ZIP leaves a receipt file found infected out (its line stays)
 - the readable e-invoice view is locked once the file is found infected
 - two bank bookings at once on the same receipt: exactly one wins
 - GET has no side effects: the Peppol status fetch is a POST, the supplier trash is cleaned on write
 - the follow-up task of a letter keeps a sealed subject out of its plain title
 - a personal office with its own Peppol connection moves into an organisation that has one (the connections stay)
usage: p2306_d2_office_hardening_test.py <datadir>      (P2306D2_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import subprocess
import sys
import threading
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # noqa: E402,F401  shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
D = O + "/docs"
K = O + "/bank"
TODAY = testclock.today().isoformat()
MONTH = TODAY[:7]
de = lambda iso: f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"  # noqa: E731
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_ct(code, timeout=300):
    """Python code inside the server container (the app loaded) -> stdout + stderr ('TIMEOUT' after timeout seconds)."""
    try:
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + code],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "exec", CT, "pkill", "-f", "TASKS_PARSE_PROBE"], capture_output=True)
        return "TIMEOUT"
    return r.stdout + r.stderr


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


UBL = """<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ID>UBL-2306-0001</cbc:ID>
  <cbc:IssueDate>2026-10-05</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Beispiel Druckerei</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>Druckweg 1</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName>
      <cbc:PostalZone>12345</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Beispiel Druckerei GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Frida Film</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">38.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">200.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">38.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">200.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">238.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">238.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">100</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Flyer A5</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">2.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>
"""

if not (os.environ.get("P2306D2_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098 -e KALMIDO_PURGE_TRASH=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
assert A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"}).ok
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma AG"), (Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text
PB = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]

# ---------------------------------------------------------------- Peppol: an own endpoint inside the network
PEP = O + "/peppol"
INTERNAL = "http://127.0.0.1:8098/own"  # on the calendar allow list of this server
for who, s in (("an organisation admin", Ca), ("a person without an organisation", Fr)):
    for url in (INTERNAL, "https://10.1.2.3/own", "https://localhost/own"):
        r = s.put(B + PEP, json={"provider": "custom", "endpoint_url": url})
        check(r.status_code == 400, f"{who}: no internal endpoint {url} ({r.status_code} {r.text[:120]})")
    r = s.put(B + PEP, json={"provider": "custom", "endpoint_url": "https://ap.example.com/own", "api_key": "key-x"})
    check(r.ok and r.json()["endpoint_url"] == "https://ap.example.com/own", f"{who}: a public https endpoint stays possible {r.text[:160]}")
r = A.put(B + PEP, json={"provider": "custom", "endpoint_url": INTERNAL, "api_key": "key-a"})
check(r.ok and r.json()["endpoint_url"] == INTERNAL, f"the instance admin: the allowed internal host {r.text[:160]}")
out = in_ct("from kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.office.peppol import _pep_allow\n"
            f"c = connect()\nwith system_ctx(c):\n    print('allow', ('127.0.0.1', 8098) in _pep_allow(c, {ORG}), len(_pep_allow(c, {ORG2})), len(_pep_allow(c, {PB})))\nc.close()")
check("allow True 0 0" in out, "at send time the internal hosts count only for a connection an instance admin saved " + out[-300:])

# ---------------------------------------------------------------- cal_http: credentials and a body only on the same origin
REDIR = r'''
import http.server, threading
from kalmido.calendars.subscriptions import cal_http, CalError
LOC = {}
class Hd(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/a":
            self.send_response(307); self.send_header("Location", LOC["to"]); self.send_header("Content-Length", "0"); self.end_headers()
            return
        b = ("ok " + (self.headers.get("Authorization") or "-")).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST
    def log_message(self, *a):
        pass
s1, s2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd), http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd)
for s in (s1, s2):
    threading.Thread(target=s.serve_forever, daemon=True).start()
p1, p2 = s1.server_address[1], s2.server_address[1]
allow = frozenset({("127.0.0.1", None)})
def go(to, **k):
    LOC["to"] = to
    try:
        st, _h, raw, _u = cal_http(f"http://127.0.0.1:{p1}/a", allow=allow, cross_redirects=True, **k)
        return raw.decode()
    except CalError as e:
        return e.code
print("same", go("/b", method="POST", body=b"x", headers={"Authorization": "Bearer k"}))
print("port", go(f"http://127.0.0.1:{p2}/b", method="POST", body=b"x", headers={"Authorization": "Bearer k"}))
print("bare", go(f"http://127.0.0.1:{p2}/b"))
'''
out = in_ct(REDIR)
check("same ok Bearer k" in out, "a redirect on the same origin keeps the credentials " + out[-300:])
check("port redirect" in out, "a redirect to another port (another origin) with credentials and a body is refused " + out[-300:])
check("bare redirect" in out, "a redirect to another origin over http is refused " + out[-300:])

# ---------------------------------------------------------------- the number scheme parse
out = in_ct("import time  # TASKS_PARSE_PROBE\nfrom kalmido.office.model import onc_parse\nt = time.monotonic()\n"
            "onc_parse('{client}-{project}-{initials}-{client}-{seq}', 'a-' * 149 + 'x')\n"
            "onc_parse('{client}-{project}-{initials}-{client}-{project}-{initials}-{seq}', 'a-' * 149 + 'x')\n"
            "print('parse', round(time.monotonic() - t, 2) < 3, onc_parse('RE-{yyyy}-{seq:3}', 'RE-2026-007'), "
            "onc_parse('{client}-KV{seq:2}', 'Kunde-Eins-KV05'), onc_parse('RE-{seq}', 'x' * 400))", timeout=60)
check("parse True (7, None) (5, None) (None, None)" in out, "the number scheme parse is fast and still reads numbers " + out[-300:])

# ---------------------------------------------------------------- the personal office: receipts, DATEV duplicates
UWS = Fr.get(B + O + "/books").json()["upload_ws"]


def upload(s, name, data=None, mime="application/pdf", ws=None):
    r = s.post(B + "/api/docs", data={"ws": ws or UWS}, files={"files": (name, data or tiny_pdf(name), mime)})
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def receipt(s, name, amount, day=TODAY):
    nid = upload(s, name + ".pdf")
    done(s, nid)
    r1 = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day, "name": name})
    r2 = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True})
    assert r1.ok and r2.ok, (r1.text, r2.text)
    return nid


assert Fr.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}}).ok
R1, R2, R3 = receipt(Fr, "Lizenz Eins", "119.00"), receipt(Fr, "Lizenz Zwei", "59.50"), receipt(Fr, "Lizenz Drei", "23.80")
FAKE = upload(Fr, "Lizenz Kopie.pdf")
done(Fr, FAKE)
# a possible duplicate of a document that is no receipt (FAKE) and one of a receipt (R1)
sql("UPDATE doc_meta SET dup_of=?, dup_ok=0 WHERE node_id=?", (FAKE, R2), write=True)
sql("UPDATE doc_meta SET dup_of=?, dup_ok=0 WHERE node_id=?", (R1, R3), write=True)
P = f"?from={MONTH}-01&to={TODAY}"
r = Fr.get(B + O + "/datev/extf" + P)
bel = {x[10].strip('"') for x in (ln.split(";") for ln in r.content.decode("cp1252").split("\r\n")[2:-1])} if r.ok else set()
check(f"B{R1}" in bel and f"B{R2}" in bel and f"B{R3}" not in bel,
      f"DATEV: a duplicate stays out only when its original is a receipt ({r.status_code} {sorted(bel)})")

# ---------------------------------------------------------------- no-store on the downloads
for what, url in (("DATEV ZIP", O + "/datev/zip" + P), ("GoBD ZIP", O + "/gobd/export"),
                  ("meals CSV", O + f"/meals/report?from={MONTH}-01&to={TODAY}&format=csv"), ("equipment value CSV", O + "/equipment/value.csv")):
    r = Fr.get(B + url)
    check(r.ok and "no-store" in r.headers.get("Cache-Control", ""), f"{what}: not cached ({r.status_code} {r.headers.get('Cache-Control')} {r.text[:100] if not r.ok else ''})")

# ---------------------------------------------------------------- books export ZIP and the e-invoice view: the malware lock
ts = testclock.now().isoformat(timespec="seconds")


def infect(nid):
    ver = sql("SELECT MAX(no) FROM fs_versions WHERE node_id=?", (nid,))[0][0] or 0
    sql("INSERT INTO upload_scan(kind, ref_id, ver, org_id, state, sig, created_at) VALUES('fs',?,?,NULL,'infected','Test-Signatur',?) "
        "ON CONFLICT (kind, ref_id, ver) DO UPDATE SET state='infected', sig='Test-Signatur'", (nid, ver, ts), write=True)


def zip_receipts():
    r = Fr.get(B + O + f"/books/export?from={MONTH}-01&to={TODAY}&zip=1")
    assert r.ok, r.text[:200]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = [n for n in z.namelist() if n.startswith("receipts/")]
    csv = next(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".csv"))
    return names, csv


names0, _csv = zip_receipts()
check(any("Lizenz Drei" in n for n in names0), f"books export ZIP: the receipt files ({names0})")
infect(R3)
names1, csv1 = zip_receipts()
check(not any("Lizenz Drei" in n for n in names1) and len(names1) == len(names0) - 1 and "Lizenz Drei" in csv1,
      f"books export ZIP: a receipt file found infected stays out, its line stays ({names1})")
EI = upload(Fr, "rechnung.xml", UBL.encode(), "application/xml", ws="private")
d = done(Fr, EI)
check(d and d.get("einvoice") and Fr.get(B + f"/api/docs/{EI}/einvoice").status_code == 200, f"the e-invoice view ({d and d.get('state')})")
check(Ca.get(B + f"/api/docs/{EI}/einvoice").status_code == 404, "another person: 404 on the e-invoice view")
infect(EI)
r = Fr.get(B + f"/api/docs/{EI}/einvoice")
check(r.status_code == 403 and "Flyer" not in r.text, f"the e-invoice view of a file found infected is locked ({r.status_code})")

# ---------------------------------------------------------------- bank: two bookings at once on the same receipt
rows = [(TODAY, "Software Beispiel GmbH", f"Abo {i}", "-11,90") for i in range(8)]
csv = "Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n" + "".join(f"{de(d_)};{c_};{p_};{a_}\n" for d_, c_, p_, a_ in rows)
pv = Fr.post(B + K + "/import/preview", json={"text": csv}).json()
mp = {k: pv["guess"].get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
assert Fr.post(B + K + "/import", json={"text": csv, "filename": "konto.csv", "mapping": mp}).status_code == 201
TX = {t["purpose"]: t["id"] for t in Fr.get(B + K + "/tx?state=all").json()["items"]}
F1, F2 = sess("frida"), sess("frida")
wins = []
for rnd in range(4):
    rc = receipt(Fr, f"Hosting {rnd}", "11.90")
    res, gate = [], threading.Barrier(2)

    def match(s, tid, rc=rc, res=res, gate=gate):
        gate.wait()
        res.append(s.post(B + f"{K}/tx/{tid}/match", json={"kind": "receipt", "id": rc}).status_code)

    th = [threading.Thread(target=match, args=(s, TX[f"Abo {2 * rnd + i}"])) for i, s in enumerate((F1, F2))]
    for t in th:
        t.start()
    for t in th:
        t.join()
    n = sql("SELECT COUNT(*) FROM office_bank_tx WHERE match_kind='receipt' AND match_id=? AND deleted_at IS NULL", (rc,))[0][0]
    wins.append((sorted(res), n))
check(all(w == ([200, 409], 1) for w in wins), f"two bookings at once on one receipt: one wins, one 409 ({wins})")

# ---------------------------------------------------------------- GET has no side effects
cl = Fr.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
INV = Fr.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": TODAY, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
assert Fr.post(B + f"{D}/{INV}/finalize").ok
r = Fr.post(B + f"{D}/{INV}/peppol/refresh")
check(r.ok and "sends" in r.json(), f"the Peppol status fetch is a POST ({r.status_code} {r.text[:120]})")
check(Fr.get(B + f"{D}/{INV}/peppol?refresh=1").ok, "the Peppol view stays a plain GET")
check(Ca.post(B + f"{D}/{INV}/peppol/refresh").status_code == 404, "another organisation: 404 on the status fetch")
sql("INSERT INTO office_suppliers(org_id, account_no, name, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?,?)",
    (PB, "70001", "Alter Lieferant", ts, ts, "2020-01-01T00:00:00Z"), write=True)
SUP = sql("SELECT id FROM office_suppliers WHERE org_id=? AND account_no='70001'", (PB,))[0][0]
check(Fr.get(B + O + "/datev/suppliers").ok and sql("SELECT 1 FROM office_suppliers WHERE id=?", (SUP,)) == [(1,)],
      "reading the suppliers deletes nothing")
check(Fr.post(B + O + f"/datev/suppliers/{SUP}/restore").status_code == 404 and not sql("SELECT 1 FROM office_suppliers WHERE id=?", (SUP,)),
      "a supplier past the trash period is cleaned on the next write (restore: 404)")

# ---------------------------------------------------------------- letters: the follow-up task and a sealed subject
TICK = ("import json\nfrom kalmido.core.db import connect\nfrom kalmido.office.letterlinks import ltl_followup_tick\nc = connect()\n"
        "print('made', json.dumps(ltl_followup_tick(c, force=True)))\nc.close()")
LT = O + "/letters"
for who, s in (("organisation", A), ("person without an organisation", Fr)):
    L = s.post(B + LT, json={"subject": "Vertraulicher Betreff", "rcpt_name": "Amt Beispiel"}).json()
    assert s.post(B + f"{LT}/{L['id']}/sent", json={"followup_days": 14}).ok
    sql("UPDATE office_letters SET followup_due='2020-01-01' WHERE id=?", (L["id"],), write=True)
    out = in_ct(TICK)
    sealed = str(sql("SELECT subject FROM office_letters WHERE id=?", (L["id"],))[0][0]).startswith("kenc1:")
    tid = sql("SELECT followup_task_id FROM office_letters WHERE id=?", (L["id"],))[0][0]
    t = sql("SELECT title, content FROM tasks WHERE id=?", (tid,)) if tid else []
    check(t and (("Vertraulich" not in t[0][0] + t[0][1] and t[0][0] == "Follow-up: Letter") if sealed else "Vertraulich" in t[0][0]),
          f"{who}: the follow-up task keeps a sealed subject out (sealed {sealed}, {t and t[0][0]}) {out[-200:]}")

# ---------------------------------------------------------------- the move of a personal office with its own Peppol connection
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": FID}).json()["id"]
Fr.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
assert Fr.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": "Gamma Studio", **COMPANY}}).ok
r = Fr.put(B + PEP, json={"provider": "storecove", "account": "999", "api_key": "key-g"})
check(r.ok, "the organisation has its own Peppol connection " + r.text[:120])
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + O + "/move/org", json={"org": GAM, "confirm": True})
check(r.ok, f"the personal office moves although both have a Peppol connection ({r.status_code} {r.text[:300]})")
rows = dict(sql("SELECT org_id, provider FROM office_peppol WHERE org_id IN (?, ?)", (GAM, PB)))
check(rows.get(GAM) == "storecove" and rows.get(PB) == "custom", f"each area keeps its own connection ({rows})")
check(sql("SELECT account FROM office_peppol WHERE org_id=?", (GAM,)) == [("999",)], "the organisation's connection is unchanged")

print(f"p2306_d2_office_hardening: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
