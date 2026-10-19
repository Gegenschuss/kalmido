#!/usr/bin/env python3
"""2.102.0 API tests, part D (server architecture), own container (start.sh, restarted with KEEP=1 between the steps).
Invented accounts only (example.com).
 - #1994: GET /api/admin/health -- instance admins only (a member, a person without an organisation, an agent's token and
   nobody get 401 / 403); the fields (version, role, threads, pool, connections, loops), numbers only (no account names);
   KALMIDO_THREADS / KALMIDO_DB_POOL_MAX move threads and pool
 - #1996: kalmido_migrations -- a fresh database records every MIGRATIONS step (id table.column, the second step of a
   column table.column#2) and the one-shots (flag:migr_*); a second start runs nothing; a database without the table
   (every one before 2.102) records everything as present; a recorded step whose column is gone runs again; a deleted
   one-shot flag repeats the one-shot (settings flag and row both back)
 - #1997: the role web starts no background loop (health: no loop, the watchdog's lock is free) and still serves; a worker
   process (`python app.py worker`) next to it takes the loops (its heartbeat in the web's health, the lock held); next to
   a process with the role all a second process waits for every loop (no double pushes / mails / backups)
usage: p2102_d_api_test.py <datadir>      (P2102D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh -- then only
       the checks without a restart run)"""
import ast
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CONT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
NOSTART = os.environ.get("P2102D_NOSTART") == "1"
FAILS, OKS = [], [0]


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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def logs(tail=400):
    out = subprocess.run(["docker", "logs", "--tail", str(tail), CONT], capture_output=True, text=True)
    return out.stdout + out.stderr


def app_log():
    text = logs()
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def start(keep=False, extra=""):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + extra, **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for _ in range(60):
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                break
        except requests.RequestException:
            pass
        time.sleep(0.5)


def lock_free(name):
    """The loop's advisory lock is free (psql takes and drops it again at its exit) -- no process runs that loop."""
    v = sql("SELECT pg_try_advisory_lock(21020, hashtext(?))", ("loop:" + name,))[0][0]
    return v in (True, "t", 1, "1")


def health(s):
    r = s.get(B + "/api/admin/health")
    return r.json() if r.ok else {}


def wait_for(fn, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        v = fn()
        if v:
            return v
        time.sleep(1)
    return fn()


def migration_ids():
    """The ids the server gives the MIGRATIONS steps (core/db.py mig_ids), from the exported schema."""
    src = open(os.path.join(N, "..", "kalmido", "core", "schema.py"), encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MIGRATIONS":
            seen, out = {}, []
            for e in node.value.elts:
                k = f"{e.elts[0].value}.{e.elts[1].value}"
                seen[k] = seen.get(k, 0) + 1
                out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
            return out
    return []


def setup():
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    a = sess("alice")
    a.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
    r = a.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123",
                                       "email": "bob@example.com"})
    assert r.ok, r.text
    return a


if not NOSTART:
    start()
A = setup() if not NOSTART else sess("alice")
Bo = sess("bob")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json().get("id")
if ORG:
    A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"})
FID, Fr = freelancer(B, A)
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "admin-read"], "username": "claude", "display_name": "Claude"}).json()

# ---------------------------------------------------------------- #1994: rights
r = A.get(B + "/api/admin/health")
check(r.ok, f"#1994: the instance admin reads the health numbers {r.status_code} {r.text[:200]}")
if not r.ok:
    app_log()
    sys.exit(1)
check(Bo.get(B + "/api/admin/health").status_code == 403, "#1994: an organisation's admin who is no instance admin: 403")
check(Fr.get(B + "/api/admin/health").status_code == 403, "#1994: a person without an organisation: 403")
check(requests.get(B + "/api/admin/health", headers={**H, "Authorization": "Bearer " + ag.get("token", "x")}).status_code in (401, 403),
      "#1994: an agent's token (even with admin-read): 401 / 403")
check(requests.get(B + "/api/admin/health", headers=H).status_code in (401, 403), "#1994: nobody signed in: 401 / 403")

# ---------------------------------------------------------------- #1994: fields
j = r.json()
check(j.get("ok") is True and j.get("version") and j.get("role") == "all", f"#1994: version + role all (the default) {j.get('role')}")
th, pl, cn = j.get("threads") or {}, j.get("pool") or {}, j.get("connections") or {}
check(th.get("configured") == 16 and th.get("busy", 0) >= 1 and th.get("peak", 0) >= th.get("busy", 0),
      f"#1994: 16 threads by default, this request counts as busy {th}")
check(pl.get("max") == int(os.environ.get("KALMIDO_DB_POOL_MAX") or 56) and pl.get("min") == 4 and pl.get("timeouts") == 0
      and "pool_size" in pl and "requests_waiting" in pl, f"#1994: the pool's counters (4..56 = 16 x 3 + 8) {pl}")
check(cn.get("max_connections", 0) >= 100 and cn.get("replicas") == 1 and cn.get("need") == pl.get("max", 0) + 6 and cn.get("ok") is True,
      f"#1994: the connection budget {cn}")
check(all(isinstance(v, (int, float)) for v in pl.values()), "#1994: pool = numbers only")
low = r.text.lower()
check("alice" not in low and "bob" not in low and "example.com" not in low and "password" not in low,
      "#1994: no account names / addresses in the answer")
loops = j.get("loops") or {}
check(loops.get("watchdog") == "running" and loops.get("git") == "running", f"#1994 / #1997: the loops of this process {loops}")

# ---------------------------------------------------------------- #1997: one process per loop (the lock is held)
check(not lock_free("watchdog") and not lock_free("git"), "#1997: the watchdog's and git's locks are held by the server")
check(lock_free("mail-in"), "#1997: a loop that is off here (no mailbox) holds no lock")

# ---------------------------------------------------------------- #1996: fresh database
ids = migration_ids()
rows = {r[0]: r for r in sql("SELECT id, applied_at, note FROM kalmido_migrations")}
check(len(ids) > 300 and set(ids) <= set(rows), f"#1996: every MIGRATIONS step recorded ({len(ids)} steps, missing "
      f"{sorted(set(ids) - set(rows))[:5]})")
check("lists.tap_done#2" in rows and rows["lists.tap_done"][2] in ("applied", "present"), "#1996: id table.column, a second step #2")
check(all(rows[i][2] in ("applied", "present") and rows[i][1] for i in ids if i in rows), "#1996: note applied / present + time")
check("flag:migr_kind" in rows and rows["flag:migr_kind"][2] == "one-shot", "#1996: the one-shots recorded (flag:migr_*)")
check([r[0] for r in sql("SELECT value FROM settings WHERE key='migr_kind'")] == ["1"],
      "#1996: the settings flag stays written (an older version reads it after a rollback)")

if NOSTART:
    print(f"p2102_d_api_test: {OKS[0]} ok, {len(FAILS)} failed (P2102D_NOSTART: no restarts)")
    sys.exit(1 if FAILS else 0)

# ---------------------------------------------------------------- #1996: the second start runs nothing
before = {r[0]: (r[1], r[2]) for r in sql("SELECT id, applied_at, note FROM kalmido_migrations")}
start(keep=True)
after = {r[0]: (r[1], r[2]) for r in sql("SELECT id, applied_at, note FROM kalmido_migrations")}
diff = sorted(set(after.items()) ^ set(before.items()))
check(after == before, f"#1996: a second start changes nothing ({len(diff)} rows differ: {diff[:4]})")
check("step(s) applied" not in logs(200), "#1996: no step applied in the log")

# ---------------------------------------------------------------- #1996: a database from before (no table)
sql("DROP TABLE kalmido_migrations")
start(keep=True)
up = {r[0]: r[1] for r in sql("SELECT id, note FROM kalmido_migrations")}
check(set(ids) <= set(up) and all(up[i] == "present" for i in ids), "#1996: upgrade -- every step found present, none applied")
check(up.get("flag:migr_kind") == "one-shot", "#1996: upgrade -- the one-shot flags recorded")
check(sess("alice").get(B + "/api/state").ok, "#1996: the app works after the upgrade")

# ---------------------------------------------------------------- #1996: a recorded column that is gone runs again
sql("ALTER TABLE habit_logs DROP COLUMN note")
t0 = sql("SELECT applied_at FROM kalmido_migrations WHERE id='flag:migr_kind272'")[0][0]
sql("DELETE FROM settings WHERE key='migr_kind272'")
time.sleep(1.1)
start(keep=True)
r = sql("SELECT note FROM kalmido_migrations WHERE id='habit_logs.note'")
check(r and r[0][0] == "again" and sql("SELECT column_name FROM information_schema.columns WHERE table_name='habit_logs' AND column_name='note'"),
      f"#1996: the dropped column came back (note again) {r}")
r = sql("SELECT applied_at FROM kalmido_migrations WHERE id='flag:migr_kind272'")
check(r and r[0][0] > t0 and sql("SELECT value FROM settings WHERE key='migr_kind272'")[0][0] == "1",
      "#1996: a deleted one-shot flag repeats the one-shot: flag back, the row has the new time")

# ---------------------------------------------------------------- #1997: role web
start(keep=True, extra=" -e KALMIDO_ROLE=web")
A = sess("alice")
j = health(A)
check(j.get("role") == "web" and not any(v == "running" for v in (j.get("loops") or {}).values()),
      f"#1997: role web -- no loop runs {j.get('role')} {j.get('loops')}")
check(lock_free("watchdog") and lock_free("calendars") and lock_free("backup"), "#1997: role web -- the loops' locks are free")
LID = A.post(B + "/api/lists", json={"name": "Web role list"}).json().get("id")
check(LID and A.post(B + "/api/tasks", json={"title": "Served by the web role", "list_id": LID}).ok, "#1997: role web serves requests")
# a worker process next to it (in the same container: the same image and database)
subprocess.run(["docker", "exec", "-d", "-e", "KALMIDO_WORKER_HEARTBEAT=5", CONT, "python", "app.py", "worker"], check=False)
hb = wait_for(lambda: ((health(A).get("worker") or {}).get("loops") or {}).get("watchdog") == "running" and health(A)["worker"], 60)
check(isinstance(hb, dict) and hb.get("loops", {}).get("watchdog") == "running" and hb.get("age_s", 99) < 60 and hb.get("version"),
      f"#1997: the worker runs the loops, its heartbeat shows in the web's health {hb}")
check(not lock_free("watchdog"), "#1997: the worker holds the watchdog's lock")
check(health(A).get("role") == "web" and not any(v == "running" for v in (health(A).get("loops") or {}).values()),
      "#1997: the web process still runs none itself")

# ---------------------------------------------------------------- #1997: role all + a second process: it waits
start(keep=True)
A = sess("alice")
check(health(A).get("loops", {}).get("watchdog") == "running", "#1997: role all again -- the server runs the watchdog")
sql("DELETE FROM settings WHERE key='wrk_heartbeat'")
subprocess.run(["docker", "exec", "-d", "-e", "KALMIDO_WORKER_HEARTBEAT=5", CONT, "python", "app.py", "worker"], check=False)
hb = wait_for(lambda: (health(A).get("worker") or {}).get("loops"), 60)
check(isinstance(hb, dict) and hb.get("watchdog") == "waiting" and hb.get("git") == "waiting"
      and not any(v == "running" for k, v in hb.items() if k in ("watchdog", "git", "calendars", "backup", "webhooks")),
      f"#1997: a second process waits for every loop the first one runs (no double pushes) {hb}")
check(health(A).get("loops", {}).get("watchdog") == "running", "#1997: the first process keeps running it")

# ---------------------------------------------------------------- #1994: threads + pool per env
start(keep=True, extra=" -e KALMIDO_THREADS=6")
A = sess("alice")
j = health(A)
check((j.get("threads") or {}).get("configured") == 6 and (j.get("pool") or {}).get("max") == 26,
      f"#1994: KALMIDO_THREADS=6 -> 6 threads, pool 6 x 3 + 8 = 26 {j.get('threads')} {j.get('pool', {}).get('max')}")
start(keep=True, extra=" -e KALMIDO_DB_POOL_MAX=300 -e KALMIDO_REPLICAS=2")
A = sess("alice")
j = health(A)
check((j.get("pool") or {}).get("max") == 300 and (j.get("connections") or {}).get("ok") is False,
      f"#1994: an explicit pool + 2 replicas over max_connections -> not ok {j.get('connections')}")
check("WARNING database connections" in logs(400), "#1994: the start-up warning in the log")

print(f"p2102_d_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
