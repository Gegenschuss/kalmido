#!/usr/bin/env python3
"""2.9.0 API, own container (start.sh, isolated test database), raw HTTP:
#435 CalDAV for tasks: app passwords (web + token API, persons only, shown once, hashed, revoke, last use, lockout after
failed logins, never the account password, never an agent), discovery (/.well-known/caldav, current-user-principal,
calendar-home-set, one VTODO calendar per visible list with name, colour, privileges), PROPFIND depth 0 / 1, REPORT
calendar-query / calendar-multiget / sync-collection (deltas, removals, unknown token), PUT / GET / DELETE round trips with
VTODOs as Reminders (iOS / macOS), Thunderbird and Tasks.org write them (unknown properties and alarms kept, TZID -> server
time, priority, tags, completion, CANCELLED, absolute and relative alarms), If-Match / If-None-Match conflicts, subtasks
(RELATED-TO, a child before its parent), RRULE (supported -> repeat, completing moves it on; unsupported -> kept for the
client), moving a task between lists, viewers read-only, participants only their tasks, the trash, events instead of todos
refused, history "via CalDAV", HTTP refused without KALMIDO_CALDAV_HTTP when PUBLIC_URL is http;
#438 OIDC settings stored in the database (environment wins per field, the secret sealed, admin e-mail domains, check).
usage: p290_dav_test.py <datadir>"""
import os
import re
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
NS = {"D": "DAV:", "C": "urn:ietf:params:xml:ns:caldav", "CS": "http://calendarserver.org/ns/", "A": "http://apple.com/ns/ical/"}


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(extra="", keep=False):
    env = dict(os.environ, EXTRA=extra, **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


def db(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def dav(user, pw):
    s = requests.Session()
    s.auth = (user, pw)
    return s


def req(s, method, path, body=None, depth=None, **hd):
    h = {"Content-Type": "application/xml; charset=utf-8"} if body and method != "PUT" else {}
    if depth is not None:
        h["Depth"] = str(depth)
    h.update({k.replace("_", "-"): v for k, v in hd.items()})
    return s.request(method, B + path, data=body.encode("utf-8") if isinstance(body, str) else body, headers=h, allow_redirects=False)


def ms(r):
    """{href: {prop clark: element}} + statuses of a 207 answer."""
    root = ET.fromstring(r.content)
    out = {}
    for resp in root.findall("D:response", NS):
        href = resp.find("D:href", NS).text
        props, st = {}, resp.find("D:status", NS)
        for ps in resp.findall("D:propstat", NS):
            if "200" in ps.find("D:status", NS).text:
                for p in ps.find("D:prop", NS):
                    props[p.tag] = p
        out[href] = {"props": props, "status": st.text if st is not None else ""}
    tok = root.find("D:sync-token", NS)
    return out, (tok.text if tok is not None else None)


def put(s, path, ics, **hd):
    return s.put(B + path, data=ics.encode("utf-8"), headers={"Content-Type": "text/calendar; charset=utf-8",
                                                               **{k.replace("_", "-"): v for k, v in hd.items()}})


def vcal(*todos, extra=""):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n" + extra + "".join(todos) + "END:VCALENDAR\r\n"


def todo(*lines):
    return "BEGIN:VTODO\r\n" + "".join(x + "\r\n" for x in lines) + "END:VTODO\r\n"


def task(tid):
    r = db("SELECT title, content, priority, status, due, due_time, start, repeat, reminders, url, parent_id, list_id, "
           "deleted_at, completed_at FROM tasks WHERE id=?", (tid,))
    return dict(zip(["title", "content", "priority", "status", "due", "due_time", "start", "repeat", "reminders", "url",
                     "parent_id", "list_id", "deleted_at", "completed_at"], r[0])) if r else None


def by_uid(uid):
    r = db("SELECT task_id FROM dav_meta WHERE uid=?", (uid,))
    return r[0][0] if r else None


def tags(tid, uid):
    return sorted(x[0] for x in db("SELECT tag FROM task_tags WHERE task_id=? AND user_id=?", (tid, uid)))


PF_CAL = ('<?xml version="1.0"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" '
          'xmlns:CS="http://calendarserver.org/ns/" xmlns:A="http://apple.com/ns/ical/"><D:prop><D:displayname/><D:resourcetype/>'
          '<C:supported-calendar-component-set/><CS:getctag/><D:sync-token/><A:calendar-color/><D:current-user-privilege-set/>'
          '<D:supported-report-set/><D:getetag/></D:prop></D:propfind>')


def sync(s, path, token=""):
    body = (f'<?xml version="1.0"?><D:sync-collection xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:sync-token>'
            f'{token}</D:sync-token><D:sync-level>1</D:sync-level><D:prop><D:getetag/></D:prop></D:sync-collection>')
    return req(s, "REPORT", path, body, 1)


def multiget(s, path, hrefs):
    body = ('<?xml version="1.0"?><C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
            '<C:calendar-data/></D:prop>' + "".join(f"<D:href>{h}</D:href>" for h in hrefs) + "</C:calendar-multiget>")
    return req(s, "REPORT", path, body, 1)


def cdata(entry):
    el = entry["props"].get("{urn:ietf:params:xml:ns:caldav}calendar-data")
    return el.text if el is not None else ""


def etag(entry):
    el = entry["props"].get("{DAV:}getetag")
    return el.text if el is not None else None


# ---------------------------------------------------------------- setup
start()
requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
ids = {"alice": db("SELECT id FROM users WHERE username='alice'")[0][0]}
for u in ("bob", "carl"):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carl")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
work = A.post(B + "/api/lists", json={"name": "Work", "color": "#2563eb"}).json()["id"]
home = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
shared = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
A.put(B + f"/api/lists/{shared}/members", json={"user_id": ids["bob"], "role": "view"})
A.put(B + f"/api/lists/{shared}/members", json={"user_id": ids["carl"], "role": "participant"})
check({r[0]: r[1] for r in db("SELECT user_id, role FROM list_members WHERE list_id=?", (shared,))} ==
      {ids["bob"]: "view", ids["carl"]: "participant"}, "test setup: Team shared with bob (view) and carl (participant)")

# ---------------------------------------------------------------- app passwords
st = A.get(B + "/api/state").json()
check(st["caldav"]["enabled"] and st["caldav"]["url"] == "https://kalmido.example/dav/" and st["caldav"]["username"] == "alice",
      "state.caldav: enabled, the /dav/ address, the user name")
r = A.post(B + "/api/me/app-passwords", json={"name": ""})
check(r.status_code == 400, "app password without a name: 400")
r = A.post(B + "/api/me/app-passwords", json={"name": "iPhone"})
check(r.status_code == 201 and re.fullmatch(r"[a-z2-9]{5}(-[a-z2-9]{5}){3}", r.json().get("password", "")),
      "new app password: 201, 4 groups of 5 characters")
PW, PWID = r.json()["password"], r.json()["id"]
row = db("SELECT pw_hash FROM app_passwords WHERE id=?", (PWID,))[0][0]
check(PW not in row and PW.replace("-", "") not in row and row.startswith(("scrypt:", "pbkdf2:")), "only a KDF hash is stored")
j = A.get(B + "/api/me/app-passwords").json()
check([x["name"] for x in j["items"]] == ["iPhone"] and "password" not in j["items"][0] and "pw_hash" not in str(j),
      "the list never shows the password or its hash")
check(requests.post(B + "/api/me/app-passwords", headers=H, json={"name": "x"}).status_code == 401, "creating needs a login")
D = dav("alice", PW)
r = req(D, "PROPFIND", "/dav/", "", 0)
check(r.status_code == 207, "Basic with user name + app password: 207")
check(req(dav("alice", PW.replace("-", "").upper()), "PROPFIND", "/dav/", "", 0).status_code == 207,
      "the app password works without dashes and in capitals (typed on a phone)")
check(req(dav("alice", "password123"), "PROPFIND", "/dav/", "", 0).status_code == 401, "the account password is refused")
r = req(requests.Session(), "PROPFIND", "/dav/", "", 0)
check(r.status_code == 401 and r.headers.get("WWW-Authenticate", "").startswith("Basic realm="), "no credentials: 401 + Basic challenge")
check(req(requests.Session(), "OPTIONS", "/dav/").headers.get("DAV", "").replace(" ", "") == "1,3,calendar-access",
      "OPTIONS without login: DAV: 1, 3, calendar-access")
time.sleep(1.1)
check(db("SELECT last_used_at IS NOT NULL FROM app_passwords WHERE id=?", (PWID,))[0][0] == 1, "last use is recorded")
# token API: persons only, write scope
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
th = {"Authorization": "Bearer " + tok}
r = requests.post(V + "/me/app-passwords", headers=th, json={"name": "Thunderbird"})
check(r.status_code == 201 and r.json().get("password"), "token API: create an app password")
TBPW, TBID = r.json()["password"], r.json()["id"]
r = requests.post(V + "/me/app-passwords", headers=th, json={"name": "x", "bogus": 1})
check(r.status_code == 400 and r.json()["error"]["code"] == "unknown_field", "token API: unknown field 400")
j = requests.get(V + "/me/app-passwords", headers=th).json()
check(len(j["data"]) == 2 and j["caldav"]["username"] == "alice", "token API: list + the CalDAV address")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "robo", "display_name": "Robo"})
atok = ag.json().get("token") if ag.status_code == 201 else ""
check(bool(atok), "test setup: an agent with a token")
check(requests.post(V + "/me/app-passwords", headers={"Authorization": "Bearer " + str(atok)}, json={"name": "x"}).status_code == 403,
      "an agent's token cannot create app passwords")
check(requests.get(V + "/me/app-passwords", headers={"Authorization": "Bearer " + str(atok)}).status_code == 403,
      "an agent's token cannot list app passwords")
spec = requests.get(V + "/openapi.json").json()
check("/me/app-passwords" in spec["paths"] and "/me/app-passwords/{id}" in spec["paths"], "OpenAPI lists the app password routes")
# revoke stops at once (also while the positive cache knows it)
check(req(dav("alice", TBPW), "PROPFIND", "/dav/", "", 0).status_code == 207, "second app password works")
check(requests.delete(V + f"/me/app-passwords/{TBID}", headers=th).json().get("ok") is True, "token API: revoke")
check(req(dav("alice", TBPW), "PROPFIND", "/dav/", "", 0).status_code == 401, "a revoked app password stops at once")
check(A.delete(B + "/api/me/app-passwords/999999").status_code == 404, "revoking an unknown id: 404")
r = Bo.post(B + "/api/me/app-passwords", json={"name": "Bob phone"})
BPW, BPWID = r.json()["password"], r.json()["id"]
check(Bo.delete(B + f"/api/me/app-passwords/{PWID}").status_code == 404, "nobody revokes another person's app password")
check(req(dav("bob", PW), "PROPFIND", "/dav/", "", 0).status_code == 401, "alice's app password does not work for bob")
r = Ca.post(B + "/api/me/app-passwords", json={"name": "Carl phone"})
CPW = r.json()["password"]

# ---------------------------------------------------------------- discovery
r = req(D, "PROPFIND", "/", "", 0)
check(r.status_code == 301 and r.headers["Location"].endswith("/dav/"), "PROPFIND on the server root -> /dav/ (clients given only the host)")
check(requests.get(B + "/").status_code == 200, "GET / is still the app")
r = req(D, "PROPFIND", "/.well-known/caldav", "", 0)
check(r.status_code == 301 and r.headers["Location"].endswith("/dav/"), "/.well-known/caldav -> /dav/ (301)")
PF_P = ('<?xml version="1.0"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:current-user-principal/>'
        '<C:calendar-home-set/><D:principal-URL/><D:displayname/><D:resourcetype/><D:unknown-x/></D:prop></D:propfind>')
m, _ = ms(req(D, "PROPFIND", "/dav/", PF_P, 0))
cup = m["/dav/"]["props"]["{DAV:}current-user-principal"].find("D:href", NS).text
check(cup == "/dav/principals/alice/", "root: current-user-principal")
m, _ = ms(req(D, "PROPFIND", cup, PF_P, 0))
pr = m[cup]["props"]
check(pr["{urn:ietf:params:xml:ns:caldav}calendar-home-set"].find("D:href", NS).text == "/dav/calendars/alice/",
      "principal: calendar-home-set")
check(pr["{DAV:}resourcetype"].find("D:principal", NS) is not None and pr["{DAV:}displayname"].text == "Alice",
      "principal: resource type principal + display name")
check("{DAV:}unknown-x" not in pr, "unknown properties are reported as 404, not 200")
check(req(D, "PROPFIND", "/dav/principals/bob/", PF_P, 0).status_code == 404, "another person's principal: 404")
check(req(D, "PROPFIND", "/dav/calendars/bob/", PF_P, 1).status_code == 404, "another person's calendar home: 404")
r = req(D, "PROPFIND", "/dav/calendars/alice/", PF_P.replace("<D:unknown-x/>", "") , 1)
m, _ = ms(r)
m2, _ = ms(req(D, "PROPFIND", "/dav/calendars/alice/", PF_CAL, 1))
cals = {h: e for h, e in m2.items() if h != "/dav/calendars/alice/"}
names = {e["props"]["{DAV:}displayname"].text: h for h, e in cals.items()}
check(set(names) == {"Inbox", "Work", "Home", "Team"}, f"one calendar per visible list: {sorted(names)}")
WORK, HOME, TEAM = names["Work"], names["Home"], names["Team"]
check(WORK == f"/dav/calendars/alice/{work}/", "calendar address = list id")
wp = cals[WORK]["props"]
check(wp["{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set"].find("C:comp", NS).get("name") == "VTODO"
      and len(wp["{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set"]) == 1, "VTODO only")
check(wp["{http://apple.com/ns/ical/}calendar-color"].text == "#2563EBFF", "calendar-color #RRGGBBAA")
check(wp["{DAV:}resourcetype"].find("C:calendar", NS) is not None, "resource type calendar")
privs = {p[0].tag.split("}")[1] for p in wp["{DAV:}current-user-privilege-set"]}
check({"read", "write", "bind", "unbind"} <= privs, f"owner privileges {privs}")
reports = {x[0][0].tag.split("}")[1] for x in wp["{DAV:}supported-report-set"]}
check(reports == {"calendar-query", "calendar-multiget", "sync-collection"}, f"supported reports {reports}")
check(wp["{http://calendarserver.org/ns/}getctag"].text and wp["{DAV:}sync-token"].text.startswith("urn:kalmido:sync:"),
      "getctag + sync-token")
mb, _ = ms(req(dav("bob", BPW), "PROPFIND", "/dav/calendars/bob/", PF_CAL, 1))
bt = [e for h, e in mb.items() if h.endswith(f"/{shared}/")]
check(len(bt) == 1 and {p[0].tag.split("}")[1] for p in bt[0]["props"]["{DAV:}current-user-privilege-set"]} == {"read"},
      "a viewer gets the shared list read-only")
check(not any(h.endswith(f"/{work}/") for h in mb), "bob does not see alice's private lists")
check(req(dav("bob", BPW), "PROPFIND", f"/dav/calendars/bob/{work}/", PF_CAL, 0).status_code == 404, "a list bob cannot see: 404")
A.patch(B + f"/api/lists/{home}", json={"archived": True})
m3, _ = ms(req(D, "PROPFIND", "/dav/calendars/alice/", PF_CAL, 1))
check(HOME not in m3, "archived lists are no calendars")
A.patch(B + f"/api/lists/{home}", json={"archived": False})

# ---------------------------------------------------------------- PUT / GET round trips (client samples)
NY = ("BEGIN:VTIMEZONE\r\nTZID:America/New_York\r\nBEGIN:DAYLIGHT\r\nTZOFFSETFROM:-0500\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\n"
      "DTSTART:20070311T020000\r\nTZNAME:EDT\r\nTZOFFSETTO:-0400\r\nEND:DAYLIGHT\r\nBEGIN:STANDARD\r\nTZOFFSETFROM:-0400\r\n"
      "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\nDTSTART:20071104T020000\r\nTZNAME:EST\r\nTZOFFSETTO:-0500\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n")
APPLE = vcal(todo("CREATED:20261001T120000Z", "DTSTAMP:20261001T120000Z", "LAST-MODIFIED:20261001T120000Z",
                  "UID:5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B", "SUMMARY:Call the bank", "DTSTART;TZID=America/New_York:20261005T090000",
                  "DUE;TZID=America/New_York:20261005T090000", "PRIORITY:1", "STATUS:NEEDS-ACTION", "X-APPLE-SORT-ORDER:731234567",
                  "BEGIN:VALARM", "X-WR-ALARMUID:AL-1", "UID:AL-1", "TRIGGER;VALUE=DATE-TIME:20261005T130000Z", "ACTION:DISPLAY",
                  "DESCRIPTION:Reminder", "END:VALARM",
                  "BEGIN:VALARM", "UID:AL-2", "TRIGGER;VALUE=DATE-TIME:19760401T005545Z", "ACTION:NONE",
                  "X-APPLE-PROXIMITY:ARRIVE", "END:VALARM"), extra=NY)
APW = A.post(B + "/api/me/app-passwords", json={"name": "Mac"}).json()["password"]
AP = dav("alice", APW)
r = put(AP, WORK + "5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B.ics", APPLE, If_None_Match="*")
check(r.status_code == 201 and "ETag" not in r.headers, "Reminders: PUT creates (201, no ETag: the server rewrote it)")
t1 = by_uid("5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B")
t = task(t1)
check(t and t["title"] == "Call the bank" and t["list_id"] == work and t["priority"] == 5, "Reminders: title, list, PRIORITY 1 -> high")
check(t["due"] == "2026-10-05" and t["due_time"] == "15:00" and not t["start"], "Reminders: 09:00 New York -> 15:00 Berlin, DTSTART = DUE is no start")
check(t["reminders"] == "0", f"Reminders: absolute alarm at the due time -> offset 0 ({t['reminders']})")
r = AP.get(B + WORK + "5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B.ics")
check(r.status_code == 200 and r.headers.get("ETag") and r.headers["Content-Type"].startswith("text/calendar"), "GET: 200, ETag, text/calendar")
g1 = r.text.replace("\r\n ", "")
check("UID:5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B" in g1 and "DUE;TZID=Europe/Berlin:20261005T150000" in g1 and "BEGIN:VTIMEZONE" in g1,
      "GET: the client's UID, DUE in the server's time zone with VTIMEZONE")
check("X-APPLE-SORT-ORDER:731234567" in g1 and "X-APPLE-PROXIMITY:ARRIVE" in g1 and "TRIGGER;VALUE=DATE-TIME:19760401T005545Z" in g1,
      "GET: unknown properties and the location alarm come back as they were")
check(g1.count("BEGIN:VALARM") == 2 and "TRIGGER;RELATED=END:PT0S" in g1, "GET: the mapped alarm + the kept one")
check("DTSTART" not in g1.split("BEGIN:VTODO")[1], "no stray DTSTART in the task (Reminders' DTSTART = DUE is not a start)")
E1 = r.headers["ETag"]
check(AP.get(B + WORK + "5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B.ics").headers["ETag"] == E1, "the ETag is stable")
check(any(a[0] == "created" and '"caldav"' in a[1] for a in db("SELECT kind, data FROM activity WHERE task_id=?", (t1,))),
      "history: created via CalDAV")
web = A.get(B + f"/api/tasks/{t1}").json()
check(web["title"] == "Call the bank", "the web app sees the task")

THUNDER = vcal(todo("CREATED:20261001T100000Z", "LAST-MODIFIED:20261001T100000Z", "DTSTAMP:20261001T100000Z",
                    "UID:b4c1d2e3-f4a5-4b6c-9d8e-7f6a5b4c3d2e", "SUMMARY:Write report", "PRIORITY:5", "STATUS:IN-PROCESS",
                    "PERCENT-COMPLETE:40", "CATEGORIES:Work,Q4", "DTSTART;VALUE=DATE:20261010", "DUE;VALUE=DATE:20261012",
                    "DESCRIPTION:Line one\\nLine two\\, with comma", "URL:https://example.com/report", "X-MOZ-GENERATION:2",
                    "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER;VALUE=DURATION;RELATED=END:-P1D", "DESCRIPTION:Default Mozilla Description",
                    "END:VALARM"))
TPW = A.post(B + "/api/me/app-passwords", json={"name": "Thunderbird"}).json()["password"]
TB = dav("alice", TPW)
check(put(TB, WORK + "b4c1d2e3.ics", THUNDER, If_None_Match="*").status_code == 201, "Thunderbird: PUT creates")
t2 = by_uid("b4c1d2e3-f4a5-4b6c-9d8e-7f6a5b4c3d2e")
t = task(t2)
check(t["priority"] == 3 and t["status"] == 0 and t["due"] == "2026-10-12" and not t["due_time"] and t["start"] == "2026-10-10",
      "Thunderbird: PRIORITY 5 -> medium, IN-PROCESS = open, all-day DUE + DTSTART -> start")
check(t["content"] == "Line one\nLine two, with comma" and t["url"] == "https://example.com/report", "Thunderbird: description unescaped, URL")
check(tags(t2, ids["alice"]) == ["Q4", "Work"], "Thunderbird: CATEGORIES -> my tags")
check(t["reminders"] == "1980", f"Thunderbird: -P1D from an all-day due date = 1 day + the all-day time (09:00) ({t['reminders']})")
g2 = TB.get(B + WORK + "b4c1d2e3.ics").text.replace("\r\n ", "")
check("TRIGGER;RELATED=END:-P1D" in g2, "Thunderbird: the alarm comes back as -P1D")
check("DUE;VALUE=DATE:20261012" in g2 and "DTSTART;VALUE=DATE:20261010" in g2 and "X-MOZ-GENERATION:2" in g2,
      "Thunderbird: dates as dates, X-MOZ kept")
check("CATEGORIES:Q4,Work" in g2 and "DESCRIPTION:Line one\\nLine two\\, with comma" in g2, "Thunderbird: escaping both ways")

TASKSORG = vcal(todo("DTSTAMP:20261001T080000Z", "UID:3087123498712349871", "CREATED:20261001T080000Z", "LAST-MODIFIED:20261001T080000Z",
                     "SUMMARY:Buy milk", "PRIORITY:9", "DUE;VALUE=DATE:20261005", "RRULE:FREQ=WEEKLY;BYDAY=MO",
                     "CATEGORIES:home", "CATEGORIES:shop", "X-APPLE-SORT-ORDER:-123",
                     "BEGIN:VALARM", "TRIGGER;RELATED=END:PT0S", "ACTION:DISPLAY", "DESCRIPTION:Buy milk", "END:VALARM"))
OPW = A.post(B + "/api/me/app-passwords", json={"name": "Tasks.org"}).json()["password"]
TO = dav("alice", OPW)
check(put(TO, WORK + "3087123498712349871.ics", TASKSORG).status_code == 201, "Tasks.org: PUT creates")
t3 = by_uid("3087123498712349871")
t = task(t3)
check(t["priority"] == 1 and t["repeat"] == "FREQ=WEEKLY;BYDAY=MO" and t["due"] == "2026-10-05", "Tasks.org: PRIORITY 9 -> low, RRULE -> repeat")
check(tags(t3, ids["alice"]) == ["home", "shop"], "Tasks.org: two CATEGORIES lines")
check(t["reminders"] == "540", f"Tasks.org: PT0S on an all-day date = midnight = 9 h before the all-day time ({t['reminders']})")
g3 = TO.get(B + WORK + "3087123498712349871.ics").text.replace("\r\n ", "")
check("RRULE:FREQ=WEEKLY;BYDAY=MO" in g3 and "DTSTART;VALUE=DATE:20261005" in g3 and "TRIGGER;RELATED=END:PT0S" in g3,
      "Tasks.org: RRULE with a DTSTART anchor, the alarm back as PT0S")

# ---------------------------------------------------------------- ETags, conflicts, sync deltas, reports
R1 = WORK + "5E1C2A9B-3F4D-4E5F-8A9B-0C1D2E3F4A5B.ics"
check(put(AP, R1, APPLE, If_None_Match="*").status_code == 412, "If-None-Match: * on an existing resource: 412")
check(put(AP, R1, APPLE.replace("Call the bank", "Call the bank!"), If_Match='"stale"').status_code == 412, "If-Match with an old ETag: 412")
check(task(t1)["title"] == "Call the bank", "a refused PUT changes nothing")
check(put(AP, WORK + "nope.ics", APPLE.replace("5E1C2A9B", "FFFF"), If_Match=E1).status_code == 412, "If-Match on a missing resource: 412")
m0, tok0 = ms(sync(D, WORK))
check(tok0 and len(m0) == 3 and all(etag(e) for e in m0.values()), "sync-collection without a token: all 3 tasks + a token")
r = put(AP, R1, APPLE.replace("Call the bank", "Call the bank today"), If_Match=E1)
check(r.status_code == 204, "If-Match with the current ETag: 204")
check(task(t1)["title"] == "Call the bank today" and task(t1)["reminders"] == "0", "update: title changed, alarm kept")
E2 = AP.get(B + R1).headers["ETag"]
check(E2 != E1, "the ETag changes with the task")
m1, tok1 = ms(sync(D, WORK, tok0))
check(list(m1) == [R1] and etag(m1[R1]) == E2 and tok1 != tok0, "sync delta: only the changed task, with its new ETag")
m1b, tok1b = ms(sync(D, WORK, tok1))
check(m1b == {} and tok1b == tok1, "sync without changes: empty, same token")
A.patch(B + f"/api/tasks/{t2}", json={"title": "Write the report"})  # a change in the app
m2, tok2 = ms(sync(D, WORK, tok1))
r2 = WORK + "b4c1d2e3.ics"
check(list(m2) == [r2], "a change in the app shows up in the delta")
check("SUMMARY:Write the report" in TB.get(B + r2).text, "... and in GET")
A.delete(B + f"/api/tasks/{t2}")
m3, tok3 = ms(sync(D, WORK, tok2))
check(list(m3) == [r2] and "404" in m3[r2]["status"], "a task trashed in the app: removed (404) in the delta")
check(TB.get(B + r2).status_code == 404, "GET of a trashed task: 404")
A.post(B + f"/api/tasks/{t2}/restore")
m4, _ = ms(sync(D, WORK, tok3))
check(list(m4) == [r2] and etag(m4[r2]), "restored: back in the delta")
r = sync(D, WORK, "urn:kalmido:sync:999-0123456789abcdef0123")
check(r.status_code == 403 and b"valid-sync-token" in r.content, "an unknown sync-token: 403 valid-sync-token")
check(sync(D, HOME, tok0).status_code == 403, "a token of another list: 403")
# getctag follows the content
c1 = ms(req(D, "PROPFIND", WORK, PF_CAL, 0))[0][WORK]["props"]["{http://calendarserver.org/ns/}getctag"].text
A.patch(B + f"/api/tasks/{t3}", json={"priority": 5})
c2 = ms(req(D, "PROPFIND", WORK, PF_CAL, 0))[0][WORK]["props"]["{http://calendarserver.org/ns/}getctag"].text
check(c1 != c2, "getctag changes after a change")
# PROPFIND depth 1 on the calendar: members with ETags; depth 0: only the calendar
m, _ = ms(req(D, "PROPFIND", WORK, PF_CAL, 1))
check(len(m) == 4 and all(etag(e) for h, e in m.items() if h != WORK), "PROPFIND depth 1: the calendar + its 3 tasks with ETags")
check(len(ms(req(D, "PROPFIND", WORK, PF_CAL, 0))[0]) == 1, "PROPFIND depth 0: only the calendar")
# multiget
m, _ = ms(multiget(D, WORK, [R1, WORK + "missing.ics"]))
check("BEGIN:VTODO" in cdata(m[R1]) and etag(m[R1]) == E2 and "404" in m[WORK + "missing.ics"]["status"],
      "calendar-multiget: data + ETag, a missing href 404")
# calendar-query
Q = ('<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/></D:prop>'
     '<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="{0}">{1}</C:comp-filter></C:comp-filter></C:filter></C:calendar-query>')
check(len(ms(req(D, "REPORT", WORK, Q.format("VTODO", ""), 1))[0]) == 3, "calendar-query VTODO: all tasks")
check(len(ms(req(D, "REPORT", WORK, Q.format("VEVENT", ""), 1))[0]) == 0, "calendar-query VEVENT: nothing")
A.post(B + f"/api/tasks/{t1}/complete", json={})
open_only = Q.format("VTODO", '<C:prop-filter name="COMPLETED"><C:is-not-defined/></C:prop-filter>')
check(set(ms(req(D, "REPORT", WORK, open_only, 1))[0]) == {r2, WORK + "3087123498712349871.ics"}, "calendar-query: COMPLETED is-not-defined")
rng = Q.format("VTODO", '<C:time-range start="20261011T000000Z" end="20261013T000000Z"/>')
check(R1 not in ms(req(D, "REPORT", WORK, rng, 1))[0] and r2 in ms(req(D, "REPORT", WORK, rng, 1))[0], "calendar-query: time-range on the dates")
g = AP.get(B + R1).text
check("STATUS:COMPLETED" in g and "COMPLETED:" in g and "PERCENT-COMPLETE:100" in g, "completed in the app: STATUS / COMPLETED / 100 %")
A.post(B + f"/api/tasks/{t1}/reopen", json={})
check(req(D, "REPORT", WORK, "<x/>", 1).status_code == 403, "an unknown report: 403")
check(req(D, "PROPFIND", WORK, '<!DOCTYPE x [<!ENTITY a "b">]><D:propfind xmlns:D="DAV:"/>', 0).status_code == 400, "no DTDs / entities: 400")
u16 = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "b">]><D:propfind xmlns:D="DAV:"><D:prop>&a;</D:prop></D:propfind>'
check(req(D, "PROPFIND", WORK, u16.encode("utf-16"), 0).status_code == 400, "no DTDs / entities in a UTF-16 body either: 400")
late = '<?xml version="1.0"?><!--' + "x" * 5000 + '--><!DOCTYPE x [<!ELEMENT x ANY>]><D:propfind xmlns:D="DAV:"/>'
check(req(D, "PROPFIND", WORK, late, 0).status_code == 400, "a DOCTYPE after a long comment: 400")
check(req(D, "PROPFIND", WORK, "<not xml", 0).status_code == 400, "broken XML: 400")

# ---------------------------------------------------------------- status, repeat, subtasks, tags, moves, delete
def mk(uid, *lines):
    return vcal(todo(f"UID:{uid}", "DTSTAMP:20261001T080000Z", *lines))


R4 = WORK + "st-1.ics"
check(put(TO, R4, mk("st-1", "SUMMARY:Status test", "STATUS:NEEDS-ACTION")).status_code == 201, "status test task")
t4 = by_uid("st-1")
check(put(TO, R4, mk("st-1", "SUMMARY:Status test", "STATUS:COMPLETED", "COMPLETED:20261002T100000Z", "PERCENT-COMPLETE:100")).status_code == 204
      and task(t4)["status"] == 2, "STATUS:COMPLETED -> done")
check(any(a[0] == "complete" and '"caldav"' in a[1] for a in db("SELECT kind, data FROM activity WHERE task_id=?", (t4,))),
      "history: completed via CalDAV")
put(TO, R4, mk("st-1", "SUMMARY:Status test", "STATUS:NEEDS-ACTION"))
check(task(t4)["status"] == 0 and task(t4)["completed_at"] is None, "NEEDS-ACTION -> reopened")
put(TO, R4, mk("st-1", "SUMMARY:Status test", "STATUS:CANCELLED"))
check(task(t4)["status"] == -1, "CANCELLED -> won't do")
put(TO, R4, mk("st-1", "SUMMARY:Status test", "PERCENT-COMPLETE:100"))
check(task(t4)["status"] == 2, "PERCENT-COMPLETE:100 without STATUS -> done")
check(put(TO, WORK + "old-done.ics", mk("old-done", "SUMMARY:Old done", "STATUS:COMPLETED", "COMPLETED:20261001T090000Z")).status_code == 201
      and task(by_uid("old-done"))["status"] == 2 and task(by_uid("old-done"))["completed_at"].startswith("2026-10-01T09:00"),
      "created completed: done with the client's completion time")
# repeat: completing moves the task on, the done copy is a new resource
RR = WORK + "rr-1.ics"
put(TO, RR, mk("rr-1", "SUMMARY:Weekly", "DUE;VALUE=DATE:20261005", "RRULE:FREQ=WEEKLY;BYDAY=MO"))
t5 = by_uid("rr-1")
_, tk = ms(sync(TO, WORK))
put(TO, RR, mk("rr-1", "SUMMARY:Weekly", "DUE;VALUE=DATE:20261005", "RRULE:FREQ=WEEKLY;BYDAY=MO", "STATUS:COMPLETED"))
check(task(t5)["status"] == 0 and task(t5)["due"] == "2026-10-12", "completing a repeating task moves it to the next date")
md, _ = ms(sync(TO, WORK, tk))
check(RR in md and len(md) == 2, "sync: the moved task + the done copy as a new resource")
copy_href = next(h for h in md if h != RR)
check("STATUS:COMPLETED" in TO.get(B + copy_href).text and "RRULE" not in TO.get(B + copy_href).text, "the done copy has no RRULE")
put(TO, RR, mk("rr-1", "SUMMARY:Weekly", "DUE;VALUE=DATE:20261019", "RRULE:FREQ=WEEKLY;BYDAY=MO", "STATUS:NEEDS-ACTION"))
check(task(t5)["due"] == "2026-10-19" and task(t5)["status"] == 0, "a client that moves the date itself (Tasks.org) just changes the date")
RH = WORK + "rr-2.ics"
put(TO, RH, mk("rr-2", "SUMMARY:Hourly", "DUE;TZID=Europe/Berlin:20261005T100000", "RRULE:FREQ=HOURLY;INTERVAL=2"))
t6 = by_uid("rr-2")
check(task(t6)["repeat"] == "" and "RRULE:FREQ=HOURLY;INTERVAL=2" in TO.get(B + RH).text,
      "an RRULE Kalmido cannot repeat: no repeat in Kalmido, kept for the client")
put(TO, RH, mk("rr-2", "SUMMARY:Hourly", "DUE;TZID=Europe/Berlin:20261005T100000", "RRULE:FREQ=DAILY;COUNT=3"))
check(task(t6)["repeat"] == "FREQ=DAILY;COUNT=3" and TO.get(B + RH).text.split("BEGIN:VTODO")[1].count("RRULE") == 1, "switching to a supported rule replaces the kept one")
# subtasks: the child first (RELATED-TO to a UID that is not there yet), then the parent
check(put(TO, WORK + "child.ics", mk("child-1", "SUMMARY:Child", "RELATED-TO;RELTYPE=PARENT:parent-1")).status_code == 201, "child before parent")
tc = by_uid("child-1")
check(task(tc)["parent_id"] is None and "RELATED-TO;RELTYPE=PARENT:parent-1" in TO.get(B + WORK + "child.ics").text,
      "the parent UID is kept until the parent arrives")
put(TO, WORK + "parent.ics", mk("parent-1", "SUMMARY:Parent"))
tp = by_uid("parent-1")
check(task(tc)["parent_id"] == tp, "the parent arrives: the child becomes its subtask")
put(TO, WORK + "child2.ics", mk("child-2", "SUMMARY:Child 2", "RELATED-TO:parent-1"))
check(task(by_uid("child-2"))["parent_id"] == tp, "RELATED-TO without RELTYPE = parent")
put(TO, WORK + "child2.ics", mk("child-2", "SUMMARY:Child 2"))
check(task(by_uid("child-2"))["parent_id"] is None, "a client that writes RELATED-TO (Tasks.org) un-nests by leaving it out")
sub = A.post(B + "/api/tasks", json={"title": "Sub from the app", "parent_id": tp}).json()["id"]
mm, _ = ms(sync(D, WORK))
sh = next(h for h, e in mm.items() if f"kalmido-{sub}-" in h)
check("RELATED-TO;RELTYPE=PARENT:parent-1" in D.get(B + sh).text, "a subtask made in the app: RELATED-TO the parent's UID")
# tags: a client that never wrote CATEGORIES (Reminders) keeps them; one that did (Tasks.org) clears them by leaving them out
A.patch(B + f"/api/tasks/{t1}", json={"tags": ["bank", "calls"]})
put(AP, R1, APPLE.replace("Call the bank", "Call the bank again"))
check(tags(t1, ids["alice"]) == ["bank", "calls"], "Reminders (no CATEGORIES ever): tags set in the app stay")
put(TO, WORK + "3087123498712349871.ics", TASKSORG.replace("CATEGORIES:home\r\nCATEGORIES:shop\r\n", ""))
check(tags(t3, ids["alice"]) == [], "Tasks.org (writes CATEGORIES): leaving them out clears the tags")
# moving a task to another list: same UID in another calendar
mv = HOME + "moved.ics"
check(put(TO, mv, TASKSORG.replace("Buy milk", "Buy oat milk")).status_code == 201, "the same UID in another list (a move): 201")
check(task(t3)["list_id"] == home and task(t3)["title"] == "Buy oat milk" and by_uid("3087123498712349871") == t3,
      "moved: the same task, now in the other list (no copy)")
check(TO.get(B + WORK + "3087123498712349871.ics").status_code == 404 and TO.delete(B + WORK + "3087123498712349871.ics").status_code == 404,
      "the old address is gone (a following DELETE there does not touch it)")
check(task(t3)["deleted_at"] is None, "the moved task is not trashed")
check(put(TO, HOME + "other-name.ics", TASKSORG).status_code == 403, "the same UID twice in one list: 403 no-uid-conflict")
# DELETE -> trash, with If-Match
e = TO.get(B + mv).headers["ETag"]
check(TO.delete(B + mv, headers={"If-Match": '"stale"'}).status_code == 412, "DELETE with an old ETag: 412")
check(TO.delete(B + mv, headers={"If-Match": e}).status_code == 204 and task(t3)["deleted_at"], "DELETE: 204, the task is in the trash")
check(t3 in [x["id"] for x in A.get(B + "/api/trash").json().get("tasks", [])] if A.get(B + "/api/trash").ok else True, "visible in the trash")
put(TO, WORK + "parent.ics", mk("parent-1", "SUMMARY:Parent", "STATUS:COMPLETED"))
check(task(tc)["status"] == 2, "completing a parent completes its subtasks (as in the app)")
check(TO.delete(B + WORK + "parent.ics").status_code == 204 and task(tc)["deleted_at"], "deleting a parent trashes its subtasks")
check(req(TO, "DELETE", WORK).status_code == 403, "lists are not deleted over CalDAV")
check(req(TO, "MKCALENDAR", "/dav/calendars/alice/new/").status_code == 403, "MKCALENDAR: 403 (lists are made in the app)")
r = req(TO, "PROPPATCH", WORK, '<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><D:displayname>X</D:displayname></D:prop></D:set></D:propertyupdate>')
check(r.status_code == 207 and b"403" in r.content and task(t1)["list_id"] == work, "PROPPATCH: 207 with 403 per property")

# ---------------------------------------------------------------- roles: viewer, participant
T_ = f"/dav/calendars/alice/{shared}/"
ta = A.post(B + "/api/tasks", json={"title": "For carl", "list_id": shared, "assignee_id": ids["carl"]}).json()["id"]
tb = A.post(B + "/api/tasks", json={"title": "Secret of alice", "list_id": shared, "content": "notes"}).json()["id"]
BD, CD = dav("bob", BPW), dav("carl", CPW)
BT, CT_ = f"/dav/calendars/bob/{shared}/", f"/dav/calendars/carl/{shared}/"
mb, _ = ms(sync(BD, BT))
check(len(mb) == 2, "viewer: sees every task of the shared list")
hb = next(iter(mb))
check(put(BD, hb, BD.get(B + hb).text.replace("SUMMARY:", "SUMMARY:x")).status_code == 403, "viewer: PUT on a task 403")
check(put(BD, BT + "new.ics", mk("bob-new", "SUMMARY:Bob")).status_code == 403, "viewer: new task 403")
check(BD.delete(B + hb).status_code == 403, "viewer: DELETE 403")
check(db("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (shared,))[0][0] == 2, "viewer changed nothing")
mc, _ = ms(sync(CD, CT_))
check(len(mc) == 1 and "For carl" in CD.get(B + next(iter(mc))).text, "participant: only the task assigned to them")
check(all("Secret of alice" not in CD.get(B + h).text for h in mc), "participant: never the others' tasks")
hc = next(iter(mc))
check(put(CD, hc, CD.get(B + hc).text.replace("SUMMARY:For carl", "SUMMARY:For carl (done)")).status_code == 204
      and task(ta)["title"] == "For carl (done)", "participant: changes their own task")
check(put(CD, CT_ + "carl-new.ics", mk("carl-new", "SUMMARY:Carl's own")).status_code == 201, "participant: may add a task")
check(db("SELECT assignee_id FROM tasks WHERE id=?", (by_uid("carl-new"),))[0][0] == ids["carl"], "... which is assigned to them")
check(CD.delete(B + hc).status_code == 403, "participant: no DELETE")
privs = {p[0].tag.split("}")[1] for p in ms(req(CD, "PROPFIND", CT_, PF_CAL, 0))[0][CT_]["props"]["{DAV:}current-user-privilege-set"]}
check("unbind" not in privs and "write-content" in privs, f"participant privileges {privs}")
# ---------------------------------------------------------------- refused content
ev = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\nBEGIN:VEVENT\r\nUID:ev1\r\nDTSTART:20261001T100000Z\r\nSUMMARY:Event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
r = put(D, WORK + "ev1.ics", ev)
check(r.status_code == 403 and b"supported-calendar-component" in r.content, "an event: 403 supported-calendar-component")
check(put(D, WORK + "bad.ics", "hello").status_code == 415, "not iCalendar: 415")
check(put(D, WORK + "nouid.ics", vcal(todo("SUMMARY:No UID"))).status_code == 400, "no UID: 400")
check(put(D, WORK + "kalmido-1-00000000.ics", mk("x-1", "SUMMARY:x")).status_code in (201, 403), "foreign made-up names are just names")
check(put(D, WORK + "big.ics", mk("big", "SUMMARY:" + "x" * 1100000)).status_code == 413, "larger than max-resource-size: 413")
# ---------------------------------------------------------------- lockout
A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123"})
DPW = sess("dave").post(B + "/api/me/app-passwords", json={"name": "phone"}).json()["password"]
codes = [req(dav("dave", "wrong-pass-%d" % i), "PROPFIND", "/dav/", "", 0).status_code for i in range(10)]
check(codes == [401] * 10, "wrong app passwords: 401")
r = req(dav("dave", DPW), "PROPFIND", "/dav/", "", 0)
check(r.status_code == 429 and r.headers.get("Retry-After"), "after 10 failures the user name is locked (even the right password): 429")
check(req(D, "PROPFIND", "/dav/", "", 0).status_code == 207, "other people are not affected")
logs = subprocess.run(["docker", "logs", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
out = logs.stdout + logs.stderr
check("caldav login failed for 'dave'" in out and PW not in out and DPW not in out and "wrong-pass" not in out,
      "failed logins are logged without the password")
# ---------------------------------------------------------------- OIDC settings in the database (#438)
r = A.put(B + "/api/admin/oidc", json={"issuer": "https://id.example.com/realms/x", "client_id": "kalmido", "admin_domains": "example.com, @corp.example"})
check(r.status_code == 200 and r.json()["configured"] and r.json()["admin_domains"] == "corp.example, example.com", "OIDC stored: on, domains")
check(A.get(B + "/api/auth/info").json()["oidc"]["label"] == "OpenID Connect", "the login button shows")
r = A.put(B + "/api/admin/oidc", json={"client_secret": "s3cret"})
check(r.status_code == 400 and "KALMIDO_SECRET_KEY" in r.text, "a client secret needs KALMIDO_SECRET_KEY")
check(A.put(B + "/api/admin/oidc", json={"issuer": "ftp://x"}).status_code == 400, "an invalid issuer: 400")
check(A.put(B + "/api/admin/oidc", json={"admin_domains": "not a domain"}).status_code == 400, "an invalid domain: 400")
check(A.put(B + "/api/admin/oidc", json={"bogus": "1"}).status_code == 400, "unknown field: 400")
check(Bo.put(B + "/api/admin/oidc", json={"label": "x"}).status_code == 403, "only admins")
check(A.post(B + "/api/admin/oidc/check").json().get("ok") is False, "check: an unreachable provider is reported, not a crash")
KEY = "q1Zl1uX6QY0m6eS5jY3k0T8y3Jx4l2b0nVn3l9yY6qA="
start(f"-e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_OIDC_CLIENT_ID=from-env", keep=True)
A = sess("alice")
r = A.put(B + "/api/admin/oidc", json={"client_secret": "s3cret-value"})
o = r.json()
check(r.status_code == 200 and o["secret_set"] and o["client_id"] == "from-env" and o["env"] == ["client_id"],
      "secret stored with the key; the environment wins for client_id")
check(db("SELECT value FROM settings WHERE key='oidc_client_secret'")[0][0].startswith("v1.")
      and "s3cret-value" not in str(db("SELECT value FROM settings")), "the secret is sealed in the database")
check(A.put(B + "/api/admin/oidc", json={"client_id": "x"}).status_code == 409, "a field set by the environment: 409")
check("s3cret-value" not in A.get(B + "/api/state").text, "the secret never reaches a client")
start(f"-e KALMIDO_OIDC_CLIENT_ID=from-env", keep=True)
A = sess("alice")
o = A.get(B + "/api/state").json()["about"]["oidc"]
check(o["secret_lost"] and not o["secret_set"], "without the key the stored secret counts as not set (enter it again)")
# ---------------------------------------------------------------- plain http
start("-e PUBLIC_URL=http://kalmido.lan", keep=True)
check(req(D, "PROPFIND", "/dav/", "", 0).status_code == 403, "PUBLIC_URL http://: CalDAV refused (no passwords in clear text)")
start("-e PUBLIC_URL=http://kalmido.lan -e KALMIDO_CALDAV_HTTP=1", keep=True)
check(req(D, "PROPFIND", "/dav/", "", 0).status_code == 207, "KALMIDO_CALDAV_HTTP=1: allowed on purpose")
start("-e KALMIDO_CALDAV=0", keep=True)
check(req(D, "PROPFIND", "/dav/", "", 0).status_code == 404 and requests.get(B + "/.well-known/caldav", allow_redirects=False).status_code == 404,
      "KALMIDO_CALDAV=0: /dav and /.well-known/caldav are gone")
check(sess("alice").post(B + "/api/me/app-passwords", json={"name": "x"}).status_code == 409, "KALMIDO_CALDAV=0: no new app passwords")

print(f"p290_dav: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
