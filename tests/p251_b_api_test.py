#!/usr/bin/env python3
"""2.51.0 API tests (part B: #1351 "an inquiry becomes a project", #1358 the setup assistant), own container (start.sh).
 - kind inquiry, asked by the person (POST /api/proposals {kind: inquiry, agent_id, text}): the event job_request carries
   the documented input (text, area, project types, office.ok false without the agent's office right, no clients then);
   missing text / unknown field 400
 - the agent's answer: validation (unknown section, a shoot day without a date, end before start, an unknown project type,
   a client id that was not offered, missing tasks) 400; a valid proposal 201
 - applying as the person: ONE step creates the project list (project type, sections, tasks + subtasks, the edited title),
   shoot days as event drafts (status tentative, all-day and timed, an edited date) in the person's own calendar (the
   module "events" switched on); the quotation part is left out while the agent has no office right; counts in the answer
 - undo removes the list, the event drafts and switches the module off again; redo creates it all again; another person
   sees / applies / undoes nothing (404)
 - the agent proposes on its own (POST /api/v1/agent/proposals {kind, user_id, proposal}): a ready proposal + News for the
   person; a person the agent does not work with 404; offer_id without office right 403; setup with offer_id 400
 - kind setup: modules on / off (only real changes), new lists with sections, a first project of a type; applied as the
   person, undo puts the modules back and removes the lists while they are empty (a list with a task stays, named)
 - the quotation part (part A's office/agentdocs.py): skipped when the module is missing in this build
usage: p251_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

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


def q(sql, args=()):
    con = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=30, **k)

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=30, **k)


def events(cl, kind):
    return [e for e in cl.get("/agent/events", params={"since": 0, "limit": 500}).json()["data"] if e["event"] == kind]


def feats(s):
    return set(x for x in (s.get(B + "/api/state").json()["settings"].get("features") or "").split(",") if x)


if not os.environ.get("PK2_SMOKE"):  # PK2_SMOKE=1: against a server that is already up (a quick local check)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "planner", "display_name": "Planner"})
assert r.status_code in (200, 201), r.text
AG, cl = r.json()["id"], Api(r.json()["token"])
W = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent shares a list with alice")
A.patch(B + "/api/settings", json={"features": ",".join(sorted(feats(A) - {"events", "time"}))})
F0 = feats(A)
check("events" not in F0, "setup: events off")

# ================================================================== #1351: the request
r = A.post(B + "/api/proposals", json={"kind": "inquiry", "agent_id": AG})
check(r.status_code == 400, f"inquiry without text: 400 ({r.status_code})")
r = A.post(B + "/api/proposals", json={"kind": "inquiry", "agent_id": AG, "text": "x", "nope": 1})
check(r.status_code == 400, f"inquiry with an unknown field: 400 ({r.status_code})")
MAIL = "Hello, we need an image film, two shoot days in May, budget about 10k. Regards, Example Ltd (info@example.com)"
r = A.post(B + "/api/proposals", json={"kind": "inquiry", "agent_id": AG, "text": MAIL, "file_name": "inquiry.eml"})
check(r.status_code == 201, f"inquiry request: 201 ({r.status_code} {r.text[:200]})")
J = r.json()["id"]
ev = [e for e in events(cl, "job_request") if e["data"]["job"]["id"] == J]
check(len(ev) == 1, "the agent got job_request")
inp = ev[0]["data"]["input"] if ev else {}
check(inp.get("text") == MAIL and inp.get("file_name") == "inquiry.eml", "input: the text the person sent")
check(inp.get("office", {}).get("ok") is False and inp.get("clients") == [], f"input: no office right -> no office data ({inp.get('office')})")
check("agency" in (inp.get("project_types") or []) and inp.get("area") == "private", f"input: project types + area ({inp.get('area')})")

GOOD = {"kind": "inquiry", "summary": "Image film for Example Ltd", "name": "Image film Example", "project_type": "agency",
        "client": {"name": "Example Ltd"}, "sections": ["Prep", "Shoot"],
        "tasks": [{"title": "Call back the client", "section": "Prep", "due": "2027-05-01"},
                  {"title": "Location scout", "section": "Prep", "subtasks": [{"title": "Ask for the permit"}]},
                  {"title": "Shoot", "section": "Shoot", "depends_on": [1]}],
        "shoot_days": [{"title": "Shoot day 1", "date": "2027-05-10", "location": "Studio"},
                       {"title": "Shoot day 2", "date": "2027-05-11", "start_time": "08:00", "end_time": "18:00"}],
        "offer": {"title": "Image film", "items": [{"text": "Camera day", "qty": 2, "unit": "day", "price": 900},
                                                   {"text": "Edit", "qty": 3, "unit": "day", "price": 650, "discount": 10}]}}


def bad(patch, what):
    b = {**GOOD, **patch}
    r = cl.post(f"/agent/jobs/{J}/proposal", json=b)
    check(r.status_code == 400, f"invalid proposal ({what}): 400 ({r.status_code} {r.text[:120]})")


bad({"tasks": [{"title": "x", "section": "Nope"}]}, "unknown section")
bad({"shoot_days": [{"title": "x"}]}, "shoot day without a date")
bad({"shoot_days": [{"title": "x", "date": "2027-05-10", "start_time": "10:00", "end_time": "09:00"}]}, "end before start")
bad({"project_type": "rocket"}, "unknown project type")
bad({"client": {"id": 99999}}, "a client id that was not offered")
bad({"tasks": []}, "no tasks")
bad({"offer": {"items": [{"text": "x", "qty": -1}]}}, "negative quantity")
bad({"shoot_days": [{"title": "x", "date": "2027-05-10", "crew": ["bob"]}]}, "unknown field")
r = cl.post(f"/agent/jobs/{J}/proposal", json=GOOD)
check(r.status_code == 201, f"valid inquiry proposal: 201 ({r.status_code} {r.text[:300]})")

v = A.get(B + f"/api/proposals/{J}").json()
check(v.get("state") == "ready" and v["proposal"]["project_type"] == "agency" and len(v["proposal"]["shoot_days"]) == 2,
      "the person sees the ready proposal")
check(v["proposal"]["client"] == {"id": None, "name": "Example Ltd"}, "a client name stays a suggestion")
check(Bo.get(B + f"/api/proposals/{J}").status_code == 404, "another person: 404")
check(Bo.post(B + f"/api/proposals/{J}/apply", json={"select": ["0"]}).status_code == 404, "another person cannot apply")

SEL = ["0", "1", "1.0", "2", "300", "301", "400", "400.0", "400.1"]
r = A.post(B + f"/api/proposals/{J}/apply", json={"select": SEL, "name": "Image film 2027",
                                                    "edits": {"0": {"title": "Call back Example"}, "301": {"due": "2027-05-12"}}})
check(r.status_code == 200, f"apply: 200 ({r.status_code} {r.text[:300]})")
res = r.json() if r.ok else {}
LID = res.get("list_id")
check(res.get("created") == 4 and res.get("events") == 2 and res.get("offer_id") is None, f"apply counts: {res}")
lst = q("SELECT * FROM lists WHERE id=?", (LID,))
check(lst and lst[0]["name"] == "Image film 2027" and lst[0]["kind"] == "project" and lst[0]["ptype"] == "agency"
      and lst[0]["owner_id"] == ALICE and lst[0]["org_id"] is None, f"the project list ({dict(lst[0]) if lst else None})")
secs = [r_[0] for r_ in q("SELECT name FROM sections WHERE list_id=? ORDER BY sort", (LID,))]
check(secs == ["Prep", "Shoot"], f"the proposed sections only (not the type's standard ones): {secs}")
ts = q("SELECT title, created_by, parent_id FROM tasks WHERE list_id=? ORDER BY id", (LID,))
check([t["title"] for t in ts] == ["Call back Example", "Location scout", "Ask for the permit", "Shoot"], f"tasks: {[t['title'] for t in ts]}")
check(all(t["created_by"] == ALICE for t in ts), "tasks: created as the person")
check(len(q("SELECT 1 FROM task_deps d JOIN tasks t ON t.id=d.task_id WHERE t.list_id=?", (LID,))) == 1, "the dependency")
evs = q("SELECT e.title, e.status, e.all_day, e.start, e.\"end\", e.location, c.owner_id FROM events e JOIN ev_cals c ON c.id=e.cal_id "
        "WHERE e.deleted_at IS NULL ORDER BY e.start")
check(len(evs) == 2 and all(e["status"] == "tentative" and e["owner_id"] == ALICE for e in evs), f"event drafts (tentative, own calendar): {evs}")
check(evs and evs[0]["all_day"] == 1 and evs[0]["start"] == "2027-05-10" and evs[0]["location"] == "Studio", "all-day shoot day")
check(len(evs) > 1 and evs[1]["start"] == "2027-05-12T08:00" and evs[1]["end"] == "2027-05-12T18:00", "timed shoot day, edited date")
check("events" in feats(A), "the calendar module was switched on")
ap = [e for e in events(cl, "job") if e["data"]["job"]["id"] == J]
check(ap and ap[-1]["data"]["proposal"]["state"] == "applied" and ap[-1]["data"]["proposal"].get("project_list_id") == LID, "the agent hears: applied + list")
check(A.post(B + f"/api/proposals/{J}/apply", json={"select": SEL}).status_code == 409, "apply twice: 409")

check(Bo.post(B + f"/api/proposals/{J}/undo").status_code == 404, "another person cannot undo")
r = A.post(B + f"/api/proposals/{J}/undo")
check(r.ok and r.json().get("undone", 0) >= 6, f"undo: {r.status_code} {r.text[:200]}")
check(not q("SELECT 1 FROM lists WHERE id=?", (LID,)), "undo: the clean project is gone")
check(not q("SELECT 1 FROM events WHERE deleted_at IS NULL"), "undo: the event drafts are gone")
check("events" not in feats(A), "undo: the module is off again")
r = A.post(B + f"/api/proposals/{J}/redo")
check(r.ok and r.json().get("list_id") and r.json()["list_id"] != LID, f"redo: a new project ({r.text[:200]})")
LID2 = r.json().get("list_id") if r.ok else None
check(len(q("SELECT 1 FROM tasks WHERE list_id=?", (LID2,))) == 4 and len(q("SELECT 1 FROM events WHERE deleted_at IS NULL AND status='tentative'")) == 2,
      "redo: tasks and event drafts again")
# undo after someone added a task: the list stays, the proposal's tasks go to the trash, the drafts go
A.post(B + "/api/tasks", json={"title": "my own", "list_id": LID2})
r = A.post(B + f"/api/proposals/{J}/undo")
check(r.ok and q("SELECT 1 FROM lists WHERE id=?", (LID2,)), f"undo with an own task: the list stays ({r.text[:120]})")
check(len(q("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (LID2,))) == 1, "undo: only the own task is left")
check(not q("SELECT 1 FROM events WHERE deleted_at IS NULL"), "undo: drafts gone")
r = A.post(B + f"/api/proposals/{J}/redo")
check(r.ok and len(q("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (LID2,))) == 5
      and len(q("SELECT 1 FROM events WHERE deleted_at IS NULL")) == 2, f"redo: tasks restored, drafts back ({r.text[:120]})")

# ================================================================== the agent proposes on its own (chat)
OWN = {k: GOOD[k] for k in ("name", "sections", "tasks", "shoot_days")}
r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": BOB, "proposal": OWN})
check(r.status_code == 404, f"a person the agent does not work with: 404 ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "offer_id": 1, "proposal": OWN})
check(r.status_code in (403, 404), f"offer_id without an office right: refused ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "setup", "user_id": ALICE, "offer_id": 1, "proposal": {"modules": [{"key": "time", "on": True}]}})
check(r.status_code == 400, f"setup with offer_id: 400 ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "title": "Inquiry from the chat", "proposal": {**OWN, "nope": 1}})
check(r.status_code == 400, f"unknown field in an own proposal: 400 ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "title": "Inquiry from the chat", "proposal": OWN})
check(r.status_code == 201 and r.json().get("prop_state", r.json().get("proposal") and "ready"), f"own inquiry proposal: 201 ({r.status_code} {r.text[:200]})")
J2 = r.json().get("id") if r.ok else None
v = A.get(B + f"/api/proposals/{J2}").json()
check(v.get("state") == "ready" and v.get("kind") == "inquiry", "the person sees it as a ready proposal")
check(any(n["kind"] == "proposal" and n["data"].get("job") == J2 for n in A.get(B + "/api/news").json()["items"]), "News: proposal ready")
check(A.post(B + f"/api/proposals/{J2}/discard").ok, "discard")
check(any(e["data"]["job"]["id"] == J2 and e["data"]["proposal"]["state"] == "discarded" for e in events(cl, "job")), "the agent hears: discarded")

# ================================================================== #1358: setup
A.patch(B + "/api/settings", json={"features": ",".join(sorted((feats(A) | {"habits"}) - {"time", "kanban"}))})
F1 = feats(A)
r = cl.post("/agent/proposals", json={"kind": "setup", "user_id": ALICE, "proposal": {"modules": [{"key": "rocket", "on": True}]}})
check(r.status_code == 400, f"setup: unknown module 400 ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "setup", "user_id": ALICE, "proposal": {"modules": [{"key": "habits", "on": True}]}})
check(r.status_code == 400, f"setup: nothing changes 400 ({r.status_code})")
SET = {"summary": "For a small video agency", "modules": [{"key": "time", "on": True}, {"key": "habits", "on": False}, {"key": "cal", "on": "cal" in F1}],
       "lists": [{"name": "Leads", "color": "#a855f7", "sections": ["New", "Contacted"]}, {"name": "Admin"}],
       "project": {"type": "software", "name": "Website"}}
r = cl.post("/agent/proposals", json={"kind": "setup", "user_id": ALICE, "proposal": SET})
check(r.status_code == 201, f"setup proposal: 201 ({r.status_code} {r.text[:300]})")
J3 = r.json().get("id") if r.ok else None
p = r.json().get("proposal", {}) if r.ok else {}
check(len(p.get("modules", [])) == 2, f"setup: only real module changes kept ({p.get('modules')})")
r = A.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0", "1", "100", "101", "200"], "edits": {"101": {"title": "Office"}}})
check(r.ok, f"setup apply: {r.status_code} {r.text[:200]}")
f2 = feats(A)
check("time" in f2 and "habits" not in f2, f"setup: modules switched ({f2 - F1}, {F1 - f2})")
check("kanban" in f2, "setup: the project type's modules on")
names = {r_["name"]: r_["id"] for r_ in q("SELECT id, name FROM lists WHERE owner_id=? AND deleted_at IS NULL", (ALICE,))} \
    if q("SELECT 1 FROM information_schema.columns WHERE table_name='lists' AND column_name='deleted_at'") else \
    {r_["name"]: r_["id"] for r_ in q("SELECT id, name FROM lists WHERE owner_id=?", (ALICE,))}
check({"Leads", "Office", "Website"} <= set(names), f"setup: lists + project created ({sorted(names)})")
check([r_[0] for r_ in q("SELECT name FROM sections WHERE list_id=? ORDER BY sort", (names.get("Leads"),))] == ["New", "Contacted"], "setup: sections")
check(q("SELECT ptype FROM lists WHERE id=?", (names.get("Website"),))[0][0] == "software", "setup: project type")
A.post(B + "/api/tasks", json={"title": "first lead", "list_id": names.get("Leads")})
r = A.post(B + f"/api/proposals/{J3}/undo")
check(r.ok and "Leads" in (r.json().get("skipped") or []), f"setup undo: a used list stays, named ({r.text[:200]})")
check(feats(A) == F1, f"setup undo: modules back ({feats(A) ^ F1})")
check(q("SELECT 1 FROM lists WHERE id=?", (names.get("Leads"),)) and not q("SELECT 1 FROM lists WHERE id=?", (names.get("Office"),))
      and not q("SELECT 1 FROM lists WHERE id=?", (names.get("Website"),)), "setup undo: the empty lists are gone")
r = A.post(B + f"/api/proposals/{J3}/redo")
check(r.ok and "time" in feats(A), f"setup redo: modules again ({r.text[:120]})")
check(Bo.get(B + f"/api/proposals/{J3}").status_code == 404, "setup: another person 404")
# asked by the person
r = A.post(B + "/api/proposals", json={"kind": "setup", "agent_id": AG, "text": "I run a small video agency"})
check(r.status_code == 201, f"setup request: 201 ({r.status_code} {r.text[:200]})")
ev = [e for e in events(cl, "job_request") if e["data"]["job"]["id"] == (r.json().get("id") if r.ok else 0)]
check(ev and ev[0]["data"]["input"].get("text") == "I run a small video agency" and len(ev[0]["data"]["input"].get("modules", [])) > 20
      and "lists" not in ev[0]["data"]["input"], "setup input: text + modules, no list names")

# ================================================================== the quotation part (part A's office switches)
if not os.path.exists(os.path.join(N, "..", "kalmido", "office", "agentdocs.py")) and not os.environ.get("PK2_OFFICE"):
    print("SKIP: office/agentdocs.py (part A) not in this build: quotation part not tested", flush=True)
else:
    O = B + "/api/office"
    A.patch(B + "/api/settings", json={"features": ",".join(sorted(feats(A) | {"office", "clients"}))})
    A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
    r = A.post(B + "/api/my/agents", json={"username": "officeplanner", "display_name": "Office Planner", "scopes": ["write", "office"]})
    check(r.status_code == 201, f"office: a personal agent ({r.status_code} {r.text[:120]})")
    PAG, pcl = r.json()["id"], Api(r.json()["token"])
    A.put(B + f"/api/lists/{W}/members", json={"user_id": PAG, "role": "edit"})
    A.get(O + "/settings")  # the personal office
    CLP = A.post(B + "/api/clients", json={"name": "Example Ltd"}).json()["id"]
    OWN2 = {**{k: GOOD[k] for k in ("name", "sections", "tasks", "shoot_days", "offer")}, "client": {"name": "example ltd"}}
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "proposal": OWN2})
    check(r.status_code == 201 and r.json()["input"]["office"]["ok"] is False and r.json()["input"]["clients"] == [],
          f"office: switches off -> no office data, the quotation not possible ({r.status_code} {r.text[:160]})")
    JX = r.json().get("id")
    check(A.get(B + f"/api/proposals/{JX}").json()["input"]["office"]["ok"] is False, "office: the dialog knows the quotation is not possible")
    check(A.patch(O + f"/agents/{PAG}", json={"office_drafts": True}).ok, "office: the agent's switch on")
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "proposal": OWN2})
    check(r.status_code == 201 and r.json()["input"]["office"] == {"ok": False, "reason": "privacy_off"}, f"office: privacy switch still off ({r.text[:160]})")
    check(A.put(O + "/settings", json={"agents_read": 1}).ok, "office: the privacy switch on")
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "proposal": OWN2})
    check(r.status_code == 201 and r.json()["input"]["office"]["ok"] is True and [x["id"] for x in r.json()["input"]["clients"]] == [CLP],
          f"office: both switches on -> the area's clients ({r.text[:200]})")
    JO = r.json().get("id")
    check(cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "proposal": {**OWN2, "client": {"id": CLP}}}).status_code == 400,
          "office: another agent (no office right) cannot name the client id")
    r = A.post(B + f"/api/proposals/{JO}/apply", json={"select": ["0", "300", "400", "400.0", "400.1"]})
    check(r.ok and r.json().get("offer_id"), f"office: apply creates the quotation draft ({r.text[:200]})")
    OFF = r.json().get("offer_id") if r.ok else None
    PL = r.json().get("list_id") if r.ok else None
    d = q("SELECT status, number, agent_id, list_id, client_id FROM office_docs WHERE id=?", (OFF,))
    check(d and d[0]["status"] == "draft" and d[0]["number"] == "" and d[0]["agent_id"] == PAG and d[0]["list_id"] == PL and d[0]["client_id"] == CLP,
          f"office: a draft without a number, by the agent, bound to the project and the client ({[dict(x) for x in d]})")
    check(q("SELECT client_id FROM lists WHERE id=?", (PL,))[0][0] == CLP, "office: the client name found the existing client")
    check(len(q("SELECT 1 FROM office_doc_items WHERE doc_id=?", (OFF,))) == 2, "office: two items")
    lg = [x["action"] for x in q("SELECT action FROM office_doc_log WHERE user_id=? ORDER BY id", (PAG,))]
    check("agent_read" in lg and "agent_write" in lg, f"office: the access log names the agent ({lg})")
    r = A.post(B + f"/api/proposals/{JO}/undo")
    check(r.ok and not q("SELECT 1 FROM office_docs WHERE id=?", (OFF,)), f"office: undo removes the draft ({r.text[:120]})")
    r = A.post(B + f"/api/proposals/{JO}/redo")
    check(r.ok and q("SELECT 1 FROM office_docs WHERE status='draft' AND agent_id=? AND list_id=?", (PAG, r.json().get("list_id"))), "office: redo drafts it again")
    # an accepted quotation becomes a project (with a deal of the pipeline)
    DL = A.post(O + "/deals", json={"title": "Image film", "client_id": CLP, "value": 5000}).json()
    QD = A.post(O + f"/deals/{DL['id']}/offer").json().get("doc_id")
    A.put(O + f"/docs/{QD}", json={"items": [{"kind": "service", "title": "Camera day", "qty": 2, "unit": "day", "rate": 900}]})
    for st_ in ("sent", "accepted"):
        A.post(O + f"/docs/{QD}/status", json={"status": st_})
    acc = [e for e in events(pcl, "offer_accepted") if e["data"].get("doc_id") == QD]
    check(len(acc) == 1, "office: the agent hears offer_accepted")
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "offer_id": QD, "proposal": OWN2})
    check(r.status_code == 400, f"office: an accepted quotation gets no new one ({r.status_code})")
    FROM = {"name": "Image film (accepted)", "sections": [], "tasks": [{"title": "Camera day"}], "shoot_days": [{"title": "Camera day 1", "date": "2027-06-01"}]}
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "offer_id": QD, "proposal": FROM})
    check(r.status_code == 201 and r.json()["input"]["offer"]["id"] == QD and r.json()["proposal"]["client"]["id"] == CLP,
          f"office: the project from the accepted quotation takes its client ({r.text[:200]})")
    JA = r.json().get("id")
    r = A.post(B + f"/api/proposals/{JA}/apply", json={"select": ["0", "300"]})
    PA = r.json().get("list_id") if r.ok else None
    check(r.ok and q("SELECT list_id FROM office_deals WHERE id=?", (DL["id"],))[0][0] == PA, f"office: the deal gets the project ({r.text[:120]})")
    A.post(B + f"/api/proposals/{JA}/undo")
    check(q("SELECT list_id FROM office_deals WHERE id=?", (DL["id"],))[0][0] is None, "office: undo unbinds the deal")
    r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "offer_id": QD, "proposal": FROM})
    check(r.status_code == 403, f"office: an agent without the office right never reads the quotation ({r.status_code})")
    A.put(O + "/settings", json={"agents_read": 0})
    r = pcl.post("/agent/proposals", json={"kind": "inquiry", "user_id": ALICE, "offer_id": QD, "proposal": FROM})
    check(r.status_code == 403, f"office: privacy switch off again -> 403 ({r.status_code})")

# ================================================================== 2.51.0 review fixes (negative tests)
# #1351 review 6: the mode "all" never reaches a person who shares no list with the agent
check(A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "all"}).ok, "review 6: proposals mode all")
r = cl.post("/agent/proposals", json={"kind": "setup", "user_id": BOB, "proposal": {"modules": [{"key": "habits", "on": True}]}})
check(r.status_code == 404, f"review 6: mode all, setup for a person without a shared list: 404 ({r.status_code})")
r = cl.post("/agent/proposals", json={"kind": "inquiry", "user_id": BOB, "proposal": OWN})
check(r.status_code == 404, f"review 6: mode all, inquiry for a person without a shared list: 404 ({r.status_code})")
A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "shared"})


print(f"p251_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
