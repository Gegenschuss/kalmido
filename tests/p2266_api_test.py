#!/usr/bin/env python3
"""2.266.0 API tests (Audit M: notifications arrive), own container (start.sh, SMTP sink stub_mail.py). Invented names only.
 - #2962 the assignee's own due reminder passes the owner's template "read" (a comment by the owner stays capped)
 - #2970 a DM with someone removed from the organisation (and the list) is frozen: no new message (403), no edit, no
   reaction, no push for the other one; the room stays readable and says closed
 - #2965 a customer's decision through a link: a News item "signoff" + an absolute push link for the active creator; a
   creator who is no longer in the office gets nothing, the office admins get it instead
 - #2963 security mails to the person: new device, password changed, e-mail changed (old + new address), deactivated,
   registration approved; the first sign-in of an account only stores its browser
 - #2964 with KALMIDO_ROLE=web (no watchdog in the process) an admin alert of a request still reaches the admin_alerts
usage: p2266_api_test.py <datadir>      (P2266_NOSTART=1: a running server, no start.sh)"""
import email
import email.policy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, DATA, check, sess, until  # noqa: E402

FEAT = "cal,comments,collab,office,clients"
SMTP = {"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
        "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
        return r
    finally:
        c.close()


def pushes(topic):
    try:
        return [p for p in (json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()) if p["topic"] == topic]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def mails():
    out = []
    try:
        for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8"):
            m = json.loads(x)
            msg = email.message_from_string(m["raw"], policy=email.policy.default)
            body = msg.get_body(("plain",))
            out.append({"to": [t.lower() for t in m["to"]], "subject": str(msg["subject"] or ""), "text": body.get_content() if body else ""})
    except OSError:
        pass
    return out


def mail_to(addr, part, wait=12):
    return until(lambda: [m for m in mails() if addr in m["to"] and part in m["subject"]], wait)


def stub_mail():
    os.makedirs(os.path.join(DATA, "mail"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
    time.sleep(1)


os.environ["KALMIDO_NOTIF_TEMPLATE"] = "read"  # the app's own default (start.sh: all)
if kt.fresh(env=SMTP, prefix="P2266"):
    stub_mail()
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
check(A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "t-alice", "email": "alice@example.com"}).ok, "setup: alice's topic")
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
for e in ("bob@example.com", "carol@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": e, "role": "member"}).ok
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
L = A.post(B + "/api/lists", json={"name": "Spring campaign", "org_id": ORG, "kind": "project"}).json()["id"]
for u in (BOB, CAROL):
    check(A.put(B + f"/api/lists/{L}/members", json={"user_id": u, "role": "edit"}).ok, f"setup: {u} in the list")

# ================================================================ #2962 the assignee's own reminder under "read"
now = datetime.now(ZoneInfo("Europe/Berlin"))
if now.hour < 23 or now.minute < 50:
    clear()
    due = (now + timedelta(minutes=2)).strftime("%H:%M")
    T = A.post(B + "/api/tasks", json={"title": "Book the studio", "list_id": L, "assignee_id": BOB, "due": now.date().isoformat(),
                                       "due_time": due, "reminders": "5"}).json()["id"]
    check(until(lambda: [p for p in pushes("t-bob") if p["title"] == "Book the studio"], 8),
          "#2962: the assignee's own due reminder pushes although the owner's template is read")
    clear()
    A.post(B + f"/api/tasks/{T}/comments", json={"body": "a plain comment"})
    time.sleep(2.5)
    check(not pushes("t-bob"), "#2962: a plain comment of the owner stays capped by read (the template still works)")

# ================================================================ #2970 a DM after leaving the organisation
r = Bo.post(B + "/api/team/dm", json={"user_id": CAROL})
check(r.ok, f"setup: bob opens a DM with carol ({r.status_code} {r.text[:100]})")
DM = r.json().get("id")
r = Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Hello from the team"})
check(r.ok, "#2970: while they work together bob writes")
MID = r.json().get("id") if r.ok else None
until(lambda: pushes("t-carol"), 8)  # the push of this allowed message first (TASKS_PUSH_GAP may delay it), then clear()
time.sleep(1)
check(A.delete(B + f"/api/lists/{L}/members/{BOB}").ok, "setup: bob leaves the list")
check(A.delete(B + f"/api/orgs/{ORG}/members/{BOB}").ok, "setup: bob is removed from the organisation")
clear()
r = Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Am I still in?"})
check(r.status_code == 403, f"#2970: the ex-member cannot write in the DM any more ({r.status_code})")
check(Ca.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "hi"}).status_code == 403, "#2970: the other side cannot write either")
if MID:
    check(Bo.patch(B + f"/api/team/messages/{MID}", json={"body": "edited"}).status_code == 403, "#2970: no edit in a frozen DM")
    check(Ca.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "up"}).status_code == 403, "#2970: no reaction in a frozen DM")
time.sleep(1.5)
check(not pushes("t-carol"), "#2970: no push reaches carol")
r = Bo.get(B + f"/api/team/rooms/{DM}/messages")
check(r.ok and "Hello from the team" in r.text, "#2970: the old messages stay readable")
room = next((x for x in Ca.get(B + "/api/team").json().get("rooms", []) if x["id"] == DM), {})
check(room.get("closed") is True, f"#2970: the room says closed {room}")

# ================================================================ #2965 a customer's decision through a link
L2 = A.post(B + "/api/lists", json={"name": "Imagefilm", "org_id": ORG, "kind": "project"}).json()["id"]
form_key = lambda h: (re.search(r'name="f" value="([0-9a-f]+)"', h) or [None, ""])[1]  # noqa: E731


def decide(tok, do="accept"):
    pg = requests.get(B + "/s/q/" + tok, allow_redirects=False)
    return requests.post(B + "/s/q/" + tok, data={"f": form_key(pg.text), "name": "Max Muster", "ok": "1", "do": do},
                         allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"})


def news(s, kind):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


r = A.post(B + f"/api/lists/{L2}/signoffs", json={})
check(r.ok and r.json().get("url"), f"setup: an acceptance link ({r.status_code} {r.text[:120]})")
S1 = r.json()
clear()
check(decide(S1["url"].split("/s/q/")[1]).status_code == 303, "the customer accepts")
p = until(lambda: pushes("t-alice"), 6)
check(p and p[0]["title"] == "Approved by the customer" and str(p[0].get("click") or "").startswith("http"),
      f"#2965: the active creator gets the push with an absolute link {p}")
n = news(A, "signoff")
check(n and n[0]["data"].get("state") == "accepted" and n[0]["data"].get("name") == "Max Muster", f"#2965: and a News item {n}")
S2 = A.post(B + f"/api/lists/{L2}/signoffs", json={}).json()
sql("UPDATE office_signoffs SET created_by=? WHERE id=?", (BOB, S2["id"]), write=True)  # made by bob, who left
clear()
check(decide(S2["url"].split("/s/q/")[1], "decline").status_code == 303, "the customer declines a link of the ex-member")
p = until(lambda: pushes("t-alice"), 6)
check(p and p[0]["title"] == "Declined by the customer", f"#2965: the office admin hears of it instead {p}")
check(not pushes("t-bob") and not news(Bo, "signoff"), "#2965: the ex-member gets neither a push nor a News item")

# ================================================================ #2963 security mails
check(not mail_to("bob@example.com", "New sign-in", 1), "#2963: the first sign-in only stores the browser")
s2 = requests.Session()
s2.headers.update({**kt.H, "User-Agent": "Mozilla/5.0 (Android 14; Mobile; rv:131.0) Gecko/131.0 Firefox/131.0"})
check(s2.post(B + "/api/auth/login", json={"username": "bob", "password": "password123"}).ok, "bob signs in on a phone")
m = mail_to("bob@example.com", "New sign-in")
check(m and "Firefox on Android" in m[0]["text"] and ".x" in m[0]["text"], f"#2963: a mail about the new device {m[:1]}")
check(Bo.patch(B + "/api/me", json={"password": "password456", "current_password": "password123"}).ok, "bob changes the password")
check(mail_to("bob@example.com", "Your password was changed"), "#2963: the password mail")
check(A.patch(B + f"/api/users/{CAROL}", json={"email": "carol.new@example.com"}).ok, "an admin changes carol's address")
check(mail_to("carol@example.com", "e-mail address was changed") and mail_to("carol.new@example.com", "e-mail address was changed"),
      "#2963: the old and the new address hear of it")
check(A.patch(B + f"/api/users/{DAVE}", json={"disabled": True}).ok, "an admin deactivates dave")
check(mail_to("dave@example.com", "deactivated"), "#2963: dave hears of it")
r = A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin", "password": "password123", "email": "erin@example.com"})
ERIN = r.json()["id"]
sql("UPDATE users SET signup='pending', disabled=1 WHERE id=?", (ERIN,), write=True)
check(A.post(B + f"/api/users/{ERIN}/approve").ok, "an admin approves erin's registration")
check(mail_to("erin@example.com", "approved"), "#2963: erin learns it by mail")
check(not [m for m in mails() if "Your account was deactivated" in m["subject"] and "erin@example.com" in m["to"]],
      "#2963: a waiting registration is no deactivation")

# ================================================================ #2964 admin alerts in the role "web"
if not kt.nostart("P2266"):
    kt.fresh(env={**SMTP, "KALMIDO_ROLE": "web", "KALMIDO_ADMIN_ALERTS": "1"}, keep=True)
    A = sess("alice")
    check(A.patch(B + f"/api/users/{ERIN}", json={"is_admin": True}).ok, "an admin makes erin an admin (a security alert)")
    rows = until(lambda: sql("SELECT kind, key FROM admin_alerts WHERE key LIKE ?", ("admin:erin%",)), 45)
    check(rows, "#2964: the alert of a request in the role web reaches admin_alerts (no watchdog in that process)")
sys.exit(kt.done("p2266_api"))
