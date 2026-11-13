"""2.392.2 (#3366): the server's watchdog over agent jobs -- it tells, it never stops anything.

Every watchdog tick (notify/push.py WD_TICKS), once per case (job_watch, unique kind + ref):
 - job_stalled: a running job (not a request waiting for approval, not a person's request job) without progress (agent_jobs
   .updated_at: every log line, state change or working update moves it) for the agent's work style stall_min minutes
   (default 60, 0 = off). A new update ends the case; the next stall is a new one.
 - branch_stranded: a branch of an open task (git_branches: commits the default branch lacks) while no job of the task is
   open, the last one ended WATCH_STRAND_DAYS (3) days ago or more. A merge, a new commit (another case), a new job or the
   completed task end it.
Each finding goes to the agent of the job (event job_stalled / branch_stranded; the task only while it sees it, the branch
name marked untrusted) and to the job's owner (the person it is for, else the agent's owner): a News entry (row "approval":
"An agent waits for me") and a push only where that row's push is on, the agent's work style lets it disturb (push limits or
results, never = no push) and its daily push budget holds. Waiting for me lists the open ones (agents/waiting.py). As the
net under every other way a job ends, the tick also clears the delivery marks of jobs that ended (tasks/deliver.py)."""
from datetime import timedelta

from ..core.access import task_visible
from ..core.coltype import ct_iso  # 2.1095.0 (#5306): a time column as the canonical text in SQL
from ..core.config import PUBLIC_URL
from ..core.db import iso, now_utc, parse_iso
from ..core.i18n import N_, tr
from ..collab.news import news_add, notif_ok
from ..notify.push import notify, push_prio, WD_TICKS
from ..tasks.deliver import dv_job_ended
from ..api.v1 import task_for
from .chat import h6e_agent_push_ok
from .core import agent_emit, agent_row, job_dict, lst_brief
from .workstyle import ws_get

WATCH_STRAND_DAYS = 3
WATCH_TITLE = {"job_stalled": N_("{0}: a job makes no progress"), "branch_stranded": N_("{0}: work lies on a branch without a merge")}
WATCH_STALL_FLOOR = 15  # minutes: nothing below (ws_value keeps stall_min at 0 or 15..1440)
WATCH_MAX = 200  # cases per kind and tick (the rest comes in the next tick)


def _owner(c, j):
    if j["user_id"]:
        return j["user_id"]
    r = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (j["agent_id"],)).fetchone()
    return r["owner_id"] if r else None


def _new_case(c, kind, ref, j, tid, detail=""):
    """Records the case; None when it was told already."""
    r = c.execute("""INSERT INTO job_watch(kind, ref, agent_id, user_id, job_id, task_id, detail, created_at) VALUES(?,?,?,?,?,?,?,?)
                     ON CONFLICT (kind, ref) DO NOTHING RETURNING id""",
                  (kind, ref, j["agent_id"], _owner(c, j), j["id"], tid, detail, iso(now_utc()))).fetchone()
    return r[0] if r else None


def _tell(c, users, S, LG, kind, j, tid, data):
    """The event to the agent, the News entry and (maybe) a push to the owner."""
    aid = j["agent_id"]
    row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone() if tid else None
    ev = {**data, "job": job_dict(c, j)}
    if row and task_visible(c, tid, aid, full=True):
        ev.update(task=task_for(c, row, aid), list=lst_brief(c, row["list_id"]))
    agent_emit(c, aid, kind, ev, actor=None)
    uid = _owner(c, j)
    if not uid or uid not in users:
        return
    from ..core.objnotify import obj_readers  # 2.891.0 (#5270)
    s, lid = S[uid], row["list_id"] if row else None
    news_add(c, uid, "job_watch", task_id=tid if row and obj_readers(c, "task", tid, [uid]) else None,  # 2.891.0 (#5270): the core's read right, as news_add asks
             data={"kind": kind, "job": j["id"], "title": (j["title"] or "")[:200], **{k: v for k, v in data.items() if k in ("minutes", "days")}},
             actor=aid)  # collab_user decides (the collaboration module of the person)
    a = agent_row(c, aid)
    if not a or ws_get(a)["push"] == "never" or not notif_ok(c, uid, s, "approval", "push", lid) or not h6e_agent_push_ok(aid, uid):
        return
    lg = LG.get(uid, "en")
    notify(uid, tr(WATCH_TITLE[kind], a["display_name"] or a["username"], lg=lg), j["title"] or "", push_prio(s),
           f"{PUBLIC_URL}/#job/{j['id']}", s=s, kind="other")


def watch_stalled(c, users, S, LG):
    now = now_utc()
    rows = c.execute("""SELECT * FROM agent_jobs WHERE state='running' AND kind IS NULL AND COALESCE(approval, '')='' AND updated_at<?
                         ORDER BY updated_at LIMIT ?""", (iso(now - timedelta(minutes=WATCH_STALL_FLOOR)), WATCH_MAX)).fetchall()
    ws = {}
    for j in rows:
        if j["agent_id"] not in ws:
            a = agent_row(c, j["agent_id"])
            ws[j["agent_id"]] = ws_get(a)["stall_min"] if a else 0
        mins = ws[j["agent_id"]]
        at = parse_iso(j["updated_at"])
        if not mins or at is None or at > now - timedelta(minutes=mins):
            continue
        if _new_case(c, "job_stalled", f"{j['id']}@{j['updated_at']}", j, j["task_id"]):
            m = int((now - at).total_seconds() // 60)
            _tell(c, users, S, LG, "job_stalled", j, j["task_id"], {"since": j["updated_at"], "minutes": m, "limit_minutes": mins,
                  "hint": "No progress on this job for a while. Report progress, end it (done / failed) or say what blocks it."})
    c.execute("""UPDATE job_watch SET cleared_at=? WHERE kind='job_stalled' AND cleared_at IS NULL AND NOT EXISTS
                 (SELECT 1 FROM agent_jobs j WHERE j.id=job_watch.job_id AND j.state='running'
                  AND CAST(j.id AS TEXT) || '@' || """ + ct_iso("j.updated_at") + """ = job_watch.ref)""", (iso(now),))  # 2.1095.0 (#5306): the form Python read


def watch_stranded(c, users, S, LG):
    now = now_utc()
    rows = c.execute("""SELECT b.conn_id, b.name, b.sha, b.ahead, b.task_id, k.owner, k.repo FROM git_branches b
                         JOIN tasks t ON t.id=b.task_id JOIN git_conns k ON k.id=b.conn_id
                         WHERE b.ahead>0 AND b.sha<>'' AND t.status=0 AND t.deleted_at IS NULL
                         AND NOT EXISTS (SELECT 1 FROM agent_jobs j WHERE j.state IN ('running','waiting')
                                         AND (j.task_id=t.id OR j.id IN (SELECT job_id FROM agent_job_tasks WHERE task_id=t.id)))
                         ORDER BY b.task_id, b.name LIMIT ?""", (WATCH_MAX * 5,)).fetchall()
    live, told = set(), 0
    for b in rows:
        j = c.execute("""SELECT * FROM agent_jobs WHERE kind IS NULL AND (task_id=? OR id IN (SELECT job_id FROM agent_job_tasks WHERE task_id=?))
                         ORDER BY updated_at DESC, id DESC LIMIT 1""", (b["task_id"], b["task_id"])).fetchone()
        at = parse_iso(j["updated_at"]) if j else None
        if not j or at is None or at > now - timedelta(days=WATCH_STRAND_DAYS):
            continue  # a branch no job of an agent left behind (or not long enough) is not the watchdog's
        ref = f"{b['task_id']}:{b['conn_id']}:{b['name']}@{b['sha']}"
        live.add(ref)
        if told < WATCH_MAX and _new_case(c, "branch_stranded", ref, j, b["task_id"], b["name"][:200]):
            told += 1
            _tell(c, users, S, LG, "branch_stranded", j, b["task_id"],
                  {"branch": {"name": b["name"], "repo": f"{b['owner']}/{b['repo']}", "ahead": b["ahead"], "origin": "git", "untrusted": True},
                   "days": int((now - at).total_seconds() // 86400), "since": j["updated_at"],
                   "hint": "Work of this task lies on a branch without a merge and no job is open. Merge it, or park the task with the reason."})
    if len(rows) >= WATCH_MAX * 5:
        return  # 2.392.2 (review): only a complete look ends cases (a branch beyond the window still lies there)
    for r in c.execute("SELECT id, ref FROM job_watch WHERE kind='branch_stranded' AND cleared_at IS NULL").fetchall():
        if r["ref"] not in live:
            c.execute("UPDATE job_watch SET cleared_at=? WHERE id=?", (iso(now), r["id"]))


def watch_tick(c, users, S, LG):
    dv_job_ended(c)  # tasks/deliver.py: the in_progress marks of jobs that ended in a way without its own call
    watch_stalled(c, users, S, LG)
    watch_stranded(c, users, S, LG)
    c.commit()


def watch_open(c, uid):
    """The open findings told to uid (Waiting for me): rows of job_watch + the job's title, newest first."""
    return c.execute("""SELECT w.*, j.title AS job_title FROM job_watch w LEFT JOIN agent_jobs j ON j.id=w.job_id
                        WHERE w.user_id=? AND w.cleared_at IS NULL ORDER BY w.id DESC LIMIT 100""", (uid,)).fetchall()


WD_TICKS.append(("agent job watch", watch_tick))
