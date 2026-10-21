#!/usr/bin/env python3
"""2.151.0 (#2560): the rule "the task list is the truth for tickets and releases" reaches every place a new software
agent gets its rules from: the launcher's fixed rules, the template (and its in-app copy AG_RULES), the setup guide and
the coding-agent guide. Pure text check, no container.
freelancer-matrix: agents-rules (no route; the rule text is the same for a person without an organisation)"""
import os
import re
import sys

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
F, ok = [], 0
PHRASES = [
    ("task list is the truth", r"task list is the truth"),
    ("never done before default branch + published", r"default branch\s+and published"),
    ("rest = new version", r"enter a new version"),
    ("no unmerged branch", r"never end work on an unmerged branch"),
    ("task named in commits", r"kalmido-<id>"),
    ("list_build_status before done", r"list_build_status"),
]


def read(*p):
    with open(os.path.join(R, *p), encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).lower()


files = {"mcp/agent_rules.md": read("mcp", "agent_rules.md"), "mcp/CLAUDE.template.md": read("mcp", "CLAUDE.template.md"),
         "docs/AGENT-SETUP.md": read("docs", "AGENT-SETUP.md"), "docs/AGENTS.md": read("docs", "AGENTS.md")}
jsp = os.path.join(R, "static", "js", "agentchat.js")
if os.path.exists(jsp):
    with open(jsp, encoding="utf-8") as f:
        files["AG_RULES"] = re.sub(r"\\n|\s+", " ", f.read()).lower()
for name, txt in files.items():
    for what, pat in PHRASES:
        if re.search(pat.lower(), txt):
            ok += 1
        else:
            F.append(f"{name}: {what}")
            print("FAIL:", name, what)
print(f"p2151_b: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
