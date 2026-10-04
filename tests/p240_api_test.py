#!/usr/bin/env python3
"""2.4.0 API tests: subfolders (#361), project types (#243), project templates with relative dates (#328), ticket types
(#340) and quick capture (#187).
 - folders are paths of at most 2 levels ("Clients/Company X"): typed spaces around "/" are dropped, deeper is refused
   (web + API v1), the folder order (settings "folders") and the folded folders ("folders_closed") take paths
 - rename / move (POST /api/folders/rename): a top folder takes its subfolders along (lists, order, folded state), a
   subfolder moves into another folder or to the top level, a folder with subfolders cannot become a subfolder, a folder
   cannot go into itself; delete (POST /api/folders/delete): a top folder's subfolders become top-level folders, a
   subfolder's lists go to its parent; everything per user (a member's own folder rows, the owner's untouched)
 - migration: existing flat folder names with a "/" (owner rows, member rows, the stored order) stay top-level (U+2215)
 - project types: POST /api/lists {ptype} (sections in the person's language, custom fields, view, ticket types, "move
   dependent tasks along", the modules it needs switched on: modules_on), POST /api/v1/lists {project_type}, bad type 400,
   the setup's "Start with a project"
 - project templates (#328): POST /api/templates {list_id, relative} keeps dates relative to the project start (earliest
   start / due), the span, sections, fields, ticket settings and the dependencies (node keys); apply {start, end?}: dates
   from the start, stretched / squeezed to the end, dependencies re-created, bad / reversed dates 400; an edited template
   keeps its dependencies, one that would close a cycle is dropped
 - ticket types: list setting tickets (owner only), task ttype (web) / type (API v1, events, OpenAPI), a new bug / feature
   with empty notes gets the template (built-in in the person's language, or the list's own; not with ticket types off,
   not over given notes), changing the type of a task with empty notes fills them too, activity line, v1 filter ?type=
 - quick capture: GET /capture is the app, the manifest has the "Quick add" shortcut with its icons
Starts its OWN containers (start.sh).
usage: p240_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
C = "∕"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(keep=False):
    if not keep:
        # the container of the previous suite still writes into DATA: stop it first, or rm races it (CI: "Directory not empty")
        subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def stop():
    subprocess.run(["docker", "stop", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)


def dbx(q, a=()):
    con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        r = con.execute(q, a).fetchall()
        con.commit()
        return r
    finally:
        con.close()


def st(s):
    return s.get(B + "/api/state").json()


def lst(s, lid):
    return next(x for x in st(s)["lists"] if x["id"] == lid)


def folder(s, lid):
    return lst(s, lid)["folder"]


def settings(s):
    return st(s)["settings"]


import json  # noqa: E402

start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en"})
TOKA = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
VA = Api(TOKA)

# ================================================================== #361 folders as paths
L1 = A.post(B + "/api/lists", json={"name": "Website", "folder": " Clients /  Company X "}).json()["id"]
check(folder(A, L1) == "Clients/Company X", f"path normalized: {folder(A, L1)!r}")
L2 = A.post(B + "/api/lists", json={"name": "Retainer", "folder": "Clients"}).json()["id"]
L3 = A.post(B + "/api/lists", json={"name": "Shop", "folder": "Clients/Company Y"}).json()["id"]
L4 = A.post(B + "/api/lists", json={"name": "Garden", "folder": "Home"}).json()["id"]
r = A.post(B + "/api/lists", json={"name": "Deep", "folder": "A/B/C"})
check(r.status_code == 400 and "2 levels" in r.json().get("error", ""), f"3 levels refused: {r.status_code} {r.text[:80]}")
check(A.patch(B + f"/api/lists/{L4}", json={"folder": "Home/Outside/Beds"}).status_code == 400, "PATCH: 3 levels refused")
check(A.post(B + "/api/lists/reorder", json={"ids": [L4], "folder": {str(L4): "a/b/c"}}).status_code == 400, "reorder: 3 levels refused")
check(A.patch(B + "/api/settings", json={"folders": json.dumps(["Clients", "Clients/Company X", "Clients/Company Y", "Home"])}).ok,
      "folder order with paths")
check(A.patch(B + "/api/settings", json={"folders": json.dumps(["a/b/c"])}).status_code == 400, "folder order: 3 levels refused")
check(A.patch(B + "/api/settings", json={"folders_closed": json.dumps(["Clients/Company Y", "Home"])}).ok, "folded folders stored")
check(json.loads(settings(A)["folders_closed"]) == ["Clients/Company Y", "Home"], "folders_closed in the state")
check(A.patch(B + "/api/settings", json={"folders_closed": "nope"}).status_code == 400, "folders_closed: bad json 400")
check(A.patch(B + "/api/settings", json={"folders_closed": json.dumps([1])}).status_code == 400, "folders_closed: not text 400")
# API v1
j = VA.get("/lists").json()["data"]
check(next(x for x in j if x["id"] == L1)["folder"] == "Clients/Company X", "v1: folder path")
r = VA.post("/lists", json={"name": "V1 deep", "folder": "x/y/z"})
check(r.status_code == 400, f"v1: 3 levels refused ({r.status_code})")
r = VA.post("/lists", json={"name": "V1 sub", "folder": "Clients / Company Z"})
check(r.status_code == 201 and r.json()["folder"] == "Clients/Company Z", "v1: create in a subfolder")
L5 = r.json()["id"]
# a member's own placement
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "edit"}).ok, "share Website with bob")
check(Bo.patch(B + f"/api/lists/{L1}", json={"folder": "Work/Clients"}).ok, "member: own folder path")
check(folder(Bo, L1) == "Work/Clients" and folder(A, L1) == "Clients/Company X", "member path is bob's own")

# ---- rename / move
check(A.post(B + "/api/folders/rename", json={"old": "Clients", "new": "Customers"}).ok, "rename a top folder")
check(folder(A, L1) == "Customers/Company X" and folder(A, L2) == "Customers" and folder(A, L3) == "Customers/Company Y",
      "subfolders and lists move along")
check(folder(Bo, L1) == "Work/Clients", "bob's folders untouched")
o = json.loads(settings(A)["folders"])
check(o[:3] == ["Customers", "Customers/Company X", "Customers/Company Y"], f"order follows: {o}")
check("Customers/Company Y" in json.loads(settings(A)["folders_closed"]), "folded state follows the rename")
check(A.post(B + "/api/folders/rename", json={"old": "Customers/Company Y", "new": "Home/Company Y"}).ok, "subfolder into another folder")
check(folder(A, L3) == "Home/Company Y", "its list moved along")
check(A.post(B + "/api/folders/rename", json={"old": "Home/Company Y", "new": "Company Y"}).ok, "subfolder to the top level")
check(folder(A, L3) == "Company Y", "now top-level")
r = A.post(B + "/api/folders/rename", json={"old": "Customers", "new": "Home/Customers"})
check(r.status_code == 400, f"a folder with subfolders cannot become a subfolder ({r.status_code})")
check(folder(A, L1) == "Customers/Company X", "refused: nothing moved")
check(A.post(B + "/api/folders/rename", json={"old": "Customers", "new": "Customers/x"}).status_code == 400, "not into itself")
check(A.post(B + "/api/folders/rename", json={"old": "Company Y", "new": "Home/Company Y"}).ok, "a folder without subfolders nests")
check(folder(A, L3) == "Home/Company Y", "nested")
check(A.post(B + "/api/folders/rename", json={"old": "Home/Company Y", "new": "Home/Company Y/deeper"}).status_code == 400,
      "never 3 levels")
check(Bo.post(B + "/api/folders/rename", json={"old": "Work", "new": "Job"}).ok and folder(Bo, L1) == "Job/Clients", "member renames own folders")
check(folder(A, L1) == "Customers/Company X", "the owner's placement stays")
# ---- delete: children move up one level
check(A.post(B + "/api/folders/delete", json={"name": "Home/Company Y"}).ok, "delete a subfolder")
check(folder(A, L3) == "Home", "its lists go to the parent folder")
check(A.post(B + "/api/folders/delete", json={"name": "Customers"}).ok, "delete a top folder")
check(folder(A, L1) == "Company X" and folder(A, L2) == "" and folder(A, L5) == "Company Z",
      f"subfolders became top-level folders, the folder's own lists top level: {folder(A, L1)!r} {folder(A, L2)!r} {folder(A, L5)!r}")
o = json.loads(settings(A)["folders"])
check("Customers" not in o and "Company X" in o, f"order: the deleted folder is gone, its subfolders stay: {o}")
check(A.post(B + "/api/folders/delete", json={"name": ""}).status_code == 400, "delete: name missing 400")

# ================================================================== #340 ticket types
T1 = A.post(B + "/api/lists", json={"name": "App", "kind": "project", "tickets": True}).json()["id"]
check(lst(A, T1)["tickets"] == 1, "list created with ticket types on")
check(VA.get(f"/lists/{T1}").json()["tickets"] is True, "v1 list: tickets")
t = A.post(B + "/api/tasks", json={"title": "Crash on start", "list_id": T1, "ttype": "bug"}).json()
check(t["ttype"] == "bug" and "**Steps to reproduce**" in t["content"] and "**Environment**" in t["content"], "new bug: template notes")
t2 = A.post(B + "/api/tasks", json={"title": "Dark mode", "list_id": T1, "ttype": "feature", "content": "my notes"}).json()
check(t2["content"] == "my notes", "given notes are never replaced")
t3 = A.post(B + "/api/tasks", json={"title": "Refactor", "list_id": T1, "ttype": "task"}).json()
check(t3["content"] == "", "type task: no template")
check(A.post(B + "/api/tasks", json={"title": "x", "list_id": T1, "ttype": "epic"}).status_code == 400, "unknown type 400")
P = A.post(B + "/api/lists", json={"name": "Plain"}).json()["id"]
t4 = A.post(B + "/api/tasks", json={"title": "not a ticket list", "list_id": P, "ttype": "bug"}).json()
check(t4["content"] == "", "ticket types off: no template")
# German person, the list's own template
A.patch(B + "/api/settings", json={"lang": "de"})
t5 = A.post(B + "/api/tasks", json={"title": "Absturz", "list_id": T1, "ttype": "bug"}).json()
check("**Schritte zum Nachstellen**" in t5["content"], "German UI: German template")
A.patch(B + "/api/settings", json={"lang": "en"})
check(A.patch(B + f"/api/lists/{T1}", json={"ticket_tpl": {"feature": "## Why\n"}}).ok, "own feature template")
t6 = A.post(B + "/api/tasks", json={"title": "Export", "list_id": T1, "ttype": "feature"}).json()
check(t6["content"] == "## Why\n", "the list's own template")
check(A.patch(B + f"/api/lists/{T1}", json={"ticket_tpl": {"epic": "x"}}).status_code == 400, "template: unknown kind 400")
check(A.patch(B + f"/api/lists/{T1}", json={"ticket_tpl": {"bug": 5}}).status_code == 400, "template: not text 400")
# changing the type of a task with empty notes
t7 = A.post(B + "/api/tasks", json={"title": "Later a bug", "list_id": T1}).json()
u = A.patch(B + f"/api/tasks/{t7['id']}", json={"ttype": "bug"}).json()
check(u["ttype"] == "bug" and "**Expected**" in u["content"], "type changed on empty notes: template")
tl = A.get(B + f"/api/tasks/{t7['id']}/timeline").json()
acts = [x for x in (tl.get("items") or tl.get("activity") or []) if x.get("kind") == "ttype"] if isinstance(tl, dict) else []
check(acts or any(r[0] == "ttype" for r in dbx("SELECT kind FROM activity WHERE task_id=?", (t7["id"],))), "activity line for the type")
u = A.patch(B + f"/api/tasks/{t7['id']}", json={"ttype": ""}).json()
check(u["ttype"] == "", "type removed")
# owner only
check(A.put(B + f"/api/lists/{T1}/members", json={"user_id": BOB, "role": "edit"}).ok, "share App with bob")
check(Bo.patch(B + f"/api/lists/{T1}", json={"tickets": False}).status_code == 403, "member cannot switch ticket types")
check(Bo.patch(B + f"/api/lists/{T1}", json={"ticket_tpl": {"bug": "x"}}).status_code == 403, "member cannot change templates")
tb = Bo.post(B + f"/api/tasks", json={"title": "Bob's bug", "list_id": T1, "ttype": "bug"}).json()
check(tb["ttype"] == "bug", "a member files tickets")
# API v1 + filter + OpenAPI
r = VA.post("/tasks", json={"title": "Via API", "list_id": T1, "type": "feature"})
check(r.status_code == 201 and r.json()["type"] == "feature" and r.json()["notes"] == "## Why\n", "v1: type + template")
check(VA.post("/tasks", json={"title": "x", "list_id": T1, "type": "epic"}).status_code == 400, "v1: unknown type 400")
vid = r.json()["id"]
check(VA.req("PATCH", f"/tasks/{vid}", json={"type": None}).json()["type"] is None, "v1: type null clears")
bugs = VA.get("/tasks", params={"list_id": T1, "type": "bug"}).json()["data"]
check(bugs and all(x["type"] == "bug" for x in bugs) and len(bugs) == 3, f"v1 filter ?type=bug ({len(bugs)})")
check(VA.get("/tasks", params={"type": "none", "list_id": T1}).json()["data"][0]["type"] is None, "v1 filter ?type=none")
check(VA.get("/tasks", params={"type": "x"}).status_code == 400, "v1 filter: bad type 400")
spec = requests.get(V + "/openapi.json").json()
check("type" in spec["components"]["schemas"]["Task"]["properties"] and "project_type" in spec["components"]["schemas"]["ListInput"]["properties"],
      "OpenAPI: Task.type, ListInput.project_type")
# agent events carry the type
ra = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"}).json()
CL = Api(ra["token"])
check(A.put(B + f"/api/lists/{T1}/members", json={"user_id": ra["id"], "role": "edit"}).ok, "share with the agent")
A.post(B + "/api/tasks", json={"title": "Fix login", "list_id": T1, "ttype": "bug", "assignee_id": ra["id"]})
ev = [e for e in CL.get("/agent/events", params={"since": 0, "limit": 500}).json()["data"] if e["event"] == "assigned"]
check(ev and ev[-1]["data"]["task"]["type"] == "bug", "agent event: task.type")

# ================================================================== #243 project types
FE = settings(A)["features"]
A.patch(B + "/api/settings", json={"features": ",".join(f for f in FE.split(",") if f not in ("kanban", "deps"))})
r = A.post(B + "/api/lists", json={"name": "Kalmido", "ptype": "software", "folder": "Dev/Tools"})
check(r.ok, f"software project: {r.status_code} {r.text[:120]}")
j = r.json()
SW = j["id"]
check(sorted(j["modules_on"]) == ["deps", "kanban"], f"modules switched on: {j['modules_on']}")
check(all(f in settings(A)["features"].split(",") for f in ("kanban", "deps")), "features now on")
L = lst(A, SW)
check(L["kind"] == "project" and L["view"] == "kanban" and L["tickets"] == 1 and L["dep_shift"] == 1 and L["folder"] == "Dev/Tools",
      "software: project, kanban, tickets, move along, folder")
secs = [x["name"] for x in st(A)["sections"] if x["list_id"] == SW]
check(secs == ["Backlog", "Next", "In progress", "Review", "Done"], f"software sections: {secs}")
A.patch(B + "/api/settings", json={"lang": "de"})
AG = A.post(B + "/api/lists", json={"name": "Kunde X", "ptype": "agency"}).json()
secs = [x["name"] for x in st(A)["sections"] if x["list_id"] == AG["id"]]
check(secs == ["Anfrage", "Konzept", "Umsetzung", "Abnahme", "Abrechnung"], f"agency sections in German: {secs}")
fl = [(f["name"], f["type"]) for f in st(A)["fields"] if f["list_id"] == AG["id"]]
check(fl == [("Kunde", "text"), ("Budget h", "number")], f"agency fields: {fl}")
PR = A.post(B + "/api/lists", json={"name": "Umzug", "ptype": "private"}).json()
secs = [x["name"] for x in st(A)["sections"] if x["list_id"] == PR["id"]]
check(secs == ["Ideen", "Planung", "Erledigen"] and not [f for f in st(A)["fields"] if f["list_id"] == PR["id"]], f"private: {secs}")
A.patch(B + "/api/settings", json={"lang": "en"})
check(A.post(B + "/api/lists", json={"name": "x", "ptype": "space"}).status_code == 400, "unknown project type 400")
r = VA.post("/lists", json={"name": "Via API", "project_type": "agency"})
check(r.status_code == 201 and r.json()["kind"] == "project", "v1: project_type")
check(VA.post("/lists", json={"name": "x", "project_type": "nope"}).status_code == 400, "v1: bad project_type 400")

# ================================================================== #328 project templates with relative dates
D0 = date(2026, 11, 2)
iso = lambda d: d.isoformat()  # noqa: E731
PJ = A.post(B + "/api/lists", json={"name": "Launch", "kind": "project", "tickets": True, "dep_shift": True}).json()["id"]
S1 = A.post(B + "/api/sections", json={"list_id": PJ, "name": "Prep"}).json()["id"]
a = A.post(B + "/api/tasks", json={"title": "Brief", "list_id": PJ, "section_id": S1, "start": iso(D0), "due": iso(D0 + timedelta(days=2))}).json()["id"]
b = A.post(B + "/api/tasks", json={"title": "Design", "list_id": PJ, "due": iso(D0 + timedelta(days=6))}).json()["id"]
c = A.post(B + "/api/tasks", json={"title": "Ship", "list_id": PJ, "due": iso(D0 + timedelta(days=10)), "ttype": "task"}).json()["id"]
sub = A.post(B + "/api/tasks", json={"title": "Sketch", "parent_id": b, "due": iso(D0 + timedelta(days=4))}).json()["id"]
check(A.post(B + "/api/deps", json={"task_id": b, "blocker_id": a}).ok, "dep Design waits on Brief")
check(A.post(B + "/api/deps", json={"task_id": c, "blocker_id": b}).ok, "dep Ship waits on Design")
check(A.post(B + "/api/deps", json={"task_id": sub, "blocker_id": a}).ok, "dep Sketch waits on Brief")
r = A.post(B + "/api/templates", json={"list_id": PJ, "relative": True, "name": "Launch plan"})
check(r.ok, f"save relative template {r.status_code} {r.text[:100]}")
tp = r.json()
d = tp["data"]
check(d["rel"] is True and d["span"] == 10 and d["tickets"] == 1 and d["dep_shift"] == 1 and d["sections"] == ["Prep"], f"template: {d.get('span')}")
offs = {n["title"]: (n["start_offset"], n["due_offset"]) for n in d["tasks"]}
check(offs == {"Brief": (0, 2), "Design": (None, 6), "Ship": (None, 10)}, f"offsets from the project start: {offs}")
check(len(d["deps"]) == 3, f"dependencies kept: {d['deps']}")
# apply with a start
r = A.post(B + f"/api/templates/{tp['id']}/apply", json={"name": "Launch 2", "start": "2027-01-04", "folder": "Dev/Launches"})
check(r.ok, f"apply with start {r.status_code} {r.text[:100]}")
N1 = r.json()["list_id"]
ts = {t["title"]: t for t in st(A)["tasks"] if t["list_id"] == N1}
check(ts["Brief"]["start"] == "2027-01-04" and ts["Brief"]["due"] == "2027-01-06" and ts["Ship"]["due"] == "2027-01-14"
      and ts["Sketch"]["due"] == "2027-01-08", "dates from the start")
check(lst(A, N1)["folder"] == "Dev/Launches" and lst(A, N1)["tickets"] == 1 and lst(A, N1)["dep_shift"] == 1, "folder, ticket types, move along")
check(ts["Ship"]["ttype"] == "task", "ticket type kept")
nd = dbx("SELECT task_id, blocker_id FROM task_deps WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)", (N1,))
want = {(ts["Design"]["id"], ts["Brief"]["id"]), (ts["Ship"]["id"], ts["Design"]["id"]), (ts["Sketch"]["id"], ts["Brief"]["id"])}
check(set(nd) == want, f"dependencies re-created: {nd}")
check(ts["Brief"]["section_id"] and [x["name"] for x in st(A)["sections"] if x["id"] == ts["Brief"]["section_id"]] == ["Prep"], "section kept")
# stretched to an end date (span 10 -> 20 days)
N2 = A.post(B + f"/api/templates/{tp['id']}/apply", json={"start": "2027-02-01", "end": "2027-02-21"}).json()["list_id"]
ts2 = {t["title"]: t for t in st(A)["tasks"] if t["list_id"] == N2}
check(ts2["Ship"]["due"] == "2027-02-21" and ts2["Design"]["due"] == "2027-02-13" and ts2["Brief"]["due"] == "2027-02-05", "stretched to the end")
N3 = A.post(B + f"/api/templates/{tp['id']}/apply", json={"start": "2027-03-01", "end": "2027-03-06"}).json()["list_id"]
ts3 = {t["title"]: t for t in st(A)["tasks"] if t["list_id"] == N3}
check(ts3["Ship"]["due"] == "2027-03-06" and ts3["Design"]["due"] == "2027-03-04", "squeezed to the end")
check(A.post(B + f"/api/templates/{tp['id']}/apply", json={"start": "2027-13-01"}).status_code == 400, "bad start 400")
check(A.post(B + f"/api/templates/{tp['id']}/apply", json={"start": "2027-03-10", "end": "2027-03-01"}).status_code == 400, "end before start 400")
# an edited template keeps its dependencies; one closing a cycle is dropped
d2 = dict(d)
d2["deps"] = d["deps"] + [[d["deps"][0][1], d["deps"][0][0]]]
r = A.patch(B + f"/api/templates/{tp['id']}", json={"data": d2})
check(r.ok and len(r.json()["data"]["deps"]) == 3, f"cycle edge dropped: {r.json()['data'].get('deps')}")
# a non-relative template (today based) still works, now with dependencies too
r = A.post(B + "/api/templates", json={"list_id": PJ, "name": "Plain copy"}).json()
check(r["data"]["rel"] is False and len(r["data"]["deps"]) == 3, "list template: deps kept, not relative")

# ================================================================== #187 quick capture
r = requests.get(B + "/capture?title=Hi&url=https://example.org")
check(r.ok and "<html" in r.text.lower() and "app.js" in r.text, "GET /capture: the app")
m = A.get(B + "/manifest.json").json()
cap = [x for x in m["shortcuts"] if x["url"] == "/?action=capture"]
check(cap and cap[0]["name"] == "Quick add", "manifest: Quick add shortcut")
check(all(requests.get(B + i["src"]).ok for i in cap[0]["icons"]), "shortcut icons exist")

# ================================================================== migration: flat folders with "/" stay top-level
stop()
dbx("UPDATE lists SET folder='Kunden/Firma' WHERE id=?", (L4,))
dbx("UPDATE list_members SET folder='Privat/Alt' WHERE list_id=? AND user_id=?", (L1, BOB))
uid_a = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
dbx("UPDATE user_settings SET value=? WHERE user_id=? AND key='folders'", (json.dumps(["Kunden/Firma", "Home"]), uid_a))
dbx("DELETE FROM settings WHERE key='migr_folder_path'")
start(keep=True)
A = sess("alice")
Bo = sess("bob")
check(folder(A, L4) == "Kunden" + C + "Firma", f"owner row: kept top-level ({folder(A, L4)!r})")
check(folder(Bo, L1) == "Privat" + C + "Alt", f"member row: kept top-level ({folder(Bo, L1)!r})")
check(json.loads(settings(A)["folders"])[0] == "Kunden" + C + "Firma", "folder order migrated")
check(dbx("SELECT value FROM settings WHERE key='migr_folder_path'") == [("1",)], "migration done once")

# ================================================================== setup: "Start with a project"
start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "zoe", "display_name": "Zoe", "password": "password123"}).ok
Z = sess("zoe")
r = Z.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["kanban", "deps"], "project_type": "nope"})
check(r.status_code == 400, "setup: bad project type 400")
r = Z.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["kanban", "deps"], "project_type": "software"})
check(r.ok, f"setup with a project {r.status_code}")
ls = [x for x in st(Z)["lists"] if not x["is_inbox"]]
check(len(ls) == 1 and ls[0]["name"] == "Software / AI dev" and ls[0]["kind"] == "project" and ls[0]["tickets"] == 1, f"setup project: {ls}")

print(f"p240_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
