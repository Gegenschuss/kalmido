#!/usr/bin/env python3
"""2.280.0 A (#3108) API test: a slimmer start state. Own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks
 - GET /api/state: a note longer than 200 characters goes without its text (no "content", content_n = its length), a
   short one stays; GET /api/tasks/<id>, the delta and the agent API carry the whole note; the same for a person
   without an organisation
 - 300 tasks with long notes: the state is far below the size of the notes alone (was: every note in it)
 - list progress: the same numbers as the old query (done copies of recurring tasks not counted)
 - a restart (same triggers) keeps the change rows: a delta from before it is no full state (was: every client loaded the
   whole state after a restart / live update); a since from before the first start stays full
 - PERF lines (information): bytes and statements of /api/state for 300 tasks
usage: p2280_e_api_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, B, CT, check, dbx, done, fresh, setup, until  # noqa: E402,F401

TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


fresh()
A = setup()
assert A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "progress,comments,collab"}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks
NOTE = "Invented brief for the shoot. " * 100  # 3,000 characters
SHORT = "Short invented note"


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def stask(s, tid):
    return next((t for t in s.get(B + "/api/state").json()["tasks"] if t["id"] == tid), None)


L = A.post(B + "/api/lists", json={"name": "Shoot briefs"}).json()["id"]
TL = task(A, "Long note", L, content=NOTE)
TS = task(A, "Short note", L, content=SHORT)
TE = task(A, "Exactly 200", L, content="y" * 200)
t = stask(A, TL)
check(t is not None and "content" not in t and t.get("content_n") == len(NOTE), f"#3108 a long note is not in the state {str(t)[:200]}")
check(stask(A, TS).get("content") == SHORT and "content_n" not in stask(A, TS), "#3108 a short note stays in the state")
check(stask(A, TE).get("content") == "y" * 200, "#3108 200 characters stay")
# 2.280.0 F (#3108): content_n counts as the client does (UTF-16 units: a sign outside the basic plane counts 2), the client
# compares it with the length of a note it kept
TU = task(A, "Note with signs", L, content="\U0001F3AC take " * 40)
check(stask(A, TU).get("content_n") == len(("\U0001F3AC take " * 40).encode("utf-16-le")) // 2 == 320,
      f"#3108 F content_n in UTF-16 units {stask(A, TU).get('content_n')}")
check(A.get(B + f"/api/tasks/{TL}").json().get("content") == NOTE, "#3108 GET /api/tasks/<id> has the whole note")
v0 = A.get(B + "/api/version").json()["v"]
check(A.patch(B + f"/api/tasks/{TL}", json={"title": "Long note (2)"}).ok, "the long-note task changes")
d = A.get(B + "/api/state/delta", params={"since": v0, "lean": "1"}).json()
dt = next((x for x in d.get("tasks", []) if x["id"] == TL), {})
check(d.get("full") is False and dt.get("content") == NOTE, f"#3108 the delta carries the whole note {str(d)[:200]}")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"], "expires_days": 30}).json()["token"]
r = requests.get(B + f"/api/v1/tasks/{TL}", headers={"Authorization": "Bearer " + tok})
check(r.ok and r.json().get("content", r.json().get("notes")) == NOTE, f"#3108 the agent API has the whole note {r.status_code}")
FL = Fr.post(B + "/api/lists", json={"name": "Frida's briefs"}).json()["id"]
FT = task(Fr, "Frida's long note", FL, content=NOTE)
ft = stask(Fr, FT)
check(ft is not None and "content" not in ft and Fr.get(B + f"/api/tasks/{FT}").json().get("content") == NOTE,
      "#3108 without an organisation: the same (freelancer-matrix: tasks)")

# 300 tasks with long notes
L3 = A.post(B + "/api/lists", json={"name": "Many briefs"}).json()["id"]
for i in range(300):
    task(A, f"Brief {i}", L3, content=NOTE)
r = A.get(B + "/api/state")
n3, b3 = nstmt(r), len(r.content)
print(f"PERF #3108 /api/state with 300 tasks of 3,000-character notes: {b3} B, {n3} statements (the notes alone: {300 * len(NOTE)} B)", flush=True)
check(b3 < 300 * len(NOTE) // 2, f"#3108 the state is far below the notes alone ({b3} B < {300 * len(NOTE) // 2} B)")
check(sum(1 for x in r.json()["tasks"] if x["list_id"] == L3) == 300, "#3108 every task is still in the state")

# list progress: the same numbers as the old query
LP = A.post(B + "/api/lists", json={"name": "Progress"}).json()["id"]
TR = task(A, "Recurring", LP, due="2026-01-05", repeat="FREQ=DAILY")
for _ in range(2):
    check(A.patch(B + f"/api/tasks/{TR}", json={"status": 2}).ok, "the recurring task done once more")
TD = task(A, "Done", LP)
check(A.patch(B + f"/api/tasks/{TD}", json={"status": 2}).ok, "a done task")
for i in range(2):
    task(A, f"Open {i}", LP)
old = dbx("""SELECT COUNT(*) FILTER (WHERE t.status=0), COUNT(*) FILTER (WHERE t.status=2)
             FROM (SELECT tasks.*, MIN(id) OVER (PARTITION BY list_id, created_at, title) AS st_first FROM tasks WHERE list_id=?) t
             WHERE t.deleted_at IS NULL AND t.status IN (0, 2) AND t.parent_id IS NULL AND NOT (t.status=2 AND t.st_first<t.id)""", (LP,))[0]
pr = next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == LP).get("progress") or {}
check(pr.get("done") == old[1] and pr.get("total") == old[0] + old[1] and pr.get("total", 0) >= 4,
      f"#3108 list progress as the old query {pr} vs open {old[0]} / done {old[1]}")

# a restart keeps the change rows
v1 = A.get(B + "/api/version").json()["v"]
check(A.patch(B + f"/api/tasks/{TS}", json={"title": "Short note (2)"}).ok, "a change before the restart")
subprocess.run(["docker", "restart", CT], check=True, capture_output=True)


def healthy():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


check(until(healthy, 60), "the container is back")
d = A.get(B + "/api/state/delta", params={"since": v1, "lean": "1"}).json()
check(d.get("full") is False and TS in {x["id"] for x in d.get("tasks", [])},
      f"#3108 after a restart: the delta from before it (no herd of full states) {str(d)[:200]}")
check(A.get(B + "/api/state/delta", params={"since": 0, "lean": "1"}).json().get("full") is True, "#3108 a since from before the first start: full")

sys.exit(done("p2280_e_api"))
