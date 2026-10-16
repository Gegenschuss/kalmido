#!/usr/bin/env python3
"""2.51.0 API tests, part C (#1352 pin board + weekly status, #1353 time check + time proposals, #1355 shoot planning).
Invented names only.
 - pin board: an agent (scope pinboard) reads the notepads of a shared project, writes its own, changes / removes only its
   own (people's: 403), one status block per agent and list (upsert); without the scope 403; read-only share 403; a list
   not shared with it 404; the web app marks its notepads (agent_id)
 - weekly status: done, overdue, blocked with blockers, waiting on external, who waits on whom
 - time check: a day over 12 h, an entry over 10 h, overlaps, weekend without an event, an event without time (only in a
   calendar shared with the agent); from-events needs the calendar scope; a person the agent does not work for: 404
 - time proposal: validation (future, a list the agent cannot see), apply with edited times = entries as the person, undo /
   redo; the kind cannot be requested by a person
 - shoot proposal: the disposition of the agent's own organisation (another one: 404), warnings per row (double booking,
   absence, other projects), apply = tasks + tentative events + option bookings (never firm), undo / redo; a resource of
   another organisation: 400; a list of another organisation: 404; a personal agent of a freelancer reads her personal area
 - rollback: only new columns
tenant-matrix: list, agent, hub, aggregate
usage: p251_c_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
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
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,collab,comments,time,events,dispo,deps,fields"


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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
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


def agent(name, scopes, org=None, owner=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:  # an organisation's agent is a member of it (sharing a list with it needs that)
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    return aid, tok(t)


if not os.environ.get("P251C_NOSTART"):
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
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id!=?) OR user_id=?",
    (ORG, BOB, CAROL, ORG2, DAVE, ERIN), write=True)
AG, AGS = agent("crewbot", ["read", "tasks:write", "comments", "pinboard", "time", "calendar"], org=ORG)
AG0, AG0S = agent("plainbot", ["read", "tasks:write", "comments"], org=ORG)
PAG, PAGS = agent("erinbot", ["read", "tasks:write", "comments", "pinboard", "time", "calendar"], owner=ERIN)
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})

# ---- rollback: new columns only
cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='list_notepads'")}
check({"agent_id", "agent_key"} <= cols, f"new columns list_notepads.agent_id / agent_key ({sorted(cols)})")

# ---- the project of Alpha, shared with the agents
r = Bo.post(B + "/api/lists", json={"name": "Film Alpha", "kind": "project"})
P = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P), write=True)
for uid, role in ((AG, "edit"), (CAROL, "edit")):
    r = Bo.put(B + f"/api/lists/{P}/members", json={"user_id": uid, "role": role})
    check(r.ok, f"setup: share P with {uid} ({r.status_code} {r.text[:150]})")
r = Bo.post(B + "/api/lists", json={"name": "Film Two", "kind": "project"})
P2 = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P2), write=True)
check(Bo.put(B + f"/api/lists/{P2}/members", json={"user_id": AG, "role": "view"}).ok, "setup: P2 read-only for the agent")
r = Bo.post(B + "/api/lists", json={"name": "Secret", "kind": "project"})
PX = r.json()["id"]
r = Bo.post(B + "/api/lists", json={"name": "Film Three", "kind": "project"})
P3 = r.json()["id"]  # one agent per list: the agent without the scope gets its own
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P3), write=True)
check(Bo.put(B + f"/api/lists/{P3}/members", json={"user_id": AG0, "role": "edit"}).ok, "setup: P3 for the agent without the scope")

# =================================================================== #1352 pin board
r = Bo.post(B + f"/api/lists/{P}/notepads", json={"title": "Contacts", "body": "call the location"})
HUM = [x for x in r.json()["pads"] if x["title"] == "Contacts"][0]["id"]
r = AGS.get(V + f"/lists/{P}/notepads")
check(r.ok and [x["id"] for x in r.json()["data"]] == [HUM] and r.json()["data"][0]["agent_id"] is None, f"agent reads the notepads ({r.status_code} {r.text[:150]})")
r = AGS.post(V + f"/lists/{P}/notepads", json={"title": "Ideas", "body": "- a"})
check(r.status_code == 201 and r.json()["agent_id"] == AG and r.json()["mine"], f"agent writes its own notepad ({r.status_code} {r.text[:150]})")
OWN = r.json()["id"]
r = AGS.patch(V + f"/notepads/{HUM}", json={"body": "overwritten"})
check(r.status_code == 403, f"a person's notepad: 403 ({r.status_code})")
check(AGS.delete(V + f"/notepads/{HUM}").status_code == 403, "deleting a person's notepad: 403")
check(dbx("SELECT body FROM list_notepads WHERE id=?", (HUM,))[0][0] == "call the location", "the person's notepad is unchanged")
r = AGS.patch(V + f"/notepads/{OWN}", json={"body": "- a\n- b"})
check(r.ok and r.json()["body"] == "- a\n- b", "agent changes its own notepad")
check(AG0S.post(V + f"/lists/{P3}/notepads", json={"title": "x"}).status_code == 403, "without the scope pinboard: 403")
check(AG0S.get(V + f"/lists/{P3}/notepads").ok, "reading needs read only")
check(AGS.post(V + f"/lists/{P2}/notepads", json={"title": "x"}).status_code == 403, "read-only share: 403")
check(AGS.get(V + f"/lists/{PX}/notepads").status_code == 404, "a list not shared with the agent: 404")
r1 = AGS.put(V + f"/lists/{P}/status-pad", json={"body": "## Status\n- 1"})
r2 = AGS.put(V + f"/lists/{P}/status-pad", json={"body": "## Status\n- 2"})
check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"] and r2.json()["agent_key"] == "status",
      f"status block: created once, then overwritten ({r1.status_code} {r2.status_code})")
STATUS = r1.json()["id"]
check(Bo.patch(B + f"/api/notepads/{STATUS}", json={"body": "edited by bob"}).ok, "a person may edit the agent's block")
r = AGS.put(V + f"/lists/{P}/status-pad", json={"body": "## Status\n- 3"})
check(r.ok and r.json()["id"] == STATUS and r.json()["body"].endswith("3"), "the next run overwrites its own block")
check(Bo.post(B + f"/api/v1/lists/{P}/notepads", json={"title": "x"}).status_code in (401, 403), "the v1 routes need a token")
ov = Bo.get(B + f"/api/lists/{P}/overview").json()
pads = {x["id"]: x for x in (ov.get("layout") or {}).get("pads", [])}
check(pads.get(OWN, {}).get("agent_id") == AG and pads.get(HUM, {}).get("agent_id") is None, f"the web app marks the agent's notepads ({list(pads.values())[:3]})")
check(AGS.delete(V + f"/notepads/{OWN}").ok and not dbx("SELECT 1 FROM list_notepads WHERE id=?", (OWN,)), "agent removes its own notepad")

# ---- the weekly status
T1 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Book the studio", "assignee_id": CAROL}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Shot list", "assignee_id": BOB, "due": "2026-10-01"}).json()["id"]
T3 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Script", "assignee_id": BOB}).json()["id"]
T4 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Permit"}).json()["id"]
check(Bo.post(B + "/api/deps", json={"task_id": T2, "blocker_id": T1}).ok, "setup: shot list waits on the studio")
dbx("UPDATE tasks SET status=2, completed_at=?, completed_by=? WHERE id=?", (date.today().isoformat() + "T08:00:00+00:00", BOB, T3), write=True)
dbx("UPDATE tasks SET waiting_at=?, wait_note='city office' WHERE id=?", ("2026-10-01T08:00:00+00:00", T4), write=True)
w = AGS.get(V + f"/lists/{P}/weekly-status").json()
check(w["counts"]["done"] == 1 and [x["id"] for x in w["done"]] == [T3], f"weekly: done ({w.get('counts')})")
check([x["id"] for x in w["overdue"]] == [T2] and w["overdue"][0]["days_late"] > 0, "weekly: overdue")
check(w["blocked"] and w["blocked"][0]["id"] == T2 and w["blocked"][0]["blocked_by"][0]["id"] == T1, "weekly: blocked + blocker")
check([x["id"] for x in w["waiting"]] == [T4] and w["waiting"][0]["on"] == "city office", "weekly: waiting on external")
check(w["waits"] == [{"who": BOB, "on": CAROL, "task_ids": [T2]}] and w["people"].get(str(CAROL)) == "Carol", f"weekly: who waits on whom ({w['waits']})")
check(AGS.get(V + f"/lists/{PX}/weekly-status").status_code == 404, "weekly: a list not shared: 404")

# =================================================================== #1353 time check + time proposals
check(Bo.patch(B + f"/api/lists/{P}", json={"time_tracking": True}).ok, "setup: time tracking on in P")
today = date.today()
D1 = today - timedelta(days=3)
while D1.weekday() > 4:
    D1 -= timedelta(days=1)
SAT = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
D2 = today - timedelta(days=1)
for d, a, b in ((D1, "06:00", "17:30"), (D1, "17:00", "20:00"), (SAT, "10:00", "12:00")):
    r = Bo.post(B + "/api/time/entries", json={"task_id": T1, "start": f"{d}T{a}", "end": f"{d}T{b}"})
    check(r.ok, f"setup: entry {d} {a} ({r.status_code} {r.text[:100]})")
r = Bo.post(B + "/api/events", json={"title": "Edit day A", "start": f"{D2}T09:00", "end": f"{D2}T18:00", "task_id": T1})
check(r.status_code == 201, f"setup: an event yesterday ({r.status_code} {r.text[:100]})")
EV, CAL = r.json()["id"], r.json()["cal_id"]
r = AGS.get(V + "/time/check", params={"user_id": BOB})
kinds = sorted({x["kind"] for x in r.json().get("issues", [])})
check(r.ok and {"day_long", "entry_long", "overlap"} <= set(kinds) and "event_no_time" not in kinds,
      f"check: long day, long entry, overlap; the event of an unshared calendar stays unseen ({kinds})")
check("weekend" in kinds, f"check: weekend entry without an event ({kinds})")
check(Bo.put(B + f"/api/evcals/{CAL}/members", json={"user_id": AG, "role": "view"}).ok, "setup: bob shares his calendar with the agent")
r = AGS.get(V + "/time/check", params={"user_id": BOB})
ev = [x for x in r.json()["issues"] if x["kind"] == "event_no_time"]
check(ev and ev[0]["event_id"] == EV, f"check: the shared event without time ({ev})")
check(AG0S.get(V + "/time/check", params={"user_id": BOB}).status_code == 403, "check: without the scope time 403")
check(AGS.get(V + "/time/check", params={"user_id": DAVE}).status_code == 404, "check: a person the agent does not work for: 404")
r = AGS.get(V + "/time/from-events", params={"user_id": BOB})
fe = r.json().get("events", [])
check(r.ok and fe and fe[0]["event_id"] == EV and fe[0]["start"] == "09:00" and fe[0]["task_id"] == T1, f"from-events ({r.text[:200]})")
ITEM = {"date": fe[0]["date"], "start": "09:00", "end": "18:00", "task_id": T1, "event_id": EV, "note": "shoot"}
r = AGS.post(V + "/agent/proposals/time", json={"user_id": BOB, "items": [{**ITEM, "date": str(today + timedelta(days=3))}]})
check(r.status_code == 400, f"time proposal: future 400 ({r.status_code})")
r = AGS.post(V + "/agent/proposals/time", json={"user_id": BOB, "items": [{**ITEM, "task_id": None, "list_id": PX}]})
check(r.status_code == 400, f"time proposal: a list the agent cannot see 400 ({r.status_code})")
check(AG0S.post(V + "/agent/proposals/time", json={"user_id": BOB, "items": [ITEM]}).status_code == 403, "time proposal: without scope 403")
r = AGS.post(V + "/agent/proposals/time", json={"user_id": BOB, "summary": "From your calendar", "items": [ITEM]})
check(r.status_code == 201 and r.json()["kind"] == "time", f"time proposal created ({r.status_code} {r.text[:150]})")
JT = r.json()["id"]
check(Bo.get(B + f"/api/proposals/{JT}").ok and Ca.get(B + f"/api/proposals/{JT}").status_code == 404, "only bob opens it")
check(Bo.post(B + "/api/proposals", json={"agent_id": AG, "kind": "time"}).status_code == 400, "a person cannot request kind time")
n0 = len(dbx("SELECT id FROM time_entries WHERE user_id=?", (BOB,)))
r = Bo.post(B + f"/api/proposals/{JT}/apply", json={"select": ["0"], "edits": {"0": {"start": "09:30", "note": "shoot day"}}})
check(r.ok and r.json()["created"] == 1, f"apply ({r.status_code} {r.text[:150]})")
e = dbx("SELECT seconds, note, task_id FROM time_entries WHERE user_id=? ORDER BY id DESC LIMIT 1", (BOB,))[0]
check(e[0] == 8.5 * 3600 and e[1] == "shoot day" and e[2] == T1, f"the entry as bob with the edited time ({tuple(e)})")
check(Bo.post(B + f"/api/proposals/{JT}/undo").json().get("undone") == 1 and len(dbx("SELECT id FROM time_entries WHERE user_id=?", (BOB,))) == n0, "undo removes it")
check(Bo.post(B + f"/api/proposals/{JT}/redo").json().get("redone") == 1 and len(dbx("SELECT id FROM time_entries WHERE user_id=?", (BOB,))) == n0 + 1, "redo adds it again")

# =================================================================== #1355 disposition + shoot proposals
DAY = date(2026, 11, 23)  # a Monday
r = Bo.post(B + "/api/team/dispo/bookings", json={"title": "Other film", "start": str(DAY), "end": str(DAY), "status": "firm", "org": ORG,
                                                  "resources": [{"kind": "user", "id": BOB}]})
check(r.status_code == 201, f"setup: bob is booked elsewhere ({r.status_code} {r.text[:150]})")
r = Ca.post(B + "/api/team/absences", json={"kind": "sick", "start_date": str(DAY), "end_date": str(DAY), "note": "flu"})
check(r.status_code == 201, f"setup: carol is away ({r.status_code})")
r = AGS.get(V + "/dispo", params={"start": str(DAY), "days": 2})
j = r.json()
check(r.ok and j["org_id"] == ORG and [b["title"] for b in j["bookings"]] == ["Other film"], f"agent reads the disposition of Alpha ({r.text[:200]})")
check(str(CAROL) in j["away"] and "sick" not in r.text and "flu" not in r.text, "away only, never the kind or the note")
check(AGS.get(V + "/dispo", params={"org": ORG2}).status_code == 404, "another organisation: 404")
check(AG0S.get(V + "/dispo").status_code == 403, "without the scope calendar: 403")
fr = AGS.get(V + "/dispo/free", params={"date": str(DAY)}).json()
check(not [p for p in fr["people"] if p["id"] in (BOB, CAROL)], f"free: neither bob (booked) nor carol (away) ({fr['people']})")
SHOOT = {"list_id": P, "summary": "Two days", "days": [
    {"date": str(DAY), "start": "08:00", "end": "18:00", "title": "Shoot day 1", "location": "Studio"},
    {"date": str(DAY + timedelta(days=1)), "title": "Shoot day 2"},
    {"date": str(DAY + timedelta(days=2)), "title": "Shoot day 1 (variant)", "alt_of": 0}],
    "crew": [{"kind": "user", "id": BOB, "day": 0}, {"kind": "user", "id": CAROL, "day": 0}, {"kind": "user", "id": CAROL, "day": 1}]}
check(AGS.post(V + "/agent/proposals/shoot", json={**SHOOT, "crew": [{"kind": "user", "id": DAVE, "day": 0}]}).status_code == 400,
      "crew of another organisation: 400")
r = Da.post(B + "/api/lists", json={"name": "Beta film", "kind": "project"})
PB = r.json()["id"]
check(AGS.post(V + "/agent/proposals/shoot", json={**SHOOT, "list_id": PB, "crew": []}).status_code == 404, "a list of another organisation: 404")
check(AGS.post(V + "/agent/proposals/shoot", json={**SHOOT, "list_id": P2, "crew": []}).status_code == 403, "a read-only list: 403")
r = AGS.post(V + "/agent/proposals/shoot", json=SHOOT)
check(r.status_code == 201 and r.json()["kind"] == "shoot", f"shoot proposal ({r.status_code} {r.text[:200]})")
JS = r.json()["id"]
p = r.json()["proposal"]
check([w["kind"] for w in p["crew"][0]["warnings"]] == ["double"] and p["crew"][0]["warnings"][0]["titles"] == ["Other film"], f"bob: double booking ({p['crew'][0]})")
check([w["kind"] for w in p["crew"][1]["warnings"]] == ["away"] and not p["crew"][2]["warnings"], "carol: away on day 1, free on day 2")
check(p["days"][0]["warnings"] and p["days"][0]["warnings"][0]["kind"] == "other_projects" and not p["days"][1]["warnings"], "day 1: other projects")
check(len(p["items"]) == 6 and p["days"][2]["alt_of"] == 0, "items = 3 days + 3 crew rows, the variant marked")
r = Bo.post(B + f"/api/proposals/{JS}/apply", json={"select": ["0", "1", "3", "4", "5"], "edits": {"0": {"start": "09:00", "location": "Hall 2"}}})
check(r.ok, f"apply the shoot ({r.status_code} {r.text[:200]})")
evs = dbx("SELECT title, status, start, location, task_id FROM events WHERE created_by=? AND deleted_at IS NULL AND title LIKE 'Shoot day%' ORDER BY id", (BOB,))
check([(x[0], x[1]) for x in evs] == [("Shoot day 1", "tentative"), ("Shoot day 2", "tentative")] and evs[0][2].endswith("T09:00") and evs[0][3] == "Hall 2",
      f"two drafts (tentative) with the edits, the variant not selected ({[tuple(x) for x in evs]})")
tl = {x[0]: x[1] for x in dbx("SELECT id, list_id FROM tasks WHERE id IN (?, ?)", (evs[0][4], evs[1][4]))}
check(set(tl.values()) == {P}, "each draft is linked to a task of the project")
bk = dbx("SELECT resource_id, status, list_id, event_id FROM hub_bookings WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (P,))
check(sorted((x[0], x[1]) for x in bk) == sorted([(BOB, "option"), (CAROL, "option"), (CAROL, "option")]) and all(x[3] for x in bk),
      f"crew as options, linked to the drafts ({[tuple(x) for x in bk]})")
check(not dbx("SELECT 1 FROM hub_bookings WHERE list_id=? AND status='firm'", (P,)), "never firm")
r = Bo.post(B + f"/api/proposals/{JS}/undo")
check(r.ok and not dbx("SELECT 1 FROM hub_bookings WHERE list_id=? AND deleted_at IS NULL", (P,))
      and not dbx("SELECT 1 FROM events WHERE created_by=? AND deleted_at IS NULL AND title LIKE 'Shoot day%'", (BOB,)), f"undo: drafts and options gone ({r.text[:120]})")
r = Bo.post(B + f"/api/proposals/{JS}/redo")
check(r.ok and len(dbx("SELECT 1 FROM hub_bookings WHERE list_id=? AND deleted_at IS NULL", (P,))) == 3, "redo: back again")
eid = dbx("SELECT id FROM events WHERE created_by=? AND deleted_at IS NULL AND title='Shoot day 2'", (BOB,))[0][0]
check(Bo.patch(B + f"/api/events/{eid}", json={"status": "confirmed"}).ok, "Confirm a draft (status confirmed)")
check(Bo.get(B + f"/api/evcals/{CAL}/export.ics").text.count("STATUS:TENTATIVE") == 1, "CalDAV / export: the other draft stays TENTATIVE")

# ---- a freelancer's personal agent: her personal area
r = Er.post(B + "/api/lists", json={"name": "Erin film", "kind": "project"})
PE = r.json()["id"]
check(Er.put(B + f"/api/lists/{PE}/members", json={"user_id": PAG, "role": "edit"}).ok, "setup: erin shares her project with her agent")
r = Er.post(B + "/api/team/dispo/bookings", json={"title": "Erin booked", "start": str(DAY), "end": str(DAY), "status": "firm",
                                                  "resources": [{"kind": "user", "id": ERIN}]})
check(r.status_code == 201, f"setup: erin books herself in her personal area ({r.status_code} {r.text[:120]})")
j = PAGS.get(V + "/dispo", params={"start": str(DAY)}).json()
check([b["title"] for b in j.get("bookings", [])] == ["Erin booked"] and [p["id"] for p in j["resources"]["people"]] == [ERIN],
      f"personal agent reads her personal area ({str(j)[:200]})")
r = PAGS.post(V + "/agent/proposals/shoot", json={"list_id": PE, "days": [{"date": str(DAY), "title": "Erin shoot"}], "crew": [{"kind": "user", "id": ERIN}]})
check(r.status_code == 201 and r.json()["proposal"]["crew"][0]["warnings"][0]["kind"] == "double", f"freelancer: shoot proposal with warning ({r.status_code} {r.text[:150]})")
check(PAGS.get(V + "/time/check").json().get("user_id") == ERIN, "a personal agent checks its owner's time by default")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
