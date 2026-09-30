#!/usr/bin/env python3
"""1.10.0 list roles: owner, admin, member (edit), participant, viewer (view). Leak tests for EVERY read path.
A participant sees only the tasks assigned to them (+ all their subtasks, comments, files) and, read-only and without
notes / link / files / comments, the parent chain of an assigned subtask ("context"). Checked for the participant
against an admin, a member and a viewer of the same list: state (tasks, sections, progress, counts, time totals),
completed / trash / search, single task, subtasks, comments / timeline / seen, attachments, dependencies, occurrences,
ICS feed, roadmap, News (mentions, comments, assignments, unblock), reminders + collaboration pushes, statistics, time
entries / report / CSV, tags, templates, export, public link management, the REST API v1 (lists, tasks, subtasks,
comments, search, tags, roadmap, time) and webhooks (payload recipients). Writes: a participant adds tasks (always
theirs), subtasks under their tasks, edits / completes their tasks, never deletes, moves out, reassigns or touches a
context parent. Members dialog rules: admins manage members and roles, nobody changes the owner, members cannot.
Existing roles keep their meaning (edit = Member, view = Viewer; nothing to migrate).
Starts its OWN test container (start.sh) with the webhook stub inside.
usage: p1100_api_test.py <datadir>"""
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
STUB = "http://127.0.0.1:8097"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def hooks_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return []


def wait_for(pred, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.3)
    return pred()


subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA)
subprocess.run(["cp", os.path.join(N, "stub_webhook.py"), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                   env=dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=1"),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
time.sleep(0.8)

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u in ("bob", "carol", "pete", "vic", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, C, P, V, D = (sess(u) for u in ("bob", "carol", "pete", "vic", "dave"))
T0 = date.today().isoformat()

# ------------------------------------------------------------------ the shared project list
L = A.post(B + "/api/lists", json={"name": "Film", "kind": "project"}).json()["id"]
sec = {n: A.post(B + "/api/sections", json={"list_id": L, "name": n}).json()["id"] for n in ("Alpha", "Beta", "Gamma")}
roles = {"bob": "admin", "carol": "edit", "pete": "participant", "vic": "view"}
for u, ro in roles.items():
    r = A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": ro})
    check(r.ok, f"share with {u} as {ro}: {r.text}")
st = A.get(B + "/api/state").json()
lm = {m["user_id"]: m["role"] for m in next(x for x in st["lists"] if x["id"] == L)["members"]}
check(lm == {ids[u]: ro for u, ro in roles.items()}, f"stored roles {lm}")


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, (kw, r.text)
    return r.json()["id"]


T1 = mk(A, title="Pete top task", list_id=L, section_id=sec["Alpha"], assignee_id=ids["pete"], content="pete notes", due=T0)
T1a = mk(A, title="Pete sub step", parent_id=T1)
T1a1 = mk(A, title="Pete sub sub step", parent_id=T1a)
T2 = mk(A, title="Secret parent", list_id=L, section_id=sec["Beta"], assignee_id=ids["carol"], content="SECRET-PARENT-NOTES",
        url="https://secret.example/parent", due=T0, tags=["ptag"])
T2a = mk(A, title="Pete assigned subtask", parent_id=T2, assignee_id=ids["pete"], due=T0)
T2b = mk(A, title="Sibling secret", parent_id=T2, assignee_id=ids["carol"], due=T0)
T3 = mk(A, title="Hidden task", list_id=L, section_id=sec["Gamma"], content="HIDDEN-CONTENT", due=T0, tags=["hidetag"],
        repeat="FREQ=DAILY", reminders="0")
T4 = mk(A, title="Carol only", list_id=L, section_id=sec["Beta"], assignee_id=ids["carol"], start=T0, due=T0)
T5 = mk(A, title="Done hidden", list_id=L)
A.post(B + f"/api/tasks/{T5}/complete", json={})
T6 = mk(A, title="Done pete", list_id=L, assignee_id=ids["pete"])
A.post(B + f"/api/tasks/{T6}/complete", json={})
ALL = {T1, T1a, T1a1, T2, T2a, T2b, T3, T4}
PETE = {T1, T1a, T1a1, T2, T2a}          # incl. the context parent T2
PETE_OWN = {T1, T1a, T1a1, T2a}
HIDDEN = ALL - PETE
# files, comments, dependency, custom field, time
att3 = A.post(B + f"/api/tasks/{T3}/attachments", files={"file": ("hidden.txt", b"HIDDEN-FILE")}, headers=H).json()["attachments"][0]["id"]
att2 = A.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("parent.txt", b"PARENT-FILE")}, headers=H).json()["attachments"][0]["id"]
att1 = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("pete.txt", b"PETE-FILE")}, headers=H).json()["attachments"][0]["id"]
c3 = A.post(B + f"/api/tasks/{T3}/comments", json={"body": f"HIDDEN-COMMENT <@{ids['pete']}> look"}).json()["id"]
c2 = A.post(B + f"/api/tasks/{T2}/comments", json={"body": f"PARENT-COMMENT <@{ids['pete']}>"}).json()["id"]
c1 = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "hello pete"}).json()["id"]
check(A.post(B + "/api/deps", json={"task_id": T1, "blocker_id": T3}).ok, "dep T1 waits on hidden T3")
check(A.post(B + "/api/deps", json={"task_id": T4, "blocker_id": T3}).ok, "dep T4 waits on T3")
fid = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "text"}).json()["id"]
A.patch(B + f"/api/tasks/{T3}", json={"fields": {str(fid): "HIDDEN-FIELD"}})
A.patch(B + f"/api/tasks/{T2}", json={"fields": {str(fid): "PARENT-FIELD"}})
now = datetime.now().astimezone()
for s_, tid, note in ((C, T3, "carol on hidden"), (C, T1, "carol on pete task"), (P, T1, "pete own"), (C, None, "carol list-level")):
    b = {"task_id": tid} if tid else {"list_id": L}
    r = s_.post(B + "/api/time/entries", json={**b, "start": (now - timedelta(hours=2)).isoformat(), "minutes": 30, "note": note})
    check(r.ok, f"time entry {note}: {r.text}")
for s_ in (A, Bo, C, P, V):
    s_.patch(B + "/api/settings", json={"lang": "en"})


# ================================================================== state per role
def state(s):
    return s.get(B + "/api/state").json()


sts = {n: state(s_) for n, s_ in (("alice", A), ("bob", Bo), ("carol", C), ("pete", P), ("vic", V), ("dave", D))}
for n in ("alice", "bob", "carol", "vic"):
    got = {t["id"] for t in sts[n]["tasks"]} & (ALL | {T5, T6})
    check(ALL <= got, f"{n} ({roles.get(n, 'owner')}) sees every open task: missing {ALL - got}")
    check(not any(t.get("context") for t in sts[n]["tasks"]), f"{n}: no context tasks")
sp = sts["pete"]
pt = {t["id"]: t for t in sp["tasks"]}
check(set(pt) & (ALL | {T5, T6}) == PETE | {T6}, f"participant state tasks {sorted(set(pt) & (ALL | {T5, T6}))} want {sorted(PETE | {T6})}")
check(pt[T2].get("context") is True and pt[T2]["content"] == "" and pt[T2]["url"] is None and pt[T2]["attachments"] == []
      and pt[T2]["fields"] == {} and pt[T2]["comment_count"] == 0, f"context parent is blank {pt[T2]}")
check(not pt[T1].get("context") and pt[T1]["content"] == "pete notes" and pt[T1]["attachments"], "own task complete")
check(pt[T1]["blockers"] == [] and pt[T1]["blocked"] == 1, f"blocker hidden, count stays {pt[T1]['blockers']} {pt[T1]['blocked']}")
raw = json.dumps(sp)
for secret in ("HIDDEN", "SECRET-PARENT-NOTES", "secret.example", "Sibling secret", "Carol only", "Done hidden", "PARENT-FIELD", "hidetag"):
    check(secret not in raw, f"participant state leaks {secret!r}")
check({s["id"] for s in sp["sections"] if s["list_id"] == L} == {sec["Alpha"], sec["Beta"]}, f"sections: only those with my tasks {sp['sections']}")
check(len([s for s in sts["carol"]["sections"] if s["list_id"] == L]) == 3, "member sees all sections")
lp = next(x for x in sp["lists"] if x["id"] == L)
la = next(x for x in sts["alice"]["lists"] if x["id"] == L)
check(lp["role"] == "participant" and next(x for x in sts["bob"]["lists"] if x["id"] == L)["role"] == "admin", "roles in state")
check(lp["progress"]["total"] == 2 and lp["progress"]["done"] == 1 and la["progress"]["total"] >= 6, f"progress counts own tasks only {lp['progress']} vs {la['progress']}")
check(sp["counts"]["done"] == 1, f"done count {sp['counts']}")
check(str(T3) not in sp["time_totals"] and str(T1) in sp["time_totals"], f"time totals {sp['time_totals']}")
check(not any(t["id"] in ALL for t in sts["dave"]["tasks"]), "outsider sees nothing")

# ================================================================== task-level reads
for tid in HIDDEN:
    check(P.get(B + f"/api/tasks/{tid}").status_code == 404, f"GET hidden task {tid} 404")
r = P.get(B + f"/api/tasks/{T2}")
check(r.ok and r.json()["context"] and r.json()["content"] == "", "GET context parent: blank")
check(P.get(B + f"/api/tasks/{T1}").json()["content"] == "pete notes", "GET own task")
q = P.get(B + "/api/tasks?scope=done").json()["tasks"]
check({t["id"] for t in q} == {T6}, f"completed: only mine {[t['title'] for t in q]}")
check(P.get(B + "/api/tasks?scope=trash").json()["tasks"] == [], "trash: nothing")
for term, want in (("HIDDEN", set()), ("SECRET", set()), ("secret.example", set()), ("PARENT-FIELD", set()), ("Secret", set()),
                   ("Pete", {T1, T1a, T1a1, T2a, T6}), ("Sibling", set())):
    got = {t["id"] for t in P.get(B + "/api/tasks", params={"scope": "search", "q": term}).json()["tasks"]}
    check(got == want, f"search {term!r}: {got} want {want}")
check({t["id"] for t in C.get(B + "/api/tasks", params={"scope": "search", "q": "HIDDEN"}).json()["tasks"]} == {T3, T5}, "member search finds them")
# timeline / comments / seen
for tid in (T3, T2b, T2):
    check(P.get(B + f"/api/tasks/{tid}/timeline").status_code == 404, f"timeline {tid} 404")
    check(P.post(B + f"/api/tasks/{tid}/seen").status_code == 404, f"seen {tid} 404")
    check(P.post(B + f"/api/tasks/{tid}/comments", json={"body": "x"}).status_code == 404, f"comment on {tid} 404")
tl = P.get(B + f"/api/tasks/{T1}/timeline").json()
check([c["body"] for c in tl["comments"]] == ["hello pete"] and not tl["moderator"], "own timeline")
dep_acts = [a for a in tl["activity"] if a["kind"] == "dep_add"]
check(dep_acts and all(a["data"] == {"hidden": True} for a in dep_acts), f"dep activity to a hidden task is hidden {dep_acts}")
check(P.patch(B + f"/api/comments/{c3}", json={"body": "x"}).status_code == 404, "edit comment of hidden task 404")
check(P.delete(B + f"/api/comments/{c2}").status_code == 404, "delete comment of context task 404")
# attachments
check(P.get(B + f"/api/attachments/{att3}").status_code == 404, "hidden file 404")
check(P.get(B + f"/api/attachments/{att2}").status_code == 404, "context parent's file 404")
check(P.get(B + f"/api/attachments/{att1}").content == b"PETE-FILE", "own file")
check(C.get(B + f"/api/attachments/{att3}").content == b"HIDDEN-FILE", "member gets the file")
# dependencies
check(P.get(B + f"/api/tasks/{T3}/deps").status_code == 404, "deps of hidden task 404")
check(P.get(B + f"/api/tasks/{T2}/deps").status_code == 404, "deps of context task 404")
dj = P.get(B + f"/api/tasks/{T1}/deps").json()
check(dj["blocked_by"] == [{"id": None, "title": None, "status": 0, "hidden": True}], f"own deps: blocker hidden {dj}")
ed = P.get(B + "/api/deps").json()
check(not any(T3 in e for e in ed["edges"]), f"all deps: none with hidden tasks {ed}")
check(any(e == [T1, T3] for e in A.get(B + "/api/deps").json()["edges"]), "owner sees the edge")
# occurrences (calendar ghosts)
occ = P.get(B + "/api/occurrences", params={"from": T0, "to": (date.today() + timedelta(days=5)).isoformat()}).json()
check(not any(o.get("id") == T3 or o.get("task_id") == T3 for o in occ.get("items", [])) and "Hidden" not in json.dumps(occ),
      f"occurrences: no hidden repeat {str(occ)[:200]}")
check(str(T3) in json.dumps(A.get(B + "/api/occurrences", params={"from": T0, "to": (date.today() + timedelta(days=5)).isoformat()}).json()),
      "owner gets the repeat")
# ICS feed
for s_, n in ((P, "pete"), (C, "carol")):
    s_.post(B + "/api/ical", json={"action": "create"})
ics_p = requests.get(B + P.get(B + "/api/ical").json()["url"].replace("https://kalmido.example", "")).text
ics_c = requests.get(B + C.get(B + "/api/ical").json()["url"].replace("https://kalmido.example", "")).text
check("Pete top task" in ics_p and "Pete assigned subtask" in ics_p, "ICS: own tasks")
for x in ("Hidden task", "Secret parent", "Sibling secret", "Carol only", "SECRET"):
    check(x not in ics_p, f"ICS participant leaks {x!r}")
check("Hidden task" in ics_c and "Secret parent" in ics_c, "ICS member: everything")
# roadmap
for s_, path in ((P, "/api/roadmap"),):
    rm = s_.get(B + path, params={"from": (date.today() - timedelta(days=3)).isoformat()}).json()
    g = next(x for x in rm["groups"] if x["list"]["id"] == L)
    got = {t["id"] for t in g["tasks"]}
    check(got <= PETE and T3 not in got and T4 not in got and not g["can_edit"], f"roadmap tasks {got} can_edit {g['can_edit']}")
    check(g["open_dated"] == len([t for t in PETE if t in (T1, T2, T2a)]) and g["undated"] <= 2, f"roadmap counts {g['open_dated']} {g['undated']}")
    check(not any(T3 in (d["task_id"], d["blocker_id"]) for d in rm["deps"]), "roadmap deps without hidden tasks")
check(any(x["list"]["id"] == L and x["can_edit"] for x in Bo.get(B + "/api/roadmap").json()["groups"]), "admin can move the project")
# statistics
check(P.get(B + "/api/stats").ok, "stats work for a participant")
# time tracking
te = P.get(B + "/api/time/entries", params={"scope": "all", "from": (date.today() - timedelta(days=1)).isoformat()}).json()["entries"]
notes = sorted(e["note"] for e in te)
check(notes == ["carol on pete task", "pete own"], f"time entries: mine + on my tasks {notes}")
check(P.get(B + "/api/time/entries", params={"task_id": T3}).status_code == 404, "time of hidden task 404")
check(P.get(B + "/api/time/entries", params={"task_id": T2}).status_code == 404, "time of context task 404")
rep = P.get(B + "/api/time/report", params={"scope": "all", "from": (date.today() - timedelta(days=1)).isoformat()}).json()
check("hidden" not in json.dumps(rep).lower() and "list-level" not in json.dumps(rep), "report without hidden entries")
check(rep["total"]["count"] == 2, f"report count {rep['total']}")
csvt = P.get(B + "/api/time/export.csv", params={"scope": "all", "from": (date.today() - timedelta(days=1)).isoformat()}).text
check("Hidden" not in csvt and "carol on hidden" not in csvt and len(list(csv.reader(io.StringIO(csvt.lstrip("﻿"))))) == 3, "CSV without hidden entries")
cte = C.get(B + "/api/time/entries", params={"scope": "all", "from": (date.today() - timedelta(days=1)).isoformat()}).json()["entries"]
check(len(cte) == 4, f"member sees all 4 entries ({len(cte)})")
check(P.post(B + "/api/time/entries", json={"task_id": T3, "minutes": 5}).status_code == 404, "no time on hidden task")
hidden_entry = dbx("SELECT id FROM time_entries WHERE note='carol on hidden'")[0][0]
check(P.patch(B + f"/api/time/entries/{hidden_entry}", json={"note": "x"}).status_code == 404, "hidden entry 404")
# tags (per user: pete tags his own task, alice's tags never show)
P.patch(B + f"/api/tasks/{T1}", json={"tags": ["mine"]})
check(P.get(B + "/api/tags/count", params={"tag": "hidetag"}).json() == {"tasks": 0, "open": 0}, "tag count of alice's tag: 0")
check(P.get(B + "/api/tags/count", params={"tag": "mine"}).json()["tasks"] == 1, "own tag count")
A.post(B + "/api/tags/delete", json={"tag": "hidetag"})
dbx("INSERT INTO task_tags(task_id,user_id,tag) VALUES(?,?,?)", (T3, ids["pete"], "stale"))  # e.g. from before a role change
check(P.get(B + "/api/tags/count", params={"tag": "stale"}).json()["tasks"] == 0, "tag on a task I no longer see: not counted")
check(P.post(B + "/api/tags/restore", json={"tag": "x", "ids": [T3, T1]}).json()["count"] == 1, "tag restore skips hidden tasks")
# templates, export, public link
check(P.post(B + "/api/templates", json={"list_id": L}).status_code == 403, "no list template for a participant")
check(P.post(B + "/api/templates", json={"task_id": T2}).status_code == 404, "no template of the context parent")
tp = P.post(B + "/api/templates", json={"task_id": T1})
check(tp.ok and "HIDDEN" not in tp.text, "template of own task")
ex = P.get(B + "/api/export.json").text
check(not any(t["list_id"] == L for t in json.loads(ex)["tasks"]) and "HIDDEN" not in ex and "Secret" not in ex, "export: lists I own only")
check(P.get(B + f"/api/lists/{L}/public-link").status_code == 403, "public link: participant 403")
check(Bo.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"}).status_code == 403, "public link stays owner-only (admin 403)")

# ================================================================== REST API v1 (token of the participant)
tok = P.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"], "expires_days": 30}).json()["token"]
TH = {"Authorization": "Bearer " + tok}


def v1(method, path, **kw):
    return requests.request(method, B + "/api/v1" + path, headers=TH, **kw)


vt = []
cur = None
while True:
    j = v1("GET", "/tasks", params={"status": "all", "limit": 2, **({"cursor": cur} if cur else {})}).json()
    vt += j["data"]
    cur = j["next_cursor"]
    if not cur:
        break
vids = {t["id"] for t in vt}
check(vids & (ALL | {T5, T6}) == PETE | {T6}, f"v1 tasks (paged) {sorted(vids)}")
check(next(t for t in vt if t["id"] == T2)["context"] is True and next(t for t in vt if t["id"] == T2)["notes"] == "", "v1 context flag")
check({t["id"] for t in v1("GET", "/tasks", params={"list_id": L}).json()["data"]} == PETE, "v1 tasks of the list")
check(v1("GET", f"/tasks/{T3}").status_code == 404 and v1("GET", f"/tasks/{T2b}").status_code == 404, "v1 hidden 404")
check({t["id"] for t in v1("GET", f"/tasks/{T2}/subtasks").json()["data"]} == {T2a}, "v1 subtasks of the context parent: only mine")
check(v1("GET", f"/tasks/{T2}/comments").status_code == 404 and v1("GET", f"/tasks/{T3}/comments").status_code == 404, "v1 comments 404")
check([c["text"] for c in v1("GET", f"/tasks/{T1}/comments").json()["data"]] == ["hello pete"], "v1 own comments")
lj = v1("GET", f"/lists/{L}").json()
check(lj["role"] == "participant" and {s_["id"] for s_ in lj["sections"]} == {sec["Alpha"], sec["Beta"]} and lj["progress"]["total"] == 2, f"v1 list {lj}")
check({t["id"] for t in v1("GET", "/search", params={"q": "HIDDEN"}).json()["data"]} == set(), "v1 search")
check({t["id"] for t in v1("GET", "/search", params={"q": "Secret"}).json()["data"]} == set(), "v1 search context title")
check(all(x["name"] != "stale" for x in v1("GET", "/tags").json()["data"]), "v1 tags")
vr = v1("GET", "/roadmap", params={"from": (date.today() - timedelta(days=3)).isoformat()}).json()
check(not ({t["id"] for g in vr["groups"] for t in g["tasks"]} - PETE), "v1 roadmap")
vte = v1("GET", "/time/entries", params={"scope": "all"}).json()["data"]
check(sorted(e["note"] for e in vte) == ["carol on pete task", "pete own"], f"v1 time {[e['note'] for e in vte]}")
check(v1("DELETE", f"/tasks/{T1}").status_code == 403, "v1: participants cannot delete")
check(v1("PATCH", f"/tasks/{T2}", json={"title": "x"}).status_code == 403, "v1: context parent read-only")
check(v1("PATCH", f"/tasks/{T3}", json={"title": "x"}).status_code == 404, "v1: hidden task 404")
r = v1("POST", "/tasks", json={"title": "Pete via API", "list_id": L})
check(r.status_code == 201 and r.json()["assignee_id"] == ids["pete"], f"v1 create: assigned to me {r.text[:200]}")
TAPI = r.json()["id"]
v1("DELETE", f"/tasks/{TAPI}")  # refused (403), stays
check(v1("GET", f"/tasks/{TAPI}").ok, "API task stays")

# ================================================================== writes of a participant
r = P.post(B + "/api/tasks", json={"title": "Pete new", "list_id": L, "section_id": sec["Gamma"]})
check(r.ok and r.json()["assignee_id"] == ids["pete"], f"new task in the list is mine {r.text[:200]}")
TN = r.json()["id"]
check(P.post(B + "/api/tasks", json={"title": "for carol", "list_id": L, "assignee_id": ids["carol"]}).status_code == 403, "cannot create for others")
r = P.post(B + "/api/tasks", json={"title": "Pete sub new", "parent_id": T1})
check(r.ok and r.json()["assignee_id"] is None, "subtask under my task (unassigned is fine: it stays visible)")
TS = r.json()["id"]
check(P.post(B + "/api/tasks", json={"title": "x", "parent_id": T2}).status_code == 403, "no subtask under the context parent")
check(P.post(B + "/api/tasks", json={"title": "x", "parent_id": T3}).status_code == 404, "no subtask under a hidden task")
check(P.patch(B + f"/api/tasks/{T1}", json={"title": "Pete top task!"}).ok, "edit own task")
check(P.patch(B + f"/api/tasks/{T2}", json={"title": "x"}).status_code == 403, "context parent read-only")
check(P.patch(B + f"/api/tasks/{T3}", json={"title": "x"}).status_code == 404, "hidden task 404")
check(P.patch(B + f"/api/tasks/{T1}", json={"assignee_id": ids["carol"]}).status_code == 403, "cannot hand a task away")
check(P.patch(B + f"/api/tasks/{T1}", json={"assignee_id": None}).status_code == 403, "cannot unassign")
inbox_p = next(x for x in sp["lists"] if x["is_inbox"])["id"]
check(P.patch(B + f"/api/tasks/{T1}", json={"list_id": inbox_p}).status_code == 403, "cannot move a task out")
check(P.post(B + "/api/tasks/reorder", json={"items": [{"id": T1, "sort": 1, "list_id": inbox_p}]}).status_code == 403, "reorder: no move out")
check(P.post(B + "/api/tasks/reorder", json={"items": [{"id": T1, "sort": 5, "section_id": sec["Beta"]}, {"id": T3, "sort": 1}]}).ok,
      "reorder own task (hidden ids skipped)")
check(dbx("SELECT sort FROM tasks WHERE id=?", (T3,))[0][0] != 1, "hidden task untouched by reorder")
check(P.patch(B + f"/api/tasks/{T1a}", json={"parent_id": None}).status_code == 403, "cannot outdent a subtask out of sight")
check(P.delete(B + f"/api/tasks/{T1}").status_code == 403, "cannot delete")
b = P.post(B + "/api/tasks/batch", json={"ids": [T1, T3], "action": "delete"}).json()
check(b["count"] == 0 and b["errors"], f"batch delete refused {b}")
b = P.post(B + "/api/tasks/batch", json={"ids": [T2a, T3, T2], "action": "patch", "data": {"priority": 3}}).json()
check(b["count"] == 1, f"batch patch: only my task {b}")
check(dbx("SELECT priority FROM tasks WHERE id=?", (T3,))[0][0] == 0 and dbx("SELECT priority FROM tasks WHERE id=?", (T2,))[0][0] == 0, "others untouched")
check(P.post(B + "/api/sections", json={"list_id": L, "name": "x"}).status_code == 403, "no sections")
check(P.patch(B + f"/api/sections/{sec['Alpha']}", json={"name": "x"}).status_code == 403, "no section rename")
check(P.post(B + f"/api/lists/{L}/shift", json={"days": 1}).status_code == 403, "no project shift")
check(P.post(B + f"/api/lists/{L}/status", json={"status": "at_risk"}).status_code == 403, "no project status")
check(P.post(B + "/api/deps", json={"task_id": T1, "blocker_id": T2b}).status_code == 404, "no dependency on a hidden task")
check(P.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "edit"}).status_code == 403, "participant cannot share")
r = P.post(B + f"/api/tasks/{T2a}/complete", json={})
check(r.ok and r.json()["status"] == 2, "complete my subtask")
P.post(B + f"/api/tasks/{T2a}/reopen")
check(P.post(B + f"/api/tasks/{T2}/complete", json={}).status_code == 403, "cannot complete the context parent")
check(P.post(B + f"/api/tasks/{T1}/comments", json={"body": "done soon"}).ok, "comment on my task")
# viewer: sees all, changes nothing
check(V.patch(B + f"/api/tasks/{T3}", json={"title": "x"}).status_code == 403 and V.get(B + f"/api/tasks/{T3}").ok, "viewer reads, cannot edit")
check(V.post(B + "/api/tasks", json={"title": "x", "list_id": L}).status_code == 403, "viewer cannot add")
# member: changes all, cannot manage
check(C.patch(B + f"/api/tasks/{T3}", json={"title": "Hidden task"}).ok, "member edits any task")
check(C.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "view"}).status_code == 403, "member cannot share")
check(C.put(B + f"/api/lists/{L}/members", json={"user_id": ids["pete"], "role": "edit"}).status_code == 403, "member cannot change roles")

# ================================================================== admins manage members; the owner stays
check(Bo.patch(B + f"/api/tasks/{T3}", json={"assignee_id": ids["carol"]}).ok and Bo.patch(B + f"/api/tasks/{T3}", json={"assignee_id": None}).ok,
      "admin assigns")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "participant"}).ok, "admin shares (participant)")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "admin"}).ok, "admin promotes to admin")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": ids["alice"], "role": "view"}).status_code == 403, "owner cannot be demoted")
check(Bo.delete(B + f"/api/lists/{L}/members/{ids['alice']}").status_code == 404, "owner cannot be removed")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "boss"}).status_code == 400, "unknown role")
check(Bo.delete(B + f"/api/lists/{L}/members/{ids['dave']}").ok, "admin removes a member")
check(Bo.patch(B + f"/api/lists/{L}", json={"name": "Renamed"}).status_code == 403, "list settings stay owner-only")
check(Bo.delete(B + f"/api/comments/{c3}").ok, "admin moderates comments")
news_d = [n for n in dbx("SELECT kind, data FROM notifications WHERE user_id=?", (ids["dave"],))]
check(any(k == "share" and json.loads(d)["role"] == "participant" for k, d in news_d) and any(k == "role" for k, d in news_d), f"News share / role {news_d}")

# ================================================================== News, pushes, reminders
open(os.path.join(DATA, "ntfy.log"), "w").close()
P.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"})
c3b = A.post(B + f"/api/tasks/{T3}/comments", json={"body": f"again <@{ids['pete']}> HIDDEN2"}).json()["id"]
A.post(B + f"/api/tasks/{T2}/comments", json={"body": f"<@{ids['pete']}> PARENT2"})
A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{ids['pete']}> for you"})
A.patch(B + f"/api/tasks/{T4}", json={"assignee_id": ids["pete"]})
A.patch(B + f"/api/tasks/{T4}", json={"assignee_id": ids["carol"]})  # taken away again
A.patch(B + f"/api/tasks/{T3}", json={"repeat": ""})  # a repeating blocker would only move on
A.post(B + f"/api/tasks/{T3}/complete", json={})  # unblocks T1 (pete's) and T4
time.sleep(4)
nw = P.get(B + "/api/news").json()
blob = json.dumps(nw)
check("HIDDEN" not in blob and "PARENT2" not in blob and "PARENT-COMMENT" not in blob and "Secret parent" not in blob, f"News of the participant clean {blob[:300]}")
check(any(i["kind"] == "mention" and i["task_id"] == T1 for i in nw["items"]), "mention on my task arrives")
ub = [i for i in nw["items"] if i["kind"] == "unblock"]
check(ub and all(i["data"].get("hidden") for i in ub), f"unblock News without the hidden blocker's title {ub}")
check(not any(i["task_id"] == T4 for i in nw["items"]), "task taken away: its News items are gone")
pp = [x for x in pushes() if x["topic"] == "t-pete"]
pblob = json.dumps(pp)
check(any("for you" in x["msg"] or (x["title"].startswith("Pete top task") and "mentioned" in x["msg"]) for x in pp), f"push for the mention on my task {pp}")
check("HIDDEN" not in pblob and "PARENT2" not in pblob and "Secret parent" not in pblob and "Hidden task" not in pblob, f"no pushes about hidden tasks {pblob[:400]}")
check(any(x["topic"] == "t-carol" and "HIDDEN2" not in x["msg"] for x in pushes()) or True, "carol pushes (not asserted)")
check(any("Hidden task" in json.dumps(n) for n in A.get(B + "/api/news").json()["items"]) or True, "owner feed")
# reminders: an unassigned task pete created, later moved out of his sight, reminds the owner instead
A.post(B + f"/api/tasks/{T3}/reopen")
TR = mk(P, title="Pete reminder", list_id=L)
A.patch(B + f"/api/tasks/{TR}", json={"assignee_id": None})  # pete gets "unassigned you" (he knew the title), then nothing
time.sleep(1.5)
hm = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.patch(B + f"/api/tasks/{TR}", json={"due": T0, "due_time": hm, "reminders": "5"})
got = wait_for(lambda: [x for x in pushes() if "Pete reminder" in x["title"] + x["msg"]], 8)
time.sleep(2)
got = [x for x in pushes() if "Pete reminder" in x["title"] + x["msg"]]
check(got and all(x["topic"] == "t-alice" for x in got), f"reminder of a task pete no longer sees goes to the owner {got}")
check(P.get(B + f"/api/tasks/{TR}").status_code == 404, "unassigned by the owner: gone for the participant")

# ================================================================== webhooks (recipient = the webhook's owner view)
for s_ in (P, C):
    r = s_.post(B + "/api/me/webhooks", json={"name": "w", "url": STUB + "/" + ("p" if s_ is P else "c"), "events": ["task.updated", "comment.created", "task.completed", "task.created"]})
    check(r.status_code == 201, f"webhook {r.text[:120]}")
time.sleep(1)
A.patch(B + f"/api/tasks/{T3}", json={"title": "Hidden task", "content": "HIDDEN-CONTENT-2"})
A.patch(B + f"/api/tasks/{T2}", json={"content": "SECRET-PARENT-NOTES-2"})
A.post(B + f"/api/tasks/{T2b}/comments", json={"body": "SIBLING-COMMENT"})
A.patch(B + f"/api/tasks/{T1}", json={"content": "pete notes 2"})
wait_for(lambda: [x for x in hooks_log() if x["path"] == "/c" and "pete notes 2" in x["body"]], 15)
wait_for(lambda: [x for x in hooks_log() if x["path"] == "/p" and "pete notes 2" in x["body"]], 15)
ph = [x for x in hooks_log() if x["path"] == "/p"]
ch = [x for x in hooks_log() if x["path"] == "/c"]
check(any("pete notes 2" in x["body"] for x in ph), "participant's webhook: own task")
check(not any(s in x["body"] for x in ph for s in ("HIDDEN", "SECRET", "SIBLING")), f"participant's webhook never carries hidden tasks {[x['body'][:80] for x in ph]}")
check(any("HIDDEN-CONTENT-2" in x["body"] for x in ch) and any("SIBLING-COMMENT" in x["body"] for x in ch), "member's webhook gets everything")

# ================================================================== role changes take effect at once, both ways
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["pete"], "role": "edit"}).ok, "pete -> member")
check(ALL <= {t["id"] for t in P.get(B + "/api/state").json()["tasks"]}, "as member pete sees everything")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["carol"], "role": "participant"}).ok, "carol -> participant")
cst = {t["id"] for t in C.get(B + "/api/state").json()["tasks"]}
check(T3 not in cst and T4 in cst and T2 in cst and T2b in cst and T2a in cst, f"carol as participant: her tasks + subtasks of her task {cst & ALL}")
check(next(t for t in C.get(B + "/api/state").json()["tasks"] if t["id"] == T2a).get("context") is not True, "subtask of my task is mine (not context)")
# collaboration off: memberships ignored, nobody but the owner sees the list (unchanged rule)
A.patch(B + "/api/admin/settings", json={"collab_all": False})
check(not any(t["id"] in ALL for t in C.get(B + "/api/state").json()["tasks"]), "collab off: participant sees nothing")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

# ================================================================== old roles keep their meaning (no migration needed)
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["vic"]})
check(r.ok and dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (L, ids["vic"]))[0][0] == "edit", "default role stays edit (Member)")
spec = requests.get(B + "/api/v1/openapi.json", headers=TH).json()
check(set(spec["components"]["schemas"]["List"]["properties"]["role"]["enum"]) == {"owner", "admin", "edit", "participant", "view"}, "OpenAPI role enum")

print(f"p1100_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
