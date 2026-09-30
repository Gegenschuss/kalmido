#!/usr/bin/env python3
"""2.1.1 (#326): mcp/claude_usage_hook.py (the Claude Code Stop hook) against a stub Kalmido API, no container.
A sample transcript (tests/fixtures/claude_transcript.jsonl): one message written on two lines counts once, one report per
model, synthetic messages and broken lines are skipped, no text of the transcript is ever sent; the state per session (only
new messages next time, a half-written last line waits), the cost from a price table, the task of the agent's status,
a task that is gone (report without it), Kalmido unreachable (state kept, sent later), the env file, and a hook that never
fails (exit 0 on bad input).
usage: usage_hook_test.py"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp"))
import claude_usage_hook as hook  # noqa: E402

FAILS, OKS = [], [0]
REQS = []
STATE = {"agent": {"status": "idle", "status_task": None}, "bad_task": False}
TOKEN = "abk_test_hook_token"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        REQS.append({"m": "GET", "p": self.path, "auth": self.headers.get("Authorization")})
        self._send(200, STATE["agent"]) if self.path == "/api/v1/agent" else self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n) or b"{}")
        REQS.append({"m": "POST", "p": self.path, "b": b, "auth": self.headers.get("Authorization")})
        if STATE["bad_task"] and "task_id" in b:
            return self._send(400, {"error": {"code": "bad_request", "message": "Invalid value: task_id"}})
        self._send(201, {"id": len(REQS)})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
tmp = tempfile.mkdtemp(prefix="kalmido-hook-")
tr = os.path.join(tmp, "session.jsonl")
shutil.copy(os.path.join(HERE, "fixtures", "claude_transcript.jsonl"), tr)
ENV = {"KALMIDO_URL": URL, "KALMIDO_TOKEN": TOKEN, "KALMIDO_USAGE_STATE_DIR": os.path.join(tmp, "state")}
HOOK = {"session_id": "sess-1234abcd", "transcript_path": tr, "hook_event_name": "Stop"}


def posts():
    return [r for r in REQS if r["m"] == "POST"]


def run(env=None, h=None):
    n0 = len(posts())
    hook.run(h or HOOK, env or ENV)
    return posts()[n0:]


# the first run: everything so far, one report per model
p = run()
by = {r["b"]["model"]: r["b"] for r in p}
check(set(by) == {"claude-sonnet-4-5", "claude-haiku-4-5"}, f"one report per model, synthetic skipped: {list(by)}")
s = by.get("claude-sonnet-4-5", {})
check(s.get("input_tokens") == 15 and s.get("output_tokens") == 160 and s.get("cache_write_tokens") == 2300 and s.get("cache_read_tokens") == 32000,
      f"a message on two lines counts once: {s}")
check(by.get("claude-haiku-4-5", {}).get("input_tokens") == 800 and by["claude-haiku-4-5"]["output_tokens"] == 60, "haiku")
check(all(r["p"] == "/api/v1/agent/usage" and r["auth"] == "Bearer " + TOKEN for r in p), "POST /api/v1/agent/usage with the token")
check(all("cost_usd" not in r["b"] and "task_id" not in r["b"] for r in p), "no price table: no cost; idle agent: no task")
check(all(set(r["b"]) <= {"model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "note", "cost_usd", "task_id"} for r in p),
      "only numbers + ids")
check("SECRET" not in json.dumps(REQS), "no transcript text is ever sent")
check(s.get("note", "").startswith("claude-code sess-123") and len(s["note"]) <= 200, f"short note: {s.get('note')}")
check(os.path.exists(hook.state_path(ENV["KALMIDO_USAGE_STATE_DIR"], "sess-1234abcd")), "state file per session")

# nothing new -> nothing sent
check(run() == [], "second run without new messages: nothing")
# a half-written line waits; completed, it counts
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","requestId":"req_5","message":{"id":"msg_05","model":"claude-sonnet-4-5","usage":{"input_tokens":7,"output_tokens":3')
check(run() == [], "a half-written last line is not read yet")
with open(tr, "a", encoding="utf-8") as f:
    f.write(',"cache_read_input_tokens":0}}}\n')
p = run()
check(len(p) == 1 and p[0]["b"]["input_tokens"] == 7 and p[0]["b"]["output_tokens"] == 3, f"then it counts, alone: {[r['b'] for r in p]}")
# the same message id again (another content block) is not counted twice
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","requestId":"req_5","message":{"id":"msg_05","model":"claude-sonnet-4-5","usage":{"input_tokens":7,"output_tokens":3}}}\n')
check(run() == [], "a message id already reported is not counted again")

# price table + the task of the agent's status
STATE["agent"] = {"status": "working", "status_task": 42}
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","message":{"id":"msg_06","model":"claude-sonnet-4-5","usage":{"input_tokens":1000000,"output_tokens":100000,'
            '"cache_creation_input_tokens":0,"cache_read_input_tokens":1000000}}}\n')
p = run({**ENV, "KALMIDO_USAGE_PRICES": json.dumps({"claude-sonnet": [1, 1, 1, 1], "claude-sonnet-4": [3, 15, 3.75, 0.3]})})
check(len(p) == 1 and abs(p[0]["b"]["cost_usd"] - (3 + 1.5 + 0.3)) < 1e-9, f"cost from the longest price prefix: {p[0]['b'] if p else p}")
check(p and p[0]["b"].get("task_id") == 42, "task_id of the agent's status while working")
# a task that is gone: 400 -> sent again without it
STATE["bad_task"] = True
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","message":{"id":"msg_07","model":"claude-sonnet-4-5","usage":{"input_tokens":9,"output_tokens":1}}}\n')
p = run()
check(len(p) == 2 and "task_id" in p[0]["b"] and "task_id" not in p[1]["b"] and p[1]["b"]["input_tokens"] == 9, "400 for the task: reported without it")
STATE.update(bad_task=False, agent={"status": "idle", "status_task": None})
# Kalmido unreachable: state kept, the next run sends the missed turn
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","message":{"id":"msg_08","model":"claude-sonnet-4-5","usage":{"input_tokens":11,"output_tokens":2}}}\n')
hook.run(HOOK, {**ENV, "KALMIDO_URL": "http://127.0.0.1:9"})
p = run()
check(len(p) == 1 and p[0]["b"]["input_tokens"] == 11, "unreachable: sent on the next run")
# a fixed task, an env file, the CLI (always exit 0), dry run
envf = os.path.join(tmp, "agent.env")
with open(envf, "w", encoding="utf-8") as f:
    f.write(f"# agent\nexport KALMIDO_URL=\"{URL}\"\nKALMIDO_TOKEN='{TOKEN}'\nKALMIDO_USAGE_TASK=7\nKALMIDO_USAGE_STATE_DIR={ENV['KALMIDO_USAGE_STATE_DIR']}\n")
check(hook.load_env(envf) == {"KALMIDO_URL": URL, "KALMIDO_TOKEN": TOKEN, "KALMIDO_USAGE_TASK": "7", "KALMIDO_USAGE_STATE_DIR": ENV["KALMIDO_USAGE_STATE_DIR"]},
      "env file: export, quotes, comments")
with open(tr, "a", encoding="utf-8") as f:
    f.write('{"type":"assistant","message":{"id":"msg_09","model":"claude-opus-4-1","usage":{"input_tokens":4,"output_tokens":4}}}\n')
clean_env = {k: v for k, v in os.environ.items() if not k.startswith("KALMIDO_")}
cp = subprocess.run([sys.executable, os.path.join(HERE, "..", "mcp", "claude_usage_hook.py"), "--dry-run", envf], input=json.dumps(HOOK),
                    capture_output=True, text=True, env=clean_env, timeout=30)
check(cp.returncode == 0 and json.loads(cp.stdout.strip().splitlines()[0])["task_id"] == 7, f"--dry-run prints the report: {cp.stdout} {cp.stderr}")
n0 = len(posts())
cp = subprocess.run([sys.executable, os.path.join(HERE, "..", "mcp", "claude_usage_hook.py"), envf], input=json.dumps(HOOK),
                    capture_output=True, text=True, env=clean_env, timeout=30)
p = posts()[n0:]
check(cp.returncode == 0 and len(p) == 1 and p[0]["b"]["model"] == "claude-opus-4-1" and p[0]["b"]["task_id"] == 7, f"CLI with the env file: {p} {cp.stderr}")
for bad in ("not json", "", json.dumps({"transcript_path": "/nonexistent"})):
    cp = subprocess.run([sys.executable, os.path.join(HERE, "..", "mcp", "claude_usage_hook.py")], input=bad, capture_output=True, text=True,
                        env=clean_env, timeout=30)
    check(cp.returncode == 0, f"bad input -> exit 0 ({bad[:20]!r}: {cp.stderr.strip()[:100]})")
out = io.StringIO()
check(hook.run({"transcript_path": tr, "session_id": "new-session"}, {"KALMIDO_USAGE_STATE_DIR": ENV["KALMIDO_USAGE_STATE_DIR"]}, dry_run=True, out=out)
      and "SECRET" not in out.getvalue(), "a new session starts at the beginning (dry run, no URL needed)")
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
