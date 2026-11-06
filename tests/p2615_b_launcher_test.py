#!/usr/bin/env python3
# kalmido-suite: after=p2440_a_launcher nodata
"""2.615.0 part B (#3658, #3757): the reference starter (mcp/agent_run.py, mcp/agent_job.py) does what the hosted service
does -- without a server (a stub API in the process, a small HTTP stub and a fake agent command for the job runs):
 - #3751 reply_ref: the answered message in full (fenced, up to 4000 characters, file names), else the quote + "only the start"
 - #3752 approval_closed: identical duplicate cards close one per line; "Card N: ..." wins; partial hits stay unambiguous
 - #3753 / #2390 approval_check: advice against and quoted words are no ask; an approval named in passing is one
 - #3754 status_typing: a task run sends the typing dots on its task; an old server (404) switches them off
 - #3755 job_wake: a wake after a done job may answer STILL (nothing posted); failed always posts
 - #2347 approval_move / job_cards: a card wanders to the newest answer; a job's result card knows its job, its answer goes
   to the job (inbox while it runs, a wake of the ended job in its session)
 - #1801 job_inbox: a person's message reaches the running job after its next tool step
 - #2422 abort: Stop with job_id ends that one local job
Pure Python, no container."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kt import check, done, until

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "mcp"))
sys.path.insert(0, MCP)
TMP = tempfile.mkdtemp(prefix="kalmido-p2615b-")
os.chdir(TMP)
REQS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        REQS.append({"m": method, "p": self.path, "ct": self.headers.get("Content-Type") or "", "body": body})
        out, code = {}, 200
        if self.path == "/api/v1/agent/jobs" and method == "POST":
            out, code = {"id": 61 + sum(1 for r in REQS if r["p"] == "/api/v1/agent/jobs" and r["m"] == "POST") - 1}, 201
        elif self.path == "/api/v1/agent/progress":
            code = 201
        elif method == "POST" and "/agent/chats/" in self.path:
            out = {"id": 5000 + len(REQS)}
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
JST = os.path.join(TMP, "jst")
os.environ.update(KALMIDO_URL=URL, KALMIDO_TOKEN="abk_" + "z" * 30, KALMIDO_STATE_DIR=JST)

spec = importlib.util.spec_from_file_location("agent_run", os.path.join(MCP, "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
ar.RETRY_429_S = (0, 0, 0, 0)
import agent_job  # noqa: E402  (the module the runner imports too)

# ---- the fake agent command (named claude: stream-json in for jobs); the mode comes from words in the prompt
FAKE = os.path.join(TMP, "bin", "claude")
SEEN = os.path.join(TMP, "seen.jsonl")
os.makedirs(os.path.dirname(FAKE))
with open(FAKE, "w") as f:
    f.write("#!" + sys.executable + "\n" + r'''import json, os, sys
args = sys.argv[1:]
stream_in = "--input-format" in args
first = json.loads(sys.stdin.readline())["message"]["content"][0]["text"] if stream_in else sys.stdin.read()
def seen(o):
    with open(os.environ["FAKE_SEEN"], "a") as f:
        f.write(json.dumps(o) + "\n")
seen({"args": args, "prompt": first, "job": os.environ.get("KALMIDO_JOB_ID")})
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "model": "fake-1", "session_id": "sess-2615"})
final = os.environ.get("FAKE_FINAL", "All green.")
if "WAITMSG" in first:
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "I build the first part"},
         {"type": "tool_use", "name": "Bash", "input": {"command": "true"}}]}})
    seen({"waiting": True})
    line = sys.stdin.readline()  # the launcher plays the inbox in as the next user message
    seen({"inbox": json.loads(line)["message"]["content"][0]["text"] if line.strip() else ""})
    final = "Built, with the message."
if "CARDRESULT" in first:
    final = "Ready to upload.\n\n```approval\nUpload the demo\n```"
if "answered your approval card" in first:
    final = "Uploaded."
out({"type": "result", "subtype": "success", "is_error": False, "result": final})
''')
os.chmod(FAKE, 0o755)
os.environ.update(FAKE_SEEN=SEEN)


def seen():
    try:
        return [json.loads(l) for l in open(SEEN) if l.strip()]
    except OSError:
        return []


class StubApi:
    def __init__(self):
        self.posts, self.withdrawn, self.typed, self.soft_calls = [], [], [], []
        self.lang = ""

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None, job_id=None):
        self.posts.append({"uid": uid, "body": body, "approval": approval, "suggest": suggest})
        return {"id": 700 + len(self.posts)}

    def withdraw(self, uid, mid, outcome=""):
        self.withdrawn.append((uid, str(mid), outcome))
        return True

    def task_typing(self, tid):
        self.typed.append(tid)
        return True

    def soft(self, method, path, body=None, timeout=20):
        self.soft_calls.append((method, path, body))
        return 200

    def req(self, *a, **k):
        return {"owner_id": 7, "runtime": {"model": "", "reset_seq": 0}}

    def status(self, *a, **k):
        pass

    typing = progress = quota = notice = status


def runner(name):
    r = ar.Runner([FAKE], os.path.join(TMP, name))
    r.api = r.usage.api = StubApi()
    return r


def go(r, evs, final="All green."):
    os.environ["FAKE_FINAL"] = final
    uid = ar.Runner.chat_uid(evs[0])
    r.run(uid, evs)


# ================================================================ #3751 reply_ref: the whole answered message
long = "Line one of a long message. " * 20 + "THE END"
full = ar.reply_hint({"id": 9, "name": "Ann", "user_id": 7, "text": long[:140], "full": {"text": long, "files": ["plan.pdf"]}})
check("THE END" in full and "plan.pdf" in full and "<<<message reply-9 from user 7>>>" in full, f"the whole message, fenced, with its files: {full[:200]}")
check(len(ar.reply_hint({"id": 9, "full": {"text": "x" * 9000}})) < 4300, "at most 4000 characters of it")
q = ar.reply_hint({"id": 9, "name": "Ann", "text": "y" * 140})
check(q.startswith('(This answers Ann: "') and "only the start" in q, f"not loaded: the quote and that only its start is known: {q[-80:]}")
check(ar.reply_hint({"id": 5, "name": "Ann", "text": "the blue one?"}) == '(This answers Ann: "the blue one?")', "a short quote as before")
api = ar.Api(URL, "t")
api.req = lambda m, p, b=None, query=None, timeout=30, retry=True: {"data": [{"id": 9, "body": long, "attachments": [{"name": "plan.pdf"}]}]}
check(api.reply_message(7, {"id": 9}) == {"text": long, "files": ["plan.pdf"]}, "reply_message reads the message by its id")
check(api.reply_message(7, {"id": 9, "deleted": True}) is None and api.reply_message(7, {"id": 9, "enc": True}) is None,
      "deleted / encrypted: nothing fetched")
api.req = lambda *a, **k: {"data": [{"id": 8, "body": "another"}]}
check(api.reply_message(7, {"id": 9}) is None, "another message in the answer: None (the quote stays)")

# ================================================================ #3752 / #2347 approval_closed: duplicates, numbers, words
aps = {"55": {"title": "Deploy 1.2"}, "56": {"title": "Tag the release"}, "57": {"title": "Tag the release"},
       "58": {"title": "Upload the demo video to the website"}}
check(ar.match_approval("Tag the release", aps)[0] in ("56", "57"), "two identical cards: the line closes one of them")
check(ar.match_approval("Card 57: Tag the release", aps) == ("57", False), "Card N wins")
check(ar.match_approval("No: Karte 55: whatever", aps) == ("55", True), "Karte N with No: in front")
check(ar.match_approval("Card 99: Deploy 1.2", aps) == ("55", False), "a stale number falls back to the words")
check(ar.match_approval("upload demo video website", aps)[0] == "58", "one card whose words match clearly")
part = {"60": {"title": "Release the new invoice layout"}, "61": {"title": "Release the new invoice layout for Clara"}}
check(ar.match_approval("Release the new invoice layout now", part)[0] is None, "partial hits on two cards: nothing (never a guess)")

# ================================================================ #3753 / #2390 approval_check
for t in ("Das empfehle ich gerade nicht.", "I would not recommend that.", 'Die Aufgabe "Soll ich das umsetzen?" ist erledigt.',
          "Titel „Vorschlag: Fix übernehmen?“ steht in der Liste.", "Deine Freigabe ist eingetragen.", "Your approval is noted.",
          "Nach deiner Freigabe habe ich gebaut."):
    check(ar.asks_without_card(t, "de") == ("", ""), f"no ask: {t!r}")
for t in ("Der Demo-Upload braucht deine Website-Freigabe.", "Sobald du freigibst, lade ich hoch.", "Ist das deine Freigabe?",
          "This needs your approval before it goes out.", "Once you approve, I upload it.", "Ich empfehle, das in 2.40 mitzunehmen."):
    check(ar.asks_without_card(t, "de")[0] != "", f"asks: {t!r}")

# ================================================================ #3754 status_typing on the task
api = ar.Api(URL, "t")
codes = [404]
api.soft = lambda m, p, b=None, timeout=20: (codes.append(p), 404)[1]
check(api.task_typing(5) is False and api.task_typing_ok is False, "an old server (404): no task typing")
n = len(codes)
api.task_typing(5)
check(len(codes) == n, "switched off: no further call")
r = runner("typing")
go(r, [{"event": "task_updated", "seq": 1, "data": {"task": {"id": 77, "title": "T"}}}], final="Done.")
check(r.api.typed and set(r.api.typed) == {77}, f"a task run sends the typing dots on its task: {r.api.typed}")
r.api.typed.clear()
go(r, [{"event": "chat", "seq": 2, "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 2, "body": "hi"}}}])
check(r.api.typed == [], "a chat run never types on a task")

# ================================================================ #3755 a quiet wake after a done job
wake = lambda st: {"event": "job_wake", "seq": f"wake-{st}", "data": {"job": {"id": 3, "title": "Build", "state": st}, "user": {"id": 7}}}
check("STILL" in "\n".join(ar.wake_hint(wake("done")["data"])) and "STILL" not in "\n".join(ar.wake_hint(wake("failed")["data"])),
      "only the done wake offers the line STILL")
check(ar.wake_still("**STILL**: nothing new") == (True, "nothing new") and ar.wake_still("STILLSTAND im Bau")[0] is False
      and ar.wake_still("Still ist es")[0] is False, "QUIET_RE: STILL alone or with a separator")
r = runner("wake")
go(r, [wake("done")], final="STILL")
check(r.api.posts == [], f"STILL after a done job: nothing posted: {r.api.posts}")
go(r, [wake("failed")], final="STILL")
check(len(r.api.posts) == 1, "a failed job always gets its line")
go(r, [wake("done")], final="STILL\n\n```approval\nStart the next build\n```")
check(r.api.posts[-1]["approval"] and "STILL" not in r.api.posts[-1]["body"], "STILL with a card: the card is posted, the STILL line not")

# ================================================================ #2347 approval_move: the card wanders to the newest answer
r = runner("move")
r.approvals = {"55": {"uid": 7, "title": "Deploy 1.2", "at": time.time() - 60}}
go(r, [{"event": "chat", "seq": 3, "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 3, "body": "and the deploy?"}}}],
   final="The deploy waits for you, see card 55.")
new = [m for m in r.approvals]
check(r.api.posts[-1]["approval"] == {"title": "Deploy 1.2"} and r.api.withdrawn == [(7, "55", "")] and new and new[0] != "55",
      f"the answer carries the card again, the old one is withdrawn: {r.api.posts[-1]} {r.api.withdrawn} {new}")
check(r.approvals[new[0]].get("moved_from") == "55" and r.approvals[new[0]]["at"] < time.time() - 30, "same age, it knows where it came from")
evs = r.groups([{"event": "chat_choice", "data": {"message_id": 55, "approval": "approved", "user": {"id": 7}}}])
check(len(evs) == 1 and (evs[0][1][0]["data"].get("approval_request") or {}).get("title") == "Deploy 1.2" and not r.approvals,
      f"a press on the old card counts for the new one: {evs}")
r.approvals = {"56": {"uid": 7, "title": "Tag the release", "at": time.time()}}
go(r, [{"event": "chat", "seq": 4, "data": {"user": {"id": 7, "name": "Ann"}, "message": {"id": 4, "body": "ok"}}}], final="All green.")
check("56" in r.approvals and r.api.posts[-1]["approval"] is None, "an answer that does not refer to the card leaves it where it is")

# ================================================================ #2422 Stop with job_id ends that one local job
agent_job.STATE_DIR = None
os.makedirs(agent_job.job_dir(81), exist_ok=True)
agent_job.save({"id": 81, "kalmido_job": 81, "title": "Long", "state": "running", "chat_user": 7, "cmd_pid": None, "runner_pid": None})
r = runner("abort")
r.state_dir = JST
r.abort({"event": "abort", "seq": "12", "data": {"user": {"id": 7}, "job_id": 81}})
check(agent_job.load(81)["state"] == "stopped", "Stop with job_id: that job is stopped")
check(any(c[1] == "/agent/jobs/81" and (c[2] or {}).get("state") == "stopped" for c in r.api.soft_calls)
      and any(c[1] == "/agent/aborted" and (c[2] or {}).get("job_id") == 81 for c in r.api.soft_calls)
      and not any(c[1].startswith("/agent/chats/") for c in r.api.soft_calls), f"marked stopped and confirmed, no note: {r.api.soft_calls}")
r.api.soft_calls.clear()
r.abort({"event": "abort", "seq": "13", "data": {"user": {"id": 7}, "job_id": 82}})
check(any(c[1] == "/agent/jobs/82" and "append_log" in (c[2] or {}) for c in r.api.soft_calls), "a job this launcher does not run: the note as before")

# ================================================================ #1801 job_inbox + #2347 job_cards, with real job runs
JENV = {**os.environ, "KALMIDO_CHAT_USER": "7", "KALMIDO_JOB_CMD": json.dumps([FAKE])}
JENV.pop("KALMIDO_OUTBOX", None)


def job(*a, inp=None):
    return subprocess.run([sys.executable, os.path.join(MCP, "agent_job.py"), *a], input=inp, env=JENV, capture_output=True,
                          text=True, timeout=60)


rj = job("start", "--title", "Inbox", "-", inp="WAITMSG build it")
jid = int(rj.stdout.split("#")[1].split()[0]) if "#" in rj.stdout else 0
check(jid and until(lambda: any(x.get("waiting") for x in seen()), 40), f"the job runs and made a tool step: {rj.stdout} {rj.stderr[-300:]}")
check((agent_job.load(jid) or {}).get("inbox") is True, "a claude job takes messages (inbox)")
r = runner("inbox")
r.state_dir = JST
left = r.intercept([{"event": "job", "data": {"action": "message", "text": "Please also update the README", "user": {"id": 7, "name": "Ann"},
                                              "job": {"id": jid, "title": "Inbox"}}}])
check(left == [], "the message to the running job starts no chat run")
check(until(lambda: any("Please also update the README" in str(x.get("inbox") or "") for x in seen()), 40),
      "the job reads the message after its tool step")
check(until(lambda: (agent_job.load(jid) or {}).get("state") == "done", 40), "the job ends as done")
check(any(q["m"] == "PATCH" and q["p"].endswith(f"/jobs/{jid}") and b"message delivered" in q["body"] for q in REQS), "its log says so")
left = r.intercept([{"event": "job", "data": {"action": "message", "text": "late", "user": {"id": 7}, "job": {"id": jid}}}])
check(len(left) == 1, "an ended job: the message becomes a chat run as before")

REQS.clear()
rj = job("start", "--title", "Card", "-", inp="CARDRESULT prepare the upload")
cid = int(rj.stdout.split("#")[1].split()[0]) if "#" in rj.stdout else 0
check(cid and until(lambda: (agent_job.load(cid) or {}).get("state") == "done", 40), "the card job ends")
cards = (agent_job.load(cid) or {}).get("cards") or {}
posted = [json.loads(q["body"]) for q in REQS if q["m"] == "POST" and q["p"] == "/api/v1/agent/chats/7" and q["ct"].startswith("application/json")]
check(cards and list(cards.values())[0]["title"] == "Upload the demo" and any((b.get("approval") or {}).get("title") == "Upload the demo"
                                                                             and b.get("job_id") == cid for b in posted),
      f"the result's block became a card of the job: {cards} {posted[-1:]}")
mid = next(iter(cards))
os.remove(SEEN)
r = runner("cards")
r.state_dir = JST
evs = r.groups([{"event": "chat_choice", "data": {"message_id": int(mid), "approval": "approved", "user": {"id": 7, "name": "Ann"}}}])
check(evs == [], "yes on the job's card starts no chat run")
check(until(lambda: any("answered your approval card: Approval: yes - Upload the demo" in str(x.get("prompt") or "") for x in seen()), 40),
      f"the ended job is woken in its session with the answer: {seen()[-1:]}")
check(until(lambda: (agent_job.load(cid) or {}).get("state") == "done", 40) and any("--resume" in (x.get("args") or []) for x in seen()),
      "the same session goes on and ends again")
check(r.groups([{"event": "chat_choice", "data": {"message_id": int(mid), "approval": "approved", "user": {"id": 7}}}]) == [],
      "the same answer twice counts once")
# 2.615.0 (#2390): a result that asks without a card and has exactly one suggestion -> that suggestion is the card
b, appr, sugg, _ = agent_job.result_blocks("Der Upload braucht deine Website-Freigabe.\n\n```suggest\nDemo hochladen\n```")
check(appr == {"title": "Demo hochladen"} and sugg == [], f"one suggestion of an asking result becomes the card: {appr} {sugg}")
b, appr, sugg, _ = agent_job.result_blocks("All built.\n\n```suggest\nShow the log\n```")
check(appr is None and sugg == ["Show the log"], "a result that asks nothing keeps its button")

done("p2615_b_launcher")
