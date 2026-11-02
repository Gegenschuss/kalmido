#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.439.0 (#3617) API tests: the person's part of the office's mails. Own container (start.sh through kt.fresh) with two SMTP
stubs (stub_mail.py: 1025 = the server's, a copy on 1026 = a mailbox). Invented companies, people and addresses only.
tenant-matrix: office  freelancer-matrix: office
 - the prefilled signature comes from the person's name and the company data; it is attached under the standard text and
   under an own text, behind "-- ", as text + HTML with the logo as an embedded picture (no outside link); the PDF stays
   attached; signature false leaves all of it off for this one mail (a plain mail as before)
 - own signature, sender name, answer address per person and office: saved, shown only to that person, encrypted at rest;
   HTML in a signature stays text; logo off = HTML without the picture; '' = none; null = the prefilled one again
 - Reply-To: per mail, else the person's, else the company's; a wrong address 400, a line break in the sender name never
   reaches a header
 - a letter by e-mail carries the same
 - a mailbox with SMTP: the mail leaves through it with its address; in an organisation the person's own private one only
   when chosen; a failing mailbox 409 and nothing marked sent
 - a member's own signature counts for the day's limit of own texts, an admin's does not
 - a person without an organisation (personal office) does all of it the same way
usage: p2439_a_mailsig_test.py <datadir>"""
import email
import email.policy
import json
import os
import struct
import subprocess
import sys
import time
import zlib

import dbx as dbxm
import kt
from kt import B, CT, DATA, H, check, done, sess
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
O = "/api/office"
D = O + "/docs"
KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
FEAT = "cal,comments,collab,office,clients,docs,files,contacts"
CO = {"name": "Studio Nordlicht GmbH", "street": "Elbstrasse 5", "zip": "20457", "city": "Hamburg", "country": "DE", "phone": "040 123456",
      "website": "https://www.nordlicht.example/", "email": "hallo@nordlicht.example", "vat_id": "DE123456789", "iban": "DE02120300000000202051",
      "bic": "BYLADEM1001", "bank_name": "Beispielbank", "tax_number": "12/345/67890"}

kt.fresh(env={"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none", "KALMIDO_MAIL_FROM": "kalmido@example.test",
              "KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1:1026,127.0.0.1:1027", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0",
              "KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2439A")
for d in ("mail", "mail2"):
    os.makedirs(os.path.join(DATA, d, "in"), exist_ok=True)
src = open(os.path.join(N, "stub_mail.py")).read()
open(os.path.join(DATA, "stub_mail.py"), "w").write(src)
open(os.path.join(DATA, "stub_mail2.py"), "w").write(src.replace('"/data/mail"', '"/data/mail2"').replace("1143", "1144").replace("1025", "1026"))
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail2.py"])
time.sleep(1.2)
import requests  # noqa: E402
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ORG = ME["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Member", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [ME["id"], CAROL], "admins": [ME["id"]]})
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})


def sent(box="mail"):
    """The mails the SMTP stub received, oldest first, parsed."""
    try:
        rows = [json.loads(x) for x in open(os.path.join(DATA, box, "out.jsonl"), encoding="utf-8") if x.strip()]
    except OSError:
        return []
    return [email.message_from_string(x["raw"], policy=email.policy.default) for x in rows]


def parts(m):
    """(text, html, picture parts, pdf names) of a parsed mail."""
    t, h, pics, pdf = None, None, [], []
    for p in m.walk():
        ct = p.get_content_type()
        if p.is_multipart():
            continue
        if ct == "text/plain" and t is None:
            t = p.get_content()
        elif ct == "text/html" and h is None:
            h = p.get_content()
        elif ct.startswith("image/"):
            pics.append(p)
        elif ct == "application/pdf":
            pdf.append(p.get_filename())
    return t, h, pics, pdf


def png():
    """A small red PNG, written by hand (no picture library on the test side)."""
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\0" + b"\xc0\x20\x20" * 300 for _ in range(100))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 300, 100, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")


def invoice(s, cl):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": kt.today().isoformat(), "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


def send(s, cl, box="mail", **kw):
    """Sends a new invoice with kw -> (response, the mail that arrived or None)."""
    n = len(sent(box))
    r = s.post(B + f"{D}/{invoice(s, cl)}/send", json={"to": "kunde@example.com", "datev": False, **kw})
    new = sent(box)
    return r, (new[n] if len(new) > n else None)


for who, s, name in (("org", A, "Alice Admin"), ("freelancer", Fr, "Frida")):
    r = s.put(B + O + "/settings", json={"company_fields": CO})
    assert r.ok, r.text
    r = s.post(B + "/api/clients", json={"name": f"Kunde {who}", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE", "email": "kunde@example.com"})
    assert r.ok, r.text
    CL = r.json()["id"]
    if who == "org":
        CLA = CL
    r = s.post(B + O + "/logo", files={"file": ("logo.png", png(), "image/png")})
    check(r.ok, f"{who}: logo uploaded {r.status_code} {r.text[:120]}")

    # ---- the prefilled signature
    p = s.get(B + O + "/mail-profile").json()
    check(p["signature"] == p["default_signature"] and not p["saved"] and p["logo"] and p["has_logo"], f"{who}: prefilled, logo on {p}")
    for x in (name, "Studio Nordlicht GmbH", "Elbstrasse 5, 20457 Hamburg", "040 123456", "www.nordlicht.example"):
        check(x in p["signature"], f"{who}: the prefilled signature names {x}: {p['signature']!r}")
    check("https://" not in p["signature"], f"{who}: the website as printed")
    check(p["logo_data"].startswith("data:image/png;base64,"), f"{who}: the preview's logo comes along (members may not read the logo route)")
    check(p["default_reply_to"] == "hallo@nordlicht.example" and p["via"] == "server" and p["note"], f"{who}: answer address + the sentence on the sender {p}")

    # ---- attached under the standard text, text + HTML + logo + PDF
    r, m = send(s, CL)
    check(r.ok and m is not None, f"{who}: sent {r.status_code} {r.text[:160]}")
    t, h, pics, pdf = parts(m)
    check(f"\n\n-- \n{p['signature']}" in t.replace("\r\n", "\n"), f"{who}: under the text behind '-- ': {t!r}")
    check(t.index("Studio Nordlicht GmbH") < t.index("-- "), f"{who}: below the standard text")
    check(h and "cid:kalmido-sig-logo" in h and "http" not in h.replace("www.nordlicht", ""), f"{who}: HTML with the embedded logo, no outside link: {h and h[:300]}")
    check(len(pics) == 1 and pics[0]["Content-ID"] == "<kalmido-sig-logo>", f"{who}: the logo travels with the mail {[x['Content-ID'] for x in pics]}")
    check(len(pics[0].get_content()) < 20000 and struct.unpack(">I", pics[0].get_content()[20:24])[0] == 96, f"{who}: the logo made small (96 px high)")
    check(len(pdf) == 1, f"{who}: the PDF still attached {pdf}")
    check("picture" not in t and "cid:" not in t, f"{who}: the text part has no picture")
    check(m["Reply-To"] == "hallo@nordlicht.example", f"{who}: Reply-To = the company {m['Reply-To']}")
    check(name in str(m["From"]) and "kalmido@example.test" in str(m["From"]), f"{who}: server's address with the person's name {m['From']}")

    # ---- under an own text, and off for one mail
    r, m = send(s, CL, text="Hallo Kunde,\nanbei die Rechnung.")
    t = parts(m)[0].replace("\r\n", "\n")
    check(t.startswith("Hallo Kunde,\nanbei die Rechnung.\n\n-- \n"), f"{who}: under an own text {t!r}")
    r, m = send(s, CL, signature=False)
    t, h, pics, pdf = parts(m)
    check(r.ok and "-- \n" not in t.replace("\r\n", "\n") and h is None and not pics and len(pdf) == 1, f"{who}: left off for this mail: a plain mail with its PDF")

    # ---- own values
    r = s.put(B + O + "/mail-profile", json={"signature": "Beste Gruesse\n<b>Team</b> & Co", "from_name": f"Buero {who}", "reply_to": f"{who}@nordlicht.example"})
    j = r.json()
    check(r.ok and j["saved"] and j["signature"] == "Beste Gruesse\n<b>Team</b> & Co" and j["from_name"] == f"Buero {who}", f"{who}: saved {r.text[:200]}")
    r, m = send(s, CL)
    t, h, pics, pdf = parts(m)
    check("Beste Gruesse\n<b>Team</b> & Co" in t.replace("\r\n", "\n"), f"{who}: the own signature, as text")
    check("&lt;b&gt;Team&lt;/b&gt; &amp; Co" in h and "<b>Team" not in h, f"{who}: HTML in a signature stays text {h[:300]}")
    check(f"Buero {who}" in str(m["From"]) and "kalmido@example.test" in str(m["From"]), f"{who}: own sender name, the server's address {m['From']}")
    check(m["Reply-To"] == f"{who}@nordlicht.example", f"{who}: Reply-To = the person's {m['Reply-To']}")
    r, m = send(s, CL, reply_to="einmal@nordlicht.example")
    check(r.ok and m["Reply-To"] == "einmal@nordlicht.example", f"{who}: Reply-To for this one mail {m and m['Reply-To']}")
    n = len(sent())
    for bad in ("kein-mail", "a@b.example\r\nBcc: x@example.org", "a@b.example, c@d.example"):
        r = s.post(B + f"{D}/{invoice(s, CL)}/send", json={"to": "kunde@example.com", "datev": False, "reply_to": bad})
        check(r.status_code == 400, f"{who}: wrong answer address {bad!r} 400 ({r.status_code})")
        check(s.put(B + O + "/mail-profile", json={"reply_to": bad}).status_code in (200, 400) and s.get(B + O + "/mail-profile").json()["reply_to"] in (f"{who}@nordlicht.example",), f"{who}: never stored {bad!r}")
    check(len(sent()) == n, f"{who}: a wrong answer address sends nothing")
    r = s.put(B + O + "/mail-profile", json={"from_name": "A\r\nBcc: x@example.org"})
    r, m = send(s, CL)
    check(m is not None and m["Bcc"] is None and "\n" not in str(m["From"]), f"{who}: a line break in the sender name never reaches a header {m and m['From']}")
    s.put(B + O + "/mail-profile", json={"from_name": ""})
    for body, why in (({"signature": "x" * 1001}, "too long"), ({"signature": "\n".join("abcdefghijklmn")}, "too many lines"), ({"via": "nowhere"}, "unknown way"),
                      ({"logo": "yes"}, "logo not a switch"), ({"signature": 5}, "no text"), ({}, "nothing")):
        check(s.put(B + O + "/mail-profile", json=body).status_code == 400, f"{who}: {why}: 400")

    # ---- a text that looks sealed stays a text (review): nothing breaks the person's mails
    r = s.put(B + O + "/mail-profile", json={"signature": "kenc1:gruss", "from_name": "kenc1:name"})
    check(r.ok and "gruss" in r.json()["signature"], f"{who}: a text that looks sealed is saved {r.status_code}")
    check(s.get(B + O + "/mail-profile").ok and s.put(B + O + "/mail-profile", json={"reply_to": "kenc1:x@nordlicht.example"}).status_code == 400, f"{who}: read again; as an address 400")
    r, m = send(s, CL)
    check(r.ok and "gruss" in parts(m)[0], f"{who}: and sent {r.status_code}")
    s.put(B + O + "/mail-profile", json={"signature": "Beste Gruesse\n<b>Team</b> & Co", "from_name": ""})

    # ---- logo off, none, the prefilled one again
    s.put(B + O + "/mail-profile", json={"logo": False})
    r, m = send(s, CL)
    t, h, pics, pdf = parts(m)
    check(h and "<img" not in h and not pics and "Team" in h, f"{who}: logo off = HTML without the picture")
    s.put(B + O + "/mail-profile", json={"signature": ""})
    r, m = send(s, CL)
    t, h, pics, pdf = parts(m)
    check("-- \n" not in t.replace("\r\n", "\n") and h is None, f"{who}: no signature at all when saved empty")
    j = s.put(B + O + "/mail-profile", json={"signature": None, "logo": True}).json()
    check(j["signature"] == j["default_signature"] and not j["saved"], f"{who}: null = the prefilled one again")

    # ---- a letter by e-mail
    r = s.post(B + O + "/letters", json={"rcpt_name": "Kunde", "rcpt_address": "Weg 2\n10115 Berlin", "rcpt_email": "kunde@example.com", "subject": "Betreff", "body": "Text"})
    check(r.status_code == 201, f"{who}: letter {r.status_code} {r.text[:200]}")
    lid = r.json()["id"]
    n = len(sent())
    r = s.post(B + O + f"/letters/{lid}/send-mail", json={"reply_to": "brief@nordlicht.example"})
    check(r.ok and len(sent()) == n + 1, f"{who}: letter sent {r.status_code} {r.text[:200]}")
    t, h, pics, pdf = parts(sent()[-1])
    check(f"\n\n-- \n{j['signature']}" in t.replace("\r\n", "\n") and h and len(pics) == 1 and len(pdf) == 1, f"{who}: the letter's mail carries the signature, logo and PDF")
    check(sent()[-1]["Reply-To"] == "brief@nordlicht.example", f"{who}: a letter without its own address: the answer address of this mail")
    r = s.post(B + O + "/letters", json={"rcpt_name": "Kunde", "rcpt_address": "Weg 2\n10115 Berlin", "rcpt_email": "kunde@example.com", "subject": "Zwei", "body": "Text"})
    r = s.post(B + O + f"/letters/{r.json()['id']}/send-mail", json={"signature": False})
    t, h, pics, pdf = parts(sent()[-1])
    check(r.ok and "-- \n" not in t.replace("\r\n", "\n") and h is None and not pics, f"{who}: a letter's mail without it")

# ---- per person: carol sees her own, not alice's; at rest encrypted
A.put(B + O + "/mail-profile", json={"signature": "Geheim Alice", "reply_to": "alice@nordlicht.example"})
p = Ca.get(B + O + "/mail-profile")
check(p.ok and "Geheim Alice" not in p.text and "Carol Member" in p.json()["signature"] and not p.json()["reply_to"], f"carol: her own values, not alice's {p.text[:200]}")
check(Ca.put(B + O + "/mail-profile", json={"from_name": "Carol B."}).ok, "a member saves her own")
check(A.get(B + O + "/mail-profile").json()["from_name"] == "", "alice's row untouched")
c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
rows = c.execute("SELECT mail_sig, mail_reply_to FROM office_letter_profiles WHERE org_id=? AND user_id=?", (ORG, ME["id"])).fetchall()
c.close()
check(rows and rows[0][0] and "Geheim" not in rows[0][0] and "alice@" not in rows[0][1], f"encrypted at rest {[str(x)[:30] for x in rows]}")
A.put(B + O + "/mail-profile", json={"signature": None, "reply_to": ""})

# ---- a person ruled by office groups: the own mail settings stay theirs
R = O + "/rights"
g = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Nur Briefe"})
assert g.status_code == 201, g.text
assert A.patch(B + f"{R}/groups/{g.json()['id']}", json={"levels": {"letters": "edit"}}).ok
r = A.put(B + f"{R}/people/{CAROL}", json={"groups": [f"g:{g.json()['id']}"]})
check(r.ok, f"carol into a group {r.text[:160]}")
check(Ca.get(B + O + "/mail-profile").ok and Ca.put(B + O + "/mail-profile", json={"from_name": "Carol C."}).ok, "any office access: own mail settings (read and write)")
check(Ca.get(B + O + "/settings").ok and Ca.put(B + O + "/settings", json={"lang": "de"}).status_code == 403, "the office's settings stay closed for her")
check(Ca.get(B + O + "/mail-status").ok, "the send dialog's status too (it has no area either)")
g = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Versand"})
assert g.status_code == 201, g.text
r = A.patch(B + f"{R}/groups/{g.json()['id']}", json={"levels": {"invoices": "edit", "offers": "edit"}, "specials": ["release"]})
assert r.ok, r.text
r = A.put(B + f"{R}/people/{CAROL}", json={"groups": [f"g:{g.json()['id']}"]})
assert r.ok, r.text

# ---- a mailbox with SMTP: the mail leaves through it (the organisation's, then her own when chosen)
BOX = {"smtp_host": "127.0.0.1", "smtp_port": 1026, "smtp_tls": "none", "from_addr": "office@nordlicht.example", "from_name": "Alpha Office"}
r = A.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": f"org:{ORG}"})
check(r.ok, f"Alpha's mailbox {r.status_code} {r.text[:200]}")
p = A.get(B + O + "/mail-profile").json()
check(p["via"] == "workspace" and "office@nordlicht.example" in p["note"], f"org: the sentence names the mailbox {p['note']}")
r, m = send(A, CLA, box="mail2")
check(r.ok and m is not None and "office@nordlicht.example" in str(m["From"]) and "Alpha Office" in str(m["From"]), f"org: through the workspace's mailbox {r.status_code} {m and m['From']}")
A.put(B + O + "/mail-profile", json={"via": "server"})
r, m = send(A, CLA)
check(r.ok and m is not None and "kalmido@example.test" in str(m["From"]), "org: the server when chosen")
A.put(B + O + "/mail-profile", json={"via": ""})
r = Fr.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": "private", "from_addr": "frida@nordlicht.example", "from_name": ""})
check(r.ok, f"the freelancer's mailbox {r.status_code} {r.text[:200]}")
FCL = Fr.get(B + "/api/clients").json()
FCL = (FCL.get("clients") if isinstance(FCL, dict) else FCL)[0]["id"]
r, m = send(Fr, FCL, box="mail2")
t, h, pics, pdf = parts(m)
check(r.ok and "frida@nordlicht.example" in str(m["From"]) and "-- \n" in t.replace("\r\n", "\n") and len(pdf) == 1, f"freelancer: through her own mailbox {m and m['From']}")
r = Ca.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": "private", "from_addr": "carol@nordlicht.example", "from_name": ""})
check(r.ok, f"carol's private mailbox {r.status_code} {r.text[:200]}")
p = Ca.get(B + O + "/mail-profile").json()
check(p.get("via") == "workspace" and {w["key"] for w in p.get("ways", [])} == {"server", "workspace", "private"}, f"her own one only when chosen {p}")
check(Ca.put(B + O + "/mail-profile", json={"via": "private"}).json()["via"] == "private", "chosen")
check("carol@nordlicht.example" in Ca.get(B + O + "/mail-profile").json()["note"], "the sentence names her address")
check(not [w for w in A.get(B + O + "/mail-profile").json()["ways"] if w["key"] == "private"], "alice has no such way (nobody else's mailbox)")

# ---- a series: no person pressed send, so none of a person's settings (review): never the admin's private mailbox or answer address
r = A.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": "private", "from_addr": "alice-privat@nordlicht.example", "from_name": ""})
check(r.ok, f"alice's private mailbox {r.text[:160]}")
A.put(B + O + "/mail-profile", json={"via": "private", "reply_to": "alice-privat@nordlicht.example", "signature": "Privat Alice"})
r, m = send(A, CLA, box="mail2")
check(r.ok and "alice-privat@nordlicht.example" in str(m["From"]), f"her own mail: through her private mailbox {m and m['From']}")
t = A.post(B + D, json={"kind": "invoice", "client_id": CLA, "items": [{"title": "Wartung", "qty": 1, "rate": 50}]}).json()
s_ = A.post(B + O + "/series", json={"template_id": t["id"], "every": "monthly", "start": kt.today().isoformat(), "auto_send": 1})
check(s_.status_code == 201, f"a series {s_.text[:200]}")
n = len(sent("mail2"))
r = A.post(B + O + f"/series/{s_.json()['id']}/run")
check(r.ok and r.json().get("sent"), f"the series sent its invoice {r.text[:200]}")
m = sent("mail2")[n] if len(sent("mail2")) > n else None
check(m is not None and "office@nordlicht.example" in str(m["From"]) and m["Reply-To"] == "hallo@nordlicht.example", f"a series: the workspace's mailbox, the company's address {m and (m['From'], m['Reply-To'])}")
check(m is not None and "Privat Alice" not in parts(m)[0] and "Studio Nordlicht GmbH" in parts(m)[0], "a series: the prefilled signature")
A.put(B + O + "/mail-profile", json={"via": "", "reply_to": "", "signature": None})

# ---- a failing mailbox: 409, nothing sent, nothing marked
r = A.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": f"org:{ORG}", "smtp_port": 1027})
did = invoice(A, CLA)
r = A.post(B + f"{D}/{did}/send", json={"to": "kunde@example.com", "datev": False})
d = A.get(B + f"{D}/{did}").json()
check(r.status_code == 409 and d.get("status") != "sent" and not d.get("sent_at"), f"a mailbox that does not answer: 409, not marked sent ({r.status_code} {d.get('status')})")
A.put(B + O + "/mail-profile", json={"via": "server"})

# ---- a member's own signature counts as an own text (2.39.1 N7), an admin's does not
Ca.put(B + O + "/mail-profile", json={"via": "server", "signature": "Meine freien Worte"})
c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
for _ in range(50):
    c.execute("INSERT INTO office_doc_log(org_id, at, action, detail) VALUES(?,?,?,?)", (ORG, now, "send", '{"own_text": 1}'))
c.commit()
c.close()
d2 = invoice(A, CLA)
r = Ca.post(B + f"{D}/{d2}/send", json={"to": "kunde@example.com", "datev": False})
check(r.status_code == 429, f"a member's own signature hits the limit ({r.status_code} {r.text[:160]})")
Ca.put(B + O + "/mail-profile", json={"signature": None})
n = len(sent())
r = Ca.post(B + f"{D}/{d2}/send", json={"to": "kunde@example.com", "datev": False})
check(r.ok and len(sent()) == n + 1, f"the prefilled signature does not ({r.status_code} {r.text[:160]})")
A.put(B + O + "/mail-profile", json={"signature": "Admin sagt"})
r, m = send(A, CLA)
check(r.ok, f"an admin's own signature is not limited ({r.status_code})")
sys.exit(done("p2439_a_mailsig"))
