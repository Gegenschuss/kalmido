#!/usr/bin/env python3
"""2.173.0 API tests (part A): trips and staying in touch per space (#2680), own container (start.sh). Trips (projects of
Home & life with dates) and staying in touch exist privately and in each organisation, like Reading in 2.172.0;
contracts, devices, health, the household budget and family stay private. Guarded here:
 - a trip is made in the organisation shown (space org:<id>) or moved there like any project; contracts / devices /
   health / budget / family projects still get 409 for an organisation
 - a member the trip is shared with sees it in the organisation's view, a non-member / guest gets 404, read-only reads
   but adds nothing (403); private trips never in an organisation's view and the other way round
 - staying in touch: the organisation's view lists the contacts of its address books, the private view the others;
   read-only members set nothing on an organisation's contact (403), guests do not see it (404)
 - agents / API tokens: no organisation space, an organisation's trip never goes to an agent automatically, the REST API
   leaves an organisation's contacts alone
 - "Travel expenses" of a trip: one office trip filled from it (period, destination, name), a second call opens the same;
   only the admins of the trip's organisation (members 403), a private trip in the person's own office
 - a person without an organisation uses everything privately (freelancer-matrix: life_org)
 - 2.173.1 A (#2714): the travel expenses button asks whether expenses are linked (GET); an organisation's trip reaches
   no agent event and not the assistant; a folder default moves a trip like the project dialog; care_space also from
   an address book the organisation owns
tenant-matrix: life_org"""
import os
import subprocess
import sys
from datetime import date, timedelta

import requests

import dbx as dbxm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FEATS = "comments,collab,contacts,care,travel,office,contracts,home,health,budget,family"


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u, orgs in (("bob", [{"id": ORG, "role": "member"}]), ("rita", [{"id": ORG, "role": "readonly"}]),
                ("gina", [{"id": ORG, "role": "guest"}]), ("frank", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
Bo, Ri, Gi, Fr = sess("bob"), sess("rita"), sess("gina"), sess("frank")
for s in (A, Bo, Ri, Gi, Fr):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATS}).ok
# an agent of Alice's before any trip exists (an organisation's trip must not reach it)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
AGID = r.json().get("user_id") or r.json().get("id")
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private", "contacts"]})
assert r.ok, r.text
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}

D1 = (testclock.today() + timedelta(days=20)).isoformat()
D2 = (testclock.today() + timedelta(days=23)).isoformat()


def life(s, sp):
    return s.get(B + "/api/life", params={"space": sp})


def trip_ids(s, sp):
    r = life(s, sp)
    return [x["list_id"] for x in r.json().get("travel", {}).get("trips", [])] if r.ok else None


def care_ids(s, sp):
    r = life(s, sp)
    return [x["contact_id"] for x in r.json().get("care", {}).get("items", [])] if r.ok else None


# ================================================================ trips: made in a space
r = A.post(B + "/api/life/trips", json={"name": "Trade fair", "from": D1, "to": D2, "where": "Hamburg", "packing": "", "space": SP})
check(r.status_code == 201 and r.json().get("space") == SP, "trip made in the organisation " + r.text[:200])
OT = r.json()["list_id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (OT,))[0][0] == ORG, "the trip's project belongs to the organisation")
check(not dbx("SELECT 1 FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND u.kind='agent'", (OT,)),
      "no agent in the organisation's trip")
r = A.post(B + "/api/life/trips", json={"name": "Holiday", "from": D1, "to": D2, "packing": ""})
check(r.status_code == 201 and "space" not in r.json(), "trip without space = private (as before) " + r.text[:200])
PT = r.json()["list_id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (PT,))[0][0] is None, "the private trip has no organisation")
check(trip_ids(A, SP) == [OT], "organisation view: only its trip")
check(trip_ids(A, "private") == [PT], "private view: only the private trip")
check(trip_ids(A, "") == [PT], "no space = private")
j = life(A, SP).json()
check(set(j["modules"]) <= {"travel", "care"} and "contracts" not in j and "health" not in j and "home" not in j,
      "organisation view: only travel and staying in touch " + str(j.get("modules")))
check(j.get("space") == SP, "the view names its space")

# ---- moving: trips may go into an organisation, the other Home & life / family projects not
r = A.post(B + "/api/life/trips", json={"name": "Workshop", "from": D1, "to": D2, "packing": ""})
MT = r.json()["list_id"]
r = A.patch(B + f"/api/lists/{MT}", json={"org_id": ORG})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (MT,))[0][0] == ORG, "a private trip moves into the organisation " + r.text[:200])
check(MT in trip_ids(A, SP) and MT not in trip_ids(A, "private"), "the moved trip follows")
r = A.patch(B + f"/api/lists/{MT}", json={"org_id": None})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (MT,))[0][0] is None, "and back to private " + r.text[:200])
for kind in ("contracts", "home", "health", "budget"):
    lid = A.post(B + "/api/lists", json={"name": "L " + kind, "org_id": None}).json()["id"]
    check(A.patch(B + f"/api/lists/{lid}", json={"life": kind}).ok, f"{kind}: set privately")
    r = A.patch(B + f"/api/lists/{lid}", json={"org_id": ORG})
    check(r.status_code == 409 and dbx("SELECT org_id FROM lists WHERE id=?", (lid,))[0][0] is None, f"{kind}: stays private (409) {r.status_code}")
lid = A.post(B + "/api/lists", json={"name": "Shopping", "org_id": None}).json()["id"]
check(A.patch(B + f"/api/lists/{lid}", json={"family": "shopping"}).ok, "family: set privately")
check(A.patch(B + f"/api/lists/{lid}", json={"org_id": ORG}).status_code == 409, "family: stays private (409)")
# setting "trip" on an organisation's project keeps it in the organisation
lid = A.post(B + "/api/lists", json={"name": "Org project", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/lists/{lid}", json={"life": "travel", "trip": {"from": D1, "to": D2}}).ok
      and dbx("SELECT org_id FROM lists WHERE id=?", (lid,))[0][0] == ORG, "a project of the organisation made a trip stays there")

# ---- rights: members, read-only, guests, other organisations
check(trip_ids(Bo, SP) == [], "a member does not see a trip not shared with them")
r = A.patch(B + f"/api/lists/{OT}", json={"org_visibility": "org"})
# 2.173.0 review (#2680): "everyone in the organisation" stays off for trips (it would reach org channels / agent paths)
check(r.status_code == 409, f"an organisation's trip is not opened to the whole organisation ({r.status_code})")
r = A.put(B + f"/api/lists/{OT}/members", json={"user_id": uid["bob"], "role": "edit"})
check(r.ok, "shared with the member " + r.text[:200])
check(OT in (trip_ids(Bo, SP) or []), f"the member sees the organisation's trip {trip_ids(Bo, SP)}")
check(OT not in (trip_ids(Bo, "private") or []), "... never in their private view")
check(life(Ri, SP).status_code == 200, "read-only reads the organisation's view")
r = Ri.post(B + "/api/life/trips", json={"name": "No", "from": D1, "to": D2, "packing": "", "space": SP})
check(r.status_code == 403, f"read-only makes no trip ({r.status_code})")
check(life(Gi, SP).status_code == 404, "a guest: no organisation view (404)")
r = Gi.post(B + "/api/life/trips", json={"name": "No", "from": D1, "to": D2, "packing": "", "space": SP})
check(r.status_code == 404, f"a guest makes no trip ({r.status_code})")
check(life(Fr, SP).status_code == 404, "another organisation's view: 404")
r = Fr.post(B + "/api/life/trips", json={"name": "No", "from": D1, "to": D2, "packing": "", "space": SP})
check(r.status_code == 404, f"no trip into another organisation ({r.status_code})")
check(Fr.get(B + f"/api/lists/{OT}").status_code == 404 or OT not in [x["id"] for x in Fr.get(B + "/api/state").json()["lists"]],
      "the other organisation's admin does not see the trip")
check(A.post(B + "/api/life/trips", json={"name": "X", "from": D1, "to": D2, "packing": "", "space": "org:x"}).status_code == 400, "bad space: 400")

# ================================================================ staying in touch per space
PB = A.post(B + "/api/books", json={"name": "Mine", "org_id": None}).json()["id"]
OB = A.post(B + "/api/books", json={"name": "Customers", "org_id": ORG}).json()["id"]
r = A.post(B + f"/api/books/{OB}/org", json={"org_role": "edit"})
check(r.ok, "the organisation's address book " + r.text[:200])
PC = A.post(B + "/api/contacts", json={"book_id": PB, "fn": "Pat Private"}).json()["id"]
OC = A.post(B + "/api/contacts", json={"book_id": OB, "fn": "Carla Customer"}).json()["id"]
for cid in (PC, OC):
    r = A.put(B + f"/api/contacts/{cid}/care", json={"every_days": 30})
    check(r.ok and r.json()["every_days"] == 30, f"care set on {cid} " + r.text[:200])
check(care_ids(A, "private") == [PC], "private view: only the private contact")
check(care_ids(A, SP) == [OC], "organisation view: only the organisation's contact")
r = Bo.put(B + f"/api/contacts/{OC}/care", json={"every_days": 14, "last": "today"})
check(r.ok, "a member keeps in touch with an organisation's contact " + r.text[:200])
check(care_ids(Bo, SP) == [OC] and care_ids(A, SP) == [OC], "each person their own entry")
check(dbx("SELECT every_days FROM contact_care WHERE user_id=? AND contact_id=?", (1, OC))[0][0] == 30, "Alice's entry unchanged")
r = Ri.put(B + f"/api/contacts/{OC}/care", json={"every_days": 14})
check(r.status_code == 403, f"read-only sets nothing on an organisation's contact ({r.status_code})")
r = Gi.put(B + f"/api/contacts/{OC}/care", json={"every_days": 14})
check(r.status_code == 404, f"a guest does not see the organisation's contact ({r.status_code})")
r = Fr.put(B + f"/api/contacts/{OC}/care", json={"every_days": 14})
check(r.status_code == 404, f"another organisation: 404 ({r.status_code})")

# ================================================================ agents and API tokens: the private space only
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + "/api/life", headers=hd, params={"space": SP}).status_code in (401, 403, 404), f"{who}: no organisation view")
    check(requests.post(B + "/api/life/trips", headers=hd, json={"name": "X", "from": D1, "to": D2, "space": SP}).status_code in (401, 403, 404),
          f"{who}: no trip into the organisation")
r = requests.get(B + "/api/v1/life", headers=PTH)
check(r.ok and OT not in [x["list_id"] for x in r.json().get("travel", {}).get("trips", [])], "REST API: no organisation trip " + r.text[:200])
check(r.ok and OC not in [x["contact_id"] for x in r.json().get("care", {}).get("items", [])], "REST API: no organisation contact")
r = requests.put(B + f"/api/v1/contacts/{OC}/care", headers=PTH, json={"every_days": 7})
check(r.status_code == 404, f"REST API: an organisation's contact is left alone ({r.status_code})")
r = requests.put(B + f"/api/v1/contacts/{PC}/care", headers=PTH, json={"every_days": 7})
check(r.ok, "REST API: a private contact as before " + r.text[:200])
# 2.173.0 review (#2680): reading a contact through the REST API carries no "stay in touch" of an organisation's contact
r = requests.get(B + f"/api/v1/contacts/{OC}", headers=PTH)
check(r.status_code == 404 or "care" not in (r.json().get("data") or r.json()), f"REST API: no care on an organisation's contact ({r.status_code})")
r = requests.get(B + f"/api/v1/contacts/{PC}", headers=PTH)
check(r.ok and "care" in (r.json().get("data") or r.json()), "REST API: care on a private contact as before " + r.text[:200])
# the REST API's projects and tasks leave an organisation's trip out (a full token too), a private one stays
r = requests.get(B + "/api/v1/lists", headers=PTH)
ids = [x["id"] for x in (r.json().get("data") or [])] if r.ok else []
check(r.ok and OT not in ids and PT in ids, f"REST API lists: no organisation trip, the private one (OT {OT in ids}, PT {PT in ids})")
r = requests.get(B + "/api/v1/tasks", headers=PTH, params={"list_id": OT})
check(r.status_code in (403, 404) or not (r.json().get("data") or []), f"REST API tasks of an organisation trip: none ({r.status_code})")
# never shared with an agent: by hand, folder or automatically
if AGID:
    r = A.put(B + f"/api/lists/{OT}/members", json={"user_id": AGID, "role": "edit"})
    check(r.status_code == 409, f"an organisation's trip is not shared with an agent ({r.status_code})")
r = requests.post(B + "/api/v1/life/trips", headers=PTH, json={"name": "Api", "from": D1, "to": D2, "space": SP})
check(r.status_code == 400, f"REST API: no space field ({r.status_code})")
check(requests.post(B + f"/api/life/trips/{OT}/expenses", headers=AGH).status_code in (401, 403, 404), "agent: no travel expenses")

# ================================================================ travel expenses from a trip
r = Bo.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 403, f"a member makes no travel expenses ({r.status_code})")
r = Fr.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 404, f"another organisation: 404 ({r.status_code})")
r = A.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 201 and r.json()["created"] and r.json()["office_id"] == ORG, "travel expenses made " + r.text[:200])
TID = r.json().get("trip_id")
row = dbx("SELECT org_id, date_from, date_to, overnight, created_by FROM office_trips WHERE id=?", (TID,))
check(row and tuple(row[0]) == (ORG, D1, D2, 1, 1), f"filled from the trip: {row}")
r = A.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 200 and r.json()["trip_id"] == TID and not r.json()["created"], "a second click: the same one")
check(dbx("SELECT COUNT(*) FROM office_trips WHERE org_id=?", (ORG,))[0][0] == 1, "exactly one office trip")
check(A.patch(B + "/api/settings", json={"workspace": SP}).ok, "the office of the organisation")
j = A.get(B + "/api/office/trips", params={"year": D1[:4]}).json()
t = next((x for x in j["trips"] if x["id"] == TID), None)
check(t is not None and t["dest"] == "Hamburg" and t["note"] == "Trade fair", f"the office shows it: {t and (t['dest'], t['note'])}")
check(A.delete(B + f"/api/office/trips/{TID}").ok, "deleted in the office")
r = A.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 201 and r.json()["trip_id"] != TID, "after deleting it, a new one " + r.text[:200])
TID2 = r.json().get("trip_id")
r = A.post(B + f"/api/life/trips/{PT}/expenses")
pof = dbx("SELECT id FROM orgs WHERE personal_of=1")
check(r.status_code == 201 and pof and r.json()["office_id"] == pof[0][0], "a private trip: the person's own office " + r.text[:200])
# 2.173.0 review (#2680): moved to another office area -> no second one
dbx("UPDATE office_trips SET org_id=? WHERE id=?", (pof[0][0], TID2))
r = A.post(B + f"/api/life/trips/{OT}/expenses")
check(r.status_code == 409, f"moved to another office area: 409, no second one ({r.status_code})")
dbx("UPDATE office_trips SET org_id=? WHERE id=?", (ORG, TID2))
r = A.post(B + f"/api/life/trips/{lid + 100000}/expenses")
check(r.status_code == 404, "an unknown trip: 404")
nl = A.post(B + "/api/lists", json={"name": "Plain", "org_id": None}).json()["id"]
check(A.post(B + f"/api/life/trips/{nl}/expenses").status_code == 404, "a project that is no trip: 404")

# ================================================================ 2.173.0 review (#2680): the trip's event stays in its workspace
assert A.patch(B + "/api/settings", json={"features": FEATS + ",events"}).ok
r = A.post(B + "/api/life/trips", json={"name": "Fair 2", "from": D1, "to": D2, "packing": "", "space": SP, "event": True})
e = r.json().get("event_id") if r.ok else None
co = dbx("SELECT c.org_id FROM events e JOIN ev_cals c ON c.id=e.cal_id WHERE e.id=?", (e,)) if e else []
check(r.status_code == 201 and (e is None or co[0][0] == ORG), f"an organisation's trip: its event only in an organisation calendar {co}")
r = A.post(B + "/api/life/trips", json={"name": "Holiday 2", "from": D1, "to": D2, "packing": "", "event": True})
e = r.json().get("event_id") if r.ok else None
co = dbx("SELECT c.org_id FROM events e JOIN ev_cals c ON c.id=e.cal_id WHERE e.id=?", (e,)) if e else []
check(r.status_code == 201 and (e is None or co[0][0] is None), f"a private trip: its event only in a private calendar {co}")
assert A.patch(B + "/api/settings", json={"features": FEATS}).ok

# ================================================================ a person without an organisation (freelancer-matrix: life_org)
FID, Fl = freelancer(B, A)
r = Fl.post(B + "/api/life/trips", json={"name": "Client visit", "from": D1, "to": D2, "where": "Berlin", "packing": "", "space": "private"})
check(r.status_code == 201, "freelancer: a trip " + r.text[:200])
FT = r.json()["list_id"]
check(trip_ids(Fl, "private") == [FT], "freelancer: the own trips")
r = Fl.post(B + f"/api/life/trips/{FT}/expenses")
check(r.status_code == 201 and r.json()["created"], "freelancer: travel expenses in the personal office " + r.text[:200])
r2 = Fl.post(B + f"/api/life/trips/{FT}/expenses")
check(r2.status_code == 200 and r2.json()["trip_id"] == r.json()["trip_id"], "freelancer: the same one again")
FB = Fl.get(B + "/api/books").json()["items"]
fbid = FB[0]["id"] if FB else Fl.post(B + "/api/books", json={"name": "Mine"}).json()["id"]
FC = Fl.post(B + "/api/contacts", json={"book_id": fbid, "fn": "Fred Friend"}).json()["id"]
check(Fl.put(B + f"/api/contacts/{FC}/care", json={"every_days": 30, "last": "today"}).ok, "freelancer: stay in touch")
check(care_ids(Fl, "private") == [FC], "freelancer: the own contacts to stay in touch with")
check(life(Fl, SP).status_code == 404, "freelancer: no organisation space (404)")
check(Fl.post(B + "/api/life/trips", json={"name": "X", "from": D1, "to": D2, "space": SP}).status_code == 404, "freelancer: no trip into an organisation")

# ================================================================ 2.173.1 A (#2714): review follow-ups
# the travel expenses button knows whether expenses are linked (GET, the same gate as the POST)
r = A.get(B + f"/api/life/trips/{OT}/expenses")
check(r.ok and r.json().get("trip_id") == TID2, "GET: the linked travel expenses " + r.text[:200])
check(Bo.get(B + f"/api/life/trips/{OT}/expenses").status_code == 403, "GET: a member 403")
check(Fr.get(B + f"/api/life/trips/{OT}/expenses").status_code == 404, "GET: another organisation 404")
check(requests.get(B + f"/api/life/trips/{OT}/expenses", headers=AGH).status_code in (401, 403, 404), "GET: no agent")
check(requests.get(B + f"/api/life/trips/{PT}/expenses", headers=PTH).status_code in (401, 403, 404), "GET: no API token")
NT = A.post(B + "/api/life/trips", json={"name": "Later", "from": D1, "to": D2, "packing": ""}).json()["list_id"]
r = A.get(B + f"/api/life/trips/{NT}/expenses")
check(r.ok and r.json().get("trip_id") is None, "GET: none linked yet " + r.text[:200])
r = Fl.get(B + f"/api/life/trips/{FT}/expenses")
check(r.ok and r.json().get("trip_id") == r2.json()["trip_id"], "freelancer: GET the linked travel expenses " + r.text[:200])
check(A.get(B + f"/api/life/trips/{nl}/expenses").status_code == 404, "GET: a project that is no trip: 404")

# an agent that is in an organisation's trip anyway hears nothing of it; a private trip as before
if AGID:
    ts = testclock.today().isoformat()
    for lid_ in (OT, PT):
        dbx("INSERT INTO list_members(list_id, user_id, role, added_at) VALUES(?,?,'edit',?) ON CONFLICT DO NOTHING", (lid_, AGID, ts))
    ot_t = A.post(B + "/api/tasks", json={"title": "Book hotel", "list_id": OT}).json()["id"]
    pt_t = A.post(B + "/api/tasks", json={"title": "Pack bags", "list_id": PT}).json()["id"]
    r = A.post(B + f"/api/tasks/{ot_t}/wake", json={"agent_id": AGID})
    check(r.status_code in (404, 409) or not r.json().get("ok"), "agent: no event of an organisation's trip " + r.text[:200])
    r = A.post(B + f"/api/tasks/{pt_t}/wake", json={"agent_id": AGID})
    check(r.ok and r.json().get("ok"), "agent: an event of a private trip as before " + r.text[:200])
    dbx("DELETE FROM list_members WHERE user_id=? AND list_id IN (?,?)", (AGID, OT, PT))

# the assistant leaves an organisation's trip out
A.patch(B + "/api/settings", json={"assistant_on": "1"})
r = A.put(B + "/api/assistant/lists", json={"list_ids": [OT, PT]})
if r.status_code != 404:  # the assistant is configured in this run
    ids = [x["id"] for x in r.json().get("lists", [])] if r.ok else []
    check(r.ok and OT not in ids and PT in ids, f"assistant: no organisation trip, the private one ({r.status_code} {ids})")
    A.put(B + "/api/assistant/lists", json={"list_ids": []})

# a folder default moves a trip into the organisation like the project dialog; other Home & life projects stay private
FT1 = A.post(B + "/api/life/trips", json={"name": "Fold trip", "from": D1, "to": D2, "packing": ""}).json()["list_id"]
FH = A.post(B + "/api/lists", json={"name": "Fold health", "org_id": None}).json()["id"]
check(A.patch(B + f"/api/lists/{FH}", json={"life": "health"}).ok, "folder: a health project")
for lid_ in (FT1, FH):
    check(A.patch(B + f"/api/lists/{lid_}", json={"folder": "Fold2714"}).ok, "folder set")
r = A.put(B + "/api/folders/props", json={"folder": "Fold2714", "props": {"org_id": ORG}})
check(r.ok, "folder default: organisation " + r.text[:200])
sk = {x["id"]: x.get("skipped") or [] for x in r.json().get("lists", [])} if r.ok else {}
check(dbx("SELECT org_id FROM lists WHERE id=?", (FT1,))[0][0] == ORG and not sk.get(FT1), f"folder: the trip moves along {sk.get(FT1)}")
check(dbx("SELECT org_id FROM lists WHERE id=?", (FH,))[0][0] is None and sk.get(FH), f"folder: the health project stays private {sk.get(FH)}")

# care_space reads COALESCE(org_id, owner_org_id): the organisation's own address book counts for the organisation (a book
# with owner_org_id but no org_id is not visible to anyone, so only the consistent case is reachable through the API)
check(tuple(dbx("SELECT org_id, owner_org_id FROM books WHERE id=?", (OB,))[0]) == (ORG, ORG) and OC in (care_ids(A, SP) or []),
      "care: the organisation-owned address book counts for the organisation")

# ================================================================ before 2.173: nothing rewritten
check(dbx("SELECT COUNT(*) FROM life_trip_costs")[0][0] >= 3, "the links are kept")

print(f"p2173_a_travel_care_scope: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
