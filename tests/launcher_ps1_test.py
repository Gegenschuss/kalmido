#!/usr/bin/env python3
"""mcp/agent_launcher.ps1 (2.7.2, #420) against a stub API (no container): the dry run (-Once) with model / auto-compact,
the paused agent (403), the env file (quotes, comments, export), the token never in the output; then the loop with a fake
agent command: started with the settings, restarted on "Reset now" (reset_seq), on changed settings, stopped when paused.
Needs pwsh (PowerShell 7) on PATH or in $PWSH; prints SKIP and exits 0 without it."""
import json, os, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
F, ok = [], 0


def check(c, what):
    global ok
    if c:
        ok += 1
    else:
        F.append(what); print("FAIL:", what)


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


def until(fn, n=60):
    for _ in range(n):
        if fn():
            return True
        time.sleep(0.5)
    return False


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
    time.sleep(3)
    check(len(starts()) == 3, "no restart without a change")
    STATE["enabled"] = False
    time.sleep(4)
    out = subprocess.run(["pgrep", "-f", "python3 " + fake], capture_output=True, text=True).stdout.split()
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
check(TOKEN not in (err or ""), "the token is never in the log")
check("restart: reset now (0 -> 1)" in (err or "") and "restart: runtime settings changed" in (err or "") and "paused in Kalmido: stopping" in (err or ""),
      "the log names every restart: " + (err or "")[-400:])
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
print(f"launcher_ps1: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
