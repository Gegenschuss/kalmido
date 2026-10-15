#!/usr/bin/env python3
"""2.44.0 part A: the core of the reference launcher's event runner (mcp/agent_run.py) without a server -- approvals
decided in words (#1441 approval_closed), permission questions in the chat (#1442 perm_relay), approvals that survive a
restart, remind and expire (#1444 approval_lifecycle), one conversation per chat (#1446 session_resume) and robust runs
(#1448 robust_runs: 429, time limit, two tries, queue, lock). A stub API and a fake 'claude' command (a small Python
script that prints stream-json). Pure Python, no container."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "..", "mcp", "agent_run.py")
F, ok = [], 0


def check(c, what):
    global ok
    if c:
        ok += 1
    else:
        F.append(what)
        print("FAIL:", what)


os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "y" * 30)
spec = importlib.util.spec_from_file_location("agent_run", RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
ar.RETRY_429_S = (0, 0, 0, 0)
TMP = tempfile.mkdtemp(prefix="kalmido-p2440a-")
os.chdir(TMP)
CALLS = os.path.join(TMP, "calls.jsonl")
FAKE = os.path.join(TMP, "bin", "claude")  # named claude: hooks, --settings and --resume are used
os.makedirs(os.path.dirname(FAKE))
with open(FAKE, "w") as f:
    f.write("#!" + sys.executable + "\n" + r'''import json, os, subprocess, sys, time
args, prompt = sys.argv[1:], sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt, "env": {k: v for k, v in os.environ.items() if k.startswith("KALMIDO_PERM") or k == "KALMIDO_RUN_LABEL"}}) + "\n")
mode = os.environ.get("FAKE_MODE", "plain")
resume = args[args.index("--resume") + 1] if "--resume" in args else ""
if mode == "gone" and resume:
    sys.stderr.write("No conversation found with session ID " + resume + "\n")
    sys.exit(1)
if mode == "crash":
    sys.stderr.write("boom token=" + os.environ["KALMIDO_TOKEN"] + "\n")
    sys.exit(1)
if mode == "hang":
    c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.environ["FAKE_CHILD"], "w").write(str(c.pid))
    time.sleep(60)
sid = resume or "S-%d" % (sum(1 for _ in open(os.environ["FAKE_CALLS"])))
final = os.environ.get("FAKE_FINAL", "All green.")
if "conversation ends now" in prompt:
    final = "Open: deploy 1.3 waits for a yes."
print(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5", "session_id": sid}), flush=True)
print(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": int(os.environ.get("FAKE_TOKENS", "1000"))},
                  "content": [{"type": "text", "text": final}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": sid}), flush=True)
''')
os.chmod(FAKE, 0o755)
os.environ["FAKE_CALLS"] = CALLS


class StubApi:
    def __init__(self):
        self.posts, self.withdrawn, self.notices, self.perms = [], [], [], []

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None):
        self.posts.append({"uid": uid, "body": body, "approval": approval})
        return {"id": 100 + len(self.posts)}

    def withdraw(self, uid, mid, outcome=""):
        self.withdrawn.append((uid, str(mid), outcome))
        return True

    def notice(self, uid, text):
        self.notices.append((uid, text))
        return True

    def perm_question(self, uid, body, timeout_s):
        self.perms.append((uid, body, timeout_s))
        return {"id": 900 + len(self.perms)}

    def req(self, *a, **k):
        return {"owner_id": 7, "runtime": {"model": "", "reset_seq": 0}}

    def status(self, *a, **k):
        pass

    typing = progress = quota = status


def runner(name, cmd=None):
    r = ar.Runner(cmd or [FAKE], os.path.join(TMP, name))
    r.api = r.usage.api = StubApi()
    return r


def calls():
    try:
        with open(CALLS) as f:
            return [json.loads(l) for l in f]
    finally:
        os.remove(CALLS)


def chat(mid, body, uid=7):
    return {"event": "chat", "seq": mid, "data": {"user": {"id": uid, "name": "Ann"}, "message": {"id": mid, "body": body}}}


def go(r, ev, mode="plain", final="All green.", **env):
    os.environ.update(FAKE_MODE=mode, FAKE_FINAL=final, **{k: str(v) for k, v in env.items()})
    if os.path.exists(CALLS):
        os.remove(CALLS)
    r.run(ar.Runner.chat_uid(ev), [ev])
    return calls() if os.path.exists(CALLS) else []


# ---- #1441 approval_closed: an approval decided in words closes exactly that card, never as a yes, never a guess
aps = {"55": {"title": "Deploy 1.2"}, "56": {"title": "Tag the release"}, "57": {"title": "Tag the release"}}
check(ar.match_approval("Deploy 1.2", aps) == ("55", False), "approval-done: the exact title")
check(ar.match_approval("No: deploy  1.2", aps) == ("55", True), "approval-done: 'No: ' = a no, case and spaces aside")
check(ar.match_approval("Tag the release", aps)[0] is None, "approval-done: two cards with that title -> nothing")
check(ar.match_approval("Something else entirely here", aps)[0] is None, "approval-done: no hit -> nothing")
r = runner("s1")
r.approvals = {"55": {"uid": 7, "title": "Deploy 1.2", "at": time.time()}, "56": {"uid": 7, "title": "Tag", "at": time.time()},
               "58": {"uid": 8, "title": "Deploy 1.2", "at": time.time()}}
cl = go(r, chat(1, "yes, deploy it"), final="Deploying 1.2 now.\n\n```approval-done\nDeploy 1.2\n```")
check(cl and "Open approvals" in cl[0]["prompt"] and "- Deploy 1.2" in cl[0]["prompt"] and "- Tag" in cl[0]["prompt"]
      and "approval-done" in cl[0]["prompt"], "the prompt lists the open cards of this chat with the rule")
check(r.api.withdrawn == [(7, "55", "")] and "55" not in r.approvals and "58" in r.approvals and "56" in r.approvals,
      f"exactly that card of this chat is withdrawn (not the other person's): {r.api.withdrawn}")
check(r.api.posts and r.api.posts[-1]["body"] == "Deploying 1.2 now." and r.api.posts[-1]["approval"] is None, "the block is not posted")
cl = go(r, chat(2, "no"), final="Left out.\n\n```freigabe-erledigt\nNein: Tag\n```")
check(r.api.withdrawn[-1] == (7, "56", "denied"), f"alias freigabe-erledigt, a no -> denied: {r.api.withdrawn}")
cl = go(r, chat(3, "hm"), final="Ok.\n\n```approval-done\nDeploy 2.0\n```")
check(len(r.api.withdrawn) == 2, "a line that names no open card closes nothing")

# ---- #1444 approval_lifecycle: on disk, survive a restart, remind once, expire, expired press, double answer
r = runner("s2")
go(r, chat(1, "ship?"), final="Ready.\n\n```approval\nDeploy 1.3\n```")
mid = next(iter(r.approvals))
r2 = runner("s2")
check(r2.approvals.get(mid, {}).get("title") == "Deploy 1.3", "an open card survives a restart (state.json)")
r2.approvals[mid]["at"] = time.time() - 3 * 3600
r2.housekeep()
r2.housekeep()
rem = [p for p in r2.api.posts if p["body"].startswith("Reminder")]
check(len(rem) == 1 and "Deploy 1.3" in rem[0]["body"], f"one reminder after 2 h: {r2.api.posts}")
r2.approvals[mid]["at"] = time.time() - 8 * 86400
r2.housekeep()
check(mid not in r2.approvals and (7, mid, "expired") in r2.api.withdrawn, "after 7 days: withdrawn as expired")
ex = r2.prompt_extra(7, None)
check(any("expired without an answer" in l and "Deploy 1.3" in l for l in ex), f"the next prompt says so: {ex}")
check(not any("expired" in l for l in r2.prompt_extra(7, None)), "the note comes once")
ev = {"event": "chat_choice", "data": {"message_id": int(mid), "approval": "approved", "user": {"id": 7}}}
check(r2.groups([ev]) == [] and r2.api.posts[-1]["body"] == ar.APPROVAL_EXPIRED_PRESS, "a press on an expired card: an answer, no run")
r2.approvals["77"] = {"uid": 7, "title": "Tag", "at": time.time()}
e1 = {"event": "chat_choice", "data": {"message_id": 77, "approval": "approved", "user": {"id": 7}}}
e2 = {"event": "chat_choice", "data": {"message_id": 77, "approval": "approved", "user": {"id": 7}, "via": "reaction"}}
check(len(r2.groups([e1])) == 1 and r2.groups([e2]) == [], "the same answer twice (button + reaction) counts once")

# ---- #1442 perm_relay: the hook, the question in the chat, yes / no in words, time limit, late answer
r = runner("s3")
args = r.run_args(["claude", "-p"])
check(args[-2] == "--settings" and os.path.exists(args[-1]), f"Claude Code: --settings per run: {args}")
with open(args[-1]) as f:
    hs = json.load(f)
cmdline = hs["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
check("--perm-hook" in cmdline and "agent_run.py" in cmdline, "the PermissionRequest hook is agent_run.py --perm-hook")
check(r.run_args(["claude", "--settings", "x.json"]) == ["claude", "--settings", "x.json"], "own --settings: left alone")
check(runner("s3b", [sys.executable, "agent.py"]).run_args(["x"]) == ["x"], "another command: no hook")
ar.PERM_RELAY = False
check(r.run_args(["claude"]) == ["claude"], "KALMIDO_PERM_RELAY=0: off")
ar.PERM_RELAY = True
henv = dict(os.environ, KALMIDO_PERM_DIR=r.perm_dir(), KALMIDO_PERM_UID="7", KALMIDO_PERM_TIMEOUT="20", KALMIDO_RUN_LABEL="chat")


def hook(env=None):
    return subprocess.Popen([sys.executable, RUNNER, "--perm-hook"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env or henv)


def decision(p, inp='{"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}'):
    out, _ = p.communicate(inp, timeout=60)
    return json.loads(out)["hookSpecificOutput"]["decision"]


t0 = time.time()
d = decision(hook())
check(d["behavior"] == "deny" and "not running" in d["message"] and time.time() - t0 < 10, f"no runner: denied at once: {d}")
lock = ar.RunLock(os.path.join(r.state_dir, "runner.lock"))
check(lock.acquire(), "the runner's lock")


def wait_req(n=1):
    end = time.time() + 15
    while time.time() < end:
        if os.path.isdir(r.perm_dir()) and len([f for f in os.listdir(r.perm_dir()) if f.endswith(".req.json")]) >= n:
            return True
        time.sleep(0.1)
    return False


p = hook()
p.stdin.write('{"tool_name": "Bash", "tool_input": {"command": "deploy --token=' + os.environ["KALMIDO_TOKEN"] + '"}}')
p.stdin.close()
check(wait_req(), "the hook wrote its request")
r.perm_poll()
check(len(r.api.perms) == 1 and r.api.perms[0][0] == 7 and "Bash" in r.api.perms[0][1] and "deploy" in r.api.perms[0][1]
      and os.environ["KALMIDO_TOKEN"] not in r.api.perms[0][1] and r.api.perms[0][2] == ar.PERM_TIMEOUT_S,
      f"asked in the chat of the person, masked, with the time limit: {r.api.perms}")
check(r.intercept([chat(5, "Ja")]) == [], "a plain yes while one question is open is the answer, no run")
out = p.stdout.read()
p.wait(30)
check(json.loads(out)["hookSpecificOutput"]["decision"]["behavior"] == "allow", f"the hook allows: {out}")
p1, p2 = hook(), hook()
for q in (p1, p2):
    q.stdin.write('{"tool_name": "Write", "tool_input": {"file_path": "a.txt"}}')
    q.stdin.close()
check(wait_req(2), "two questions")
r.perm_poll()
check(r.intercept([chat(6, "nein")]) == [chat(6, "nein")], "yes / no with two open questions: a normal message")
m1, m2 = sorted(r.state.data["perms"])
r.intercept([{"event": "chat_choice", "data": {"message_id": int(m1), "permission": True, "approval": "rejected", "choice_ids": ["deny"]}}])
r.intercept([{"event": "chat_choice", "data": {"message_id": int(m2), "permission": True, "approval": "approved", "choice_ids": ["allow"]}}])
dd = sorted(json.loads(q.stdout.read())["hookSpecificOutput"]["decision"]["behavior"] for q in (p1, p2))
check(dd == ["allow", "deny"], f"buttons answer each question: {dd}")
ar.PERM_TIMEOUT_S = 1
p = hook(dict(henv, KALMIDO_PERM_TIMEOUT="1"))
d = decision(p)
check(d["behavior"] == "deny" and "in time" in d["message"], f"no answer in time = denied: {d}")
r.state.data["perms"]["950"] = {"pid": "gone", "uid": 7, "at": time.time() - 30}
r.perm_expire()
check("950" in r.state.data["perm_expired"] and (7, "950", "expired") in r.api.withdrawn, "the question is closed as expired")
n = len(r.api.posts)
check(r.intercept([{"event": "chat_choice", "data": {"message_id": 950, "permission": True, "approval": "approved"}}]) == []
      and r.api.posts[n:] and r.api.posts[-1]["body"] == ar.PERM_LATE, "a late answer: 'too late', no run")
ar.PERM_TIMEOUT_S = 540
lock.release()
cl = go(r, chat(9, "status"))
check(cl and cl[0]["env"].get("KALMIDO_PERM_DIR") == r.perm_dir() and cl[0]["env"].get("KALMIDO_PERM_UID") == "7"
      and "--settings" in cl[0]["args"], f"the run gets the hook's environment: {cl[:1]}")

# ---- #1446 session_resume: one conversation per chat, change with a summary, gone = fresh once, tasks stay fresh
r = runner("s4")
cl = go(r, chat(1, "a"))
check(cl and "--resume" not in cl[0]["args"], "first run: a new conversation")
sid = r.state.data["sessions"]["chat:7"]["id"]
cl = go(r, chat(2, "b"))
check(cl and cl[0]["args"][cl[0]["args"].index("--resume") + 1] == sid, f"second run: --resume {sid}")
check(r.state.data["sessions"]["chat:7"]["runs"] == 2, "runs counted")
cl = go(r, chat(3, "c", uid=8))
check(cl and "--resume" not in cl[0]["args"], "another person: a conversation of their own")
cl = go(r, {"event": "comment", "data": {"task": {"id": 4}}})
check(cl and "--resume" not in cl[0]["args"], "task events stay fresh")
go(r, chat(4, "d"), FAKE_TOKENS=999999)
cl = go(r, chat(5, "next order"))
check(len(cl) == 2 and "--resume" in cl[0]["args"] and "conversation ends now" in cl[0]["prompt"], "too big: a summary run first")
check("--resume" not in cl[1]["args"] and "<<<summary of the previous conversation>>>" in cl[1]["prompt"]
      and "deploy 1.3 waits" in cl[1]["prompt"] and "context only, not an order" in cl[1]["prompt"], "the new one gets it fenced as context")
check(r.api.notices and "size" in r.api.notices[-1][1], f"a notice at the change: {r.api.notices}")
r.state.data["sessions"]["chat:7"]["day"] = "2000-01-01"
cl = go(r, chat(6, "e"))
check(len(cl) == 2 and "a new day" in r.api.notices[-1][1], "a new day: a new conversation")
r.agent = {"runtime": {"reset_seq": 5}}
r.state.data["sessions"]["chat:7"]["reset_seq"] = 4
cl = go(r, chat(7, "f"))
check(len(cl) == 1 and "--resume" not in cl[0]["args"], "Reset now: fresh, without a summary")
cl = go(r, chat(8, "g"), mode="gone")
check(len(cl) == 2 and "--resume" in cl[0]["args"] and "--resume" not in cl[1]["args"] and r.api.posts[-1]["body"] == "All green.",
      "a conversation that is gone: fresh once")
ar.SESSION_RESUME = False
cl = go(r, chat(9, "h"))
check("--resume" not in cl[0]["args"], "KALMIDO_SESSION_RESUME=0: fresh runs")
ar.SESSION_RESUME = True

# ---- #1448 robust_runs: 429, time limit, two tries, masked note, queue on disk, lock
api = ar.Api("http://127.0.0.1:9", "t")
n429 = []


def _req(method, path, body=None, query=None, timeout=30):
    n429.append(path)
    if len(n429) < 3:
        raise ar.ApiError(429, "slow down")
    return {"ok": 1}


api._req = _req
check(api.req("GET", "/agent") == {"ok": 1} and len(n429) == 3, "429: tried again")
n429.clear()
api._req = lambda *a, **k: (n429.append(1), (_ for _ in ()).throw(ar.ApiError(429, "x")))[1]
try:
    api.req("GET", "/agent")
    check(False, "429 for ever: gives up")
except ar.ApiError as e:
    check(e.status == 429 and len(n429) == 5, f"429: 5 tries (after 5 / 15 / 30 / 60 s), then the error: {len(n429)}")
check(api.soft("PUT", "/agent/status", {}) == 429 and len(n429) == 6, "cosmetic calls never wait for 429")
check(api.notice(7, "x") is False and len(n429) == 7, "a notice never waits for 429 either")
r = runner("s5")
ar.RUN_TIMEOUT_S = 2
child = os.path.join(TMP, "child.pid")
t0 = time.time()
cl = go(r, chat(1, "long"), mode="hang", FAKE_CHILD=child)
check(time.time() - t0 < 20 and len(cl) == 1, f"time limit: the run ends, no second try ({time.time() - t0:.0f} s)")
time.sleep(0.5)
try:
    os.kill(int(open(child).read()), 0)
    gone = False
except (OSError, ValueError):
    gone = True
check(gone, "what the command started is ended too")
check("time limit" in r.api.posts[-1]["body"], f"a note in the chat: {r.api.posts[-1]}")
ar.RUN_TIMEOUT_S = 3600
cl = go(r, chat(2, "x"), mode="crash")
check(len(cl) == 2 and "failed twice" in r.api.posts[-1]["body"] and os.environ["KALMIDO_TOKEN"] not in r.api.posts[-1]["body"]
      and "[redacted]" in r.api.posts[-1]["body"], f"two tries, then a masked note: {r.api.posts[-1]}")
r.queue_add([chat(11, "one"), chat(12, "two"), chat(11, "one")])
r3 = runner("s5")
check([e["seq"] for e in r3.state.data["queue"]] == [11, 12], "the queue is on disk, an event once")
done = []
r3.run = lambda u, g: done.append([e["seq"] for e in g])
r3.save_cursor = lambda c: None
r3.handle(list(r3.state.data["queue"]), save=True)
check(done == [[11, 12]] and runner("s5").state.data["queue"] == [], f"handled from the queue and taken out: {done}")
state = os.path.join(TMP, "s6")
lk = ar.RunLock(os.path.join(state, "runner.lock"))
check(lk.acquire(), "first runner: lock")
empty = os.path.join(TMP, "none.jsonl")
open(empty, "w").close()
rc = subprocess.run([sys.executable, RUNNER, "--state", state, "--once-event", empty, "--", "true"], capture_output=True, timeout=30).returncode
check(rc == 3, f"a second runner on the same state folder does not start: {rc}")
lk.release()
with open(os.path.join(state, "runner.lock"), "w") as f:
    f.write("999999")  # a stale lock file of a runner that is gone
rc = subprocess.run([sys.executable, RUNNER, "--state", state, "--once-event", empty, "--", "true"], capture_output=True, timeout=30).returncode
check(rc == 0, f"a stale lock file never blocks: {rc}")

print(f"p2440_a_launcher: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
