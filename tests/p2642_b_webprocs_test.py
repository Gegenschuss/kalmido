#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.642.0 part B (#4975): KALMIDO_WEB_PROCS=2 -- two web processes of one container on the same port (SO_REUSEPORT).
"A second process" in the parts below = `docker exec ... python` in the test container (its own Python process on the same
database, like p2622_b_procstate). Invented names only.
 - setup code: the first web process prints ONE code, its hash is in settings; requests to both processes print no second
   one; another process accepts the printed code; the first account deletes the hash
 - both processes answer on the same port (proc index 0 and 1 in /api/admin/health), threads and pool shared out
   (24 threads -> 12 + 12, pool 12 + 16 and 12 + 8); only process 0 runs background loops, process 1 has the role web;
   a restore is refused (WRK_SINGLE false); the signals are on without KALMIDO_PGBUS; a killed process 1 is started again
 - busy lock across processes: while one process holds a calendar subscription's sync, cal_sync of another process says
   "already syncing" and leaves the row alone; after the release it syncs
 - hour limits across processes: uploads per person (upr_guard), form bytes (h6d_form_bytes), browser error reports per
   person (cer_rate_ok): what one process counted, the next process sees
 - an agent's long-poll wakes for an event of another process (the bus is on by KALMIDO_WEB_PROCS alone)
usage: p2642_b_webprocs_test.py <datadir>      (a fresh container; P2642B_NOSTART=1 = the server already runs that way)"""
import os
import re
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, H, check, dbx  # noqa: E402

os.environ["KALMIDO_SETUP_CODE"] = ""  # start.sh: an empty value = the code check on (default off in the suites)
kt.fresh({"KALMIDO_WEB_PROCS": "2"}, prefix="P2642B")
kt.docker_logs_on_first_fail()

PRE = "import app\nfrom kalmido.core.db import connect, db\nfrom kalmido.core.config import app as fa\nc = connect()\n"


def box(code, commit=True):
    """Python in another process of the container (the same database)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", PRE + code + ("\nc.commit()" if commit else "\nc.rollback()") + "\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def logs():
    out = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return out.stdout + out.stderr


# ================================================================== setup code across processes
CODE_RE = re.compile(r"Setup code: ([a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})")
codes = kt.until(lambda: CODE_RE.findall(logs()), timeout=20)
check(len(codes) == 1, f"#4975: the first web process prints one setup code {len(codes)}")
CODE = codes[0] if codes else ""
check(bool(dbx("SELECT 1 FROM settings WHERE key='setup_code_start_hash' AND value <> ''")), "#4975: the code's hash is in settings")
check(not dbx("SELECT 1 FROM settings WHERE value LIKE ?", ("%" + CODE.replace("-", "") + "%",)), "#4975: the code itself is not stored")
for _ in range(16):  # fresh connections: the kernel spreads them over both processes, each asks sh_code_ensure
    requests.get(B + "/api/auth/info", headers=H)
check(len(CODE_RE.findall(logs())) == 1, "#4975: the second process prints no code of its own")
chk = "from kalmido.accounts.setupcode import sh_code_check\nwith fa.test_request_context('/'):\n    print('check', repr(sh_code_check(c, {0!r})))"
out = box(chk.format(CODE), commit=False)
check("check None" in out, "#4975: another process accepts the printed code " + out[-200:])
out = box(chk.format("zzzz-zzzz-zzzz"), commit=False)
check("check (" in out and "403" in out, "#4975: and refuses a wrong one " + out[-200:])
s0 = requests.Session()
s0.headers.update(H)
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": kt.PASSWORD, "setup_code": CODE})
check(r.ok, f"#4975: the first account with the printed code {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM settings WHERE key='setup_code_start_hash'"), "#4975: the code's hash goes with the first account")
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})

# ================================================================== two processes on one port
def health():
    try:
        r = requests.get(B + "/api/admin/health", headers=H, cookies=A.cookies, timeout=30)  # a new connection each time
    except requests.ConnectionError:  # a connection queued at a process killed on purpose goes with it: not there (yet)
        return {}
    return r.json() if r.ok else {}


seen = {}


def both():
    j = health()
    p = j.get("proc") or {}
    if "index" in p:
        seen[p["index"]] = j
    return len(seen) == 2


check(kt.until(both, timeout=30, step=0.1), f"#4975: both web processes answer on the same port {sorted(seen)}")
p0, p1 = seen.get(0, {}), seen.get(1, {})
check(p0.get("proc", {}).get("of") == 2 and p1.get("proc", {}).get("of") == 2 and p0["proc"]["pid"] != p1["proc"]["pid"],
      f"#4975: two processes of two {p0.get('proc')} {p1.get('proc')}")
check(p0.get("threads", {}).get("configured") == 12 and p1.get("threads", {}).get("configured") == 12,
      f"#4975: 24 threads shared out 12 + 12 {p0.get('threads')} {p1.get('threads')}")
check(p0.get("pool", {}).get("max") == 28 and p1.get("pool", {}).get("max") == 20,
      f"#4975: pool 12 + 16 (background work) and 12 + 8 {p0.get('pool', {}).get('max')} {p1.get('pool', {}).get('max')}")
check(p0.get("role") == "all" and p1.get("role") == "web", f"#4975: roles all / web {p0.get('role')} {p1.get('role')}")
run0 = [k for k, v in (p0.get("loops") or {}).items() if v == "running"]
run1 = [k for k, v in (p1.get("loops") or {}).items() if v == "running"]
check(bool(run0) and not run1, f"#4975: background loops only in process 0 {run0} / {run1}")
check((p0.get("connections") or {}).get("web_procs") == 2, f"#4975: the connection check counts both {p0.get('connections')}")
out = box("from kalmido.admin.worker import WRK_SINGLE\nfrom kalmido.core.pgbus import bus_active\nprint('single', WRK_SINGLE, 'bus', bus_active())")
check("single False bus True" in out, "#4975: no restore with two web processes; the signals are on " + out[-200:])

# a process 1 that ends is started again by process 0
old = p1.get("proc", {}).get("pid")
k = subprocess.run(["docker", "exec", CT, "python", "-c", f"import os, signal; os.kill({int(old or 0)}, signal.SIGKILL); print('killed')"],
                   capture_output=True, text=True)
check("killed" in k.stdout, "setup: process 1 killed " + (k.stdout + k.stderr)[-200:])


def back():
    j = health()
    p = j.get("proc") or {}
    return p.get("index") == 1 and p.get("pid") != old


check(kt.until(back, timeout=40, step=0.2), "#4975: process 0 starts an ended process 1 again")

# ================================================================== busy lock across processes (calendar sync)
aid = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
sid = dbx("INSERT INTO cal_subs(user_id, kind, url, interval, tried_at, created_at) VALUES(?, 'ics', 'x', 60, ?, ?) RETURNING id",
          (aid, now, now))[0][0]
hold = subprocess.Popen(["docker", "exec", "-i", CT, "python", "-c", PRE + "import sys\nfrom kalmido.core.ephem import eph_busy_take\n"
                         f"print('taken', eph_busy_take('calsub:{sid}'), flush=True)\nsys.stdin.readline()\n"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
line = ""
end = time.monotonic() + 30
while time.monotonic() < end and "taken" not in line:
    line = hold.stdout.readline() or line
    if hold.poll() is not None and "taken" not in line:
        break
check("taken True" in line, "setup: another process holds the subscription's sync " + line[-200:])
sync = f"from kalmido.calendars.subscriptions import cal_sync\nfrom kalmido.core.pg import system_ctx\nwith system_ctx(c):\n    print('sync', cal_sync(c, {sid}))"
out = box(sync)
row = dbx("SELECT tried_at FROM cal_subs WHERE id=?", (sid,))
check("sync False" in out and row and row[0][0] == now, f"#4975: a second sync of another process waits it out {out[-200:]} {row}")
hold.stdin.write("\n")
hold.stdin.flush()
hold.wait(30)
out = box(sync)
row = dbx("SELECT tried_at FROM cal_subs WHERE id=?", (sid,))
check("sync True" in out and row and row[0][0] != now, f"#4975: after the release it syncs {out[-200:]} {row}")
out = box("from kalmido.core.ephem import eph_busy_take, eph_busy_give\n"
          "a = eph_busy_take('p2642:x')\nb = eph_busy_take('p2642:x')\neph_busy_give('p2642:x')\nprint('twice', a, b, eph_busy_take('p2642:x'))")
check("twice True False True" in out, "#4975: two threads of one process: the second one is busy too " + out[-200:])

# ================================================================== hour limits across processes
up = ("import kalmido.admin.hosting as HO\nfrom kalmido.core.errors import Denied\nHO.UPLOAD_HOURLY_MB = 1\n"
      f"with fa.test_request_context('/', method='POST', data=b'x' * 700000):\n"
      f"    try:\n        HO.upr_guard({aid})\n        print('upload ok')\n    except Denied as e:\n        print('upload refused', e.args)")
out1, out2 = box(up), box(up)
check("upload ok" in out1 and "upload refused" in out2, f"#4975: the uploads of one hour count over the processes {out1[-120:]} / {out2[-120:]}")
frm = "import kalmido.team.forms as F\nF.FRM_BYTES_HOUR = 1000\nprint('form refused', F.h6d_form_bytes(987654, {0}))"
out1, out2 = box(frm.format(800)), box(frm.format(300))
check("form refused False" in out1 and "form refused True" in out2, f"#4975: the form bytes of one hour count over the processes {out1[-80:]} / {out2[-80:]}")
cer = "import kalmido.integrations.errorreports as E\nE.CER_PER_HOUR = 3\nprint('cer', [E.cer_rate_ok({0}) for _ in range({1})])"
out1, out2 = box(cer.format(aid, 3)), box(cer.format(aid, 1))
check("cer [True, True, True]" in out1 and "cer [False]" in out2, f"#4975: the error reports of one hour count over the processes {out1[-80:]} / {out2[-80:]}")

# ================================================================== an agent's long-poll hears another process
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "robo2642", "display_name": "Robo"})
assert r.ok, r.text
AID, ATOK = r.json()["id"], r.json()["token"]
ag = requests.Session()
ag.headers.update({"Authorization": "Bearer " + ATOK, **H})
cur = ag.get(B + "/api/v1/agent/events", params={"since": "latest"}).json()["cursor"]
res = {}


def poll():
    t = time.time()
    rr = requests.get(B + "/api/v1/agent/events", params={"since": cur, "wait": 20}, headers=ag.headers)
    res["r"] = (rr, time.time() - t)
    res["end"] = time.monotonic()


th = threading.Thread(target=poll)
th.start()
check(kt.until(lambda: any((health().get("threads") or {}).get("busy", 0) >= 2 for _ in range(4)), timeout=10),
      "setup: the agent's long-poll waits in one of the processes")
out = box("from kalmido.agents.core import agent_emit\n"
          f"print('seq', agent_emit(c, {AID}, 'nudge', {{'text': 'p2642'}}, actor=None))")
emitted = time.monotonic()  # the other process has committed its event and ended
th.join(25)
rr, dt = res.get("r", (None, 99))
# 2.766.0 (#5323, CI red of 2.756 / 2.759 at 8.1 s): dt from the start of the poll also holds the setup wait and the other
# process' start (docker exec + imports, slow on the CI runner) - the wake itself is the time after that process ended; without a
# wake the poll waits its full 20 s (no recheck), so the server's own "waited" below 20 is the proof it woke
lag = res.get("end", emitted + 99) - emitted
waited = (rr.json().get("waited", 99) if rr is not None and rr.ok else 99)
check("seq " in out and rr is not None and rr.ok and rr.json()["data"] and lag < 5 and waited < 18,
      f"#4975: the long-poll wakes for an event of another process ({lag:.1f}s after it, waited {waited}s of 20, all {dt:.1f}s) {out[-200:]}")
sys.exit(kt.done("p2642_b_webprocs"))
