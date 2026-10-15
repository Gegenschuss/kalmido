#!/usr/bin/env python3
"""2.46.6 part A: the reference launcher (mcp/agent_run.py, mcp/agent_job.py) without a server -- suggestion buttons cut
at a word (#1722). A stub API, pure Python, no container."""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(HERE, "..", "mcp")
RUNNER = os.path.join(MCP, "agent_run.py")
F, ok = [], 0


def check(c, what):
    global ok
    if c:
        ok += 1
    else:
        F.append(what)
        print("FAIL:", what)


os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "y" * 30)
sys.path.insert(0, MCP)
spec = importlib.util.spec_from_file_location("agent_run", RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
TMP = tempfile.mkdtemp(prefix="kalmido-p2466a-")
os.chdir(TMP)

# ---- #1722: suggestion buttons end at a word with "…", at most 80 characters
LONG = "Run the full test suite on the test machine and then compare the results with the last release build"
cut = ar.label_cut(LONG)
check(len(cut) <= 80 and cut.endswith("…"), f"a long suggestion is at most 80 characters and ends with …: {cut!r}")
check(LONG.startswith(cut[:-1]) and LONG[len(cut) - 1] == " ", f"cut at a word, never mid-word: {cut!r}")
check(ar.label_cut("Show the log") == "Show the log", "a short suggestion stays as it is")
check(ar.label_cut("  Show   the\nlog ") == "Show the log", "whitespace is folded")
check(ar.label_cut("Deploy it now, " + "x" * 64 + " tail") == "Deploy it now…", "punctuation before the … is dropped")
check(len(ar.label_cut("y" * 120)) == 80, "one long word: cut hard at 80")
tb = ar.split_tail_blocks("Done.\n\n```suggest\n1. " + LONG + "\n```")
check(tb[2] == [cut], f"the parser cuts at a word too: {tb[2]}")


class Cap:
    def __init__(self):
        self.bodies = []

    def _post_chat(self, uid, b):
        self.bodies.append(b)
        return {"id": 1}

    def req(self, method, path, body=None, timeout=30):
        self.bodies.append(body)
        return {"id": 2}


api = ar.Api("http://127.0.0.1:9", "abk_" + "y" * 30)
cap = Cap()
api._post_chat, api.req = cap._post_chat, cap.req
api.chat(7, "Done.", suggest=[LONG])
api.comment(5, "Done.", suggest=[LONG])
check([b["choices"][0]["label"] for b in cap.bodies] == [cut, cut], f"chat and comment buttons use the cut label: {cap.bodies}")
p = ar.build_prompt([{"event": "chat", "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 1, "body": "hi"}}}], 7)
check("at most 80 characters" in p, "the chat prompt names the 80-character limit")
p = ar.build_prompt([{"event": "comment", "data": {"task": {"id": 5}}}], None)
check("at most 80 characters" in p, "the task prompt names the 80-character limit")

print(f"p2466_a_launcher: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
