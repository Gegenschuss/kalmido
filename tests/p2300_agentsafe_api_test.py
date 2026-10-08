#!/usr/bin/env python3
"""2.30.0 API tests: agents stay inside one circle of people (#919) and "Use safely" (#920).
 - bridges: an agent in two lists whose people are neither the same nor one inside the other. Sharing a list with an agent
   (PUT /api/lists/<id>/members, PUT /api/lists/<id>/agent) or adding a person to a list with an agent that creates one
   answers 409 agent_bridge with the lists (names only of lists the asker sees); bridge_ok from someone who manages every
   list involved stores the approval, from anyone else 403; nested circles need nothing; "Share all" skips such lists and
   names them; bridges from before (a membership written directly) are flagged unapproved in the agent's settings
 - moving a task across circles: an agent's PATCH list_id / move / batch into a list with other people waits for approval
   (202 + job), into a list with fewer people it goes through; approving runs it
 - least privilege: an agent (list_ids in its settings, mirrored on its tokens) and a personal token limited to selected
   lists: other lists answer 404, list / task queries and search leave them out, no events about them, GET /api/v1/me names
   the limit, a list the limited token creates stays usable, invalid ids 400
 - the access log: per agent, list, day read / write counters; members of the list see them, others get 404
usage: p2300_agentsafe_api_test.py <datadir>"""
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


def members(s, lid):
    return {m["user_id"]: m["role"] for m in lists_of(s)[lid].get("members", [])}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE = ME["id"]
ORG = ME["workspaces"][0]["id"]


def mk(s, name, people=()):
    lid = s.post(B + "/api/lists", json={"name": name, "org_id": ORG}).json()["id"]
    for p in people:
        assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": p, "role": "edit"}).ok
    return lid


r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "second", "display_name": "Second"})
CL2, CL2H = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

# ================================================================== bridges
Q = mk(A, "Mine")                 # {alice}
AB = mk(A, "Alice+Bob", [BOB])    # {alice, bob}
AC = mk(A, "Alice+Carol", [CAROL])  # {alice, carol}
check(A.put(B + f"/api/lists/{Q}/members", json={"user_id": CL, "role": "edit"}).ok, "#919: share a private list with the agent")
check(A.put(B + f"/api/lists/{AB}/members", json={"user_id": CL, "role": "edit"}).ok, "#919: nested circles ({alice} inside {alice, bob}) need no approval")
r = A.put(B + f"/api/lists/{AC}/members", json={"user_id": CL, "role": "edit"})
j = r.json()
check(r.status_code == 409 and j.get("code") == "agent_bridge" and any(b["list_id"] == AB and b["name"] == "Alice+Bob" for b in j.get("bridges", [])),
      "#919: a list with other people than the agent's other list -> 409 agent_bridge naming it " + r.text[:200])
check("Claude" in j.get("error", "") and "Alice+Bob" in j.get("error", ""), "#919: ... the message names the agent and the list " + j.get("error", "")[:160])
check(CL not in members(A, AC), "#919: ... the agent did not join")
r = A.put(B + f"/api/lists/{AC}/agent", json={"agent_id": CL})
check(r.status_code == 409 and r.json().get("code") == "agent_bridge", "#919: the list's agent picker is refused the same way " + r.text[:120])
# Bob shares his own list with the agent: a bridge to Alice's lists, and he does not manage them -> his bridge_ok is refused
BX = mk(Bo, "Bob only")
r = Bo.put(B + f"/api/lists/{BX}/members", json={"user_id": CL, "role": "edit"})
check(r.status_code == 409 and r.json().get("code") == "agent_bridge", "#919: Bob's private list + the agent's other lists = a bridge " + r.text[:120])
check(r.json().get("hidden", 0) >= 1 and not any(b["list_id"] == Q for b in r.json().get("bridges", [])), "#919: ... lists Bob cannot see are counted, never named " + r.text[:200])
r = Bo.put(B + f"/api/lists/{BX}/members", json={"user_id": CL, "role": "edit", "bridge_ok": True})
check(r.status_code == 403 and CL not in members(Bo, BX), "#919: bridge_ok from someone who does not manage every list involved: 403 " + r.text[:120])
# Alice manages both: she confirms
r = A.put(B + f"/api/lists/{AC}/agent", json={"agent_id": CL, "bridge_ok": True})
check(r.ok and CL in members(A, AC), "#919: the owner confirms the bridge (bridge_ok) " + r.text[:120])
check(dbx("SELECT by_id FROM agent_bridges WHERE agent_id=? AND list_a=? AND list_b=?", (CL, min(AB, AC), max(AB, AC))) == [(ALICE,)], "#919: ... stored with who approved it")
ad = {a["id"]: a for a in A.get(B + "/api/admin/agents").json()["agents"]}
bs = ad[CL].get("bridges") or []
check(any(b["approved"] and b["by_name"] == "Alice" and {x["id"] for x in b["lists"]} == {AB, AC} for b in bs), "#919: the agent's settings show the approved bridge " + str(bs)[:200])
# adding a person to a list with the agent: Dave into the private list -> {alice, dave} vs {alice, bob} and {alice, carol}
r = A.put(B + f"/api/lists/{Q}/members", json={"user_id": DAVE, "role": "edit"})
check(r.status_code == 409 and r.json().get("code") == "agent_bridge" and any(b["list_id"] == AB for b in r.json()["bridges"]),
      "#919: adding a person to a list with an agent that creates a bridge -> 409 " + r.text[:160])
check(DAVE not in members(A, Q), "#919: ... the person was not added")
r = A.put(B + f"/api/lists/{Q}/members", json={"user_id": DAVE, "role": "edit", "bridge_ok": True})
check(r.ok and DAVE in members(A, Q), "#919: ... with bridge_ok it is added " + r.text[:80])
check(A.put(B + f"/api/lists/{Q}/members", json={"user_id": DAVE, "role": "view"}).ok, "#919: a role change never asks again")

# the same people as in another list of the agent: no new bridge (an existing one is not asked about again)
X0 = mk(A, "Also Alice+Bob")
check(A.put(B + f"/api/lists/{X0}/members", json={"user_id": CL, "role": "edit"}).ok and A.put(B + f"/api/lists/{X0}/members", json={"user_id": BOB, "role": "edit"}).ok,
      "#919: a list with exactly the people of another list of the agent needs no approval")
# Share all: the second agent; lists with another agent are skipped (one agent per list), lists that would be a bridge too
X1 = mk(A, "X with Bob", [BOB])
X2 = mk(A, "X with Carol", [CAROL])
r = A.post(B + f"/api/agents/{CL2}/share-all")
j = r.json()
check(r.ok and j["added"] >= 1 and any(l["id"] == X2 for l in j.get("bridge", [])) and j.get("bridge_reason"), "#919: Share all skips and names a list that would be a bridge " + r.text[:240])
check(CL2 in members(A, X1) and CL2 not in members(A, X2), "#919: ... the first list joined, the other not")
bl = A.get(B + f"/api/agents/{CL2}/bridges").json()["bridges"]
check(bl == [], "#919: ... no bridge came about " + str(bl)[:120])
# a bridge from before 2.30 (a membership written directly): kept, flagged, not approved
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (X2, CL2, "edit", "edit", 99, "2026-01-01T00:00:00+00:00"), write=True)
ad = {a["id"]: a for a in A.get(B + "/api/admin/agents").json()["agents"]}
check(any(not b["approved"] and {x["id"] for x in b["lists"]} == {X1, X2} for b in ad[CL2]["bridges"]), "#919: an old bridge stays and is flagged unapproved " + str(ad[CL2]["bridges"])[:200])
bb = Bo.get(B + f"/api/agents/{CL2}/bridges")
check(bb.ok and all(x["name"] is None for b in bb.json()["bridges"] for x in b["lists"] if x["id"] == X2), "#919: someone in only one of the lists sees the other one unnamed " + bb.text[:200])
check(Ca.get(B + f"/api/agents/{CL}/bridges").status_code in (200, 404), "#919: the bridges route answers")
# review: sharing by e-mail address and groups never open a bridge (silently, nothing about the account is revealed)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "third", "display_name": "Third"})
CL3 = r.json()["id"]
E1, E2 = mk(A, "E with Bob", [BOB]), mk(A, "E alone")
check(A.put(B + f"/api/lists/{E1}/members", json={"user_id": CL3, "role": "edit"}).ok and A.put(B + f"/api/lists/{E2}/members", json={"user_id": CL3, "role": "edit"}).ok, "#919: a third agent in {alice, bob} and {alice}")
r = A.put(B + f"/api/lists/{E2}/members", json={"email": "carol@example.com", "role": "edit"})
check(r.ok and r.json().get("by_email") and CAROL not in members(A, E2), "#919: a share by address that would be a bridge does nothing, answers as usual " + r.text[:100])
GID = A.post(B + "/api/admin/groups", json={"name": "Office", "members": [CAROL]}).json()["id"]
r = A.put(B + f"/api/lists/{E2}/groups/{GID}", json={"role": "edit"})
check(CAROL not in members(A, E2), "#919: a group does not add a person that would open a bridge " + r.text[:100])
A.delete(B + f"/api/lists/{E2}/groups/{GID}")
# review: bridge_ok through the REST API, only from a person's token
atok = {"Authorization": "Bearer " + A.post(B + "/api/me/tokens", json={"name": "alice", "scopes": ["read", "write"]}).json()["token"]}
r = requests.put(V + f"/lists/{E2}/members/{DAVE}", headers=atok, json={"role": "edit"})
check(r.status_code == 409 and r.json()["error"]["code"] == "agent_bridge", "#919: v1 member share that opens a bridge: 409 agent_bridge " + r.text[:160])
r = requests.put(V + f"/lists/{E2}/members/{DAVE}", headers=atok, json={"role": "edit", "bridge_ok": True})
check(r.ok and DAVE in members(A, E2), "#919: ... bridge_ok from a person's token confirms it " + r.text[:120])

# ================================================================== moving tasks across circles (agents)
# the agent's own list, shared with Alice and Bob (written directly: an agent's sharing waits for approval anyway)
AG = requests.post(V + "/lists", headers=CLH, json={"name": "Agent board", "org_id": ORG}).json()["id"]
for p in (ALICE, BOB):
    dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (AG, p, "edit", "edit", 50, "2026-10-01T00:00:00+00:00"), write=True)
t1 = requests.post(V + "/tasks", headers=CLH, json={"title": "from the board", "list_id": AG}).json()  # AG = {alice, bob}
check(t1.get("id"), "#919: the agent writes in its list " + str(t1)[:80])
r = requests.patch(V + f"/tasks/{t1['id']}", headers=CLH, json={"list_id": AC})  # {alice, carol} is not inside {alice, bob}
check(r.status_code == 202 and r.json().get("approval_required"), "#919: an agent moving a task to other people waits for approval (PATCH) " + r.text[:160])
J = r.json()["job"]["id"]
check("other people" in r.json()["job"]["title"], "#919: ... the approval says why " + r.json()["job"]["title"])
check(dbx("SELECT list_id FROM tasks WHERE id=?", (t1["id"],)) == [(AG,)], "#919: ... nothing moved yet")
r = requests.post(V + f"/tasks/{t1['id']}/move", headers=CLH, json={"list_id": AC})
check(r.status_code == 202, "#919: ... the same through POST move " + r.text[:120])
t2 = requests.post(V + "/tasks", headers=CLH, json={"title": "batch me", "list_id": AG}).json()
r = requests.post(V + "/tasks/batch", headers=CLH, json={"ids": [t2["id"]], "action": "update", "changes": {"list_id": AC}})
check(r.status_code == 202, "#919: ... and through the batch " + r.text[:120])
r = A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"})
check(r.ok and dbx("SELECT list_id FROM tasks WHERE id=?", (t1["id"],)) == [(AC,)], "#919: approved by the owner, it moves " + r.text[:200])
t3 = requests.post(V + "/tasks", headers=CLH, json={"title": "to fewer", "list_id": AG}).json()
r = requests.patch(V + f"/tasks/{t3['id']}", headers=CLH, json={"list_id": AB})  # {alice, bob} -> {alice, bob}
check(r.ok and r.json()["list_id"] == AB, "#919: moving into a list with the same (or fewer) people needs nothing " + r.text[:120])
t4 = A.post(B + "/api/tasks", json={"title": "person moves", "list_id": Q}).json()
check(A.patch(B + f"/api/tasks/{t4['id']}", json={"list_id": AB}).ok, "#919: people move freely (only agents wait)")
# review: an agent's own share request waits for approval; a bridge behind it needs someone who manages every list
r = requests.put(V + f"/lists/{AG}/members/{CAROL}", headers=CLH, json={"role": "view"})
check(r.status_code == 202, "#919: an agent's share waits for approval " + r.text[:100])
r = A.post(B + f"/api/agents/jobs/{r.json()['job']['id']}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "failed" and "different people" in r.json()["log"] and CAROL not in members(A, AG),
      "#919: ... approved by someone who does not manage the agent's own list: the job fails with a clear reason " + r.text[:200])
# the board's people were written directly (a bridge nobody approved); take them out again for the next part
dbx("DELETE FROM list_members WHERE list_id=? AND user_id IN (?,?)", (AG, ALICE, BOB), write=True)

# ================================================================== least privilege: list restriction
r = A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [AB]})
check(r.ok and r.json()["list_ids"] == [AB], "#919: the admin limits the agent to selected lists " + r.text[:120])
check(dbx("SELECT list_ids FROM api_tokens WHERE user_id=?", (CL,)) == [(str(AB),)], "#919: ... mirrored on its token")
me = requests.get(V + "/me", headers=CLH).json()
check(me["token"].get("list_ids") == [AB], "#919: GET /api/v1/me names the limit " + str(me.get("token"))[:160])
vl = [l["id"] for l in requests.get(V + "/lists", headers=CLH).json()["data"]]
check(AB in vl and Q not in vl and AC not in vl, "#919: GET /api/v1/lists leaves the other lists out " + str(vl))
check(requests.get(V + f"/lists/{Q}", headers=CLH).status_code == 404, "#919: another list answers 404")
check(requests.get(V + f"/tasks/{t1['id']}", headers=CLH).status_code == 404, "#919: a task of another list answers 404")
tl = requests.get(V + "/tasks?limit=500", headers=CLH).json().get("data", [])
check(tl and all(t["list_id"] == AB for t in tl), "#919: GET /api/v1/tasks only from the allowed lists " + str({t["list_id"] for t in tl}))
sr = requests.get(V + "/search?q=from%20the%20board", headers=CLH).json().get("data", [])
check(not sr, "#919: search leaves the other lists out " + str(sr)[:120])
check(requests.post(V + "/tasks", headers=CLH, json={"title": "nope", "list_id": Q}).status_code == 404, "#919: writing into another list: 404")
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
A.post(B + "/api/tasks", json={"title": "hey @claude in mine", "list_id": Q})
A.post(B + "/api/tasks", json={"title": "hey @claude in AB", "list_id": AB})
time.sleep(0.5)
ev = requests.get(V + f"/agent/events?since={cur}", headers=CLH).json()["data"]
check(any("in AB" in str(e["data"]) for e in ev) and not any("in mine" in str(e["data"]) for e in ev), "#919: no events about the other lists " + str([e["event"] for e in ev]))
check(A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [BX]}).status_code == 400, "#919: a list the agent is not in cannot be chosen")
nl = requests.post(V + "/lists", headers=CLH, json={"name": "Agent's own", "org_id": ORG})
check(nl.status_code == 201 and requests.get(V + f"/lists/{nl.json()['id']}", headers=CLH).ok, "#919: a list the limited agent creates stays usable " + nl.text[:120])
check(A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": []}).json()["list_ids"] == [], "#919: [] = all lists again")
check(requests.get(V + f"/lists/{Q}", headers=CLH).ok, "#919: ... the other list is back")
# a personal token limited to one list
r = Bo.post(B + "/api/me/tokens", json={"name": "only AB", "scopes": ["read", "write"], "list_ids": [AB]})
check(r.ok and r.json()["list_ids"] == [AB], "#919: a personal token limited to one list " + r.text[:120])
BT, BTID = {"Authorization": "Bearer " + r.json()["token"]}, r.json()["id"]
vl = [l["id"] for l in requests.get(V + "/lists", headers=BT).json()["data"]]
check(vl == [AB], "#919: ... it sees only that list " + str(vl))
check(requests.get(V + f"/lists/{BX}", headers=BT).status_code == 404, "#919: ... Bob's own other list does not exist for it")
check(Bo.patch(B + f"/api/me/tokens/{BTID}", json={"list_ids": [AC]}).status_code == 400, "#919: a list Bob does not see cannot be chosen")
r = Bo.patch(B + f"/api/me/tokens/{BTID}", json={"list_ids": []})
check(r.ok and r.json()["list_ids"] == [] and BX in [l["id"] for l in requests.get(V + "/lists", headers=BT).json()["data"]], "#919: [] = all lists again " + r.text[:100])
# personal agent: its owner limits it
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot"})
BB = r.json()["id"]
check(Bo.put(B + f"/api/lists/{BX}/members", json={"user_id": BB, "role": "edit"}).ok, "#919: a personal agent in its owner's list")
r = Bo.patch(B + f"/api/my/agents/{BB}", json={"list_ids": [BX]})
check(r.ok and r.json()["list_ids"] == [BX], "#919: the owner limits a personal agent " + r.text[:120])
# review: widening the limit must not switch on an unapproved bridge
check(A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [AB]}).ok, "#919: narrowing is always fine")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (BX, CL, "edit", "edit", 98, "2026-01-01T00:00:00+00:00"), write=True)
r = A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": []})
check(r.status_code == 409 and r.json().get("code") == "agent_bridge", "#919: lifting the limit onto an unapproved bridge: 409 " + r.text[:160])
check(A.get(B + "/api/admin/agents").json()["agents"][[a["id"] for a in A.get(B + "/api/admin/agents").json()["agents"]].index(CL)]["list_ids"] == [AB], "#919: ... the limit stays")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [], "bridge_ok": True}).status_code == 403, "#919: ... bridge_ok from someone who does not manage Bob's list: 403")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (BX, CL), write=True)
check(A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": []}).ok, "#919: without the bridge it is lifted")
# review: a limited token gets no full export, News only of its lists
r = Bo.post(B + "/api/me/tokens", json={"name": "AB again", "scopes": ["read", "write", "export"], "list_ids": [AB]})
BT2 = {"Authorization": "Bearer " + r.json()["token"]}
check(requests.get(V + "/export", headers=BT2).status_code == 403, "#919: GET /export with a limited token: 403")
nw = requests.get(V + "/news", headers=BT2).json().get("data", [])
check(all(not x.get("list_id") or x["list_id"] == AB for x in nw), "#919: News of the limited token only from its lists " + str([x.get("list_id") for x in nw]))
# review: somebody else's personal agent: its bridges are not shown, not even to an admin
check(A.get(B + f"/api/agents/{BB}/bridges").status_code == 404, "#919: an admin does not read another person's personal agent's bridges")
check(Bo.get(B + f"/api/agents/{BB}/bridges").ok, "#919: ... its owner does")

# ================================================================== access log
time.sleep(1.2)
requests.get(V + f"/tasks/{t3['id']}", headers=CLH)                                    # read AB
requests.post(V + f"/tasks/{t3['id']}/comments", headers=CLH, json={"body": "seen"})    # write AB
requests.get(V + f"/lists/{Q}", headers=CLH)                                            # read Q
r = Bo.get(B + f"/api/lists/{AB}/agent-access")
check(r.ok and r.json()["days"] == 30, "#919: a member reads the list's agent access " + r.text[:160])
rows = [x for x in r.json().get("data", []) if x["agent_id"] == CL]
check(rows and rows[0]["read"] >= 1 and rows[0]["write"] >= 1 and rows[0]["name"] == "Claude", "#919: ... read and write counted per day " + str(rows))
check(not any(x["agent_id"] == CL2 for x in r.json()["data"]), "#919: ... only agents that touched the list")
check(Ca.get(B + f"/api/lists/{AB}/agent-access").status_code == 404, "#919: someone outside the list gets 404")
qa = A.get(B + f"/api/lists/{Q}/agent-access").json()["data"]
check(any(x["agent_id"] == CL and x["read"] >= 1 for x in qa), "#919: the other list has its own counters " + str(qa))
n = dbx("SELECT COUNT(*) FROM agent_list_access")[0][0]
check(0 < n <= 20, f"#919: stored sparingly (one row per agent, list, day and kind): {n}")

print(f"p2300_agentsafe_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
