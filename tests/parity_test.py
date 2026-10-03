#!/usr/bin/env python3
"""2.15.0 (#479) parity: what people can do in the app, agents can do through the API and the MCP server.
No container needed. Reads app.py and mcp/kalmido_mcp.py:
 1. every route the web client has (/api/..., not /api/v1) is either mapped to the REST API route(s) that do the same
    (APP_TO_API) or listed with a reason in APP_ONLY (sign-in, credentials, admin, devices, people's side of approvals ...)
 2. every mapped REST route exists
 3. every REST route is reached by at least one MCP tool (each tool is run against a recording fake API with arguments
    made from its input schema, plus the variants in TOOL_VARIANTS) or listed with a reason in API_ONLY
 4. nothing in the tables is stale (a mapped / listed route that no longer exists, a variant of an unknown tool)
A new app feature without an API route, or a new API route without an MCP tool, fails here until it gets one (or a
documented exception). usage: python3 tests/parity_test.py"""
import importlib.util
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def norm(p):
    return re.sub(r"<[^>]+>", "{}", p)


src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
routes = re.findall(r'^@app\.(get|post|put|patch|delete)\("(/api/[^"]*)"', src, re.M)
APP = {f"{m.upper()} {norm(p)}" for m, p in routes if not p.startswith("/api/v1/")}
API = {f"{m.upper()} {norm(p)[len('/api/v1'):]}" for m, p in routes if p.startswith("/api/v1/")}

# ---- 1. the web client's routes -> the REST API
APP_TO_API = {
    "GET /api/state": ["GET /lists", "GET /tasks", "GET /habits", "GET /filters", "GET /me"],
    "GET /api/tasks": ["GET /tasks", "GET /search", "GET /trash"],
    "GET /api/tasks/{}": ["GET /tasks/{}"],
    "POST /api/tasks": ["POST /tasks", "POST /tasks/{}/subtasks"],
    "PATCH /api/tasks/{}": ["PATCH /tasks/{}"],
    "DELETE /api/tasks/{}": ["DELETE /tasks/{}"],
    "POST /api/tasks/{}/complete": ["POST /tasks/{}/complete"],
    "POST /api/tasks/{}/reopen": ["POST /tasks/{}/reopen"],
    "POST /api/tasks/{}/restore": ["POST /tasks/{}/restore"],
    "POST /api/tasks/{}/skip": ["POST /tasks/{}/skip"],
    "POST /api/tasks/{}/take": ["POST /tasks/{}/take"],
    "PUT /api/tasks/{}/waiting": ["PUT /tasks/{}/waiting"],
    "DELETE /api/tasks/{}/waiting": ["DELETE /tasks/{}/waiting"],
    "POST /api/tasks/{}/attachments": ["POST /tasks/{}/attachments"],
    "POST /api/tasks/{}/comments": ["POST /tasks/{}/comments"],
    "GET /api/tasks/{}/timeline": ["GET /tasks/{}/comments"],
    "GET /api/tasks/{}/deps": ["GET /tasks/{}/dependencies"],
    "POST /api/tasks/reorder": ["POST /tasks/{}/move"],
    "POST /api/tasks/batch": ["POST /tasks/batch"],
    "POST /api/tasks/purge-done": ["POST /tasks/batch"],
    "DELETE /api/trash": ["DELETE /trash"],
    "GET /api/attachments/{}": ["GET /attachments/{}"],
    "DELETE /api/attachments/{}": ["DELETE /attachments/{}"],
    "PATCH /api/comments/{}": ["PATCH /comments/{}"],
    "DELETE /api/comments/{}": ["DELETE /comments/{}"],
    "POST /api/comments/{}/reactions": ["POST /comments/{}/reactions", "DELETE /comments/{}/reactions/{}"],
    "POST /api/deps": ["POST /tasks/{}/dependencies"],
    "DELETE /api/deps/{}/{}": ["DELETE /tasks/{}/dependencies/{}"],
    "POST /api/lists": ["POST /lists"],
    "PATCH /api/lists/{}": ["PATCH /lists/{}"],
    "DELETE /api/lists/{}": ["DELETE /lists/{}"],
    "POST /api/lists/{}/checklist": ["POST /tasks/batch"],
    "POST /api/lists/{}/shift": ["POST /lists/{}/shift"],
    "PUT /api/lists/{}/members": ["PUT /lists/{}/members/{}"],
    "DELETE /api/lists/{}/members/{}": ["DELETE /lists/{}/members/{}"],
    "GET /api/lists/{}/groups": ["GET /lists/{}/groups"],
    "PUT /api/lists/{}/groups/{}": ["PUT /lists/{}/groups/{}"],
    "DELETE /api/lists/{}/groups/{}": ["DELETE /lists/{}/groups/{}"],
    "GET /api/groups": ["GET /groups"],
    "POST /api/lists/{}/owner": ["POST /lists/{}/owner"],
    "PUT /api/lists/{}/bell": ["PATCH /me/notifications"],
    "POST /api/lists/{}/fields": ["POST /lists/{}/fields"],
    "PATCH /api/fields/{}": ["PATCH /fields/{}"],
    "DELETE /api/fields/{}": ["DELETE /fields/{}"],
    "POST /api/lists/{}/tags": ["POST /lists/{}/tags"],
    "PATCH /api/list-tags/{}": ["PATCH /lists/{}/tags/{}"],
    "DELETE /api/list-tags/{}": ["DELETE /lists/{}/tags/{}"],
    "POST /api/sections": ["POST /lists/{}/sections"],
    "PATCH /api/sections/{}": ["PATCH /sections/{}"],
    "DELETE /api/sections/{}": ["DELETE /sections/{}"],
    "POST /api/lists/{}/sections/order": ["PUT /lists/{}/sections/order"],
    "GET /api/lists/{}/overview": ["GET /lists/{}/overview"],
    "PATCH /api/lists/{}/overview": ["PATCH /lists/{}/overview"],
    "POST /api/lists/{}/links": ["POST /lists/{}/links"],
    "PATCH /api/lists/{}/links/{}": ["PATCH /lists/{}/links/{}"],
    "DELETE /api/lists/{}/links/{}": ["DELETE /lists/{}/links/{}"],
    "PUT /api/lists/{}/links/order": ["PUT /lists/{}/links/order"],
    "POST /api/lists/{}/milestones": ["POST /lists/{}/milestones"],
    "PATCH /api/lists/{}/milestones/{}": ["PATCH /lists/{}/milestones/{}"],
    "DELETE /api/lists/{}/milestones/{}": ["DELETE /lists/{}/milestones/{}"],
    "POST /api/lists/{}/files": ["POST /lists/{}/files"],
    "GET /api/list-files/{}": ["GET /lists/{}/files/{}"],
    "DELETE /api/list-files/{}": ["DELETE /lists/{}/files/{}"],
    "GET /api/lists/{}/status": ["GET /lists/{}/overview"],
    "POST /api/lists/{}/status": ["PUT /lists/{}/status"],
    "GET /api/lists/{}/repos": ["GET /lists/{}/repos"],
    "POST /api/filters": ["POST /filters"],
    "PATCH /api/filters/{}": ["PATCH /filters/{}"],
    "DELETE /api/filters/{}": ["DELETE /filters/{}"],
    "POST /api/folders/rename": ["POST /folders/rename"],
    "POST /api/folders/delete": ["POST /folders/delete"],
    "GET /api/templates": ["GET /templates"],
    "POST /api/templates": ["POST /templates"],
    "PATCH /api/templates/{}": ["PATCH /templates/{}"],
    "DELETE /api/templates/{}": ["DELETE /templates/{}"],
    "POST /api/templates/{}/apply": ["POST /templates/{}/apply"],
    "POST /api/habits": ["POST /habits"],
    "PATCH /api/habits/{}": ["PATCH /habits/{}"],
    "DELETE /api/habits/{}": ["DELETE /habits/{}"],
    "POST /api/habits/{}/log": ["POST /habits/{}/checkin"],
    "POST /api/time/start": ["POST /time/timer"],
    "POST /api/time/stop": ["DELETE /time/timer"],
    "GET /api/time/entries": ["GET /time/entries"],
    "POST /api/time/entries": ["POST /time/entries"],
    "PATCH /api/time/entries/{}": ["PATCH /time/entries/{}"],
    "DELETE /api/time/entries/{}": ["DELETE /time/entries/{}"],
    "GET /api/time/report": ["GET /time/entries"],
    "GET /api/time/export.csv": ["GET /time/entries"],
    "GET /api/news": ["GET /news"],
    "POST /api/news/read": ["POST /news/read"],
    "GET /api/roadmap": ["GET /roadmap"],
    "GET /api/dayplan": ["GET /dayplan"],
    "GET /api/dayplan/review": ["GET /dayplan/review"],
    "GET /api/export.json": ["GET /export"],
    "POST /api/import/{}": ["POST /import/{}"],
    "POST /api/import/ticktick": ["POST /import/{}"],
    "POST /api/imports/{}/undo": ["POST /imports/{}/undo"],
    "GET /api/me/app-passwords": ["GET /me/app-passwords"],
    "POST /api/me/app-passwords": ["POST /me/app-passwords"],
    "DELETE /api/me/app-passwords/{}": ["DELETE /me/app-passwords/{}"],
    "GET /api/chat-files/{}": ["GET /chat-attachments/{}"],
    "DELETE /api/chat-files/{}": ["DELETE /chat-attachments/{}"],
    "POST /api/agents/{}/chat/{}/reactions": ["POST /agents/{}/chat/{}/reactions"],
    "GET /api/agents": ["GET /agents"],
}
# app routes with no API counterpart on purpose (prefix match on "METHOD /api/path"; reason first)
APP_ONLY = [
    ("sign-in, sessions, two-factor, passkeys, OIDC: a person in a browser", ("* /api/auth/", "* /api/me/2fa", "* /api/me/passkeys", "=PATCH /api/me", "=GET /api/me")),
    ("credentials and keys of the account: tokens, webhooks, upload token, avatar, phone shortcut", (
        "* /api/me/tokens", "* /api/me/webhooks", "POST /api/me/drop-token", "* /api/me/avatar", "GET /api/me/share/")),
    ("administration: never through a token (agents are never admins); admins read users / status with admin-read", (
        "* /api/admin/", "* /api/users", "GET /api/version", "GET /api/about", "GET /api/health")),
    ("agents are managed by people (admins / owners), not by tokens", ("* /api/my/agents",)),
    ("approvals and proposals come only from people (the agent's side: /agent/jobs, POST /agent/jobs/{id}/proposal)", (
        "* /api/agents/jobs", "* /api/proposals", "POST /api/comments/{}/apply")),
    ("people's side of the agent chat, waking and sharing with agents (the agent uses /agent/*)", (
        "=GET /api/agents/{}/chat", "=POST /api/agents/{}/chat", "POST /api/agents/{}/wake", "POST /api/tasks/{}/wake", "* /api/agents/{}/share",
        "* /api/agents/{}/autoshare", "GET /api/agents/usage")),
    ("devices and pushes of a person", ("* /api/push/", "POST /api/ntfy/test")),
    ("Paperless: never for tokens or agents", ("* /api/paperless", "* /api/tasks/{}/paperless", "POST /api/attachments/{}/to-paperless",
                                             "* /api/lists/{}/paperless")),
    ("public links: sharing outside the instance, people only", ("* /api/lists/{}/public-link",)),
    ("repositories: their secrets are entered by people; the API reads them (GET /lists/{id}/repos)", (
        "POST /api/lists/{}/repos", "* /api/repos/", "POST /api/hooks/git/", "POST /api/tasks/{}/git-undo")),
    ("external calendar subscriptions and the calendar feed link: personal settings", ("* /api/calendars", "* /api/ical")),
    ("the app's personal settings, onboarding and sample data", ("PATCH /api/settings", "POST /api/onboarding", "* /api/sample")),
    ("the focus timer is a personal on-screen timer; time is tracked with /time/timer", ("* /api/pomo/",)),
    ("views computed for the screen (the data is in /tasks, /tasks/{id}/dependencies, /time/entries)", (
        "GET /api/stats", "GET /api/occurrences", "GET /api/deps", "GET /api/imports")),
    ("app conveniences: undo of a completion (= reopen), read markers, News removal, sidebar order, folder of a person's "
     "tag (personal tags change with the task's tags), list owner lookup, icon pictures", (
        "POST /api/tasks/{}/undo", "POST /api/tasks/{}/seen", "POST /api/news/dismiss", "POST /api/lists/reorder", "* /api/tags/",
        "POST /api/lists/{}/tags/promote", "GET /api/lists/{}/owner", "* /api/lists/{}/icon", "GET /api/list-icon/", "GET /api/avatar/",
        "GET /api/admin/lists/orphaned", "GET /api/lists/{}/owner")),
    ("folder shares with groups: people only (sharing of a list with a group: /lists/{id}/groups)", ("* /api/folders/groups",)),
]


def app_only(r):
    m, p = r.split(" ", 1)
    for _, pats in APP_ONLY:
        for pat in pats:
            if pat.startswith("="):  # exact: "=GET /api/me"
                if pat[1:] == r:
                    return True
                continue
            pm, pp = pat.split(" ", 1)
            if (pm in ("*", m)) and (p == pp or p.startswith(pp.rstrip("/") + "/") or (pp.endswith("/") and p.startswith(pp))
                                     or (pm == "*" and p.startswith(pp))):
                return True
    return False


missing = sorted(r for r in APP if r not in APP_TO_API and not app_only(r))
check(not missing, f"app routes without an API route or a documented exception: {missing}")
stale = sorted(r for r in APP_TO_API if r not in APP)
check(not stale, f"APP_TO_API lists routes the app no longer has: {stale}")
both = sorted(r for r in APP_TO_API if app_only(r))
check(not both, f"routes both mapped and excepted: {both}")
# ---- 2. the mapped API routes exist
gone = sorted({x for v in APP_TO_API.values() for x in v if x not in API})
check(not gone, f"mapped API routes that do not exist: {gone}")
for pats in (x[1] for x in APP_ONLY):
    for pat in pats:
        if pat.startswith("="):
            check(pat[1:] in APP, f"APP_ONLY entry matches nothing: {pat}")
            continue
        pm, pp = pat.split(" ", 1)
        check(any((pm in ("*", r.split(" ", 1)[0])) and r.split(" ", 1)[1].startswith(pp) for r in APP), f"APP_ONLY entry matches nothing: {pat}")

# ---- 3. every API route has an MCP tool
spec = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)
CALLS = {}


PATS = sorted(((r, re.compile("^" + re.escape(r).replace(re.escape("{}"), "[^/]+") + "$")) for r in API), key=lambda x: x[0].count("{}"))


def route_of(method, path):
    """The API route a concrete call hits (literal segments before placeholders, as Flask matches them)."""
    return next((r for r, rx in PATS if rx.match(f"{method} {path}")), f"{method} {path}")


class Rec:
    def call(self, method, path, query=None, body=None, timeout=None, multipart=None, binary_cap=None):
        CALLS.setdefault(self.tool, set()).add(route_of(method, path))
        if binary_cap:
            return {"bytes": b"x", "mime": "text/plain", "name": "x"}
        return {"data": [], "ok": True}


def sample(schema):
    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t
    if "enum" in schema:
        return schema["enum"][0]
    return {"integer": 1, "number": 1, "string": "x", "boolean": True, "array": [], "object": {}}.get(t, 1)


TOOL_VARIANTS = {  # extra arguments that reach other routes of the same tool
    "get_attachment": [{"source": "chat"}, {"source": "project", "list_id": 1}],
    "react": [{"remove": True}],
    "upload_attachment": [],
}
rec = Rec()
for name, _, schema, fn in mcp.TOOLS:
    props = schema.get("properties", {})
    base = {k: sample(props[k]) for k in schema.get("required", [])}
    if name == "upload_attachment":
        base["files"] = [{"name": "a.txt", "base64": "eA=="}]
    if name == "upload_project_file":
        base["base64"] = "eA=="
    if name == "send_chat":
        base["body"] = "x"
    for extra in [{}] + TOOL_VARIANTS.get(name, []):
        rec.tool = name
        try:
            fn(rec, {**base, **extra})
        except mcp.ApiError as e:
            check(False, f"tool {name} {extra}: {e.message}")
reached = {c for s in CALLS.values() for c in s}
API_ONLY = {  # REST routes on purpose without an MCP tool (reason)
    "GET /openapi.json": "the API description itself",
    "POST /import/{}": "imports of other apps' files: people upload them (multipart) in the app or with the REST API",
    "POST /imports/{}/undo": "belongs to the import",
    "POST /lists/{}/owner": "transferring a list: never agents (403)",
    "GET /admin/users": "admin-read: never for agents",
    "GET /admin/status": "admin-read: never for agents",
    "GET /admin/agents/{}/audit": "admin-read: never for agents",
    "GET /me/app-passwords": "account: never for agents",
    "POST /me/app-passwords": "account: never for agents",
    "DELETE /me/app-passwords/{}": "account: never for agents",
    "PATCH /me/notifications": "account: never for agents",
    "POST /agents/{}/chat/{}/reactions": "a person's reaction in an agent chat (the agent: react_to_chat)",
    "GET /lists/{}/links": "in get_project_overview",
    "GET /lists/{}/milestones": "in get_project_overview",
}
none = sorted(r for r in API if r not in reached and r not in API_ONLY)
check(not none, f"API routes without an MCP tool or a documented exception: {none}")
stale = sorted(r for r in API_ONLY if r not in API)
check(not stale, f"API_ONLY lists routes that no longer exist: {stale}")
both = sorted(r for r in API_ONLY if r in reached)
check(not both, f"API_ONLY routes that do have a tool now (drop them from the list): {both}")
unknown = sorted({c for c in reached if c not in API})
check(not unknown, f"MCP tools call routes the API does not have: {unknown}")
check(set(TOOL_VARIANTS) <= {t[0] for t in mcp.TOOLS}, "TOOL_VARIANTS: known tools only")
# every tool has a scope rule that matches the scope of its route(s) in the OpenAPI document is checked against the live
# server in p2150_api_test.py; here: every tool name in TOOL_SCOPES exists
check(set(mcp.TOOL_SCOPE) <= {t[0] for t in mcp.TOOLS}, f"TOOL_SCOPES: unknown tools {sorted(set(mcp.TOOL_SCOPE) - {t[0] for t in mcp.TOOLS})}")
print(f"app routes: {len(APP)} ({len(APP_TO_API)} mapped), API routes: {len(API)} ({len(API) - len(API_ONLY)} with MCP tools), MCP tools: {len(mcp.TOOLS)}")
print(f"parity: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
