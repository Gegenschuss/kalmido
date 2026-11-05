#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.560.0 B (#4699): the agent's data lock on the side ways to the same data (audit #2822, A-F2). Invented names only.
 - tables: a table bound to a locked project, shared with the agent one by one (sheet_shares) or filed in a folder shared
   with it, gives the agent nothing: GET / PUT /api/v1/sheets, the index and the file store's content route (404); a new
   share with the agent is refused and the agent is not offered as a target; opened again: it reads and writes
 - events: an event whose task lies in a locked project (or in a private trip with the area travel locked) is left out of
   GET /api/v1/events and is 404 on its own route (read, change); the plain event stays; opened: it comes back
 - areas "calendar" / "contacts": switches of the gear (GET /api/v1/agent data_lock names them); locked, the agent gets no
   calendar, no event (list empty, own route 404, new 403, free / busy 403) and no address book or contact (403 / 404),
   also not through a book share; opened: everything again
 - freelancer-matrix: agents (a person without an organisation and her own agent)
usage: p2560_b_datalock_ways_test.py <datadir>      (KMT_NOSTART=1 / P2560B_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup

V = B + "/api/v1"
D = "2026-11-10"

fresh(prefix="P2560B", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot",
                                         "scopes": ["read", "tasks:write", "calendar", "contacts", "sheets:read", "sheets:write", "files:read"]})
check(r.status_code in (200, 201), f"her personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
    (FA, "events,contacts,sheets,files,collab"))  # the agent's own module switches


def lock(**b):
    r = F.patch(B + f"/api/agents/{FA}/data-lock", json=b)
    check(r.status_code == 200, f"lock {b}: {r.status_code} {r.text[:160]}")
    return r.json()


def ag(method, path, **kw):
    return getattr(requests, method)(V + path, headers=FH, timeout=30, **kw)


# ---------------------------------------------------------------- the data
P_LOCK = F.post(B + "/api/lists", json={"name": "Secret project"}).json()["id"]
P_TRIP = F.post(B + "/api/lists", json={"name": "Lisbon trip"}).json()["id"]
dbx("UPDATE lists SET life='travel' WHERE id=?", (P_TRIP,))
T_LOCK = F.post(B + "/api/tasks", json={"title": "Plan", "list_id": P_LOCK}).json()["id"]
T_TRIP = F.post(B + "/api/tasks", json={"title": "Flight", "list_id": P_TRIP}).json()["id"]

# tables: one shared with the agent by itself, one in a folder shared with the agent; both bound to the locked project
r = F.post(B + "/api/sheets", json={"title": "Project rates", "space": "private", "list_id": P_LOCK})
check(r.status_code == 201, f"a table of the project {r.status_code} {r.text[:120]}")
S1 = r.json()["id"]
check(F.post(B + f"/api/sheets/{S1}/shares", json={"user_id": FA, "role": "write"}).status_code in (200, 201), "S1 shared with the agent")
r = F.post(B + "/api/sheets/folders", json={"name": "Agent folder", "space": "private"})
check(r.status_code == 201, f"a folder {r.status_code} {r.text[:120]}")
FOLD = r.json()["folder"]["id"]
r = F.post(B + "/api/sheets", json={"title": "Project costs", "space": "private", "list_id": P_LOCK, "folder_id": FOLD})
check(r.status_code == 201, f"a filed table of the project {r.status_code} {r.text[:120]}")
S2 = r.json()["id"]
check(F.post(B + f"/api/files/nodes/{FOLD}/shares", json={"agent_id": FA, "role": "edit"}).status_code == 201, "the folder shared with the agent")
S3 = F.post(B + "/api/sheets", json={"title": "Plain table", "space": "private"}).json()["id"]
check(F.post(B + f"/api/sheets/{S3}/shares", json={"user_id": FA, "role": "read"}).status_code in (200, 201), "S3 shared with the agent")
NODE2 = {x["id"]: x for x in F.get(B + "/api/sheets").json()["sheets"]}[S2].get("fnode")
check(bool(NODE2), "S2 has its node in the folder")

# events in her calendar, the agent a member
CAL = F.post(B + "/api/evcals", json={"name": "Frida"}).json()["id"]
check(F.put(B + f"/api/evcals/{CAL}/members", json={"user_id": FA, "role": "edit"}).ok, "the calendar shared with the agent")


def event(title, tid=None):
    r = F.post(B + "/api/events", json={"cal_id": CAL, "title": title, "start": f"{D}T09:00", "end": f"{D}T10:00",
                                         **({"task_id": tid} if tid else {})})
    check(r.status_code == 201, f"event {title}: {r.status_code} {r.text[:120]}")
    eid = r.json()["id"]
    if tid:
        dbx("UPDATE events SET task_id=? WHERE id=?", (tid, eid))  # bound to the task like a preparation task
    return eid


E_PLAIN, E_PROJ, E_TRIP = event("Plain meeting"), event("Project meeting", T_LOCK), event("Airport", T_TRIP)

# contacts: her book shared with the agent
r = F.post(B + "/api/books", json={"name": "Clients"})
check(r.status_code == 201, f"a book {r.status_code} {r.text[:120]}")
BK = r.json()["id"]
CT = F.post(B + "/api/contacts", json={"book_id": BK, "fn": "Paula Example"}).json()["id"]
check(F.put(B + f"/api/books/{BK}/members", json={"user_id": FA, "role": "view"}).ok, "the book shared with the agent")


def ev_ids():
    r = ag("get", f"/events?from={D}&to={D}")
    check(r.status_code == 200, f"GET /events {r.status_code} {r.text[:120]}")
    return {x.get("eid") for x in r.json().get("data", [])}


# ---------------------------------------------------------------- counter-check first: without a lock it sees everything
for sid in (S1, S2, S3):
    check(ag("get", f"/sheets/{sid}").status_code == 200, f"no lock: the agent reads table {sid}")
check(ag("get", f"/files/{NODE2}/content").status_code == 200, "no lock: the filed table through the file store")
check(ev_ids() >= {E_PLAIN, E_PROJ, E_TRIP}, "no lock: every event")
check(ag("get", "/contacts").status_code == 200 and any(x["id"] == CT for x in ag("get", "/contacts").json().get("data", [])),
      "no lock: the shared contact")

# ---------------------------------------------------------------- (a) tables of a locked project
lock(lists=[P_LOCK], areas={"travel": True})
for sid in (S1, S2):
    check(ag("get", f"/sheets/{sid}").status_code == 404, f"locked project: table {sid} 404 (share / folder)")
    r = ag("put", f"/sheets/{sid}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]})
    check(r.status_code == 404, f"locked project: no write into table {sid} ({r.status_code})")
ids = {x["id"] for x in ag("get", "/sheets").json().get("data", [])}
check(S3 in ids and not ids & {S1, S2}, f"the index: only the plain table {ids}")
check(not {x["id"] for x in ag("get", "/sheets?space=shared").json().get("data", [])} & {S1, S2}, "the shared index: neither")
r = ag("get", f"/files/{NODE2}/content")
check(r.status_code in (403, 404) and b"Project" not in r.content, f"the file store's content route: nothing ({r.status_code})")
check(ag("get", f"/sheets/{S3}").status_code == 200, "the plain table stays")
tg = F.get(B + f"/api/sheets/{S1}/shares").json()
check(FA not in [x["id"] for x in tg.get("agents", [])], f"the locked agent is not offered as a target {tg.get('agents')}")
r = F.post(B + f"/api/sheets/{S1}/shares", json={"user_id": FA, "role": "read"})
check(r.status_code == 409 and ag("get", f"/sheets/{S1}").status_code == 404, f"no share with the locked agent ({r.status_code})")
check(F.get(B + f"/api/sheets/{S1}").ok and F.get(B + f"/api/sheets/{S2}").ok, "the owner still sees both tables")

# ---------------------------------------------------------------- (b) events of locked tasks (project, private trip)
got = ev_ids()
check(E_PLAIN in got and E_PROJ not in got and E_TRIP not in got, f"the events: only the plain one {got}")
for eid in (E_PROJ, E_TRIP):
    check(ag("get", f"/events/{eid}").status_code == 404, f"event {eid} of a locked task: GET 404")
    check(ag("patch", f"/events/{eid}", json={"title": "x"}).status_code == 404, f"event {eid}: PATCH 404")
check(ag("get", f"/events/{E_PLAIN}").status_code == 200, "the plain event stays readable")
check(F.get(B + f"/api/events/{E_PROJ}").ok, "the owner still sees the project's event")
# Fable review F1/F2 (2.560.0): the calendar's export and the agent's own feed link leave them out too
r = ag("get", f"/event-calendars/{CAL}/export")
check(r.status_code == 200, f"export {r.status_code} {r.text[:120]}")
ics = r.json().get("ics") or ""
check("Plain meeting" in ics and "Project meeting" not in ics and "Airport" not in ics, "the export: only the plain event")
dbx("INSERT INTO ev_cal_feeds(cal_id, user_id, secret, created_at) VALUES(?,?,?,?)", (CAL, FA, "p2560bsecret", "2026-11-05T00:00:00Z"))
FEED = dbx("SELECT id FROM ev_cal_feeds WHERE user_id=? AND cal_id=?", (FA, CAL))[0][0]
r = requests.get(B + f"/ical/ev/{FEED}.p2560bsecret.ics", timeout=30)
check(r.status_code == 200 and "Plain meeting" in r.text, f"the agent's feed works {r.status_code}")
check("Project meeting" not in r.text and "Airport" not in r.text, "the agent's feed: no event of a locked task")
check("Project meeting" in F.get(B + f"/api/evcals/{CAL}/export.ics").text, "the owner's export keeps the project's event")

# ---------------------------------------------------------------- (c) the areas calendar and contacts
lock(areas={"calendar": True, "contacts": True})
dl = ag("get", "/agent").json().get("data_lock") or {}
check({"calendar", "contacts"} <= set(dl.get("areas", [])), f"GET /api/v1/agent names the locked areas {dl}")
r = ag("get", "/event-calendars")
check(r.status_code == 200 and r.json().get("data") == [], f"calendar locked: no calendar {r.status_code} {r.text[:120]}")
check(ev_ids() == set(), "calendar locked: no event")
check(ag("get", f"/events/{E_PLAIN}").status_code == 404, "calendar locked: the plain event 404")
r = ag("post", "/events", json={"cal_id": CAL, "title": "x", "start": f"{D}T11:00", "end": f"{D}T12:00"})
check(r.status_code in (403, 404), f"calendar locked: no new event ({r.status_code})")
check(ag("get", f"/event-calendars/{CAL}/export").status_code == 404, "calendar locked: no export")
r = ag("get", f"/events/freebusy?day={D}&users={FID}")
check(r.status_code == 403, f"calendar locked: no free / busy ({r.status_code})")
for p in ("/address-books", "/contacts", f"/contacts/{CT}", f"/address-books/{BK}/export"):
    r = ag("get", p)
    check(r.status_code in (403, 404) and b"Paula" not in r.content, f"contacts locked: {p} -> {r.status_code}")
check(F.get(B + f"/api/contacts/{CT}").ok, "the owner still sees the contact")

# ---------------------------------------------------------------- opened again: everything back (the scan sees them)
lock(lists=[], areas={"travel": False, "calendar": False, "contacts": False})
for sid in (S1, S2):
    check(ag("get", f"/sheets/{sid}").status_code == 200, f"opened: table {sid} readable")
check(ag("put", f"/sheets/{S1}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]}).status_code == 200, "opened: the agent writes S1")
check(ag("get", f"/files/{NODE2}/content").status_code == 200, "opened: the filed table through the file store")
check(ev_ids() >= {E_PLAIN, E_PROJ, E_TRIP}, "opened: every event again")
check(any(x["id"] == CT for x in ag("get", "/contacts").json().get("data", [])), "opened: the contact again")
sys.exit(done("p2560_b_datalock_ways"))
