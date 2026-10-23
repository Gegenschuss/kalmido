#!/usr/bin/env python3
"""2.41.0 API tests, part E (chat), own container (start.sh). Invented names only.
 - #1206 notices in the agent chat: POST /api/v1/agent/chats/{id} with kind notice = one line (line breaks become
   spaces), at most 200 characters, nothing else allowed (choices, task_id, reply_to ... 400), an unknown kind 400, at
   most one file (multipart); the message carries kind notice (others kind message) for the person and the agent; never
   unread, no "asks"; it leaves older answer buttons open
 - the reference launcher (mcp/agent_run.py): a chat run whose command reports compact_boundary sends the notice
   "Conversation compacted (HH:MM)" into that chat; an older server (400 for kind) gets nothing, never a normal message
usage: p2410_e_api_test.py <datadir>"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(N, "..", "mcp")
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2410E_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,agents"})
ALICE = A.get(B + "/api/me").json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AID, TOKEN = r.json()["id"], r.json()["token"]
AH = {"Authorization": "Bearer " + TOKEN}
L = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"}).ok, "setup: the agent shares the list")
CH = B + f"/api/v1/agent/chats/{ALICE}"


def post(body):
    return requests.post(CH, json=body, headers=AH)


def unread():
    a = [x for x in A.get(B + "/api/agents").json().get("agents", []) if x.get("id") == AID]
    return a[0].get("chat_unread") if a else None


# ================= #1206 the notice
r = post({"body": "Which one?", "choices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]})
check(r.status_code == 201 and r.json().get("kind") == "message", "#1206: a normal message says kind message " + r.text[:200])
Q = r.json()["id"]
check(unread() == 1, f"#1206: set-up: the question is unread ({unread()})")
r = post({"body": "  New session,\n summary taken over (22:10)?  ", "kind": "notice"})
n = r.json()
check(r.status_code == 201 and n.get("kind") == "notice" and n.get("body") == "New session, summary taken over (22:10)?",
      "#1206: a notice, one line " + r.text[:200])
check(n.get("asks") is False and n.get("choices") is None, "#1206: a notice asks nothing, has no buttons")
check(unread() == 1, f"#1206: a notice is never unread ({unread()})")
check(post({"body": "x", "kind": "shout"}).status_code == 400, "#1206: an unknown kind 400")
check(post({"body": "x", "kind": "message"}).json().get("kind") == "message", "#1206: kind message = a normal message")
for extra in ({"choices": [{"id": "a", "label": "A"}]}, {"task_id": 1}, {"reply_to": Q}, {"offer_save": True},
              {"approval": {"title": "Go?"}}, {"permission": True}):
    r = post({"body": "x", "kind": "notice", **extra})
    check(r.status_code == 400, f"#1206: a notice with {list(extra)} 400 " + r.text[:160])
check(post({"body": "x" * 201, "kind": "notice"}).status_code == 400, "#1206: more than 200 characters 400")
check(post({"body": "y" * 200, "kind": "notice"}).status_code == 201, "#1206: 200 characters are fine")
check(post({"body": "  ", "kind": "notice"}).status_code == 400, "#1206: an empty notice 400")
# one file (the summary), not two
r = requests.post(CH, data={"body": "Conversation compacted (22:10)", "kind": "notice"},
                  files=[("file", ("summary.md", b"# Summary\n\n- done\n", "text/markdown"))], headers=AH)
check(r.status_code == 201 and r.json().get("kind") == "notice" and [a["name"] for a in r.json().get("attachments", [])] == ["summary.md"],
      "#1206: a notice with one file " + r.text[:200])
r = requests.post(CH, data={"body": "x", "kind": "notice"},
                  files=[("file", ("a.md", b"a", "text/markdown")), ("file", ("b.md", b"b", "text/markdown"))], headers=AH)
check(r.status_code == 400, "#1206: a notice with two files 400 " + r.text[:160])
# the person: the question's buttons are still open after the notices; the agent sees kind too
ms = A.get(B + f"/api/agents/{AID}/chat?limit=30").json()["messages"]
q = [m for m in ms if m["id"] == Q]
check(q and q[0].get("choice_state") == "expired", "#1206: set-up: the later normal message makes the buttons expire " + json.dumps(q)[:200])
r = post({"body": "Pick one", "choices": [{"id": "a", "label": "A"}]})
Q2 = r.json()["id"]
post({"body": "Conversation compacted (22:12)", "kind": "notice"})
ms = A.get(B + f"/api/agents/{AID}/chat?limit=30").json()["messages"]
q2 = [m for m in ms if m["id"] == Q2]
check(q2 and q2[0].get("choice_state") == "open", "#1206: a notice leaves the buttons of the message before it open " + json.dumps(q2)[:200])
check(sum(1 for m in ms if m.get("kind") == "notice") == 4 and all(m.get("kind") in ("message", "notice") for m in ms),
      "#1206: the person sees kind on every message " + json.dumps([m.get("kind") for m in ms]))
ag = requests.get(B + "/api/v1/agent/chats", headers=AH).json().get("data", [])
check(any(m.get("kind") == "notice" for m in ag), "#1206: GET /agent/chats carries kind")
r = A.post(B + f"/api/agents/{AID}/chat/{Q2}/choice", json={"choice_ids": ["a"]})
check(r.ok, "#1206: the buttons before the notice can be pressed " + r.text[:160])

# ================= the reference launcher: compact_boundary -> a notice
TMP = tempfile.mkdtemp(prefix="kalmido-p2410e-")
FAKE = os.path.join(TMP, "fakeclaude")
with open(FAKE, "w") as f:
    f.write(r'''#!/usr/bin/env python3
import json, sys
sys.stdin.read()
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "model": "claude-opus-5-5", "permissionMode": "default", "tools": [], "session_id": "s"})
out({"type": "system", "subtype": "compact_boundary", "session_id": "s", "compact_metadata": {"trigger": "auto", "pre_tokens": 160000}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "All builds are green."}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "All builds are green.", "session_id": "s"})
''')
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IEXEC)
EV = os.path.join(TMP, "ev.jsonl")
with open(EV, "w") as f:
    f.write(json.dumps({"event": "chat", "data": {"user": {"id": ALICE, "name": "Alice"}, "message": {"id": 1, "body": "How are the builds?"}}}) + "\n")
before = max(m["id"] for m in A.get(B + f"/api/agents/{AID}/chat?limit=30").json()["messages"])
env = {**os.environ, "KALMIDO_URL": B, "KALMIDO_TOKEN": TOKEN, "KALMIDO_APPROVAL_CHECK": "0"}
r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", os.path.join(TMP, "st"), "--once-event", EV, "--", FAKE],
                   capture_output=True, text=True, timeout=90, env=env, cwd=TMP)
check(r.returncode == 0, "launcher: the run ends cleanly " + r.stderr[-300:])
new = [m for m in A.get(B + f"/api/agents/{AID}/chat?limit=30").json()["messages"] if m["id"] > before]
nt = [m for m in new if m.get("kind") == "notice"]
check(len(nt) == 1 and re.fullmatch(r"Conversation compacted \(\d\d:\d\d\)", nt[0]["body"]), "launcher: compact_boundary -> one notice " + json.dumps(new)[:300])
check([m["body"] for m in new if m.get("kind") == "message"] == ["All builds are green."], "launcher: the answer as a normal message " + json.dumps(new)[:300])

# an older server: 400 for kind -> nothing, never a normal message instead
SEEN = {"posts": []}


class Old(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        raw = json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, {"data": []} if "/agent/chats" in self.path else {"runtime": {}})

    def do_PUT(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(200, {})

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if "/agent/chats/" in self.path:
            if SEEN.get("status") and b.get("kind") == "notice":  # 2.41.0 (#1206): a 429 loses only that line
                return self._send(SEEN["status"], {"error": "Too many requests"})
            if set(b) - {"body", "task_id", "choices", "reply_to", "approval", "expires_in"} - SEEN.get("ok", set()):
                return self._send(400, {"error": "Unknown field: " + ",".join(sorted(set(b) - {"body", "task_id", "choices"}))})
            SEEN["posts"].append(b)
            return self._send(201, {"id": len(SEEN["posts"])})
        self._send(200, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Old)
threading.Thread(target=srv.serve_forever, daemon=True).start()
env = {**os.environ, "KALMIDO_URL": f"http://127.0.0.1:{srv.server_address[1]}", "KALMIDO_TOKEN": "abk_" + "o" * 30, "KALMIDO_APPROVAL_CHECK": "0"}
r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", os.path.join(TMP, "st2"), "--once-event", EV, "--", FAKE],
                   capture_output=True, text=True, timeout=90, env=env, cwd=TMP)
check(r.returncode == 0, "old server: the runner ends cleanly " + r.stderr[-300:])
check([p["body"] for p in SEEN["posts"]] == ["All builds are green."], f"old server: only the answer, no notice as a message: {SEEN['posts']}")
check("before 2.41" in r.stderr, "old server: notices are switched off (logged) " + r.stderr[-300:])

# 2.41.0 (#1206): a free notice text with braces never stops the run (only {0} becomes the time)
SEEN.update(posts=[], ok={"kind"})
r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", os.path.join(TMP, "st3"), "--once-event", EV, "--", FAKE],
                   capture_output=True, text=True, timeout=90, env={**env, "KALMIDO_NOTICE_COMPACTED": "{x} squeezed {0} {"}, cwd=TMP)
nb = [p["body"] for p in SEEN["posts"] if p.get("kind") == "notice"]
check(r.returncode == 0 and len(nb) == 1 and re.fullmatch(r"\{x\} squeezed \d\d:\d\d \{", nb[0]), f"launcher: braces in the notice text {nb} " + r.stderr[-300:])
# a 429 is no old server: nothing sent, notices stay on (no "before 2.41")
SEEN.update(posts=[], status=429)
r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", os.path.join(TMP, "st4"), "--once-event", EV, "--", FAKE],
                   capture_output=True, text=True, timeout=90, env=env, cwd=TMP)
check(r.returncode == 0 and [p["body"] for p in SEEN["posts"]] == ["All builds are green."] and "before 2.41" not in r.stderr,
      f"launcher: a 429 on the notice does not switch notices off {SEEN['posts']} " + r.stderr[-300:])
srv.shutdown()

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2410_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
