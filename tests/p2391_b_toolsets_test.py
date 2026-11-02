#!/usr/bin/env python3
"""2.391.0 B (#3358): MCP toolsets (mcp/kalmido_mcp.py --toolsets / KALMIDO_TOOLSETS).
freelancer-matrix: n/a (no route: a start option of the local MCP server, nothing runs against Kalmido)
 - every tool is in exactly one package of TOOLSETS (a new tool without an entry turns this red), no entry names an unknown tool
 - parse_toolsets: chat always on, all = every package but integrations, no value = no limit, a typo raises
 - tools/list shows only the tools of the active packages; tools/call of another one: "not in the active toolsets"
 - the default (no option) lists every tool as before; both launchers hand KALMIDO_TOOLSETS on (capability toolsets)
Pure Python, no container, no server."""
# kalmido-suite: after=launcher_parity nodata
import collections
import importlib.util
import json
import os
import subprocess
import sys

from kt import check, done

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(N, "..", "mcp")
sp = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(MCP, "kalmido_mcp.py"))
m = importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)

names = [t[0] for t in m.TOOLS]
cnt = collections.Counter(n for v in m.TOOLSETS.values() for n in v)
check(len(names) == len(set(names)), "tool names are unique")
check(not [n for n in names if n not in cnt], f"every tool has a toolset: {[n for n in names if n not in cnt]}")
check(not [n for n, c in cnt.items() if c > 1], f"no tool in two toolsets: {[n for n, c in cnt.items() if c > 1]}")
check(not [n for n in cnt if n not in m.TOOL_MAP], f"no toolset entry names an unknown tool: {[n for n in cnt if n not in m.TOOL_MAP]}")
for k in ("tickets", "code", "chat", "office", "calendar", "wiki", "life", "integrations"):
    check(k in m.TOOLSETS, f"toolset {k} exists")
check("create_api_token" in m.TOOLSETS["integrations"] and set(m.TOOLSETS["integrations"]) == set(m.TOOL_SCOPES["integrations"]),
      "integrations = exactly the setup tools of scope integrations (#3362)")
check(m.TOOLSET_OF["wait_for_events"] == "chat" and m.TOOLSET_OF["create_task"] == "tickets" and m.TOOLSET_OF["get_office"] == "office"
      and m.TOOLSET_OF["start_timer"] == "office" and m.TOOLSET_OF["list_repos"] == "code", "sample assignments")

P = m.parse_toolsets
check(P("") is None and P(None) is None and P("  ") is None, "no value = no limit")
check(P("tickets") == frozenset({"tickets", "chat"}), "chat is always on")
check(P("Tickets, code") == frozenset({"tickets", "code", "chat"}), "case and spaces are tolerated")
check(P("all") == frozenset(m.ALL_TOOLSETS) and "integrations" not in P("all") and "chat" in P("all"), "all = every package but integrations")
check("integrations" in P("all,integrations") and "wiki" in P("all,integrations"), "integrations only when named")
try:
    P("tickets,nope")
    check(False, "an unknown toolset raises")
except ValueError as e:
    check("nope" in str(e), "an unknown toolset raises with the name")


class Api:  # token_scopes -> None: every tool allowed, the server would decide
    def call(self, *a, **k):
        raise m.ApiError(0, "offline")


def listed():
    r = m.handle(Api(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {t["name"] for t in r["result"]["tools"]}


m._ME["v"], m._ME["at"] = None, 10**9  # cached "unknown": every tool is listed
try:
    m.ACTIVE_TOOLSETS = None
    check(listed() == set(names), "default: every tool is listed as before")
    m.ACTIVE_TOOLSETS = P("calendar")
    got = listed()
    want = set(m.TOOLSETS["calendar"]) | set(m.TOOLSETS["chat"])
    check(got == want, f"calendar: only calendar + chat tools ({len(got)} vs {len(want)})")
    check("create_task" not in got and "create_event" in got and "wait_for_events" in got, "calendar: sample tools")
    r = m.handle(Api(), {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_task", "arguments": {}}})
    res = r["result"]
    check(res.get("isError") is True and "not in the active toolsets" in res["content"][0]["text"], "a tool outside the toolsets is refused clearly")
    r = m.handle(Api(), {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}})
    check("error" in r and "Unknown tool" in r["error"]["message"], "an unknown tool stays an unknown tool")
    m.ACTIVE_TOOLSETS = P("all")
    got = listed()
    check("list_repos" in got and got == set(names) - set(m.TOOLSETS["integrations"]), "all lists everything but the integrations tools")
    m.ACTIVE_TOOLSETS = P("all,integrations")
    check(listed() == set(names), "all,integrations lists every tool")
finally:
    m.ACTIVE_TOOLSETS = None

# the start option and the environment variable (a real process, tools/list over stdio; no server needed - /me fails -> all listed)
def stdio_list(args, env_extra):
    env = {**os.environ, "KALMIDO_URL": "http://127.0.0.1:9", "KALMIDO_TOKEN": "abk_" + "x" * 40, **env_extra}
    env.pop("KALMIDO_TOOLSETS", None) if "KALMIDO_TOOLSETS" not in env_extra else None
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    p = subprocess.run([sys.executable, "-I", os.path.join(MCP, "kalmido_mcp.py")] + args, input=req, capture_output=True, text=True, env=env, timeout=60)
    return p


p = stdio_list(["--toolsets", "calendar"], {})
out = json.loads(p.stdout.splitlines()[0])["result"]["tools"] if p.stdout.strip() else []
check({t["name"] for t in out} == set(m.TOOLSETS["calendar"]) | set(m.TOOLSETS["chat"]), "--toolsets calendar over stdio")
p = stdio_list([], {"KALMIDO_TOOLSETS": "wiki"})
out = json.loads(p.stdout.splitlines()[0])["result"]["tools"] if p.stdout.strip() else []
check({t["name"] for t in out} == set(m.TOOLSETS["wiki"]) | set(m.TOOLSETS["chat"]), "KALMIDO_TOOLSETS=wiki over stdio")
p = stdio_list(["--toolsets", "bogus"], {})
check(p.returncode == 2 and "bogus" in p.stderr, "a typo ends the server with exit 2")

# starter parity: both launchers name the capability, the list knows it
caps = json.load(open(os.path.join(MCP, "launcher_capabilities.json"), encoding="utf-8"))["capabilities"]
check(any(c["id"] == "toolsets" for c in caps), "launcher_capabilities.json has toolsets")
for f in ("agent_launcher.sh", "agent_launcher.ps1"):
    src = open(os.path.join(MCP, f), encoding="utf-8").read()
    check("kalmido-capability: toolsets" in src and "KALMIDO_TOOLSETS" in src, f"{f} names the capability and the variable")

sys.exit(done("p2391_b_toolsets"))
