#!/usr/bin/env python3
"""agent_dispatch.py -- the mechanical dispatcher of the reference starter (2.481.0, #3662 / #3320). Without it the starter
only reacts to events (chat, task events, jobs): nothing works a list off on its own, planned tasks can be left lying.
With it switched on, the event runner (agent_run.py) calls one `tick()` every few minutes, and that tick works the
chosen lists off deterministically -- no model decides what comes next:

  1. read the open tasks of the configured lists, the jobs of this host (agent_job.py) and the commits of the project's
     git repository (a commit subject with "#ID" = task ID is built),
  2. compute ONE state per task (STATES below),
  3. guard: a job without a progress line for stale_h hours, a job that ended with its tasks still open (one try more
     each, at max_tries the task is "stuck" and the person is told once), commits on a branch that never reached
     close_ref, a one-way task without approval, a task waiting for something,
  4. close the tasks whose commit is in close_ref (a comment with the commit, then complete),
  5. when a place is free and no brake holds: cut the next bundle (priority order, task sizes as points) and start ONE
     job (agent_job.py start) with a brief built from the tasks,
  6. once a day at report_at: a short report into the person's chat.

Switched on in Kalmido: Settings > Agents > (agent) > Runtime > "Work the list off" (GET /api/v1/agent runtime.dispatch:
"" off, "dry" dry run, "on"); KALMIDO_DISPATCH (off | dry | on) on this computer outranks it. A dry run reads everything
and writes nothing: what it would do goes to <state dir>/dispatch-dry.log and into the daily report.
The project configuration is KALMIDO-DISPATCH.json in the project folder (KALMIDO_DISPATCH_CONFIG = another path); without
lists in it the dispatcher stays idle. Keys and defaults: DEFAULTS. A stop file (<state dir>/dispatch-STOP or
KALMIDO-DISPATCH-STOP in the project folder) holds new starts; closing and the guard go on.

usage: agent_dispatch.py [--state DIR] [--dry-run] [--once]   one tick from the command line (the runner's environment:
                                                              KALMIDO_URL, KALMIDO_TOKEN); --dry-run prints what it would do
Only the Python standard library; Linux, macOS, Windows. Never prints the token or task texts into the log."""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "KALMIDO-DISPATCH.json"
STOP_FILE = "dispatch-STOP"
STATE_FILE = "dispatch.json"
DRY_LOG = "dispatch-dry.log"
MODES = ("off", "dry", "on")
STATES = ("done", "building", "on_branch", "held", "needs_yes", "stuck", "ready")
RUNNING = ("starting", "running", "paused")

DEFAULTS = {
    "lists": [],              # names or ids of the lists to work off (required)
    "places": 1,              # jobs of the dispatcher at once
    "worktree": False,        # jobs in their own git worktree (agent_job.py --worktree, branch job/<id>; merging is the project's)
    "interval_min": 10,       # minutes between two ticks
    "job_timeout_h": 6,
    "size_field": "Size",     # a field of the list with S / M / L (the first letter counts); a list tag S / M / L works too
    "size_points": {"S": 1, "M": 3, "L": 8},
    "size_default": "M",
    "bundle_points": 8,       # at most this many points per job (a bigger task goes alone)
    "bundle_max": 6,          # at most this many tasks per job
    "group_field": "",        # tasks with the same value of this field go into one job together ("" = no groups)
    "first_tags": [],         # tags / list tags that go first (class 0)
    "title_classes": [],      # regular expressions on the title; the first match = class 1, 2, ...
    "skip_tags": ["blocked", "keep"],  # never started
    "keep_tags": ["keep"],    # never closed
    "waiting_rx": r"(?im)^\s*\**\s*(waiting for|blocked by|needs|wartet auf|braucht)\s*:",
    "one_way_rx": r"(?i)\b(one[- ]way|no way back|irreversible|cannot be undone|einbahn|ohne r(ü|ue)ckweg)\b",
    "one_way_ok_tag": "approved",  # a one-way task starts only with this tag (set by a person: the approval)
    "close_ref": "",          # git ref whose commits close tasks ("" = the current branch; e.g. "origin/main" or a live branch)
    "fetch": False,           # git fetch before reading close_ref (for a remote ref)
    "stale_h": 3.0,           # a running job without a progress line for this long = finding
    "max_tries": 2,           # jobs that ended with the task still open; then "stuck"
    "branch_max_d": 2.0,      # commits on a job branch outside close_ref for this long = finding
    "report_at": "18:00",     # local time of the daily report ("" = none)
    "usage_limit_pct": 95.0,  # a fresh week value at or above this holds new starts (0 = never)
    "check_cmd": "",          # the project's check (tests / lint) the brief asks the job to run before it commits
    "finish_cmd": "",         # the project's own way to land a branch / go live, named in the brief ("" = none)
    "brief_extra": "",        # more text for every brief (the project's rules)
    "max_writes": 40,         # writes (comments, closes) per tick
}
ID_RE = re.compile(r"(?<![Jj]ob )(?<![\w/])#(\d{1,9})\b")


LOGGED = set()


def log_once(msg):
    """A configuration warning once per run of the runner, not every tick."""
    if msg not in LOGGED:
        LOGGED.add(msg)
        log(msg)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] dispatch: {msg}", file=sys.stderr, flush=True)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_config(project_dir):
    """DEFAULTS + KALMIDO-DISPATCH.json (unknown keys are named once in the log and left out); (config, problem)."""
    path = os.environ.get("KALMIDO_DISPATCH_CONFIG") or os.path.join(project_dir, CONFIG_FILE)
    cfg = dict(DEFAULTS)
    if not os.path.isfile(path):
        return cfg, "no " + CONFIG_FILE
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = None
    if not isinstance(raw, dict):
        return cfg, CONFIG_FILE + " is no JSON object"
    unknown = sorted(k for k in raw if k not in DEFAULTS)
    if unknown:
        log_once("unknown keys in the configuration left out: " + ", ".join(unknown))
    for k, v in raw.items():
        if k in DEFAULTS and (type(v) is type(DEFAULTS[k]) or (isinstance(DEFAULTS[k], float) and isinstance(v, int))):
            cfg[k] = v
        elif k in DEFAULTS:
            log_once(f"configuration key {k}: wrong type, default kept")
    return cfg, "" if cfg["lists"] else "no lists in " + CONFIG_FILE


def mode_of(agent):
    """off | dry | on: KALMIDO_DISPATCH on this computer, else runtime.dispatch of GET /api/v1/agent ("" = off)."""
    env = (os.environ.get("KALMIDO_DISPATCH") or "").strip().lower()
    if env in MODES:
        return env
    v = str(((agent or {}).get("runtime") or {}).get("dispatch") or "").strip().lower()
    return v if v in MODES else "off"


# ---- what one task is

def tags_of(t):
    return [str(x) for x in (t.get("tags") or []) + (t.get("list_tags") or [])]


def has_tag(t, names):
    low = {str(n).strip().lower() for n in names if str(n).strip()}
    return any(x.strip().lower() in low for x in tags_of(t))


def size_of(t, cfg, field_ids):
    """S / M / L of a task: the size field of its list (the first letter of the value / option name), else a list tag that is
    just S / M / L, else size_default."""
    fid = field_ids.get((t.get("list_id"), "size"))
    v = str((t.get("fields") or {}).get(fid) or "").strip() if fid else ""
    v = field_ids.get((t.get("list_id"), "size_opt", v), v)
    if v[:1].upper() in cfg["size_points"]:
        return v[:1].upper()
    for x in tags_of(t):
        if x.strip().upper() in cfg["size_points"]:
            return x.strip().upper()
    return cfg["size_default"]


def points(t, cfg, field_ids):
    return int(cfg["size_points"].get(size_of(t, cfg, field_ids), cfg["size_points"].get(cfg["size_default"], 3)))


def group_of(t, field_ids):
    fid = field_ids.get((t.get("list_id"), "group"))
    return str((t.get("fields") or {}).get(fid) or "").strip() if fid else ""


PRIO_RANK = {"urgent": 0, "high": 1, "medium": 2, "normal": 2, "": 2, "low": 3}


def prio_class(t, cfg):
    if cfg["first_tags"] and has_tag(t, cfg["first_tags"]):
        return 0
    for i, pat in enumerate(cfg["title_classes"]):
        try:
            if re.search(pat, t.get("title") or ""):
                return 1 + i
        except re.error:
            continue
    return 1 + len(cfg["title_classes"])


def sort_key(t, cfg):
    p = t.get("priority")
    rank = PRIO_RANK.get(str(p).lower(), 2) if not isinstance(p, int) else max(0, 3 - p)
    return (prio_class(t, cfg), rank, t.get("due") or "9999-99-99", int(t["id"]))


def classify(tasks, evidence, jobs, reg, cfg):
    """One state per open task (STATES): done (commit in close_ref), building (an open job of the dispatcher has it),
    on_branch (a commit on a job branch only), held (skip tag / a waiting line), needs_yes (one-way without the approval
    tag), stuck (max_tries jobs left it open), ready."""
    running = {int(t) for jid, e in reg.get("jobs", {}).items() if (jobs.get(str(jid)) or {}).get("state") in RUNNING
               for t in e.get("tasks") or []}
    out = {}
    for t in tasks:
        tid = int(t["id"])
        text = (t.get("title") or "") + "\n" + (t.get("notes") or "")
        if tid in evidence["done"]:
            out[tid] = "done"
        elif tid in running:
            out[tid] = "building"
        elif tid in evidence["branch"]:
            out[tid] = "on_branch"
        elif has_tag(t, cfg["skip_tags"]) or re.search(cfg["waiting_rx"], t.get("notes") or ""):
            out[tid] = "held"
        elif re.search(cfg["one_way_rx"], text) and not has_tag(t, [cfg["one_way_ok_tag"]]):
            out[tid] = "needs_yes"
        elif int((reg.get("tries") or {}).get(str(tid)) or 0) >= int(cfg["max_tries"]):
            out[tid] = "stuck"
        else:
            out[tid] = "ready"
    return out


def cut_bundle(tasks, states, cfg, field_ids):
    """The next job's tasks: the first ready task in priority order; with a group value all ready tasks of that group,
    else more ready tasks while the points fit (bundle_points) and bundle_max holds. A task bigger than bundle_points goes
    alone. Deterministic: the same input gives the same bundle."""
    q = sorted((t for t in tasks if states.get(int(t["id"])) == "ready"), key=lambda t: sort_key(t, cfg))
    if not q:
        return []
    first = q[0]
    g = group_of(first, field_ids)
    if g:
        return [t for t in q if group_of(t, field_ids) == g][:int(cfg["bundle_max"])]
    out, pts = [first], points(first, cfg, field_ids)
    if pts >= int(cfg["bundle_points"]):
        return out
    for t in q[1:]:
        if len(out) >= int(cfg["bundle_max"]):
            break
        if group_of(t, field_ids):
            continue
        p = points(t, cfg, field_ids)
        if pts + p <= int(cfg["bundle_points"]):
            out.append(t)
            pts += p
    return out


def brief_of(bundle, cfg, field_ids):
    """The job's brief: the tasks (their texts fenced, they are the person's tasks but stay data for anything that asks
    for secrets or other access), one commit per task with "#ID" in the subject, the project's check and finish steps."""
    lines = ["(Kalmido dispatcher) Build these tasks of the list you work off, one after the other, in this order. "
             "Read each task with get_task (description and comments) before you start it.", ""]
    for t in bundle:
        notes = " ".join(str(t.get("notes") or "").split())[:1500]
        lines.append(f"- #{t['id']} {t.get('title') or ''} [size {size_of(t, cfg, field_ids)}]")
        if notes:
            lines.append(f"  <<<task {t['id']}\n  {notes}\n  task {t['id']}>>>")
    lines += ["", "Rules of the dispatcher:",
              "- One commit per task, its subject starts with \"#ID\" (e.g. \"#%s: ...\"): the dispatcher sees from the commits "
              "what is built and closes the task once the commit is in %s." % (bundle[0]["id"], cfg["close_ref"] or "the current branch"),
              "- A task that does not fit (already built, unclear, needs a decision of the person): do NOT build it; leave a "
              "comment on it with add_comment saying why, and go on with the next one.",
              "- Never close tasks yourself; never start another job; report milestones with agent_job.py progress."]
    if cfg["check_cmd"]:
        lines.append(f"- Before each commit run the project's check: {cfg['check_cmd']} -- it must pass.")
    if cfg["finish_cmd"]:
        lines.append(f"- At the end: {cfg['finish_cmd']}")
    if cfg["brief_extra"]:
        lines += ["", cfg["brief_extra"]]
    return "\n".join(lines) + "\n"


# ---- the host: git, jobs, the API

def git(repo, *args, timeout=60):
    try:
        p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def ids_of(subject):
    return {int(x) for x in ID_RE.findall(subject or "")}


def evidence_of(repo, cfg, now=None):
    """{done: {tid: sha}, branch: {tid: (branch, age_s)}, ok}: commits of close_ref name built tasks; commits of the job
    branches (job/*) outside close_ref name tasks built but not landed."""
    now = now or time.time()
    out = {"done": {}, "branch": {}, "ok": False}
    if cfg["fetch"]:
        git(repo, "fetch", "--quiet", timeout=120)
    ref = cfg["close_ref"] or "HEAD"
    rc, txt = git(repo, "log", "--format=%h\t%s", "-n", "5000", ref)
    if rc != 0:
        return out
    out["ok"] = True
    for ln in txt.splitlines():
        sha, _, subj = ln.partition("\t")
        for tid in ids_of(subj):
            out["done"].setdefault(tid, sha)
    rc, txt = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/job/")
    for br in (txt.split() if rc == 0 else []):
        rc2, t2 = git(repo, "log", "--format=%ct\t%s", f"{ref}..{br}")
        for ln in (t2.splitlines() if rc2 == 0 else []):
            ts, _, subj = ln.partition("\t")
            for tid in ids_of(subj):
                if tid not in out["done"]:
                    out["branch"].setdefault(tid, (br, now - float(ts or now)))
    return out


def host_jobs(state_dir):
    """The jobs of agent_job.py on this host: {id: job dict}."""
    try:
        sys.path.insert(0, HERE)
        import agent_job
    except ImportError:
        return {}
    agent_job.STATE_DIR = state_dir
    try:
        return {str(j["id"]): j for j in agent_job.all_jobs()}
    except Exception as e:
        log(f"jobs: {type(e).__name__}")
        return {}


def last_progress(state_dir, jid, job):
    """Epoch of the job's last progress line (its progress.log), else its start."""
    p = os.path.join(state_dir, "jobs", str(jid), "progress.log")
    try:
        return os.path.getmtime(p)
    except OSError:
        return float(job.get("revived") or job.get("created") or 0)


class Writer:
    """Every write of a tick goes through here; a dry run only records."""

    def __init__(self, dry, limit):
        self.dry, self.limit, self.done = dry, int(limit), []

    def __call__(self, what, fn=None):
        if len(self.done) >= self.limit:
            return False
        self.done.append(what)
        if self.dry or fn is None:
            return True
        try:
            fn()
            return True
        except Exception as e:
            log(f"{what}: {type(e).__name__} {str(e)[:120]}")
            return False


def read_tasks(api, cfg):
    """(tasks, field_ids, problem): the open tasks of the configured lists; field_ids maps (list id, "size" | "group") to the
    field's id and (list id, "size_opt", option id) to the option's name."""
    try:
        lists = api.req("GET", "/lists") or {}
    except Exception as e:
        return [], {}, f"lists: {type(e).__name__}"
    lists = lists.get("data", lists) if isinstance(lists, dict) else lists
    want = [str(x).strip().lower() for x in cfg["lists"]]
    chosen = [l for l in lists or [] if str(l.get("id")) in want or str(l.get("name") or "").strip().lower() in want]
    if not chosen:
        return [], {}, "none of the configured lists is shared with the agent"
    tasks, fids = [], {}
    for l in chosen:
        lid = l["id"]
        try:
            fs = api.req("GET", f"/lists/{int(lid)}/fields") or {}
            for f in (fs.get("data", fs) if isinstance(fs, dict) else fs) or []:
                name = str(f.get("name") or "").strip().lower()
                for key in ("size", "group"):
                    if cfg[key + "_field"] and name == cfg[key + "_field"].strip().lower():
                        fids[(lid, key)] = str(f["id"])
                        if key == "size":
                            for o in ((f.get("options") or {}).get("options") or []):
                                fids[(lid, "size_opt", str(o.get("id")))] = str(o.get("name") or "")
        except Exception:
            pass  # no fields: sizes from list tags / the default
        cursor = None
        for _ in range(20):
            q = {"list_id": lid, "status": "open", "limit": 500}
            if cursor:
                q["cursor"] = cursor
            page = api.req("GET", "/tasks", query=q) or {}
            tasks += [t for t in page.get("data") or [] if not t.get("deleted")]
            cursor = page.get("next_cursor") or page.get("cursor")
            if not cursor:
                break
    return tasks, fids, ""


def start_job(bundle, brief, cfg, env, state_dir):
    """agent_job.py start with the brief on stdin; (job id | None, message)."""
    title = "Dispatcher: " + " ".join(f"#{t['id']}" for t in bundle)
    first = (bundle[0].get("title") or "")[:60]
    title = f"{title} {first}".strip()[:180]
    args = [sys.executable or "python3", os.path.join(HERE, "agent_job.py"), "start", "--title", title, "--task", str(bundle[0]["id"]),
            "--timeout-h", str(cfg["job_timeout_h"])] + (["--worktree"] if cfg["worktree"] else []) + ["-"]
    e = dict(env or os.environ)
    e["KALMIDO_STATE_DIR"] = state_dir
    try:
        p = subprocess.run(args, input=brief, capture_output=True, text=True, timeout=180, env=e)
    except (OSError, subprocess.SubprocessError) as ex:
        return None, type(ex).__name__
    m = re.search(r"Job #(\d+)", p.stdout or "")
    return (int(m.group(1)) if m else None), " ".join((p.stdout or p.stderr or "").split())[:160]


# ---- one tick

class Dispatcher:
    """One dispatcher per runner. host: the runner (api, state_dir, agent, say(), usage, child_env, perm_uid) -- or the
    small stand-in of the command line. tick() is safe to call often: it waits interval_min between real rounds."""

    def __init__(self, host, project_dir=None):
        self.host = host
        self.project_dir = project_dir or os.getcwd()
        self.state_path = os.path.join(host.state_dir, STATE_FILE)
        self.reg = load_json(self.state_path, {})
        for k, v in (("jobs", {}), ("tries", {}), ("told", {}), ("counted", []), ("closed", {}), ("started", 0)):
            self.reg.setdefault(k, v)
        self.last = 0.0

    def save(self):
        try:
            write_json(self.state_path, self.reg)
        except OSError as e:
            log(f"state: {type(e).__name__}")

    def say(self, key, *args):
        return self.host.say(key, *args) if hasattr(self.host, "say") else key

    def owner(self):
        f = getattr(self.host, "perm_uid", None)
        v = f() if f else None
        v = v or ((getattr(self.host, "agent", None) or {}).get("owner_id"))
        return int(v) if str(v or "").isdigit() else None

    def brakes(self, cfg):
        out = []
        if os.path.exists(os.path.join(self.host.state_dir, STOP_FILE)) or os.path.exists(os.path.join(self.project_dir, "KALMIDO-DISPATCH-STOP")):
            out.append("stop file")
        u = getattr(self.host, "usage", None)
        if u and float(cfg["usage_limit_pct"] or 0) > 0:
            rl, _ = u.fresh()
            w = (rl or {}).get("seven_day") or {}
            if w.get("used_percentage") is not None and float(w["used_percentage"]) >= float(cfg["usage_limit_pct"]):
                out.append(f"usage {w['used_percentage']}%")
            if u.paused_until():
                out.append("usage limit")
        closed = getattr(self.host, "ws_closed", False)
        if closed:
            out.append("outside the work window")
        return out

    def tick(self, now=None, force=False, dry=None):
        """One round when it is due (or force). Returns the result dict (or None when not due / off)."""
        now = now or time.time()
        agent = getattr(self.host, "agent", None) or {}
        mode = mode_of(agent)
        if mode == "off" and dry is None:
            return None
        cfg, problem = load_config(self.project_dir)
        if not force and now - self.last < max(1, int(cfg["interval_min"])) * 60:
            return None
        self.last = now
        dry = (mode == "dry") if dry is None else dry
        res = {"mode": "dry" if dry else "on", "problem": problem, "states": {}, "findings": [], "started": None, "closed": [], "brakes": []}
        if problem:
            if self.reg["told"].get("problem") != problem:
                self.reg["told"]["problem"] = problem
                self.save()
                log(problem + ": idle")
            return res
        w = Writer(dry, cfg["max_writes"])
        tasks, fids, problem = read_tasks(self.host.api, cfg)
        if problem:
            res["problem"] = problem
            log(problem)
            return res
        jobs = host_jobs(self.host.state_dir)
        ev = evidence_of(self.project_dir, cfg, now)
        if not ev["ok"]:
            res["problem"] = "no git repository (or close_ref unknown) in the project folder"
            log(res["problem"])
            return res
        self.guard(jobs, cfg, now, res)
        states = classify(tasks, ev, jobs, self.reg, cfg)
        res["states"] = states
        by_id = {int(t["id"]): t for t in tasks}
        for tid, st in sorted(states.items()):
            t = by_id[tid]
            if st == "done" and not has_tag(t, cfg["keep_tags"]):
                sha = ev["done"][tid]
                api = self.host.api
                ok = w(f"close #{tid} (commit {sha})", lambda tid=tid, sha=sha: (
                    api.req("POST", f"/tasks/{tid}/comments", {"body": self.say("dispatch_closed", sha, cfg["close_ref"] or "HEAD")}),
                    api.req("POST", f"/tasks/{tid}/complete")))
                if ok:
                    res["closed"].append(tid)
            elif st == "on_branch":
                br, age = ev["branch"][tid]
                if age >= float(cfg["branch_max_d"]) * 86400:
                    self.finding(res, f"branch:{tid}", self.say("dispatch_on_branch", f"#{tid}", br))
            elif st == "needs_yes":
                self.finding(res, f"yes:{tid}", self.say("dispatch_needs_yes", f"#{tid}", cfg["one_way_ok_tag"]))
            elif st == "stuck":
                self.finding(res, f"stuck:{tid}", self.say("dispatch_stuck", f"#{tid}", cfg["max_tries"]))
        res["brakes"] = self.brakes(cfg)
        running = [jid for jid in self.reg["jobs"] if (jobs.get(str(jid)) or {}).get("state") in RUNNING]
        free = int(cfg["places"]) - len(running)
        if free > 0 and not res["brakes"]:
            bundle = cut_bundle(tasks, states, cfg, fids)
            if bundle:
                ids = [int(t["id"]) for t in bundle]
                brief = brief_of(bundle, cfg, fids)
                if dry:
                    w("start a job for " + " ".join(f"#{i}" for i in ids))
                    res["started"] = {"tasks": ids, "dry": True}
                else:
                    env = self.host.child_env(self.owner(), None) if hasattr(self.host, "child_env") else dict(os.environ)
                    if self.owner():
                        env["KALMIDO_CHAT_USER"] = str(self.owner())
                    jid, msg = start_job(bundle, brief, cfg, env, self.host.state_dir)
                    if jid:
                        self.reg["jobs"][str(jid)] = {"tasks": ids, "at": now}
                        self.reg["started"] = int(self.reg.get("started") or 0) + 1
                        res["started"] = {"tasks": ids, "job": jid}
                        w(f"started job #{jid} for " + " ".join(f"#{i}" for i in ids))
                    else:
                        log(f"job not started: {msg}")
                        res["brakes"].append("job not started")
        self.report(res, tasks, cfg, now, dry, w)
        tell = [f for f in res["findings"] if f.get("new")]
        if tell and not dry and self.owner():
            text = self.say("dispatch_findings") + "\n" + "\n".join("- " + f["text"] for f in tell)
            self.chat(text)
        if dry:
            self.dry_log(w.done, res)
        self.save()
        return res

    def guard(self, jobs, cfg, now, res):
        """Jobs of the dispatcher: an ended one counts one try for each of its tasks (once); a running one without a progress
        line for stale_h hours is a finding. Jobs gone from this host (removed state folder) count as ended."""
        for jid, e in list(self.reg["jobs"].items()):
            j = jobs.get(str(jid))
            st = (j or {}).get("state") or "lost"
            if st in RUNNING:
                last = last_progress(self.host.state_dir, jid, j)
                if now - last >= float(cfg["stale_h"]) * 3600:
                    self.finding(res, f"stale:{jid}:{int(last)}", self.say("dispatch_stale", f"#{jid}", round((now - last) / 3600, 1)))
                continue
            if str(jid) not in self.reg["counted"]:
                self.reg["counted"].append(str(jid))
                self.reg["counted"] = self.reg["counted"][-500:]
                for tid in e.get("tasks") or []:
                    self.reg["tries"][str(tid)] = int(self.reg["tries"].get(str(tid)) or 0) + 1
            if now - float(e.get("at") or now) > 30 * 86400:
                self.reg["jobs"].pop(jid, None)

    def finding(self, res, key, text):
        new = key not in self.reg["told"]
        res["findings"].append({"key": key, "text": text, "new": new})
        if new:
            self.reg["told"][key] = int(time.time())

    def chat(self, text):
        if getattr(self.host, "quiet", False):  # the command line dry run: printed, never posted
            print(text)
            return
        uid = self.owner()
        api = self.host.api
        try:
            if hasattr(api, "chat"):
                api.chat(uid, text)
            else:
                api.req("POST", f"/agent/chats/{uid}", {"body": text})
        except Exception as e:
            log(f"chat: {type(e).__name__}")

    def report(self, res, tasks, cfg, now, dry, w):
        """Once a day after report_at (local time): counts per state, jobs started, findings, the brakes; in a dry run also
        what it would have done (the report is the only thing a dry run posts)."""
        at = cfg["report_at"]
        if not re.fullmatch(r"\d{2}:\d{2}", at or "") or not self.owner():
            return
        lt = time.localtime(now)
        day = time.strftime("%Y-%m-%d", lt)
        if self.reg.get("report_day") == day or time.strftime("%H:%M", lt) < at:
            return
        self.reg["report_day"] = day
        counts = {}
        for st in res["states"].values():
            counts[st] = counts.get(st, 0) + 1
        lines = [self.say("dispatch_report_dry" if dry else "dispatch_report", day)]
        lines.append(", ".join(f"{self.say('dispatch_state_' + s)} {counts[s]}" for s in STATES if counts.get(s)) or self.say("dispatch_nothing"))
        if res["brakes"]:
            lines.append(self.say("dispatch_brakes", ", ".join(res["brakes"])))
        for f in res["findings"]:
            lines.append("- " + f["text"])
        if dry:
            lines += ["- " + x for x in w.done[:20]]
        self.chat("\n".join(lines))

    def dry_log(self, done, res):
        try:
            with open(os.path.join(self.host.state_dir, DRY_LOG), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M ") + json.dumps({"would": done, "brakes": res["brakes"],
                                                                        "findings": [x["text"] for x in res["findings"]]}, ensure_ascii=False) + "\n")
        except OSError:
            pass


# ---- the command line: one tick by hand

class CliHost:
    def __init__(self, state_dir):
        sys.path.insert(0, HERE)
        import agent_run
        self.api = agent_run.Api(os.environ["KALMIDO_URL"], os.environ["KALMIDO_TOKEN"])
        self.state_dir = os.path.expanduser(state_dir)
        os.makedirs(self.state_dir, exist_ok=True)
        self.agent = self.api.req("GET", "/agent") or {}
        self._say = agent_run.say

    def say(self, key, *args):
        return self._say(key, self.agent.get("lang"), *args)

    def perm_uid(self, tid=None):
        v = self.agent.get("perm_user_id") or os.environ.get("KALMIDO_PERM_USER") or self.agent.get("owner_id")
        return int(v) if str(v or "").isdigit() else None


def main(argv):
    state, dry = os.environ.get("KALMIDO_STATE_DIR") or "~/.cache/kalmido-agent", False
    i = 0
    while i < len(argv):
        if argv[i] == "--state":
            state = argv[i + 1]; i += 2
        elif argv[i] == "--dry-run":
            dry = True; i += 1
        elif argv[i] == "--once":
            i += 1
        else:
            print(__doc__)
            return 0 if argv[i] in ("-h", "--help") else 2
    if not os.environ.get("KALMIDO_URL") or not os.environ.get("KALMIDO_TOKEN"):
        print("KALMIDO_URL / KALMIDO_TOKEN missing")
        return 2
    host = CliHost(state)
    host.quiet = dry
    d = Dispatcher(host)
    if dry:
        d.save = lambda: None  # a dry run from the command line leaves the dispatcher's state as it is
    res = d.tick(force=True, dry=True if dry else None) or {"mode": "off"}
    out = dict(res)
    out["states"] = {str(k): v for k, v in (res.get("states") or {}).items()}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
