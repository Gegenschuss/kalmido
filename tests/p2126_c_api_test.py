#!/usr/bin/env python3
"""2.126.0 API tests, part C (#1976 #1977 #1985 #1986 #1991 + #1979 I1-I3 I6 + #1992 K4-K8 K10): limits, sync, calendars.
 - #1976: failed logins count per IPv6 /64 network (a new address in the same /64 is limited too, another /64 is not),
   IPv4 stays per exact address
 - #1977: many failed CalDAV logins from many addresses do not lock the person out; the address that failed stays limited
 - #1979 I2: a valid API token / public link works from an address that is limited for invalid ones
 - #1979 I1: the per-link budgets are shared per address (static check of the four places)
 - #1979 I3: an alarm / attachment a person's task app kept is sent back to that person only
 - #1979 I6: the test e-mail has a limit (when mail is set up)
 - #1985: RDATE of a repeating event: round trip over CalDAV, the extra dates show in the range
 - #1986: one background contacts import per person at a time (a second one = 409)
 - #1992 K4: a change of the place keeps the sent reminders, a change of the time resets them
 - #1992 K5: an imported (mirrored) address book is read only over CardDAV
 - #1992 K6: changed occurrences follow a moved series; a new rule drops the ones it no longer has
 - #1992 K8: two UIDs that differ only in characters a resource name cannot carry get two names
 - #1992 K10: a person without an organisation links a contact of a private book shared with them to a private client
freelancer-matrix: pim, own, office
usage: p2126_c_api_test.py <datadir>      (a fresh container; P2126C_NOSTART=1 = the server already runs)"""
import base64
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
ROOT = os.path.join(N, "..")


def login(user, pw, ip):
    return requests.post(B + "/api/auth/login", json={"username": user, "password": pw}, headers={**H, "X-Forwarded-For": ip}).status_code


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    r = c.execute(sql, args).fetchall()
    c.commit()
    return r


def dav(user, pw, m, path, body=None, ip=None, **h):
    hd = {"X-Forwarded-Proto": "https", **({"X-Forwarded-For": ip} if ip else {}), **{k.replace("_", "-"): v for k, v in h.items()}}
    return requests.request(m, B + path, auth=(user, pw), data=body.encode() if isinstance(body, str) else body, headers=hd,
                            allow_redirects=False)


def vcal(*comps):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n" + "".join(comps) + "END:VCALENDAR\r\n"


def comp(kind, *lines):
    return f"BEGIN:{kind}\r\n" + "".join(x + "\r\n" for x in lines) + f"END:{kind}\r\n"


def unfold(t):
    return t.replace("\r\n ", "").replace("\r\n\t", "")


def vcards(n, prefix):
    rnd = random.Random(11)
    ph = base64.b64encode(bytes(rnd.getrandbits(8) for _ in range(1500))).decode()
    out = []
    for i in range(n):
        out.append("\r\n".join(["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:Probe Person {i}", f"N:Person {i};Probe;;;",
                                f"EMAIL:probe.{i}@example.com", "PHOTO;ENCODING=b;TYPE=JPEG:" + ph, "END:VCARD"]) + "\r\n")
    return "".join(out)


if not os.environ.get("P2126C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True,
                                     "modules": ["cal", "comments", "events", "contacts"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "vic", "wes"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo = sess("bob")
for s_ in (A, Bo):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,events,contacts,collab,comments"})
FR_ID, FR = freelancer(B, A, "frida")
GUS_ID, GUS = freelancer(B, A, "gus")

# ============================================================ #1976: IPv6 per /64, IPv4 per address
codes = [login("vic", "wrong-pass", f"2001:db8:1:2::{i + 1}") for i in range(5)]
check(codes == [401] * 5, f"#1976: five wrong passwords from five addresses of one /64: 401 {codes}")
check(login("vic", "password123", "2001:db8:1:2::99") == 429, "#1976: a further address of that /64 is limited too")
check(login("vic", "password123", "2001:db8:1:3::1") == 200, "#1976: an address of another /64 signs in")
codes = [login("wes", "wrong-pass", "198.51.100.7") for _ in range(5)]
check(codes == [401] * 5 and login("wes", "password123", "198.51.100.7") == 429, f"#1976: IPv4: the address that failed is limited {codes}")
check(login("wes", "password123", "198.51.100.8") == 200, "#1976: IPv4: the next address is not (exact address)")

# ============================================================ #1977: CalDAV lock per name + address, never for the name alone
PWB = Bo.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
check(dav("bob", PWB, "PROPFIND", "/dav/", "", Depth="0").status_code == 207, "#1977: setup: bob's app password works")
n = 0
for a in range(16):  # 160 failures from 16 addresses (10 each: the limit of a pair), above the per-name ceiling of 150
    for _ in range(10):
        n += dav("bob", "wrong-app-password", "PROPFIND", "/dav/", "", ip=f"203.0.113.{a + 1}", Depth="0").status_code == 401
check(n == 160, f"#1977: 160 wrong app passwords answered 401 ({n})")
check(dav("bob", PWB, "PROPFIND", "/dav/", "", ip="203.0.113.200", Depth="0").status_code == 207,
      "#1977: bob still syncs from a new address after many failures elsewhere")
check(dav("bob", PWB, "PROPFIND", "/dav/", "", ip="203.0.113.1", Depth="0").status_code == 429,
      "#1977: the address that failed ten times stays limited for that name")

# ============================================================ #1979 I2: a valid token / link works from a limited address
TOK = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"], "expires_days": 30}).json()["token"]
IP2 = "192.0.2.44"
codes = [requests.get(V + "/me", headers={"Authorization": f"Bearer abk_{'q' * 30}{i:013d}", "X-Forwarded-For": IP2}).status_code
         for i in range(32)]
check(codes[-1] == 429 and codes[0] == 401, f"#1979 I2: invalid tokens from one address: 401, then 429 ({codes.count(401)} x 401)")
r = requests.get(V + "/me", headers={"Authorization": "Bearer " + TOK, "X-Forwarded-For": IP2})
check(r.status_code == 200, f"#1979 I2: a valid token from that address works ({r.status_code})")
L = A.post(B + "/api/lists", json={"name": "Shared view"}).json()["id"]
A.post(B + "/api/tasks", json={"list_id": L, "title": "Visible task"})
lk = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
PTOK = lk.json()["link"]["url"].split("/s/")[1] if lk.ok else ""
check(lk.ok and PTOK, f"#1979 I2: setup: a public link ({lk.status_code} {lk.text[:120]})")
IP3 = "192.0.2.45"
codes = [requests.get(B + f"/s/{'Z' * 31}{i % 10}", headers={"X-Forwarded-For": IP3}).status_code for i in range(32)]
check(codes[-1] == 429, f"#1979 I2: unknown links from one address end with 429 ({codes.count(404)} x 404)")
r = requests.get(B + f"/s/{PTOK}", headers={"X-Forwarded-For": IP3})
check(r.status_code == 200 and "Visible task" in r.text, f"#1979 I2: the valid link opens from that address ({r.status_code})")

# ============================================================ #1979 I1: per-link budgets shared per address (static)
srcs = {p: open(os.path.join(ROOT, p), encoding="utf-8").read() for p in
        ("kalmido/team/forms.py", "kalmido/lists/public.py", "kalmido/office/signoff.py", "kalmido/team/portal.py", "kalmido/api/common.py")}
# 2.149.0: the helper moved with the rate limits from api/v1.py into api/common.py (v1.py imports it)
check("def hit_budget(" in srcs["kalmido/api/common.py"], "#1979 I1: the shared budget helper exists")
for p, key in (("kalmido/team/forms.py", "formh:"), ("kalmido/lists/public.py", "pubfbl:"), ("kalmido/office/signoff.py", "sigl:"),
               ("kalmido/team/portal.py", "ptch:")):
    check(f'hit_budget(f"{key}' in srcs[p] and f'hit_limit(f"{key}' not in srcs[p], f"#1979 I1: {p}: the hourly budget is shared per address")

# ============================================================ #1979 I3: kept alarms / attachments go back to their writer only
TL = A.post(B + "/api/lists", json={"name": "Team todos"}).json()["id"]
A.put(B + f"/api/lists/{TL}/members", json={"user_id": uid["bob"], "role": "edit"})
PWA = A.post(B + "/api/me/app-passwords", json={"name": "Mac"}).json()["password"]
TODO = vcal(comp("VTODO", "UID:i3-todo-1", "DTSTAMP:20261020T100000Z", "SUMMARY:Pack the car", "X-PROBE-PROP:kept",
                 "ATTACH:https://files.example/plan.pdf",
                 "BEGIN:VALARM", "UID:AL-9", "TRIGGER;VALUE=DATE-TIME:19760401T005545Z", "ACTION:NONE", "X-APPLE-PROXIMITY:ARRIVE",
                 "END:VALARM"))
r = dav("alice", PWA, "PUT", f"/dav/calendars/alice/{TL}/i3-todo-1.ics", TODO, Content_Type="text/calendar", If_None_Match="*")
check(r.status_code in (201, 204), f"#1979 I3: alice's app stores a task with a kept alarm ({r.status_code} {r.text[:120]})")
ga = unfold(dav("alice", PWA, "GET", f"/dav/calendars/alice/{TL}/i3-todo-1.ics").text)
gb = unfold(dav("bob", PWB, "GET", f"/dav/calendars/bob/{TL}/i3-todo-1.ics").text)
check("X-APPLE-PROXIMITY:ARRIVE" in ga and "ATTACH:https://files.example/plan.pdf" in ga, "#1979 I3: alice gets her alarm and attachment back")
check("SUMMARY:Pack the car" in gb and "X-APPLE-PROXIMITY" not in gb and "ATTACH:" not in gb and "AL-9" not in gb,
      "#1979 I3: bob gets the task without alice's alarm and attachment " + gb[:400])
check("X-PROBE-PROP:kept" in gb, "#1979 I3: other kept properties still go to everyone")

# ============================================================ #1979 I6: the test e-mail is limited
codes = [A.post(B + "/api/me/mail/test").status_code for _ in range(7)]
check(codes[0] == 409 and set(codes) == {409} or 429 in codes[5:], f"#1979 I6: test e-mails: off (409) or limited after five {codes}")

# ============================================================ #1985: RDATE round trip + extra dates in the range
y = date.today().year + 1
for who, s, pw, user in (("alice", A, PWA, "alice"), ("frida", FR, None, "frida")):
    if pw is None:
        pw = s.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]  # freelancer-matrix: pim
    cal = s.post(B + "/api/evcals", json={"name": f"Series {who}"}).json()["id"]
    ev = vcal(comp("VEVENT", f"UID:rd-{who}", "DTSTAMP:20261020T100000Z", "SUMMARY:Choir", f"DTSTART:{y}0105T180000Z",
                   f"DTEND:{y}0105T190000Z", "RRULE:FREQ=WEEKLY;COUNT=3", f"RDATE:{y}0108T180000Z,{y}0110T180000Z",
                   "EXRULE:FREQ=MONTHLY;COUNT=1"))
    r = dav(user, pw, "PUT", f"/dav/calendars/{user}/e{cal}/rd-{who}.ics", ev, Content_Type="text/calendar", If_None_Match="*")
    check(r.status_code in (201, 204), f"#1985 {who}: the series with two extra dates is stored ({r.status_code} {r.text[:120]})")
    g = unfold(dav(user, pw, "GET", f"/dav/calendars/{user}/e{cal}/rd-{who}.ics").text)
    check(f"RDATE:{y}0108T180000Z,{y}0110T180000Z" in g and "RRULE:" in g and "EXRULE:FREQ=MONTHLY;COUNT=1" in g,
          f"#1985 {who}: GET gives the RDATE and EXRULE back " + g[g.find("BEGIN:VEVENT"):][:500])
    its = s.get(B + f"/api/events?from={y}-01-01&to={y}-01-31&calendar_id={cal}").json().get("items", [])
    days = sorted(x["start"][:10] for x in its)
    check(len(days) == 5 and f"{y}-01-08" in days and f"{y}-01-10" in days, f"#1985 {who}: three weekly + two extra dates {days}")

# ============================================================ #1986: one background import per person
BK = A.post(B + "/api/books", json={"name": "Big import"}).json()["id"]
text = vcards(1300, "c86")
r1 = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("a.vcf", text, "text/vcard")})
r2 = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("a.vcf", text, "text/vcard")})
check(r1.status_code == 202, f"#1986: the first background import starts ({r1.status_code} {r1.text[:120]})")
check(r2.status_code == 409 and "already running" in r2.text, f"#1986: a second one while it runs: 409 ({r2.status_code} {r2.text[:120]})")
iid, st = r1.json().get("import_id", "x"), {}
for _ in range(400):
    st = A.get(B + f"/api/books/imports/{iid}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.25)
check(st.get("state") == "done" and st.get("created") == 1300, f"#1986: the first import ends with all contacts {str(st)[:200]}")
FBK = FR.post(B + "/api/books", json={"name": "Frida import"}).json()["id"]  # freelancer-matrix: pim
r = FR.post(B + f"/api/books/{FBK}/import?background=1", files={"file": ("f.vcf", vcards(150, "f86"), "text/vcard")})
check(r.status_code == 202, f"#1986: a person without an organisation imports in the background ({r.status_code} {r.text[:120]})")

# ============================================================ #1992 K4: reminders reset only on a change of the time
KC = A.post(B + "/api/evcals", json={"name": "K4"}).json()["id"]
st0 = f"{y}-03-02T10:00"
K4 = A.post(B + "/api/events", json={"title": "Review", "cal_id": KC, "start": st0, "end": f"{y}-03-02T11:00", "reminders": [15]}).json()["id"]
dbx("INSERT INTO ev_reminded(event_id,user_id,k,at) VALUES(?,?,?,?)",  # a recent time: the watchdog forgets old rows
    (K4, uid["alice"], f"{st0}|15", datetime.now(timezone.utc).isoformat(timespec="seconds")))
check(A.patch(B + f"/api/events/{K4}", json={"location": "Room 2"}).ok, "#1992 K4: the place changes")
check(dbx("SELECT COUNT(*) FROM ev_reminded WHERE event_id=?", (K4,))[0][0] == 1, "#1992 K4: a sent reminder stays sent after a change of the place")
A.patch(B + f"/api/events/{K4}", json={"title": "Review (new title)", "start": st0, "end": f"{y}-03-02T11:00"})
check(dbx("SELECT COUNT(*) FROM ev_reminded WHERE event_id=?", (K4,))[0][0] == 1, "#1992 K4: ... also when the same time is sent along")
A.patch(B + f"/api/events/{K4}", json={"start": f"{y}-03-02T12:00", "end": f"{y}-03-02T13:00"})
check(dbx("SELECT COUNT(*) FROM ev_reminded WHERE event_id=?", (K4,))[0][0] == 0, "#1992 K4: a new time counts the reminders again")

# ============================================================ #1992 K5: a mirrored address book is read only over CardDAV
src = dbx("INSERT INTO contact_srcs(user_id,name,url,status,created_at) VALUES(?,?,?,?,?) RETURNING id",
          (uid["alice"], "Outside", "https://contacts.example/book", "error", "2026-01-01T00:00:00+00:00"))[0][0]
MB = A.post(B + "/api/books", json={"name": "Mirror"}).json()["id"]
dbx("UPDATE books SET src_id=? WHERE id=?", (src, MB))
CARD = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:k5-card\r\nFN:Mirror Probe\r\nN:Probe;Mirror;;;\r\nEND:VCARD\r\n"
r = dav("alice", PWA, "PUT", f"/dav/addressbooks/alice/b{MB}/k5-card.vcf", CARD, Content_Type="text/vcard")
check(r.status_code == 403, f"#1992 K5: PUT into the mirrored book: 403 ({r.status_code})")
r = dav("alice", PWA, "PUT", f"/dav/addressbooks/alice/b{BK}/k5-card.vcf", CARD, Content_Type="text/vcard")
check(r.status_code in (201, 204), f"#1992 K5: an own book still takes it ({r.status_code})")
dbx("UPDATE contacts SET book_id=? WHERE uid='k5-card'", (MB,))
r = dav("alice", PWA, "DELETE", f"/dav/addressbooks/alice/b{MB}/k5-card.vcf")
check(r.status_code == 403, f"#1992 K5: DELETE in the mirrored book: 403 ({r.status_code})")
pf = dav("alice", PWA, "PROPFIND", f"/dav/addressbooks/alice/b{MB}/", '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop>'
         '<D:current-user-privilege-set/></D:prop></D:propfind>', Depth="0")
check(pf.status_code == 207 and "<D:read/>" in pf.text and "<D:write/>" not in pf.text, "#1992 K5: the book shows as read only " + pf.text[:300])

# ============================================================ #1992 K6: changed occurrences follow a moved series
K6 = A.post(B + "/api/events", json={"title": "Standup", "cal_id": KC, "start": f"{y}-04-06T09:00", "end": f"{y}-04-06T09:15",
                                     "rrule": "FREQ=WEEKLY;COUNT=4"}).json()
r = A.patch(B + f"/api/events/{K6['id']}?occ={y}-04-13T09:00", json={"title": "Standup (long)"})
check(r.ok and len(r.json()["overrides"]) == 1, "#1992 K6: setup: one changed occurrence")
r = A.patch(B + f"/api/events/{K6['id']}", json={"title": "Standup", "start": f"{y}-04-06T09:00", "end": f"{y}-04-06T09:15"})
check(r.ok and len(r.json()["overrides"]) == 1, "#1992 K6: an edit without a new time keeps it")
# 2.126.0 review (#1992 K6): a moved series takes its changed occurrence along; a new rule drops the ones it no longer has
r = A.patch(B + f"/api/events/{K6['id']}", json={"start": f"{y}-04-07T10:00", "end": f"{y}-04-07T10:15"})
ov = r.json().get("overrides") if r.ok else None
check(ov and len(ov) == 1 and ov[0]["rid"] == f"{y}-04-14T10:00", f"#1992 K6: the series moves: the change moves along {r.text[:200]}")
r = A.patch(B + f"/api/events/{K6['id']}", json={"rrule": "FREQ=MONTHLY;COUNT=2"})
check(r.ok and r.json()["overrides"] == [], f"#1992 K6: a new rule without that date: the old change is dropped {r.text[:200]}")
its = A.get(B + f"/api/events?from={y}-04-01&to={y}-06-10&calendar_id={KC}").json().get("items", [])
check(len([x for x in its if x["eid"] == K6["id"]]) == 2 and not any(x["title"] == "Standup (long)" for x in its),
      "#1992 K6: two dates, no leftover single date")

# ============================================================ #1992 K8: unusual UIDs get distinct resource names
ICS = vcal(comp("VEVENT", "UID:k8:probe", "DTSTAMP:20261020T100000Z", "SUMMARY:One", f"DTSTART:{y}0601T100000Z", f"DTEND:{y}0601T110000Z"),
           comp("VEVENT", "UID:k8/probe", "DTSTAMP:20261020T100000Z", "SUMMARY:Two", f"DTSTART:{y}0602T100000Z", f"DTEND:{y}0602T110000Z"))
r = A.post(B + f"/api/evcals/{KC}/import", files={"file": ("k8.ics", ICS, "text/calendar")})
hrefs = [h for (h,) in dbx("SELECT href FROM events WHERE cal_id=? AND uid LIKE 'k8%'", (KC,))]
check(r.ok and len(hrefs) == 2 and len(set(hrefs)) == 2, f"#1992 K8: two events, two names {hrefs}")
ms = dav("alice", PWA, "PROPFIND", f"/dav/calendars/alice/e{KC}/", '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:getetag/>'
         '</D:prop></D:propfind>', Depth="1").text
check(all(h in ms for h in hrefs), "#1992 K8: both show over CalDAV")

# ============================================================ #1992 K10: a private client links a contact of a shared private book
a_, b_ = sorted((FR_ID, GUS_ID))
dbx("INSERT INTO conn_links(a_id,b_id,created_at) VALUES(?,?,?)", (a_, b_, "2026-01-01T00:00:00+00:00"))
GB = GUS.post(B + "/api/books", json={"name": "Gus shared"}).json()["id"]
GCT = GUS.post(B + "/api/contacts", json={"book_id": GB, "given": "Hanna", "family": "Probe", "emails": [{"value": "hanna@example.com"}]}).json().get("id")
r = GUS.put(B + f"/api/books/{GB}/members", json={"user_id": FR_ID, "role": "view"})
check(GCT and r.ok, f"#1992 K10: setup: gus shares his private book with frida ({r.status_code} {r.text[:120]})")
r = FR.post(B + "/api/clients", json={"name": "Frida's client", "contacts": [{"name": "Hanna"}]})  # freelancer-matrix: office
check(r.status_code == 201 and r.json().get("org_id") is None, f"#1992 K10: setup: frida's private client ({r.status_code} {r.text[:120]})")
FCL, FK = (r.json()["id"], r.json()["contacts"][0]["id"]) if r.ok else (0, 0)
got = {x["id"] for x in FR.get(B + f"/api/clients/{FCL}/book-contacts").json().get("contacts", [])}
check(GCT in got, f"#1992 K10: the client dialog offers the shared book's contact ({sorted(got)})")
r = FR.patch(B + f"/api/clients/{FCL}", json={"contacts": [{"id": FK, "name": "Hanna", "contact_id": GCT}]})
check(r.ok and r.json()["contacts"][0].get("contact_id") == GCT, f"#1992 K10: frida links it ({r.status_code} {r.text[:160]})")
bd = A.get(B + "/api/admin/orgs").json().get("boundary", {})
check(not bd.get("kinds", {}).get("client_contact"), f"#1992 K10: the nightly boundary check accepts the link {bd.get('kinds')}")
CB = Bo.post(B + "/api/books", json={"name": "Bob org book"}).json()["id"]
OCT = Bo.post(B + "/api/contacts", json={"book_id": CB, "given": "Org", "family": "Probe"}).json().get("id")
r = FR.patch(B + f"/api/clients/{FCL}", json={"contacts": [{"id": FK, "name": "Hanna", "contact_id": OCT}]})
check(r.status_code in (400, 404), f"#1992 K10: a contact frida cannot read is refused ({r.status_code})")

print(f"p2126_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
