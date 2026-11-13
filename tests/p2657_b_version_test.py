#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.657.0 part B (#5052): the version rule outside the core's own routes. Invented names only.
   freelancer-matrix: pim, lists
 - an agent's own calendar: PATCH /api/v1/event-calendars/<id> with a new name and no version = 400 version_required (before:
   the route took the calendar's own version for it); with the updated_at it read = changed; with an old one = 409 with
   error.current; "hidden" alone (its own view setting) needs none
 - an old calendar without a version (updated_at '' from before 2.566.0) shows created_at as its version and takes it
 - an agent's own address book: the same rule (400 / 200 / 409)
 - a project's settings: an agent's PATCH /api/v1/lists/<id> without a version = 400, with it = changed, with an old one =
   409; a person's PATCH /api/lists/<id> with an old expect_updated_at = 409 and nothing changes (before: written over), without
   one as before; the version moves on with each change of the project's row
 - ev_lock: reopening a poll puts its event into the trash under the event's lock 'event-<id>': while another connection
   holds it, the request waits and the event stays; after that COMMIT it goes (before: deleted at once)
 - the same for a person without an organisation (her own calendar, book and project)
usage: p2657_b_version_test.py <datadir>"""
import os
import subprocess
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, dbx, until  # noqa: E402

FEAT = "cal,events,contacts,comments,collab"
V = B + "/api/v1"

kt.fresh(env={"KALMIDO_API_RATE": "100000"}, prefix="P2657B")
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents (the freelancer's)
DBC, DBN = open(os.path.join(DATA, ".kalmido-db")).read().split()


def sql_w(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def agent(owner_sess, name, admin=True):
    """An agent with calendar, contacts and structure scopes -> (id, headers)."""
    url = B + ("/api/admin/agents" if admin else "/api/my/agents")
    r = owner_sess.post(url, json={"scopes": ["read", "structure", "calendar", "contacts"], "username": name, "display_name": name.title()})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    aid = j.get("user_id") or j.get("id")
    sql_w("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
          (aid, FEAT))
    return aid, {"Authorization": "Bearer " + j["token"], "X-Requested-With": "x"}


def vreq(h, m, path, **kw):
    return requests.request(m, V + path, headers=h, timeout=30, **kw)


def code(r):
    try:
        e = r.json().get("error")
    except ValueError:
        return None
    return e.get("code") if isinstance(e, dict) else None


def ver_of(h, path, rid):
    j = vreq(h, "GET", path).json()
    rows = j if isinstance(j, list) else (j.get("items") or j.get("data") or [])
    return next((x.get("updated_at") for x in rows if x.get("id") == rid), None)


def settings_rule(who, h):
    # ---- calendars
    r = vreq(h, "POST", "/event-calendars", json={"name": f"{who} plan"})
    check(r.status_code in (200, 201), f"{who}: the agent's own calendar ({r.status_code} {r.text[:120]})")
    K = r.json()["id"]
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"name": "Renamed"})
    check(r.status_code == 400 and code(r) == "version_required", f"{who}: calendar renamed without a version = 400 ({r.status_code} {r.text[:160]})")
    v1 = ver_of(h, "/event-calendars", K)
    check(bool(v1), f"{who}: the calendar shows its version ({v1})")
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"name": "Renamed", "expect_updated_at": v1})
    check(r.ok and r.json().get("name") == "Renamed" and r.json().get("updated_at") not in (None, "", v1),
          f"{who}: with the version read = renamed, a new version ({r.status_code} {r.text[:160]})")
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"color": "#336699", "expect_updated_at": v1})
    cur = (r.json().get("error") or {}).get("current") if r.status_code == 409 else None
    check(r.status_code == 409 and isinstance(cur, dict) and cur.get("name") == "Renamed",
          f"{who}: an old version = 409 with error.current ({r.status_code} {r.text[:160]})")
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"hidden": True})
    check(r.ok and r.json().get("hidden") is True, f"{who}: hidden alone needs no version ({r.status_code} {r.text[:120]})")
    vreq(h, "PATCH", f"/event-calendars/{K}", json={"hidden": False})
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"color": "#336699"})
    check(r.status_code == 400, f"{who}: the colour without a version = 400 too ({r.status_code})")
    r = requests.patch(V + f"/event-calendars/{K}", headers={**h, "If-Match": ver_of(h, "/event-calendars", K)}, json={"color": "#336699"}, timeout=30)
    check(r.ok and r.json().get("color") == "#336699", f"{who}: the version as If-Match = changed ({r.status_code} {r.text[:120]})")
    # an old calendar without a version (before 2.566.0)
    # 2.1095.0 (#5306): updated_at is TIMESTAMPTZ now - '' cannot be stored any more; core/coltype.py turned an old '' into the
    # row's created_at, which is what this state looks like after the move
    sql_w("UPDATE ev_cals SET updated_at=created_at WHERE id=?", (K,))
    created = dbx("SELECT created_at FROM ev_cals WHERE id=?", (K,))[0][0]
    v0 = ver_of(h, "/event-calendars", K)
    check(v0 == created, f"{who}: an old calendar shows created_at as its version ({v0} / {created})")
    r = vreq(h, "PATCH", f"/event-calendars/{K}", json={"name": "Old one", "expect_updated_at": v0})
    check(r.ok and r.json().get("name") == "Old one", f"{who}: and takes it ({r.status_code} {r.text[:160]})")

    # ---- address books
    r = vreq(h, "POST", "/address-books", json={"name": f"{who} contacts"})
    check(r.status_code in (200, 201), f"{who}: the agent's own address book ({r.status_code} {r.text[:120]})")
    BK = r.json()["id"]
    r = vreq(h, "PATCH", f"/address-books/{BK}", json={"name": "Clients"})
    check(r.status_code == 400 and code(r) == "version_required", f"{who}: book renamed without a version = 400 ({r.status_code} {r.text[:160]})")
    b1 = ver_of(h, "/address-books", BK)
    r = vreq(h, "PATCH", f"/address-books/{BK}", json={"name": "Clients", "expect_updated_at": b1})
    check(r.ok and r.json().get("name") == "Clients" and r.json().get("updated_at") not in (None, "", b1),
          f"{who}: with the version = renamed, a new version ({r.status_code} {r.text[:160]})")
    r = vreq(h, "PATCH", f"/address-books/{BK}", json={"color": "#aa3355", "expect_updated_at": b1})
    check(r.status_code == 409 and dbx("SELECT color FROM books WHERE id=?", (BK,))[0][0] != "#aa3355",
          f"{who}: book with an old version = 409, nothing changed ({r.status_code} {r.text[:160]})")

    # ---- projects
    r = vreq(h, "POST", "/lists", json={"name": f"{who} project"})
    check(r.status_code == 201, f"{who}: the agent's own project ({r.status_code} {r.text[:120]})")
    L = r.json()["id"]
    l0 = r.json().get("updated_at")
    check(bool(l0), f"{who}: a project shows its version ({l0})")
    r = vreq(h, "PATCH", f"/lists/{L}", json={"name": "Moved on"})
    check(r.status_code == 400 and code(r) == "version_required", f"{who}: project PATCH without a version = 400 ({r.status_code} {r.text[:160]})")
    r = vreq(h, "PATCH", f"/lists/{L}", json={"name": "Moved on", "expect_updated_at": l0})
    l1 = r.json().get("updated_at") if r.ok else None
    check(r.ok and r.json().get("name") == "Moved on" and l1 not in (None, "", l0), f"{who}: with the version = changed, a new one ({r.status_code} {r.text[:160]})")
    r = vreq(h, "PATCH", f"/lists/{L}", json={"color": "#118844", "expect_updated_at": l0})
    check(r.status_code == 409 and dbx("SELECT color FROM lists WHERE id=?", (L,))[0][0] != "#118844",
          f"{who}: project PATCH with an old version = 409, nothing changed ({r.status_code} {r.text[:160]})")
    return L


# ================================================================== an organisation's agent (alice's)
AG, AH = agent(A, "planbot")
LA = settings_rule("agent", AH)

# ================================================================== a person's web PATCH of a project's settings
L = A.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
r = A.patch(B + f"/api/lists/{L}", json={"color": "#224466"})
v0 = r.json().get("updated_at") if r.ok else None
check(bool(v0), f"a person without a version: as before, the answer carries the new version ({r.status_code} {r.text[:120]})")
r = A.patch(B + f"/api/lists/{L}", json={"color": "#224488", "expect_updated_at": v0})
v1 = r.json().get("updated_at") if r.ok else None
check(r.ok and bool(v1) and v1 != v0, f"with the version read = changed, a new version ({v0} -> {v1})")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Not this", "expect_updated_at": v0})
check(r.status_code == 409 and isinstance(r.json().get("current"), dict), f"a person with an old version = 409 with current ({r.status_code} {r.text[:160]})")
check(dbx("SELECT name FROM lists WHERE id=?", (L,))[0][0] == "Garden", "the name stays as it was")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Garden plot", "expect_updated_at": v1})
check(r.ok and dbx("SELECT name FROM lists WHERE id=?", (L,))[0][0] == "Garden plot", f"with the version now = changed ({r.status_code})")
v2 = r.json().get("updated_at") if r.ok else None
# an old project without a version: the change takes created_at
sql_w("UPDATE lists SET updated_at=created_at WHERE id=?", (L,))  # 2.1095.0 (#5306): '' is created_at after the move (core/coltype.py)
created = dbx("SELECT created_at FROM lists WHERE id=?", (L,))[0][0]
r = A.patch(B + f"/api/lists/{L}", json={"name": "Garden old", "expect_updated_at": created})
check(r.ok and dbx("SELECT name FROM lists WHERE id=?", (L,))[0][0] == "Garden old", f"an old project takes created_at as its version ({r.status_code} {r.text[:120]})")
check(v2 and v2 != v1, "the version came back with the answer")


# ================================================================== ev_lock: a poll's event goes under the event's lock
def lock_rows(eid):
    return [bool(x[0]) for x in dbx("SELECT granted FROM pg_locks WHERE locktype='advisory' AND objsubid=1 "
                                    "AND objid::text::bigint = (hashtext(?)::bigint & 4294967295)", (f"event-{eid}",))]


class Holder:
    """Another connection holding the event's lock (an open transaction in psql) until release()."""
    def __init__(self, eid):
        self.p = subprocess.Popen(["docker", "exec", "-i", DBC, "psql", "-U", "kalmido", "-d", DBN, "-X", "-q"], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        self.p.stdin.write(f"BEGIN;\nSELECT pg_advisory_xact_lock(hashtext('event-{int(eid)}'));\n")
        self.p.stdin.flush()
        self.ok = bool(until(lambda: True in lock_rows(eid), 20))

    def release(self):
        self.p.stdin.write("COMMIT;\n\\q\n")
        self.p.stdin.close()
        self.p.wait(30)


def gone(eid):
    x = dbx("SELECT deleted_at FROM events WHERE id=?", (eid,))
    return bool(x and x[0][0])


def poll_waits(who, s):
    r = s.post(B + "/api/polls", json={"title": "Team lunch", "duration": 60, "tz": "Europe/Berlin",
                                       "options": [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]})
    check(r.status_code == 201, f"{who}: a poll ({r.status_code} {r.text[:120]})")
    P = r.json()["poll"]
    r = s.post(B + f"/api/polls/{P['id']}/decide", json={"option_id": P["options"][0]["id"]})
    eid = r.json().get("event_id") if r.ok else None
    check(bool(eid), f"{who}: chosen, its event ({r.status_code} {r.text[:160]})")
    if not eid:
        return
    h = Holder(eid)
    check(h.ok, f"{who}: the other connection holds the event's lock")
    out = {}
    t = threading.Thread(target=lambda: out.update(r=s.post(B + f"/api/polls/{P['id']}/reopen")))
    t.start()
    blocked = until(lambda: False in lock_rows(eid) or not t.is_alive(), 20) and t.is_alive()
    mid = gone(eid)
    h.release()
    t.join(60)
    r = out.get("r")
    check(blocked, f"{who}: reopening waits for the event's lock (#5052)")
    check(not mid, f"{who}: the event stays while the lock is held")
    check(r is not None and r.ok and gone(eid), f"{who}: after the COMMIT the event is in the trash ({r is not None and r.status_code})")


poll_waits("alice", A)

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
FA, FH = agent(Fr, "fridabot", admin=False)
settings_rule("frida's agent", FH)
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
fv = Fr.patch(B + f"/api/lists/{FL}", json={"color": "#553311"}).json().get("updated_at")
r = Fr.patch(B + f"/api/lists/{FL}", json={"name": "x", "expect_updated_at": "2020-01-01T00:00:00.000Z"})
check(r.status_code == 409 and dbx("SELECT name FROM lists WHERE id=?", (FL,))[0][0] == "Studio", f"frida: an old version = 409 ({r.status_code})")
check(Fr.patch(B + f"/api/lists/{FL}", json={"name": "Studio 2", "expect_updated_at": fv}).ok, "frida: with the version = changed")
poll_waits("frida", Fr)

sys.exit(kt.done("p2657_b_version"))
