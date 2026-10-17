#!/usr/bin/env python3
"""2.86.0 API tests, part E: agents / API hardening from the audit (N19, N20, N29-N32, N34). Invented names only.
 - N19: a token limited to selected lists never creates lists on import (403, nothing created); a file whose list matches
   an allowed list by name, or target = an allowed list, imports as usual
 - N20: a participant's mention picker (timeline people) names only the people who share the task; a mention of anyone
   else becomes plain text; the list owner still sees every member
 - N29: an agent's share request for a person it cannot see answers 404 without a waiting job; removing a non-member and
   unsharing a group the list is not shared with create no job; a visible person still waits for approval (202)
 - N30: the approval card of an agent's batch names the changed fields and the list with its task count
 - N31: at most KALMIDO_AGENT_PUSH_DAY pushes per agent and person a day (the messages still arrive)
 - N32: queued events of a list taken away from the agent are left out when it polls
 - N34: GET /api/v1/workload shows an agent only the people who share a list with it
usage: p286_e_api_test.py <datadir>      (a fresh container; P286E_NOSTART=1 = the server already runs, N31 is skipped)"""
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PUSH_DAY = 2


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


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def agent(name, scopes):
    r = A.post(B + "/api/admin/agents", json={"scopes": scopes, "username": name, "display_name": name.title()})
    assert r.ok, r.text
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def jobs(aid):
    return dbx("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=?", (aid,))[0][0]


def ev_list(x):
    d = x.get("data") or {}
    return d.get("list_id") or (d.get("task") or {}).get("list_id") or (d.get("list") or {}).get("id")


NOSTART = bool(os.environ.get("P286E_NOSTART"))
if not NOSTART:
    env = dict(os.environ)
    env["EXTRA"] = (env.get("EXTRA", "") + f" -e KALMIDO_AGENT_PUSH_DAY={PUSH_DAY}").strip()
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "t-alice"})
uid = {}
for u in ("bob", "carol", "erin", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "dave" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})
assert r.status_code in (200, 201), r.text
Bo, Ca = sess("bob"), sess("carol")
for s_ in (Bo, Ca):
    s_.patch(B + "/api/settings", json={"lang": "en"})


def mklist(name):
    r = A.post(B + "/api/lists", json={"name": name, "org_id": ORG})
    assert r.ok, r.text
    return r.json()["id"]


def task(lid, title, **kw):
    r = A.post(B + "/api/tasks", json={"list_id": lid, "title": title, **kw})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== N19: list-limited token and import
G = mklist("Garden")
OTHER = mklist("Shed")
r = A.post(B + "/api/me/tokens", json={"name": "garden only", "scopes": ["read", "write"], "list_ids": [G]})
check(r.status_code == 201, f"setup: a token limited to one list {r.text[:160]}")
TK = {"Authorization": "Bearer " + r.json().get("token", "")}


def ics(cal, title):
    return (f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//example//test//EN\r\nX-WR-CALNAME:{cal}\r\nBEGIN:VTODO\r\n"
            f"UID:{title.replace(' ', '-')}@example.com\r\nSUMMARY:{title}\r\nEND:VTODO\r\nEND:VCALENDAR\r\n").encode()


def imp(data, **opts):
    return requests.post(V + "/import/ics", headers=TK, files={"file": ("tasks.ics", data)}, data={k: str(v) for k, v in opts.items()})


n_lists = dbx("SELECT COUNT(*) FROM lists WHERE owner_id=?", (ALICE,))[0][0]
r = imp(ics("Brand new", "Plant tulips"))
check(r.status_code == 403 and "cannot create new lists" in r.text, f"N19: a limited token cannot create a list on import {r.status_code} {r.text[:160]}")
r = imp(ics("Brand new", "Plant tulips"), dry_run=1)
check(r.status_code == 403, f"N19: ... not even in the preview ({r.status_code})")
r = imp(ics("Shed", "Oil the hinges"))
check(r.status_code == 403, f"N19: a list of the same name outside the token's lists is refused too ({r.status_code})")
check(dbx("SELECT COUNT(*) FROM lists WHERE owner_id=?", (ALICE,))[0][0] == n_lists, "N19: no list was created")
check(not dbx("SELECT 1 FROM tasks WHERE title IN ('Plant tulips', 'Oil the hinges')"), "N19: no task was created")
r = imp(ics("Garden", "Water the roses"))
check(r.ok and dbx("SELECT list_id FROM tasks WHERE title='Water the roses'") == [(G,)] if r.ok else False,
      f"N19: a file whose list is the allowed list by name goes into it {r.status_code} {r.text[:160]}")
r = imp(ics("Brand new", "Cut the hedge"), target=G)
check(r.ok and dbx("SELECT list_id FROM tasks WHERE title='Cut the hedge'") == [(G,)] if r.ok else False,
      f"N19: target = an allowed list imports as usual {r.status_code} {r.text[:160]}")
check(dbx("SELECT COUNT(*) FROM lists WHERE owner_id=?", (ALICE,))[0][0] == n_lists, "N19: still no new list")
r = A.post(B + "/api/me/tokens", json={"name": "all lists", "scopes": ["read", "write"]})
r = requests.post(V + "/import/ics", headers={"Authorization": "Bearer " + r.json()["token"]},
                  files={"file": ("tasks.ics", ics("Brand new", "Paint the fence"))})
check(r.ok and dbx("SELECT COUNT(*) FROM lists WHERE owner_id=?", (ALICE,))[0][0] == n_lists + 1,
      f"N19: a token without a list limit still creates the list {r.status_code} {r.text[:160]}")

# ================================================================== N20: a participant's mention picker
L = mklist("Projects")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob edits")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["carol"], "role": "participant"}).ok, "setup: carol takes part")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["erin"], "role": "participant"}).ok, "setup: erin takes part")
T = task(L, "Carol's job", assignee_id=uid["carol"])
task(L, "Erin's job", assignee_id=uid["erin"])
r = Ca.get(B + f"/api/tasks/{T}/timeline")
ppl = {p["id"] for p in r.json().get("people", [])} if r.ok else set()
check(r.ok and {ALICE, uid["bob"], uid["carol"]} <= ppl, f"N20: the participant sees the people who share the task {sorted(ppl)}")
check(uid["erin"] not in ppl, f"N20: ... not another participant of the list {sorted(ppl)}")
ppl_a = {p["id"] for p in A.get(B + f"/api/tasks/{T}/timeline").json().get("people", [])}
check({ALICE, uid["bob"], uid["carol"], uid["erin"]} <= ppl_a, f"N20: the owner still sees every member {sorted(ppl_a)}")
r = Ca.post(B + f"/api/tasks/{T}/comments", json={"body": f"ask <@{uid['erin']}> and <@{uid['bob']}>"})
check(r.ok, f"setup: the participant comments {r.status_code} {r.text[:160]}")
row = dbx("SELECT body, mentions FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T,))
body, ment = (row[0][0] or "", row[0][1] or "") if row else ("", "")
check(f"<@{uid['erin']}>" not in body and str(uid["erin"]) not in ment.split(","), f"N20: a mention of someone outside the task stays plain text {body!r} {ment!r}")
check(f"<@{uid['bob']}>" in body and str(uid["bob"]) in ment.split(","), f"N20: a mention of someone who shares the task stays {body!r} {ment!r}")

# ================================================================== N29: share requests name nobody the agent cannot see
SH, SHH = agent("sharer", ["read", "tasks:write", "comments", "structure"])
GL = requests.post(V + "/lists", headers=SHH, json={"name": "Agent shares"}).json()["id"]
GID = A.post(B + "/api/admin/groups", json={"name": "Office", "members": [uid["bob"]]}).json()["id"]
n0 = jobs(SH)
r = requests.put(V + f"/lists/{GL}/members/{uid['dave']}", headers=SHH, json={"role": "view"})
check(r.status_code == 404 and jobs(SH) == n0, f"N29: a person of another organisation: 404, no waiting job ({r.status_code})")
r = requests.put(V + f"/lists/{GL}/members/999999", headers=SHH, json={"role": "view"})
check(r.status_code == 404 and jobs(SH) == n0, f"N29: an unknown id: 404, no job ({r.status_code})")
r = requests.delete(V + f"/lists/{GL}/members/{uid['carol']}", headers=SHH)
check(r.status_code == 404 and jobs(SH) == n0, f"N29: removing someone who is no member: 404, no job naming them ({r.status_code})")
r = requests.delete(V + f"/lists/{GL}/groups/{GID}", headers=SHH)
check(r.status_code != 202 and jobs(SH) == n0, f"N29: unsharing a group the list is not shared with: no job ({r.status_code})")
r = requests.put(V + f"/lists/{GL}/members/{uid['bob']}", headers=SHH, json={"role": "view"})
check(r.status_code == 202 and jobs(SH) == n0 + 1 and "Bob" in r.json()["job"]["title"],
      f"N29: a person it may see still waits for approval {r.status_code} {r.text[:160]}")

# ================================================================== N30: the batch approval card
W = mklist("Kitchen")
BA, BAH = agent("batcher", ["read", "tasks:write"])
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": BA, "role": "edit"}).ok, "setup: the agent edits the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob edits the list")
TS = [task(W, f"Dish {i}") for i in range(12)]
r = requests.post(V + "/tasks/batch", headers=BAH, json={"ids": TS, "action": "update", "changes": {"priority": 3}})
ttl = r.json().get("job", {}).get("title", "") if r.status_code == 202 else ""
check(r.status_code == 202 and "12" in ttl, f"N30: a batch of 12 waits for approval {r.status_code} {r.text[:160]}")
check("priority" in ttl and "Kitchen (12)" in ttl, f"N30: the card names the field and the list with its count {ttl!r}")

# ================================================================== N34: workload for an agent
r = requests.get(V + "/workload", headers=BAH)
wp = {p["id"] for p in r.json().get("people", [])} if r.ok else set()
check(r.ok and ALICE in wp, f"N34: the agent sees a person who shares a list with it {r.status_code} {sorted(wp)} {r.text[:120]}")
check(not ({uid["carol"], uid["erin"]} & wp), f"N34: ... not the rest of the organisation {sorted(wp)}")

# ================================================================== N32: events of a list taken away
EV, EVH = agent("listener", ["read", "tasks:write"])
L4 = mklist("Cellar")
check(A.put(B + f"/api/lists/{L4}/members", json={"user_id": EV, "role": "edit"}).ok, "setup: the agent is in the list")
T4 = task(L4, "Sort the wine", assignee_id=EV)
r = requests.get(V + "/agent/events", headers=EVH, params={"since": 0})
before = [x for x in r.json().get("data", []) if ev_list(x) == L4] if r.ok else []
check(r.ok and before, f"setup: the agent has events of the list {r.status_code} {[x['event'] for x in before]}")
check(A.delete(B + f"/api/lists/{L4}/members/{EV}").ok, "setup: the agent is taken out of the list")
r = requests.get(V + "/agent/events", headers=EVH, params={"since": 0})
after = [x for x in r.json().get("data", []) if ev_list(x) == L4] if r.ok else []
leak = [x["event"] for x in after if not (x["event"] == "unassigned" and set((x["data"].get("task") or {})) <= {"id", "list_id"})]
check(r.ok and not leak, f"N32: no queued event of the list is read after it was taken away {leak}")
check(r.ok and r.json().get("cursor", 0) >= max(x["seq"] for x in before), "N32: the cursor still moves past them")

# ================================================================== N31: daily push budget per agent and person
CH, CHH = agent("chatter", ["read", "tasks:write", "comments"])
if NOSTART:
    print("N31: skipped (the server was started without KALMIDO_AGENT_PUSH_DAY)")
else:
    check(A.post(B + f"/api/agents/{CH}/chat", json={"body": "Hello"}).status_code == 201, "setup: alice opens the chat")
    sent = []
    for i in range(PUSH_DAY + 2):
        r = requests.post(V + f"/agent/chats/{ALICE}", headers=CHH, json={"body": f"Pantry note {i}"})
        sent.append(r.status_code)
    check(all(x == 201 for x in sent), f"N31: every message arrives in the chat {sent}")
    t0 = time.time()
    while time.time() - t0 < 8 and not any("Pantry note 0" in (p.get("msg") or "") for p in pushes()):
        time.sleep(0.3)
    time.sleep(2)
    got = [p.get("msg") or "" for p in pushes() if "Pantry note" in (p.get("msg") or "")]
    check(any("Pantry note 0" in m for m in got), f"N31: the first message pushes {got}")
    check(len(got) <= PUSH_DAY and not any(f"Pantry note {PUSH_DAY}" in m or f"Pantry note {PUSH_DAY + 1}" in m for m in got),
          f"N31: past the daily budget no more pushes {got}")
    msgs = A.get(B + f"/api/agents/{CH}/chat").json().get("messages", [])
    check(len([m for m in msgs if "Pantry note" in (m.get("body") or "")]) == PUSH_DAY + 2, "N31: ... the messages are all in the chat")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
