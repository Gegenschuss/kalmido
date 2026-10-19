#!/usr/bin/env python3
"""2.111.0 API tests (part B, #2056): invitations by e-mail to external attendees + the subscription link of an event
calendar. Own container (start.sh, mode workspaces, an SMTP sink).
 - invitations: send_invites mails the new external addresses an .ics (METHOD:REQUEST, ORGANIZER + Reply-To = the inviting
   person, ATTENDEE with RSVP), people of this server get no mail, without the flag nothing goes out, a change of the notes
   alone mails nobody, a new time mails every external one again (higher SEQUENCE), removing one sends METHOD:CANCEL to it,
   a repeating event goes with its RRULE / EXDATE, deleting sends CANCEL only to who had an invitation, restoring invites
   them again; the daily limit answers 429 before anything is stored; only who may change the event triggers mails
 - the subscription link: none without create, the feed only with the right secret (wrong / old after rotate / off = 404),
   no attendees' addresses in it, Cache-Control no-store; a person who no longer sees the calendar (sharing ended) gets
   404 on their own link; another person reaches neither the link routes nor the calendar's feed
 - a freelancer without an organisation: own calendar, invitation mail and subscription link work the same
tenant-matrix: calendar, ical
freelancer-matrix: pim
usage: p2111_b_api_test.py <datadir>"""
import email as _em
import email.policy  # noqa: F401  (_em.policy)
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,events,contacts"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def wait_mail(to, n, secs=10):
    for _ in range(secs * 5):
        if len(mails(to)) >= n:
            return mails(to)
        time.sleep(0.2)
    return mails(to)


def parts(m):
    """(subject, plain text, ics text, reply-to) of a mail of the sink."""
    msg = _em.message_from_string(m["raw"], policy=_em.policy.default)
    text, ics = "", ""
    for x in msg.walk():
        if x.get_content_type() == "text/plain" and not x.get_filename():
            text += x.get_content()
        elif x.get_content_type() == "text/calendar":
            c = x.get_content()
            ics += c.decode("utf-8") if isinstance(c, bytes) else c
    return str(msg["Subject"]), text, re.sub(r"\r\n[ \t]", "", ics), str(msg["Reply-To"] or "")


def feed_path(url):
    return urllib.parse.urlparse(url).path


if not os.environ.get("P2111B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025"
               " -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
if not dbx("SELECT email FROM users WHERE id=?", (ALICE,))[0][0]:
    dbx("UPDATE users SET email='alice@example.com' WHERE id=?", (ALICE,))
D = (date.today() + timedelta(days=5)).isoformat()

# ================================================================== invitations
j = A.get(B + "/api/evinvite").json()
check(j["mail_ok"] is True and j["day_max"] == 200 and j["left"] == 200 and j["invited"] == [], "the editor learns: mail works, 200 a day " + str(j))
CAL = A.post(B + "/api/evcals", json={"name": "Alice Termine", "org_id": None}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Projektstart", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                    "location": "Studio 3", "description": "Bitte Unterlagen mitbringen.", "send_invites": True,
                                    "attendees": [{"email": "ext1@example.com", "name": "Ext Eins"}, {"user_id": BOB}]})
check(r.status_code == 201, "an event with an external and an internal attendee " + r.text[:200])
E1 = r.json()["id"]
m = wait_mail("ext1@example.com", 1)
check(len(m) == 1, f"the external address gets one invitation ({len(m)})")
if m:
    subj, text, ics, rt = parts(m[0])
    check(subj.startswith("Invitation: Projektstart"), "subject: Invitation " + subj)
    check("Alice Admin invites you: Projektstart" in text and "Studio 3" in text and "Bitte Unterlagen" in text, "the text names who, what, where " + text[:300])
    check("METHOD:REQUEST" in ics and "BEGIN:VEVENT" in ics and "SUMMARY:Projektstart" in ics, "the .ics is a REQUEST " + ics[:300])
    check(re.search(r"ORGANIZER;CN=Alice Admin:mailto:alice@example\.com", ics) is not None, "ORGANIZER = the inviting person's address")
    check(re.search(r"ATTENDEE;[^\n]*RSVP=TRUE[^\n]*:mailto:ext1@example\.com", ics) is not None, "ATTENDEE with RSVP")
    check("urn:kalmido:user" not in ics and "bob@example.com" not in ics and "VALARM" not in ics, "no people of the server, no alarms in the invitation")
    check("alice@example.com" in rt, "Reply-To = the inviting person " + rt)
    SEQ1 = int(re.search(r"SEQUENCE:(\d+)", ics).group(1))
time.sleep(0.6)
check(not mails("bob@example.com"), "a person of this server gets no mail (News + push instead)")
check(dbx("SELECT invited_seq IS NOT NULL FROM event_attendees WHERE event_id=? AND email='ext1@example.com'", (E1,))[0][0] in (True, 1, "t"),
      "the attendee is marked as invited")
j = A.get(B + f"/api/evinvite?event_id={E1}").json()
check([x["email"] for x in j["invited"]] == ["ext1@example.com"] and j["left"] == 199, "the editor sees who got an invitation " + str(j))

ev = A.get(B + f"/api/events/{E1}").json()
r = A.patch(B + f"/api/events/{E1}", json={"description": "Neue Notiz", "send_invites": True, "expect": ev["updated_at"]})
check(r.ok, "changing the notes " + r.text[:200])
time.sleep(1)
check(len(mails("ext1@example.com")) == 1, "a change of the notes alone mails nobody")

atts = [{"email": "ext1@example.com", "name": "Ext Eins"}, {"user_id": BOB}, {"email": "ext2@example.com"}]
r = A.patch(B + f"/api/events/{E1}", json={"attendees": atts, "send_invites": True})
check(r.ok, "a second external address " + r.text[:200])
check(len(wait_mail("ext2@example.com", 1)) == 1 and len(mails("ext1@example.com")) == 1, "only the new address gets an invitation")
check(dbx("SELECT COUNT(*) FROM event_attendees WHERE event_id=? AND invited_seq IS NOT NULL", (E1,))[0][0] == 2,
      "the mark of the first one survives replacing the attendees")

r = A.patch(B + f"/api/events/{E1}", json={"start": f"{D}T14:00", "end": f"{D}T15:00", "send_invites": True})
check(r.ok, "a new time " + r.text[:200])
m1, m2 = wait_mail("ext1@example.com", 2), wait_mail("ext2@example.com", 2)
check(len(m1) == 2 and len(m2) == 2, f"a new time mails every external attendee again ({len(m1)}, {len(m2)})")
if len(m1) == 2:
    subj, text, ics, rt = parts(m1[1])
    check(subj.startswith("Updated invitation: ") and "METHOD:REQUEST" in ics and "T140000" in ics, "the update: the new time " + subj)
    check(int(re.search(r"SEQUENCE:(\d+)", ics).group(1)) > SEQ1, "the update has a higher SEQUENCE")

r = A.patch(B + f"/api/events/{E1}", json={"attendees": atts + [{"email": "ext3@example.com"}]})
check(r.ok, "an address added without the flag " + r.text[:200])
time.sleep(1)
check(not mails("ext3@example.com"), "without send_invites nothing is mailed (the default, also for agents)")

r = A.patch(B + f"/api/events/{E1}", json={"attendees": [atts[0], atts[1], {"email": "ext3@example.com"}], "send_invites": True})
check(r.ok, "removing ext2 " + r.text[:200])
m2 = wait_mail("ext2@example.com", 3)
check(len(m2) == 3 and "METHOD:CANCEL" in parts(m2[-1])[2] and parts(m2[-1])[0].startswith("Cancelled: "), "the removed attendee gets a cancellation")
check(len(wait_mail("ext3@example.com", 1)) == 1, "the address that had none gets its invitation now")

# a repeating event: one invitation with the rule and its left-out date
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Jour fixe", "start": f"{D}T09:00", "end": f"{D}T09:30", "tz": "Europe/Berlin",
                                    "rrule": "FREQ=WEEKLY;COUNT=6", "send_invites": True, "attendees": [{"email": "serie@example.com"}]})
check(r.status_code == 201, "a weekly series " + r.text[:200])
E2 = r.json()["id"]
ms = wait_mail("serie@example.com", 1)
check(len(ms) == 1 and "RRULE:FREQ=WEEKLY;COUNT=6" in parts(ms[0])[2], "the series goes as one invitation with its rule")
occ2 = (date.fromisoformat(D) + timedelta(days=7)).isoformat() + "T09:00"
check(A.delete(B + f"/api/events/{E2}?occ={occ2}").ok, "leave out one date")
ms = wait_mail("serie@example.com", 2)
check(len(ms) == 2 and "EXDATE" in parts(ms[1])[2] and "METHOD:REQUEST" in parts(ms[1])[2], "who was invited gets the series without that date")

# rights: only who may change the event
check(Ca.patch(B + f"/api/events/{E1}", json={"title": "x", "send_invites": True}).status_code == 404, "another person: 404, no mail")
check(Ca.get(B + f"/api/evinvite?event_id={E1}").status_code == 404, "another person learns nothing about the invitations")
A.put(B + f"/api/evcals/{CAL}/members", json={"user_id": BOB, "role": "view"})
check(Bo.patch(B + f"/api/events/{E1}", json={"title": "x", "send_invites": True}).status_code == 403, "a reader of the calendar: 403")
check(Bo.get(B + f"/api/evinvite?event_id={E1}").status_code == 403, "a reader does not see the invitation marks")
check(A.post(B + "/api/events", json={"cal_id": CAL, "title": "x", "start": D, "all_day": True, "send_invites": "yes"}).status_code == 400,
      "send_invites must be true / false")

# delete -> cancellation to who had an invitation; restore -> invited again
n1, n3 = len(mails("ext1@example.com")), len(mails("ext3@example.com"))
check(A.delete(B + f"/api/events/{E1}").ok, "delete the event")
m1 = wait_mail("ext1@example.com", n1 + 1)
check(len(m1) == n1 + 1 and "METHOD:CANCEL" in parts(m1[-1])[2] and "STATUS:CANCELLED" in parts(m1[-1])[2], "deleting sends a cancellation")
check(len(wait_mail("ext3@example.com", n3 + 1)) == n3 + 1, "also to the second invited address")
check(len(mails("ext2@example.com")) == 3, "the removed one gets nothing more")
check(A.post(B + f"/api/events/{E1}/restore").ok, "restore (Undo)")
m1 = wait_mail("ext1@example.com", n1 + 2)
check(len(m1) == n1 + 2 and "METHOD:REQUEST" in parts(m1[-1])[2], "restoring invites them again")
c_seq = int(re.search(r"SEQUENCE:(\d+)", parts(m1[-2])[2]).group(1))
check(int(re.search(r"SEQUENCE:(\d+)", parts(m1[-1])[2]).group(1)) > c_seq, "the new invitation outranks the cancellation")

# the daily limit: 429 before the event is stored
dbx("UPDATE ev_invite_day SET n=199 WHERE user_id=?", (ALICE,))
before = A.get(B + f"/api/events?from={D}&to={D}").json()["items"]
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Zu viele", "start": f"{D}T16:00", "end": f"{D}T17:00", "send_invites": True,
                                    "attendees": [{"email": "l1@example.com"}, {"email": "l2@example.com"}]})
check(r.status_code == 429 and "200" in r.text, "the daily limit: 429 with a text " + r.text[:200])
check(len(A.get(B + f"/api/events?from={D}&to={D}").json()["items"]) == len(before), "nothing was stored")
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Ohne Mail", "start": f"{D}T16:00", "end": f"{D}T17:00",
                                    "attendees": [{"email": "l1@example.com"}]})
check(r.status_code == 201, "without the flag the limit does not apply " + r.text[:200])
dbx("UPDATE ev_invite_day SET n=0 WHERE user_id=?", (ALICE,))

# ================================================================== the subscription link
check(A.get(B + f"/api/evcals/{CAL}/feed").json()["url"] is None, "no link before create")
j = A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).json()
U1 = j["url"]
check(bool(U1) and re.search(r"/ical/ev/\d+\.[A-Za-z0-9_-]{30,}\.ics$", U1) is not None, "create: a secret link " + str(U1))
check(A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).json()["url"] == U1, "create again keeps the link")
pub = requests.Session()
r = pub.get(B + feed_path(U1))
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/calendar") and "no-store" in r.headers.get("Cache-Control", ""),
      f"the feed without login ({r.status_code}, {r.headers.get('Cache-Control')})")
check("SUMMARY:Projektstart" in r.text and "Jour fixe" in r.text and "RRULE:FREQ=WEEKLY;COUNT=6" in r.text and "METHOD:PUBLISH" in r.text,
      "the feed has the calendar's events with their rules")
check("mailto:" not in r.text and "ATTENDEE" not in r.text and "VALARM" not in r.text, "no attendees' addresses, no alarms in the feed")
fid, sec = feed_path(U1).rsplit("/", 1)[1][:-4].split(".", 1)
check(pub.get(B + f"/ical/ev/{fid}.{'x' * len(sec)}.ics").status_code == 404, "a wrong secret: 404")
check(pub.get(B + f"/ical/ev/{fid}.ics").status_code == 404, "no secret: 404")
check(pub.get(B + "/ical/ev/999999.abc.ics").status_code == 404, "an unknown link: 404")
U2 = A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "rotate"}).json()["url"]
check(U2 and U2 != U1 and pub.get(B + feed_path(U1)).status_code == 404 and pub.get(B + feed_path(U2)).status_code == 200,
      "rotate: the old link stops at once, the new one works")
check(A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "off"}).json()["url"] is None and pub.get(B + feed_path(U2)).status_code == 404,
      "off: the link is gone (404)")
check(A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "nope"}).status_code == 400, "an unknown action: 400")
check(Ca.get(B + f"/api/evcals/{CAL}/feed").status_code == 404 and Ca.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).status_code == 404,
      "another person reaches no link of the calendar: 404")
# a reader makes their own link; it stops when the sharing ends
UB = Bo.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).json().get("url")
check(UB and pub.get(B + feed_path(UB)).status_code == 200, "a person the calendar is shared with has their own link")
check(A.get(B + f"/api/evcals/{CAL}/feed").json()["url"] is None, "the owner's link is separate (still off)")
check(A.delete(B + f"/api/evcals/{CAL}/members/{BOB}").ok, "stop sharing with bob")
check(pub.get(B + feed_path(UB)).status_code == 404, "the link of someone who no longer sees the calendar: 404")
UA = A.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).json()["url"]
check(pub.get(B + feed_path(UA)).status_code == 200, "the owner's new link works")
# deleting the calendar: invited attendees get the cancellation, the link ends
n3 = len(mails("ext3@example.com"))
check(A.delete(B + f"/api/evcals/{CAL}").ok, "delete the calendar")
check(len(wait_mail("ext3@example.com", n3 + 1)) == n3 + 1 and "METHOD:CANCEL" in parts(mails("ext3@example.com")[-1])[2],
      "deleting the calendar cancels its invitations")
check(pub.get(B + feed_path(UA)).status_code == 404, "the link of a deleted calendar: 404")

# ================================================================== a freelancer without an organisation
FID, Fr = freelancer(B, A)
FCAL = Fr.post(B + "/api/evcals", json={"name": "Frida Kalender"}).json()["id"]
r = Fr.post(B + "/api/events", json={"cal_id": FCAL, "title": "Kundentermin", "start": f"{D}T12:00", "end": f"{D}T13:00", "send_invites": True,
                                     "attendees": [{"email": "kundin@example.com", "name": "Kundin"}]})
check(r.status_code == 201, "freelancer: an event with an external attendee " + r.text[:200])
mk = wait_mail("kundin@example.com", 1)
check(len(mk) == 1 and "METHOD:REQUEST" in parts(mk[0])[2] and "frida@example.com" in parts(mk[0])[3], "freelancer: the invitation, answers go to her")
check(Fr.get(B + "/api/evinvite").json()["mail_ok"] is True, "freelancer: the editor info")
UF = Fr.post(B + f"/api/evcals/{FCAL}/feed", json={"action": "create"}).json().get("url")
rf = pub.get(B + feed_path(UF)) if UF else None
check(rf is not None and rf.status_code == 200 and "Kundentermin" in rf.text, "freelancer: the subscription link of the own calendar")
check(Fr.get(B + f"/api/evcals/{FCAL}/feed").json()["url"] == UF, "freelancer: the link is shown again")
check(Ca.get(B + f"/api/evcals/{FCAL}/feed").status_code == 404, "nobody else reaches the freelancer's link")
check(Fr.post(B + f"/api/evcals/{FCAL}/feed", json={"action": "off"}).json()["url"] is None and pub.get(B + feed_path(UF)).status_code == 404,
      "freelancer: off")

print(f"p2111_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
