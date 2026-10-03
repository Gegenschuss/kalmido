#!/usr/bin/env python3
"""Package D3 API tests (fresh DB on the TEST container :3048): the roadmap. GET /api/roadmap (groups in sidebar order,
folders, summary spans over every open dated task, undated counts, the date window, projects_only, include_done,
dependencies, view-only members, bad parameters), POST /api/lists/<id>/shift (every open dated task incl. subtasks by the
same number of days, durations kept, undated / done / trashed tasks untouched, one transaction, the cap, edit rights,
input checks, dependents in other lists only where "Move dependent tasks along" is on and only when moved later, the
client's one-request undo), dates at month ends, leap days and across the DST switches of Europe/Berlin, the user
setting "roadmap", and the token API (/api/v1/roadmap read scope, /api/v1/lists/{id}/shift write scope, OpenAPI)."""
import os, sqlite3, sys
from datetime import date, timedelta
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def db():
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def state(s):
    return s.get(B + "/api/state").json()


def task(s, tid):
    return next((t for t in state(s)["tasks"] if t["id"] == tid), None)


def row(tid):
    with db() as c:
        return dict(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())


D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
DAVE = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123"}).json()["id"]
Bb, Cc, Dd = sess("bob"), sess("carol"), sess("dave")


def mk(title, lid, due=None, start=None, s=A, **kw):
    b = {"title": title, "list_id": lid, **kw}
    if due is not None:
        b["due"] = due
    if start is not None:
        b["start"] = start
    r = s.post(B + "/api/tasks", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def newlist(name, kind="project", folder="", s=A):
    r = s.post(B + "/api/lists", json={"name": name, "kind": kind, **({"folder": folder} if folder else {})})
    assert r.ok, r.text
    return r.json()["id"]


WEB = newlist("🌐 Website relaunch", folder="Clients")
BRAND = newlist("Brand refresh", folder="Clients")
FILM = newlist("Image film")
SHOP = newlist("Groceries", kind="list")
EMPTY = newlist("New pitch")
A.patch(B + "/api/settings", json={"folders": '["Clients"]'})
A.put(B + f"/api/lists/{WEB}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{WEB}/members", json={"user_id": CAROL, "role": "view"})

w1 = mk("Kickoff", WEB, D(0))
w2 = mk("Design", WEB, D(10), D(2))
w3 = mk("Build", WEB, D(30), D(11))
w3a = mk("Build: CMS", WEB, D(20), D(12), parent_id=w3)
wN = mk("Collect ideas", WEB)  # no date
wD = mk("Old draft", WEB, D(-3))
A.post(B + f"/api/tasks/{wD}/complete")
b1 = mk("Moodboard", BRAND, D(40), D(35))
f1 = mk("Shoot", FILM, D(60), D(50))
f2 = mk("Cut", FILM, D(400))  # far away: outside the default window
g1 = mk("Milk", SHOP, D(1))

# ================= GET /api/roadmap
r = A.get(B + "/api/roadmap")
check(r.ok, f"roadmap: 200 ({r.status_code})")
j = r.json()
ids = [g["list"]["id"] for g in j["groups"]]
check(ids[0] == state(A)["lists"][0]["id"] and state(A)["lists"][0]["is_inbox"], "roadmap: the inbox first")
check(ids.index(FILM) < ids.index(WEB) and ids.index(SHOP) < ids.index(WEB), f"roadmap: lists without a folder before the folder: {ids}")
check(ids.index(WEB) < ids.index(BRAND), "roadmap: lists inside the folder in sidebar order")
check(j["folders"] == ["Clients"], f"roadmap: folders in order: {j['folders']}")
G = {g["list"]["id"]: g for g in j["groups"]}
check(G[WEB]["folder"] == "Clients" and G[FILM]["folder"] == "", "roadmap: folder per group")
check(G[WEB]["span"] == {"start": D(0), "end": D(30)}, f"summary span = earliest start or due .. latest due of the open tasks: {G[WEB]['span']}")
check(G[WEB]["open_dated"] == 4 and G[WEB]["undated"] == 1, f"counts: 4 open dated (subtask included), 1 without date: {G[WEB]['open_dated']} {G[WEB]['undated']}")
check(G[FILM]["span"] == {"start": D(50), "end": D(400)}, "span covers tasks outside the window too")
check([t["id"] for t in G[FILM]["tasks"]] == [f1], "tasks: only those overlapping the window (default: 14 days back, 194 ahead)")
check(j["from"] == D(-14) and j["to"] == D(180), f"default window: {j['from']} .. {j['to']}")
check([t["id"] for t in G[WEB]["tasks"]] == [w1, w2, w3, w3a], f"tasks sorted by start (or due): {[t['id'] for t in G[WEB]['tasks']]}")
check(all(t["status"] == "open" for t in G[WEB]["tasks"]), "open tasks only by default")
t2 = next(t for t in G[WEB]["tasks"] if t["id"] == w2)
check(t2["start"] == D(2) and t2["due"] == D(10) and t2["priority"] == "none" and "title" in t2, "task fields")
check(G[EMPTY]["span"] is None and G[EMPTY]["tasks"] == [], "a project without dates: span null")
check(G[WEB]["list"]["kind"] == "project" and G[SHOP]["list"]["kind"] == "list" and "progress" in G[WEB]["list"], "list object with kind + progress")
p = G[WEB]["list"]["progress"]
check(p["done"] == 1 and p["total"] == 5, f"progress = the project progress (main tasks, done vs. all): {p}")
check(G[WEB]["can_edit"] is True, "owner can edit")
j = A.get(B + "/api/roadmap", params={"projects_only": "1"}).json()
check(SHOP not in [g["list"]["id"] for g in j["groups"]] and j["projects_only"] is True
      and not any(g["list"]["is_inbox"] for g in j["groups"]), "projects_only: plain lists and the inbox left out")
j = A.get(B + "/api/roadmap", params={"include_done": "true"}).json()
check(any(t["id"] == wD and t["status"] == "done" for g in j["groups"] for t in g["tasks"]), "include_done: completed tasks with their status")
j = A.get(B + "/api/roadmap", params={"from": D(45), "to": D(420)}).json()
G = {g["list"]["id"]: g for g in j["groups"]}
check([t["id"] for t in G[FILM]["tasks"]] == [f1, f2] and G[WEB]["tasks"] == [], "custom window: overlap test on start..due")
for bad, what in [({"from": D(5), "to": D(1)}, "to before from"), ({"from": D(0), "to": D(1200)}, "window over the cap"),
                  ({"from": "yesterday"}, "bad date"), ({"projects_only": "maybe"}, "bad flag")]:
    check(A.get(B + "/api/roadmap", params=bad).status_code == 400, f"roadmap 400: {what}")
check(sess().get(B + "/api/roadmap").status_code in (401, 403), "roadmap: login required")
# dependencies between lists
A.post(B + "/api/deps", json={"task_id": b1, "blocker_id": w3})
j = A.get(B + "/api/roadmap").json()
check({"task_id": b1, "blocker_id": w3} in j["deps"], "deps: across lists")
# members
jc = Cc.get(B + "/api/roadmap").json()
gc = {g["list"]["id"]: g for g in jc["groups"]}
check(WEB in gc and BRAND not in gc and gc[WEB]["can_edit"] is False, "view-only member: sees the shared list, can_edit false")
check(not any(d["blocker_id"] == w3 and d["task_id"] == b1 for d in jc["deps"]), "deps of tasks the member cannot see are not listed")
check(WEB not in {g["list"]["id"] for g in Dd.get(B + "/api/roadmap").json()["groups"]}, "no access: list not listed")

# ================= POST /api/lists/<id>/shift
before = {t: row(t) for t in (w1, w2, w3, w3a, wN, wD)}
r = Cc.post(B + f"/api/lists/{WEB}/shift", json={"days": 7})
check(r.status_code == 403, f"shift: view-only member refused ({r.status_code})")
r = Dd.post(B + f"/api/lists/{WEB}/shift", json={"days": 7})
check(r.status_code == 404, f"shift: no access = 404 ({r.status_code})")
check(all(row(t)["due"] == before[t]["due"] for t in before), "refused shifts changed nothing")
for bad in (0, "abc", True, 3651, -3651, 1.5, None):
    rr = A.post(B + f"/api/lists/{WEB}/shift", json={"days": bad})
    check(rr.status_code == 400, f"shift: days={bad!r} refused ({rr.status_code})")
with db() as c:
    v0 = c.execute("SELECT value FROM settings WHERE key='version'").fetchone()[0]
r = Bb.post(B + f"/api/lists/{WEB}/shift", json={"days": 7})
check(r.ok, f"shift: edit member may move the project ({r.status_code} {r.text[:200]})")
j = r.json()
check(j["count"] == 4 and j["days"] == 7 and {m["id"] for m in j["moved"]} == {w1, w2, w3, w3a}, f"shift: the 4 open dated tasks (subtask too): {j.get('count')}")
m2 = next(m for m in j["moved"] if m["id"] == w2)
check(m2 == {"id": w2, "title": "Design", "start": D(9), "due": D(17), "prev_start": D(2), "prev_due": D(10)}, f"moved entry with previous dates: {m2}")
for t, (s0, d0) in {w1: (None, 0), w2: (2, 10), w3: (11, 30), w3a: (12, 20)}.items():
    x = row(t)
    check(x["due"] == D(d0 + 7) and x["start"] == (D(s0 + 7) if s0 is not None else None), f"task {t}: start + due +7, duration kept")
check(row(wN)["due"] is None and row(wD)["due"] == before[wD]["due"], "undated and completed tasks untouched")
with db() as c:
    check(c.execute("SELECT value FROM settings WHERE key='version'").fetchone()[0] != v0, "version bumped (clients reload)")
    check(c.execute("SELECT COUNT(*) FROM activity WHERE kind='due' AND task_id IN (?,?,?,?)", (w1, w2, w3, w3a)).fetchone()[0] >= 4,
          "an activity line per moved task")
# dependents in other lists: BRAND waits on w3 (moved to +37). BRAND without dep_shift: stays
check(row(b1)["due"] == D(40) and j["shifted"] == [], "dependent list without 'Move dependent tasks along': not moved")
A.patch(B + f"/api/lists/{BRAND}", json={"dep_shift": True})
r = A.post(B + f"/api/lists/{WEB}/shift", json={"days": 7}).json()  # w3 due +44 -> Moodboard (starts +35) conflicts -> +7
check([x["id"] for x in r["shifted"]] == [b1] and row(b1)["due"] == D(47) and row(b1)["start"] == D(42), f"dependent with the setting on: moved by the same delta: {r['shifted']}")
with db() as c:
    check(c.execute("SELECT 1 FROM activity WHERE task_id=? AND kind='dep_shift'", (b1,)).fetchone(), "dependent: activity line dep_shift")
r = A.post(B + f"/api/lists/{WEB}/shift", json={"days": -3}).json()
check(r["shifted"] == [] and row(b1)["due"] == D(47), "moving earlier never moves dependents")
# the client's undo: one batch request, every task back to its own dates
r = A.post(B + f"/api/lists/{WEB}/shift", json={"days": 14}).json()
allm = r["moved"] + r["shifted"]
items = {str(x["id"]): {"start": x["prev_start"], "due": x["prev_due"], "_prev": {"start": x["start"], "due": x["due"]}} for x in allm}
u = A.post(B + "/api/tasks/batch", json={"ids": [x["id"] for x in allm], "action": "patch_each", "data": {"items": items}})
check(u.ok and u.json()["count"] == len(allm), f"undo: one batch for all ({u.status_code})")
check(all(row(x["id"])["due"] == x["prev_due"] and row(x["id"])["start"] == x["prev_start"] for x in allm), "undo: every task back")
# undo does not overwrite a change made elsewhere in the meantime (_prev)
r = A.post(B + f"/api/lists/{FILM}/shift", json={"days": 2}).json()
A.patch(B + f"/api/tasks/{f1}", json={"due": D(90)})
items = {str(x["id"]): {"start": x["prev_start"], "due": x["prev_due"], "_prev": {"start": x["start"], "due": x["due"]}} for x in r["moved"]}
A.post(B + "/api/tasks/batch", json={"ids": [x["id"] for x in r["moved"]], "action": "patch_each", "data": {"items": items}})
check(row(f1)["due"] == D(90) and row(f2)["due"] == D(400), "undo keeps a due date changed elsewhere meanwhile, the others go back")
# empty list / trash
r = A.post(B + f"/api/lists/{EMPTY}/shift", json={"days": 3})
check(r.ok and r.json()["count"] == 0, "a list without dated tasks: ok, nothing moved")
tr_ = mk("Trashed", EMPTY, D(5))
A.delete(B + f"/api/tasks/{tr_}")
A.post(B + f"/api/lists/{EMPTY}/shift", json={"days": 3})
check(row(tr_)["due"] == D(5), "tasks in the trash are not moved")

# ---- the cap: more than 500 dated tasks -> 409, nothing moved (inserted directly, one transaction)
BIG = newlist("Big")
with db() as c:
    c.executemany("INSERT INTO tasks(list_id,title,due,created_at,updated_at,sort) VALUES(?,?,?,?,?,?)",
                  [(BIG, f"t{i}", D(i % 50), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", i) for i in range(501)])
    c.commit()
r = A.post(B + f"/api/lists/{BIG}/shift", json={"days": 1})
check(r.status_code == 409 and "at most 500" in r.json().get("error", ""), f"cap: 501 dated tasks refused with a message ({r.status_code} {r.text[:120]})")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM tasks WHERE list_id=? AND due=?", (BIG, D(0))).fetchone()[0] == 11, "cap: nothing moved")
    c.execute("DELETE FROM tasks WHERE list_id=? AND title='t500'", (BIG,))
    c.commit()
r = A.post(B + f"/api/lists/{BIG}/shift", json={"days": 1})
check(r.ok and r.json()["count"] == 500, f"cap: exactly 500 are moved ({r.status_code})")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM tasks WHERE list_id=? AND due=?", (BIG, D(1))).fetchone()[0] == 10
          and c.execute("SELECT COUNT(*) FROM tasks WHERE list_id=? AND due=?", (BIG, D(0))).fetchone()[0] == 0, "500 moved in one go")
Ad = sess("dave")
Ad.patch(B + "/api/settings", json={"lang": "de"})
DL = newlist("Dave", s=Ad)
with db() as c:
    c.executemany("INSERT INTO tasks(list_id,title,due,created_at,updated_at,sort) VALUES(?,?,?,?,?,?)",
                  [(DL, f"t{i}", D(1), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", i) for i in range(501)])
    c.commit()
r = Ad.post(B + f"/api/lists/{DL}/shift", json={"days": 1})
check(r.status_code == 409 and "höchstens 500" in r.json().get("error", ""), f"cap message in the user's language: {r.text[:120]}")

# ---- dates: month ends, leap day, DST (the container runs in Europe/Berlin; dates are calendar days)
CAL = newlist("Calendar edge cases")
c1 = mk("Jan end", CAL, "2027-01-31")
c2 = mk("Feb range", CAL, "2027-02-28", "2027-02-27")
c3 = mk("Leap", CAL, "2028-02-28")
c4 = mk("Spring DST", CAL, "2027-03-27", due_time="09:00")
c5 = mk("Autumn DST", CAL, "2026-10-24", "2026-10-23", due_time="23:30")
c6 = mk("Mar end", CAL, "2027-03-31")
r = A.post(B + f"/api/lists/{CAL}/shift", json={"days": 1})
check(r.ok, "calendar edge cases: shift +1")
exp = {c1: (None, "2027-02-01"), c2: ("2027-02-28", "2027-03-01"), c3: (None, "2028-02-29"), c4: (None, "2027-03-28"),
       c5: ("2026-10-24", "2026-10-25"), c6: (None, "2027-04-01")}
for t, (s, d) in exp.items():
    x = row(t)
    check(x["due"] == d and x["start"] == s, f"+1 day: {x['title']}: {x['start']} {x['due']} (want {s} {d})")
check(row(c4)["due_time"] == "09:00" and row(c5)["due_time"] == "23:30", "the time of day stays across the DST switch")
r = A.post(B + f"/api/lists/{CAL}/shift", json={"days": -32})
check(row(c6)["due"] == "2027-02-28" and row(c1)["due"] == "2026-12-31" and row(c3)["due"] == "2028-01-28", "-32 days: across month and year ends")
A.post(B + f"/api/lists/{CAL}/shift", json={"days": 32})
r = A.post(B + f"/api/lists/{CAL}/shift", json={"days": 7})
check(row(c4)["due"] == "2027-04-04" and row(c5)["due"] == "2026-11-01" and row(c5)["start"] == "2026-10-31", "+7 days over the DST weekends: whole days")
d3 = row(c3)["due"]
r = A.post(B + f"/api/lists/{CAL}/shift", json={"days": 3650})
check(r.ok and row(c3)["due"] == (date.fromisoformat(d3) + timedelta(days=3650)).isoformat(), f"the maximum (3650 days) works: {row(c3)['due']}")
with db() as c:  # a date near the end of the calendar: refused before anything is written
    c.execute("UPDATE tasks SET due='9999-12-30' WHERE id=?", (c1,))
    c.commit()
due3 = row(c3)["due"]
r = A.post(B + f"/api/lists/{CAL}/shift", json={"days": 5})
check(r.status_code == 400 and row(c3)["due"] == due3, "a date out of range: 400 and nothing moved")

# ================= the user setting "roadmap" (view prefs)
ok = A.patch(B + "/api/settings", json={"roadmap": '{"v":"timeline","z":"quarter","po":false,"hd":true,"who":"me","ls":[1,2],"def":"c","t":{"l3":1,"f:Clients":0}}'})
check(ok.ok and '"z":"quarter"' in state(A)["settings"]["roadmap"], "roadmap prefs stored")
for bad in ['{"v":"gantt"}', '{"z":"year"}', '{"ls":["x"]}', '{"t":{"x1":1}}', '{"t":{"l1":2}}', '{"who":"bob"}', '{"evil":1}', "[1]", "{no json"]:
    check(A.patch(B + "/api/settings", json={"roadmap": bad}).status_code == 400, f"roadmap prefs refused: {bad}")
check(A.patch(B + "/api/settings", json={"roadmap": ""}).ok, "roadmap prefs: empty = defaults")

# ================= the token API
TOK_R = A.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read"]}).json()["token"]
TOK_W = A.post(B + "/api/me/tokens", json={"name": "w", "scopes": ["read", "write"]}).json()["token"]
hr, hw = {"Authorization": "Bearer " + TOK_R}, {"Authorization": "Bearer " + TOK_W}
r = requests.get(B + "/api/v1/roadmap", headers=hr, params={"projects_only": "true"})
check(r.ok and all(g["list"]["kind"] == "project" for g in r.json()["groups"]), f"v1 roadmap with a read token ({r.status_code})")
check(requests.get(B + "/api/v1/roadmap", headers=hr, params={"foo": 1}).status_code == 400, "v1 roadmap: unknown parameter")
bad = requests.get(B + "/api/v1/roadmap", headers=hr, params={"from": "x"}).json()
check(bad.get("error", {}).get("code") and bad["error"].get("message"), f"v1 error format: {bad}")
r = requests.post(B + f"/api/v1/lists/{FILM}/shift", headers=hr, json={"days": 1})
check(r.status_code == 403, f"v1 shift needs the write scope ({r.status_code})")
d0 = row(f1)["due"]
r = requests.post(B + f"/api/v1/lists/{FILM}/shift", headers=hw, json={"days": 2})
check(r.ok and r.json()["count"] == 2 and row(f1)["due"] == (date.fromisoformat(d0) + timedelta(days=2)).isoformat(), f"v1 shift with a write token ({r.status_code})")
check(requests.post(B + f"/api/v1/lists/{FILM}/shift", headers=hw, json={"days": 1, "x": 1}).status_code == 400, "v1 shift: unknown field")
check(requests.post(B + f"/api/v1/lists/{FILM}/shift", headers=hw, json={}).status_code == 400, "v1 shift: days missing")
TB = Cc.post(B + "/api/me/tokens", json={"name": "c", "scopes": ["read", "write"]}).json()["token"]
r = requests.post(B + f"/api/v1/lists/{WEB}/shift", headers={"Authorization": "Bearer " + TB}, json={"days": 1})
check(r.status_code == 403, f"v1 shift: view-only member refused ({r.status_code})")
r = requests.post(B + f"/api/v1/lists/{BRAND}/shift", headers={"Authorization": "Bearer " + TB}, json={"days": 1})
check(r.status_code == 404, f"v1 shift: invisible list 404 ({r.status_code})")
spec = requests.get(B + "/api/v1/openapi.json").json()
check("/roadmap" in spec["paths"] and spec["paths"]["/lists/{id}/shift"]["post"]["x-kalmido-scope"] == "tasks:write"
      and spec["paths"]["/roadmap"]["get"]["x-kalmido-scope"] == "read" and "RoadmapGroup" in spec["components"]["schemas"], "OpenAPI: both documented with their scopes")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
