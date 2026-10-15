#!/usr/bin/env python3
"""2.46.6 part A: the reference launcher (mcp/agent_run.py, mcp/agent_job.py) without a server -- suggestion buttons cut
at a word (#1722), exactly one suggestion (#1714), the fixed rules block in every run (#1715),
WORKFLOW-KALMIDO.md (#1717), a wake run after a job and a lost job continued once (#1445). A stub
API and a fake 'claude' command (prints stream-json), pure Python, no container."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

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

# ---- #1714: exactly one suggestion per answer (chat and task runs); the parser still takes up to three
p = ar.build_prompt([{"event": "chat", "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 1, "body": "hi"}}}], 7)
check("exactly ONE short suggestion" in p and "Up to three" not in p, "the chat prompt asks for exactly one suggestion")
check("already offers" in p and "next-best different one" in p, "never a suggestion an earlier message already offers")
p = ar.build_prompt([{"event": "comment", "data": {"task": {"id": 5}}}], None)
check("at most ONE next step" in p and "up to three" not in p, "the task prompt offers at most one next step")
tb = ar.split_tail_blocks("Done.\n\n```suggest\nA\nB\nC\nD\n```")
check(tb[2] == ["A", "B", "C"], f"own rules that give three still work (at most three taken): {tb[2]}")
tpl = open(os.path.join(MCP, "CLAUDE.template.md"), encoding="utf-8").read()
check("exactly **one** suggestion" in tpl and "80 characters" in tpl, "the template says one suggestion, 80 characters")

# ---- #1715: the fixed rules block in front of every run; the project's CLAUDE.md is never touched
CALLS = os.path.join(TMP, "calls.jsonl")
FAKE = os.path.join(TMP, "bin", "claude")
os.makedirs(os.path.dirname(FAKE))
with open(FAKE, "w") as f:
    f.write("#!" + sys.executable + "\n" + r"""import json, os, sys
args, prompt = sys.argv[1:], sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt}) + "\n")
final = os.environ.get("FAKE_FINAL", "All green.")
sid = "S-1"
print(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5", "session_id": sid}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": sid}), flush=True)
""")
os.chmod(FAKE, 0o755)
os.environ["FAKE_CALLS"] = CALLS
AGENT = {"owner_id": 7, "lang": "de", "runtime": {"model": "", "reset_seq": 0}}


class StubApi:
    def __init__(self, agent=None):
        self.posts, self.comments, self.agent = [], [], agent if agent is not None else AGENT

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None):
        self.posts.append({"uid": uid, "body": body, "suggest": suggest})
        return {"id": 100 + len(self.posts)}

    def comment(self, tid, body, approval=None, suggest=None):
        self.comments.append((tid, body, suggest))
        return {"id": 1}

    def req(self, method, path, *a, **k):
        return dict(self.agent) if path == "/agent" else {}

    def soft(self, method, path, *a, **k):
        return self.req(method, path)

    def withdraw(self, *a, **k):
        return True

    def notice(self, *a, **k):
        return True

    def status(self, *a, **k):
        pass

    typing = progress = quota = status


def runner(name, agent=None):
    r = ar.Runner([FAKE], os.path.join(TMP, name))
    r.api = r.usage.api = StubApi(agent)
    if r.extras:
        r.extras.api = r.api
    return r


def calls():
    try:
        with open(CALLS) as f:
            return [json.loads(l) for l in f]
    except OSError:
        return []
    finally:
        if os.path.exists(CALLS):
            os.remove(CALLS)


def chat(mid, body, uid=7):
    return {"event": "chat", "seq": mid, "data": {"user": {"id": uid, "name": "Ann"}, "message": {"id": mid, "body": body}}}


PROJ = os.path.join(TMP, "project")
os.makedirs(PROJ)
with open(os.path.join(PROJ, "CLAUDE.md"), "w") as f:
    f.write("# My project\nOwn rules.\n")
os.chdir(PROJ)
before = sorted(os.listdir(PROJ))
r = runner("s1")
r.run(7, [chat(1, "hello")])
cl = calls()
check(len(cl) == 1 and cl[0]["prompt"].startswith("## Fixed rules of the Kalmido launcher"), "a chat run starts with the rules block")
p = cl[0]["prompt"] if cl else ""
check("personal agent of Kalmido account id 7" in p and "answer in German" in p, "owner id and language come from Kalmido")
check("never weaken" in p and "CLAUDE.md" in p, "the block says CLAUDE.md cannot weaken it")
check("NOTIZEN.md" in p and "ignore your rules" in p and "No secrets" in p and "Exactly one suggestion" in p, "all rules of the task are in the block")
check("{{" not in p and "<!--" not in p, "no placeholder or file comment left")
check(p.index("Fixed rules") < p.index("<<<message 1 from user 7>>>"), "the block comes before the event")
r.run(None, [{"event": "comment", "seq": 2, "data": {"task": {"id": 5}, "comment": {"id": 3, "text": "x"}}}])
cl = calls()
check(len(cl) == 1 and cl[0]["prompt"].startswith("## Fixed rules of the Kalmido launcher"), "a task run starts with the rules block too")
check(open(os.path.join(PROJ, "CLAUDE.md")).read() == "# My project\nOwn rules.\n" and sorted(os.listdir(PROJ)) == before,
      "the project's CLAUDE.md is unchanged and no file was added to the project folder")
os.environ["KALMIDO_OWNER_IDS"] = "7,9"
t = ar.rules_block({"owner_id": None, "lang": "en"})
check("team agent" in t and "account ids 7, 9" in t and "if that is unclear: English" in t, f"a team agent: the persons, narrowed: {t[:400]}")
os.environ.pop("KALMIDO_OWNER_IDS")
# 2.46.6 (#1715, review): no agent info = the last good owner from the state folder; nothing cached = take no order
ar.RULES_CACHE_DIR = os.path.join(TMP, "who-empty")
t = ar.rules_block({})
who = t.split("Who gives orders:**")[1].split("\n")[0]
check("team agent" not in who and not any(ch.isdigit() for ch in who) and "take no new order" in who, f"no agent info, nothing cached: no orders {who}")
ar.RULES_CACHE_DIR = os.path.join(TMP, "who-cached")
ar.rules_block(AGENT)
t = ar.rules_block({})
check("account id 7" in t and "team agent" not in t, "a failed agent request: the cached owner, never the team text")
ar.RULES_CACHE_DIR = None
real = ar.RULES_FILE
ar.RULES_FILE = os.path.join(TMP, "missing.md")
t = ar.rules_block(AGENT)
ar.RULES_FILE = real
check("Fixed rules" in t and "account id 7" in t, "a missing rules file: the short built-in block")
spec = importlib.util.spec_from_file_location("agent_job", os.path.join(MCP, "agent_job.py"))
aj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aj)
jb = aj.rules_for_job(StubApi())
check(jb.startswith("## Fixed rules") and "account id 7" in jb, "a job's brief starts with the rules block")

# ---- #1717: WORKFLOW-KALMIDO.md: read first, written by the agent; the first chat run without it asks once
check("WORKFLOW-KALMIDO.md" in ar.rules_block(AGENT) and "read it first" in ar.rules_block(AGENT), "the rules block names WORKFLOW-KALMIDO.md")
r = runner("s2")
r.run(None, [{"event": "comment", "seq": 1, "data": {"task": {"id": 5}, "comment": {"id": 3, "text": "x"}}}])
check("Launcher, once" not in calls()[0]["prompt"], "a task run never asks for the routine")
r.run(7, [chat(1, "hello")])
p1 = calls()[0]["prompt"]
check("Launcher, once" in p1 and "orders come from" in p1 and "results go" in p1 and "report status" in p1,
      "the first chat run without the file asks once (orders, inbox, results, status)")
r.run(7, [chat(2, "next")])
check("Launcher, once" not in calls()[0]["prompt"], "the second chat run does not ask again")
check(runner("s2").state.data.get("workflow_asked"), "'asked' survives a restart (state folder)")
check(sorted(os.listdir(PROJ)) == before, "nothing written into the project folder")
with open(os.path.join(PROJ, "WORKFLOW-KALMIDO.md"), "w") as f:
    f.write("Orders come from the list Inbox.\n")
r = runner("s3")
r.run(7, [chat(1, "hello")])
check("Launcher, once" not in calls()[0]["prompt"], "the file is there: no question")
os.remove(os.path.join(PROJ, "WORKFLOW-KALMIDO.md"))

# ---- #1445: a job that ended wakes the chat agent with exactly ONE chat run
r = runner("s4")
aj.STATE_DIR = r.state_dir


def mkjob(jid, **kw):
    j = {"id": jid, "kalmido_job": jid, "title": f"Build {jid}", "state": "running", "cmd": [FAKE], "task": None, "chat_user": 7,
         "timeout_s": 600, "resumes": 0, "created": time.time() - 3600, "cwd": PROJ, "worktree": None, "session": "", **kw}
    aj.save(j)
    with open(os.path.join(aj.job_dir(jid), "brief.txt"), "w") as f:
        f.write("Build the release.")
    return j


j = mkjob(50, state="done")
check(aj.add_wake(j, "done", "All built. Tests green.") and not aj.add_wake(aj.load(50), "done", "again"), "one wake file per job, never two")
check(r.job_watch() == 1 and r.job_watch() == 0, "the runner takes the wake once")
q = list(r.state.data["queue"])
check(len(q) == 1 and q[0]["event"] == "job_wake" and r.chat_uid(q[0]) == 7, f"queued as a chat run for the job's person: {q}")
r.handle(q, save=True)
r.queue_drop(q)
cl = calls()
check(len(cl) == 1 and 'Job #50 "Build 50"' in cl[0]["prompt"] and "is done" in cl[0]["prompt"] and "All built" in cl[0]["prompt"],
      "exactly one wake run with the job's outcome and result")
check(cl and cl[0]["prompt"].startswith("## Fixed rules") and "Launcher, once" not in cl[0]["prompt"], "the wake run has the rules block, no routine question")
check(r.api.posts and r.api.posts[-1]["uid"] == 7, "its answer goes into the person's chat")
check(not r.state.data["queue"] and r.job_watch() == 0 and calls() == [], "nothing left: no second wake run")
j = mkjob(51, state="stopped")
aj.add_wake(j, "stopped", hint="It was stopped by a person.")
r.job_watch()
q = list(r.state.data["queue"])
r.handle(q, save=True)
r.queue_drop(q)
p = calls()[0]["prompt"]
check("was stopped" in p and "Do not start it again" in p, "a stopped job: a wake run with the hint not to restart it")
j = mkjob(52, state="done", chat_user=None)
check(not aj.add_wake(j, "done", "x") and not os.path.exists(os.path.join(r.state_dir, "wakes", "52.json")), "no chat person: no wake run")
check(any("Job #52" in n for n in r.extras.take_notes()) if r.extras else True, "... a note for the next run instead")

# ---- #1445: after a restart a lost job is continued ONCE in the same session
spawned = []
real_spawn = aj.spawn_run
aj.spawn_run = lambda j, extra=None: spawned.append((j["id"], list(extra or [])))
mkjob(60, runner_pid=999999, session="S-9")
mkjob(61, runner_pid=999999)
check(aj.revive_lost(None) == [60] and spawned == [(60, ["--revive"])], f"a lost job with a session goes on once: {spawned}")
check(aj.load(60)["state"] == "starting" and aj.load(61)["state"] == "lost", "the one without a session stays lost")
w = aj.take_wakes()
check(len(w) == 1 and w[0]["job"]["id"] == 61 and w[0]["job"]["state"] == "lost", f"... and wakes the chat agent: {w}")
j = aj.load(60)
j["revived"] = time.time() - 120  # its new process is gone too
aj.save(j)
check(aj.revive_lost(None) == [] and spawned == [(60, ["--revive"])], "lost again: never continued a second time")
w = aj.take_wakes()
check(aj.load(60)["state"] == "lost" and len(w) == 1 and "interrupted again" in w[0]["hint"], f"... it stays lost and wakes the chat agent: {w}")
check(aj.revive_lost(None) == [] and aj.take_wakes() == [], "nothing more after that")
aj.spawn_run = real_spawn
mkjob(62, state="starting", created=time.time())
check(aj.revive_lost(None) == [] and aj.load(62)["state"] == "starting", "a job that is just being started is not lost")

# the continued run itself: the same session (--resume) with the note instead of the brief
CMD2 = os.path.join(TMP, "bin", "agentcmd")  # not named claude: no stream input
shutil.copy(FAKE, CMD2)
os.chmod(CMD2, 0o755)
mkjob(63, state="starting", session="S-9", cmd=[CMD2])
env = dict(os.environ, KALMIDO_STATE_DIR=r.state_dir)
rc = subprocess.run([sys.executable, os.path.join(MCP, "agent_job.py"), "_run", "63", "--revive"], env=env, capture_output=True, timeout=60).returncode
cl = calls()
check(rc == 0 and len(cl) == 1 and cl[0]["args"][-2:] == ["--resume", "S-9"] and cl[0]["prompt"].startswith("## Fixed rules")
      and cl[0]["prompt"].strip().endswith(aj.REVIVE_PROMPT),  # 2.46.6 (#1715, review): the rules block in front of the note too
      f"revive: --resume of the same session, rules block + the note as the prompt: {cl}")
w = aj.take_wakes()
check(aj.load(63)["state"] == "done" and len(w) == 1 and w[0]["job"]["state"] == "done", "the continued job ends and wakes the chat agent")

print(f"p2466_a_launcher: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
