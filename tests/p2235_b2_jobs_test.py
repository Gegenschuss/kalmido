#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.235.0 B2 (#2902): the data lock also holds for what a person hands an agent as a proposal job (review finding 1).
 - "Sort the basket" (triage), "Plan my day" (dayplan) and "Break down" (subtasks) of a person without an organisation
   (freelancer-matrix: agents) to their personal agent: the private e-mail (default lock) and a task with a locked tag are
   neither in the event job_request nor in GET /api/v1/agent/jobs/<id>; the plain tasks are (counter-check)
 - a locked task as the job's own task (break down a private e-mail) -> 404; a basket with only locked tasks -> 400
 - a lock set after the request: GET /api/v1/agent/jobs/<id> leaves the newly locked task out
usage: p2235_b2_jobs_test.py <datadir>      (KMT_NOSTART=1 / P2235B2_NOSTART=1: a running server)"""
import json
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, dbx, fresh, setup

V = B + "/api/v1"
fresh(prefix="P2235B2", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)

r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write"]})
check(r.status_code in (200, 201), f"a personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
ags = [a["id"] for a in F.get(B + "/api/proposals/agents").json().get("agents", [])]
check(FA in ags, f"the owner may ask their agent for proposals {ags}")


def task(title, **kw):
    r = F.post(B + "/api/tasks", json={"title": title, **kw})
    check(r.ok, f"task {title}: {r.status_code} {r.text[:120]}")
    return r.json()["id"]


def ask(**b):
    return F.post(B + "/api/proposals", json={"agent_id": FA, **b})


def events():
    return requests.get(V + "/agent/events?since=0&limit=500", headers=FH).json().get("data", [])


def job_text(jid):
    """(the job_request event of job jid, GET /api/v1/agent/jobs/<jid>) as text."""
    ev = [e for e in events() if e["event"] == "job_request" and (e["data"].get("job") or {}).get("id") == jid]
    check(len(ev) == 1, f"job {jid}: one job_request")
    r = requests.get(V + f"/agent/jobs/{jid}", headers=FH)
    check(r.status_code == 200, f"job {jid}: GET {r.status_code} {r.text[:120]}")
    return json.dumps(ev[0]["data"]), json.dumps(r.json())


# ---------------------------------------------------------------- the basket: a plain item, a private e-mail, a tagged one
I_OK = task("ZQXPLAIN call the printer")
I_MAIL = task("ZQXMAIL subject of a private mail", content="ZQXMAIL body")
dbx("UPDATE tasks SET tt_id=? WHERE id=?", ("mail:<zqx-b2@example.com>", I_MAIL))
I_TAG = task("ZQXTAG doctor letter", tags=["Privat"])
r = F.patch(B + f"/api/agents/{FA}/data-lock", json={"tags": ["privat"]})
check(r.status_code == 200, f"lock: tag privat (+ the default e-mail lock) {r.status_code} {r.text[:120]}")

r = ask(kind="triage")
check(r.status_code == 201, f"triage: 201 {r.status_code} {r.text[:200]}")
ev, got = job_text(r.json()["id"])
for where, txt in (("job_request", ev), ("GET /agent/jobs", got)):
    check("ZQXPLAIN" in txt, f"triage {where}: the plain item is there (counter-check)")
    check("ZQXMAIL" not in txt and "ZQXTAG" not in txt, f"triage {where}: no locked item {txt[:300]}")
r = ask(kind="triage", task_ids=[I_MAIL, I_TAG])
check(r.status_code == 400 and "ZQX" not in r.text, f"triage of locked items only: 400 {r.status_code}")

# ---------------------------------------------------------------- the day plan and a breakdown in a project
P = F.post(B + "/api/lists", json={"name": "Open work"}).json()["id"]
D_OK = task("ZQXPLAIN write the offer", list_id=P)
D_MAIL = task("ZQXMAIL answer the landlord", list_id=P)
dbx("UPDATE tasks SET tt_id=? WHERE id=?", ("mail:<zqx-b2b@example.com>", D_MAIL))
D_TAG = task("ZQXTAG private appointment", list_id=P, tags=["privat"])
r = ask(kind="dayplan")
check(r.status_code == 201, f"dayplan: 201 {r.status_code} {r.text[:200]}")
ev, got = job_text(r.json()["id"])
for where, txt in (("job_request", ev), ("GET /agent/jobs", got)):
    check("ZQXPLAIN" in txt, f"dayplan {where}: the plain task is there (counter-check)")
    check("ZQXMAIL" not in txt and "ZQXTAG" not in txt, f"dayplan {where}: no locked task {txt[:300]}")
    check(f'"task_id": {D_MAIL}' not in txt and f'"task_id": {D_TAG}' not in txt, f"dayplan {where}: nor their ids")

PARENT = task("ZQXPLAIN big job", list_id=P)
task("ZQXPLAIN step one", list_id=P, parent_id=PARENT)
task("ZQXTAG secret step", list_id=P, parent_id=PARENT, tags=["Privat"])
r = ask(kind="subtasks", task_id=PARENT)
check(r.status_code == 201, f"subtasks: 201 {r.status_code} {r.text[:200]}")
ev, got = job_text(r.json()["id"])
for where, txt in (("job_request", ev), ("GET /agent/jobs", got)):
    check("step one" in txt and "ZQXTAG" not in txt, f"subtasks {where}: the plain subtask only {txt[:300]}")
r = ask(kind="subtasks", task_id=D_MAIL)
check(r.status_code == 404 and "ZQX" not in r.text, f"break down a private e-mail: 404 {r.status_code}")

# ---------------------------------------------------------------- a lock set later counts for the stored input
I_LATER = task("ZQXLATER becomes private", tags=["later"])
r = ask(kind="triage", task_ids=[I_OK, I_LATER])
check(r.status_code == 201, f"triage before the lock: 201 {r.status_code}")
J = r.json()["id"]
check("ZQXLATER" in requests.get(V + f"/agent/jobs/{J}", headers=FH).text, "before the lock the agent gets it (counter-check)")
check(F.patch(B + f"/api/agents/{FA}/data-lock", json={"tags": ["privat", "later"]}).status_code == 200, "lock: tag later")
txt = requests.get(V + f"/agent/jobs/{J}", headers=FH).text
check("ZQXLATER" not in txt and "ZQXPLAIN" in txt, f"after the lock GET /agent/jobs leaves it out {txt[:300]}")
check("ZQXMAIL" in F.get(B + f"/api/tasks/{I_MAIL}").text, "the owner still sees the e-mail task")

# ---------------------------------------------------------------- finding 2: many locked e-mails (more than inline) stay hidden
r = F.put(B + f"/api/lists/{P}/members", json={"user_id": FA, "role": "edit"})
check(r.ok, f"project shared with the agent {r.status_code} {r.text[:120]}")
dbx("""INSERT INTO tasks(list_id, title, created_by, created_at, updated_at, tt_id)
       SELECT list_id, 'ZQXMANY ' || g, created_by, created_at, updated_at, 'mail:<m' || g || '@example.com>'
       FROM tasks, generate_series(1, 700) g WHERE id=?""", (D_OK,))
MANY = dbx("SELECT id FROM tasks WHERE title LIKE 'ZQXMANY %' ORDER BY id")
check(len(MANY) == 700, f"700 e-mail tasks ({len(MANY)})")
txt = requests.get(V + f"/tasks?list_id={P}", headers=FH).text
check("ZQXPLAIN" in txt and "ZQXMANY" not in txt and "ZQXMAIL" not in txt, f"700 locked e-mails: none in the list {txt[:200]}")
check(requests.get(V + f"/tasks/{MANY[-1][0]}", headers=FH).status_code == 404, "one of them: 404")
r = requests.patch(V + f"/tasks/{MANY[0][0]}", headers=FH, json={"title": "x"})
check(r.status_code == 404, f"a write on one of them: 404 {r.status_code}")
sys.exit(done("p2235_b2_jobs"))
