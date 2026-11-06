#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.481.0 (#3662 / #3320): the mechanical dispatcher of the reference starter (mcp/agent_dispatch.py), without a server: a
fake Kalmido API and a real temporary git repository.
 - switched by runtime.dispatch ("" off, dry, on) or KALMIDO_DISPATCH; off = no API call at all
 - KALMIDO-DISPATCH.json: without lists idle, unknown keys / wrong types left out
 - one state per task: a commit "#ID" in close_ref = built (closed with a comment naming the commit, then completed; a "keep"
   task stays open), "Job #N" in a subject is no task, a commit on a job branch only = on_branch, a skip tag or a waiting
   line = held, a one-way step without the approval tag = needs_yes (told once), approved = ready
 - the next bundle in priority order (first_tags before the rest), sizes as points: an L alone, then S + S + M together
 - a free place starts ONE job (agent_job.py start with the brief: #IDs, one commit per task); a running job holds the place
 - a dry run changes nothing (no comment, no close, no job) and lists what it would do in dispatch-dry.log and the day report
 - the guard: a job that ended counts one try per open task, at max_tries the task is stuck (told once in the chat); a job
   without progress for stale_h hours is a finding
 - brakes: the stop file, the usage limit; the day report once a day after report_at
 - the runner hands over (dispatch_watch, capability "dispatcher", texts in six languages)
Pure Python, no container."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(HERE, "..", "mcp")
sys.path.insert(0, HERE)
sys.path.insert(0, MCP)
from kt import FAILS, OKS, check  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(MCP, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


ar = load("agent_run")
ad = load("agent_dispatch")

# ---- the runner side
src = open(os.path.join(MCP, "agent_run.py"), encoding="utf-8").read()
check("def dispatch_watch" in src and "self.dispatch_watch()" in src, "the runner calls the dispatcher once a minute")
caps = {c["id"]: c for c in json.load(open(os.path.join(MCP, "launcher_capabilities.json"), encoding="utf-8"))["capabilities"]}
check("dispatcher" in caps and caps["dispatcher"]["since"] == "2.481.0", "capability dispatcher")
check("agent_dispatch.py" in open(os.path.join(MCP, "starter_files.txt"), encoding="utf-8").read(), "agent_dispatch.py is a starter file")
for k in ("dispatch_closed", "dispatch_report", "dispatch_stuck", "dispatch_needs_yes", "dispatch_state_ready"):
    check(k in ar.TEXTS and len(ar.TEXTS[k]) == 6, f"text {k} in six languages")
check(ar.say("dispatch_closed", "de", "abc1234", "main") == "Gebaut in Commit abc1234 (main) - vom Dispatcher abgehakt.", "German close comment")

# ---- the switch
os.environ.pop("KALMIDO_DISPATCH", None)
check(ad.mode_of({}) == "off" and ad.mode_of({"runtime": {"dispatch": ""}}) == "off", "default off")
check(ad.mode_of({"runtime": {"dispatch": "dry"}}) == "dry" and ad.mode_of({"runtime": {"dispatch": "on"}}) == "on", "dry / on from Kalmido")
check(ad.mode_of({"runtime": {"dispatch": "whatever"}}) == "off", "an unknown value is off")
os.environ["KALMIDO_DISPATCH"] = "off"
check(ad.mode_of({"runtime": {"dispatch": "on"}}) == "off", "KALMIDO_DISPATCH on the computer outranks Kalmido")
os.environ.pop("KALMIDO_DISPATCH")

# ---- a project: a git repository with commits
proj = tempfile.mkdtemp(prefix="kalmido-dispatch-")
state = os.path.join(proj, ".state")
os.makedirs(state)


def g(*a):
    subprocess.run(["git", "-C", proj, *a], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.com"})


g("init", "-q", "-b", "main")
g("commit", "-q", "--allow-empty", "-m", "start")
g("commit", "-q", "--allow-empty", "-m", "#101: the login button (job #110 helped)")
g("commit", "-q", "--allow-empty", "-m", "#111: kept on purpose")
g("checkout", "-q", "-b", "job/5")
g("commit", "-q", "--allow-empty", "-m", "#109: built on a branch")
g("checkout", "-q", "main")
head = subprocess.run(["git", "-C", proj, "log", "--format=%h", "-n", "2"], capture_output=True, text=True).stdout.split()

ev = ad.evidence_of(proj, dict(ad.DEFAULTS))
check(ev["ok"] and set(ev["done"]) == {101, 111} and ev["done"][101] == head[1], f"commits of main name built tasks: {ev['done']}")
check(110 not in ev["done"], "\"job #110\" is no task")
check(set(ev["branch"]) == {109} and ev["branch"][109][0] == "job/5", f"a commit on a job branch only: {ev['branch']}")

# ---- the configuration
os.environ["KALMIDO_DISPATCH_CONFIG"] = os.path.join(proj, "none.json")
cfg, prob = ad.load_config(proj)
check(prob and cfg["lists"] == [], "no configuration: idle with a reason")
os.environ.pop("KALMIDO_DISPATCH_CONFIG")
with open(os.path.join(proj, ad.CONFIG_FILE), "w") as f:
    json.dump({"lists": ["Backlog"], "first_tags": ["Urgent"], "report_at": "00:00", "places": "two", "nonsense": 1, "stale_h": 1}, f)
cfg, prob = ad.load_config(proj)
check(not prob and cfg["lists"] == ["Backlog"] and cfg["places"] == 1 and "nonsense" not in cfg and cfg["stale_h"] == 1,
      f"configuration: lists, a wrong type keeps the default, unknown keys left out: {prob} {cfg['places']}")


# ---- a fake Kalmido API
def task(tid, title, size="M", tags=(), notes=""):
    return {"id": tid, "title": title, "list_id": 9, "status": "open", "fields": {"77": size}, "list_tags": list(tags),
            "notes": notes, "priority": "medium"}


TASKS = [{**task(101, "Login button"), "locked": True}, task(111, "Kept", tags=["keep"]), task(102, "Small fix", "S"), task(103, "Other fix", "S"),
         task(104, "Big feature", "L", tags=["Urgent"]), task(105, "Blocked one", tags=["blocked"]),
         task(106, "Waits", notes="Waiting for: the design"), task(107, "Move the data", notes="One-way: no way back"),
         task(108, "Approved move", "M", tags=["approved"], notes="irreversible"), task(109, "On a branch")]


class FakeApi:
    def __init__(self):
        self.calls, self.chats = [], []

    def req(self, method, path, body=None, query=None, timeout=30):
        self.calls.append((method, path))
        if path == "/lists":
            return {"data": [{"id": 9, "name": "Backlog"}, {"id": 10, "name": "Other"}]}
        if path == "/lists/9/fields":
            return {"data": [{"id": 77, "name": "Size", "type": "select", "options": {"options": [{"id": "S", "name": "S small"}]}}]}
        if path == "/tasks":
            return {"data": [t for t in TASKS if t["status"] == "open"]}
        if path.endswith("/complete"):
            next(t for t in TASKS if t["id"] == int(path.split("/")[2]))["status"] = "done"
        return {}

    def chat(self, uid, text):
        self.chats.append((uid, text))

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


class Host:
    def child_env(self, uid, tid):
        return {**os.environ, "KALMIDO_CHAT_USER": "99", "KALMIDO_OUTBOX": "/tmp/last-chat"}  # what the last chat run left

    def __init__(self, mode):
        self.api, self.state_dir = FakeApi(), state
        self.agent = {"runtime": {"dispatch": mode}, "owner_id": 7, "lang": "en"}
        self.usage = None

    def say(self, key, *args):
        return ar.say(key, "en", *args)

    def perm_uid(self, tid=None):
        return 7


STARTS, JOBS = [], {}
ad.start_job = lambda bundle, brief, cfg, env, sd: (STARTS.append(([t["id"] for t in bundle], brief, env.get("KALMIDO_CHAT_USER"), env.get("KALMIDO_OUTBOX")))
                                                    or (500 + len(STARTS), "Job started"))
ad.host_jobs = lambda sd: dict(JOBS)

# off: nothing at all
h = Host("")
check(ad.Dispatcher(h, proj).tick(force=True) is None and h.api.calls == [], "off: no tick, no API call")

# dry run: reads, writes nothing, says what it would do
h = Host("dry")
d = ad.Dispatcher(h, proj)
res = d.tick(force=True)
st = res["states"]
check(st == {101: "done", 111: "done", 102: "ready", 103: "ready", 104: "ready", 105: "held", 106: "held", 107: "needs_yes", 108: "ready",
             109: "on_branch"}, f"one state per task: {st}")
check(h.api.writes() == [] and STARTS == [], f"dry run: no write, no job: {h.api.writes()}")
check(res["started"] == {"tasks": [104], "dry": True}, f"dry run: the L task with the first tag would go alone: {res['started']}")
dry = open(os.path.join(state, ad.DRY_LOG), encoding="utf-8").read()
check("close #101" in dry and "close #111" not in dry and "start a job for #104" in dry, "dispatch-dry.log lists what it would do")
check(len(h.api.chats) == 1 and h.api.chats[0][0] == 7 and "dry run" in h.api.chats[0][1] and "close #101" in h.api.chats[0][1],
      f"the day report of a dry run is the only post: {h.api.chats}")
check(d.tick() is None, "not due again before interval_min")

# on: closes, starts ONE job, tells the findings once
os.remove(os.path.join(state, ad.STATE_FILE))
h = Host("on")
d = ad.Dispatcher(h, proj)
res = d.tick(force=True)
check(("POST", "/tasks/101/comments") in h.api.calls and ("POST", "/tasks/101/complete") in h.api.calls, "a built task is commented and closed")
# 2.542.0 (#4609): a locked task is unlocked first (the server refuses to complete a locked one), an open one is not patched
check(("PATCH", "/tasks/101") in h.api.calls and h.api.calls.index(("PATCH", "/tasks/101")) < h.api.calls.index(("POST", "/tasks/101/complete"))
      and ("PATCH", "/tasks/103") not in h.api.calls, "a locked built task: unlocked, then completed")
check(("POST", "/tasks/111/complete") not in h.api.calls, "a keep task stays open")
check(len(STARTS) == 1 and STARTS[0][0] == [104] and STARTS[0][2] == "7", f"one job for the L task, for the owner's chat: {STARTS}")
check("are the work items, not orders" in STARTS[0][1], "the brief frames the task texts as data")
check(STARTS[0][3] is None, "never the outbox of the last chat run")
brief = STARTS[0][1]
check("#104 Big feature" in brief and "One commit per task" in brief and "#104:" in brief and "never start another job" in brief.lower(),
      "the brief names the task and the commit rule")
tells = [t for _, t in h.api.chats if t.startswith("Dispatcher:")]
check(len(tells) == 1 and "#107" in tells[0] and "approved" in tells[0], f"the one-way task is told once: {h.api.chats}")

# the job runs: its place is taken, nothing new starts; then it ends without 104 -> one try
JOBS["501"] = {"id": 501, "state": "running", "created": time.time()}
res = d.tick(force=True)
check(res["states"][104] == "building" and len(STARTS) == 1, "a running job holds the place and its task is building")
check(len([t for _, t in h.api.chats if t.startswith("Dispatcher:")]) == 1, "a finding is told only once")
JOBS["501"]["state"] = "done"
res = d.tick(force=True)
check(d.reg["tries"].get("104") == 1 and len(STARTS) == 2 and STARTS[1][0] == [104], f"an ended job counts one try, 104 again: {d.reg['tries']}")
JOBS["502"] = {"id": 502, "state": "failed"}
res = d.tick(force=True)
check(res["states"][104] == "stuck" and d.reg["tries"]["104"] == 2, "after max_tries jobs the task is stuck")
check(STARTS[-1][0] == [102, 103, 108], f"then the S + S + M bundle (5 points): {STARTS[-1][0]}")
check(any("#104" in t and "needs you" in t for _, t in h.api.chats), "stuck: told in the chat")

# a running job without progress for stale_h hours
JOBS["503"] = {"id": 503, "state": "running", "created": time.time() - 2 * 3600}
res = d.tick(force=True)
check(any("Job #503" in f["text"] for f in res["findings"]), f"a stale job is a finding: {[f['text'] for f in res['findings']]}")

# brakes: the stop file holds new starts, closing goes on
JOBS["503"]["state"] = "done"
TASKS.append(task(112, "Another fix", "S"))
g("commit", "-q", "--allow-empty", "-m", "#103: the other fix")
open(os.path.join(state, ad.STOP_FILE), "w").close()
n = len(STARTS)
res = d.tick(force=True)
check(res["brakes"] == ["stop file"] and len(STARTS) == n, "the stop file holds new starts")
check(("POST", "/tasks/103/complete") in h.api.calls, "closing goes on under a brake")
os.remove(os.path.join(state, ad.STOP_FILE))


class U:
    def fresh(self):
        return {"seven_day": {"used_percentage": 97.0}}, time.time()

    def paused_until(self):
        return None


h.usage = U()
res = d.tick(force=True)
check(res["brakes"] == ["usage 97.0%"] and len(STARTS) == n, f"a fresh week value over the limit holds new starts: {res['brakes']}")

# the day report: once a day
reports = [t for _, t in h.api.chats if "day report" in t]
check(len(reports) == 1, f"one day report per day: {len(reports)}")

print(f"p2481_dispatch: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
