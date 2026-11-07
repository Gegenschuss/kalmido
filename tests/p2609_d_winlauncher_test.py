#!/usr/bin/env python3
# kalmido-suite: after=launcher_ps1 nodata
"""2.609.0 (#3660) the Windows launcher for real: mcp/agent_launcher.ps1 --events against a stub API (no container, no
Kalmido server), with a stand-in for claude that prints stream-json. The CI runs this file on windows-latest (job
"windows-launcher" in .github/workflows/ci.yml, only when mcp/ changed; nightly and by hand always), with PowerShell 7
and Windows PowerShell 5.1; the normal suites run it on Linux / macOS with pwsh (SKIP of the launcher part without one).
 0. ci.yml: the job, its filter (run for real with bash + git in a throwaway repository, not on Windows)
 1. launcher_gone / win_pid_gone without Windows: a stand-in kernel32 (alive, ended, no such process, refused) and the
    nt branch of launcher_gone (pure Python, everywhere)
 2. on Windows: win_pid_gone with the real kernel32 (this process alive, an ended one gone)
 3. the launcher: it starts (PUT /api/v1/agent/status with the host), an event is worked off (the answer is posted), the
    time limit of a run ends the command with its child (taskkill /T on Windows), a pause in Kalmido ends the whole tree (event runner, the command, what the command started), the event waits in the
    runner's queue and runs after the resume, and a launcher killed hard leaves no runner behind (launcher_gone)
Waits are on states (until), never fixed sleeps. Standard library only; tests/kt.py needs time zone data (pip tzdata on Windows)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import check, done, until  # noqa: E402  (tests/kt.py: standard library only)

ROOT = os.path.join(HERE, "..")
PS1 = os.path.join(ROOT, "mcp", "agent_launcher.ps1")
RUNNER = os.path.join(ROOT, "mcp", "agent_run.py")
WIN = os.name == "nt"
TOKEN = "abk_" + "w" * 30
os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN=TOKEN)
spec = importlib.util.spec_from_file_location("agent_run_p2609d", RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


# ---- 0. ci.yml: the Windows job runs only when mcp/ changed, never holds the required check; its filter for real (bash + git)
with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
    ci = f.read()


def ci_job(name):
    m = re.search(r"^  " + re.escape(name) + r":\n((?:    .*\n|\n)+)", ci, re.M)
    return m.group(1) if m else ""


wj, cj, td = ci_job("windows-launcher"), ci_job("windows-launcher-changes"), ci_job("tests-done")
check("runs-on: windows-latest" in wj and "needs: windows-launcher-changes" in wj
      and "if: needs.windows-launcher-changes.outputs.run == 'true'" in wj, "ci.yml: the job windows-launcher on windows-latest, behind the filter")
check("python tests/p2609_d_winlauncher_test.py" in wj and "PWSH: pwsh" in wj and "PWSH: powershell.exe" in wj,
      "ci.yml: this file with PowerShell 7 and Windows PowerShell 5.1")
check("runs-on: ubuntu-latest" in cj and "run: ${{ steps.changed.outputs.run }}" in cj, "ci.yml: the filter job is a small Linux job")
check(re.search(r"needs: tests\n", td) and "windows" not in td, "ci.yml: the required check (tests-done) does not wait for the Windows job")
sm = re.search(r"        run: \|\n((?:          .*\n)+)", cj)
check(sm, "ci.yml: the filter step has a run block")
bash = shutil.which("bash")
if sm and bash and shutil.which("git") and not WIN:
    script = "".join(x[10:] + "\n" for x in sm.group(1).split("\n") if x)
    g = tempfile.mkdtemp(prefix="kalmido-p2609d-git-")
    def gx(*a):
        return subprocess.run(["git", "-C", g, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                              capture_output=True, text=True, check=True).stdout.strip()

    gx("init", "-q")

    def commit(path):
        full = os.path.join(g, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a") as f:
            f.write("x\n")
        gx("add", "-A")
        gx("commit", "-qm", path)
        return gx("rev-parse", "HEAD")

    c0 = commit("README.md")
    c1 = commit("docs/a.md")
    c2 = commit("mcp/agent_run.py")
    c3 = commit("static/x.js")

    def filt(event, sha, before="", base=""):
        out = os.path.join(g, "out.txt")
        open(out, "w").close()
        env = dict(os.environ, EVENT=event, BEFORE=before, BASE=base, GITHUB_SHA=sha, GITHUB_OUTPUT=out)
        r = subprocess.run([bash, "-c", script], cwd=g, env=env, capture_output=True, text=True)
        with open(out) as f:
            return r.returncode, f.read().strip()

    for args, want, what in ((("push", c1, c0), "run=false", "a push without mcp/: skipped"),
                             (("push", c2, c1), "run=true", "a push that changes mcp/: runs"),
                             (("push", c3, c0), "run=true", "a push of several commits, one under mcp/: runs"),
                             (("push", c3, c2), "run=false", "a push after the mcp/ commit: skipped"),
                             (("pull_request", c3, "", c2), "run=false", "a pull request against its base without mcp/: skipped"),
                             (("pull_request", c3, "", c1), "run=true", "a pull request with mcp/: runs"),
                             (("push", c1, "0" * 40), "run=true", "a new branch (before = zeros): runs"),
                             (("push", c1, "f" * 40), "run=true", "a before that is not in the history: runs"),
                             (("schedule", c1, c0), "run=true", "nightly: always"),
                             (("workflow_dispatch", c1, c0), "run=true", "by hand: always")):
        rc, out = filt(*args)
        check(rc == 0 and out == want, f"windows filter: {what} ({rc}, {out!r})")
    shutil.rmtree(g, ignore_errors=True)


# ---- 1. win_pid_gone with a stand-in kernel32, launcher_gone's nt branch
class K32:
    def __init__(self, handle, err=0, ok=True, code=259):
        self.handle, self.err, self.ok, self.code, self.closed, self.opened = handle, err, ok, code, 0, []

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return self.handle

    def get_last_error(self):
        return self.err

    def GetExitCodeProcess(self, h, ref):
        ref._obj.value = self.code
        return self.ok

    def CloseHandle(self, h):
        self.closed += 1


for k, want, what in ((K32(5, code=259), False, "a running process (STILL_ACTIVE)"),
                      (K32(5, code=0), True, "an ended process that a handle keeps listed"),
                      (K32(0, err=87), True, "no process with this number (ERROR_INVALID_PARAMETER)"),
                      (K32(0, err=5), False, "refused: another user's process (ERROR_ACCESS_DENIED) is alive"),
                      (K32(5, ok=False), False, "exit code unreadable: not gone (never end on a guess)")):
    got = ar.win_pid_gone(4242, k32=k)
    check(got is want, f"win_pid_gone: {what} -> {want} (got {got})")
    check(k.opened == [(0x1000, False, 4242)], f"win_pid_gone asks only for a limited query: {k.opened}")
    check(k.closed == (1 if k.handle else 0), f"win_pid_gone closes the handle it opened: {what}")

real_name, real_probe = ar.os.name, ar.win_pid_gone
asked = []
try:
    def probe_gone(pid):  # a stand-in for the Windows probe: notes the number it was asked for and says "gone"
        asked.append(pid)
        return True
    ar.win_pid_gone = probe_gone
    ar.os.name = "nt"
    os.environ["KALMIDO_LAUNCHER_PID"] = "4711"
    check(ar.launcher_gone() is True and asked == [4711], f"launcher_gone on Windows asks win_pid_gone (was: always False): {asked}")

    def broken(pid):
        raise OSError("no kernel32")
    ar.win_pid_gone = broken
    check(ar.launcher_gone() is False, "launcher_gone on Windows: a failing probe never ends the runner")
    os.environ["KALMIDO_LAUNCHER_PID"] = "x"
    check(ar.launcher_gone() is False, "launcher_gone on Windows: not a number -> not gone")
finally:
    ar.os.name, ar.win_pid_gone = real_name, real_probe
    os.environ.pop("KALMIDO_LAUNCHER_PID", None)

# ---- 2. the real kernel32 (Windows only)
if WIN:
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    check(ar.win_pid_gone(os.getpid()) is False, "win_pid_gone: this process is alive")
    check(ar.win_pid_gone(dead.pid) is True, f"win_pid_gone: an ended process is gone ({dead.pid})")
    os.environ["KALMIDO_LAUNCHER_PID"] = str(os.getpid())
    check(ar.launcher_gone() is False, "launcher_gone on Windows: launcher alive")
    os.environ["KALMIDO_LAUNCHER_PID"] = str(dead.pid)
    check(ar.launcher_gone() is True, "launcher_gone on Windows: launcher gone")
    os.environ.pop("KALMIDO_LAUNCHER_PID", None)


def pid_alive(pid):
    if not pid:
        return False
    if WIN:
        return not ar.win_pid_gone(int(pid))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:  # a zombie of a child of ours counts as gone
        return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:1] not in ("Z", "")
    except OSError:
        return True


# ---- 3. the launcher with a stub API
PWSH = os.environ.get("PWSH") or shutil.which("pwsh") or (shutil.which("powershell") if WIN else None)
if not PWSH:
    print("p2609_d_winlauncher: launcher part SKIP (no pwsh)")
    sys.exit(done("p2609_d_winlauncher"))

ST = {"enabled": True, "events": [], "status": [], "posts": [], "lock": threading.Lock()}


def chat_event(seq, body):
    return {"event": "chat", "seq": seq, "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": seq, "body": body}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self.reply(401, {"error": "token"})
        path, _, q = self.path.partition("?")
        if path == "/api/v1/agent":
            if not ST["enabled"]:
                return self.reply(403, {"error": "paused"})
            return self.reply(200, {"id": 9, "owner_id": 7, "enabled": True, "status": "idle", "events_cursor": 0,
                                    "runtime": {"model": "", "autocompact": True, "reset_seq": 0, "timezone": "UTC"}})
        if path == "/api/v1/agent/events":
            since = int(dict(x.partition("=")[::2] for x in q.split("&") if x).get("since") or 0)
            end = time.time() + 1
            while True:
                with ST["lock"]:
                    evs = [e for e in ST["events"] if e["seq"] > since]
                if evs or time.time() > end:
                    break
                time.sleep(0.1)
            return self.reply(200, {"data": evs, "cursor": max([since] + [e["seq"] for e in evs])})
        return self.reply(200, {})

    def do_PUT(self):
        b = self.body()
        if self.path == "/api/v1/agent/status":
            ST["status"].append(b)
        return self.reply(200, {})

    def do_POST(self):
        b = self.body()
        if self.path.startswith("/api/v1/agent/chats/"):
            ST["posts"].append({"path": self.path, "body": b.get("body") or "", "kind": b.get("kind") or ""})
            return self.reply(200, {"id": 100 + len(ST["posts"])})
        return self.reply(200, {})

    do_PATCH = do_DELETE = do_POST


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"

tmp = tempfile.mkdtemp(prefix="kalmido-p2609d-")
runs = os.path.join(tmp, "runs.jsonl")
hang = os.path.join(tmp, "hang.on")
fake = os.path.join(tmp, "fake_claude.py")
# the stand-in for claude: one line per run (its pid and parent = the event runner), a "hang" event starts a child and waits
# while hang.on exists (the pause must end both); else stream-json like Claude Code with the event's text in the answer
with open(fake, "w") as f:
    f.write(r'''import json, os, subprocess, sys, time
args, prompt = sys.argv[1:], sys.stdin.read()
rec = {"pid": os.getpid(), "ppid": os.getppid(), "hang": "please hang" in prompt, "stall": "please stall" in prompt}
if (rec["hang"] and os.path.exists(os.environ["FAKE_HANG"])) or rec["stall"]:
    c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    rec["child"] = c.pid
with open(os.environ["FAKE_RUNS"], "a") as f:
    f.write(json.dumps(rec) + "\n")
if rec["stall"]:  # until the runner's time limit ends it with its child
    time.sleep(600)
while rec.get("child") and os.path.exists(os.environ["FAKE_HANG"]):
    time.sleep(0.2)
word = "please hang" if rec["hang"] else ("hello one" if "hello one" in prompt else "?")
final = "Done: " + word
sid = args[args.index("--resume") + 1] if "--resume" in args else "S-%d" % os.getpid()
print(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5", "session_id": sid}), flush=True)
print(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 100}, "content": [{"type": "text", "text": final}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": sid}), flush=True)
''')
envf = os.path.join(tmp, "agent.env")
state = os.path.join(tmp, "state")
with open(envf, "w") as f:
    f.write(f"KALMIDO_URL={URL}\nKALMIDO_TOKEN={TOKEN}\nKALMIDO_POLL=1\nKALMIDO_RESTART_DELAY=1\nKALMIDO_HOST=winci\nKALMIDO_RUN_TIMEOUT=60\n"
            f"KALMIDO_STATE_DIR={state}\nKALMIDO_PYTHON={sys.executable}\nKALMIDO_AGENT_PROFILE=claude\n"
            f"KALMIDO_RUN_LOG={os.path.join(tmp, 'agent_run.log')}\nFAKE_RUNS={runs}\nFAKE_HANG={hang}\n")
logf = open(os.path.join(tmp, "launcher.log"), "w")


def start():
    # the command is the stand-in through the plain Python (a wrapper: KALMIDO_AGENT_PROFILE=claude in the env file)
    return subprocess.Popen([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", PS1, "-e", envf,
                             "--events", "--", sys.executable, fake], stdout=logf, stderr=subprocess.STDOUT, cwd=tmp)


def records():
    try:
        with open(runs) as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def answered(word):
    return [p for p in ST["posts"] if ("Done: " + word) in p["body"]]


def logs():
    out = []
    for n in ("launcher.log", "agent_run.log"):
        try:
            with open(os.path.join(tmp, n), errors="replace") as f:
                out.append(f"--- {n}\n" + f.read()[-3000:])
        except OSError:
            pass
    return "\n".join(out)


launcher = start()
left = []
try:
    # start: the host is reported, the event runner is up (its first GET /api/v1/agent/events)
    check(until(lambda: any(s.get("host") == "winci" for s in ST["status"]), 90),
          f"the launcher starts and reports its host: {ST['status'][:3]}\n{logs()}")
    # one event is worked off: the stand-in runs once, its answer is posted into the chat
    with ST["lock"]:
        ST["events"].append(chat_event(1, "hello one"))
    check(until(lambda: answered("hello one"), 120), f"an event is worked off, the answer is posted: {ST['posts'][-3:]}\n{logs()}")
    r1 = records()
    runner_pid = r1[0]["ppid"] if r1 else None
    check(pid_alive(runner_pid), f"the event runner is alive after the run ({runner_pid})")

    # the time limit of a run (KALMIDO_RUN_TIMEOUT, 60 s: above the up to ~32 s a pause needs on Windows, see below) ends
    # the command with its child (taskkill /T /F on Windows) and says so in the chat; the runner goes on
    with ST["lock"]:
        ST["events"].append(chat_event(2, "please stall"))
    check(until(lambda: any(r.get("stall") for r in records()), 120), f"the stalling run is there\n{logs()}")
    sr = [r for r in records() if r.get("stall")][0]
    left += [sr["pid"], sr["child"]]
    check(until(lambda: not pid_alive(sr["pid"]) and not pid_alive(sr["child"]), 150),
          f"the time limit ends the command and its child: {[(p, pid_alive(p)) for p in (sr['pid'], sr['child'])]}\n{logs()}")
    check(until(lambda: [p for p in ST["posts"] if "time limit" in p["body"]], 60), f"the chat hears of the time limit: {ST['posts'][-3:]}")
    check(pid_alive(runner_pid), "the runner itself goes on after a time limit")

    # a pause in Kalmido during a run ends the tree: the runner, the command, the command's child
    open(hang, "w").close()
    with ST["lock"]:
        ST["events"].append(chat_event(3, "please hang"))
    check(until(lambda: any(r.get("child") for r in records()), 120), f"the hanging run is there\n{logs()}")
    hr = [r for r in records() if r.get("child")][0]
    left += [hr["pid"], hr["child"], hr["ppid"]]
    check(hr["ppid"] == runner_pid, f"the run is a child of the same runner ({hr['ppid']} vs {runner_pid})")
    ST["enabled"] = False
    tree = (hr["ppid"], hr["pid"], hr["child"])
    check(until(lambda: not any(pid_alive(p) for p in tree), 120),
          f"the pause ends the whole tree: {[(p, pid_alive(p)) for p in tree]}\n{logs()}")
    check(launcher.poll() is None, "the launcher itself stays (waiting for the resume)")
    check(not answered("please hang"), "the stopped run posted nothing")

    # resume: a new runner takes the event from its queue on disk and answers it
    os.remove(hang)
    ST["enabled"] = True
    check(until(lambda: answered("please hang"), 120), f"after the resume the waiting event is answered: {ST['posts'][-3:]}\n{logs()}")
    r2 = [r for r in records() if r["hang"] and not r.get("child")]
    runner2 = r2[-1]["ppid"] if r2 else None
    check(runner2 and runner2 != runner_pid and pid_alive(runner2), f"a new runner after the resume ({runner2})")
    left.append(runner2)

    # the launcher killed hard (task manager / an ended scheduled task: no finally): its runner ends by itself
    launcher.kill()
    launcher.wait(30)
    check(until(lambda: not pid_alive(runner2), 180), f"a launcher killed hard leaves no runner behind (launcher_gone)\n{logs()}")
    check("the launcher that started this runner is gone" in logs(), "the runner says why it ended")
finally:
    if launcher.poll() is None:
        launcher.kill()
    for p in left:
        if p and pid_alive(p):
            try:
                if WIN:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p)], capture_output=True)
                else:
                    os.kill(int(p), 9)
            except OSError:
                pass
    srv.shutdown()
    logf.close()

sys.exit(done("p2609_d_winlauncher"))
