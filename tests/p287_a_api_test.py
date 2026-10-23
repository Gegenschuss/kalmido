#!/usr/bin/env python3
"""2.87.0 API tests, part A: the organisation boundary of event invitations and of list hand-overs (audit T3 H1 + H2,
#1983 #1984). Invented names only.
 - #1983: a person (and their agent) who leaves an organisation, or is removed by an admin, is no longer invited to the
   events of its calendars: the event is gone from GET /api/events/<id> (404), the range, the RSVP (404) and the CalDAV
   invitations collection; an invitation to a private calendar's event stays; a stale invitation row of a former member is
   ignored by the read layer, counted by the boundary check (att_person) and taken out by "Clean up"; a new invitation of
   someone outside the calendar's organisation is refused (409 naming the rule, an invisible one is an unknown user); an
   event with such a person does not move into an organisation's calendar; a calendar moves into an organisation only while every
   invited person fits it (409)
 - #1984: a list goes only to a person the owner may see (or a member of the list): an id of another organisation answers
   exactly like an id that does not exist (web + API v1); a visible person still gets it; a freelancer without an
   organisation hands a private list to a contact
usage: p287_a_api_test.py <datadir>      (a fresh container; P287A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
DAY = "2026-11-12"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P287A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "erin", "dave", "fred", "gina"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u in ("bob", "carol", "erin") else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})
assert r.status_code in (200, 201), r.text
S = {u: sess(u) for u in ("bob", "carol", "erin", "fred", "gina")}
for s_ in S.values():
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,events,contacts"})
A.patch(B + "/api/settings", json={"features": "cal,comments,events,contacts"})


def cal(s, name, org):
    r = s.post(B + "/api/evcals", json={"name": name, "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


def event(s, cid, title, who, hour=10):
    r = s.post(B + "/api/events", json={"cal_id": cid, "title": title, "start": f"{DAY}T{hour:02d}:00", "end": f"{DAY}T{hour + 1:02d}:00",
                                        "attendees": [{"user_id": x} for x in who]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def in_range(s, eid):
    r = s.get(B + f"/api/events?from={DAY}&to={DAY}")
    return r.ok and eid in {x["eid"] for x in r.json().get("items", [])}


def dav_inv(user, pw):
    r = requests.request("PROPFIND", B + f"/dav/calendars/{user}/inv/", auth=(user, pw),
                         data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>',
                         headers={"Depth": "1", "X-Forwarded-Proto": "https"}, allow_redirects=False)
    return r.status_code, r.text


TEAM = cal(A, "Team", ORG)
HOME = cal(A, "Home", None)

# ================================================================== #1983: leaving an organisation ends its invitations
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
r = S["bob"].post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot"})
BOT = r.json().get("id") if r.ok else None
check(BOT is not None, f"setup: bob's personal agent {r.status_code} {r.text[:160]}")
E1 = event(A, TEAM, "Quarterly review", [uid["bob"], uid["carol"]])
E2 = event(A, HOME, "Garden party", [uid["bob"]], 14)
if BOT:
    dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, BOT))
    dbx("INSERT INTO event_attendees(event_id, user_id, partstat) VALUES(?, ?, 'needs-action')", (E1, BOT))
Bo = S["bob"]
check(Bo.get(B + f"/api/events/{E1}").ok and in_range(Bo, E1), "setup: bob sees the team event he is invited to")
check(Bo.post(B + f"/api/events/{E1}/rsvp", json={"partstat": "accepted"}).ok, "setup: bob answers the invitation")
r = Bo.post(B + "/api/me/app-passwords", json={"name": "Phone"})
BPW = r.json().get("password", "") if r.ok else ""
st, body = dav_inv("bob", BPW)
check(st == 207 and body.count(".ics") == 2, f"setup: bob's CalDAV invitations hold both events ({st}, {body.count('.ics')})")

r = Bo.delete(B + f"/api/orgs/{ORG}/members/{uid['bob']}")
check(r.ok, f"bob leaves the organisation {r.status_code} {r.text[:160]}")
check(not dbx("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (E1, uid["bob"])),
      "#1983: bob's invitation to the team event is removed")
if BOT:
    check(not dbx("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (E1, BOT)), "#1983: ... his agent's too")
check(dbx("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (E1, uid["carol"])) != [], "#1983: carol stays invited")
check(Bo.get(B + f"/api/events/{E1}").status_code == 404, "#1983: the team event is gone for bob (404)")
check(not in_range(Bo, E1), "#1983: ... not in his range")
check(Bo.post(B + f"/api/events/{E1}/rsvp", json={"partstat": "declined"}).status_code == 404, "#1983: ... no answer (404)")
check(Bo.get(B + f"/api/events/{E2}").ok and in_range(Bo, E2), "#1983: the private calendar's invitation stays")
check(Bo.post(B + f"/api/events/{E2}/rsvp", json={"partstat": "accepted"}).ok, "#1983: ... and bob still answers it")
st, body = dav_inv("bob", BPW)
check(st == 207 and body.count(".ics") == 1, f"#1983: CalDAV invitations keep only the private event ({st}, {body.count('.ics')})")
check(S["carol"].get(B + f"/api/events/{E1}").ok, "#1983: carol still sees the team event")

# a stale invitation row (e.g. from before 2.87): ignored by the read layer, counted and cleaned up by the boundary check
dbx("INSERT INTO event_attendees(event_id, user_id, partstat) VALUES(?, ?, 'accepted')", (E1, uid["bob"]))
check(Bo.get(B + f"/api/events/{E1}").status_code == 404 and not in_range(Bo, E1), "#1983: a left-over row gives bob nothing")
check(Bo.post(B + f"/api/events/{E1}/rsvp", json={"partstat": "declined"}).status_code == 404, "#1983: ... no answer either")
st, body = dav_inv("bob", BPW)
check(body.count(".ics") == 1, f"#1983: ... nor over CalDAV ({body.count('.ics')})")
bd = A.get(B + "/api/admin/orgs").json().get("boundary", {})
check(bd.get("kinds", {}).get("att_person") == 1, f"#1983: the boundary check counts the invitation (att_person) {bd.get('kinds')}")
det = [x for x in bd.get("details", []) if x.get("kind") == "att_person"]
check(det and det[0].get("type") == "event" and det[0].get("name") == "Quarterly review" and det[0].get("fixable"),
      f"#1983: ... named with the event for the admin {det}")
r = A.post(B + "/api/admin/orgs/boundary/repair")
check(r.ok and r.json().get("kinds", {}).get("att_person") == 1, f"#1983: Clean up takes it out {r.text[:200]}")
check(not dbx("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (E1, uid["bob"])), "#1983: ... the row is gone")

# removed by an admin
Er = S["erin"]
E3 = event(A, TEAM, "Planning day", [uid["erin"]], 16)
check(Er.get(B + f"/api/events/{E3}").ok, "setup: erin sees her invitation")
r = A.delete(B + f"/api/orgs/{ORG}/members/{uid['erin']}")
check(r.ok, f"the admin removes erin {r.status_code} {r.text[:160]}")
check(Er.get(B + f"/api/events/{E3}").status_code == 404 and not in_range(Er, E3), "#1983: removed by the admin: the event is gone")
check(Er.post(B + f"/api/events/{E3}/rsvp", json={"partstat": "accepted"}).status_code == 404, "#1983: ... no answer (404)")

# new invitations: only people of the calendar's organisation; a private calendar invites who one may see (gina: a contact
# of alice outside the organisation)
lo, hi = sorted((ALICE, uid["gina"]))
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-18T10:00:00.000Z')", (lo, hi))
r = A.post(B + "/api/events", json={"cal_id": TEAM, "title": "Lunch", "start": f"{DAY}T12:00", "attendees": [{"user_id": uid["gina"]}]})
# 2.87.0 (#1983, review): a visible person outside the organisation gets the workspace rule (409), an invisible one stays unknown
check(r.status_code == 409 and "Gina" in r.text and "not a member" in r.text, f"#1983: an organisation's event invites nobody outside it {r.status_code} {r.text[:160]}")
r = A.patch(B + f"/api/events/{E1}", json={"attendees": [{"user_id": uid["carol"]}, {"user_id": uid["gina"]}]})
check(r.status_code == 409 and "Gina" in r.text, f"#1983: ... also when editing ({r.status_code})")
r = A.post(B + "/api/events", json={"cal_id": TEAM, "title": "Lunch", "start": f"{DAY}T12:00", "attendees": [{"user_id": uid["dave"]}]})
check(r.status_code == 400 and "unknown user" in r.text, f"#1983: ... someone one may not see stays an unknown user {r.status_code} {r.text[:160]}")
r = A.post(B + "/api/events", json={"cal_id": HOME, "title": "Tea", "start": f"{DAY}T17:00", "attendees": [{"user_id": uid["gina"]}]})
check(r.status_code == 201 and S["gina"].get(B + f"/api/events/{r.json().get('id')}").ok if r.status_code == 201 else False,
      f"#1983: a private calendar still invites a contact outside the organisation {r.status_code} {r.text[:160]}")
TEA = r.json().get("id") if r.status_code == 201 else 0
r = A.patch(B + f"/api/events/{TEA}", json={"cal_id": TEAM})
check(r.status_code == 409 and "Gina" in r.text, f"#1983 (review): an event with an outsider does not move into an organisation's calendar {r.status_code} {r.text[:160]}")
check(dbx("SELECT cal_id FROM events WHERE id=?", (TEA,)) == [(HOME,)], "#1983 (review): ... it stays in the private calendar")
r = A.patch(B + f"/api/events/{E1}", json={"title": "Quarterly review!", "attendees": [{"user_id": uid["carol"]}]})
check(r.ok, f"#1983: editing with the organisation's people still works {r.status_code} {r.text[:160]}")
# a calendar moves into the organisation only while its invited people fit (bob is invited to the garden party)
r = A.patch(B + f"/api/evcals/{HOME}", json={"org_id": ORG})
check(r.status_code == 409 and "Bob" in r.text, f"#1983: a calendar with an invited outsider does not move into the organisation {r.status_code} {r.text[:160]}")
check(dbx("SELECT org_id FROM ev_cals WHERE id=?", (HOME,)) == [(None,)], "#1983: ... it stays private")

# ================================================================== #1984: list hand-over only to visible people
L = A.post(B + "/api/lists", json={"name": "Offsite ideas", "org_id": None}).json()["id"]
r_unknown = A.post(B + f"/api/lists/{L}/owner", json={"user_id": 999999})
r_hidden = A.post(B + f"/api/lists/{L}/owner", json={"user_id": uid["dave"]})
check(r_hidden.status_code == 404 and r_hidden.status_code == r_unknown.status_code and r_hidden.json() == r_unknown.json(),
      f"#1984: a person of another organisation answers like an unknown id {r_hidden.status_code} {r_hidden.text[:120]} / {r_unknown.text[:120]}")
check(dbx("SELECT owner_id FROM lists WHERE id=?", (L,)) == [(ALICE,)], "#1984: the list stays with alice")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L, uid["dave"])), "#1984: dave got nothing")
r = A.post(B + "/api/me/tokens", json={"name": "owner", "scopes": ["read", "write", "structure"]})
TK = {"Authorization": "Bearer " + r.json().get("token", "")} if r.ok else {}
v_unknown = requests.post(V + f"/lists/{L}/owner", headers=TK, json={"user_id": 999999})
v_hidden = requests.post(V + f"/lists/{L}/owner", headers=TK, json={"user_id": uid["dave"]})
check(v_hidden.status_code == 404 and v_hidden.status_code == v_unknown.status_code and v_hidden.json() == v_unknown.json(),
      f"#1984: API v1 answers the same for both {v_hidden.status_code} {v_hidden.text[:120]} / {v_unknown.status_code} {v_unknown.text[:120]}")
check(dbx("SELECT owner_id FROM lists WHERE id=?", (L,)) == [(ALICE,)], "#1984: ... the list still stays with alice")
r = A.post(B + f"/api/lists/{L}/owner", json={"user_id": uid["carol"]})
check(r.ok and dbx("SELECT owner_id FROM lists WHERE id=?", (L,)) == [(uid["carol"],)], f"#1984: a visible person still gets the list {r.status_code} {r.text[:160]}")

# a freelancer without an organisation: own contact yes, a stranger no
Fr = S["fred"]
FL = Fr.post(B + "/api/lists", json={"name": "Workshop"}).json()["id"]
r = Fr.post(B + f"/api/lists/{FL}/owner", json={"user_id": uid["gina"]})
check(r.status_code == 404 and "unknown user" in r.text, f"#1984: a freelancer cannot hand a list to someone they are not connected with ({r.status_code})")
lo, hi = sorted((uid["fred"], uid["gina"]))
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-18T10:00:00.000Z')", (lo, hi))
r = Fr.post(B + f"/api/lists/{FL}/owner", json={"user_id": uid["gina"]})
check(r.ok and dbx("SELECT owner_id FROM lists WHERE id=?", (FL,)) == [(uid["gina"],)],
      f"#1984: ... but to a contact {r.status_code} {r.text[:160]}")
FL2 = Fr.post(B + "/api/lists", json={"name": "Sketches"}).json()["id"]
r = Fr.post(B + f"/api/lists/{FL2}/owner", json={"user_id": uid["carol"]})
check(r.status_code == 404, f"#1984: ... never to a person of an organisation they are not connected with ({r.status_code})")

print(f"p287_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
