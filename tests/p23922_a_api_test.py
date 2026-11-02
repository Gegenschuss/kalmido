#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.2 (#3365): the delivery state of a task (in progress, parked, waiting), own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks, lists
 - nothing said by default (delivery null); PATCH /api/v1/tasks/{id} {delivery} by an agent with write access; parked needs a
   reason; waiting for a task (one the caller sees, not itself) or a note; a bad state, a job id outside in_progress, an unknown
   part: 400; null clears it; the same again changes nothing; the history keeps it
 - the app: PUT / DELETE /api/tasks/{id}/delivery; a viewer 403, a stranger 404
 - GET /api/v1/tasks?delivery= (one, several, none), a bad value 400
 - jobs: an agent's running job on a task without a state sets in_progress (job id), ending it clears it; a parked task stays
   parked; two jobs: ending one hands the mark to the other; the working mark (POST / DELETE .../working) the same; a person's
   Stop clears it; a job id of another task: 400
 - Waiting for me: the person's own parked tasks (kind parked, why = the reason); the delivery report: parked = stuck
 - list column delivery, sort col:delivery, group_field delivery
 - a list with the lock: no note (409), the state works; a list that gets the lock keeps no note
 - a person without an organisation: all of it in her own list
usage: p23922_a_api_test.py <datadir>"""
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


def task(s, lid, title):
    return s.post(B + "/api/tasks", json={"title": title, "list_id": lid}).json()["id"]


def dv(h, tid):
    return requests.get(V + f"/tasks/{tid}", headers=h).json().get("delivery")


def patch(h, tid, v):
    return requests.patch(V + f"/tasks/{tid}", headers=h, json={"delivery": v})


def ids(h, **q):
    return sorted(x["id"] for x in requests.get(V + "/tasks", headers=h, params={"limit": 500, **q}).json()["data"])


kt.fresh()
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")  # a person without an organisation is the main case: her own list
GU, G = freelancer(B, A, "gert")
XU, X = freelancer(B, A, "xena")  # a stranger
L = F.post(B + "/api/lists", json={"name": "Release", "kind": "project", "ptype": "software"}).json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": GU, "role": "view"}).ok, "setup: a viewer")
AID, AH = agent(F, "fridabot", L)
T1, T2, T3, T4 = task(F, L, "Import"), task(F, L, "Export"), task(F, L, "Report"), task(F, L, "Plain")
XL = X.post(B + "/api/lists", json={"name": "Hers"}).json()["id"]
XT = task(X, XL, "Not yours")

# ================================================================== set, read, clear
check(dv(AH, T1) is None, "nothing said by default")
check(patch(AH, T1, {"state": "parked"}).status_code == 400, "parked without a reason: 400")
r = patch(AH, T1, {"state": "parked", "note": "Waits for the client's answer"})
d = r.json().get("delivery") or {}
check(r.ok and d.get("state") == "parked" and d.get("note") == "Waits for the client's answer" and d.get("by") == AID and d.get("since"),
      "an agent parks a task with a reason " + r.text[:300])
check(patch(AH, T1, {"state": "parked", "note": "Waits for the client's answer"}).ok, "the same again")
n_act = len(dbx("SELECT 1 FROM activity WHERE task_id=? AND kind='delivery'", (T1,)))
check(n_act == 1, f"the history keeps it once ({n_act})")
check(patch(AH, T1, {"state": "done"}).status_code == 400, "a bad state: 400")
check(patch(AH, T1, {"state": "parked", "note": "x", "why": 1}).status_code == 400, "an unknown part: 400")
check(patch(AH, T1, {"state": "parked", "note": "x", "job_id": 1}).status_code == 400, "a job id outside in_progress: 400")
check(patch(AH, T1, {"state": "parked", "note": "x" * 501}).status_code == 400, "a note too long: 400")
r = patch(AH, T2, {"state": "waiting", "task_id": T1})
check(r.ok and r.json()["delivery"]["task_id"] == T1 and r.json()["delivery"]["state"] == "waiting", "waiting for a task " + r.text[:200])
check(patch(AH, T2, {"state": "waiting", "task_id": T2}).status_code == 400, "waiting for itself: 400")
check(patch(AH, T2, {"state": "waiting", "task_id": XT}).status_code == 400, "waiting for a task it does not see: 400")
r = F.put(B + f"/api/tasks/{T3}/delivery", json={"state": "waiting", "note": "the new server"})
check(r.ok and r.json()["delivery"]["note"] == "the new server", "the app: waiting for a note " + r.text[:200])
check(G.put(B + f"/api/tasks/{T3}/delivery", json={"state": "parked", "note": "x"}).status_code == 403, "a viewer: 403")
check(X.put(B + f"/api/tasks/{T3}/delivery", json={"state": "parked", "note": "x"}).status_code == 404, "a stranger: 404")
check(X.delete(B + f"/api/tasks/{T3}/delivery").status_code == 404, "a stranger cannot clear it: 404")
st = next(t for t in F.get(B + "/api/state").json()["tasks"] if t["id"] == T3)
check(st.get("delivery") == "waiting" and st.get("delivery_note") == "the new server", "the app's task carries it")

# ================================================================== the filter
check(ids(AH, delivery="parked") == [T1], "filter parked")
check(ids(AH, delivery="parked,waiting") == sorted([T1, T2, T3]), "filter several")
check(T4 in ids(AH, delivery="none") and T1 not in ids(AH, delivery="none"), "filter none")
check(requests.get(V + "/tasks", headers=AH, params={"delivery": "done"}).status_code == 400, "filter: a bad value 400")
check(F.delete(B + f"/api/tasks/{T3}/delivery").json().get("delivery") is None, "the app clears it")
check(patch(AH, T2, None).ok and dv(AH, T2) is None, "null clears it")

# ================================================================== jobs
r = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Build the export", "task_id": T2})
J1 = r.json()["id"]
d = dv(AH, T2) or {}
check(r.status_code == 201 and d.get("state") == "in_progress" and d.get("job_id") == J1, f"a running job sets in_progress {d}")
r = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Second look", "task_id": T2})
J2 = r.json()["id"]
check((dv(AH, T2) or {}).get("job_id") == J1, "a second job leaves the first one's mark")
requests.patch(V + f"/agent/jobs/{J1}", headers=AH, json={"state": "done"})
check((dv(AH, T2) or {}).get("job_id") == J2, "the first ends: the mark goes to the other open job")
requests.patch(V + f"/agent/jobs/{J2}", headers=AH, json={"state": "failed"})
check(dv(AH, T2) is None, "the last one ends: cleared")
r = requests.post(V + "/agent/jobs", headers=AH, json={"title": "On a parked task", "task_id": T1})
check((dv(AH, T1) or {}).get("state") == "parked", "a job never overwrites parked")
requests.patch(V + f"/agent/jobs/{r.json()['id']}", headers=AH, json={"state": "done"})
check((dv(AH, T1) or {}).get("state") == "parked", "... and its end does not clear it")
r = requests.post(V + f"/tasks/{T4}/working", headers=AH, json={"text": "starting"})
check(r.status_code == 201 and (dv(AH, T4) or {}).get("state") == "in_progress", "the working mark sets in_progress " + r.text[:200])
check(patch(AH, T4, {"state": "in_progress", "job_id": J1}).status_code == 400, "a job id that is not open on this task: 400")
requests.delete(V + f"/tasks/{T4}/working", headers=AH)
check(dv(AH, T4) is None, "the working mark ends: cleared")
r = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Stopped by her", "task_id": T4})
J3 = r.json()["id"]
check((dv(AH, T4) or {}).get("job_id") == J3, "in progress again")
r = F.post(B + f"/api/agents/jobs/{J3}/action", json={"action": "stop"})
check(r.ok and dv(AH, T4) is None, "her Stop clears it " + r.text[:200])
r = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Waiting job", "task_id": T4, "state": "waiting"})
check(dv(AH, T4) is None, "a job reported as waiting sets nothing")
requests.patch(V + f"/agent/jobs/{r.json()['id']}", headers=AH, json={"state": "running"})
check((dv(AH, T4) or {}).get("state") == "in_progress", "running again: in progress")

# ================================================================== Waiting for me, the delivery report
F.patch(B + f"/api/tasks/{T1}", json={"assignee_id": FU})
w = F.get(B + "/api/inbox").json()
pk = [x for x in w["items"] if x["kind"] == "parked"]
check([x["id"] for x in pk] == [T1] and pk[0]["why"] == "Waits for the client's answer" and w["counts"].get("parked") == 1, f"Waiting for me: parked {pk}")
check(not [x for x in G.get(B + "/api/inbox").json()["items"] if x["kind"] == "parked"], "not hers: not in another person's")
rep = requests.get(V + f"/lists/{L}/delivery-report", headers=AH)
if rep.ok:
    stk = {x["id"]: x for x in rep.json()["stuck"]}
    check(stk.get(T1, {}).get("reason") == "parked", f"the delivery report: parked = stuck {list(stk.values())[:3]}")
    check("parked" in rep.json()["markdown"], "... in its text")
else:
    check(False, "delivery report " + rep.text[:200])

# ================================================================== list column, sort, grouping
r = F.patch(B + f"/api/lists/{L}", json={"columns": ["due", "delivery"]})
check(r.ok, "the column delivery " + r.text[:200])
check(F.patch(B + f"/api/lists/{L}", json={"sort_mode": "col:delivery"}).ok, "sort by the column")
r = F.patch(B + f"/api/lists/{L}", json={"group_field": "delivery"})
check(r.ok and next(x for x in F.get(B + "/api/state").json()["lists"] if x["id"] == L).get("group_field") == "delivery", "grouped by the delivery state " + r.text[:200])
check(F.patch(B + f"/api/lists/{L}", json={"group_field": "deliveryx"}).status_code == 400, "a bad grouping: 400")


# ================================================================== the lock
def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(48)}, separators=(",", ":"))


LK = F.post(B + "/api/lists", json={"name": "Locked"}).json()["id"]
TK = task(F, LK, "Secret")
check(F.put(B + f"/api/tasks/{TK}/delivery", json={"state": "parked", "note": "plain reason"}).ok, "before the lock: parked with a reason")
assert F.put(B + "/api/e2e/keys", json={"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
                                        "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
                                        "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}).ok
r = F.post(B + f"/api/lists/{LK}/e2e/start", json={"keys": [{"user_id": FU, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
check(r.ok, "the lock starts " + r.text[:200])
j = F.get(B + f"/api/lists/{LK}/e2e/todo").json()
out = {"tasks": [{"id": x["id"], **{k: ct(j["gen"]) for k, v in x.items() if k != "id" and v is not None}} for x in j["tasks"]]}
check(F.post(B + f"/api/lists/{LK}/e2e/bulk", json=out).ok, "the texts encrypted")
check(F.post(B + f"/api/lists/{LK}/e2e/finish").ok, "the lock is on")
row = dbx("SELECT delivery, delivery_note FROM tasks WHERE id=?", (TK,))[0]
check(row[0] == "parked" and row[1] == "", f"the state stays, its note goes {row[:2]}")
check(F.put(B + f"/api/tasks/{TK}/delivery", json={"state": "parked", "note": "Plain"}).status_code == 409, "a locked list takes no note")
check(F.put(B + f"/api/tasks/{TK}/delivery", json={"state": "waiting"}).ok, "the state without a note stays possible")
act = [x[0] for x in dbx("SELECT data FROM activity WHERE task_id=? AND kind='delivery'", (TK,))]
check(act and all("plain reason" not in (a if isinstance(a, str) else json.dumps(a)) for a in act), f"no plain note in the history {act}")

sys.exit(done("p23922_a_api"))
