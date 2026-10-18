#!/usr/bin/env python3
"""2.79.0 API tests: fixes from the security audit #476 part 1 (own container via start.sh, isolated test database).
 - H1 (#1886): an ICS import never invites an account the importer may not see (another organisation): X-KALMIDO-USER /
   urn:kalmido:user:<id> of a stranger -> no attendee row with that user (the address stays as a plain address), no News
   item / invitation for the stranger; a person of the own organisation is still invited by id
 - M1 (#1887): POST /api/v1/me/app-passwords only with a token for all lists that has calendar + contacts
 - M2 (#1888): an admin token with read + admin-read cannot write PUT /api/v1/admin/announcement; with account it can
 - M4 (#1890): ~100 wrong invitation tokens from many addresses do not lock the links of everybody (per address only)
 - M5 (#1891): a child account has no API and no CalDAV; making an account a child removes its tokens and app passwords
 - M6 (#1892): time entries of a health list: not in /api/v1/time/entries for a token without "private" (also not the
   own ones), with "private" they are there
 - M8 (#1894): the backup archive takes agent chat files, budget receipts and document previews along (folder rule)
 - M9 (#1895): the default of KALMIDO_TRUSTED_PROXIES no longer contains the Docker bridge gateway (static check;
   the behaviour is in p2100_api_test.py)"""
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def D(n):
    return (testclock.today() + timedelta(days=n)).isoformat()


def tok(s, scopes, **extra):
    r = s.post(B + "/api/me/tokens", json={"name": "t", "scopes": scopes, "expires_days": 30, **extra})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def ics(*lines):
    ev = "BEGIN:VEVENT\r\n" + "".join(x + "\r\n" for x in lines) + "END:VEVENT\r\n"
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n" + ev + "END:VCALENDAR\r\n"


if not os.environ.get("P279_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True,
                                     "modules": ["cal", "comments", "events", "contacts", "family"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
for u in ("bob", "carol", "kiddo"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Ki = sess("bob"), sess("carol"), sess("kiddo")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
for s_ in (A, Bo, Ca, Ki):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
# two organisations: Alpha (alice, bob) and Beta (carol); alice may not see carol
ALPHA = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
BETA = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Beta', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u, o in (("alice", ALPHA), ("bob", ALPHA), ("kiddo", ALPHA), ("carol", BETA)):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (o, ids[u]))
CAROL, BOB = ids["carol"], ids["bob"]

# ============================================================ H1: ICS import invites only people the importer may see
CAL = A.post(B + "/api/evcals", json={"name": "Imported"}).json()["id"]
news0 = len([x for x in Ca.get(B + "/api/news").json().get("items", []) if x["kind"] == "evinvite"])
FILE = ics("UID:h1-probe-1", "DTSTAMP:20261005T100000Z", "SUMMARY:Click this link", "DTSTART:20261120T100000Z", "DTEND:20261120T110000Z",
           f"ATTENDEE;CN=Carol;X-KALMIDO-USER={CAROL}:mailto:someone@example.org",
           f"ATTENDEE;CN=Carol again:urn:kalmido:user:{CAROL}",
           f"ATTENDEE;CN=Bob;X-KALMIDO-USER={BOB}:urn:kalmido:user:{BOB}")
r = A.post(B + f"/api/evcals/{CAL}/import", files={"file": ("x.ics", FILE, "text/calendar")})
check(r.ok and r.json().get("created") == 1, f"H1: the file is imported {r.status_code} {r.text[:200]}")
ev = [x for x in A.get(B + f"/api/events?from=2026-11-01&to=2026-11-30&calendar_id={CAL}").json().get("items", [])]
check(len(ev) == 1, f"H1: one event {ev}")
if ev:
    e = A.get(B + f"/api/events/{ev[0]['eid']}").json()
    us = {a.get("user_id") for a in e.get("attendees", [])}
    mails = {a.get("email") for a in e.get("attendees", [])}
    check(CAROL not in us, f"H1: no attendee row for the stranger of another organisation {e.get('attendees')}")
    check("someone@example.org" in mails, f"H1: the address of that line stays a plain address {mails}")
    check(BOB in us, f"H1: a person of the own organisation is still invited by id {us}")
    check(Ca.get(B + f"/api/events/{ev[0]['eid']}").status_code in (403, 404), "H1: the stranger cannot open the event")
check(not dbx("SELECT 1 FROM event_attendees WHERE user_id=?", (CAROL,)), "H1: no attendee row with the stranger at all")
news1 = len([x for x in Ca.get(B + "/api/news").json().get("items", []) if x["kind"] == "evinvite"])
check(news1 == news0, f"H1: no invitation in the stranger's News ({news0} -> {news1})")

# ============================================================ M1: app passwords only from full calendar + contacts tokens
r = requests.post(V + "/me/app-passwords", headers=tok(A, ["read", "account"]), json={"name": "x"})
check(r.status_code == 403, f"M1: account alone: 403 {r.status_code}")
r = requests.post(V + "/me/app-passwords", headers=tok(A, ["read", "write"]), json={"name": "x"})
check(r.status_code == 403, f"M1: legacy write: 403 {r.status_code}")
LL = A.post(B + "/api/lists", json={"name": "Only this"}).json()["id"]
r = requests.post(V + "/me/app-passwords", headers=tok(A, ["read", "account", "calendar", "contacts"], list_ids=[LL]), json={"name": "x"})
check(r.status_code == 403, f"M1: a token limited to lists: 403 {r.status_code} {r.text[:200]}")
n_pw = dbx("SELECT COUNT(*) FROM app_passwords WHERE user_id=1")[0][0]
check(n_pw == 0, "M1: no app password was created by the refused requests")
r = requests.post(V + "/me/app-passwords", headers=tok(A, ["read", "account", "calendar", "contacts"]), json={"name": "Phone"})
check(r.status_code == 201 and r.json().get("password"), f"M1: a full token with calendar + contacts: 201 {r.status_code} {r.text[:200]}")

# ============================================================ M2: admin routes need their own scope too
r = requests.put(V + "/admin/announcement", headers=tok(A, ["read", "admin-read"]), json={"text": "Maintenance", "level": "maintenance"})
check(r.status_code == 403, f"M2: read + admin-read cannot set the announcement {r.status_code} {r.text[:200]}")
check(not A.get(B + "/api/state").json().get("announce"), "M2: no announcement was set")
r = requests.put(V + "/admin/announcement", headers=tok(A, ["read", "admin-read", "account"]), json={"text": ""})
check(r.ok, f"M2: with account it works {r.status_code} {r.text[:200]}")
r = requests.get(V + "/admin/status", headers=tok(A, ["read", "admin-read"]))
check(r.ok, f"M2: reading admin data stays possible with admin-read {r.status_code}")

# ============================================================ M4: no server-wide lock of the token links
for i in range(21):  # 105 wrong tokens from 21 addresses (5 each: below every per-address limit)
    for _ in range(5):
        requests.post(B + "/api/auth/invite/check", json={"token": "x" * 43}, headers={**H, "X-Forwarded-For": f"10.79.0.{i + 1}"})
r = requests.post(B + "/api/auth/invite/check", json={"token": "y" * 43}, headers={**H, "X-Forwarded-For": "10.79.1.1"})
check(r.status_code == 404, f"M4: after 105 wrong tokens from other addresses a new address is not locked {r.status_code}")
r = requests.post(B + "/api/auth/invite/check", json={"token": "y" * 43}, headers={**H, "X-Forwarded-For": "10.79.0.1"})
check(r.status_code == 429, f"M4: the address that failed 5 times is still limited {r.status_code}")

# ============================================================ M5: child accounts: no API, no CalDAV
KT = tok(Ki, ["read", "write"])
check(requests.get(V + "/lists", headers=KT).ok, "M5: before: the token works")
KPW = requests.post(V + "/me/app-passwords", headers=tok(Ki, ["read", "account", "calendar", "contacts"]), json={"name": "Phone"}).json().get("password")
check(bool(KPW), "M5: before: an app password exists")
dav = lambda pw: requests.request("PROPFIND", B + "/dav/", auth=("kiddo", pw), headers={"Depth": "0", "X-Forwarded-Proto": "https"})  # noqa: E731
check(dav(KPW).status_code == 207, f"M5: before: CalDAV works {dav(KPW).status_code}")
r = A.patch(B + f"/api/users/{ids['kiddo']}", json={"kid": True})
check(r.ok, f"M5: kiddo becomes a child account {r.status_code} {r.text[:200]}")
check(requests.get(V + "/lists", headers=KT).status_code == 401, "M5: the old token stops")
check(dav(KPW).status_code == 401, f"M5: the old app password stops {dav(KPW).status_code}")
check(not dbx("SELECT 1 FROM api_tokens WHERE user_id=?", (ids["kiddo"],)), "M5: the child's tokens are deleted")
check(not dbx("SELECT 1 FROM app_passwords WHERE user_id=?", (ids["kiddo"],)), "M5: the child's app passwords are deleted")
check(Ki.get(B + "/api/state").ok, "M5: the web session of the child keeps working")

# ============================================================ M6: time entries of health lists need "private"
HL = A.post(B + "/api/lists", json={"name": "Physio", "time_tracking": True}).json()["id"]
HT = A.post(B + "/api/tasks", json={"title": "Knee therapy", "list_id": HL}).json()["id"]
r = A.post(B + "/api/time/entries", json={"task_id": HT, "start": D(-1) + "T09:00", "minutes": 45, "note": "left knee"})
check(r.ok, f"M6: setup: a time entry {r.status_code} {r.text[:200]}")
check(A.patch(B + f"/api/lists/{HL}", json={"life": "health"}).ok, "M6: setup: the list becomes a health list")
q = {"from": D(-3), "to": D(0)}
r = requests.get(V + "/time/entries", params=q, headers=tok(A, ["read", "time"]))
blob = r.text
check(r.ok and "Knee therapy" not in blob and "left knee" not in blob, f"M6: no title / note of the health task without private {r.status_code} {blob[:300]}")
r = requests.get(V + "/time/entries", params=q, headers=tok(A, ["read", "time", "private"]))
check(r.ok and "Knee therapy" in r.text, f"M6: with private the entry is there {r.status_code} {r.text[:300]}")
check("Knee therapy" in A.get(B + "/api/time/entries", params=q).text, "M6: the app (session) shows it as before")

# ============================================================ M8: the backup takes all kinds of stored files along
for rel in ("attachments/chat/7-1/probe-chat.txt", "attachments/budget/9/probe-receipt.txt", "attachments/docthumbs/5-probe.jpg",
            "attachments/wiki/3/probe-wiki.pdf"):  # 2.99.0 (#2182, review H1): the files of knowledge pages
    p = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("probe")
os.makedirs(os.path.join(DATA, "attachments", ".wikitmp"), exist_ok=True)  # 2.99.0 (#2182): a wiki export being written
with open(os.path.join(DATA, "attachments", ".wikitmp", "export-probe.zip"), "w") as f:
    f.write("probe")
n0 = len(A.get(B + "/api/admin/backups").json().get("items", []))
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"M8: a backup is started {r.status_code} {r.text[:200]}")
st = {}
for _ in range(100):  # it runs in the background
    st = A.get(B + "/api/admin/backups").json()
    if not st.get("running") and (len(st.get("items", [])) > n0 or st.get("last_error")):
        break
    time.sleep(0.3)
names, man = [], {}
items = st.get("items") or []
name = st.get("last_name") or ((items[0] or {}).get("name") if items else None)
path = os.path.join(DATA, "backups", name or "-")
if name and os.path.isfile(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        man = json.loads(z.read("manifest.json"))
check(bool(names), f"M8: the archive is there ({name}, {st.get('last_error')})")
check(man.get("skipped_files") == 0, f"M8: nothing skipped ({man.get('skipped_files')})")
check(not any(".wikitmp" in x for x in names), "2.99.0 (#2182): the temporary wiki export stays out of the archive")
for rel in ("attachments/chat/7-1/probe-chat.txt", "attachments/budget/9/probe-receipt.txt", "attachments/docthumbs/5-probe.jpg",
            "attachments/wiki/3/probe-wiki.pdf"):  # 2.99.0 (#2182, review H1): the files of knowledge pages
    check(rel in names, f"M8: {rel} is in the archive")

# ============================================================ M9: the default of the trusted proxies
cfg = open(os.path.join(os.path.dirname(N), "kalmido", "core", "config.py")).read()
m = re.search(r'os\.environ\.get\("KALMIDO_TRUSTED_PROXIES", "([^"]*)"\)', cfg)
check(m and m.group(1).replace(" ", "") == "127.0.0.1,::1", f"M9: default loopback only, no docker gateway ({m and m.group(1)})")

print(f"p279_sec_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
