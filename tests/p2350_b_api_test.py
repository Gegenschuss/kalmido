#!/usr/bin/env python3
"""2.35.0 API tests, part B: approval requests in the agent chat (#1103), own container (start.sh).
 - POST /api/v1/agent/chats/{uid} with approval {title, what?, yes_label?, no_label?} (+ expires_in): buttons yes (primary)
   / no, choices.approval {title, what}; body may be left out (the title is the text); bad shapes 400 (no title, too long,
   unknown keys, together with choices / multi / permission); multipart with approval as a JSON string
 - it stays open while newer messages come (and does not make other buttons expire); the app's agent list carries
   approvals_open (only for the person of the chat), the chat carries approvals_open (also older than the loaded page)
 - only the person of the chat answers: another person 404, the agent's own token never; a press sends chat_choice with
   approval approved / rejected + approval_request; a second press 409; a 👎 on the open card answers it (via reaction,
   chat_choice + reaction); after expires_at: expired, a press 409; withdraw with an outcome
 - push "Approval needed: <agent>" (notification row approval, on by default); switched off: the plain chat push
 - no schema change (choices is json in an existing column): the rollback image 2.34 keeps running
usage: p2350_b_api_test.py <datadir>"""
import json
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
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com",
                                   "ntfy_topic": "t-bob"})
BOB = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"})
CAROL = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
Bo.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Chat home", "org_id": ORG}).json()
assert A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "edit"}).ok  # the person first (no agent bridge, #919)
assert A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"}).ok
assert A.patch(B + f"/api/lists/{W['id']}", json={"agent_members": True}).ok  # members may chat with the list's agents (#928)


def events(since):
    return requests.get(V + f"/agent/events?since={since}&limit=200", headers=CLH).json()


def latest():
    return requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]


def say(uid=None, **kw):
    return requests.post(V + f"/agent/chats/{uid or ALICE}", headers=CLH, json=kw)


def press(s, mid, ids):
    return s.post(B + f"/api/agents/{CL}/chat/{mid}/choice", json={"choice_ids": ids})


def msgs(s=A):
    return {m["id"]: m for m in s.get(B + f"/api/agents/{CL}/chat").json()["messages"]}


def open_n(s=A):
    a = [x for x in s.get(B + "/api/agents").json()["agents"] if x["id"] == CL]
    return a[0].get("approvals_open") if a else None


# ================================================================== shape
r = say(approval={"title": "Publish release 2.35.0", "what": "The new version goes live for everyone"}, expires_in=7200)
check(r.status_code == 201, "an approval request is created " + r.text[:200])
m1 = r.json()
ch = m1.get("choices") or {}
check(ch.get("approval", {}).get("title") == "Publish release 2.35.0" and ch["approval"].get("what") == "The new version goes live for everyone",
      "choices.approval carries title + what " + str(ch)[:200])
check([c["id"] for c in ch.get("choices", [])] == ["yes", "no"] and ch["choices"][0].get("style") == "primary", "buttons yes (primary) / no " + str(ch.get("choices")))
check(ch["approval"].get("std") == 1 and not ch.get("permission") and ch.get("expires_at"), "default labels marked std, not a permission question, expires_at set")
check(m1["body"] == "Publish release 2.35.0" and m1["choice_state"] == "open" and m1["asks"], "without body the title is the text; open; asks " + str((m1["body"], m1["choice_state"])))
for bad, why in ((None, "no title"), ({"what": "x"}, "missing title"), ({"title": " "}, "empty title"), ({"title": "x" * 201}, "title too long"),
                 ({"title": "x", "what": "y" * 1001}, "what too long"), ({"title": "x", "foo": 1}, "unknown key"), ({"title": "x", "yes_label": 3}, "label not text"),
                 ("not json", "a string that is no json"), ([1], "a list")):
    if bad is None:
        continue
    r = say(approval=bad)
    check(r.status_code == 400, f"approval with {why} -> 400 " + str(r.status_code))
for extra in ({"choices": ["a", "b"]}, {"multi": True}, {"permission": True}):
    r = say(approval={"title": "x"}, **extra)
    check(r.status_code == 400, f"approval together with {list(extra)[0]} -> 400 " + str(r.status_code))
check(say(approval={"title": "x"}, expires_in=5).status_code == 400, "expires_in below 10 s -> 400")
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, data={"body": "Details in the file", "approval": json.dumps({"title": "Send the offer", "yes_label": "Send", "no_label": "Hold"})},
                  files={"file": ("offer.txt", b"offer text", "text/plain")})
check(r.status_code == 201 and r.json()["choices"]["approval"]["title"] == "Send the offer" and [c["label"] for c in r.json()["choices"]["choices"]] == ["Send", "Hold"]
      and "std" not in r.json()["choices"]["approval"] and len(r.json()["attachments"]) == 1, "multipart: approval as a JSON string with own labels + a file " + r.text[:200])
m2 = r.json()

# ================================================================== stays open; counted; pinned
q = say(body="Which colour?", choices=["red", "blue"]).json()
say(body="Status: the build runs.")
ms = msgs()
check(ms[m1["id"]]["choice_state"] == "open" and ms[m2["id"]]["choice_state"] == "open", "newer messages do not expire an approval request")
check(ms[q["id"]]["choice_state"] == "expired", "... while normal buttons still expire with newer messages")
q2 = say(body="Plan it now?", choices=["Now", "Later"]).json()
say(approval={"title": "Delete the old branch"})
ms = msgs()
check(ms[q2["id"]]["choice_state"] == "open", "an approval request does not make the open buttons before it expire " + str(ms[q2["id"]]["choice_state"]))
check(open_n() == 3, "the agent list carries approvals_open for the person of the chat " + str(open_n()))
check(open_n(Bo) == 0, "... another person who shares a list with the agent sees 0 " + str(open_n(Bo)))
j = A.get(B + f"/api/agents/{CL}/chat?limit=1").json()
check([x["id"] for x in j.get("approvals_open", [])][:2] == [m1["id"], m2["id"]] and len(j["messages"]) == 1, "the chat returns the open approvals also beyond the loaded page "
      + str([x["id"] for x in j.get("approvals_open", [])]))

# ================================================================== who answers
check(press(Bo, m1["id"], ["yes"]).status_code == 404, "another person cannot answer (404)")
check(press(Ca, m1["id"], ["yes"]).status_code in (403, 404), "a stranger cannot answer")
r = requests.post(B + f"/api/agents/{CL}/chat/{m1['id']}/choice", headers={**CLH, **H}, json={"choice_ids": ["yes"]})
check(r.status_code in (401, 403, 404), "the agent's own token cannot answer " + str(r.status_code))
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{m1['id']}/reactions", headers=CLH, json={"emoji": "up"})
check(dbx("SELECT choice FROM agent_chat WHERE id=?", (m1["id"],))[0][0] is None, "a 👍 of the agent approves nothing")
check(press(A, m1["id"], ["maybe"]).status_code == 400, "an unknown answer id -> 400")
cur = latest()
r = press(A, m1["id"], ["yes"])
check(r.ok and r.json()["choice_state"] == "answered" and r.json()["choice"]["ids"] == ["yes"] and r.json()["choice"]["user_id"] == ALICE,
      "the person approves " + r.text[:200])
ev = [e for e in events(cur)["data"] if e["event"] == "chat_choice"]
d = ev[0]["data"] if ev else {}
check(len(ev) == 1 and d.get("approval") == "approved" and d.get("approval_request") == {"title": "Publish release 2.35.0", "what": "The new version goes live for everyone"}
      and d.get("via") == "button" and d.get("choice_ids") == ["yes"] and d.get("user", {}).get("id") == ALICE and "permission" not in d,
      "the agent gets chat_choice with approval approved + approval_request " + str(d)[:300])
check(press(A, m1["id"], ["no"]).status_code == 409, "a second press -> 409")
check(open_n() == 2, "approvals_open counts down " + str(open_n()))
cur = latest()
r = A.post(B + f"/api/agents/{CL}/chat/{m2['id']}/reactions", json={"emoji": "down"})
check(r.ok and r.json().get("approval") == "rejected", "a 👎 on the open card rejects it " + r.text[:160])
evs = events(cur)["data"]
cc = [e["data"] for e in evs if e["event"] == "chat_choice"]
check(len(cc) == 1 and cc[0]["approval"] == "rejected" and cc[0]["via"] == "reaction" and cc[0]["choice_ids"] == ["no"], "... chat_choice rejected via reaction " + str(cc)[:200])
check(any(e["event"] == "reaction" and e["data"].get("approval") == "rejected" for e in evs), "... and the reaction event with approval rejected")
check(msgs()[m2["id"]]["choice_state"] == "answered", "the card is answered")

# ================================================================== time limit, withdraw
m3 = say(approval={"title": "Restart the worker"}, expires_in=60).json()
c3 = json.loads(dbx("SELECT choices FROM agent_chat WHERE id=?", (m3["id"],))[0][0])
c3["expires_at"] = "2020-01-01T00:00:00.000Z"
dbx("UPDATE agent_chat SET choices=? WHERE id=?", (json.dumps(c3), m3["id"]), write=True)
check(msgs()[m3["id"]]["choice_state"] == "expired", "after expires_at: expired (silence is no yes)")
check(press(A, m3["id"], ["yes"]).status_code == 409, "... a press -> 409")
r = A.post(B + f"/api/agents/{CL}/chat/{m3['id']}/reactions", json={"emoji": "up"})
check(r.ok and not r.json().get("approval"), "... a 👍 is no approval any more " + r.text[:120])
op = [x for x in A.get(B + f"/api/agents/{CL}/chat").json()["approvals_open"]]
check(len(op) == 1 and op[0]["choices"]["approval"]["title"] == "Delete the old branch", "only the one still open is pinned " + str([x["id"] for x in op]))
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{op[0]['id']}/withdraw", headers=CLH, json={"outcome": "allowed"})
check(r.status_code == 400, "review N1: the agent cannot close an approval request as allowed (400) " + str(r.status_code))
r = requests.post(V + f"/agent/chats/{ALICE}/messages/{op[0]['id']}/withdraw", headers=CLH, json={"outcome": "denied"})
check(r.ok and r.json()["choices"].get("withdrawn_at") and r.json()["choices"]["outcome"] == "denied" and r.json()["choice"] is None,
      "withdraw with the outcome denied on an approval request " + r.text[:160])
check(open_n() == 0 and not A.get(B + f"/api/agents/{CL}/chat").json()["approvals_open"], "nothing open any more")
check(requests.post(V + f"/agent/chats/{BOB}/messages/{m3['id']}/withdraw", headers=CLH, json={}).status_code == 404, "withdraw in another conversation -> 404")

# ================================================================== review M5: at most 10 open per agent and person, the newest 20 pinned
ten = [say(approval={"title": f"Step {i + 1}"}) for i in range(10)]
check(all(x.status_code == 201 for x in ten), "10 open approval requests are fine")
say(body="May I run this?", permission=True)  # a permission question does not count towards the 10
r = say(approval={"title": "Step 11"})
check(r.status_code == 409 and "open approval requests first" in r.text, "the 11th open one -> 409 'answer the open ones first' " + r.text[:160])
check(say(uid=BOB, approval={"title": "Other person"}).status_code == 201, "... the limit is per person")
requests.post(V + f"/agent/chats/{ALICE}/messages/{ten[0].json()['id']}/withdraw", headers=CLH, json={"outcome": "expired"})
check(say(approval={"title": "Step 11"}).status_code == 201, "after closing one, a new one is fine again")
check(len(A.get(B + f"/api/agents/{CL}/chat").json()["approvals_open"]) == 11 and open_n() == 11, "10 approvals + 1 permission question open")
for i in range(12):  # many permission questions: the chat pins only the newest 20
    say(body=f"May I run step {i}?", permission=True)
ap = A.get(B + f"/api/agents/{CL}/chat").json()["approvals_open"]
check(len(ap) == 20 and ap[-1]["body"] == "May I run step 11?", "approvals_open returns at most the newest 20 " + str(len(ap)))
dbx("UPDATE agent_chat SET choice='{\"ids\":[\"no\"],\"at\":\"2026-01-01T00:00:00.000Z\",\"user_id\":%d}' WHERE agent_id=? AND user_id=? AND choice IS NULL AND choices IS NOT NULL" % ALICE,
    (CL, ALICE), write=True)


# ================================================================== push
def bob_push(title):
    n0 = len(pushes())
    check(say(uid=BOB, approval={"title": title}).status_code == 201, "an approval request to Bob: " + title)
    for _ in range(30):
        got = [p for p in pushes()[n0:] if p["topic"] == "t-bob"]
        if got:
            return got
        time.sleep(0.2)
    return []


dbx("DELETE FROM agent_chat WHERE agent_id=? AND user_id=?", (CL, BOB), write=True)  # a fresh hour for Bob
got = bob_push("Book the venue")
check(len(got) == 1 and got[0].get("title") == "Approval needed: Claude" and "Book the venue" in got[0].get("msg", "") and got[0].get("prio") == "4",
      "push 'Approval needed: <agent>' with the title, priority 4 " + str(got)[:300])
check(Bo.patch(B + "/api/settings", json={"push_priority": "3"}).ok, "Bob chooses push priority 3")
got = bob_push("Book the band")
check(len(got) == 1 and got[0].get("title") == "Approval needed: Claude" and got[0].get("prio") == "3", "review M5: a priority the person chose wins over the floor 4 " + str(got)[:200])
check(Bo.patch(B + "/api/settings", json={"notify": {"approval": {"push": 0}}}).ok, "Bob switches the approval push off")
got = bob_push("Book the second venue")
check(len(got) == 1 and got[0].get("title") == "Claude", "switched off: the plain chat push " + str(got)[:200])
Bo.patch(B + "/api/settings", json={"notify": {"approval": {"push": 1}}})
got = bob_push("Book the caterer")
check(len(got) == 1 and got[0].get("title") == "Approval needed: Claude", "on again: 'Approval needed' (4th request this hour)")
got = bob_push("Book the photographer")
check(len(got) == 1 and got[0].get("title") == "Approval needed: Claude", "5th request this hour: still 'Approval needed'")
got = bob_push("Book the flowers")
check(len(got) == 1 and got[0].get("title") == "Claude", "review M5: the 6th within an hour comes as the plain chat push " + str(got)[:200])
check(say(uid=CAROL, approval={"title": "x"}).status_code == 404, "a person who shares nothing with the agent -> 404")

# ================================================================== schema
check(not dbx("SELECT name FROM sqlite_master WHERE name LIKE '%approval%' AND type='table'"), "no new table (choices json in agent_chat)")
spec = requests.get(V + "/openapi.json").json()
props = spec["paths"]["/agent/chats/{id}"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
check("approval" in props and props["approval"]["properties"]["title"]["maxLength"] == 200, "OpenAPI documents approval")

print(f"p2350_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
