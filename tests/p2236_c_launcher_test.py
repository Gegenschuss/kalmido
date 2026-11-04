#!/usr/bin/env python3
"""2.236.0 C (#2905) the reference starters keep the work window of the work style, against a stub API (no container):
 - mcp/agent_run.py work_window_open: work_mode always = open; office = only from-to on the work days in the instance's
   time zone (over midnight too); without a usable time zone the server's state of the last read
 - the runner (Runner.work_closed): closed -> status paused with the time it goes on (read once from the server), open
   again -> idle; one status per change; the event work_style_changed updates the work style without a run
 - agent_launcher.sh (and agent_launcher.ps1 when pwsh is there): work_style.state.working false -> no session starts (the
   launcher keeps polling), the log names the time; working true -> the agent starts
 - 2.503.0 (#4309) a pause with a reason (status paused, no status_key): the runner starts no run, keeps the events in its queue,
   sends no status (working / idle would overwrite the reason), a pause during a run holds the next group, a bundle goes back to
   the queue; resume: the events run once. The runner's own pauses (status_key set) and a server without the key never hold. The
   launchers do not report "idle" at their start during such a pause.
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
# #1604: the runner checks below use the real clock (time.time()); pin "empty work_days = closed" at a fixed Monday 09:00 too
check(not ar.work_window_open({**OFFICE, "work_days": []}, at(2026, 10, 26, 9, 0)), "no work days: closed, also Monday 09:00")
check(not ar.work_window_open({**OFFICE, "state": {"timezone": "No/Such_Zone", "working": False}}),
      "an unknown time zone: the server's state (closed)")

# ---------------------------------------------------------------- the runner: status per change, the event
calls = []
ws_closed = {**OFFICE, "work_days": [], "state": {"timezone": "Europe/Berlin", "working": False,
                                                  "work_resumes_at": "2026-10-26T07:00:00+00:00"}}
fake = SimpleNamespace(agent={"work_style": ws_closed}, api=SimpleNamespace(status=lambda *a, **k: calls.append(a)),
                       refresh_agent=lambda: calls.append(("refresh",)))
fake.say = lambda *a: ar.Runner.say(fake, *a)
fake.status_say = lambda *a, **k: ar.Runner.status_say(fake, *a, **k)
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

# ---------------------------------------------------------------- 2.503.0 (#4309): a pause with a reason holds the runner
os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "h" * 30)
AG = {"status": "idle", "status_key": ""}
PUTS, RUNS = [], []
hold_dir = tempfile.mkdtemp(prefix="kalmido-p4309-")


def hold_req(method, path, body=None, **_k):
    if method == "PUT":
        PUTS.append(body)
        return {}
    if path == "/agent":
        if AG.get("fail"):
            raise OSError("not reachable")
        return {"owner_id": 7, "runtime": {"reset_seq": 0}, "events_cursor": 1, **{k: v for k, v in AG.items() if k != "fail"}}
    if path == "/agent/events":
        import time
        time.sleep(0.1)
        return {"data": [], "cursor": 1}
    return {}


def hold_runner(name):
    h = ar.Runner(["true"], os.path.join(hold_dir, name))
    h.extras = None
    h.api.req = hold_req
    h.run = lambda uid, group: RUNS.append(sorted(e["seq"] for e in group))
    return h


def hold_chat(seq, uid):
    return {"event": "chat", "seq": seq, "data": {"user": {"id": uid, "name": "Ann"}, "message": {"id": seq, "body": "hello"}}}


h = hold_runner("a")
check(h.held() is False, "idle: not held")
AG.update(status="paused", status_key="status_plan_limit")
check(h.held() is False, "the runner's own pause (status_key set): not held")
AG.pop("status_key")
check(h.held() is False, "a server without status_key cannot tell them apart: never held")
AG.update(status="paused", status_key="")
check(h.held() is True, "paused with a reason: held")
AG["fail"] = True
check(h.held() is True, "the check fails: what was known stays")
AG.pop("fail")
h.api.status("working", "busy")
h.api.status("idle")
h.status_say("paused", "status_plan_limit")
check(PUTS == [], f"held: no status goes out, the reason stays {PUTS}")
kept = h.handle([hold_chat(11, 7)], save=True)
check(RUNS == [] and [e["seq"] for e in kept] == [11], f"held: no run, the event is kept {RUNS} {kept}")
AG.update(status="idle", status_key="")
h.api.status("working", "busy")
check([b["status"] for b in PUTS] == ["working"], f"resumed: the status goes out again {PUTS}")

h = hold_runner("b")
PUTS.clear()
RUNS.clear()


def pause_during(uid, group):
    RUNS.append(sorted(e["seq"] for e in group))
    AG.update(status="paused", status_key="")


h.run = pause_during
kept = h.handle([hold_chat(21, 7), hold_chat(22, 8), hold_chat(23, 9)], save=True)
check(RUNS == [[21]] and [e["seq"] for e in kept] == [22, 23], f"a pause during a run holds the next groups {RUNS} {kept}")
h = hold_runner("c")
inner = [{"event": "task_updated", "seq": 31, "data": {}}, {"event": "task_updated", "seq": 32, "data": {}}]
check([e["seq"] for e in h.handle([{"event": "task_bundle", "seq": 32, "data": {"events": inner}}], save=True)] == [31, 32]
      and [e["seq"] for e in h.state.data["queue"]] == [31, 32], f"a held bundle: its events go back to the queue {h.state.data['queue']}")

ar.HOLD_POLL_S = 0.1
h = hold_runner("d")
RUNS.clear()
with h.state.lock:
    h.state.data["queue"].append(hold_chat(41, 7))
threading.Thread(target=h.loop, daemon=True).start()
check(until(lambda: h.was_held, 30), "the loop: the pause is seen")
check(RUNS == [] and [e["seq"] for e in h.state.data["queue"]] == [41], f"the loop: paused, the event stays in the queue {RUNS}")
AG.update(status="idle", status_key="")
check(until(lambda: RUNS == [[41]] and not h.state.data["queue"], 30), f"the loop: resumed, the event runs once and leaves the queue {RUNS}")


class BundleExtras:  # review: a task event of the batch goes straight into a bundle that is due
    def __init__(self):
        self.pending = []

    def intake(self, evs):
        self.pending += [e for e in evs if e["event"] != "chat"]
        return [e for e in evs if e["event"] == "chat"]

    def due(self):
        return bool(self.pending)

    def take_bundle(self):
        evs, self.pending = self.pending, []
        return [{"event": "task_bundle", "seq": max(e["seq"] for e in evs), "data": {"events": evs}}]


h = hold_runner("e")
h.extras = BundleExtras()
RUNS.clear()


def pause_once(uid, group):
    RUNS.append(sorted(e["seq"] for e in group))
    if len(RUNS) == 1:
        AG.update(status="paused", status_key="")


h.run = pause_once
with h.state.lock:
    h.state.data["queue"] += [hold_chat(51, 7), {"event": "task_updated", "seq": 52, "data": {}}]
threading.Thread(target=h.loop, daemon=True).start()
check(until(lambda: RUNS == [[51]] and [e["seq"] for e in h.state.data["queue"]] == [52], 30),
      f"a pause during the run: the task event of the same batch stays in the queue {RUNS} {h.state.data['queue']}")
AG.update(status="idle", status_key="")
check(until(lambda: RUNS == [[51], [52]] and not h.state.data["queue"], 30), f"resumed: the bundle runs {RUNS}")
shutil.rmtree(hold_dir, ignore_errors=True)

# ---------------------------------------------------------------- the launchers against a stub API
TOKEN = "abk_secret_test_token_2236"
STATE = {"working": False, "polls": 0, "paused": False, "puts": 0}


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
        body = json.dumps({"id": 9, "enabled": True, "status": "paused" if STATE["paused"] else "idle", "status_key": "", "runtime": {"reset_seq": 0, "timezone": "UTC"},
                           "work_style": {"work_mode": "office", "state": st}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        STATE["puts"] += 1
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
        check(STATE["puts"] >= 1, f"{name}: without a pause the launcher reports its host (status idle)")
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
    # 2.503.0 (#4309): the report at the start says idle and would end a pause with a reason
    STATE.update(working=True, polls=0, paused=True, puts=0)
    p = subprocess.Popen(cmd + ["-e", envf, "--", agent], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    try:
        check(until(lambda: STATE["polls"] >= 3, 60) and STATE["puts"] == 0, f"{name}: a pause with a reason: no status from the start of the launcher ({STATE['puts']})")
    finally:
        p.terminate()
        try:
            p.wait(timeout=40)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        subprocess.run(["pkill", "-f", "python3 " + agent])
    STATE.update(paused=False)
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
sys.exit(done("p2236_c_launcher"))
