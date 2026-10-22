#!/usr/bin/env python3
"""2.145.0 API tests, part C (#2431): more columns in a list's CSV file. Own container (start.sh). Invented names only,
addresses @example.com.
 - GET /api/lists/<id>/export.csv: the old columns keep their order (custom fields after them), the new ones are appended:
   start date (start, else the day plan's slot), deadline (the due day of a deadline), duration (h), tracked time (h, the
   task's total), created by, completed by, milestone, sprint, checklist (checkbox lines of the notes, then the subtasks, one
   cell with line breaks, quotes doubled); hours with a decimal point in English, a decimal comma (and ';') in German
 - a participant still gets only the tasks assigned to them, with the tracked time they may see
 - a person without an organisation (freelancer-matrix: lists): the new columns on the own private list
usage: p2145_c_api_test.py <datadir>      (a fresh container; P2145C_NOSTART=1 = the server already runs)"""
import csv
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
NEW = ["Start date", "Deadline", "Duration (h)", "Tracked time (h)", "Created by", "Completed by", "Milestone", "Sprint", "Checklist"]


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


def rows(r):
    t = r.content.decode("utf-8")
    assert t.startswith("﻿"), "BOM"
    first = t[1:].split("\r\n", 1)[0]
    d = ";" if first.count(";") > first.count(",") else ","
    return list(csv.reader(io.StringIO(t[1:]), delimiter=d))


def table(r):
    R = rows(r)
    return R[0], {x[0]: dict(zip(R[0], x)) for x in R[1:]}


if not os.environ.get("P2145C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "time_all": True,
                                     "modules": ["comments", "fields", "time"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
for u in ("bob", "pete"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Pe = sess("bob"), sess("pete")
for s in (A, Bo, Pe):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,fields,time"}).ok

L = A.post(B + "/api/lists", json={"name": "Shop fit", "kind": "project", "org_id": ORG, "time_tracking": True}).json()["id"]
for u, ro in (("bob", "edit"), ("pete", "participant")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid[u], "role": ro}).ok
fref = A.post(B + f"/api/lists/{L}/fields", json={"name": "Ref", "type": "text"}).json()["id"]


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, (kw, r.text)
    return r.json()["id"]


def patch(s, tid, **kw):
    r = s.patch(B + f"/api/tasks/{tid}", json=kw)
    assert r.ok, (kw, r.text)


MS = mk(A, title="Release one", list_id=L, ms=1, due="2031-06-30")
T1 = mk(A, title="Paint walls", list_id=L, due="2031-05-10", content='Plan\n- [x] Buy "glue", brushes\n- [ ] Cut tiles\nplain line',
        assignee_id=uid["pete"])
patch(A, T1, start="2031-05-01", duration=90, deadline=1, milestone_id=MS, fields={str(fref): "R-1"})
mk(A, title="Sub open", parent_id=T1, assignee_id=uid["pete"])
S2 = mk(A, title="Sub done", parent_id=T1, assignee_id=uid["pete"])
A.post(B + f"/api/tasks/{S2}/complete", json={})
T2 = mk(Bo, title="Order lamps", list_id=L)
Bo.post(B + f"/api/tasks/{T2}/complete", json={})
T3 = mk(A, title="Hidden from pete", list_id=L, due="2031-05-12")
# time: alice 90 min on T1, bob 30 min on T1, bob 60 min on T3
for s, t, m in ((A, T1, 90), (Bo, T1, 30), (Bo, T3, 60)):
    r = s.post(B + "/api/time/entries", json={"task_id": t, "start": "2026-01-05T09:00", "minutes": m})
    assert r.status_code in (200, 201), r.text
# sprints on, T1 into sprint 1
r = A.put(B + f"/api/lists/{L}/sprint-settings", json={"on": True})
assert r.ok, r.text
SP = r.json()["started_id"]
assert A.post(B + f"/api/lists/{L}/sprints/assign", json={"ids": [T1], "sprint_id": SP}).ok

# ================================================================ the columns
r = A.get(B + f"/api/lists/{L}/export.csv")
check(r.status_code == 200, f"csv 200 {r.status_code} {r.text[:200]}")
head, by = table(r)
check(head[:11] == ["Title", "Status", "Due", "Priority", "Tags", "Assignee", "Section", "Parent task", "Description", "Completed", "Created"]  # 2.165.3 (#2629): Description instead of Notes
      and head[11:] == ["Ref"] + NEW, f"old columns in order, custom field, the new ones appended {head}")
t1 = by["Paint walls"]
check(t1["Start date"] == "2031-05-01" and t1["Deadline"] == "2031-05-10", f"start + deadline {t1}")
check(t1["Duration (h)"] == "1.50" and t1["Tracked time (h)"] == "2.00", f"duration 90 min, tracked 2 h (en: point) {t1}")
check(t1["Created by"] == "Alice" and t1["Completed by"] == "", f"created by, not completed {t1}")
check(t1["Milestone"] == "Release one" and t1["Sprint"] == "Sprint 1", f"milestone + sprint {t1}")
check(t1["Checklist"] == '[x] Buy "glue", brushes\n[ ] Cut tiles\n[ ] Sub open\n[x] Sub done', f"checklist cell {t1['Checklist']!r}")
check('"[x] Buy ""glue"", brushes\n[ ] Cut tiles\n[ ] Sub open\n[x] Sub done"' in r.content.decode("utf-8"), "the cell is quoted, quotes doubled")
t2 = by["Order lamps"]
check(t2["Created by"] == "Bob" and t2["Completed by"] == "Bob" and t2["Deadline"] == "" and t2["Tracked time (h)"] == "", f"bob's task {t2}")
check(by["Hidden from pete"]["Deadline"] == "" and by["Hidden from pete"]["Tracked time (h)"] == "1.00", "a due day without deadline: empty")
check(by["Release one"]["Milestone"] == "" and by["Sub open"]["Checklist"] == "", "empty cells stay empty")
# German: decimal comma, ';'
A.patch(B + "/api/settings", json={"lang": "de"})
rd = A.get(B + f"/api/lists/{L}/export.csv")
hd, bd = table(rd)
check(rd.content.decode("utf-8").split("\r\n")[0].count(";") >= 20, "German: ';'")
check(len(hd) == len(head) and bd["Paint walls"][hd[14]] == "1,50" and bd["Paint walls"][hd[15]] == "2,00", f"German: decimal comma {bd['Paint walls']}")
check(bd["Paint walls"][hd[1]] == "Offen", f"German: an open task is \"Offen\" (the state, not the verb) {bd['Paint walls'][hd[1]]}")
A.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================ a participant
rp = Pe.get(B + f"/api/lists/{L}/export.csv")
hp, bp = table(rp)
check(rp.ok and set(bp) == {"Paint walls", "Sub open", "Sub done"}, f"participant: only their tasks {list(bp)}")
check(bp["Paint walls"]["Tracked time (h)"] == "2.00" and bp["Paint walls"]["Created by"] == "Alice", f"participant: time on own task {bp['Paint walls']}")
check(bp["Paint walls"]["Checklist"].endswith("[ ] Sub open\n[x] Sub done"), "participant: subtasks in the checklist")

# ================================================================ a person without an organisation (freelancer-matrix: lists)
FID, Fl = freelancer(B, A)
Fl.patch(B + "/api/settings", json={"lang": "en"})
PL = Fl.post(B + "/api/lists", json={"name": "Private plans", "org_id": None, "kind": "project", "time_tracking": True}).json()["id"]
FT = mk(Fl, title="Own task", list_id=PL, content="- [ ] first")
patch(Fl, FT, duration=30)
Fl.post(B + "/api/time/entries", json={"task_id": FT, "start": "2026-01-05T09:00", "minutes": 45})
hf, bf = table(Fl.get(B + f"/api/lists/{PL}/export.csv"))
f1 = bf.get("Own task", {})
check(hf[-9:] == NEW and f1.get("Duration (h)") == "0.50" and f1.get("Checklist") == "[ ] first" and f1.get("Created by"),
      f"freelancer: new columns on the own list {f1}")
check(f1.get("Tracked time (h)") == "0.75", f"freelancer: tracked time {f1}")
check(Fl.get(B + f"/api/lists/{L}/export.csv").status_code == 404, "freelancer: an organisation's list: 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
