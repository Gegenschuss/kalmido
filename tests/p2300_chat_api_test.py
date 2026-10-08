#!/usr/bin/env python3
"""2.30.0 API tests (agent chat + listening in), own container (start.sh).
 - #1037 answer buttons expire: a newer message of the agent or of the person makes older open buttons expire
   (choice_state expired, a press answers 409 "This suggestion is no longer current"), pressed ones stay answered; the
   agent withdraws buttons (POST /api/v1/agent/chats/{uid}/messages/{mid}/withdraw); v1 and the agent's chat list carry
   choice_state
 - #1041 permission questions: permission: true adds Allow / Deny (allow / deny ids of 2.28 hosts count too), expires_in;
   a button press sends chat_choice (approval, via button) AND the reaction event a 👍 sends; a 👍 / 👎 answers it the other
   way round (choice via reaction, chat_choice too); a permission question does not expire with newer messages; after
   expires_at a press is 409 and a 👍 no approval; withdraw with an outcome
 - #1034 listening in by project type: software lists -> every agent listens in (task_added for created AND moved tasks,
   every comment); other lists only @mention / assignment; a switch per list (listen_agent_ids, listen_default), a change
   of the project type starts over, a folder setting agent_listen, tidy also for moved tasks, tasks_added only to
   listeners; the migration keeps who listened before
usage: p2300_chat_api_test.py <datadir>"""
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


def lists_of(s):
    return {l["id"]: l for l in s.get(B + "/api/state").json()["lists"]}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = sess("bob")
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Chat home", "org_id": ORG}).json()
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"})


def events(since):
    return requests.get(V + f"/agent/events?since={since}&limit=200", headers=CLH).json()


def latest():
    return requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]


def agent_say(body, **kw):
    r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": body, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def press(mid, ids):
    return A.post(B + f"/api/agents/{CL}/chat/{mid}/choice", json={"choice_ids": ids})


def msgs():
    return {m["id"]: m for m in A.get(B + f"/api/agents/{CL}/chat").json()["messages"]}


# ================================================================== #1037 answer buttons expire
m1 = agent_say("Shall I plan 2.30 now?", choices=[{"id": "yes", "label": "Plan 2.30"}, {"id": "no", "label": "Later"}])
check(m1["choice_state"] == "open", "#1037: a new question's buttons are open " + str(m1.get("choice_state")))
m2 = agent_say("Or rather 2.31 first?", choices=[{"id": "a", "label": "2.31 first"}, {"id": "b", "label": "Stay with 2.30"}])
ms = msgs()
check(ms[m1["id"]]["choice_state"] == "expired" and ms[m2["id"]]["choice_state"] == "open", "#1037: a newer agent message makes the older buttons expire " + str((ms[m1["id"]]["choice_state"], ms[m2["id"]]["choice_state"])))
r = press(m1["id"], ["yes"])
check(r.status_code == 409 and "no longer current" in r.json().get("error", ""), "#1037: a press on expired buttons -> 409 'no longer current' " + r.text[:120])
cur = latest()
r = press(m2["id"], ["a"])
check(r.ok and r.json()["choice_state"] == "answered", "#1037: the newest buttons answer " + r.text[:120])
ev = events(cur)["data"]
check([e["event"] for e in ev] == ["chat_choice"] and ev[0]["data"]["choice_ids"] == ["a"] and "permission" not in ev[0]["data"], "#1037: one chat_choice, no permission fields " + str([e["event"] for e in ev]))
m3 = agent_say("Which colour?", choices=["red", "blue"])
r = A.post(B + f"/api/agents/{CL}/chat", json={"body": "neither, green please"})
check(r.status_code == 201, "#1037: the person writes " + r.text[:80])
ms = msgs()
check(ms[m3["id"]]["choice_state"] == "expired" and ms[m2["id"]]["choice_state"] == "answered", "#1037: my own message makes the open buttons expire, answered ones stay answered")
check(press(m3["id"], ["red"]).status_code == 409, "#1037: ... and a press on them is refused (an old tab, an offline outbox)")
# v1: the agent's view and the person's token
j = requests.get(V + "/agent/chats?since=0", headers=CLH).json()
st = {m["id"]: m["choice_state"] for m in j["data"]}
check(st.get(m1["id"]) == "expired" and st.get(m2["id"]) == "answered" and st.get(m3["id"]) == "expired", "#1037: the agent's chat list carries choice_state " + str(st))
# withdraw
m4 = agent_say("Shall I tidy the inbox?", choices=["Yes", "No"])
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{m4['id']}/withdraw", headers=CLH, json={})
check(r.ok and r.json()["choice_state"] == "withdrawn", "#1037: the agent withdraws its buttons " + r.text[:120])
check(press(m4["id"], ["Yes"]).status_code == 409, "#1037: a press on withdrawn buttons -> 409")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{m4['id']}/withdraw", headers=CLH, json={"outcome": "allowed"}).status_code == 400, "#1037: an outcome only on permission questions")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{m2['id']}/withdraw", headers=CLH, json={}).status_code == 409, "#1037: an answered question cannot be withdrawn")
check(requests.post(V + f"/agent/chats/{BOB}/messages/{m4['id']}/withdraw", headers=CLH, json={}).status_code == 404, "#1037: ... nor one of another conversation")
check(A.post(V + f"/agent/chats/{ALICE}/messages/{m4['id']}/withdraw", json={}).status_code in (401, 403, 404), "#1037: a person cannot withdraw (agents only)")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{m4['id']}/withdraw", headers=CLH, json={"x": 1}).status_code == 400, "#1037: unknown fields are refused")
# a person's token presses through v1 (409 on expired too)
r = A.post(B + "/api/me/tokens", json={"name": "phone", "scopes": ["read", "comments"]})
AT = {"Authorization": "Bearer " + r.json()["token"]} if r.ok else {}
m5 = agent_say("Ship it?", choices=["Ship", "Wait"])
agent_say("Status: the build runs.")
r = requests.post(V + f"/agents/{CL}/chat/{m5['id']}/choice", headers=AT, json={"choice_ids": ["Ship"]})
check(r.status_code == 409, "#1037: v1 press on expired buttons -> 409 " + str(r.status_code))
# the OpenAPI document knows the new route + fields
spec = requests.get(V + "/openapi.json", headers=CLH).json()
check("/agent/chats/{id}/messages/{mid}/withdraw" in spec["paths"], "#1037: withdraw is in the OpenAPI document")

# ================================================================== #1041 permission questions
cur = latest()
p1 = agent_say("May I run this?\n```\n./deploy.sh staging\n```", permission=True, expires_in=600)
ch = p1["choices"]
check(ch["permission"] is True and [c["id"] for c in ch["choices"]] == ["allow", "deny"] and ch.get("expires_at"), "#1041: permission: true adds Allow / Deny and expires_at " + str(ch))
agent_say("Meanwhile: the tests are green.")
A.post(B + f"/api/agents/{CL}/chat", json={"body": "ok thanks"})
ms = msgs()
check(ms[p1["id"]]["choice_state"] == "open", "#1041: a permission question stays open while newer messages come")
pre = agent_say("Pick one", choices=["x", "y"])
p_mid = agent_say("May I delete the cache?", permission=True)
ms = msgs()
check(ms[pre["id"]]["choice_state"] == "open", "#1041: a permission question does not make older buttons expire")
cur = latest()
r = press(p1["id"], ["allow"])
check(r.ok and r.json()["choice"]["ids"] == ["allow"] and r.json()["choice"].get("via") == "button", "#1041: Allow answers " + r.text[:160])
ev = events(cur)["data"]
cc = [e for e in ev if e["event"] == "chat_choice"]
rx = [e for e in ev if e["event"] == "reaction"]
check(cc and cc[0]["data"]["permission"] is True and cc[0]["data"]["approval"] == "approved" and cc[0]["data"]["via"] == "button", "#1041: chat_choice with permission + approval " + str(cc)[:200])
check(rx and rx[0]["data"]["approval"] == "approved" and rx[0]["data"]["chat_message"]["id"] == p1["id"] and rx[0]["data"]["reaction"]["emoji"] == "up" and rx[0]["data"].get("via") == "button",
      "#1041: ... and the reaction event a 👍 sends (hosts that listen for 👍 keep working) " + str(rx)[:200])
check(press(p1["id"], ["deny"]).status_code == 409, "#1041: answered once")
# a 👍 / 👎 answers the other way round
cur = latest()
r = A.post(B + f"/api/agents/{CL}/chat/{p_mid['id']}/reactions", json={"emoji": "down"})
check(r.ok and r.json()["approval"] == "rejected", "#1041: 👎 on a permission question is a rejection " + r.text[:120])
m = msgs()[p_mid["id"]]
check(m["choice"] and m["choice"]["ids"] == ["deny"] and m["choice"]["via"] == "reaction" and m["choice_state"] == "answered", "#1041: ... and answers it like the Deny button " + str(m["choice"]))
ev = events(cur)["data"]
check(sorted(e["event"] for e in ev) == ["chat_choice", "reaction"] and all(e["data"]["approval"] == "rejected" for e in ev), "#1041: ... chat_choice (via reaction) + reaction " + str([(e["event"], e["data"].get("via")) for e in ev]))
check(press(p_mid["id"], ["allow"]).status_code == 409, "#1041: a button after the 👎 is refused")
# 2.28 / 2.29 hosts: buttons allow / deny count as a permission question
old = agent_say("Darf ich das ausführen?", choices=[{"id": "allow", "label": "Erlauben", "style": "primary"}, {"id": "deny", "label": "Ablehnen", "style": "danger"}])
check(old["choices"].get("permission") is True and old["asks"] is True, "#1041: allow / deny ids of older hosts count as a permission question")
check(requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "x", "permission": True, "choices": ["a", "b"]}).status_code == 400, "#1041: permission with other buttons is refused")
check(requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "x", "expires_in": 60}).status_code == 400, "#1041: expires_in without a permission question is refused")
check(requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "x", "permission": True, "expires_in": 3}).status_code == 400, "#1041: expires_in below 10 s is refused")
# expired
p3 = agent_say("May I restart the worker?", permission=True, expires_in=10)
dbx("UPDATE agent_chat SET choices=json_set(choices, '$.expires_at', '2000-01-01T00:00:00.000+00:00') WHERE id=?", (p3["id"],), write=True)
m = msgs()[p3["id"]]
check(m["choice_state"] == "expired", "#1041: after expires_at the question is expired " + str(m["choice_state"]))
check(press(p3["id"], ["allow"]).status_code == 409, "#1041: ... a press is 409")
cur = latest()
r = A.post(B + f"/api/agents/{CL}/chat/{p3['id']}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["approval"] is None, "#1041: ... a 👍 is no go-ahead any more " + r.text[:120])
ev = events(cur)["data"]
check(not any(e["event"] == "chat_choice" for e in ev) and all(e["data"].get("approval") is None for e in ev), "#1041: ... and sends no approval " + str([(e["event"], e["data"].get("approval")) for e in ev]))
# the host decided another way: withdraw with an outcome
p4 = agent_say("May I push?", permission=True)
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{p4['id']}/withdraw", headers=CLH, json={"outcome": "allowed"})
check(r.ok and r.json()["choices"]["outcome"] == "allowed" and r.json()["choice_state"] == "answered", "#1041: withdraw with outcome allowed " + r.text[:160])
p5 = agent_say("May I prune?", permission=True)
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{p5['id']}/withdraw", headers=CLH, json={"outcome": "expired"})
check(r.ok and r.json()["choice_state"] == "expired", "#1041: withdraw with outcome expired")
check(requests.post(V + f"/agent/chats/{ALICE}/messages/{p5['id']}/withdraw", headers=CLH, json={"outcome": "maybe"}).status_code in (400, 409), "#1041: unknown outcomes are refused")

# ================================================================== #1034 listening in by project type
SW = A.post(B + "/api/lists", json={"name": "App dev", "ptype": "software", "org_id": ORG}).json()
AG = A.post(B + "/api/lists", json={"name": "Campaign", "ptype": "agency", "org_id": ORG}).json()
PL = A.post(B + "/api/lists", json={"name": "Plain", "org_id": ORG}).json()
for l in (SW, AG, PL):
    A.put(B + f"/api/lists/{l['id']}/agent", json={"agent_id": CL})
    A.put(B + f"/api/lists/{l['id']}/members", json={"user_id": BOB, "role": "edit"})
    A.patch(B + f"/api/lists/{l['id']}", json={"agent_members": True})  # 2.26: Bob's comments / mentions may reach the agent
L = lists_of(A)
check(L[SW["id"]]["listen_agent_ids"] == [CL] and L[SW["id"]]["listen_default"] is True, "#1034: a software list: the agent listens in by default " + str((L[SW["id"]]["listen_agent_ids"], L[SW["id"]].get("listen_default"))))
check(L[AG["id"]]["listen_agent_ids"] == [] and L[AG["id"]]["listen_default"] is False and L[PL["id"]]["listen_agent_ids"] == [], "#1034: agency / plain lists: only via @")
v1l = {l["id"]: l for l in requests.get(V + "/lists", headers=CLH).json()["data"]}
check(v1l[SW["id"]]["listen_agent_ids"] == [CL] and v1l[SW["id"]]["listen_default"] is True, "#1034: v1 lists show listen_agent_ids + listen_default")
cur = latest()
t_sw = Bo.post(B + "/api/tasks", json={"title": "Login breaks on Safari", "list_id": SW["id"]}).json()["id"]
t_ag = Bo.post(B + "/api/tasks", json={"title": "Draft the flyer", "list_id": AG["id"]}).json()["id"]
t_pl = Bo.post(B + "/api/tasks", json={"title": "Buy paper", "list_id": PL["id"]}).json()["id"]
ev = events(cur)["data"]
added = {e["data"]["task"]["id"]: e for e in ev if e["event"] == "task_added"}
check(t_sw in added and added[t_sw]["data"]["how"] == "created", "#1034: a task created in a software list reaches the agent " + str(list(added)))
check(t_ag not in added and t_pl not in added, "#1034: ... in other lists not (only via @)")
check(added.get(t_sw) and added[t_sw]["data"]["list"]["project_type"] == "software" and added[t_sw]["data"]["list"]["listen_agent_ids"] == [CL], "#1034: the event's list carries project_type + listen_agent_ids")
cur = latest()
Bo.patch(B + f"/api/tasks/{t_pl}", json={"list_id": SW["id"]})
ev = events(cur)["data"]
check(any(e["event"] == "task_added" and e["data"]["task"]["id"] == t_pl and e["data"]["how"] == "moved" for e in ev), "#1034: a task moved into a software list reaches it (how: moved) " + str([e["event"] for e in ev]))
cur = latest()
Bo.post(B + f"/api/tasks/{t_sw}/comments", json={"body": "Also on iPad"})
Bo.post(B + f"/api/tasks/{t_ag}/comments", json={"body": "Colours?"})
ev = events(cur)["data"]
cm = [e["data"]["task"]["id"] for e in ev if e["event"] == "comment"]
check(cm == [t_sw], "#1034: comments: every one in the software list, none in the agency list " + str(cm))
cur = latest()
Bo.post(B + f"/api/tasks/{t_ag}/comments", json={"body": f"<@{CL}> what do you think?"})
check(any(e["event"] == "mention" for e in events(cur)["data"]), "#1034: an @mention still reaches it in the agency list")
# the switch per list
r = A.patch(B + f"/api/lists/{AG['id']}", json={"listen_agent_ids": [CL]})
check(r.ok and lists_of(A)[AG["id"]]["listen_agent_ids"] == [CL], "#1034: listening switched on in an agency list " + r.text[:80])
cur = latest()
t2 = Bo.post(B + "/api/tasks", json={"title": "Second flyer", "list_id": AG["id"]}).json()["id"]
check(any(e["event"] == "task_added" and e["data"]["task"]["id"] == t2 for e in events(cur)["data"]), "#1034: ... then new tasks reach it there too")
r = A.patch(B + f"/api/lists/{SW['id']}", json={"listen_agent_ids": []})
check(r.ok and lists_of(A)[SW["id"]]["listen_agent_ids"] == [], "#1034: switched off in a software list")
cur = latest()
Bo.post(B + "/api/tasks", json={"title": "Quiet one", "list_id": SW["id"]})
check(not any(e["event"] == "task_added" for e in events(cur)["data"]), "#1034: ... then nothing arrives without @")
check(Bo.patch(B + f"/api/lists/{SW['id']}", json={"listen_agent_ids": [CL]}).status_code == 403, "#1034: a member cannot switch it")
check(requests.patch(V + f"/lists/{SW['id']}", headers=CLH, json={"listen_agent_ids": [CL]}).status_code == 403, "#1034: the agent cannot switch it")
# a change of the project type starts over with its default
r = A.patch(B + f"/api/lists/{PL['id']}", json={"ptype": "software"})
check(r.ok and lists_of(A)[PL["id"]]["listen_agent_ids"] == [CL], "#1034: a plain list becomes software -> the agent listens in " + str(lists_of(A)[PL["id"]]["listen_agent_ids"]))
r = A.patch(B + f"/api/lists/{AG['id']}", json={"ptype": "private"})
check(r.ok and lists_of(A)[AG["id"]]["listen_agent_ids"] == [], "#1034: an agency list -> private: back to the default (off)")
r = A.patch(B + f"/api/lists/{AG['id']}", json={"ptype": "software", "listen_agent_ids": []})
check(r.ok and lists_of(A)[AG["id"]]["listen_agent_ids"] == [], "#1034: switching the type and listening in one request keeps the explicit choice")
A.patch(B + f"/api/lists/{AG['id']}", json={"ptype": "agency"})
# tidy also for moved tasks (separate switch, default off)
check(lists_of(A)[SW["id"]]["agent_tidy"] == "off", "#1034: tidying stays off by default in software lists")
A.patch(B + f"/api/lists/{AG['id']}", json={"agent_tidy": "suggest"})
cur = latest()
t3 = Bo.post(B + "/api/tasks", json={"title": "Move me", "list_id": PL["id"]}).json()["id"]
time.sleep(1)
cur = latest()
Bo.patch(B + f"/api/tasks/{t3}", json={"list_id": AG["id"]})
time.sleep(2)
ev = events(cur)["data"]
check(any(e["event"] == "tidy" and e["data"]["task"]["id"] == t3 for e in ev), "#1034: tidy on: a moved-in task gets the tidy event " + str([e["event"] for e in ev]))
check(not any(e["event"] == "task_added" for e in ev), "#1034: ... tidying is independent of listening (no task_added in a list that does not listen)")
A.patch(B + f"/api/lists/{AG['id']}", json={"agent_tidy": "off"})
# folder setting agent_listen
F1 = A.post(B + "/api/lists", json={"name": "F1", "folder": "Agency", "org_id": ORG}).json()
A.put(B + f"/api/lists/{F1['id']}/agent", json={"agent_id": CL})
r = A.put(B + "/api/folders/props", json={"folder": "Agency", "props": {"agent_listen": True}})
check(r.ok and lists_of(A)[F1["id"]]["listen_agent_ids"] == [CL], "#1034: the folder setting 'agent listens in' reaches its lists " + r.text[:120])
F2 = A.post(B + "/api/lists", json={"name": "F2", "folder": "Agency", "org_id": ORG}).json()
A.put(B + f"/api/lists/{F2['id']}/agent", json={"agent_id": CL})
check(lists_of(A)[F2["id"]]["listen_agent_ids"] == [CL], "#1034: ... a new list in the folder too (also its agent connected later)")
A.patch(B + f"/api/lists/{F2['id']}", json={"listen_agent_ids": []})
own = lists_of(A)[F2["id"]].get("folder_own") or ""
check("agent_listen" in own, "#1034: a list switched on its own differs from the folder " + str(own))
check(A.put(B + "/api/folders/props", json={"folder": "Agency", "props": {"agent_listen": "yes"}}).status_code == 400, "#1034: agent_listen takes true / false")
# a bulk only to listeners
cur = latest()
for i in range(8):
    Bo.post(B + "/api/tasks", json={"title": f"bulk sw {i}", "list_id": PL["id"]})   # PL is software now (listening)
    Bo.post(B + "/api/tasks", json={"title": f"bulk ag {i}", "list_id": AG["id"]})   # agency, not listening
time.sleep(18)
ev = events(cur)["data"]
bulk = [e for e in ev if e["event"] == "tasks_added"]
check(len(bulk) == 1 and bulk[0]["data"]["list_id"] == PL["id"], "#1034: a bulk comes as tasks_added only from the listening list " + str([(e["data"]["list_id"], e["data"]["count"]) for e in bulk]))
check(not any(e["event"] == "task_added" and e["data"]["list"]["id"] == AG["id"] for e in ev), "#1034: ... nothing from the other")

# ================================================================== #1034 the migration keeps who listened before
# a 2.29 database: agent_listen in the old form (NULL = the tidy agent while tidying is on; "3" = these read every comment)
M1 = A.post(B + "/api/lists", json={"name": "Old tidy", "org_id": ORG}).json()
M2 = A.post(B + "/api/lists", json={"name": "Old explicit sw", "ptype": "software", "org_id": ORG}).json()
M3 = A.post(B + "/api/lists", json={"name": "Old default sw", "ptype": "software", "org_id": ORG}).json()
M4 = A.post(B + "/api/lists", json={"name": "Old plain", "org_id": ORG}).json()
for l in (M1, M2, M3, M4):
    A.put(B + f"/api/lists/{l['id']}/agent", json={"agent_id": CL})
dbx("UPDATE lists SET agent_listen=NULL, agent_tidy='suggest' WHERE id=?", (M1["id"],), write=True)
dbx("UPDATE lists SET agent_listen='' WHERE id=?", (M2["id"],), write=True)   # 2.29: "nobody" chosen explicitly
dbx("UPDATE lists SET agent_listen=NULL WHERE id IN (?, ?)", (M3["id"], M4["id"]), write=True)
dbx("DELETE FROM settings WHERE key='migr_listen2300'", write=True)
subprocess.run(["docker", "restart", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], check=True, stdout=subprocess.DEVNULL)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
A = sess("alice")
L = lists_of(A)
check(L[M1["id"]]["listen_agent_ids"] == [CL], "#1034 migration: the tidy agent that listened by the old default keeps listening " + str(L[M1["id"]]["listen_agent_ids"]))
check(L[M2["id"]]["listen_agent_ids"] == [], "#1034 migration: an explicit 'nobody' in a software list stays")
check(L[M3["id"]]["listen_agent_ids"] == [CL], "#1034 migration: a software list on the default: its agent listens in")
check(L[M4["id"]]["listen_agent_ids"] == [], "#1034 migration: a plain list on the default: nobody")
check(dbx("SELECT value FROM settings WHERE key='migr_listen2300'") == [("1",)], "#1034 migration: runs once")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
