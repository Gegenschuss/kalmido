#!/usr/bin/env python3
"""2.99.0 API tests, part C (#2195): a quotation accepted through its customer link prints the acceptance. Own container in
mode workspaces with org encryption on. Invented companies, people and figures only.
 - open link: the customer's PDF is the original (empty "Signature, stamp of the client" line, no acceptance box)
 - accepted: the customer's PDF (/s/q/<token>/pdf) and the app's PDF show the box "Accepted online by <name>", the time
   (UTC) and the SHA-256 of the accepted content (the signoff's doc_hash), without the empty signature line; the app's
   ?original=1 is the original (a quotation keeps no stored original: it is written from its snapshot); the accepted
   version is its own sealed file below the organisation's office folder
 - declined: the original (no box), in the app as well
 - another organisation: 404 for the app's PDF
 - the personal office of a person without an organisation (freelancer fixture): the same
usage: p299_c_api_test.py <datadir>      (P299C_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import glob
import os
import re
import subprocess
import sys
import time
import zlib

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
D = "/api/office/docs"
SIGN_LINE = "Signature, stamp of the client"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def anon(path):
    return requests.get(B + path, allow_redirects=False)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def pdf_hex(data):
    """The text of a PDF written by Kalmido: its content streams inflated (the text is in <hex> strings)."""
    out = b""
    # Kalmido ends a stream with "\nendstream": a compressed stream may itself end in a CR byte (1 in 256), "\r?" cut it off (CI red, 2.145.1 #2439)
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def in_pdf(data, text):
    return text.encode("cp1252").hex() in pdf_hex(data)


def quotation(s, title, finalise=False):
    r = s.post(B + D, json={"project_title": title, "lang": "en", "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG"]}})
    assert r.status_code == 201, r.text
    q = r.json()["id"]
    assert s.put(B + f"{D}/{q}/items", json={"items": [{"title": "Schnitt", "qty": 2, "rate": 900}]}).ok
    if finalise:
        r = s.post(B + f"{D}/{q}/finalize")
        assert r.ok, r.text
    assert s.post(B + f"{D}/{q}/status", json={"status": "sent"}).ok
    r = s.post(B + f"{D}/{q}/signoff", json={})
    assert r.ok, r.text
    return q, r.json()["url"].split("/s/q/")[1], r.json()["id"]


def decide(tok, do, name):
    pg = anon("/s/q/" + tok)
    d = {"f": form_key(pg.text), "name": name, "do": do}
    if do == "accept":
        d["ok"] = "1"
    else:
        d["reason"] = "Zu teuer"
    return requests.post(B + "/s/q/" + tok, data=d, allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"})


def accepted_box(pdf, name, h):
    return pdf[:4] == b"%PDF" and in_pdf(pdf, "Accepted online by") and in_pdf(pdf, name) and in_pdf(pdf, h) and not in_pdf(pdf, SIGN_LINE)


if os.environ.get("P299C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
A.put(B + "/api/office/settings", json={"currency": "EUR", "company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345",
                                                                             "city": "Musterstadt", "country": "DE"}})

# ---------------------------------------------------------------- a finalised quotation, accepted online
Q, TOK, SID = quotation(A, "Imagefilm Herbst", finalise=True)
pdf = anon(f"/s/q/{TOK}/pdf").content
check(pdf[:4] == b"%PDF" and in_pdf(pdf, SIGN_LINE) and not in_pdf(pdf, "Accepted online by"), "open link: the original with the empty signature line")
check(decide(TOK, "accept", "Max Muster").status_code == 303, "accepted")
H1 = sql("SELECT doc_hash FROM office_signoffs WHERE id=?", (SID,))[0][0]
check(len(H1) == 64, "setup: the signoff has the content hash")
pdf = anon(f"/s/q/{TOK}/pdf")
check(pdf.status_code == 200 and accepted_box(pdf.content, "Max Muster", H1), "customer: the PDF shows the acceptance (name, hash), no empty signature line")
check(in_pdf(pdf.content, "Time (UTC)"), "customer: the time (UTC)")
check(in_pdf(pdf.content, "SIMPLE ELECTRONIC SIGNATURE"), "customer: the kind of signature (the box's head)")
check("accepted" in pdf.headers.get("Content-Disposition", ""), f"customer: the file is named as accepted {pdf.headers.get('Content-Disposition')}")
acc = glob.glob(os.path.join(DATA, "office", str(ORG), f"doc{Q}-*.accepted-{SID}.pdf"))
check(len(acc) == 1, f"filing: the accepted version is its own file next to the original {acc}")
check(acc and open(acc[0], "rb").read()[:4] != b"%PDF", "filing: the accepted version is sealed at rest")
app = A.get(B + f"{D}/{Q}/pdf")
check(app.status_code == 200 and accepted_box(app.content, "Max Muster", H1), "app: the quotation's PDF is the accepted version")
app = A.get(B + f"{D}/{Q}/pdf?original=1")
check(app.status_code == 200 and in_pdf(app.content, SIGN_LINE) and not in_pdf(app.content, "Accepted online by"), "app: ?original=1 the original")
check(Ca.get(B + f"{D}/{Q}/pdf").status_code == 404, "another organisation: 404")

# ---------------------------------------------------------------- a draft quotation (no stored original), accepted
Q2, TOK2, SID2 = quotation(A, "Imagefilm Winter")
check(decide(TOK2, "accept", "Erika Beispiel").status_code == 303, "draft quotation: accepted")
H2 = sql("SELECT doc_hash FROM office_signoffs WHERE id=?", (SID2,))[0][0]
check(accepted_box(anon(f"/s/q/{TOK2}/pdf").content, "Erika Beispiel", H2), "draft quotation: the customer's PDF shows the acceptance")
check(accepted_box(A.get(B + f"{D}/{Q2}/pdf").content, "Erika Beispiel", H2), "draft quotation: the app's PDF as well")

# ---------------------------------------------------------------- declined: the original
Q3, TOK3, SID3 = quotation(A, "Imagefilm Frühling")
check(decide(TOK3, "decline", "Max Muster").status_code == 303, "declined")
pdf = anon(f"/s/q/{TOK3}/pdf").content
check(pdf[:4] == b"%PDF" and in_pdf(pdf, SIGN_LINE) and not in_pdf(pdf, "Accepted online by"), "declined: the customer's PDF is the original")
pdf = A.get(B + f"{D}/{Q3}/pdf").content
check(in_pdf(pdf, SIGN_LINE) and not in_pdf(pdf, "Accepted online by"), "declined: the app's PDF is the original")
check(not glob.glob(os.path.join(DATA, "office", str(ORG), f"doc{Q3}-*.accepted-*.pdf")), "declined: no accepted version filed")

# ---------------------------------------------------------------- the personal office of a person without an organisation
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.put(B + "/api/office/settings", json={"currency": "EUR", "company_fields": {"name": "Frida Film", "street": "Hafenweg 1", "zip": "20457",
                                                                              "city": "Hamburg", "country": "DE"}})
QF, TOKF, SIDF = quotation(Fr, "Imagefilm Privat", finalise=True)
check(not in_pdf(anon(f"/s/q/{TOKF}/pdf").content, "Accepted online by"), "personal office: open link, the original")
check(decide(TOKF, "accept", "Paula Privat").status_code == 303, "personal office: accepted")
HF = sql("SELECT doc_hash FROM office_signoffs WHERE id=?", (SIDF,))[0][0]
check(accepted_box(anon(f"/s/q/{TOKF}/pdf").content, "Paula Privat", HF), "personal office: the customer's PDF shows the acceptance")
check(accepted_box(Fr.get(B + f"{D}/{QF}/pdf").content, "Paula Privat", HF), "personal office: the app's PDF as well")
check(A.get(B + f"{D}/{QF}/pdf").status_code == 404, "personal office: not the organisation's")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
