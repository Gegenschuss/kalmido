#!/usr/bin/env python3
"""2.153.0 API tests, part A (#2028, office: correspondence -- letters), own container (start.sh, org encryption on).
Invented companies, people and addresses only.
tenant-matrix: office
freelancer-matrix: office
 - a draft letter: recipient from a client of the office (name + address lines + e-mail frozen, the contact person as
   "z. Hd." on request) or an address book contact the person sees in the office's space; date today, greeting / signer
   from the profile; change the draft; the list without the text, filters status / client / search
 - recipients: clients and contacts of the office's space only (another organisation's / a private book: not offered,
   contact_id of them 404)
 - PDF: %PDF, sender line (ledger.ofx_sender_line), recipient, subject, reference line, a draft says ENTWURF
 - sent: status, sent_at, follow-up date, the PDF filed once into the documents space (folder of the client; without a
   client the folder "Korrespondenz"); a sent letter cannot be changed (409) nor sent again; delivered + its undo
 - copy = a new draft; save as template (kind letter) and a new letter from it with the variables filled
 - profile: greeting, name, signature picture (PNG / JPEG <= 300 KB; others 400), only in the writer's letters
 - archive + restore (the undo); texts and the picture encrypted at rest
 - rights: an organisation member 403, an agent 403, another organisation 404; a person without organisation (personal
   office, freelancer fixture) uses everything with private clients and private address books
usage: p2106_a_api_test.py <datadir>      (P2106A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import datetime
import os
import re
import struct
import subprocess
import sys
import time
import zlib

import dbx as dbxm
import requests
from freelancer_fixture import freelancer
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,contacts,files"
O = "/api/office"
LT = O + "/letters"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def pdf_hex(data):
    """The text of a PDF written by Kalmido: its content streams inflated (the text is in <hex> strings)."""
    out = b""
    # 2.294.0 (#3155): no "\r?" before endstream - a compressed stream may itself end in a CR byte (as p293_a, 2.145.1 #2439)
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def in_pdf(data, text):
    return text.encode("cp1252").hex() in pdf_hex(data)


def png(w=40, h=12):
    """A small grey PNG (a stand-in for a signature picture)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes([90, 90, 90]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


if os.environ.get("P2106A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345",
                                                                                   "city": "Musterstadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg", "country": "DE",
                                       "contact": "Erika Beispiel", "email": "post@kunde-eins.example.com"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
BK = A.post(B + "/api/books", json={"name": "Behörden", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/contacts", json={"book_id": BK, "given": "Max", "family": "Muster", "org": "Finanzamt Musterstadt",
                                       "addresses": [{"street": "Amtsweg 3", "code": "12345", "city": "Musterstadt", "country": "DE"}],
                                       "emails": [{"value": "poststelle@finanzamt.example.com"}]})
assert r.status_code == 201, r.text
CT = r.json()["id"]
BKP = A.post(B + "/api/books", json={"name": "Privat", "org_id": None}).json()["id"]  # Alice's private book: not of the office area
CTP = A.post(B + "/api/contacts", json={"book_id": BKP, "fn": "Tante Privat"}).json()["id"]
BK2 = Ca.post(B + "/api/books", json={"name": "Fremd", "org_id": ORG2}).json()["id"]
CT2 = Ca.post(B + "/api/contacts", json={"book_id": BK2, "fn": "Fremdkontakt"}).json()["id"]

# ---------------------------------------------------------------- rights first
check(Bo.get(B + LT).status_code == 403 and Bo.post(B + LT, json={}).status_code == 403, "an organisation member: 403")
check(requests.get(B + LT, headers=AGH).status_code == 403 and requests.post(B + LT, json={}, headers=AGH).status_code == 403, "an agent token: 403")
check(requests.get(B + LT, headers=H).status_code == 401, "signed out: 401")

# ---------------------------------------------------------------- recipients
rc = A.get(B + LT + "/recipients").json()["recipients"]
cli = [x for x in rc if x["kind"] == "client" and x["client_id"] == CL]
check(cli and cli[0]["rcpt_name"] == "Kunde Eins GmbH" and cli[0]["rcpt_address"] == "Kundenweg 5\n20000 Hamburg"
      and cli[0]["rcpt_email"] == "post@kunde-eins.example.com", f"recipient: the client with address lines and e-mail {cli[:1]}")
check(any(x.get("client_id") == CL and re.match(r"(z\. Hd\.|Attn\.) Erika Beispiel\n", x["rcpt_address"]) for x in rc), "recipient: the contact person as z. Hd.")
ct = [x for x in rc if x["kind"] == "contact" and x["contact_id"] == CT]
check(ct and ct[0]["rcpt_name"] == "Finanzamt Musterstadt" and ct[0]["rcpt_address"] == "Max Muster\nAmtsweg 3\n12345 Musterstadt"
      and ct[0]["rcpt_email"] == "poststelle@finanzamt.example.com", f"recipient: the address book contact of the organisation {ct[:1]}")
check(not any(x.get("contact_id") in (CTP, CT2) for x in rc) and not any(x.get("client_id") == CL2 for x in rc),
      "recipients: no private book, no other organisation's contact / client")
q = A.get(B + LT + "/recipients?q=finanzamt").json()["recipients"]
check([x.get("contact_id") for x in q] == [CT], f"recipients: search {q}")

# ---------------------------------------------------------------- a draft
today = testclock.today().isoformat()
r = A.post(B + LT, json={"client_id": CL, "subject": "Kündigung Rahmenvertrag", "body": "Sehr geehrte Damen und Herren,\n\nhiermit kündigen wir.\n\n- Punkt eins\n- Punkt zwei",
                         "ref_line": "Ihr Schreiben vom 01.10.2026"})
check(r.status_code == 201, f"a new letter ({r.status_code} {r.text[:200]})")
L1 = r.json()
check(L1["status"] == "draft" and L1["letter_date"] == today and L1["rcpt_name"] == "Kunde Eins GmbH" and L1["rcpt_address"] == "Kundenweg 5\n20000 Hamburg"
      and L1["rcpt_email"] == "post@kunde-eins.example.com", f"the recipient snapshot from the client {L1}")
check(L1["greeting"] in ("Mit freundlichen Grüßen", "Kind regards") and L1["sign_name"] == "Alice Admin" and L1["lang"] == "de" and L1["sign_image"] == 0,
      f"greeting / signer by default {L1['greeting']} {L1['sign_name']}")
check(A.post(B + LT, json={"client_id": CL2}).status_code == 404 and A.post(B + LT, json={"contact_id": CT2}).status_code == 404
      and A.post(B + LT, json={"contact_id": CTP}).status_code == 404, "another organisation's client / contact, a private contact: 404")
check(A.post(B + LT, json={"channel": "pigeon"}).status_code == 400 and A.post(B + LT, json={"letter_date": "19.10.2026"}).status_code == 400,
      "a bad channel / date: 400")
r = A.post(B + LT, json={"contact_id": CT, "subject": "Einspruch Bescheid"})
L2 = r.json()
check(r.status_code == 201 and L2["rcpt_name"] == "Finanzamt Musterstadt" and "Amtsweg 3" in L2["rcpt_address"], "a letter to an address book contact")
r = A.patch(B + f"{LT}/{L2['id']}", json={"rcpt_address": "Max Muster\nPostfach 12\n12345 Musterstadt", "channel": "registered", "tracking_no": "RR123456789DE"})
check(r.ok and r.json()["rcpt_address"].startswith("Max Muster\nPostfach") and r.json()["channel"] == "registered", "change the draft (address free to edit)")
check(Ca.get(B + f"{LT}/{L1['id']}").status_code == 404 and Ca.patch(B + f"{LT}/{L1['id']}", json={"subject": "x"}).status_code == 404
      and Ca.get(B + f"{LT}/{L1['id']}/pdf").status_code == 404 and Ca.post(B + f"{LT}/{L1['id']}/sent", json={}).status_code == 404,
      "another organisation reaches no letter (404)")
check(Bo.get(B + f"{LT}/{L1['id']}").status_code == 403, "the member: 403 on a letter")
row = sql("SELECT subject, body, rcpt_name, rcpt_address, ref_line FROM office_letters WHERE id=?", (L1["id"],))[0]
check(all(str(x).startswith("kenc1:") for x in row) and "Kündigung" not in str(row[0]), f"subject / text / recipient / reference encrypted at rest {str(row[0])[:20]}")

# ---------------------------------------------------------------- list
lst = A.get(B + LT).json()
check({x["id"] for x in lst["letters"]} == {L1["id"], L2["id"]} and all("body" not in x for x in lst["letters"]), "the list without the text")
check(any(c["id"] == CL for c in lst["clients"]) and not any(c["id"] == CL2 for c in lst["clients"]) and lst["profile"]["default_greeting"]
      and {c["key"] for c in lst["channels"]} == {"post", "email", "registered", "fax"}, "the list's meta: clients, profile, channels")
check([x["id"] for x in A.get(B + LT + f"?client_id={CL}&brief=1").json()["letters"]] == [L1["id"]] and "clients" not in A.get(B + LT + "?brief=1").json(),
      "filter by client; brief without meta")
check([x["id"] for x in A.get(B + LT + "?q=einspruch").json()["letters"]] == [L2["id"]], "search in the (encrypted) subject")
check(A.get(B + LT + "?status=x").status_code == 400 and A.get(B + LT + "?status=sent").json()["letters"] == [], "status filter")

# ---------------------------------------------------------------- PDF
r = A.get(B + f"{LT}/{L1['id']}/pdf")
check(r.ok and r.content[:5] == b"%PDF-" and "inline" in r.headers.get("Content-Disposition", ""), "the draft's PDF (inline)")
check(in_pdf(r.content, "Beispiel Film GmbH · Musterweg 1 · 12345 Musterstadt"), "PDF: the sender line")
check(in_pdf(r.content, "Kunde Eins GmbH") and in_pdf(r.content, "Kundenweg 5") and in_pdf(r.content, "Kündigung Rahmenvertrag")
      and in_pdf(r.content, "Ihr Schreiben vom 01.10.2026") and in_pdf(r.content, L1["greeting"]) and in_pdf(r.content, "Alice Admin"),
      "PDF: recipient, subject, reference line, greeting, name")
check(in_pdf(r.content, "ENTWURF"), "PDF: a draft says ENTWURF")
check("attachment" in A.get(B + f"{LT}/{L1['id']}/pdf?dl=1").headers.get("Content-Disposition", ""), "PDF ?dl=1 = download")

# ---------------------------------------------------------------- profile + signature picture
check(A.put(B + LT + "/profile", json={"image": base64.b64encode(b"GIF89a....").decode()}).status_code == 400, "profile: a GIF 400")
check(A.put(B + LT + "/profile", json={"image": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (310 * 1024)).decode()}).status_code == 400, "profile: too large 400")
r = A.put(B + LT + "/profile", json={"greeting": "Beste Grüße", "name": "Alice Admin, Geschäftsführerin", "image": "data:image/png;base64," + base64.b64encode(png()).decode()})
check(r.ok and r.json()["has_image"] and r.json()["greeting"] == "Beste Grüße" and r.json()["image"].startswith("data:image/png;base64,"), f"profile saved {r.text[:120]}")
check(str(sql("SELECT image FROM office_letter_profiles WHERE org_id=? AND user_id=?", (ORG, ALICE))[0][0]).startswith("kenc1:"), "the picture encrypted at rest")
r = A.post(B + LT, json={"client_id": CL, "subject": "Mit Unterschrift", "body": "Text"})
L3 = r.json()
check(L3["greeting"] == "Beste Grüße" and L3["sign_name"] == "Alice Admin, Geschäftsführerin" and L3["sign_image"] == 1, "a new letter takes the profile")
p = A.get(B + f"{LT}/{L3['id']}/pdf").content
check(b"/Sig" in p and in_pdf(p, "Beste Grüße"), "PDF: the signature picture is in")
check(b"/Sig" not in A.get(B + f"{LT}/{L1['id']}/pdf").content, "PDF: not in a letter without sign_image")
check(A.delete(B + LT + "/profile/image").json()["has_image"] is False and b"/Sig" not in A.get(B + f"{LT}/{L3['id']}/pdf").content, "picture removed")

# ---------------------------------------------------------------- sent, filed, delivered
check(A.post(B + f"{LT}/{L1['id']}/delivered").status_code == 409, "delivered before sent: 409")
r = A.post(B + f"{LT}/{L1['id']}/sent", json={"channel": "post", "followup_days": 14})
check(r.ok, f"mark as sent ({r.status_code} {r.text[:200]})")
S1 = r.json()
due = (testclock.today() + datetime.timedelta(days=14)).isoformat()
check(S1["status"] == "sent" and S1["sent_at"] and S1["followup_due"] == due and S1["node_id"], f"sent: status, follow-up date, filed {S1.get('followup_due')}")
n = sql("SELECT n.org_id, n.kind, p.name, n.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (S1["node_id"],))
check(n and n[0][0] == ORG and n[0][1] == "file" and n[0][2] == "Kunde Eins GmbH" and n[0][3].endswith(".pdf"), f"the PDF in the documents space, folder of the client {n}")
check(A.get(B + f"/api/docs/{S1['node_id']}").ok, "the admin reaches the filed PDF")
check(Bo.get(B + f"/api/docs/{S1['node_id']}").status_code in (403, 404) and Ca.get(B + f"/api/docs/{S1['node_id']}").status_code in (403, 404), "member / other organisation do not")
pd = A.get(B + f"{LT}/{L1['id']}/pdf").content
check(pd[:5] == b"%PDF-" and not in_pdf(pd, "ENTWURF") and in_pdf(pd, "Kündigung Rahmenvertrag"), "the sent PDF without the draft mark")
check(A.patch(B + f"{LT}/{L1['id']}", json={"subject": "neu"}).status_code == 409 and A.post(B + f"{LT}/{L1['id']}/sent", json={}).status_code == 409,
      "a sent letter: PATCH / sent again 409")
check(sql("SELECT COUNT(*) FROM doc_meta WHERE ext_id=?", (f"letter:{L1['id']}",))[0][0] == 1, "filed once")
r = A.post(B + f"{LT}/{L2['id']}/sent", json={})
check(r.ok and r.json()["followup_due"] is None and r.json()["tracking_no"] == "RR123456789DE", "sent without follow-up, tracking number kept")
n = sql("SELECT p.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (r.json()["node_id"],))
check(n and n[0][0] in ("Korrespondenz", "Correspondence"), f"without a client: folder Correspondence {n}")  # English until the translations are in
r = A.post(B + f"{LT}/{L1['id']}/delivered")
check(r.ok and r.json()["status"] == "delivered" and r.json()["delivered_at"], "delivered")
r = A.delete(B + f"{LT}/{L1['id']}/delivered")
check(r.ok and r.json()["status"] == "sent" and not r.json()["delivered_at"], "delivered undone")

# ---------------------------------------------------------------- copy, templates
r = A.post(B + LT, json={"copy_of": L1["id"]})
C1 = r.json()
check(r.status_code == 201 and C1["status"] == "draft" and C1["subject"] == "Kündigung Rahmenvertrag" and C1["body"] == L1["body"] and C1["client_id"] == CL
      and C1["letter_date"] == today and not C1["node_id"] and not C1["sent_at"], "edit a copy = a new draft")
A.patch(B + f"{LT}/{C1['id']}", json={"body": "Sehr geehrte Damen und Herren,\n\n{{client.name}} erhält dies am {{today}} von {{company.name}}.", "subject": "Mahnung"})
r = A.post(B + f"{LT}/{C1['id']}/template", json={})
check(r.status_code == 201 and r.json()["kind"] == "letter" and r.json()["name"] == "Mahnung" and r.json()["sign"] == 0, f"save as template {r.text[:160]}")
TL = r.json()["id"]
check(any(t["id"] == TL for t in A.get(B + LT).json()["templates"]) and any(t["id"] == TL for t in A.get(B + O + "/doc-templates").json()["templates"]),
      "the letter template in the letters and in the documents tab")
r = A.post(B + LT, json={"template_id": TL, "client_id": CL})
check(r.status_code == 201 and r.json()["subject"] == "Mahnung" and "Kunde Eins GmbH erhält dies am" in r.json()["body"] and "Beispiel Film GmbH" in r.json()["body"]
      and "{{" not in r.json()["body"], f"a letter from the template, variables filled {r.json().get('body')}")
check(str(sql("SELECT body FROM office_doc_templates WHERE id=?", (TL,))[0][0]).startswith("kenc1:"), "the template text encrypted at rest")
check(Ca.post(B + LT, json={"template_id": TL}).status_code == 404 and Ca.post(B + LT, json={"copy_of": L1["id"]}).status_code == 404,
      "another organisation: template / copy 404")

# 2.294.0 (#3155): a letter from the sample template "Auftragsbestätigung" (dt_fill), long enough for two pages: as a draft
# ENTWURF is the bold diagonal watermark on every page and no head line; sent = no mark at all
def marks(data, word):
    hx, w = pdf_hex(data), word.encode("cp1252").hex()
    return hx.count(w), len(re.findall(r"2 Tr [^<]*<" + w + "> Tj", hx)), len(re.findall(rb"/Type\s*/Page\b", data))


r = A.post(B + O + "/doc-templates", json={"starter": "confirmation", "lang": "de"})
check(r.status_code == 201 and r.json()["name"] == "Auftragsbestätigung", f"#3155: the sample template Auftragsbestätigung ({r.status_code} {r.text[:120]})")
r = A.post(B + LT, json={"template_id": r.json().get("id"), "client_id": CL})
AB = r.json()
check(r.status_code == 201 and AB["subject"] == "Auftragsbestätigung" and "{{" not in AB["body"], f"#3155: a letter from Auftragsbestätigung ({r.text[:120]})")
A.patch(B + f"{LT}/{AB['id']}", json={"body": AB["body"] + "\n\n" + "\n\n".join(["Weitere Einzelheiten zum Auftrag stehen in diesem Absatz, damit das Anschreiben über mehr als eine Seite läuft."] * 45)})
n_all, n_wm, n_pg = marks(A.get(B + f"{LT}/{AB['id']}/pdf").content, "ENTWURF")
check(n_pg >= 2 and n_all == n_wm == n_pg, f"#3155: the draft: ENTWURF as watermark on every page, no head line ({n_all} words, {n_wm} watermarks, {n_pg} pages)")
check(A.post(B + f"{LT}/{AB['id']}/sent", json={}).ok and marks(A.get(B + f"{LT}/{AB['id']}/pdf").content, "ENTWURF")[0] == 0, "#3155: sent = no ENTWURF")

# ---------------------------------------------------------------- archive / restore
check(A.delete(B + f"{LT}/{C1['id']}").ok and C1["id"] not in [x["id"] for x in A.get(B + LT).json()["letters"]], "archive a letter")
check(C1["id"] in [x["id"] for x in A.get(B + LT + "?archived=1").json()["letters"]], "archived ones with ?archived=1")
check(A.post(B + f"{LT}/{C1['id']}/restore").ok and C1["id"] in [x["id"] for x in A.get(B + LT).json()["letters"]], "restore (the undo)")
check(Ca.delete(B + f"{LT}/{C1['id']}").status_code == 404 and Ca.post(B + f"{LT}/{C1['id']}/restore").status_code == 404, "another organisation: archive 404")

# ---------------------------------------------------------------- a person without organisation (personal office)  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
check(Fr.get(B + O + "/settings").json().get("role") == "admin", "freelancer: admin of the own personal office")
Fr.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": "Frida Film", "street": "Weg 2", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CP = Fr.post(B + "/api/clients", json={"name": "Privatkunde Eins", "street": "Weg 1", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
FBK = Fr.post(B + "/api/books", json={"name": "Meine Kontakte", "org_id": None}).json()["id"]
FCT = Fr.post(B + "/api/contacts", json={"book_id": FBK, "fn": "Vermieterin Beispiel", "addresses": [{"street": "Hausweg 9", "code": "10000", "city": "Berlin"}]}).json()["id"]
rc = Fr.get(B + LT + "/recipients").json()["recipients"]
check(any(x.get("client_id") == CP for x in rc) and any(x.get("contact_id") == FCT for x in rc) and not any(x.get("contact_id") in (CT, CTP) for x in rc)
      and not any(x.get("client_id") == CL for x in rc), "freelancer: own clients and private contacts only")
check(Fr.post(B + LT, json={"client_id": CL}).status_code == 404 and Fr.post(B + LT, json={"contact_id": CT}).status_code == 404, "freelancer: an organisation's client / contact 404")
check(Fr.get(B + f"{LT}/{L1['id']}").status_code == 404, "freelancer: an organisation's letter 404")
r = Fr.post(B + LT, json={"client_id": CP, "subject": "Rechnungsanschrift", "body": "Text"})
FL = r.json()
check(r.status_code == 201 and FL["lang"] == "en" and FL["greeting"] == "Kind regards" and FL["rcpt_name"] == "Privatkunde Eins", f"freelancer: a letter {FL.get('greeting')}")
r = Fr.post(B + LT, json={"contact_id": FCT, "subject": "Kündigung Wohnung"})
check(r.status_code == 201 and "Hausweg 9" in r.json()["rcpt_address"], "freelancer: a letter to a private contact")
n_all, n_wm, n_pg = marks(Fr.get(B + f"{LT}/{FL['id']}/pdf").content, "DRAFT")  # 2.294.0 (#3155)
check(n_all == n_wm == n_pg >= 1, f"freelancer: the draft carries DRAFT as watermark, no head line ({n_all}/{n_wm}/{n_pg})")
r = Fr.post(B + f"{LT}/{FL['id']}/sent", json={})
check(r.ok and r.json()["node_id"], "freelancer: sent + filed")
n = sql("SELECT n.org_id, n.owner_id, p.name FROM fs_nodes n JOIN fs_nodes p ON p.id=n.parent_id WHERE n.id=?", (r.json()["node_id"],))
check(n and n[0][0] is None and n[0][1] == FID and n[0][2] == "Privatkunde Eins", f"freelancer: the PDF in the private documents {n}")
check(A.get(B + f"/api/docs/{r.json()['node_id']}").status_code in (403, 404), "freelancer: the PDF is not the others'")
check(str(sql("SELECT subject FROM office_letters WHERE id=?", (FL["id"],))[0][0]).startswith("kenc1:"), "freelancer: encrypted at rest")
check(Fr.put(B + LT + "/profile", json={"name": "Frida"}).json()["name"] == "Frida" and A.get(B + LT + "/profile").json()["name"] != "Frida", "freelancer: own profile")
check(Fr.get(B + f"{LT}/{FL['id']}/pdf").content[:5] == b"%PDF-" and Fr.post(B + f"{LT}/{FL['id']}/delivered").ok, "freelancer: PDF, delivered")
check(A.get(B + f"{LT}/{FL['id']}").status_code == 404, "the freelancer's letter is not the organisation's")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
