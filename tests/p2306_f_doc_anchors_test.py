#!/usr/bin/env python3
"""2.306.0 F (#2942, #2939, #2933, #2930): the agent pages stay true. The link check (tools/check_links.py, also CI lint) covers
docs/, mcp/ and the top-level pages and catches a broken anchor; the MCP server reports the app's VERSION; the short
mcp/README.md names react_to_chat `remove` and get_attachment `source: team`; the permission profiles (hardened / standard)
stand in every place that shows settings.json (guides, security page, in-app guide); the setup prompt is the same text in the
guide, the prompt file and the app, runs the launcher with --events and has no events.sh step; the in-app guide has no loop
prompt on wait_for_events and its Windows steps create the folders, run.ps1 and .mcp.json.
freelancer-matrix: agents (docs / client text only, no route)
Pure Python, no container."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from kt import FAILS, OKS, check, done  # noqa: E402  (shared helpers, tests/kt.py)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# the link check: green on the repository, red on a broken anchor and a missing file, and it reads mcp/*.md
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_links.py"), "-v"], capture_output=True, text=True)
check(r.returncode == 0, "check_links.py is green on the repository: " + r.stdout[-400:])
check(re.search(r"(\d+) pages", r.stdout) and int(re.search(r"(\d+) pages", r.stdout).group(1)) >= 28 + 3, "the check also reads mcp/*.md")
with tempfile.TemporaryDirectory() as d:
    bad = os.path.join(d, "bad.md")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("# Title\n\n[ok](#title) [anchor](#no-such-heading-2100) [file](missing.md#x)\n")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_links.py"), bad], capture_output=True, text=True)
    check(r.returncode == 1 and "no-such-heading-2100" in r.stdout and "missing.md" in r.stdout, "check_links.py reports a broken anchor and a missing file")

# the MCP server reports the app's version, not a fixed 2.21.0
spec = importlib.util.spec_from_file_location("kalmido_mcp_f", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
check(mod.SERVER_VERSION == read("VERSION").strip(), f"SERVER_VERSION follows VERSION: {mod.SERVER_VERSION}")
# 2.306.0 review (#2927): a starter folder from agent-setup (no ../VERSION) reads the VERSION the setup wrote next to it
with tempfile.TemporaryDirectory() as d:
    inst = os.path.join(d, "inst")
    os.makedirs(inst)
    shutil.copy(os.path.join(ROOT, "mcp", "kalmido_mcp.py"), inst)

    def ver_of(tag):
        sp = importlib.util.spec_from_file_location("kalmido_mcp_" + tag, os.path.join(inst, "kalmido_mcp.py"))
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m.SERVER_VERSION
    check(ver_of("none") == "0", "a starter folder without VERSION: 0")
    with open(os.path.join(inst, "VERSION"), "w", encoding="utf-8") as f:
        f.write("9.8.7\n")
    check(ver_of("inst") == "9.8.7", "a starter folder: the VERSION next to kalmido_mcp.py")
for name, src in (("setup.sh", read("static", "agent", "setup.sh")), ("setup.ps1", read("static", "agent", "setup.ps1"))):
    check('"VERSION"' in src or "'VERSION'" in src, f"{name}: writes the server's VERSION next to the starter files")

# mcp/README.md: short, and the two parameters that were wrong
rm = read("mcp", "README.md")
check("remove" in rm and "react_to_chat" in rm and "`on`" not in rm, "README: react_to_chat takes remove, not on")
check("`team`" in rm and "get_attachment" in rm, "README: get_attachment source team")
check(rm.count("\n| `") < 40, "README: the long tool tables are gone")
for sc in ("office", "pinboard", "layouts", "import", "sheets:read", "sheets:write", "files:read", "files:write", "wiki:read"):
    check(f"`{sc}`" in rm, f"README names the scope {sc}")

# permission profiles everywhere settings.json is shown
for page in ("AGENT-SETUP.md", "AGENT-SECURITY.md", "AGENTS.md"):
    t = read("docs", page).lower()
    check("hardened" in t and "standard" in t, f"{page}: hardened and standard profile")
chat = read("static", "js", "agentchat.js")
check("Hardened: defaultMode dontAsk" in chat and "Standard: mode default" in chat, "agentchat.js: both profiles in the rules text")
check("AG_HEADLESS" not in chat and "call the kalmido tool wait_for_events" not in chat, "agentchat.js: no loop prompt on wait_for_events")
check("New-Item -ItemType Directory -Force $HOME\\\\.config\\\\kalmido, $HOME\\\\agent" in chat and "AG_WIN_RUN" in chat and "AG_WIN_MCP" in chat,
      "agentchat.js: Windows steps create the folders, run.ps1 and .mcp.json")
check("run.ps1 -Value" in chat and ".mcp.json -Value" in chat, "agentchat.js: the Windows files are written with New-Item -Force")

# the setup prompt: the same text in the guide, the prompt file and the app
pf = read("docs", "agent-setup-prompt.txt").strip()
guide = read("docs", "AGENT-SETUP.md")
check(pf in guide, "the prompt file is the prompt block of AGENT-SETUP.md")
steps = re.findall(r"^(\d+)\. (.*)$", pf, re.M)
check([n for n, _ in steps] == [str(i) for i in range(1, len(steps) + 1)], "prompt steps numbered 1..n")
check("events.sh" not in pf and "BASH_DEFAULT_TIMEOUT_MS" not in pf, "the prompt has no events.sh step and no BASH timeouts")
check("--events" in pf, "the prompt runs the launcher with --events")
app = re.search(r'const AG_PROMPT = "(.*?)";\n', chat, re.S)
check(bool(app) and app.group(1).replace('\\"', '"').replace("\\n", "\n") == pf, "the app's AG_PROMPT is the prompt file")
check("(step 3), then run the test checklist (step 10)" in guide, "the guide refers to the prompt's own step numbers")
check("which one tidies it up" not in guide.replace("so that agent is the one that tidies it up", ""), "the guide no longer asks which of several agents tidies up")

# scope facts in the docs follow the code (api/v1.py): the default set and the legacy write
api = read("docs", "API.md")
agents = read("docs", "AGENTS.md")
check("`files:read` / `files:write` | on |" in agents, "AGENTS.md: the file store is on by default")
check("starts with *Read*, *Tasks* and *Comments*;" not in guide and "*Read files* and *Add files*" in guide, "AGENT-SETUP.md: the default set names the file store")
check("`office`, `pinboard`, `layouts`, `import`, `sheets:*`" in api, "API.md: legacy write leaves out the sensitive scopes")
check("| `POST /tasks/{id}/tidy` | tasks:write |" in api, "API.md: tidy needs tasks:write")
check("`propose_contract_notice` | agent (no scope) |" in agents, "AGENTS.md: the notice proposal needs no scope")
check("one exception" in read("docs", "AGENT-SECURITY.md").lower() and "exception to \"only what is shared\"" in agents, "the office exception is named in the security page and in AGENTS.md")

sys.exit(done("p2306_f_doc_anchors"))
