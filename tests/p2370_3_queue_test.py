#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.370.3 (#2760): exports and imports as rows of the queue bg_jobs, their state read from the row (any process).
Own container (start.sh, restarted with KEEP=1 for the role web). Invented accounts only (example.com).
 - the role all: an account export is a row (kind umz:export, long slot), done at once, its state "done"; a contacts import
   in the background is a row whose progress the route reads (done, counts)
 - the account / knowledge import's server slots are rows: two import rows waiting elsewhere -> the last piece of an upload
   answers 429 (nothing queued, the upload waits for its last piece again); without them the check runs as a row
 - the role web (no queue thread): the export waits as a row and its state says "running", not "interrupted"; a second start
   is 409; a contacts import waits as a row and its state is readable here; a worker started next to it does both and the
   web process shows "done" (the state of another process)
 - a stop (SIGTERM, bgj_on_term) puts the process' running rows back at once: a kind with runs left waits again, a one-run
   kind (an import) is failed "stopped" (no 2.5 min of "running" for nothing); the process ends with 143
 - long kinds (exports / imports) have slots of their own: with them full, short rows (mails) are still taken
 - the pushes after a request are one row "push:send" (sent at once in the role all, payload emptied); in the role web the
   row waits and the push goes out when a worker takes it; a web process hands bookmark previews to the worker as a row;
   the update check and the pushes of a client's approval / video comment are kinds of the queue (no thread of the request)
freelancer-matrix: n/a (no new route; alice has no organisation: the account export / contacts import run as a person without one)
usage: p2370_3_queue_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import kt
import requests
from kt import check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CONT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
OLD = "2000-01-01T00:00:00+00:00"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


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


def wait_for(fn, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return fn()


def py(code, role="web"):
    """Runs code in a second process of the container (no loops); returns (exit code, the last line as JSON or {})."""
    for _try in range(3):  # the import may meet the running server's start-up DDL (deadlock): try again
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", "-e", "KALMIDO_ROLE=" + role, CONT,
                            "python", "-c", "import app\n" + code], capture_output=True, text=True)
        if "DeadlockDetected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    try:
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print((r.stdout + r.stderr)[-2000:], flush=True)
        return r.returncode, {}


def rows(kind):
    return sql("SELECT id, state, attempts, payload, error, user_id FROM bg_jobs WHERE kind=? ORDER BY id", (kind,))


def vcards(n, prefix):
    return "".join("\r\n".join(["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:Probe Person {i}", f"N:Person {i};Probe;;;",
                                f"EMAIL:probe.{prefix}.{i}@example.com", "END:VCARD"]) + "\r\n" for i in range(n))


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def export_state(s):
    return s.get(B + "/api/account/export").json()


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "contacts", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "ntfy_topic": "t-bob2760"})
BOB = r.json()["id"]
sess("bob").patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Queue probe"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok

# ---------------------------------------------------------------- the pushes after a request: one queue row, sent at once
A.post(B + "/api/tasks", json={"title": "Queue push one", "list_id": L, "assignee_id": BOB})
got = wait_for(lambda: [p for p in pushes() if p.get("topic") == "t-bob2760" and "Queue push one" in (p.get("title") or "")], 20)
check(got, f"push: the assign push reaches the person {pushes()[-3:]}")
pr = wait_for(lambda: [x for x in rows("push:send") if x[1] == "done"], 20)
check(pr and all(x[3] == "" and x[2] == 1 for x in pr), f"push: a queue row push:send, done after one run, payload emptied {rows('push:send')}")

# ---------------------------------------------------------------- the role all: the export and the contacts import are rows
r = A.post(B + "/api/account/export")
check(r.status_code == 202 and r.json().get("state") in ("running", "done"), f"export: 202 and running {r.status_code} {r.text[:200]}")
st = wait_for(lambda: (lambda j: j if j.get("state") == "done" else None)(export_state(A)), 90)
check(st and st.get("file") and st.get("bytes"), f"export: done with its file {st}")
ex = rows("umz:export")
check(len(ex) == 1 and ex[0][1] == "done" and ex[0][2] == 1 and ex[0][3] == "" and ex[0][5] == ALICE,
      f"export: one row of the queue for the person, done after one run, payload emptied {[(x[0], x[1], x[2], x[5]) for x in ex]}")

BK = A.post(B + "/api/books", json={"name": "Queue import"}).json()["id"]
r = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("a.vcf", vcards(150, "q2760"), "text/vcard")})
check(r.status_code == 202 and r.json().get("import_id"), f"contacts import: 202 with an import id {r.status_code} {r.text[:200]}")
IID = r.json().get("import_id", "x")
st = wait_for(lambda: (lambda j: j if j.get("state") in ("done", "failed") else None)(A.get(B + f"/api/books/imports/{IID}").json()), 90)
check(st and st.get("state") == "done" and st.get("created") == 150 and st.get("done") == 150,
      f"contacts import: done, its counts from the row {st}")
li = rows("contacts:import")
check(len(li) == 1 and li[0][1] == "done" and li[0][3] == "", f"contacts import: one row, done, payload emptied {[(x[0], x[1]) for x in li]}")
check(sess("alice").get(B + "/api/books/imports/nope").status_code == 404, "contacts import: an unknown id is 404")

# ---------------------------------------------------------------- the import slots of the server are rows
for i in range(2):  # two imports of nobody in particular waiting on the server (a slot each)
    sql("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at) VALUES('wki:import', '', 'wait', 0, '2999-01-01T00:00:00+00:00', ?)", (OLD,))
blob = os.urandom(64)
j = A.post(B + "/api/account/import", json={"size": len(blob), "name": "probe.zip"}).json()
UP = j.get("id")
r = A.put(B + f"/api/account/import/{UP}?offset=0", data=blob, headers={"Content-Type": "application/octet-stream"})
check(r.status_code == 429 and "Too many imports" in r.json().get("error", ""), f"account import: two import rows elsewhere -> 429 {r.status_code} {r.text[:160]}")
check(not rows("umz:check"), "account import: nothing queued after the 429")
check(A.get(B + f"/api/account/import/{UP}").json().get("state") == "upload", "account import: the upload waits for its last piece again")
sql("DELETE FROM bg_jobs WHERE kind='wki:import'")
r = A.put(B + f"/api/account/import/{UP}?offset=0", data=blob, headers={"Content-Type": "application/octet-stream"})
check(r.status_code == 200, f"account import: with the slots free the last piece is taken {r.status_code} {r.text[:160]}")
st = wait_for(lambda: (lambda x: x if x.get("state") == "invalid" else None)(A.get(B + f"/api/account/import/{UP}").json()), 60)
check(st and st.get("state") == "invalid", f"account import: the check ran as a row (random bytes: invalid) {st}")
ck = rows("umz:check")
check(len(ck) == 1 and ck[0][1] == "done" and ck[0][5] == ALICE, f"account import: the check is a row of the person {[(x[0], x[1]) for x in ck]}")

# 2.551.0 (#4643): a look at the queue that fails (the database busy for a moment) counts an export as running (not as ended), as
# the imports do (#4295); the contacts import's state answers 503 (keep asking), not 404 (gone)
bz = py(f"""
import json
from kalmido.admin import acctexport as ae, orgexport as oe
from kalmido.contacts import web as cw
def boom(*a, **k):
    raise RuntimeError("p4643: no answer from the database")
ae.bgj_busy = oe.bgj_busy = cw.bgj_state = boom
out = {{"account": ae._running({ALICE}), "org": oe._running(987654)}}
try:
    cw.op_import_state({ALICE}, "4643000000000000000000ab")
    out["contacts"] = 200
except Exception as e:
    out["contacts"] = getattr(e, "status", getattr(e, "code", str(e)))
print(json.dumps(out))
""")[1]
check(bz.get("account") is True, f"#4643: account export: a failing look at the queue counts it as running {bz}")
check(bz.get("org") is True, f"#4643: organisation export: a failing look at the queue counts it as running {bz}")
check(bz.get("contacts") == 503, f"#4643: contacts import state: a failing look at the queue is 503, not 404 {bz}")

# ---------------------------------------------------------------- long slots: full with exports / imports, mails still go
lg = py("""
import json
from kalmido.accounts import bgjobs as q
q._SLOTS["long"] = q.BGJ_LONG_SLOTS
full = q._kinds_free()
q._SLOTS["long"] = 0
q._SLOTS["busy"] = q.BGJ_SLOTS
busy = q._kinds_free()
q._SLOTS["busy"] = 0
print(json.dumps({"full": full, "busy": busy, "long": sorted(q.BGJ_LONG)}))
""")[1]
kinds = py("""
import json
from kalmido.accounts import bgjobs as q
from kalmido.core.instance import UPDATE_KICK
print(json.dumps({"kinds": sorted(q.BGJ_FNS), "tries": {k: q.BGJ_TRIES_OF[k] for k in ("push:send", "umz:import", "wki:import", "contacts:import", "umz:export")}, "kick": len(UPDATE_KICK)}))
""")[1]
check({"push:send", "instance:update", "life:bmpreview"} <= set(kinds.get("kinds") or ()) and kinds.get("kick") == 1,
      f"kinds: pushes, the update check and the bookmark previews are queue kinds, the update check queued via UPDATE_KICK {kinds}")
check(kinds.get("tries") == {"push:send": 1, "umz:import": 1, "wki:import": 1, "contacts:import": 1, "umz:export": 3},
      f"kinds that write run once (never twice after a lost run), an export runs again {kinds.get('tries')}")
want_long = {"umz:export", "ox:export", "umz:check", "umz:unlock", "umz:import", "wki:import", "contacts:import"}
check(want_long <= set(lg.get("long") or ()), f"the exports / imports are long kinds {lg.get('long')}")
check(lg.get("full") and "mail:pwreset" in lg["full"] and not want_long & set(lg["full"]),
      f"long slots full: short kinds are still taken, no long one {lg.get('full')}")
check(lg.get("busy") and set(lg["busy"]) <= set(lg["long"]) and "mail:pwreset" not in lg["busy"],
      f"short slots full: only long kinds are taken {lg.get('busy')}")

# ---------------------------------------------------------------- a stop puts the running rows back at once
code, _ = py("""
import json, os, signal
from kalmido.accounts import bgjobs as q
from kalmido.core.db import connect
c = connect()
for kind, att in (("backup", 1), ("umz:import", 1), ("backup", 3)):
    c.execute("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at, started_at, beat_at, started_by, error) "
              "VALUES(?, 'v2.x', 'run', ?, '2999-01-01T00:00:00+00:00', ?, ?, ?, ?, 'p2760')", (kind, att, q.iso(q._now()), q.iso(q._now()), q.iso(q._now()), q._TOKEN))
c.execute("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at, started_at, beat_at, started_by, error) "
          "VALUES('backup', 'v2.x', 'run', 1, '2999-01-01T00:00:00+00:00', ?, ?, ?, 'other-process', 'p2760')", (q.iso(q._now()),) * 3)
c.commit()
c.close()
import threading, time as tm
q._SLOTS["busy"] = 1  # review 1: a row still running gets its grace time before the release
def end():
    tm.sleep(1.5)
    q._SLOTS["busy"] = 0
threading.Thread(target=end, daemon=True).start()
q.bgj_on_term()
open("/tmp/p2760-t0", "w").write(str(tm.time()))
os.kill(os.getpid(), signal.SIGTERM)
import time
time.sleep(5)
print(json.dumps({"alive": True}))
""")
took = subprocess.run(["docker", "exec", CONT, "python", "-c", "import os,time;print(time.time()-float(open('/tmp/p2760-t0').read()))"],
                      capture_output=True, text=True).stdout.strip()
check(code == 143, f"stop: the process ends with 143 after the release (not after the SIGKILL) {code}")
check(took and 1.0 < float(took) < 8.5, f"stop: a running row gets its grace time (about 1.5 s here), at most KALMIDO_BG_STOP_WAIT_S {took}")
got = sql("SELECT kind, attempts, state, error, started_by FROM bg_jobs WHERE error IN ('p2760', 'stopped') ORDER BY id")
check([(g[0], g[2]) for g in got] == [("backup", "wait"), ("umz:import", "failed"), ("backup", "failed"), ("backup", "run")],
      f"stop: a row with runs left waits again, a one-run import and a row with its runs used up fail, another process' row stays {got}")
check(got[0][4] == "" and got[1][3] == "stopped", f"stop: the waiting row is free for any process, the failed one says stopped {got}")
sql("DELETE FROM bg_jobs WHERE error IN ('p2760', 'stopped')")

# review 7: the progress of an ended row (names of bad cards, counts) goes after an hour
pg = py("""
import json
from datetime import timedelta
from kalmido.accounts import bgjobs as q
from kalmido.core.db import connect
c = connect()
rid = c.execute("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at, finished_at, progress) VALUES('contacts:import', '', 'done', 1, ?, ?, ?, '{\\"bad\\": [1]}') RETURNING id", (q.iso(q._now()), q.iso(q._now()), q.iso(q._now() - timedelta(hours=2)))).fetchone()[0]
c.commit()
q.bgj_house(c, force=True)
print(json.dumps({"p": c.execute("SELECT progress FROM bg_jobs WHERE id=?", (rid,)).fetchone()[0]}))
c.execute("DELETE FROM bg_jobs WHERE id=?", (rid,))
c.commit()
""")[1]
check(pg.get("p") == "", f"housekeeping: the progress of a row ended over an hour ago is emptied {pg}")

# ---------------------------------------------------------------- the role web: rows wait, the state comes from the row
start(keep=True, extra=" -e KALMIDO_ROLE=web")
A = sess("alice")
r = A.post(B + "/api/account/export")
check(r.status_code == 202 and r.json().get("state") == "running", f"role web: the export is queued, running {r.status_code} {r.text[:160]}")
time.sleep(4)
st = export_state(A)
check(st.get("state") == "running" and not st.get("error"),
      f"role web: while its row waits the export says running, not interrupted (no thread of this process) {st}")
check(rows("umz:export")[-1][1] == "wait", f"role web: the row waits for the worker {rows('umz:export')[-1][:3]}")
r = A.post(B + "/api/account/export")
check(r.status_code == 409, f"role web: a second start while the row waits: 409 {r.status_code}")
r = A.delete(B + "/api/account/export")
check(r.ok and not [x for x in rows("umz:export") if x[1] == "wait"], f"role web: an export waiting for a worker can be removed (review 6) {r.status_code}")
r = A.post(B + "/api/account/export")
check(r.status_code == 202, f"role web: and started again {r.status_code}")
r = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("b.vcf", vcards(120, "w2760"), "text/vcard")})
check(r.status_code == 202, f"role web: a contacts import is queued {r.status_code} {r.text[:160]}")
IID = r.json().get("import_id", "x")
st = A.get(B + f"/api/books/imports/{IID}").json()
check(st.get("state") == "running" and st.get("total") == 120, f"role web: its state is read from the waiting row {st}")
check(A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("c.vcf", vcards(120, "x2760"), "text/vcard")}).status_code == 409,
      "role web: a second contacts import of the person while one waits: 409")
n_push = len(rows("push:send"))
A.post(B + "/api/tasks", json={"title": "Queue push two", "list_id": L, "assignee_id": BOB})
bm = py("""
import json
from kalmido.life.bookmarks import bm_kick
from kalmido.accounts.session import bg_here
bm_kick([987654321])
print(json.dumps({"bg": bg_here()}))
""")[1]
time.sleep(3)
check(len(rows("push:send")) == n_push + 1 and rows("push:send")[-1][1] == "wait" and not [p for p in pushes() if "Queue push two" in (p.get("title") or "")],
      f"role web: the push waits as a row, nothing sent from the web process {rows('push:send')[-2:]}")
check(bm.get("bg") is False and [x for x in rows("life:bmpreview") if x[1] == "wait"],
      f"role web: bookmark previews go to the worker as a row {bm} {rows('life:bmpreview')}")
subprocess.run(["docker", "exec", "-d", "-e", "KALMIDO_WORKER_HEARTBEAT=5", CONT, "python", "app.py", "worker"], check=False)
got = wait_for(lambda: [p for p in pushes() if p.get("topic") == "t-bob2760" and "Queue push two" in (p.get("title") or "")], 120)
check(got, "role web: the worker takes the push row and sends it")
check(wait_for(lambda: [x for x in rows("life:bmpreview") if x[1] == "done"], 60), f"role web: the worker takes the preview row {rows('life:bmpreview')}")
st = wait_for(lambda: (lambda j: j if j.get("state") == "done" else None)(export_state(A)), 120)
check(st and st.get("file"), f"role web: the worker's export is done, the web process shows it {st}")
st = wait_for(lambda: (lambda j: j if j.get("state") in ("done", "failed") else None)(A.get(B + f"/api/books/imports/{IID}").json()), 120)
check(st and st.get("state") == "done" and st.get("created") == 120, f"role web: the worker's contacts import is done, read here {st}")
# a row that ended without its run writing the end (the server stopped meanwhile): interrupted, not running for ever
sql("UPDATE bg_jobs SET state='failed', error='stopped' WHERE kind='contacts:import' AND id=(SELECT MAX(id) FROM bg_jobs WHERE kind='contacts:import')")
sql("UPDATE bg_jobs SET progress=replace(progress, '\"state\": \"done\"', '\"state\": \"running\"') WHERE kind='contacts:import' AND id=(SELECT MAX(id) FROM bg_jobs WHERE kind='contacts:import')")
st = A.get(B + f"/api/books/imports/{IID}").json()
check(st.get("state") == "failed" and "interrupted" in (st.get("error") or ""), f"a row ended without the run's end: interrupted {st}")

sys.exit(kt.done("p2370_3_queue_test"))
