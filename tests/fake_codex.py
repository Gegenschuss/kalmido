"""2.391.0 D (#3359): a fake `codex` command for tests/p2391_d_codex_profile_test.py (copied there as bin/codex behind a
shebang; never run on its own). It plays back the JSONL event stream of `codex exec --json` as the public Codex CLI docs
describe it (thread.started, turn.started, item.started / item.completed with agent_message, reasoning, command_execution,
mcp_tool_call, turn.completed with usage, turn.failed, error), reads the prompt from stdin (`-`) and goes on with
`exec ... resume <id> -`. FAKE_CALLS: a file each call is written to; FAKE_MODE plain | card | fail | gone; FAKE_FINAL the
answer."""
import json
import os
import sys

args, prompt = sys.argv[1:], sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt}) + "\n")
mode = os.environ.get("FAKE_MODE", "plain")
if args[:1] != ["exec"] or "--json" not in args or args[-1] != "-":
    sys.stderr.write("usage: codex exec --json [resume ID] -\n")
    sys.exit(2)
resume = args[args.index("resume") + 1] if "resume" in args else ""
if mode == "gone" and resume:
    sys.stderr.write(f"Error: thread {resume} not found\n")
    sys.exit(1)
n = sum(1 for _ in open(os.environ["FAKE_CALLS"]))
tid = resume or f"TH-{n}"
final = os.environ.get("FAKE_FINAL", "All green.")
if mode == "card" and resume and prompt.startswith("(Launcher check"):
    final = "Shall I delete the old branch?\n\n```approval\nDelete branch old\n```"


def out(ev):
    print(json.dumps(ev), flush=True)


out({"type": "thread.started", "thread_id": tid})
out({"type": "turn.started"})
out({"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "**Thinking** about it"}})
if not resume and mode in ("plain", "fail", "gone"):
    out({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "Let me check the list."}})
    out({"type": "item.started", "item": {"id": "item_2", "type": "mcp_tool_call", "server": "kalmido", "tool": "list_tasks",
                                          "status": "in_progress"}})
    out({"type": "item.completed", "item": {"id": "item_2", "type": "mcp_tool_call", "server": "kalmido", "tool": "list_tasks",
                                            "status": "completed"}})
if mode == "fail":
    out({"type": "error", "message": "Reconnecting... 1/5"})
    out({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again later."}})
    sys.exit(1)
out({"type": "item.completed", "item": {"id": "item_9", "type": "agent_message", "text": final}})
out({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 1000, "output_tokens": 80,
                                         "reasoning_output_tokens": 10}})
