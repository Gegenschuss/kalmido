#!/usr/bin/env python3
"""2.125.0 API tests, part B (#2119, #2120): monthly timesheets and the person's own time zone of time tracking, own container
(start.sh). Invented names only.
 - #2119 a member closes a past month: creating, changing, moving into it, deleting an entry of it -> 409 (never 500), the
   web API and API v1 (personal token: error code month_closed); "Delete all times of this project" leaves the locked entry;
   the entry list and the report mark the entry as locked; closing the current month locks the timer start (409)
 - the member reopens a closed month; after the approval only an admin of the organisation can (403 for the member)
 - an admin of the organisation sees the closed month (hours on the organisation's lists only, never private time), approves
   it, takes the approval back (Undo), sends it back with a note (the member gets the News item, the month is open again),
   takes the sending back (Undo); a member of the organisation cannot decide (403), an admin of another organisation gets 404
 - a person without an organisation closes and reopens alone, a decision about it is 404 (freelancer-matrix: time)
 - #2120 the setting tz (IANA name, '' = the server's, invalid -> 400): an entry 23:30-00:30 Europe/Berlin counts on two days
   (report days, CSV rows, totals the same, rounding split, not applied twice); in America/New_York the same entry is one day;
   the switch time_split_midnight off keeps one day / one row
usage: p2125_b_api_test.py <datadir>      (a fresh container; P2125B_NOSTART=1 = the server already runs)"""
import base64
import csv
import io
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import testclock  # noqa: E402
import dbx as dbxm  # noqa: E402  2.125.0 (#2119): the sealed note in the database

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "time,collab,comments"


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


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


if not os.environ.get("P2125B_NOSTART"):
    # 2.125.0 (#2119): with the master key, so the decision's note is sealed
    KEY = base64.b64encode(os.urandom(32)).decode()
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "erin" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done", "tz": "Europe/Berlin"})

now = testclock.now().astimezone(timezone.utc)  # 2.180.0 B (#2693): the test clock
BER = ZoneInfo("Europe/Berlin")
cur = now.astimezone(BER).date().replace(day=1)
prev = (cur - timedelta(days=1)).replace(day=1)
M, CUR = prev.strftime("%Y-%m"), cur.strftime("%Y-%m")
IN_M = datetime(prev.year, prev.month, 15, 10, 0, tzinfo=BER)

# a list of the organisation and a private one, both with time tracking
L = Bo.post(B + "/api/lists", json={"name": "Harbour site", "time_tracking": True}).json()["id"]
LP = Bo.post(B + "/api/lists", json={"name": "Own notes", "time_tracking": True, "org_id": None}).json()["id"]
E1 = Bo.post(B + "/api/time/entries", json={"list_id": L, "start": iso(IN_M), "minutes": 60, "note": "survey"}).json()["id"]
EP = Bo.post(B + "/api/time/entries", json={"list_id": LP, "start": iso(IN_M + timedelta(hours=2)), "minutes": 30}).json()["id"]
# 2.180.0 B (#2693): EC lies in the open month - not before its first Berlin midnight (on the 1st just after 0 o'clock
# "now - 50 min" was in the month that is closed below)
EC = Bo.post(B + "/api/time/entries", json={"list_id": L, "start": iso(max(now - timedelta(minutes=50), datetime(cur.year, cur.month, 1, tzinfo=BER))), "minutes": 20}).json()["id"]

# ================================================================ #2119: close, lock
r = Bo.get(B + "/api/time/sheets", params={"month": M})
j = r.json() if r.ok else {}
check(r.ok and j["sheet"]["state"] == "open" and j["can"]["close"] and not j["can"]["reopen"], "an open month " + r.text[:300])
check(Bo.get(B + "/api/time/sheets", params={"month": "2026-13"}).status_code == 400, "an invalid month: 400")
check(Bo.post(B + "/api/time/sheets", json={"month": M, "action": "nope"}).status_code == 400, "an unknown action: 400")
fut = (cur + timedelta(days=40)).strftime("%Y-%m")
check(Bo.post(B + "/api/time/sheets", json={"month": fut, "action": "close"}).status_code == 400, "a month in the future: 400")
# 2.125.0 R (#2119): bob looks at his private workspace -- the month still belongs to his organisation (approval)
check(Bo.patch(B + "/api/settings", json={"workspace": "private"}).ok, "bob shows the private workspace")
r = Bo.post(B + "/api/time/sheets", json={"month": M, "action": "close"})
check(r.ok and r.json()["sheet"]["state"] == "closed" and r.json()["sheet"]["org_id"] == ORG, "bob closes the month " + r.text[:300])
Bo.patch(B + "/api/settings", json={"workspace": "all"})
check(Bo.post(B + "/api/time/sheets", json={"month": M, "action": "close"}).status_code == 409, "closed twice: 409")
r = Bo.post(B + "/api/time/entries", json={"list_id": L, "start": iso(IN_M + timedelta(days=1)), "minutes": 30})
check(r.status_code == 409 and "closed" in r.json().get("error", ""), "a new entry in the closed month: 409 " + r.text[:200])
check(Bo.patch(B + f"/api/time/entries/{E1}", json={"note": "changed"}).status_code == 409, "changing its entry: 409")
check(Bo.delete(B + f"/api/time/entries/{E1}").status_code == 409, "deleting its entry: 409")
check(Bo.patch(B + f"/api/time/entries/{EC}", json={"start": iso(IN_M + timedelta(days=2))}).status_code == 409,
      "moving an entry into the closed month: 409")
check(Bo.patch(B + f"/api/time/entries/{EC}", json={"note": "fine"}).ok, "an entry of the open month stays changeable")
es = Bo.get(B + "/api/time/entries", params={"from": prev.isoformat(), "to": (cur - timedelta(days=1)).isoformat()}).json()["entries"]
check(any(e["id"] == E1 and e.get("locked") for e in es), "the entry list marks it as locked")
rp = Bo.get(B + "/api/time/report", params={"from": prev.isoformat(), "to": (cur - timedelta(days=1)).isoformat()}).json()
check(any(e["id"] == E1 and e.get("locked") for e in rp["entries"]), "the report marks it as locked")
# API v1 with the person's own token
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "time"], "expires_days": 30}).json().get("token")
V1 = {"Authorization": "Bearer " + str(tok)}
r = requests.post(V + "/time/entries", json={"list_id": L, "start": iso(IN_M + timedelta(days=3)), "minutes": 15}, headers=V1)
check(r.status_code == 409 and r.json().get("error", {}).get("code") == "month_closed", "API v1: month_closed " + r.text[:200])
r = requests.patch(V + f"/time/entries/{E1}", json={"note": "x"}, headers=V1)
check(r.status_code == 409 and r.json().get("error", {}).get("code") == "month_closed", "API v1 change: month_closed")
check(requests.delete(V + f"/time/entries/{E1}", headers=V1).status_code == 409, "API v1 delete: 409")
# "Delete all times of this project": the locked entry stays
pv = Bo.get(B + f"/api/lists/{L}/time/delete-all").json()
check(pv.get("locked") == 1, "the preview names the locked entry " + str(pv))
r = Bo.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Harbour site"})
check(r.ok and all(e["start"] != iso(IN_M) for e in r.json()["entries"]), "delete all: the locked entry is not deleted")
check(any(e["id"] == E1 for e in Bo.get(B + "/api/time/entries", params={"from": prev.isoformat()}).json()["entries"]), "... it is still there")
r = Bo.post(B + f"/api/lists/{L}/time/restore", json={"entries": r.json()["entries"]})
check(r.ok, "restore of the others")

# ================================================================ the decision
# tenant-matrix: timesheet
r = Ca.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"})
check(r.status_code == 403, "a member of the organisation cannot approve: 403 " + r.text[:200])
r = Er.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"})
check(r.status_code == 404, "an admin of another organisation: 404")
check(Bo.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"}).status_code == 403,
      "bob cannot approve his own month")
j = A.get(B + "/api/time/sheets", params={"month": M}).json()
x = next((r for r in j.get("review") or [] if r["user_id"] == uid["bob"] and r["month"] == M), None)
check(x is not None and x["state"] == "closed" and x["seconds"] == 3600, "the admin sees the closed month, only the organisation's hours " + str(x))
check(not (Ca.get(B + "/api/time/sheets", params={"month": M}).json().get("review")), "a member has no review list")
check(not (Er.get(B + "/api/time/sheets", params={"month": M}).json().get("review")), "another organisation's admin sees nothing")
r = A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"})
check(r.ok, "alice approves " + r.text[:200])
j = Bo.get(B + "/api/time/sheets", params={"month": M}).json()
check(j["sheet"]["state"] == "approved" and j["sheet"]["decided_by"] == uid["alice"] and not j["can"]["reopen"], "approved")
check(Bo.post(B + "/api/time/sheets", json={"month": M, "action": "reopen"}).status_code == 403, "bob cannot reopen an approved month")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "unapprove"}).ok, "Undo of the approval")
check(Bo.get(B + "/api/time/sheets", params={"month": M}).json()["sheet"]["state"] == "closed", "... closed again")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"}).ok, "approved again")
r = A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "return", "note": "Tuesday is missing"})
check(r.ok, "alice sends it back " + r.text[:200])
j = Bo.get(B + "/api/time/sheets", params={"month": M}).json()
check(j["sheet"]["state"] == "open" and j["sheet"]["note"] == "Tuesday is missing" and j["can"]["close"], "sent back: open with the note")
news = Bo.get(B + "/api/news").json().get("items", [])
check(any(n["kind"] == "tsheet" and n.get("data", {}).get("act") == "return" for n in news), "bob gets the News item")
# 2.125.0 (#2119): the note stays out of the News item (and the push); bob reads it in the app (sealed in time_sheets.note)
check(all("Tuesday is missing" not in str(n) for n in news if n["kind"] == "tsheet"), "the note is not in the News item")
_c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
try:
    _raw = str(_c.execute("SELECT note FROM time_sheets WHERE user_id=? AND month=?", (uid["bob"], M)).fetchone()[0])
    _nraw = str(_c.execute("SELECT data FROM notifications WHERE user_id=? AND kind='tsheet'", (uid["bob"],)).fetchall())
finally:
    _c.close()
check(_raw.startswith("kenc1:") and "Tuesday" not in _raw, "the note is sealed in the database " + _raw[:40])
check("Tuesday" not in _nraw, "the stored News data holds no note")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "restore"}).ok, "Undo of the sending back")
check(Bo.get(B + "/api/time/sheets", params={"month": M}).json()["sheet"]["state"] == "approved", "... approved again")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "restore"}).status_code == 409,
      "restore without a sending back: 409")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "return"}).ok, "sent back without a note")
check(Bo.patch(B + f"/api/time/entries/{E1}", json={"note": "fixed"}).ok, "open again: bob changes the entry")
check(Bo.post(B + "/api/time/sheets", json={"month": M, "action": "close"}).ok, "bob closes it again")
anews = A.get(B + "/api/news").json().get("items", [])
check(any(n["kind"] == "tsheet" and n.get("data", {}).get("act") == "closed" for n in anews), "the admin gets the closed month as News")
check(Bo.post(B + "/api/time/sheets", json={"month": M, "action": "reopen"}).ok, "bob reopens his closed month himself")
check(Bo.patch(B + f"/api/time/entries/{E1}", json={"note": "fixed again"}).ok, "... and changes it")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["bob"], "month": M, "action": "approve"}).status_code == 409,
      "an open month cannot be approved")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": 999999, "month": M, "action": "approve"}).status_code == 404, "unknown person: 404")

# the current month: the timer start is locked too
check(Bo.post(B + "/api/time/sheets", json={"month": CUR, "action": "close"}).ok, "bob closes the current month")
r = Bo.post(B + "/api/time/start", json={"list_id": L, "at": iso(now)})
check(r.status_code == 409, "timer start into a closed month: 409 " + r.text[:200])
check(Bo.post(B + "/api/time/sheets", json={"month": CUR, "action": "reopen"}).ok, "reopened")
check(Bo.post(B + "/api/time/start", json={"list_id": L}).ok, "the timer runs")
check(Bo.post(B + "/api/time/sheets", json={"month": CUR, "action": "close"}).status_code == 409, "closing with a running timer of it: 409")
Bo.post(B + "/api/time/stop", json={})

# 2.125.0 R (#2119): carol's approved month stays locked after she left the organisation; closing again is no 500
CL = Ca.post(B + "/api/lists", json={"name": "Carol private", "time_tracking": True, "org_id": None}).json()["id"]
CE = Ca.post(B + "/api/time/entries", json={"list_id": CL, "start": iso(IN_M), "minutes": 30}).json()["id"]
r = Ca.post(B + "/api/time/sheets", json={"month": M, "action": "close"})
check(r.ok and r.json()["sheet"]["org_id"] == ORG, "carol closes in the organisation " + r.text[:200])
check(A.post(B + "/api/time/sheets/decide", json={"user_id": uid["carol"], "month": M, "action": "approve"}).ok, "alice approves carol's month")
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['carol']}").ok, "carol leaves the organisation")
j = Ca.get(B + "/api/time/sheets", params={"month": M}).json()
check(j["sheet"]["state"] == "approved" and M in j["locked"] and j["can"]["reopen"], "left: her sheet stays approved " + str(j)[:300])
check(Ca.delete(B + f"/api/time/entries/{CE}").status_code == 409, "left: the entry stays locked")
r = Ca.post(B + "/api/time/sheets", json={"month": M, "action": "close"})
check(r.status_code == 409, f"left: closing again is 409, never 500 ({r.status_code})")
check(Ca.post(B + "/api/time/sheets", json={"month": M, "action": "reopen"}).ok, "left: she reopens it herself")
r = Ca.post(B + "/api/time/sheets", json={"month": M, "action": "close"})
check(r.ok and r.json()["sheet"]["org_id"] is None, "left: closing again works, now without an organisation " + r.text[:200])

# ================================================================ a person without an organisation
# freelancer-matrix: time
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"tz": "Europe/Berlin"})
FL = Fr.post(B + "/api/lists", json={"name": "Studio", "time_tracking": True}).json()["id"]
FE = Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": iso(IN_M), "minutes": 45}).json()["id"]
r = Fr.post(B + "/api/time/sheets", json={"month": M, "action": "close"})
check(r.ok and r.json()["sheet"]["state"] == "closed" and r.json()["sheet"]["org_id"] is None, "freelancer closes alone " + r.text[:200])
check(Fr.delete(B + f"/api/time/entries/{FE}").status_code == 409, "freelancer: locked")
check(Fr.get(B + "/api/time/sheets", params={"month": M}).json()["review"] is None, "freelancer: no review list")
check(Fr.post(B + "/api/time/sheets/decide", json={"user_id": FID, "month": M, "action": "approve"}).status_code == 404,
      "freelancer: no approval step (404)")
check(A.post(B + "/api/time/sheets/decide", json={"user_id": FID, "month": M, "action": "approve"}).status_code == 404,
      "an organisation's admin never decides about a freelancer")
check(Fr.post(B + "/api/time/sheets", json={"month": M, "action": "reopen"}).ok, "freelancer reopens")
check(Fr.delete(B + f"/api/time/entries/{FE}").ok, "freelancer: open again")

# ================================================================ #2120: time zone + midnight
check(Fr.patch(B + "/api/settings", json={"tz": "Mars/Base"}).status_code == 400, "an unknown time zone: 400")
D = (now.astimezone(BER) - timedelta(days=3)).date()
D1 = D + timedelta(days=1)
st = datetime(D.year, D.month, D.day, 23, 30, tzinfo=BER)
r = Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": iso(st), "minutes": 60, "note": "night"})
check(r.ok, "an entry 23:30-00:30 Berlin " + r.text[:200])
NE = r.json()["id"] if r.ok else 0
q = {"from": D.isoformat(), "to": D1.isoformat()}
rp = Fr.get(B + "/api/time/report", params=q).json()
days = {d["date"]: d["seconds"] for d in rp["days"]}
check(days == {D.isoformat(): 1800, D1.isoformat(): 1800}, "Berlin: two days of 30 min " + str(days))
check(rp["total"]["seconds"] == 3600 and rp["split"] is True and rp["tz"] == "Europe/Berlin", "the total stays one hour")
e = next((x for x in rp["entries"] if x["id"] == NE), {})
check(e.get("day") == D.isoformat() and len(e.get("parts") or []) == 2, "the entry stays one, with two parts")
c = Fr.get(B + "/api/time/export.csv", params=q)
rows = [x for x in csv.reader(io.StringIO(c.text.lstrip("﻿")), delimiter=",") if x][1:]
night = [x for x in rows if x[-1] == "night"]
check(len(night) == 2 and night[0][3].endswith("23:30") and night[0][4].endswith("00:00") and night[1][4].endswith("00:30"),
      "CSV: one row per day " + str(night))
check([x[6] for x in night] == ["0:30", "0:30"], "CSV: half an hour each")
# rounding: 23:50-00:10 rounded up to 15 min -> 30 min, split 15 / 15 (not rounded twice)
Fr.patch(B + "/api/settings", json={"time_rounding": "15"})
st2 = datetime(D1.year, D1.month, D1.day, 23, 50, tzinfo=BER)
NE2 = Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": iso(st2), "minutes": 20}).json()["id"]
rp = Fr.get(B + "/api/time/report", params={"from": D1.isoformat(), "to": (D1 + timedelta(days=1)).isoformat()}).json()
e = next((x for x in rp["entries"] if x["id"] == NE2), {})
check(e.get("rounded") == 1800 and [p["rounded"] for p in e.get("parts") or []] == [900, 900], "rounding once, split by share " + str(e.get("parts")))
check(sum(d["rounded"] for d in rp["days"]) == rp["total"]["rounded"], "the days add up to the total (rounded)")
Fr.patch(B + "/api/settings", json={"time_rounding": "0"})
# New York: the same entry is 17:30-18:30 on D, one day
check(Fr.patch(B + "/api/settings", json={"tz": "America/New_York"}).ok, "tz New York")
rp = Fr.get(B + "/api/time/report", params={"from": D.isoformat(), "to": D.isoformat()}).json()
e = next((x for x in rp["entries"] if x["id"] == NE), {})
check(e.get("day") == D.isoformat() and not e.get("parts"), "New York: one day " + str(e))
check({d["date"]: d["seconds"] for d in rp["days"]}.get(D.isoformat()) == 3600, "New York: an hour on D")
# the switch off: Berlin, one day, one CSV row
Fr.patch(B + "/api/settings", json={"tz": "Europe/Berlin", "time_split_midnight": "0"})
rp = Fr.get(B + "/api/time/report", params=q).json()
check({d["date"]: d["seconds"] for d in rp["days"]}.get(D.isoformat()) == 3600 and rp["split"] is False, "split off: the day of the start")
c = Fr.get(B + "/api/time/export.csv", params=q)
check(len([x for x in csv.reader(io.StringIO(c.text.lstrip("﻿"))) if x and x[-1] == "night"]) == 1, "split off: one CSV row")
check(Fr.patch(B + "/api/settings", json={"tz": ""}).ok, "back to the server's time zone")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
