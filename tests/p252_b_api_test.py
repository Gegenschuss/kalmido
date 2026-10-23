#!/usr/bin/env python3
"""2.52.0 API tests (part B: #1128 writing events into subscribed CalDAV calendars), own container (start.sh) with the fake
calendar server inside (stub_calendar.py: /dav/calendars/alice/rw/ writable, /dav/calendars/alice/ro/ read only).
 - "Allow writing" per subscription: off by default, only CalDAV (an ICS link is refused), turning it on checks
   current-user-privilege-set (a read-only calendar cannot be switched on); writing while off -> 403
 - the events answer marks events of writable subscriptions (uid, dvw_write, dvw_rec) and the subscription (w)
 - new event = PUT <uuid>.ics with If-None-Match: *, change = GET + PUT with If-Match that keeps unknown properties,
   ATTENDEE and VALARM, delete = DELETE with If-Match + undo (put back) once
 - conflict: the resource changed elsewhere -> 409 "changed elsewhere", nothing overwritten, the subscription reloaded
 - a repeating series moves as a whole ("only this date" refused), EXDATE-free daily rule shifted by the same amount
 - isolation: another account cannot write into (or switch) someone's subscription (404); a stored href outside the
   subscription's collection (other path, '..', other host) is refused before any request
usage: p252_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8095"
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
T = testclock.today()


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def q(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def stub_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "calstub.log")) if x.strip()]
    except FileNotFoundError:
        return []


def store():
    try:
        return json.load(open(os.path.join(DATA, "rwstore.json")))
    except (FileNotFoundError, ValueError):
        return {}


def ext_put(name, data):
    """A change made elsewhere (another device): straight into the fake server, no If-Match."""
    code = ("import urllib.request,base64,sys\nr=urllib.request.Request('http://127.0.0.1:8095/dav/calendars/alice/rw/' + sys.argv[1], "
            "data=sys.stdin.buffer.read(), method='PUT', headers={'X-Stub-External': '1', 'Authorization': 'Basic ' + "
            "base64.b64encode(b'alice:secret-pw').decode()})\nprint(urllib.request.urlopen(r).status)")
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code, name], input=data.encode(), capture_output=True)
    return r.stdout.decode().strip()


def events(s, lo=-2, hi=12):
    r = s.get(B + f"/api/calendars/events?from={T + timedelta(days=lo)}&to={T + timedelta(days=hi)}")
    assert r.ok, r.text
    return r.json()


def ymd(n):
    return (T + timedelta(days=n)).isoformat()


subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA, exist_ok=True)
subprocess.run(["cp", os.path.join(N, "stub_calendar.py"), DATA])
env = dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8095 -e KALMIDO_CALENDAR_REFRESH_GAP=0 -e KALMIDO_CALENDAR_RATE=200")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_calendar.py"])
time.sleep(0.8)

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
Bo = sess("bob")

# ---- subscriptions: an ICS link, the writable and the read-only CalDAV calendar
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/good.ics"})
assert r.ok, r.text
ICS = r.json()["created"][0]
DAV = {"kind": "caldav", "url": STUB + "/dav/", "username": "alice", "password": "secret-pw"}
r = A.post(B + "/api/calendars", json={**DAV, "calendars": [{"url": STUB + "/dav/calendars/alice/rw/", "name": "Writable"},
                                                            {"url": STUB + "/dav/calendars/alice/ro/", "name": "Shared read-only"}]})
assert r.ok, r.text
RW, RO = r.json()["created"]
subs = {x["id"]: x for x in r.json()["subs"]}
check(subs[RW]["write"] is False and subs[RW]["can_write"] is False, "new CalDAV subscription: writing off by default")
check(q("SELECT dav_write, dav_can_write FROM cal_subs WHERE id=?", (RW,))[0] == (0, 0), "db: dav_write / dav_can_write 0")
res = {u: (h, e, rec) for u, h, e, rec in q("SELECT uid, href, etag, rec FROM cal_dav_res WHERE sub_id=?", (RW,))}
check(res.get("rw-1@stub") == (STUB + "/dav/calendars/alice/rw/one.ics", '"rw-a"', 0) and res.get("rw-rec@stub", (0, 0, 0))[2] == 1,
      f"sync stores href + ETag per UID, rec for a series: {res}")
j = events(A)
check(j["subs"][str(RW)]["w"] is False and not any(e.get("dvw_write") for e in j["events"]), "writing off: no event is marked writable")

# ---- switch: ICS refused, read-only calendar refused, writing while off 403
r = A.post(B + f"/api/calendars/{ICS}/write", json={"on": True})
check(r.status_code == 409, f"ICS link: no writing ({r.status_code})")
r = A.post(B + f"/api/calendars/{RO}/write", json={"on": True})
check(r.status_code == 409 and r.json().get("code") == "read_only", f"read-only calendar (no write privilege): switch refused ({r.status_code} {r.text[:120]})")
check(q("SELECT dav_write FROM cal_subs WHERE id=?", (RO,))[0][0] == 0, "read-only calendar stays off")
r = A.post(B + f"/api/calendars/{RW}/events", json={"title": "x", "all_day": True, "start": ymd(5), "end": ymd(6)})
check(r.status_code == 403, f"writing while the switch is off: 403 ({r.status_code})")
r = A.post(B + f"/api/calendars/{RW}/write", json={"on": "yes"})
check(r.status_code == 400, f"switch: on must be a boolean ({r.status_code})")
n0 = len(stub_log())
r = A.post(B + f"/api/calendars/{RW}/write", json={"on": True})
check(r.ok and r.json()["write"] is True and r.json()["can_write"] is True, f"writable calendar: switched on ({r.text[:160]})")
check(any(x["method"] == "PROPFIND" and x["path"] == "/dav/calendars/alice/rw/" for x in stub_log()[n0:]), "switching on asks the server (PROPFIND privileges)")
j = events(A)
ev1 = next((e for e in j["events"] if e.get("uid") == "rw-1@stub"), None)
rec = [e for e in j["events"] if e.get("uid") == "rw-rec@stub"]
check(j["subs"][str(RW)]["w"] is True and ev1 and ev1["dvw_write"] is True and ev1["dvw_rec"] is False, f"events of the writable calendar are marked: {ev1}")
check(len(rec) == 5 and all(e["dvw_rec"] for e in rec), f"the daily series is marked as a series ({len(rec)})")
check(not any(e.get("dvw_write") for e in j["events"] if e["sub"] in (ICS, RO)), "ICS / read-only events are never marked writable")

# ---- new event
n0 = len(stub_log())
r = A.post(B + f"/api/calendars/{RW}/events", json={"title": "Planning, room 2", "location": "Room 2", "description": "line 1\nline 2",
                                                    "all_day": False, "start": ymd(4) + "T14:00", "end": ymd(4) + "T15:30", "tz": "Europe/Berlin"})
check(r.ok and r.json().get("uid"), f"new event in the CalDAV calendar ({r.status_code} {r.text[:160]})")
NEW = r.json().get("uid", "")
puts = [x for x in stub_log()[n0:] if x["method"] == "PUT"]
check(len(puts) == 1 and puts[0]["path"] == f"/dav/calendars/alice/rw/{NEW}.ics" and puts[0]["inm"] == "*", f"PUT <uuid>.ics with If-None-Match: * ({puts})")
data = store().get("rw", {}).get(f"{NEW}.ics", ["", ""])[1]
check("SUMMARY:Planning\\, room 2" in data and f"DTSTART;TZID=Europe/Berlin:{ymd(4).replace('-', '')}T140000" in data and "BEGIN:VTIMEZONE" in data
      and "DESCRIPTION:line 1\\nline 2" in data, "the new resource: escaped text, TZID start, time zone")
ne = next((e for e in events(A)["events"] if e.get("uid") == NEW), None)
check(ne and ne["title"] == "Planning, room 2" and ne["location"] == "Room 2" and ne["dvw_write"], f"the new event shows after the sync: {ne}")
for bad in ({"title": "x", "all_day": False, "start": "tomorrow", "end": "x"}, {"title": 5, "all_day": True, "start": ymd(1), "end": ymd(2)},
            {"title": "x", "all_day": False, "start": ymd(1) + "T10:00", "end": ymd(1) + "T09:00"},
            {"title": "x", "all_day": False, "start": ymd(1) + "T10:00", "end": ymd(1) + "T11:00", "tz": "Mars/Base"}):
    r = A.post(B + f"/api/calendars/{RW}/events", json=bad)
    check(r.status_code == 400, f"invalid new event refused: {bad} ({r.status_code})")

# ---- change: only the changed properties; unknown ones, ATTENDEE, VALARM stay
n0 = len(stub_log())
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-1@stub", "occ": ev1["start"], "title": "Writable one (moved)",
                                                     "all_day": False, "start": ymd(3) + "T11:00", "end": ymd(3) + "T12:30", "tz": "Europe/Berlin"})
check(r.ok, f"change an event ({r.status_code} {r.text[:160]})")
lg = stub_log()[n0:]
check([x["method"] for x in lg][:2] == ["GET", "PUT"] and lg[1]["im"] == '"rw-a"', f"change = GET, then PUT with If-Match of the stored ETag ({[(x['method'], x['im']) for x in lg]})")
data = store().get("rw", {}).get("one.ics", ["", ""])[1]
check("X-STUB-KEEP:yes" in data and "ATTENDEE" in data and "BEGIN:VALARM" in data and "TRIGGER:-PT10M" in data, "unknown properties, ATTENDEE, VALARM kept")
check("SUMMARY:Writable one (moved)" in data and f"DTSTART;TZID=Europe/Berlin:{ymd(3).replace('-', '')}T110000" in data
      and f"DTEND;TZID=Europe/Berlin:{ymd(3).replace('-', '')}T123000" in data and "SEQUENCE:1" in data, "title + times changed in the series' zone, SEQUENCE up")
e1 = next((e for e in events(A)["events"] if e.get("uid") == "rw-1@stub"), {})
check(e1.get("title") == "Writable one (moved)", f"the change shows after the sync: {e1.get('title')}")

# ---- conflict: changed elsewhere -> nothing overwritten
ext = data.replace("SUMMARY:Writable one (moved)", "SUMMARY:Changed on the phone")
check(ext_put("one.ics", ext) in ("204", "201"), "changed elsewhere (fake server)")
n0 = len(stub_log())
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-1@stub", "occ": e1["start"], "title": "Kalmido wins?"})
check(r.status_code == 409 and r.json().get("code") == "conflict", f"conflict: 409 ({r.status_code} {r.text[:160]})")
check(not [x for x in stub_log()[n0:] if x["method"] == "PUT"], "conflict: no PUT was sent")
check("SUMMARY:Changed on the phone" in store()["rw"]["one.ics"][1], "conflict: the other change stays")
e1 = next((e for e in events(A)["events"] if e.get("uid") == "rw-1@stub"), {})
check(e1.get("title") == "Changed on the phone", f"conflict: the subscription was reloaded ({e1.get('title')})")
# a stored ETag that no longer matches the resource (the GET says so): refused before any PUT
q("UPDATE cal_dav_res SET etag='\"stale\"' WHERE sub_id=? AND uid='rw-1@stub'", (RW,))
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-1@stub", "occ": e1["start"], "title": "Stale"})
check(r.status_code == 409, f"stale ETag: 409, nothing written ({r.status_code})")
check("SUMMARY:Changed on the phone" in store()["rw"]["one.ics"][1], "stale ETag: the resource is unchanged")

# ---- a repeating series: only the whole series
first = min(rec, key=lambda e: e["start"])
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-rec@stub", "occ": first["start"], "scope": "one", "title": "one"})
check(r.status_code == 409, f"series: 'only this date' refused ({r.status_code})")
second = sorted(rec, key=lambda e: e["start"])[1]
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-rec@stub", "occ": second["start"], "scope": "all", "all_day": False,
                                                     "start": ymd(2) + "T09:00", "end": ymd(2) + "T09:45", "tz": "Europe/Berlin"})
check(r.ok, f"series: moving one date moves the series ({r.status_code} {r.text[:120]})")
data = store()["rw"]["rec.ics"][1]
check(f"DTSTART;TZID=Europe/Berlin:{ymd(1).replace('-', '')}T090000" in data and f"DTEND;TZID=Europe/Berlin:{ymd(1).replace('-', '')}T094500" in data
      and "RRULE:FREQ=DAILY;COUNT=5" in data, "series: start + length moved by the same amount, the rule stays")
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-rec@stub", "occ": second["start"], "all_day": True, "start": ymd(2), "end": ymd(3)})
check(r.status_code == 409, f"series: no switch between all-day and timed ({r.status_code})")

# ---- delete + undo
NEWE = next(e for e in events(A)["events"] if e.get("uid") == NEW)
n0 = len(stub_log())
r = A.delete(B + f"/api/calendars/{RW}/events?uid={NEW}")
check(r.ok and r.json().get("undo"), f"delete ({r.status_code})")
TOK = r.json().get("undo")
dl = [x for x in stub_log()[n0:] if x["method"] == "DELETE"]
check(len(dl) == 1 and dl[0]["im"], f"DELETE with If-Match ({dl})")
check(f"{NEW}.ics" not in store()["rw"] and not any(e.get("uid") == NEW for e in events(A)["events"]), "deleted on the server and in Kalmido")
check(Bo.post(B + f"/api/calendars/{RW}/events/restore", json={"undo": TOK}).status_code == 404, "undo: another account cannot use the token")
r = A.post(B + f"/api/calendars/{RW}/events/restore", json={"undo": TOK})
check(r.ok and f"{NEW}.ics" in store()["rw"], f"undo puts the event back ({r.status_code})")
check(A.post(B + f"/api/calendars/{RW}/events/restore", json={"undo": TOK}).status_code == 410, "undo works once")
check(A.post(B + f"/api/calendars/{RW}/events/restore", json={"undo": "nope"}).status_code == 410, "undo: an unknown token")
r = A.delete(B + f"/api/calendars/{RW}/events?uid=not-there")
check(r.status_code == 404, f"delete: unknown UID 404 ({r.status_code})")

# ---- isolation + hrefs outside the collection
n0 = len(stub_log())
for m, p, b in (("post", f"/api/calendars/{RW}/events", {"title": "x", "all_day": True, "start": ymd(1), "end": ymd(2)}),
                ("patch", f"/api/calendars/{RW}/events", {"uid": "rw-1@stub", "title": "x"}),
                ("delete", f"/api/calendars/{RW}/events?uid=rw-1@stub", None),
                ("post", f"/api/calendars/{RW}/write", {"on": False})):
    r = getattr(Bo, m)(B + p, json=b) if b is not None else getattr(Bo, m)(B + p)
    check(r.status_code == 404, f"another account: {m} {p} -> 404 ({r.status_code})")
check(not stub_log()[n0:], "another account: no request reached the calendar server")
check(not any(e.get("sub") == RW for e in events(Bo)["events"]), "another account does not see the events")
for href in (STUB + "/dav/calendars/alice/ro/ro.ics", STUB + "/dav/calendars/alice/rw/../ro/ro.ics", STUB + "/dav/calendars/alice/rw/%2e%2e/ro/ro.ics",
             "http://127.0.0.1:8096/dav/calendars/alice/rw/one.ics", "http://evil.test:8095/dav/calendars/alice/rw/one.ics",
             STUB + "/dav/calendars/alice/rw/"):
    q("UPDATE cal_dav_res SET href=? WHERE sub_id=? AND uid='rw-1@stub'", (href, RW))
    n0 = len(stub_log())
    r = A.delete(B + f"/api/calendars/{RW}/events?uid=rw-1@stub")
    check(r.status_code == 400 and not stub_log()[n0:], f"href outside the collection refused before any request: {href} ({r.status_code})")
check("ro.ics" in store()["ro"] and "one.ics" in store()["rw"], "nothing was deleted through a foreign href")
r = A.post(B + f"/api/calendars/{RW}/refresh")
check(r.ok, "refresh restores the real hrefs")

# ---- 2.58.0 (#1789): a weak stored ETag -> no write attempt, a clear message; PUT / DELETE never follow a redirect
et = q("SELECT etag FROM cal_dav_res WHERE sub_id=? AND uid='rw-1@stub'", (RW,))[0][0]
q("UPDATE cal_dav_res SET etag=? WHERE sub_id=? AND uid='rw-1@stub'", ("W/" + et, RW))
for m, p, b in (("patch", f"/api/calendars/{RW}/events", {"uid": "rw-1@stub", "title": "Weak"}), ("delete", f"/api/calendars/{RW}/events?uid=rw-1@stub", None)):
    n0 = len(stub_log())
    r = getattr(A, m)(B + p, json=b) if b is not None else getattr(A, m)(B + p)
    check(r.status_code == 409 and r.json().get("code") == "weak_etag" and "weak" in r.json().get("error", ""),
          f"weak ETag: {m} -> 409 weak_etag ({r.status_code} {r.text[:120]})")
    check(not [x for x in stub_log()[n0:] if x["method"] in ("PUT", "DELETE")], f"weak ETag: {m} sent no write")
q("UPDATE cal_dav_res SET etag=?, href=? WHERE sub_id=? AND uid='rw-1@stub'", (et, STUB + "/dav/calendars/alice/rw/moved.ics", RW))
for m, p, b in (("patch", f"/api/calendars/{RW}/events", {"uid": "rw-1@stub", "title": "Redirected"}), ("delete", f"/api/calendars/{RW}/events?uid=rw-1@stub", None)):
    n0 = len(stub_log())
    r = getattr(A, m)(B + p, json=b) if b is not None else getattr(A, m)(B + p)
    lg = stub_log()[n0:]
    check(r.status_code == 502 and r.json().get("code") == "redirect", f"redirect on {m}: refused ({r.status_code} {r.text[:120]})")
    check(not [x for x in lg if x["method"] in ("PUT", "DELETE") and x["path"].endswith("/one.ics")], f"redirect on {m}: not followed {[(x['method'], x['path']) for x in lg]}")
check("one.ics" in store()["rw"] and "Redirected" not in store()["rw"]["one.ics"][1], "redirect: the resource is unchanged")
check(A.post(B + f"/api/calendars/{RW}/refresh").ok, "refresh restores the real href")

# ---- switching off
r = A.post(B + f"/api/calendars/{RW}/write", json={"on": False})
check(r.ok and r.json()["write"] is False, "switched off again")
check(not any(e.get("dvw_write") for e in events(A)["events"]), "off: no event is marked writable")
r = A.patch(B + f"/api/calendars/{RW}/events", json={"uid": "rw-1@stub", "title": "x"})
check(r.status_code == 403, f"off: changing refused ({r.status_code})")
# the credentials never leave the server
check("secret-pw" not in json.dumps(A.get(B + "/api/calendars").json()), "the password is never returned")

print(f"p252_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
