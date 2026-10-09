#!/usr/bin/env python3
"""2.34.0 API tests, part A: the morning briefing (#264) and the status report of a project (#265).
 - briefing (GET /api/briefing): due today / overdue (mine: assigned to me or without assignee in my own lists), blocked
   (waiting on someone outside, an open task in a project), changed by OTHERS since 18:00 yesterday on tasks that concern
   me (assigned, comment, status, date; my own changes do not count), lying idle (#266, mine only); read state per day on
   the server (POST /api/briefing/read, read: false undoes it), bad bodies 400; agents get 404 on the person's routes
 - the agent API: GET /api/v1/briefing?user_id= only for a person who may chat with the agent (shares a list), only from the
   lists shared with the agent (a private list stays out); another agent / a stranger / a missing user_id: 404 / 400
   (tenant-matrix: aggregate); a personal token reads only its own
 - the push: setting brief_time (validated), once a day, numbers only (title "Your briefing")
 - status report (GET /api/lists/<id>/status-report, /api/v1/...): done / in progress / blocked / overdue / upcoming /
   milestones / tracked time in the period, Markdown in the person's or the asked language without comments, notes or
   names; period from / to / days (bad values 400); a stranger 404, an agent only in shared lists, a participant only
   their tasks (tenant-matrix: list)
 - nothing new in the schema (only user settings keys): the rollback image 2.33 keeps running
usage: p2340_a_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/me").json().get("id") or dbx("SELECT id FROM users WHERE username='alice'")[0][0]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
T0 = date.today()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731


def task(s, title, lid, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def share(lid, uid, role="edit"):
    r = A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if r.status_code == 409:
        r = A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role, "bridge_ok": True})
    check(r.ok, f"setup: {uid} in list {lid} " + r.text[:120])


CL, CLH = agent("claude")
OT, OTH = agent("otto")
P = A.post(B + "/api/lists", json={"name": "Website", "kind": "project"}).json()["id"]   # alice, bob, dave (participant), claude
PRIV = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]                  # alice only
share(P, BOB)
share(P, DAVE, "participant")
share(P, CL)
CP = Ca.post(B + "/api/lists", json={"name": "Carol project", "kind": "project"}).json()["id"]

# ================================================================== #264 briefing
t_today = task(A, "Call the printer", P, due=D(0))
t_over = task(A, "Send the offer", P, due=D(-2))
t_priv = task(A, "Dentist", PRIV, due=D(0))
t_bobs = task(A, "Layout draft", P, due=D(0), assignee_id=BOB)       # due today, but Bob's
t_wait = task(A, "Texts from the client", P)
check(A.put(B + f"/api/tasks/{t_wait}/waiting", json={"note": "Client Miller", "until": D(5)}).ok, "setup: waiting")
t_blk = task(A, "Go live", P)
t_pre = task(A, "Hosting contract", P)
r = A.post(B + "/api/deps", json={"task_id": t_blk, "blocker_id": t_pre})
check(r.ok, "setup: a dependency " + r.text[:120])
t_cmt = task(A, "Logo variants", P)
t_done = task(A, "Domain", P)
t_due = task(A, "Photos", P, due=D(9))
# others change things (Bob) -- and Alice changes one herself (does not count)
check(Bo.post(B + f"/api/tasks/{t_cmt}/comments", json={"body": "First drafts are in"}).ok, "setup: bob comments")
check(Bo.post(B + f"/api/tasks/{t_done}/complete").ok, "setup: bob completes")
check(Bo.patch(B + f"/api/tasks/{t_due}", json={"due": D(10)}).ok, "setup: bob moves a date")
t_new = task(Bo, "Review the sitemap", P, assignee_id=ALICE)
t_self = task(A, "My own change", P)
A.patch(B + f"/api/tasks/{t_self}", json={"due": D(20)})
A.post(B + f"/api/tasks/{t_self}/comments", json={"body": "note to self"})

r = A.get(B + "/api/briefing")
check(r.ok, "briefing: 200 " + r.text[:200])
b = r.json()
n = b.get("counts", {})
today_ids = [x["id"] for x in b.get("today", [])]
check(t_today in today_ids and t_over in today_ids and t_priv in today_ids, "briefing: today + overdue + the private list (the person sees everything) " + str(today_ids))
check(t_bobs not in today_ids, "briefing: a task assigned to someone else is not mine")
check(n.get("today") == 2 and n.get("overdue") == 1, "briefing: counts today 2, overdue 1 " + str(n))
check(any(x["id"] == t_over and x["overdue"] for x in b["today"]), "briefing: the overdue one is marked")
bl = {x["id"]: x for x in b.get("blocked", [])}
check(t_wait in bl and bl[t_wait]["reason"] == "waiting" and bl[t_wait]["wait_note"] == "Client Miller", "briefing: waiting on someone " + str(bl.get(t_wait)))
check(t_blk in bl and bl[t_blk]["reason"] == "blocked" and bl[t_blk]["open_blockers"] == 1, "briefing: blocked by an open task " + str(list(bl)))
ch = {x["id"]: x for x in b.get("changed", [])}
check(ch.get(t_cmt, {}).get("kinds") == ["comment"] and ch[t_cmt]["by"][0]["name"] == "Bob", "briefing: bob's comment " + str(ch.get(t_cmt)))
check("status" in ch.get(t_done, {}).get("kinds", []), "briefing: bob completed a task alice created " + str(ch.get(t_done)))
check("due" in ch.get(t_due, {}).get("kinds", []), "briefing: bob moved a date " + str(ch.get(t_due)))
check("assigned" in ch.get(t_new, {}).get("kinds", []), "briefing: a new task assigned to alice " + str(ch.get(t_new)))
check(t_self not in ch, "briefing: alice's own changes do not count")
check(n.get("changed") == len(ch) == 4, "briefing: changed counts tasks " + str(n))
check("First drafts" not in r.text, "briefing: no comment text in the briefing")
check(b.get("read") is False and b.get("since"), "briefing: not read yet, since set " + str(b.get("since")))
# Bob's view: his own task due today, nothing of alice's private list
bb = Bo.get(B + "/api/briefing").json()
check([x["id"] for x in bb["today"]] == [t_bobs], "briefing: bob sees his task only " + str(bb["today"]))
check(t_priv not in [x["id"] for k in ("today", "blocked", "changed", "stale") for x in bb[k]] and "Dentist" not in json.dumps(bb), "briefing: never another person's private list")
# read state
since0 = b["since"]
r = A.post(B + "/api/briefing/read", json={"read": True})
check(r.ok and r.json()["read"] is True and r.json()["since"] == since0, "read: marked, the start of 'changed' stays for today " + r.text[:160])
st = json.loads(dbx("SELECT value FROM user_settings WHERE user_id=? AND key='brief_read'", (ALICE,))[0][0])
check(st.get("day") == T0.isoformat() and st.get("at"), "read: stored on the server per day " + str(st))
check(A.get(B + "/api/briefing").json()["read"] is True, "read: every device sees it")
check(A.post(B + "/api/briefing/read", json={"read": False}).json()["read"] is False, "read: false = unread again")
for bad in ({"read": "yes"}, {"x": 1}, [1]):
    check(A.post(B + "/api/briefing/read", json=bad).status_code == 400, f"read: bad body {bad} -> 400")
A.post(B + "/api/briefing/read", json={"read": True})
A.patch(B + "/api/settings", json={"brief_read": "{}", "brief_sent": "x"})
check(json.loads(dbx("SELECT value FROM user_settings WHERE user_id=? AND key='brief_read'", (ALICE,))[0][0]).get("day") == T0.isoformat(),
      "the read state is server-only (PATCH /api/settings ignores it)")
# a read on an earlier day moves "since" to that moment
dbx("UPDATE user_settings SET value=? WHERE user_id=? AND key='brief_read'",
    (json.dumps({"day": D(-1), "at": "2000-01-01T00:00:00+00:00", "prev": ""}), ALICE), write=True)
s2 = A.get(B + "/api/briefing").json()["since"]
check(s2[:10] >= D(-8), "since: never more than 7 days back " + s2)
dbx("UPDATE user_settings SET value=? WHERE user_id=? AND key='brief_read'",
    (json.dumps({"day": D(-1), "at": since0, "prev": ""}), ALICE), write=True)
check(A.get(B + "/api/briefing").json()["since"] == since0, "since: the moment of the read on an earlier day")

# ---- the agent API (tenant-matrix: aggregate)
r = requests.get(V + "/briefing", params={"user_id": ALICE}, headers=CLH)
check(r.ok, "v1: the agent reads alice's briefing " + r.text[:200])
vb = r.json()
check(t_today in [x["id"] for x in vb["today"]] and t_priv not in [x["id"] for x in vb["today"]] and "Dentist" not in r.text,
      "v1: only the lists alice shares with the agent " + str([x["id"] for x in vb["today"]]))
check(vb["read"] is False and vb["counts"]["today"] == 1, "v1: counts without the private list " + str(vb["counts"]))
check(requests.get(V + "/briefing", params={"user_id": CAROL}, headers=CLH).status_code == 404, "v1: a person who does not share a list with the agent: 404")
check(requests.get(V + "/briefing", params={"user_id": OT}, headers=CLH).status_code == 404, "v1: another agent: 404")
check(requests.get(V + "/briefing", params={"user_id": 99999}, headers=CLH).status_code == 404, "v1: unknown id: 404")
check(requests.get(V + "/briefing", headers=CLH).status_code == 400, "v1: an agent must name the person")
check(requests.get(V + "/briefing", params={"user_id": ALICE}, headers=OTH).status_code == 404, "v1: an agent without shared lists: 404")
check(requests.get(V + "/briefing", params={"user_id": BOB}, headers=CLH).status_code == 404,
      "v1: bob is only a member (lists open to their agents: owner / admins), not a chat partner: 404")
check(requests.get(V + "/briefing", params={"user_id": ALICE, "x": 1}, headers=CLH).status_code == 400, "v1: unknown parameter 400")
check(requests.get(V + "/briefing", params={"user_id": ALICE, "since": "nonsense"}, headers=CLH).status_code == 400, "v1: bad since 400")
r = requests.get(V + "/briefing", params={"user_id": ALICE, "since": "2020-01-01T00:00:00Z"}, headers=CLH)
check(r.ok and r.json()["since"] >= (T0 - timedelta(days=8)).isoformat(), "v1: since is capped at 7 days " + r.text[:100])
check(requests.get(B + "/api/briefing", headers=CLH).status_code in (401, 403, 404), "the app route is not for agent tokens")
tk = A.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read"]})
if tk.ok:
    TH = {"Authorization": "Bearer " + tk.json()["token"]}
    check(requests.get(V + "/briefing", headers=TH).json().get("counts", {}).get("today") == 2, "v1: a personal token reads its own briefing")
    check(requests.get(V + "/briefing", params={"user_id": BOB}, headers=TH).status_code == 404, "v1: a personal token cannot read someone else's")
else:
    check(False, "setup: personal token " + tk.text[:120])
# reading through the API marks nothing read
check(A.get(B + "/api/briefing").json()["read"] is False, "v1: reading marks nothing read")
spec = requests.get(V + "/openapi.json", headers=CLH).json()
check("/briefing" in spec["paths"] and "/lists/{id}/status-report" in spec["paths"], "openapi: both documented")

# ---- the push
check(Bo.patch(B + "/api/settings", json={"brief_time": "25:00"}).status_code == 400, "push: an invalid time 400")
open(os.path.join(DATA, "ntfy.log"), "w").close()
check(Bo.patch(B + "/api/settings", json={"brief_time": "00:00"}).ok, "push: bob turns it on")
got = []
for _ in range(16):
    time.sleep(0.5)
    got = [p for p in pushes() if p["topic"] == "t-bob" and p.get("title") == "Your briefing"]
    if got:
        break
check(len(got) == 1 and "1 due today" in got[0].get("msg", ""), "push: one push with the numbers " + str(got)[:300])
check("Layout draft" not in json.dumps(got), "push: numbers only, no titles")
time.sleep(2)
check(len([p for p in pushes() if p["topic"] == "t-bob" and p.get("title") == "Your briefing"]) == 1, "push: once a day")
check(dbx("SELECT value FROM user_settings WHERE user_id=? AND key='brief_sent'", (BOB,)) == [(T0.isoformat(),)], "push: brief_sent = today")
check(not [p for p in pushes() if p["topic"] == "t-carol" and p.get("title") == "Your briefing"], "push: off by default")

# ================================================================== #265 status report (tenant-matrix: list)
m1 = task(A, "Launch", P, due=D(5), ms=True)
t_prog = task(A, "Navigation", P)
A.post(B + f"/api/tasks/{t_prog}/comments", json={"body": "internal: the client is difficult"})
r = A.post(B + "/api/time/entries", json={"task_id": t_prog, "start": D(-1) + "T09:00", "minutes": 90})
check(r.ok, "setup: a time entry " + r.text[:120])
t_dave = task(A, "Dave's part", P, assignee_id=DAVE)
r = A.get(B + f"/api/lists/{P}/status-report")
check(r.ok, "report: 200 " + r.text[:200])
rp = r.json()
check(rp["from"] == D(-6) and rp["to"] == D(0), "report: the last 7 days by default " + rp["from"] + " " + rp["to"])
check([x["id"] for x in rp["done"]] == [t_done], "report: done in the period " + str(rp["done"]))
prog = [x["id"] for x in rp["in_progress"]]
check(t_prog in prog and t_cmt in prog and t_wait not in prog and t_blk not in prog, "report: in progress (changed / commented / time), blocked ones apart " + str(prog))
check({x["id"] for x in rp["blocked"]} >= {t_wait, t_blk}, "report: blocked " + str(rp["blocked"]))
check([x["id"] for x in rp["overdue"]] == [t_over], "report: overdue " + str(rp["overdue"]))
up = {x["id"]: x for x in rp["upcoming"]}
check(m1 in up and up[m1]["milestone"] and t_due in up and t_today in up, "report: next dates incl. the milestone " + str(list(up)))
check(any(x["id"] == m1 and not x["done"] for x in rp["milestones"]), "report: the next milestone")
check(rp["time"] and rp["time"]["seconds"] == 5400 and rp["time"]["tasks"][0]["id"] == t_prog, "report: tracked time " + str(rp["time"]))
md = rp["markdown"]
check(md.startswith("# Status report: Website") and "## Completed (1)" in md and "- Domain" in md, "report: markdown " + md[:200])
check("## Tracked time" in md and "Total: 1.5 h" in md, "report: hours in the text")
check("difficult" not in md and "Bob" not in md and "Alice" not in md and "First drafts" not in md and "Client Miller" in md,
      "report: no comments / names in the text; the waiting note stays (it is the task's state)")
r = A.get(B + f"/api/lists/{P}/status-report", params={"lang": "de"})
check(r.ok and r.json()["markdown"].startswith("# Statusbericht: Website") and "1,5 Std." in r.json()["markdown"], "report: German text " + r.text[:200])
check(A.get(B + f"/api/lists/{P}/status-report", params={"lang": "xx"}).status_code == 400, "report: unknown language 400")
r = A.get(B + f"/api/lists/{P}/status-report", params={"from": D(-1), "to": D(-30)})
check(r.ok and r.json()["from"] == D(-30) and r.json()["to"] == D(-1) and not r.json()["done"], "report: from / to swapped, older period without the completion")
for bad in ({"days": 0}, {"days": 400}, {"from": "2026-13-01"}, {"to": "x"}):
    check(A.get(B + f"/api/lists/{P}/status-report", params=bad).status_code == 400, f"report: {bad} -> 400")
r = A.get(B + f"/api/lists/{P}/status-report", params={"days": 30, "from": D(-500), "to": D(0)})
check(r.status_code == 400, "report: a period longer than a year 400")
# who may read it
check(Ca.get(B + f"/api/lists/{P}/status-report").status_code == 404, "report: a stranger 404")
check(A.get(B + f"/api/lists/{CP}/status-report").status_code == 404, "report: a list of another person 404")
check(A.get(B + "/api/lists/999999/status-report").status_code == 404, "report: unknown list 404")
check(Bo.get(B + f"/api/lists/{P}/status-report").ok, "report: a member reads it")
dp = Da.get(B + f"/api/lists/{P}/status-report").json()
check(json.dumps(dp).count('"id": ') >= 1 and "Domain" not in json.dumps(dp) and "Navigation" not in json.dumps(dp),
      "report: a participant sees only their own tasks " + json.dumps(dp)[:300])
r = requests.get(V + f"/lists/{P}/status-report", headers=CLH, params={"days": 7})
check(r.ok and r.json()["counts"]["done"] == 1, "v1: the agent reads the report of a shared list " + r.text[:160])
check(requests.get(V + f"/lists/{PRIV}/status-report", headers=CLH).status_code == 404, "v1: not a list that is not shared with it")
check(requests.get(V + f"/lists/{P}/status-report", headers=OTH).status_code == 404, "v1: another agent 404")
check(requests.get(V + f"/lists/{P}/status-report", headers=CLH, params={"bad": 1}).status_code == 400, "v1: unknown parameter 400")
# review M1: the tracked hours only with the scope time and with time tracking on for the person
check(r.ok and r.json()["time"] is None, "M1: an agent token without the scope time gets no hours " + str(r.json().get("time")))
if tk.ok:
    check(requests.get(V + f"/lists/{P}/status-report", headers=TH).json()["time"] is None, "M1: a read-only token gets no hours")
tk2 = A.post(B + "/api/me/tokens", json={"name": "with time", "scopes": ["read", "time"]})
check(tk2.ok and (requests.get(V + f"/lists/{P}/status-report", headers={"Authorization": "Bearer " + tk2.json()["token"]})
                  .json()["time"] or {}).get("seconds") == 5400, "M1: a token with the scope time gets the hours")
fs0 = dbx("SELECT value FROM user_settings WHERE user_id=? AND key='features'", (ALICE,))
fs0 = fs0[0][0] if fs0 else "cal,comments,collab,time"
check(A.patch(B + "/api/settings", json={"features": ",".join(f for f in fs0.split(",") if f != "time")}).ok, "M1: alice turns time tracking off")
rp2 = A.get(B + f"/api/lists/{P}/status-report").json()
check(rp2["time"] is None and "Tracked time" not in rp2["markdown"], "M1: time tracking off -> no hours in the report")
A.patch(B + "/api/settings", json={"features": fs0})
check((A.get(B + f"/api/lists/{P}/status-report").json()["time"] or {}).get("seconds") == 5400, "M1: back on -> the hours again")

# ================================================================== rollback safety: no new tables / columns from part A
check(not dbx("SELECT name FROM sqlite_master WHERE name LIKE '%brief%'"), "schema: nothing new for the briefing (user settings only)")

print(f"p2340_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
