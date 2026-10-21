#!/usr/bin/env python3
"""2.155.0 A tests: CalDAV writes from a device (#2074 #2079). Invented names only, own test calendars.
 - #2074: answering an invitation in the phone's calendar = a PUT of the invitation with a changed PARTSTAT of the own
   ATTENDEE: only that answer is taken (like the answer in the app), a changed title / time / another person's answer is
   ignored without an error, If-Match is checked, GET + the ETag + the sync token show the new answer, a new resource in the
   invitations stays refused (403), DELETE of an invitation = declined, the privileges offer write-content (no bind)
 - #2079: MKCALENDAR (and extended MKCOL) creates an own calendar like "new calendar" in the app: name, colour, description
   from the body, 201 + Location, it shows in PROPFIND of the home and in the app under the client's address, takes events;
   twice = 405; only tasks (VTODO) / reserved names = 403; deleting it over CalDAV stays refused; a person without an
   organisation gets it in the private space (freelancer-matrix: pim)
usage: p2155_a_caldav_test.py <datadir>      (a fresh container; P2155A_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
DAY = "2026-11-12"
PF = '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/>' \
     '<d:displayname/><d:current-user-privilege-set/><d:sync-token/></d:prop></d:propfind>'
MKCAL = ('<?xml version="1.0" encoding="UTF-8"?><C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" '
         'xmlns:A="http://apple.com/ns/ical/"><D:set><D:prop><D:displayname>{name}</D:displayname>'
         '<A:calendar-color>#FF2968FF</A:calendar-color><C:calendar-description>Trips and days off</C:calendar-description>'
         '<C:supported-calendar-component-set>{comps}</C:supported-calendar-component-set></D:prop></D:set></C:mkcalendar>')
EV = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//Device//EN", "BEGIN:VEVENT", "UID:{uid}",
                  "DTSTAMP:20261101T100000Z", "DTSTART:20261113T090000Z", "DTEND:20261113T100000Z", "SUMMARY:{title}",
                  "END:VEVENT", "END:VCALENDAR", ""])


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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Dav:
    def __init__(self, s, user):
        r = s.post(B + "/api/me/app-passwords", json={"name": "Phone"})
        assert r.ok, r.text
        self.user, self.pw = user, r.json()["password"]

    def req(self, m, path, data=None, **hd):
        h = {"X-Forwarded-Proto": "https", **hd}
        if isinstance(data, str):
            data = data.encode("utf-8")
        return requests.request(m, B + path, auth=(self.user, self.pw), data=data, headers=h, allow_redirects=False)


def hrefs(text):
    return re.findall(r"<D:href>([^<]+)</D:href>", text)


def etag_of(r):
    return r.headers.get("ETag", "")


def att(s, eid, uid_):
    r = s.get(B + f"/api/events/{eid}")
    return next((a["partstat"] for a in (r.json().get("attendees") or []) if a.get("user_id") == uid_), None) if r.ok else None


def answered(text, uid_, ps):
    """text (the GET of an invitation) with the ATTENDEE line of uid_ set to PARTSTAT ps, and a changed title."""
    out = []
    for line in text.replace("\r\n ", "").split("\r\n"):
        if line.startswith("ATTENDEE") and f"urn:kalmido:user:{uid_}" in line:
            line = re.sub(r"PARTSTAT=[A-Z-]+", f"PARTSTAT={ps}", line)
        elif line.startswith("SUMMARY"):
            line = "SUMMARY:Changed on the phone"
        out.append(line)
    return "\r\n".join(out)


if not os.environ.get("P2155A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,events,contacts"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
S = {u: sess(u) for u in uid}
for s_ in S.values():
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,events,contacts"})
TEAM = A.post(B + "/api/evcals", json={"name": "Team", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": TEAM, "title": "Planning", "start": f"{DAY}T10:00", "end": f"{DAY}T11:00",
                                    "attendees": [{"user_id": uid["bob"]}, {"user_id": uid["carol"]}]})
assert r.status_code == 201, r.text
E1 = r.json()["id"]

# ================================================================== #2074: answers from the phone
bob = Dav(S["bob"], "bob")
INV = "/dav/calendars/bob/inv/"
r = bob.req("PROPFIND", INV, PF, Depth="1")
check(r.status_code == 207, f"bob's invitations collection {r.status_code}")
items = [h for h in hrefs(r.text) if h.endswith(".ics")]
check(len(items) == 1, f"one invitation {items}")
coll_part = r.text.split("</D:response>")[0]
check("<D:write-content/>" in coll_part and "<D:bind/>" not in coll_part and "<D:read/>" in coll_part,
      f"#2074: the invitations offer write-content, no bind {coll_part[-400:]}")
tok0 = (re.findall(r"<D:sync-token>([^<]+)</D:sync-token>", r.text) or [""])[0]
H1 = items[0] if items else INV + "none.ics"
g = bob.req("GET", H1)
check(g.status_code == 200 and "PARTSTAT=NEEDS-ACTION" in g.text, "the invitation without an answer")
old_etag = etag_of(g)
r = bob.req("PUT", H1, answered(g.text, uid["bob"], "ACCEPTED"), **{"Content-Type": "text/calendar; charset=utf-8", "If-Match": old_etag})
check(r.status_code == 204, f"#2074: PUT with PARTSTAT=ACCEPTED: 204 ({r.status_code} {r.text[:160]})")
check(att(A, E1, uid["bob"]) == "accepted", "#2074: the app shows bob's answer (the organiser sees accepted)")
check(A.get(B + f"/api/events/{E1}").json()["title"] == "Planning", "#2074: the changed title is ignored")
g2 = bob.req("GET", H1)
mine = [x for x in g2.text.replace("\r\n ", "").split("\r\n") if x.startswith("ATTENDEE") and f"urn:kalmido:user:{uid['bob']}" in x]
check(g2.status_code == 200 and mine and "PARTSTAT=ACCEPTED" in mine[0] and "SUMMARY:Planning" in g2.text,
      f"#2074: GET shows the new answer and the stored title {mine}")
check(etag_of(g2) and etag_of(g2) != old_etag, "#2074: a new ETag after the answer")
r = bob.req("PROPFIND", INV, PF, Depth="1")
tok1 = (re.findall(r"<D:sync-token>([^<]+)</D:sync-token>", r.text) or [""])[0]
check(tok1 and tok1 != tok0, "#2074: a new sync token after the answer")
r = bob.req("PUT", H1, answered(g.text, uid["bob"], "DECLINED"), **{"Content-Type": "text/calendar", "If-Match": old_etag})
check(r.status_code == 412 and att(A, E1, uid["bob"]) == "accepted", f"#2074: a stale If-Match: 412, nothing changed ({r.status_code})")
r = bob.req("PUT", H1, answered(g2.text, uid["bob"], "DECLINED"), **{"Content-Type": "text/calendar", "If-Match": etag_of(g2)})
check(r.status_code == 204 and att(A, E1, uid["bob"]) == "declined", f"#2074: PARTSTAT=DECLINED ({r.status_code})")
g3 = bob.req("GET", H1)
r = bob.req("PUT", H1, answered(g3.text, uid["carol"], "ACCEPTED"), **{"Content-Type": "text/calendar"})
check(r.status_code == 204 and att(A, E1, uid["carol"]) == "needs-action" and att(A, E1, uid["bob"]) == "declined",
      f"#2074: another attendee's answer is never set ({r.status_code})")
r = bob.req("PUT", H1, answered(g3.text, uid["bob"], "TENTATIVE"), **{"Content-Type": "text/calendar"})
check(r.status_code == 204 and att(A, E1, uid["bob"]) == "tentative", "#2074: PARTSTAT=TENTATIVE = maybe")
r = bob.req("PUT", INV + "new-one.ics", EV.format(uid="new-one", title="Mine"), **{"Content-Type": "text/calendar"})
check(r.status_code == 403, f"#2074: a new resource in the invitations: still 403 ({r.status_code})")
check(not dbx("SELECT 1 FROM events WHERE uid='new-one'"), "#2074: ... nothing stored")
r = bob.req("DELETE", H1)
check(r.status_code == 204 and att(A, E1, uid["bob"]) == "declined", f"#2074: DELETE of an invitation = declined ({r.status_code})")
r = bob.req("DELETE", H1.rsplit("/", 1)[0] + "/nope-2155.ics")  # 2.155.0 review: an unknown invitation = 404, not 403
check(r.status_code == 404, f"#2074: DELETE of an unknown invitation = 404 ({r.status_code})")
check(A.get(B + f"/api/events/{E1}").ok and not dbx("SELECT deleted_at FROM events WHERE id=?", (E1,))[0][0],
      "#2074: ... the event itself stays")
r = A.post(B + "/api/events", json={"cal_id": TEAM, "title": "Owner's own", "start": f"{DAY}T12:00", "end": f"{DAY}T13:00"})
A.put(B + f"/api/evcals/{TEAM}/members", json={"user_id": uid["carol"], "role": "view"})
carol = Dav(S["carol"], "carol")
r = carol.req("PUT", f"/dav/calendars/carol/e{TEAM}/x-1.ics", EV.format(uid="x-1", title="X"), **{"Content-Type": "text/calendar"})
check(r.status_code == 403, f"a view-only calendar: a new event still 403 ({r.status_code})")

# ================================================================== #2079: MKCALENDAR
alice = Dav(A, "alice")
NEW = "/dav/calendars/alice/3F2A-77B1-CAL/"
r = alice.req("MKCALENDAR", NEW, MKCAL.format(name="Holidays", comps='<C:comp name="VEVENT"/>'), **{"Content-Type": "application/xml"})
check(r.status_code == 201 and r.headers.get("Location", "").endswith(NEW), f"#2079: MKCALENDAR 201 + Location ({r.status_code} {r.text[:160]})")
cals = {c["name"]: c for c in A.get(B + "/api/evcals").json()["items"]}
hc = cals.get("Holidays") or {}
check(hc.get("color") == "#ff2968" and hc.get("description") == "Trips and days off" and hc.get("role") == "owner",
      f"#2079: in the app with colour + description {hc}")
check(hc.get("org_id") == ORG, f"#2079: in the person's workspace like a new calendar in the app ({hc.get('org_id')})")
r = alice.req("PROPFIND", "/dav/calendars/alice/", PF, Depth="1")
check(NEW in hrefs(r.text) and f"/dav/calendars/alice/e{hc.get('id')}/" not in hrefs(r.text), "#2079: PROPFIND of the home lists it under the client's address")
home_part = r.text.split("</D:response>")[0]
check("<D:bind/>" in home_part, "#2079: the home offers bind")
r = alice.req("MKCALENDAR", NEW, MKCAL.format(name="Again", comps='<C:comp name="VEVENT"/>'))
check(r.status_code == 405 and "Again" not in {c["name"] for c in A.get(B + "/api/evcals").json()["items"]}, f"#2079: twice: 405 ({r.status_code})")
r = alice.req("PUT", NEW + "trip-1.ics", EV.format(uid="trip-1", title="Trip"), **{"Content-Type": "text/calendar", "If-None-Match": "*"})
check(r.status_code == 201 and alice.req("GET", NEW + "trip-1.ics").status_code == 200, f"#2079: the new calendar takes events ({r.status_code})")
check(dbx("SELECT cal_id FROM events WHERE uid='trip-1'") == [(hc.get("id"),)], "#2079: ... stored in that calendar")
r = alice.req("PROPFIND", NEW, PF, Depth="0")
tok = (re.findall(r"<D:sync-token>([^<]+)</D:sync-token>", r.text) or [""])[0]
rep = ('<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>' + tok + '</d:sync-token><d:sync-level>1</d:sync-level>'
       '<d:prop><d:getetag/></d:prop></d:sync-collection>')
check(alice.req("REPORT", NEW, rep, Depth="1").status_code == 207, "#2079: sync-collection with its token")
r = alice.req("MKCALENDAR", "/dav/calendars/alice/todo-1/", MKCAL.format(name="Todos", comps='<C:comp name="VTODO"/>'))
check(r.status_code == 403 and "supported-calendar-component" in r.text, f"#2079: only tasks: 403 (lists are made in the app) ({r.status_code})")
r = alice.req("MKCALENDAR", "/dav/calendars/alice/e99999/", "")
check(r.status_code == 403, f"#2079: a reserved name: 403 ({r.status_code})")
TL = A.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
check(alice.req("MKCALENDAR", f"/dav/calendars/alice/{TL}/", "").status_code == 405, "#2079: a task list's address: 405")
check(alice.req("MKCALENDAR", f"/dav/calendars/alice/e{TEAM}/", "").status_code == 405, "#2079: an event calendar's address: 405")
r = alice.req("MKCALENDAR", "/dav/calendars/bob/abc/", "")
check(r.status_code in (403, 404), f"#2079: never in another person's home ({r.status_code})")
r = alice.req("MKCOL", "/dav/calendars/alice/ext-1/", '<?xml version="1.0"?><D:mkcol xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
              '<D:set><D:prop><D:resourcetype><D:collection/><C:calendar/></D:resourcetype><D:displayname>Extended</D:displayname>'
              '</D:prop></D:set></D:mkcol>')
check(r.status_code == 201 and "Extended" in {c["name"] for c in A.get(B + "/api/evcals").json()["items"]}, f"#2079: extended MKCOL ({r.status_code})")
check(alice.req("MKCOL", "/dav/calendars/alice/plain-1/", "").status_code == 403, "#2079: a plain MKCOL: 403")
r = alice.req("MKCALENDAR", "/dav/calendars/alice/empty-1/", "")
check(r.status_code == 201 and dbx("SELECT name FROM ev_cals WHERE owner_id=? AND dav_name='empty-1'", (ALICE,)) == [("Calendar",)],
      f"#2079: no body = 'Calendar' ({r.status_code})")
check(alice.req("DELETE", NEW).status_code == 403 and "Holidays" in {c["name"] for c in A.get(B + "/api/evcals").json()["items"]},
      "#2079: deleting a calendar over CalDAV stays refused")
A.put(B + f"/api/evcals/{hc.get('id')}/members", json={"user_id": uid["bob"], "role": "view"})
r = bob.req("PROPFIND", "/dav/calendars/bob/", PF, Depth="1")
check(f"/dav/calendars/bob/e{hc.get('id')}/" in hrefs(r.text) and NEW.replace("alice", "bob") not in hrefs(r.text),
      "#2079: shared with bob it has the usual address there")
S["bob"].patch(B + "/api/settings", json={"features": "cal,comments,contacts"})
r = bob.req("MKCALENDAR", "/dav/calendars/bob/b-1/", "")
check(r.status_code == 403, f"#2079: events switched off: 403 ({r.status_code})")

# ================================================================== a person without an organisation (P4)
# freelancer-matrix: pim
FID, Fr = freelancer(B, A, "frida")
fr = Dav(Fr, "frida")
r = fr.req("MKCALENDAR", "/dav/calendars/frida/F1/", MKCAL.format(name="Studio", comps='<C:comp name="VEVENT"/><C:comp name="VTODO"/>'))
check(r.status_code == 201, f"P4: frida creates a calendar from her phone ({r.status_code} {r.text[:160]})")
fc = {c["name"]: c for c in Fr.get(B + "/api/evcals").json()["items"]}.get("Studio") or {}
check(fc.get("role") == "owner" and fc.get("org_id") is None, f"P4: ... in her private space {fc}")
lo, hi = sorted((ALICE, FID))
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-21T10:00:00.000Z')", (lo, hi))
HOME = A.post(B + "/api/evcals", json={"name": "Home", "org_id": None}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": HOME, "title": "Studio visit", "start": f"{DAY}T15:00", "end": f"{DAY}T16:00",
                                    "attendees": [{"user_id": FID}]})
check(r.status_code == 201, f"P4: alice invites frida from a private calendar {r.status_code} {r.text[:160]}")
E2 = r.json().get("id")
r = fr.req("PROPFIND", "/dav/calendars/frida/inv/", PF, Depth="1")
fi = [h for h in hrefs(r.text) if h.endswith(".ics")]
if fi:
    g = fr.req("GET", fi[0])
    r = fr.req("PUT", fi[0], answered(g.text, FID, "ACCEPTED"), **{"Content-Type": "text/calendar", "If-Match": etag_of(g)})
    check(r.status_code == 204 and att(A, E2, FID) == "accepted", f"P4: frida accepts from her phone ({r.status_code})")
else:
    check(False, f"P4: frida's invitations collection {r.status_code} {r.text[:200]}")

print(f"p2155_a_caldav: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
