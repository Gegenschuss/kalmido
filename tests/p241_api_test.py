#!/usr/bin/env python3
"""2.4.1 API tests: agent runtime settings (#377), exactly one tidy agent per list (#379), the agent's state for the chat
header + typing signal (#375) and the wake routes without a button (#376).
 - runtime: defaults in GET /api/v1/agent (+ timezone) and the admin list; PATCH /api/admin/agents/{id} {runtime} changes only
   the given keys, validates model (characters, length), autocompact (bool), autocompact_pct (10-100 / null), nightly_reset
   (HH:MM / ""), unknown keys; an unchanged runtime sends no event, a change sends runtime_changed; admins only; create with
   runtime; POST /api/admin/agents/{id}/reset raises reset_seq + event reset (admins only, 409 while paused)
 - tidy agent: the first agent with edit rights by default (participants never), tidy events only to it, PATCH
   /api/lists/{id} {tidy_agent_id} (owner / list admin; a participant agent, a non-member, a bad type refused), v1 lists +
   the event's list carry tidy_agent_id, suggestions / POST /api/v1/tasks/{id}/tidy by another agent 403, the fallback when
   the tidy agent leaves the list, the one-time migration of lists with tidy on (their first agent)
 - chat header: online null before the first poll, true after it (last_poll_at, poll_age), false after 5 minutes without one
   (and back with a version bump); POST /api/v1/agent/typing {chat_user_id} (validation, only people sharing a list, 10 s,
   the answer ends it, only the addressed person sees it); my_job; OpenAPI /agent/typing
 - wake: POST /api/tasks/{id}/wake and /api/agents/{id}/wake still send the event
Starts its OWN containers (start.sh).
usage: p241_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")


def put_member(s, lid, uid, role):
    """2.26.0: shares like PUT /lists/{id}/members; a second agent (one agent per list) joins as in a list from before the
    update, and the list's members may use its agents (the list switch, default off since 2.26.0). Returns a truthy object."""
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if r.status_code == 409 and "one agent" in r.text.lower():
        c_ = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
        c_.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
                   (lid, uid, role, role))
        c_.commit()
        c_.close()
    s.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True})
    return r.status_code == 409 or r.ok


V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(keep=False):
    if not keep:
        subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def stop():
    subprocess.run(["docker", "stop", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)

    def patch(self, p, **k):
        return self.req("PATCH", p, **k)


def dbx(q, a=()):
    con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        r = con.execute(q, a).fetchall()
        con.commit()
        return r
    finally:
        con.close()


def events(cl, since=0):
    return cl.get("/agent/events", params={"since": since, "limit": 500}).json()["data"]


def kinds(cl, kind, since=0):
    return [e for e in events(cl, since) if e["event"] == kind]


def new_agent(a, name, **extra):
    r = a.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title(), **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], Api(r.json()["token"])


def agent_seen(s, aid):
    return next((a for a in s.get(B + "/api/agents").json()["agents"] if a["id"] == aid), None)


def lst(s, lid):
    return next(x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid)


def version(s):
    return s.get(B + "/api/version").json()["v"]


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
AG, cl = new_agent(A, "claude")
AG2, cl2 = new_agent(A, "helper")
AG3, ro = new_agent(A, "robo")

# ================================================================== #377 runtime settings
me = cl.get("/agent").json()
check(me.get("runtime") == {"model": "", "autocompact": True, "autocompact_pct": None, "nightly_reset": "", "reset_seq": 0,
                            "timezone": "Europe/Berlin"}, f"runtime defaults: {me.get('runtime')}")
adm = next(a for a in A.get(B + "/api/admin/agents").json()["agents"] if a["id"] == AG)
check(adm["runtime"]["model"] == "" and adm["runtime"]["reset_seq"] == 0, "admin list: runtime")
cur = me["events_cursor"]
r = A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": {"model": "sonnet", "autocompact_pct": 70, "nightly_reset": "04:00"}})
check(r.ok and r.json()["runtime"] == {"model": "sonnet", "autocompact": True, "autocompact_pct": 70, "nightly_reset": "04:00", "reset_seq": 0},
      f"runtime saved: {r.status_code} {r.text[:200]}")
ev = kinds(cl, "runtime_changed", cur)
check(len(ev) == 1 and ev[0]["data"]["runtime"]["model"] == "sonnet" and ev[0]["data"]["runtime"]["timezone"] == "Europe/Berlin"
      and ev[0]["actor"]["id"] == ALICE, f"event runtime_changed: {ev}")
check(cl.get("/agent").json()["runtime"]["nightly_reset"] == "04:00", "the agent reads it")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": {"model": "claude-opus-4-1[1m]"}})
rt = r.json().get("runtime", {})
check(r.ok and rt["model"] == "claude-opus-4-1[1m]" and rt["autocompact_pct"] == 70 and rt["nightly_reset"] == "04:00",
      f"only the given keys change: {rt}")
n0 = len(kinds(cl, "runtime_changed", cur))
check(A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": {"model": "claude-opus-4-1[1m]"}}).ok, "same value: ok")
check(len(kinds(cl, "runtime_changed", cur)) == n0, "unchanged runtime: no event")
for bad, what in (({"model": "rm -rf /"}, "model with spaces"), ({"model": "x" * 101}, "model too long"), ({"model": 5}, "model not text"),
                  ({"autocompact": "yes"}, "autocompact not bool"), ({"autocompact_pct": 5}, "pct < 10"), ({"autocompact_pct": 101}, "pct > 100"),
                  ({"autocompact_pct": True}, "pct bool"), ({"autocompact_pct": 70.5}, "pct float"), ({"nightly_reset": "25:00"}, "bad time"),
                  ({"nightly_reset": "4"}, "time without minutes"), ({"sandbox": True}, "unknown key")):
    check(A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": bad}).status_code == 400, f"400: {what}")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": "opus"}).status_code == 400, "runtime not an object: 400")
check(cl.get("/agent").json()["runtime"]["model"] == "claude-opus-4-1[1m]", "a refused change changed nothing")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"runtime": {"autocompact": False, "autocompact_pct": None, "nightly_reset": "", "model": ""}})
check(r.ok and r.json()["runtime"] == {"model": "", "autocompact": False, "autocompact_pct": None, "nightly_reset": "", "reset_seq": 0},
      f"back to defaults, auto-compact off: {r.json().get('runtime')}")
check(Bo.patch(B + f"/api/admin/agents/{AG}", json={"runtime": {"model": "opus"}}).status_code == 403, "non-admin: 403")
check(cl.patch(f"/agent", json={"runtime": {"model": "opus"}}).status_code in (403, 404, 405), "the agent cannot change it itself")
AG4, cl4 = new_agent(A, "nightly", runtime={"model": "haiku", "nightly_reset": "03:30"})
check(cl4.get("/agent").json()["runtime"]["model"] == "haiku" and cl4.get("/agent").json()["runtime"]["nightly_reset"] == "03:30",
      "created with runtime")
check(A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "badrt", "runtime": {"autocompact_pct": 3}}).status_code == 400
      and not dbx("SELECT 1 FROM users WHERE username='badrt'"), "create with a bad runtime: 400, nothing created")
# reset now
cur = cl.get("/agent").json()["events_cursor"]
v0 = version(A)
r = A.post(B + f"/api/admin/agents/{AG}/reset")
check(r.ok and r.json() == {"ok": True, "reset_seq": 1}, f"reset: {r.status_code} {r.text[:100]}")
ev = kinds(cl, "reset", cur)
check(len(ev) == 1 and ev[0]["data"]["reset_seq"] == 1 and ev[0]["data"]["runtime"]["reset_seq"] == 1 and ev[0]["data"]["user"]["id"] == ALICE,
      f"event reset: {ev}")
check(cl.get("/agent").json()["runtime"]["reset_seq"] == 1 and version(A) != v0, "reset_seq 1, the version moved")
A.post(B + f"/api/admin/agents/{AG}/reset")
check(cl.get("/agent").json()["runtime"]["reset_seq"] == 2, "reset_seq counts on")
check(Bo.post(B + f"/api/admin/agents/{AG}/reset").status_code == 403, "reset: non-admin 403")
check(A.post(B + "/api/admin/agents/99999/reset").status_code == 404, "reset: unknown agent 404")
A.patch(B + f"/api/admin/agents/{AG4}", json={"enabled": False})
check(A.post(B + f"/api/admin/agents/{AG4}/reset").status_code == 409, "reset while paused: 409")
check(A.patch(B + f"/api/admin/agents/{AG4}", json={"runtime": {"model": "opus"}}).ok, "runtime of a paused agent can be edited")
A.patch(B + f"/api/admin/agents/{AG4}", json={"enabled": True})
check(cl4.get("/agent").json()["runtime"]["model"] == "opus" and not kinds(cl4, "runtime_changed"), "paused: saved, no event")

# ================================================================== #379 one tidy agent per list
L = A.post(B + "/api/lists", json={"name": "Inbox cleanup"}).json()["id"]
for uid, role in ((BOB, "edit"), (AG3, "participant"), (AG, "edit"), (AG2, "edit")):
    assert put_member(A, L, uid, role)
check(lst(A, L)["tidy_agent_id"] == AG, f"default: the first agent with edit rights (robo is a participant): {lst(A, L)['tidy_agent_id']}")
check(A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "suggest"}).ok, "tidy on")
curs = {k: c.get("/agent").json()["events_cursor"] for k, c in (("cl", cl), ("cl2", cl2), ("ro", ro))}
T1 = A.post(B + "/api/tasks", json={"title": "call the plumber about the kitchen sink next week maybe tuesday", "list_id": L}).json()["id"]
check([e["data"]["task"]["id"] for e in kinds(cl, "tidy", curs["cl"])] == [T1], "tidy event to the tidy agent")
check(not kinds(cl2, "tidy", curs["cl2"]) and not kinds(ro, "tidy", curs["ro"]), "no tidy event to the other agents")
ev = kinds(cl, "tidy", curs["cl"])[0]
check(ev["data"]["list"].get("tidy_agent_id") == AG, "the event's list carries tidy_agent_id")
check(next(x for x in cl.get("/lists").json()["data"] if x["id"] == L)["tidy_agent_id"] == AG, "v1 lists: tidy_agent_id")
check(A.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": AG3}).status_code == 400, "participant agent: 400")
check(A.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": AG4}).status_code == 400, "agent not in the list: 400")
check(A.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": BOB}).status_code == 400, "a person: 400")
check(A.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": "2"}).status_code == 400, "not a number: 400")
check(Bo.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": AG2}).status_code == 403, "member without manage rights: 403")
check(cl.patch(f"/lists/{L}", json={"tidy_agent_id": AG2}).status_code in (400, 403, 404, 405), "no v1 route for it")
check(A.patch(B + f"/api/lists/{L}", json={"tidy_agent_id": AG2}).ok and lst(A, L)["tidy_agent_id"] == AG2, "owner picks helper")
check(lst(Bo, L)["tidy_agent_id"] == AG2, "a member sees the tidy agent too")
curs = {k: c.get("/agent").json()["events_cursor"] for k, c in (("cl", cl), ("cl2", cl2))}
T2 = A.post(B + "/api/tasks", json={"title": "buy new filters for the vacuum cleaner and the kitchen hood", "list_id": L}).json()["id"]
check([e["data"]["task"]["id"] for e in kinds(cl2, "tidy", curs["cl2"])] == [T2] and not kinds(cl, "tidy", curs["cl"]), "events now only to helper")
r = cl.post(f"/tasks/{T2}/comments", json={"body": "Suggestion", "suggestion": {"title": "Vacuum + hood filters"}})
check(r.status_code == 403, f"suggestion by the other agent: 403 ({r.status_code})")
check(cl2.post(f"/tasks/{T2}/comments", json={"body": "Suggestion", "suggestion": {"title": "Vacuum + hood filters"}}).status_code == 201,
      "suggestion by the tidy agent")
A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "auto"})
check(cl.post(f"/tasks/{T2}/tidy", json={"title": "x"}).status_code == 403, "auto tidy by the other agent: 403")
check(cl2.post(f"/tasks/{T2}/tidy", json={"title": "Filters: vacuum + hood"}).ok, "auto tidy by the tidy agent")
# the tidy agent leaves the list -> the first remaining candidate; comes back -> still the chosen one
assert A.delete(B + f"/api/lists/{L}/members/{AG2}").ok
check(lst(A, L)["tidy_agent_id"] == AG, "helper left: claude tidies up")
assert put_member(A, L, AG2, "edit")
check(lst(A, L)["tidy_agent_id"] == AG2, "helper back: the stored choice counts again")
check(A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "suggest", "tidy_agent_id": AG}).ok and lst(A, L)["tidy_agent_id"] == AG
      and lst(A, L)["agent_tidy"] == "suggest", "mode + agent in one PATCH")
# a list with only a participant agent: tidy cannot be switched on
LP = A.post(B + "/api/lists", json={"name": "Participant only"}).json()["id"]
A.put(B + f"/api/lists/{LP}/members", json={"user_id": AG3, "role": "participant"})
r = A.patch(B + f"/api/lists/{LP}", json={"agent_tidy": "suggest"})
check(r.status_code == 409 and "edit rights" in r.json().get("error", ""), f"only a participant agent: 409 ({r.status_code} {r.text[:80]})")
check(lst(A, LP)["tidy_agent_id"] is None, "no candidate: tidy_agent_id null")
spec = requests.get(B + "/api/v1/openapi.json").json()
check("/agent/typing" in spec["paths"] and "tidy_agent_id" in spec["components"]["schemas"]["List"]["properties"]
      and "runtime" in spec["components"]["schemas"]["Agent"]["properties"], "OpenAPI: /agent/typing, List.tidy_agent_id, Agent.runtime")
check({"runtime_changed", "reset"} <= set(spec["components"]["schemas"]["AgentEvent"]["properties"]["event"]["enum"]), "OpenAPI: new events")

# ================================================================== #375 chat header: online / typing / my_job
AG5, cl5 = new_agent(A, "chatty")
C = A.post(B + "/api/lists", json={"name": "Chat list"}).json()["id"]
for uid in (BOB, AG5):
    put_member(A, C, uid, "edit")
a4 = agent_seen(A, AG5)
check(a4 and a4["online"] is None and a4["last_poll_at"] is None and a4["poll_age"] is None and a4["typing"] == 0,
      f"never polled: online null ({a4 and {k: a4.get(k) for k in ('online', 'last_poll_at', 'poll_age')}})")
v0 = version(A)
cl5.get("/agent/events", params={"since": 0})
a4 = agent_seen(A, AG5)
check(a4["online"] is True and a4["last_poll_at"] and a4["poll_age"] is not None and a4["poll_age"] <= 2, f"after a poll: online {a4['online']}")
check(version(A) != v0, "coming online moves the version")
v1 = version(A)
cl5.get("/agent/events", params={"since": 0})
check(version(A) == v1, "the next poll (within 30 s) writes nothing")
check(cl5.get("/agent").json()["online"] is True, "GET /agent: online")
# typing
r = cl5.post("/agent/typing", json={"chat_user_id": ALICE})
check(r.ok and r.json() == {"ok": True, "chat_user_id": ALICE, "expires_in": 10}, f"typing: {r.status_code} {r.text[:100]}")
check(7 < agent_seen(A, AG5)["typing"] <= 10, f"alice sees the typing signal: {agent_seen(A, AG5)['typing']}")
check(agent_seen(Bo, AG5)["typing"] == 0, "bob does not")
check(cl5.post("/agent/typing", json={"chat_user_id": ALICE, "x": 1}).status_code == 400, "unknown field: 400")
check(cl5.post("/agent/typing", json={}).status_code == 400, "missing chat_user_id: 400")
check(cl5.post("/agent/typing", json={"chat_user_id": "1"}).status_code == 400, "chat_user_id as text: 400")
check(cl5.post("/agent/typing", json={"chat_user_id": CAROL}).status_code == 404, "a person who shares nothing with it: 404")
check(cl5.post("/agent/typing", json={"chat_user_id": AG}).status_code == 404, "another agent: 404")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
check(Api(tok).post("/agent/typing", json={"chat_user_id": BOB}).status_code == 403, "people cannot send it")
cl5.post(f"/agent/chats/{ALICE}", json={"body": "Here is the answer."})
check(agent_seen(A, AG5)["typing"] == 0, "the answer ends the typing signal")
cl5.post("/agent/typing", json={"chat_user_id": BOB})
time.sleep(10.5)
check(agent_seen(Bo, AG5)["typing"] == 0, "the signal runs out after 10 s")
# my_job
j = cl5.post("/agent/jobs", json={"title": "Write the offer", "user_id": ALICE}).json()
check(agent_seen(A, AG5)["my_job"] is True and agent_seen(Bo, AG5)["my_job"] is False, "my_job: only for the person the job is for")
cl5.patch(f"/agent/jobs/{j['id']}", json={"state": "done"})
check(agent_seen(A, AG5)["my_job"] is False, "a finished job does not count")
# offline after 5 minutes without a poll (and back)
stop()
old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
dbx("UPDATE agents SET last_poll_at=? WHERE user_id=?", (old, AG5))
# the migration of #379 runs once: a list that had tidy on before 2.4.1 gets its first agent
dbx("UPDATE lists SET agent_tidy='suggest', tidy_agent=NULL WHERE id=?", (C,))
dbx("DELETE FROM settings WHERE key='migr_tidy_agent'")
start(keep=True)
A, Bo = sess("alice"), sess("bob")
a4 = agent_seen(A, AG5)
check(a4["online"] is False and a4["poll_age"] >= 590, f"no poll for 10 minutes: offline ({a4['online']}, {a4['poll_age']})")
check(dbx("SELECT tidy_agent FROM lists WHERE id=?", (C,)) == [(AG5,)], "migration: the list's first agent tidies it up")
check(dbx("SELECT value FROM settings WHERE key='migr_tidy_agent'") == [("1",)], "migration done once")
check(dbx("SELECT tidy_agent FROM lists WHERE id=?", (L,)) == [(AG,)], "migration: a stored choice stays")
v0 = version(A)
cl5.get("/agent/events", params={"since": 0})
check(agent_seen(A, AG5)["online"] is True and version(A) != v0, "back online with a version bump")

# ================================================================== #376 wake without a button: the routes stay
T3 = A.post(B + "/api/tasks", json={"title": "Wake me", "list_id": C}).json()["id"]
cur = cl5.get("/agent").json()["events_cursor"]
r = A.post(B + f"/api/tasks/{T3}/wake", json={})
check(r.ok and r.json()["agent_id"] == AG5, f"POST /api/tasks/{{id}}/wake: {r.status_code}")
r = A.post(B + f"/api/agents/{AG5}/wake", json={"task_id": T3})
ev = kinds(cl5, "wake", cur)
check(r.ok and [e["data"]["source"] for e in ev] == ["task", "chat"], f"both wake routes send the event: {[e['data'].get('source') for e in ev]}")

print(f"p241_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
