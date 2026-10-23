#!/usr/bin/env python3
"""2.94.0 API tests (part B): appointment booking by customers (#1929), own container (start.sh, mode workspaces, an SMTP sink).
 - the person's settings: the page (address rules, taken address 409, a foreign calendar / office area refused, weekly hours
   validated), appointment types (validation, edit, delete + restore), switching on picks a calendar; kid accounts 403, an
   agent token never reaches the routes, the calendar module off = 409; another person reaches nothing (404)
 - free times: the weekly hours minus a busy event (+- the buffer of the type), an event marked free does not block, the
   public page never shows a title of the calendar
 - the public flow without login: page -> type -> time -> form (check value, Sec-Fetch-Site, honeypot, address check) ->
   pending booking (holds the time: a second booking of it is refused) -> mail with the confirmation link -> GET shows a
   button only, POST confirms -> event (customer as attendee) + contact (taken again for the same address) + lead (part A,
   tolerant until it is merged) + mail with the cancel link; the customer cancels (event deleted, time free again); the
   person cancels (mail with the reason)
 - spam protection: at most 3 open bookings per address, unconfirmed bookings expire after 30 minutes, the same 404 for
   unknown and switched-off pages and tokens, the rate limit per client address
 - a freelancer without an organisation: own calendar, own contacts, the lead in the personal office
tenant-matrix: calendar
freelancer-matrix: pim
usage: p294_b_api_test.py <datadir>"""
import email as _em
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402  (2.149.0, #2512: the group's test time, run_all.sh `now`)

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
BER = ZoneInfo("Europe/Berlin")
FEAT = "cal,comments,collab,office,clients,events,contacts"
AP = "/api/appt"


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


def body_of(m):
    msg = _em.message_from_string(m["raw"])
    return "".join(x.get_payload(decode=True).decode() for x in msg.walk() if x.get_content_type() == "text/plain"), str(msg["Subject"])


def wait_mail(to, n, secs=10):
    for _ in range(secs * 5):
        if len(mails(to)) >= n:
            return mails(to)
        time.sleep(0.2)
    return mails(to)


def link_in(m, kind):
    t = body_of(m)[0]
    x = re.search(r"/s/b/" + kind + r"/([A-Za-z0-9_-]{20,64})", t)
    return x.group(1) if x else None


def fkey(text):
    m = re.search(r'name="f" value="([0-9a-f]+)"', text)
    return m.group(1) if m else ""


def slots(text, slug, tid):
    return set(re.findall(rf'href="/s/b/{re.escape(slug)}/{tid}/(\d{{8}}T\d{{4}})"', text))


pub = requests.Session()  # the customer: no login


def book(slug, tid, key, name, mail, extra=None, headers=None):
    g = pub.get(f"{B}/s/b/{slug}/{tid}/{key}")
    data = {"f": fkey(g.text), "name": name, "email": mail, "phone": "+49 30 1234567", "message": "Bitte kurz anrufen.", **(extra or {})}
    return pub.post(f"{B}/s/b/{slug}/{tid}/{key}", data=data, headers=headers or {}, allow_redirects=False)


# 2.149.0 (#2513): the minute of the rate limits shortened to RATE_S (test containers only, KALMIDO_TEST_RATE_WINDOW_S)
RATE_S = 60 if os.environ.get("P294B_NOSTART") else 20
if not os.environ.get("P294B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025"
               " -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test" + f" -e KALMIDO_TEST_RATE_WINDOW_S={RATE_S}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
KID = A.post(B + "/api/users", json={"username": "tim", "display_name": "Tim", "password": "password123", "kid": True, "parents": [ALICE]}).json().get("id")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "calendar"], "username": "claude", "display_name": "Claude"})
AGTOK = r.json().get("token") if r.ok else None
ALL = {d: [["08:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

# ================================================================== the settings
j = A.get(B + AP + "/page").json()
check(j["exists"] is False and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", j["page"]["slug"]) and j["mail_ok"] is True and j["links_ok"] is True,
      "the empty page with a suggested address " + str(j)[:300])
check(any(o["id"] == ORG for o in j["offices"]) and any(o["personal"] for o in j["offices"]) and not any(o["id"] == ORG2 for o in j["offices"]),
      "office areas for leads: the personal office + the organisation where alice is admin " + str(j["offices"]))
check(A.put(B + AP + "/page", json={"slug": "A!"}).status_code == 400, "an invalid address: 400")
check(A.put(B + AP + "/page", json={"slug": "ab"}).status_code == 400, "a too short address: 400")
r = A.put(B + AP + "/page", json={"slug": "alice-termine", "title": "Termine bei Alice", "intro": "Ein kurzes Gespräch.", "hours": ALL, "tz": "Europe/Berlin",
                                  "office_org_id": ORG})
check(r.ok and r.json()["exists"] and r.json()["page"]["url"].endswith("/s/b/alice-termine") and r.json()["page"]["office_org_id"] == ORG
      and r.json()["page"]["enabled"] is False, "the page is saved (off) " + r.text[:300])
check(Ca.put(B + AP + "/page", json={"slug": "alice-termine"}).status_code == 409, "a taken address: 409")
check(A.put(B + AP + "/page", json={"office_org_id": ORG2}).status_code == 404, "an organisation alice is not in: 404")
check(Bo.put(B + AP + "/page", json={"office_org_id": ORG}).status_code == 404, "a member who is no office admin: 404")
CCAL = Ca.post(B + "/api/evcals", json={"name": "Carols"}).json()["id"]
check(A.put(B + AP + "/page", json={"cal_id": CCAL}).status_code == 404, "another person's calendar: 404")
check(A.put(B + AP + "/page", json={"hours": {"mon": [["10:00", "09:00"]]}}).status_code == 400, "hours: end before start 400")
check(A.put(B + AP + "/page", json={"hours": {"mon": [["09:00", "12:00"], ["11:00", "13:00"]]}}).status_code == 400, "hours: overlapping 400")
check(A.put(B + AP + "/page", json={"hours": {"xyz": []}}).status_code == 400, "hours: an unknown day 400")
check(A.put(B + AP + "/page", json={"tz": "Mars/Base"}).status_code == 400, "an unknown time zone 400")
if KID:
    check(sess("tim").get(B + AP + "/page").status_code == 403, "a kid account: 403")
if AGTOK:
    r = requests.get(B + AP + "/page", headers={**H, "Authorization": f"Bearer {AGTOK}"})
    check(r.status_code in (401, 403), f"an agent token never reaches the settings ({r.status_code})")
    r = requests.get(B + "/api/v1/appt/page", headers={"Authorization": f"Bearer {AGTOK}"})
    check(r.status_code in (403, 404), f"no booking routes in the REST API ({r.status_code})")
Bo.patch(B + "/api/settings", json={"features": "cal,comments,collab"})
check(Bo.get(B + AP + "/page").status_code == 409, "the calendar module off: 409")
Bo.patch(B + "/api/settings", json={"features": FEAT})

# appointment types
r = A.post(B + AP + "/types", json={"name": "Erstgespräch", "duration_min": 30, "buffer_min": 15, "notice_h": 0, "days_ahead": 30, "location": "Videoanruf"})
check(r.status_code == 201 and r.json()["duration_min"] == 30 and r.json()["active"] is True, "a new appointment type " + r.text[:200])
T1 = r.json()["id"]
check(A.post(B + AP + "/types", json={"name": "x", "duration_min": 2}).status_code == 400, "a too short duration: 400")
check(A.post(B + AP + "/types", json={"name": " "}).status_code == 400, "a name is required")
T2 = A.post(B + AP + "/types", json={"name": "Workshop", "duration_min": 120}).json()["id"]
check(A.patch(B + f"{AP}/types/{T2}", json={"location": "Studio", "active": False}).json()["active"] is False, "edit + inactive")
check(A.delete(B + f"{AP}/types/{T2}").ok and T2 not in [t["id"] for t in A.get(B + AP + "/types").json()["types"]], "delete")
check(A.post(B + f"{AP}/types/{T2}/restore").ok and T2 in [t["id"] for t in A.get(B + AP + "/types").json()["types"]], "restore (Undo)")
check(Ca.patch(B + f"{AP}/types/{T1}", json={"name": "x"}).status_code == 404 and Ca.delete(B + f"{AP}/types/{T1}").status_code == 404
      and Ca.post(B + f"{AP}/types/{T2}/restore").status_code == 404, "another person reaches no type: 404")
check(Ca.get(B + AP + "/types").json()["types"] == [], "another person lists none")

# switching on
check(pub.get(B + "/s/b/alice-termine").status_code == 404, "off: the public page is 404")
r = A.put(B + AP + "/page", json={"enabled": True})
check(r.ok and r.json()["page"]["enabled"] is True and r.json()["page"]["cal_id"], "switched on: a calendar is chosen " + r.text[:200])
ACAL = r.json()["page"]["cal_id"]

# ================================================================== free times
D = testclock.now().date() + timedelta(days=3)  # 2.149.0 (#2512)
MON = D - timedelta(days=D.weekday())
K = D.strftime("%Y%m%d")
A.post(B + "/api/events", json={"title": "Geheimes Treffen", "cal_id": ACAL, "start": f"{D}T11:00", "end": f"{D}T12:00", "tz": "Europe/Berlin"})
A.post(B + "/api/events", json={"title": "Frei markiert", "cal_id": ACAL, "start": f"{D}T14:00", "end": f"{D}T15:00", "tz": "Europe/Berlin", "busy": False})
r = pub.get(f"{B}/s/b/alice-termine")
check(r.status_code == 200 and "Erstgespräch" in r.text and "Termine bei Alice" in r.text and "Workshop" not in r.text and "<script" not in r.text,
      "the public page lists the active types, no scripts")
check("noindex" in r.text, "not indexed")
r = pub.get(f"{B}/s/b/alice-termine/{T1}?w={MON}")
S1 = slots(r.text, "alice-termine", T1)
check(r.status_code == 200 and f"{K}T1000" in S1 and f"{K}T1030" not in S1 and f"{K}T1100" not in S1 and f"{K}T1200" not in S1 and f"{K}T1230" in S1,
      "free times: the busy event +- 15 min buffer blocks " + str(sorted(x for x in S1 if x.startswith(K))))
check(f"{K}T1400" in S1, "an event marked free does not block")
check(f"{K}T0800" in S1 and f"{K}T1730" in S1 and f"{K}T1800" not in S1 and f"{K}T0730" not in S1, "the weekly hours bound the times")
check("Geheim" not in r.text and "Frei markiert" not in r.text, "no title of the calendar leaves the server")
check("Europe/Berlin" in r.text, "the time zone is named")
check(pub.get(f"{B}/s/b/alice-termine/{T2}").status_code == 404, "an inactive type: 404")
A.patch(B + f"{AP}/types/{T2}", json={"active": True})
check(pub.get(f"{B}/s/b/alice-termine/{T2}").status_code == 200, "active again: its times")
check(pub.get(f"{B}/s/b/no-such-page").status_code == 404 and pub.get(f"{B}/s/b/no-such-page").text == pub.get(f"{B}/s/b/alice-termine-x").text,
      "unknown pages: the same 404")
CT1 = Ca.post(B + AP + "/types", json={"name": "Carol Typ"}).json()["id"]
check(pub.get(f"{B}/s/b/alice-termine/{CT1}").status_code == 404, "another person's type on alice's page: 404")
check(pub.get(f"{B}/s/b/alice-termine/{T1}/{K}T1100").status_code == 409, "a busy time: 'no longer free'")
check(pub.get(f"{B}/s/b/alice-termine/{T1}/{K}T1005").status_code == 409, "a time off the grid is not free")

# ================================================================== booking
M1 = "kunde.eins@example.com"
PRE = pub.get(f"{B}/s/b/alice-termine/{T1}/{K}T1000")  # a second customer has the same form open
r = book("alice-termine", T1, f"{K}T1000", "Kunde Eins", M1)
check(r.status_code == 200 and "check your e-mail" in r.text, "booked: check your e-mail " + str(r.status_code))
bk = dbx("SELECT id, status, name, email, confirm_hash, cancel_hash, event_id FROM appt_bookings WHERE email=?", (M1,))
check(len(bk) == 1 and bk[0][1] == "pending" and bk[0][4] and len(bk[0][4]) == 64 and bk[0][6] is None, "a pending booking, only the token hash " + str(bk))
B1 = bk[0][0]
ms = wait_mail(M1, 1)
check(len(ms) == 1 and "Please confirm your booking" in body_of(ms[0])[1], "one mail to confirm " + str([body_of(m)[1] for m in ms]))
TOK1 = link_in(ms[0], "c") if ms else None
check(TOK1 and TOK1 not in json.dumps(dbx("SELECT * FROM appt_bookings WHERE id=?", (B1,)), default=str), "the token is only in the mail")
r = pub.post(f"{B}/s/b/alice-termine/{T1}/{K}T1000", data={"f": fkey(PRE.text), "name": "Kunde Zwei", "email": "kunde.zwei@example.com"}, allow_redirects=False)
check(r.status_code == 409 and not dbx("SELECT 1 FROM appt_bookings WHERE email='kunde.zwei@example.com'"), "the held time cannot be booked a second time " + str(r.status_code))
check(f"{K}T1000" not in slots(pub.get(f"{B}/s/b/alice-termine/{T1}?w={MON}").text, "alice-termine", T1), "a pending booking holds the time")
r = book("alice-termine", T1, f"{K}T0800", "Bot", "bot@example.com", {"website": "http://spam.example.com"})
check(r.status_code == 200 and not dbx("SELECT 1 FROM appt_bookings WHERE email='bot@example.com'"), "honeypot: the same answer, nothing stored")
r = book("alice-termine", T1, f"{K}T0800", "Kunde Drei", "keine-adresse")
check(r.status_code == 400, "an invalid address: the form again (400)")
r = pub.post(f"{B}/s/b/alice-termine/{T1}/{K}T0800", data={"f": "0" * 64, "name": "X Y", "email": "x@example.com"}, allow_redirects=False)
check(r.status_code == 403, "a forged check value: 403")
g0 = pub.get(f"{B}/s/b/alice-termine/{T1}/{K}T0800")
r = pub.post(f"{B}/s/b/alice-termine/{T1}/{K}T0800", data={"f": fkey(g0.text), "name": "X Y", "email": "x@example.com"}, headers={"Sec-Fetch-Site": "cross-site"},
             allow_redirects=False)
check(r.status_code == 403, "a cross-site post: 403")
# 2.148.1 G (#2485): a booking refused at the address's daily limit does not use up the page's own mail quota
# 2.161.2 CI fix: the server's day (the test clock, KALMIDO_TEST_NOW of run_all.sh `now wed 10:00`), not the real UTC day
from datetime import timezone as _tz
from testclock import now as _tnow
_day = _tnow().astimezone(_tz.utc).strftime("%Y-%m-%d")
dbx("INSERT INTO mail_counts(k,day,n) VALUES('r:full@example.com',?,99) ON CONFLICT(k) DO UPDATE SET n=99, day=excluded.day", (_day,))
_q = lambda: (dbx("SELECT n FROM mail_counts WHERE k=? AND day=?", (f"apb:{ALICE}", _day)) or [(0,)])[0][0]
q0 = _q()
r = book("alice-termine", T1, f"{K}T0800", "Kunde Voll", "full@example.com")
check(r.status_code == 429 and _q() == q0, f"address at its daily limit: 429, the page quota unchanged {r.status_code} {q0} {_q()}")

# confirming
r = pub.get(f"{B}/s/b/c/{TOK1}")
check(r.status_code == 200 and "Confirm the booking" in r.text and dbx("SELECT status FROM appt_bookings WHERE id=?", (B1,))[0][0] == "pending",
      "GET of the confirmation link shows a button only (mail scanners)")
r = pub.post(f"{B}/s/b/c/{TOK1}", data={"f": "x"}, allow_redirects=False)
check(r.status_code == 403, "confirming without the check value: 403")
r = pub.post(f"{B}/s/b/c/{TOK1}", data={"f": fkey(pub.get(f"{B}/s/b/c/{TOK1}").text)}, allow_redirects=False)
check(r.status_code == 303, "confirmed " + str(r.status_code))
row = dbx("SELECT status, event_id, contact_id, deal_id, cancel_hash, ip FROM appt_bookings WHERE id=?", (B1,))[0]
check(row[0] == "confirmed" and row[1] and row[2] and row[4] and row[5] == "", "confirmed with event + contact, the address dropped " + str(row))
ev = dbx("SELECT title, cal_id, location, description, deleted_at FROM events WHERE id=?", (row[1],))[0]
check(ev[0] == "Erstgespräch: Kunde Eins" and ev[1] == ACAL and ev[2] == "Videoanruf" and M1 in ev[3] and "Bitte kurz anrufen." in ev[3], "the event in the page's calendar " + str(ev))
check([tuple(x) for x in dbx("SELECT email, name FROM event_attendees WHERE event_id=?", (row[1],))] == [(M1, "Kunde Eins")], "the customer is the attendee")
ct = dbx("SELECT c.fn, c.emails, b.owner_id FROM contacts c JOIN books b ON b.id=c.book_id WHERE c.id=?", (row[2],))[0]
check(ct[0] == "Kunde Eins" and M1 in ct[1] and ct[2] == ALICE, "a contact in alice's address book " + str(ct))
check(bool(row[3]), "the booking made a lead (office/leads.py lead_from_booking)")
if row[3]:
    dl = dbx("SELECT org_id, stage, source, follow_up FROM office_deals WHERE id=?", (row[3],))[0]
    check(tuple(dl[:3]) == (ORG, "lead", "booking") and dl[3] == K[:4] + "-" + K[4:6] + "-" + K[6:8], "the lead in the organisation's office, follow-up = the day " + str(dl))
check("Booking confirmed" in pub.get(f"{B}/s/b/c/{TOK1}").text, "the confirmation link shows the state afterwards")
ms = wait_mail(M1, 2)
check(len(ms) == 2 and "Your appointment is booked" in body_of(ms[1])[1] and "Videoanruf" in body_of(ms[1])[0], "the mail with the details")
CX1 = link_in(ms[1], "x") if len(ms) > 1 else None
check(bool(CX1), "... and the cancel link")
check(f"{K}T1000" not in slots(pub.get(f"{B}/s/b/alice-termine/{T1}?w={MON}").text, "alice-termine", T1), "the booked time is gone")
bl = A.get(B + AP + "/bookings").json()["bookings"]
check(any(b["id"] == B1 and b["status"] == "confirmed" and b["event_id"] == row[1] for b in bl), "the person's list of bookings")
check(Ca.get(B + AP + "/bookings").json()["bookings"] == [], "another person sees none")

# the same customer again: the contact is taken again
r = book("alice-termine", T1, f"{K}T1230", "Kunde Eins", M1)
ms = wait_mail(M1, 3)
TOK2 = link_in(ms[2], "c") if len(ms) > 2 else None
r = pub.post(f"{B}/s/b/c/{TOK2}", data={"f": fkey(pub.get(f"{B}/s/b/c/{TOK2}").text)}, allow_redirects=False)
B2, ct2 = dbx("SELECT id, contact_id FROM appt_bookings WHERE email=? AND status='confirmed' AND id<>?", (M1, B1))[0]
check(ct2 == row[2] and dbx("SELECT COUNT(*) FROM contacts WHERE emails LIKE ?", (f"%{M1}%",))[0][0] == 1, "the existing contact is taken, no double")

# the customer cancels
r = pub.get(f"{B}/s/b/x/{CX1}")
check(r.status_code == 200 and "Cancel the appointment" in r.text, "the cancel page")
r = pub.post(f"{B}/s/b/x/{CX1}", data={"f": fkey(r.text), "reason": "Krank"})
check(r.status_code == 200 and "Appointment cancelled" in r.text, "cancelled by the customer")
row = dbx("SELECT status, cancelled_by, cancel_reason, event_id FROM appt_bookings WHERE id=?", (B1,))[0]
check(tuple(row[:3]) == ("cancelled", "guest", "Krank") and dbx("SELECT deleted_at FROM events WHERE id=?", (row[3],))[0][0], "status + the event deleted " + str(row))
check(f"{K}T1000" in slots(pub.get(f"{B}/s/b/alice-termine/{T1}?w={MON}").text, "alice-termine", T1), "the time is free again")
check("Appointment cancelled" in pub.get(f"{B}/s/b/x/{CX1}").text, "the cancel link shows the state afterwards")

time.sleep(RATE_S + 1)  # 2.149.0 (#2513): the rate limit per client address (10 posts a minute) of the steps above

# the person cancels
check(Ca.post(B + f"{AP}/bookings/{B2}/cancel", json={}).status_code == 404, "another person cannot cancel: 404")
r = A.post(B + f"{AP}/bookings/{B2}/cancel", json={"reason": "Ich bin leider verhindert."})
check(r.ok and r.json()["status"] == "cancelled" and r.json()["cancelled_by"] == "host", "cancelled by the person")
check(A.post(B + f"{AP}/bookings/{B2}/cancel", json={}).status_code == 409, "a second cancel: 409")
ms = wait_mail(M1, 5)
check(len(ms) == 5 and "cancelled" in body_of(ms[4])[1] and "verhindert" in body_of(ms[4])[0], "the customer gets a mail with the reason " + str([body_of(m)[1] for m in ms]))

# ================================================================== spam protection
M3 = "kunde.drei@example.com"
for hm in ("0800", "0900", "1600"):
    book("alice-termine", T1, f"{K}T{hm}", "Kunde Drei", M3)
check(dbx("SELECT COUNT(*) FROM appt_bookings WHERE email=? AND status='pending'", (M3,))[0][0] == 3, "three open bookings")
r = book("alice-termine", T1, f"{K}T1700", "Kunde Drei", M3)
check(r.status_code == 429 and dbx("SELECT COUNT(*) FROM appt_bookings WHERE email=?", (M3,))[0][0] == 3, "a fourth open booking per address is refused")
ms3 = wait_mail(M3, 3)
TOK3 = link_in(ms3[0], "c") if ms3 else None
B3 = dbx("SELECT id FROM appt_bookings WHERE email=? ORDER BY id LIMIT 1", (M3,))[0][0]
dbx("UPDATE appt_bookings SET created_at=? WHERE id=?", ((testclock.now().astimezone(ZoneInfo("UTC")) - timedelta(minutes=31)).isoformat(timespec="seconds"), B3))
A.get(B + AP + "/bookings")
check(dbx("SELECT status FROM appt_bookings WHERE id=?", (B3,))[0][0] == "expired", "an unconfirmed booking expires after 30 minutes")
r = pub.get(f"{B}/s/b/c/{TOK3}")
check(r.status_code == 410 and "expired" in r.text, "its confirmation link says so " + str(r.status_code))
check(pub.get(f"{B}/s/b/c/{'x' * 43}").status_code == 404 and pub.get(f"{B}/s/b/x/{'y' * 43}").status_code == 404, "unknown tokens: 404")
A.put(B + AP + "/page", json={"enabled": False})
check(pub.get(f"{B}/s/b/alice-termine").status_code == 404 and pub.get(f"{B}/s/b/alice-termine").text == pub.get(f"{B}/s/b/no-such-page").text,
      "a switched-off page: the same 404 as an unknown one")
TOK4 = link_in(ms3[1], "c") if len(ms3) > 1 else "z" * 43
check(pub.get(f"{B}/s/b/c/{TOK4}").status_code == 404, "no confirmation while the page is off")
A.put(B + AP + "/page", json={"enabled": True})
# 2.94.0 (#1929 review): the person cancels an open booking: its confirmation link shows the state (410), not the bad-link 404
if len(ms3) > 2:
    TOK5 = link_in(ms3[2], "c")
    B5 = dbx("SELECT id FROM appt_bookings WHERE email=? ORDER BY id OFFSET 2 LIMIT 1", (M3,))[0][0]
    check(A.post(B + f"{AP}/bookings/{B5}/cancel", json={}).ok, "the person cancels an open booking")
    r = pub.get(f"{B}/s/b/c/{TOK5}")
    check(r.status_code == 410, "its confirmation link: 410, not 404 " + str(r.status_code))

# ================================================================== a freelancer without an organisation
r = Do.get(B + AP + "/page").json()
check([o["personal"] for o in r["offices"]] == [True], "the freelancer: only the personal office " + str(r["offices"]))
r = Do.put(B + AP + "/page", json={"slug": "dora-frei", "hours": ALL, "tz": "Europe/Berlin", "office_org_id": "personal", "enabled": True})
check(r.ok and r.json()["page"]["enabled"] and r.json()["page"]["office_org_id"], "the freelancer's page with the personal office " + r.text[:200])
DPO = r.json()["page"]["office_org_id"]
check(dbx("SELECT personal_of FROM orgs WHERE id=?", (DPO,))[0][0] == dbx("SELECT id FROM users WHERE username='dora'")[0][0], "... her own personal office")
DT = Do.post(B + AP + "/types", json={"name": "Beratung", "duration_min": 60, "notice_h": 0}).json()["id"]
MD = "kundin.vier@example.com"
book("dora-frei", DT, f"{K}T1000", "Kundin Vier", MD)
ms = wait_mail(MD, 1)
TD = link_in(ms[0], "c") if ms else None
r = pub.post(f"{B}/s/b/c/{TD}", data={"f": fkey(pub.get(f"{B}/s/b/c/{TD}").text)}, allow_redirects=False)
row = dbx("SELECT status, event_id, contact_id, deal_id FROM appt_bookings WHERE email=?", (MD,))[0]
DORA = dbx("SELECT id FROM users WHERE username='dora'")[0][0]
check(row[0] == "confirmed" and dbx("SELECT k.owner_id FROM events e JOIN ev_cals k ON k.id=e.cal_id WHERE e.id=?", (row[1],))[0][0] == DORA
      and dbx("SELECT b.owner_id FROM contacts c JOIN books b ON b.id=c.book_id WHERE c.id=?", (row[2],))[0][0] == DORA, "the freelancer's booking: own calendar + contacts " + str(row))
check(bool(row[3]) and dbx("SELECT org_id FROM office_deals WHERE id=?", (row[3] or 0,))[0][0] == DPO, "the lead in her personal office")
check(not any(b["email"] == MD for b in A.get(B + AP + "/bookings").json()["bookings"]), "alice does not see dora's bookings")
check(Do.post(B + f"{AP}/bookings/{B2}/cancel", json={}).status_code == 404, "dora cannot reach alice's booking")

# ================================================================== the rate limit per client address
codes = []
for i in range(12):
    g0 = pub.get(f"{B}/s/b/dora-frei/{DT}/{K}T1400")
    codes.append(pub.post(f"{B}/s/b/dora-frei/{DT}/{K}T1400", data={"f": fkey(g0.text), "name": "Spam Bot", "email": "kaputt"}).status_code)
check(429 in codes, "too many posts from one address: 429 " + str(codes))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
