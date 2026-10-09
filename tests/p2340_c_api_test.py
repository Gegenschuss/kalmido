#!/usr/bin/env python3
"""2.34.0 API tests (agent C), own container (start.sh).
 - #272 planned agent jobs: GET / POST /api/agents/<aid>/schedules, PATCH / DELETE /api/agent-schedules/<id>, POST .../run;
   who may plan (people who may chat with the agent, for themselves), managers (instance admins for a team agent, the owner
   of a personal agent) see and manage all, everybody else 404; validation (rhythm, days, time, time zone, list open to the
   person for the agent, unknown fields, lengths), at most 20 per person and agent; the next due time in the person's time
   zone; the watchdog sends ONE scheduled_job event per due time (late after an outage, never a catch-up storm), Run now
   (manual, at most every 10 minutes; manual_by when a manager runs someone else's plan), the kill switch (skipped), a list no longer shared (the plan switches itself off);
   the agent API (GET /api/v1/agent/schedules, read only), OpenAPI, the account export, a backup with the new table
   verifies and restores
usage: p2340_c_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_BACKUP_TICK=1"))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
for who in (CL, BOB):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in Work")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})  # bob may use the list's agents
PRIV = A.post(B + "/api/lists", json={"name": "Alice only"}).json()["id"]  # claude is not in it
W2 = A.post(B + "/api/lists", json={"name": "Second"}).json()["id"]  # bob keeps reaching claude here when Work goes
for who in (CL, BOB):
    A.put(B + f"/api/lists/{W2}/members", json={"user_id": who, "role": "edit"})
A.patch(B + f"/api/lists/{W2}", json={"agent_members": True})
O2 = A.post(B + "/api/lists", json={"name": "Otto's"}).json()["id"]
A.put(B + f"/api/lists/{O2}/members", json={"user_id": OT, "role": "edit"})


def plans(s, aid=CL):
    return s.get(B + f"/api/agents/{aid}/schedules")


def new(s, aid=CL, **b):
    body = {"title": "Week plan", "prompt": "Write the week plan.", "freq": "weekly", "days": [1], "time": "09:00", "tz": "Europe/Berlin", **b}
    return s.post(B + f"/api/agents/{aid}/schedules", json=body)


def events(h=CLH):
    return [e for e in requests.get(V + "/agent/events", headers=h, params={"since": 0, "limit": 500}).json()["data"] if e["event"] == "scheduled_job"]


def wait_for(fn, t=8.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


# ---- who may plan / see
r = plans(Bo)
check(r.status_code == 200 and r.json()["data"] == [] and r.json()["manager"] is False and r.json()["may_create"] is True and r.json()["max"] == 20,
      "#272: bob (may chat with claude) sees his empty plans " + r.text[:200])
check(plans(Ca).status_code == 404, "#272: carol (shares no list with claude) -> 404")
check(new(Ca).status_code == 404, "#272: carol cannot plan for claude -> 404")
check(plans(Bo, 999999).status_code == 404, "#272: an unknown agent -> 404")
check(plans(Bo, ALICE).status_code == 404, "#272: a person is not an agent -> 404")
check(plans(Bo, OT).status_code == 404, "#272: bob does not reach otto -> 404")

r = new(Bo, list_id=W)
p1 = r.json() if r.status_code == 201 else {}
check(r.status_code == 201 and p1["mine"] and p1["list_id"] == W and p1["list_name"] == "Work" and p1["enabled"] and p1["by_name"] == "Bob",
      "#272: bob plans a weekly job about Work " + r.text[:300])
nx = datetime.fromisoformat(p1["next_at"]) if p1.get("next_at") else None
check(nx and nx > datetime.now(timezone.utc) and nx.astimezone(ZoneInfo("Europe/Berlin")).isoweekday() == 1
      and nx.astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M") == "09:00" and nx - datetime.now(timezone.utc) <= timedelta(days=7),
      f"#272: the next run is the coming Monday 09:00 in Berlin ({p1.get('next_at')})")
r = new(Bo, freq="daily", time="07:30", tz="America/New_York", title="Daily")
nx = datetime.fromisoformat(r.json()["next_at"]) if r.ok else None
check(r.status_code == 201 and nx.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "07:30" and r.json()["days"] == [],
      "#272: daily at 07:30 New York time " + r.text[:200])
DAILY = r.json()["id"]
r = new(Bo, freq="monthly", days=[31], title="Monthly")
d = datetime.fromisoformat(r.json()["next_at"]).astimezone(ZoneInfo("Europe/Berlin")) if r.ok else None
last = ((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day if d else 0
check(r.status_code == 201 and d.day == last, f"#272: monthly on the 31st = the last day of a shorter month ({d})")
MONTHLY = r.json()["id"]
r = new(Bo, freq="weekdays", title="Workdays")
check(r.status_code == 201 and datetime.fromisoformat(r.json()["next_at"]).astimezone(ZoneInfo("Europe/Berlin")).isoweekday() <= 5,
      "#272: working days Mon-Fri")
check(Bo.delete(B + f"/api/agent-schedules/{r.json()['id']}").ok, "#272: delete my plan")

# ---- validation
bad = [({"freq": "hourly"}, "unknown rhythm"), ({"freq": "weekly", "days": []}, "weekly without days"), ({"days": [0]}, "weekday 0"),
       ({"days": [8]}, "weekday 8"), ({"days": ["1"]}, "weekday as text"), ({"days": [True]}, "weekday bool"),
       ({"freq": "monthly", "days": [32]}, "day 32"), ({"freq": "monthly", "days": [1, 2]}, "two days of the month"),
       ({"time": "25:00"}, "hour 25"), ({"time": "9:00"}, "time without leading zero"), ({"time": 900}, "time as number"),
       ({"tz": "Mars/Base"}, "unknown time zone"), ({"title": ""}, "empty title"), ({"title": "x" * 121}, "long title"),
       ({"prompt": "  "}, "empty prompt"), ({"prompt": "x" * 4001}, "long prompt"), ({"enabled": 1}, "enabled not bool"),
       ({"list_id": "1"}, "list id as text"), ({"agent_id": OT}, "unknown field"), ({"next_at": "2031-01-01"}, "next_at is not writable")]
for b, what in bad:
    r = new(Bo, **b)
    check(r.status_code == 400, f"#272: refused: {what} ({r.status_code} {r.text[:80]})")
check(new(Bo, list_id=PRIV).status_code == 404, "#272: a list bob cannot see -> 404")
check(new(Bo, list_id=O2).status_code == 404, "#272: otto's list (bob is no member) -> 404")
r = new(A, list_id=PRIV)
check(r.status_code == 400 and "not shared" in r.text, "#272: alice: her list without claude cannot be saved -> 400 " + r.text[:120])
check(len(plans(Bo).json()["data"]) == 3, "#272: refused plans are not stored")

# ---- at most 20 per person and agent
made = []
for i in range(17):
    made.append(new(Bo, title=f"n{i}").json()["id"])
r = new(Bo, title="one too many")
check(r.status_code == 409, f"#272: the 21st plan of bob for claude -> 409 ({r.status_code})")
check(new(A, title="alice's own").status_code == 201, "#272: the limit is per person (alice may still plan)")
for i in made:
    Bo.delete(B + f"/api/agent-schedules/{i}")

# ---- managers: an instance admin sees and manages every plan of a team agent; others 404
j = plans(A).json()
check(j["manager"] is True and {p["user_id"] for p in j["data"]} == {ALICE, BOB} and j["data"][0]["user_id"] == ALICE,
      "#272: alice (instance admin) sees all plans of claude, her own first")
bp = next(p for p in j["data"] if p["id"] == p1["id"])
check(bp["mine"] is False and bp["by_name"] == "Bob", "#272: bob's plan is marked as his")
check({p["user_id"] for p in plans(Bo).json()["data"]} == {BOB}, "#272: bob sees only his own plans")
r = A.patch(B + f"/api/agent-schedules/{p1['id']}", json={"enabled": False})
check(r.ok and r.json()["enabled"] is False and r.json()["next_at"] is None, "#272: alice pauses bob's plan " + r.text[:200])
r = Bo.patch(B + f"/api/agent-schedules/{p1['id']}", json={"enabled": True, "time": "10:15"})
check(r.ok and r.json()["enabled"] and r.json()["time"] == "10:15" and r.json()["next_at"], "#272: bob switches it on again at 10:15")
alice_plan = next(p for p in j["data"] if p["user_id"] == ALICE)
check(Bo.patch(B + f"/api/agent-schedules/{alice_plan['id']}", json={"enabled": False}).status_code == 404, "#272: bob cannot touch alice's plan -> 404")
check(Ca.patch(B + f"/api/agent-schedules/{p1['id']}", json={"enabled": False}).status_code == 404, "#272: carol cannot change bob's plan -> 404")
check(Ca.delete(B + f"/api/agent-schedules/{p1['id']}").status_code == 404, "#272: carol cannot delete it -> 404")
check(Ca.post(B + f"/api/agent-schedules/{p1['id']}/run").status_code == 404, "#272: carol cannot run it -> 404")
check(Bo.patch(B + "/api/agent-schedules/999999", json={"enabled": False}).status_code == 404, "#272: unknown plan -> 404")
check(Bo.patch(B + f"/api/agent-schedules/{p1['id']}", json={"list_id": PRIV}).status_code == 404, "#272: bob cannot move his plan to alice's list")
check(A.patch(B + f"/api/agent-schedules/{p1['id']}", json={"list_id": PRIV}).status_code in (400, 404),
      "#272: alice cannot point bob's plan at a list that is not open to bob")
A.delete(B + f"/api/agent-schedules/{alice_plan['id']}")

# ---- the agent API: read only, per agent
r = requests.get(V + "/agent/schedules", headers=CLH)
d = r.json()["data"] if r.ok else []
check(r.ok and {p["id"] for p in d} == {p1["id"], DAILY, MONTHLY} and all(p["user_id"] == BOB for p in d), "#272: claude reads its plans " + r.text[:200])
w = next((p for p in d if p["id"] == p1["id"]), {})
check(w.get("prompt") == "Write the week plan." and (w.get("list") or {}).get("id") == W and "mine" not in w, "#272: with prompt and list")
check(requests.get(V + "/agent/schedules", headers=OTH).json()["data"] == [], "#272: otto has none")
check(requests.post(V + "/agent/schedules", headers=CLH, json={"title": "x"}).status_code in (404, 405), "#272: an agent cannot create plans")
tok = Bo.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read"]})
if tok.ok and tok.json().get("token"):
    check(requests.get(V + "/agent/schedules", headers={"Authorization": "Bearer " + tok.json()["token"]}).status_code == 403,
          "#272: a person's token cannot read agent plans")
spec = requests.get(V + "/openapi.json").json()
check("/agent/schedules" in spec.get("paths", {}) and "Schedule" in spec.get("components", {}).get("schemas", {}), "#272: OpenAPI documents it")

# ---- the watchdog: one event per due time
for p in (DAILY, MONTHLY):
    Bo.patch(B + f"/api/agent-schedules/{p}", json={"enabled": False})
past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", (past, p1["id"]), write=True)
ev = wait_for(lambda: [e for e in events() if e["data"]["schedule_id"] == p1["id"]])
e = ev[0]["data"] if ev else {}
check(len(ev) == 1 and e.get("title") == "Week plan" and e.get("prompt") == "Write the week plan." and e.get("list_id") == W
      and e.get("by") == {"id": BOB, "name": "Bob"} and e.get("chat_with") == BOB and e.get("late") is False and e.get("manual") is False
      and e.get("due_at") == past and (e.get("list") or {}).get("name") == "Work" and e.get("rhythm", {}).get("time") == "10:15",
      "#272: the due plan sent ONE scheduled_job event " + str(ev)[:400])
time.sleep(2.5)
st = plans(Bo).json()["data"]
q = next(p for p in st if p["id"] == p1["id"])
check(len([x for x in events() if x["data"]["schedule_id"] == p1["id"]]) == 1 and q["last_state"] == "sent" and q["next_at"] > past
      and datetime.fromisoformat(q["next_at"]) > datetime.now(timezone.utc), "#272: no second event, the next run is in the future " + str(q)[:200])
# an outage of three days: only ONE run, marked late
dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds"), p1["id"]), write=True)
ev = wait_for(lambda: [x for x in events() if x["data"]["schedule_id"] == p1["id"] and x["data"]["late"]])
time.sleep(2.5)
check(len(ev) == 1 and len([x for x in events() if x["data"]["schedule_id"] == p1["id"]]) == 2, "#272: after an outage exactly one late run, no catch-up")
check(next(p for p in plans(Bo).json()["data"] if p["id"] == p1["id"])["last_state"] == "late", "#272: last_state late")

# ---- Run now
r = Bo.post(B + f"/api/agent-schedules/{p1['id']}/run")
check(r.status_code == 429, "#272: Run now right after a run -> 429 " + r.text[:100])
dbx("UPDATE agent_schedules SET last_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(timespec="seconds"), p1["id"]), write=True)
r = Bo.post(B + f"/api/agent-schedules/{p1['id']}/run")
ev = [x for x in events() if x["data"]["schedule_id"] == p1["id"] and x["data"]["manual"]]
check(r.ok and r.json()["last_state"] == "manual" and len(ev) == 1 and ev[0]["actor"] and ev[0]["actor"]["id"] == BOB,
      "#272: Run now sends one manual event with bob as the actor " + r.text[:200])
check(Bo.post(B + f"/api/agent-schedules/{p1['id']}/run").status_code == 429, "#272: Run now at most every 10 minutes")
before = r.json()["next_at"]
check(next(p for p in plans(Bo).json()["data"] if p["id"] == p1["id"])["next_at"] == before, "#272: Run now keeps the rhythm")
check(ev and ev[0]["data"].get("manual_by", "missing") is None, "N2: the person's own Run now: manual_by null")
# review N2: a manager runs bob's plan -> the event names who triggered it (the answer still goes to bob)
dbx("UPDATE agent_schedules SET last_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(timespec="seconds"), p1["id"]), write=True)
r = A.post(B + f"/api/agent-schedules/{p1['id']}/run")
ev = [x for x in events() if x["data"]["schedule_id"] == p1["id"] and x["data"].get("manual_by")]
check(r.ok and len(ev) == 1 and ev[0]["data"]["manual_by"]["id"] == ALICE and ev[0]["data"]["manual_by"]["name"]
      and ev[0]["data"]["chat_with"] == BOB, "N2: alice's Run now on bob's plan: manual_by alice, chat with bob " + r.text[:200])

# ---- kill switch: skipped, nothing queued
n0 = len(events())
check(A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": False}).ok, "setup: claude switched off")
dbx("UPDATE agent_schedules SET next_at=?, last_at=NULL WHERE id=?", (past, p1["id"]), write=True)
q = wait_for(lambda: (lambda p: p if p["last_state"] == "skipped" else None)(next(p for p in plans(Bo).json()["data"] if p["id"] == p1["id"])))
check(q and q["last_state"] == "skipped" and q["enabled"] and q["next_at"] > past, "#272: a switched-off agent: the run is skipped, the plan goes on " + str(q)[:200])
check(Bo.post(B + f"/api/agent-schedules/{p1['id']}/run").status_code == 409, "#272: Run now on a switched-off agent -> 409")
A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": True})
check(len(events()) == n0, "#272: nothing was queued while it was off")

# ---- the list is no longer shared with the agent: the plan switches itself off
A.delete(B + f"/api/lists/{W}/members/{CL}")
dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", (past, p1["id"]), write=True)
q = wait_for(lambda: (lambda p: p if not p["enabled"] else None)(next(p for p in plans(Bo).json()["data"] if p["id"] == p1["id"])))
check(q and q["last_state"] == "no_list" and q["next_at"] is None, "#272: list no longer shared -> switched off (no_list) " + str(q)[:200])
check(len(events()) == n0, "#272: and no event")
A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"})
r = Bo.patch(B + f"/api/agent-schedules/{p1['id']}", json={"enabled": True})
check(r.ok and r.json()["enabled"] and r.json()["last_state"] is None, "#272: switched on again, the reason is gone")

# ---- the account export carries my plans
ex = Bo.get(B + "/api/export.json")
check(ex.ok and any(p["id"] == p1["id"] for p in ex.json().get("agent_schedules", [])), "#272: the account export lists bob's plans")
check(not any(p["user_id"] != BOB for p in ex.json().get("agent_schedules", [])), "#272: only his own")

# ---- a backup with the new table verifies and restores
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: a backup with agent_schedules verifies " + r.text[:200])
dbx("DELETE FROM agent_schedules", write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
Bo = sess("bob")
check(any(p["id"] == p1["id"] for p in plans(Bo).json().get("data", [])), "backup: the plans are back after the restore")

# ---- deleting the agent removes its plans
A.delete(B + f"/api/admin/agents/{CL}")
check(dbx("SELECT COUNT(*) FROM agent_schedules WHERE agent_id=?", (CL,))[0][0] == 0, "#272: plans go with their agent")

print(f"p2340_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
