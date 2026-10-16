#!/usr/bin/env python3
"""2.50.0 API tests, part A (#1195 absences, #1194 resources and disposition). Invented names only.
 - absences: everyone enters their own; an organisation's admin also for its members, a member not for others
 - the team sees "away" and the period, never the kind / note (sick leave); the person and the admins see them
 - another organisation: nothing (list, check, edit, delete: 404); delete = Undo (restore)
 - German public holidays per state (Easter formula): Good Friday / Whit Monday / Reformation Day / Buss- und Bettag
 - workload: capacity 0 in a week away; the day plan: a hint instead of a proposal; the assign check: "absent" only
 - people without an organisation (freelancers): their own absences in their personal area
 - disposition: booking people / contacts / equipment / sets, option and firm, double bookings and absences = warnings
   (never blocked), "who is free", the booked person sees their own bookings, guests / other organisations: no access
 - rollback: only new tables / columns
tenant-matrix: hub
usage: p250_a_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
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


if not os.environ.get("P250A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
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
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
# erin: no organisation at all (a freelancer)
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id!=?) OR user_id=?",
    (ORG, BOB, CAROL, ORG2, DAVE, ERIN), write=True)
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")

# ---- rollback: new tables / columns only
t = {r[0] for r in dbx("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'hub_%'")}
check("hub_absences" in t, f"new table hub_absences ({t})")
check(dbx("SELECT 1 FROM information_schema.columns WHERE table_name='orgs' AND column_name='hub_holiday_state'"), "new column orgs.hub_holiday_state")

# ---- absences: own, by an admin, not by a member for others
D1 = "2026-11-02"  # a Monday
r = Ca.post(B + "/api/team/absences", json={"kind": "sick", "start_date": D1, "end_date": "2026-11-06", "note": "flu"})
check(r.status_code == 201 and r.json()["kind"] == "sick", f"carol enters her own sick leave ({r.status_code} {r.text[:200]})")
SICK = r.json()["id"]
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D1, "user_id": BOB})
check(r.status_code == 403, f"a member cannot enter an absence for somebody else ({r.status_code})")
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2026-11-10", "end_date": "2026-11-10", "half_day": "am", "user_id": CAROL})
check(r.status_code == 201, f"the organisation's admin enters an absence for carol ({r.status_code} {r.text[:200]})")
HALF = r.json()["id"]
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D1, "user_id": DAVE})
check(r.status_code == 404, f"the admin cannot enter an absence for a person of another organisation ({r.status_code})")
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2026-11-10", "end_date": "2026-11-12", "half_day": "pm"})
check(r.status_code == 400, f"a half day spans one day only ({r.status_code})")
r = Bo.post(B + "/api/team/absences", json={"kind": "holiday", "start_date": D1})
check(r.status_code == 400, f"unknown kind: 400 ({r.status_code})")
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2026-11-09", "end_date": "2026-11-01"})
check(r.status_code == 400, f"end before start: 400 ({r.status_code})")
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2026-11-16", "end_date": "2026-11-20"})
check(r.status_code == 201, "bob enters his own vacation")
VAC = r.json()["id"]

# ---- visibility: the team sees "away" only; the person and the admins see the kind
q = {"start": "2026-11-01", "end": "2026-11-30"}
j = Bo.get(B + "/api/team/absences", params=q).json()
mine = {x["id"]: x for x in j["items"]}
check(mine.get(SICK, {}).get("kind") == "sick" and mine[SICK].get("note") == "flu", "the admin sees carol's kind and note")
check(j["admin"] is True and {p["id"] for p in j["people"]} == {BOB, CAROL}, f"people of Alpha ({[p['id'] for p in j['people']]})")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, CAROL), write=True)
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, BOB), write=True)
j = Bo.get(B + "/api/team/absences", params=q).json()
it = {x["id"]: x for x in j["items"]}
check(SICK in it and "kind" not in it[SICK] and "note" not in it[SICK], f"a team member sees carol 'away' only, no kind ({it.get(SICK)})")
check(it[SICK]["start_date"] == D1 and it[SICK]["end_date"] == "2026-11-06", "the team sees the period")
check(it.get(VAC, {}).get("kind") == "vacation", "bob still sees his own kind")
check(not it[SICK].get("can_edit"), "a member cannot edit carol's absence")
check(Bo.patch(B + f"/api/team/absences/{SICK}", json={"note": "x"}).status_code == 403, "a member: no edit of others (403)")
check(Bo.delete(B + f"/api/team/absences/{SICK}").status_code == 403, "a member: no delete of others (403)")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, BOB), write=True)
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, CAROL), write=True)
# another organisation: nothing
j = Da.get(B + "/api/team/absences", params=q).json()
check(not j["items"] and {p["id"] for p in j["people"]} == {DAVE}, "another organisation sees no absence of Alpha")
check(Da.get(B + "/api/team/absences", params={**q, "org": ORG}).status_code == 404, "another organisation's area: 404")
check(Da.patch(B + f"/api/team/absences/{SICK}", json={"note": "x"}).status_code == 404, "another organisation: no edit (404)")
check(Da.delete(B + f"/api/team/absences/{SICK}").status_code == 404, "another organisation: no delete (404)")
check(Da.get(B + "/api/team/absences/check", params={"user": CAROL, "date": D1}).json().get("absent") is False, "check across organisations: nothing")
r = Bo.get(B + "/api/team/absences/check", params={"user": CAROL, "date": "2026-11-03"}).json()
check(r.get("absent") is True and "kind" not in r, f"check: 'absent' without the kind ({r})")
check(Bo.get(B + "/api/team/absences/check", params={"user": CAROL, "date": "2026-11-09"}).json().get("absent") is False, "check: back the next week")

# ---- edit, delete = Undo
r = Ca.patch(B + f"/api/team/absences/{SICK}", json={"end_date": "2026-11-05"})
check(r.ok and r.json()["end_date"] == "2026-11-05", "carol edits her own absence")
check(Ca.delete(B + f"/api/team/absences/{HALF}").ok, "carol deletes an absence an admin entered for her")
check(not any(x["id"] == HALF for x in Bo.get(B + "/api/team/absences", params=q).json()["items"]), "deleted: gone from the list")
check(Ca.post(B + f"/api/team/absences/{HALF}/restore").ok, "Undo: restore")
check(any(x["id"] == HALF for x in Bo.get(B + "/api/team/absences", params=q).json()["items"]), "restored: back in the list")

# ---- public holidays (state of the organisation; admins only)
check(Ca.put(B + "/api/team/absences/holidays", json={"state": "BY"}).status_code == 403, "a member cannot set the state")
check(Bo.put(B + "/api/team/absences/holidays", json={"state": "XX"}).status_code == 400, "unknown state: 400")
check(Bo.put(B + "/api/team/absences/holidays", json={"state": "SN"}).ok, "the admin sets Saxony")
j = Ca.get(B + "/api/team/absences", params={"start": "2026-03-01", "end": "2026-12-31"}).json()
hol = {h["date"]: h["name"] for h in j["holidays"]}
check(hol.get("2026-04-03") == "Karfreitag" and "2026-05-25" in hol, f"Good Friday + Whit Monday 2026 ({sorted(hol)[:4]})")
check("2026-10-31" in hol and "2026-11-18" in hol, "Saxony: Reformation Day + Buss- und Bettag (18.11.2026)")
check("2026-06-04" not in hol, "Saxony: no Corpus Christi")
check(not Da.get(B + "/api/team/absences", params={"start": "2026-03-01", "end": "2026-12-31"}).json()["holidays"], "Beta has no state: no holidays")

# ---- workload: capacity 0 in a week away, lower with a holiday
Bo.patch(B + "/api/settings", json={"features": "collab,workload"})
w = Bo.get(B + "/api/workload", params={"start": "2026-11-16", "weeks": 1}).json()
pb = next((p for p in w["people"] if p["id"] == BOB), None)
check(pb and pb["weeks"][0]["capacity_h"] == 0 and pb["weeks"][0]["absent_days"] == 5, f"workload: bob's week away has no capacity ({pb and pb['weeks'][0]})")
w = Bo.get(B + "/api/workload", params={"start": "2026-11-16", "weeks": 1}).json()
pc = next((p for p in w["people"] if p["id"] == CAROL), None)
check(pc and abs(pc["weeks"][0]["capacity_h"] - pc["capacity_h"] * 4 / 5) < 0.01, f"workload: Buss- und Bettag takes a fifth of carol's week ({pc and pc['weeks'][0]})")

# ---- day plan: a hint instead of a proposal on a day away
r = Bo.post(B + "/api/tasks", json={"title": "Prepare the shoot", "list_id": Bo.get(B + "/api/state").json()["lists"][0]["id"], "due": "2026-11-17", "duration": 60})
check(r.status_code in (200, 201), f"setup: a task ({r.status_code})")
p = Bo.get(B + "/api/dayplan", params={"date": "2026-11-17"}).json()
check(p.get("away", {}).get("kind") == "vacation" and not p["plan"], f"day plan on a day away: hint, no proposal ({p.get('away')}, {len(p.get('plan', []))})")
p = Bo.get(B + "/api/dayplan", params={"date": "2026-11-24"}).json()
check("away" not in p, "day plan on a normal day: no hint")

# ---- a freelancer without an organisation
r = Er.post(B + "/api/team/absences", json={"kind": "off", "start_date": "2026-11-20"})
check(r.status_code == 201, f"a freelancer enters a day off ({r.status_code} {r.text[:200]})")
EOFF = r.json()["id"]
j = Er.get(B + "/api/team/absences", params=q).json()
check([x["id"] for x in j["items"]] == [EOFF] and j["admin"] is True and [p["id"] for p in j["people"]] == [ERIN], "the freelancer sees only their own area")
check(Er.put(B + "/api/team/absences/holidays", json={"state": "BY"}).ok, "the freelancer sets their own state")
check(Bo.patch(B + f"/api/team/absences/{EOFF}", json={"note": "x"}).status_code == 404, "nobody else reads a freelancer's absence")
check(Bo.get(B + "/api/team/absences/check", params={"user": ERIN, "date": "2026-11-20"}).json().get("absent") is False, "the check tells nothing about private areas")


# ---- agents (REST API v1 / MCP get_absences): "away" only, own workspace only
A = sess("alice")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "helper", "display_name": "Helper"})
AGT, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], **H}
check(A.patch(B + f"/api/admin/agents/{AGT}", json={"org_id": ORG}).ok, "setup: an agent of Alpha")
r = requests.get(B + "/api/v1/absences", params={"start": "2026-11-01", "end": "2026-11-30"}, headers=AGH)
j = r.json() if r.ok else {}
check(r.ok and j.get("org_id") == ORG and any(x["user_id"] == CAROL for x in j["items"]), f"agent: Alpha's absences ({r.status_code} {r.text[:200]})")
check(r.ok and all("kind" not in x and "note" not in x for x in j["items"]) and "sick" not in r.text and "flu" not in r.text, "agent: never the kind or the note")
check(requests.get(B + "/api/v1/absences", params={"org": ORG2}, headers=AGH).status_code == 404, "agent: another organisation 404")
check(A.patch(B + f"/api/admin/agents/{AGT}", json={"org_id": None}).ok, "setup: the agent becomes private")
check(requests.get(B + "/api/v1/absences", headers=AGH).status_code == 404, "a private agent sees no team (404)")
check(A.post(B + "/api/team/absences", json={"kind": "off", "start_date": D1}).status_code in (201, 404), "the instance admin outside Alpha enters into their own area")
r = requests.get(B + "/api/team/absences", headers=AGH)
check(r.status_code in (401, 403), f"agents cannot use the web routes ({r.status_code})")
A.post(B + "/api/auth/logout")

# ---- disposition (#1194): module off -> 409; resources of the area only
check(Bo.get(B + "/api/team/dispo").status_code == 409, "disposition off by default: 409")
for s_ in (Bo, Ca, Da):
    s_.patch(B + "/api/settings", json={"features": "collab,workload,dispo,office,contacts"})
check(dbx("SELECT 1 FROM information_schema.tables WHERE table_name='hub_bookings'"), "new table hub_bookings")
now = "2026-01-01T00:00:00Z"
CAM = dbx("INSERT INTO office_equipment(org_id,name,category,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id", (ORG, "Camera A", "Camera", now, now), write=True)[0][0]
LIGHT = dbx("INSERT INTO office_equipment(org_id,name,category,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id", (ORG, "Light kit", "Light", now, now), write=True)[0][0]
FOREIGN = dbx("INSERT INTO office_equipment(org_id,name,category,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id", (ORG2, "Beta drone", "Air", now, now), write=True)[0][0]
SET = dbx("INSERT INTO office_sets(org_id,name,items,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id",
          (ORG, "Interview set", f'[{{"equipment_id": {CAM}, "qty": 1}}, {{"equipment_id": {LIGHT}, "qty": 1}}]', now, now), write=True)[0][0]
j = Bo.get(B + "/api/team/dispo", params={"start": "2026-11-16", "days": 7}).json()
check({e["id"] for e in j["resources"]["equipment"]} == {CAM, LIGHT} and [x["id"] for x in j["resources"]["sets"]] == [SET], f"resources: Alpha's equipment + set only ({j.get('resources', {}).get('equipment')})")
check({p["id"] for p in j["resources"]["people"]} == {BOB, CAROL}, "resources: Alpha's people")
check(str(BOB) in j["away"] and "kind" not in str(j["away"]), "disposition shows bob away (no kind)")

# ---- booking: option / firm, conflicts are warnings
r = Ca.post(B + "/api/team/dispo/bookings", json={"title": "Shoot day 1", "start": "2026-11-17", "status": "option",
                                                  "resources": [{"kind": "user", "id": BOB}, {"kind": "equipment", "id": CAM}]})
check(r.status_code == 201 and r.json()["warnings"] == 1, f"booking bob on his vacation: created, one warning ({r.status_code} {r.text[:300]})")
bk = {x["kind"]: x for x in r.json()["bookings"]}
check(bk["user"]["away"] is True and bk["equipment"]["away"] is False, "bob is marked away (vacation = not free)")
r = Ca.post(B + "/api/team/dispo/bookings", json={"title": "Shoot day 2", "start": "2026-11-17T10:00", "end": "2026-11-17T14:00", "status": "firm",
                                                  "resources": [{"kind": "set", "id": SET}, {"kind": "user", "id": CAROL}]})
check(r.status_code == 201, f"booking the set the same day: created ({r.status_code} {r.text[:200]})")
bs = {x["kind"]: x for x in r.json()["bookings"]}
check(bk["equipment"]["id"] in bs["set"]["conflicts"], f"double booking: the set holds Camera A ({bs['set']})")
check(not bs["user"]["conflicts"] and not bs["user"]["away"], "carol is free")
r = Ca.post(B + "/api/team/dispo/bookings", json={"title": "Evening", "start": "2026-11-17T15:00", "end": "2026-11-17T18:00",
                                                  "resources": [{"kind": "user", "id": CAROL}]})
check(r.status_code == 201 and not r.json()["bookings"][0]["conflicts"], "same person, later the same day: no conflict")
r = Ca.post(B + "/api/team/dispo/bookings", json={"title": "x", "start": "2026-11-17", "resources": [{"kind": "equipment", "id": FOREIGN}]})
check(r.status_code == 404, f"another organisation's equipment cannot be booked ({r.status_code})")
r = Ca.post(B + "/api/team/dispo/bookings", json={"title": "x", "start": "2026-11-17", "resources": [{"kind": "user", "id": DAVE}]})
check(r.status_code == 404, f"a person of another organisation cannot be booked ({r.status_code})")
fr = Ca.get(B + "/api/team/dispo/free", params={"date": "2026-11-17"}).json()
check(not fr["equipment"] and not fr["sets"] and BOB not in [p["id"] for p in fr["people"]], f"who is free: Camera A / set / bob not ({fr})")
fr = Ca.get(B + "/api/team/dispo/free", params={"date": "2026-11-24"}).json()
check({p["id"] for p in fr["people"]} == {BOB, CAROL} and len(fr["equipment"]) == 2, "who is free a week later: everybody")
j = Ca.get(B + "/api/team/dispo", params={"start": "2026-11-16", "days": 7}).json()
check(len(j["bookings"]) == 5, f"the week's bookings ({len(j['bookings'])})")

# ---- other organisation / no module / mine
j = Da.get(B + "/api/team/dispo", params={"start": "2026-11-16", "days": 7}).json()
check(not j["bookings"], "another organisation sees none of Alpha's bookings")
check(Da.patch(B + f"/api/team/dispo/bookings/{bk['user']['id']}", json={"title": "x"}).status_code == 404, "another organisation: no edit (404)")
check(Da.delete(B + f"/api/team/dispo/bookings/{bk['user']['id']}").status_code == 404, "another organisation: no delete (404)")
Bo.patch(B + "/api/settings", json={"features": "collab,workload"})
check(Bo.get(B + "/api/team/dispo").status_code == 409, "without the module: no disposition")
m = Bo.get(B + "/api/team/bookings/mine", params={"since": "2026-11-01"}).json()["bookings"]
check([x["title"] for x in m] == ["Shoot day 1"] and m[0]["status"] == "option", f"bob sees his own booking (as an option) without the module ({m})")
check(not Da.get(B + "/api/team/bookings/mine", params={"since": "2026-11-01"}).json()["bookings"], "dave has no bookings")

# ---- firm booking -> News for the booked person; edit the whole job; delete = Undo
r = Ca.patch(B + f"/api/team/dispo/bookings/{bk['user']['id']}", json={"status": "firm", "all": True})
check(r.ok and all(x["status"] == "firm" for x in r.json()["bookings"]) and len(r.json()["bookings"]) == 2, "the whole job becomes firm")
news = Bo.get(B + "/api/news").json()
items = news.get("items", news) if isinstance(news, dict) else news
check(any(x.get("kind") == "dispo" for x in items), "a firm booking: News for bob")
r = Ca.delete(B + f"/api/team/dispo/bookings/{bk['user']['id']}", params={"all": 1})
check(r.ok and len(r.json()["ids"]) == 2, "delete the whole job")
check(not Bo.get(B + "/api/team/bookings/mine", params={"since": "2026-11-01"}).json()["bookings"], "deleted: gone from mine")
check(Ca.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json()["ids"]}).json().get("restored") == 2, "Undo restores the job")
check(Da.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json()["ids"]}).status_code == 404, "another organisation cannot restore")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
