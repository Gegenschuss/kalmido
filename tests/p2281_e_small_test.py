#!/usr/bin/env python3
"""2.281.0 E (#3117): small load fixes from audit Q with the same answers. Own container (start.sh, upload limit 1 MB per
hour). Invented people and texts only; every check runs as a person WITHOUT an organisation (freelancer fixture).
freelancer-matrix: pim, time, tasks
 - the contact list reads the photo as a flag (no SELECT * with the picture data), the list still says photo true and the
   contact itself still has its picture
 - GET /api/time/entries: newest first as before (also the same start: higher id first), limit=2 = the first two of the
   full list with the totals of ALL entries (seconds / mine), a running timer counts in the totals; the LIMIT is in SQL
 - GET /api/events: the same occurrences (one day, several days, all day, an open weekly series; not: before, after,
   a series that ended) and the range query uses the index ix2281_events_range with the end in the index condition
 - uploads per person and hour: the second upload over KALMIDO_UPLOAD_HOURLY_MB = 429 with a text, someone else may
   still upload
 - the app-role check (pg_roles) runs once per process, not per new database connection; pool_refresh asks again
usage: p2281_e_small_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import FAILS, OKS, B, CT, check, sess, today  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
env = dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + " -e KALMIDO_UPLOAD_HOURLY_MB=1").strip())
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    try:
        return json.loads(out[-1]) if out else {"err": r.stderr[-800:]}
    except ValueError:
        return {"err": out[-1][:300] + " " + r.stderr[-800:]}


# One request through the app inside the container with every SQL statement recorded (Q: [sql, args]); `after` may use Q.
PROBE = '''
from kalmido.core import pg
from kalmido.core.config import app as fa
Q = []
_ex = pg.Conn.execute
def ex(self, sql, args=None):
    Q.append([sql, list(args or [])])
    return _ex(self, sql, args)
pg.Conn.execute = ex
cl = fa.test_client()
H = {"X-Requested-With": "kalmido"}
r = cl.post("/api/auth/login", json={"username": %r, "password": "password123"}, headers=H, base_url="https://localhost")
del Q[:]
r = cl.get(%r, headers=H, base_url="https://localhost")
pg.Conn.execute = _ex
out = {"status": r.status_code, "q": Q}
%s
print(json.dumps(out, default=str))
'''


def probe(user, path, after=""):
    return in_app(PROBE % (user, path, after))


def sql_with(res, *parts):
    return [q for q in res.get("q", []) if all(p in q[0] for p in parts)]


# ================================================================== contact list without the picture data
BK = Fr.post(B + "/api/books", json={"name": "People", "org_id": None}).json()["id"]
PHOTO = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"p" * 300_000).decode()
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Ada Example", "emails": [{"value": "ada@example.com"}], "photo": PHOTO})
check(r.status_code in (200, 201), f"contact with a photo created: {r.status_code} {r.text[:200]}")
CA = r.json().get("id")
Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Ben Example"})
r = Fr.get(B + "/api/contacts")
its = {c["fn"]: c for c in r.json().get("items", [])}
check(its.get("Ada Example", {}).get("photo") is True and its.get("Ben Example", {}).get("photo") is False,
      f"the list says photo true / false: {[(k, v.get('photo')) for k, v in its.items()]}")
check(len(r.content) < 20_000, f"the list answer carries no picture ({len(r.content)} bytes)")
check((Fr.get(B + f"/api/contacts/{CA}").json().get("photo") or "").startswith("data:image/png;base64,"), "the contact still has its picture")
res = probe("frida", "/api/contacts")
q = sql_with(res, "FROM contacts WHERE", "ORDER BY")
check(res.get("status") == 200 and len(q) == 1, f"the list query ran once: {res.get('status')} {len(q)} {res.get('err', '')}")
check(q and "SELECT *" not in q[0][0] and "photo!=''" in q[0][0], f"the list query reads the photo as a flag: {q[0][0][:160] if q else ''}")

# ================================================================== time entries: LIMIT in SQL, the same answer
L = Fr.post(B + "/api/lists", json={"name": "Shoot", "kind": "project", "time_tracking": True}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"list_id": L, "title": "Cut the trailer"}).json()["id"]
D0 = today()
made = []
for i, mins in enumerate((10, 20, 30, 40)):
    r = Fr.post(B + "/api/time/entries", json={"task_id": T, "start": f"{D0 - timedelta(days=i + 1)}T09:00", "minutes": mins, "note": f"n{i}"})
    check(r.ok, f"entry {i}: {r.text[:200]}")
    made.append((r.json().get("id"), mins))
r = Fr.post(B + "/api/time/entries", json={"list_id": L, "start": f"{D0 - timedelta(days=1)}T09:00", "minutes": 5, "note": "same start"})
made.append((r.json().get("id"), 5))
check(Fr.post(B + "/api/time/start", json={"task_id": T}).ok, "timer started")
j = Fr.get(B + "/api/time/entries?scope=mine").json()
es = j.get("entries", [])
check(len(es) == 6 and es[0]["running"], f"six entries, the running one first: {len(es)}")
check(j.get("seconds") == sum(e["seconds"] for e in es) and j.get("mine") == j.get("seconds"),
      f"totals with the running timer: {j.get('seconds')} / {j.get('mine')} vs {sum(e['seconds'] for e in es)}")
check([e["id"] for e in es[1:3]] == [made[4][0], made[0][0]], f"the same start: higher id first {[e['id'] for e in es[1:3]]}")
check([e["id"] for e in es[3:]] == [made[1][0], made[2][0], made[3][0]], "older entries follow newest first")
Fr.post(B + "/api/time/stop", json={})
full = Fr.get(B + "/api/time/entries?scope=mine").json()
two = Fr.get(B + "/api/time/entries?scope=mine&limit=2").json()
check([e["id"] for e in two["entries"]] == [e["id"] for e in full["entries"][:2]], "limit=2 = the first two of the full list")
check(two["seconds"] == full["seconds"] == sum(e["seconds"] for e in full["entries"]) and two["mine"] == full["mine"],
      f"limit=2 keeps the totals of all entries: {two['seconds']} / {full['seconds']}")
lj = Fr.get(B + f"/api/time/entries?scope=mine&lists={L}").json()
check(len(lj["entries"]) == len(full["entries"]) and lj["seconds"] == full["seconds"], "the list filter answers as before")
check(Fr.get(B + "/api/time/entries?limit=x").status_code == 400, "a bad limit is still 400")
res = probe("frida", "/api/time/entries?scope=mine&limit=2")
q = sql_with(res, "FROM time_entries e LEFT JOIN tasks t")
check(res.get("status") == 200 and q and "LIMIT" in q[0][0] and 2 in q[0][1],
      f"the entry query carries the LIMIT: {res.get('status')} {(q[0][0][-90:], q[0][1][-1:]) if q else res.get('err', '')}")

# ================================================================== events: the same occurrences, the range index
E0 = D0 + timedelta(days=30)
LO, HI = E0, E0 + timedelta(days=6)
EVS = {"single": {"start": f"{E0 + timedelta(days=2)}T10:00", "end": f"{E0 + timedelta(days=2)}T11:00"},
       "multi": {"start": f"{E0 - timedelta(days=3)}T09:00", "end": f"{E0 + timedelta(days=1)}T17:00"},
       "allday": {"all_day": True, "start": str(E0 + timedelta(days=5)), "end": str(E0 + timedelta(days=8))},
       "weekly": {"start": f"{E0 - timedelta(days=60)}T08:00", "end": f"{E0 - timedelta(days=60)}T09:00", "rrule": "FREQ=WEEKLY"},
       "before": {"start": f"{E0 - timedelta(days=10)}T10:00", "end": f"{E0 - timedelta(days=10)}T11:00"},
       "after": {"start": f"{HI + timedelta(days=10)}T10:00", "end": f"{HI + timedelta(days=10)}T11:00"},
       "ended": {"start": f"{E0 - timedelta(days=60)}T08:00", "end": f"{E0 - timedelta(days=60)}T09:00",
                 "rrule": "FREQ=WEEKLY;UNTIL=" + (E0 - timedelta(days=20)).strftime("%Y%m%d") + "T000000Z"}}
for t, b in EVS.items():
    r = Fr.post(B + "/api/events", json={"title": t, **b})
    check(r.status_code in (200, 201), f"event {t}: {r.status_code} {r.text[:160]}")
its = Fr.get(B + f"/api/events?from={LO}&to={HI}").json().get("items", [])
got = sorted(i["title"] for i in its)
check(got == ["allday", "multi", "single", "weekly"], f"the same occurrences in the range: {got}")
AFTER = '''
from kalmido.core.db import connect
c = connect()
c.execute("SET enable_seqscan=off")
ev = [x for x in Q if "FROM events WHERE cal_id IN" in x[0]]
out["ev"] = ev[0][0] if ev else ""
try:
    pr = c.execute("EXPLAIN " + ev[0][0], ev[0][1]).fetchall() if ev else []
    out["plan"] = [str(r[0]) for r in pr]
except Exception as e:
    out["plan_err"] = repr(e)[:400]
out["ix"] = [r[0] for r in c.execute("SELECT indexdef FROM pg_indexes WHERE indexname='ix2281_events_range'").fetchall()]
c.rollback()
c.close()
'''
res = probe("frida", f"/api/events?from={LO}&to={HI}", AFTER)
plan = "\n".join(res.get("plan") or [])
check(bool(res.get("ix")), f"the index exists: {res.get('ix')} {res.get('err', '')}")
check("CASE WHEN last_day='' THEN '9999-12-31' ELSE last_day END)>=" in (res.get("ev") or ""),
      f"the range query filters the end with the index expression: {(res.get('ev') or '')[:220]}")
check("ix2281_events_range" in plan and any("Index Cond" in ln and "CASE" in ln and "first_day" in ln for ln in plan.splitlines()),
      "the range query can use ix2281_events_range with the end in the index condition (seqscan off)")
print("PERF event range plan (seqscan off): " + " | ".join(ln.strip() for ln in plan.splitlines()) + f" {res.get('plan_err') or ''}")  # information

# ================================================================== uploads per person and hour (1 MB in this container)
BIG = b"a" * 700_000
r = Fr.post(B + f"/api/tasks/{T}/attachments", files={"file": ("one.txt", BIG, "text/plain")})
check(r.ok, f"first upload of the hour: {r.status_code} {r.text[:160]}")
r = Fr.post(B + f"/api/tasks/{T}/attachments", files={"file": ("two.txt", BIG, "text/plain")})
check(r.status_code == 429 and "Upload limit reached" in (r.json().get("error") or ""), f"second upload over 1 MB/h: {r.status_code} {r.text[:200]}")
TA = A.post(B + "/api/tasks", json={"title": "Alice files"}).json()["id"]
r = A.post(B + f"/api/tasks/{TA}/attachments", files={"file": ("a.txt", BIG, "text/plain")})
check(r.ok, f"someone else may still upload: {r.status_code}")

# ================================================================== the app-role check once per process
ROLE = '''
import psycopg
from kalmido.core import pg as P, rls
from kalmido.core.db import DATABASE_URL
n = [0]
class W:
    def __init__(s, c):
        s.c = c
    def execute(s, q, *a):
        n[0] += "pg_roles" in q
        return s.c.execute(q, *a)
    def commit(s):
        s.c.commit()
def one():
    raw = psycopg.connect(DATABASE_URL)
    P._rls_enter(W(raw))
    u = raw.execute("SELECT current_user").fetchone()[0]
    raw.close()
    return u
roles = [one() for _ in range(5)]
first = n[0]
P.pool_refresh()
roles.append(one())
raw = psycopg.connect(DATABASE_URL)
need = bool(raw.execute(rls.enter_sql()).fetchone()[0])
login = raw.execute("SELECT current_user").fetchone()[0]
raw.close()
print(json.dumps({"first": first, "again": n[0] - first, "roles": roles, "need": need, "login": login}))
'''
res = in_app(ROLE)
check(res.get("first", 9) <= 1, f"five new connections: the role check at most once ({res})")
check(res.get("again") == 1, f"after pool_refresh the check runs again: {res.get('again')}")
want = "kalmido_app" if res.get("need") else res.get("login")
check(res.get("roles") and all(x == want for x in res["roles"]), f"every connection works as {want}: {res.get('roles')}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
