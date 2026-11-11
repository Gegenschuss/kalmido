#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.0 B API tests (#3364): a task is completed when its package or code is released; "partly, the rest in Y".
Own container (start.sh) with the fake GitHub of fake_git.py and the webhook receiver stub_webhook.py inside.
freelancer-matrix: lists
freelancer-matrix: tasks
 - lists.git_close_release: off for every list, set by who manages the list (PUT .../repos/close-release), shown in GET .../repos
 - with it on the poll completes the open stale tasks (git_closes kind release, activity, Undo), not a task only in main; once per
   task and version: Undo keeps it open for that version, a later version completes it again; no provider request of its own
 - webhooks and agents hear task.completed with via "release"
 - POST /api/tasks/{id}/partial, /api/v1/tasks/{id}/partial and the comment command: stays open, version field Y, the rest task
   (same place, tags, people, assignee), the dependency, the comment; an old commit tag does not complete it, stale false until Y
   is released, then tag Y completes it; sent again = nothing new; honest answers without a version field / for a wrong version /
   without write access; a stranger: 404
 - a select field as version field; a person without an organisation; OpenAPI
 - 2.392.2 (#3365): a parked task stays open, cleared the next pass completes it
usage: p2392_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, login  # noqa: E402
from kt import check, done, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
GH = "http://127.0.0.1:8090"
STATE = {"8090": {}, "8091": {}, "8092": {}, "8093": {}}


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=60, **k)

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=60, **k)


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


def dbq(sql, args=()):
    c = dbx.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def polls(cid, n=2):
    def at():
        r = dbq("SELECT polled_at FROM git_conns WHERE id=?", (cid,))
        return r[0][0] if r else None
    for _ in range(n):
        a = at()
        until(lambda: at() != a, 20)


def git_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "git.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def wh_log():
    try:
        return [json.loads(json.loads(x)["body"]) for x in open(os.path.join(DATA, "wh.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def task(s, tid):
    return next((x for x in s.get(B + "/api/state").json()["tasks"] if x["id"] == tid), None)


def status(tid):
    return dbq("SELECT status FROM tasks WHERE id=?", (tid,))[0][0]


def fval(tid, fid):
    r = dbq("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid))
    return r[0][0] if r else None


def cm(sha, msg, repo="acme/app"):
    at = (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sha": sha, "html_url": f"{GH}/{repo}/commit/{sha}", "author": {"login": "dev"},
            "commit": {"message": msg, "author": {"name": "Dev", "date": at}, "committer": {"date": at}}}


put_state()
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True, env=dict(os.environ, EXTRA=" ".join((
    "-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1",
    "-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097", "-e KALMIDO_WEBHOOK_TICK=1"))))
assert r.returncode == 0, r.stdout + r.stderr
put_state()
for f in ("fake_git.py", "stub_webhook.py"):
    subprocess.run(["cp", os.path.join(N, f), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + f])
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update({"X-Requested-With": "kalmido"})
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ids = {}
for u in ("bob", "carol", "dora", "vera"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca, Do, Ve = login(B, "bob"), login(B, "carol"), login(B, "dora"), login(B, "vera")
for s in (Bo, Ca, Do, Ve):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, ag = r.json()["id"], Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "stranger", "display_name": "Stranger"})
other = Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "talker", "display_name": "Talker"})
TK, talker = r.json()["id"], Api(r.json()["token"])
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
for uid, role in ((ids["bob"], "edit"), (AG, "edit"), (ids["vera"], "view"), (ids["dora"], "participant")):
    r = A.put(B + f"/api/lists/{P}/members", json={"user_id": uid, "role": role})
    assert r.ok, f"{uid} {role} {r.status_code} {r.text}"
FP = A.post(B + f"/api/lists/{P}/fields", json={"name": "Paket", "type": "text"}).json()["id"]
T = {k: A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": P}).json()["id"] for k in range(1, 10)}  # 2.392.2 (#3365): + T[9] parked
assert A.patch(B + f"/api/tasks/{T[2]}", json={"fields": {str(FP): "2.10"}}).ok
g = STATE["8090"]["acme/app"] = {
    "default_branch": "main", "pulls": [],
    "commits": {"main": [cm("a3", f"Polish #{T[3]}"), cm("a5", f"Part of #{T[5]}"), cm("a1", f"Feature #{T[1]}")]},
    "tags": [{"name": "v2.10.0"}, {"name": "v2.9.3"}],
    "compare": {"v2.9.3...v2.10.0": [cm("a1", f"Feature #{T[1]}"), cm("a5", f"Part of #{T[5]}")], "v2.10.0...main": [cm("a3", f"Polish #{T[3]}")]},
    "branches": [{"name": "main", "commit": {"sha": "a3"}}]}
put_state()
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app"})
check(r.status_code == 201, f"connected {r.status_code} {r.text[:150]}")
CID = r.json().get("id")
check(until(lambda: dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a1'", (CID,)) == [("v2.10.0",)]), "the tag of the first commit")
polls(CID)

# ------------------------------------------------------------------ the switch: off by default, who manages the list
check(A.get(B + f"/api/lists/{P}/repos").json().get("close_release") is False, "repos: off by default")
check(dbq("SELECT COUNT(*) FROM lists WHERE git_close_release<>0") == [(0,)], "no list has it on")
b1 = (task(A, T[1])["code"] or {}).get("build") or {}
check(b1.get("stale") is True, f"task 1 is stale {b1}")
polls(CID)
check(status(T[1]) == 0 and status(T[2]) == 0, "off: stale tasks stay open")
check(Bo.put(B + f"/api/lists/{P}/repos/close-release", json={"on": True}).status_code == 403, "a member cannot switch it")
check(Ca.put(B + f"/api/lists/{P}/repos/close-release", json={"on": True}).status_code == 404, "a stranger: 404")
check(A.put(B + f"/api/lists/{P}/repos/close-release", json={"on": 1}).status_code == 400, "not a boolean: 400")

# ------------------------------------------------------------------ partial before the switch: T5 has an old commit tag
b5 = (task(A, T[5])["code"] or {}).get("build") or {}
check(b5.get("state") == "released" and b5.get("stale") is True, f"task 5: its commit is in 2.10.0 {b5}")
ltid = A.post(B + f"/api/lists/{P}/tags", json={"name": "secret"}).json()["id"]
Do_t = A.post(B + "/api/tasks", json={"title": "For Dora", "list_id": P, "assignee_id": ids["dora"], "ltags": ["secret"], "priority": 5}).json()["id"]
r = ag.post(f"/tasks/{T[5]}/partial", json={"version": "v2.12", "note": "the import is left"})
check(r.status_code == 200, f"agent: partial {r.status_code} {r.text[:200]}")
j = r.json()
REST = (j.get("rest") or {}).get("id")
check(j.get("version") == "2.12" and j.get("partly_in") == "2.10.0" and j["task"].get("partial_until") == "2.12", f"the answer {str(j)[:300]}")
check(j["rest"].get("title") == "Rest: Task 5" and j["rest"].get("list_id") == P and j["rest"].get("notes") == "the import is left", "the rest task")
check(fval(T[5], FP) == "2.12" and fval(REST, FP) == "2.12", "version field of both = Y")
check(dbq("SELECT 1 FROM task_deps WHERE task_id=? AND blocker_id=?", (T[5], REST)) == [(1,)], "the task waits on its rest")
cs = [x[0] for x in dbq("SELECT body FROM comments WHERE task_id=? ORDER BY id", (T[5],))]
check(len(cs) == 1 and cs[0].startswith("Partly in 2.10.0, rest in 2.12") and f"#{REST}" in cs[0] and "the import is left" in cs[0], f"the comment {cs}")
b5 = (task(A, T[5])["code"] or {}).get("build") or {}
check(b5.get("stale") is False and b5.get("state") == "released", f"waiting for Y: not stale {b5}")
check(T[5] not in {x["id"] for x in A.get(B + f"/api/lists/{P}/build-status").json()["data"]}, "build-status leaves it out")
check(ag.get(f"/tasks/{T[5]}").json().get("partial_until") == "2.12", "get_task: partial_until")
check(ag.get(f"/tasks/{T[1]}").json().get("partial_until") is None and "partial_until" not in task(A, T[1]), "not set: null / absent")
r = A.post(B + f"/api/tasks/{T[5]}/partial", json={"version": "2.12"})
check(r.ok and r.json().get("already") is True and r.json().get("rest") is None, f"sent again {r.text[:150]}")
check(dbq("SELECT COUNT(*) FROM tasks WHERE title='Rest: Task 5'") == [(1,)], "... makes no second rest")
# what decides who sees it comes along
r = A.post(B + f"/api/tasks/{Do_t}/partial", json={"version": "2.13"})
check(r.ok, f"session route {r.status_code} {r.text[:200]}")
RD = r.json()["rest"]["id"]
check(task(Do, RD) is not None and r.json()["rest"].get("assignee_id") == ids["dora"] and r.json()["rest"].get("priority") == 5, "the participant sees the rest")
check(dbq("SELECT tag_id FROM obj_tag_links WHERE kind='task' AND obj_id=?", (RD,)) == [(ltid,)], "the list tag comes along")  # 2.947.0 (#5275): the core's tags (obj_tags / obj_tag_links)
check(task(Do, REST) is None, "... and no other task")
# refused
check(Ca.post(B + f"/api/tasks/{T[6]}/partial", json={"version": "2.20"}).status_code == 404, "a stranger: 404")
check(other.post(f"/tasks/{T[6]}/partial", json={"version": "2.20"}).status_code == 404, "an agent it is not shared with: 404")
check(Ve.post(B + f"/api/tasks/{T[6]}/partial", json={"version": "2.20"}).status_code == 403, "view only: 403")
check(A.post(B + f"/api/tasks/{T[6]}/partial", json={"version": "soon"}).status_code == 400, "not a version: 400")
check(A.post(B + f"/api/tasks/{T[6]}/partial", json={"version": "2.10"}).status_code == 400, "already released: 400")
check(A.post(B + f"/api/tasks/{T[6]}/partial", json={"version": "2.20", "x": 1}).status_code == 400, "unknown field: 400")
check(status(T[6]) == 0 and fval(T[6], FP) is None, "nothing changed")

# ------------------------------------------------------------------ the comment command
r = Bo.post(B + f"/api/tasks/{T[6]}/comments", json={"body": "Teilweise: Rest in 2.14\nthe rest of the text"})
j = r.json()
check(r.ok and (j.get("partial") or {}).get("applied") is True and j["partial"].get("version") == "2.14", f"command {r.text[:200]}")
check(dbq("SELECT partial_until FROM tasks WHERE id=?", (T[6],)) == [("2.14",)] and fval(T[6], FP) == "2.14", "the command acted")
R6 = j["partial"]["rest_id"]
check(dbq("SELECT title FROM tasks WHERE id=?", (R6,)) == [("Rest: Task 6",)], "the rest of the command")
c7 = T[7]
r = Ve.post(B + f"/api/tasks/{c7}/comments", json={"body": "partly: rest in 2.15"})
check(r.ok and r.json()["partial"]["applied"] is False and r.json()["partial"].get("reason"), f"view only: a comment and a hint {r.text[:200]}")
check(dbq("SELECT partial_until FROM tasks WHERE id=?", (c7,)) == [(None,)], "... nothing happened")
TL = A.post(B + "/api/lists", json={"name": "Talk", "kind": "project"}).json()["id"]
assert A.put(B + f"/api/lists/{TL}/members", json={"user_id": TK, "role": "edit"}).ok
A.post(B + f"/api/lists/{TL}/fields", json={"name": "Version", "type": "text"})
tt = A.post(B + "/api/tasks", json={"title": "Talk", "list_id": TL}).json()["id"]
r = talker.post(f"/tasks/{tt}/comments", json={"body": "partly: rest in 2.15"})
check(r.status_code == 201 and r.json().get("partial", {}).get("applied") is False, f"token without tasks:write {r.status_code} {r.text[:200]}")
r = ag.post(f"/tasks/{c7}/comments", json={"body": "partly: rest in soon"})
check(r.status_code == 201 and r.json().get("partial", {}).get("applied") is False, "not a version: a comment and a hint")
r = A.post(B + f"/api/tasks/{c7}/comments", json={"body": "The note says partly: rest in 2.15 in the middle"})
check(r.ok and "partial" not in r.json(), "only as the first line")
r = A.post(B + f"/api/tasks/{c7}/comments", json={"body": "x\npartly: rest in 2.15"})
check(r.ok and "partial" not in r.json(), "not in a later line")
NF = A.post(B + "/api/lists", json={"name": "Plain", "kind": "project"}).json()["id"]
tn = A.post(B + "/api/tasks", json={"title": "No field", "list_id": NF}).json()["id"]
r = A.post(B + f"/api/tasks/{tn}/comments", json={"body": "partly: rest in 2.5"})
check(r.ok and r.json()["partial"]["applied"] is False and "version field" in r.json()["partial"].get("reason", ""), f"no version field: honest {r.text[:200]}")
check(dbq("SELECT partial_until FROM tasks WHERE id=?", (tn,)) == [(None,)] and dbq("SELECT COUNT(*) FROM tasks WHERE list_id=?", (NF,)) == [(1,)], "... nothing else")
check(A.post(B + f"/api/tasks/{tn}/partial", json={"version": "2.5"}).status_code == 400, "route: 400 without a version field")
# a select field
SL = A.post(B + "/api/lists", json={"name": "Sel", "kind": "project"}).json()["id"]
r = A.post(B + f"/api/lists/{SL}/fields", json={"name": "Release", "type": "select", "options": {"options": [{"id": "o1", "name": "3.1"}]}})
check(r.ok, f"select field {r.text[:200]}")
FS = r.json().get("id")
A.put(B + f"/api/lists/{SL}/repos/version-field", json={"field": FS})
ts = A.post(B + "/api/tasks", json={"title": "Sel", "list_id": SL}).json()["id"]
check(A.post(B + f"/api/tasks/{ts}/partial", json={"version": "3.2"}).status_code == 400, "select: no such option")
oid = (A.get(B + f"/api/state").json()["fields"] and next(f for f in A.get(B + "/api/state").json()["fields"] if f["id"] == FS)["options"]["options"][0]["id"])
r = A.post(B + f"/api/tasks/{ts}/partial", json={"version": "3.1"})
check(r.ok and str(fval(ts, FS)) == str(oid), f"select: the option's id {r.status_code} {r.text[:150]}")

# ------------------------------------------------------------------ the switch on
wh = A.post(B + "/api/me/webhooks", json={"name": "w", "url": "http://127.0.0.1:8097/ok", "events": ["task.completed"]})
check(wh.ok, f"webhook {wh.text[:150]}")
seq = (ag.get("/agent/events", params={"since": 0}).json().get("data") or [{}])[-1].get("seq", 0)
polls(CID)
n0 = len(git_log())
polls(CID, 3)
off_reqs = len(git_log()) - n0
# a one-way step without a yes in a list that asks for one stays open (#3370), with the yes the next pass completes it
assert A.patch(B + f"/api/tasks/{T[8]}", json={"fields": {str(FP): "2.10"}}).ok
assert A.patch(B + f"/api/lists/{P}", json={"irreversible_needs_yes": True}).ok
assert A.put(B + f"/api/tasks/{T[8]}/irreversible", json={"reason": "drops a column"}).ok
# 2.392.2 (#3365): a parked task stays open, cleared the next pass completes it
assert A.patch(B + f"/api/tasks/{T[9]}", json={"fields": {str(FP): "2.10"}}).ok
assert A.put(B + f"/api/tasks/{T[9]}/delivery", json={"state": "parked", "note": "waits for the client"}).ok
check(A.put(B + f"/api/lists/{P}/repos/close-release", json={"on": True}).json().get("on") is True, "switched on")
check(A.get(B + f"/api/lists/{P}/repos").json().get("close_release") is True, "repos: on")
check(until(lambda: status(T[1]) == 2 and status(T[2]) == 2), "commit in a tag and released package: completed")
check(dbq("SELECT kind, ref, versions FROM git_closes WHERE task_id=?", (T[1],)) == [("release", "2.10.0", "2.10.0.0")], f"git_closes {dbq('SELECT * FROM git_closes WHERE task_id=?', (T[1],))}")
check(status(T[3]) == 0, "only in main: stays open")
check(status(T[5]) == 0, "waiting for Y: an old commit tag does not complete it")
check(status(T[8]) == 0, "a one-way step without a yes: stays open")
check(status(T[9]) == 0, "#3365: a parked task stays open")
check(A.delete(B + f"/api/tasks/{T[9]}/delivery").ok, "#3365: parking cleared")
check(A.post(B + f"/api/tasks/{T[8]}/irreversible-yes").ok, "the yes")
polls(CID)
check(until(lambda: status(T[8]) == 2), "with the yes the next pass completes it")
check(until(lambda: status(T[9]) == 2), "#3365: no longer parked: the next pass completes it")
act = [x[0] for x in dbq("SELECT data FROM activity WHERE task_id=? AND kind='git_done'", (T[1],))]
da = act[0] if act and isinstance(act[0], dict) else json.loads(act[0]) if act else {}
check(len(act) == 1 and da.get("kind") == "release" and da.get("title") == "2.10.0", f"activity {act}")
check(until(lambda: [e for e in wh_log() if e.get("event") == "task.completed" and e["data"]["task"]["id"] == T[1]]), f"webhook {wh_log()[:2]}")
e = next(e for e in wh_log() if e["data"]["task"]["id"] == T[1])
check(e.get("via") == "release" and e.get("actor") is None, f"webhook: via release {e.get('via')} {e.get('actor')}")
evs = [e for e in ag.get("/agent/events", params={"since": seq}).json().get("data", []) if e["event"] == "task.completed"]
ev = next((e for e in evs if e["data"]["task"]["id"] == T[1]), {})
check(ev.get("via") == "release" and ev.get("data", {}).get("version") == "2.10.0", f"agent event {str(ev)[:200]}")
check(not [e for e in other.get("/agent/events", params={"since": 0}).json().get("data", []) if e["event"] == "task.completed"], "an agent without the list hears nothing")
polls(CID)
n0 = len(git_log())
polls(CID, 3)
check(len(git_log()) - n0 <= off_reqs + 3, f"no provider request of its own: {len(git_log()) - n0} vs {off_reqs}")
sig = dbq("SELECT rel_sig FROM git_conns WHERE id=?", (CID,))[0][0]
polls(CID)
check(sig and dbq("SELECT rel_sig FROM git_conns WHERE id=?", (CID,))[0][0] == sig, "nothing changed: the pass does not run")

# Undo: not again for that version, a later version again
r = A.post(B + f"/api/tasks/{T[1]}/git-undo")
check(r.ok and status(T[1]) == 0, f"Undo {r.status_code} {r.text[:150]}")
polls(CID, 2)
A.patch(B + f"/api/tasks/{T[1]}", json={"title": "Task 1 changed"})  # a change: the pass runs
polls(CID, 2)
check(status(T[1]) == 0, "after Undo: not again for the same version")
check(len(dbq("SELECT 1 FROM activity WHERE task_id=? AND kind='git_done'", (T[1],))) == 1, "... once")
# a new version: 2.11 with T1's later commit; and Y of T5 / T2's rest
g["commits"]["main"].insert(0, cm("a6", f"More for #{T[1]}"))
g["tags"].insert(0, {"name": "v2.11.0"})
g["compare"]["v2.10.0...v2.11.0"] = [cm("a6", f"More for #{T[1]}")]
g["compare"]["v2.11.0...main"] = []
g["branches"][0]["commit"]["sha"] = "a6"
put_state()
check(until(lambda: status(T[1]) == 2), "a later version completes it again")
check(dbq("SELECT versions FROM git_closes WHERE task_id=?", (T[1],))[0][0].split() == ["2.10.0.0", "2.11.0.0"], "both versions remembered")
check(status(T[5]) == 0, "2.11 is not Y")
g["tags"].insert(0, {"name": "v2.12.0"})
g["compare"]["v2.11.0...v2.12.0"] = []
g["compare"]["v2.12.0...main"] = []
put_state()
check(until(lambda: status(T[5]) == 2), "tag Y completes the task")
check(dbq("SELECT ref FROM git_closes WHERE task_id=?", (T[5],)) == [("2.12",)], "... in Y")
check(until(lambda: status(REST) == 2), "... and its rest (package released)")

# ------------------------------------------------------------------ 2.662.0 (#4602): a list of an organisation
# tasks carry org_id under row-level security now; the poll's release events run without a person and must still read
# the task of an organisation's list (before the fix: TypeError, rolled back, never completed)
r = A.post(B + "/api/admin/orgs", json={"name": "Acme"})
check(r.status_code == 201, f"org list: an organisation {r.status_code} {r.text[:150]}")
WS = r.json().get("id")
STATE["8090"]["acme/org"] = {"default_branch": "main", "pulls": [], "commits": {"main": []}, "tags": [{"name": "3.0.0"}, {"name": "2.9.0"}],
                             "compare": {"2.9.0...3.0.0": [], "3.0.0...main": []}, "branches": [{"name": "main", "commit": {"sha": "o1"}}]}
put_state()
OL = A.post(B + "/api/lists", json={"name": "Org app", "kind": "project", "org_id": WS}).json()["id"]
check(dbq("SELECT org_id FROM lists WHERE id=?", (OL,)) == [(WS,)], "org list: in alice's organisation")
OF = A.post(B + f"/api/lists/{OL}/fields", json={"name": "Version", "type": "text"}).json()["id"]
r = A.post(B + f"/api/lists/{OL}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/org"})
check(r.status_code == 201, f"org list: connected {r.status_code} {r.text[:150]}")
check(A.put(B + f"/api/lists/{OL}/repos/close-release", json={"on": True}).ok, "org list: the switch")
ot = A.post(B + "/api/tasks", json={"title": "Org page", "list_id": OL, "fields": {str(OF): "3.0"}}).json()["id"]
check(dbq("SELECT org_id FROM tasks WHERE id=?", (ot,)) == [(WS,)], "org list: the task carries the organisation")
check(until(lambda: status(ot) == 2), "org list: released package completes the task (release events read it under RLS)")

# ------------------------------------------------------------------ without an organisation
FID, Fr = freelancer(B, A)  # freelancer-matrix: lists
STATE["8090"]["frida/site"] = {"default_branch": "main", "pulls": [], "commits": {"main": []}, "tags": [{"name": "1.0.0"}, {"name": "0.9.0"}],
                               "compare": {"0.9.0...1.0.0": [], "1.0.0...main": []}, "branches": [{"name": "main", "commit": {"sha": "f1"}}]}
put_state()
FL = Fr.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
FF = Fr.post(B + f"/api/lists/{FL}/fields", json={"name": "Version", "type": "text"}).json()["id"]
r = Fr.post(B + f"/api/lists/{FL}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/site"})
check(r.status_code == 201, f"freelancer: connected {r.status_code} {r.text[:150]}")
FC = r.json().get("id")
check(Fr.put(B + f"/api/lists/{FL}/repos/close-release", json={"on": True}).ok, "freelancer: the switch")
ft = Fr.post(B + "/api/tasks", json={"title": "Page", "list_id": FL, "fields": {str(FF): "1.0"}}).json()["id"]
fp = Fr.post(B + "/api/tasks", json={"title": "Part", "list_id": FL}).json()["id"]
check(until(lambda: status(ft) == 2), "freelancer: released package completes the task")
r = Fr.post(B + f"/api/tasks/{fp}/comments", json={"body": "teilweise: Rest in 1.1"})
check(r.ok and r.json()["partial"]["applied"] is True, f"freelancer: the command {r.text[:150]}")
check(dbq("SELECT title, list_id FROM tasks WHERE id=?", (r.json()["partial"]["rest_id"],)) == [("Rest: Part", FL)], "freelancer: the rest")
fq = Fr.post(B + "/api/tasks", json={"title": "Web", "list_id": FL}).json()["id"]
fv = Fr.post(B + "/api/tasks", json={"title": "Token", "list_id": FL}).json()["id"]
r = Fr.post(B + f"/api/tasks/{fq}/partial", json={"version": "1.2"})  # freelancer-matrix: tasks
check(r.ok and r.json()["task"].get("partial_until") == "1.2", f"freelancer: the route {r.status_code} {r.text[:150]}")
ft_h = {"Authorization": "Bearer " + Fr.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "tasks:write"]}).json()["token"]}
r = requests.post(B + f"/api/v1/tasks/{fv}/partial", json={"version": "1.3"}, headers=ft_h, timeout=30)  # freelancer-matrix: tasks
check(r.ok and r.json()["task"].get("partial_until") == "1.3", f"freelancer: the token route {r.status_code} {r.text[:150]}")

spec = requests.get(V + "/openapi.json", headers=ag.h, timeout=30).json()
check(spec["paths"]["/tasks/{id}/partial"]["post"]["x-kalmido-scope"] == "tasks:write", "OpenAPI: the route and its scope")
check("partial_until" in spec["components"]["schemas"]["Task"]["properties"], "OpenAPI: partial_until")
sys.exit(done("p2392_b_api"))
