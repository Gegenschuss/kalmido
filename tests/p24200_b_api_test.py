#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.420.0 API tests (part B, #3499): one HTML frame for every Kalmido mail (kalmido/core/mailframe.py mail_html).
Own container (start.sh, an SMTP sink).
 - mail_html: user texts escaped (<script> never raw), Safe parts as they are, the button in petrol #1a7f8e, only http(s)
   links get a button, the small print at the bottom, the logo only when the mail embeds it
 - the sources: no violet #6d4ad8 and no bare mail page (font-family:sans-serif / system-ui div) left in kalmido/
 - every mail kind carries the frame: invitation / reset link and event invitation through their routes (SMTP sink),
   findability, booking, portal, security, notification and daily mails through their builders in the container; the
   text part stays as it was
 - a freelancer without an organisation: the event invitation comes in the same frame
freelancer-matrix: pim
usage: p24200_b_api_test.py <datadir>"""
import email as _em
import email.policy  # noqa: F401  (_em.policy)
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
ROOT = os.path.dirname(N)
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FRAME = 'width="560"'  # the card of the shared frame
PETROL = "background:#1a7f8e"


def py(code):
    """Python in the app container (the app's own functions); prints one JSON line."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import os; os.environ['TASKS_WATCHDOG']='0'\nimport app, json\n" + code],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr[-600:]
    except (ValueError, IndexError):
        return None, out.stdout[-300:] + out.stderr[-600:]


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def wait_mail(to, n, secs=15):
    end = time.time() + secs
    while time.time() < end and len(mails(to)) < n:  # the sink file grows when the mail arrives
        time.sleep(0.2)
    return mails(to)


def parts(m):
    """(subject, plain text, html) of a mail of the sink."""
    msg = _em.message_from_string(m["raw"], policy=_em.policy.default)
    text, hb = "", ""
    for x in msg.walk():
        if x.get_content_type() == "text/plain" and not x.get_filename():
            text += x.get_content()
        elif x.get_content_type() == "text/html":
            hb += x.get_content()
    return str(msg["Subject"]), text, hb


def framed(hb, what):
    check(FRAME in hb and "#16141f" in hb and "#6d4ad8" not in hb and "font-family:sans-serif" not in hb,
          f"{what}: the shared frame " + hb[:200])


# ================================================================ the sources: no old frame left
src = {}
for p in glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True):
    with open(p, encoding="utf-8") as f:
        src[os.path.relpath(p, ROOT)] = f.read()
check(len(src) > 50, f"the server sources are there ({len(src)})")
bad = [p for p, s in src.items() if "6d4ad8" in s.lower()]
check(not bad, f"no violet #6d4ad8 left in kalmido/ {bad}")
bare = [p for p, s in src.items() if 'body style=\\"font-family:sans-serif\\"' in s or "<div style=\"font-family:system-ui,sans-serif;max-width:34rem" in s
        or "'<div style=\"font-family:system-ui,sans-serif;max-width:34rem" in s]
check(not bare, f"no bare mail page left {bare}")

if not os.environ.get("P24200B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025"
               " -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)  # the sink starts listening (as p2111_b)

# ================================================================ mail_html itself
j, er = py("from kalmido.core.mailframe import Safe, mail_html\n"
           "a = mail_html('S <x>', ['Hi <script>alert(1)</script>', Safe('<b>ok</b>'), '', 'two\\nlines'], 'Go <now>', 'https://example.com/a?b=1&c=\"2\"',"
           " 'Small <i>print</i>', 'Hello <Bob>')\n"
           "b = mail_html('S', ['x'], 'Bad', 'javascript:alert(1)')\n"
           "c = mail_html('S', ['x'], foot=Safe('<a href=\"https://example.com/stop\">stop</a>'), logo=True, brand='Studio & Co')\n"
           "print(json.dumps([a, b, c]))")
check(j is not None, "mail_html runs in the container " + er)
if j:
    a, b, c = j
    check("<script>" not in a and "&lt;script&gt;" in a and "&lt;Bob&gt;" in a and "Go &lt;now&gt;" in a and "S &lt;x&gt;" in a,
          "user texts are escaped (lines, heading, button, title)")
    check("<b>ok</b>" in a and "two<br>lines" in a, "a Safe part goes in as it is, line breaks become <br>")
    check(a.count('<p style="margin:0 0 16px') == 2, "two text paragraphs: the empty line is skipped, the Safe part is a block")
    check(PETROL in a and 'href="https://example.com/a?b=1&amp;c=&quot;2&quot;"' in a, "the button: petrol, the link escaped with quotes")
    check("Small &lt;i&gt;print&lt;/i&gt;" in a and "font-size:13px" in a and "#5f6b6e" in a, "the small print at the bottom, escaped")
    check("font-size:20px" in a and "font-size:16px;line-height:1.55" in a and FRAME in a, "heading 20 px, text 16 px / 1.55, card 560 px")
    check("javascript:" not in b and PETROL not in b, "a link that is not http(s) gets no button")
    check('<a href="https://example.com/stop">stop</a>' in c and "cid:logo" in c and "Studio &amp; Co" in c, "Safe foot, the logo when embedded, the brand escaped")
    check("cid:logo" not in a, "no logo without an embedded one")

# ================================================================ accounts
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob <b>Member</b>", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,events,contacts", "tour": "done"})

# the reset link (invitation frame with the logo) through its route
r = A.post(B + f"/api/users/{BOB}/invite", json={"send": True})
check(r.ok and r.json().get("sent") is True, "the reset link goes out by mail " + r.text[:200])
m = wait_mail("bob@example.com", 1)
check(len(m) >= 1, f"bob gets the reset mail ({len(m)})")
if m:
    subj, text, hb = parts(m[-1])
    framed(hb, "reset link")
    check("cid:logo" in hb and PETROL in hb and "Bob &lt;b&gt;Member&lt;/b&gt;" in hb and "<b>Member</b>" not in hb,
          "reset link: logo, petrol button, the name escaped")
    check("Set a new password" in text and "/#invite/" in text and "<td" not in text, "reset link: the text part as before " + text[:200])

# security, findability, notifications, daily mail: through their builders
j, er = py(f"from kalmido.accounts.secmail import sec_content\nfrom kalmido.accounts.discover import _confirm_mail\n"
           f"from kalmido.notify.channels import evm_content\nfrom kalmido.integrations.mail import digest_mail_content\n"
           f"c = app.connect()\n"
           f"s = sec_content(c, {BOB}, 'codes', (), 'en')\n"
           f"d = _confirm_mail(c, {{'id': {BOB}, 'display_name': 'Bob <i>', 'username': 'bob'}}, 'bob@example.com', 'tok123')\n"
           f"n = evm_content([('Alice assigned you: <Plan>', 'Inbox', 'https://example.com/#t/1')], 3, 'en')\n"
           f"print(json.dumps([s, d, n]))")
check(j is not None, "the builders run " + er)
if j:
    s, d, n = j
    framed(s[2], "security mail")
    check(PETROL in s[2] and "#settings/account" in s[2] and "recovery codes" in s[1] and "#settings/account" in s[1],
          "security mail: the button to the settings, the text part as before")
    framed(d[2], "findability")
    check(PETROL in d[2] and "#dsc-confirm/tok123" in d[2] and "Bob &lt;i&gt;" in d[2] and "bob@example.com" in d[2],
          "findability: button, greeting escaped, the address in the small print")
    check(d[1].startswith("Hello Bob <i>,") and "#dsc-confirm/tok123" in d[1], "findability: the text part as before")
    framed(n[2], "notification mail")
    check("&lt;Plan&gt;" in n[2] and "<Plan>" not in n[2] and "#settings/notify" in n[2] and "and 2 more" in n[2],
          "notification mail: entries escaped, the settings link and the rest count")
    check("- Alice assigned you: <Plan> · Inbox" in n[1], "notification mail: the text part as before")

TODAY, _ = py("from kalmido.core.db import local_now\nprint(json.dumps(local_now().date().isoformat()))")  # the container's (test) clock
TODAY = TODAY or date.today().isoformat()
tid = A.post(B + "/api/tasks", json={"title": "Report <due>", "due": TODAY}).json().get("id")
j, er = py(f"from kalmido.integrations.mail import digest_mail_content\nc = app.connect()\n"
           f"print(json.dumps(digest_mail_content(c, {ALICE}, {TODAY!r})))")
check(j is not None and tid, "the daily mail is built " + er)
if j:
    framed(j[2], "daily mail")
    check(PETROL in j[2] and "/#today" in j[2] and "Report &lt;due&gt;" in j[2] and "Report <due>" in j[1], "daily mail: button, task escaped, text part as before")

# booking and portal: their frame helpers
j, er = py("from kalmido.calendars.apptbook import apb_mail_html\nfrom kalmido.team.portal import _pt_mail_html\n"
           "a = apb_mail_html(['Hello <Kim>,', ''], 'https://example.com/c/x', 'Confirm the booking', 'Ignore <it>', 'Please confirm', 'Studio <N>', 'en')\n"
           "b = apb_mail_html(['Hello'], None, None)\n"
           "p = _pt_mail_html(['Done <x>'], 'https://example.com/p', 'Show the report', 'You get <a href=\"https://example.com/stop\">stop</a>', 'Done')\n"
           "print(json.dumps([a, b, p]))")
check(j is not None, "the booking / portal helpers run " + er)
if j:
    a, b, p = j
    framed(a, "booking mail")
    check(PETROL in a and "Hello &lt;Kim&gt;," in a and "Ignore &lt;it&gt;" in a and "Studio &lt;N&gt;" in a, "booking: petrol button, texts escaped, the page's name in the head")
    check(PETROL not in b, "booking without a link: no button")
    framed(p, "portal mail")
    check(PETROL in p and "Done &lt;x&gt;" in p and '<a href="https://example.com/stop">stop</a>' in p, "portal: button, text escaped, the ready foot link")

# ================================================================ event invitation through its route
D = (date.today() + timedelta(days=5)).isoformat()
CAL = A.post(B + "/api/evcals", json={"name": "Alice Termine", "org_id": None}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Start <x>", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                    "description": "Bring <notes>", "send_invites": True, "attendees": [{"email": "ext1@example.com", "name": "Ext"}]})
check(r.status_code == 201, "an event with an external attendee " + r.text[:200])
m = wait_mail("ext1@example.com", 1)
check(len(m) == 1, f"the invitation goes out ({len(m)})")
if m:
    subj, text, hb = parts(m[0])
    framed(hb, "event invitation")
    check("Start &lt;x&gt;" in hb and "Bring &lt;notes&gt;" in hb and "calendar file" in hb, "event invitation: texts escaped, the small print")
    check("Alice Admin invites you: Start <x>" in text and "Bring <notes>" in text, "event invitation: the text part as before")

# ================================================================ a freelancer without an organisation
FID, Fr = freelancer(B, A)
FCAL = Fr.post(B + "/api/evcals", json={"name": "Frida Kalender"}).json()["id"]
r = Fr.post(B + "/api/events", json={"cal_id": FCAL, "title": "Kundentermin", "start": f"{D}T12:00", "end": f"{D}T13:00", "send_invites": True,
                                     "attendees": [{"email": "kundin@example.com", "name": "Kundin"}]})
check(r.status_code == 201, "freelancer: an event with an external attendee " + r.text[:200])
mk = wait_mail("kundin@example.com", 1)
check(len(mk) == 1, f"freelancer: the invitation goes out ({len(mk)})")
if mk:
    framed(parts(mk[0])[2], "freelancer event invitation")

print(f"\n{OKS[0]} checks ok, {len(FAILS)} failed", flush=True)
if FAILS:
    print("FAILED:\n - " + "\n - ".join(FAILS))
    sys.exit(1)
print("ALL OK")
