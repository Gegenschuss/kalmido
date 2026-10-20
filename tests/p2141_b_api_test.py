#!/usr/bin/env python3
"""2.141.0 part B (#2140, #2139): the HTML view of a filed e-mail and a task / an event made from it.
 - HTML view: GET /api/hubmail/mails/<id> says html / html_ext; GET .../html = the cleaned page with its own strict CSP
   (default-src 'none', img-src data: -- + https: with ?images=1 --, CSP sandbox, frame-ancestors 'self'), X-Frame-Options
   SAMEORIGIN, nosniff, no-referrer; script / iframe / object / embed / form / meta refresh / on* / javascript: gone, links
   open in a new tab with noopener noreferrer, cid: pictures as data: URLs, external pictures only with ?images=1; a mail
   without an HTML part (or without its .eml) = 404 there and html false
 - mail -> task / event: the picks = lists / calendars of the mail's workspace I may write in; title without Re / Fwd,
   description = text start + sender; into another workspace 409, a list I may only read 404; the task / event remembers
   the mail (hub_mail_links), the mail lists what was made from it; the mail of a task: subject only for who may read the
   mail, else neither subject nor id
 - another organisation / agents: nothing (tenant-matrix: hubmail); a person without organisation in the private space
   (freelancer-matrix: hub)
usage: p2141_b_api_test.py <datadir>      (a fresh container; P2141B_NOSTART=1: a running server with the stub mailbox)"""
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
NOSTART = os.environ.get("P2141B_NOSTART") == "1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="]
FEAT = "cal,collab,comments,events,contacts,clients"
# a 1x1 PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def js(r):
    try:
        return r.json()
    except ValueError:
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print("NO JSON:", r.status_code, r.text[:300], "\n", log.stdout[-3000:], log.stderr[-3000:], flush=True)
        return {}


NEXT = [0]
HTML = """<html><head><meta http-equiv="refresh" content="0;url=https://evil.example.com/"><title>T</title>
<style>@import url(https://evil.example.com/x.css); .box{color:#123456;background:url(https://img.example.com/bg.png)}</style>
<script>alert(1)</script><link rel="stylesheet" href="https://evil.example.com/y.css"><base href="https://evil.example.com/"></head>
<body onload="alert(2)"><div class="box" style="color:red;background-image:url('https://img.example.com/a.png');width:expression(alert(3))">Hello <b>HTML</b> world</div>
<p><a href="https://example.com/page" onclick="alert(4)">a link</a> <a href="java&#x09;script:alert(5)">bad link</a> <a href="#top">top</a></p>
<img src="cid:logo@example.test" alt="logo" onerror="alert(6)"><img src="https://img.example.com/track.gif" alt="tracker">
<img src="http://img.example.com/plain.gif"><img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" alt="svg">
<iframe src="https://evil.example.com/"></iframe><object data="x.swf"></object><embed src="x.swf">after-embed
<form action="https://evil.example.com/"><input name="pw"><button>Send</button></form><svg><script>alert(7)</script></svg>
<noscript><p>noscript-text</p></noscript><table><tr><td bgcolor="#eeeeee">cell</td></tr></table></body></html>"""


def mail(to, frm, subject, text, html=None, cid=False):
    """Drop one mail into the stub mailbox (text, + an HTML alternative, + a related picture); returns its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = f"<p2141b-{NEXT[0]}@example.test>"
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


# ---- setup: alice (admin), Alpha = bob (admin) + carol, Beta = dave, frida = a person without organisation
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
U = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    U[u] = r.json()["id"]
BOB, CAROL, DAVE = U["bob"], U["carol"], U["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [BOB, CAROL], "admins": [BOB]})
A.patch(B + f"/api/admin/orgs/{ORG2}", json={"members": [DAVE], "admins": [DAVE]})
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, BOB, CAROL, ORG2, DAVE), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "bobbot", "display_name": "Bobbot"})
AGT = r.json().get("token") or ""
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
FR, Fr = freelancer(B, A)
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + AGT})

IN_B = Bo.post(B + "/api/hubmail/address", json={"ws": f"org:{ORG}"}).json().get("address")
IN_F = Fr.post(B + "/api/hubmail/address", json={"ws": "private"}).json().get("address")
check(IN_B and IN_F, f"setup: the filing addresses ({IN_B}, {IN_F})")
M_HTML = mail(IN_B, "Shop <news@example.test>", "Re: Fwd: Spring offer", "Hello HTML world (text part)", HTML, cid=True)
M_TEXT = mail(IN_B, "Pat <pat@example.test>", "AW: Plain question", "Only text here.\nSecond line.")
M_FR = mail(IN_F, "Client <client@example.test>", "Meeting next week", "Can we meet on Tuesday?", "<p>Can we meet on <b>Tuesday</b>?</p>")
check(poll(3), "setup: three mails filed")
HM, TM, FM = mid_of(M_HTML), mid_of(M_TEXT), mid_of(M_FR)
check(HM and TM and FM, f"setup: the mail ids ({HM}, {TM}, {FM})")

# ---- #2140 the HTML view (tenant-matrix: hubmail)
m = js(Bo.get(B + f"/api/hubmail/mails/{HM}"))
check(m.get("html") is True, f"the mail has an HTML part ({m.get('html')})")
check((m.get("html_ext") or 0) >= 3, f"external pictures counted ({m.get('html_ext')})")
check(m.get("body", "").startswith("Hello HTML world"), "the text view stays as it was")
check(m.get("made") == [], f"nothing made yet ({m.get('made')})")
r = Bo.get(B + f"/api/hubmail/mails/{HM}/html")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/html"), f"the HTML page ({r.status_code} {r.headers.get('Content-Type')})")
csp = r.headers.get("Content-Security-Policy", "")
check("default-src 'none'" in csp and "img-src data:" in csp and "https:" not in csp, f"strict CSP without external pictures ({csp})")
check("sandbox" in csp and "allow-scripts" not in csp and "allow-same-origin" not in csp, "CSP sandbox without scripts / same origin")
check("frame-ancestors 'self'" in csp and "form-action 'none'" in csp and "base-uri 'none'" in csp, "CSP: framed only by the app, no forms, no base")
check(r.headers.get("X-Frame-Options") == "SAMEORIGIN", f"X-Frame-Options SAMEORIGIN ({r.headers.get('X-Frame-Options')})")
check(r.headers.get("X-Content-Type-Options") == "nosniff" and r.headers.get("Referrer-Policy") == "no-referrer", "nosniff + no-referrer")
check("no-store" in r.headers.get("Cache-Control", ""), "not cached")
h = r.text
low = h.lower()
check("<script" not in low and "alert(" not in low, "no script and no script text")
check(" onload" not in low and " onclick" not in low and " onerror" not in low, "no on* attributes")
check("javascript" not in low and "expression(" not in low and "@import" not in low, "no javascript:, expression(), @import")
check("<iframe" not in low and "<object" not in low and "<embed" not in low and "<form" not in low and "<input" not in low, "no iframe / object / embed / form / input")
check("http-equiv" not in low and "evil.example.com" not in low and "<link" not in low, "no meta refresh, no foreign base / link / stylesheet")
check("<svg" not in low and "image/svg" not in low, "no SVG (inline or as a picture)")
check("noscript-text" not in h, "noscript content gone")
check("after-embed" in h and "Hello <b>HTML</b> world" in h and ">cell</td>" in h, "the content stays (text, bold, table)")
check('href="https://example.com/page"' in h and 'target="_blank"' in h and 'rel="noopener noreferrer"' in h, "links open in a new tab, noopener noreferrer")
check("<a>bad link</a>" in h, "the javascript link keeps its text but loses the address")
check('href="#top" target="_self"' in h, "an anchor inside the mail stays in the frame")
check('src="data:image/png;base64,' in h, "the cid: picture as a data: URL")
check("img.example.com" not in h, "external pictures (img, CSS url) left out")
check(".box{color:#123456" in h, "the style block stays (cleaned)")
r = Bo.get(B + f"/api/hubmail/mails/{HM}/html?images=1")
csp = r.headers.get("Content-Security-Policy", "")
check(r.ok and "img-src data: https:" in csp, f"Load images: https pictures allowed ({csp})")
check('src="https://img.example.com/track.gif"' in r.text and 'src="https://img.example.com/plain.gif"' in r.text, "the external pictures (http raised to https)")
check("https://img.example.com/a.png" in r.text and "https://img.example.com/bg.png" in r.text, "CSS pictures with Load images")
check("javascript" not in r.text.lower() and "<script" not in r.text.lower(), "Load images keeps the rest cleaned")
t = js(Bo.get(B + f"/api/hubmail/mails/{TM}"))
check(t.get("html") is False and t.get("html_ext") == 0, f"a text mail: no HTML ({t.get('html')})")
check(Bo.get(B + f"/api/hubmail/mails/{TM}/html").status_code == 404, "a text mail: no HTML page")
# the original gone (or damaged) = the text view
dbx("UPDATE hub_mails SET eml_id=NULL WHERE id=?", (TM,), write=True)
check(js(Bo.get(B + f"/api/hubmail/mails/{TM}")).get("html") is False, "without the original: the text view")
check(Da.get(B + f"/api/hubmail/mails/{HM}/html").status_code == 404, "another organisation: 404")
check(Ca.get(B + f"/api/hubmail/mails/{HM}/html").status_code == 404, "a colleague: bob's unassigned mail is not hers (404)")
check(AG.get(B + f"/api/hubmail/mails/{HM}/html").status_code in (401, 403), "an agent: nothing")
check(Bo.get(B + "/api/hubmail/mails/999999/html").status_code == 404, "an unknown mail: 404")

# ---- #2139 mail -> task / event
PLA = Bo.post(B + "/api/lists", json={"name": "Alpha work", "org_id": ORG}).json()["id"]
PRIV = Bo.post(B + "/api/lists", json={"name": "Bob home", "org_id": None}).json()["id"]
CL = Ca.post(B + "/api/lists", json={"name": "Carol read", "org_id": ORG}).json()["id"]
check(Ca.put(B + f"/api/lists/{CL}/members", json={"user_id": BOB, "role": "view"}).ok, "setup: bob may only read Carol read")
check(Bo.put(B + f"/api/lists/{PLA}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol works in Alpha work")
r = Bo.post(B + "/api/evcals", json={"name": "Alpha cal", "org_id": ORG})
check(r.ok, f"setup: an Alpha calendar ({r.status_code} {r.text[:120]})")
CAL = js(r).get("id")
CALP = js(Bo.post(B + "/api/evcals", json={"name": "Bob private cal", "org_id": None})).get("id")
mk = js(Bo.get(B + f"/api/hubmail/mails/{HM}/make"))
lids = {x["id"] for x in mk.get("lists", [])}
check(PLA in lids and PRIV not in lids and CL not in lids, f"picks: only writable lists of the mail's workspace ({sorted(lids)})")
cids = {x["id"] for x in mk.get("calendars", [])}
check(CAL in cids and CALP not in cids, f"picks: only calendars of the mail's workspace ({sorted(cids)})")
check(mk.get("title") == "Spring offer", f"title without Re / Fwd ({mk.get('title')})")
check("Hello HTML world" in mk.get("description", "") and "news@example.test" in mk.get("description", ""), "description = text start + sender")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PRIV}).status_code == 409, "a task into another workspace: 409")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": CL}).status_code == 404, "a list bob may only read: 404")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": "x"}).status_code == 400, "a bad list id: 400")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PLA, "due": "tomorrow"}).status_code == 400, "a bad date: 400")
check(Da.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PLA}).status_code == 404, "another organisation: 404")
check(AG.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PLA}).status_code in (401, 403), "an agent: nothing")
r = Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PLA, "due": "2026-10-23"})
check(r.status_code == 201, f"a task from the mail ({r.status_code} {r.text[:200]})")
TID = js(r).get("task_id")
tk = js(Bo.get(B + f"/api/tasks/{TID}"))
check(tk.get("title") == "Spring offer" and tk.get("list_id") == PLA and tk.get("due") == "2026-10-23", f"the task: title, list, date ({tk.get('title')}, {tk.get('due')})")
check("news@example.test" in (tk.get("content") or ""), "the task's description names the sender")
check(not any(k.startswith(("mail", "hub")) for k in tk), "the task answer carries no mail data (agents read tasks)")
lk = js(Bo.get(B + f"/api/hubmail/links?task_id={TID}"))
check(lk.get("links") == [{"mail_id": HM, "subject": "Re: Fwd: Spring offer"}], f"the task knows its mail ({lk})")
lk = js(Ca.get(B + f"/api/hubmail/links?task_id={TID}"))
check(lk.get("links") == [{"mail_id": None, "subject": ""}], f"carol sees the task, not the mail: no subject, no id ({lk})")
check(Da.get(B + f"/api/hubmail/links?task_id={TID}").status_code == 404, "another organisation: the task's link 404")
check(AG.get(B + f"/api/hubmail/links?task_id={TID}").status_code in (401, 403), "an agent: no link")
check(Bo.get(B + "/api/hubmail/links").status_code == 400, "links without a task / event: 400")
r = Bo.post(B + f"/api/hubmail/mails/{HM}/task", json={"list_id": PLA, "title": "  Own   title "})
check(r.status_code == 201 and js(Bo.get(B + f"/api/tasks/{js(r).get('task_id')}")).get("title") == "Own title", "an own title")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/event", json={"cal_id": CALP, "start": "2026-10-23"}).status_code == 409, "an event into another workspace: 409")
check(Bo.post(B + f"/api/hubmail/mails/{HM}/event", json={"cal_id": CAL, "start": "soon"}).status_code == 400, "a bad start: 400")
r = Bo.post(B + f"/api/hubmail/mails/{HM}/event", json={"cal_id": CAL, "start": "2026-10-23T14:30"})
check(r.status_code == 201, f"an event from the mail ({r.status_code} {r.text[:200]})")
EID = js(r).get("event_id")
ev = js(Bo.get(B + f"/api/events/{EID}"))
check(ev.get("title") == "Spring offer" and ev.get("start", "").startswith("2026-10-23T14:30") and not ev.get("all_day"), f"the event: title, time ({ev.get('start')})")
check("news@example.test" in (ev.get("description") or ""), "the event's description names the sender")
r = Bo.post(B + f"/api/hubmail/mails/{HM}/event", json={"cal_id": CAL, "start": "2026-10-24"})
check(r.status_code == 201 and js(Bo.get(B + f"/api/events/{js(r).get('event_id')}")).get("all_day"), "a date only = all day")
check(js(Bo.get(B + f"/api/hubmail/links?event_id={EID}")).get("links") == [{"mail_id": HM, "subject": "Re: Fwd: Spring offer"}], "the event knows its mail")
made = js(Bo.get(B + f"/api/hubmail/mails/{HM}")).get("made") or []
check([x["kind"] for x in made] == ["task", "task", "event", "event"] and made[0]["id"] == TID and made[0]["title"] == "Spring offer", f"the mail lists what was made ({made})")
check(len(dbx("SELECT id FROM hub_mail_links WHERE mail_id=? AND org_id=?", (HM, ORG))) == 4, "hub_mail_links rows in the mail's organisation")
# a deleted task drops out of the mail's list; the deleted mail leaves only "E-mail"
Bo.delete(B + f"/api/tasks/{TID}")
check(TID not in [x["id"] for x in js(Bo.get(B + f"/api/hubmail/mails/{HM}")).get("made") or [] if x["kind"] == "task"], "a deleted task leaves the mail's list")
Bo.delete(B + f"/api/hubmail/mails/{HM}")
check(js(Bo.get(B + f"/api/hubmail/links?event_id={EID}")).get("links") == [{"mail_id": None, "subject": ""}], "a deleted mail: only 'E-mail'")
Bo.post(B + f"/api/hubmail/mails/{HM}/restore", json={})

# ---- a person without organisation (freelancer-matrix: hub)
FL = Fr.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
FC = js(Fr.post(B + "/api/evcals", json={"name": "Frida cal"})).get("id")
fm = js(Fr.get(B + f"/api/hubmail/mails/{FM}"))
check(fm.get("html") is True and fm.get("html_ext") == 0, f"freelancer: the HTML view of a private mail ({fm.get('html')})")
r = Fr.get(B + f"/api/hubmail/mails/{FM}/html")
check(r.ok and "<b>Tuesday</b>" in r.text, "freelancer: the cleaned page")
mk = js(Fr.get(B + f"/api/hubmail/mails/{FM}/make"))
check(FL in {x["id"] for x in mk.get("lists", [])} and FC in {x["id"] for x in mk.get("calendars", [])}, "freelancer: own list + calendar offered")
check(PRIV not in {x["id"] for x in mk.get("lists", [])}, "freelancer: never another person's private list")
check(Fr.post(B + f"/api/hubmail/mails/{FM}/task", json={"list_id": PRIV}).status_code == 404, "freelancer: bob's private list 404")
r = Fr.post(B + f"/api/hubmail/mails/{FM}/task", json={"list_id": FL})
check(r.status_code == 201, f"freelancer: a task from the mail ({r.status_code})")
r2 = Fr.post(B + f"/api/hubmail/mails/{FM}/event", json={"cal_id": FC, "start": "2026-10-27"})
check(r2.status_code == 201, f"freelancer: an event from the mail ({r2.status_code})")
check(js(Fr.get(B + f"/api/hubmail/links?task_id={js(r).get('task_id')}")).get("links") == [{"mail_id": FM, "subject": "Meeting next week"}], "freelancer: the task knows its mail")
check(js(Fr.get(B + f"/api/hubmail/links?event_id={js(r2).get('event_id')}")).get("links", [{}])[0].get("mail_id") == FM, "freelancer: the event knows its mail")
check(Bo.get(B + f"/api/hubmail/mails/{FM}/html").status_code == 404 and Bo.get(B + f"/api/hubmail/mails/{FM}/make").status_code == 404, "the freelancer's mail stays hers")
check(Bo.get(B + f"/api/hubmail/links?task_id={js(r).get('task_id')}").status_code == 404, "the freelancer's task stays hers")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed", flush=True)
if not NOSTART:
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
sys.exit(1 if FAILS else 0)
