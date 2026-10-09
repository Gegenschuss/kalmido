#!/usr/bin/env python3
"""2.35.0 API tests, part A (#1098): the reference launcher in event mode, step by step as AGENT-SETUP.md describes it, on a
fresh instance with a fake `claude` that plays a real stream-json protocol (init, text + tool calls, tool output,
rate_limit_event, result):
 - agent_launcher.sh --events (and agent_launcher.ps1 --events when pwsh is there) starts mcp/agent_run.py; a chat message
   of the person becomes ONE headless run: the prompt carries the message and the quote it answers (reply reference)
 - steps: the prose before each tool call arrives under the answer (only for that person), tool output never, a token in
   the prose is masked, the final answer is posted once and is no step
 - model ("Opus 5.5" from the init event) and permission mode (auto from --permission-mode acceptEdits) in the agent's host
   info; status idle after the run
 - plan usage ring from the rate_limit_event (week 83.1 %, every window, measured now)
 - an answer ending in an ```approval block becomes an approval card / Yes-No buttons; pressing Yes starts a run whose prompt
   says "Approval: yes"
 - a task event (comment) is a run without steps and without a chat answer
 - an older server (stub without /agent/progress, /agent/quota, host fields, approval): the run still answers
usage: p2350_a_api_test.py <datadir>"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(N, "..", "mcp")
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
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


def wait_for(fn, what, secs=45):
    end = time.time() + secs
    while time.time() < end:
        try:
            v = fn()
        except Exception:
            v = None
        if v:
            return v
        time.sleep(0.5)
    check(False, "timeout: " + what)
    return None


# ---- a fake claude: reads the prompt on stdin, keeps it, plays a stream-json run
TMP = tempfile.mkdtemp(prefix="kalmido-p2350a-")
FAKE = os.path.join(TMP, "fakeclaude")
PROMPTS = os.path.join(TMP, "prompts.jsonl")
with open(FAKE, "w") as f:
    f.write(r'''#!/usr/bin/env python3
import json, sys, time, os
args = sys.argv[1:]
prompt = sys.stdin.read()
with open(os.environ["FAKE_PROMPTS"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt}) + "\n")
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "model": "claude-opus-5-5[1m]", "permissionMode": "acceptEdits", "tools": []})
if "Approval: yes" in prompt:
    final = "Thanks, it is done."
elif "deploy please" in prompt:
    final = "I am ready to deploy version 1.2.\n\n```approval\nDeploy version 1.2\nThe new version goes live for everyone.\n```"
elif "This is a task event" in prompt:
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "I comment on the task."}, {"type": "tool_use", "id": "t1", "name": "mcp__kalmido__add_comment", "input": {}}]}})
    final = "Commented."
else:
    final = "All builds are green."
if "This is a chat run" in prompt and "deploy please" not in prompt and "Approval:" not in prompt:
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "I look at the build first, key abk_" + "q" * 30 + "."}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat log"}}]}})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "TOOLOUTPUT line 1"}]}})
    time.sleep(2.2)
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Now I check the tests."}, {"type": "tool_use", "id": "t2", "name": "Read", "input": {}}]}})
    out({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.42, "resetsAt": 4102444800}, "seven_day": {"utilization": 0.831, "resetsAt": 4102444800}, "seven_day_overage_included": {"utilization": 0.12, "resetsAt": 4102444800}}}, "uuid": "u", "session_id": "s"})
    time.sleep(2.2)
out({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": "s"})
''')
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IEXEC)


def prompts():
    try:
        with open(PROMPTS) as f:
            return [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        return []


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/me").json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AID, TOKEN = r.json()["id"], r.json()["token"]
AH = {"Authorization": "Bearer " + TOKEN}
L = A.post(B + "/api/lists", json={"name": "Work", "kind": "project"}).json()["id"]
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"})
check(r.ok, "setup: the agent shares the list " + r.text[:120])
TASK = A.post(B + "/api/tasks", json={"title": "Fix the login", "list_id": L}).json()["id"]

ENV = os.path.join(TMP, "agent.env")
with open(ENV, "w") as f:
    f.write(f"KALMIDO_URL={B}\nKALMIDO_TOKEN={TOKEN}\nKALMIDO_POLL=2\nKALMIDO_STATE_DIR={TMP}/state\nFAKE_PROMPTS={PROMPTS}\n")
os.chmod(ENV, 0o600)

# the dry run shows the runner in front of the command, never the token
r = subprocess.run(["bash", os.path.join(MCP, "agent_launcher.sh"), "-e", ENV, "--events", "--once", "--", FAKE],
                   capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and "agent_run.py -- " + FAKE in r.stdout, "dry run: agent_run.py in front of the command " + repr(r.stdout[-200:]))
check(TOKEN not in r.stdout + r.stderr, "the token is never printed")


def start_launcher(kind):
    if kind == "sh":
        cmd = ["bash", os.path.join(MCP, "agent_launcher.sh"), "-e", ENV, "--events", "--", FAKE, "--permission-mode", "acceptEdits"]
    else:
        cmd = [PWSH, "-NoProfile", "-NonInteractive", "-File", os.path.join(MCP, "agent_launcher.ps1"), "-e", ENV, "--events",
               "--", FAKE, "--permission-mode", "acceptEdits"]
    log = open(os.path.join(TMP, f"launcher-{kind}.log"), "w")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=TMP), log


def stop_launcher(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(40)
    except Exception:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass


def chat():
    return A.get(B + f"/api/agents/{AID}/chat").json()


def agent_msgs():
    return [m for m in (chat().get("messages") or chat().get("data") or []) if m.get("sender") == "agent" or m.get("from") == "agent"]


def step_texts(m):
    return [s.get("text") if isinstance(s, dict) else str(s) for s in (m.get("steps") or [])]


# an earlier question of the agent that Alice answers (reply reference)
r = requests.post(V + f"/agent/chats/{ALICE}", headers=AH, json={"body": "Should I check the nightly build?"})
check(r.status_code == 201, "the agent asks first " + r.text[:120])
Q = r.json().get("id") or (r.json().get("message") or {}).get("id")

P, LOG = start_launcher("sh")
try:
    time.sleep(3)
    r = A.post(B + f"/api/agents/{AID}/chat", json={"body": "Yes, check it", "reply_to": Q})
    check(r.status_code == 201, "Alice answers the question " + r.text[:120])
    ans = wait_for(lambda: [m for m in agent_msgs() if "All builds are green" in (m.get("body") or m.get("text") or "")], "the answer arrives")
    pr = prompts()
    check(len(pr) == 1, f"one run for one message: {len(pr)}")
    if pr:
        check("-p" in pr[0]["args"] and "stream-json" in pr[0]["args"] and "--verbose" in pr[0]["args"], "headless stream-json run: " + str(pr[0]["args"]))
        check("Yes, check it" in pr[0]["prompt"] and 'This answers your own message: "Should I check the nightly build?"' in pr[0]["prompt"],
              "the prompt carries the message and the quote it answers")
        check(TOKEN not in pr[0]["prompt"], "the token is not in the prompt")
    if ans:
        m = ans[-1]
        st = step_texts(m)
        check(len(st) == 2 and st[0].startswith("I look at the build first") and st[1] == "Now I check the tests.", f"two steps under the answer: {st}")
        check(not any("TOOLOUTPUT" in x for x in st), "tool output never becomes a step")
        check(not any("abk_qqqq" in x for x in st) and any("[redacted]" in x or "[entfernt]" in x for x in st), "a token in a step is masked")
        check(not any("All builds are green" in x for x in st), "the answer is no step")
        check(len([x for x in agent_msgs() if "All builds are green" in (x.get("body") or x.get("text") or "")]) == 1, "the answer is posted once")
    me = requests.get(V + "/agent", headers=AH).json()
    hi = me.get("host") or {}
    check(hi.get("model") == "Opus 5.5" and hi.get("permission_mode") == "auto", f"model + permission mode reported: {hi}")
    check(wait_for(lambda: requests.get(V + "/agent", headers=AH).json().get("status") == "idle", "idle after the run", 15), "status idle after the run")
    q = requests.get(V + "/agent/quota", headers=AH).json().get("quota") or {}
    ws = {w.get("key"): w.get("percent") for w in q.get("windows") or []}
    check(ws.get("seven_day") == 83.1 and ws.get("five_hour") == 42.0, f"plan usage from the stream: {ws}")
    check("seven_day_overage_included" in ws, "a further window passes through: " + str(list(ws)))
    check(q.get("stale") is False, "measured now: not grey")

    # approval: the answer ends in an ```approval block
    n0 = len(prompts())
    A.post(B + f"/api/agents/{AID}/chat", json={"body": "deploy please"})
    card = wait_for(lambda: [m for m in agent_msgs() if "ready to deploy" in (m.get("body") or m.get("text") or "")], "the approval question arrives")
    if card:
        m = card[-1]
        ch = m.get("choices") or {}
        btn = ch.get("choices") if isinstance(ch, dict) else ch
        ids = [b.get("id") for b in (btn or [])]
        check(ids == ["yes", "no"], f"Yes / No on the question: {ids}")
        check("```approval" not in (m.get("body") or m.get("text") or ""), "the block itself is not shown")
        if isinstance(ch, dict) and ch.get("approval") is not None:
            check((ch.get("approval") or {}).get("title") == "Deploy version 1.2", "approval card with its title: " + json.dumps(ch)[:200])
        r = A.post(B + f"/api/agents/{AID}/chat/{m['id']}/choice", json={"choice_ids": ["yes"]})
        check(r.ok, "Alice presses Yes " + r.text[:160])
        wait_for(lambda: [x for x in agent_msgs() if "Thanks, it is done" in (x.get("body") or x.get("text") or "")], "the approved run answers")
        pr = prompts()[n0:]
        check(any("Approval: yes" in x["prompt"] or "pressed: " in x["prompt"] for x in pr), "the yes comes back as a run")

    # a task event: no steps, no chat answer
    n0, nmsg = len(prompts()), len(agent_msgs())
    Bh = A.post(B + f"/api/tasks/{TASK}/comments", json={"body": "<@%d> please look at this" % AID})
    check(Bh.ok, "a comment that mentions the agent " + Bh.text[:120])
    wait_for(lambda: len(prompts()) > n0, "the task event starts a run")
    time.sleep(2)
    pr = prompts()[n0:]
    check(pr and "This is a task event" in pr[0]["prompt"], "task event prompt")
    check(len(agent_msgs()) == nmsg, "a task event posts nothing into the chat")
finally:
    stop_launcher(P)
    LOG.close()
with open(os.path.join(TMP, "launcher-sh.log")) as f:
    lg = f.read()
check(TOKEN not in lg and "Yes, check it" not in lg, "the launcher log has no token and no message text")

# ---- the PowerShell launcher, the same flow once (when pwsh is there)
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
if PWSH:
    n0 = len(prompts())
    P, LOG = start_launcher("ps1")
    try:
        time.sleep(4)
        A.post(B + f"/api/agents/{AID}/chat", json={"body": "and once more from Windows"})
        got = wait_for(lambda: len([m for m in agent_msgs() if "All builds are green" in (m.get("body") or m.get("text") or "")]) >= 2, "ps1: the answer arrives", 60)
        check(bool(got), "ps1 --events: a chat message gets its answer")
        check(len(prompts()) == n0 + 1, "ps1: one run")
    finally:
        stop_launcher(P)
        LOG.close()
else:
    print("p2350_a_api: pwsh missing, the .ps1 is covered by launcher_parity + launcher_ps1 (static)")

# ---- an older server (stub): no steps / ring / host fields / approval -> still answers, as before
SEEN = {"posts": [], "status": []}


class Old(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        b = json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_PUT(self):
        b = self._body()
        if self.path == "/api/v1/agent/status":
            if set(b) - {"status", "text", "task_id"}:
                return self._send(400, {"error": "Unknown field"})
            SEEN["status"].append(b["status"])
            return self._send(200)
        self._send(404)

    def do_POST(self):
        b = self._body()
        if self.path.startswith("/api/v1/agent/chats/"):
            if set(b) - {"body", "task_id", "choices"}:
                return self._send(400, {"error": "Unknown field: " + ",".join(sorted(set(b) - {"body", "task_id", "choices"}))})
            SEEN["posts"].append(b)
            return self._send(201, {"id": len(SEEN["posts"])})
        self._send(404)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Old)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ev = os.path.join(TMP, "old.jsonl")
with open(ev, "w") as f:
    f.write(json.dumps({"event": "chat", "data": {"user": {"id": 5, "name": "Ann"}, "message": {"id": 1, "body": "Hello"}}}) + "\n")
    f.write(json.dumps({"event": "chat", "data": {"user": {"id": 5, "name": "Ann"}, "message": {"id": 2, "body": "deploy please"}}}) + "\n")
env = {**os.environ, "KALMIDO_URL": f"http://127.0.0.1:{srv.server_address[1]}", "KALMIDO_TOKEN": "abk_" + "o" * 30, "FAKE_PROMPTS": PROMPTS}
r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", os.path.join(TMP, "st2"), "--once-event", ev, "--", FAKE],
                   capture_output=True, text=True, timeout=90, env=env, cwd=TMP)
check(r.returncode == 0, "old server: the runner ends cleanly " + r.stderr[-300:])
check(len(SEEN["posts"]) == 1 and "ready to deploy" in SEEN["posts"][0]["body"], f"old server: one answer for two messages in a row: {SEEN['posts']}")
check(SEEN["posts"] and [c["id"] for c in SEEN["posts"][0].get("choices") or []] == ["yes", "no"], "old server: Yes / No buttons instead of the card")
check(SEEN["status"][-1:] == ["idle"] and "working" in SEEN["status"], f"old server: plain status working -> idle: {SEEN['status']}")
check("before 2.32" in r.stderr and "before 2.35" in r.stderr, "old server: the features are switched off once (logged)")
srv.shutdown()

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2350_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
