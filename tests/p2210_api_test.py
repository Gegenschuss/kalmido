#!/usr/bin/env python3
"""2.21.0 API tests: package "Events & contacts" (#659 #658, own container via start.sh, isolated test database).
Events: calendars (create, rename, colour, share view / edit, hide, leave, delete), events (all day, several days, time zones,
validation, repeat rules with left-out and changed occurrences across the change to winter time, moving keeps the length,
a stale copy is refused), invitations (a person sees only that event, replies; a contact; an address), preparation tasks,
deleting + restoring, reminders (watchdog -> push), the family events of 2.19 becoming events (migration), ICS import of a
calendar export (twice = no doubles). CalDAV for events with realistic client requests (iOS Calendar, DAVx5, Thunderbird):
discovery, PROPFIND, calendar-query with time-range, calendar-multiget, sync-collection deltas, PUT / GET round trips that keep
what Kalmido has no field for, If-Match / If-None-Match, the wrong component, read-only roles, the invitations collection.
Contacts: address books, contacts (validation, search, groups, move, conflict), sharing, links to tasks (privacy), birthdays
as tasks, vCard import / export; CardDAV (iOS vCard 3.0 with labels + photo, vCard 4.0, multiget in another version, sync,
query filters, groups, read-only). API v1 + scopes (calendar, contacts: never in "read" or the legacy "write" for contacts),
OpenAPI, module switches, the data export, #671 (one tolerant local_day)."""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
BERLIN = ZoneInfo("Europe/Berlin")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def healthy():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def dbx(q, a=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


class Dav:
    """A calendar / contacts app: HTTP Basic with an app password, the methods and bodies real clients send."""
    def __init__(self, user, pw, ua="iOS/18.0 (22A3354) dataaccessd/1.0"):
        self.s = requests.Session()
        self.s.auth = (user, pw)
        self.s.headers["User-Agent"] = ua

    def req(self, m, path, body=None, **h):
        return self.s.request(m, B + path, data=body.encode() if isinstance(body, str) else body, headers=h, allow_redirects=False)


def ms(xml):
    """{href: {prop-tag: text}} of a multistatus (only the 200 propstats) + the 404 hrefs."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    out, gone = {}, []
    for r in root.iter("{DAV:}response"):
        href = r.find("{DAV:}href").text
        st = r.find("{DAV:}status")
        if st is not None and "404" in st.text:
            gone.append(href)
            continue
        props = {}
        for ps in r.findall("{DAV:}propstat"):
            if "200" in ps.find("{DAV:}status").text:
                for p in ps.find("{DAV:}prop"):
                    props[p.tag] = p
        out[href] = props
    tok = root.find("{DAV:}sync-token")
    return out, gone, (tok.text if tok is not None else None)


def txt(el):
    return "".join(el.itertext()) if el is not None else ""


PF_HOME = """<?xml version="1.0" encoding="UTF-8"?><A:propfind xmlns:A="DAV:" xmlns:B="urn:ietf:params:xml:ns:caldav"
 xmlns:C="http://calendarserver.org/ns/" xmlns:D="http://apple.com/ns/ical/"><A:prop><A:current-user-privilege-set/>
 <A:displayname/><A:resourcetype/><B:supported-calendar-component-set/><C:getctag/><A:sync-token/><D:calendar-color/>
 <D:calendar-order/><B:calendar-description/></A:prop></A:propfind>"""
PF_PRINCIPAL = """<?xml version="1.0" encoding="UTF-8"?><A:propfind xmlns:A="DAV:" xmlns:B="urn:ietf:params:xml:ns:caldav"
 xmlns:E="urn:ietf:params:xml:ns:carddav"><A:prop><B:calendar-home-set/><E:addressbook-home-set/><B:calendar-user-address-set/>
 <A:current-user-principal/><A:displayname/></A:prop></A:propfind>"""
PF_ETAG = '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getetag/><d:getcontenttype/></d:prop></d:propfind>'
SYNC = ('<?xml version="1.0" encoding="utf-8"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>{}</d:sync-token>'
        '<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>')
QUERY = ('<?xml version="1.0" encoding="utf-8"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
         '</D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT"><C:time-range start="{}" end="{}"/>'
         '</C:comp-filter></C:comp-filter></C:filter></C:calendar-query>')
MULTI = ('<?xml version="1.0" encoding="utf-8"?><C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop>'
         '<D:getetag/><C:calendar-data/></D:prop>{}</C:calendar-multiget>')
VTZ = ("BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nBEGIN:DAYLIGHT\r\nTZOFFSETFROM:+0100\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\n"
       "DTSTART:19810329T020000\r\nTZNAME:CEST\r\nTZOFFSETTO:+0200\r\nEND:DAYLIGHT\r\nBEGIN:STANDARD\r\nTZOFFSETFROM:+0200\r\n"
       "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\nDTSTART:19961027T030000\r\nTZNAME:CET\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n")


def ics(*events, tz=True, prodid="-//Apple Inc.//iPhone OS 18.0//EN"):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:" + prodid + "\r\nCALSCALE:GREGORIAN\r\n" + (VTZ if tz else "") + "".join(events) + "END:VCALENDAR\r\n"


def vevent(*lines):
    return "BEGIN:VEVENT\r\n" + "".join(x + "\r\n" for x in lines) + "END:VEVENT\r\n"


def occs(s, lo, hi, cal=None):
    r = s.get(B + f"/api/events?from={lo}&to={hi}" + (f"&calendar_id={cal}" if cal else ""))
    return r.json().get("items", []) if r.ok else r


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, capture_output=True)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "events", "contacts", "family"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "push_channel": "ntfy"})
A.patch(B + "/api/users/1", json={"email": "alice@example.org", "ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("eve", "Eve")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.org"})
    check(r.ok, f"user {u} " + r.text[:200])
    ids[u] = r.json()["id"]
    A.patch(B + f"/api/users/{ids[u]}", json={"ntfy_topic": "t-" + u})
BOB, EVE = ids["bob"], ids["eve"]
Bo, Ev = sess("bob"), sess("eve")
for s_ in (Bo, Ev):
    s_.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "push_channel": "ntfy"})
st = A.get(B + "/api/state").json()
fs = st["settings"]["features"].split(",")
check("events" in fs and "contacts" in fs and st["evcals"] == [] and st["books"] == [] and "evsig" in st, f"the setup switches events + contacts on {fs}")
check("events" in Bo.get(B + "/api/state").json()["settings"]["features"].split(","), "a new user has the modules too (default)")

# ================================================================== calendars
check(A.post(B + "/api/evcals", json={"name": ""}).status_code == 400 and A.post(B + "/api/evcals", json={"name": "x", "color": "red"}).status_code == 400,
      "a calendar needs a name and a #rrggbb colour")
check(A.post(B + "/api/evcals", json={"name": "x", "owner_id": 2}).status_code == 400, "unknown fields: 400")
W = A.post(B + "/api/evcals", json={"name": "Work", "color": "#2dd4bf"}).json()
P = A.post(B + "/api/evcals", json={"name": "Private"}).json()
check(W["role"] == "owner" and W["color"] == "#2dd4bf" and P["color"] and P["color"] != W["color"], f"two calendars, the second got its own colour {P}")
check(A.patch(B + f"/api/evcals/{W['id']}", json={"name": "Work stuff"}).json()["name"] == "Work stuff", "rename")
check(Bo.patch(B + f"/api/evcals/{W['id']}", json={"name": "x"}).status_code == 404 and Bo.delete(B + f"/api/evcals/{W['id']}").status_code == 404,
      "someone else: the calendar does not exist for them")
cals = A.get(B + "/api/state").json()["evcals"]
check([c["name"] for c in cals] == ["Work stuff", "Private"], f"in the state, in their order {[c['name'] for c in cals]}")

# ================================================================== events: validation, time zones, repeat rules
today = date.today()
D = today + timedelta(days=3)
r = A.post(B + "/api/events", json={"title": "Dentist", "cal_id": P["id"], "start": f"{D}T15:00", "end": f"{D}T14:00"})
check(r.status_code == 400 and "after the start" in r.json()["error"], "end before start: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": "2026-13-01T10:00"}).status_code == 400, "an impossible date: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00", "tz": "Mars/Base"}).status_code == 400, "an unknown time zone: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00", "rrule": "FREQ=HOURLY"}).status_code == 400, "an hourly rule: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00", "rrule": "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30"}).status_code == 400,
      "a rule that never matches: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00", "color": "#fff"}).status_code == 400, "an unknown field: 400")
check(A.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00", "cal_id": 999}).status_code == 404, "an unknown calendar: 404")
E1 = A.post(B + "/api/events", json={"title": "Dentist", "cal_id": P["id"], "start": f"{D}T15:00", "location": "Main St 1",
                                     "reminders": [30], "description": "Bring the card"}).json()
check(E1["end"] == f"{D}T16:00" and E1["tz"] == "Europe/Berlin" and E1["reminders"] == [30] and E1["role"] == "owner",
      f"a timed event: one hour by default, the server's zone {E1['end']} {E1['tz']}")
E2 = A.post(B + "/api/events", json={"title": "Holiday", "cal_id": P["id"], "all_day": True, "start": str(D), "end": str(D + timedelta(days=3))}).json()
o = [x for x in occs(A, D, D + timedelta(days=5)) if x["eid"] == E2["id"]]
check(len(o) == 1 and o[0]["all_day"] and o[0]["start"] == str(D) and o[0]["end"] == str(D + timedelta(days=3)), f"all day over three days, end exclusive {o}")
NY = A.post(B + "/api/events", json={"title": "Call NYC", "cal_id": W["id"], "start": f"{D}T09:00", "end": f"{D}T09:30", "tz": "America/New_York"}).json()
o = [x for x in occs(A, D, D) if x["eid"] == NY["id"]][0]
ny_utc = datetime.fromisoformat(f"{D}T09:00").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
check(o["start"] == ny_utc and NY["tz"] == "America/New_York", f"another time zone: 9:00 in New York = {ny_utc} {o['start']}")
r = A.patch(B + f"/api/events/{E1['id']}", json={"start": f"{D + timedelta(days=1)}T10:00"})
check(r.ok and r.json()["end"] == f"{D + timedelta(days=1)}T11:00", "moved: it keeps its length")
check(A.patch(B + f"/api/events/{E1['id']}", json={"title": "x", "expect": "2000-01-01T00:00:00+00:00"}).status_code == 409, "a stale copy: 409")
# weekly 9:00 over the change to winter time (last Sunday of October): stays 9:00 local
y = today.year if today < date(today.year, 10, 20) else today.year + 1
oct25 = max(date(y, 10, d) for d in range(25, 32) if date(y, 10, d).weekday() == 6)
mon = oct25 - timedelta(days=6)
WK = A.post(B + "/api/events", json={"title": "Standup", "cal_id": W["id"], "start": f"{mon}T09:00", "end": f"{mon}T09:15",
                                     "rrule": "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6"}).json()
o = [x for x in occs(A, mon, mon + timedelta(days=30)) if x["eid"] == WK["id"]]
loc = [datetime.fromisoformat(x["start"].replace("Z", "+00:00")).astimezone(BERLIN).strftime("%H:%M") for x in o]
check(len(o) == 6 and set(loc) == {"09:00"}, f"weekly, COUNT=6, 9:00 local before and after the change to winter time {loc}")
second = o[1]["occ"]
r = A.patch(B + f"/api/events/{WK['id']}?occ={second}", json={"title": "Standup (moved)", "start": second[:10] + "T11:00", "end": second[:10] + "T11:30"})
check(r.ok and r.json()["overrides"][0]["rid"] == second and r.json()["overrides"][0]["start"] == second[:10] + "T11:00", "only this date: an override")
check(A.delete(B + f"/api/events/{WK['id']}?occ={o[2]['occ']}").ok, "only this date: deleted")
o2 = [x for x in occs(A, mon, mon + timedelta(days=30)) if x["eid"] == WK["id"]]
check(len(o2) == 5 and o2[1]["title"] == "Standup (moved)" and o2[1]["changed"] and o[2]["occ"] not in [x["occ"] for x in o2],
      f"5 dates left, the moved one changed {[(x['title'], x['occ']) for x in o2]}")
check(A.patch(B + f"/api/events/{E1['id']}?occ={D}T15:00", json={"title": "x"}).status_code == 400, "a single date of an event that does not repeat: 400")
check(A.get(B + f"/api/events/{WK['id']}").json()["exdates"] == [o[2]["occ"]], "the left-out date is listed")
far = occs(A, today, today + timedelta(days=500))
check(not isinstance(far, list) and far.status_code == 400, "a range of more than 400 days: 400")
YR = A.post(B + "/api/events", json={"title": "Anniversary dinner", "cal_id": P["id"], "all_day": True, "start": str(D), "rrule": "FREQ=YEARLY"}).json()
o = [x for x in occs(A, D, D + timedelta(days=370)) if x["eid"] == YR["id"]]
check(len(o) == 2, f"yearly: this year and the next {[(x['start']) for x in o]}")
r = A.patch(B + f"/api/events/{YR['id']}", json={"rrule": ""})
check(r.ok and r.json()["rrule"] == "" and len([x for x in occs(A, D, D + timedelta(days=370)) if x["eid"] == YR["id"]]) == 1, "the repeat removed: once")

# ================================================================== sharing + hiding + invitations
check(Bo.get(B + f"/api/events/{E1['id']}").status_code == 404 and not [x for x in occs(Bo, D, D + timedelta(days=3))], "Bob sees nothing of Alice's calendars")
check(A.put(B + f"/api/evcals/{W['id']}/members", json={"user_id": BOB, "role": "view"}).ok, "Work shared with Bob (view)")
cb = Bo.get(B + "/api/evcals").json()["items"]
check(len(cb) == 1 and cb[0]["role"] == "view" and cb[0]["owner_name"] == "Alice" and "members" not in cb[0], f"Bob: the calendar, view, no member list {cb}")
check({x["eid"] for x in occs(Bo, D, D)} == {NY["id"]}, "Bob sees the Work events only")
check(Bo.patch(B + f"/api/events/{NY['id']}", json={"title": "x"}).status_code == 403 and Bo.post(B + "/api/events", json={"title": "x", "cal_id": W["id"], "start": f"{D}T10:00"}).status_code == 403,
      "view: no changes, no new events")
check(Bo.get(B + f"/api/events/{E1['id']}").status_code == 404, "Bob: an event of the Private calendar stays hidden")
A.put(B + f"/api/evcals/{W['id']}/members", json={"user_id": BOB, "role": "edit"})
check(Bo.patch(B + f"/api/events/{NY['id']}", json={"location": "Zoom"}).ok, "edit: Bob changes a Work event")
nb = [n for n in Bo.get(B + "/api/news").json().get("items", []) if n["kind"] == "evshare"]
check(nb and nb[0]["data"]["name"] == "Work stuff", "Bob got News: a calendar was shared")
check(Bo.patch(B + f"/api/evcals/{W['id']}", json={"hidden": True}).json()["hidden"] and not occs(Bo, D, D), "Bob hides Work: gone from his views")
Bo.patch(B + f"/api/evcals/{W['id']}", json={"hidden": False})
check(Bo.patch(B + f"/api/evcals/{W['id']}", json={"name": "x"}).status_code == 403, "only the owner renames")
# invitations
r = A.post(B + "/api/events", json={"title": "Family dinner", "cal_id": P["id"], "start": f"{D}T19:00", "end": f"{D}T21:00",
                                    "attendees": [{"user_id": EVE}, {"email": "uncle@example.net", "name": "Uncle Tom"}]})
FD = r.json()
check(r.status_code == 201 and len(FD["attendees"]) == 2 and FD["attendees"][0]["partstat"] == "needs-action", "an event with a person and an address")
ev_ = Ev.get(B + f"/api/events/{FD['id']}").json()
check(ev_["role"] == "attendee" and ev_["cal_id"] is None and ev_["task_id"] is None and ev_["partstat"] == "needs-action", "Eve: only this event, without the calendar")
check(Ev.get(B + f"/api/events/{E1['id']}").status_code == 404 and {x["eid"] for x in occs(Ev, D, D + timedelta(days=3))} == {FD["id"]}, "Eve sees nothing else of the calendar")
check(Ev.patch(B + f"/api/events/{FD['id']}", json={"title": "x"}).status_code == 403, "an invited person cannot change it")
r = Ev.post(B + f"/api/events/{FD['id']}/rsvp", json={"partstat": "accepted"})
check(r.ok and r.json()["partstat"] == "accepted" and A.get(B + f"/api/events/{FD['id']}").json()["attendees"][0]["partstat"] == "accepted", "Eve accepts: Alice sees it")
check(Bo.post(B + f"/api/events/{FD['id']}/rsvp", json={"partstat": "accepted"}).status_code == 404, "someone not invited cannot reply")
check(Ev.post(B + f"/api/events/{FD['id']}/rsvp", json={"partstat": "yes"}).status_code == 400, "an unknown reply: 400")
ne = [n for n in Ev.get(B + "/api/news").json().get("items", []) if n["kind"] == "evinvite"]
check(ne and ne[0]["data"]["title"] == "Family dinner", "Eve got News: the invitation")
check(until(lambda: any(m.get("topic") == "t-eve" and "invited you" in (m.get("title") or "") for m in ntfy()), 8), "… and a push")
A.patch(B + f"/api/events/{FD['id']}", json={"title": "Family dinner (Sunday)"})
check(A.get(B + f"/api/events/{FD['id']}").json()["attendees"][0]["partstat"] == "accepted", "a change keeps Eve's answer")
# preparation task + delete / restore
r = A.post(B + f"/api/events/{E1['id']}/prep-task", json={"days_before": 2})
PT = r.json()["task"]
check(r.status_code == 201 and PT["title"] == "Prepare: Dentist" and PT["due"] == str(D + timedelta(days=1) - timedelta(days=2)) and r.json()["event"]["task_id"] == PT["id"],
      f"preparation task: two days before, linked {PT.get('due')}")
check(A.post(B + f"/api/events/{E1['id']}/prep-task", json={}).status_code == 409, "a second one: 409")
st = A.get(B + "/api/state").json()
check(st["evlinks"].get(str(PT["id"]), [{}])[0].get("id") == E1["id"], "the state links the task to its event")
check([e["id"] for e in A.get(B + f"/api/tasks/{PT['id']}/events").json()["items"]] == [E1["id"]], "GET /api/tasks/<id>/events")
check(A.delete(B + f"/api/events/{E2['id']}").ok and A.get(B + f"/api/events/{E2['id']}").status_code == 404 and not [x for x in occs(A, D, D + timedelta(days=5)) if x["eid"] == E2["id"]],
      "deleted: gone")
check(A.post(B + f"/api/events/{E2['id']}/restore").ok and A.get(B + f"/api/events/{E2['id']}").ok, "restored")
# reminders: an event in 2 minutes with a reminder 5 minutes before
now = datetime.now(BERLIN) + timedelta(minutes=2)
RM = A.post(B + "/api/events", json={"title": "Soon meeting", "cal_id": W["id"], "start": now.strftime("%Y-%m-%dT%H:%M"), "reminders": [5],
                                     "location": "Room 4"}).json()
check(until(lambda: any(m.get("topic") == "t-alice" and m.get("title") == "Soon meeting" and "Room 4" in (m.get("msg") or "") for m in ntfy()), 15),
      "the reminder came as a push to Alice (owner) with the place")
check(until(lambda: any(m.get("topic") == "t-bob" and m.get("title") == "Soon meeting" for m in ntfy()), 10), "… and to Bob (the calendar is shared with him)")
time.sleep(2.5)
check(len([m for m in ntfy() if m.get("topic") == "t-alice" and m.get("title") == "Soon meeting"]) == 1, "once only")

# ================================================================== ICS import (an export of another calendar)
GOOGLE = ics(
    vevent("DTSTART;TZID=Europe/Berlin:20261102T080000", "DTEND;TZID=Europe/Berlin:20261102T083000", "RRULE:FREQ=DAILY;COUNT=5",
           "EXDATE;TZID=Europe/Berlin:20261104T080000", "UID:g-daily@google.com", "SUMMARY:Run", "DTSTAMP:20261001T000000Z"),
    vevent("DTSTART;TZID=Europe/Berlin:20261105T100000", "DTEND;TZID=Europe/Berlin:20261105T103000", "RECURRENCE-ID;TZID=Europe/Berlin:20261105T080000",
           "UID:g-daily@google.com", "SUMMARY:Run (late)", "DTSTAMP:20261001T000000Z"),
    vevent("DTSTART;VALUE=DATE:20261224", "DTEND;VALUE=DATE:20261227", "UID:g-xmas@google.com", "SUMMARY:Christmas", "TRANSP:TRANSPARENT"),
    vevent("DTSTART:20261110T120000Z", "DTEND:20261110T130000Z", "UID:g-utc@google.com", "SUMMARY:Lunch UTC", "X-GOOGLE-CONFERENCE:https://meet.example"),
    prodid="-//Google Inc//Google Calendar 70.9054//EN")
IMP = A.post(B + "/api/evcals", json={"name": "Google"}).json()
r = A.post(B + f"/api/evcals/{IMP['id']}/import?dry=1", files={"file": ("cal.ics", GOOGLE, "text/calendar")})
check(r.ok and r.json()["created"] == 3 and not A.get(B + "/api/events?from=2026-11-01&to=2026-11-30&calendar_id=%d" % IMP["id"]).json()["items"], f"dry run: counts only {r.text[:200]}")
r = A.post(B + f"/api/evcals/{IMP['id']}/import", files={"file": ("cal.ics", GOOGLE, "text/calendar")})
check(r.ok and r.json() == {"created": 3, "updated": 0, "skipped": 0, "errors": 0}, f"imported: 3 events {r.text[:200]}")
r = A.post(B + f"/api/evcals/{IMP['id']}/import", files={"file": ("cal.ics", GOOGLE, "text/calendar")})
check(r.ok and r.json()["created"] == 0 and r.json()["updated"] == 3, "imported twice: updated, no doubles")
o = occs(A, date(2026, 11, 1), date(2026, 12, 31), IMP["id"])
runs = [(x["title"], x["start"]) for x in o if x["title"].startswith("Run")]
check(len(runs) == 4 and ("Run (late)", "2026-11-05T09:00:00Z") in runs and not any(s.startswith("2026-11-04") for _, s in runs),
      f"daily x5, one left out, one moved to 10:00 {runs}")
xm = [x for x in o if x["title"] == "Christmas"]
check(xm and xm[0]["all_day"] and xm[0]["end"] == "2026-12-27", "all-day Christmas")
lu = [x for x in o if x["title"] == "Lunch UTC"]
check(lu and lu[0]["start"] == "2026-11-10T12:00:00Z", "a UTC event")
check(A.post(B + f"/api/evcals/{IMP['id']}/import", files={"file": ("x.ics", "hello", "text/calendar")}).status_code == 400, "not an ICS file: 400")

# ================================================================== CalDAV: discovery + events (iOS, DAVx5, Thunderbird)
r = A.post(B + "/api/me/app-passwords", json={"name": "iPhone"})
PW = r.json()["password"]
iph = Dav("alice", PW)
r = iph.req("PROPFIND", "/.well-known/caldav", PF_PRINCIPAL, Depth="0")
check(r.status_code == 301 and r.headers["Location"].endswith("/dav/"), "/.well-known/caldav -> /dav/")
r = iph.req("PROPFIND", "/.well-known/carddav", PF_PRINCIPAL, Depth="0")
check(r.status_code == 301 and r.headers["Location"].endswith("/dav/"), "/.well-known/carddav -> /dav/")
r = iph.req("PROPFIND", "/dav/principals/alice/", PF_PRINCIPAL, Depth="0")
p = ms(r.text)[0]["/dav/principals/alice/"]
addrs = [x.text for x in p["{urn:ietf:params:xml:ns:caldav}calendar-user-address-set"]]
check(txt(p["{urn:ietf:params:xml:ns:carddav}addressbook-home-set"]).strip() == "/dav/addressbooks/alice/" and "mailto:alice@example.org" in addrs
      and "urn:kalmido:user:1" in addrs, f"principal: addressbook-home-set, the addresses {addrs}")
r = iph.req("PROPFIND", "/dav/calendars/alice/", PF_HOME, Depth="1")
home = ms(r.text)[0]
comps = {h: [c.get("name") for c in pp.get("{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set", [])] for h, pp in home.items()}
ev_colls = [h for h, c in comps.items() if c == ["VEVENT"]]
check(r.status_code == 207 and f"/dav/calendars/alice/e{W['id']}/" in ev_colls and f"/dav/calendars/alice/e{P['id']}/" in ev_colls
      and any(c == ["VTODO"] for c in comps.values()), f"the home: task lists (VTODO) and event calendars (VEVENT) {comps}")
check("inv" not in "".join(ev_colls), "no Invitations collection for Alice (she is invited nowhere)")
WC = f"/dav/calendars/alice/e{W['id']}/"
check(txt(home[WC]["{http://apple.com/ns/ical/}calendar-color"]) == "#2DD4BFFF" and txt(home[WC]["{DAV:}displayname"]) == "Work stuff", "name + colour")
r = iph.req("PROPFIND", WC, PF_ETAG, Depth="1")
mem, _, _ = ms(r.text)
check(len([h for h in mem if h.endswith(".ics")]) == 3, f"Work: three events (Standup, Call NYC, Soon meeting) {list(mem)}")
r = iph.req("REPORT", WC, SYNC.format(""), Depth="1")
_, _, tok0 = ms(r.text)
# iOS creates an event: VTIMEZONE, VALARM, X-APPLE properties, a structured location
IOS = ics(vevent("CREATED:20261005T100000Z", "UID:IOS-ABC-1", "DTEND;TZID=Europe/Berlin:20261108T130000", "TRANSP:OPAQUE",
                 "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC", "SUMMARY:Dentist (phone)", "LAST-MODIFIED:20261005T100000Z",
                 "DTSTAMP:20261005T100000Z", "DTSTART;TZID=Europe/Berlin:20261108T120000", "LOCATION:Main St 1\\nTown", "SEQUENCE:0",
                 "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-TITLE=Main St 1:geo:52.5,13.4",
                 "BEGIN:VALARM", "X-WR-ALARMUID:A1", "UID:A1", "TRIGGER:-PT30M", "ACTION:DISPLAY", "DESCRIPTION:Reminder", "END:VALARM"))
r = iph.req("PUT", WC + "IOS-ABC-1.ics", IOS, **{"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
check(r.status_code == 201, f"iOS PUT: created {r.status_code} {r.text[:200]}")
e = [x for x in occs(A, date(2026, 11, 8), date(2026, 11, 8)) if x["title"] == "Dentist (phone)"]
check(e and e[0]["start"] == "2026-11-08T11:00:00Z" and e[0]["location"] == "Main St 1, Town", f"the event in the app (the address on one line) {e}")
ef = A.get(B + f"/api/events/{e[0]['eid']}").json()
check(ef["reminders"] == [30] and ef["uid"] == "IOS-ABC-1", "the alarm became a reminder of 30 minutes")
r = iph.req("GET", WC + "IOS-ABC-1.ics")
body = r.text
check(r.ok and "X-APPLE-STRUCTURED-LOCATION" in body and "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC" in body and "TRIGGER:-PT30M" in body
      and "DTSTART;TZID=Europe/Berlin:20261108T120000" in body and "BEGIN:VTIMEZONE" in body and r.headers.get("ETag"),
      "GET: what Kalmido has no field for comes back, the time zone, the alarm")
et = r.headers["ETag"]
r = iph.req("PUT", WC + "IOS-ABC-1.ics", IOS.replace("Dentist (phone)", "Dentist (moved)"), **{"Content-Type": "text/calendar", "If-Match": '"stale"'})
check(r.status_code == 412, "a stale If-Match: 412")
r = iph.req("PUT", WC + "IOS-ABC-1.ics", IOS.replace("Dentist (phone)", "Dentist (moved)").replace("20261108T12", "20261109T12").replace("20261108T13", "20261109T13"),
            **{"Content-Type": "text/calendar", "If-Match": et})
check(r.status_code == 204 and A.get(B + f"/api/events/{e[0]['eid']}").json()["start"] == "2026-11-09T12:00", "the right If-Match: updated")
A.patch(B + f"/api/events/{e[0]['eid']}", json={"description": "From the app"})
r = iph.req("REPORT", WC, SYNC.format(tok0), Depth="1")
ch, gone, tok1 = ms(r.text)
check(r.status_code == 207 and list(ch) == [WC + "IOS-ABC-1.ics"] and not gone and tok1 != tok0, f"sync-collection: only the changed resource {list(ch)}")
r = iph.req("GET", WC + "IOS-ABC-1.ics")
check("DESCRIPTION:From the app" in r.text and "X-APPLE-STRUCTURED-LOCATION" in r.text, "a change in the app reaches the phone, the rest stays")
# DAVx5: a recurring event with an exception, a different time zone and attendees (one is Bob by his e-mail)
DAVX = ics(vevent("UID:davx-rec-1", "DTSTAMP:20261005T100000Z", "SUMMARY:Team sync", "DTSTART;TZID=Europe/Berlin:20261103T100000",
                  "DTEND;TZID=Europe/Berlin:20261103T110000", "RRULE:FREQ=WEEKLY;UNTIL=20261124T090000Z", "EXDATE;TZID=Europe/Berlin:20261110T100000",
                  "ORGANIZER;CN=Alice:mailto:alice@example.org", "ATTENDEE;CN=Bob;PARTSTAT=ACCEPTED;ROLE=REQ-PARTICIPANT;X-KALMIDO-USER=%d:urn:kalmido:user:%d" % (BOB, BOB),
                  "ATTENDEE;CN=Guest;PARTSTAT=NEEDS-ACTION:mailto:guest@example.net"),
           vevent("UID:davx-rec-1", "DTSTAMP:20261005T100000Z", "RECURRENCE-ID;TZID=Europe/Berlin:20261117T100000", "SUMMARY:Team sync (long)",
                  "DTSTART;TZID=Europe/Berlin:20261117T100000", "DTEND;TZID=Europe/Berlin:20261117T123000"), prodid="+//IDN bitfire.at//DAVx5/4.4//EN")
dx = Dav("alice", PW, "DAVx5/4.4-ose (2024/09/01; dav4jvm; okhttp/4.12.0) Android/14")
r = dx.req("PUT", WC + "davx-rec-1.ics", DAVX, **{"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
check(r.status_code == 201, f"DAVx5 PUT {r.status_code} {r.text[:200]}")
o = [x for x in occs(A, date(2026, 11, 1), date(2026, 11, 30)) if x["title"].startswith("Team sync")]
check([(x["start"], x["title"]) for x in o] == [("2026-11-03T09:00:00Z", "Team sync"), ("2026-11-17T09:00:00Z", "Team sync (long)"), ("2026-11-24T09:00:00Z", "Team sync")],
      f"weekly until 24 Nov, 10 Nov left out, 17 Nov longer {[(x['start'], x['title']) for x in o]}")
ts_ = A.get(B + f"/api/events/{o[0]['eid']}").json()
att = {a["email"] or a["user_id"]: a for a in ts_["attendees"]}
check(att.get(BOB, {}).get("partstat") == "needs-action" and "guest@example.net" in att, f"attendees: Bob (by his Kalmido id; his answer is his own, not the client's) + the guest {ts_['attendees']}")
check(Bo.get(B + f"/api/events/{o[0]['eid']}").ok, "Bob sees it (also as a member of Work)")
r = dx.req("GET", WC + "davx-rec-1.ics")
check("RECURRENCE-ID;TZID=Europe/Berlin:20261117T100000" in r.text and "EXDATE;TZID=Europe/Berlin:20261110T100000" in r.text
      and "X-KALMIDO-USER=%d:urn:kalmido:user:%d" % (BOB, BOB) in r.text.replace("\r\n ", "") and "bob@example.org" not in r.text and "alice@example.org" not in r.text
      and "UNTIL=20261124T090000Z" in r.text,
      "GET: the exception, the left-out date, the attendees, UNTIL in UTC " + "|".join(l for l in r.text.split("\r\n") if l.startswith(("ATTENDEE", "ORGANIZER", "RRULE", "EXDATE", "RECURRENCE"))))
r = dx.req("REPORT", WC, QUERY.format("20261117T000000Z", "20261118T000000Z"), Depth="1")
hit = list(ms(r.text)[0])
check(WC + "davx-rec-1.ics" in hit and WC + "IOS-ABC-1.ics" not in hit, f"calendar-query time-range: the series with a date that day {hit}")
r = dx.req("REPORT", WC, MULTI.format(f"<D:href>{WC}davx-rec-1.ics</D:href><D:href>{WC}nope.ics</D:href>"), Depth="1")
mm, gone, _ = ms(r.text)
check("BEGIN:VEVENT" in txt(mm[WC + "davx-rec-1.ics"]["{urn:ietf:params:xml:ns:caldav}calendar-data"]) and gone == [WC + "nope.ics"], "calendar-multiget: data + 404")
# an address never picks (or reveals) an account; an editor cannot answer for someone else
ORA = ics(vevent("UID:oracle-1", "DTSTAMP:20261005T100000Z", "SUMMARY:Probe", "DTSTART;TZID=Europe/Berlin:20261104T100000",
                 "DTEND;TZID=Europe/Berlin:20261104T110000", "ATTENDEE;PARTSTAT=ACCEPTED:mailto:eve@example.org"))
check(dx.req("PUT", WC + "oracle-1.ics", ORA, **{"Content-Type": "text/calendar"}).status_code == 201, "PUT with a server user's e-mail")
oe = [x for x in occs(A, date(2026, 11, 4), date(2026, 11, 4)) if x["title"] == "Probe"]
oa = A.get(B + f"/api/events/{oe[0]['eid']}").json()["attendees"] if oe else []
check(oa and oa[0]["user_id"] is None and oa[0]["email"] == "eve@example.org" and Ev.get(B + f"/api/events/{oe[0]['eid']}").status_code == 404,
      f"an e-mail stays an address: no account looked up, Eve sees nothing {oa}")
r = A.patch(B + f"/api/events/{FD['id']}", json={"attendees": [{"user_id": EVE, "partstat": "declined"}]})
check(r.ok and r.json()["attendees"][0]["partstat"] == "accepted", "the organiser cannot change Eve's answer")
check(A.post(B + "/api/events", json={"title": "x", "start": "2026-11-01T10:00", "rrule": "FREQ=DAILY;UNTIL=20261340T000000Z"}).status_code == 400,
      "an impossible UNTIL: 400, not 500")
check(A.get(B + "/api/events?from=0001-01-01&to=0001-02-01").status_code == 400 and A.get(B + "/api/calendars/events?from=9999-12-01&to=9999-12-31").status_code == 400,
      "dates outside 1900-2999: 400")
r = A.patch(B + f"/api/events/{WK['id']}?occ={mon}T13:00", json={"title": "ghost"})
check(r.status_code == 400, "a date the series does not have: 400")
# Thunderbird: no VTIMEZONE, a floating time, an all-day event
tb = Dav("alice", PW, "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Thunderbird/128.3.0")
TB = ics(vevent("UID:tb-1", "DTSTAMP:20261005T100000Z", "SUMMARY:Floating", "DTSTART:20261120T080000", "DTEND:20261120T090000"),
         tz=False, prodid="-//Mozilla.org/NONSGML Mozilla Calendar V1.1//EN")
check(tb.req("PUT", WC + "tb-1.ics", TB, **{"Content-Type": "text/calendar"}).status_code == 201, "Thunderbird PUT")
o = [x for x in occs(A, date(2026, 11, 20), date(2026, 11, 20)) if x["title"] == "Floating"]
check(o and o[0]["start"] == "2026-11-20T07:00:00Z", "a floating time is the server's wall time")
TB2 = ics(vevent("UID:tb-2", "DTSTAMP:20261005T100000Z", "SUMMARY:Day off", "DTSTART;VALUE=DATE:20261121", "DTEND;VALUE=DATE:20261122"), tz=False)
check(tb.req("PUT", WC + "tb-2.ics", TB2, **{"Content-Type": "text/calendar"}).status_code == 201, "an all-day event over CalDAV")
# what an event calendar refuses
TODO = ics("BEGIN:VTODO\r\nUID:todo-1\r\nSUMMARY:x\r\nEND:VTODO\r\n")
r = iph.req("PUT", WC + "todo-1.ics", TODO, **{"Content-Type": "text/calendar"})
check(r.status_code == 403 and "supported-calendar-component" in r.text, "a VTODO in an event calendar: 403")
lid = [l for l in A.get(B + "/api/state").json()["lists"] if l["is_inbox"]][0]["id"]
r = iph.req("PUT", f"/dav/calendars/alice/{lid}/ev-in-list.ics", IOS.replace("IOS-ABC-1", "ev-in-list"), **{"Content-Type": "text/calendar"})
check(r.status_code == 403, "a VEVENT in a task list: 403")
r = iph.req("PUT", WC + "dup.ics", IOS, **{"Content-Type": "text/calendar"})
check(r.status_code == 403 and "no-uid-conflict" in r.text, "the same UID under another name: 403 no-uid-conflict")
check(iph.req("MKCALENDAR", "/dav/calendars/alice/new/").status_code == 403, "MKCALENDAR: create calendars in the app")
# Bob: edit on Work over DAV, Private does not exist for him; Eve: the invitations collection
r = Bo.post(B + "/api/me/app-passwords", json={"name": "Phone"})
bob = Dav("bob", r.json()["password"])
r = bob.req("PROPFIND", "/dav/calendars/bob/", PF_HOME, Depth="1")
bh = ms(r.text)[0]
check(f"/dav/calendars/bob/e{W['id']}/" in bh and f"/dav/calendars/bob/e{P['id']}/" not in bh, "Bob's home: Work, not Private")
check(bob.req("GET", f"/dav/calendars/bob/e{P['id']}/x.ics").status_code == 404, "Private does not exist for Bob")
A.put(B + f"/api/evcals/{W['id']}/members", json={"user_id": BOB, "role": "view"})
r = bob.req("PUT", f"/dav/calendars/bob/e{W['id']}/bob-1.ics", IOS.replace("IOS-ABC-1", "bob-1"), **{"Content-Type": "text/calendar"})
check(r.status_code == 403, "view only: PUT 403")
check(bob.req("DELETE", f"/dav/calendars/bob/e{W['id']}/IOS-ABC-1.ics").status_code == 403, "view only: DELETE 403")
r = Ev.post(B + "/api/me/app-passwords", json={"name": "Phone"})
eve = Dav("eve", r.json()["password"])
r = eve.req("PROPFIND", "/dav/calendars/eve/inv/", PF_ETAG, Depth="1")
inv, _, _ = ms(r.text)
check(r.status_code == 207 and len([h for h in inv if h.endswith(".ics")]) == 1, f"Eve: the invitations collection with the dinner {list(inv)}")
r = eve.req("PUT", "/dav/calendars/eve/inv/x.ics", IOS.replace("IOS-ABC-1", "x"), **{"Content-Type": "text/calendar"})
check(r.status_code == 403, "the invitations are read-only")
# DELETE over DAV -> sync says 404
_, _, tok2 = ms(iph.req("REPORT", WC, SYNC.format(""), Depth="1").text)
r = iph.req("DELETE", WC + "tb-1.ics")
check(r.status_code == 204 and not [x for x in occs(A, date(2026, 11, 20), date(2026, 11, 20)) if x["title"] == "Floating"], "DELETE")
r = iph.req("REPORT", WC, SYNC.format(tok2), Depth="1")
ch, gone, _ = ms(r.text)
check(gone == [WC + "tb-1.ics"] and not ch, f"sync after DELETE: only a 404 for the deleted one {gone} {list(ch)}")
r = iph.req("REPORT", WC, SYNC.format(tok1), Depth="1")
ch, gone, _ = ms(r.text)
check(WC + "tb-2.ics" in ch and WC + "davx-rec-1.ics" in ch and WC + "tb-1.ics" not in gone, "sync from an older token: the new ones (one created + deleted meanwhile: never seen)")
check(iph.req("REPORT", WC, SYNC.format("urn:kalmido:sync:e1-0000000000000000dead"), Depth="1").status_code == 403, "an unknown sync-token: 403")

# ================================================================== contacts (web)
check(A.post(B + "/api/contacts", json={}).status_code == 400, "a contact needs a name or a company")
check(A.post(B + "/api/contacts", json={"given": "X", "emails": [{"value": "no-mail"}]}).status_code == 400, "a bad e-mail: 400")
check(A.post(B + "/api/contacts", json={"given": "X", "bday": "1980-02-30"}).status_code == 400, "an impossible birthday: 400")
check(A.post(B + "/api/contacts", json={"given": "X", "photo": "data:text/html;base64,PGh0bWw+"}).status_code == 400, "a photo must be an image")
C1 = A.post(B + "/api/contacts", json={"given": "Erika", "family": "Mustermann", "org": "ACME", "title": "CEO",
                                      "emails": [{"value": "erika@example.org", "type": ["work"]}], "phones": [{"value": "+49 170 1234567", "type": ["cell"]}],
                                      "addresses": [{"street": "Main St 1", "city": "Berlin", "code": "10115", "country": "Germany", "type": ["work"]}],
                                      "bday": "1964-08-12", "groups": ["Customers", "VIP"], "note": "Met at the fair"}).json()
check(C1["fn"] == "Erika Mustermann" and C1["role"] == "owner" and C1["book_id"], f"a contact, the display name from the parts {C1.get('fn')}")
books = A.get(B + "/api/books").json()["items"]
check(len(books) == 1 and books[0]["name"] == "Contacts" and books[0]["count"] == 1, "the first contact created the address book Contacts")
BK = books[0]["id"]
C2 = A.post(B + "/api/contacts", json={"fn": "Plumber Joe", "phones": [{"value": "030 999"}], "groups": ["Home"]}).json()
for q, want in (("erika", [C1["id"]]), ("1701234567", [C1["id"]]), ("acme", [C1["id"]]), ("berlin", [C1["id"]]), ("joe", [C2["id"]]), ("", [C1["id"], C2["id"]])):
    got = [x["id"] for x in A.get(B + "/api/contacts", params={"q": q}).json()["items"]]
    check(sorted(got) == sorted(want), f"search {q!r}: {got}")
j = A.get(B + "/api/contacts", params={"group": "VIP"}).json()
check([x["id"] for x in j["items"]] == [C1["id"]] and j["groups"] == ["Customers", "Home", "VIP"], f"group filter + all groups {j['groups']}")
r = A.patch(B + f"/api/contacts/{C1['id']}", json={"title": "Chair", "expect": C1["updated_at"]})
check(r.ok and r.json()["title"] == "Chair" and r.json()["org"] == "ACME", "a change keeps the other fields")
check(A.patch(B + f"/api/contacts/{C1['id']}", json={"title": "x", "expect": C1["updated_at"]}).status_code == 409, "a stale copy: 409")
check(Bo.get(B + f"/api/contacts/{C1['id']}").status_code == 404 and Bo.get(B + "/api/contacts").json()["items"] == [], "Bob sees no contacts of Alice")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": BOB, "role": "view"}).ok, "the address book shared with Bob (view)")
check(Bo.get(B + f"/api/contacts/{C1['id']}").ok and Bo.patch(B + f"/api/contacts/{C1['id']}", json={"title": "x"}).status_code == 403, "view: read, no change")
nb = [n for n in Bo.get(B + "/api/news").json().get("items", []) if n["kind"] == "abshare"]
check(bool(nb), "Bob got News: an address book was shared")
# links to tasks + privacy
T1 = A.post(B + "/api/tasks", json={"title": "Wait for the offer"}).json()
r = A.post(B + f"/api/tasks/{T1['id']}/contacts", json={"contact_id": C1["id"], "kind": "waiting"})
check(r.ok and r.json()["items"] == [{"contact_id": C1["id"], "kind": "waiting", "fn": "Erika Mustermann"}], "a contact linked to a task (waiting on)")
check(A.post(B + f"/api/tasks/{T1['id']}/contacts", json={"contact_id": C1["id"], "kind": "boss"}).status_code == 400, "an unknown kind: 400")
st = A.get(B + "/api/state").json()
check(st["tcontacts"].get(str(T1["id"])) == [{"contact_id": C1["id"], "kind": "waiting", "fn": "Erika Mustermann"}], "the state: the task's contacts")
check([t["task_id"] for t in A.get(B + f"/api/contacts/{C1['id']}").json()["tasks"]] == [T1["id"]], "the contact lists the task")
SL = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
A.put(B + f"/api/lists/{SL}/members", json={"user_id": EVE, "role": "edit"})
T2 = A.post(B + "/api/tasks", json={"title": "Call the plumber", "list_id": SL}).json()
A.post(B + f"/api/tasks/{T2['id']}/contacts", json={"contact_id": C2["id"], "kind": "responsible"})
check(Ev.get(B + "/api/state").json()["tcontacts"] == {} and Ev.get(B + f"/api/contacts/{C2['id']}").status_code == 404,
      "Eve sees the shared task, not the contact (she does not see the address book)")
check(Ev.post(B + f"/api/tasks/{T2['id']}/contacts", json={"contact_id": C2["id"]}).status_code == 404, "… and cannot link it")
check(A.delete(B + f"/api/tasks/{T1['id']}/contacts/{C1['id']}").ok and not A.get(B + "/api/state").json()["tcontacts"].get(str(T1["id"])), "unlinked")
# contacts as attendees
r = A.post(B + "/api/events", json={"title": "Offer meeting", "cal_id": W["id"], "start": f"{D}T11:00", "attendees": [{"contact_id": C1["id"]}]})
check(r.ok and r.json()["attendees"][0]["email"] == "erika@example.org" and r.json()["attendees"][0]["name"] == "Erika Mustermann", "a contact as an attendee")
check([e["event_id"] for e in A.get(B + f"/api/contacts/{C1['id']}").json()["events"]] == [r.json()["id"]], "the contact lists the event")
check(Bo.post(B + "/api/events", json={"title": "x", "start": f"{D}T11:00", "attendees": [{"contact_id": 99999}]}).status_code == 404, "an unknown contact: 404")
# birthdays as tasks (module Family)
BL = A.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
r = A.patch(B + f"/api/books/{BK}", json={"birthdays_list_id": BL})
check(r.ok and r.json()["birthdays_list_id"] == BL, "the address book's birthday list")
bt = [t for t in A.get(B + "/api/state").json()["tasks"] if t["list_id"] == BL]
check(len(bt) == 1 and bt[0]["title"] == "Birthday: Erika Mustermann" and bt[0]["due"][5:] == "08-12" and bt[0]["fam"]["year"] == 1964,
      f"Erika's birthday became a yearly task {[(t['title'], t['due']) for t in bt]}")
A.patch(B + f"/api/contacts/{C1['id']}", json={"bday": "--09-01", "anniversary": "2001-06-20"})
bt = sorted((t["title"], t["due"][5:], (t["fam"] or {}).get("year")) for t in A.get(B + "/api/state").json()["tasks"] if t["list_id"] == BL)
check(bt == [("Anniversary: Erika Mustermann", "06-20", 2001), ("Birthday: Erika Mustermann", "09-01", None)], f"a new date + an anniversary {bt}")
check(Bo.patch(B + f"/api/books/{BK}", json={"birthdays_list_id": BL}).status_code == 403, "only the owner chooses the list")
# vCard import / export
VCF = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Doe;Jane;;;\r\nFN:Jane Doe\r\nEMAIL;TYPE=INTERNET:jane@example.com\r\nUID:imp-1\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Max Power\r\nTEL;VALUE=uri;TYPE=cell:tel:+49-30-1234\r\nUID:imp-2\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nVERSION:3.0\r\nN:;;;;\r\nEND:VCARD\r\n")
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("c.vcf", VCF, "text/vcard")})
check(r.ok and r.json()["created"] == 2 and r.json()["errors"] == 1, f"vCard import: two contacts, the card without a name is not readable {r.text[:200]}")
check(A.post(B + f"/api/books/{BK}/import", files={"file": ("c.vcf", VCF, "text/vcard")}).json()["created"] == 0, "imported twice: no doubles")
mp = [x for x in A.get(B + "/api/contacts", params={"q": "max"}).json()["items"]]
check(mp and mp[0]["phone"] == "+49-30-1234", "a tel: URI of vCard 4 becomes the number")
r = A.get(B + f"/api/books/{BK}/export.vcf")
check(r.ok and r.text.count("BEGIN:VCARD") == 4 and "UID:imp-2" in r.text, "export: every card")

# ================================================================== CardDAV (iOS Contacts, DAVx5, Thunderbird)
AB = f"/dav/addressbooks/alice/b{BK}/"
r = iph.req("PROPFIND", "/dav/addressbooks/alice/", '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop>'
            '<d:resourcetype/><d:displayname/><card:supported-address-data/><d:current-user-privilege-set/><d:sync-token/></d:prop></d:propfind>', Depth="1")
abh = ms(r.text)[0]
check(r.status_code == 207 and AB in abh and abh[AB]["{DAV:}resourcetype"].find("{urn:ietf:params:xml:ns:carddav}addressbook") is not None
      and len(abh[AB]["{urn:ietf:params:xml:ns:carddav}supported-address-data"]) == 2, "the address book home: the book, vCard 3 + 4")
r = iph.req("REPORT", AB, '<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:"><d:sync-token/><d:sync-level>1</d:sync-level><d:prop><d:getetag/>'
            '</d:prop></d:sync-collection>', Depth="1")
cards0, _, ctok = ms(r.text)
check(len(cards0) == 4 and ctok, f"sync-collection: four cards {len(cards0)}")
PHOTO = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 60).decode()
IOSV = ("BEGIN:VCARD\r\nVERSION:3.0\r\nPRODID:-//Apple Inc.//iPhone OS 18.0//EN\r\nN:Appleseed;Johnny;;;\r\nFN:Johnny Appleseed\r\nORG:Apple;Garden;\r\n"
        "item1.EMAIL;type=INTERNET;type=pref:johnny@example.com\r\nitem1.X-ABLabel:_$!<Other>!$_\r\nTEL;type=CELL;type=VOICE;type=pref:+1 555 0100\r\n"
        "item2.ADR;type=HOME;type=pref:;;1 Infinite Loop;Cupertino;CA;95014;United States\r\nitem2.X-ABADR:us\r\n"
        "BDAY;X-APPLE-OMIT-YEAR=1604:1604-03-04\r\nX-SOCIALPROFILE;type=twitter:x.com/johnny\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{PHOTO}\r\nUID:IOS-CARD-1\r\nEND:VCARD\r\n")
r = iph.req("PUT", AB + "IOS-CARD-1.vcf", IOSV, **{"Content-Type": "text/vcard; charset=utf-8", "If-None-Match": "*"})
check(r.status_code == 201, f"iOS card PUT {r.status_code} {r.text[:200]}")
jc = [x for x in A.get(B + "/api/contacts", params={"q": "johnny"}).json()["items"]]
cj = A.get(B + f"/api/contacts/{jc[0]['id']}").json() if jc else {}
check(cj.get("fn") == "Johnny Appleseed" and cj["org"] == "Apple" and cj["dept"] == "Garden" and cj["bday"] == "--03-04" and cj["photo"].startswith("data:image/jpeg;base64,")
      and cj["emails"][0]["value"] == "johnny@example.com" and cj["addresses"][0]["city"] == "Cupertino", f"mapped: org / dept, birthday without the year, photo, e-mail, address {cj}")
r = iph.req("GET", AB + "IOS-CARD-1.vcf")
check(r.ok and "item1.EMAIL" in r.text and "item1.X-ABLabel:_$!<Other>!$_" in r.text and "X-SOCIALPROFILE;type=twitter:x.com/johnny" in r.text
      and "BDAY;X-APPLE-OMIT-YEAR=1604:1604-03-04" in r.text and "PHOTO;ENCODING=b;TYPE=JPEG:" in r.text and "item2.X-ABADR:us" in r.text,
      "GET: the labels (item groups), the social profile, the birthday, the photo come back")
cet = r.headers["ETag"]
A.patch(B + f"/api/contacts/{cj['id']}", json={"note": "Planted trees"})
check(iph.req("PUT", AB + "IOS-CARD-1.vcf", IOSV, **{"Content-Type": "text/vcard", "If-Match": cet}).status_code == 412, "changed in the app meanwhile: 412")
r = iph.req("REPORT", AB, '<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>%s</d:sync-token><d:sync-level>1</d:sync-level>'
            '<d:prop><d:getetag/></d:prop></d:sync-collection>' % ctok, Depth="1")
ch, gone, _ = ms(r.text)
check(list(ch) == [AB + "IOS-CARD-1.vcf"] and not gone, f"sync: only Johnny {list(ch)}")
V4 = "BEGIN:VCARD\r\nVERSION:4.0\r\nKIND:org\r\nFN:Bakery Ltd\r\nORG:Bakery Ltd\r\nANNIVERSARY:20100501\r\nUID:v4-1\r\nTEL;TYPE=work:+49 30 5555\r\nEND:VCARD\r\n"
check(dx.req("PUT", AB + "v4-1.vcf", V4, **{"Content-Type": "text/vcard"}).status_code == 201, "a vCard 4.0 (DAVx5)")
r = dx.req("REPORT", AB, '<?xml version="1.0"?><card:addressbook-multiget xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
           f'<card:address-data content-type="text/vcard" version="3.0"/></d:prop><d:href>{AB}v4-1.vcf</d:href></card:addressbook-multiget>', Depth="1")
ad = txt(ms(r.text)[0][AB + "v4-1.vcf"]["{urn:ietf:params:xml:ns:carddav}address-data"])
check("VERSION:3.0" in ad and "X-ANNIVERSARY:2010-05-01" in ad, f"multiget in version 3.0: converted {ad[:200]}")
r = dx.req("GET", AB + "v4-1.vcf")
check("VERSION:4.0" in r.text and "KIND:org" in r.text and "ANNIVERSARY:20100501" in r.text, "GET: its own version 4.0")
r = tb.req("REPORT", AB, '<?xml version="1.0"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
           '</d:prop><card:filter><card:prop-filter name="EMAIL"><card:text-match collation="i;unicode-casemap" match-type="contains">example.com'
           '</card:text-match></card:prop-filter></card:filter></card:addressbook-query>', Depth="1")
hit = sorted(ms(r.text)[0])
check(hit == sorted([AB + "IOS-CARD-1.vcf", AB + "imp-1.vcf"]), f"addressbook-query: e-mail contains example.com {hit}")
INJ = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Inject\r\nUID:inj-1\\nPHOTO;VALUE=uri:https://tracker.example/x\r\nEND:VCARD\r\n"
check(iph.req("PUT", AB + "inj-1.vcf", INJ, **{"Content-Type": "text/vcard"}).status_code == 201
      and "\r\nPHOTO;VALUE=uri" not in iph.req("GET", AB + "inj-1.vcf").text, "a line break in a UID never becomes a property")
iph.req("DELETE", AB + "inj-1.vcf")
t0_ = time.time()
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("x.vcf", "BEGIN:VCARD\n" * 40000, "text/vcard")})
check(time.time() - t0_ < 5 and r.ok and r.json()["created"] == 0, f"40000 cards without an end: answered at once ({time.time() - t0_:.1f} s)")
GRP = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Friends\r\nFN:Friends\r\nX-ADDRESSBOOKSERVER-KIND:group\r\nX-ADDRESSBOOKSERVER-MEMBER:urn:uuid:IOS-CARD-1\r\nUID:grp-1\r\nEND:VCARD\r\n"
check(iph.req("PUT", AB + "grp-1.vcf", GRP, **{"Content-Type": "text/vcard"}).status_code == 201 and "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:IOS-CARD-1" in iph.req("GET", AB + "grp-1.vcf").text,
      "an Apple group card is kept as it came")
check(not [x for x in A.get(B + "/api/contacts", params={"q": "friends"}).json()["items"]], "… and is no contact in the list")
r = bob.req("PROPFIND", "/dav/addressbooks/bob/", PF_ETAG, Depth="1")
check(f"/dav/addressbooks/bob/b{BK}/" in ms(r.text)[0], "Bob's address book home: the shared book")
check(bob.req("PUT", f"/dav/addressbooks/bob/b{BK}/b.vcf", V4.replace("v4-1", "b-1"), **{"Content-Type": "text/vcard"}).status_code == 403, "view only: PUT 403")
check(eve.req("GET", AB.replace("alice", "eve") + "IOS-CARD-1.vcf").status_code == 404, "Eve: the book does not exist for her")
check(iph.req("PUT", AB + "bad.vcf", "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:x\r\nEND:VCARD\r\n", **{"Content-Type": "text/vcard"}).status_code == 400, "a card without a UID: 400")
check(iph.req("DELETE", AB + "v4-1.vcf").status_code == 204 and not A.get(B + "/api/contacts", params={"q": "bakery"}).json()["items"], "DELETE a card")

# ================================================================== API v1 + scopes + OpenAPI
def tok(scopes):
    r = A.post(B + "/api/me/tokens", json={"name": "t" + str(time.time()), "scopes": scopes})
    return {"Authorization": "Bearer " + r.json()["token"]}


V = B + "/api/v1"
rd, cal, con, legacy = tok(["read"]), tok(["read", "calendar"]), tok(["read", "contacts"]), tok(["read", "write"])
check(requests.get(V + "/events", headers=rd, params={"from": str(D), "to": str(D)}).status_code == 403
      and requests.get(V + "/contacts", headers=rd).status_code == 403, "read alone: no events, no contacts")
r = requests.get(V + "/events", headers=cal, params={"from": str(D), "to": str(D)})
check(r.ok and {x["eid"] for x in r.json()["data"]} >= {FD["id"], NY["id"]} and r.json()["next_cursor"] is None, "scope calendar: the occurrences")
check(requests.get(V + "/contacts", headers=cal).status_code == 403, "calendar is not contacts")
r = requests.get(V + "/contacts", headers=con, params={"q": "erika"})
check(r.ok and r.json()["data"][0]["fn"] == "Erika Mustermann" and r.json()["total"] == 1, "scope contacts: search")
check(requests.get(V + "/contacts", headers=legacy).status_code == 403 and requests.get(V + "/event-calendars", headers=legacy).ok,
      "an old write token: events yes, contacts no (sensitive)")
r = requests.post(V + "/events", headers=cal, json={"title": "From the API", "start": f"{D}T08:00", "cal_id": W["id"]})
check(r.status_code == 201 and r.json()["title"] == "From the API", "POST /events")
EV = r.json()["id"]
check(requests.patch(V + f"/events/{EV}", headers=cal, json={"location": "Here"}).json()["location"] == "Here", "PATCH /events/{id}")
check(requests.post(V + f"/events/{EV}/prep-task", headers=cal, json={}).status_code == 403, "prep-task also needs tasks:write")
check(requests.post(V + f"/events/{EV}/prep-task", headers=tok(["read", "calendar", "tasks:write"]), json={}).status_code == 201, "… with it: 201")
check(requests.delete(V + f"/events/{EV}", headers=cal).status_code == 204 and requests.post(V + f"/events/{EV}/restore", headers=cal).ok, "DELETE + restore")
r = requests.post(V + f"/event-calendars/{IMP['id']}/import", headers=cal, json={"ics": GOOGLE})
check(r.ok and r.json()["updated"] == 3, "import over the API: the same file updates")
check("BEGIN:VCALENDAR" in requests.get(V + f"/event-calendars/{IMP['id']}/export", headers=cal).json()["ics"], "export over the API")
check(requests.put(V + f"/event-calendars/{P['id']}/members/{EVE}", headers=cal, json={"role": "view"}).ok and Ev.get(B + f"/api/events/{E1['id']}").ok,
      "share over the API")
r = requests.post(V + "/contacts", headers=con, json={"fn": "API person", "emails": [{"value": "api@example.org"}]})
check(r.status_code == 201, "POST /contacts")
check(requests.post(V + f"/tasks/{T1['id']}/contacts", headers=con, json={"contact_id": r.json()["id"]}).status_code == 403, "linking also needs tasks:write")
check(requests.get(V + "/address-books", headers=con).json()["data"][0]["id"] == BK, "GET /address-books")
check("BEGIN:VCARD" in requests.get(V + f"/address-books/{BK}/export", headers=con).json()["vcf"], "vCard export over the API")
spec = requests.get(V + "/openapi.json", headers=rd).json()
sc = {(p, m): o["x-kalmido-scope"] for p, ms_ in spec["paths"].items() for m, o in ms_.items()}
check(sc[("/events", "get")] == "calendar" and sc[("/contacts", "get")] == "contacts" and sc[("/contacts/{id}", "delete")] == "contacts"
      and sc[("/event-calendars/{id}/members/{user_id}", "put")] == "calendar", "OpenAPI: the scopes")
r = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper"})
check(r.ok and "contacts" not in r.json()["effective_scopes"] and "calendar" not in r.json()["effective_scopes"], f"a new agent: neither calendar nor contacts {r.json().get('effective_scopes')}")

# ================================================================== module switches
Bo.patch(B + "/api/settings", json={"features": "cal,comments"})
check(Bo.post(B + "/api/events", json={"title": "x", "start": f"{D}T10:00"}).status_code == 409 and Bo.get(B + "/api/contacts").status_code == 409,
      "modules off: events refused (409), contacts refused")
st = Bo.get(B + "/api/state").json()
check(st["evcals"] == [] and st["books"] == [] and st["tcontacts"] == {}, "modules off: nothing in the state")
r = bob.req("PROPFIND", "/dav/calendars/bob/", PF_HOME, Depth="1")
check(not [h for h in ms(r.text)[0] if "/e" in h.split("/")[-2][:1]], "modules off: no event calendars over CalDAV")
r = bob.req("PROPFIND", "/dav/addressbooks/bob/", PF_ETAG, Depth="1")
check(len(ms(r.text)[0]) == 1, "modules off: an empty address book home")
Bo.patch(B + "/api/settings", json={"features": "cal,comments,events,contacts"})

# ================================================================== the data export, #671
ex = A.get(B + "/api/export.json").json()
check(len(ex.get("events", [])) >= 5 and len(ex.get("contacts", [])) >= 4 and ex.get("event_calendars"), "the data export has my events and contacts")
out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app; print(app.local_day('garbage'), app.local_day(''), app.local_day('2026-10-05T23:30:00+00:00'))"],
                     capture_output=True, text=True).stdout.strip().splitlines()[-1]
check(out == "None None 2026-10-06", f"#671: one tolerant local_day {out}")

# ================================================================== the family events of 2.19 become events (migration on start)
FL = A.post(B + "/api/lists", json={"name": "Family", "family": ""}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
D7 = today + timedelta(days=7)
FT = A.post(B + "/api/tasks", json={"title": "Zoo trip", "list_id": FL, "due": str(D7), "due_time": "10:00", "duration": 180, "reminders": "60"}).json()
r = A.patch(B + f"/api/tasks/{FT['id']}", json={"people": [BOB]})
check(r.ok, "a family event of 2.19 (a task with someone who comes along) " + r.text[:200])
dbx("DELETE FROM settings WHERE key='migr_ev221'")
subprocess.run(["docker", "restart", CT], check=True, capture_output=True)
until(healthy, 40)
A = sess("alice")
row = dbx("SELECT id, title, start, end, task_id, reminders FROM events WHERE task_id=?", (FT["id"],))
check(row and row[0][1] == "Zoo trip" and row[0][2] == f"{D7}T10:00" and row[0][3] == f"{D7}T13:00" and row[0][5] == "60",
      f"migrated: an event with the time, 3 hours, the reminder {row}")
if row:
    e = A.get(B + f"/api/events/{row[0][0]}").json()
    check([(a["user_id"], a["partstat"]) for a in e["attendees"]] == [(BOB, "accepted")] and e["task_id"] == FT["id"], "Bob is invited (accepted), the task is linked")
t = [x for x in A.get(B + "/api/state").json()["tasks"] if x["id"] == FT["id"]]
check(t and t[0]["status"] == 2, "the task is done (it is the event now, nothing comes twice)")
check(dbx("SELECT kind FROM activity WHERE task_id=? AND kind='event'", (FT["id"],)), "its history says so")
subprocess.run(["docker", "restart", CT], check=True, capture_output=True)
until(healthy, 40)
check(len(dbx("SELECT id FROM events WHERE task_id=?", (FT["id"],))) == 1, "once only (a second start migrates nothing)")

print(f"\np2210 api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
