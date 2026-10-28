#!/usr/bin/env python3
"""2.352.0 D (#2754): filed mails are shown shortened. A forwarded mail (Apple "Begin forwarded message" with header, content,
signature and an older quote) -- GET /api/hubmail/mails/<id> gives "body" whole and "body_short" (the header as ONE line
"From <sender>, <date>", content only, no signature / older quote); GET .../html?short=1 is the cleaned page without the
quote blocks, the signature and the forwarding header (also a Gmail forward and a plain reply with a quote); the page without
?short stays whole; "html_short" says whether the switch is worth showing; the original .eml is unchanged and still served.
A plain mail stays as it is (body_short == body, html_short false). A person without organisation: the same (freelancer-matrix: hub).
usage: p2352_d_mailtrim_test.py <datadir>      (a fresh container with the stub mailbox)"""
import email.message
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
NOSTART = os.environ.get("P2352D_NOSTART") == "1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="]
FEAT = "cal,collab,comments,events,contacts,clients"
# a 1x1 PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def js(r):
    try:
        return r.json()
    except ValueError:
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print("NO JSON:", r.status_code, r.text[:300], "\n", log.stdout[-3000:], log.stderr[-3000:], flush=True)
        return {}


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def js(r):
    try:
        return r.json()
    except ValueError:
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print("NO JSON:", r.status_code, r.text[:300], "\n", log.stdout[-3000:], log.stderr[-3000:], flush=True)
        return {}


NEXT = [0]


def mail(to, frm, subject, text, html=None, cid=False):
    """Drop one mail into the stub mailbox (text, + an HTML alternative, + a related picture); returns its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = f"<p2352d-{NEXT[0]}@example.test>"
    m["Date"] = "Tue, 20 Oct 2026 10:00:00 +0200"
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
        if cid:
            m.get_payload()[1].add_related(PNG, "image", "png", cid="<logo@example.test>")
    open(os.path.join(DATA, "mail", "in", f"{NEXT[0]}.eml"), "wb").write(bytes(m))
    return m["Message-ID"]


def poll(n_expected, secs=40):
    A.post(B + "/api/admin/mail/poll")
    return until(lambda: len(dbx("SELECT id FROM hub_mails")) >= n_expected, secs)


def mid_of(msgid):
    r = dbx("SELECT id FROM hub_mails WHERE message_id=?", (msgid,))
    return r[0][0] if r else 0


# ---- setup: alice (admin) and frida = a person without organisation
if not NOSTART:
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(1.2)
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
FR, Fr = freelancer(B, A)
IN_A = A.post(B + "/api/hubmail/address", json={"ws": "private"}).json().get("address")
IN_F = Fr.post(B + "/api/hubmail/address", json={"ws": "private"}).json().get("address")
check(IN_A and IN_F, "setup: the filing addresses")

FWD_TEXT = """Hi team, see below.

Begin forwarded message:

From: Erika Muster <erika@example.com>
Subject: Offer
Date: 12 October 2026 at 10:00:00 CEST
To: me@example.com

The real content of the offer.

Kind regards
Erika Muster

> an older quoted reply line
"""
FWD_HTML = ("<html><body><div>Hi team, see below.</div><div><br><blockquote type=\"cite\"><div>Begin forwarded message:</div><br>"
            "<div><span><b>From: </b></span><span>Erika Muster &lt;erika@example.com&gt;</span></div>"
            "<div><span><b>Subject: </b></span><span>Offer</span></div>"
            "<div><span><b>Date: </b></span><span>12 October 2026 at 10:00:00 CEST</span></div>"
            "<div><span><b>To: </b></span><span>me@example.com</span></div><br>"
            "<div>The real content of the offer.</div>"
            "<div class=\"gmail_quote\"><blockquote>an older quoted reply</blockquote></div>"
            "<div class=\"gmail_signature\">Signature of Erika</div></blockquote></div></body></html>")
GM_HTML = ("<div dir=\"ltr\">my own words<br><br><div class=\"gmail_quote\"><div dir=\"ltr\" class=\"gmail_attr\">---------- Forwarded message ---------<br>"
           "From: <strong>Gil Mail</strong> <span dir=\"ltr\">&lt;<a href=\"mailto:gil@example.com\">gil@example.com</a>&gt;</span><br>"
           "Date: Mon, 12 Oct 2026 at 10:00<br>Subject: Hello<br>To: &lt;a@example.com&gt;<br></div><br><br>Gmail forward content</div></div>")
RE_HTML = ("<div>My plain answer.</div><div class=\"gmail_quote\"><div class=\"gmail_attr\">On Mon, Pat wrote:</div>"
           "<blockquote class=\"gmail_quote\">the question I answer</blockquote></div>")
PLAIN_TEXT = "Just a short plain note.\nSecond line."
M_FWD = mail(IN_A, "Moe <moe@example.test>", "Fwd: Offer", FWD_TEXT, FWD_HTML)
M_GM = mail(IN_A, "Moe <moe@example.test>", "Fwd: Hello", "my own words\n\n---------- Forwarded message ---------\nFrom: Gil Mail <gil@example.com>\nDate: Mon, 12 Oct 2026 at 10:00\nSubject: Hello\n\nGmail forward content", GM_HTML)
M_RE = mail(IN_A, "Pat <pat@example.test>", "Re: Question", "My plain answer.\n\nOn Mon, 12 Oct 2026, Pat wrote:\n> the question I answer", RE_HTML)
M_PL = mail(IN_A, "Pat <pat@example.test>", "Plain note", PLAIN_TEXT, "<p>Just a short plain note.</p>")
M_FR = mail(IN_F, "Moe <moe@example.test>", "Fwd: Offer F", FWD_TEXT, FWD_HTML)
check(poll(5), "setup: five mails filed")
FW, GM, RE, PL, FM = (mid_of(x) for x in (M_FWD, M_GM, M_RE, M_PL, M_FR))
check(FW and GM and RE and PL and FM, f"setup: the mail ids ({FW}, {GM}, {RE}, {PL}, {FM})")


def checks(S, mid, who):
    m = js(S.get(B + f"/api/hubmail/mails/{mid}"))
    check("Kind regards" in m.get("body", "") and "older quoted" in m.get("body", ""), f"{who}: body stays whole")
    bs = m.get("body_short", "")
    check("From Erika Muster, 12 October 2026 at 10:00:00 CEST" in bs, f"{who}: the header as one line ({bs[:90]!r})")
    check("The real content of the offer." in bs and "Hi team, see below." in bs, f"{who}: own words + content stay")
    check(not any(x in bs for x in ("Kind regards", "older quoted", "To: me@example.com", "Begin forwarded")), f"{who}: signature, quote, header lines gone")
    check(m.get("html") is True and m.get("html_short") is True, f"{who}: html_short says the switch is worth showing")
    full = S.get(B + f"/api/hubmail/mails/{mid}/html").text
    short = S.get(B + f"/api/hubmail/mails/{mid}/html?short=1")
    check(short.ok and "text/html" in short.headers.get("Content-Type", ""), f"{who}: the short page")
    check("Begin forwarded message" in full and "an older quoted reply" in full and "Signature of Erika" in full, f"{who}: the page without ?short stays whole")
    t = short.text
    check("The real content of the offer." in t and "From Erika Muster, 12 October 2026 at 10:00:00 CEST" in t and "Hi team, see below." in t, f"{who}: short page keeps content + one line")
    check(not any(x in t for x in ("Begin forwarded message", "an older quoted reply", "Signature of Erika", "me@example.com", "Subject:")), f"{who}: short page loses header, quote, signature")
    check("default-src 'none'" in short.headers.get("Content-Security-Policy", "") and "sandbox" in short.headers.get("Content-Security-Policy", ""), f"{who}: same strict CSP")
    eml = [a for a in m.get("attachments", []) if a["name"].endswith(".eml")]
    if eml:
        raw = S.get(B + f"/api/hubmail/mails/{mid}/files/{eml[0]['id']}")
        check(raw.ok and b"Signature of Erika" in raw.content and b"Kind regards" in raw.content, f"{who}: the original .eml is unchanged")
    else:
        check(False, f"{who}: the original .eml is attached")


checks(A, FW, "forward")
checks(Fr, FM, "freelancer")  # freelancer-matrix: hub
g = js(A.get(B + f"/api/hubmail/mails/{GM}"))
gs = A.get(B + f"/api/hubmail/mails/{GM}/html?short=1").text
check("From Gil Mail, Mon, 12 Oct 2026 at 10:00" in g.get("body_short", ""), f"gmail forward text: one line ({g.get('body_short')!r})")
check("Gmail forward content" in gs and "my own words" in gs and "From Gil Mail, Mon, 12 Oct 2026 at 10:00" in gs and "Forwarded message" not in gs, "gmail forward html: one line + content")
r = js(A.get(B + f"/api/hubmail/mails/{RE}"))
rs = A.get(B + f"/api/hubmail/mails/{RE}/html?short=1").text
check(r.get("body_short") == "My plain answer." and "the question I answer" in r.get("body", ""), f"reply text: quote cut, body whole ({r.get('body_short')!r})")
check("My plain answer." in rs and "the question I answer" not in rs and r.get("html_short") is True, "reply html: quote block gone")
p = js(A.get(B + f"/api/hubmail/mails/{PL}"))
check(p.get("body_short") == p.get("body") and p.get("html_short") is False, "a plain mail is not shortened and offers no switch")
check(A.get(B + f"/api/hubmail/mails/{PL}/html?short=1").text.count("Just a short plain note.") == 1, "a plain mail: ?short=1 gives the same page")
check(Fr.get(B + f"/api/hubmail/mails/{FW}/html?short=1").status_code == 404, "the short page keeps the mail's rights (another person 404)")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed", flush=True)
if not NOSTART:
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
sys.exit(1 if FAILS else 0)
