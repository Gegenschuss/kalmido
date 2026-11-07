#!/usr/bin/env python3
# kalmido-suite: after=launcher_parity nodata
"""2.619.0 part B (#3659: #1521 #1870 #2196 #2383 #2792 #3267 #3467): starter parity, without a server.
 - #2196 jobs tell the weekly limit apart from the 5-hour window: wait until that reset + 10 min (no 5 h cap), an unknown
   weekly reset is never guessed (look again in an hour), a five_hour window at 100 % stays the old window wait
 - #3267 a Claude Code job gets the usage hook (--settings with Stop / SubagentStop), not with its own --settings, not with
   KALMIDO_USAGE_HOOK=0, not for another profile; the in-app setup step for macOS names agent_launcher.sh
 - #2792 agent_job.py start --audit: not with --worktree / --parent, its own cap (KALMIDO_AUDIT_MAX), the read-only note
 - #2383 looked-at images only from the project folder (KALMIDO_PROJECT_DIR, else the working folder), never the home folder
 - #3467 a task run gets GIT_AUTHOR_* / GIT_COMMITTER_* from the task's repo.git_author, a chat run does not
 - #1521 #1870 the rules block (template = AG_RULES) says formula fields are never set and has the three 2.70 flows short
Pure Python, invented names only."""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "..")
MCP = os.path.join(R, "mcp")
import kt  # noqa: E402
from kt import check  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(MCP, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(*p):
    with open(os.path.join(R, *p), encoding="utf-8") as f:
        return f.read()


TMP = tempfile.mkdtemp(prefix="p2619b-")
os.environ.pop("KALMIDO_JOB_TEST_WAIT_S", None)
os.environ.pop("KALMIDO_AGENT_PROFILE", None)
os.environ.pop("KALMIDO_USAGE_HOOK", None)
os.environ["KALMIDO_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["KALMIDO_TOKEN"] = "abk_" + "x" * 30
os.environ.setdefault("KALMIDO_URL", "http://127.0.0.1:9")
aj = load("agent_job")
ar = load("agent_run")
ax = load("agent_extras")
now = time.time()

# ---- #2196: the weekly limit is not the 5-hour window
err = {"is_error": True, "result": ""}
check(aj.limit_end({"is_error": False, "result": "done"}, "weekly limit") == "", "#2196: a run with a result never counts as a limit end")
check(aj.limit_end(err, "You've hit your limit, resets 3pm") == "window", "#2196: the 5-hour text is the window")
w = aj.limit_wait(err, "You've hit your limit", now + 3600)
check(3600 <= w <= 3600 + 130, f"#2196: the window waits until its reset + 2 min: {w}")
st = {}
aj.week_window({"unifiedWindows": {"five_hour": {"utilization": 1.0, "resetsAt": now + 3600},
                                   "seven_day": {"utilization": 0.4, "resetsAt": now + 5 * 86400}}}, st)
check(not st.get("week"), f"#2196: a full 5-hour window with the week at 40 % is no weekly limit: {st}")
st = {}
aj.week_window({"unifiedWindows": {"five_hour": {"utilization": 0.2, "resetsAt": now + 3600},
                                   "seven_day": {"utilization": 1.0, "resetsAt": now + 3 * 86400}}}, st)
check(st.get("week") and abs(st.get("week_resets", 0) - (now + 3 * 86400)) < 2, f"#2196: seven_day at 100 % = the weekly limit with its reset: {st}")
st2 = {}
aj.week_window({"rateLimitType": "seven_day_opus", "status": "rejected", "resetsAt": now + 2 * 86400}, st2)
check(st2.get("week") and st2.get("week_resets"), f"#2196: the older rateLimitType form (rejected) too: {st2}")
w = aj.limit_wait(err, "You've hit your limit", now + 3600, st["week_resets"], True)
check(3 * 86400 + 590 <= w <= 3 * 86400 + 610, f"#2196: the weekly limit waits until ITS reset + 10 min, beyond the 5 h cap: {w}")
check(aj.limit_end(err, "Weekly limit reached") == "week", "#2196: the command's text alone names the weekly limit")
w = aj.limit_wait(err, "Weekly limit reached", None, None, False)
check(w == aj.WEEK_LOOK_AGAIN_S, f"#2196: an unknown weekly reset is never guessed, it looks again in an hour: {w}")
w = aj.limit_wait(err, "weekly limit", None, now + 30 * 86400, True)
check(w <= aj.WEEK_MAX_S, f"#2196: at most 8 days: {w}")

# ---- #3267: jobs get the usage hook
d = os.path.join(TMP, "job1")
os.makedirs(d)
base = ar.profile_args("claude", ["claude"])
# 2.619.0 (#3267) after 2.615.0 (#3758): job_settings(ar, job, base, folder) gives the extra arguments of the one settings file
out = aj.job_settings(ar, {"cmd": ["claude"]}, base, d)
check(out[:1] == ["--settings"] and os.path.isfile(out[-1]), f"#3267: a Claude Code job gets --settings: {out}")
hs = json.load(open(out[-1], encoding="utf-8")) if out and os.path.isfile(out[-1]) else {}
cmds = [h["hooks"][0]["command"] for k in ("Stop", "SubagentStop") for h in (hs.get("hooks") or {}).get(k, [])]
check(len(cmds) == 2 and all("claude_usage_hook.py" in c for c in cmds), f"#3267: Stop and SubagentStop run the usage hook: {hs}")
check(aj.job_settings(ar, {"cmd": ["claude", "--settings", "/x.json"]}, base + ["--settings", "/x.json"], d) == [], "#3267: its own --settings stays alone")
check(aj.job_settings(ar, {"cmd": ["codex"]}, ["codex", "exec", "--json"], d) == [], "#3267: Codex CLI gets no Claude hook")
os.environ["KALMIDO_USAGE_HOOK"] = "0"
out0 = aj.job_settings(ar, {"cmd": ["claude"]}, base, d)
hs0 = json.load(open(out0[-1], encoding="utf-8")) if out0 else {}
check("Stop" not in (hs0.get("hooks") or {}), f"#3267: KALMIDO_USAGE_HOOK=0 switches it off for jobs too: {hs0}")
os.environ.pop("KALMIDO_USAGE_HOOK")
check(ar.usage_hook_settings().keys() == {"Stop", "SubagentStop"}, "#3267: runs and jobs share one builder")

# ---- #2792: the audit area
brief = os.path.join(TMP, "brief.txt")
with open(brief, "w", encoding="utf-8") as f:
    f.write("Check the export, report the findings.")
os.environ["KALMIDO_JOB_CMD"] = json.dumps(["claude"])
check(aj.cmd_start(["--audit", "--worktree", "--title", "Audit", brief]) == 2, "#2792: --audit is not allowed with --worktree")
check(aj.cmd_start(["--audit", "--parent", "5", "--title", "Audit", brief]) == 2, "#2792: --audit is not allowed with --parent")
os.environ["KALMIDO_AUDIT_MAX"] = "2"
for jid in (901, 902):
    aj.save({"id": jid, "title": f"Audit {jid}", "state": "running", "runner_pid": os.getpid(), "audit": True, "created": now - 600})
aj.save({"id": 903, "title": "Build", "state": "running", "runner_pid": os.getpid(), "worktree": {"branch": "job/903"}, "created": now - 600})
check(aj.cmd_start(["--audit", "--title", "Audit 3", brief]) == 3, "#2792: the audit area is full at KALMIDO_AUDIT_MAX open audit jobs")
check(sum(1 for j in aj.all_jobs() if aj.is_open(j) and j.get("worktree")) == 1, "#2792: audit jobs are not counted as working copies")
check("read only" in aj.AUDIT_NOTE.lower() and "never commit" in aj.AUDIT_NOTE.lower(), "#2792: the read-only note in front of the brief")

# ---- #2383: images only from the project folder
proj = os.path.join(TMP, "proj")
os.makedirs(proj)
img = os.path.join(proj, "shot.png")
with open(img, "wb") as f:
    f.write(b"\x89PNG" + b"0" * 20)
home = os.path.realpath(os.path.expanduser("~"))
ex = ax.Extras(None, os.path.join(TMP, "xstate"))
old_cwd = os.getcwd()
try:
    os.environ["KALMIDO_PROJECT_DIR"] = proj
    os.chdir(home)
    check(ax.image_root() == [os.path.realpath(proj)] and ex._own_image(img), "#2383: KALMIDO_PROJECT_DIR is the project folder (also started from the home folder)")
    os.environ.pop("KALMIDO_PROJECT_DIR")
    check(ax.image_root() == [], "#2383: started from the home folder without KALMIDO_PROJECT_DIR nothing counts as the project folder")
    check(not ex._own_image(img), "#2383: ... so an image elsewhere is not attached")
    os.chdir(proj)
    check(ax.image_root() == [os.path.realpath(proj)] and ex._own_image(img), "#2383: the working folder stays the project folder")
    os.environ["KALMIDO_PROJECT_DIR"] = os.path.abspath(os.sep)
    check(ax.image_root() == [], "#2383: a file system root is never the project folder")
finally:
    os.environ.pop("KALMIDO_PROJECT_DIR", None)
    os.chdir(old_cwd)
for name, pat in (("setup.sh", "KALMIDO_PROJECT_DIR=%s"), ("setup.ps1", "KALMIDO_PROJECT_DIR=`\"$Dir`\"")):
    check(pat in read("static", "agent", name), f"#2383: {name} writes KALMIDO_PROJECT_DIR into the env file")

# ---- #3467: a task run commits as the task's repo.git_author
env = ar.git_author_env({"git_author": "Team Bot <bot@example.com>", "git_coauthor": True})
check(env == {"GIT_AUTHOR_NAME": "Team Bot", "GIT_AUTHOR_EMAIL": "bot@example.com", "GIT_COMMITTER_NAME": "Team Bot",
              "GIT_COMMITTER_EMAIL": "bot@example.com", "KALMIDO_GIT_COAUTHOR": "1"}, f"#3467: Name <mail> -> git env: {env}")
check(ar.git_author_env({"git_author": "no mail here"}) == {} and ar.git_author_env(None) == {}
      and ar.git_author_env({"git_author": "A\nB <a@example.com>"}) == {}, "#3467: nothing for a missing or odd value")
rn = object.__new__(ar.Runner)
rn.extras, rn.agent, rn.state_dir = None, {"owner_id": 7}, os.path.join(TMP, "rstate")
rn.run_repo = {"git_author": "Project Bot <project@example.com>", "git_coauthor": False}
os.environ["GIT_AUTHOR_NAME"] = "Agent Default"
e1 = rn.child_env(None, 12)
check(e1.get("GIT_AUTHOR_NAME") == "Project Bot" and e1.get("GIT_COMMITTER_EMAIL") == "project@example.com" and e1.get("KALMIDO_GIT_COAUTHOR") == "0",
      f"#3467: the task run gets the project's git author: {e1.get('GIT_AUTHOR_NAME')}")
e2 = rn.child_env(7, None)
check(e2.get("GIT_AUTHOR_NAME") == "Agent Default", "#3467: a chat run keeps the agent's git author of the launcher")
os.environ.pop("GIT_AUTHOR_NAME")

# ---- #1521 #1870: the rules block (the template block = AG_RULES, checked in agent_docs_coverage too)
tpl = read("mcp", "CLAUDE.template.md")
block = re.search(r"<!-- kalmido-agent-rules:start -->\n(.*?)<!-- kalmido-agent-rules:end -->", tpl, re.S).group(1)
flat = re.sub(r"\s+", " ", block)
check(re.search(r"never set a field of type `formula`", flat), "#1521: formula fields are never set")
for what in ("kind `extract`", "kind `merge`", "`contract_notice`", "`propose_contract_notice`"):
    check(what in flat, f"#1870: the 2.70 flows in the rules block: {what}")
check("weekly limit (`seven_day`)" in flat and "never guess it" in flat, "#2196: the two plan limits in the rules block")
check("**read only**" in flat, "#2792: reviews read only in the rules block")
check("also background jobs" in flat, "#3267: the usage hook in jobs in the rules block")
js = read("static", "js", "agentchat.js")
am = re.search(r"^const AG_RULES = (\".*\");$", js, re.M)
check(am and json.loads(am.group(1)) == block, "AG_RULES equals the template block")
steps = js[js.index("const AG_STEPS"):js.index("function agGuideModal")]
auto = [ln for ln in steps.split("\n") if "N_('Autostart')" in ln]
check(auto and "LaunchAgent with agent_launcher.sh" in auto[0] and "agent_launcher.ps1" not in auto[0], "#3267: the macOS step names agent_launcher.sh")
key = re.search(r"N_\('(Required: a systemd user unit[^']*)'\)", steps)
for lang in ("de", "es", "fr", "it", "nl"):
    tr = json.loads(read("static", "i18n", lang + ".json"))
    check(key and key.group(1) in tr and "agent_launcher.ps1" not in tr.get(key.group(1), "x"), f"#3267: {lang}.json has the macOS step")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2619_b_starter: {kt.OKS[0]} ok, {len(kt.FAILS)} failed")
sys.exit(1 if kt.FAILS else 0)
