#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.394.0 A (#3377): import from Linear (personal API key against a fake Linear inside the container, tests/fake_linear.py,
or Linear's CSV export) and the Jira CSV with issue type, story points and sprint. Own container (kt.fresh). Invented data only.
freelancer-matrix: tasks, lists
 - Linear by key: preview = nothing written, paging, teams = projects, status / priority / estimate / labels / type / cycle
   (sprint) / assignee (matched in the new project) / due / parent / comments / url, the new project gets points, ticket
   types and sprints on, an issue done in an old cycle keeps the cycle as a note, idempotent re-import, undo
 - the key: never in an answer, the import record, the server log or an error text; a wrong key (401 and the GraphQL
   authentication error), Linear's rate limit (429 and RATELIMITED), a broken / too big answer -> plain 400 texts;
   a key with blanks, api_key for another source, key and file together, neither -> 400; the v1 route with a write token,
   not with a read-only one; an organisation's workspace
 - Linear CSV: the columns, done / cancelled by the Completed / Canceled columns, another CSV refused
 - Jira CSV: Bug / Story / Task -> type, story points 5 kept and 20 as a note, the sprint of an open issue into the list's
   sprint of that name (reused) or a new planned one (the last of repeated Sprint columns), a done issue keeps it as a note,
   an unknown type stays in the head line; the undo removes the sprint it created and keeps the reused one
 - everything above as a person without an organisation (the main case)
usage: p2394_a_import_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, check, CT, DATA, dbx, done, H, sess, until  # noqa: E402

V = B + "/api/v1"
KEY = "lin_api_TESTKEY0123456789abcdef"
LIN = "http://127.0.0.1:8085/graphql"


def put(**st):
    base = {"key": KEY, "issues": ISSUES, "page": 2, "mode": ""}
    base.update(st)
    with open(os.path.join(DATA, "linear.json"), "w") as f:
        json.dump(base, f)


def lin(s, url=None, **form):
    r = s.post(url or B + "/api/import/linear", data={k: str(v) for k, v in form.items()})
    try:
        return r.status_code, r.json(), r.text
    except ValueError:
        return r.status_code, {}, r.text


def imp(s, src, name, data, **opts):
    r = s.post(f"{B}/api/import/{src}", files={"file": (name, data)}, data={k: str(v) for k, v in opts.items()})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text[:300]}


def task(title, uid):
    r = dbx("SELECT * FROM tasks WHERE title=? AND created_by=? AND deleted_at IS NULL ORDER BY id DESC", (title, uid))
    return r[0] if r else None


def tags(tid):
    return sorted(x[0] for x in dbx("SELECT tag FROM task_tags WHERE task_id=?", (tid,)))


def count(uid):
    return dbx("SELECT COUNT(*) FROM tasks WHERE created_by=? AND deleted_at IS NULL", (uid,))[0][0]


def flog():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "linear.log")).read().splitlines() if x.strip()]
    except OSError:
        return []


def issue(ident, title, team="Engineering", **k):
    it = {"identifier": ident, "title": title, "description": None, "priority": 0, "estimate": None, "dueDate": None,
          "createdAt": "2026-10-01T09:00:00.000Z", "completedAt": None, "canceledAt": None,
          "url": f"https://linear.app/acme/issue/{ident}", "state": {"name": "Todo", "type": "unstarted"},
          "team": {"name": team, "key": team[:3].upper()}, "project": None, "labels": {"nodes": []}, "assignee": None,
          "cycle": None, "parent": None, "comments": {"nodes": []}}
    it.update(k)
    return it


ISSUES = [
    issue("ENG-1", "Login page", description="Build **it** with the form", priority=1, estimate=3, dueDate="2026-12-01",
          state={"name": "In Progress", "type": "started"}, cycle={"name": None, "number": 3}, project={"name": "Website"},
          labels={"nodes": [{"name": "Bug"}, {"name": "Frontend"}]},
          assignee={"name": "Frida", "displayName": "frida", "email": "frida@example.com"},
          comments={"nodes": [{"body": "Second note", "createdAt": "2026-10-03T10:00:00.000Z", "user": {"name": "Gert", "displayName": "Gert"}},
                              {"body": "Looks good", "createdAt": "2026-10-02T10:00:00.000Z", "user": {"name": "Gert", "displayName": "Gert"}}]}),
    issue("ENG-2", "Signup flow", priority=3, estimate=4, cycle={"name": "Sprint Alpha", "number": 4}, parent={"identifier": "ENG-1"},
          labels={"nodes": [{"name": "Feature"}]}),
    issue("ENG-3", "Old cleanup", priority=4, estimate=2, state={"name": "Done", "type": "completed"},
          completedAt="2026-09-20T12:00:00.000Z", cycle={"name": None, "number": 1}),
    issue("ENG-4", "Dropped idea", state={"name": "Canceled", "type": "canceled"}, canceledAt="2026-09-21T12:00:00.000Z",
          labels={"nodes": [{"name": "Improvement"}]}),
    issue("OPS-1", "Server update", team="Operations", priority=2, parent={"identifier": "ENG-99"}),
]

# ================================================================== setup: own container with the fake Linear
kt.fresh(env={"KALMIDO_LINEAR_API": LIN, "KALMIDO_IMPORT_RATE": "500"})
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Acme", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FU, F = freelancer(B, A, "frida")
put()
subprocess.run(["cp", os.path.join(N, "fake_linear.py"), DATA], check=True)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_linear.py"], check=True)
st, j, raw = until(lambda: (lambda r: r if r[0] == 200 else None)(lin(F, api_key=KEY, dry_run=1, space="private")), 15) or (0, {}, "")

# ================================================================== Linear by key: preview
n0 = count(FU)
check(st == 200 and j.get("dry_run") is True and j["created"]["tasks"] == 5 and j["created"]["lists"] == 2,
      f"preview by key: 5 tasks in 2 new projects {st} {raw[:300]}")
check(j.get("created", {}).get("sprints") == 2, f"preview: two sprints (Cycle 3, Sprint Alpha) {j.get('created')}")
sm = {x["title"]: x for x in j.get("samples", [])}
check(sm.get("Login page", {}).get("ttype") == "bug" and sm["Login page"].get("points") == 3 and sm["Login page"].get("sprint") == "Cycle 3",
      f"preview samples show type, points and sprint {sm.get('Login page')}")
check(KEY not in raw, "the key is not in the preview's answer")
check(count(FU) == n0 and not dbx("SELECT 1 FROM lists WHERE owner_id=? AND name='Engineering'", (FU,)), "preview writes nothing")
lg = flog()
check(len(lg) >= 3 and all(x["auth"] and x["good"] for x in lg) and [x["after"] for x in lg[-3:]] == [None, "2", "4"],
      f"paging: three requests with the key, cursors None / 2 / 4 {lg[-3:]}")
check(all("Linear import" in (x.get("ua") or "") for x in lg), "own User-Agent")

# ================================================================== Linear by key: import
st, j, raw = lin(F, api_key=KEY, space="private")
check(st == 200 and j.get("import_id") and j["created"]["tasks"] == 5 and j["created"]["subtasks"] == 1 and j["created"]["assigned"] == 1,
      f"import by key {st} {raw[:300]}")
check(KEY not in raw, "the key is not in the import's answer")
eng = dbx("SELECT * FROM lists WHERE owner_id=? AND name='Engineering' AND deleted_at IS NULL", (FU,))
ops = dbx("SELECT * FROM lists WHERE owner_id=? AND name='Operations' AND deleted_at IS NULL", (FU,))
check(eng and ops and eng[0]["org_id"] is None, "teams = projects, private workspace")
check(eng and eng[0]["points_on"] == 1 and eng[0]["tickets"] == 1 and json.loads(eng[0]["sprint_cfg"] or "{}").get("on") is True,
      f"the new project: points, ticket types and sprints on {dict(eng[0]) if eng else None}")
check(ops and ops[0]["points_on"] == 0 and ops[0]["tickets"] == 0 and ops[0]["sprint_cfg"] == "", "a project without them: all off")
t1, t2, t3, t4, o1 = (task(x, FU) for x in ("Login page", "Signup flow", "Old cleanup", "Dropped idea", "Server update"))
check(t1 and t1["ttype"] == "bug" and t1["points"] == 3 and t1["priority"] == 5 and t1["status"] == 0 and t1["due"] == "2026-12-01"
      and t1["tt_id"] == "linear:ENG-1" and t1["url"] == "https://linear.app/acme/issue/ENG-1" and t1["assignee_id"] == FU,
      f"ENG-1: type, points, urgent = high, open, due, key, link, assignee matched {dict(t1) if t1 else None}")
c1 = t1["content"] if t1 else ""
check("Linear: ENG-1" in c1 and "Build **it** with the form" in c1 and "Status (Linear): In Progress" in c1 and "Project: Website" in c1,
      f"ENG-1: key, Markdown description, started state, project in the notes {c1!r}")
check("Comments (Linear):" in c1 and c1.find("Looks good") < c1.find("Second note") and "**Gert · 2026-10-02**" in c1,
      f"ENG-1: comments as a notes block, oldest first, with author and day {c1!r}")
check(t1 and tags(t1["id"]) == ["Bug", "Frontend"], f"labels = tags {tags(t1['id']) if t1 else None}")
spr = {r["name"]: r for r in dbx("SELECT * FROM sprints WHERE list_id=?", (eng[0]["id"],))} if eng else {}
check(set(spr) == {"Cycle 3", "Sprint Alpha"} and all(r["state"] in ("planned", "active") for r in spr.values()),
      f"two sprints from the cycles of open issues {list(spr)}")
check(t1 and spr.get("Cycle 3") and t1["sprint_id"] == spr["Cycle 3"]["id"] and t2 and spr.get("Sprint Alpha")
      and t2["sprint_id"] == spr["Sprint Alpha"]["id"], "open issues are in their cycle's sprint")
check(t2 and t2["ttype"] == "feature" and t2["points"] is None and "Estimate: 4" in t2["content"] and t2["parent_id"] == t1["id"],
      f"ENG-2: Feature label, estimate 4 (no story point) as a note, parent issue {dict(t2) if t2 else None}")
check(t3 and t3["status"] == 2 and str(t3["completed_at"]).startswith("2026-09-20") and t3["points"] == 2 and t3["sprint_id"] is None
      and "Sprint: Cycle 1" in t3["content"] and "Cycle 1" not in spr, f"ENG-3: done, its old cycle stays a note {dict(t3) if t3 else None}")
check(t4 and t4["status"] == -1 and t4["ttype"] == "feature", "ENG-4: canceled = cancelled, Improvement = feature")
check(o1 and o1["priority"] == 5 and o1["parent_id"] is None and o1["ttype"] == "", "OPS-1: high, unknown parent = main task")
check(any("Parent task not found" in w["text"] for w in j.get("warnings", [])), "a warning for the missing parent")
rec = dbx("SELECT * FROM imports WHERE id=?", (j.get("import_id"),))
check(rec and rec[0]["source"] == "linear" and rec[0]["file_name"] == "" and KEY not in json.dumps(dict(rec[0])),
      "the import record: source linear, no file name, no key")
act = dbx("SELECT data FROM activity WHERE task_id=? AND kind='import'", (t1["id"],)) if t1 else []
check(act and "Linear" in json.dumps(act[0][0]), "activity line names Linear")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check(KEY not in logs.stdout + logs.stderr, "the key is not in the server log")
check(not dbx("SELECT 1 FROM tasks WHERE content LIKE ? OR title LIKE ?", (f"%{KEY}%", f"%{KEY}%")), "the key is in no task")
st, j2, _ = lin(F, api_key=KEY, dry_run=1, space="private")
check(st == 200 and j2["created"]["tasks"] == 0 and j2["skipped"] == 5, f"again: everything skipped {j2.get('created')} {j2.get('skipped')}")
# the undo: tasks into the trash, the projects too (nothing else in them)
r = F.post(B + f"/api/imports/{j['import_id']}/undo")
check(r.ok and r.json()["tasks"] == 5 and r.json()["lists"] == 2, f"undo by key import {r.status_code} {r.text[:200]}")

# ================================================================== the key's failures
put(key="another-key")
st, j, raw = lin(F, api_key=KEY, dry_run=1)
check(st == 400 and "did not accept the API key" in j.get("error", "") and KEY not in raw and "another" not in raw,
      f"wrong key (401): plain text, no key {st} {raw[:200]}")
put(key="another-key", mode="auth_gql")
st, j, raw = lin(F, api_key=KEY, dry_run=1)
check(st == 400 and "did not accept the API key" in j.get("error", "") and KEY not in raw, f"wrong key (GraphQL error): {st} {raw[:200]}")
for mode in ("ratelimit", "ratelimit_gql"):
    put(mode=mode)
    st, j, raw = lin(F, api_key=KEY, dry_run=1)
    check(st == 400 and "limiting requests" in j.get("error", ""), f"rate limit ({mode}): {st} {raw[:200]}")
put(mode="broken")
st, j, raw = lin(F, api_key=KEY, dry_run=1)
check(st == 400 and "could not be read" in j.get("error", ""), f"a broken answer: {st} {raw[:200]}")
put(mode="big")
st, j, raw = lin(F, api_key=KEY, dry_run=1)
check(st == 400 and "more data" in j.get("error", ""), f"a too big answer: {st} {raw[:200]}")
put()
n_log = len(flog())
st, j, raw = lin(F, api_key="lin key with blanks", dry_run=1)
check(st == 400 and "not a Linear API key" in j.get("error", "") and len(flog()) == n_log, f"a key with blanks: 400, Linear not asked {st} {raw[:200]}")
st, j = imp(F, "jira", "j.csv", b"Summary,Issue key\nx,X-1\n", dry_run=1, api_key=KEY)
check(st == 400 and "api_key" in j.get("error", ""), f"api_key for another source: 400 {st} {j}")
r = F.post(B + "/api/import/linear", files={"file": ("l.csv", b"ID,Title,Status,Team\nA-1,a,Todo,T\n")}, data={"api_key": KEY, "dry_run": "1"})
check(r.status_code == 400 and KEY not in r.text, f"key and file together: 400 {r.status_code}")
st, j, raw = lin(F, dry_run=1)
check(st == 400, f"neither key nor file: 400 {st}")

# ================================================================== v1 route, organisation
tw = F.post(B + "/api/me/tokens", json={"name": "imp", "scopes": ["read", "write"]}).json()["token"]
tr_ = F.post(B + "/api/me/tokens", json={"name": "ro", "scopes": ["read"]}).json()["token"]
r = requests.post(V + "/import/linear", headers={"Authorization": "Bearer " + tw}, data={"api_key": KEY, "dry_run": "true"})
check(r.ok and r.json()["created"]["tasks"] == 5 and KEY not in r.text, f"v1 with a write token {r.status_code} {r.text[:200]}")
r = requests.post(V + "/import/linear", headers={"Authorization": "Bearer " + tr_}, data={"api_key": KEY, "dry_run": "true"})
check(r.status_code == 403, f"v1 with a read-only token: 403 {r.status_code}")
st, j, raw = lin(A, api_key=KEY, space=f"org:{ORG}")
check(st == 200 and j["created"]["tasks"] == 5, f"an organisation's workspace {st} {raw[:200]}")
check([x[0] for x in dbx("SELECT org_id FROM lists WHERE owner_id=1 AND name='Engineering' AND deleted_at IS NULL")] == [ORG],
      "the projects belong to the organisation")

# ================================================================== Linear CSV
LCSV = ("ID,Team,Title,Description,Status,Estimate,Priority,Project,Creator,Assignee,Labels,Cycle Number,Cycle Name,Due Date,"
        "Created,Completed,Canceled,Parent issue\n"
        'DES-1,Design,Logo draft,Sketch **three**,In Review,8,High,Brand,gert,gert@example.com,"Bug, UI",2,,2026-12-05,'
        "2026-10-01T10:00:00.000Z,,,\n"
        "DES-2,Design,Colours,,Done,1,Low,,gert,,,,,,2026-10-01T10:00:00.000Z,2026-10-10T08:00:00.000Z,,DES-1\n"
        "DES-3,Design,Old font,,Canceled,,No priority,,gert,,,,,,2026-10-01T10:00:00.000Z,,2026-10-11T08:00:00.000Z,\n").encode()
st, j = imp(F, "linear", "Linear export.csv", LCSV, dry_run=1, space="private")
check(st == 200 and j["created"]["tasks"] == 3 and j["lists"][0]["name"] == "Design", f"Linear CSV preview {st} {str(j)[:300]}")
st, j = imp(F, "linear", "Linear export.csv", LCSV, space="private")
d1, d2, d3 = (task(x, FU) for x in ("Logo draft", "Colours", "Old font"))
check(d1 and d1["tt_id"] == "linear:DES-1" and d1["points"] == 8 and d1["priority"] == 5 and d1["ttype"] == "bug"
      and d1["due"] == "2026-12-05" and tags(d1["id"]) == ["Bug", "UI"], f"CSV DES-1: points, priority, type, due, labels {dict(d1) if d1 else None}")
check(d1 and "Status (Linear): In Review" in d1["content"] and "Assignee (Linear): gert@example.com" in d1["content"]
      and "Project: Brand" in d1["content"] and d1["sprint_id"], f"CSV DES-1: state, assignee (not in the project) as text, cycle 2 = sprint {d1['content'] if d1 else ''}")
check(d2 and d2["status"] == 2 and str(d2["completed_at"]).startswith("2026-10-10") and d2["parent_id"] == d1["id"] and d2["points"] == 1,
      "CSV DES-2: done by the Completed column, parent issue")
check(d3 and d3["status"] == -1 and d3["priority"] == 0, "CSV DES-3: cancelled by the Canceled column")
st, j = imp(F, "linear", "x.csv", b"Title,Due\nx,2026-01-01\n", dry_run=1)
check(st == 400 and "not a Linear CSV" in j.get("error", ""), f"another CSV refused {st} {j}")

# ================================================================== Jira CSV: type, points, sprint
J = F.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
r = F.put(B + f"/api/lists/{J}/sprint-settings", json={"on": True})
check(r.ok and r.json().get("started_id"), f"setup: sprints on, sprint 1 started {r.text[:200]}")
S1 = r.json().get("started_id")
JI = ("Summary,Issue key,Issue id,Issue Type,Status,Resolution,Custom field (Story Points),Custom field (Story point estimate),"
      "Sprint,Sprint,Project name\n"
      "Login bug,APP-1,1,Bug,To Do,,5,,Sprint 1,,App\n"
      "Signup story,APP-2,2,Story,In Progress,,,20,Sprint 1,Sprint 2,App\n"
      "Old task,APP-3,3,Task,Done,Done,,,Sprint 0,,App\n"
      "Spike thing,APP-4,4,Spike,To Do,,,,,,App\n").encode()
st, pj = imp(F, "jira", "jira.csv", JI, dry_run=1, target=J)
check(st == 200 and pj["created"]["tasks"] == 4 and pj["created"]["sprints"] == 1, f"Jira preview: 4 tasks, one new sprint {st} {str(pj)[:300]}")
check(not dbx("SELECT 1 FROM sprints WHERE list_id=? AND name='Sprint 2'", (J,)), "the preview creates no sprint")
st, j = imp(F, "jira", "jira.csv", JI, target=J)
a1, a2, a3, a4 = (task(x, FU) for x in ("Login bug", "Signup story", "Old task", "Spike thing"))
s2 = dbx("SELECT id, state FROM sprints WHERE list_id=? AND name='Sprint 2'", (J,))
check(a1 and a1["ttype"] == "bug" and a1["points"] == 5 and a1["sprint_id"] == S1 and "Story points" not in a1["content"]
      and "Bug" not in a1["content"] and "Sprint" not in a1["content"],
      f"APP-1: Bug, 5 points, into the existing Sprint 1, no note lines for them {dict(a1) if a1 else None}")
check(a2 and a2["ttype"] == "feature" and a2["points"] is None and "Story points: 20" in a2["content"] and s2
      and a2["sprint_id"] == s2[0]["id"] and s2[0]["state"] == "planned",
      f"APP-2: Story = feature, 20 points as a note, the last sprint (new, planned) {dict(a2) if a2 else None}")
check(a3 and a3["ttype"] == "task" and a3["status"] == 2 and a3["sprint_id"] is None and "Sprint: Sprint 0" in a3["content"]
      and not dbx("SELECT 1 FROM sprints WHERE list_id=? AND name='Sprint 0'", (J,)), "APP-3: done, its sprint stays a note")
check(a4 and a4["ttype"] == "" and "Jira: APP-4 · Spike" in a4["content"], "APP-4: an unknown type stays in the head line")
r = F.post(B + f"/api/imports/{j['import_id']}/undo")
check(r.ok and r.json()["tasks"] == 4, f"Jira undo {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM sprints WHERE list_id=? AND name='Sprint 2'", (J,)) and dbx("SELECT 1 FROM sprints WHERE id=?", (S1,)),
      "the undo removes the sprint it created and keeps the reused one")
check(not dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NOT NULL AND sprint_id IS NOT NULL AND sprint_id NOT IN (SELECT id FROM sprints)", (J,)),
      "no task in the trash points to the removed sprint")

# ================================================================== review of 2.394 (leader): odd values
# a sprint name of only invisible characters is no sprint (was: a new sprint without name and a note line "Sprint: ")
n_spr = len(dbx("SELECT id FROM sprints WHERE list_id=?", (J,)))
st, j = imp(F, "jira", "jira2.csv", ("Summary,Issue key,Issue id,Issue Type,Status,Sprint,Project name\n"
                                     "Ghost sprint,APP-9,9,Task,To Do,\u200b\u202e,App\n").encode(), target=J)
g9 = task("Ghost sprint", FU)
check(st == 200 and g9 and g9["sprint_id"] is None and "Sprint:" not in (g9["content"] or "")
      and len(dbx("SELECT id FROM sprints WHERE list_id=?", (J,))) == n_spr, f"invisible sprint name = no sprint {st} {dict(g9) if g9 else j}")
# a Linear priority that is no number reads as none (was: TypeError, a 500)
put(issues=[issue("ODD-1", "Odd priority", team="Odd", priority=["x"])], page=50)
st, j, raw = lin(F, api_key=KEY, space="private")
o9 = task("Odd priority", FU)
check(st == 200 and o9 and o9["priority"] == 0, f"Linear priority as a list: imported without priority {st} {raw[:200]}")

sys.exit(done("p2394_a_import"))
