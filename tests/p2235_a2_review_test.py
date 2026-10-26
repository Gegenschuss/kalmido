#!/usr/bin/env python3
"""2.235.0 A2 (#2891 #2901): the review findings of the control level (Fable review of part A), each one red without its fix
 - 1 the approval is bound to the content: a card POST /tasks/batch approved by the deadline ("recommend") never deletes
   (body not bound + one-way only with a person's Yes); a card with the delete body is marked one_way by the server and
   the deadline's Yes does not count, a person's Yes does; a card for PATCH due does not carry list_id / title, the same
   body with the keys in another order passes
 - 2 a team agent: a chat partner who only reads in the project approves nothing (also routine), neither does the
   deadline's Yes for that person
 - 3 the owner's cap also for notes (an object route) and for a move into another project (list_id in the body)
 - 4 Undo of a plan / a tick only while nobody changed it since (409, the person's values stay)
 - 5 the deadline counts from when it was set: an old card does not end at once when a deadline is picked
freelancer-matrix: agents (the personal agent belongs to a person without an organisation)
usage: p2235_a2_review_test.py <datadir>      (KMT_NOSTART=1 / P2235A2_NOSTART=1: a running server)"""
import os
import sys
from datetime import timedelta, timezone

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup, until
from testclock import now

V = B + "/api/v1"
HDR = "X-Kalmido-Approval"

os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default (tests/start.sh starts other suites with legacy)
fresh(prefix="P2235A2")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")
PID, P = freelancer(B, A, "paula")
SCOPES = ["read", "tasks:write", "comments", "delete"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def ago(hours=2):
    return (now() - timedelta(hours=hours)).astimezone(timezone.utc).isoformat(timespec="seconds")


def ctl(s, aid, patch, want=200):
    r = s.patch(B + f"/api/agents/{aid}/control", json=patch)
    check(r.status_code == want, f"control {patch} -> {r.status_code} {r.text[:200]}")


def code(r):
    try:
        return r.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


def events(h, name):
    r = requests.get(V + "/agent/events?since=0&limit=500", headers=h)
    return [e for e in r.json().get("data", []) if e.get("event") == name] if r.ok else []


def card(h, uid, step, **kw):
    r = requests.post(V + f"/agent/chats/{uid}", headers=h, json={"approval": {"title": "May I?", "step": step, **kw}})
    check(r.status_code == 201, f"approval card {r.status_code} {r.text[:200]}")
    return r.json()


def answer(s, aid, mid, choice="yes"):
    r = s.post(B + f"/api/agents/{aid}/chat/{mid}/choice", json={"choice_ids": [choice]})
    check(r.ok, f"answer {choice} {r.status_code} {r.text[:150]}")


def expired(h, mid):
    return [e for e in events(h, "approval_expired") if e["data"]["message_id"] == mid]


def age_card(aid, mid):
    kt.dbx("UPDATE agent_chat SET created_at=? WHERE id=?", (ago(), mid))
    kt.dbx("""UPDATE agents SET control=CAST(jsonb_set(CAST(control AS JSONB), '{deadline_set_at}', to_jsonb(CAST(? AS TEXT))) AS TEXT)
              WHERE user_id=?""", (ago(), aid))


# ================================================================== the personal agent of Frida (no organisation)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": SCOPES})
check(r.status_code in (200, 201), f"personal agent {r.status_code} {r.text[:150]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
FL = F.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "the list is shared with the agent")


def fapi(method, path, mid=None, **kw):
    return requests.request(method, V + path, headers={**FH, **({HDR: str(mid)} if mid else {})}, **kw)


ctl(F, FA, {"level": "routine"})
ids = [fapi("POST", "/tasks", json={"title": f"Batch {i}", "list_id": FL}).json()["id"] for i in range(3)]

# ---- 1a: a card approved by the deadline never becomes a delete
ctl(F, FA, {"deadline": "1h", "then": "recommend"})
m = card(FH, FID, {"method": "POST", "path": "/api/v1/tasks/batch"}, recommend="yes")
age_card(FA, m["id"])
check(until(lambda: expired(FH, m["id"]), 10) and expired(FH, m["id"])[0]["data"]["outcome"] == "approved",
      "1a: the body-less batch card is approved by the deadline")
r = fapi("POST", "/tasks/batch", m["id"], json={"action": "delete", "ids": ids})
check(r.status_code == 409 and code(r) == "approval_invalid", f"1a: a delete with the deadline's Yes -> 409 {r.status_code} {r.text[:200]}")
check(len(kt.dbx(f"SELECT id FROM tasks WHERE deleted_at IS NULL AND id IN ({ids[0]},{ids[1]},{ids[2]})")) == 3, "1a: nothing was deleted")
# the 409 hands over the body to copy into the card
r = fapi("POST", "/tasks/batch", json={"action": "delete", "ids": ids})
ap = r.json()["error"].get("approval") or {} if r.status_code == 409 else {}
check(ap.get("body") == {"action": "delete", "ids": ids} and ap.get("method") == "POST", f"1: the 409 names the body {ap}")
ctl(F, FA, {"deadline": "off"})
m = card(FH, FID, {k: ap[k] for k in ("method", "path", "body")}, recommend="yes")
check(m["choices"]["approval"].get("one_way") is True, f"1: the server marks a delete card one_way {m['choices']['approval']}")
kt.dbx("UPDATE agent_chat SET choice=? WHERE id=?", ('{"ids": ["yes"], "at": "%s", "user_id": null, "via": "deadline"}' % ago(0), m["id"]))
r = fapi("POST", "/tasks/batch", m["id"], json={"action": "delete", "ids": ids})
check(r.status_code == 409 and code(r) == "approval_invalid", f"1a: a one-way step never by the deadline's Yes {r.status_code}")
m = card(FH, FID, {k: ap[k] for k in ("method", "path", "body")})
answer(F, FA, m["id"])
r = fapi("POST", "/tasks/batch", m["id"], json={"ids": ids, "action": "delete"})
check(r.ok, f"1: a person's Yes on exactly that body deletes (keys in another order) {r.status_code} {r.text[:200]}")

# ---- 1b: a card for a date does not carry a move / rename
ctl(F, FA, {"level": "approve_all"})
F2 = F.post(B + "/api/lists", json={"name": "Frida other"}).json()["id"]
F.put(B + f"/api/lists/{F2}/members", json={"user_id": FA, "role": "edit"})
ctl(F, FA, {"level": "free"})
T = fapi("POST", "/tasks", json={"title": "Plan me", "list_id": FL}).json()["id"]
ctl(F, FA, {"level": "approve_all"})
m = card(FH, FID, {"method": "PATCH", "path": f"/tasks/{T}", "body": {"due": "2026-12-04"}})
answer(F, FA, m["id"])
r = fapi("PATCH", f"/tasks/{T}", m["id"], json={"due": "2026-12-04", "list_id": F2, "title": "Moved"})
check(r.status_code == 409 and code(r) == "approval_invalid", f"1b: more keys than the card -> 409 {r.status_code} {r.text[:200]}")
t = requests.get(V + f"/tasks/{T}", headers=FH).json()
check(t["list_id"] == FL and t["title"] == "Plan me", f"1b: not moved, not renamed {t.get('list_id')} {t.get('title')}")
check(fapi("PATCH", f"/tasks/{T}", m["id"], json={"due": "2026-12-04"}).ok, "1b: exactly the card's body passes (the approval came back)")

# ---- 3: the owner's cap for notes and for a move
OL = O.post(B + "/api/lists", json={"name": "Otto shared"}).json()["id"]
for uid in (FID, FA):
    kt.dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit',?) ON CONFLICT DO NOTHING", (OL, uid, ago(0)))
r = O.post(B + f"/api/lists/{OL}/notes", json={"title": "Otto's note"})
check(r.ok, f"Otto writes a note {r.status_code} {r.text[:150]}")
NID = r.json()["id"]
ctl(F, FA, {"level": "free"})
r = fapi("PATCH", f"/notes/{NID}", json={"title": "Changed by the agent"})
check(r.status_code == 409 and r.json()["error"].get("level") == "routine", f"3: a note in a project with edit rights: capped to routine {r.status_code} {r.text[:200]}")
r = fapi("PATCH", f"/tasks/{T}", json={"list_id": OL})
check(r.status_code == 409 and r.json()["error"].get("level") == "routine", f"3: a move into that project: capped {r.status_code} {r.text[:200]}")
check(requests.get(V + f"/tasks/{T}", headers=FH).json()["list_id"] == FL, "3: the task stayed")
check(fapi("PATCH", f"/tasks/{T}", json={"title": "Free in her own list"}).ok, "3: in her own list free stays free")

# ---- 4: Undo only while nobody changed it since (tasks of Frida: no agent lock in the way of her own edits)
ctl(F, FA, {"level": "routine"})


def mk(title):
    return F.post(B + "/api/tasks", json={"title": title, "list_id": FL}).json()["id"]


T4 = mk("Plan by both")
check(fapi("PATCH", f"/tasks/{T4}", json={"due": "2026-12-10"}).ok, "4: the agent plans")
check(F.patch(B + f"/api/tasks/{T4}", json={"due": "2026-12-20"}).ok, "4: Frida plans again by hand")
h = F.get(B + f"/api/agents/{FA}/control").json()["history"]
pl = [x for x in h if x["kind"] == "task_planned" and not x["undone_at"]][0]
r = F.post(B + f"/api/agents/{FA}/control/history/{pl['id']}/undo")
check(r.status_code == 409, f"4: Undo of a plan changed since -> 409 {r.status_code} {r.text[:150]}")
check(requests.get(V + f"/tasks/{T4}", headers=FH).json()["due"] == "2026-12-20", "4: Frida's date stays")
T5 = mk("Tick")
check(fapi("POST", f"/tasks/{T5}/complete").ok, "4: the agent ticks off")
check(F.post(B + f"/api/tasks/{T5}/reopen", json={}).ok and F.post(B + f"/api/tasks/{T5}/complete", json={}).ok, "4: Frida reopens and ticks off herself")
h = F.get(B + f"/api/agents/{FA}/control").json()["history"]
tk = [x for x in h if x["kind"] == "task_completed" and not x["undone_at"]][0]
r = F.post(B + f"/api/agents/{FA}/control/history/{tk['id']}/undo")
check(r.status_code == 409, f"4: Undo of a tick someone else did since -> 409 {r.status_code}")
check(kt.dbx("SELECT status FROM tasks WHERE id=?", (T5,))[0][0] != 0, "4: Frida's tick stays")
T6 = mk("Plan untouched")
check(fapi("PATCH", f"/tasks/{T6}", json={"due": "2026-12-11"}).ok, "4: the agent plans another")
h = F.get(B + f"/api/agents/{FA}/control").json()["history"]
pl = [x for x in h if x["kind"] == "task_planned" and not x["undone_at"]][0]
check(F.post(B + f"/api/agents/{FA}/control/history/{pl['id']}/undo").ok, "4: Undo of an untouched plan works")
check(requests.get(V + f"/tasks/{T6}", headers=FH).json()["due"] is None, "4: the date is gone again")

# ---- 5: the deadline counts from when it was set (a second agent of Frida is the clock: its card ends first)
r = F.post(B + "/api/my/agents", json={"username": "fridaclock", "display_name": "Clock", "scopes": SCOPES})
CA, CH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
F.put(B + f"/api/lists/{FL}/members", json={"user_id": CA, "role": "edit"})
ctl(F, FA, {"deadline": "off", "then": "reject"})
old = card(FH, FID, {"method": "PATCH", "path": f"/tasks/{T6}", "body": {"title": "Old card"}})["id"]
kt.dbx("UPDATE agent_chat SET created_at=? WHERE id=?", (ago(3), old))
ctl(F, FA, {"deadline": "1h"})
ctl(F, CA, {"deadline": "1h"})
for i in range(2):  # two ticks of the watchdog have run after the deadline was set
    ck = card(CH, FID, {"method": "PATCH", "path": f"/tasks/{T6}", "body": {"title": f"Clock {i}"}})["id"]
    age_card(CA, ck)
    check(until(lambda: expired(CH, ck), 10), f"5: the clock card {i} ended")
check(not expired(FH, old), "5: the old card did not end at once when the deadline was picked")
check(kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND choice IS NULL AND choices->>'withdrawn_at' IS NULL", (old,)), "5: it is still open")
age_card(FA, old)
check(until(lambda: expired(FH, old), 10), "5: an hour after setting the deadline it ends")

# ================================================================== 2: a team agent, a chat partner who only reads
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team", "scopes": SCOPES})
TA, TH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TL = A.post(B + "/api/lists", json={"name": "Team work"}).json()["id"]
A.put(B + f"/api/lists/{TL}/members", json={"user_id": TA, "role": "edit"})
A.put(B + f"/api/lists/{TL}/members", json={"user_id": PID, "role": "view"})
A.patch(B + f"/api/lists/{TL}", json={"agent_members": True})
step = {"method": "POST", "path": "/tasks", "body": {"title": "By a reader's Yes", "list_id": TL}}
m = card(TH, PID, step)
answer(P, TA, m["id"])
r = requests.post(V + "/tasks", headers={**TH, HDR: str(m["id"])}, json=step["body"])
check(r.status_code == 409 and code(r) == "approval_invalid", f"2: a reader's Yes approves no routine step {r.status_code} {r.text[:200]}")
ctl(A, TA, {"deadline": "1h", "then": "recommend"})
m = card(TH, PID, step, recommend="yes")
age_card(TA, m["id"])
check(until(lambda: expired(TH, m["id"]), 10), "2: the deadline answers the reader's card")
r = requests.post(V + "/tasks", headers={**TH, HDR: str(m["id"])}, json=step["body"])
check(r.status_code == 409 and code(r) == "approval_invalid", f"2: the deadline's Yes for a reader approves nothing {r.status_code}")
m = card(TH, ALICE, step)
answer(A, TA, m["id"])
r = requests.post(V + "/tasks", headers={**TH, HDR: str(m["id"])}, json=step["body"])
check(r.status_code == 201, f"2: the Yes of the project's owner passes {r.status_code} {r.text[:200]}")
sys.exit(done("p2235_a2_review"))
