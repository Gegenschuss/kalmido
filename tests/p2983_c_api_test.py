#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.983.0 part C (job/4103). Invented people and titles only, everyone a person without an organisation.
freelancer-matrix: sheets, wiki, agents, lists
 - #5643 (Fable 2.937 F9): a table / a wiki page shared by e-mail address goes to an account only when that account proved
   the address (users.email_proved); an address an admin typed in that nobody proved gets nothing (a table: the address row
   stays open and is taken at the next sign-in after the proof, shs_redeem; the wiki: answered like an unknown address);
   PATCH /api/me does not set an address at all
 - 2.1001.0 (#5669): a list / a list folder shared by e-mail address goes the same way (core/access.py addr_account): an
   address nobody proved is answered like an unknown one and binds nobody (lists keep no open address share)
 - #3915: an agent watching a task gets status_changed (completed / closed / reopened) with the task's content; nothing for
   its own completion, nothing from a member it is not open to (the agent gate), nothing once it stopped watching
usage: p2983_c_api_test.py <datadir>      (KMT_NOSTART=1 / P2983C_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2983C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FEAT = "sheets,wiki,files,cal,comments,collab"
V = B + "/api/v1"


def table(s, title):
    r = s.post(B + "/api/sheets", json={"title": title, "space": "private"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def reads(s, sid):
    return s.get(B + f"/api/sheets/{sid}").status_code == 200


def page(s, path, text):
    r = s.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def wiki_shared(s):
    return {x["path"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


def proved(uid):
    return dbx("SELECT email_proved FROM users WHERE id=?", (uid,))[0][0]


FID, F = freelancer(B, A, "frida", features=FEAT)
# uma's account was made by the server's admin with the address typed in: nobody proved it (no mailed link, no OIDC)
UID, U = freelancer(B, A, "uma", features=FEAT)

# ================================================================ #5643: the profile does not take an address
r = U.patch(B + "/api/me", json={"email": "frida@example.com"})
check(dbx("SELECT email FROM users WHERE id=?", (UID,))[0][0] == "uma@example.com",
      f"#5643: PATCH /api/me sets no address (uma cannot type in somebody else's) {r.status_code}")
check(proved(UID) == "", "(setup) #5643: uma's address is not proved")

# ================================================================ #5643: a table by address
T1 = table(F, "Rates for Uma")
r = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "uma@example.com", "role": "read"})
r2 = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "nobody@example.com", "role": "read"})
check(r.status_code == r2.status_code == 201 and set(r.json()) == set(r2.json()),
      f"#5643: the answer is the same as for an address without an account {r.status_code} {r.text[:160]}")
check(not reads(U, T1), "#5643: an account whose address nobody proved does NOT read the table")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND user_id IS NOT NULL", (T1,)) == [],
      "#5643: the address row stays open (bound to no account)")
check(sess("uma").get(B + f"/api/sheets/{T1}").status_code == 404, "#5643: a sign-in with the address not proved takes nothing")

# ================================================================ #5643: a wiki page by address
W1 = page(F, "Offer for Uma", "the offer text")
r = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "uma@example.com"})
r2 = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "nobody@example.com"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5643: wiki by address: the same answer as for an unknown address {r.status_code} {r.text[:160]}")
check("Offer for Uma" not in wiki_shared(U) and U.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 404,
      "#5643: an account whose address nobody proved does NOT read the page")

# ================================================================ #5643: after the proof
dbx("UPDATE users SET email_proved='uma@example.com' WHERE id=?", (UID,))  # (a mailed link or a verified OIDC claim)
U = sess("uma")
check(reads(U, T1), "#5643: proved: the next sign-in takes the open address row, uma reads the table")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND user_id IS NOT NULL", (T1,)) == [(UID,)],
      "#5643: ... the row is bound to her account now")
T2 = table(F, "Second sheet")
check(F.post(B + f"/api/sheets/{T2}/shares", json={"email": "UMA@example.com ", "role": "read"}).status_code == 201 and reads(U, T2),
      "#5643: proved: a table shared by address afterwards opens at once (case and blanks do not matter)")
r = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "uma@example.com"})
check(r.ok and "Offer for Uma" in wiki_shared(U), f"#5643: proved: the wiki page shared by address opens {r.status_code} {r.text[:120]}")
# an address proved before and changed by the admin afterwards proves nothing any more
dbx("UPDATE users SET email='uma.new@example.com' WHERE id=?", (UID,))
T3 = table(F, "Third sheet")
check(F.post(B + f"/api/sheets/{T3}/shares", json={"email": "uma.new@example.com", "role": "read"}).status_code == 201
      and not reads(U, T3), "#5643: an address changed after the proof: nothing until it is proved again")
# Fable F1: a row bound before (to the proved old address) is checked again when the address is shared anew
r = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "uma@example.com", "role": "write"})
check(r.status_code == 201 and not reads(U, T1), f"#5643 F1: sharing the old address again does not keep / raise uma's share {r.status_code}")
rows = dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND email_key!=''", (T1,))  # uma's and nobody's address
check(len(rows) == 2 and all(x[0] is None for x in rows), f"#5643 F1: ... the address row is open again {rows}")

# ================================================================ 2.1001.0 (#5669): a list and a list folder by address


def sees(s, lid):
    return lid in {x["id"] for x in s.get(B + "/api/state").json()["lists"]}


# uma.new@example.com is uma's address now, changed by the admin after the proof above: nobody proved it
LS = F.post(B + "/api/lists", json={"name": "Moodboard for Uma", "kind": "project"}).json()["id"]
r = F.put(B + f"/api/lists/{LS}/members", json={"email": "uma.new@example.com", "role": "edit"})
r2 = F.put(B + f"/api/lists/{LS}/members", json={"email": "nobody@example.com", "role": "edit"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5669: a list by an unproved address: the same answer as for an unknown address {r.status_code} {r.text[:160]}")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LS, UID)) and not sees(U, LS),
      "#5669: an account whose address nobody proved does NOT become a member of the list")
LF = F.post(B + "/api/lists", json={"name": "Shoot plan", "kind": "project", "folder": "Clients"}).json()["id"]
r = F.put(B + "/api/folders/people", json={"folder": "Clients", "email": "uma.new@example.com", "role": "edit"})
r2 = F.put(B + "/api/folders/people", json={"folder": "Clients", "email": "nobody@example.com", "role": "edit"})
check(r.ok and r2.ok and r.json() == r2.json(), f"#5669: a list folder by an unproved address: the same answer as for an unknown one {r.text[:160]}")
check(r.json() == {"shared": 0, "updated": 0, "by_email": True} and not sees(U, LF)
      and not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LF, UID)), "#5669: ... and uma does NOT see the list in the folder")
dbx("UPDATE users SET email_proved='uma.new@example.com' WHERE id=?", (UID,))  # (a mailed link or a verified OIDC claim)
r = F.put(B + f"/api/lists/{LS}/members", json={"email": "UMA.new@example.com ", "role": "edit"})
check(r.ok and sees(U, LS), f"#5669: proved: the list shared by address reaches uma (case and blanks do not matter) {r.text[:120]}")
r = F.put(B + "/api/folders/people", json={"folder": "Clients", "email": "uma.new@example.com", "role": "edit"})
check(r.ok and sees(U, LF), f"#5669: proved: the folder shared by address reaches uma {r.text[:120]}")
# review: an address with a stray user_id is still the address path (the answer of an unknown address, nothing more)
assert F.post(B + "/api/lists", json={"name": "Contact sheet", "kind": "project", "folder": "Prints"}).ok  # (a list refuses a stray user_id: 400)
r = F.put(B + "/api/folders/people", json={"folder": "Prints", "email": "uma.new@example.com", "user_id": "x", "role": "edit"})
check(r.json() == {"shared": 0, "updated": 0, "by_email": True}, f"#5669 review: folder by address + stray user_id: the address answer {r.text[:160]}")

# 2.1017.0 (#5774): a refusal on the address path (a list with the lock has no participants) answers like an unknown address --
# a 409 for uma's proved address and ok for an unknown one told that the address has an account; nothing is written
LK = F.post(B + "/api/lists", json={"name": "Locked notes", "kind": "project", "folder": "Safebox"}).json()["id"]
dbx("UPDATE lists SET e2e='test' WHERE id=?", (LK,))  # the lock (the server holds ciphertexts only)
r = F.put(B + f"/api/lists/{LK}/members", json={"email": "uma.new@example.com", "role": "participant"})
r2 = F.put(B + f"/api/lists/{LK}/members", json={"email": "nobody@example.com", "role": "participant"})
check(r.status_code == r2.status_code == 200 and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5774: a locked list by address as participant: the same answer for uma and an unknown address {r.status_code} {r.text[:160]}")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LK, UID)) and not sees(U, LK),
      "#5774: ... and uma does NOT become a member")
r = F.put(B + "/api/folders/people", json={"folder": "Safebox", "email": "uma.new@example.com", "role": "participant"})
r2 = F.put(B + "/api/folders/people", json={"folder": "Safebox", "email": "nobody@example.com", "role": "participant"})
check(r.status_code == r2.status_code == 200 and r.json() == r2.json() == {"shared": 0, "updated": 0, "by_email": True} and not sees(U, LK),
      f"#5774: a folder with a locked list by address as participant: the same answer for uma and an unknown address {r.status_code} {r.text[:160]}")
r = F.put(B + f"/api/lists/{LK}/members", json={"user_id": UID, "role": "participant"})
check(r.status_code == 409 and r.json().get("code") == "list_e2e_member", f"#5774: the way by user_id keeps its 409 {r.status_code} {r.text[:120]}")

# ================================================================ #3915: status changes reach a watching agent


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments"]})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    t = requests.Session()
    t.headers.update({"Authorization": "Bearer " + j["token"]})
    return j["id"], t


def events(t, since=0):
    return t.get(V + "/agent/events", params={"since": since}).json().get("data") or []


def last(t):
    return max([e.get("seq", 0) for e in events(t)] or [0])


def evs(t, since, kind, tid):
    return [e for e in events(t, since) if e.get("event") == kind and ((e.get("data") or {}).get("task") or {}).get("id") == tid]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


AG, TA = agent(F, "fridabot")
L = F.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
assert F.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
check(F.put(B + f"/api/lists/{L}/members", json={"email": "uma.new@example.com", "role": "edit"}).ok
      and bool(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L, UID))), "(setup) uma is a member of the project")
TW = task(F, L, "Watched release notes")
r = F.post(B + f"/api/tasks/{TW}/watchers", json={"user_id": AG})
check(r.ok, f"(setup) the agent watches the task {r.status_code} {r.text[:160]}")
s0 = last(TA)
check(F.post(B + f"/api/tasks/{TW}/complete", json={}).ok, "(setup) Frida completes the task")
ev = evs(TA, s0, "status_changed", TW)
check(len(ev) == 1 and ev[0]["data"].get("status") == "completed" and ev[0]["data"].get("watching") is True
      and ev[0]["data"]["task"].get("title") == "Watched release notes" and (ev[0]["data"].get("list") or {}).get("id") == L,
      f"#3915: completed: the watching agent gets status_changed with the task's content {ev}")
s0 = last(TA)
assert F.post(B + f"/api/tasks/{TW}/complete", json={"status": 0}).ok
ev = evs(TA, s0, "status_changed", TW)
check(len(ev) == 1 and ev[0]["data"].get("status") == "reopened", f"#3915: reopened {ev}")
s0 = last(TA)
assert F.post(B + f"/api/tasks/{TW}/complete", json={"status": -1}).ok
ev = evs(TA, s0, "status_changed", TW)
check(len(ev) == 1 and ev[0]["data"].get("status") == "closed", f"#3915: closed (won't do) {ev}")
assert F.post(B + f"/api/tasks/{TW}/complete", json={"status": 0}).ok
s0 = last(TA)
r = TA.post(V + f"/tasks/{TW}/complete", json={})
check(r.ok and not evs(TA, s0, "status_changed", TW), f"#3915: its own completion brings it nothing {r.status_code} {r.text[:120]}")
assert F.post(B + f"/api/tasks/{TW}/complete", json={"status": 0}).ok
s0 = last(TA)  # frida's personal agent is not open to uma, a member of the project
check(U.post(B + f"/api/tasks/{TW}/complete", json={}).ok and not evs(TA, s0, "status_changed", TW),
      "#3915: a member the agent is not open to reaches it neither by a status change (agent gate)")
assert F.post(B + f"/api/tasks/{TW}/complete", json={"status": 0}).ok
TU = task(F, L, "Not watched")
s0 = last(TA)
assert F.post(B + f"/api/tasks/{TU}/complete", json={}).ok
check(not evs(TA, s0, "status_changed", TU), "#3915: a task it does not watch: nothing")
assert F.delete(B + f"/api/tasks/{TW}/watchers/{AG}").ok
s0 = last(TA)
assert F.post(B + f"/api/tasks/{TW}/complete", json={}).ok
check(not evs(TA, s0, "status_changed", TW), "#3915: no longer watching: nothing")

sys.exit(done("p2983_c_api"))
