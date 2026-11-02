#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.0 C (#3370): one-way steps, decisions, the acceptance task, own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks, lists
 - the mark: PATCH /api/v1/tasks/{id} {irreversible: {reason}} by an agent with write access, GET shows it, a new reason takes
   the yes back, the same reason does not; an agent cannot take a mark off, a member without approver rights neither (switch on)
 - the gates, only with the list's switch on (default off: nothing changes): deploy blocks on open marked tasks, skip_checklist
   passes the checklist but not those, the suggestion and the event's gate name them (for an agent only what it sees); an
   integrate request on its own task, also when completed
 - the yes: POST /api/tasks/{id}/irreversible-yes only for approvers, never the assignee alone, never an agent, logged
 - decisions: API + session, supersedes (the old one stays readable), in get_task, the event decision_added (another agent's
   text marked untrusted), a stranger 404, a task the agent does not see no event; a list with the lock: 409, no plain text,
   a list that gets the lock keeps no reason or decision text
 - the account export carries the decisions
 - the acceptance task: off by default; on: one task per environment and version, assigned to the owner, closed tasks as
   subtasks, again after an undone deployment no second one, deployed carries its id; a webhook without a user too
 - a person without an organisation: her own list, agent, yes, decision, acceptance task
usage: p2392_c_api_test.py <datadir>"""
import base64
import json
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import check, B, dbx, H, done  # noqa: E402

V = B + "/api/v1"


def hdr(tok):
    return {"Authorization": "Bearer " + tok, **H}


def agent(s, name, lid, role="edit"):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments", "delete"]})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": role}).ok
    return aid, hdr(s.post(B + f"/api/my/agents/{aid}/token").json()["token"])


def events(h, event):
    rows = requests.get(V + "/agent/events", headers=h, params={"since": 0, "limit": 500}).json()
    rows = rows.get("data", rows.get("events", [])) if isinstance(rows, dict) else rows
    return [e for e in rows if e.get("event") == event]


def task(s, lid, title):
    return s.post(B + "/api/tasks", json={"title": title, "list_id": lid}).json()["id"]


def ask(h, tid, kind):
    sg = {"kind": kind, "evidence": "tests green", "summary": "x"}
    if kind == "integrate":
        sg["source"] = "feat/x"
    return requests.post(V + f"/tasks/{tid}/comments", headers=h, json={"body": "Ready", "suggestion": sg})


kt.fresh()
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")  # a person without an organisation is the main case here: everything below runs in her own list
GU, G = freelancer(B, A, "gert")
XU, X = freelancer(B, A, "xena")  # a stranger
L = F.post(B + "/api/lists", json={"name": "Release", "kind": "project", "ptype": "software"}).json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": GU, "role": "edit"}).ok, "setup: a member without approver rights")
AID, AH = agent(F, "fridabot", L)

# ================================================================== the mark
T1, T2 = task(F, L, "Drop the old column"), task(F, L, "Plain work")
check(requests.get(V + f"/tasks/{T1}", headers=AH).json().get("irreversible") is None, "not marked by default")
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"irreversible": {"reason": "Migration without a way back"}})
check(r.ok and r.json()["irreversible"]["reason"] == "Migration without a way back", "an agent with write access marks a task " + r.text[:200])
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"irreversible": {"why": "x"}})
check(r.status_code == 400, "an unknown part of the mark: 400")
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"irreversible": None})
check(r.status_code == 403 and requests.get(V + f"/tasks/{T1}", headers=AH).json()["irreversible"], "an agent cannot take the mark off")
check(any(a["kind"] == "irreversible" for a in F.get(B + f"/api/tasks/{T1}/timeline").json()["activity"]), "the mark stands in the history")

# ================================================================== the gates: switch off = nothing changes
D0 = ask(AH, T2, "deploy")
check(D0.status_code == 201 and "irreversible" not in D0.json()["suggestion"], "switch off: a deploy request names nothing")
r = F.post(B + f"/api/comments/{D0.json()['id']}/decide", json={"decision": "approve"})
check(r.ok and r.json()["state"] == "approved", "switch off: approved although a task is marked " + r.text[:200])
r = F.patch(B + f"/api/lists/{L}", json={"irreversible_needs_yes": True})
check(r.ok, "the owner switches it on " + r.text[:200])
check(requests.get(V + f"/lists/{L}", headers=AH).json().get("irreversible_needs_yes") is True, "the API shows the switch")
r = requests.patch(V + f"/lists/{L}", headers=AH, json={"irreversible_needs_yes": False})
check(r.status_code in (400, 403), "an agent cannot switch it off")

# ================================================================== deploy: blocked, no skip passes
D1 = ask(AH, T2, "deploy")
check([x["id"] for x in D1.json()["suggestion"].get("irreversible", [])] == [T1], "the deploy request names the marked task " + D1.text[:300])
CID = D1.json()["id"]
r = F.post(B + f"/api/comments/{CID}/decide", json={"decision": "approve", "skip_checklist": True})
check(r.ok and r.json()["state"] == "blocked" and r.json()["suggestion"]["state"] == "open", "skip_checklist does not pass " + r.text[:200])
check(r.json()["suggestion"]["irreversible"][0]["reason"] == "Migration without a way back", "the suggestion names task and reason")
r = F.post(B + f"/api/comments/{CID}/react", json={"emoji": "up"})
st = json.loads(dbx("SELECT suggestion FROM comments WHERE id=?", (CID,))[0][0])
check(st["state"] == "open", "a thumbs up does not pass either")
sg = next(k for k in F.get(B + f"/api/tasks/{T2}/timeline").json()["comments"] if k["id"] == CID)["suggestion"]
check([x["id"] for x in sg["irreversible"]] == [T1], "the timeline shows what blocks")
check(F.get(B + f"/api/tasks/{T1}/timeline").json()["may_yes"] is True, "the owner may give the yes")

# ================================================================== the review: an agent cannot make the marked task go away
L3 = F.post(B + "/api/lists", json={"name": "Elsewhere", "kind": "project"}).json()["id"]
check(F.put(B + f"/api/lists/{L3}/members", json={"user_id": AID, "role": "edit"}).ok, "setup: the agent may write in a list without the switch")
r = requests.post(V + f"/tasks/{T1}/complete", headers=AH)
check(r.status_code == 409, f"an agent cannot complete it {r.status_code} {r.text[:150]}")
r = requests.delete(V + f"/tasks/{T1}", headers=AH)
check(r.status_code == 409, f"... nor trash it {r.status_code} {r.text[:150]}")
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"list_id": L3})
check(r.status_code == 409, f"... nor move it out {r.status_code} {r.text[:150]}")
r = requests.post(V + "/tasks/batch", headers=AH, json={"action": "delete", "ids": [T1]})
check(dbx("SELECT list_id, deleted_at, completed_at FROM tasks WHERE id=?", (T1,)) == [(L, None, None)], f"... nor by batch: the task is where it was {r.text[:150]}")

# ================================================================== the yes
check(G.post(B + f"/api/tasks/{T1}/irreversible-yes").status_code == 403, "a member without approver rights: 403")
F.patch(B + f"/api/tasks/{T1}", json={"assignee_id": GU})
check(G.post(B + f"/api/tasks/{T1}/irreversible-yes").status_code == 403, "the assignee alone: 403")
check(G.delete(B + f"/api/tasks/{T1}/irreversible").status_code == 403, "with the switch on a member cannot take the mark off")
check(requests.post(B + f"/api/tasks/{T1}/irreversible-yes", headers=AH).status_code in (401, 403, 404), "never an agent")
check(X.post(B + f"/api/tasks/{T1}/irreversible-yes").status_code == 404, "a stranger: 404")
check(F.post(B + f"/api/tasks/{T2}/irreversible-yes").status_code == 409, "a task without a mark: 409")
r = F.post(B + f"/api/tasks/{T1}/irreversible-yes")
check(r.ok and r.json()["irreversible"]["yes_by"] == FU and r.json()["irreversible"]["yes_at"], "the owner's yes " + r.text[:200])
check(any(a["kind"] == "irreversible_yes" and a["user_id"] == FU for a in F.get(B + f"/api/tasks/{T1}/timeline").json()["activity"]), "the yes is logged")
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"irreversible": {"reason": "Migration without a way back"}})
check(r.json()["irreversible"]["yes_at"], "the same reason keeps the yes")
r = requests.patch(V + f"/tasks/{T1}", headers=AH, json={"irreversible": {"reason": "Also drops the backup"}})
check(not r.json()["irreversible"]["yes_at"], "a new reason takes the yes back")
r = F.post(B + f"/api/comments/{CID}/decide", json={"decision": "approve", "skip_checklist": True})
check(r.json()["state"] == "blocked", "without the yes still blocked")
F.post(B + f"/api/tasks/{T1}/irreversible-yes")
r = F.post(B + f"/api/comments/{CID}/decide", json={"decision": "approve"})
check(r.ok and r.json()["state"] == "approved" and "irreversible" not in r.json()["suggestion"], "with the yes approved " + r.text[:200])
ev = [e for e in events(AH, "reaction") if (e["data"].get("gate") or {}).get("state") == "approved"]
check(bool(ev), "the agent hears the approval")

# the event's gate names the tasks, for an agent only what it sees (a participant agent)
T3 = task(F, L, "Delete the archive")
requests.patch(V + f"/tasks/{T3}", headers=AH, json={"irreversible": {"reason": "Gone for good"}})
TI = task(F, L, "Open the new door")
r = ask(AH, TI, "integrate")
check("irreversible" not in r.json()["suggestion"], "integrate: another task's mark does not block")
check(F.post(B + f"/api/comments/{r.json()['id']}/decide", json={"decision": "approve"}).json()["state"] == "approved", "integrate on an unmarked task passes")
requests.patch(V + f"/tasks/{TI}", headers=AH, json={"irreversible": {"reason": "One way"}})
r = ask(AH, TI, "integrate")
ICID = r.json()["id"]
check([x["id"] for x in r.json()["suggestion"]["irreversible"]] == [TI], "integrate: its own marked task blocks")
F.post(B + f"/api/tasks/{TI}/complete")
r = F.post(B + f"/api/comments/{ICID}/decide", json={"decision": "approve"})
check(r.json()["state"] == "blocked", "completing the task does not open the integrate gate " + r.text[:200])
F.post(B + f"/api/tasks/{TI}/reopen")
F.post(B + f"/api/tasks/{TI}/irreversible-yes")
check(F.post(B + f"/api/comments/{ICID}/decide", json={"decision": "approve"}).json()["state"] == "approved", "with the yes the integrate request passes")

# ================================================================== decisions
r = requests.post(V + f"/tasks/{T2}/decisions", headers=AH, json={"text": "Keep the old endpoint for now"})
check(r.status_code == 201 and r.json()["by_id"] == AID and r.json()["by_agent"], "an agent records a decision " + r.text[:200])
D_1 = r.json()["id"]
check(F.get(B + f"/api/tasks/{T2}/timeline").json()["decisions"][0]["id"] == D_1, "the timeline carries the decisions")
ev = [e for e in events(AH, "decision_added")]
check(not ev, "the agent does not hear its own decision")
r = F.post(B + f"/api/tasks/{T2}/decisions", json={"text": "Drop it with the next version", "supersedes": D_1})
check(r.status_code == 201, "a person's decision replaces it " + r.text[:200])
D_2 = r.json()["id"]
ds = requests.get(V + f"/tasks/{T2}/decisions", headers=AH).json()["data"]
check([d["id"] for d in ds] == [D_1, D_2] and ds[0]["superseded_by"] == D_2 and ds[0]["text"] == "Keep the old endpoint for now", "the old one stays readable")
check([d["id"] for d in requests.get(V + f"/tasks/{T2}", headers=AH).json()["decisions"]] == [D_1, D_2], "get_task carries them")
ev = events(AH, "decision_added")
check(ev and ev[-1]["data"]["decision"]["id"] == D_2 and not ev[-1]["data"]["decision"].get("untrusted") and
      [d["id"] for d in ev[-1]["data"]["task"]["decisions"]] == [D_2], "the event decision_added with those in force")
check(F.post(B + f"/api/tasks/{T2}/decisions", json={"text": "Again", "supersedes": D_1}).status_code == 400, "a superseded one cannot be replaced twice")
check(F.post(B + f"/api/tasks/{T1}/decisions", json={"text": "Wrong task", "supersedes": D_2}).status_code == 400, "only decisions of the task")
check(F.post(B + f"/api/tasks/{T2}/decisions", json={"text": "  "}).status_code == 400, "an empty decision: 400")
check(X.get(B + f"/api/tasks/{T2}/decisions").status_code == 404, "a stranger: 404")
check(X.post(B + f"/api/tasks/{T2}/decisions", json={"text": "No"}).status_code == 404, "a stranger writes nothing")
r = F.get(B + f"/api/tasks/{T2}/timeline").json()
check(any(a["kind"] == "decision" for a in r["activity"]), "a decision stands in the history")

check("Drop it with the next version" in F.get(B + "/api/export.json").text, "the export of my data carries the decisions")

# trash + delete: the row goes with its task
F.delete(B + f"/api/tasks/{T2}")
check(F.post(B + f"/api/tasks/{T2}/decisions", json={"text": "Late"}).status_code == 409, "a task in the trash takes none")
F.post(B + f"/api/tasks/{T2}/restore")

# ================================================================== the lock
def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(48)}, separators=(",", ":"))


LK = F.post(B + "/api/lists", json={"name": "Locked"}).json()["id"]
TK = task(F, LK, "Secret")
F.put(B + f"/api/tasks/{TK}/irreversible", json={"reason": "plain reason"})
r = F.post(B + f"/api/tasks/{TK}/decisions", json={"text": "plain decision"})
check(r.status_code == 201, "before the lock: a decision")
assert F.put(B + "/api/e2e/keys", json={"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
                                        "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
                                        "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}).ok
r = F.post(B + f"/api/lists/{LK}/e2e/start", json={"keys": [{"user_id": FU, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
check(r.ok, "the lock starts " + r.text[:200])
j = F.get(B + f"/api/lists/{LK}/e2e/todo").json()
out = {"tasks": [{"id": x["id"], **{k: ct(j["gen"]) for k, v in x.items() if k != "id" and v is not None}} for x in j["tasks"]]}
check(F.post(B + f"/api/lists/{LK}/e2e/bulk", json=out).ok, "the texts encrypted")
r = F.post(B + f"/api/lists/{LK}/e2e/finish")
check(r.ok, "the lock is on " + r.text[:200])
row = dbx("SELECT irreversible, irreversible_reason FROM tasks WHERE id=?", (TK,))[0]
txt = dbx("SELECT text, by_id FROM task_decisions WHERE task_id=?", (TK,))
check(row[0] == 1 and row[1] == "", f"the mark stays, its reason goes {row[:2]}")
check(len(txt) == 1 and txt[0][0] != "plain decision" and txt[0][1] == FU, "the decision keeps who and when, not its text")
check(F.post(B + f"/api/tasks/{TK}/decisions", json={"text": "Plain"}).status_code == 409, "a locked list takes no decision")
check(F.put(B + f"/api/tasks/{TK}/irreversible", json={"reason": "Plain"}).status_code == 409, "a locked list takes no reason")
check(F.put(B + f"/api/tasks/{TK}/irreversible", json={"reason": ""}).ok, "the mark without a reason stays possible")
check(len(dbx("SELECT 1 FROM task_decisions WHERE task_id=?", (TK,))) == 1, "nothing stored in plain")

# ================================================================== the acceptance task
E = F.post(B + f"/api/lists/{L}/envs", json={"name": "Live", "auto_close": True}).json()
check(E.get("acceptance_task") is False, "off by default")
MS = F.post(B + "/api/tasks", json={"title": "2.5", "list_id": L, "ms": 1}).json()["id"]
TA, TB = task(F, L, "Feature one"), task(F, L, "Feature two")
for t in (TA, TB):
    F.patch(B + f"/api/tasks/{t}", json={"milestone_id": MS})
r = F.post(B + f"/api/envs/{E['id']}/deploy", json={"version": "1.0"}).json()
check(r["acceptance_task_id"] is None, "off: no task")
check(F.patch(B + f"/api/envs/{E['id']}", json={"acceptance_task": True}).json()["acceptance_task"] is True, "the option on")
SEC = F.post(B + f"/api/lists/{L}/tags", json={"name": "Secret"}).json()["id"]  # what locks a task keeps locking its line in the checklist
check(F.patch(B + f"/api/tasks/{TA}", json={"ltags": ["Secret"]}).ok, "setup: a list tag")
r = F.post(B + f"/api/envs/{E['id']}/deploy", json={"version": "v2.5"})
AT = r.json()["acceptance_task_id"]
check(r.status_code == 201 and AT and sorted(r.json()["closed"]) == [TA, TB], "the version brings the task " + r.text[:300])
row = dbx("SELECT title, assignee_id, status FROM tasks WHERE id=?", (AT,))[0]
check(row[0] == "Accept v2.5" and row[1] == FU and row[2] == 0, f"title and owner {row[:2]}")
kids = sorted(x[0] for x in dbx("SELECT title FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (AT,)))
check(kids == ["Feature one", "Feature two"], f"the closed tasks as subtasks {kids}")
check(dbx("""SELECT x.tag_id FROM task_list_tags x JOIN tasks t ON t.id=x.task_id WHERE t.parent_id=? AND t.title='Feature one'""", (AT,)) == [(SEC,)],
      "the line carries the tags of its task")
ev = events(AH, "deployed")
check(ev and ev[-1]["data"]["acceptance_task_id"] == AT, "deployed carries the id")
did = r.json()["id"]
r = F.post(B + f"/api/envs/{E['id']}/deploy", json={"version": "2.5"})
check(r.json()["acceptance_task_id"] is None, "the same version again: no second one")
check(F.delete(B + f"/api/envs/{E['id']}/deploys/{r.json()['id']}").ok, "the deployment undone")
r = F.post(B + f"/api/envs/{E['id']}/deploy", json={"version": "2.5"})
check(r.json()["acceptance_task_id"] is None, "after an undone deployment no second one")
check(len(dbx("SELECT 1 FROM tasks WHERE list_id=? AND title='Accept v2.5'", (L,))) == 1, "exactly one")
E2 = F.post(B + f"/api/lists/{L}/envs", json={"name": "Staging", "acceptance_task": True}).json()
r = F.post(B + f"/api/envs/{E2['id']}/deploy", json={"version": "2.5"})
check(r.json()["acceptance_task_id"], "another environment has its own")
url = F.patch(B + f"/api/envs/{E2['id']}", json={"hook": "on"}).json()["url"]
r = requests.post(B + "/" + url.split("/", 3)[3], json={"version": "3.0"})
check(r.status_code == 201, "the webhook works without a user " + r.text[:200])
check(dbx("SELECT assignee_id FROM tasks WHERE list_id=? AND title='Accept v3.0'", (L,))[0][0] == FU, "the webhook's task goes to the owner")
check(dbx("SELECT 1 FROM tasks WHERE id=? AND acceptance_of IS NOT NULL", (AT,)), "the mark stays on the server")
check("acceptance_of" not in F.get(B + f"/api/tasks/{AT}").json(), "never in an answer")

ELK = F.post(B + f"/api/lists/{LK}/envs", json={"name": "L", "acceptance_task": True})
if ELK.ok:  # a locked list: the server writes no plain title
    r = F.post(B + f"/api/envs/{ELK.json()['id']}/deploy", json={"version": "1.0"})
    check(r.ok and r.json()["acceptance_task_id"] is None, "a locked list gets none " + r.text[:200])

sys.exit(done("p2392_c_api"))
