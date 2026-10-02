#!/usr/bin/env python3
"""MCP server (mcp/kalmido_mcp.py) without Docker: a stub HTTP server imitates the Kalmido REST endpoints the tools use and
records every request (path, method, query, body, Authorization). The MCP server is driven over stdio and over HTTP
(Streamable HTTP subset): initialize (protocol negotiation), tools/list (every tool, object schemas), tools/call of every
tool -> the right endpoint + body, argument validation, API errors -> isError, the long-poll wait parameter, the HTTP
bearer check and the Origin guard. usage: python3 tests/mcp_test.py"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(N, "..", "mcp", "kalmido_mcp.py")
TOKEN = "abk_" + "t" * 40
FAILS, OKS = [], [0]
REQS = []


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self, method):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        body = json.loads(raw) if raw else None
        q = dict(urllib.parse.parse_qsl(u.query))
        REQS.append({"m": method, "p": u.path, "q": q, "b": body, "auth": self.headers.get("Authorization")})
        code, out = 200, {"ok": True, "path": u.path}
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            code, out = 401, {"error": {"code": "unauthorized", "message": "Missing or invalid API token"}}
        elif u.path.endswith("/tasks/404") or u.path.endswith("/tasks/404/comments"):
            code, out = 404, {"error": {"code": "not_found", "message": "Not found"}}
        elif u.path == "/api/v1/tasks/7/comments" and method == "GET":
            out = {"data": [{"id": 3, "body": "hi", "reactions": [{"emoji": "up", "count": 1}], "suggestion": None}], "next_cursor": None}
        elif u.path == "/api/v1/tasks/8/comments" and method == "GET":
            code, out = 403, {"error": {"code": "forbidden", "message": "Collaboration is turned off"}}
        elif u.path == "/api/v1/tasks" and q.get("list_id") in ("98", "99"):  # 2.0.8: pages for the compact rule
            n = 30 if q["list_id"] == "99" else 3
            out = {"data": [{"id": i, "title": f"T{i}", "notes": "long notes " * 20, "list_id": int(q["list_id"]), "section_id": None,
                             "parent_id": None, "status": "open", "due": None, "due_time": None, "priority": "none", "tags": [],
                             "list_tags": [], "assignee_id": None, "created_at": "2026-09-30T00:00:00Z"} for i in range(1, n + 1)],
                   "next_cursor": None}
        elif u.path == "/api/v1/agent/events":
            out = {"data": [], "cursor": int(q.get("since", 0)), "has_more": False}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._do("GET")

    def do_POST(self):
        self._do("POST")

    def do_PATCH(self):
        self._do("PATCH")

    def do_PUT(self):
        self._do("PUT")

    def do_DELETE(self):
        self._do("DELETE")


stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=stub.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{stub.server_port}"
ENV = {**os.environ, "KALMIDO_URL": BASE + "/", "KALMIDO_TOKEN": TOKEN}


class Stdio:
    def __init__(self, env=ENV):
        self.p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=env)
        self.i = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.i += 1
            msg["id"] = self.i
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        return None if notify else json.loads(self.p.stdout.readline())

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)
        return self.p.stderr.read()


def call(s, name, args):
    return s.send("tools/call", {"name": name, "arguments": args})["result"]


def last():
    return REQS[-1]


# ---- stdio
s = Stdio()
r = s.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
check(r["result"]["protocolVersion"] == "2025-06-18", "initialize echoes 2025-06-18")
check(r["result"]["capabilities"].get("tools") is not None and r["result"]["serverInfo"]["name"] == "kalmido", "initialize: tools capability + name")
check(s.send("notifications/initialized", notify=True) is None, "initialized notification")
s2 = s.send("initialize", {"protocolVersion": "1999-01-01"})
check(s2["result"]["protocolVersion"] == "2025-06-18", "unknown protocol -> latest supported")
check(s.send("initialize", {"protocolVersion": "2024-11-05"})["result"]["protocolVersion"] == "2024-11-05", "older protocol accepted")
check(s.send("ping")["result"] == {}, "ping")
check(s.send("nope/x")["error"]["code"] == -32601, "unknown method -> -32601")

tools = s.send("tools/list")["result"]["tools"]
names = {t["name"] for t in tools}
want = {"list_lists", "list_tasks", "search_tasks", "get_task", "create_task", "update_task", "complete_task", "add_comment", "react",
        "set_status", "list_events", "wait_for_events", "get_agent", "create_job", "update_job", "list_jobs", "send_chat", "list_chats",
        "tidy_task", "list_list_tags", "set_waiting", "clear_waiting", "list_waiting", "report_usage", "get_usage", "get_job",
        "submit_proposal", "chat_typing", "get_project_overview", "react_to_chat",
        "list_groups", "list_list_groups", "get_day_plan", "get_day_review"}  # 2.10.0
check(want <= names, f"all tools listed (missing {want - names})")
check(all(isinstance(t["inputSchema"], dict) and t["inputSchema"].get("type") == "object" and t["description"] for t in tools),
      "every tool has an object schema + description")

CASES = [
    ("get_agent", {}, "GET", "/api/v1/agent", None, {}),
    ("list_lists", {}, "GET", "/api/v1/lists", None, {}),
    ("list_groups", {}, "GET", "/api/v1/groups", None, {}),  # 2.10.0 (#441)
    ("list_list_groups", {"list_id": 4}, "GET", "/api/v1/lists/4/groups", None, {}),
    ("get_day_plan", {"date": "2031-05-01", "mode": "fill"}, "GET", "/api/v1/dayplan", None, {"date": "2031-05-01", "mode": "fill"}),  # 2.10.0 (#440)
    ("get_day_review", {}, "GET", "/api/v1/dayplan/review", None, {}),
    ("list_list_tags", {"list_id": 4}, "GET", "/api/v1/lists/4/tags", None, {}),
    ("list_tasks", {"list_id": 4, "status": "all", "list_tag": "bug", "assignee": "me", "limit": 20}, "GET", "/api/v1/tasks", None,
     {"list_id": "4", "status": "all", "list_tag": "bug", "assignee": "me", "limit": "20"}),
    ("search_tasks", {"q": "milk"}, "GET", "/api/v1/search", None, {"q": "milk"}),
    ("create_task", {"title": "T", "list_id": 4, "list_tags": ["bug"], "priority": "high"}, "POST", "/api/v1/tasks",
     {"title": "T", "list_id": 4, "list_tags": ["bug"], "priority": "high"}, {}),
    ("update_task", {"task_id": 7, "title": "U", "due": None}, "PATCH", "/api/v1/tasks/7", {"title": "U", "due": None}, {}),
    ("complete_task", {"task_id": 7}, "POST", "/api/v1/tasks/7/complete", None, {}),
    ("add_comment", {"task_id": 7, "body": "hello"}, "POST", "/api/v1/tasks/7/comments", {"body": "hello"}, {}),
    ("add_comment", {"task_id": 7, "body": "s", "suggestion": {"title": "Short", "list_tags": ["x"]}}, "POST", "/api/v1/tasks/7/comments",
     {"body": "s", "suggestion": {"title": "Short", "list_tags": ["x"]}}, {}),
    ("react", {"comment_id": 3, "emoji": "up"}, "POST", "/api/v1/comments/3/reactions", {"emoji": "up"}, {}),
    ("react", {"comment_id": 3, "emoji": "down", "remove": True}, "DELETE", "/api/v1/comments/3/reactions/down", None, {}),
    ("react", {"comment_id": 3, "emoji": "🚀", "remove": True}, "DELETE", "/api/v1/comments/3/reactions/%F0%9F%9A%80", None, {}),
    ("set_status", {"status": "working", "text": "on #7"}, "PUT", "/api/v1/agent/status", {"status": "working", "text": "on #7"}, {}),
    ("set_status", {"status": "working", "text": "on #7", "task_id": 7}, "PUT", "/api/v1/agent/status", {"status": "working", "text": "on #7", "task_id": 7}, {}),
    ("list_events", {"since": 12, "limit": 50}, "GET", "/api/v1/agent/events", None, {"since": "12", "limit": "50"}),
    ("wait_for_events", {"since": 12, "wait": 1}, "GET", "/api/v1/agent/events", None, {"since": "12", "wait": "1"}),
    ("list_jobs", {"state": "running"}, "GET", "/api/v1/agent/jobs", None, {"state": "running"}),
    ("create_job", {"title": "Build", "task_id": 7, "state": "waiting"}, "POST", "/api/v1/agent/jobs",
     {"title": "Build", "task_id": 7, "state": "waiting"}, {}),
    ("update_job", {"job_id": 5, "state": "done", "append_log": "ok"}, "PATCH", "/api/v1/agent/jobs/5", {"state": "done", "append_log": "ok"}, {}),
    ("list_chats", {"since": 2}, "GET", "/api/v1/agent/chats", None, {"since": "2"}),
    ("send_chat", {"user_id": 1, "body": "hi", "task_id": 7}, "POST", "/api/v1/agent/chats/1", {"body": "hi", "task_id": 7}, {}),
    ("tidy_task", {"task_id": 7, "title": "Short", "list_tags": ["bug"]}, "POST", "/api/v1/tasks/7/tidy", {"title": "Short", "list_tags": ["bug"]}, {}),
    # 2.1.0 (#335) waiting on external
    ("set_waiting", {"task_id": 7, "note": "the client", "until": "2031-01-02"}, "PUT", "/api/v1/tasks/7/waiting", {"note": "the client", "until": "2031-01-02"}, {}),
    ("set_waiting", {"task_id": 7, "until": None}, "PUT", "/api/v1/tasks/7/waiting", {"until": None}, {}),
    ("clear_waiting", {"task_id": 7}, "DELETE", "/api/v1/tasks/7/waiting", None, {}),
    ("list_waiting", {"list_id": 4}, "GET", "/api/v1/tasks", None, {"waiting": "true", "list_id": "4"}),
    ("list_tasks", {"list_id": 4, "waiting": False}, "GET", "/api/v1/tasks", None, {"waiting": "false"}),
    # 2.1.1 (#326) usage
    ("report_usage", {"model": "claude-x", "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 7, "cost_usd": 0.01, "task_id": 7, "note": "hi"},
     "POST", "/api/v1/agent/usage", {"model": "claude-x", "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 7, "cost_usd": 0.01, "task_id": 7, "note": "hi"}, {}),
    ("get_usage", {"group": "task", "from": "2031-01-01"}, "GET", "/api/v1/agent/usage", None, {"group": "task", "from": "2031-01-01"}),
    # 2.2.0 (#271 / #339) code
    ("list_repos", {"list_id": 4}, "GET", "/api/v1/lists/4/repos", None, {}),
    ("get_project_overview", {"list_id": 4}, "GET", "/api/v1/lists/4/overview", None, {}),  # 2.7.1 (#410)
    ("request_merge_approval", {"task_id": 7, "pr_url": "https://github.com/acme/app/pull/12", "summary": "Adds X"}, "POST", "/api/v1/tasks/7/comments",
     {"body": "Ready to merge: https://github.com/acme/app/pull/12\n\nAdds X",
      "suggestion": {"kind": "merge_request", "pr_url": "https://github.com/acme/app/pull/12", "summary": "Adds X"}}, {}),    # 2.3.0 (#260-#263) proposals
    ("get_job", {"job_id": 5}, "GET", "/api/v1/agent/jobs/5", None, {}),
    ("submit_proposal", {"job_id": 5, "proposal": {"kind": "subtasks", "items": [{"title": "A"}, {"title": "B"}], "dependencies": [[1, 0]]}},
     "POST", "/api/v1/agent/jobs/5/proposal", {"kind": "subtasks", "items": [{"title": "A"}, {"title": "B"}], "dependencies": [[1, 0]]}, {}),
    # 2.4.1 (#375) typing dots in a person's chat
    ("chat_typing", {"chat_user_id": 3}, "POST", "/api/v1/agent/typing", {"chat_user_id": 3}, {}),
    # 2.7.2 (#421) reactions on chat messages
    ("react_to_chat", {"user_id": 3, "message_id": 41, "emoji": "up"}, "POST", "/api/v1/agent/chats/3/messages/41/reactions", {"emoji": "up", "on": True}, {}),
    ("react_to_chat", {"user_id": 3, "message_id": 41, "emoji": "heart", "remove": True}, "POST", "/api/v1/agent/chats/3/messages/41/reactions", {"emoji": "heart", "on": False}, {}),
]
for name, args, m, p, b, q in CASES:
    n0 = len(REQS)
    res = call(s, name, args)
    rq = last() if len(REQS) > n0 else {}
    check(res.get("isError") is False, f"{name}: no error ({res})")
    check(rq.get("m") == m and rq.get("p") == p, f"{name}: {m} {p} (got {rq.get('m')} {rq.get('p')})")
    check(rq.get("b") == b, f"{name}: body {b} (got {rq.get('b')})")
    check(all(rq.get("q", {}).get(k) == v for k, v in q.items()), f"{name}: query {q} (got {rq.get('q')})")
    check(rq.get("auth") == "Bearer " + TOKEN, f"{name}: bearer token sent")
    check(isinstance(res.get("structuredContent"), dict) and json.loads(res["content"][0]["text"]) is not None, f"{name}: content")

# 2.0.8 list_tasks compact: true -> fields=compact; not given -> full up to 25, compact above; false -> always full
res = call(s, "list_tasks", {"list_id": 4, "compact": True})
check(last()["q"].get("fields") == "compact" and res["structuredContent"].get("compact") is True, "list_tasks compact=true -> ?fields=compact")
res = call(s, "list_tasks", {"list_id": 98})
got = json.loads(res["content"][0]["text"])
check("fields" not in last()["q"] and "notes" in got["data"][0] and "compact" not in got, "small page without compact: full tasks")
res = call(s, "list_tasks", {"list_id": 99})
got = json.loads(res["content"][0]["text"])
check(got.get("compact") is True and len(got["data"]) == 30 and "notes" not in got["data"][0] and "created_at" not in got["data"][0]
      and set(got["data"][0]) == {"id", "title", "list_id", "section_id", "parent_id", "status", "due", "due_time", "priority", "tags",
                                  "list_tags", "assignee_id"} and "get_task" in got.get("hint", ""), "large page without compact: compact + hint")
got = json.loads(call(s, "list_tasks", {"list_id": 99, "compact": False})["content"][0]["text"])
check("notes" in got["data"][0] and "compact" not in got and "fields" not in last()["q"], "compact=false: full even when large")
check("sections" in next(t for t in tools if t["name"] == "list_lists")["description"], "list_lists mentions the sections")

# get_task: task + comments
n0 = len(REQS)
res = call(s, "get_task", {"task_id": 7})
got = json.loads(res["content"][0]["text"])
check([x["p"] for x in REQS[n0:]] == ["/api/v1/tasks/7", "/api/v1/tasks/7/comments"], "get_task: task + comments")
check(got["comments"][0]["reactions"][0]["emoji"] == "up", "get_task: comments with reactions")
got = json.loads(call(s, "get_task", {"task_id": 8})["content"][0]["text"])
check(got["comments"] == [] and "Collaboration" in got["comments_error"], "get_task: comments refused -> task alone + reason")
# errors
res = call(s, "get_task", {"task_id": 404})
check(res["isError"] is True and "404" in res["content"][0]["text"] and "Not found" in res["content"][0]["text"], "404 -> isError with message")
res = call(s, "set_status", {"status": "sleeping"})
check(res["isError"] is True and "status" in res["content"][0]["text"], "invalid enum -> isError, no request")
res = call(s, "create_task", {})
check(res["isError"] is True and "title" in res["content"][0]["text"], "missing argument -> isError")
res = call(s, "update_task", {"task_id": "7"})
check(res["isError"] is True, "wrong type -> isError")
res = call(s, "list_lists", {"x": 1})
check(res["isError"] is True, "unknown argument -> isError")
check(s.send("tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32602, "unknown tool -> -32602")
# long poll: wait capped at 60 by schema
res = call(s, "wait_for_events", {"since": 0, "wait": 61})
check(res["isError"] is True, "wait > 60 refused")
err = s.close()
check(TOKEN not in err, "stdio: token never printed")

# wrong token -> API 401 -> isError
s = Stdio({**ENV, "KALMIDO_TOKEN": "abk_wrong"})
s.send("initialize", {"protocolVersion": "2025-06-18"})
res = call(s, "get_agent", {})
check(res["isError"] is True and "401" in res["content"][0]["text"], "bad token -> 401 isError")
s.close()
# missing config
s = Stdio({k: v for k, v in os.environ.items() if k not in ("KALMIDO_URL", "KALMIDO_TOKEN")})
s.send("initialize", {})
res = call(s, "get_agent", {})
check(res["isError"] is True and "KALMIDO_URL" in res["content"][0]["text"], "missing config -> isError")
s.close()

# ---- HTTP
sk = socket.socket()
sk.bind(("127.0.0.1", 0))
port = sk.getsockname()[1]
sk.close()
hp = subprocess.Popen([sys.executable, MCP, "--http", "--port", str(port)], env={**ENV, "MCP_HTTP_TOKEN": "mcpsecret"},
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
U = f"http://127.0.0.1:{port}/mcp"


def post(obj, token="mcpsecret", origin=None, url=U):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        h["Authorization"] = "Bearer " + token
    if origin:
        h["Origin"] = origin
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", port), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)
code, j = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
check(code == 200 and j["result"]["protocolVersion"] == "2025-03-26", "http: initialize")
code, j = post({"jsonrpc": "2.0", "method": "notifications/initialized"})
check(code == 202 and j is None, "http: notification -> 202")
code, j = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
check(code == 200 and want <= {t["name"] for t in j["result"]["tools"]}, "http: tools/list")
n0 = len(REQS)
code, j = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wait_for_events", "arguments": {"since": 5, "wait": 2}}})
check(code == 200 and j["result"]["isError"] is False and REQS[-1]["q"].get("wait") == "2", "http: wait_for_events passes wait")
code, j = post([{"jsonrpc": "2.0", "id": 4, "method": "ping"}, {"jsonrpc": "2.0", "id": 5, "method": "ping"}])
check(code == 200 and isinstance(j, list) and len(j) == 2, "http: batch")
check(post({"jsonrpc": "2.0", "id": 6, "method": "ping"}, token=None)[0] == 401, "http: missing bearer -> 401")
check(post({"jsonrpc": "2.0", "id": 6, "method": "ping"}, token="wrong")[0] == 401, "http: wrong bearer -> 401")
check(post({"jsonrpc": "2.0", "id": 7, "method": "ping"}, origin="https://evil.example")[0] == 403, "http: foreign Origin -> 403")
check(post({"jsonrpc": "2.0", "id": 8, "method": "ping"}, origin="http://localhost:3000")[0] == 200, "http: localhost Origin ok")
check(post({"jsonrpc": "2.0", "id": 9, "method": "ping"}, url=f"http://127.0.0.1:{port}/other")[0] == 404, "http: other path -> 404")
code, j = post("not json")
check(code == 200 and j["error"]["code"] == -32600, "http: invalid request")
hp.terminate()
out, err = hp.communicate(timeout=5)
check(TOKEN not in out + err and "mcpsecret" not in out + err, "http: tokens never printed")

h = subprocess.run([sys.executable, MCP, "--help"], capture_output=True, text=True, env=ENV)
check(h.returncode == 0 and "--http" in h.stdout and TOKEN not in h.stdout, "--help")

stub.shutdown()
print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
