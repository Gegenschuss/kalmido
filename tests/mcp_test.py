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
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
REQS = []
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40
BIN = {"/api/v1/attachments/5": ("image/png", PNG, "Bildschirmfoto 1.png"),
       "/api/v1/chat-attachments/9": ("text/plain; charset=utf-8", b"hello log", "log.txt"),
       "/api/v1/attachments/6": ("application/pdf", b"%PDF" + b"0" * 100, "big.pdf"),
       "/api/v1/wiki/files/11": ("image/png", PNG, "Sketch.png"), "/api/v1/wiki/files/12": ("application/pdf", b"%PDF-1.4 x", "Offer.pdf")}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self, method):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ct = self.headers.get("Content-Type") or ""
        body = {"multipart": raw, "ctype": ct} if ct.startswith("multipart/") else json.loads(raw) if raw else None
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
        elif u.path in ("/api/v1/wiki/files/11/text", "/api/v1/wiki/files/12/text"):  # 2.488.0 (#2209)
            out = {"id": 11, "name": "Sketch.png", "size": len(PNG), "kind": "image", "text": None} if "/11/" in u.path else \
                {"id": 12, "name": "Offer.pdf", "kind": "pdf", "text": "Offer for the shoot", "chars": 19}
        elif u.path == "/api/v1/agent/events":
            out = {"data": [], "cursor": int(q.get("since", 0)), "has_more": False}
        # 2.13.1 (#465): binary answers for get_attachment
        if code == 200 and u.path in BIN:
            mime, data, name = BIN[u.path]
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{urllib.parse.quote(name)}")
            self.end_headers()
            self.wfile.write(data)
            return
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
want = {"list_lists", "list_tasks", "search", "get_task", "create_task", "update_task", "complete_task", "add_comment", "react",
        "set_status", "list_events", "wait_for_events", "get_agent", "create_job", "update_job", "list_jobs", "send_chat", "list_chats",
        "tidy_task", "list_list_tags", "set_waiting", "clear_waiting", "list_waiting", "report_usage", "get_usage", "get_job",
        "submit_proposal", "chat_typing", "get_project_overview", "react_to_chat",
        "list_groups", "list_list_groups", "get_day_plan", "get_day_review",  # 2.10.0
        "list_attachments", "get_attachment",  # 2.13.1 (#465)
        "set_list_columns"}  # 2.14.0 (#425)
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
    ("search", {"q": "milk", "kind": "tasks"}, "GET", "/api/v1/search", None, {"q": "milk", "kind": "tasks"}),  # 2.1026.0 (#5280): search_tasks -> search kind tasks
    # 2.1026.0 (#5280): ONE search tool; each kind carries its own filters only, chat_with -> agent, the flags -> "1"
    ("search", {"q": "milk"}, "GET", "/api/v1/search", None, {"q": "milk", "kind": "all"}),
    ("search", {"q": "milk", "kind": "tasks", "semantic": True, "fulltext": True, "cursor": "c1"}, "GET", "/api/v1/search", None,
     {"q": "milk", "kind": "tasks", "semantic": "1", "fulltext": "1", "cursor": "c1"}),
    ("search", {"q": "plan", "kind": "messages", "art": "c,t", "chat_with": 3, "task": 7, "space": "x"}, "GET", "/api/v1/search", None,
     {"q": "plan", "kind": "messages", "art": "c,t", "agent": "3", "task": "7"}),
    ("search", {"kind": "contacts", "trash": 1, "book_id": 2}, "GET", "/api/v1/search", None, {"kind": "contacts", "trash": "1", "book_id": "2"}),
    ("search", {"q": "memo", "kind": "notes", "list_id": 4}, "GET", "/api/v1/search", None, {"q": "memo", "kind": "notes", "list_id": "4"}),
    ("search", {"q": "invoice", "kind": "files", "space": "org:3", "limit": 9}, "GET", "/api/v1/search", None,
     {"q": "invoice", "kind": "files", "space": "org:3"}),
    ("search", {"q": "Muller", "kind": "wiki", "space": "private", "limit": 10}, "GET", "/api/v1/search", None,
     {"q": "Muller", "kind": "wiki", "space": "private", "limit": "10"}),
    ("search", {"q": "Dentist", "kind": "events", "limit": 5}, "GET", "/api/v1/search", None, {"q": "Dentist", "kind": "events", "limit": "5"}),
    ("create_task", {"title": "T", "list_id": 4, "list_tags": ["bug"], "priority": "high"}, "POST", "/api/v1/tasks",
     {"title": "T", "list_id": 4, "list_tags": ["bug"], "priority": "high"}, {}),
    ("update_task", {"task_id": 7, "title": "U", "due": None}, "PATCH", "/api/v1/tasks/7", {"title": "U", "due": None}, {}),
    ("complete_task", {"task_id": 7}, "POST", "/api/v1/tasks/7/complete", None, {}),
    ("complete_task", {"task_id": 7, "expect_due": "2031-05-01"}, "POST", "/api/v1/tasks/7/complete", {"expect_due": "2031-05-01"}, {}),  # 2.270.0 C (#3022)
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
    ("get_reply_style", {"user_id": 3}, "GET", "/api/v1/agent/chats/3/reply-style", None, {}),  # 2.491.0 (#2849)
    ("send_chat", {"user_id": 1, "body": "hi", "task_id": 7}, "POST", "/api/v1/agent/chats/1", {"body": "hi", "task_id": 7}, {}),
    ("tidy_task", {"task_id": 7, "title": "Short", "list_tags": ["bug"]}, "POST", "/api/v1/tasks/7/tidy", {"title": "Short", "list_tags": ["bug"]}, {}),
    # 2.1.0 (#335) waiting on external
    ("set_waiting", {"task_id": 7, "note": "the client", "until": "2031-01-02"}, "PUT", "/api/v1/tasks/7/waiting", {"note": "the client", "until": "2031-01-02"}, {}),
    ("set_waiting", {"task_id": 7, "until": None}, "PUT", "/api/v1/tasks/7/waiting", {"until": None}, {}),
    ("clear_waiting", {"task_id": 7}, "DELETE", "/api/v1/tasks/7/waiting", None, {}),
    ("list_waiting", {"list_id": 4}, "GET", "/api/v1/tasks", None, {"waiting": "true", "list_id": "4"}),
    ("list_tasks", {"list_id": 4, "waiting": False}, "GET", "/api/v1/tasks", None, {"waiting": "false"}),
    ("list_stale_tasks", {"list_id": 4, "days": 10}, "GET", "/api/v1/stale", None, {"list_id": "4", "days": "10"}),  # 2.34.0 (#266)
    ("get_time_gaps", {"user_id": 2, "days": 7}, "GET", "/api/v1/time/gaps", None, {"user_id": "2", "days": "7"}),  # 2.34.0 (#269)
    # 2.1.1 (#326) usage
    ("report_usage", {"model": "claude-x", "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 7, "cost_usd": 0.01, "task_id": 7, "note": "hi"},
     "POST", "/api/v1/agent/usage", {"model": "claude-x", "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 7, "cost_usd": 0.01, "task_id": 7, "note": "hi"}, {}),
    ("get_usage", {"group": "task", "from": "2031-01-01"}, "GET", "/api/v1/agent/usage", None, {"group": "task", "from": "2031-01-01"}),
    # 2.33.0 (#1045) the usage ring
    ("report_plan_usage", {"rate_limits": {"seven_day": {"used_percentage": 41.2, "resets_at": 1999999999}}, "limit": 90}, "PUT", "/api/v1/agent/quota",
     {"rate_limits": {"seven_day": {"used_percentage": 41.2, "resets_at": 1999999999}}, "limit": 90}, {}),
    ("report_plan_usage", {"windows": [{"label": "Week", "percent": 12}]}, "PUT", "/api/v1/agent/quota", {"windows": [{"label": "Week", "percent": 12}]}, {}),
    ("get_plan_usage", {}, "GET", "/api/v1/agent/quota", None, {}),
    ("clear_plan_usage", {}, "DELETE", "/api/v1/agent/quota", None, {}),
    ("list_schedules", {}, "GET", "/api/v1/agent/schedules", None, {}),  # 2.34.0 (#272)
    # 2.2.0 (#271 / #339) code
    ("list_repos", {"list_id": 4}, "GET", "/api/v1/lists/4/repos", None, {}),
    ("get_waiting", {"user_id": 5}, "GET", "/api/v1/me/waiting", None, {"user_id": "5"}),  # 2.392.0 D (#3369)
    ("get_delivery_report", {"list_id": 7, "date": "2026-11-01"}, "GET", "/api/v1/lists/7/delivery-report", None, {"date": "2026-11-01"}),
    ("export_brief", {"task_ids": [3, 9], "lang": "de"}, "POST", "/api/v1/tasks/brief", {"task_ids": [3, 9], "lang": "de"}, {}),  # 2.392.3 (#3368)
    ("partial_task", {"task_id": 7, "version": "2.5", "note": "left"}, "POST", "/api/v1/tasks/7/partial", {"version": "2.5", "note": "left"}, {}),  # 2.392.0 B (#3364)
    ("list_build_status", {"list_id": 4}, "GET", "/api/v1/lists/4/build-status", None, {}),  # 2.151.0 A (#2558)
    ("get_project_overview", {"list_id": 4}, "GET", "/api/v1/lists/4/overview", None, {}),  # 2.7.1 (#410)
    # 2.657.0 (#5052): set_list_columns requires the version read (expect_updated_at), it goes along
    ("set_list_columns", {"list_id": 4, "columns": ["id", "due", "f:3"], "expect_updated_at": "v1"}, "PATCH", "/api/v1/lists/4",
     {"columns": ["id", "due", "f:3"], "expect_updated_at": "v1"}, {}),  # 2.14.0
    ("set_list_columns", {"list_id": 4, "columns": None, "expect_updated_at": "v1"}, "PATCH", "/api/v1/lists/4", {"columns": None, "expect_updated_at": "v1"}, {}),
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
    # 2.13.1 (#465) attachments
    ("list_attachments", {"task_id": 7}, "GET", "/api/v1/tasks/7/attachments", None, {}),
    # 2.391.0 C (#3362): setting up integrations (people's scripts; an agent never has the scope)
    ("list_webhooks", {}, "GET", "/api/v1/me/webhooks", None, {}),
    ("list_webhooks", {"org_id": 3}, "GET", "/api/v1/orgs/3/webhooks", None, {}),
    ("create_webhook", {"url": "https://example.com/h", "events": ["task.created"]}, "POST", "/api/v1/me/webhooks",
     {"url": "https://example.com/h", "events": ["task.created"]}, {}),
    ("rotate_webhook_secret", {"webhook_id": 5, "org_id": 3}, "POST", "/api/v1/orgs/3/webhooks/5/secret", None, {}),
    ("create_api_token", {"name": "ci", "scopes": ["read"], "expires_days": 7}, "POST", "/api/v1/me/tokens",
     {"name": "ci", "scopes": ["read"], "expires_days": 7}, {}),
    ("revoke_api_token", {"token_id": 9}, "DELETE", "/api/v1/me/tokens/9", None, {}),
    ("add_repo_connection", {"list_id": 4, "repo": "acme/app"}, "POST", "/api/v1/lists/4/repos", {"repo": "acme/app"}, {}),
    ("set_repo_version_field", {"list_id": 4, "field": "auto"}, "PUT", "/api/v1/lists/4/repos/version-field", {"field": "auto"}, {}),
    ("remove_repo_connection", {"repo_id": 2}, "DELETE", "/api/v1/repos/2", None, {}),
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

# 2.1026.0 (#5280): the filter of another kind is not sent (space on messages, limit on files), the old tools are gone
call(s, "search", {"q": "plan", "kind": "messages", "space": "x", "list_id": 4})
check("space" not in last()["q"] and "list_id" not in last()["q"], f"search messages: no foreign filter (got {last()['q']})")
call(s, "search", {"q": "invoice", "kind": "files", "limit": 9})
check("limit" not in last()["q"], f"search files: no limit (got {last()['q']})")
check(not names & {"search_tasks", "search_messages", "search_contacts", "search_files", "search_notes"}, "the five old search tools are gone")
check(next(t for t in tools if t["name"] == "search")["inputSchema"]["properties"]["kind"]["enum"]
      == ["all", "tasks", "messages", "contacts", "notes", "files", "wiki", "events"], "search: the kinds (never office)")

# 2.13.1 (#465): get_attachment -> base64 + mime / name; an image also as an MCP image item; the size cap; chat files;
# send_chat with files -> multipart
import base64  # noqa: E402
res = call(s, "get_attachment", {"attachment_id": 5})
check(last()["p"] == "/api/v1/attachments/5" and res["isError"] is False, "get_attachment: GET /attachments/5")
sc = res["structuredContent"]
check(base64.b64decode(sc["base64"]) == PNG and sc["mime"] == "image/png" and sc["name"] == "Bildschirmfoto 1.png" and sc["size"] == len(PNG),
      "get_attachment: base64, mime, name, size")
check(res["content"][1]["type"] == "image" and res["content"][1]["mimeType"] == "image/png" and base64.b64decode(res["content"][1]["data"]) == PNG
      and "base64" not in json.loads(res["content"][0]["text"]), "get_attachment: image item for the model, text without base64")
res = call(s, "get_attachment", {"attachment_id": 9, "source": "chat"})
check(last()["p"] == "/api/v1/chat-attachments/9" and base64.b64decode(res["structuredContent"]["base64"]) == b"hello log"
      and res["structuredContent"]["mime"] == "text/plain" and [x["type"] for x in res["content"]] == ["text", "text"],  # 2.126.0 (#1978): + the data note
      "get_attachment source chat: text file, no image item")
res = call(s, "get_attachment", {"attachment_id": 6, "max_bytes": 50})
check(res["isError"] is True and "max_bytes=50" in res["content"][0]["text"], "get_attachment: over max_bytes -> isError")
check(call(s, "get_attachment", {"attachment_id": 6, "max_bytes": 30 * 1024 * 1024})["isError"] is True, "get_attachment: max_bytes above 20 MB refused")
res = call(s, "send_chat", {"user_id": 1, "body": "see", "task_id": 7, "files": [{"name": "a.png", "base64": base64.b64encode(PNG).decode(), "mime": "image/png"}]})
rq = last()
check(res["isError"] is False and rq["p"] == "/api/v1/agent/chats/1" and rq["b"]["ctype"].startswith("multipart/form-data; boundary=")
      and b'name="body"\r\n\r\nsee' in rq["b"]["multipart"] and b'name="task_id"\r\n\r\n7' in rq["b"]["multipart"]
      and b'name="file"; filename="a.png"\r\nContent-Type: image/png' in rq["b"]["multipart"] and PNG in rq["b"]["multipart"],
      "send_chat with files -> multipart (body, task_id, file)")
check(call(s, "send_chat", {"user_id": 1, "files": [{"name": "x", "base64": "%%%"}]})["isError"] is True, "send_chat: bad base64 -> isError")
# 2.1048.0 (#5861): wiki_append sends only the added text (POST /wiki/pages/{id}/append), never a body
res = call(s, "wiki_append", {"page_id": 4, "text": "- a link"})
check(res["isError"] is False and last()["m"] == "POST" and last()["p"] == "/api/v1/wiki/pages/4/append" and last()["b"] == {"text": "- a link"},
      f"wiki_append: POST /wiki/pages/4/append with the text only {last()}")
# 2.1068.0 (#5829): under (a heading) goes along
res = call(s, "wiki_append", {"page_id": 4, "text": "- a link", "under": "Links"})
check(res["isError"] is False and last()["b"] == {"text": "- a link", "under": "Links"}, f"wiki_append: under goes along {last()}")
# 2.1082.0 (#5830): the targeted changes send only the change (append / replace one section), never the whole text
for tool, args, path, body in (
        ("wiki_replace_section", {"page_id": 4, "heading": "Setup", "text": "x", "expect_updated_at": "v"}, "/api/v1/wiki/pages/4/replace-section",
         {"heading": "Setup", "text": "x", "expect_updated_at": "v"}),
        ("task_notes_append", {"task_id": 7, "text": "- found", "under": "Plan"}, "/api/v1/tasks/7/notes/append", {"text": "- found", "under": "Plan"}),
        ("task_notes_replace_section", {"task_id": 7, "heading": "Plan", "text": "y", "expect_updated_at": "v"}, "/api/v1/tasks/7/notes/replace-section",
         {"heading": "Plan", "text": "y", "expect_updated_at": "v"}),
        ("project_overview_append", {"list_id": 3, "text": "z"}, "/api/v1/lists/3/overview/append", {"text": "z"}),
        ("project_overview_replace_section", {"list_id": 3, "heading": "Goal", "text": "z", "expect_updated_at": ""},
         "/api/v1/lists/3/overview/replace-section", {"heading": "Goal", "text": "z", "expect_updated_at": ""})):
    res = call(s, tool, args)
    check(res["isError"] is False and last()["m"] == "POST" and last()["p"] == path and last()["b"] == body, f"{tool}: POST {path} {last()}")
# 2.488.0 (#2209): wiki_files lists a page's files; wiki_read_file reads one as text (a PDF) or the bytes (a picture: an image item)
res = call(s, "wiki_files", {"page_id": 4})
check(res["isError"] is False and last()["p"] == "/api/v1/wiki/pages/4/files" and last()["m"] == "GET", "wiki_files: GET /wiki/pages/4/files")
res = call(s, "wiki_read_file", {"file_id": 12, "max_chars": 500})
check(res["isError"] is False and last()["p"] == "/api/v1/wiki/files/12/text" and last()["q"] == {"max_chars": "500"}
      and res["structuredContent"].get("text") == "Offer for the shoot", "wiki_read_file: a PDF as text (GET /wiki/files/12/text)")
res = call(s, "wiki_read_file", {"file_id": 11})
check(res["isError"] is False and [r["p"] for r in REQS[-2:]] == ["/api/v1/wiki/files/11/text", "/api/v1/wiki/files/11"]
      and base64.b64decode(res["structuredContent"]["base64"]) == PNG and res["content"][1]["type"] == "image"
      and res["content"][1]["mimeType"] == "image/png", "wiki_read_file: a picture comes back as an image item")
res = call(s, "wiki_read_file", {"file_id": 12, "as": "base64"})
check(res["isError"] is False and last()["p"] == "/api/v1/wiki/files/12" and res["structuredContent"]["mime"] == "application/pdf"
      and base64.b64decode(res["structuredContent"]["base64"]) == b"%PDF-1.4 x" and [x["type"] for x in res["content"]] == ["text", "text"],
      "wiki_read_file as base64: the PDF's bytes, no image item")
check(call(s, "wiki_read_file", {"file_id": 11, "as": "base64", "max_bytes": 10})["isError"] is True, "wiki_read_file: over max_bytes -> isError")
check(call(s, "send_chat", {"user_id": 1})["isError"] is True, "send_chat: neither body nor files -> isError")

# 2.0.8 list_tasks compact: true -> fields=compact; not given -> full up to 25, compact above; false -> always full
res = call(s, "list_tasks", {"list_id": 4, "compact": True})
check(last()["q"].get("fields") == "compact" and res["structuredContent"].get("compact") is True, "list_tasks compact=true -> ?fields=compact")
res = call(s, "list_tasks", {"list_id": 98})
got = json.loads(res["content"][0]["text"])
check("fields" not in last()["q"] and "notes" in got["data"][0] and "compact" not in got, "small page without compact: full tasks")
res = call(s, "list_tasks", {"list_id": 99})
got = json.loads(res["content"][0]["text"])
check(got.get("compact") is True and len(got["data"]) == 30 and "notes" not in got["data"][0] and "created_at" not in got["data"][0]
      and set(got["data"][0]) == {"id", "title", "list_id", "section_id", "section_kind", "parent_id", "status", "due", "due_time", "priority", "tags",
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
# 2.126.0 (#1979 G2): --http needs MCP_HTTP_TOKEN (16+ characters)
nt = subprocess.run([sys.executable, MCP, "--http", "--port", str(port)], env={k: v for k, v in ENV.items() if k != "MCP_HTTP_TOKEN"},
                    capture_output=True, text=True, timeout=20)
check(nt.returncode == 2 and "MCP_HTTP_TOKEN" in nt.stderr, f"http: no MCP_HTTP_TOKEN -> does not start ({nt.returncode})")
nt = subprocess.run([sys.executable, MCP, "--http", "--port", str(port)], env={**ENV, "MCP_HTTP_TOKEN": "short"}, capture_output=True, text=True, timeout=20)
check(nt.returncode == 2, "http: a too short MCP_HTTP_TOKEN -> does not start")
hp = subprocess.Popen([sys.executable, MCP, "--http", "--port", str(port)], env={**ENV, "MCP_HTTP_TOKEN": "mcpsecret-0123456789"},
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
U = f"http://127.0.0.1:{port}/mcp"


def post(obj, token="mcpsecret-0123456789", origin=None, url=U):
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
