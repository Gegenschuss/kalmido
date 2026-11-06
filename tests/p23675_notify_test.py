#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.367.5 (#2975, #2980): notification mails can be left with one click, and the small gaps of the notifications. Invented names only.
freelancer-matrix: tasks
#2975
 (1) the daily mail: sender's name, one-click headers, a footer with the settings link; "sent" only after success, a failed try
     comes back after the gap, at most 3 times, the day's mail limit counts it once; used-up limit = no mail
 (2) the event mail: sender's name and one-click headers; a plain mail has none
 (3) the off link: GET changes nothing, POST (mail client's button, nobody signed in) turns the mails off; a wrong link is a 404,
     also for a person without an organisation
 (4) the portal's off link takes the mail client's one-click POST, a plain POST without the form key stays refused
#2980
 (5) "completed by others" reaches the bell by default
 (6) the app badge in a push is the number of the app: News for me + direct messages
 (7) a push carries the person's language; test titles are translated, test pushes have a limit
 (8) a language the app does not have falls back to English (bookings)
 (9) a rule's comment with an @mention tells the person
 (10) an edited chat message tells who was newly @mentioned, nobody twice
 (11) a project handed over by an organisation admin tells the old owner; a task freed from its blocker tells a group's people / the creator of an agent's task
 (12) only the title in the push: the text stays out of the push, the channels keep it
 (13) a push service's 413: once more with a short text; the dismiss tick counts refusals
 (14) mails name the organisation shared with the sender, none when unclear
 (15) News of an organisation / a list / a connection stay out of an ex-member's feed; being removed stays readable
 (16) a nag cap counts over restarts (the database)
 (17) 2.540.0 (#4383): News of an organisation are judged by its number where they carry one (names repeat), the name as fallback
usage: p23675_notify_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer, org_join
from kt import FAILS, OKS, check, sess, me_id

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
        c.commit()
        return rows
    finally:
        c.close()


HEAD = """import json, time
import app
from kalmido.core.config import app as flask_app
from kalmido.core.db import connect, usettings, uset
from kalmido.core.pg import system_ctx
import kalmido.integrations.mail as M
c = connect()
M.MAIL_OUT_ON = True
M.SMTP.update(host="mail.example.com", **{"from": "notes@example.com"})
SENT = []
FAIL = [False]
def deliver(m, smtp=None):
    if FAIL[0]:
        raise OSError("no")
    SENT.append({k: str(m[k]) for k in ("From", "To", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post") if m[k]} | {"text": m.get_body(("plain",)).get_content()})
M.mail_deliver = deliver
"""


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", HEAD + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def wait_push(pred, sec=8):
    end = time.time() + sec
    while time.time() < end:
        hit = [x for x in pushes() if pred(x)]
        if hit:
            return hit[0]
        time.sleep(0.1)
    return None


def news(s, kind=None):
    its = s.get(B + "/api/news").json()["items"]
    return [x for x in its if kind is None or x["kind"] == kind]


def task(s, title, lid=None, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, **({"list_id": lid} if lid else {}), **kw})
    assert r.status_code < 300, r.text
    return r.json()["id"]


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + f"/api/users/{me_id(A)}", json={"ntfy_topic": "t-alice", "email": "alice@example.com"})
ids = {"alice": 1}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u, "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for x in (A, Bo, Ca, Da):
    x.patch(B + "/api/settings", json={"lang": "en"})
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for uid in (BOB, CAROL, DAVE):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid, "role": "edit"}).ok
FR, Fr = freelancer(B, A)
FT = task(Fr, "Invoice run", due="2020-01-01")
clear()

# ---- (1) the daily mail
Fr.patch(B + "/api/settings", json={"digest_mail": "1"})
out = in_app(f"""
out = {{}}
today = "2026-10-31"
def run():
    with system_ctx(c):
        return M.digest_mail_user(c, {FR}, usettings(c, {FR}), today)
FAIL[0] = True
out["fail"] = run()
with system_ctx(c):
    out["sent0"] = usettings(c, {FR})["digest_mail_sent"]
    out["try0"] = usettings(c, {FR})["digest_mail_try"]
FAIL[0] = False
out["soon"] = run()
out["n_soon"] = len(SENT)
with system_ctx(c):
    uset(c, {FR}, "digest_mail_try", today + ":1:1")
    c.commit()
out["again"] = run()
out["mail"] = SENT[0] if SENT else None
with system_ctx(c):
    out["sent1"] = usettings(c, {FR})["digest_mail_sent"]
    out["budget"] = [r[0] for r in c.execute("SELECT n FROM mail_counts WHERE k LIKE 'r:%'")]
out["twice"] = run()
out["n"] = len(SENT)
with system_ctx(c):
    uset(c, {FR}, "digest_mail_sent", "")
    uset(c, {FR}, "digest_mail_try", today + ":3:1")
    c.commit()
out["third"] = run()
with system_ctx(c):
    uset(c, {FR}, "digest_mail_try", "")
    c.execute("UPDATE mail_counts SET n=99 WHERE k LIKE 'r:%'")
    c.commit()
out["limit"] = run()
out["n2"] = len(SENT)
with system_ctx(c):
    out["sent2"] = usettings(c, {FR})["digest_mail_sent"]
    c.execute("DELETE FROM mail_counts")
    c.commit()
""")
check(out["fail"] is False and out["sent0"] == "" and out["try0"].startswith("2026-10-31:1:"), f"(1) a failed mail is not marked as sent: {out}")
check(out["soon"] is False and out["n_soon"] == 0, "(1) not again within the gap")
m = out["mail"]
check(out["again"] is True and m and "<notes@example.com>" in m["From"] and m["From"] != "notes@example.com", f"(1) after the gap it goes out, with the sender's name: {m}")
check(m and "/mail/off/" in m.get("List-Unsubscribe", "") and m.get("List-Unsubscribe-Post") == "List-Unsubscribe=One-Click", f"(1) one-click headers: {m}")
check(m and "#settings/notify" in m["text"], "(1) the footer links the settings")
check(out["sent1"] == "2026-10-31" and out["budget"] == [1], f"(1) marked sent after success, counted once: {out}")
check(out["twice"] is False and out["n"] == 1, "(1) one mail a day")
check(out["third"] is False, "(1) three failed tries: over for the day")
check(out["limit"] is False and out["n2"] == 1 and out["sent2"] == "2026-10-31", f"(1) the day's limit used up: no mail, not tried again: {out}")

# ---- (2) the event mail
T = task(A, "Poster", L, assignee_id=DAVE)
Da.patch(B + "/api/settings", json={"mail_assign": "always"})
out = in_app(f"""
from datetime import datetime, timezone
from kalmido.notify.channels import evm_user
with system_ctx(c):
    c.execute("INSERT INTO notify_mail_queue(user_id,kind,task_id,actor_id,created_at) VALUES(?,?,?,?,?)", ({DAVE}, "assign", {T}, 1, 1))
    c.commit()
    evm_user(c, {DAVE}, usettings(c, {DAVE}), "en", datetime.now(timezone.utc))
M.mail_send("x@example.com", "plain", "text")
out = SENT
""")
check(len(out) == 2 and "<notes@example.com>" in out[0]["From"] and out[0]["From"] != "notes@example.com", f"(2) sender's name: {out}")
check("/mail/off/" in out[0].get("List-Unsubscribe", "") and out[0].get("List-Unsubscribe-Post"), f"(2) one-click headers: {out[0]}")
check("List-Unsubscribe" not in out[1], "(2) a mail without the link has no such header (security mails, invoices)")

# ---- (3) the off link
url = m["List-Unsubscribe"].strip("<>")
tok = url.rsplit("/", 1)[1]
path = B + "/mail/off/" + tok
N = requests.Session()
r = N.get(path)
check(r.status_code == 200 and "<form" in r.text, f"(3) GET shows one button: {r.status_code}")
check(Fr.get(B + "/api/state").json()["settings"]["digest_mail"] == "1", "(3) GET changes nothing (mail scanners)")
r = N.post(path, data={"List-Unsubscribe": "One-Click"})
check(r.status_code == 200, f"(3) one-click POST without a session: {r.status_code}")
check(Fr.get(B + "/api/state").json()["settings"]["digest_mail"] == "0", "(3) a person without an organisation: the daily mail is off")
bad = tok[:-1] + ("0" if tok[-1] != "0" else "1")
check(N.post(B + "/mail/off/" + bad).status_code == 404, "(3) a wrong signature: 404")
other = tok.replace(f"{FR}.", f"{BOB}.", 1)
check(N.post(B + "/mail/off/" + other).status_code == 404, "(3) the link of one person does not fit another")
check(N.get(B + "/mail/off/" + tok[:-1] + "ü").status_code == 404, "(3) odd characters: 404, no error")
check(N.get(B + "/mail/off/².digest.x").status_code == 404, "(3) a digit int() does not take: 404, no error")
ev = out[0]["List-Unsubscribe"].strip("<>").rsplit("/", 1)[1]
check(N.post(B + "/mail/off/" + ev).status_code == 200, "(3) the event mail's link")
st = Da.get(B + "/api/state").json()["settings"]
check(st["mail_assign"] == "off" and st["mail_mention"] == "off", f"(3) the event mails are off: {st['mail_assign']}")

# ---- (4) the portal's off link
T4 = task(A, "A report", L)
out = in_app(f"""
from kalmido.team.portal import pt_create
with system_ctx(c):
    l = c.execute("SELECT id, org_id, owner_id FROM lists WHERE id=?", ({L},)).fetchone()
    pid, out = pt_create(c, {T4}, l, None, "Someone", "reporter@example.com")
    c.commit()
""")
notify = lambda: dbw("SELECT notify FROM portal_tickets WHERE task_id=?", (T4,))[0][0]
check(notify() == 1, "(4) setup: the report gets mails")
check(N.post(B + f"/p/{out}/stop", data={}).status_code in (403, 400) and notify() == 1, "(4) a POST without the form key stays refused")
r = N.post(B + f"/p/{out}/stop", data={"List-Unsubscribe": "One-Click"})
check(r.status_code == 200 and notify() == 0, f"(4) the mail client's one-click POST: {r.status_code}")

# ---- (5) done by others, in the bell by default
T5 = task(Ca, "Banner", L, assignee_id=BOB)
Ca.patch(B + "/api/settings", json={"lang": "en"})
Bo.post(B + f"/api/tasks/{T5}/complete", json={})
check(any(x["task_id"] == T5 for x in news(Ca, "complete")), f"(5) the News item is there: {[x['kind'] for x in news(Ca)]}")

# ---- (6) the badge
r = A.post(B + "/api/team/dm", json={"user_id": BOB})
rid = r.json().get("id") or r.json()["room"]["id"]
assert A.post(B + f"/api/team/rooms/{rid}/messages", json={"body": "Hello"}).ok
T6 = task(A, "Seen by Bob", L)
Ca.post(B + f"/api/tasks/{T6}/comments", json={"body": "A plain comment"})
st = Bo.get(B + "/api/state").json()
out = in_app(f"""
from kalmido.notify.push import badge_count
out = badge_count({BOB})
""")
check(out == st["news"]["unread_me"] + st["team"]["dm_unread"], f"(6) the push's badge = the app's number: {out} vs {st['news']['unread_me']} + {st['team']['dm_unread']}")

# ---- (7) language, test titles
out = in_app(f"""
import kalmido.notify.push as P
seen = []
P.WEBPUSH_ON = True
P.webpush_user = lambda uid, payload, *a, **k: seen.append(payload) or 1
with system_ctx(c):
    uset(c, {DAVE}, "lang", "de")
    uset(c, {DAVE}, "push_channel", "webpush")
    c.commit()
P.notify({DAVE}, "Title", "Text")
out = seen[0]["lang"]
with system_ctx(c):
    uset(c, {DAVE}, "lang", "en")
    uset(c, {DAVE}, "push_channel", "ntfy")
    c.commit()
""")
check(out == "de", f"(7) the push carries the language: {out}")
Da.patch(B + "/api/settings", json={"lang": "de"})
clear()
check(Da.post(B + "/api/ntfy/test").json().get("ok"), "(7) ntfy test")
p = wait_push(lambda x: x["topic"] == "t-dave")
check(p and "Benachrichtigungen" in p["msg"], f"(7) the text in the person's language: {p}")
Da.patch(B + "/api/settings", json={"lang": "en"})
clear()
Da.post(B + "/api/ntfy/test")
p = wait_push(lambda x: x["topic"] == "t-dave")
check(p and p.get("title") == "Kalmido: test", f"(7) the title through the translation: {p}")
codes = [Da.post(B + "/api/ntfy/test").status_code for _ in range(38)]
check(set(codes) == {200}, f"(7) tests go through up to the limit: {codes}")
check(Da.post(B + "/api/push/test", json={}).status_code == 429, "(7) then 429, push and ntfy test share it")

# ---- (8) a language the app does not have
out = in_app("""
from kalmido.calendars.apptbook import lang_of
out = lang_of({"lang": "xx"})
""")
check(out == "en", f"(8) falls back: {out}")

# ---- (9) a rule's comment with a mention
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "Tell Carol", "trigger": {"kind": "created"}, "action": {"kind": "comment", "text": f"Please look <@{CAROL}>"}})
check(r.ok, f"(9) rule: {r.status_code} {r.text[:200]}")
clear()
T9 = task(Bo, "New flyer", L)
check(wait_push(lambda x: x["topic"] == "t-carol"), f"(9) a push for the person mentioned: {pushes()}")
check(any(x["task_id"] == T9 for x in news(Ca, "mention")), "(9) and the mention in the News")
c9 = dbw("SELECT mentions FROM comments WHERE task_id=?", (T9,))
check(c9 and str(CAROL) in str(c9[0][0]), f"(9) stored with the comment: {c9}")
A.delete(B + f"/api/rules/{r.json().get('id')}") if r.ok else None

# ---- (10) an edited chat message
rooms = Bo.get(B + "/api/team").json()["rooms"]
rl = next(x["id"] for x in rooms if x.get("list_id") == L)
mid = Bo.post(B + f"/api/team/rooms/{rl}/messages", json={"body": "Hello all"}).json()["id"]
time.sleep(0.3)
clear()
r = Bo.patch(B + f"/api/team/messages/{mid}", json={"body": f"Hello <@{CAROL}>"})
check(r.ok, f"(10) edit: {r.status_code}")
check(wait_push(lambda x: x["topic"] == "t-carol"), f"(10) the newly mentioned hears it: {pushes()}")
time.sleep(0.5)
n = len([x for x in pushes() if x["topic"] == "t-carol"])
check(not [x for x in pushes() if x["topic"] in ("t-alice", "t-dave")], "(10) the others do not")
Bo.patch(B + f"/api/team/messages/{mid}", json={"body": f"Hello again <@{CAROL}>"})
time.sleep(1)
check(len([x for x in pushes() if x["topic"] == "t-carol"]) == n, "(10) a second edit tells nobody again")

# ---- (11) a project handed on, a task freed
OR = A.post(B + "/api/orgs", json={"name": "Nordwind"}).json()["id"]
OR2 = A.post(B + "/api/orgs", json={"name": "Seewind"}).json()["id"]
for oid in (OR, OR2):
    for u in ("bob", "carol"):
        check(A.put(B + f"/api/orgs/{oid}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, oid, "password123"), f"(11) {u} joins {oid}")
OL = Bo.post(B + "/api/lists", json={"name": "Campaign", "org_id": OR}).json()["id"]
assert Bo.put(B + f"/api/lists/{OL}/members", json={"user_id": CAROL, "role": "edit"}).ok
r = A.post(B + f"/api/orgs/{OR}/lists/{OL}/owner", json={"user_id": CAROL})
check(r.ok, f"(11) the admin hands it on: {r.status_code} {r.text[:200]}")
it = [x for x in news(Bo, "owner") if x.get("data", {}).get("given") == "Carol"]
check(it, f"(11) the old owner is told: {news(Bo, 'owner')}")
check(any(x.get("data", {}).get("given") is None for x in news(Ca, "owner")), "(11) the new owner as before")
gid = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [BOB, DAVE]}).json()
gid = gid.get("id") or gid["group"]["id"]
out = in_app(f"""
from kalmido.tasks.dependencies import dep_people
with system_ctx(c):
    out = [dep_people(c, {{"assignee_group_id": {gid}, "assignee_id": None, "created_by": 1}}),
           dep_people(c, {{"assignee_group_id": None, "assignee_id": {CAROL}, "created_by": 1}}),
           dep_people(c, {{"assignee_group_id": None, "assignee_id": None, "created_by": 1}})]
""")
check(sorted(out[0]) == sorted([BOB, DAVE]) and out[1] == [CAROL] and out[2] == [1], f"(11) a group's people, the assignee, the creator: {out}")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
out = in_app(f"""
from kalmido.tasks.dependencies import dep_people
with system_ctx(c):
    out = dep_people(c, {{"assignee_group_id": None, "assignee_id": {ag['id']}, "created_by": {BOB}}})
""")
check(out == [BOB], f"(11) an agent's task: its creator: {out}")

# ---- (12) only the title
clear()
Ca.patch(B + "/api/settings", json={"push_title_only": "1"})
check(Ca.get(B + "/api/state").json()["settings"]["push_title_only"] == "1", "(12) the setting is stored")
T12 = task(A, "Budget talk", L, assignee_id=CAROL)
time.sleep(0.5)
clear()
Bo.post(B + f"/api/tasks/{T12}/comments", json={"body": f"<@{CAROL}> pays 48.500 EUR"})
p = wait_push(lambda x: x["topic"] == "t-carol")
check(p and "48.500" not in p["msg"] and "48.500" not in (p.get("title") or ""), f"(12) no text in the push: {p}")
out = in_app(f"""
import kalmido.notify.push as P
import kalmido.notify.channels as CH
seen, chn = [], []
P.WEBPUSH_ON = True
P.webpush_user = lambda uid, payload, *a, **k: seen.append(payload) or 1
CH.chn_push = lambda uid, title, msg, *a, **k: chn.append(msg) or False
with system_ctx(c):
    uset(c, {CAROL}, "push_channel", "webpush")
    c.commit()
P.notify({CAROL}, "Title", "Secret text")
out = [seen[0]["body"], seen[0]["title"], chn]
with system_ctx(c):
    uset(c, {CAROL}, "push_channel", "ntfy")
    c.commit()
""")
check(out[0] == "" and out[1] == "Title" and out[2] == ["Secret text"], f"(12) web push title only, channels keep the text: {out}")
Ca.patch(B + "/api/settings", json={"push_title_only": "0"})

# ---- (13) 413 and refusals
out = in_app(f"""
import kalmido.notify.push as P
calls = []
def send(sub, payload, prio="4", ttl=86400, topic=None):
    calls.append(len(payload.get("body") or ""))
    return (413, None) if len(calls) == 1 else (201, None)
P.webpush_send = send
with system_ctx(c):
    c.execute("INSERT INTO push_subs(user_id,endpoint,p256dh,auth,label,created_at) VALUES(?,?,?,?,?,?)", ({DAVE}, "https://push.example.com/a", "k", "a", "x", "2026-01-01T00:00:00+00:00"))
    c.commit()
n = P.webpush_user({DAVE}, P.webpush_payload("T", "x" * 900, "4"))
sid = None
with system_ctx(c):
    sid = c.execute("SELECT id FROM push_subs WHERE user_id=?", ({DAVE},)).fetchone()[0]
    c.execute("INSERT INTO push_tags(sub_id,tag,handled_at,sent_at) VALUES(?,?,?,?)", (sid, "t-1", time.time(), time.time()))  # just handled: the server's own tick waits
    c.commit()
P.webpush_send = lambda sub, payload, prio="4", ttl=86400, topic=None: (403, None)
P.DISMISS_WAIT, P.WEBPUSH_ON = 0, True
with system_ctx(c):
    P.push_dismiss_tick(c)
    f = c.execute("SELECT fails FROM push_subs WHERE id=?", (sid,)).fetchone()
    c.execute("DELETE FROM push_subs WHERE id=?", (sid,))
    c.commit()
out = [n, calls, f[0] if f else None]
""")
check(out[0] == 1 and out[1] == [900, 200], f"(13) the second try is short and arrives: {out}")
check(out[2] == 1, f"(13) the dismiss tick counts the refusal: {out}")

# ---- (14) the organisation of a mail
out = in_app(f"""
from kalmido.accounts.invite import invite_org
with system_ctx(c):
    out = [invite_org(c, {{"id": {BOB}}}, "reset", None), invite_org(c, {{"id": {BOB}}}, "reset", {DAVE}), invite_org(c, {{"id": {BOB}}}, "reset", 1)]
""")
check(out[0] == "" and out[1] == "" and out[2] == "", f"(14) two organisations and no clear sender: no name: {out}")
Da.post(B + "/api/orgs", json={"name": "Dave Works"})
out = in_app(f"""
from kalmido.accounts.invite import invite_org
with system_ctx(c):
    out = invite_org(c, {{"id": {DAVE}}}, "reset", None)
""")
check(out == "Dave Works", f"(14) one organisation: its name: {out}")

# ---- (15) an ex-member's News
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "share", json.dumps({"org": True, "name": "Seewind", "role": "member"}), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "unshare", json.dumps({"org": True, "name": "Seewind"}), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "orglist", json.dumps({"action": "delete", "name": "Secret plan", "org": "Seewind"}), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "orglist", json.dumps({"action": "ldelete", "name": "My own"}), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,actor_id,kind,data,created_at) VALUES(?,?,?,?,?)", (CAROL, FR, "connok", json.dumps({"name": "Frida"}), "2026-10-31T10:00:00.000+00:00"))
names = [(x["kind"], x.get("data", {}).get("name")) for x in news(Ca)]
check(("share", "Seewind") in names and ("orglist", "Secret plan") in names, f"(15) a member sees them: {names}")
check(("connok", "Frida") not in names, "(15) no connection (any more): the item is gone")
r = A.delete(B + f"/api/orgs/{OR2}/members/{CAROL}")
check(r.ok, f"(15) carol leaves: {r.status_code} {r.text[:200]}")
Ca2 = sess("carol")
names = [(x["kind"], x.get("data", {}).get("name")) for x in news(Ca2)]
check(("share", "Seewind") not in names, f"(15) the ex-member no longer sees the organisation: {names}")
check(("orglist", "Secret plan") not in names, "(15) nor a list's name of it")
check(("unshare", "Seewind") in names, "(15) being removed stays readable")
check(("orglist", "My own") in names, "(15) an item of my own list stays")

dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "orglist", json.dumps({"action": "archive", "name": "Campaign", "org": "Old Nordwind"}), "2026-10-31T10:00:00.000+00:00"))
names = [(x["kind"], x.get("data", {}).get("name")) for x in news(Ca2)]
check(("orglist", "Campaign") in names, "(15) a name no organisation has any more (renamed): the item stays for the members")

# ---- (17) 2.540.0 (#4383): an item that carries org_id is judged by the number (names can repeat, #4077), the name is the fallback
un = dbw("SELECT data FROM notifications WHERE user_id=? AND kind='unshare' ORDER BY id DESC LIMIT 1", (CAROL,))
check(un and json.loads(un[0][0]).get("org_id") == OR2, f"(17) the News of being removed carries the organisation's number: {un}")
DUP = Da.post(B + "/api/orgs", json={"name": "Nordwind"}).json().get("id")
check(DUP and DUP != OR, f"(17) another person's company with the same name as carol's organisation: {DUP}")
for nm, d in (("Dup share", {"org": True, "name": "Nordwind", "org_id": DUP, "role": "member", "x": "Dup share"}),
              ("Own share", {"org": True, "name": "Nordwind", "org_id": OR, "role": "member", "x": "Own share"}),
              ("Renamed share", {"org": True, "name": "Nordwind alt", "org_id": OR, "role": "member", "x": "Renamed share"}),
              ("Gone share", {"org": True, "name": "Nordwind", "org_id": 987654, "role": "member", "x": "Gone share"}),
              ("Old share", {"org": True, "name": "Nordwind", "role": "member", "x": "Old share"})):
    dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "share", json.dumps(d), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "orglist", json.dumps({"action": "delete", "name": "Dup plan", "org": "Nordwind", "org_id": DUP}), "2026-10-31T10:00:00.000+00:00"))
dbw("INSERT INTO notifications(user_id,kind,data,created_at) VALUES(?,?,?,?)", (CAROL, "orglist", json.dumps({"action": "delete", "name": "Own plan", "org": "Nordwind", "org_id": OR}), "2026-10-31T10:00:00.000+00:00"))
its = news(sess("carol"))
xs = {x.get("data", {}).get("x") for x in its if x["kind"] == "share"}
ls = {x.get("data", {}).get("name") for x in its if x["kind"] == "orglist"}
check("Dup share" not in xs and "Dup plan" not in ls, f"(17) an item of the other company with the same name stays out of carol's News: {sorted(filter(None, xs))} {sorted(filter(None, ls))}")
check({"Own share", "Renamed share", "Gone share", "Old share"} <= xs and "Own plan" in ls,
      f"(17) her own organisation by number (also renamed), a number no organisation has, an old item by name: {sorted(filter(None, xs))}")

# ---- (16) the nag cap
out = in_app(f"""
from kalmido.api.common import hit_limit
from kalmido.core.ratedb import rate_hit
from kalmido.tasks.validation import NAG_HOUR_CAP
out = [hit_limit("nag:{DAVE}", NAG_HOUR_CAP, 3600) for _ in range(NAG_HOUR_CAP)]
""")
out2 = in_app(f"""
from kalmido.api.common import hit_limit
from kalmido.tasks.validation import NAG_HOUR_CAP
out = hit_limit("nag:{DAVE}", NAG_HOUR_CAP, 3600)
""")
check(not any(out) and out2 is True, f"(16) the cap holds in a new process: {out} {out2}")

print(f"p23675_notify: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
