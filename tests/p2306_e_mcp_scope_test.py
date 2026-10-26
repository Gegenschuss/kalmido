#!/usr/bin/env python3
"""2.306.0 E (#2741): every MCP tool asks for the scope of the REST route(s) it calls, so tools/list hides a tool the
token cannot use (a read token sees no write tool).
freelancer-matrix: agents (the OpenAPI document is the same for every account; the scope rule holds without an organisation too)
 - each tool of mcp/kalmido_mcp.py runs against a recording fake API (arguments from its input schema, as in
   tests/parity_test.py); the routes it hits are looked up in the server's OpenAPI document (x-kalmido-scope)
 - the tool's scope (TOOL_SCOPES, else read) is one of the scopes of its routes; a tool that writes (a route with another
   scope than read) never counts as read; a route with scope agent = a tool for agents only
 - tools under agent call only /agent routes or routes with scope read / agent; every route a tool calls is in the document
 - tool_allowed: a read-only token does not see the eight tools of #2741
usage: p2306_e_mcp_scope_test.py <datadir>      (KMT_NOSTART=1 / P2306EM_NOSTART=1: a running server)"""
import importlib.util
import os
import re
import sys

import requests
from kt import B, check, done, fresh, setup

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sp = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mcp)

fresh(prefix="P2306EM")
A = setup()
spec = requests.get(B + "/api/v1/openapi.json", timeout=30).json()
S = {}
for p, ms in spec["paths"].items():
    for m, op in ms.items():
        if isinstance(op, dict) and "x-kalmido-scope" in op:
            S[f"{m.upper()} " + re.sub(r"\{[^}]+\}", "{}", p)] = op["x-kalmido-scope"]
check(len(S) > 300, f"the OpenAPI document has the operations ({len(S)})")
PATS = sorted(((r, re.compile("^" + re.escape(r).replace(re.escape("{}"), "[^/]+") + "$")) for r in S), key=lambda x: x[0].count("{}"))


def route_of(method, path):
    path = path.split("?")[0]
    return next((r for r, rx in PATS if rx.match(f"{method} {path}")), None) or f"{method} {path}"


CALLS = {}


class Rec:
    tool = ""

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


VARIANTS = {  # extra arguments that reach other routes of the same tool (as TOOL_VARIANTS in parity_test.py)
    "list_files": [{"folder_id": 1}], "read_file": [{"as": "base64"}], "write_file": [{"file_id": 1}],
    "get_attachment": [{"source": "chat"}, {"source": "project", "list_id": 1}, {"source": "team"}],
    "react": [{"remove": True}],
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
    for extra in [{}] + VARIANTS.get(name, []):
        rec.tool = name
        try:
            fn(rec, {**base, **extra})
        except Exception:  # noqa: BLE001 -- a tool that checks its arguments itself: the calls made so far count
            pass

bad, unknown = [], []
for name, _, _, _ in mcp.TOOLS:
    need = mcp.TOOL_SCOPE.get(name, "read")
    routes = sorted(CALLS.get(name, ()))
    unknown += [(name, r) for r in routes if r not in S]
    scs = {S[r] for r in routes if r in S}
    if not scs:
        continue
    if need == "agent":
        ok = all(r.split(" ", 1)[1].startswith("/agent") or S.get(r) in ("read", "agent") for r in routes if r in S)
    else:
        ok = need in scs and not (scs - {"read"} and need == "read") and "agent" not in scs - {need}
    if not ok:
        bad.append((name, need, [(r, S.get(r)) for r in routes]))
check(not bad, f"every MCP tool has the scope of its route(s): {bad[:8]} ({len(bad)})")
check(not unknown, f"every route an MCP tool calls is in the OpenAPI document: {unknown[:8]}")
for name, want in (("set_deployment", "structure"), ("duplicate_list", "structure"), ("set_task_sprint", "structure"),
                   ("set_list_review", "structure"), ("review_task", "tasks:write"), ("list_documents", "files:read"),
                   ("get_document", "files:read"), ("update_document", "files:write")):
    check(mcp.TOOL_SCOPE.get(name) == want, f"{name}: scope {want} ({mcp.TOOL_SCOPE.get(name, 'read')})")

# tools/list for a read-only person token: none of them shows
mcp._ME.update(at=0.0, v=None)


class Me:
    def call(self, method, path, **kw):
        return {"kind": "user", "token": {"effective_scopes": ["read"]}}


me = Me()
hidden = [n for n in ("set_deployment", "duplicate_list", "set_task_sprint", "set_list_review", "review_task", "list_documents",
                      "get_document", "update_document") if mcp.tool_allowed(me, n)]
check(not hidden, f"a read token does not see them: {hidden}")
check(mcp.tool_allowed(me, "list_tasks") if "list_tasks" in mcp.TOOL_MAP else True, "a read tool stays visible")
sys.exit(done("p2306_e_mcp_scope"))
