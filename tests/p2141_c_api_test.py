#!/usr/bin/env python3
"""2.141.0 API tests, part C: the disposition export as CSV / ICS (#2142) and the consent import from a CSV (#2143).
Invented names only, addresses @example.com.
 - export: CSV (BOM, header, one row per booking, hours of timed bookings, formula cells defused) and ICS (one VEVENT per booking,
   whole days with an exclusive end), the period and the filter of the view, deleted bookings out, another area's bookings
   out, a bad format / no module refused, a person without an organisation exports their own area
 - the calendar feed carries multi-day bookings of the person and not the deleted ones
 - import: preview names every problem line (no address, bad / future date, duplicate), nothing stored before "apply";
   dd.mm.yyyy and ISO, comma / semicolon, header or none; a consent that exists stays, unsubscribed / bounced stay, an address
   that is no contact is counted, not created; the proof carries the date and "Import: <file> · <source>"; limits; rights
   (members 403, other workspace 404, agents 403); a person without an organisation imports into their own space
usage: p2141_c_api_test.py <datadir>      (P2141C_NOSTART=1 = the server already runs)
freelancer-matrix: hub
tenant-matrix: newsletter"""
import os
import subprocess
import sys
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,collab,comments,events,contacts,dispo,workload,office"
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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P2141C_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = (ids[k] for k in ("bob", "carol", "dave", "erin"))
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB}).json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE}).json()["id"]
A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [BOB, CAROL], "admins": [BOB]})
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
dbx("DELETE FROM org_members WHERE user_id IN (?, ?)", (1, ERIN), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "nlbot", "display_name": "Nlbot"})
assert r.status_code == 201, r.text
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
S = {u: sess(u) for u in ("bob", "carol", "dave", "erin")}
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
Bo, Ca, Da, Er = S["bob"], S["carol"], S["dave"], S["erin"]
WA = f"org:{ALPHA}"
E = B + "/api/team/dispo/export"

# ---- disposition export
def book(s, title, start, end=None, who=None, **kw):
    r = s.post(B + "/api/team/dispo/bookings", json={"title": title, "start": start, **({"end": end} if end else {}), **kw,
                                                      "resources": [{"kind": "user", "id": who}]})
    assert r.status_code in (200, 201), r.text
    return r.json()["bookings"][0]["id"]


b1 = book(Bo, "Shoot day", "2026-11-17", "2026-11-19", CAROL, status="firm", note="=SUM(1)")
b2 = book(Bo, "Interview", "2026-11-18T10:00", "2026-11-18T13:30", BOB, status="option")
b3 = book(Bo, "Gone", "2026-11-18", None, BOB)
b4 = book(Bo, "Later", "2026-12-20", None, BOB)
bx = book(Da, "Beta job", "2026-11-17", None, DAVE)
Bo.delete(B + f"/api/team/dispo/bookings/{b3}")
q = {"start": "2026-11-16", "days": 7}
r = Bo.get(E, params={**q, "format": "csv"})
t = r.text
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "attachment" in r.headers.get("Content-Disposition", ""), f"csv: download ({r.status_code})")
check(t.startswith("﻿") and t.splitlines()[0].lstrip("﻿").split(",")[0] == "Resource", f"csv: BOM + header ({t[:60]!r})")
check("Shoot day" in t and "Interview" in t and "Gone" not in t and "Later" not in t and "Beta job" not in t,
      "csv: the period's bookings of this area, no deleted one")
check(",3.5," in t, "csv: hours of the timed booking")
check("'=SUM(1)" in t, "csv: a formula in the note is defused")
r = Bo.get(E, params={**q, "format": "ics"})
t = r.text
check(r.ok and r.headers["Content-Type"].startswith("text/calendar") and t.startswith("BEGIN:VCALENDAR") and t.count("BEGIN:VEVENT") == 2, f"ics: two events ({t.count('BEGIN:VEVENT')})")
check("DTSTART;VALUE=DATE:20261117" in t and "DTEND;VALUE=DATE:20261120" in t, "ics: the whole days end the day after")
check("DTSTART:20261118T100000" in t and "DTEND:20261118T133000" in t and "STATUS:TENTATIVE" in t and "STATUS:CONFIRMED" in t, "ics: timed event + status")
check("Beta job" not in t and "Gone" not in t, "ics: no other area, no deleted booking")
t = Bo.get(E, params={**q, "format": "csv", "filter": "tech"}).text
check("Shoot day" not in t and len(t.splitlines()) == 1, "filter 'equipment': only the header here")
t = Bo.get(E, params={"start": "2026-12-20", "days": 7, "format": "csv"}).text
check("Later" in t and "Shoot day" not in t, "another period")
check(Bo.get(E, params={**q, "format": "pdf"}).status_code == 400, "bad format 400")
check(Bo.get(E, params={**q, "days": "x"}).status_code == 400, "bad days 400")
check(requests.get(E, headers=AGH).status_code in (401, 403), "agents refused")
check(requests.get(E).status_code == 401, "no login 401")
Da.patch(B + "/api/settings", json={"features": "collab,contacts"})
check(Da.get(E, params=q).status_code == 409, "module off: 409")
Da.patch(B + "/api/settings", json={"features": FEAT})
# freelancer-matrix: hub
fb = book(Er, "Own job", "2026-11-17", None, ERIN)
t = Er.get(E, params={**q, "format": "csv"}).text
check("Own job" in t and "Shoot day" not in t, "a person without an organisation exports their own area")
check(Er.get(E, params={**q, "format": "ics"}).text.count("BEGIN:VEVENT") == 1, "freelancer: ics")
# calendar feed: the multi-day booking of carol, not the deleted one
r = Ca.get(B + "/api/calendars/events", params={"from": "2026-11-15", "to": "2026-11-22"})
t = r.text
check(r.ok and "Shoot day" in t, f"calendar: carol's multi-day booking is there ({r.status_code})")
check(Bo.get(B + "/api/calendars/events", params={"from": "2026-11-15", "to": "2026-11-22"}).text.count("Gone") == 0, "calendar: deleted booking not there")

# ---- consent import
r = Bo.post(B + "/api/books", json={"name": "Customers", "org_id": ALPHA})
BK = r.json()["id"]
Bo.post(B + f"/api/books/{BK}/org", json={"org_role": "edit"})


def contact(s, book_, fn, email):
    r = s.post(B + "/api/contacts", json={"book_id": book_, "fn": fn, "emails": [{"value": email}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def cons(s, cid):
    return s.get(B + f"/api/contacts/{cid}").json()["newsletter"]


C1, C2, C3, C4, C5 = (contact(Bo, BK, n, f"{n.lower()}@example.com") for n in ("Anna", "Ben", "Cleo", "Dora", "Emil"))
Bo.put(B + "/api/newsletter/consent", json={"ids": [C3], "status": "yes", "source": "Form"})
Bo.put(B + "/api/newsletter/consent", json={"ids": [C5], "status": "yes", "source": "Form"})
dbx("UPDATE contacts SET nl_status='unsub' WHERE id=?", (C5,), write=True)
future = (date.today() + timedelta(days=3)).isoformat()
CSV = ("E-Mail;Datum;Quelle\n"
       "anna@example.com;05.03.2025;Messe\n"
       "ben@example.com;2025-04-01;\n"
       "cleo@example.com;01.01.2024;Flyer\n"
       "emil@example.com;01.01.2024;Flyer\n"
       "nobody@example.com;01.01.2024;x\n"
       "not-an-address;01.01.2024;x\n"
       "dora@example.com;31.02.2025;x\n"
       f"dora@example.com;{future};x\n"
       "anna@example.com;06.03.2025;dup\n"
       ";01.01.2025;none\n")
IM = B + "/api/newsletter/consent/import"
r = Bo.post(IM, json={"ws": WA, "csv": CSV, "filename": "consents.csv"})
j = r.json() if r.ok else {}
check(r.ok and j["rows"] == 10 and j["valid"] == 5 and j["errors_count"] == 5, f"preview counts ({r.status_code} {r.text[:300]})")
check({(x["line"], x["code"]) for x in j.get("errors", [])} == {(7, "email"), (8, "date"), (9, "future"), (10, "dup"), (11, "email")},
      f"preview: line numbers + reasons ({j.get('errors')})")
check(j.get("will_change") == 2 and j.get("kept") == 2 and j.get("unmatched") == 1, f"preview: will change / kept / not a contact ({j})")
check(cons(Bo, C1)["status"] in ("", None) and cons(Bo, C2)["status"] in ("", None), "the preview stores nothing")
r = Bo.post(IM, json={"ws": WA, "csv": CSV, "filename": "consents.csv", "apply": True})
check(r.ok and r.json()["applied"] == 2, f"apply ({r.status_code} {r.text[:200]})")
n1 = cons(Bo, C1)
check(n1["status"] == "yes" and n1["at"].startswith("2025-03-05") and n1["source"] == "Import: consents.csv · Messe", f"the proof: date + source ({n1})")
check(cons(Bo, C2)["source"] == "Import: consents.csv" and cons(Bo, C2)["at"].startswith("2025-04-01"), "no source column value: the file name only")
check(cons(Bo, C3)["source"] == "Form" and cons(Bo, C5)["status"] == "unsub", "an existing consent stays, an unsubscribe stays")
check(len(dbx("SELECT id FROM contacts WHERE lower(emails) LIKE '%nobody@%'")) == 0, "no contact is created")
# header-less comma file, ISO date with time
r = Bo.post(IM, json={"ws": WA, "csv": "dora@example.com,2025-06-01T08:00:00Z,Web\n", "apply": True})
check(r.ok and r.json()["applied"] == 1 and cons(Bo, C4)["at"].startswith("2025-06-01"), f"no header, comma, ISO with time ({r.text[:200]})")
# limits + rights
check(Bo.post(IM, json={"ws": WA, "csv": ""}).status_code == 400, "empty file 400")
check(Bo.post(IM, json={"ws": WA, "csv": "a@example.com,2025-01-01\n" * 5001}).status_code == 400, "too many rows 400")
check(Bo.post(IM, json={"ws": WA, "csv": "x" * (2 * 1024 * 1024 + 1)}).status_code == 400, "too large 400")
check(Bo.post(IM, json={"ws": WA, "csv": CSV, "bogus": 1}).status_code == 400, "unknown field 400")
check(Ca.post(IM, json={"ws": WA, "csv": CSV}).status_code == 403, "a member cannot import")
check(Da.post(IM, json={"ws": WA, "csv": CSV}).status_code == 404, "another organisation 404")
check(requests.post(IM, json={"ws": WA, "csv": CSV}, headers=AGH).status_code in (401, 403), "agents refused")
# freelancer-matrix: newsletter
RB = Er.post(B + "/api/books", json={"name": "Erin clients", "org_id": None}).json()["id"]
EC = contact(Er, RB, "Fritz", "fritz@example.com")
r = Er.post(IM, json={"ws": "private", "csv": "fritz@example.com;02.02.2025;Card\n", "filename": "f.csv", "apply": True})
check(r.ok and r.json()["applied"] == 1 and cons(Er, EC)["status"] == "yes", f"a person without an organisation imports ({r.status_code} {r.text[:200]})")
check(Er.post(IM, json={"ws": WA, "csv": CSV}).status_code == 404, "...and not into an organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
