#!/usr/bin/env python3
# kalmido-suite: after=p2615_b_launcher nodata
"""2.974.0 (#5668): the model per run in the reference starter (mcp/agent_run.py), switched on in Kalmido (runtime
model_split, model_decide, model_routine):
 - which events take the model for the person's messages and decisions and which the routine model (model_choice): chat,
   buttons, reactions, comments, unknown events = decide; new tasks, tidy, follow-ups = routine; a job wake only with a HARD
   sign (not done, late messages, result not in the chat, a question / approval card, an open decision, a hard red that is
   not a story, soft or negated); a planned job only with a sign word
 - model_pair / session_model_key / with_model
 - end to end with a fake claude in PATH: a chat run on the decide model, a task event on the routine model, a job wake in
   the same conversation (resumed, other model), a failed switch runs once more on the previous model and the conversation
   stays on it; switch off = the command's own --model, untouched
 - 2.992.0 (#5684): the third kind, reviews (run_kind, model_review): only what the trigger says (review_requested, a planned
   job with review: true or a list check), never a word; a decision in the same run wins; the review model empty = the decide
   model; the conversation key of 2.974 stays; every run hands its kind and id to the usage hook (KALMIDO_RUN_CLASS / _ID),
   a summary run and the switch off none
Pure Python, no container."""
import importlib.util
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kt import check, done

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "mcp"))
sys.path.insert(0, MCP)
TMP = tempfile.mkdtemp(prefix="kalmido-p5668-")
os.chdir(TMP)


class H(BaseHTTPRequestHandler):  # a stub server for anything the runner's helpers call on their own (answers {})
    def log_message(self, *a):
        pass

    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(KALMIDO_URL=f"http://127.0.0.1:{srv.server_address[1]}", KALMIDO_TOKEN="abk_" + "z" * 30, KALMIDO_STATE_DIR=os.path.join(TMP, "jst"))

spec = importlib.util.spec_from_file_location("agent_run", os.path.join(MCP, "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
ar.RETRY_429_S = (0, 0, 0, 0)

D, R = "big", "small"


def ev(kind, **data):
    return {"event": kind, "seq": 1, "data": data}


def wake(state="done", text="All built, 3 tasks closed.", posted=True, late=None):
    return ev("job_wake", job={"id": 4, "state": state, "title": "Build"}, text=text, posted=posted, late=late or [], user={"id": 7})


def pick(*evs):
    return ar.model_choice(list(evs), D, R)


# ================================================================ which event takes which model
for e in (ev("chat", user={"id": 7}, message={"id": 1, "body": "hi"}), ev("chat_choice", user={"id": 7}), ev("reaction"),
          ev("comment", comment={"body": "x"}), ev("mention"), ev("team_message"), ev("message_edited"), ev("deployed"), ev("assigned")):
    check(pick(e)[0] == D, f"decide: {e['event']} {pick(e)}")
for e in (ev("task_added", task={"id": 5}), ev("tasks_added", task_ids=[5, 6]), ev("tidy"), ev("stale_tasks"), ev("followup_due")):
    check(pick(e)[0] == R, f"routine: {e['event']} {pick(e)}")
check(pick(ev("task_added"), ev("chat", user={"id": 7}))[0] == D, "a group with one event that needs a decision: decide")
check(pick(ev("task_added"), ev("tidy"))[0] == R, "a group of routine events: routine")
check(ar.model_choice([ev("chat")], "opus", "opus") == ("opus", "one model"), "both the same: one model")

# job wakes: only a hard sign takes the big model
check(pick(wake()) == (R, "job wake without a hard sign"), f"a done job, result in the chat: routine {pick(wake())}")
for w, what in ((wake(state="failed"), "failed"), (wake(state="lost"), "lost"), (wake(posted=False), "result not in the chat"),
                (wake(late=[{"uid": 7, "text": "and the footer?"}]), "messages came too late"),
                (wake(text="The deploy failed: the server refused the upload."), "hard red in the present"),
                (wake(text="Der Upload ist fehlgeschlagen, Server antwortet 500."), "hard red, German"),
                (wake(text="Built. This needs your decision: blue or green header."), "open decision"),
                (wake(text="Fertig. Braucht dich: welche Farbe soll der Kopf haben."), "open decision, German"),
                (wake(text="Ready to upload.\n\n```approval\nUpload the demo\n```"), "approval card"),
                (wake(text="Shall I also move the old tasks to the archive?"), "a question"),
                (wake(text="Found a security issue in the upload check, details below.") , "security finding")):
    check(pick(w)[0] == D, f"wake decide: {what} {pick(w)}")
for w, what in ((wake(text="It failed first, fixed now: all green."), "a story (first ... fixed)"),
                (wake(text="Nothing failed, 12 tests green."), "negated"),
                (wake(text="Ohne Fix war der Test rot, jetzt grün. Nichts blockiert."), "German story + negation"),
                (wake(text='Added the label "blocked" to task 5.'), "quoted word"),
                (wake(text="One soft check failed (flaky timer), collected for the bundle fix."), "soft"),
                (wake(text="Built without a decision from you; the rule says so."), "no decision needed"),
                (wake(text="Done: the header is blue, as decided yesterday."), "a decision named, not open"),
                (wake(text="Ran the check:\n```\nstep 3 failed (expected in the sample)\n```\nAll good."), "red inside a code block"),
                (wake(text="Ich habe deine Entscheidung von gestern umgesetzt, die Liste ist sauber."), "German: a decision named, not open"),
                (wake(text="Release notes list the decisions and warnings of the week."), "words alone")):
    check(pick(w)[0] == R, f"wake routine: {what} {pick(w)}")

# planned jobs: a sign word in title or prompt
check(pick(ev("scheduled_job", title="Weekly summary", prompt="Summarise the week in 5 lines."))[0] == R, "planned job without a sign: routine")
check(pick(ev("scheduled_job", title="Approvals", prompt="Check which approvals wait."))[0] == D, "planned job naming approvals: decide")
check(pick(ev("scheduled_job", title="Morgenrunde", prompt="Was ist rot?"))[0] == D, "planned job, German sign word: decide")
check(pick(ev("scheduled_job", title="Monatsbericht", prompt="Sammle die erledigten Aufgaben."))[0] == R, "German, no sign: routine")

# ================================================================ helpers
check(ar.model_pair({"model": "opus"}) is None and ar.model_pair({"model_split": "true"}) is None, "off (or not a real true): no pair")
check(ar.model_pair({"model": "opus", "model_split": True}) == ("opus", "opus"), "empty fields = the agent's model")
check(ar.model_pair({"model": "", "model_split": True, "model_decide": "opus", "model_routine": " sonnet "}) == ("opus", "sonnet"), "both fields")
check(ar.session_model_key({"model": "opus"}) == "opus" and ar.session_model_key({"model_split": True, "model_decide": "a", "model_routine": "b"}) == "a/b",
      "the conversation is bound to the setting, not to one run's model")
# 2.992.0 (#5684): reviews - what the trigger says, never a word in the text
V = "fable"
pv = lambda *evs: ar.model_choice(list(evs), D, R, review=V)  # noqa: E731
check(pv(ev("review_requested", task={"id": 5})) == (V, "review (review_requested)"), f"#5684: a review the agent is asked for: review {pv(ev('review_requested'))}")
check(pv(ev("scheduled_job", title="Audit", prompt="Read the code", review=True))[0] == V, "#5684: a planned job of the kind Review: review")
check(pv(ev("scheduled_job", title="Check the project", prompt="x", list_check=True))[0] == V, "#5684: a scheduled check of a project: review")
check(pv(ev("scheduled_job", title="Review the week", prompt="review and audit everything"))[0] == R,
      "#5684: the word review / audit in a plain planned job is no review (routine)")
check(pv(ev("chat", user={"id": 7}, message={"body": "please review this"}))[0] == D, "#5684: the word in a chat is no review (decide)")
check(pv(ev("scheduled_job", title="Approve the invoices", prompt="x", review=True))[0] == V, "#5684: a review plan stays review (no sign words counted)")
check(pv(ev("review_requested"), ev("chat", user={"id": 7}))[0] == D, "#5684: a decision in the same run wins")
check(pv(ev("review_requested"), ev("task_added"))[0] == V, "#5684: a review with routine: review")
check(pv(ev("review_requested"), wake(state="failed"))[0] == D, "#5684: a review with a hard job wake: decide")
check(pv(ev("scheduled_job", title="x", prompt="y", review="yes"))[0] == R, "#5684: only a real true counts")
check(ar.model_choice([ev("review_requested")], D, R) == (D, "review (review_requested)"), "#5684: no review model given = the decide model")
check(ar.model_choice([ev("review_requested")], "opus", "opus", "opus") == ("opus", "one model"), "#5684: all three the same: one model")
check(ar.run_kind([ev("task_added")]) == ("routine", "routine (task_added)") and ar.run_kind([]) == ("decide", "no event"), "#5684: run_kind")
check(ar.model_review({"model_split": True, "model_decide": "opus"}) == "opus" and ar.model_review({"model_split": True, "model_review": " fable "}) == "fable"
      and ar.model_review({"model": "x"}) is None, "#5684: model_review: empty = the decide model, off = None")
check(ar.session_model_key({"model_split": True, "model_decide": "a", "model_routine": "b", "model_review": ""}) == "a/b"
      and ar.session_model_key({"model_split": True, "model_decide": "a", "model_routine": "b", "model_review": "a"}) == "a/b"
      and ar.session_model_key({"model_split": True, "model_decide": "a", "model_routine": "b", "model_review": "c"}) == "a/b/c",
      "#5684: the conversation key of 2.974 stays; a review model of its own adds /c")
check(ar.with_model(["claude", "-p", "--model", "x", "--model=y", "--verbose"], "z") == ["claude", "-p", "--verbose", "--model", "z"],
      "with_model replaces every --model")
check(ar.with_model(["claude", "--model", "x"], "") == ["claude"], "empty = the command's default (no --model)")

# ================================================================ end to end: a fake claude in PATH
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
FAKE = os.path.join(BIN, "claude")
SEEN = os.path.join(TMP, "seen.jsonl")
with open(FAKE, "w") as f:
    f.write("#!" + sys.executable + "\n" + r'''import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
model = args[args.index("--model") + 1] if "--model" in args else ""
with open(os.environ["FAKE_SEEN"], "a") as f:
    f.write(json.dumps({"args": args, "model": model, "resume": args[args.index("--resume") + 1] if "--resume" in args else "",
                        "cls": os.environ.get("KALMIDO_RUN_CLASS", ""), "rid": os.environ.get("KALMIDO_RUN_ID", "")}) + "\n")
if model and model == os.environ.get("FAKE_FAIL_MODEL") and "--resume" in args:
    sys.stderr.write("model not available for this session\n")
    sys.exit(1)
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "model": "claude-" + (model or "default"), "session_id": "sess-5668"})
out({"type": "result", "subtype": "success", "is_error": False, "result": "STILL" if "Job #" in prompt else "Done."})
''')
os.chmod(FAKE, 0o755)
os.environ.update(FAKE_SEEN=SEEN, PATH=BIN + os.pathsep + os.environ.get("PATH", ""))


def seen():
    try:
        return [json.loads(ln) for ln in open(SEEN) if ln.strip()]
    except OSError:
        return []


RT = {"model": "base", "reset_seq": 0, "model_split": True, "model_decide": "opus", "model_routine": "sonnet"}


class StubApi:
    def __init__(self):
        self.posts, self.lang = [], ""

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None, job_id=None):
        self.posts.append({"uid": uid, "body": body})
        return {"id": 700 + len(self.posts)}

    def soft(self, *a, **k):
        return 200

    def req(self, *a, **k):
        return {"owner_id": 7, "runtime": dict(RT)}

    def withdraw(self, *a, **k):
        return True

    def task_typing(self, tid):
        return True

    def status(self, *a, **k):
        pass

    typing = progress = quota = notice = status


r = ar.Runner(["claude", "--model", "base"], os.path.join(TMP, "st"))  # the launcher appends --model <runtime model>
r.api = r.usage.api = StubApi()
r.refresh_agent()


def go(evs):
    n = len(seen())
    r.run(ar.Runner.chat_uid(evs[0]), evs)
    return seen()[n:]


s = go([ev("chat", user={"id": 7, "name": "Ann"}, message={"id": 11, "body": "Plan the week"})])
check(len(s) == 1 and s[0]["model"] == "opus" and s[0]["args"].count("--model") == 1, f"chat: the decide model, one --model: {s}")
s = go([ev("task_added", task={"id": 5, "title": "New"})])
check(len(s) == 1 and s[0]["model"] == "sonnet" and not s[0]["resume"], f"a new task (task event): the routine model, a fresh run: {s}")
s = go([wake()])
check(len(s) == 1 and s[0]["model"] == "sonnet" and s[0]["resume"] == "sess-5668", f"a quiet job wake: routine, in the same conversation: {s}")
s = go([wake(state="failed", text="time limit")])
check(len(s) == 1 and s[0]["model"] == "opus" and s[0]["resume"] == "sess-5668", f"a failed job: decide, same conversation: {s}")
sess = r.state.data["sessions"].get("chat:7") or {}
check(sess.get("model") == "opus/sonnet" and sess.get("last_model") == "opus", f"the conversation keeps the setting and its last model: {sess}")

# 2.992.0 (#5684): the usage hook learns the kind and the id of every run (the child's environment)
os.environ.update(KALMIDO_RUN_CLASS="routine", KALMIDO_RUN_ID="inherited")  # never inherited from the launcher's environment
s = go([ev("chat", user={"id": 7, "name": "Ann"}, message={"id": 13, "body": "hi"})])
s2 = go([ev("task_added", task={"id": 8, "title": "New"})])
RT.update(model_review="fable")
r.refresh_due = True
s3 = go([ev("review_requested", task={"id": 9, "title": "Check it"})])
check(len(s) == 1 and s[0]["cls"] == "decide" and len(s[0]["rid"]) == 16 and len(s2) == 1 and s2[0]["cls"] == "routine"
      and s2[0]["rid"] not in ("", "inherited", s[0]["rid"]), f"#5684: each run hands its kind and a new id to the hook: {s} {s2}")
check(len(s3) == 1 and s3[0]["model"] == "fable" and s3[0]["cls"] == "review", f"#5684: a review the agent is asked for: the review model, kind review: {s3}")
RT.update(model_review="")
r.refresh_due = True
s3 = go([ev("review_requested", task={"id": 9, "title": "Check it"})])
check(len(s3) == 1 and s3[0]["model"] == "opus" and s3[0]["cls"] == "review", f"#5684: no review model = the decide model, still kind review: {s3}")
for k in ("KALMIDO_RUN_CLASS", "KALMIDO_RUN_ID"):
    os.environ.pop(k)

# a switch that fails early: once more on the previous model, the conversation stays on it
os.environ["FAKE_FAIL_MODEL"] = "sonnet"
s = go([wake()])
check(len(s) == 2 and s[0]["model"] == "sonnet" and s[1]["model"] == "opus" and s[1]["resume"] == "sess-5668",
      f"failed switch: again on the previous model, same conversation: {s}")
stuck = (r.state.data.get("model_stuck") or {}).get("chat:7") or {}
check(stuck.get("model") == "opus", f"model_stuck holds the conversation: {stuck}")
os.environ.pop("FAKE_FAIL_MODEL")
s = go([wake()])
check(len(s) == 1 and s[0]["model"] == "opus", f"while stuck the next routine run of that chat stays on it: {s}")
s = go([ev("tidy", task={"id": 6})])
check(len(s) == 1 and s[0]["model"] == "sonnet", f"a task event (no conversation) is not bound by it: {s}")

# a new setting = a new conversation
RT.update(model_routine="haiku")
r.refresh_due = True
s = go([ev("chat", user={"id": 7, "name": "Ann"}, message={"id": 12, "body": "next"})])
check(s and s[-1]["model"] == "opus" and not s[-1]["resume"] and "chat:7" not in (r.state.data.get("model_stuck") or {}),
      f"changed setting: the conversation starts fresh, no longer bound to the old model: {s}")
RT.update(model_decide="haiku")
r.refresh_due = True
s = go([wake()])
check(s and s[-1]["model"] == "haiku", f"a new conversation picks again (not stuck): {s}")

# switch off: the command's own --model stays as it is
RT.update(model_split=False)
r.refresh_due = True
s = go([ev("task_added", task={"id": 7})])
check(len(s) == 1 and s[0]["model"] == "base" and s[0]["args"].count("--model") == 1, f"off: the launcher's --model, untouched: {s}")
check(s[0]["cls"] == "" and s[0]["rid"] == "", f"#5684: off = no kind for the usage hook: {s}")
sys.exit(done("p5668_model_per_run"))
