#!/usr/bin/env python3
# kalmido-suite: after=p2440_a_launcher nodata
"""2.391.0 D (#3359): the runner profiles of mcp/agent_run.py / agent_job.py -- claude (Claude Code as before), codex (Codex
CLI: `codex exec --json -`, its JSONL event stream mapped to steps / answer / session, the chat going on with
`codex exec --json resume <id> -`) and generic (stdout = the answer). A fake `codex` command (tests/fake_codex.py) plays the
event stream of `codex exec --json` back as the public Codex docs describe it; real Codex is never called. A stub API.
Pure Python, no container."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

import kt  # shared helpers (tests/kt.py)
from kt import check

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(HERE, "..", "mcp")
RUNNER = os.path.join(MCP, "agent_run.py")
os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "z" * 30)
os.environ.pop("KALMIDO_AGENT_PROFILE", None)
spec = importlib.util.spec_from_file_location("agent_run", RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
ar.RETRY_429_S = (0, 0, 0, 0)
ar.STEP_GAP_S = 0
TMP = tempfile.mkdtemp(prefix="kalmido-p2391d-")
os.chdir(TMP)
CALLS = os.path.join(TMP, "calls.jsonl")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
FAKE = os.path.join(BIN, "codex")  # named codex: the profile comes from the name
with open(FAKE, "w") as f:
    f.write("#!" + sys.executable + "\n" + open(os.path.join(HERE, "fake_codex.py"), encoding="utf-8").read())
os.chmod(FAKE, 0o755)
GENERIC = os.path.join(BIN, "myagent")
with open(GENERIC, "w") as f:
    f.write("#!" + sys.executable + "\n" + r'''import json, os, sys
prompt = sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "prompt": prompt}) + "\n")
print("Plain answer line one.")
print("Line two.")
''')
os.chmod(GENERIC, 0o755)
os.environ["FAKE_CALLS"] = CALLS
os.environ["CODEX_HOME"] = os.path.join(TMP, "codexhome")
os.makedirs(os.environ["CODEX_HOME"])


class StubApi:
    def __init__(self):
        self.posts, self.steps, self.notices, self.statuses = [], [], [], []

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None, **k):
        self.posts.append({"uid": uid, "body": body, "approval": approval})
        return {"id": 100 + len(self.posts)}

    def progress(self, text, uid=None, **k):
        self.steps.append(text)
        return True

    def notice(self, uid, text):
        self.notices.append((uid, text))
        return True

    def req(self, *a, **k):
        return {"owner_id": 7, "runtime": {"model": "opus", "reset_seq": 0}}

    def status(self, *a, **k):
        self.statuses.append((a, k))

    def withdraw(self, *a, **k):
        return True

    def typing(self, *a, **k):
        pass

    quota = typing


def runner(name, cmd):
    r = ar.Runner(cmd, os.path.join(TMP, name))
    r.api = r.usage.api = StubApi()
    return r


def calls():
    if not os.path.exists(CALLS):
        return []
    with open(CALLS) as f:
        out = [json.loads(ln) for ln in f]
    os.remove(CALLS)
    return out


def chat(mid, body, uid=7):
    return {"event": "chat", "seq": mid, "data": {"user": {"id": uid, "name": "Ann"}, "message": {"id": mid, "body": body}}}


def go(r, ev, mode="plain", final="All green.", **env):
    os.environ.update(FAKE_MODE=mode, FAKE_FINAL=final, **{k: str(v) for k, v in env.items()})
    calls()
    r.run(ar.Runner.chat_uid(ev), [ev])
    return calls()


# ---- the profile: from the name, KALMIDO_AGENT_PROFILE wins, other names stay as before
check(ar.agent_profile(["claude"]) == "claude" and ar.agent_profile(["/usr/bin/codex"]) == "codex"
      and ar.agent_profile(["C:\\npm\\codex.cmd"]) == "codex", "profile from the command's name")
check(ar.agent_profile(["my-wrapper.sh"]) == "claude" and not ar.claude_native(["my-wrapper.sh"]),
      "another name: the stream-json arguments as before, but no Claude Code hooks")
os.environ["KALMIDO_AGENT_PROFILE"] = "generic"
check(ar.agent_profile(["claude"]) == "generic" and not ar.claude_native(["claude"]), "KALMIDO_AGENT_PROFILE wins over the name")
os.environ["KALMIDO_AGENT_PROFILE"] = "claude"
check(ar.claude_native(["my-wrapper.sh"]), "KALMIDO_AGENT_PROFILE=claude: a wrapper of Claude Code gets the hooks")
os.environ["KALMIDO_AGENT_PROFILE"] = "nonsense"
check(ar.agent_profile(["codex"]) == "codex", "an unknown value counts as not set")
os.environ.pop("KALMIDO_AGENT_PROFILE")

# ---- the arguments per profile
check(ar.profile_args("claude", ["claude", "--mcp-config", "m.json"]) == ["claude", "--mcp-config", "m.json", "-p", "--output-format",
                                                                           "stream-json", "--verbose"], "claude: as before")
check(ar.with_session("claude", ["claude", "-p"], "S1") == ["claude", "-p", "--resume", "S1"], "claude: --resume")
ca = ar.profile_args("codex", ["codex", "-m", "gpt-5-codex"])
check(ca == ["codex", "exec", "-m", "gpt-5-codex", "--json"], f"codex: exec --json, no -p / stream-json: {ca}")
check(ar.profile_args("codex", ["codex", "exec", "--json", "--skip-git-repo-check"]) == ["codex", "exec", "--json", "--skip-git-repo-check"],
      "codex: own exec / --json are kept, nothing doubled")
check(ar.with_session("codex", ca, None)[-1] == "-" and ar.with_session("codex", ca, "T9")[-3:] == ["resume", "T9", "-"],
      "codex: the prompt from stdin (-), a conversation goes on with exec ... resume <id> -")
check(ar.profile_args("generic", ["myagent", "--x"]) == ["myagent", "--x"] and ar.with_session("generic", ["myagent"], "S") == ["myagent"],
      "generic: the command as it is, never a session")
check(ar.codex_model(["codex", "--model", "o4-mini"]) == "o4-mini" and ar.codex_model(["codex", "-c", "model=gpt-5"]) == "gpt-5",
      "codex model from the command")
with open(os.path.join(os.environ["CODEX_HOME"], "config.toml"), "w") as f:
    f.write('model = "gpt-5-codex"\n\n[profiles.fast]\nmodel = "o4-mini"\n')
check(ar.codex_model(["codex"]) == "gpt-5-codex", "codex model from config.toml (top level only)")

# ---- the stream of `codex exec --json`
steps, models = [], []
st = ar.Stream(steps.append, models.append, lambda u: None)
st.model_hint = "gpt-5-codex"
ev = [{"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"}, {"type": "turn.started"},
      {"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "SECRET REASONING"}},
      {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "I look at the files first."}},
      {"type": "item.started", "item": {"id": "item_2", "type": "command_execution", "command": "bash -lc ls", "status": "in_progress"}},
      {"type": "item.completed", "item": {"id": "item_2", "type": "command_execution", "command": "bash -lc ls",
                                          "aggregated_output": "TOOL OUTPUT", "exit_code": 0, "status": "completed"}},
      {"type": "item.completed", "item": {"id": "item_3", "type": "mcp_tool_call", "server": "kalmido", "tool": "add_rule", "status": "completed"}},
      {"type": "item.completed", "item": {"id": "item_4", "type": "agent_message", "text": "Repo contains docs and sdk."}},
      {"type": "turn.completed", "usage": {"input_tokens": 24763, "cached_input_tokens": 24448, "output_tokens": 122,
                                           "reasoning_output_tokens": 0}}]
for e in ev:
    st.feed(json.dumps(e) + "\n")
    st.last_sent = 0
check(st.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53", "the thread id is the session")
check(models == ["gpt-5-codex"], f"the model from COMMAND / config at the start: {models}")
check(steps == ["I look at the files first."], f"one step (text before a tool item), never reasoning, tool output or the answer: {steps}")
check(st.tools == 2 and st.rules_added, f"tool items counted once each, add_rule seen: {st.tools}")
check(ar.result_text(st) == "Repo contains docs and sdk." and st.context_tokens == 24885, "the last agent message is the answer, tokens")
st = ar.Stream(lambda t: None, lambda m: None, lambda u: None)
for e in ({"type": "thread.started", "thread_id": "T1"}, {"type": "error", "message": "stream disconnected"},
          {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}):
    st.feed(json.dumps(e) + "\n")
check(ar.result_text(st) == "" and st.err_tail[-1] == "You've hit your usage limit.", f"turn.failed: no answer, the error kept: {st.err_tail}")

# ---- a chat run with the fake codex: the answer, a step, no Claude Code arguments, the conversation goes on
r = runner("c1", [FAKE, "--skip-git-repo-check"])
check(r.profile == "codex" and not r.is_claude() and r.can_resume() and r.mode_fixed(), "runner: profile codex")
cl = go(r, chat(1, "Hello"), final="Here is the overview.")
check(len(cl) == 1, f"one run: {cl}")
a = cl[0]["args"]
check(a[:1] == ["exec"] and "--json" in a and a[-1] == "-" and "resume" not in a, f"fresh: codex exec ... --json -: {a}")
check(not any(x in a for x in ("-p", "--output-format", "--settings", "--permission-mode", "--model", "--resume")),
      f"no Claude Code arguments, no hooks, no model of Kalmido: {a}")
check("Hello" in cl[0]["prompt"] and "Fixed rules" in cl[0]["prompt"], "the prompt with the rules block on stdin")
check(r.api.posts and r.api.posts[-1]["body"] == "Here is the overview.", f"the answer is posted: {r.api.posts}")
check(r.api.steps == ["Let me check the list."], f"the text before a tool item became a step: {r.api.steps}")
check(r.state.data["sessions"].get("chat:7", {}).get("id") == "TH-1", f"the conversation is kept: {r.state.data['sessions']}")
cl = go(r, chat(2, "And the next one?"), final="Next is the invoice.")
a = cl[0]["args"]
check(a[-3:] == ["resume", "TH-1", "-"] and a.index("--json") < a.index("resume"), f"the second message goes on: ... --json resume TH-1 -: {a}")
check(r.api.posts[-1]["body"] == "Next is the invoice.", "the second answer")

# ---- approval check: an answer that asks without a card goes back once in the same conversation
cl = go(r, chat(3, "Delete it?"), mode="card", final="Shall I delete the old branch?")
check(len(cl) == 2 and cl[1]["args"][-3:] == ["resume", "TH-1", "-"] and cl[1]["prompt"].startswith("(Launcher check"),
      f"the card question goes back once through resume: {[c['args'] for c in cl]}")
check(r.api.posts[-1]["approval"] == {"title": "Delete branch old"}, f"the card from the second answer: {r.api.posts[-1]}")

# ---- a failed turn: no answer, a failure note (masked), no second try after a tool item
r = runner("c2", [FAKE])
cl = go(r, chat(1, "Go"), mode="fail")
check(len(cl) == 1, f"a failed turn after a tool item: no second try: {len(cl)}")
check(r.api.posts and "usage limit" in r.api.posts[-1]["body"] and "abk_" not in r.api.posts[-1]["body"],
      f"the failure note names the error: {r.api.posts}")
cl = go(r, chat(2, "Again"), mode="gone")
check(len(cl) == 2 and "resume" not in cl[1]["args"], f"a conversation that cannot be resumed: the second try is fresh: {[c['args'] for c in cl]}")

# ---- a task event: fresh, never resumed, no steps
r = runner("c3", [FAKE])
cl = go(r, {"event": "comment", "seq": 5, "data": {"task": {"id": 12, "title": "T"}}}, final="Noted.")
check(cl and "resume" not in cl[0]["args"] and not r.api.steps and not r.api.posts, "task event: fresh run, no steps, posted nowhere")

# ---- generic: stdout is the answer, nothing added
r = runner("g1", [GENERIC, "--flag"])
check(r.profile == "claude", "a name that is neither claude nor codex keeps the old arguments without the variable")
os.environ["KALMIDO_AGENT_PROFILE"] = "generic"
r = runner("g2", [GENERIC, "--flag"])
cl = go(r, chat(1, "Hi"))
check(r.profile == "generic" and cl and cl[0]["args"] == ["--flag"], f"generic: the command as it is: {cl and cl[0]['args']}")
check(r.api.posts and r.api.posts[-1]["body"] == "Plain answer line one.\nLine two.", f"generic: stdout is the answer: {r.api.posts}")
cl = go(r, chat(2, "Again"))
check(cl and cl[0]["args"] == ["--flag"] and not r.state.data["sessions"], "generic: no conversation")
os.environ.pop("KALMIDO_AGENT_PROFILE")

# ---- the job runner uses the same helpers
spec = importlib.util.spec_from_file_location("agent_job", os.path.join(MCP, "agent_job.py"))
aj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aj)
m = aj.runner_module()
check(m is not None and m.agent_profile(["codex"]) == "codex" and m.with_session("codex", ["codex", "exec", "--json"], "J1")[-3:] == ["resume", "J1", "-"],
      "agent_job.py builds a job's run with the profile of agent_run.py")
src = open(os.path.join(MCP, "agent_job.py"), encoding="utf-8").read()
check("ar.codex_event(ev)" in src and 'profile == "generic"' in src, "agent_job.py reads the Codex stream and generic stdout")

# ---- both launchers take the command and the profile from the env file
for name in ("agent_launcher.sh", "agent_launcher.ps1"):
    s = open(os.path.join(MCP, name), encoding="utf-8").read()
    check("KALMIDO_AGENT_CMD" in s and "KALMIDO_AGENT_PROFILE" in s and "kalmido-capability: profile" in s, f"{name}: command + profile")
if shutil.which("bash"):
    # the sh launcher splits KALMIDO_AGENT_CMD like a shell (words, quotes) -- the part before the first request only
    envf = os.path.join(TMP, "a.env")
    with open(envf, "w") as f:
        f.write('KALMIDO_URL=http://127.0.0.1:9\nKALMIDO_TOKEN=abk_x\nKALMIDO_AGENT_CMD=\'codex --skip-git-repo-check -c "model=gpt 5"\'\n')
    code = ('set -a; . "$1"; set +a; CMD=(); '
            'if [[ ${#CMD[@]} -eq 0 && -n "${KALMIDO_AGENT_CMD:-}" ]]; then eval "CMD=($KALMIDO_AGENT_CMD)"; fi; printf "%s|" "${CMD[@]}"')
    launcher = open(os.path.join(MCP, "agent_launcher.sh"), encoding="utf-8").read()
    check('eval "CMD=($KALMIDO_AGENT_CMD)"' in launcher, "the launcher line the check below runs")
    out = subprocess.run(["bash", "-c", code, "x", envf], capture_output=True, text=True).stdout
    check(out == "codex|--skip-git-repo-check|-c|model=gpt 5|", f"KALMIDO_AGENT_CMD as shell words: {out!r}")
# ---- the setup scripts ask for the tool (Claude Code by default) and hand Codex the MCP server with -c
ROOT = os.path.join(HERE, "..")
ssh = open(os.path.join(ROOT, "static", "agent", "setup.sh"), encoding="utf-8").read()
sps = open(os.path.join(ROOT, "static", "agent", "setup.ps1"), encoding="utf-8").read()
check("--tool" in ssh and "-Tool" in sps and "ask_tool" in ssh and "ask_tool" in sps and "TOOL=${TOOL:-claude}" in ssh
      and "$Tool = 'claude'" in sps, "setup.sh / setup.ps1: --tool / -Tool, asked once, Claude Code by default")
check("mcp_servers.kalmido.command=" in ssh and "mcp_servers.kalmido.command=" in sps and "kalmido_mcp_run" in ssh
      and "kalmido_mcp_run" in sps, "setup: Codex gets the MCP server per run through a wrapper that reads the env file")
if shutil.which("bash"):
    r = subprocess.run(["bash", os.path.join(ROOT, "static", "agent", "setup.sh"), "--tool", "nope", "--dry-run", "--url",
                        "https://kalmido.example.com", "--dir", os.path.join(TMP, "proj")], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    check(r.returncode != 0 and "nope" in (r.stderr + r.stdout), f"setup.sh: an unknown tool stops at once: {r.returncode} {r.stderr[-200:]}")
sys.exit(kt.done("p2391_d_codex_profile"))
