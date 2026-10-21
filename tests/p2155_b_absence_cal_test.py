#!/usr/bin/env python3
"""2.155.0 API tests (part B, #2076 #2077): public holidays and absences in the calendar, their subscription link, and
the free / busy spans of the people one invites. Invented names only. Own container (start.sh, mode workspaces).
 - holidays: the events answer of the calendar views carries the holidays of the area's state (holiday: true), a person's
   own state wins (setting holiday_state, unknown = 400), Austria works offline too, cal_holidays 0 = none
 - absences: my own ones with their kind (absence "own"); the colleagues' only with cal_abs_team 1, only "away" (never the
   kind or the note), only of my own organisation, never of another one
 - the subscription link: none before create, the feed only with the right secret (wrong / old after rotate / off = 404),
   only my own absences + holidays, a sick leave says "Away", no note, Cache-Control no-store
 - free / busy: only spans (start, end, busy | away), never a title / place / calendar; an event shown as free
   (TRANSP:TRANSPARENT, busy false), an all-day and a cancelled one never count; skip leaves the edited event out;
   an absence / a half day / a holiday = away; people of another organisation are left out; a person without an
   organisation gets only their own bar (nobody else, not even by id)
 - a freelancer (no organisation): own state in the settings, own absences in the calendar, the link, the own bar
tenant-matrix: hub, calendar, ical
freelancer-matrix: hub, pim
usage: p2155_b_absence_cal_test.py <datadir>"""
import os
import subprocess
import sys
import urllib.parse
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,events,contacts,workload"
TZ = "Europe/Berlin"


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


def cal(s, lo, hi):
    r = s.get(B + "/api/calendars/events", params={"from": lo, "to": hi})
    assert r.ok, r.text
    return r.json()["events"]


def fb(s, day, users, **kw):
    return s.get(B + "/api/events/freebusy", params={"day": day, "users": ",".join(str(u) for u in users), "tz": TZ, **kw})


def slots(j, uid):
    for p in j["people"]:
        if p["user_id"] == uid:
            return [(x["start"], x["end"], x["kind"]) for x in p["slots"]]
    return None


if not os.environ.get("P2155B_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id!=?)", (ORG, BOB, CAROL, ORG2, DAVE), write=True)
FID, Fr = freelancer(B, A, "fiona")
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"}).ok

# ---- rollback: a new table and new settings only
t = {r[0] for r in dbx("SELECT table_name FROM information_schema.tables WHERE table_name='abs_cal_feeds'")}
check(t == {"abs_cal_feeds"}, f"new table abs_cal_feeds ({t})")
st = Ca.get(B + "/api/state").json()["settings"]
check(st.get("cal_holidays") == "1" and st.get("cal_abs") == "1" and st.get("cal_abs_team") == "0" and st.get("holiday_state") == "",
      "defaults: holidays + own absences on, the team's off, own state empty " + str({k: st.get(k) for k in ("cal_holidays", "cal_abs", "cal_abs_team", "holiday_state")}))

# ================================================================== #2076 holidays in the calendar views
check(not [e for e in cal(Ca, "2027-01-01", "2027-01-10") if e.get("holiday")], "no state anywhere: no holidays")
check(Bo.put(B + "/api/team/absences/holidays", json={"state": "BY"}).ok, "the admin sets Bavaria for Alpha")
hol = {e["start"]: e for e in cal(Ca, "2027-01-01", "2027-01-10") if e.get("holiday")}
check(set(hol) == {"2027-01-01", "2027-01-06"}, f"Bavaria: New Year + Epiphany ({sorted(hol)})")
h = hol.get("2027-01-01") or {}
check(h.get("all_day") is True and h.get("end") == "2027-01-02" and h.get("title") == "Neujahr" and not h.get("own"),
      "a holiday is a read-only all-day entry with its name " + str(h))
check(not [e for e in cal(Da, "2027-01-01", "2027-01-10") if e.get("holiday")], "Beta has no state: none for dave")
check(Ca.patch(B + "/api/settings", json={"holiday_state": "XX"}).status_code == 400, "an unknown own state: 400")
check(Ca.patch(B + "/api/settings", json={"holiday_state": "BE"}).ok, "carol picks Berlin for herself")
hol = {e["start"] for e in cal(Ca, "2027-01-01", "2027-03-10") if e.get("holiday")}
check("2027-01-06" not in hol and "2027-03-08" in hol and "2027-01-01" in hol, f"her own state wins over Alpha's ({sorted(hol)})")
j = Ca.get(B + "/api/team/absences/feed").json()
check(j["own"] == "BE" and j["state"] == "BE" and j["area"] == "BY" and "AT" in j["states"] and j["url"] is None,
      "the Calendars window learns the states, her choice, the area's one; no link yet " + str({k: j[k] for k in ("own", "state", "area", "url")}))
check(Ca.patch(B + "/api/settings", json={"cal_holidays": "0"}).ok and not [e for e in cal(Ca, "2027-01-01", "2027-03-10") if e.get("holiday")],
      "holidays switched off: none")
Ca.patch(B + "/api/settings", json={"cal_holidays": "1"})

# ================================================================== #2076 absences in the calendar views
D = date.today() + timedelta(days=21)
while D.weekday() >= 5:
    D += timedelta(days=1)
DS = D.isoformat()
D2 = (D + timedelta(days=1)).isoformat()
r = Ca.post(B + "/api/team/absences", json={"kind": "sick", "start_date": DS, "end_date": DS, "note": "Grippe vertraulich"})
check(r.status_code in (200, 201), "carol enters a sick leave " + r.text[:200])
SICK = r.json().get("id")
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D2, "end_date": D2, "half_day": "am"})
check(r.status_code in (200, 201), "and a morning off " + r.text[:200])
own = [e for e in cal(Ca, DS, D2) if e.get("absence")]
check(len(own) == 2 and all(e["absence"] == "own" and e["all_day"] for e in own), "her own absences are in her calendar " + str(own))
check(any(e["title"].startswith("Sick leave") for e in own) and any("morning" in e["title"] for e in own),
      "she sees her own kind and the half day " + str([e["title"] for e in own]))
check("Grippe" not in str(own), "the note never goes into the calendar")
check(Ca.patch(B + "/api/settings", json={"cal_abs": "0"}).ok and not [e for e in cal(Ca, DS, D2) if e.get("absence")], "own absences switched off")
Ca.patch(B + "/api/settings", json={"cal_abs": "1"})
check(not [e for e in cal(Bo, DS, D2) if e.get("absence")], "the team's absences are off by default")
check(Bo.patch(B + "/api/settings", json={"cal_abs_team": "1"}).ok, "bob switches the team's absences on")
tm = [e for e in cal(Bo, DS, D2) if e.get("absence")]
check(len(tm) == 2 and all(e["absence"] == "team" and e["user_id"] == CAROL and e["title"].startswith("Carol: away") for e in tm),
      "bob sees carol away, by name " + str([e.get("title") for e in tm]))
check("Sick" not in str(tm) and "Grippe" not in str(tm) and "Vacation" not in str(tm), "never the kind or the note of a colleague (not even for the admin)")
check(Da.patch(B + "/api/settings", json={"cal_abs_team": "1"}).ok and not [e for e in cal(Da, DS, D2) if e.get("absence")],
      "another organisation never sees them")
check(Bo.patch(B + "/api/settings", json={"workspace": "private"}).ok and not [e for e in cal(Bo, DS, D2) if e.get("absence") == "team"],
      "workspace switch on Private: no colleagues")
Bo.patch(B + "/api/settings", json={"workspace": "all"})

# ================================================================== #2076 the subscription link
check(Ca.post(B + "/api/team/absences/feed", json={"action": "bogus"}).status_code == 400, "an unknown action: 400")
url = Ca.post(B + "/api/team/absences/feed", json={"action": "create"}).json()["url"]
check(bool(url) and "/ical/abs/" in url, "create makes a link " + str(url))
P1 = urllib.parse.urlparse(url).path
check(Ca.post(B + "/api/team/absences/feed", json={"action": "create"}).json()["url"] == url, "create again keeps it")
r = requests.get(B + P1)
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/calendar") and "no-store" in r.headers.get("Cache-Control", ""),
      f"the feed: ICS, not cached ({r.status_code} {r.headers.get('Cache-Control')})")
ics = r.text.replace("\r\n ", "")
check("BEGIN:VCALENDAR" in ics and f"UID:absence-{SICK}@kalmido" in ics and f"DTSTART;VALUE=DATE:{DS.replace('-', '')}" in ics,
      "her sick leave is in it as an all-day event")
check("SUMMARY:Away" in ics and "Sick" not in ics and "Grippe" not in ics, "a sick leave says Away; no note")
check("SUMMARY:Neujahr" in ics and "TRANSP:TRANSPARENT" in ics, "the holidays of her state, shown as free")
D5 = (D + timedelta(days=5)).isoformat()  # not the day of the free / busy checks below
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D5, "end_date": D5})
BOBABS = r.json().get("id")
check(bool(BOBABS) and f"absence-{BOBABS}@" not in requests.get(B + P1).text, "nobody else's absence is in her feed")
fid, sec = P1.rsplit("/", 1)[1][:-4].split(".", 1)
check(requests.get(B + f"/ical/abs/{fid}.{sec[:-2]}xx.ics").status_code == 404, "a wrong secret: 404")
check(requests.get(B + f"/ical/abs/{int(fid) + 999}.{sec}.ics").status_code == 404, "an unknown id: 404")
url2 = Ca.post(B + "/api/team/absences/feed", json={"action": "rotate"}).json()["url"]
check(url2 and url2 != url and requests.get(B + P1).status_code == 404, "rotate: the old link stops at once")
P2 = urllib.parse.urlparse(url2).path
check(requests.get(B + P2).status_code == 200, "the new link works")
check(Bo.get(B + "/api/team/absences/feed").json()["url"] is None, "bob does not see carol's link")
check(Ca.post(B + "/api/team/absences/feed", json={"action": "off"}).json()["url"] is None and requests.get(B + P2).status_code == 404,
      "off removes it")

# ================================================================== #2077 free / busy
CB = Bo.post(B + "/api/evcals", json={"name": "Bob privat", "org_id": None}).json()["id"]


def ev(s, calid, title, a, b, **kw):
    r = s.post(B + "/api/events", json={"cal_id": calid, "title": title, "start": a, "end": b, "tz": TZ, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


E1 = ev(Bo, CB, "Geheimes Gespraech", f"{DS}T10:00", f"{DS}T11:30", location="Hinterzimmer")
ev(Bo, CB, "Nur Erinnerung", f"{DS}T14:00", f"{DS}T15:00", busy=False)
ev(Bo, CB, "Ganztags", DS, D2, all_day=True)
ev(Bo, CB, "Abgesagt", f"{DS}T16:00", f"{DS}T17:00", status="cancelled")
ev(Bo, CB, "Davor", f"{DS}T11:00", f"{DS}T12:00")
check(fb(Bo, DS, ["x"]).status_code == 400 and fb(Bo, DS, list(range(1, 23))).status_code == 400 and fb(Bo, "21.10.", [BOB]).status_code == 400,
      "bad users / too many / a bad day: 400")
r = fb(Ca, DS, [BOB, CAROL, DAVE, FID])
check(r.ok, "carol asks for bob, herself, dave and the freelancer " + r.text[:200])
j = r.json()
check({p["user_id"] for p in j["people"]} == {BOB, CAROL}, f"only people of her organisation (and herself) ({[p['user_id'] for p in j['people']]})")
check(slots(j, BOB) == [("10:00", "12:00", "busy")], f"bob: busy 10-12 merged; free / all-day / cancelled ones never count ({slots(j, BOB)})")
check(slots(j, CAROL) == [("00:00", "24:00", "away")], f"carol: away all day (sick leave) ({slots(j, CAROL)})")
check(not any(w in r.text for w in ("Geheim", "Hinterzimmer", "Bob privat", "Sick", "Grippe", "Erinnerung")), "no titles, places, calendars or kinds")
check(set(j["people"][0]) == {"user_id", "slots"} and set(j["people"][0]["slots"][0]) == {"start", "end", "kind"}, "nothing but spans " + str(j["people"][0]))
check(slots(fb(Bo, DS, [BOB], skip=E1).json(), BOB) == [("11:00", "12:00", "busy")], "skip leaves the edited event out")
# 2.155.0 review: skip only for an event of one's own (no probing of a colleague's event ids)
check(slots(fb(Ca, DS, [BOB], skip=E1).json(), BOB) == [("10:00", "12:00", "busy")], "skip of someone else's event is ignored")
check(slots(fb(Ca, D2, [CAROL]).json(), CAROL) == [("00:00", "12:00", "away")], "a morning off: away until noon")
check(slots(fb(Bo, "2027-01-06", [BOB]).json(), BOB) == [("00:00", "24:00", "away")], "a holiday of his state: away")
r = fb(Da, DS, [BOB, CAROL, DAVE])
check(r.ok and [p["user_id"] for p in r.json()["people"]] == [DAVE], "dave (another organisation) gets only himself")
r = fb(Bo, DS, [BOB], tz="../../etc/passwd")
check(r.ok and r.json()["tz"] != "../../etc/passwd", "a bad time zone falls back to the server's")

# ================================================================== freelancer: own state, own absences, link, own bar only
# freelancer-matrix: hub, pim
check(Fr.patch(B + "/api/settings", json={"holiday_state": "AT"}).ok, "the freelancer picks Austria")
hol = {e["start"]: e["title"] for e in cal(Fr, "2027-10-20", "2027-12-31") if e.get("holiday")}
check(hol.get("2027-10-26") == "Nationalfeiertag" and hol.get("2027-12-08") == "Mariä Empfängnis" and "2027-10-31" not in hol,
      f"Austria offline: national day + Immaculate Conception, no Reformation Day ({hol})")
r = Fr.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": DS, "end_date": D2})
check(r.status_code in (200, 201), "the freelancer enters a vacation " + r.text[:200])
fa = [e for e in cal(Fr, DS, D2) if e.get("absence")]
check(len(fa) == 1 and fa[0]["absence"] == "own" and fa[0]["title"] == "Vacation", "her vacation in her calendar " + str(fa))
check(Fr.patch(B + "/api/settings", json={"cal_abs_team": "1"}).ok and not [e for e in cal(Fr, DS, D2) if e.get("absence") == "team"],
      "no colleagues without an organisation")
fu = Fr.post(B + "/api/team/absences/feed", json={"action": "create"}).json()["url"]
fx = requests.get(B + urllib.parse.urlparse(fu).path).text
check("SUMMARY:Vacation" in fx and "Nationalfeiertag" in fx and f"absence-{SICK}@" not in fx, "her link: her vacation + Austria's holidays only")
CF = Fr.post(B + "/api/evcals", json={"name": "Fiona", "org_id": None}).json()["id"]
ev(Fr, CF, "Kunde", f"{DS}T09:00", f"{DS}T09:30")
r = fb(Fr, DS, [FID, BOB, CAROL, DAVE])
check(r.ok and [p["user_id"] for p in r.json()["people"]] == [FID], "the freelancer's bar: only herself, nobody else by id " + r.text[:200])
check(slots(r.json(), FID) == [("00:00", "24:00", "away"), ("09:00", "09:30", "busy")], f"her own spans ({slots(r.json(), FID)})")

print(f"p2155_b_absence_cal: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
