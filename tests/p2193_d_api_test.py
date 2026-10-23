#!/usr/bin/env python3
"""2.193.0 API tests, part D (#2220): the rest of the background work through the database. Own container (start.sh,
restarted with KEEP=1 between the steps). Invented accounts only (example.com).
 - the queue bg_jobs: "Back up now" is a row (payload sealed, no plain argument), in the role all it is done at once (the
   backup listed, the row done, payload emptied); the health shows the loop bgjobs and the rows per state (numbers only)
 - the role web: no queue thread at all (no loop in the health, also none of the on-demand queues), "Back up now" waits
   as a row (the state says running), two takers at once get two different rows (FOR UPDATE SKIP LOCKED); a row whose
   process is gone (state run, no beat) is taken again by a worker process started next to it and done (runs 2)
 - incoming mail: one message of a mailbox is handled once, also when two processes fetch it (mail_fetch with the same
   box twice); a second copy with another UID stays a mail of its own; a box without a key works as before
 - the agents' log writers have names (agent-audit, agent-access); every kind of the queue is registered
usage: p2193_d_api_test.py <datadir>"""
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


def health(s):
    r = s.get(B + "/api/admin/health")
    return r.json() if r.ok else {}


def py(code, role="web"):
    """Runs code in a second process of the container (no loops: TASKS_WATCHDOG=0, role web); the last line = JSON."""
    for _try in range(3):  # 2.165.4: the import may meet the running server's start-up DDL (deadlock): try again
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", "-e", "KALMIDO_ROLE=" + role, CONT,
                            "python", "-c", "import app\n" + code], capture_output=True, text=True)
        if "DeadlockDetected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print((r.stdout + r.stderr)[-2000:], flush=True)
        return {}


def rows(kind="backup"):
    return sql("SELECT id, state, attempts, payload, error FROM bg_jobs WHERE kind=? ORDER BY id", (kind,))


def backups(s):
    return s.get(B + "/api/admin/backups").json()


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})

# ---------------------------------------------------------------- the role all: "Back up now" through the queue, at once
n0 = len(backups(A)["items"])
t0 = time.time()
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202 and r.json().get("running"), f"back up now: 202, the state says running at once {r.status_code} {r.text[:200]}")
j = wait_for(lambda: (lambda b: b if not b["running"] and len(b["items"]) > n0 else None)(backups(A)), 60)
check(j and len(j["items"]) == n0 + 1 and j["last_ok"] and not j["last_error"], f"the backup is written and listed {j and j.get('items')}")
check(time.time() - t0 < 30, f"done without a noticeable wait ({time.time() - t0:.1f} s)")
rs = rows()
check(len(rs) == 1 and rs[0][1] == "done" and rs[0][2] == 1 and rs[0][3] == "", f"one row of the queue, done after one run, payload emptied {rs}")
h = health(A)
q = h.get("queue") or {}
check(set(q) == {"wait", "run", "done", "failed"} and all(isinstance(v, int) for v in q.values()) and q["done"] >= 1,
      f"health: the queue's rows per state, numbers only {q}")
check((h.get("loops") or {}).get("bgjobs") == "running", f"health: the loop bgjobs runs in this process {h.get('loops')}")
check(not sql("SELECT 1 FROM bg_jobs WHERE payload<>'' AND state='done'"), "no payload is kept after a run")

# ---------------------------------------------------------------- every kind registered, the writers named, sealed payload
reg = py("""
import json, threading
from kalmido.accounts.bgjobs import BGJ_FNS, _seal, _unseal
from kalmido.core.db import connect
c = connect()
s = _seal(c, "backup", ["manual"])
big = ["x" * 20000, bytes(range(256)) * 30, ("a", None, 3)]  # a long mail with HTML and an attachment
back = _unseal(c, "mail:evinvite", _seal(c, "mail:evinvite", big))
try:
    _unseal(c, "backup", _seal(c, "mail:evinvite", big))
    bound = False
except Exception:
    bound = True
print(json.dumps({"kinds": sorted(BGJ_FNS), "sealed": s.startswith("v1.") and "manual" not in s,
                  "big": back == [big[0], big[1], ["a", None, 3]], "bound": bound}))
""")
want = {"backup", "offsite", "orgcrypt:migrate", "orgcrypt:settle", "mail:pwreset", "mail:apptbook", "mail:polls",
        "mail:evinvite", "mail:forms", "mail:portal"}
check(want <= set(reg.get("kinds") or ()), f"every kind is registered {reg.get('kinds')}")
check(reg.get("sealed") is True, "the arguments are sealed with the server key (no plain value in the row)")
check(reg.get("big") is True and reg.get("bound") is True,
      f"a long payload with bytes comes back whole, a row of another kind cannot be opened {reg}")
src = {f: open(os.path.join(N, "..", "kalmido", *f.split("/")), encoding="utf-8").read() for f in
       ("agents/usage.py", "agents/safety.py", "docs/ingest.py", "files/textscan.py", "paperless/ngx.py", "paperless/zipimp.py",
        "tasks/related.py")}
check('name="agent-audit"' in src["agents/usage.py"] and 'name="agent-access"' in src["agents/safety.py"],
      "the agents' log writers have thread names")
check(all("if not bg_here():" in src[f] for f in ("docs/ingest.py", "files/textscan.py", "paperless/ngx.py", "paperless/zipimp.py",
                                                  "tasks/related.py")), "every on-demand queue asks bg_here() before it starts a thread")

# ---------------------------------------------------------------- incoming mail: once per mailbox, also with two processes
mail = py(r"""
import json
from kalmido.integrations.mail import mail_fetch

class FakeIMAP:
    def __init__(self, msgs):
        self.msgs, self.read = msgs, (lambda n: b"")
    def select(self, folder):
        return "OK", [b"1"]
    def uid(self, cmd, *a):
        if cmd == "SEARCH":
            return "OK", [b" ".join(self.msgs)]
        if cmd == "FETCH":
            u, what = a
            if "SIZE" in what:
                return "OK", [b"1 (UID " + u + b" RFC822.SIZE 200)"]
            return "OK", [(b"1 (RFC822 {200}", self.msgs[u])]
        return "OK", [b""]

raw = b"Message-ID: <p2193d-1@example.com>\r\nSubject: Test\r\nFrom: a@example.com\r\n\r\nBody"
other = b"Subject: no id\r\nFrom: b@example.com\r\n\r\nBody 2"
seen = []
imp = lambda c, r: seen.append(r) or 1
n1 = mail_fetch(FakeIMAP({b"7": raw, b"8": other}), "INBOX", imp, box="test:p2193d")
n2 = mail_fetch(FakeIMAP({b"7": raw, b"8": other}), "INBOX", imp, box="test:p2193d")  # a second process, same mails
first = len(seen)
n3 = mail_fetch(FakeIMAP({b"9": raw}), "INBOX", imp, box="test:p2193d")  # a second copy (another UID)
n4 = mail_fetch(FakeIMAP({b"7": raw}), "INBOX", imp, box="test:p2193d-other")  # another mailbox
n5 = mail_fetch(FakeIMAP({b"7": raw}), "INBOX", imp)  # no key: as before
print(json.dumps({"n": [n1, n2, n3, n4, n5], "first": first, "all": len(seen)}))
""")
check(mail.get("n") == [2, 0, 1, 1, 1] and mail.get("first") == 2 and mail.get("all") == 5,
      f"mail: handled once per mailbox (a second fetch takes nothing), a copy with another UID and another mailbox count {mail}")
keys = sql("SELECT box, mid FROM mail_in_seen WHERE box LIKE 'test:p2193d%'")
check(len(keys) == 4 and all(len(k[1]) == 64 and "example.com" not in k[1] for k in keys), f"mail: the claims hold hashes only {keys}")

# ---------------------------------------------------------------- the role web: no queue thread, rows wait for the worker
start(keep=True, extra=" -e KALMIDO_ROLE=web")
A = sess("alice")
h = health(A)
lazy = ("filetext", "docs", "paperless", "paperless-zipcheck", "embed", "bgjobs")
check(h.get("role") == "web" and not any(k in (h.get("loops") or {}) for k in lazy),
      f"role web: no queue thread (none of {lazy} in the health) {h.get('loops')}")
n0 = len(backups(A)["items"])
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202 and r.json().get("running") == "manual", f"role web: back up now is queued, the state says running {r.text[:120]}")
check(A.post(B + "/api/admin/backups").status_code == 409, "role web: a second one while one waits: busy")
time.sleep(4)
rs = rows()
check(rs and rs[-1][1] == "wait" and rs[-1][3].startswith("v1.") and len(backups(A)["items"]) == n0,
      f"role web: the row waits for the worker (nothing runs here) {[(x[0], x[1]) for x in rs]}")
check((health(A).get("queue") or {}).get("wait") == 1, "role web: the health counts the waiting row")
# two takers at once: two different rows
sql("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at) VALUES('backup', '', 'wait', 0, '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00')")
two = py("""
import json
from kalmido.accounts.bgjobs import bgj_claim
from kalmido.core.db import connect
c1, c2 = connect(), connect()
a, b = bgj_claim(c1), bgj_claim(c2)
c3 = connect()
none = bgj_claim(c3)
out = {"a": a and a["id"], "b": b and b["id"], "third": none and none["id"]}
for c in (c1, c2, c3):
    c.rollback()
print(json.dumps(out))
""")
check(two.get("a") and two.get("b") and two["a"] != two["b"] and two.get("third") is None,
      f"SKIP LOCKED: two takers at once get two different rows, a third none {two}")
sql("DELETE FROM bg_jobs WHERE run_after='2000-01-01T00:00:00+00:00'")
# a run whose process is gone: state run, no beat for long -> the worker takes it again
rid = rows()[-1][0]
sql("UPDATE bg_jobs SET state='run', attempts=1, started_at='2000-01-01T00:00:00+00:00', beat_at='2000-01-01T00:00:00+00:00' WHERE id=?", (rid,))
subprocess.run(["docker", "exec", "-d", "-e", "KALMIDO_WORKER_HEARTBEAT=5", CONT, "python", "app.py", "worker"], check=False)
done = wait_for(lambda: [x for x in rows() if x[0] == rid and x[1] == "done"], 90)
check(done and done[0][2] == 2 and done[0][3] == "", f"a lost run is taken again by the worker and done (runs 2) {rows()}")
check(wait_for(lambda: len(backups(A)["items"]) == n0 + 1, 30), "the worker's backup is listed in the web process")

# review 2.193.0: a lost mail is not sent twice (failed, not again); a kind of another version is not taken (it waits)
sql("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at, started_at, beat_at) VALUES('mail:pwreset', '', 'run', 1, '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00')")
sql("INSERT INTO bg_jobs(kind, payload, state, attempts, run_after, created_at) VALUES('zz:other-version', 'v1.x', 'wait', 0, '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00')")
lost = wait_for(lambda: [x for x in rows("mail:pwreset") if x[1] != "run"], 90)
check(lost and lost[-1][1] == "failed" and lost[-1][2] == 1 and lost[-1][4] == "lost", f"a lost mail run fails instead of a second send {rows('mail:pwreset')}")
time.sleep(5)
other = rows("zz:other-version")
check(other and other[-1][1] == "wait" and other[-1][2] == 0 and other[-1][3] == "v1.x", f"a kind this version does not know waits untouched {other}")

sys.exit(kt.done("p2193_d_api_test"))
