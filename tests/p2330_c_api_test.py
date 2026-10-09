#!/usr/bin/env python3
"""2.33.0 API tests, part C: notification templates per list and shared folder (#927) and the client address check (#834).
 - a new share starts with "read" (KALMIDO_NOTIF_TEMPLATE=read here, the app's default): a comment on a member's task
   gives no push (the News item stays), a mention and an assignment still push; "work" lets the comment push through;
   a template per person beats the list's; "custom" pushes only the ticked events; due reminders follow the template
 - only the owner changes it (member 403, stranger 404, bad values 400, a person not in the list 404); members read what
   limits them (state notif_cap, GET .../notify-template); agents read it via /api/v1, never change it
 - folders: a list in a shared folder follows the folder's template until it has its own, "reset_lists" brings the lists
   back to the folder, a template per person of the folder, a rename keeps it, a stranger's folder is 404
 - migration (once): lists / folders shared before 2.33 get "all" written, their owners are asked once (notif_ask)
 - rollback safety: only new tables (list_notif, folder_notif, login_ips)
 - #834: GET /api/admin/client-ip (admins): the address the server sees, private, the warning when many accounts sign in
   from one private address (the test setup IS that case: every request comes through the docker gateway) + server log
usage: p2330_c_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
NAME = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def to(topic, wait=1.5):
    time.sleep(wait)
    return [p for p in pushes() if p["topic"] == topic]


def start(keep=False):
    env = {**os.environ, "KALMIDO_NOTIF_TEMPLATE": "read"}
    if keep:
        env["KEEP"] = "1"
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)


start()
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
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")


def tpl_url(lid):
    return B + f"/api/lists/{lid}/notify-template"


def task(s, title, lid, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    assert r.ok, r.text


def state_list(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for who in (BOB, CAROL):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": who, "role": "edit"}).ok

# ================================================================== a new share starts with "read"
j = A.get(tpl_url(L)).json()
check(j["own"] is None and j["effective"]["tpl"] == "read" and j["default"] == "read" and {p["user_id"] for p in j["people"]} == {BOB, CAROL},
      "#927: owner sees the list's template: nothing own, effective read, both members " + json.dumps(j)[:200])
jb = Bo.get(tpl_url(L)).json()
check(jb["effective"]["tpl"] == "read" and jb["by"] == "Alice" and "mention" in jb["allowed"] and "comment" not in jb["allowed"] and "people" not in jb,
      "#927: a member reads only what limits them " + json.dumps(jb)[:200])
sl = state_list(Bo, L)
check(sl and sl["notif_cap"] and sl["notif_cap"]["tpl"] == "read" and sl["notif_cap"]["by"] == "Alice", "#927: state notif_cap for the member")
check(state_list(A, L)["notif_cap"] is None, "#927: the owner is never limited (notif_cap null)")

T1 = task(Bo, "T1 bob", L)
clear()
comment(A, T1, "a plain comment")
check(not to("t-bob"), "#927 read: a comment on bob's task gives NO push")
check(any(n["kind"] == "comment" and n["task_id"] == T1 for n in Bo.get(B + "/api/news").json()["items"]), "#927 read: ... the News item is still there")
T2 = task(Bo, "T2 bob", L)
clear()
comment(A, T2, f"<@{BOB}> please look")
check(len(to("t-bob")) == 1, "#927 read: a mention still pushes")
clear()
task(A, "T3 for carol", L, assignee_id=CAROL)
check(len(to("t-carol")) == 1, "#927 read: an assignment still pushes")

# ================================================================== owner changes it; per person; custom
r = A.put(tpl_url(L), json={"tpl": "work"})
check(r.ok and r.json()["own"]["tpl"] == "work" and r.json()["effective"]["tpl"] == "work", "#927: owner sets work " + r.text[:120])
T4 = task(Bo, "T4 bob", L)
clear()
comment(A, T4, "now with work")
check(len(to("t-bob")) == 1, "#927 work: the comment on bob's task pushes")
r = A.put(tpl_url(L), json={"tpl": "read", "user_id": CAROL})
check(r.ok and next(p for p in r.json()["people"] if p["user_id"] == CAROL)["own"]["tpl"] == "read", "#927: a template for carol only")
T5 = task(Ca, "T5 carol", L)
clear()
comment(A, T5, "carol is on read")
check(not to("t-carol"), "#927: the per-person template beats the list's (no push for carol)")
check(Ca.get(tpl_url(L)).json()["effective"]["tpl"] == "read" and Bo.get(tpl_url(L)).json()["effective"]["tpl"] == "work",
      "#927: carol read, bob work")
r = A.put(tpl_url(L), json={"tpl": "custom", "custom": {"mention": 1, "comment": 0}})
check(r.ok and r.json()["own"] == {"tpl": "custom", "custom": {"comment": 0, "mention": 1}}, "#927: custom stored " + r.text[:160])
T6 = task(Bo, "T6 bob", L)
clear()
comment(A, T6, "custom without comments")
check(not to("t-bob"), "#927 custom: an unticked event gives no push")
T6b = task(Bo, "T6b bob", L)
clear()
comment(A, T6b, f"<@{BOB}> ticked")
check(len(to("t-bob")) == 1, "#927 custom: a ticked event pushes")

# ---- due reminders follow it (bob on read: none; on work: one)
now = datetime.now(ZoneInfo("Europe/Berlin"))
if now.hour < 23 or now.minute < 50:
    due = (now + timedelta(minutes=2)).strftime("%H:%M")
    A.put(tpl_url(L), json={"tpl": "read", "user_id": BOB})
    clear()
    task(A, "R1 reminder", L, assignee_id=BOB, due=now.date().isoformat(), due_time=due, reminders="5")
    check(not [p for p in to("t-bob", 3.5) if p["title"] == "R1 reminder"], "#927 read: the due reminder gives no push")
    A.put(tpl_url(L), json={"tpl": "work", "user_id": BOB})
    clear()
    task(A, "R2 reminder", L, assignee_id=BOB, due=now.date().isoformat(), due_time=due, reminders="5")
    check([p for p in to("t-bob", 3.5) if p["title"] == "R2 reminder"], "#927 work: the due reminder pushes")
    A.put(tpl_url(L), json={"tpl": None, "user_id": BOB})

# ---- who may change it
check(Bo.put(tpl_url(L), json={"tpl": "all"}).status_code == 403, "#927: a member cannot change it (403)")
check(Da.get(tpl_url(L)).status_code == 404 and Da.put(tpl_url(L), json={"tpl": "all"}).status_code == 404, "#927: a stranger gets 404")
check(A.get(tpl_url(999999)).status_code == 404, "#927: an unknown list 404")
check(A.put(tpl_url(L), json={"tpl": "loud"}).status_code == 400, "#927: an unknown template 400")
check(A.put(tpl_url(L), json={"tpl": "custom", "custom": {"usage": 1}}).status_code == 400, "#927: a custom event that is not offered 400")
check(A.put(tpl_url(L), json={"tpl": "work", "user_id": DAVE}).status_code == 404, "#927: a person not in the list 404")
check(A.put(tpl_url(L), json={"tpl": None}).json()["own"] is None, "#927: null = back to the folder / default")

# ---- agents read it, never change it
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
check(r.ok, "setup: agent " + r.text[:100])
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
r = requests.get(V + f"/lists/{L}/notify-template", headers=AGH)
check(r.ok and r.json()["effective"]["tpl"] == "read" and "people" not in r.json(), "#927: the agent reads what limits it via /api/v1 " + r.text[:120])
check(requests.put(V + f"/lists/{L}/notify-template", headers=AGH, json={"tpl": "all"}).status_code in (404, 405), "#927: no v1 route to change it")
check(not requests.put(tpl_url(L), headers={**AGH, **H}, json={"tpl": "all"}).ok, "#927: the agent's token cannot change it in the app API")
check(all(p["user_id"] != AG for p in A.get(tpl_url(L)).json()["people"]), "#927: agents are not offered a template per person")
L3 = A.post(B + "/api/lists", json={"name": "Agent's list"}).json()["id"]
assert A.put(B + f"/api/lists/{L3}/members", json={"user_id": BOB, "role": "edit"}).ok
dbx("UPDATE lists SET owner_id=? WHERE id=?", (AG, L3), write=True)
check(Bo.get(tpl_url(L3)).json()["effective"]["tpl"] == "all", "#927: a list owned by an agent limits nobody (no person could choose)")
tok = A.post(B + "/api/me/tokens", json={"name": "own", "scopes": ["read"]}).json()["token"]
r = requests.get(V + f"/lists/{L}/notify-template", headers={"Authorization": "Bearer " + tok})
check(r.ok and "people" in r.json(), "#927: the owner's own token reads the whole setting")
spec = requests.get(V + "/openapi.json").json()
check("/lists/{id}/notify-template" in spec["paths"] and "get" in spec["paths"]["/lists/{id}/notify-template"]
      and "put" not in spec["paths"]["/lists/{id}/notify-template"], "#927: OpenAPI documents it read only")

# ================================================================== folders
F1 = A.post(B + "/api/lists", json={"name": "In team", "folder": "Team"}).json()["id"]
r = A.put(B + "/api/folders/people", json={"folder": "Team", "user_id": BOB, "role": "edit"})
check(r.ok and state_list(Bo, F1) is not None, "setup: folder Team shared with bob " + r.text[:100])
FU = B + "/api/folders/notify-template"
j = A.get(FU, params={"folder": "Team"}).json()
check(j["own"] is None and j["effective"]["tpl"] == "read" and [p["user_id"] for p in j["people"]] == [BOB] and j["lists"] == 1,
      "#927 folder: info " + json.dumps(j)[:200])
r = A.put(FU, json={"folder": "Team", "tpl": "work"})
check(r.ok and r.json()["own"]["tpl"] == "work", "#927 folder: owner sets work")
jb = Bo.get(tpl_url(F1)).json()
check(jb["effective"]["tpl"] == "work", "#927 folder: the list in it follows the folder " + json.dumps(jb)[:120])
check(A.get(tpl_url(F1)).json()["inherited"] == {"tpl": "work", "custom": {}, "folder": "Team"}, "#927 folder: the list shows what it inherits")
A.put(tpl_url(F1), json={"tpl": "all"})
check(Bo.get(tpl_url(F1)).json()["effective"]["tpl"] == "all", "#927 folder: the list's own template overrides the folder")
check(A.get(FU, params={"folder": "Team"}).json()["lists_own"] == 1, "#927 folder: one list with its own template")
A.put(FU, json={"folder": "Team", "reset_lists": True})
check(Bo.get(tpl_url(F1)).json()["effective"]["tpl"] == "work" and A.get(tpl_url(F1)).json()["own"] is None,
      "#927 folder: reset_lists -> the lists follow the folder again")
A.put(FU, json={"folder": "Team", "tpl": "read", "user_id": BOB})
check(Bo.get(tpl_url(F1)).json()["effective"]["tpl"] == "read", "#927 folder: a template per person of the folder")
check(A.put(FU, json={"folder": "Team", "tpl": "read", "user_id": CAROL}).status_code == 404, "#927 folder: a person the folder is not shared with 404")
check(Bo.get(FU, params={"folder": "Team"}).status_code == 404 and Bo.put(FU, json={"folder": "Team", "tpl": "all"}).status_code == 404,
      "#927 folder: someone else's folder 404")
check(A.post(B + "/api/folders/rename", json={"old": "Team", "new": "Crew"}).ok, "setup: rename Team -> Crew")
j = A.get(FU, params={"folder": "Crew"}).json()
check(j["own"] and j["own"]["tpl"] == "work" and j["people"][0]["own"]["tpl"] == "read", "#927 folder: the templates went along with the rename")
check(Bo.get(tpl_url(F1)).json()["effective"]["tpl"] == "read", "#927 folder: ... and still apply")

# ================================================================== #834 client addresses
r = A.get(B + "/api/admin/client-ip")
j = r.json() if r.ok else {}
check(r.ok and j["ip"] and j["private"] is True, "#834: Your IP as the server sees it (the docker gateway here) " + r.text[:160])
check(j.get("warning") and j["warning"]["accounts"] >= 3 and j["warning"]["ip"] == j["ip"],
      "#834: many accounts from one private address -> warning " + json.dumps(j.get("warning")))
check(Bo.get(B + "/api/admin/client-ip").status_code == 403, "#834: admins only")
logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True).stdout + \
    subprocess.run(["docker", "logs", NAME], capture_output=True, text=True).stderr
check("client addresses do not arrive" in logs, "#834: the warning is in the server log")
check(dbx("SELECT COUNT(DISTINCT user_id) FROM login_ips")[0][0] >= 4, "#834: private sign-in addresses remembered")

# ================================================================== migration (once) + the one-time question
check(A.get(B + "/api/state").json()["notif_ask"] == [], "#927: no question on a new server")
dbx("DELETE FROM list_notif", write=True)
dbx("DELETE FROM folder_notif", write=True)
dbx("DELETE FROM settings WHERE key='migr_notiftpl2330'", write=True)
start(keep=True)
A, Bo = sess("alice"), sess("bob")
rows = dbx("SELECT list_id, user_id, tpl FROM list_notif ORDER BY list_id")
check((L, 0, "all") in rows and not any(r[0] == F1 for r in rows), "#927 migration: the shared list got all, the list in the shared folder not " + str(rows))
check(dbx("SELECT owner_id, folder, user_id, tpl FROM folder_notif") == [(1, "Crew", 0, "all")], "#927 migration: the shared folder got all")
ask = A.get(B + "/api/state").json()["notif_ask"]
check({(x["kind"], x.get("id") or x.get("folder")) for x in ask} == {("folder", "Crew"), ("list", L)}, "#927 migration: the owner is asked once " + json.dumps(ask))
check(Bo.get(B + "/api/state").json()["notif_ask"] == [], "#927 migration: members are not asked")
check(Bo.get(tpl_url(L)).json()["effective"]["tpl"] == "all" and Bo.get(tpl_url(F1)).json()["effective"]["tpl"] == "all",
      "#927 migration: nothing changes silently (all)")
check(A.post(B + "/api/notify-templates/asked", json={}).ok and A.get(B + "/api/state").json()["notif_ask"] == [], "#927: answered -> no question")

# ================================================================== rollback safety
cols = [r[1] for r in dbx("PRAGMA table_info(lists)")]
check(not any("notif" in c for c in cols) and not any("notif" in r[1] for r in dbx("PRAGMA table_info(list_members)")),
      "rollback: lists / list_members unchanged")
check([r[1] for r in dbx("PRAGMA table_info(list_notif)")] == ["list_id", "user_id", "tpl", "custom", "updated_at"]
      and [r[1] for r in dbx("PRAGMA table_info(login_ips)")] == ["ip", "user_id", "at"], "rollback: only new tables")
r = A.get(B + "/api/export.json")
exp = r.json() if r.ok else {}
check("list_notif" in exp and "folder_notif" in exp, "#927: the account export carries the templates")

print(f"p2330_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
