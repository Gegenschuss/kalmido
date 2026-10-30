#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.424.0 B (#3450) API tests: receipts by mail without a PDF attached. Own container (start.sh + the IMAP stub for the
mail input). Invented companies, figures, addresses (@example.com / example.org) and files only (every PDF is made here).
freelancer-matrix: office
 - link detection (docs/maillink.py ml_links / ml_pick): "Rechnung herunterladen" to a known invoice host, a generic
   invoice link ending in .pdf, a bare URL in the text part; not: http, unsubscribe, a known host without invoice words, an
   invoice word without a PDF; at most three links per mail
 - the download (ml_fetch through the SSRF guard of the calendars): http refused unless the test switch, loopback /
   private / link-local (metadata) / ULA / a name resolving to loopback refused ("blocked") with the real download, a
   user:password URL refused; against a stub server on 127.0.0.1 (let through only for this test): a PDF taken with its
   file name (also after a redirect on the same host), a login page / a fake PDF -> not_pdf, 401 -> auth, too large ->
   too_large, a redirect to another host over http -> refused
 - the mail import (docs_ingest via docs_mail_import, downloads faked): a link PDF becomes a document (source mail), the same
   invoice as a PDF attachment (other bytes) is marked as duplicate (supplier + invoice number + amount), the same PDF again
   from a second mail is not stored twice, the same mail twice gives one document, a mail with an attachment downloads
   nothing, a link that needs a login -> the mail itself (.eml) tagged "Receipt link needs a login", a mail without file
   and link -> the mail itself without the tag; the documents run through the recognition (invoice number read)
 - the forwarding address in the office settings (GET / POST /api/office/receipt-mail): the personal office of a person
   without an organisation and the company office are separate addresses, equal to the documents settings' address of that
   space, POST keeps the address, renew makes a new one (the old one stops), agents 403
 - 2.424.0 B2 (#3450, review findings): only the real invoice hosts count as known (no google.com / paypal.com / apple.com);
   a server sending its headers drop by drop ends at the mail's deadline (cal_http until, "timeout"); the downloads of
   one mail stop at ML_MAIL_DEADLINE; the hourly budget per document address (30 downloads, 60 mails without a file, a new
   hour starts again) and a spent budget downloads / files nothing; the IMAP poll downloads BEFORE the database work
   (outside the gate, with the deadline); an inline logo does not stop the link (an attached image does); a member
   with the level "own" in Receipts sees the own forwarding address
usage: p2424_b_api_test.py <datadir>"""
import base64
import email.message
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # noqa: E402  shared helpers (tests/kt.py)
MAILENV = (" -e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0"
           " -e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600 -e KALMIDO_DOCS_SCAN_S=2")


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def py(code):
    """Runs code inside the test container (the app's modules importable); -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + MAILENV),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients,docs,files"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)

# ---------------------------------------------------------------- 1. link detection + the download (inside the container)
PROBE = r'''
import email.message, http.server, json, threading, app
from kalmido.docs import maillink as ML
from kalmido.calendars.subscriptions import CalError, cal_ip_public
out = {}
def mk(text, html=None):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "billing@example.com", "tasks@example.test", "Your invoice"
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    return m
H = ('<p>Danke</p><a href="https://pay.stripe.com/invoice/acct_1/invst_2/pdf?s=em&amp;x=1">Rechnung herunterladen</a>'
     '<a href="https://example.com/unsubscribe">Abmelden</a><a href="http://example.com/rechnung.pdf">Rechnung (http)</a>'
     '<a href="https://shop.example.com/files/Rechnung-2026-17.pdf">hier</a><a href="https://www.google.com/">Google</a>'
     '<a href="https://example.com/blog/invoice-tips">Invoice tips</a>')
out["links"] = ML.ml_links(mk("Invoice PDF: https://billing.example.org/inv/123.pdf\nNews: https://example.org/news", H))
out["many"] = len(ML.ml_links(mk("\n".join(f"Rechnung {i}: https://example.org/r/{i}.pdf" for i in range(6)))))
out["none"] = ML.ml_links(mk("Hallo, bis bald. https://example.org/blog"))
out["pick"] = [ML.ml_pick(u, t) for u, t in (("https://my.paddle.com/receipt/123", "View receipt"), ("https://example.org/a.pdf", ""),
               ("https://example.org/invoice/7", "Download"), ("https://example.org/facture.pdf", ""), ("https://pay.stripe.com/x", "Open"))]
out["ip"] = [cal_ip_public(a) for a in ("169.254.169.254", "10.1.2.3", "172.16.5.4", "127.0.0.1", "fd00::1", "fe80::1",
             "::ffff:127.0.0.1", "100.64.0.1", "0.0.0.0", "93.184.216.34")]
def code(fn):
    try:
        n, d = fn()
        return ["ok", n, d[:5].decode("latin-1")]
    except CalError as e:
        return [e.code]
PDF = b"%PDF-1.4\n% stub invoice\n" + b"0" * 200
class Hd(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        p = self.path
        if p == "/ok.pdf":
            self.send(200, "application/pdf", PDF, {"Content-Disposition": 'attachment; filename="Rechnung RE-1.pdf"'})
        elif p == "/noname":
            self.send(200, "application/octet-stream", PDF)
        elif p == "/login":
            self.send(200, "text/html", b"<html><form>Login</form></html>")
        elif p == "/fake.pdf":
            self.send(200, "application/pdf", b"<html>not a pdf</html>")
        elif p == "/big.pdf":
            self.send(200, "application/pdf", PDF + b"1" * 5000)
        elif p == "/deny":
            self.send(401, "text/plain", b"no")
        elif p == "/redir-same":
            self.send(302, "text/plain", b"", {"Location": "/ok.pdf"})
        elif p == "/redir-other":
            self.send(302, "text/plain", b"", {"Location": f"http://localhost:{PORT}/ok.pdf"})
        elif p == "/redir-meta":
            self.send(302, "text/plain", b"", {"Location": "http://169.254.169.254/latest/meta-data/"})
        else:
            self.send(404, "text/plain", b"")
    def send(self, st, ct, body, hd=None):
        self.send_response(st)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (hd or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
U = f"http://127.0.0.1:{PORT}"
ok = lambda u: ML.ml_get(u, allow=frozenset({("127.0.0.1", PORT)}))
out["http_refused"] = code(lambda: ML.ml_fetch(U + "/ok.pdf"))
out["loopback"] = code(lambda: ML.ml_fetch(U + "/ok.pdf", https_only=False))
out["v6loop"] = code(lambda: ML.ml_fetch(f"http://[::1]:{PORT}/ok.pdf", https_only=False))
out["blocked"] = [code(lambda u=u: ML.ml_fetch(u)) for u in ("https://169.254.169.254/latest/r.pdf", "https://10.0.0.1/r.pdf",
                  "https://[fd00::1]/r.pdf", "https://localhost/r.pdf", "https://[::ffff:127.0.0.1]/r.pdf")]
out["userinfo"] = code(lambda: ML.ml_fetch("https://user:pw@example.com/r.pdf"))
out["stub"] = {k: code(lambda k=k: ML.ml_fetch(U + k, get=ok, https_only=False)) for k in
               ("/ok.pdf", "/noname", "/login", "/fake.pdf", "/deny", "/redir-same", "/redir-other", "/redir-meta", "/missing")}
ML.ML_MAX_BYTES = 1000
out["big"] = code(lambda: ML.ml_fetch(U + "/big.pdf", get=ok, https_only=False))
print(json.dumps(out))
'''
j = py(PROBE)
L = set(j.get("links") or [])
check(L == {"https://pay.stripe.com/invoice/acct_1/invst_2/pdf?s=em&x=1", "https://shop.example.com/files/Rechnung-2026-17.pdf",
            "https://billing.example.org/inv/123.pdf"}, f"links: known host + generic .pdf + bare URL, nothing else ({j.get('links')})")
check(j.get("many") == 3, f"at most three links per mail ({j.get('many')})")
check(j.get("none") == [], f"a mail without invoice links: none ({j.get('none')})")
check(j.get("pick") == [True, False, False, True, False], f"pick: paddle receipt, no words, no pdf, facture.pdf, stripe without words ({j.get('pick')})")
check(j.get("ip") == [False] * 9 + [True], f"SSRF guard: metadata, private, loopback, ULA, link-local, mapped, CGNAT, 0.0.0.0 refused ({j.get('ip')})")
check(j.get("http_refused") == ["config"], f"plain http refused ({j.get('http_refused')})")
check(j.get("loopback") == ["blocked"] and j.get("v6loop") == ["blocked"], f"loopback (v4 / v6) refused by the real download ({j.get('loopback')} {j.get('v6loop')})")
check(j.get("blocked") == [["blocked"]] * 5, f"https to metadata / private / ULA / localhost / mapped loopback: blocked ({j.get('blocked')})")
check(j.get("userinfo") == ["config"], "a URL with user:password refused")
st = j.get("stub") or {}
check(st.get("/ok.pdf") == ["ok", "Rechnung RE-1.pdf", "%PDF-"], f"stub: a PDF with its file name ({st.get('/ok.pdf')})")
check(st.get("/noname") == ["ok", "invoice.pdf", "%PDF-"], f"stub: octet-stream PDF without a name -> invoice.pdf ({st.get('/noname')})")
check(st.get("/redir-same") == ["ok", "Rechnung RE-1.pdf", "%PDF-"], f"stub: a redirect on the same host is followed ({st.get('/redir-same')})")
check(st.get("/login") == ["not_pdf"] and st.get("/fake.pdf") == ["not_pdf"], f"stub: login page / fake PDF -> not_pdf ({st.get('/login')} {st.get('/fake.pdf')})")
check(st.get("/deny") == ["auth"] and st.get("/missing") == ["not_found"], f"stub: 401 -> auth, 404 -> not_found ({st.get('/deny')} {st.get('/missing')})")
check(st.get("/redir-other") == ["redirect"] and st.get("/redir-meta") == ["redirect"],
      f"stub: a redirect to another host (localhost, metadata) over http refused ({st.get('/redir-other')} {st.get('/redir-meta')})")
check(j.get("big") == ["too_large"], f"size limit ({j.get('big')})")

# ---------------------------------------------------------------- 2. the forwarding address in the office settings
A.patch(B + "/api/settings", json={"workspace": "private"})
for s in (Fr, A):
    assert s.get(B + "/api/office/settings").ok  # the personal office is there
check(Fr.get(B + "/api/office/receipt-mail").json() == {"enabled": True, "address": "", "ws": "private"}, "freelancer: no address yet, personal office = private")
r = Fr.post(B + "/api/office/receipt-mail", json={})
FADDR = r.json().get("address", "")
check(r.ok and FADDR.startswith("tasks+d") and r.json()["ws"] == "private", f"freelancer: address made ({r.text[:160]})")
check(Fr.post(B + "/api/office/receipt-mail", json={}).json()["address"] == FADDR, "POST again keeps the address")
check(Fr.get(B + "/api/docs/settings?ws=private").json()["mail"]["address"] == FADDR, "= the address of the documents settings (private)")
r = A.post(B + "/api/office/receipt-mail", json={})
A_PRIV = r.json().get("address", "")
check(r.ok and r.json()["ws"] == "private" and A_PRIV and A_PRIV != FADDR, f"alice's personal office: her own private address ({r.text[:160]})")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + "/api/office/receipt-mail", json={})
A_ORG = r.json().get("address", "")
check(r.ok and r.json()["ws"] == f"org:{ORG}" and A_ORG and A_ORG != A_PRIV, f"company office: a separate address ({r.text[:160]})")
check(A.get(B + f"/api/docs/settings?ws=org:{ORG}").json()["mail"]["address"] == A_ORG, "= the documents settings' address of Alpha")
r = A.post(B + "/api/office/receipt-mail", json={"renew": True})
check(r.ok and r.json()["address"] not in ("", A_ORG), "renew: a new address")
OLD_ORG, A_ORG = A_ORG, r.json()["address"]
tk = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
check(tk.ok and tk.json().get("token"), "an agent made " + tk.text[:120])
if tk.ok and tk.json().get("token"):
    ag = requests.Session()
    ag.headers.update({"Authorization": "Bearer " + tk.json()["token"], **H})
    check(ag.get(B + "/api/office/receipt-mail").status_code == 403 and ag.post(B + "/api/office/receipt-mail", json={}).status_code == 403,
          "an agent token: no address (403)")

# ---------------------------------------------------------------- 3. the mail import (downloads faked inside the container)
INV = ["Beispiel Software GmbH · Hauptstraße 1 · 12345 Musterstadt", "Rechnung", "Rechnungs-Nr.: INV-4711", "Datum: 03.10.2026",
       "Abo Pro Oktober      100,00 EUR", "zzgl. 19 % MwSt.      19,00 EUR", "Gesamtbetrag         119,00 EUR", "USt-IdNr. DE987654321"]
P_LINK = text_pdf(INV)
P_ATT = text_pdf(INV + ["Kopie aus dem Kundenkonto"])
IMPORT = r'''
import base64, email.message, email.policy, json, app
from kalmido.core.db import connect
from kalmido.docs import ingest as I, maillink as ML
ARGS = json.loads(%r)
PDFS = {k: base64.b64decode(v) for k, v in ARGS["pdfs"].items()}
calls = []
def fake(url, allow=frozenset(), until=None):  # 2.424.0 B2 (#3450): ml_get takes the mail's deadline (until)
    calls.append(url)
    if "login" in url:
        return 200, {"Content-Type": "text/html"}, b"<html>Bitte anmelden</html>", url
    return 200, {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="Invoice-INV-4711.pdf"'}, PDFS["link"], url
ML.ml_get = fake
I.docs_kick = lambda: None  # the server's queue recognises them (this process ends at once)
out = {}
for m in ARGS["mails"]:
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = "billing@example.com", m["to"], m["subject"], m["mid"]
    msg.set_content(m["text"])
    if m.get("html"):
        msg.add_alternative(m["html"], subtype="html")
    if m.get("att"):
        msg.add_attachment(PDFS[m["att"]], maintype="application", subtype="pdf", filename="rechnung.pdf")
    raw = bytes(msg)
    n0 = len(calls)
    c = connect()
    try:
        nid = I.docs_mail_import(c, email.message_from_bytes(raw, policy=email.policy.default), raw)
    finally:
        c.close()
    out[m["key"]] = {"nid": nid, "calls": len(calls) - n0}
print(json.dumps(out))
'''
LINK_HTML = '<p>Danke für deinen Einkauf.</p><a href="https://pay.stripe.com/invoice/acct_9/inv_1/pdf">Rechnung herunterladen</a>'
MAILS = [
    {"key": "link", "to": FADDR, "mid": "<p2424b-1@example.com>", "subject": "Deine Rechnung", "text": "Danke.", "html": LINK_HTML},
    {"key": "again", "to": FADDR, "mid": "<p2424b-1@example.com>", "subject": "Deine Rechnung", "text": "Danke.", "html": LINK_HTML},
    {"key": "att", "to": FADDR, "mid": "<p2424b-2@example.com>", "subject": "Rechnung als PDF", "text": "Anbei. https://pay.stripe.com/invoice/x/y/pdf", "att": "att"},
    {"key": "second", "to": FADDR, "mid": "<p2424b-3@example.com>", "subject": "Erinnerung: Rechnung", "text": "Danke.", "html": LINK_HTML},
    {"key": "login", "to": FADDR, "mid": "<p2424b-4@example.com>", "subject": "Fwd: Your receipt",
     "text": "Download invoice: https://billing.example.org/login/invoice/9.pdf"},
    {"key": "plain", "to": FADDR, "mid": "<p2424b-5@example.com>", "subject": "Bestätigungscode", "text": "Dein Code lautet 482913."},
    {"key": "org", "to": A_ORG, "mid": "<p2424b-6@example.com>", "subject": "Rechnung Alpha", "text": "Danke.", "html": LINK_HTML},
    {"key": "oldorg", "to": OLD_ORG, "mid": "<p2424b-7@example.com>", "subject": "Alte Adresse", "text": "Danke.", "html": LINK_HTML},
]
ARGS = json.dumps({"pdfs": {"link": base64.b64encode(P_LINK).decode(), "att": base64.b64encode(P_ATT).decode()}, "mails": MAILS})
j = py(IMPORT % ARGS)
nid = lambda k: (j.get(k) or {}).get("nid")
calls = lambda k: (j.get(k) or {}).get("calls")
DL, DA = nid("link"), nid("att")


def doc(s, i):
    r = s.get(B + f"/api/docs/{i}")
    return r.json() if r.ok else None


def done(s, i, secs=90):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, i)), secs)


check(DL and calls("link") == 1, f"a link mail: one download, one document ({j.get('link')})")
d = done(Fr, DL) if DL else None
check(d and d["name"] == "Invoice-INV-4711.pdf" and d["source"] == "mail" and d["ws"] == f"u{FID}",
      f"the link PDF is a document of the private space ({d and (d['name'], d['source'], d['ws'])})")
check(d and d["state"] == "done" and (d.get("extracted") or {}).get("invoice_no") == "INV-4711",
      f"and runs through the recognition (invoice number read: {d and (d['state'], (d.get('extracted') or {}).get('invoice_no'))})")
check(dbx("SELECT ext_id FROM doc_meta WHERE node_id=?", (DL,)) == [("mail:<p2424b-1@example.com>:link:0",)], "ext_id mail:<id>:link:0")
check(nid("again") == DL, f"the same mail twice: the same document ({j.get('again')})")
check(DA and DA != DL and calls("att") == 0, f"a mail with a PDF attached downloads nothing ({j.get('att')})")
da = done(Fr, DA) if DA else None
check(da and (da.get("duplicate_of") or {}).get("id") == DL,
      f"the same invoice as attachment (other bytes): duplicate of the link PDF ({da and da.get('duplicate_of')})")
check(nid("second") == DL, f"the same PDF from a second mail: not stored again ({j.get('second')})")
DLG = nid("login")
dl = done(Fr, DLG) if DLG else None
check(dl and dl["name"].endswith(".eml") and dl["name"] == "Your receipt.eml" and calls("login") == 1,
      f"a link that needs a login: the mail itself is the document ({dl and dl['name']}, {calls('login')})")
check(dl and "Receipt link needs a login" in [t["name"] for t in dl.get("tags") or []],
      f"tagged 'Receipt link needs a login' ({dl and dl.get('tags')})")
check(dl and (dl.get("text") or "").startswith("Receipt link needs a login"), "the hint stands first in its text")
DP = nid("plain")
dp = done(Fr, DP) if DP else None
check(dp and dp["name"] == "Bestätigungscode.eml" and not dp.get("tags") and "482913" in (dp.get("text") or "") and calls("plain") == 0,
      f"a mail without file and link: the mail itself, no tag, no download ({dp and (dp['name'], dp.get('tags'))})")
DO = nid("org")
check(DO and dbx("SELECT org_id FROM fs_nodes WHERE id=?", (DO,)) == [(ORG,)], f"the company address: a document of Alpha ({j.get('org')})")
check(Fr.get(B + f"/api/docs/{DO}").status_code == 404, "the freelancer does not see Alpha's document")
check(not nid("oldorg") and calls("oldorg") == 0, f"the renewed-away address takes nothing in, downloads nothing ({j.get('oldorg')})")
check(not dbx("SELECT 1 FROM tasks WHERE tt_id LIKE 'mail:<p2424b-%'"), "no task from a document mail")

# ---------------------------------------------------------------- 4. 2.424.0 B2 (#3450): the review findings
B2 = r"""
import base64, email.message, email.policy, http.server, json, threading, time, app
from kalmido.core.db import connect, now_iso
from kalmido.core.pg import system_ctx
from kalmido.accounts.session import GATE
from kalmido.docs import ingest as I, maillink as ML
from kalmido.integrations import mail as MI
from kalmido.calendars.subscriptions import CalError
ARGS = json.loads(%r)
PDFS = {k: base64.b64decode(v) for k, v in ARGS["pdfs"].items()}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
I.docs_kick = lambda: None
out = {}
tok = lambda a: a.split("+", 1)[1].split("@", 1)[0]
# (1c) known hosts: exactly the hosts that serve the invoice
out["hosts"] = [ML.ml_pick(u, t) for u, t in (("https://payments.google.com/invoice/7", "View invoice"),
                ("https://www.paypal.com/invoice/p/x", "Invoice"), ("https://apps.apple.com/receipt/1", "Receipt"),
                ("https://invoice.stripe.com/i/acct_1/x", "Download invoice"), ("https://my.paddle.com/receipt/1", "Receipt"))]
# (2) a server that drips its headers: the deadline ends it (connect + header phase too)
class Drip(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        try:
            self.wfile.write(b"HTTP/1.1 200 OK\r\n")
            self.wfile.flush()
            for _ in range(600):
                self.wfile.write(b"X")
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
srv.daemon_threads = True
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
t0 = time.monotonic()
try:
    ML.ml_get(f"http://127.0.0.1:{PORT}/r.pdf", allow=frozenset({("127.0.0.1", PORT)}), until=time.monotonic() + 2)
    out["drip"] = ["ok"]
except CalError as e:
    out["drip"] = [e.code]
out["drip_s"] = round(time.monotonic() - t0, 1)
# (2) all the downloads of one mail end at ML_MAIL_DEADLINE
def mk(to, mid, html=None, text="Danke.", att=None, logo=False, photo=False):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "billing@example.com", to, "Your invoice", mid
    m.set_content(text)
    if html:
        m.add_alternative(html + ('<img src="cid:logo">' if logo else ""), subtype="html")  # 2.424.0 (#3450): the HTML shows the logo
        if logo:
            m.get_payload()[1].add_related(PNG, "image", "png", cid="<logo>", filename="logo.png", disposition="inline")
    if att:
        m.add_attachment(PNG, maintype="image", subtype="png", filename="scan.png")
    if photo:  # 2.424.0 (#3450): iPhone Mail sends a photographed receipt inline with a file name, not shown by cid
        m.add_attachment(PNG + bytes(150_000), maintype="image", subtype="png", filename="IMG_1234.png", disposition="inline")
    return m
slow = []
def slow_get(u):
    slow.append(u)
    time.sleep(0.6)
    return 200, {"Content-Type": "text/html"}, b"<html>login</html>", u
ML.ML_MAIL_DEADLINE = 1
three = mk(ARGS["f"], "<p2424b2-0@example.com>", text="\n".join(f"Rechnung {i}: https://example.org/r/{i}.pdf" for i in range(3)))
ML.ml_collect(three, get=slow_get)
out["slow"] = len(slow)
ML.ML_MAIL_DEADLINE = 40
# (1a) the hourly budget of one document address
T = tok(ARGS["a_priv"])
c = connect()
try:
    with system_ctx(c):
        out["b_links"] = [ML.ml_budget(c, T, "links", 25), ML.ml_budget(c, T, "links", 25), ML.ml_budget(c, T, "links", 1)]
        out["b_eml"] = sum(ML.ml_budget(c, T, "eml") for _ in range(61))
        c.execute("UPDATE doc_mail SET hits_hour='2000-01-01T00' WHERE token=?", (T,))
        out["b_hour"] = [ML.ml_budget(c, T, "links", 3), ML.ml_budget(c, T, "eml")]
        c.execute("UPDATE doc_mail SET hits_hour=?, hits_links=30, hits_eml=60 WHERE token=?", (now_iso()[:13], T))
    c.commit()
finally:
    c.close()
calls = []
def fake(url, allow=frozenset(), until=None):
    calls.append((GATE.active, until is not None))
    return 200, {"Content-Type": "application/pdf"}, PDFS["pre"], url
ML.ml_get = fake
def imp(m, pre=None):
    raw = bytes(m)
    c = connect()
    try:
        return I.docs_mail_import(c, email.message_from_bytes(raw, policy=email.policy.default), raw, pre)
    finally:
        c.close()
LH = '<p>Danke.</p><a href="https://invoice.stripe.com/i/acct_7/inv_7">Download invoice</a>'
spent = mk(ARGS["a_priv"], "<p2424b2-1@example.com>", LH)
pre = MI.mail_import(None, bytes(spent))
out["spent"] = {"pre": [len(pre[0]), len(pre[1])], "calls": len(calls), "nid": imp(spent, pre)}
# (2) the IMAP poll: the download runs before the database work (outside the gate), with the mail's deadline
open("/data/mail/in/901.eml", "wb").write(bytes(mk(ARGS["f"], "<p2424b2-2@example.com>", LH)))
out["poll"] = MI.mail_poll_once()
out["poll_calls"] = calls[:]
# (3) an inline logo is no receipt: the link is followed; an attached image is one: no download
PDFS["pre"] = PDFS["logo"]
n0 = len(calls)
out["logo"] = {"nid": imp(mk(ARGS["f"], "<p2424b2-3@example.com>", LH, logo=True)), "calls": len(calls) - n0}
n0 = len(calls)
out["attimg"] = {"nid": imp(mk(ARGS["f"], "<p2424b2-4@example.com>", LH, att=True)), "calls": len(calls) - n0}
n0 = len(calls)
out["photo"] = {"nid": imp(mk(ARGS["f"], "<p2424b2-6@example.com>", LH, photo=True)), "calls": len(calls) - n0}
print(json.dumps(out))
"""
ARGS2 = json.dumps({"f": FADDR, "a_priv": A_PRIV, "pdfs": {"pre": base64.b64encode(text_pdf(["Rechnung", "Rechnungs-Nr.: B2-1"])).decode(),
                    "logo": base64.b64encode(text_pdf(["Rechnung", "Rechnungs-Nr.: B2-2"])).decode()}})
j = py(B2 % ARGS2)
check(j.get("hosts") == [False, False, False, True, True],
      f"known hosts: only the invoice hosts (not payments.google.com / paypal.com / apple.com) ({j.get('hosts')})")
check(j.get("drip") == ["timeout"] and (j.get("drip_s") or 99) < 8,
      f"headers dripping: ended at the deadline ({j.get('drip')}, {j.get('drip_s')} s)")
check(j.get("slow") in (1, 2), f"the downloads of one mail stop at the mail's deadline ({j.get('slow')} of 3)")
check(j.get("b_links") == [25, 5, 0] and j.get("b_eml") == 60, f"budget per address and hour: 30 downloads, 60 mails ({j.get('b_links')} {j.get('b_eml')})")
check(j.get("b_hour") == [3, 1], f"a new hour: the budget starts again ({j.get('b_hour')})")
sp = j.get("spent") or {}
check(sp.get("pre") == [0, 0] and sp.get("calls") == 0 and not sp.get("nid"),
      f"budget spent: the link not fetched and not counted (no 'needs a login' tag), the mail not filed ({sp})")  # 2.424.0 (#3450): review N2
check(not dbx("SELECT 1 FROM doc_meta WHERE ext_id LIKE 'mail:<p2424b2-1@%'"), "budget spent: no document")
check(j.get("poll") == 1 and j.get("poll_calls") == [[0, True]],
      f"IMAP poll: one download, outside the gate (no transaction), with the deadline ({j.get('poll')} {j.get('poll_calls')})")
check(dbx("SELECT count(*) FROM doc_meta WHERE ext_id='mail:<p2424b2-2@example.com>:link:0'") == [(1,)], "IMAP poll: the link PDF is a document")
lg = j.get("logo") or {}
check(lg.get("calls") == 1 and lg.get("nid") and dbx("SELECT ext_id FROM doc_meta WHERE node_id=?", (lg.get("nid"),)) == [("mail:<p2424b2-3@example.com>:link:0",)],
      f"an inline logo: the link is still followed, the PDF is the document ({lg})")
ai = j.get("attimg") or {}
check(ai.get("calls") == 0 and ai.get("nid") and dbx("SELECT ext_id FROM doc_meta WHERE node_id=?", (ai.get("nid"),)) == [("mail:<p2424b2-4@example.com>:0",)],
      f"an attached image: it is the receipt, no download ({ai})")
ph = j.get("photo") or {}
check(ph.get("calls") == 0 and ph.get("nid") and dbx("SELECT ext_id FROM doc_meta WHERE node_id=?", (ph.get("nid"),)) == [("mail:<p2424b2-6@example.com>:0",)],
      f"an inline photo with a file name (iPhone Mail): it is the receipt, no download ({ph})")  # 2.424.0 (#3450): review N1
# (5) the level "own" in Receipts: the own forwarding address
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/office/rights/people/{r.json()['id']}", json={"groups": ["tpl:staff"]}).ok
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
r = Bo.get(B + "/api/office/receipt-mail")
check(r.status_code == 200 and r.json().get("ws") == f"org:{ORG}", f"group Staff (receipts: own): GET receipt-mail 200 ({r.status_code} {r.text[:120]})")

print(f"p2424_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
