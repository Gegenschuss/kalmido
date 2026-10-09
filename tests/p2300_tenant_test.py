#!/usr/bin/env python3
"""2.30.0 API tests: the workspace boundary beyond lists (#1036).
 - calendars and address books have a workspace (ev_cals.org_id / books.org_id, null = private): the migration of a server
   from before (into the owner's organisation unless clearly private or a member does not fit; shares untouched), the default
   of a new one, the rule for members (an organisation's one only for its members and agents, a private one never for an
   organisation's agent), moving one (409 while a member does not fit), B2: shared only with people one may see
 - the nightly boundary check (memberships across the boundary, count in GET /api/admin/orgs, an admin alert once)
 - mode workspaces (two organisations + a private person): B1 groups without a visible member stay unknown, the form of an
   organisation's list only for its members (instance admins included), folder people never bring a foreign personal agent,
   newly invited event attendees must be visible, and the cross-tenant matrix per object kind (a person of the other
   organisation, a private person and the other organisation's agent see and change nothing, by id): calendars, events,
   address books, contacts, groups, templates, CalDAV / CardDAV, the calendar feed, webhooks, export, attachments, chat
   files, forms, clients, statistics, public links, comments, folders, day plan / roadmap / occurrences
usage: p2300_tenant_test.py <datadir>      (a fresh container; the suite restarts it itself with other settings)"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MARK = "Zq7Alpha"  # in every name of the first organisation's objects: it must never show up for the others
FEAT = "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,events,contacts,clients,workload,forms"


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def restart(extra, **env):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra, **env)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **kw):
        return requests.get(V + p, headers=self.h, **kw)

    def req(self, m, p, **kw):
        return requests.request(m, V + p, headers=self.h, **kw)


def no(r, what):
    check(r.status_code in (403, 404), f"{what}: refused ({r.status_code} {r.text[:120]})")


def hidden(r, what):
    check(r.status_code in (200, 207, 403, 404) and MARK not in r.text, f"{what}: nothing of the first organisation ({r.status_code}) {r.text[:160] if MARK in r.text else ''}")


def boundary(s):
    return s.get(B + "/api/admin/orgs").json()["boundary"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "teambot", "display_name": "Team bot"})
AG1, AG1H = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "alicebot", "display_name": "Alice bot", "owner_id": 1})
PA = r.json()["id"]
check(A.patch(B + f"/api/admin/agents/{AG1}", json={"org_id": ORG}).ok and A.patch(B + f"/api/admin/agents/{PA}", json={"org_id": None}).ok,
      "setup: a team agent of the organisation, a private personal agent")

# ================================================================== the migration of calendars and address books (mode organisation)
def cal(s, name, **kw):
    r = s.post(B + "/api/evcals", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()


def book(s, name, **kw):
    r = s.post(B + "/api/books", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()


KT, KF, KPA, KX = cal(A, "Team")["id"], cal(A, "Familie")["id"], cal(A, "Agentcal")["id"], cal(A, "Mixed")["id"]
BT, BP = book(A, "Team contacts")["id"], book(A, "Privat")["id"]
TS = "2026-10-01T00:00:00+00:00"
for k, u in ((KT, BOB), (KPA, PA), (KX, AG1), (KX, PA)):
    dbx("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'view',?)", (k, u, TS), write=True)
dbx("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'view',?)", (BT, BOB, TS), write=True)
# as a 2.29 server left them: no workspace yet, the migration not run
dbx("UPDATE ev_cals SET org_id=NULL", write=True)
dbx("UPDATE books SET org_id=NULL", write=True)
dbx("DELETE FROM settings WHERE key='migr_ws2300'", write=True)
restart("")
A, Bo = sess("alice"), sess("bob")
st = A.get(B + "/api/state").json()
cw = {c["id"]: c for c in st["evcals"]}
check(cw[KT]["org_id"] == ORG and cw[KF]["org_id"] is None and cw[KPA]["org_id"] is None and cw[KX]["org_id"] is None,
      "#1036 migration: a calendar goes into the organisation; one named like Family, one with a private agent, one with agents of both stay private "
      + str({k: cw[k]["org_id"] for k in cw}))
check({m["user_id"] for m in cw[KT]["members"]} == {BOB} and {m["user_id"] for m in cw[KX]["members"]} == {AG1, PA},
      "#1036 migration: nobody loses access (the members stay)")
bw = {b["id"]: b for b in st["books"]}
check(bw[BT]["org_id"] == ORG and bw[BP]["org_id"] is None, "#1036 migration: address books the same way " + str({k: bw[k]["org_id"] for k in bw}))
check(KT in {c["id"] for c in Bo.get(B + "/api/state").json()["evcals"]}, "#1036 migration: bob still has the shared calendar")
bd = boundary(A)
check(bd["violations"] == 1 and bd["kinds"] == {"cal_agent": 1} and bd["sample"]["cal_agent"] == [[KX, AG1]],
      "#1036 boundary: the team agent in the private calendar is counted (kept, not removed) " + str(bd))
check(A.delete(B + f"/api/evcals/{KX}/members/{AG1}").ok and boundary(A)["violations"] == 0, "#1036 boundary: taken out -> 0")
check(Bo.get(B + "/api/admin/orgs").status_code == 403, "#1036 boundary: the count is for the operator only")
dbx("UPDATE settings SET value='0' WHERE key='migr_ws2300'", write=True)  # once only: nothing changes on a later start
dbx("UPDATE settings SET value='1' WHERE key='migr_ws2300'", write=True)

# ---- new calendars / address books and the rule for members (mode organisation: everyone is in the organisation)
c1 = cal(A, "Plan")
check(c1["org_id"] == ORG, "#1036: a new calendar is the organisation's by default (as a new list)")
c2 = cal(A, "Mine", org_id=None)
check(c2["org_id"] is None, "#1036: ... or private when chosen")
r = A.put(B + f"/api/evcals/{c1['id']}/members", json={"user_id": PA, "role": "view"})
check(r.status_code == 409 and "calendars and address books" in r.text, "#1036: a private agent joins no calendar of the organisation " + r.text[:120])
r = A.put(B + f"/api/evcals/{c2['id']}/members", json={"user_id": AG1, "role": "view"})
check(r.status_code == 409, "#1036: the organisation's agent joins no private calendar " + r.text[:100])
check(A.put(B + f"/api/evcals/{c1['id']}/members", json={"user_id": AG1, "role": "view"}).ok, "#1036: ... but the organisation's one")
check(A.put(B + f"/api/evcals/{c2['id']}/members", json={"user_id": PA, "role": "view"}).ok, "#1036: the private agent joins the private one")
r = A.patch(B + f"/api/evcals/{c1['id']}", json={"org_id": None})
check(r.status_code == 409 and "Team bot" in r.text, "#1036: a calendar does not become private while the organisation's agent is in it " + r.text[:100])
check(Bo.patch(B + f"/api/evcals/{c1['id']}", json={"org_id": None}).status_code in (403, 404), "#1036: only the owner moves it")
check(A.delete(B + f"/api/evcals/{c1['id']}/members/{AG1}").ok and A.patch(B + f"/api/evcals/{c1['id']}", json={"org_id": None}).json()["org_id"] is None,
      "#1036: without it, it becomes private")
check(A.patch(B + f"/api/evcals/{c1['id']}", json={"org_id": ORG}).json()["org_id"] == ORG, "#1036: and back into the organisation")
check(A.patch(B + f"/api/evcals/{c1['id']}", json={"org_id": 999}).status_code == 409, "#1036: only into an own organisation")
b1, b2 = book(A, "Clients"), book(A, "Home", org_id=None)
check(b1["org_id"] == ORG and b2["org_id"] is None, "#1036: address books: the organisation's by default, private when chosen")
check(A.put(B + f"/api/books/{b2['id']}/members", json={"user_id": AG1, "role": "view"}).status_code == 409, "#1036: the organisation's agent joins no private address book")
check(A.put(B + f"/api/books/{b1['id']}/members", json={"user_id": BOB, "role": "edit"}).ok, "#1036: a member of the organisation joins its address book")
check(A.patch(B + f"/api/books/{b2['id']}", json={"org_id": ORG}).json()["org_id"] == ORG, "#1036: an address book moves into the organisation")
ag = requests.post(V + "/event-calendars", headers=AG1H, json={"name": "Bot cal"})
check(ag.status_code in (201, 403) and (ag.status_code == 403 or ag.json()["org_id"] == ORG), "#1036: an agent's own calendar is in its workspace " + ag.text[:100])

# ---- the nightly boundary check: an admin alert once, the time of the last run
LP = A.post(B + "/api/lists", json={"name": "Private list", "org_id": None}).json()["id"]
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,?)", (LP, AG1, TS), write=True)
restart("-e KALMIDO_TENANT_CHECK=always", KALMIDO_ADMIN_ALERTS="1")
A = sess("alice")
items = []
for _ in range(20):
    items = [i for i in A.get(B + "/api/admin/alerts").json()["items"] if i["kind"] == "security" and "boundary" in i["message"].lower()]
    if items:
        break
    time.sleep(0.5)
check(len(items) == 1 and "1 memberships" in items[0]["message"] and "list_agent 1" in items[0]["message"],
      "#1036 nightly check: an admin alert (ids and counts only) " + str([i["message"] for i in items]))
time.sleep(2.5)
check(len([i for i in A.get(B + "/api/admin/alerts").json()["items"] if i["kind"] == "security" and "boundary" in i["message"].lower()]) == 1,
      "#1036 nightly check: the same findings are not reported again")
bd = boundary(A)
check(bd["violations"] == 1 and bd["checked_at"], "#1036 nightly check: count + when it ran " + str(bd))
check(A.delete(B + f"/api/lists/{LP}/members/{AG1}").ok, "cleanup: the agent out of the private list")
time.sleep(1.5)
check(boundary(A)["violations"] == 0, "#1036 nightly check: clean again")

# ================================================================== mode workspaces: two organisations + a private person
restart("-e KALMIDO_INSTANCE_MODE=workspaces")
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok and A.delete(B + f"/api/orgs/{ORG}/members/{DAVE}").ok, "setup: carol only in Beta, dave in no organisation")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "calendar", "contacts", "export", "attachments:read"],
                                         "username": "betabot", "display_name": "Beta bot"})
AGB, agb = r.json()["id"], Api(r.json()["token"])
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (BETA, AGB), write=True)
dbx("INSERT OR IGNORE INTO org_members(org_id,user_id,role) VALUES(?,?,'member')", (BETA, AGB), write=True)
check(boundary(A)["violations"] == 0, "workspaces: the boundary is clean")

# ---- the first organisation's objects (bob), all named with MARK
LA = Bo.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ORG}).json()["id"]
TA = Bo.post(B + "/api/tasks", json={"title": f"{MARK} task", "list_id": LA, "due": "2026-10-20", "repeat": "FREQ=WEEKLY"}).json()["id"]
Bo.post(B + f"/api/tasks/{TA}/comments", json={"body": f"{MARK} comment"})
CA_ = dbx("SELECT id FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TA,))[0][0]
Bo.post(B + f"/api/tasks/{TA}/attachments", files={"file": (f"{MARK}.txt", b"secret\n", "text/plain")})
AA = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TA,))[0][0]
KA = cal(Bo, f"{MARK} cal")
check(KA["org_id"] == ORG, "workspaces: bob's new calendar is his organisation's")
KA = KA["id"]
EA = Bo.post(B + "/api/events", json={"title": f"{MARK} event", "start": "2026-10-21T10:00", "end": "2026-10-21T11:00", "cal_id": KA}).json()["id"]
BA = book(Bo, f"{MARK} book")["id"]
CTA = Bo.post(B + "/api/contacts", json={"book_id": BA, "given": MARK, "family": "Contact"}).json()["id"]
TPA = Bo.post(B + "/api/templates", json={"task_id": TA, "name": f"{MARK} template"}).json()["id"]
r = Bo.post(B + f"/api/lists/{LA}/forms", json={"title": f"{MARK} form"})
check(r.status_code == 201, "setup: a form " + r.text[:100])
FA, FURL = r.json()["id"], r.json()["url"].replace("https://kalmido.example", "")
r = Bo.post(B + "/api/clients", json={"name": f"{MARK} client", "org_id": ORG})
check(r.status_code == 201, "setup: a client " + r.text[:100])
CLA = r.json()["id"]
r = A.post(B + "/api/admin/groups", json={"name": f"{MARK} group", "members": [1, BOB]})
GA = r.json()["id"]
WA = Bo.post(B + "/api/me/webhooks", json={"name": "w", "url": "https://hooks.example.invalid/hook", "events": ["task.created"]}).json()["id"]
LAG = A.post(B + "/api/lists", json={"name": f"{MARK} agent list", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{LAG}/members", json={"user_id": AG1, "role": "edit"}).ok
r = A.post(B + f"/api/agents/{AG1}/chat", data={"body": "look"}, files=[("file", (f"{MARK}.txt", b"chat file\n", "text/plain"))])
check(r.status_code == 201, "setup: a chat file " + r.text[:120])
FC = (r.json().get("attachments") or [{}])[0].get("id")
# 2.34.0 (#272): a planned job of the organisation's team agent (alice, on the agent's list)
r = A.post(B + f"/api/agents/{AG1}/schedules", json={"title": f"{MARK} plan", "prompt": f"{MARK} prompt", "freq": "daily", "time": "09:00",
                                                       "tz": "Europe/Berlin", "list_id": LAG})
check(r.status_code in (200, 201), "setup: a planned job " + r.text[:120])
SCH = r.json().get("id")

# ---- B2 / B3: sharing calendars and address books
r = Bo.put(B + f"/api/evcals/{KA}/members", json={"user_id": CAROL, "role": "view"})
check(r.status_code == 404, "#1036 B2: a calendar is not shared with an invisible person (404 like an unknown id) " + r.text[:80])
check(Bo.put(B + f"/api/books/{BA}/members", json={"user_id": DAVE, "role": "view"}).status_code == 404, "#1036 B2: ... nor an address book")
check(Bo.put(B + f"/api/evcals/{KA}/members", json={"user_id": AGB, "role": "view"}).status_code in (404, 409), "#1036: nor the other organisation's agent")
# dave becomes a connection of bob (a private list shared by e-mail): visible, but still not in the organisation
LPB = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
assert Bo.put(B + f"/api/lists/{LPB}/members", json={"email": "dave@example.com"}).ok
r = Bo.put(B + f"/api/evcals/{KA}/members", json={"user_id": DAVE, "role": "view"})
check(r.status_code == 409 and "not a member of the organisation" in r.text, "#1036 B3: an organisation's calendar only for its members " + r.text[:100])
check(Bo.put(B + f"/api/books/{BA}/members", json={"user_id": DAVE, "role": "view"}).status_code == 409, "#1036 B3: ... and its address book")
KP = cal(Bo, "Bob's own", org_id=None)["id"]
check(Bo.put(B + f"/api/evcals/{KP}/members", json={"user_id": DAVE, "role": "view"}).ok, "#1036 B3: a private calendar is shared with a connection")
r = Bo.patch(B + f"/api/evcals/{KP}", json={"org_id": ORG})
check(r.status_code == 409 and "Dave" in r.text, "#1036 B3: it cannot go into the organisation while dave is in it " + r.text[:100])
check(Bo.patch(B + f"/api/evcals/{KP}", json={"org_id": BETA}).status_code == 409, "#1036: nor into an organisation bob is not in")
r = requests.put(V + f"/event-calendars/{KA}/members/{DAVE}", headers=AG1H, json={"role": "view"})
check(r.status_code in (403, 404, 409), "#1036: the API refuses the same (an agent is no calendar owner) " + str(r.status_code))
# event attendees: a person newly invited to an existing event must be visible
r = Bo.patch(B + f"/api/events/{EA}", json={"attendees": [{"user_id": CAROL}]})
check(r.status_code in (400, 404), "#1036: an invisible person is not invited to an existing event " + r.text[:80])

# ---- B1 groups: a group without anybody one may see is not known
gn = lambda s: [g_["name"] for g_ in s.get(B + "/api/groups").json()["groups"]]
check(f"{MARK} group" in gn(Bo) and f"{MARK} group" not in gn(Ca), "#1036 B1: the group's name stays inside its organisation " + str(gn(Ca)))
check(f"{MARK} group" not in gn(Da), "#1036 B1: ... also for a private connection of one member (dave knows bob) " + str(gn(Da)))
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
no(Ca.put(B + f"/api/lists/{LB}/groups/{GA}", json={"role": "edit"}), "#1036 B1: carol cannot share with the group by id")
no(agb.get(f"/groups/{GA}"), "#1036 B1: nor the other organisation's agent read it")
GE = A.post(B + "/api/admin/groups", json={"name": "Empty group"}).json()["id"]
check("Empty group" in gn(A) and "Empty group" not in gn(Bo), "#1036 B1: an empty group: its creator keeps it, nobody else sees it")
dbx("INSERT OR IGNORE INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GA, CAROL, TS), write=True)
gm = {g_["id"]: g_ for g_ in Ca.get(B + "/api/groups").json()["groups"]}
check(GA in gm, "B1: a member of the group knows it (a group in common connects its members, as before)")
check(BOB not in [m["user_id"] for m in agb.get(f"/groups/{GA}").json().get("members", [])], "B1: the API shows no invisible member either")
dbx("DELETE FROM group_members WHERE group_id=? AND user_id=?", (GA, CAROL), write=True)

# ---- forms: an organisation's form only for its members (the instance admin is no exception in this mode)
r = Ca.post(B + f"/api/lists/{LB}/forms", json={"title": "Beta form"})
FB = r.json()["url"].replace("https://kalmido.example", "")
check(Da.get(B + FB).status_code == 404 and A.get(B + FB).status_code == 404, "#1036: Beta's form is not for dave or the instance admin")
check(Ca.get(B + FB).status_code == 200, "#1036: ... but for Beta")
check(Ca.get(B + FURL).status_code == 404 and Da.get(B + FURL).status_code == 404, "#1036: the first organisation's form not for carol / dave")

# ---- folder people never bring somebody else's personal agent into a member's new list (#929 + #1036)
LF = A.post(B + "/api/lists", json={"name": "Shared folder list", "folder": "Proj", "org_id": ORG}).json()["id"]
PA2 = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "alicebot2", "display_name": "Alice bot 2", "owner_id": 1}).json()["id"]
check(A.patch(B + f"/api/admin/agents/{PA2}", json={"org_id": ORG}).ok, "setup: alice's personal agent in the organisation")
check(A.put(B + "/api/folders/people", json={"folder": "Proj", "user_id": BOB, "role": "edit"}).ok
      and A.put(B + "/api/folders/people", json={"folder": "Proj", "user_id": PA2, "role": "edit"}).ok, "setup: the folder shared with bob and alice's agent")
LBN = Bo.post(B + "/api/lists", json={"name": "Bob in Proj", "folder": "Proj"}).json()["id"]
mem = {r_[0] for r_ in dbx("SELECT user_id FROM list_members WHERE list_id=?", (LBN,))}
check(1 in mem and PA2 not in mem, "#1036: bob's new list in the shared folder goes to alice, not to alice's personal agent " + str(mem))
no(Ca.put(B + "/api/folders/people", json={"folder": "X", "user_id": BOB, "role": "edit"}), "#1036 folder: carol cannot share a folder with an invisible person")

# ================================================================== the cross-tenant matrix per object kind
# tenant-matrix: calendar, event, book, contact, group, template, dav, ical, webhook, export, attachment, chatfile, form, client, stats, publiclink, comment, folder, aggregate, task, list, people, agent
for name, s in (("carol", Ca), ("dave", Da)):
    st = s.get(B + "/api/state").json()
    hidden(s.get(B + "/api/state"), f"matrix {name}: state")
    check(KA not in {c["id"] for c in st["evcals"]} and BA not in {b["id"] for b in st["books"]}, f"matrix {name}: no calendar / address book of the first organisation")
    # calendars + events
    no(s.patch(B + f"/api/evcals/{KA}", json={"name": "x"}), f"matrix {name}: calendar PATCH")
    no(s.delete(B + f"/api/evcals/{KA}"), f"matrix {name}: calendar DELETE")
    no(s.put(B + f"/api/evcals/{KA}/members", json={"user_id": CAROL if s is Ca else DAVE}), f"matrix {name}: join a calendar")
    no(s.get(B + f"/api/evcals/{KA}/export.ics"), f"matrix {name}: calendar export")
    no(s.get(B + f"/api/events/{EA}"), f"matrix {name}: event GET")
    no(s.patch(B + f"/api/events/{EA}", json={"title": "x"}), f"matrix {name}: event PATCH")
    no(s.post(B + f"/api/events/{EA}/rsvp", json={"partstat": "accepted"}), f"matrix {name}: event reply")
    hidden(s.get(B + "/api/events?from=2026-10-01&to=2026-10-31"), f"matrix {name}: event range")
    no(s.get(B + f"/api/events?from=2026-10-01&to=2026-10-31&calendar_id={KA}"), f"matrix {name}: a range of the calendar")
    hidden(s.get(B + "/api/calendars/events?from=2026-10-01&to=2026-10-31"), f"matrix {name}: calendar views")
    # address books + contacts
    no(s.patch(B + f"/api/books/{BA}", json={"name": "x"}), f"matrix {name}: address book PATCH")
    no(s.get(B + f"/api/books/{BA}/export.vcf"), f"matrix {name}: address book export")
    no(s.get(B + f"/api/contacts/{CTA}"), f"matrix {name}: contact GET")
    no(s.patch(B + f"/api/contacts/{CTA}", json={"note": "x"}), f"matrix {name}: contact PATCH")
    no(s.delete(B + f"/api/contacts/{CTA}"), f"matrix {name}: contact DELETE")
    hidden(s.get(B + f"/api/contacts?q={MARK}"), f"matrix {name}: contact search")
    # tasks, comments, attachments, chat files
    no(s.get(B + f"/api/tasks/{TA}"), f"matrix {name}: task GET")
    no(s.patch(B + f"/api/comments/{CA_}", json={"body": "x"}), f"matrix {name}: comment PATCH")
    no(s.post(B + f"/api/comments/{CA_}/reactions", json={"emoji": "+1"}), f"matrix {name}: comment reaction")
    no(s.get(B + f"/api/attachments/{AA}"), f"matrix {name}: attachment GET")
    no(s.delete(B + f"/api/attachments/{AA}"), f"matrix {name}: attachment DELETE")
    if FC:
        no(s.get(B + f"/api/chat-files/{FC}"), f"matrix {name}: chat file GET")
    # templates
    no(s.patch(B + f"/api/templates/{TPA}", json={"name": "x"}), f"matrix {name}: template PATCH")
    no(s.post(B + f"/api/templates/{TPA}/apply", json={}), f"matrix {name}: template apply")
    no(s.post(B + "/api/templates", json={"task_id": TA}), f"matrix {name}: a template from a foreign task")
    hidden(s.get(B + "/api/templates"), f"matrix {name}: template list")
    # forms, clients, workload
    no(s.patch(B + f"/api/forms/{FA}", json={"title": "x"}), f"matrix {name}: form PATCH")
    no(s.get(B + f"/api/lists/{LA}/forms"), f"matrix {name}: forms of a foreign list")
    no(s.get(B + f"/api/clients/{CLA}"), f"matrix {name}: client GET")
    no(s.patch(B + f"/api/clients/{CLA}", json={"name": "x"}), f"matrix {name}: client PATCH")
    hidden(s.get(B + "/api/clients"), f"matrix {name}: client list")
    hidden(s.get(B + "/api/workload"), f"matrix {name}: workload")
    # webhooks, public link, lists, folders
    no(s.patch(B + f"/api/me/webhooks/{WA}", json={"name": "x"}), f"matrix {name}: webhook PATCH")
    no(s.get(B + f"/api/me/webhooks/{WA}/log"), f"matrix {name}: webhook log")
    no(s.get(B + f"/api/lists/{LA}/public-link"), f"matrix {name}: public link of a foreign list")
    no(s.get(B + f"/api/lists/{LA}/owner"), f"matrix {name}: list GET")
    hidden(s.get(B + "/api/folders/props?folder=Proj"), f"matrix {name}: folder settings are only the own folder's")
    hidden(s.get(B + "/api/folders/people?folder=Proj"), f"matrix {name}: folder people are only the own folder's")
    # aggregates: export, statistics, feed, day plan, roadmap, occurrences, tags
    hidden(s.get(B + "/api/export.json"), f"matrix {name}: export")
    hidden(s.get(B + "/api/stats"), f"matrix {name}: statistics")
    hidden(s.get(B + "/api/dayplan"), f"matrix {name}: day plan")
    hidden(s.get(B + "/api/roadmap"), f"matrix {name}: roadmap")
    hidden(s.get(B + "/api/occurrences?from=2026-10-01&to=2026-12-31"), f"matrix {name}: occurrences")
    # 2.34.0: stale tasks (#266), time gaps (#269), planned agent jobs (#272)
    hidden(s.get(B + "/api/stale"), f"matrix {name}: stale tasks")
    no(s.get(B + f"/api/stale?list_id={LA}"), f"matrix {name}: stale tasks of a foreign list")
    hidden(s.get(B + "/api/time/gaps"), f"matrix {name}: time gaps")
    no(s.get(B + f"/api/agents/{AG1}/schedules"), f"matrix {name}: planned jobs of a foreign agent")
    no(s.post(B + f"/api/agents/{AG1}/schedules", json={"title": "x", "prompt": "x", "freq": "daily", "time": "09:00", "tz": "Europe/Berlin"}),
       f"matrix {name}: plan a job for a foreign agent")
    no(s.patch(B + f"/api/agent-schedules/{SCH}", json={"enabled": False}), f"matrix {name}: planned job PATCH")
    no(s.post(B + f"/api/agent-schedules/{SCH}/run"), f"matrix {name}: planned job run now")
    no(s.delete(B + f"/api/agent-schedules/{SCH}"), f"matrix {name}: planned job DELETE")
    s.post(B + "/api/ical", json={"action": "create"})
    hidden(requests.get(B + s.get(B + "/api/ical").json()["url"].replace("https://kalmido.example", "")), f"matrix {name}: calendar feed")
    # people: invitations / sign-in links are no way to reach somebody of another organisation
    uname = "carol" if s is Ca else "dave"
    pw = s.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()
    dav = requests.Session()
    dav.auth = (uname, pw.get("password") or pw.get("token") or "")
    for path in (f"/dav/calendars/{uname}/", f"/dav/addressbooks/{uname}/"):
        hidden(dav.request("PROPFIND", B + path, headers={"Depth": "1"}), f"matrix {name}: DAV {path}")
    check(dav.request("PROPFIND", B + f"/dav/calendars/{uname}/e{KA}/", headers={"Depth": "1"}).status_code in (403, 404), f"matrix {name}: DAV the foreign calendar")
    check(dav.request("PROPFIND", B + f"/dav/addressbooks/{uname}/b{BA}/", headers={"Depth": "1"}).status_code in (403, 404), f"matrix {name}: DAV the foreign address book")
    check(dav.request("PROPFIND", B + "/dav/calendars/bob/", headers={"Depth": "1"}).status_code in (403, 404), f"matrix {name}: DAV bob's home")
# the instance admin reaches nobody of Beta through the account routes (people)
for path in (f"/api/users/{CAROL}/signin-link", f"/api/users/{CAROL}/invite"):
    no(A.post(B + path, json={}), f"matrix people: {path} for an invisible person")
# the other organisation's agent (REST API)
for p in (f"/tasks/{TA}", f"/events/{EA}", f"/contacts/{CTA}", f"/clients/{CLA}", f"/attachments/{AA}", f"/lists/{LA}", f"/lists/{LA}/forms"):
    no(agb.get(p), f"matrix agent: GET {p}")
if FC:
    no(agb.get(f"/chat-attachments/{FC}"), "matrix agent: chat file")
# 2.34.0: a file's text (#368), stale tasks (#266), time gaps (#269), the agent's planned jobs (#272)
no(agb.get(f"/attachments/{AA}/text"), "matrix agent: the text of a foreign file")
no(agb.get(f"/stale?list_id={LA}"), "matrix agent: stale tasks of a foreign list")
no(agb.get(f"/time/gaps?user_id={BOB}"), "matrix agent: time gaps of a person of the other organisation")
no(agb.req("PATCH", f"/event-calendars/{KA}", json={"name": "x"}), "matrix agent: calendar PATCH")
no(agb.req("PATCH", f"/address-books/{BA}", json={"name": "x"}), "matrix agent: address book PATCH")
no(agb.req("PATCH", f"/templates/{TPA}", json={"name": "x"}), "matrix agent: template PATCH")
no(agb.req("PATCH", f"/forms/{FA}", json={"title": "x"}), "matrix agent: form PATCH")
for p in ("/event-calendars", "/address-books", "/events?from=2026-10-01&to=2026-10-31", "/contacts", "/templates", "/export", "/search?q=" + MARK, "/tasks", "/lists", "/stale", "/time/gaps", "/agent/schedules"):
    hidden(agb.get(p), f"matrix agent: {p}")
# webhooks: carol's hook gets nothing of the first organisation (deliveries only for visible tasks)
WC = Ca.post(B + "/api/me/webhooks", json={"name": "c", "url": "https://hooks.example.invalid/hook", "events": ["task.created"]}).json()["id"]
Bo.post(B + "/api/tasks", json={"title": f"{MARK} later", "list_id": LA})
Ca.post(B + "/api/tasks", json={"title": "Beta later", "list_id": LB})
time.sleep(1.5)
q = dbx("SELECT payload FROM webhook_queue WHERE webhook_id=?", (WC,))
lg = dbx("SELECT COUNT(*) FROM webhook_log WHERE webhook_id=?", (WC,))[0][0]
check(not any(MARK in r_[0] for r_ in q) and (q or lg), f"matrix webhook: carol's hook has her own task, nothing of the first organisation ({len(q)} queued, {lg} logged)")
check(SCH in {x["id"] for x in A.get(B + f"/api/agents/{AG1}/schedules").json().get("data", [])},
      "matrix agent: the planned job is untouched (nobody of the other organisation changed or deleted it)")
check(boundary(A)["violations"] == 0, "the boundary is still clean after the whole suite")

print(f"\np2300_tenant: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
