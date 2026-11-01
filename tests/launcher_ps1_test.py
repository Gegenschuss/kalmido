#!/usr/bin/env python3
"""mcp/agent_launcher.ps1 (2.7.2, #420) against a stub API (no container): the dry run (-Once) with model / auto-compact,
the paused agent (403), the env file (quotes, comments, export), the token never in the output; then the loop with a fake
agent command: started with the settings, restarted on "Reset now" (reset_seq), on changed settings, stopped when paused.
Needs pwsh (PowerShell 7) on PATH or in $PWSH; prints SKIP and exits 0 without it."""
import json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kt import check, done, until  # 2.206.0 B (#2762): shared helpers (tests/kt.py)

HERE = os.path.dirname(os.path.abspath(__file__))
PS1 = os.path.join(HERE, "..", "mcp", "agent_launcher.ps1")
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
if not PWSH:
    print("launcher_ps1: SKIP (no pwsh)")
    sys.exit(0)
TOKEN = "abk_secret_test_token_123"
STATE = {"code": 200, "runtime": {"model": "opus", "autocompact": True, "autocompact_pct": 70, "nightly_reset": None,
                                  "reset_seq": 0, "timezone": "Europe/Berlin"}, "enabled": True, "auth": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        STATE["auth"].append(self.headers.get("Authorization"))
        if self.path != "/api/v1/agent":
            self.send_response(404); self.end_headers(); return
        body = json.dumps({"error": "paused"} if STATE["code"] != 200 else {"id": 9, "enabled": STATE["enabled"], "runtime": STATE["runtime"]}).encode()
        self.send_response(STATE["code"]); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
tmp = tempfile.mkdtemp(prefix="kalmido-ps1-")
envf = os.path.join(tmp, "agent.env")
with open(envf, "w") as f:
    f.write(f"# the agent's env\nexport KALMIDO_URL=\"{URL}/\"\nKALMIDO_TOKEN='{TOKEN}'\nKALMIDO_POLL=1\nKALMIDO_RESTART_DELAY=1\nEXTRA_VAR=hello world\n")


def run(*args, timeout=60):
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", PS1, *args], capture_output=True, text=True, timeout=timeout)


# ---- dry run
r = run("-e", envf, "--once", "--", "claude", "-p", "Work through your events")
check(r.returncode == 0, f"-Once exits 0: {r.returncode} {r.stderr[-300:]}")
check(r.stdout.strip() == "env CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70 claude -p Work through your events --model opus", "dry run line: " + repr(r.stdout))
check(TOKEN not in r.stdout + r.stderr, "the token is never printed")
check(STATE["auth"][-1] == f"Bearer {TOKEN}", "the token goes into the Authorization header")
STATE["runtime"].update(autocompact=False, model="")
r = run("-e", envf, "--once")
check(r.stdout.strip() == "env DISABLE_AUTO_COMPACT=1 claude", "auto-compact off, default model, default command: " + repr(r.stdout))
STATE["runtime"].update(autocompact=True, autocompact_pct=None)
r = run("-e", envf, "--once", "--", "mytool")
check(r.stdout.split() == ["env", "mytool"], "auto-compact on without a percentage: nothing set: " + repr(r.stdout))
STATE["code"] = 403
r = run("-e", envf, "--once")
check(r.returncode == 0 and r.stdout.split() == ["env", "claude"], "a paused agent (403): plain command in the dry run: " + repr(r.stdout))
STATE["code"] = 500
r = run("-e", envf, "--once")
check(r.returncode == 1 and "HTTP 500" in r.stderr, f"Kalmido error at the start: exit 1 ({r.returncode}) {r.stderr[-200:]}")
STATE["code"] = 200
r = run("-e", os.path.join(tmp, "missing.env"), "--once")
check(r.returncode == 2, "a missing env file: exit 2")
with open(os.path.join(tmp, "bad.env"), "w") as f:
    f.write(f"KALMIDO_URL={URL}\n")
r = run("-e", os.path.join(tmp, "bad.env"), "--once")
check(r.returncode == 2 and "KALMIDO_TOKEN missing" in r.stderr, "no token in the env file: exit 2")

# ---- the loop with a fake agent: every start appends its arguments + env to a log, then it runs until stopped
log = os.path.join(tmp, "starts.log")
fake = os.path.join(tmp, "fakeagent")
with open(fake, "w") as f:
    f.write("#!/usr/bin/env python3\nimport json, os, sys, time\n"
            f"open({log!r}, 'a').write(json.dumps({{'args': sys.argv[1:], 'pct': os.environ.get('CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'),"
            " 'dis': os.environ.get('DISABLE_AUTO_COMPACT'), 'extra': os.environ.get('EXTRA_VAR'), 'tok': bool(os.environ.get('KALMIDO_TOKEN'))}) + '\\n')\n"
            "time.sleep(600)\n")
os.chmod(fake, 0o755)
STATE["runtime"].update(model="sonnet", autocompact=True, autocompact_pct=60, reset_seq=0)
STATE["enabled"] = True
p = subprocess.Popen([PWSH, "-NoProfile", "-NonInteractive", "-File", PS1, "-e", envf, "--", fake, "--flag"],
                     stdout=subprocess.DEVNULL, stderr=(errf := open(os.path.join(tmp, "launcher.err"), "w+")), text=True)


def starts():
    try:
        return [json.loads(x) for x in open(log)]
    except FileNotFoundError:
        return []


try:
    check(until(lambda: len(starts()) == 1), "the agent starts")
    s = starts()[0] if starts() else {}
    check(s.get("args") == ["--flag", "--model", "sonnet"] and s.get("pct") == "60" and not s.get("dis"), "started with model + auto-compact: " + json.dumps(s))
    check(s.get("extra") == "hello world" and s.get("tok"), "the env file's variables reach the command")
    STATE["runtime"]["reset_seq"] = 1  # "Reset now"
    check(until(lambda: len(starts()) == 2), "Reset now -> a fresh start")
    STATE["runtime"].update(autocompact=False)
    check(until(lambda: len(starts()) == 3), "changed settings -> a fresh start")
    check(starts()[-1].get("dis") == "1" and not starts()[-1].get("pct"), "auto-compact off now: " + json.dumps(starts()[-1]))
    # 2.206.0 B (#2513): "nothing happens" = three more polls of the launcher (KALMIDO_POLL=1) instead of a fixed 3 s
    polls = len(STATE["auth"])
    check(until(lambda: len(STATE["auth"]) >= polls + 3, 30), "the launcher keeps polling")
    check(len(starts()) == 3, "no restart without a change")
    STATE["enabled"] = False

    def agent_pids():
        return subprocess.run(["pgrep", "-f", "python3 " + fake], capture_output=True, text=True).stdout.split()
    until(lambda: not agent_pids(), 30)  # 2.206.0 B (#2513): wait for the stop instead of a fixed 4 s
    out = agent_pids()
    check(not out, f"paused -> the agent is stopped ({out})")
    STATE["enabled"] = True
    check(until(lambda: len(starts()) == 4), "enabled again -> started")
finally:
    p.terminate()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    errf.seek(0); err = errf.read(); errf.close()
    subprocess.run(["pkill", "-f", "python3 " + fake])
# ---- 2.443.0 (#2940): robust like the .sh; the rest of the parity in launcher_parity_test.py
envr = os.path.join(tmp, "robust.env")
with open(envr, "w") as f:
    f.write(f"KALMIDO_URL={URL}\nKALMIDO_TOKEN={TOKEN}\nKALMIDO_POLL=1\nKALMIDO_RESTART_DELAY=1\n")
STATE["runtime"].update(reset_seq=0, nightly_reset=None)
STATE["enabled"] = True
errp = os.path.join(tmp, "robust.err")


def robust_log():
    with open(errp) as f:
        return f.read()


p = subprocess.Popen([PWSH, "-NoProfile", "-NonInteractive", "-File", PS1, "-e", envr, "--", os.path.join(tmp, "no-such-agent")],
                     stdout=subprocess.DEVNULL, stderr=open(errp, "w"))
check(until(lambda: robust_log().count("the command did not start") >= 2, 45), "a command that cannot start is tried again: " + robust_log()[-300:])
check(p.poll() is None, "the launcher stays")
STATE["runtime"]["reset_seq"] = "x"  # a value that throws in the round: only that round fails
check(until(lambda: "error:" in robust_log(), 30), "an error in one round is logged: " + robust_log()[-300:])
check(p.poll() is None, "an error in one round does not end the launcher")
STATE["runtime"]["reset_seq"] = 0
p.terminate()
check(p.wait(30) == 0, "TERM after errors: exit 0")

# the scheduled task writes with *>> into agent.log: stderr is a console there, not a pipe. A pty stands in for that console
import pty  # noqa: E402

agentlog = os.path.join(tmp, "agent.log")
master, slave = pty.openpty()
with open(os.path.join(tmp, "noname.env"), "w") as f:
    f.write(f"KALMIDO_URL={URL}\n")
noname = os.path.join(tmp, "noname.env")
r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", f"& '{PS1}' -e '{noname}' --once *>> '{agentlog}'"], stdin=slave, stdout=slave, stderr=slave, timeout=60)
os.close(slave); os.close(master)
check(os.path.exists(agentlog) and "KALMIDO_TOKEN missing" in open(agentlog).read(), "the log line is in the file of *>>")

# the table for Windows PowerShell 5.1: every Windows id is a real one, Europe/Berlin is in it
# 2.445.0 (#3748): a Linux without the legacy tz names cannot load every id; its Windows id table still knows them
src = open(PS1, encoding="utf-8").read()
table = src[src.index("$WinZones = @{"):src.index("function Now-In")]
ids = re.findall(r"^  '([^']+)' = '", table, re.M)
check(len(ids) > 30 and "Europe/Berlin" in table, f"the zone table: {len(ids)}")
script = "foreach ($i in @(" + ",".join(f"'{i}'" for i in ids) + ")) { try { [void][TimeZoneInfo]::FindSystemTimeZoneById($i) } catch { $x = $null; if (-not [TimeZoneInfo]::TryConvertWindowsIdToIanaId($i, [ref]$x)) { Write-Output \"BAD $i\" } } }"
r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and "BAD" not in r.stdout, f"every Windows zone id exists: {r.stdout[-300:]} {r.stderr[-200:]}")

# 2.445.0 (#3748): agent_run.py keeps its own agent_run.log (on Windows by default; here via KALMIDO_RUN_LOG): a restart appends
# instead of overwriting, and a file over 1 MiB moves to .1 so it cannot grow without end
rl = os.path.join(tmp, "agent_run.log")
runner = os.path.join(HERE, "..", "mcp", "agent_run.py")
snippet = "import importlib.util,sys; sp=importlib.util.spec_from_file_location('ar', sys.argv[1]); m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); m.log(sys.argv[2])"
def run_log(line, path=rl):
    return subprocess.run([sys.executable, "-I", "-c", snippet, runner, line], env={**os.environ, "KALMIDO_RUN_LOG": path}, capture_output=True, text=True, timeout=60)
run_log("first run"); run_log("second run")
body = open(rl).read() if os.path.exists(rl) else ""
check("first run" in body and "second run" in body, "agent_run.log: a second start appends, the first run stays: " + body[-200:])
with open(rl, "a") as f:
    f.write("x" * (1024 * 1024 + 10) + "\n")
run_log("third run")
check(os.path.exists(rl + ".1") and "first run" in open(rl + ".1").read(), "agent_run.log over 1 MiB: the old content moves to .1")
check(open(rl).read().count("agent_run:") == 1 and "third run" in open(rl).read(), "agent_run.log: a fresh small file after the move")
os.chdir(tmp)
run_log("nothing", "0")
check(not os.path.exists(os.path.join(tmp, "0")), "KALMIDO_RUN_LOG=0 writes no file")

check(TOKEN not in (err or ""), "the token is never in the log")
check("restart: reset now (0 -> 1)" in (err or "") and "restart: runtime settings changed" in (err or "") and "paused in Kalmido: stopping" in (err or ""),
      "the log names every restart: " + (err or "")[-400:])
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
sys.exit(done("launcher_ps1"))
