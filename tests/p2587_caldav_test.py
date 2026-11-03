#!/usr/bin/env python3
# kalmido-suite:
"""2.383.0 tests (#2587): the rest of the calendar work of 2.155. Invented names only, own test calendars.
 - free-busy-query (RFC 4791 7.10) on an event collection: 200 + one VFREEBUSY with the busy times of the range (busy,
   timed, not cancelled; an event shown as free, an all-day one and a cancelled one stay out), in the invitations only the
   accepted dates; without a time-range 400; the collection names the report in supported-report-set
 - an answer to ONE date of a series from the phone (an override VEVENT with RECURRENCE-ID and the own PARTSTAT) is kept
   for that date only: the series keeps its answer, the calendar view, the availability bar and free-busy-query follow the
   date's answer, GET shows it back; a PUT without the date makes it follow the series again
 - the own answer per PUT in a calendar one may edit is taken (before: the own ATTENDEE line was dropped and the PUT took
   the person off the event)
 - the organiser's phone writing the series back keeps such a date as no changed occurrence of the series
 - a PUT to an invitation whose changes are ignored (a changed title) gets a new ETag, so the phone loads the stored event
 - a person without an organisation answers one date of a series too and asks free-busy-query on her own calendar
   (freelancer-matrix: pim)
usage: p2587_caldav_test.py <datadir>      (a fresh container; P2587_NOSTART=1 = the server already runs)"""
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = {"Content-Type": "text/calendar; charset=utf-8"}
PF = '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/>' \
     '<d:supported-report-set/><d:sync-token/></d:prop></d:propfind>'


def fbq(start, end):
    tr_ = f'<C:time-range start="{start}" end="{end}"/>' if start or end else ""
    return f'<?xml version="1.0" encoding="utf-8"?><C:free-busy-query xmlns:C="urn:ietf:params:xml:ns:caldav">{tr_}</C:free-busy-query>'


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


def unfold(text):
    return text.replace("\r\n ", "").split("\r\n")


def blocks(text):
    """The VEVENT blocks of calendar data (unfolded lines)."""
    out, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = []
        if cur is not None:
            cur.append(line)
        if line == "END:VEVENT" and cur is not None:
            out.append(cur)
            cur = None
    return out


def busy_lines(text):
    return [x for x in unfold(text) if x.startswith("FREEBUSY")]


def set_ps(lines, uid_, ps):
    return [re.sub(r"PARTSTAT=[A-Z-]+", f"PARTSTAT={ps}", x) if x.startswith("ATTENDEE") and f"urn:kalmido:user:{uid_}" in x else x
            for x in lines]


def cal_of(vevents):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//Device//EN"] + [x for b in vevents for x in b]
                       + ["END:VCALENDAR", ""])


def override(master, rid_day, uid_, ps, title=None):
    """An override VEVENT of master for the date rid_day (YYYYMMDD, same time) with uid_'s PARTSTAT ps."""
    st = next(x for x in master if x.startswith("DTSTART"))
    en = next(x for x in master if x.startswith("DTEND"))
    m = re.match(r"(DTSTART[^:]*):(\d{8})(T\d{6}Z?)?", st)
    me_ = re.match(r"(DTEND[^:]*):(\d{8})(T\d{6}Z?)?", en)
    out = ["BEGIN:VEVENT"]
    for x in master[1:-1]:
        if x.startswith(("RRULE", "EXDATE", "DTSTART", "DTEND", "BEGIN:VALARM", "END:VALARM", "TRIGGER", "ACTION")):
            continue
        if x.startswith("SUMMARY") and title:
            x = "SUMMARY:" + title
        out.append(x)
    out += [f"RECURRENCE-ID{m.group(1)[7:]}:{rid_day}{m.group(3) or ''}", f"{m.group(1)}:{rid_day}{m.group(3) or ''}",
            f"{me_.group(1)}:{rid_day}{me_.group(3) or ''}", "END:VEVENT"]
    return set_ps(out, uid_, ps)


def att(s, eid, uid_):
    r = s.get(B + f"/api/events/{eid}")
    return next((a["partstat"] for a in (r.json().get("attendees") or []) if a.get("user_id") == uid_), None) if r.ok else None


def occ_ps(eid, uid_):
    r = dbx("SELECT occ_ps FROM event_attendees WHERE event_id=? AND user_id=?", (eid, uid_))
    return json.loads(r[0][0]) if r and r[0][0] else {}


def href_of(eid):
    return dbx("SELECT href FROM events WHERE id=?", (eid,))[0][0]


if not os.environ.get("P2587_NOSTART"):
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
alice, bob, carol = Dav(A, "alice"), Dav(S["bob"], "bob"), Dav(S["carol"], "carol")


def ev(body, who=A):
    r = who.post(B + "/api/events", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ================================================================== free-busy-query
D = "2026-11-12"
ev({"cal_id": TEAM, "title": "Busy one", "start": f"{D}T10:00", "end": f"{D}T11:00"})
ev({"cal_id": TEAM, "title": "Shown as free", "start": f"{D}T12:00", "end": f"{D}T13:00", "busy": False})
ev({"cal_id": TEAM, "title": "All day", "start": D, "end": "2026-11-13", "all_day": True})
ev({"cal_id": TEAM, "title": "Called off", "start": f"{D}T14:00", "end": f"{D}T15:00", "status": "cancelled"})
ev({"cal_id": TEAM, "title": "Late one", "start": f"{D}T17:00", "end": f"{D}T18:00"})
TC = f"/dav/calendars/alice/e{TEAM}/"
r = alice.req("PROPFIND", TC, PF, Depth="0")
check(r.status_code == 207 and "free-busy-query" in r.text, f"#2587: the calendar names free-busy-query in supported-report-set ({r.status_code})")
r = alice.req("REPORT", TC, fbq("20261111T230000Z", "20261112T230000Z"), Depth="1", **{"Content-Type": "application/xml"})
fb = busy_lines(r.text)
check(r.status_code == 200 and "text/calendar" in r.headers.get("Content-Type", "") and "BEGIN:VFREEBUSY" in r.text,
      f"#2587: free-busy-query answers 200 with a VFREEBUSY ({r.status_code} {r.text[:200]})")
check(len(fb) == 2 and all("FBTYPE=BUSY" in x for x in fb),
      f"#2587: two busy times (free, all-day, cancelled stay out) {fb}")
check("Busy one" not in r.text and "Late one" not in r.text, "#2587: no titles in the free / busy answer")
check("DTSTART:20261111T230000Z" in r.text and "DTEND:20261112T230000Z" in r.text, "#2587: the VFREEBUSY names the asked range")
r = alice.req("REPORT", TC, fbq("20261113T000000Z", "20261114T000000Z"), Depth="1")
check(r.status_code == 200 and not busy_lines(r.text), f"#2587: an empty day: no busy times ({r.status_code})")
r = alice.req("REPORT", TC, fbq("", ""), Depth="1")
check(r.status_code == 400, f"#2587: without a time-range 400 ({r.status_code})")
r = alice.req("REPORT", TC, fbq("tomorrow", "20261114T000000Z"), Depth="1")
check(r.status_code == 400, f"#2587: an unreadable time 400 ({r.status_code})")

# ================================================================== one date of a series answered from the phone
SER = ev({"cal_id": TEAM, "title": "Weekly", "start": "2026-11-19T16:00", "end": "2026-11-19T17:00", "rrule": "FREQ=WEEKLY;COUNT=4",
          "attendees": [{"user_id": uid["bob"]}]})
INV = "/dav/calendars/bob/inv/"
H1 = INV + href_of(SER)
g = bob.req("GET", H1)
check(g.status_code == 200 and "RRULE:FREQ=WEEKLY" in g.text, f"the series as an invitation ({g.status_code})")
master = blocks(g.text)[0]
check(len(blocks(g.text)) == 1, "#2587: no answers to single dates yet: only the series (the ETag of other events stays)")
body = cal_of([set_ps(master, uid["bob"], "ACCEPTED"), override(master, "20261126", uid["bob"], "DECLINED")])
r = bob.req("PUT", H1, body, **CT, **{"If-Match": g.headers.get("ETag", "")})
check(r.status_code == 204, f"#2587: PUT of the series with one declined date: 204 ({r.status_code} {r.text[:200]})")
check(att(A, SER, uid["bob"]) == "accepted", "#2587: the series keeps the answer to the series (accepted)")
op = occ_ps(SER, uid["bob"])
check(len(op) == 1 and next(iter(op)).startswith("2026-11-26") and next(iter(op.values())) == "declined",
      f"#2587: the declined date is stored for bob alone {op}")
g2 = bob.req("GET", H1)
bl = blocks(g2.text)
ov = [b for b in bl if any(x.startswith("RECURRENCE-ID") and "20261126" in x for x in b)]
mine = lambda b: next((x for x in b if x.startswith("ATTENDEE") and f"urn:kalmido:user:{uid['bob']}" in x), "")  # noqa: E731
check(len(bl) == 2 and ov and "PARTSTAT=DECLINED" in mine(ov[0]) and "PARTSTAT=ACCEPTED" in mine(bl[0]),
      f"#2587: GET shows the date with its own answer, the series accepted {[mine(b) for b in bl]}")
check(g2.headers.get("ETag") != g.headers.get("ETag"), "#2587: a new ETag")
items = {o["occ"][:10]: o for o in S["bob"].get(B + "/api/events?from=2026-11-18&to=2026-12-12").json()["items"] if o["eid"] == SER}
check(items.get("2026-11-26", {}).get("partstat") == "declined" and items.get("2026-11-19", {}).get("partstat") == "accepted"
      and items.get("2026-12-03", {}).get("partstat") == "accepted",
      f"#2587: the calendar view shows the date's answer {[(k, v.get('partstat')) for k, v in sorted(items.items())]}")
check(not items.get("2026-11-26", {}).get("changed"), "#2587: ... the date is no changed occurrence of the series")
spans = lambda who, day: [x for p in S[who].get(B + f"/api/events/freebusy?day={day}&users={uid[who]}").json()["people"]  # noqa: E731
                          for x in p["slots"] if x["kind"] == "busy"]
check(not spans("bob", "2026-11-26") and spans("bob", "2026-12-03"),
      f"#2587: the availability bar: the declined date is free, the next one busy {spans('bob', '2026-11-26')} {spans('bob', '2026-12-03')}")
r = bob.req("REPORT", INV, fbq("20261118T000000Z", "20261211T000000Z"), Depth="1")
fb = busy_lines(r.text)
check(r.status_code == 200 and len(fb) == 3 and not any("20261126T" in x for x in fb),
      f"#2587: free-busy-query of the invitations: the three accepted dates {fb}")
# the other way round: the series declined, one date accepted
g3 = bob.req("GET", H1)
body = cal_of([set_ps(blocks(g3.text)[0], uid["bob"], "DECLINED"), override(blocks(g3.text)[0], "20261203", uid["bob"], "ACCEPTED")])
r = bob.req("PUT", H1, body, **CT)
op = occ_ps(SER, uid["bob"])
check(r.status_code == 204 and att(A, SER, uid["bob"]) == "declined" and list(op.values()) == ["accepted"] and next(iter(op)).startswith("2026-12-03"),
      f"#2587: series declined, one date accepted {op} ({r.status_code})")
check(spans("bob", "2026-12-03") and not spans("bob", "2026-11-19"), "#2587: ... only that date blocks the availability bar")
r = bob.req("REPORT", INV, fbq("20261118T000000Z", "20261211T000000Z"), Depth="1")
check(len(busy_lines(r.text)) == 1, f"#2587: ... and free-busy-query {busy_lines(r.text)}")
# a date answered like the series is no own answer; a PUT without the date follows the series again
g4 = bob.req("GET", H1)
body = cal_of([blocks(g4.text)[0], override(blocks(g4.text)[0], "20261126", uid["bob"], "DECLINED")])
bob.req("PUT", H1, body, **CT)
check(occ_ps(SER, uid["bob"]) == {}, f"#2587: a date with the series' answer stores nothing {occ_ps(SER, uid['bob'])}")
# the organiser edits the series: bob's answers to single dates stay (att_set keeps them)
bob.req("PUT", H1, cal_of([blocks(g4.text)[0], override(blocks(g4.text)[0], "20261126", uid["bob"], "ACCEPTED")]), **CT)
check(len(occ_ps(SER, uid["bob"])) == 1, "an own date answer again")
r = A.patch(B + f"/api/events/{SER}", json={"title": "Weekly sync", "attendees": [{"user_id": uid["bob"]}, {"user_id": uid["carol"]}]})
check(r.ok and len(occ_ps(SER, uid["bob"])) == 1 and att(A, SER, uid["bob"]) == "declined",
      f"#2587: the organiser changes the series and invites carol: bob's answers stay ({r.status_code} {occ_ps(SER, uid['bob'])})")
ga = alice.req("GET", TC + href_of(SER))
check(ga.status_code == 200 and len(blocks(ga.text)) == 2, f"the organiser's phone sees the date with bob's answer ({ga.status_code})")
r = alice.req("PUT", TC + href_of(SER), ga.text, **CT, **{"If-Match": ga.headers.get("ETag", "")})
check(r.status_code == 204 and dbx("SELECT overrides FROM events WHERE id=?", (SER,))[0][0] in ("", "[]", None),
      f"#2587: the organiser's phone writes the series back: the answered date is no changed occurrence ({r.status_code})")
check(len(occ_ps(SER, uid["bob"])) == 1 and att(A, SER, uid["bob"]) == "declined", "#2587: ... bob's answers stay")
g5 = bob.req("GET", H1)
bob.req("PUT", H1, cal_of([blocks(g5.text)[0]]), **CT)
check(occ_ps(SER, uid["bob"]) == {}, "#2587: a PUT without the date: it follows the series again")

# ================================================================== the own answer per PUT in a calendar one may edit
A.put(B + f"/api/evcals/{TEAM}/members", json={"user_id": uid["carol"], "role": "edit"})
E3 = ev({"cal_id": TEAM, "title": "Review", "start": "2026-11-20T09:00", "end": "2026-11-20T10:00",
         "attendees": [{"user_id": uid["carol"]}, {"user_id": uid["bob"]}]})
CH = f"/dav/calendars/carol/e{TEAM}/" + href_of(E3)
g = carol.req("GET", CH)
check(g.status_code == 200 and f"urn:kalmido:user:{uid['carol']}" in g.text, f"carol sees the event in the team calendar ({g.status_code})")
r = carol.req("PUT", CH, cal_of([set_ps(blocks(g.text)[0], uid["carol"], "ACCEPTED")]), **CT, **{"If-Match": g.headers.get("ETag", "")})
check(r.status_code == 204, f"#2587: carol's PUT in the calendar she may edit: 204 ({r.status_code} {r.text[:200]})")
check(att(A, E3, uid["carol"]) == "accepted", f"#2587: her own answer is taken ({att(A, E3, uid['carol'])})")
check(att(A, E3, uid["bob"]) == "needs-action", "#2587: ... bob's answer stays his own")
g = carol.req("GET", CH)
r = carol.req("PUT", CH, cal_of([set_ps(blocks(g.text)[0], uid["bob"], "ACCEPTED")]), **CT)
check(r.status_code == 204 and att(A, E3, uid["bob"]) == "needs-action" and att(A, E3, uid["carol"]) == "accepted",
      "#2587: another attendee's answer is never set by her PUT")

# ================================================================== an ignored change gets a new ETag
E4 = ev({"cal_id": TEAM, "title": "Planning", "start": "2026-11-21T10:00", "end": "2026-11-21T11:00", "attendees": [{"user_id": uid["bob"]}]})
H4 = INV + href_of(E4)
r = bob.req("PROPFIND", INV, PF, Depth="0")
tok = (re.findall(r"<D:sync-token>([^<]+)</D:sync-token>", r.text) or [""])[0]
g = bob.req("GET", H4)
lines = [("SUMMARY:Changed on the phone" if x.startswith("SUMMARY") else x) for x in blocks(g.text)[0]]
r = bob.req("PUT", H4, cal_of([lines]), **CT, **{"If-Match": g.headers.get("ETag", "")})
g2 = bob.req("GET", H4)
check(r.status_code == 204 and "SUMMARY:Planning" in g2.text, f"#2074: the changed title is ignored ({r.status_code})")
check(g2.headers.get("ETag") and g2.headers.get("ETag") != g.headers.get("ETag"),
      f"#2587: ... with a new ETag, so the phone loads the stored event ({g.headers.get('ETag')} {g2.headers.get('ETag')})")
rep = ('<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>' + tok + '</d:sync-token><d:sync-level>1</d:sync-level>'
       '<d:prop><d:getetag/></d:prop></d:sync-collection>')
r = bob.req("REPORT", INV, rep, Depth="1")
check(r.status_code == 207 and href_of(E4) in r.text, f"#2587: ... and the sync names it as changed ({r.status_code})")
check(att(A, E4, uid["bob"]) == "needs-action", "#2587: ... no answer was made up")

# ================================================================== a person without an organisation (P4)
# freelancer-matrix: pim
FID, Fr = freelancer(B, A, "frida")
fr = Dav(Fr, "frida")
lo, hi = sorted((ALICE, FID))
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-21T10:00:00.000Z')", (lo, hi))
HOME = A.post(B + "/api/evcals", json={"name": "Home", "org_id": None}).json()["id"]
FS = ev({"cal_id": HOME, "title": "Studio days", "start": "2026-11-17T15:00", "end": "2026-11-17T16:00", "rrule": "FREQ=WEEKLY;COUNT=3",
         "attendees": [{"user_id": FID}]})
r = fr.req("PROPFIND", "/dav/calendars/frida/inv/", PF, Depth="1")
fi = [h for h in re.findall(r"<D:href>([^<]+)</D:href>", r.text) if h.endswith(".ics")]
if fi:
    g = fr.req("GET", fi[0])
    m = blocks(g.text)[0]
    r = fr.req("PUT", fi[0], cal_of([set_ps(m, FID, "ACCEPTED"), override(m, "20261124", FID, "DECLINED")]), **CT)
    op = occ_ps(FS, FID)
    check(r.status_code == 204 and att(A, FS, FID) == "accepted" and list(op.values()) == ["declined"],
          f"P4: frida declines one date of a series from her phone {op} ({r.status_code})")
else:
    check(False, f"P4: frida's invitations collection {r.status_code} {r.text[:200]}")
FC = Fr.post(B + "/api/evcals", json={"name": "Studio"}).json()["id"]
ev({"cal_id": FC, "title": "Print run", "start": "2026-11-18T09:00", "end": "2026-11-18T12:00"}, Fr)
r = fr.req("REPORT", f"/dav/calendars/frida/e{FC}/", fbq("20261117T230000Z", "20261118T230000Z"), Depth="1")
check(r.status_code == 200 and len(busy_lines(r.text)) == 1, f"P4: free-busy-query on her own calendar ({r.status_code} {busy_lines(r.text)})")

print(f"p2587_caldav: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
