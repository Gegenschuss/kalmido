#!/usr/bin/env python3
"""2.44.0 part B (#1443 #1445 #1447): the additions of the reference starter, without a server (a stub API and a fake agent
command that plays stream-json):
 - outbox: a file the agent puts into $KALMIDO_OUTBOX and an image it looks at with Read reach the chat as files (before the
   answer); a task run has no outbox and attaches nothing; an image from an upload folder is not attached again
 - bundling: three task_added events (+ a missed) become ONE run with the tasks' text, the information becomes a note; only
   information = no run; a chat message is never held back
 - jobs: agent_job.py start / progress / list / stop; the job posts its result with its files into the chat and leaves a note
   for the next run; after a compaction the brief is played in again; the plan limit waits and resumes the same session;
   --worktree has a cap
Needs python3 and git."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(N, "..", "mcp"))
F, OK = [], [0]


def check(c, what):
    if c:
        OK[0] += 1
    else:
        F.append(what)
        print("FAIL:", what, flush=True)


TMP = tempfile.mkdtemp(prefix="kalmido-p2440b-")
REQS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        REQS.append({"m": method, "p": self.path, "ct": self.headers.get("Content-Type") or "", "body": body})
        out, code = {}, 200
        if self.path.startswith("/api/v1/tasks/") and self.path.endswith("/comments"):
            out = {"data": [{"author": {"id": 1, "name": "Pat"}, "text": "please check the footer"}]}
        elif self.path.startswith("/api/v1/tasks/"):
            tid = int(self.path.split("/")[4])
            out = {"data": {"id": tid, "title": f"Task {tid}", "notes": f"Description of task {tid}", "list_id": 3, "status": "open"}}
        elif self.path == "/api/v1/agent/jobs" and method == "POST":
            out, code = {"id": 41 + sum(1 for r in REQS if r["p"] == "/api/v1/agent/jobs" and r["m"] == "POST") - 1}, 201
        elif self.path == "/api/v1/agent/progress":
            code = 201
        elif method == "POST" and "/agent/chats/" in self.path:
            out = {"id": 900 + len(REQS)}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = lambda self: self._do("GET")
    do_POST = lambda self: self._do("POST")
    do_PUT = lambda self: self._do("PUT")
    do_PATCH = lambda self: self._do("PATCH")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"

# ---- a fake agent command: the mode comes from words in the prompt
FAKE = os.path.join(TMP, "fakeclaude")
SEEN = os.path.join(TMP, "seen.jsonl")
with open(FAKE, "w") as f:
    f.write(r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
stream_in = "--input-format" in args
if stream_in:
    first = json.loads(sys.stdin.readline())["message"]["content"][0]["text"]
else:
    first = sys.stdin.read()
with open(os.environ["FAKE_SEEN"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": first, "outbox": os.environ.get("KALMIDO_OUTBOX"),
                        "job": os.environ.get("KALMIDO_JOB_ID"), "chat_user": os.environ.get("KALMIDO_CHAT_USER")}) + "\n")
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "model": "fake-1", "session_id": "sess-1"})
ob = os.environ.get("KALMIDO_OUTBOX")
if "WRITEFILE" in first and ob:
    open(os.path.join(ob, "report.txt"), "w").write("hello report")
if "LOOKIMAGE" in first:
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "I look at the picture"},
         {"type": "tool_use", "name": "Read", "input": {"file_path": os.environ["FAKE_IMG"]}}]}})
if "LOOKUPLOAD" in first:
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": os.environ["FAKE_UPLOAD_IMG"]}}]}})
if "SLOW" in first:
    time.sleep(120)
if "COMPACT" in first:
    out({"type": "system", "subtype": "compact_boundary"})
    again = json.loads(sys.stdin.readline())["message"]["content"][0]["text"]
    with open(os.environ["FAKE_SEEN"], "a") as f:
        f.write(json.dumps({"reinjected": again}) + "\n")
if "LIMIT" in first and "--resume" not in args:
    out({"type": "rate_limit_event", "rate_limit_info": {"rateLimitType": "five_hour", "utilization": 1.0}})
    out({"type": "result", "subtype": "error", "is_error": True, "result": "You hit your usage limit"})
    sys.exit(1)
out({"type": "result", "subtype": "success", "is_error": False, "result": "All done: " + ("resumed" if "--resume" in args else "first")})
''')
os.chmod(FAKE, 0o755)

IMG = os.path.join(TMP, "shot.png")
with open(IMG, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
os.makedirs(os.path.join(TMP, "uploads"))
UPIMG = os.path.join(TMP, "uploads", "mine.png")
shutil.copy(IMG, UPIMG)

ENV = dict(os.environ, KALMIDO_URL=URL, KALMIDO_TOKEN="abk_stub_token_for_tests_1", FAKE_SEEN=SEEN, FAKE_IMG=IMG,
           FAKE_UPLOAD_IMG=UPIMG)
ENV.pop("KALMIDO_OUTBOX", None)


def seen():
    try:
        return [json.loads(l) for l in open(SEEN) if l.strip()]
    except OSError:
        return []


def reset():
    REQS.clear()
    if os.path.exists(SEEN):
        os.remove(SEEN)


def runner(events, state, extra_env=None):
    ef = os.path.join(TMP, "events.jsonl")
    with open(ef, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    r = subprocess.run([sys.executable, os.path.join(MCP, "agent_run.py"), "--state", state, "--once-event", ef, "--", FAKE],
                       env={**ENV, **(extra_env or {})}, capture_output=True, text=True, timeout=120)
    return r


def chat(body, mid=1):
    return {"event": "chat", "seq": mid, "data": {"user": {"id": 7, "name": "Pat"}, "message": {"id": mid, "body": body}}}


def files_posts():
    return [r for r in REQS if r["m"] == "POST" and "/agent/chats/" in r["p"] and r["ct"].startswith("multipart/")]


def json_posts():
    return [json.loads(r["body"]) for r in REQS if r["m"] == "POST" and "/agent/chats/" in r["p"] and r["ct"].startswith("application/json")]


# ======== outbox (#1443)
reset()
st1 = os.path.join(TMP, "st1")
r = runner([chat("WRITEFILE and LOOKIMAGE please")], st1)
check(r.returncode == 0, f"runner exit 0 ({r.stderr[-300:]})")
fp = files_posts()
check(len(fp) == 1, f"one multipart post with the files: {len(fp)}")
if fp:
    b = fp[0]["body"]
    check(b'filename="report.txt"' in b and b"hello report" in b, "the file of the outbox is attached")
    check(b'filename="shot.png"' in b and b"image/png" in b, "the image the agent looked at is attached (MIME image/png)")
idx_files = next((i for i, q in enumerate(REQS) if q["ct"].startswith("multipart/")), -1)
idx_answer = next((i for i, q in enumerate(REQS) if q["ct"].startswith("application/json") and "/agent/chats/" in q["p"] and q["m"] == "POST"), -1)
check(0 <= idx_files < idx_answer, "the files come before the answer (its buttons stay the newest message)")
s = seen()
check(s and s[0]["outbox"] and "Files for the person" in s[0]["prompt"] and "agent_job.py" in s[0]["prompt"],
      "chat run: outbox in the environment, hints for files and jobs in the prompt")
check(s and s[0]["job"] is None and s[0]["chat_user"] == "7", "the run knows the person (KALMIDO_CHAT_USER)")
check(not os.path.exists(s[0]["outbox"]), "the outbox folder is removed after sending")

reset()
r = runner([chat("LOOKUPLOAD only")], os.path.join(TMP, "st1b"))
check(not files_posts(), "an image from an upload folder is not attached again")

reset()
r = runner([{"event": "comment", "seq": 5, "data": {"task": {"id": 5, "title": "Footer"}, "comment": {"id": 2, "text": "WRITEFILE LOOKIMAGE"}}}],
           os.path.join(TMP, "st1c"))
s = seen()
check(len(s) == 1 and not s[0]["outbox"], "task run: no outbox")
check(not files_posts(), "task run: nothing attached")
check(s and "Description of task 5" in s[0]["prompt"] and "please check the footer" in s[0]["prompt"],
      "task run: description and latest comments come with the event")

# ======== bundling (#1447)
reset()
evs = [{"event": "task_added", "seq": i, "data": {"task": {"id": 10 + i, "title": f"New {i}"}, "list": {"id": 3, "name": "Dev"},
                                                   "how": "created", "user": {"id": 7, "name": "Pat"}}} for i in (1, 2, 3)]
evs.append({"event": "missed", "seq": 4, "data": {"count": 12, "events": {"comment": 12}}})
r = runner(evs, os.path.join(TMP, "st2"))
s = seen()
check(len(s) == 1, f"3 task events + 1 information = ONE run: {len(s)}")
if s:
    p = s[0]["prompt"]
    check("Bundled run" in p and all(f"Task {10 + i}" in p for i in (1, 2, 3)) and "never build" in p, "the bundle names its tasks and says: comment, never build")
    check("Description of task 11" in p, "the bundle carries the task text")
    check("Notes since your last run" in p and "older events were folded together" in p, "the information is a note in that run")
    check(not s[0]["outbox"], "a bundled run is a task run (no outbox)")

reset()
r = runner([{"event": "missed", "seq": 1, "data": {"count": 3}}], os.path.join(TMP, "st2b"))
check(not seen(), "only information: no run")
notes = os.path.join(TMP, "st2b", "notes.jsonl")
check(os.path.exists(notes) and "folded" in open(notes).read(), "...it waits as a note for the next run")

reset()
r = runner([evs[0], chat("hello now", 9)], os.path.join(TMP, "st2c"))
s = seen()
check(len(s) == 2 and "hello now" in s[0]["prompt"] and "Bundled run" in s[1]["prompt"], "a chat message is never held back: it runs first, the bundle after")

# a pending bundle survives a restart
sys.path.insert(0, MCP)
import agent_extras  # noqa: E402
class A:  # noqa: E301
    base, token = URL + "/api/v1", "t"
    def req(self, *a, **k): return {}
ex = agent_extras.Extras(A(), os.path.join(TMP, "st3"), ["x"])
ex.gather_s = 120
check(ex.intake([evs[0]]) == [] and not ex.due() and 1 <= ex.wait_s(50) <= 50, "a collected event waits (not due yet)")
ex2 = agent_extras.Extras(A(), os.path.join(TMP, "st3"), ["x"])
check(len(ex2.pending) == 1, "the pending bundle is read again after a restart")
ex2.gather_s = 0
check(ex2.due() and [e["event"] for e in ex2.take_bundle()] == ["task_bundle"], "...and runs as one event when due")
ex3 = agent_extras.Extras(A(), os.path.join(TMP, "st4"), ["x"])
ex3.owners = {"1"}
check(ex3.intake([evs[0]]) == [] and not ex3.pending and ex3.take_notes(), "an event of a person who is not an owner is only a note")

# ======== jobs (#1445)
JENV = {**ENV, "KALMIDO_STATE_DIR": os.path.join(TMP, "jst"), "KALMIDO_CHAT_USER": "7", "KALMIDO_JOB_CMD": json.dumps([FAKE]),
        "KALMIDO_JOB_TEST_WAIT_S": "1"}


def job(*a, inp=None, env=None):
    return subprocess.run([sys.executable, os.path.join(MCP, "agent_job.py"), *a], input=inp, env={**JENV, **(env or {})},
                          capture_output=True, text=True, timeout=60)


def job_state(jid):
    try:
        return json.load(open(os.path.join(TMP, "jst", "jobs", str(jid), "job.json")))
    except (OSError, ValueError):
        return {}


def alive(p):
    try:
        os.kill(p, 0)
        return True
    except OSError:
        return False


def wait_for(fn, secs=40):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.3)
    return None


reset()
r = job("start", "--title", "Release build", "-", inp="WRITEFILE build the release")
check(r.returncode == 0 and "Job #41" in r.stdout, f"job start: {r.stdout.strip()} {r.stderr[-200:]}")
check(wait_for(lambda: job_state(41).get("state") == "done"), "the job ends as done")
created = [json.loads(q["body"]) for q in REQS if q["p"] == "/api/v1/agent/jobs" and q["m"] == "POST"]
# 2.59.0 (#1827): the title starts with the job's name ("Name: Release build"), the name also goes along as {name}
check(created and created[0]["title"].endswith(": Release build") and created[0]["title"].startswith(created[0].get("name", "-") + ": ")
      and created[0]["user_id"] == 7, f"the Kalmido job is created for the person {created[:1]}")
fp = [q for q in REQS if q["ct"].startswith("multipart/") and "/agent/chats/7" in q["p"]]
check(fp and b'filename="report.txt"' in fp[0]["body"] and b"All done: first" in fp[0]["body"] and b'name="job_id"' in fp[0]["body"],
      "the result with the job's file is posted into the chat, linked to the job")
check(any(q["m"] == "PATCH" and q["p"].endswith("/jobs/41") and b'"done"' in q["body"] for q in REQS), "the Kalmido job is set to done")
# 2.46.6 (#1445): a job with a chat person wakes the chat agent (one wake file) instead of a note for the next run
wk = os.path.join(TMP, "jst", "wakes", "41.json")
check(os.path.exists(wk) and json.load(open(wk))["job"]["state"] == "done", "a wake file says the job is done")
sj = [x for x in seen() if x.get("job") == "41"]
check(sj and sj[0]["outbox"].endswith("outbox"), "the job has its own outbox")
r = job("list")
check("#41" in r.stdout and "done" in r.stdout, "list shows the job")
r = job("progress", "41", "half way, token abk_stub_token_for_tests_1")
pr = [q for q in REQS if q["m"] == "PATCH" and b"half way" in q["body"]]
check(r.returncode == 0 and pr and b"abk_stub" not in pr[0]["body"], "progress goes to the job log, secrets masked")

# stop
reset()
r = job("start", "--title", "Slow one", "-", inp="SLOW work")
jid = int(r.stdout.split("#")[1].split()[0]) if "#" in r.stdout else 0
check(wait_for(lambda: job_state(jid).get("cmd_pid")), "the slow job runs")
pid = job_state(jid).get("cmd_pid")
check(job("stop", str(jid)).returncode == 0, "stop")
check(wait_for(lambda: not alive(pid), 15), "the job's process is gone after stop")
check(job_state(jid).get("state") == "stopped", "state stopped")

# a Stop event of a job goes through the runner's intake
reset()
r = job("start", "--title", "Slow two", "-", inp="SLOW again")
jid2 = int(r.stdout.split("#")[1].split()[0])
wait_for(lambda: job_state(jid2).get("cmd_pid"))
ex = agent_extras.Extras(A(), os.path.join(TMP, "jst"), ["x"])
check(ex.intake([{"event": "job", "seq": 3, "data": {"action": "stop", "job": {"id": jid2}}}]) == [], "event job/stop is consumed by the runner")
check(wait_for(lambda: job_state(jid2).get("state") == "stopped", 10), "...and stops the job")
wait_for(lambda: not alive(job_state(jid2).get("cmd_pid") or 0), 15)

# compaction: the brief is played in again
reset()
r = job("start", "--title", "Compact", "-", inp="COMPACT brief text")
jid = int(r.stdout.split("#")[1].split()[0])
check(wait_for(lambda: job_state(jid).get("state") == "done"), "compaction job ends")
re_ = [x for x in seen() if x.get("reinjected")]
check(re_ and "compacted" in re_[0]["reinjected"] and "COMPACT brief text" in re_[0]["reinjected"], "after compaction the brief is played in again")

# plan limit: wait, resume the same session
reset()
r = job("start", "--title", "Limit", "-", inp="LIMIT work")
jid = int(r.stdout.split("#")[1].split()[0])
check(wait_for(lambda: job_state(jid).get("state") == "done", 60), "limit job ends done after the resume")
sj = [x for x in seen() if x.get("job") == str(jid)]
check(len(sj) == 2 and "--resume" in sj[1]["args"] and "sess-1" in sj[1]["args"] and "plan limit was reset" in sj[1]["prompt"],
      "the same session is resumed (--resume) after the wait")
check(job_state(jid).get("resumes") == 1, "one resume counted")
check(any(b"All done: resumed" in q["body"] for q in REQS if "/agent/chats/7" in q["p"]), "the result of the resumed run is posted")

# worktree cap
repo = os.path.join(TMP, "repo")
os.makedirs(repo)
g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)  # noqa: E731
g("init", "-q"); g("-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
reset()
env_wt = {"KALMIDO_JOB_WORKTREES": "1"}
r1 = subprocess.run([sys.executable, os.path.join(MCP, "agent_job.py"), "start", "--title", "WT one", "--worktree", "-"], input="SLOW wt",
                    env={**JENV, **env_wt}, cwd=repo, capture_output=True, text=True, timeout=60)
check(r1.returncode == 0, f"worktree job starts: {r1.stdout} {r1.stderr[-200:]}")
w1 = int(r1.stdout.split("#")[1].split()[0]) if "#" in r1.stdout else 0
check(w1 and os.path.isdir(os.path.join(TMP, "jst", "jobs", str(w1), "wt")) and f"job/{w1}" in g("branch").stdout, "own working copy and branch job/<id>")
r2 = subprocess.run([sys.executable, os.path.join(MCP, "agent_job.py"), "start", "--title", "WT two", "--worktree", "-"], input="SLOW wt",
                    env={**JENV, **env_wt}, cwd=repo, capture_output=True, text=True, timeout=60)
check(r2.returncode == 3 and "already" in r2.stdout, "the cap of open jobs with a working copy refuses another")
job("stop", str(w1))
wait_for(lambda: not alive(job_state(w1).get("cmd_pid") or 0), 15)

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2440_b_launcher: {OK[0]} ok, {len(F)} failed")
sys.exit(1 if F else 0)
