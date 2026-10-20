#!/usr/bin/env python3
"""2.126.1 API tests, part B: table rows as an agent's proposal (#2125), planned "Sort the basket" (#2126). Own container
(start.sh). Invented names only.
 - #2125: an agent proposes rows of a table shared with it as tasks of a list shared with it
   (POST /api/v1/agent/proposals/sheet-tasks): not shared table / not shared list / a list of another organisation / an
   agent of another organisation -> 404, a list in another space -> 409, a person who may not write the list -> 400, the
   direct to-tasks route stays closed to agents; the card goes to the person who shared the table, shows the rows as she
   sees them (agent title, cell title, empty rows greyed out), nobody else opens it; applying creates the ticked rows as
   tasks (edited title, history "from a proposal by"), marks the rows; rows carried over are skipped (all = 409); undo /
   redo = the batch of step 2
 - #2126: a plan gets an action (chat default, triage); triage needs no prompt, never a list; when due: an empty basket
   sends nothing (empty), else a job_request of kind triage with scheduled: true and the basket items, an open one is not
   repeated (pending); the agent answers with a normal triage proposal that the person applies; a chat plan still sends
   scheduled_job; Run now on an empty basket = 409; GET /api/v1/agent/schedules shows the action
 - a person without an organisation: own agent, private table + list -> card -> tasks; a triage plan of her own agent
   (freelancer-matrix: sheets, agents)
usage: p21261_b_api_test.py <datadir>      (a fresh container; P21261B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,collab,comments,office"


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


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


if not os.environ.get("P21261B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "erin" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
SC = ["read", "tasks:write", "comments", "sheets:read"]


def agent(name, org=None, owner=None, scopes=SC):
    body = {"scopes": scopes, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def events(a, kind):
    r = a.get(V + "/agent/events", params={"since": 0, "limit": 500})
    return [e for e in r.json()["data"] if e["event"] == kind] if r.ok else []


def acts(s, tid):
    r = s.get(B + f"/api/tasks/{tid}/timeline")
    return r.json().get("activity", []) if r.ok else []


def links(s, sid):
    r = s.get(B + f"/api/sheets/{sid}/links")
    return {x["row_id"]: x for x in r.json()["links"] if x["kind"] == "task"} if r.ok else {}


def new_sheet(s, space, title, rows):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    sh = r.json()
    cols = [c["id"] for c in sh["columns"][:3]]
    rids = [x["id"] for x in sh["rows"]]
    cells = [{"row_id": rids[i], "col_id": cols[j], "raw": v} for i, vals in enumerate(rows) for j, v in enumerate(vals) if v]
    r = s.put(B + f"/api/sheets/{sh['id']}/cells", json={"cells": cells})
    assert r.ok, r.text
    return sh["id"], cols, rids


TA, ta = agent("alphabot", org=ORG)
BB, bb = agent("betabot", org=BETA)

# ================================================================ #2125 rows -> tasks as a proposal (organisation Alpha)
SID, C, R = new_sheet(Bo, SP, "Shot list", [["Camera check", "2031-05-04", "Batteries too"], ["Book studio", "", ""], ["", "", "no title"],
                                            ["Order props", "", ""]])
L = Bo.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": TA, "role": "edit"}).ok, "setup: the agent in the list Shoot")
L2 = Bo.post(B + "/api/lists", json={"name": "Not for agents", "org_id": ORG}).json()["id"]
LP = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
Bo.put(B + f"/api/lists/{LP}/members", json={"user_id": TA, "role": "edit"})  # may fail (another space): the route says 404 / 409
LB = Er.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
GOOD = {"sheet_id": SID, "rows": [R[0], {"row_id": R[1], "title": "Book the studio"}, R[2]], "list_id": L, "title_col": C[0],
        "due_col": C[1], "notes_col": C[2], "summary": "Three rows look like to-dos."}


def propose(a, **over):
    return a.post(V + "/agent/proposals/sheet-tasks", json={**GOOD, **over})


r = propose(ta)
check(r.status_code == 404, f"a table not shared with the agent: 404 ({r.status_code})")
check(Bo.post(B + f"/api/sheets/{SID}/shares", json={"user_id": TA, "role": "read"}).status_code == 201, "setup: bob shares the table (read)")
check(propose(ta, list_id=L2).status_code == 404, "a list not shared with the agent: 404")
check(propose(ta, list_id=LB).status_code == 404, "a list of another organisation: 404")
check(propose(ta, list_id=LP).status_code in (404, 409), "a list in another space: 404 / 409")
check(propose(bb).status_code == 404, "an agent of another organisation: 404")
check(propose(ta, rows=[R[0], 987654321]).status_code == 400, "a row of no table: 400")
check(propose(ta, rows=[R[0], R[0]]).status_code == 400, "a row twice: 400")
check(propose(ta, title_col=987654321).status_code == 400, "a column of no table: 400")
check(propose(ta, colour="red").status_code == 400, "an unknown field: 400")
check(propose(ta, for_user_id=uid["carol"]).status_code == 400, "carol may not write the list: 400")
r = requests.post(B + f"/api/sheets/{SID}/to-tasks", headers={"Authorization": ta.headers["Authorization"], **H},
                  json={"list_id": L, "title_col": C[0]})
check(r.status_code in (401, 403, 404), f"the direct to-tasks stays closed to agents ({r.status_code})")
r = propose(ta)
check(r.status_code == 201 and r.json().get("proposal_state") == "ready", "the proposal: 201, ready " + r.text[:300])
J = r.json().get("id")
v = Bo.get(B + f"/api/proposals/{J}").json()
check(v.get("kind") == "sheet_tasks" and v["job"]["user_id"] == uid["bob"], "the card is bob's (he shared the table)")
rows = v.get("sheet_rows") or []
check([x["state"] for x in rows] == ["", "", "empty"], "row states: two fine, one without a title " + str(rows)[:300])
check(rows and rows[0]["title"] == "Camera check" and rows[0]["due"] == "2031-05-04" and rows[0]["notes"] == "Batteries too",
      "row 1 as bob sees it (title, due, notes)")
check(len(rows) > 1 and rows[1]["title"] == "Book the studio" and rows[1]["cell_title"] == "Book studio", "row 2: the agent's title, the cell")
check(v.get("sheet", {}).get("id") == SID and v.get("list", {}).get("id") == L, "the card names the table and the list")
check(Ca.get(B + f"/api/proposals/{J}").status_code == 404, "carol cannot open bob's card")
check(ta.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code in (401, 403, 404), "the agent cannot apply it")
r = Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0", "1"], "edits": {"0": {"title": "Check the camera"}}})
check(r.ok and r.json().get("created") == 2 and r.json().get("skipped") == 0, "bob applies two rows " + r.text[:300])
mk = links(Bo, SID)
check(set(mk) == {R[0], R[1]}, "both rows carry the mark " + str(mk)[:200])
tids = [mk[x]["target_id"] for x in (R[0], R[1]) if x in mk]
t0 = Bo.get(B + f"/api/tasks/{tids[0]}").json() if tids else {}
check(t0.get("title") == "Check the camera" and t0.get("list_id") == L and t0.get("due") == "2031-05-04", "the edited title, list, due " + str(t0)[:200])
a0 = [x for x in acts(Bo, tids[0]) if x["kind"] == "created"] if tids else []
check(a0 and a0[0]["data"].get("sheet") == SID and a0[0]["data"].get("proposal") and a0[0]["data"].get("agent") == TA,
      "history: from the table, from a proposal by the agent " + str(a0)[:200])
check(len(tids) > 1 and Bo.get(B + f"/api/tasks/{tids[1]}").json().get("title") == "Book the studio", "the agent's title")
ev = [e for e in events(ta, "job") if e["data"]["job"]["id"] == J]
check(ev and ev[-1]["data"]["action"] == "approve", "the agent hears: approved")
check(propose(ta, rows=[R[0]]).status_code == 409, "only rows carried over: 409")
r = propose(ta, rows=[R[0], R[3]])
check(r.status_code == 201 and r.json().get("skipped") == [R[0]], "the row carried over is named as skipped " + r.text[:200])
J2 = r.json().get("id")
# undo / redo = the batch of step 2
r = Bo.post(B + f"/api/proposals/{J}/undo")
check(r.ok and r.json().get("undone") == 2, "undo: both tasks " + r.text[:200])
check(tids and Bo.get(B + f"/api/tasks/{tids[0]}").status_code == 404 and not links(Bo, SID), "the tasks are in the trash, the marks gone")
r = Bo.post(B + f"/api/proposals/{J}/redo")
check(r.ok and r.json().get("redone") == 2 and set(links(Bo, SID)) == {R[0], R[1]}, "redo: back with their marks " + r.text[:200])
r = Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0", "1"]})
check(r.ok and r.json().get("created") == 1 and r.json().get("skipped") == 1, "the second card: the new row only " + r.text[:200])
# the share ends: the agent can no longer propose (the person's card stays theirs)
sh = Bo.get(B + f"/api/sheets/{SID}/shares").json()["shares"]
x = next((s for s in sh if s["user_id"] == TA), None)
check(x is not None and Bo.delete(B + f"/api/sheets/{SID}/shares/{x['id']}").ok, "bob stops sharing")
check(propose(ta, rows=[R[3]]).status_code == 404, "after the share ended: 404")

# ================================================================ #2126 planned "Sort the basket"
CL, cl = agent("clara", org=ORG, scopes=["read", "tasks:write", "comments"])
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for who in (CL, uid["bob"]):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in Work")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})


def plan(s, aid=CL, **b):
    body = {"title": "Morning sort", "freq": "weekdays", "time": "07:30", "tz": "Europe/Berlin", **b}
    return s.post(B + f"/api/agents/{aid}/schedules", json=body)


r = plan(Bo, action="triage", list_id=W)
check(r.status_code == 201 and r.json()["action"] == "triage" and r.json()["list_id"] is None and r.json()["prompt"],
      "a triage plan: no prompt needed, never a list " + r.text[:300])
PT = r.json().get("id")
check(plan(Bo, action="sing").status_code == 400, "an unknown action: 400")
check(plan(Bo).status_code == 400, "a chat plan still needs its prompt")
r = plan(Bo, title="Week plan", prompt="Write the week plan.")
check(r.status_code == 201 and r.json()["action"] == "chat", "a plan without action is a chat plan")
PC = r.json().get("id")
v1s = {x["id"]: x for x in cl.get(V + "/agent/schedules").json()["data"]}
check(v1s.get(PT, {}).get("action") == "triage" and v1s.get(PC, {}).get("action") == "chat", "the agent sees the action of its plans")
r = Bo.post(B + f"/api/agent-schedules/{PT}/run")
check(r.status_code == 409, "Run now with an empty basket: 409 " + r.text[:200])


def due(pid):
    dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"), pid), write=True)


def plan_row(pid):
    return next((x for x in Bo.get(B + f"/api/agents/{CL}/schedules").json()["data"] if x["id"] == pid), {})


dbx("UPDATE agent_schedules SET last_at=NULL, last_state='' WHERE id=?", (PT,), write=True)
due(PT)
q = wait_for(lambda: plan_row(PT).get("last_state") == "empty" and plan_row(PT))
check(q and q["next_at"] and not [e for e in events(cl, "job_request") if e["data"].get("scheduled")], "an empty basket: nothing sent (empty)")
I1 = Bo.post(B + "/api/tasks", json={"title": "Call the printer"}).json()["id"]
I2 = Bo.post(B + "/api/tasks", json={"title": "Invoice for the shoot"}).json()["id"]
HL = Bo.post(B + "/api/lists", json={"name": "Health notes"}).json()["id"]
HOK = Bo.patch(B + f"/api/lists/{HL}", json={"life": "health"}).ok
due(PT)
ev = wait_for(lambda: [e for e in events(cl, "job_request") if e["data"].get("scheduled")])
check(len(ev) == 1 and ev[0]["data"]["kind"] == "triage" and ev[0]["data"]["schedule_id"] == PT, "due: one job_request of kind triage, scheduled " + str(ev)[:300])
inp = ev[0]["data"]["input"] if ev else {}
check(sorted(x["task_id"] for x in inp.get("items", [])) == sorted([I1, I2]) and W in [x["id"] for x in inp.get("lists", [])],
      "the input of the button: the basket items, bob's lists")
check(not HOK or HL not in [x["id"] for x in inp.get("lists", [])], "unattended: never a health list as a target")
check(plan_row(PT).get("last_state") == "sent", "last_state sent")
JT = ev[0]["data"]["job"]["id"] if ev else 0
due(PT)
q = wait_for(lambda: plan_row(PT).get("last_state") == "pending" and plan_row(PT))
check(q and len([e for e in events(cl, "job_request") if e["data"].get("scheduled")]) == 1, "the open proposal is not asked again (pending)")
r = cl.post(V + f"/agent/jobs/{JT}/proposal", json={"items": [{"task_id": I1, "list_id": W}]})
check(r.status_code == 201, "the agent answers with a normal triage proposal " + r.text[:200])
r = Bo.post(B + f"/api/proposals/{JT}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("changed") == 1 and Bo.get(B + f"/api/tasks/{I1}").json()["list_id"] == W, "bob applies the morning card")
due(PC)
ev = wait_for(lambda: [e for e in events(cl, "scheduled_job") if e["data"]["schedule_id"] == PC])
check(len(ev) == 1 and ev[0]["data"]["prompt"] == "Write the week plan.", "a chat plan still sends scheduled_job")
r = Bo.patch(B + f"/api/agent-schedules/{PC}", json={"action": "triage"})
check(r.ok and r.json()["action"] == "triage" and r.json()["prompt"] == "Write the week plan.", "a chat plan can become a triage plan (text kept)")
# 2.126.1 review: a manager of the agent (the instance admin) never sends bob's basket to the agent
r = plan(Bo, title="Status note", prompt="Write the status note.")
PM = r.json().get("id")
check(A.patch(B + f"/api/agent-schedules/{PM}", json={"action": "triage"}).status_code == 403, "a manager cannot turn bob's chat plan into sorting his basket")
check(A.post(B + f"/api/agent-schedules/{PT}/run").status_code == 403, "a manager cannot run bob's triage plan now")

# ================================================================ a person without an organisation
# freelancer-matrix: sheets, agents
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
DA, da = agent("fridabot", owner=FID)
FS, FC, FR = new_sheet(Fl, "private", "Freelance to-dos", [["Send the quote", "", ""], ["Back up the drive", "", ""]])
FL = Fl.post(B + "/api/lists", json={"name": "Freelance"}).json()["id"]
check(Fl.put(B + f"/api/lists/{FL}/members", json={"user_id": DA, "role": "edit"}).ok, "freelancer: her agent in her list")
check(Fl.post(B + f"/api/sheets/{FS}/shares", json={"user_id": DA, "role": "read"}).status_code == 201, "freelancer shares the table with her agent")
check(ta.post(V + "/agent/proposals/sheet-tasks", json={"sheet_id": FS, "rows": [FR[0]], "list_id": FL, "title_col": FC[0]}).status_code == 404,
      "an organisation's agent never reaches her table")
r = da.post(V + "/agent/proposals/sheet-tasks", json={"sheet_id": FS, "rows": [FR[0], FR[1]], "list_id": FL, "title_col": FC[0]})
check(r.status_code == 201, "her agent proposes " + r.text[:300])
FJ = r.json().get("id")
v = Fl.get(B + f"/api/proposals/{FJ}").json()
check(v.get("job", {}).get("user_id") == FID and len(v.get("sheet_rows") or []) == 2, "the card is hers")
r = Fl.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0", "1"]})
check(r.ok and r.json().get("created") == 2, "freelancer applies: two tasks " + r.text[:200])
# her own agent sorts her basket by plan
Fl.post(B + "/api/tasks", json={"title": "Renew the domain"})
r = Fl.post(B + f"/api/agents/{DA}/schedules", json={"title": "Sort", "action": "triage", "freq": "daily", "time": "07:30"})
check(r.status_code == 201 and r.json()["action"] == "triage", "freelancer: a triage plan for her own agent " + r.text[:200])
FP = r.json().get("id")
r = Fl.post(B + f"/api/agent-schedules/{FP}/run")
check(r.ok, "freelancer: Run now " + r.text[:200])
ev = [e for e in events(da, "job_request") if e["data"].get("scheduled")]
check(len(ev) == 1 and ev[0]["data"].get("manual") is True and ev[0]["data"]["requested_by"]["id"] == FID, "her agent got the scheduled triage")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
