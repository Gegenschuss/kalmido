#!/usr/bin/env python3
"""2.63.0 API tests (part B): #1513 the customer portal. Own container with the e-mail stub (stub_mail.py), organisations
(mode workspaces) and a fast watchdog. Invented names and example.com addresses only.
 - the status page /p/<token>: title, state, the reporter's own text (until the team edits the description; never the form's
   signature line with the address), the public answers (team: display name) and the customer's comments -- never internal
   comments (not even in the HTML); headers (CSP, noindex, no referrer), no scripts; an unknown / guessed / deleted ticket = the
   same 404
 - the customer answers: portal = 1, ext_name, user_id NULL, News for the team; without the form check value or cross-site 403
 - comments with portal: only on a task with a ticket, only with write access, never with answer buttons; the timeline's
   ticket (address + status link for writers only), PATCH /api/tasks/{id}/ticket {notify}
 - mails: a public answer -> one mail with the status link and the off link; at most one per ticket within 10 minutes (the
   rest goes out together); "done"; the off link turns them off (no mail then)
 - sign-in: the same answer for an unknown address (no mail), the mail's link works once (a button page first), expired
   = 404, /portal shows the tickets of the same address in the SAME organisation only, sign-out, a forged cookie
 - agents: a public answer only in a shared list (v1, portal true), the customer's comment reaches a following agent as an event
   with portal + ext_name; another organisation's person sees nothing of the ticket; the client's card lists its reports
tenant-matrix: portal
usage: p263_b_api_test.py <datadir>"""
import email
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=30):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_INSTANCE_MODE=workspaces", "-e", "TASKS_WATCHDOG_INTERVAL=2"]
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
time.sleep(0.8)
OUT = os.path.join(DATA, "mail", "out.jsonl")


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbq(q, a=()):
    c = dbx.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(q, a).fetchall()
    finally:
        c.close()


def mails(to=None):
    """The mails the stub got: [(to, subject, plain text)]."""
    out = []
    try:
        lines = open(OUT, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return out
    for ln in lines:
        j = json.loads(ln)
        m = email.message_from_string(j["raw"])
        txt = ""
        for part in m.walk():
            if part.get_content_type() == "text/plain":
                txt += part.get_payload(decode=True).decode("utf-8", "replace")
        if to is None or any(to in x for x in j["to"]):
            out.append((j["to"], str(email.header.make_header(email.header.decode_header(m["Subject"] or ""))), txt))
    return out


def ticket(task_id, list_id, name, mail):
    """A ticket as the form (part A) creates it: team/portal.py pt_create inside the container -> the status-link token."""
    code = ("import sys, app\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.team.portal import pt_create\nc = app.connect()\n"
            "with system_ctx(c):\n    l = c.execute('SELECT id, org_id, owner_id FROM lists WHERE id=?', (int(sys.argv[2]),)).fetchone()\n"
            "    t = pt_create(c, int(sys.argv[1]), l, None, sys.argv[3], sys.argv[4])\nc.commit()\nprint(t[1])")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code, str(task_id), str(list_id), name, mail], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-600:]
    return out.stdout.strip().splitlines()[-1]


def key(html, action):
    m = re.search(r'action="' + re.escape(action) + r'"[^>]*>\s*<input type="hidden" name="f" value="([0-9a-f]{64})"', html)
    return m.group(1) if m else ""


P = requests.Session()  # the reporter: no account, no app header


# ---------------------------------------------------------------- setup: organisations Alpha (alice admin, bob edits, eve views) and Beta (carol)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "clients"]})
for u, n in (("bob", "Bob Team"), ("carol", "Carol Other"), ("eve", "Eve Viewer")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
Bo, Ca, Ev = sess("bob"), sess("carol"), sess("eve")
for s in (A, Bo, Ca, Ev):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,clients", "tour": "done"})
st = A.get(B + "/api/state").json()
ALICE = st["me"]["id"]
BOB, CAROL, EVE = (sess(u).get(B + "/api/state").json()["me"]["id"] for u in ("bob", "carol", "eve"))
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u in ("bob", "eve"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ev, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
L = A.post(B + "/api/lists", json={"name": "Support", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": EVE, "role": "view"}).ok
L2 = Ca.post(B + "/api/lists", json={"name": "Beta Support", "org_id": ORG2}).json()["id"]
SIG = "\n\n— Sent with the form “Report a bug” by Jane Example <jane@example.com>"
T1 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Export button does nothing", "content": "Clicking Export shows nothing at all." + SIG}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Second report of Jane", "content": "Another thing." + SIG}).json()["id"]
T4 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Plain internal task"}).json()["id"]
T2 = Ca.post(B + "/api/tasks", json={"list_id": L2, "title": "Beta ticket of the same address", "content": "Beta text." + SIG}).json()["id"]
TK1, TK3, TK2 = ticket(T1, L, "Jane Example", "Jane@Example.com"), ticket(T3, L, "Jane Example", "jane@example.com"), ticket(T2, L2, "Jane B", "jane@example.com")
check(len(TK1) >= 30 and TK1 != TK3, "setup: tickets with status-link tokens")
row = dbq("SELECT email, email_hash, token, token_hash, org_id, notify FROM portal_tickets WHERE task_id=?", (T1,))[0]
check("jane" not in (row["email"] or "").lower() and row["email_hash"] and TK1 not in row["token"] and row["org_id"] == ORG and row["notify"] == 1,
      "setup: the address and the token are stored sealed / hashed")

# ---------------------------------------------------------------- the status page
r = P.get(B + f"/p/{TK1}")
check(r.status_code == 200 and "Export button does nothing" in r.text and "Clicking Export shows nothing at all." in r.text, f"#1513: status page shows title + text {r.status_code}")
check("Sent with the form" not in r.text and "jane@example.com" not in r.text.lower(), "#1513: never the form's signature line / the address")
check("<script" not in r.text.lower() and "default-src 'none'" in r.headers.get("Content-Security-Policy", "")
      and "noindex" in r.headers.get("X-Robots-Tag", "") and r.headers.get("Referrer-Policy") == "no-referrer", "#1513: no scripts, CSP, noindex, no referrer")
check('class="ptst ptst-open"' in r.text, "#1513: state open (received)")
check(dbq("SELECT last_seen_at FROM portal_tickets WHERE task_id=?", (T1,))[0][0], "#1513: last_seen_at set")
r404a, r404b = P.get(B + "/p/" + secrets.token_urlsafe(24)), P.get(B + "/p/" + secrets.token_urlsafe(24))
check(r404a.status_code == 404 and r404b.status_code == 404 and r404a.text == r404b.text, "#1513: a guessed token = 404, always the same page")
check(P.get(B + "/p/short").status_code == 404, "#1513: a malformed token = 404")
check(Ca.get(B + f"/p/{TK1}").status_code == 200, "#1513: the page works for anyone with the link (signed in or not)")

# internal vs public comments
r = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "INTERNAL-SECRET-NOTE for <@%d>" % BOB})
check(r.ok and r.json().get("portal") is False, "#1513: a comment is internal by default")
r = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Thanks, we are looking into it.", "portal": True})
check(r.ok and r.json().get("portal") is True, "#1513: a public answer (portal true)")
PUB1 = r.json()["id"]
r = P.get(B + f"/p/{TK1}")
check("Thanks, we are looking into it." in r.text and "Alice Admin" in r.text, "#1513: the public answer with the author's display name")
check("INTERNAL-SECRET-NOTE" not in r.text and "Bob Team" not in r.text and "alice" not in r.text.replace("Alice Admin", ""),
      "#1513: internal comments / user names never in the HTML")
check(A.post(B + f"/api/tasks/{T4}/comments", json={"body": "x", "portal": True}).status_code == 400, "#1513: portal on a task without a ticket: 400")
check(Ev.post(B + f"/api/tasks/{T1}/comments", json={"body": "viewer to customer", "portal": True}).status_code == 400, "#1513: a viewer cannot answer the customer")
check(Ev.post(B + f"/api/tasks/{T1}/comments", json={"body": "viewer internal"}).ok, "#1513: ... but comments internally as before")
check(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "portal": "maybe"}).status_code == 400, "#1513: portal: true / false only")
check(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "Bob answers too", "portal": True}).ok, "#1513: a member with write access answers the customer")
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
k = tl.get("ticket") or {}
check(k.get("email") == "jane@example.com" and k.get("url", "").endswith("/p/" + TK1) and k.get("notify") is True and k.get("name") == "Jane Example",
      f"#1513: the timeline's ticket for a writer {k}")
check(any(c["id"] == PUB1 and c["portal"] for c in tl["comments"]), "#1513: comments carry portal in the app")
ke = Ev.get(B + f"/api/tasks/{T1}/timeline").json().get("ticket") or {}
check(ke.get("name") == "Jane Example" and "email" not in ke and "url" not in ke, f"#1513: a viewer sees the report, not the address / link {ke}")
check(A.get(B + f"/api/tasks/{T4}/timeline").json().get("ticket") is None, "#1513: a task without a ticket: ticket null")
check(Ca.get(B + f"/api/tasks/{T1}/timeline").status_code == 404 and Ca.patch(B + f"/api/tasks/{T1}/ticket", json={"notify": False}).status_code in (403, 404),
      "#1513: another organisation's person sees / changes nothing")
check(Ev.patch(B + f"/api/tasks/{T1}/ticket", json={"notify": False}).status_code == 403, "#1513: a viewer cannot switch the mails")
check(A.patch(B + f"/api/tasks/{T1}/ticket", json={"notify": "no"}).status_code == 400, "#1513: notify: a boolean")

# ---------------------------------------------------------------- the customer answers
page = P.get(B + f"/p/{TK1}").text
f = key(page, f"/p/{TK1}/comment")
check(bool(f), "#1513: the answer form has its check value")
check(P.post(B + f"/p/{TK1}/comment", data={"text": "no key"}).status_code == 403, "#1513: without the check value 403")
check(P.post(B + f"/p/{TK1}/comment", data={"text": "cross", "f": f}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403, "#1513: cross-site 403")
check(P.post(B + f"/p/{TK3}/comment", data={"text": "other ticket's key", "f": f}).status_code == 403, "#1513: the key of another ticket 403")
r = P.post(B + f"/p/{TK1}/comment", data={"text": "It happens in Firefox too <@1>.", "f": f}, allow_redirects=False)
check(r.status_code == 303 and r.headers.get("Location", "").startswith(f"/p/{TK1}"), f"#1513: the answer is taken {r.status_code}")
c = dbq("SELECT user_id, portal, ext_name, body FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T1,))[0]
check(c["user_id"] is None and c["portal"] == 1 and c["ext_name"] == "Jane Example" and "<@1>" not in c["body"], f"#1513: a customer's comment {dict(c)}")
news = [x for x in A.get(B + "/api/news").json().get("items", []) if x["kind"] == "comment" and (x.get("data") or {}).get("portal")]
check(news and news[0]["data"].get("ext_name") == "Jane Example", "#1513: News for the team")
check("It happens in Firefox too" in P.get(B + f"/p/{TK1}").text, "#1513: the customer's comment on the page")
n0 = dbq("SELECT COUNT(*) FROM comments WHERE task_id=?", (T1,))[0][0]
P.post(B + f"/p/{TK1}/comment", data={"text": "   ", "f": f})
check(dbq("SELECT COUNT(*) FROM comments WHERE task_id=?", (T1,))[0][0] == n0, "#1513: an empty answer is not stored")
ap = A.get(B + f"/api/tasks/{T1}/timeline").json()["comments"]
check(any(x["ext_name"] == "Jane Example" and x["portal"] for x in ap), "#1513: the app sees the customer's comment with portal")

# ---------------------------------------------------------------- mails to the reporter
first = until(lambda: [m for m in mails("jane@example.com") if "Export button does nothing" in m[1]], 25)
check(len(first) == 1 and f"/p/{TK1}" in first[0][2] and f"/p/{TK1}/stop" in first[0][2] and "Thanks, we are looking into it." in first[0][2]
      and "INTERNAL-SECRET-NOTE" not in first[0][2], f"#1513: one mail with the answers, the status link and the off link {first}")
A.post(B + f"/api/tasks/{T1}/comments", json={"body": "A second public answer.", "portal": True})
time.sleep(6)
check(len([m for m in mails("jane@example.com") if "Export button" in m[1]]) == 1, "#1513: at most one mail per ticket within 10 minutes")
dbq("UPDATE portal_tickets SET last_mail_at='2020-01-01T00:00:00+00:00' WHERE task_id=?", (T1,))
two = until(lambda: [m for m in mails("jane@example.com") if "Export button" in m[1]][1:], 25)
check(two and "A second public answer." in two[0][2], "#1513: after the gap the waiting answer goes out")
check(A.post(B + f"/api/tasks/{T1}/complete", json={}).ok, "#1513: the task is done")
dbq("UPDATE portal_tickets SET last_mail_at='2020-01-01T00:00:00+00:00' WHERE task_id=?", (T1,))
done = until(lambda: [m for m in mails("jane@example.com") if m[1].startswith("Done:")], 25)
check(done and "Export button does nothing" in done[0][1], "#1513: a mail when the report is done")
check('ptst-done' in P.get(B + f"/p/{TK1}").text, "#1513: the page says done")
r = P.get(B + f"/p/{TK1}/stop")
check(r.status_code == 200 and dbq("SELECT notify FROM portal_tickets WHERE task_id=?", (T1,))[0][0] == 0, "#1513: the off link turns the mails off")
n = len(mails("jane@example.com"))
A.post(B + f"/api/tasks/{T1}/comments", json={"body": "After the stop.", "portal": True})
dbq("UPDATE portal_tickets SET last_mail_at='2020-01-01T00:00:00+00:00' WHERE task_id=?", (T1,))
time.sleep(6)
check(len(mails("jane@example.com")) == n, "#1513: notify off = no mail")
check(A.patch(B + f"/api/tasks/{T1}/ticket", json={"notify": True}).json().get("notify") is True, "#1513: the team turns the mails on again")

# ---------------------------------------------------------------- sign-in and the portal
page = P.get(B + f"/p/{TK3}").text
fl = key(page, f"/p/{TK3}/login")
n = len(mails())
r1 = P.post(B + f"/p/{TK3}/login", data={"email": "nobody@example.com", "f": fl}, allow_redirects=False)
r2 = P.post(B + f"/p/{TK3}/login", data={"email": "JANE@example.com", "f": fl}, allow_redirects=False)
check(r1.status_code == r2.status_code == 303 and r1.headers["Location"] == r2.headers["Location"], "#1513: the same answer for an unknown address")
check(P.post(B + f"/p/{TK3}/login", data={"email": "jane@example.com"}).status_code == 403, "#1513: the sign-in form needs its check value")
got = until(lambda: [m for m in mails() if "sign-in link" in m[1]], 20)
time.sleep(1)
check(len([m for m in mails() if "sign-in link" in m[1]]) == 1 and not mails("nobody@example.com"), "#1513: a mail only to the known address")
lk = re.search(r"/portal/login/([A-Za-z0-9_-]{30,64})", got[0][2] if got else "")
lk = lk.group(1) if lk else ""
g = P.get(B + f"/portal/login/{lk}")
check(g.status_code == 200 and "kalmido_portal" not in g.headers.get("Set-Cookie", "") and "<form" in g.text, "#1513: the link opens a button page (no sign-in by GET)")
check(dbq("SELECT used_at FROM portal_logins ORDER BY id DESC LIMIT 1")[0][0] is None, "#1513: ... the link is not used up by opening it")
J = requests.Session()
r = J.post(B + f"/portal/login/{lk}", allow_redirects=False)
ck = r.headers.get("Set-Cookie", "")
check(r.status_code == 303 and "kalmido_portal=" in ck and "HttpOnly" in ck and "Path=/portal" in ck and "SameSite=Lax" in ck, f"#1513: sign-in sets the portal cookie {ck}")
check(requests.post(B + f"/portal/login/{lk}", allow_redirects=False).status_code == 404, "#1513: the link works once")
pg = J.get(B + "/portal").text
check("Export button does nothing" in pg and "Second report of Jane" in pg and "Beta ticket" not in pg, "#1513: the portal shows the same organisation's tickets only")
check(f"/p/{TK1}" in pg and f"/p/{TK2}" not in pg, "#1513: links to the status pages")
bad = "z" * 40
dbq("INSERT INTO portal_logins(email_hash,org_id,owner_id,token_hash,created_at,expires_at) VALUES(?,?,NULL,?,?,?)",
    (row["email_hash"], ORG, hashlib.sha256(bad.encode()).hexdigest(), "2020-01-01T00:00:00+00:00", "2020-01-01T00:30:00+00:00"))
check(requests.post(B + f"/portal/login/{bad}", allow_redirects=False).status_code == 404 and requests.get(B + f"/portal/login/{bad}").status_code == 404,
      "#1513: an expired link = 404")
forged = requests.Session()
v = J.cookies.get("kalmido_portal") or ""
forged.cookies.set("kalmido_portal", v[:-4] + ("0000" if not v.endswith("0000") else "1111"), path="/portal")
check("Export button" not in forged.get(B + "/portal").text, "#1513: a changed cookie shows nothing")
fo = re.search(r'name="f" value="([0-9a-f]{64})"', pg)
check(J.post(B + "/portal/logout", data={"f": "x"}).status_code == 403, "#1513: sign-out needs its check value")
r = J.post(B + "/portal/logout", data={"f": fo.group(1) if fo else ""}, allow_redirects=False)
check(r.status_code == 303 and "Export button" not in J.get(B + "/portal").text, "#1513: signed out")

# ---------------------------------------------------------------- deleted task = gone
A.delete(B + f"/api/tasks/{T3}")
r = P.get(B + f"/p/{TK3}")
check(r.status_code == 404 and r.text == r404a.text, "#1513: a deleted task's status page = the same 404")

# ---------------------------------------------------------------- agents
ra = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper", "scopes": ["read", "comments", "tasks:write"]})
assert ra.status_code == 201, ra.text
AG, AT = ra.json()["id"], tok(ra.json().get("token") or "")
dbq("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (AG, ORG))
dbq("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG))
dbq("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, AG))
check(AT.post(V + f"/tasks/{T1}/comments", json={"body": "agent", "portal": True}).status_code in (403, 404), "#1513: an agent without the list: no answer")
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
r = AT.post(V + f"/tasks/{T1}/comments", json={"body": "We fixed it in the next version.", "portal": True})
check(r.status_code == 201 and r.json().get("portal") is True, f"#1513: an agent answers the customer in a shared list {r.status_code} {r.text[:200]}")
check(AT.post(V + f"/tasks/{T1}/comments", json={"body": "q", "portal": True, "choices": ["a", "b"]}).status_code == 400, "#1513: no answer buttons to a customer")
check(AT.post(V + f"/tasks/{T4}/comments", json={"body": "q", "portal": True}).status_code == 400, "#1513: the API refuses portal without a ticket")
cs = AT.get(V + f"/tasks/{T1}/comments").json()["data"]
check(any(x["portal"] and x["author"].get("customer") for x in cs) and any(not x["portal"] for x in cs), "#1513: v1 comments carry portal (+ customer)")
check("Team" in P.get(B + f"/p/{TK1}").text and "Helper" not in P.get(B + f"/p/{TK1}").text, "#1513: an agent's answer shows as 'Team'")
f = key(P.get(B + f"/p/{TK1}").text, f"/p/{TK1}/comment")
P.post(B + f"/p/{TK1}/comment", data={"text": "Great, thank you!", "f": f})
evs = [json.loads(x[0]).get("data") or {} for x in dbq("SELECT payload FROM agent_events WHERE agent_id=? AND event='comment' ORDER BY id", (AG,))]
ce = [e for e in evs if (e.get("comment") or {}).get("ext_name") == "Jane Example"]
check(ce and ce[-1]["comment"].get("portal") is True and ce[-1]["comment"].get("author_id") is None, f"#1513: the customer's comment reaches the agent as an event {evs[-1:]}")
check(Ca.get(B + f"/api/tasks/{T1}").status_code in (403, 404), "#1513: RLS: another organisation does not see the task")

# ---------------------------------------------------------------- the team edits the description: the page shows the title only
check(A.patch(B + f"/api/tasks/{T1}", json={"content": "Root cause: the internal module X." + SIG}).ok, "setup: the team edits the notes")
pg = P.get(B + f"/p/{TK1}").text
check("Root cause" not in pg and "Clicking Export" not in pg and "Export button does nothing" in pg, "#1513: after an edit only the title (never the team's notes)")

# ---------------------------------------------------------------- the client's card
CL = A.post(B + "/api/clients", json={"name": "Example Corp", "org_id": ORG, "contacts": [{"name": "Jane Example", "email": "jane@example.com"}]}).json()["id"]
dbq("UPDATE portal_tickets SET client_id=NULL WHERE task_id=?", (T1,))
P.get(B + f"/p/{TK1}")
check(dbq("SELECT client_id FROM portal_tickets WHERE task_id=?", (T1,))[0][0] == CL, "#1513: the ticket finds the client by the contact's address")
ts = A.get(B + f"/api/clients/{CL}").json().get("tickets") or []
check([t["task_id"] for t in ts] == [T1] and ts[0]["done"] is True, f"#1513: the client's card lists its reports {ts}")
check(not dbq("SELECT 1 FROM portal_tickets WHERE task_id=? AND client_id IS NOT NULL", (T2,)), "#1513: never a client of another organisation")

print(f"p263_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
sys.exit(1 if FAILS else 0)
