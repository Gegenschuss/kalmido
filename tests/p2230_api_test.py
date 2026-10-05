#!/usr/bin/env python3
"""2.23.0 API tests: package C "Team, family, clients" (#463) and the ride-alongs, own container (start.sh) with the
SMTP stub (stub_mail.py). Clients (#463: only within the organisation, lists of a client, hours / amounts with the
client's rate as the fallback, estimate vs. actual, budget levels, the timesheet = the time report of the client's lists,
the module switch, delete rights), workload (organisation, capacity, weeks, estimate, overdue, no date, what the viewer
sees), approvals as a task type (request -> assigned, only the approver decides, approve = done, changes = back to the
person who asked, reject = won't do, News, agents never decide), forms -> tasks (#341: org / public access, the switch
Public links, a sent form = a task with the sender, the honeypot, limits, cross-site refused, events for the list's agent
with source form), #444 sign-in links + QR (admins, parents for their kids, never for admins, once, signs in), #711
self-registration (off / domain / approval / open, the same answer for taken or foreign addresses, the user name from the
address, the organisation from its domains, the confirmation mail, waiting for approval, approve), #795 the agent event
task_added (created in / moved into a list shared with the agent, moved_from only when visible), API v1 + OpenAPI."""
import email as _em
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def dbx(q, a=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": pw}).ok, u
    return s


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def events(aid):
    return [json.loads(r[0]) for r in dbx("SELECT payload FROM agent_events WHERE agent_id=? ORDER BY id", (aid,))]


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025"
           " -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,time,progress,agents"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
T0 = date.today()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
# ================================================================== #799: the kind of instance (no variable, one organisation = organisation)
oj = A.get(B + "/api/admin/orgs").json()
check(oj["mode"] == "organisation" and len(oj["orgs"]) == 1 and not oj["editable"] and set(oj["orgs"][0]["members"]) >= {1, BOB, CAROL},
      "#799: organisation mode by default: one organisation with everyone " + json.dumps(oj)[:200])
ORG1 = oj["orgs"][0]["id"]
check(A.post(B + "/api/admin/orgs", json={"name": "New"}).status_code == 403 and A.delete(B + f"/api/admin/orgs/{ORG1}").status_code == 403
      and A.patch(B + f"/api/admin/orgs/{ORG1}", json={"name": "X"}).status_code == 403
      and A.put(B + "/api/admin/orgs/visibility", json={"mode": "all"}).status_code == 403, "#799: no creating, deleting, renaming, visibility switch (403)")
check(A.get(B + "/api/state").json()["instance_mode"] == "organisation" and A.get(B + "/api/state").json()["people_visibility"] == "org", "#799: state")
# an instance that kept two organisations from 2.22 ("multi"): set up in the database (the app cannot create one any more)
ORG2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other','','2026-10-01T00:00:00Z') RETURNING id")[0][0]
dbx("DELETE FROM org_members WHERE user_id=?", (CAROL,))
dbx("INSERT INTO org_members(org_id,user_id) VALUES(?,?)", (ORG2, CAROL))
check(A.get(B + "/api/admin/orgs").json()["mode"] == "multi" and A.get(B + "/api/admin/orgs").json()["editable"], "#799: two organisations kept: multi (editable)")
A.put(B + "/api/admin/orgs/visibility", json={"mode": "org"})

# ================================================================== #795: task_added for agents
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "claude", "display_name": "Claude"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
DEV = A.post(B + "/api/lists", json={"name": "Dev", "kind": "project"}).json()["id"]
PRIV = A.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
SECRET = A.post(B + "/api/lists", json={"name": "Secret"}).json()["id"]
A.put(B + f"/api/lists/{DEV}/members", json={"user_id": AG, "role": "edit"})
A.put(B + f"/api/lists/{PRIV}/members", json={"user_id": AG, "role": "view"})
n0 = len(events(AG))
t1 = A.post(B + "/api/tasks", json={"title": "Fix the login", "list_id": DEV}).json()
ev = [e for e in events(AG)[n0:] if e["event"] == "task_added"]
check(len(ev) == 1 and ev[0]["data"]["task"]["id"] == t1["id"] and ev[0]["data"]["how"] == "created" and "moved_from" not in ev[0]["data"]
      and ev[0]["data"]["list"]["id"] == DEV and "comments" in ev[0]["data"]["task"], "#795: created in a shared list: task_added " + json.dumps(ev)[:300])
sub = A.post(B + "/api/tasks", json={"title": "Sub", "parent_id": t1["id"]}).json()
check(not any(e["event"] == "task_added" and e["data"]["task"]["id"] == sub["id"] for e in events(AG)), "#795: not for a subtask")
t2 = A.post(B + "/api/tasks", json={"title": "Moved from mine", "list_id": PRIV}).json()
t3 = A.post(B + "/api/tasks", json={"title": "Moved from secret", "list_id": SECRET}).json()
n1 = len(events(AG))
A.patch(B + f"/api/tasks/{t2['id']}", json={"list_id": DEV})
A.post(B + "/api/tasks/reorder", json={"items": [{"id": t3["id"], "list_id": DEV}]})
ev = {e["data"]["task"]["id"]: e["data"] for e in events(AG)[n1:] if e["event"] == "task_added"}
check(t2["id"] in ev and ev[t2["id"]]["how"] == "moved" and ev[t2["id"]].get("moved_from") == {"id": PRIV, "name": "Mine"},
      "#795: moved into the list: moved_from (the agent sees the source) " + json.dumps(ev.get(t2["id"]))[:200])
check(t3["id"] in ev and ev[t3["id"]]["how"] == "moved" and "moved_from" not in ev[t3["id"]], "#795: moved from a list the agent does not see: no moved_from")
n2 = len(events(AG))
A.patch(B + f"/api/tasks/{t1['id']}", json={"title": "Fix the login page"})
A.patch(B + f"/api/tasks/{t2['id']}", json={"list_id": SECRET})
check(not [e for e in events(AG)[n2:] if e["event"] == "task_added"], "#795: no event for a change or for moving out")
n3 = len(events(AG))
requests.post(V + "/tasks", headers=AGH, json={"title": "By the agent", "list_id": DEV})
check(not [e for e in events(AG)[n3:] if e["event"] == "task_added"], "#795: not for the agent's own task")

# ================================================================== clients (#463)
check(A.get(B + "/api/clients").status_code == 409, "clients: module off -> 409")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"features": FEAT + ",clients,workload,forms"})
r = A.post(B + "/api/clients", json={"name": "  Café   Aurora ", "icon": "☕", "contact": "Maria", "email": "maria@aurora.example", "rate": "80,5",
                                     "budget_h": 10, "budget_amount": 1000, "address": "Main St 1\n12345 Town"})
check(r.status_code == 201 and r.json()["name"] == "Café Aurora" and r.json()["rate"] == 80.5 and r.json()["org_id"] == ORG1
      and r.json()["address"] == "Main St 1\n12345 Town" and r.json()["can_delete"], "a client in my organisation " + r.text[:300])
CL = r.json()["id"]
for bad, what in (({"name": ""}, "no name"), ({"name": "x", "email": "nope"}, "e-mail"), ({"name": "x", "rate": "abc"}, "rate"),
                  ({"name": "x", "color": "red"}, "colour"), ({"name": "x", "org_id": ORG2}, "a foreign organisation"),
                  ({"name": "x", "budget_h": -1}, "negative budget")):
    check(Bo.post(B + "/api/clients", json=bad).status_code == 400, "client validation: " + what)
check([c["id"] for c in Bo.get(B + "/api/clients").json()["clients"]] == [CL], "Bob (same organisation) sees the client")
check(Ca.get(B + "/api/clients").json()["clients"] == [] and Ca.get(B + f"/api/clients/{CL}").status_code == 404, "Carol (other organisation): not")
check(Ca.patch(B + f"/api/clients/{CL}", json={"name": "x"}).status_code == 404 and Ca.delete(B + f"/api/clients/{CL}").status_code == 404, "… nor change it")
CL2 = Ca.post(B + "/api/clients", json={"name": "Other client"}).json()["id"]
check(CL2 not in [c["id"] for c in Bo.get(B + "/api/clients").json()["clients"]], "Carol's client stays in her organisation")
check(CL2 in [c["id"] for c in A.get(B + "/api/clients").json()["clients"]], "admins see every client")
# lists of the client
P1 = A.post(B + "/api/lists", json={"name": "Aurora website", "kind": "project"}).json()["id"]
P2 = A.post(B + "/api/lists", json={"name": "Aurora menu", "kind": "project"}).json()["id"]
A.patch(B + f"/api/lists/{P2}", json={"rate": 100})
A.put(B + f"/api/lists/{P1}/members", json={"user_id": BOB, "role": "edit"})
check(A.patch(B + f"/api/lists/{P1}", json={"client_id": CL}).ok and A.patch(B + f"/api/lists/{P2}", json={"client_id": CL}).ok, "lists -> the client")
check(Bo.patch(B + f"/api/lists/{P1}", json={"client_id": None}).status_code == 403, "an edit member cannot change the client of a list")
check(A.patch(B + f"/api/lists/{P1}", json={"client_id": 99999}).status_code == 404, "an unknown client: 404")
check(next(l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == P1)["client_id"] == CL, "the list knows its client (state)")
check(next(c for c in A.get(B + "/api/state").json()["clients"] if c["id"] == CL)["lists"] == [P1, P2], "state: the clients with their lists")
check(Bo.get(B + f"/api/clients/{CL}").json()["lists"] == [P1], "Bob sees only the client's lists he sees")
# time + estimate
ta = A.post(B + "/api/tasks", json={"title": "Design", "list_id": P1, "duration": 120}).json()["id"]
tb = A.post(B + "/api/tasks", json={"title": "Menu", "list_id": P2, "duration": 60}).json()["id"]
now = datetime.now(timezone.utc).replace(microsecond=0)
for tid, mins in ((ta, 90), (tb, 30)):
    st = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    r = A.post(B + "/api/time/entries", json={"task_id": tid, "start": st, "minutes": mins})
    check(r.ok, "a time entry " + r.text[:200])
j = A.get(B + f"/api/clients/{CL}").json()
st = j["stats"]
check(st["seconds"] == 120 * 60 and st["month_seconds"] == 120 * 60 and st["estimate_min"] == 180 and st["open"] == 2,
      "the client's hours (all + this month) and the estimate " + json.dumps(st))
check(abs(st["amount"] - (1.5 * 80.5 + 0.5 * 100)) < 0.01, "the amount: the list's rate, else the client's " + str(st["amount"]))
check(j["budget"]["pct_h"] == 20 and j["budget"]["level"] == "ok", "budget 2 of 10 h: ok " + json.dumps(j["budget"]))
pl = {x["id"]: x for x in j["per_list"]}
check(pl[P1]["estimate_min"] == 120 and pl[P1]["seconds"] == 5400 and pl[P2]["estimate_min"] == 60, "estimate vs. actual per list")
A.patch(B + f"/api/clients/{CL}", json={"budget_h": 2.4, "budget_amount": None})
check(A.get(B + f"/api/clients/{CL}").json()["budget"]["level"] == "warn", "83 % of the budget: warn")
A.patch(B + f"/api/clients/{CL}", json={"budget_h": 1})
check(A.get(B + f"/api/clients/{CL}").json()["budget"]["level"] == "over", "over the budget: over")
check(Bo.get(B + f"/api/clients/{CL}").json()["stats"]["seconds"] == 5400, "Bob: only the time of the lists he sees")
rep = A.get(B + "/api/time/report", params={"scope": "all", "lists": f"{P1},{P2}", "from": D(-31), "to": D(0)}).json()
check(rep["total"]["seconds"] == 7200 and {x["id"] for x in rep["lists"]} == {P1, P2}, "the timesheet: the time report of the client's lists")
csv_ = A.get(B + "/api/time/export.csv", params={"scope": "all", "lists": f"{P1},{P2}", "from": D(-31), "to": D(0)})
check(csv_.ok and "Aurora website" in csv_.text and "120.75" in csv_.text, "… and its CSV (the client's rate)")
# delete: creator or admin; the lists stay
check(Bo.delete(B + f"/api/clients/{CL}").status_code == 403, "Bob cannot delete Alice's client")
check(A.patch(B + f"/api/clients/{CL}", json={"archived": True}).json()["archived"] and CL not in [c["id"] for c in A.get(B + "/api/clients").json()["clients"]]
      and CL in [c["id"] for c in A.get(B + "/api/clients", params={"archived": 1}).json()["clients"]], "archived: only with ?archived=1")
A.patch(B + f"/api/clients/{CL}", json={"archived": False})
CL3 = Bo.post(B + "/api/clients", json={"name": "Temp"}).json()["id"]
check(Bo.delete(B + f"/api/clients/{CL3}").ok, "the creator deletes it")
kid = A.post(B + "/api/users", json={"username": "tim", "display_name": "Tim", "password": "password123", "kid": True, "parents": [1]}).json()["id"]
check(sess("tim").get(B + "/api/clients").status_code in (403, 409), "a kid: no clients")
# API v1
pt = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "structure", "tasks:write"]}).json()["token"]
PT = {"Authorization": "Bearer " + pt}
r = requests.get(V + "/clients", headers=PT)
check(r.ok and r.json()["clients"][0]["id"] == CL, "GET /api/v1/clients")
r = requests.post(V + "/clients", headers=PT, json={"name": "API client", "budget_h": 5})
check(r.status_code == 201 and r.json()["name"] == "API client", "POST /api/v1/clients " + r.text[:200])
check(requests.post(V + "/clients", headers=PT, json={"name": "x", "evil": 1}).status_code == 400, "v1: unknown field 400")
check(requests.patch(V + f"/clients/{r.json()['id']}", headers=PT, json={"note": "hi"}).json()["note"] == "hi", "PATCH /api/v1/clients/{id}")
check(requests.delete(V + f"/clients/{r.json()['id']}", headers=PT).ok, "DELETE /api/v1/clients/{id}")
rt = A.post(B + "/api/me/tokens", json={"name": "t2", "scopes": ["read"]}).json()["token"]
check(requests.post(V + "/clients", headers={"Authorization": "Bearer " + rt}, json={"name": "x"}).status_code == 403, "v1: creating needs the scope structure")
check(requests.patch(V + f"/lists/{P2}", headers=PT, json={"client_id": None}).json()["client_id"] is None, "v1 PATCH /lists: client_id")

# ================================================================== workload (#463)
A.patch(B + "/api/settings", json={"capacity_h": 10})
check(Bo.put(B + "/api/workload/capacity/1", json={"hours": 5}).status_code == 403, "capacity of someone else: admins only")
check(A.put(B + f"/api/workload/capacity/{BOB}", json={"hours": 20}).json()["capacity_h"] == 20, "an admin sets Bob's capacity")
check(A.put(B + "/api/workload/capacity/1", json={"hours": 999}).status_code == 400, "capacity: at most 168 h")
W1 = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
A.put(B + f"/api/lists/{W1}/members", json={"user_id": BOB, "role": "edit"})
mon = T0 - timedelta(days=T0.weekday())
A.post(B + "/api/tasks", json={"title": "Overdue", "list_id": W1, "assignee_id": BOB, "due": (mon - timedelta(days=3)).isoformat(), "duration": 240})
A.post(B + "/api/tasks", json={"title": "Next week", "list_id": W1, "assignee_id": BOB, "due": (mon + timedelta(days=8)).isoformat(), "duration": 600})
A.post(B + "/api/tasks", json={"title": "Planned", "list_id": W1, "assignee_id": BOB, "due": (mon + timedelta(days=20)).isoformat(),
                               "plan_start": mon.isoformat() + "T09:00"})
A.post(B + "/api/tasks", json={"title": "Undated", "list_id": W1, "assignee_id": BOB, "duration": 30})
A.post(B + "/api/tasks", json={"title": "Mine", "list_id": W1, "assignee_id": 1, "due": mon.isoformat(), "duration": 540})
Bp = A.post(B + "/api/lists", json={"name": "Hidden from Bob"}).json()["id"]
j = A.get(B + "/api/workload").json()
pp = {p["id"]: p for p in j["people"]}
check(set(pp) == {1, BOB} and j["org_id"] == ORG1 and len(j["weeks"]) == 4 and j["weeks"][0]["start"] == mon.isoformat(),
      "workload: the people of my organisation (no agent, kid, Carol), 4 weeks from Monday " + str(set(pp)))
w0 = pp[BOB]["weeks"][0]
check(w0["minutes"] == 240 and w0["tasks"] == 2 and w0["unestimated"] == 1 and pp[BOB]["capacity_h"] == 20 and w0["pct"] == 20,
      "this week: the overdue task (4 h) + the planned one (no estimate) " + json.dumps(w0))
check(pp[BOB]["weeks"][1]["minutes"] == 600 and pp[BOB]["weeks"][1]["pct"] == 50 and pp[BOB]["weeks"][1]["level"] == "ok", "next week 10 h of 20: ok " + json.dumps(pp[BOB]["weeks"][1]))
check(pp[BOB]["nodate"]["tasks"] == 1 and pp[1]["weeks"][0]["level"] == "warn" and pp[1]["capacity_h"] == 10, "no date; Alice 9 h of 10 h: warn " + json.dumps(pp[1]["weeks"][0]))
jb = Bo.get(B + "/api/workload").json()
check({p["id"] for p in jb["people"]} == {1, BOB}, "Bob sees the same people")
A.post(B + "/api/tasks", json={"title": "Alice private", "list_id": Bp, "assignee_id": 1, "due": mon.isoformat(), "duration": 60})
check(next(p for p in Bo.get(B + "/api/workload").json()["people"] if p["id"] == 1)["weeks"][0]["minutes"] == 540
      and next(p for p in A.get(B + "/api/workload").json()["people"] if p["id"] == 1)["weeks"][0]["minutes"] == 600,
      "only what the viewer sees is counted (Alice's private list not for Bob)")
check({p["id"] for p in Ca.get(B + "/api/workload").json()["people"]} == {CAROL}, "Carol: only her organisation")
check(Ca.get(B + "/api/workload", params={"org": ORG1}).status_code == 404, "… not another organisation")
check({p["id"] for p in A.get(B + "/api/workload", params={"org": ORG2}).json()["people"]} == {CAROL}, "admins pick the organisation")
check(A.get(B + "/api/workload", params={"weeks": 2, "start": D(7)}).json()["weeks"][0]["start"] == (mon + timedelta(days=7)).isoformat(), "start + weeks")
check(requests.get(V + "/workload", headers=PT).ok, "GET /api/v1/workload")
check(sess("tim").get(B + "/api/workload").status_code in (403, 409), "a kid: no workload")

# ================================================================== approvals (#463)
AP = A.post(B + "/api/tasks", json={"title": "Approve the logo", "list_id": W1}).json()["id"]
check(A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": CAROL}).status_code == 400, "the approver must be a person of the list")
check(A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": 1}).status_code == 400, "not oneself")
check(A.post(B + f"/api/tasks/{AP}/approval", json={"action": "approve"}).status_code == 400, "no request yet: no decision")
r = A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": BOB, "note": "Please by Friday"})
check(r.ok and r.json()["approval"] == "pending" and r.json()["approver_id"] == BOB and r.json()["assignee_id"] == BOB, "requested: assigned to Bob " + r.text[:200])
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='assign' AND task_id=?", (BOB, AP))[0][0] == 1, "Bob gets the assignment News")
check(A.post(B + f"/api/tasks/{AP}/approval", json={"action": "approve"}).status_code == 403, "only the approver decides")
r = requests.post(V + f"/tasks/{AP}/approval", headers=AGH, json={"action": "approve"})
check(r.status_code == 403, "an agent never decides")
r = Bo.post(B + f"/api/tasks/{AP}/approval", json={"action": "changes", "note": "Bigger, please"})
check(r.ok and r.json()["approval"] == "changes" and r.json()["assignee_id"] == 1 and r.json()["status"] == 0, "changes: back to Alice")
n = dbx("SELECT data FROM notifications WHERE user_id=1 AND kind='apdecide' AND task_id=?", (AP,))
check(n and json.loads(n[-1][0])["state"] == "changes" and json.loads(n[-1][0])["note"] == "Bigger, please", "Alice gets the decision (News)")
acts = [json.loads(x[0]) for x in dbx("SELECT data FROM activity WHERE task_id=? AND kind='apstate' ORDER BY id", (AP,))]
check([a["state"] for a in acts] == ["pending", "changes"] and acts[1]["note"] == "Bigger, please", "the history: requested, changes + the note")
check(any(it["kind"] == "apdecide" for it in A.get(B + "/api/news").json()["items"]), "… in Alice's News feed")
A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": BOB})
r = Bo.post(B + f"/api/tasks/{AP}/approval", json={"action": "approve"})
check(r.ok and r.json()["approval"] == "approved" and r.json()["status"] == 2, "approved: the task is done")
check(Bo.post(B + f"/api/tasks/{AP}/approval", json={"action": "reject"}).status_code == 400, "decided once")
AP2 = A.post(B + "/api/tasks", json={"title": "Budget", "list_id": W1}).json()["id"]
A.post(B + f"/api/tasks/{AP2}/approval", json={"action": "request", "approver_id": BOB})
r = Bo.post(B + f"/api/tasks/{AP2}/approval", json={"action": "reject", "note": "Too expensive"})
check(r.ok and r.json()["approval"] == "rejected" and r.json()["status"] == -1, "rejected: won't do")
AP3 = A.post(B + "/api/tasks", json={"title": "Withdrawn", "list_id": W1}).json()["id"]
A.post(B + f"/api/tasks/{AP3}/approval", json={"action": "request", "approver_id": BOB})
check(Bo.post(B + f"/api/tasks/{AP3}/approval", json={"action": "cancel"}).status_code == 403, "the approver cannot withdraw")
r = A.post(B + f"/api/tasks/{AP3}/approval", json={"action": "cancel"})
check(r.ok and "approval" not in r.json(), "withdrawn: no approval fields any more")
r = requests.post(V + f"/tasks/{AP3}/approval", headers=PT, json={"action": "request", "approver_id": BOB})
check(r.ok and r.json()["approval"] == "pending" and r.json()["approver_id"] == BOB, "POST /api/v1/tasks/{id}/approval (request) " + r.text[:200])
check(requests.get(V + f"/tasks/{AP}", headers=PT).json()["approval"] == "approved", "v1: the task shows its approval")
check(requests.get(V + f"/tasks/{AP2 + 100}", headers=PT).status_code == 404, "v1: 404 stays 404")

# ================================================================== forms (#463 / #341)
FL = A.post(B + "/api/lists", json={"name": "Requests"}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": AG, "role": "edit"})
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
SEC = A.post(B + "/api/sections", json={"list_id": FL, "name": "New"}).json()["id"]
check(Bo.post(B + f"/api/lists/{FL}/forms", json={"title": "x"}).status_code == 403, "forms: only the owner / list admins")
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "IT request", "intro": "Tell us what is broken.", "section_id": SEC})
check(r.status_code == 201 and r.json()["access"] == "org" and r.json()["url"].startswith("https://kalmido.example/f/") and r.json()["live"],
      "a form (org by default) with its link " + r.text[:200])
F1 = r.json()
tokf = F1["url"].rsplit("/", 1)[1]
check(len(tokf) >= 30 and not dbx("SELECT 1 FROM forms WHERE token=?", (tokf,)), "the token is stored sealed")
anon = requests.Session()
p = anon.get(B + "/f/" + tokf)
check(p.status_code == 401 and "log in" in p.text.lower(), "an org form: log in first")
p = Bo.get(B + "/f/" + tokf)
check(p.ok and "IT request" in p.text and "Tell us what is broken." in p.text and 'name="subject"' in p.text and "<script" not in p.text
      and "default-src 'none'" in p.headers.get("Content-Security-Policy", ""), "Bob (same organisation) sees the form, no scripts, a strict CSP")
check(Ca.get(B + "/f/" + tokf).status_code == 404, "Carol (another organisation): not available")
n4 = len(events(AG))
p = Bo.post(B + "/f/" + tokf, data={"subject": "Printer broken", "text": "It beeps."}, headers={"Sec-Fetch-Site": "same-origin"})
check(p.ok and "Thank you" in p.text, "sent")
t = dbx("SELECT id, title, content, section_id, created_by FROM tasks WHERE title='Printer broken'")
check(t and t[0][3] == SEC and t[0][4] == BOB and "It beeps." in t[0][2] and "IT request" in t[0][2] and "Bob" in t[0][2], "… a task in the section, by Bob " + str(t))
ev = [e for e in events(AG)[n4:] if e["event"] == "task_added"]
check(ev and ev[0]["data"]["source"] == "form" and ev[0]["data"]["task"]["title"] == "Printer broken", "the list's agent: task_added, source form")
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=1 AND kind='newtask'")[0][0] >= 0, "newtask events ran")
check(Bo.post(B + "/f/" + tokf, data={"subject": "x"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403, "cross-site: refused")
check(Bo.post(B + "/f/" + tokf, data={"subject": "  "}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 400, "no subject: the form again with an error")
cnt = dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (FL,))[0][0]
p = Bo.post(B + "/f/" + tokf, data={"subject": "Spam", "website": "http://spam"}, headers={"Sec-Fetch-Site": "same-origin"})
check(p.ok and dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (FL,))[0][0] == cnt, "the honeypot: looks fine, nothing created")
# public
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Bug report", "access": "public", "ask_email": True})
F2 = r.json()
tok2 = F2["url"].rsplit("/", 1)[1]
p = anon.get(B + "/f/" + tok2)
check(p.ok and 'name="email"' in p.text and 'name="name"' in p.text and 'name="website"' in p.text, "a public form: name, e-mail, the hidden honeypot")
p = anon.post(B + "/f/" + tok2, data={"subject": "Crash", "text": "On start", "name": "Eve", "email": "eve@example.org"})
t = dbx("SELECT content, created_by FROM tasks WHERE title='Crash'")
check(p.ok and t and t[0][1] is None and "Eve <eve@example.org>" in t[0][0], "anonymous: a task without a creator, the sender in the notes " + str(t))
act = dbx("SELECT data FROM activity WHERE task_id=(SELECT id FROM tasks WHERE title='Crash') AND kind='created'")
check(act and json.loads(act[0][0]).get("via") == "public_link", "history: via the link")
check(anon.post(B + "/f/" + tok2, data={"subject": "x", "email": "nope"}).status_code == 400, "a bad e-mail: 400")
codes = [anon.post(B + "/f/" + tok2, data={"subject": f"Flood {i}"}).status_code for i in range(8)]
check(429 in codes, "sending is rate limited per address " + str(codes))
A.patch(B + "/api/admin/settings", json={"public_links": False})
check(anon.get(B + "/f/" + tok2).status_code == 404 and not A.get(B + f"/api/lists/{FL}/forms").json()["forms"][1]["live"], "public links off: the public form is gone")
check(A.post(B + f"/api/lists/{FL}/forms", json={"title": "x", "access": "public"}).status_code == 409, "… and none can be created")
A.patch(B + "/api/admin/settings", json={"public_links": True})
r = A.patch(B + f"/api/forms/{F2['id']}", json={"regenerate": True})
check(r.ok and r.json()["url"] != F2["url"] and anon.get(B + "/f/" + tok2).status_code == 404, "regenerate: the old link stops")
check(A.patch(B + f"/api/forms/{F2['id']}", json={"enabled": False}).ok and anon.get(B + r.json()["url"].split("kalmido.example")[1]).status_code == 404, "disabled: gone")
check(A.patch(B + f"/api/forms/{F2['id']}", json={"access": "nope"}).status_code == 400, "form validation")
check(Bo.delete(B + f"/api/forms/{F2['id']}").status_code == 403 and A.delete(B + f"/api/forms/{F2['id']}").ok, "delete: owner / list admins")
check(anon.get(B + "/f/" + "x" * 32).status_code == 404, "an unknown token: 404")
r = requests.post(V + f"/lists/{FL}/forms", headers=PT, json={"title": "API form"})
check(r.status_code == 201 and requests.get(V + f"/lists/{FL}/forms", headers=PT).json()["forms"][-1]["title"] == "API form", "API v1: forms")
check(requests.patch(V + f"/forms/{r.json()['id']}", headers=PT, json={"intro": "Hi"}).json()["intro"] == "Hi"
      and requests.delete(V + f"/forms/{r.json()['id']}", headers=PT).ok, "API v1: PATCH / DELETE forms")

# ================================================================== #444: sign-in link + QR
r = A.post(B + f"/api/users/{kid}/signin-link")
check(r.ok and "#signin/" in r.json()["link"] and r.json()["qr"].startswith("data:image/svg+xml") and r.json()["kind"] == "login" and not r.json()["sent"],
      "a sign-in link + QR for a kid " + r.text[:200])
ktok = r.json()["link"].split("#signin/")[1]
K = requests.Session(); K.headers.update(H)
check(K.post(B + "/api/auth/invite/check", json={"token": ktok}).status_code == 404, "a sign-in link is not an invitation")
r = K.post(B + "/api/auth/link", json={"token": ktok})
check(r.ok and r.json()["ok"] and K.get(B + "/api/me").json()["username"] == "tim", "it signs the kid in")
check(requests.post(B + "/api/auth/link", headers=H, json={"token": ktok}).status_code == 404, "once")
check(Bo.post(B + f"/api/users/{kid}/signin-link").status_code == 403, "Bob (not a parent): no")
A.post(B + "/api/users", json={"username": "bobkid", "display_name": "Bobkid", "kid": True, "parents": [BOB]})
bk = next(u["id"] for u in A.get(B + "/api/users").json()["users"] if u["username"] == "bobkid")
r = Bo.post(B + f"/api/users/{bk}/signin-link")
check(r.ok and "#signin/" in r.json()["link"], "a parent creates the link for their kid")
check(A.post(B + "/api/users/1/signin-link").status_code == 409, "never for an admin")
check(A.post(B + f"/api/users/{AG}/signin-link").status_code == 404, "never for an agent")
gran = A.post(B + "/api/users", json={"username": "grandma", "display_name": "Grandma"}).json()["id"]
r = A.post(B + f"/api/users/{gran}/signin-link")
check(r.ok, "admins: also for a person without an e-mail address")
r2 = A.post(B + f"/api/users/{gran}/signin-link")
check(requests.post(B + "/api/auth/link", headers=H, json={"token": r.json()["link"].split("#signin/")[1]}).status_code == 404, "a new link: the old one stops")

# ================================================================== #711: self-registration
info = requests.get(B + "/api/auth/info").json()
check(info.get("signup") is None, "registration off by default")
check(requests.post(B + "/api/auth/signup", headers=H, json={"name": "X", "email": "x@example.org"}).status_code == 404, "off: 404")
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "nope"}).status_code == 400, "a bad mode: 400")
check(A.patch(B + f"/api/admin/orgs/{ORG2}", json={"domains": "agency.example, @Agency.example"}).json()["domains"] == "agency.example",
      "an organisation's e-mail domains (cleaned)")
A.patch(B + "/api/admin/settings", json={"signup_mode": "domain", "signup_domains": "@acme.example, foo"})
ab = A.get(B + "/api/state").json()["about"]
check(ab["signup_mode"] == "domain" and ab["signup_domains"] == "acme.example" and ab["signup_effective"] == "domain", "domain mode + the cleaned domains " + str(ab.get("signup_domains")))
info = requests.get(B + "/api/auth/info").json()
check(info["signup"] == {"mode": "domain", "password": False, "min_password": 8}, "the login page offers it " + str(info.get("signup")))
m0 = len(mails())
R = requests.Session(); R.headers.update(H)
r1 = R.post(B + "/api/auth/signup", json={"name": "Max Muster", "email": "max.muster@acme.example", "lang": "de"})
r2 = R.post(B + "/api/auth/signup", json={"name": "Foreign", "email": "someone@gmail.example"})
r3 = R.post(B + "/api/auth/signup", json={"name": "Again", "email": "MAX.muster@acme.example"})
check(r1.ok and r1.json() == r2.json() == r3.json() == {"ok": True, "mail": True, "pending": False}, "the same answer for a new, a foreign and a taken address")
u = dbx("SELECT id, username, disabled, signup, email FROM users WHERE email LIKE 'max.muster@%'")
check(len(u) == 1 and u[0][1] == "max.muster" and u[0][2] == 1 and u[0][3] == "confirm", "one account, user name from the address, waits for the confirmation " + str(u))
check(not dbx("SELECT 1 FROM users WHERE email='someone@gmail.example'"), "a foreign domain: nothing created")
ml = until(lambda: [x for x in mails()[m0:] if "max.muster@acme.example" in x["to"]])
msg = _em.message_from_string(ml[0]["raw"]) if ml else None
parts = {p.get_content_type(): p for p in msg.walk()} if msg else {}
htm = parts["text/html"].get_payload(decode=True).decode() if "text/html" in parts else ""
stok = (re.search(r"#invite/([A-Za-z0-9_-]{20,100})", htm) or [None, None])[1]
check(len([x for x in mails()[m0:]]) == 1 and stok and "Registrierung" in str(_em.header.make_header(_em.header.decode_header(msg["Subject"]))),
      "one mail (German), the confirmation link")
check(requests.post(B + "/api/auth/login", headers=H, json={"username": "max.muster", "password": "x"}).status_code == 401, "not usable before the confirmation")
r = R.post(B + "/api/auth/invite/check", json={"token": stok})
check(r.ok and r.json()["kind"] == "signup" and r.json()["username"] == "max.muster", "the page: a registration")
r = R.post(B + "/api/auth/invite/accept", json={"token": stok, "password": "max-secret-1"})
check(r.ok and r.json()["ok"] and R.get(B + "/api/me").json()["username"] == "max.muster", "confirmed + password: signed in")
st = R.get(B + "/api/state").json()
check([l for l in st["lists"] if not l["is_inbox"]] == [] and not st["me"]["is_admin"], "no list access, no admin")
dom = dbx("SELECT org_id FROM org_members WHERE user_id=?", (u[0][0],))
check(dom == [(ORG1,)], "the instance's first organisation (no domain match) " + str(dom))
# approval mode (with mail): confirm -> waits; the admin approves
A.patch(B + "/api/admin/settings", json={"signup_mode": "approval"})
m1 = len(mails())
r = R.post(B + "/api/auth/signup", json={"name": "Nina", "email": "nina@agency.example"})
check(r.json() == {"ok": True, "mail": True, "pending": True}, "approval mode: pending")
ml = until(lambda: [x for x in mails()[m1:] if "nina@agency.example" in x["to"]])
htm = [p for p in _em.message_from_string(ml[0]["raw"]).walk() if p.get_content_type() == "text/html"][0].get_payload(decode=True).decode()
ntok = re.search(r"#invite/([A-Za-z0-9_-]{20,100})", htm)[1]
r = requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": ntok, "password": "nina-secret-1"})
check(r.ok and r.json() == {"ok": False, "pending": True}, "confirmed: waits for an admin")
nid = dbx("SELECT id FROM users WHERE username='nina'")[0][0]
check(dbx("SELECT org_id FROM org_members WHERE user_id=?", (nid,)) == [(ORG2,)], "the organisation from its e-mail domains")
r = requests.post(B + "/api/auth/login", headers=H, json={"username": "nina", "password": "nina-secret-1"})
check(r.status_code == 403 and "approve" in r.json()["error"], "login: 'waits for approval' (only with the right password)")
check(requests.post(B + "/api/auth/login", headers=H, json={"username": "nina", "password": "wrong-pass-1"}).status_code == 401, "a wrong password: the usual 401")
check(any(it["kind"] == "signup" and it["data"]["user_id"] == nid for it in A.get(B + "/api/news").json()["items"]), "the admins get a News item")
check(next(x for x in A.get(B + "/api/users").json()["users"] if x["id"] == nid)["disabled"], "listed as disabled until approved")
check(Bo.post(B + f"/api/users/{nid}/approve").status_code == 403, "only admins approve")
check(A.post(B + f"/api/users/{nid}/approve").ok and sess("nina", "nina-secret-1").get(B + "/api/me").ok, "approved: Nina logs in")
check(A.post(B + f"/api/users/{nid}/approve").status_code == 409, "approve twice: 409")
check(not any(it["kind"] == "signup" for it in A.get(B + "/api/news").json()["items"]), "the News item disappears once decided")
# open mode, the rate limit, expired registrations are removed
A.patch(B + "/api/admin/settings", json={"signup_mode": "open"})
r = R.post(B + "/api/auth/signup", json={"name": "Otto", "email": "otto@anywhere.example"})
check(r.json() == {"ok": True, "mail": True, "pending": False} and dbx("SELECT signup FROM users WHERE username='otto'") == [("confirm",)], "open mode")
check(R.post(B + "/api/auth/signup", json={"name": "", "email": "y@anywhere.example"}).status_code == 400
      and R.post(B + "/api/auth/signup", json={"name": "Y", "email": "nope"}).status_code == 400, "validation: name, e-mail")
dbx("UPDATE user_invites SET expires_at='2020-01-01T00:00:00Z' WHERE user_id=(SELECT id FROM users WHERE username='otto')")
codes = [R.post(B + "/api/auth/signup", json={"name": "Z", "email": f"z{i}@anywhere.example"}).status_code for i in range(4)]
check(not dbx("SELECT 1 FROM users WHERE username='otto'"), "an expired registration is removed")
check(429 in codes, "registrations are rate limited per address " + str(codes))
A.patch(B + "/api/admin/settings", json={"signup_mode": "off"})
check(requests.get(B + "/api/auth/info").json().get("signup") is None, "off again")

# ================================================================== #823: no reaction on one's own message
cm = A.post(B + f"/api/tasks/{AP2}/comments", json={"body": "Mine"}).json()
cid = cm.get("id") or cm.get("comment", {}).get("id")
check(A.post(B + f"/api/comments/{cid}/reactions", json={"emoji": "up"}).status_code == 400, "#823: not on my own comment")
check(Bo.post(B + f"/api/comments/{cid}/reactions", json={"emoji": "up"}).ok, "#823: someone else may")
ct = A.post(B + "/api/me/tokens", json={"name": "t823", "scopes": ["read", "comments"]}).json()["token"]
check(requests.post(V + f"/comments/{cid}/reactions", headers={"Authorization": "Bearer " + ct}, json={"emoji": "heart"}).status_code == 400, "#823: API v1 too")

# ================================================================== OpenAPI
spec = requests.get(V + "/openapi.json", headers=PT).json()
for pth in ("/clients", "/clients/{id}", "/workload", "/tasks/{id}/approval", "/lists/{id}/forms", "/forms/{id}"):
    check(pth in spec["paths"], "OpenAPI: " + pth)
check("approval" in spec["components"]["schemas"]["Task"]["properties"] and "client_id" in spec["components"]["schemas"]["List"]["properties"],
      "OpenAPI: Task.approval, List.client_id")

# ================================================================== #799: KALMIDO_INSTANCE_MODE + KALMIDO_ORG_NAME (restart, same data)
def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=env["EXTRA"] + " " + extra)
    assert subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


restart("-e KALMIDO_INSTANCE_MODE=organisation -e KALMIDO_ORG_NAME=Acme")
A = sess("alice")
oj = A.get(B + "/api/admin/orgs").json()
check(oj["mode"] == "organisation" and [o["name"] for o in oj["orgs"]] == ["Acme"] and CAROL in oj["orgs"][0]["members"] and oj["name_env"],
      "#799: organisation by configuration: the first organisation, renamed, everyone in it " + json.dumps(oj)[:200])
check(requests.get(B + "/api/auth/info").json()["org"] == "Acme", "#799: the login page shows the name")
check({p["id"] for p in A.get(B + "/api/workload").json()["people"]} >= {1, BOB, CAROL}, "#799: workload: the whole organisation")
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "open"}).status_code == 409 and A.patch(B + "/api/admin/settings", json={"signup_mode": "approval"}).ok,
      "#799: an organisation registers only by domain or with approval")
restart("-e KALMIDO_INSTANCE_MODE=shared")
A = sess("alice")
Bo = sess("bob")
st = Bo.get(B + "/api/state").json()
check(st["instance_mode"] == "shared" and st["people_visibility"] == "contacts" and st["me"]["orgs"] == [], "#799: shared: no organisations, own contacts")
check(A.get(B + "/api/admin/orgs").json()["orgs"] == [] and requests.get(B + "/api/auth/info").json()["org"] == "", "#799: shared: nothing to show")
check(CAROL not in {u["id"] for u in Bo.get(B + "/api/users").json()["users"]}, "#799: Bob does not see Carol (no list in common)")
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "open"}).ok, "#799: shared: open registration possible")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
