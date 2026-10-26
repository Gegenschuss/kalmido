#!/usr/bin/env python3
"""2.236.0 C (#2905) the reference starters keep the work window of the work style, against a stub API (no container):
 - mcp/agent_run.py work_window_open: work_mode always = open; office = only from-to on the work days in the instance's
   time zone (over midnight too); without a usable time zone the server's state of the last read
 - the runner (Runner.work_closed): closed -> status paused with the time it goes on (read once from the server), open
   again -> idle; one status per change; the event work_style_changed updates the work style without a run
 - agent_launcher.sh (and agent_launcher.ps1 when pwsh is there): work_style.state.working false -> no session starts (the
   launcher keeps polling), the log names the time; working true -> the agent starts
usage: p2236_c_launcher_test.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from kt import check, done, until  # 2.206.0 B (#2762): shared helpers (tests/kt.py)

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(HERE, "..", "mcp")
spec = importlib.util.spec_from_file_location("agent_run", os.path.join(MCP, "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)

# ---------------------------------------------------------------- the window itself
BER = ZoneInfo("Europe/Berlin")


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=BER).timestamp()


OFFICE = {"work_mode": "office", "work_from": "08:00", "work_to": "18:00", "work_days": [1, 2, 3, 4, 5],
          "state": {"timezone": "Europe/Berlin", "working": True}}
check(ar.work_window_open({"work_mode": "always"}) and ar.work_window_open(None) and ar.work_window_open({}), "always / none: open")
check(ar.work_window_open(OFFICE, at(2026, 10, 26, 9, 0)), "Monday 09:00 inside 08-18")
check(not ar.work_window_open(OFFICE, at(2026, 10, 26, 18, 0)), "Monday 18:00: closed (the end is outside)")
check(not ar.work_window_open(OFFICE, at(2026, 10, 26, 7, 59)), "Monday 07:59: closed")
check(not ar.work_window_open(OFFICE, at(2026, 10, 25, 10, 0)), "Sunday 10:00: closed (no work day)")
NIGHT = {**OFFICE, "work_from": "22:00", "work_to": "06:00", "work_days": [1, 2, 3, 4, 5, 6, 7]}
check(ar.work_window_open(NIGHT, at(2026, 10, 26, 23, 0)) and ar.work_window_open(NIGHT, at(2026, 10, 27, 5, 59))
      and not ar.work_window_open(NIGHT, at(2026, 10, 26, 12, 0)), "a window over midnight")
check(not ar.work_window_open({**OFFICE, "state": {"timezone": "No/Such_Zone", "working": False}}),
      "an unknown time zone: the server's state (closed)")

# ---------------------------------------------------------------- the runner: status per change, the event
calls = []
ws_closed = {**OFFICE, "work_days": [], "state": {"timezone": "Europe/Berlin", "working": False,
                                                  "work_resumes_at": "2026-10-26T07:00:00+00:00"}}
fake = SimpleNamespace(agent={"work_style": ws_closed}, api=SimpleNamespace(status=lambda *a: calls.append(a)),
                       refresh_agent=lambda: calls.append(("refresh",)))
check(ar.Runner.work_closed(fake) is True, "closed: the runner holds the queue")
check(("refresh",) in calls and any(c[0] == "paused" and "Outside working hours, back Mon 08:00" in c[1] for c in calls if len(c) > 1),
      f"closed: status paused with the local time it goes on: {calls}")
n = len(calls)
check(ar.Runner.work_closed(fake) is True and len(calls) == n, "still closed: no second status")
fake.agent["work_style"] = {"work_mode": "always"}
check(ar.Runner.work_closed(fake) is False and calls[-1] == ("idle",), f"open again: idle {calls[-1:]}")

r = ar.Runner.__new__(ar.Runner)
r.state = SimpleNamespace(lock=threading.Lock(), data={"expired": [], "approvals": {}}, remember=lambda *a: None, save=lambda: None)
r.agent, r.extras = {"work_style": {"work_mode": "always"}}, None
try:
    out = r.groups([{"event": "work_style_changed", "seq": 1, "data": {"work_style": OFFICE}}])
    check(out == [] and r.agent["work_style"] == OFFICE, f"work_style_changed: read at once, no run ({out})")
except Exception as e:  # a changed groups() signature must not hide the check
    check(False, f"groups(work_style_changed): {type(e).__name__}: {e}")

# ---------------------------------------------------------------- the launchers against a stub API
TOKEN = "abk_secret_test_token_2236"
STATE = {"working": False, "polls": 0}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path != "/api/v1/agent":
            self.send_response(404)
            self.end_headers()
            return
        STATE["polls"] += 1
        st = {"working": STATE["working"], "work_resumes_at": None if STATE["working"] else "2026-10-26T07:00:00+00:00", "timezone": "UTC"}
        body = json.dumps({"id": 9, "enabled": True, "runtime": {"reset_seq": 0, "timezone": "UTC"},
                           "work_style": {"work_mode": "office", "state": st}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp(prefix="kalmido-p2236c-")
envf = os.path.join(tmp, "agent.env")
with open(envf, "w") as f:
    f.write(f"KALMIDO_URL=http://127.0.0.1:{srv.server_address[1]}\nKALMIDO_TOKEN={TOKEN}\nKALMIDO_POLL=1\nKALMIDO_RESTART_DELAY=1\n")
log = os.path.join(tmp, "starts.log")
agent = os.path.join(tmp, "fakeagent")
with open(agent, "w") as f:
    f.write(f"#!/usr/bin/env python3\nimport time\nopen({log!r}, 'a').write('start\\n')\ntime.sleep(600)\n")
os.chmod(agent, 0o755)


def starts():
    try:
        return len(open(log).read().split())
    except FileNotFoundError:
        return 0


launchers = [("sh", ["bash", os.path.join(MCP, "agent_launcher.sh")])]
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
if PWSH:
    launchers.append(("ps1", [PWSH, "-NoProfile", "-NonInteractive", "-File", os.path.join(MCP, "agent_launcher.ps1")]))
else:
    print("p2236_c_launcher: ps1 part SKIP (no pwsh)")
for name, cmd in launchers:
    if os.path.exists(log):
        os.remove(log)
    STATE.update(working=False, polls=0)
    errf = open(os.path.join(tmp, f"{name}.err"), "w+")
    p = subprocess.Popen(cmd + ["-e", envf, "--", agent], stdout=subprocess.DEVNULL, stderr=errf, text=True)
    try:
        check(until(lambda: STATE["polls"] >= 4, 60), f"{name}: the launcher keeps polling outside the work window")
        check(starts() == 0, f"{name}: outside the work window no session starts")
        STATE["working"] = True
        check(until(lambda: starts() == 1, 60), f"{name}: the window opens -> the agent starts")
    finally:
        p.terminate()
        try:
            p.wait(timeout=40)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        errf.seek(0)
        err = errf.read()
        errf.close()
        subprocess.run(["pkill", "-f", "python3 " + agent])
    check("outside the work window of its work style: no new session until 2026-10-26" in err and "work window open again" in err,
          f"{name}: the log names the closed window and its end: {err[-400:]}")
    check(TOKEN not in err, f"{name}: the token is never in the log")
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
sys.exit(done("p2236_c_launcher"))
