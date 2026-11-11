"""Agents: accounts, event queue + long polling, runtime settings, permissions of people towards agents."""
import contextlib
import json
import os
import re
import uuid
import threading
import time
from datetime import timedelta
from flask import g, has_request_context

from ..core.config import app, EMAIL_RE
from ..core.pg import insert_id, system_ctx, WEB_THREADS
from ..core.pgbus import bus_active, bus_on, bus_send  # 2.622.0 (#3891)
from ..core.ephem import eph_add  # 2.622.0 (#3891)
from ..core.i18n import tr
from ..core.db import db, inbox_default, iso, iso_ms, now_utc, parse_iso  # db: 2.959.0 (#4030)
from ..core.objcomments import ocm_old_cols  # 2.972.0 (#5272)
from ..accounts.session import me
from ..accounts.pictures import avatar_url
from ..core.dlock import dl_list_locked
from ..core.access import acx_task_ok, Denied, joined_lists_sql, list_people, list_role, MANAGE_ROLES, need_list, need_task, org_trip_sql, reading_sql, task_visible, vis_sql, WRITE_ROLES
from ..core.access import tasks_visible  # 2.674.0 B (#4194)
from ..core.access import otr_live  # 2.777.0 (#5378): the lists' trash condition of the core
from ..core.pg import st_ids  # 2.674.0 B (#4194)
from ..core.state import visible_sections
from ..tasks.oneway import dec_list
from ..tasks.validation import valid_hm
from ..tasks.watchers import wat_users  # 2.473.0 (#3357)
from ..collab.comments import comment_plain, user_names
from ..core.errors import BadInput
from ..notify.alerts import _env_int
from ..api.v1 import task_for, WH_ON
from ..api.common import act_via
from ..integrations.webhooks import wh_actor, wh_diff_out, wh_log, WH_QUEUE_MAX  # wh_diff_out: 2.959.0 (#4030)
from ..collab.replies import reply_of  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import is_org_admin  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import user_orgs  # 2.777.0 C (#5378)
from ..accounts.orgroles import user_orgs_full  # 2.777.0 C (#5378)


# ---------------------------------------------------------------- 2.0.0: agents, reactions, shared list tags, tidy
# AGENTS are users of kind 'agent' (users.kind): an AI assistant, a bot, an n8n flow -- anything that works through the
# REST API. An admin creates them (Settings > Users > Agents) or turns an existing user into one. An agent is never an admin,
# cannot log in to the web app (only its API tokens work) and sees exactly the lists shared with it
# (or that it owns). Kalmido never starts an agent or any AI process: it only tells the agent what happened, as signed
# webhooks (the webhook machinery: HMAC, retries, delivery log) and/or through a queue the agent polls
# (GET /api/v1/agent/events, optionally long-polling with wait=). Kill switch: agents.enabled = 0 -> its tokens are
# refused (403), no events are recorded, its webhook is off and its pending deliveries are dropped.
# Events: mention (@agent in a comment, or @name in a task's title / notes), comment (on a task the agent follows: assigned,
# created, commented before), assigned / unassigned, chat (a person wrote in the chat panel), reaction (someone reacted to
# the agent's comment; 👍 / 👎 by an approver = approval), job (Approve / Reject / Stop on one of its jobs), tidy (a new task in
# a list with "Agent may tidy up entries" on; 2.4.1: only to the list's tidy agent), wake (POST .../wake: people or scripts
# nudge agents without an event loop; no button since 2.4.1), ping (the admin's test), runtime_changed / reset (2.4.1: its
# runtime settings changed / "Reset now"). Never for the agent's
# own actions. Envelope: {id, seq, event, created_at, agent_id, actor, via, data} -- the same body for the webhook and the queue.
# REACTIONS on comments (everyone who sees the comments): 👍 👎 ❤️ (stored as up / down / heart)
# or any other single emoji (stored as the emoji itself). Only 👍 / 👎 mean something to agents (approval).
# APPROVERS (👍 / 👎 on an agent's comment count as approval / rejection): people -- never agents -- who are the list owner, a list
# admin, the task's assignee or an instance admin (and see the task). Everyone else's reaction is just a reaction.
# LIST TAGS: tags that belong to a list (list_tags) and are shared by all its members, colours per list, next to the personal
# tags (per user; 2.955.0 #5276: obj_tags scope user, was task_tags). Members with edit rights create / rename / colour / delete them; participants may
# only use existing ones on their tasks. Moving a task to another list takes its list tags along by name.
# TIDY (lists.agent_tidy off | suggest | auto): only for lists an agent is a member (or the owner) of. suggest = the agent
# comments with a structured suggestion (comments.suggestion); 👍 by someone who may change the task (or "Apply") applies
# it. auto = the agent applies it itself (POST /api/v1/tasks/<id>/tidy). Either way the original text stays verbatim at
# the top of the notes as "**Original (Name):** ...".
# 2.26.0 (#949): paused = the agent does not handle its events for now (text = the reason, shown to people: chip, chat,
# list); events keep queueing and are handled after it reports another status. Not the kill switch (enabled = 0).
AGENT_STATUSES = ("idle", "working", "waiting", "error", "paused")
AGENT_EVENTS = ("mention", "comment", "assigned", "unassigned", "chat", "reaction", "job", "tidy", "wake", "ping",
                "followup_due",  # 2.1.0 (#335): the follow-up day of a task waiting on external
                "job_request",   # 2.3.0 (#260-#263): a person asks for a proposal
                "runtime_changed", "reset",  # 2.4.1 (#377): an admin changed its runtime settings / pressed "Reset now"
                "work_style_changed",  # 2.236.0 (#2904-#2911): its owner changed how it works and reports (work_style)
                "rules_changed",  # 2.235.0 C (#2903): a person changed its standing rules (rules = the active ones)
                "data_lock_changed",  # 2.235.0 B (#2902): its owner changed what it may never see (data_lock)
                "control_changed", "approval_expired", "decision_undone",  # 2.235.0 A (#2891 #2901): its control level, an approval past its deadline, Undo
                "team_message",  # 2.17.0 (#419): someone @mentioned the agent in a list's team chat
                "task_added",  # 2.23.0 (#795): a task was created in / moved into a list shared with the agent
                "chat_choice",  # 2.28.0 (#1005): the person pressed an answer button of a chat message (message_id, choice_ids)
                "tasks_added",  # 2.29.0 (#1031): many tasks at once (a bulk move / import / script) -> ONE event with their ids
                "missed",  # 2.29.0 (#1031): events older than AGENT_EVENTS_STALE_H, folded into one summary at the next poll
                "stale_tasks",  # 2.34.0 (#266): once a day, the stale tasks of lists with "Agent follows up" on (bundled)
                "scheduled_job",  # 2.34.0 (#272): a planned job of a person is due (agents/schedules.py); answer in their chat
                "decision_added",  # 2.392.0 C (#3370): a decision was recorded on a task the agent sees with its comments
                "deployed",  # 2.60.0 (#1514): a version / milestone arrived in an environment (Staging, Live) of a list shared with the agent
                "task.completed",  # 2.392.0 B (#3364): the git poll completed a task because its package or code is released (via "release")
                "job_stalled", "branch_stranded",  # 2.392.2 (#3366): the watchdog: a running job without progress / a task's branch left without a merge
                "playbook_proposal",  # 2.39.0 (#1168): people applied / discarded the agent's proposed change of a list's Playbook
                "message_edited",  # 2.39.0 (#1179): a person changed a chat message / comment / team message the agent already had
                "file_shared",  # 2.48.0 (#1207): a folder / file of the file store was shared with the agent (node, role)
                "sheet_shared", "sheet_unshared",  # 2.465.0 (#2361): a table was shared with the agent (sheet, role) / that share ended (sheet id)
                "document_added",  # 2.48.0 (#1356): a new document was recognised in a folder / file shared with the agent
                "offer_accepted",  # 2.51.0 A (#1348): a quotation of its office area was accepted (agents with the office switch)
                "review_requested",  # 2.60.0 C (#1512): the agent is the reviewer of a task that went into review
                "sprint_started", "sprint_closed",  # 2.60.0 (#343): a sprint of a list shared with the agent started / was closed
                "chat_pinned",  # 2.62.0 (#1848): the person pinned / unpinned a message of its chat (message, pinned, user)
                "contract_notice",  # 2.70.0 C (#1359): a shared contract's last day to cancel is near (once; agents/contractprop.py)
                "abort",  # 2.144.0 A (#2412): the person pressed Stop in its chat (user, job_id?): end the running answer / the job's step
                "letter_draft_requested",  # 2.153.0 (#2031): an office admin asks the agent to draft an answer to a shared document
                "task_changed",  # 2.959.0 (#4030): a task assigned / delegated to the agent or watched by it changed: diff {field: {old, new}}
                )
JOB_STATES = ("running", "waiting", "done", "failed", "stopped")
JOB_ACTIONS = ("approve", "reject", "stop", "message")  # 2.56.0 (#1791): message = text to a running job, no state change
JOB_MESSAGE_MAX = 4000                                      # 2.56.0 (#1791): characters of a message to a job
REACTIONS = ("up", "down", "heart")   # the fixed set; any other single emoji is stored as itself
REACTION_ALIASES = {**{k: k for k in REACTIONS}, "+1": "up", "-1": "down", "\U0001f44d": "up", "\U0001f44e": "down",
                    "\u2764\ufe0f": "heart", "\u2764": "heart"}
TIDY_MODES = ("off", "suggest", "auto")
AGENT_EVENTS_KEEP_DAYS, AGENT_EVENTS_KEEP_MAX = 30, 1000   # per agent
# 2.29.0 (#1031): no backlog storm. Events older than this many hours reach a poller as one 'missed' summary (0 = off) ...
AGENT_EVENTS_STALE_H = _env_int("KALMIDO_AGENT_EVENTS_STALE_H", 48)
# ... and more than AGENT_BURST tasks added to one list by one person within AGENT_BURST_S become one 'tasks_added' event
# (sent after AGENT_BURST_QUIET_S without more); bulk-created tasks get no 'tidy' event beyond the first AGENT_BURST
AGENT_BURST, AGENT_BURST_S, AGENT_BURST_QUIET_S, AGENT_BURST_IDS = 5, 60, 15, 500
# 2.149.0 E (#2513): the two windows from the environment (tests shorten them instead of waiting a minute)
AGENT_BURST_S = _env_int("KALMIDO_AGENT_BURST_S", AGENT_BURST_S)
AGENT_BURST_QUIET_S = _env_int("KALMIDO_AGENT_BURST_QUIET_S", AGENT_BURST_QUIET_S, 0)
AGENT_JOBS_KEEP = 300                                       # per agent (finished ones beyond are removed)
JOB_LOG_MAX, JOB_TITLE_MAX, AGENT_NOTE_MAX, STATUS_TEXT_MAX = 8000, 200, 2000, 200
CHAT_MAX, CHAT_KEEP = 8000, 1000                            # characters per message, messages per person and agent
AGENT_WAIT_MAX = 60                                         # s: long-polling (GET /api/v1/agent/events?wait=)
AGENT_WAITERS_PER = 2                                       # concurrent long-polls per agent
AGENT_WAITERS_RESERVE, AGENT_WAITERS_MIN = 8, 6             # 2.391.0 A (#3360): threads kept free for normal requests; the least places
# ... on the whole server (each holds a server thread): the web threads less the reserve (at least 6, but never more than half
# of the threads: review S2, a small KALMIDO_THREADS keeps room for normal requests); KALMIDO_AGENT_WAITERS overrides
AGENT_WAITERS_ALL = _env_int("KALMIDO_AGENT_WAITERS", max(min(AGENT_WAITERS_MIN, WEB_THREADS // 2), WEB_THREADS - AGENT_WAITERS_RESERVE))
WAKE_LIMIT = 20                                             # wake requests per person within 10 minutes
AGENT_OFFLINE_S = 300                                       # 2.4.1 (#375): no event poll for this long = "offline"
AGENT_POLL_WRITE_S = 30                                     # ... the last poll is written at most this often
AGENT_TYPING_S = 10                                         # 2.4.1 (#375): a typing signal lasts this long
RUNTIME_MODEL_MAX = 100                                     # 2.4.1 (#377): characters of the model name
RUNTIME_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]*")
LTAG_MAX, LTAG_NAME_MAX = 100, 60                           # list tags per list, characters


def is_agent(u):
    try:
        return bool(u) and (u["kind"] or "user") == "agent"
    except (KeyError, IndexError):
        return False


def agent_row(c, aid):
    return c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE a.user_id=? AND u.kind='agent'""", (aid,)).fetchone() if aid else None


def agent_active(a):
    return bool(a) and bool(a["enabled"]) and not a["disabled"]


def agent_ids(c):
    return {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent'")}


def list_agents(c, lid):
    """Agent ids among the owner + members of list lid."""
    ag = agent_ids(c)
    return sorted(i for i in list_people(c, lid) if i in ag) if ag else []


def need_agent():
    """The current API user must be an agent (the agent endpoints); returns its id."""
    if not is_agent(g.user):
        raise Denied(403, tr("Only agent accounts can use this endpoint"))
    return g.user["id"]


def need_person(code=403, msg=None):
    """2.369.5 (#2517): the current user must be a person -- an agent gets Denied(code, msg) (the endpoints of people only)."""
    if is_agent(g.user):
        raise Denied(code, msg)


def lst_brief(c, lid):
    r = c.execute("SELECT id, name, is_inbox, agent_tidy, ptype FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return {"id": lid, "name": ""}
    return {"id": r["id"], "name": tr("Basket") if r["is_inbox"] and inbox_default(r["name"]) else r["name"], "agent_tidy": r["agent_tidy"] or "off",
            "tidy_agent_id": tidy_agent_of(c, lid),  # 2.4.1 (#379)
            # 2.30.0 (#1034): the list's project type and the agents that listen in (new / moved tasks, every comment)
            "project_type": r["ptype"] or None, "listen_agent_ids": listen_agents_of(c, lid)}


# ---- events: queue (polling) + webhook, long-polling wake-up
_AGENT_LOCK = threading.RLock()
_AGENT_COND = threading.Condition(_AGENT_LOCK)
_AGENT_GEN = [0]
_AGENT_WAITERS = {}
# 2.658.0 (#4193): one condition per agent with waiting long-polls (sharing _AGENT_LOCK): an event wakes only that agent's
# waiters (was notify_all: every waiting long-poll of every agent read the database again). A wake-up without agent ids
# (a lost bus signal, a caller that does not know them) still wakes all. Both dicts hold only agents with waiters
# (agents/api.py _waiter adds and drops them).
_AGENT_CONDS = {}
_AGENT_GENS = {}


def agent_wake_ids(d):
    """The agent ids of a wake-up (a list of ints) or None = all."""
    if not isinstance(d, list) or not d or not all(isinstance(x, int) and not isinstance(x, bool) for x in d):
        return None
    return d


def _agent_wake_here(d=None):
    ids = agent_wake_ids(d)
    with _AGENT_LOCK:
        if ids is None:
            _AGENT_GEN[0] += 1
            _AGENT_COND.notify_all()
            for cv in _AGENT_CONDS.values():
                cv.notify_all()
            return
        for aid in ids:
            if aid in _AGENT_CONDS:
                _AGENT_GENS[aid] = _AGENT_GENS.get(aid, 0) + 1
                _AGENT_CONDS[aid].notify_all()


def agent_notify(c=None, aids=None):
    """Wakes the agents' waiting long-polls (they look for new rows). 2.622.0 (#3891): in the other web processes too
    (core/pgbus.py). c: the events are still in that connection's transaction -- the others hear it with its commit.
    2.658.0 (#4193): aids = the agents with new events (only their long-polls wake up); None = all."""
    ids = sorted({int(x) for x in aids}) if aids else None
    _agent_wake_here(ids)
    bus_send("agents", ids, c=c)


bus_on("agents", _agent_wake_here)


@app.after_request
def agent_wakeup(resp):
    if has_request_context() and g.pop("agent_wake", False):
        agent_notify(aids=g.pop("agent_wake_ids", None))  # 2.658.0 (#4193): only the agents of this request's events
    return resp


@app.after_request
def agent_task_changed(resp):
    """2.959.0 (#4030): after a request that changed tasks, the event task_changed with the same diff as the webhook
    task.updated (tasks/validation.py log_changes collects it per request; integrations/webhooks.py wh_enqueue takes it
    later: Flask runs the after-request hooks backwards, so this one, registered after agent_wakeup and after the webhooks'
    wh_flush, runs before both and its events still wake the agents)."""
    d = g.get("wh_diff") if has_request_context() else None
    if d and resp.status_code < 400:
        try:
            c = db()
            with c.savepoint():  # a failure half way takes back the events already queued (all or none)
                n = agent_changed_events(c, d)
            if n:
                c.commit()
        except Exception as e:  # noqa: BLE001 - never fail a request that already succeeded (like wh_flush)
            with contextlib.suppress(Exception):
                db().heal()
            print("agents: task_changed failed:", type(e).__name__, e, flush=True)
    return resp


def agent_changed_events(c, diffs):
    """2.959.0 (#4030): task_changed to the agents a changed task is assigned or delegated to or that watch it, each with the
    diff as it may see it (wh_diff_out: never a text of a project encrypted in the browser, the old project only when it sees
    it). Not for a change of its own, not for its own (un)assignment (that is assigned / unassigned), not while its work style
    switches task_changed off. Returns the number of events."""
    ag = agent_ids(c)
    if not ag:
        return 0
    from .workstyle import ws_get  # loaded after this module
    n, styles, sent = 0, {}, {}
    actor = wh_actor(c) if getattr(g, "user", None) else None  # review F3: its own change is skipped before the data is built
    for tid, d in sorted(diffs.items()):
        row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            continue
        watch = wat_users(c, tid)
        dlg0 = (g.get("agent_dlg0") or {}).get(tid, row["delegate_agent_id"])  # the delegate before this request
        lo = d.get("list_id")
        for aid in sorted(({row["assignee_id"], row["delegate_agent_id"]} | watch) & ag):
            if (actor and actor["id"] == aid) or sent.get(aid, 0) >= AGENT_CHANGED_MAX:
                continue  # review F2: a bulk change brings an agent at most AGENT_CHANGED_MAX of them (its queue keeps the rest)
            if aid in (d.get("assignee_id") or ()) or (aid == row["delegate_agent_id"] and aid != dlg0):
                continue  # assigned / delegated to it (or taken away) in this request: its event assigned / unassigned says it
            if aid not in styles:
                a = agent_row(c, aid)
                styles[aid] = bool(a and ws_get(a).get("task_changed"))
            if not styles[aid] or not task_visible(c, tid, aid, full=True):
                continue
            dv = wh_diff_out(c, d, aid, row)
            if lo and lo[0] and lo[0] != lo[1] and not _agent_sees_list(c, aid, lo[0]):
                dv = {k: {**v, "old": None} for k, v in dv.items()}  # nothing of the time in a project out of its reach
            if not dv:
                continue
            extra = {"diff": dv, "assigned": aid in (row["assignee_id"], row["delegate_agent_id"]), "watching": aid in watch}
            if agent_emit(c, aid, "task_changed", agent_task_data(c, tid, aid, full=True, **extra)):
                n += 1
                sent[aid] = sent.get(aid, 0) + 1
    return n


AGENT_CHANGED_MAX = 50  # 2.959.0 (#4030, review F2): task_changed per agent and request (a bulk change of hundreds of tasks)


def _agent_sees_list(c, aid, lid):
    """2.959.0 (#4030): list lid is in agent aid's reach: a member, not a list that never reaches an agent, inside its
    list_ids limit and outside its data lock (the rules of agent_emit)."""
    if not list_role(c, lid, aid) or agent_never_lids(c, [lid]) or dl_list_locked(c, aid, lid):
        return False
    a = agent_row(c, aid)
    if a and a["list_ids"]:
        from ..agents.safety import ids_parse
        return lid in ids_parse(a["list_ids"])
    return True


def wh_queue_raw(c, w, env):
    """Queues an agent event for the agent's webhook: the delivery id is the event id, the body the event envelope."""
    if c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (w["id"],)).fetchone()[0] >= WH_QUEUE_MAX:
        wh_log(c, w["id"], env["id"], env["event"], 0, False, None, "dropped", 0)
        return
    c.execute("INSERT INTO webhook_queue(webhook_id,delivery,event,payload,attempt,next_at,created_at) VALUES(?,?,?,?,0,?,?)",
              (w["id"], env["id"], env["event"], json.dumps({**env, "webhook_id": w["id"]}, ensure_ascii=False), time.time(), iso(now_utc())))


def agent_never_sql(a="l"):
    """2.582.0 (#4380): THE condition "a list nothing of which ever reaches an agent" on lists alias a: health, budget, the
    list lock (e2e), an organisation's trip, read later (agent_emit's rule, also for what a person hands over in a proposal)."""
    return f"(COALESCE({a}.life, '') IN ('health', 'budget') OR {a}.e2e IS NOT NULL OR {org_trip_sql(a + '.')} OR {reading_sql(a)})"


def agent_never_lids(c, lids):
    """2.582.0 (#4380, audit #2483 M4): the ids among lids that never reach an agent (agent_never_sql)."""
    ids = sorted({int(x) for x in lids if x})
    if not ids:
        return set()
    return {r[0] for r in c.execute(f"SELECT l.id FROM lists l WHERE l.id IN ({','.join('?' * len(ids))}) AND {agent_never_sql()}", ids)}


def agent_emit(c, aid, event, data, actor="auto", via=None):
    """Records an event for agent aid (the polling queue) and queues its webhook delivery; the caller commits. Nothing for a
    paused / disabled agent or for the agent's own actions. Returns the event's seq or None."""
    a = agent_row(c, aid)
    if not agent_active(a):
        return None
    lid = None
    if isinstance(data, dict):  # 2.22.0 (#663): nothing of a health list ever reaches an agent
        lid = data.get("list_id") or (data.get("task") or {}).get("list_id") or (data.get("list") or {}).get("id") \
            or (data.get("room") or {}).get("list_id")
        if lid and c.execute(f"SELECT 1 FROM lists l WHERE l.id=? AND {agent_never_sql()}", (lid,)).fetchone():  # 2.582.0 (#4380): one rule
            return None  # 2.64.1 B (#1817): nor of a list with the lock; 2.72.0 (#1333): nor of a budget; 2.173.1 A (#2714): nor of an organisation's trip; 2.172.1 (#2689): nor read later
        if lid and a["list_ids"]:  # 2.30.0 (#919): an agent limited to selected lists hears nothing of the others
            from ..agents.safety import ids_parse
            if lid not in ids_parse(a["list_ids"]):
                return None
        if lid and dl_list_locked(c, aid, lid):
            return None  # 2.235.0 B (#2902): nothing of a list its data lock leaves out (tasks: acx_task_ok below)
        tk = data.get("task") if isinstance(data.get("task"), dict) else {}
        etid = tk.get("id") or data.get("task_id")
        ids_only = event == "unassigned" and set(tk) <= {"id", "list_id"}  # agent_assign_event: ids, no content
        if isinstance(etid, int) and not ids_only and not acx_task_ok(c, etid, aid):  # 2.36.2 (#1142): requires task visibility
            return None
    if actor == "auto":
        actor = wh_actor(c) if has_request_context() and getattr(g, "user", None) else None
    if actor and actor.get("id") == aid:
        return None
    # 2.26.0 (#928): who may address the agent. Another agent's actions reach it only in lists with "Agents may address
    # each other" on (any event); a person's mention / comment / assignment / reaction / team chat / nudge only where the
    # agent is open to them (agent_usable: the list's owner / admins, everyone with "Members may see and use the agent").
    if actor and lid and event not in AGENT_UNGATED:
        if actor.get("kind") == "agent" or event in AGENT_GATED:
            if not agent_usable(c, aid, actor["id"], lid):
                return None
    if lid and isinstance(lid, int) and "playbook" not in data:  # 2.39.0 (#1168): the list's effective Playbook comes along
        from ..lists.playbook import pb_event, pb_for_agent
        pb = pb_event(c, lid)
        if pb:
            data = {**data, "playbook": pb_for_agent(c, pb, aid)}  # 2.126.0 B (#1978): with its authors
    ev, ts = str(uuid.uuid4()), iso(now_utc())
    via = via or ((act_via() or "web") if has_request_context() else "web")  # 2.392.0 B (#3364): via "release"
    seq = insert_id(c, "INSERT INTO agent_events(agent_id,uuid,event,payload,created_at) VALUES(?,?,?,'{}',?)", (aid, ev, event, ts))
    env = {"id": ev, "seq": seq, "event": event, "created_at": ts, "agent_id": aid, "actor": actor, "via": via, "data": data}
    c.execute("UPDATE agent_events SET payload=? WHERE id=?", (json.dumps(env, ensure_ascii=False), seq))
    if a["webhook_id"] and WH_ON:
        w = c.execute("SELECT * FROM webhooks WHERE id=? AND enabled=1", (a["webhook_id"],)).fetchone()
        if w:
            wh_queue_raw(c, w, env)
    if (a["provider"] or "") == "kalmido-server":  # 2.557.0 B (#4670): Kalmido runs the model itself (agents/srvagent.py)
        from ..agents.srvagent import srv_event
        srv_event(c, a, event, actor)
    c.execute("""DELETE FROM agent_events WHERE agent_id=? AND (created_at<? OR id<=(SELECT id FROM agent_events WHERE agent_id=?
                 ORDER BY id DESC LIMIT 1 OFFSET ?))""",
              (aid, iso(now_utc() - timedelta(days=AGENT_EVENTS_KEEP_DAYS)), aid, AGENT_EVENTS_KEEP_MAX))
    if has_request_context():
        g.agent_wake = True
        g.setdefault("agent_wake_ids", set()).add(int(aid))  # 2.658.0 (#4193)
    else:
        agent_notify(c, [aid])  # 2.622.0 (#3891): the other processes hear it with the caller's commit
    return seq


AGENT_EVENT_COMMENTS = 20     # 2.0.8 (#333): newest comments of the task inside a task event
AGENT_EVENT_COMMENT_CHARS = 2000


def list_sections(c, uid, lid):
    """[{id, name, section_kind}] of list lid as uid sees it (participants: only sections with a task of theirs), in their order."""
    return [{"id": r["id"], "name": r["name"], "section_kind": r["kind"] or None} for r in visible_sections(c, uid) if r["list_id"] == lid]  # 2.577.0 (#3354)


def agent_event_comments(c, tid):
    """The newest AGENT_EVENT_COMMENTS comments of a task, oldest first, text shortened to AGENT_EVENT_COMMENT_CHARS."""
    rows = c.execute(f"SELECT {ocm_old_cols()} FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL ORDER BY id DESC LIMIT ?",
                     (tid, AGENT_EVENT_COMMENTS)).fetchall()[::-1]
    names = user_names(c, [r["user_id"] for r in rows])
    ag = agent_ids(c)
    nat = {r[0]: r[1] for r in c.execute("SELECT comment_id, COUNT(*) FROM attachments WHERE task_id=? AND comment_id IS NOT NULL AND deleted_at IS NULL "
                                         "GROUP BY comment_id", (tid,))}
    out = []
    for r in rows:
        txt = comment_plain(c, r["body"])
        d = {"id": r["id"], "author": {"id": r["user_id"], "name": names.get(r["user_id"], ""), "agent": r["user_id"] in ag},
             "text": txt[:AGENT_EVENT_COMMENT_CHARS], "created_at": r["created_at"], "edited_at": r["edited_at"],
             "attachments": nat.get(r["id"], 0)}
        if len(txt) > AGENT_EVENT_COMMENT_CHARS:
            d["truncated"] = True
        if r["ext_name"] and r["source"] == "git":  # review 2.981 (Fable F5): synced from the git host (#5274), no customer
            d["author"].update(name=r["ext_name"], source="git")
        elif r["ext_name"]:  # 2.50.0 (#329): a customer's comment through the public link (no account, the name they typed)
            d["author"].update(name=r["ext_name"], customer=True)
        if "portal" in r.keys() and r["portal"]:  # 2.63.0 B (#1513): the customer of a customer report sees it
            d["portal"] = True
        if r["suggestion"]:
            d["suggestion"] = json.loads(r["suggestion"])
        out.append(d)
    return out


def agent_task_data(c, tid, aid, full=None, **extra):
    """The task part of a task event. 2.0.8 (#333): the task carries its newest comments ("comments", oldest first, at
    most AGENT_EVENT_COMMENTS, "comments_total") and the list its sections and agent_tidy mode, so the agent needs no
    get_task / list_lists round trip. Only while the agent sees the task with its comments (full=None: checked here)."""
    from ..integrations.git import git_repo_for_task
    row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    task, lst = task_for(c, row, aid), lst_brief(c, row["list_id"])
    from ..tasks.snippets import snip_event, snip_parse  # 2.35.0 (#1095): a shortened copy (full code: get_task)
    task["snippets"], task["snippets_total"] = snip_event(row["snippets"]), len(snip_parse(row["snippets"]))
    from ..tasks.related import rt9_event  # 2.59.0 B (#1375): the related tasks the agent sees (cache only; none without a vector)
    rel = rt9_event(c, tid, aid)
    if rel is not None:
        task["related"] = rel
    if full is None:
        full = task_visible(c, tid, aid, full=True)
    if full:
        task["comments"] = agent_event_comments(c, tid)
        task["comments_total"] = c.execute("SELECT COUNT(*) FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL", (tid,)).fetchone()[0]
        task["decisions"] = dec_list(c, tid, current=True)  # 2.392.0 C (#3370): those in force
        lst["sections"] = list_sections(c, aid, row["list_id"])
        rp = git_repo_for_task(c, row, aid)  # 2.2.0 (#339): the repository to work in, a branch name, the linked code (2.396.0 A #3386: its git author)
        if rp:
            return {"task": task, "list": lst, "repo": rp, **extra}
    return {"task": task, "list": lst, **extra}


def agent_comment(c, k):
    rt, rq = reply_of(c, "c", k)  # 2.33.0 (#1076): the comment answers this one (a short quote)
    return {"id": k["id"], "author_id": k["user_id"], "text": comment_plain(c, k["body"]), "body": k["body"], "created_at": k["created_at"],
            "suggestion": json.loads(k["suggestion"]) if k["suggestion"] else None, "reply_to": rt, "reply": rq,
            # 2.63.0 B (#1513): portal = the customer sees it (a public answer, or the customer's own: author_id null + ext_name)
            "portal": bool(k["portal"]) if "portal" in k.keys() else False,
            **({"ext_name": k["ext_name"]} if "ext_name" in k.keys() and k["ext_name"] else {}),
            **_lv_comment_choices(k)}


def _lv_comment_choices(k):
    """2.41.0 (#1383): the answer buttons / approval card of the comment and the person's answer (only when it has them)."""
    from ..collab.cchoice import lv_jload
    ch = lv_jload(k["choices"]) if "choices" in k.keys() else None
    return {"choices": ch, "choice": lv_jload(k["choice"])} if ch else {}


def agent_comment_events(c, t, cid, mentions, new_mentions, created=True):
    """Comment on task t: 'mention' to newly mentioned agents, 'comment' to agents that follow the task (assignee, delegated
    agent, creator, watchers, earlier commenters). Only agents that see the task with its comments."""
    ag = agent_ids(c)
    if not ag:
        return
    k = c.execute(f"SELECT {ocm_old_cols()} FROM obj_comments WHERE id=? AND kind='task'", (cid,)).fetchone()  # 2.972.0 (#5272): the old keys
    follow = {t["assignee_id"], t["created_by"], t["delegate_agent_id"]} | wat_users(c, t["id"]) | {r[0] for r in c.execute(
        "SELECT DISTINCT user_id FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL AND id!=?", (t["id"], cid))}  # 2.473.0 (#3357): + delegated, watchers
    # 2.13.1 (#471): agents set to read every comment of a person in this list ("Agent reads every comment")
    listen = set(listen_agents_of(c, t["list_id"])) if created and k["user_id"] not in ag else set()
    for aid in sorted(ag):
        if aid in new_mentions:
            ev = "mention"
        elif created and (aid in follow or aid in listen) and aid not in mentions:
            ev = "comment"
        else:
            continue
        if not task_visible(c, t["id"], aid, full=True):
            continue
        agent_emit(c, aid, ev, agent_task_data(c, t["id"], aid, comment=agent_comment(c, k), **({"where": "comment"} if ev == "mention" else {})))


def agent_text_mentions(c, lid, text):
    """Agents of list lid named as @username or @display name in text (task title / notes)."""
    if not text or "@" not in text:
        return set()
    out = set()
    low = text.casefold()
    for aid in list_agents(c, lid):
        u = c.execute("SELECT username, display_name FROM users WHERE id=?", (aid,)).fetchone()
        for n in {u["username"], u["display_name"] or ""}:
            n = n.strip().casefold()
            if n and re.search(r"(?<![\w@])@" + re.escape(n) + r"(?![\w-])", low):
                out.add(aid)
    return out


def agent_task_mentions(c, tid, old_text=""):
    """@agent in a task's title / notes (new mentions only) -> 'mention' events (where: task)."""
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        return
    new = agent_text_mentions(c, t["list_id"], (t["title"] or "") + "\n" + (t["content"] or "")) - \
        agent_text_mentions(c, t["list_id"], old_text)
    for aid in sorted(new):
        if task_visible(c, tid, aid, full=True):
            agent_emit(c, aid, "mention", agent_task_data(c, tid, aid, comment=None, where="task"))


def agent_assign_event(c, tid, kind, uid, delegated=False):
    """2.473.0 (#3357): delegated = the task is delegated to the agent (tasks.delegate_agent_id), the person stays assignee."""
    if not uid or uid not in agent_ids(c):
        return
    if task_visible(c, tid, uid, full=True):
        extra = {"delegated": True} if delegated else {}
        if kind == "assigned":  # 2.236.0 C (#2906 #2907): its place in the queue + the priority rule for choosing the next task
            from .workqueue import wq_event_extra
            extra.update(wq_event_extra(c, uid, tid))
        agent_emit(c, uid, kind, agent_task_data(c, tid, uid, **extra))
    elif kind == "unassigned":  # 2.36.2 (#1142): out of sight -> only the ids (the agent can drop the task), no content
        r = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
        if r:
            agent_emit(c, uid, kind, {"task": {"id": tid, "list_id": r[0]}, "list": {"id": r[0]}, "visible": False, **({"delegated": True} if delegated else {})})


# 2.30.0 (#1034): an agent of a list either LISTENS IN (it gets every task created in or moved into the list -- task_added /
# tasks_added -- and every comment a person writes there) or is reached only by an @mention, an assignment or a wake.
# Default by project type: "Software / AI development" lists listen, all others not. lists.agent_listen keeps the choices
# that differ from that default: "" / NULL = the default for every agent; "*" / "-*" = every agent on / off (the folder
# setting); "3" / "-3" = this agent on / off (the list's own switch). A newly connected agent follows the default (or "*"),
# a change of the project type starts over with the new type's default. Tidying (agent_tidy) is a separate switch.
LISTEN_DEFAULT_PTYPES = ("software",)


def listen_default(ptype):
    return (ptype or "") in LISTEN_DEFAULT_PTYPES


def listen_ids(raw, ptype, agents):
    """lists.agent_listen + the project type -> the listening agent ids (sorted) among `agents` (the list's agents)."""
    dflt, own = listen_default(ptype), {}
    for x in str(raw or "").split(","):
        x = x.strip()
        if x in ("*", "-*"):
            dflt = x == "*"
        elif x.lstrip("-").isdigit():
            own[int(x.lstrip("-"))] = not x.startswith("-")
    return sorted(i for i in agents if own.get(i, dflt))


def listen_agents_of(c, lid):
    r = c.execute("SELECT agent_listen, ptype FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return []
    return listen_ids(r["agent_listen"], r["ptype"], set(list_agents(c, lid)))


def listen_store(c, lid, on_ids, agents):
    """Stores the listening agents of list lid explicitly per agent (the list's own switch): on_ids on, the other agents off."""
    keep = [x.strip() for x in str(c.execute("SELECT agent_listen FROM lists WHERE id=?", (lid,)).fetchone()[0] or "").split(",")
            if x.strip() in ("*", "-*")]
    own = [str(a) if a in on_ids else f"-{a}" for a in sorted(agents)]
    c.execute("UPDATE lists SET agent_listen=? WHERE id=?", (",".join(keep + own), lid))


def listen_set_all(c, lid, on):
    """The folder setting "Agent listens in": every agent of list lid on / off (None = back to the project type's default)."""
    c.execute("UPDATE lists SET agent_listen=? WHERE id=?", (None if on is None else ("*" if on else "-*"), lid))


def list_listen_update(c, lid, ids):
    """2.13.1 (#471): "Agent reads every comment" -- 2.30.0 (#1034): "Agent listens in". Owner / list admins (agent-owned list:
    its members with edit rights); never an agent. ids: agents of the list ([] = nobody)."""
    if not isinstance(ids, list) or len(ids) > 50 or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "listen_agent_ids"))
    role = need_list(c, lid, write=False)
    owner = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if is_agent(g.user) or not (role in MANAGE_ROLES or (owner in agent_ids(c) and role in WRITE_ROLES)):
        raise Denied(403, tr("Only the project owner or a project admin can change this"))
    ags = set(list_agents(c, lid))
    bad = [x for x in ids if x not in ags]
    if bad:
        raise BadInput(tr("This agent is not in the project"))
    listen_store(c, lid, set(ids), ags)


def listen_migrate(c):
    """2.30.0 (#1034), once: the meaning of lists.agent_listen changed (see listen_ids). Every list keeps exactly the agents
    that listened before: an explicit choice is written per agent; a list on the old default (the tidy agent while tidying
    was on) gets that agent written, except software lists, which take the new default (every agent of the list listens in)."""
    n = 0
    for r in c.execute("SELECT id, agent_listen, agent_tidy, ptype FROM lists").fetchall():
        ags = set(list_agents(c, r["id"]))
        if r["agent_listen"] is None:
            if listen_default(r["ptype"]):
                continue
            tid = tidy_agent_of(c, r["id"]) if (r["agent_tidy"] or "off") != "off" else None
            on = {tid} if tid in ags else set()
        else:
            on = {int(x) for x in str(r["agent_listen"]).split(",") if x.strip().isdigit()} & ags
        val = ",".join(str(a) if a in on else f"-{a}" for a in sorted(ags))
        if val != (r["agent_listen"] or ""):
            c.execute("UPDATE lists SET agent_listen=? WHERE id=?", (val or None, r["id"]))
            n += 1
    return n


def list_agent_access_update(c, lid, b):
    """2.26.0 (#928): "Members may see and use the agent" (agent_members) / "Agents may address each other" (agent_peers):
    the list's owner or a list admin (a list that belongs to an agent: its members with edit rights); never an agent."""
    role = need_list(c, lid, write=False)
    owner = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if is_agent(g.user) or not (role in MANAGE_ROLES or (owner in agent_ids(c) and role in WRITE_ROLES)):
        raise Denied(403, tr("Only the project owner or a project admin can change this"))
    for k in ("agent_members",):  # 2.40.0 (#1373): agent_peers is ignored (fixed off)
        if k in b:
            if not isinstance(b[k], bool) and b[k] not in (0, 1):
                raise BadInput(tr("Invalid value: {0}", k))
            c.execute(f"UPDATE lists SET {k}=? WHERE id=?", (int(bool(b[k])), lid))


def tidy_candidates(c, lid):
    """2.4.1 (#379): agents of list lid that may tidy it up (owner / list admin / edit rights; participants and viewers
    cannot change other people's tasks)."""
    return [a for a in list_agents(c, lid) if list_role(c, lid, a) in WRITE_ROLES]


def tidy_agent_of(c, lid, cands=None):
    """2.4.1 (#379): the ONE agent that tidies up list lid: the chosen one (lists.tidy_agent) while it still may, else the
    first candidate; None without one."""
    cands = tidy_candidates(c, lid) if cands is None else cands
    r = c.execute("SELECT tidy_agent FROM lists WHERE id=?", (lid,)).fetchone()
    if r and r[0] in cands:
        return r[0]
    return cands[0] if cands else None


_BURST, _BURST_LOCK = {}, threading.Lock()


def _burst_actor():
    return wh_actor(None) if has_request_context() and getattr(g, "user", None) else None


def burst_hit(kind, lid):
    """2.29.0 (#1031): True when the current person already did AGENT_BURST `kind` things (task_added / tidy) in list lid within
    AGENT_BURST_S -- the caller folds this one into a summary (or drops a tidy). Outside a request: never a burst."""
    a = _burst_actor()
    if not a:
        return False
    key, now = (kind, a["id"], lid), time.monotonic()
    with _BURST_LOCK:
        ts = [t for t in _BURST.get(key, ()) if now - t < AGENT_BURST_S]
        ts.append(now)
        _BURST[key] = ts[-(AGENT_BURST + 1):]
        if len(_BURST) > 2000:
            for k in [k for k, v in _BURST.items() if now - v[-1] >= AGENT_BURST_S]:
                _BURST.pop(k, None)
        n = len(ts)
    if bus_active():  # 2.622.0 (#3891): several processes count together (core/ephem.py); this process's own count is the floor
        shared = eph_add("burst", f"{kind}:{a['id']}:{lid}", 1, AGENT_BURST_S)
        n = max(n, shared or 0)
    return n > AGENT_BURST


def _burst_hold(c, lid, tid, how, from_lid, source):
    """2.465.0 (#3892): one row per task in the table, the caller commits it with the task: with KALMIDO_ROLE=web the watchdog
    (burst_tick) is another process, a burst held in this process's memory never reached it."""
    a = _burst_actor()
    c.execute("INSERT INTO agent_burst_held(actor_id,list_id,task_id,how,from_list,source,held_at) VALUES(?,?,?,?,?,?,?)",
              (a["id"], lid, tid, how, from_lid, source or "", iso_ms(now_utc())))


def burst_tick(c):
    """Watchdog: one 'tasks_added' per agent of the list for every burst that has been quiet for AGENT_BURST_QUIET_S.
    2.465.0 (#3892): DELETE ... RETURNING takes a burst once; a failure before the commit leaves it held for the next tick."""
    cut = iso_ms(now_utc() - timedelta(seconds=AGENT_BURST_QUIET_S))
    ready = c.execute("SELECT actor_id, list_id FROM agent_burst_held GROUP BY actor_id, list_id HAVING MAX(held_at)<=?", (cut,)).fetchall()
    sent = 0
    for actor_id, lid in ready:
        held = c.execute("DELETE FROM agent_burst_held WHERE actor_id=? AND list_id=? RETURNING id, task_id, how, from_list, source",
                         (actor_id, lid)).fetchall()
        held.sort(key=lambda r: r["id"])
        tids = list(dict.fromkeys(r["task_id"] for r in held))
        how = {r["how"] for r in held}
        sources = sorted({r["source"] for r in held if r["source"]})
        froms = sorted({r["from_list"] for r in held if r["from_list"]})
        kept = tids[:AGENT_BURST_IDS]
        ids = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE list_id=? AND deleted_at IS NULL AND id IN ({','.join('?' * len(kept))})",
                                       (lid, *kept))] if kept else []
        u = c.execute("SELECT id, display_name, username, kind FROM users WHERE id=?", (actor_id,)).fetchone()
        actor = {"id": u["id"], "name": u["display_name"] or u["username"], "kind": "agent" if u["kind"] == "agent" else "person"}
        listen = set(listen_agents_of(c, lid))  # 2.30.0 (#1034): only agents that listen in
        for aid in list_agents(c, lid):
            if aid not in listen:
                continue
            mine = [t for t in ids if task_visible(c, t, aid, full=True)]
            if not mine:
                continue
            data = {"list": lst_brief(c, lid), "list_id": lid, "task_ids": mine, "count": len(mine),
                    "how": "moved" if how == {"moved"} else ("created" if how == {"created"} else "mixed"),
                    "truncated": len(tids) > len(kept)}
            if sources:
                data["source"] = sources[0]
            moved_from = [{"id": f, "name": lst_brief(c, f)["name"]} for f in froms if list_role(c, f, aid)]
            if moved_from:
                data["moved_from"] = moved_from
            if agent_emit(c, aid, "tasks_added", data, actor=actor):
                sent += 1
    c.commit()
    return sent


def agent_added_events(c, tid, from_lid=None, source=None, info=None):
    """2.23.0 (#795): a top-level task was created in (from_lid None) or moved into (from_lid = the list it came from) a list:
    'task_added' to every agent of that list that sees the task (the agent's own actions excluded by agent_emit). moved_from
    {id, name} only when the agent may see the list it came from; source: 'form' / 'mail' / 'errors' / 'capture' ...
    2.30.0 (#1034): only to the agents that listen in (listen_agents_of; software lists by default); a moved task also gets
    the list's tidy event (a created one gets it from agent_tidy_events at its creation)."""
    ag = agent_ids(c)
    if not ag:
        return
    t = c.execute("SELECT id, list_id, parent_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["parent_id"] or t["deleted_at"] or t["list_id"] == from_lid:
        return
    if not list_agents(c, t["list_id"]):
        return
    if from_lid:
        agent_tidy_events(c, tid, moved=True)
    listen = set(listen_agents_of(c, t["list_id"]))
    if not listen:
        return
    if burst_hit("added", t["list_id"]):  # 2.29.0 (#1031): a bulk move / script -> one 'tasks_added' later (burst_tick)
        _burst_hold(c, t["list_id"], tid, "moved" if from_lid else "created", from_lid, source)
        return
    for aid in list_agents(c, t["list_id"]):
        if aid not in listen or not task_visible(c, tid, aid, full=True):
            continue
        extra = {"how": "moved" if from_lid else "created"}
        if from_lid and list_role(c, from_lid, aid):
            extra["moved_from"] = {"id": from_lid, "name": lst_brief(c, from_lid)["name"]}
        if source:
            extra["source"] = source
            if source in ("mail", "form", "errors"):  # 2.126.0 B (#1978): text from outside Kalmido
                extra.update(origin=source, untrusted=True)
        extra.update(info or {})  # 2.63.0 (#1513): a form's report: portal, ttype
        agent_emit(c, aid, "task_added", agent_task_data(c, tid, aid, **extra))


# 2.27.0 (#999): tidying never runs into someone's typing. A new task's 'tidy' event waits (tidy_pending) until nobody has
# changed the task for TIDY_QUIET_S and nobody has it open in a field (the client's "editing" signal, task_editing_set);
# the watchdog sends it then (tidy_tick). An agent's tidy is refused (409) when people changed the task after the event,
# or while someone edits it; the original text always stays (tidy_apply).
TIDY_QUIET_S = int(os.environ.get("KALMIDO_TIDY_QUIET_S", "120"))
TASK_EDIT_S = 45
_TEDIT, _TEDIT_LOCK = {}, threading.Lock()


def task_editing_set(c, tid, uid):
    need_task(c, tid, write=False)
    now = time.time()
    with _TEDIT_LOCK:
        for k in [k for k, v in _TEDIT.items() if v <= now]:
            _TEDIT.pop(k, None)
        if len(_TEDIT) < 5000:
            _TEDIT[tid] = now + TASK_EDIT_S
    bus_send("tedit", int(tid))  # 2.622.0 (#3891): the tidy in another process waits for it too
    return {"ok": True, "seconds": TASK_EDIT_S}


def _tedit_heard(tid):
    if isinstance(tid, int):
        with _TEDIT_LOCK:
            if len(_TEDIT) < 5000:
                _TEDIT[tid] = time.time() + TASK_EDIT_S


bus_on("tedit", _tedit_heard)


def task_being_edited(tid):
    with _TEDIT_LOCK:
        return _TEDIT.get(tid, 0) > time.time()


def agent_tidy_events(c, tid, moved=False):
    """A new top-level task by a person in a list with tidy on: 'tidy' to the list's tidy agent (2.4.1: only that one),
    2.27.0 (#999): once the task is left alone (tidy_tick). 2.30.0 (#1034): also a task a person moved into the list (moved)."""
    t = c.execute("SELECT t.*, l.agent_tidy FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    if not t or t["parent_id"] or (t["agent_tidy"] or "off") == "off" or not has_request_context() or is_agent(g.user):
        return
    aid = tidy_agent_of(c, t["list_id"])
    # 2.29.0 (#1031): tasks created in bulk through the API (a script, an import) are not tidied one by one; typing in the app
    # (a quick brain dump) still gets every tidy event. 2.30.0: a bulk move (also in the app) neither
    if aid and (act_via() == "api" or moved) and burst_hit("tidy", t["list_id"]):
        return
    if aid and task_visible(c, tid, aid, write=True):
        if TIDY_QUIET_S <= 0:  # KALMIDO_TIDY_QUIET_S=0: at once, as before 2.27 (the older test suites)
            agent_emit(c, aid, "tidy", agent_task_data(c, tid, aid, mode=t["agent_tidy"]))
            c.execute("INSERT INTO tidy_pending(task_id,actor_id,created_at,sent_at) VALUES(?,?,?,?) ON CONFLICT (task_id) DO UPDATE SET actor_id=excluded.actor_id, created_at=excluded.created_at, sent_at=excluded.sent_at", (tid, g.user["id"], iso(now_utc()), iso(now_utc())))
            return
        c.execute("INSERT INTO tidy_pending(task_id,actor_id,created_at,sent_at) VALUES(?,?,?,NULL) ON CONFLICT (task_id) DO UPDATE SET actor_id=excluded.actor_id, created_at=excluded.created_at, sent_at=NULL", (tid, g.user["id"], iso(now_utc())))


def tidy_changed_since(updated_at, sent_at):
    """2.308.0 (#3274): did people change the task after its tidy event went out? Times are whole seconds. The watchdog only
    sends once updated_at is TIDY_QUIET_S (>= 1) old, so an updated_at in the event's own second is a later change; with
    KALMIDO_TIDY_QUIET_S=0 the event goes out in the second the task was made, so only a later second counts."""
    u = updated_at or ""
    return u >= sent_at if TIDY_QUIET_S > 0 else u > sent_at


def tidy_tick(c):
    """Watchdog: sends the waiting 'tidy' events of tasks nobody touched for TIDY_QUIET_S and nobody edits right now."""
    now = now_utc()
    quiet = iso(now - timedelta(seconds=TIDY_QUIET_S))
    c.execute("DELETE FROM tidy_pending WHERE sent_at IS NOT NULL AND sent_at<?", (iso(now - timedelta(days=2)),))
    # people changed the task after its event went out (the agent's tidy is refused then): it waits for quiet again and
    # gets a new event, so an agent is never stuck on "try again later"
    c.execute("""UPDATE tidy_pending SET sent_at=NULL, created_at=? WHERE sent_at IS NOT NULL
                 AND (SELECT updated_at FROM tasks WHERE id=tidy_pending.task_id) %s sent_at
                 AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.task_id=tidy_pending.task_id AND a.kind='tidy' AND a.created_at>=tidy_pending.sent_at)
                 AND NOT EXISTS (SELECT 1 FROM obj_comments k WHERE k.kind='task' AND k.ref_id=tidy_pending.task_id AND COALESCE(k.extra->>'suggestion','')!=''
                                 AND k.created_at>=tidy_pending.sent_at::timestamptz)""" % (">=" if TIDY_QUIET_S > 0 else ">"),  # 2.308.0 (#3274): as tidy_changed_since
              (iso(now),))
    rows = c.execute("""SELECT p.*, t.updated_at, t.deleted_at, t.list_id, l.agent_tidy FROM tidy_pending p JOIN tasks t ON t.id=p.task_id
                        JOIN lists l ON l.id=t.list_id WHERE p.sent_at IS NULL ORDER BY p.created_at LIMIT 50""").fetchall()
    sent = 0
    for r in rows:
        if r["deleted_at"] or (r["agent_tidy"] or "off") == "off":
            c.execute("DELETE FROM tidy_pending WHERE task_id=?", (r["task_id"],))
            continue
        if max(r["updated_at"] or "", r["created_at"]) > quiet or task_being_edited(r["task_id"]):
            continue
        aid = tidy_agent_of(c, r["list_id"])
        if aid and task_visible(c, r["task_id"], aid, write=True):
            u = c.execute("SELECT id, username, display_name, kind FROM users WHERE id=?", (r["actor_id"],)).fetchone() if r["actor_id"] else None
            actor = {"id": u["id"], "name": u["display_name"] or u["username"], "kind": "agent" if u["kind"] == "agent" else "person"} if u else None
            agent_emit(c, aid, "tidy", agent_task_data(c, r["task_id"], aid, mode=r["agent_tidy"]), actor=actor)
            sent += 1
        c.execute("UPDATE tidy_pending SET sent_at=? WHERE task_id=?", (iso(now), r["task_id"]))
    c.commit()  # never leave the watchdog's connection holding a write transaction
    return sent


# ---- 2.4.1 (#377): runtime settings of an agent. Kalmido never runs the agent: it stores what an admin wants (model,
# auto-compact, a nightly fresh restart) and hands it to the agent (GET /api/v1/agent "runtime", event runtime_changed);
# the host's launcher applies it (docs/AGENTS.md "Runtime settings", mcp/agent_launcher.sh). "Reset now" raises reset_seq
# and sends the event reset: the host restarts the agent with a fresh session.
RUNTIME_DEFAULTS = {"model": "", "autocompact": True, "autocompact_pct": None, "nightly_reset": "", "permission_mode": "",
                    "rotate_size": "medium", "rotate_runs": 60, "rotate_idle_min": 45,
                    "perm_user": None,  # 2.312.0 D (#3266): who answers a team agent's permission questions (None = as set up)
                    "git_author_name": "", "git_author_email": "", "git_coauthor": False,  # 2.396.0 A (#3386)
                    "dispatch": "",  # 2.481.0 (#3662): the starter's mechanical dispatcher: "" off, "dry" dry run, "on"
                    # 2.974.0 (#5668): the model per run. model_split on = the host picks per run: model_decide for the person's
                    # own messages and runs that may need a decision, model_routine for routine (quiet wakes, new tasks,
                    # follow-ups, planned jobs without a sign); '' = the host's default for that kind. Off = model as before.
                    "model_split": False, "model_decide": "", "model_routine": ""}
DISPATCH_MODES = ("", "dry", "on")
# 2.396.0 A (#3386): the git author the agent's host sets for its commits (public in GitHub). '' = the neutral default;
# git_coauthor: whether the AI appends a Co-Authored-By line. A project with a repo may override name / mail (git_author_of).
GIT_AUTHOR_DEFAULT = ("Kalmido", "noreply@kalmido.com")
GIT_AUTHOR_NAME_MAX = 100
# 2.233.0 B (#3189): when the host ends a chat conversation with a summary and starts a fresh one (the "interim summary"):
# at a session size (small / medium / large; handed out as MB of the session file and as context tokens), after so many
# runs, after so many minutes of pause (0 = never; counts only from the small size on). The daily summary is the fresh
# session at nightly_reset (same key, no second field). Defaults = what the reference hosts did before.
ROTATE_SIZES = {"small": (0.4, 80000), "medium": (0.8, 150000), "large": (1.5, 250000)}
ROTATE_RUNS_RANGE = (10, 500)
ROTATE_IDLE_RANGE = (5, 1440)
# 2.29.0 (#1029): how the agent's host handles actions outside its allow list: ask = asks the person in the chat every time,
# auto = the host's safety check decides (risky things stay blocked); '' = the host's own default
PERMISSION_MODES = ("", "ask", "auto")


def _rt_model_shown(a):
    """2.974.0 (#5668): the set model the chat header compares with the one that runs; with the model per run on there is
    no single one (the header shows only the model of the last run)."""
    rt = agent_runtime(a)
    return "" if rt.get("model_split") else rt["model"]


def agent_runtime(a):
    try:
        d = json.loads(a["runtime"] or "{}")
    except (ValueError, TypeError):
        d = {}
    out = {k: d.get(k, v) for k, v in RUNTIME_DEFAULTS.items()}
    out["reset_seq"] = int(a["reset_seq"] or 0)
    return {**out, **runtime_derived(out)}


def runtime_derived(rt):
    """2.233.0 B (#3189): the values a host needs without knowing the size names (always filled in)."""
    mb, tok = ROTATE_SIZES.get(rt.get("rotate_size"), ROTATE_SIZES["medium"])
    return {"rotate_mb": mb, "rotate_tokens": tok, "rotate_idle_mb": ROTATE_SIZES["small"][0],
            "git_author": git_author_str(rt.get("git_author_name"), rt.get("git_author_email"))}


def git_author_str(name, email):
    """2.396.0 A (#3386): "Name <mail>", each empty part falls back to the neutral default."""
    return "%s <%s>" % (name or GIT_AUTHOR_DEFAULT[0], email or GIT_AUTHOR_DEFAULT[1])


def git_author_clean(name, email):
    """2.396.0 A (#3386): validates a git author name / mail pair (None / '' = default); returns (name, email)."""
    if name is None:
        name = ""
    if email is None:
        email = ""
    if not isinstance(name, str) or len(name.strip()) > GIT_AUTHOR_NAME_MAX or any(ch in "<>\x7f" or ord(ch) < 32 for ch in name):  # review: no control characters (logs, git log)
        raise BadInput(tr("Invalid value: {0}", "git_author_name"))
    if not isinstance(email, str):
        raise BadInput(tr("Invalid value: {0}", "git_author_email"))
    email = email.strip()
    if email and (len(email) > 200 or any(ch in "<>,\x7f" or ord(ch) < 32 for ch in email) or not EMAIL_RE.fullmatch(email)):
        raise BadInput(tr("Git author: please enter a valid e-mail address"))
    return name.strip(), email


def runtime_clean(cur, b):
    """Validates a (partial) runtime dict against the current one; returns the new stored dict (without reset_seq)."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "runtime"))
    unknown = sorted(k for k in b if k not in RUNTIME_DEFAULTS)
    if unknown:
        raise BadInput(tr("Invalid value: {0}", "runtime." + unknown[0]))
    out = {k: cur.get(k, v) for k, v in RUNTIME_DEFAULTS.items()}
    if "model" in b:
        m = b["model"]
        if m is None:
            m = ""
        if not isinstance(m, str):
            raise BadInput(tr("Invalid value: {0}", "model"))
        m = m.strip()
        if m and (len(m) > RUNTIME_MODEL_MAX or not RUNTIME_MODEL_RE.fullmatch(m)):
            raise BadInput(tr("Invalid value: {0}", "model"))
        out["model"] = m
    for k in ("model_decide", "model_routine"):  # 2.974.0 (#5668): same rules as model
        if k in b:
            m = b[k] if b[k] is not None else ""
            if not isinstance(m, str):
                raise BadInput(tr("Invalid value: {0}", k))
            m = m.strip()
            if m and (len(m) > RUNTIME_MODEL_MAX or not RUNTIME_MODEL_RE.fullmatch(m)):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = m
    if "model_split" in b:
        if not isinstance(b["model_split"], bool):
            raise BadInput(tr("Invalid value: {0}", "model_split"))
        out["model_split"] = b["model_split"]
    if "autocompact" in b:
        if not isinstance(b["autocompact"], bool):
            raise BadInput(tr("Invalid value: {0}", "autocompact"))
        out["autocompact"] = b["autocompact"]
    if "autocompact_pct" in b:
        v = b["autocompact_pct"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 10 <= v <= 100):
            raise BadInput(tr("Invalid value: {0}", "autocompact_pct"))
        out["autocompact_pct"] = v
    if "nightly_reset" in b:
        v = b["nightly_reset"] or ""
        if not isinstance(v, str) or (v and not valid_hm(v)):
            raise BadInput(tr("Invalid value: {0}", "nightly_reset"))
        out["nightly_reset"] = v
    if "permission_mode" in b:
        v = b["permission_mode"] if b["permission_mode"] is not None else ""
        if v not in PERMISSION_MODES:
            raise BadInput(tr("Invalid value: {0}", "permission_mode"))
        out["permission_mode"] = v
    if "perm_user" in b:  # 2.312.0 D (#3266): an account id or None; who may be chosen: runtime_set (perm_user_ok)
        v = b["perm_user"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
            raise BadInput(tr("Invalid value: {0}", "perm_user"))
        out["perm_user"] = v
    if "rotate_size" in b:  # 2.233.0 B (#3189)
        if b["rotate_size"] not in ROTATE_SIZES:
            raise BadInput(tr("Invalid value: {0}", "rotate_size"))
        out["rotate_size"] = b["rotate_size"]
    for k, (lo, hi), off in (("rotate_runs", ROTATE_RUNS_RANGE, False), ("rotate_idle_min", ROTATE_IDLE_RANGE, True)):
        if k in b:
            v = b[k]
            if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi or (off and v == 0)):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
    if "git_author_name" in b or "git_author_email" in b:  # 2.396.0 A (#3386)
        out["git_author_name"], out["git_author_email"] = git_author_clean(
            b.get("git_author_name", out["git_author_name"]), b.get("git_author_email", out["git_author_email"]))
    if "git_coauthor" in b:
        if not isinstance(b["git_coauthor"], bool):
            raise BadInput(tr("Invalid value: {0}", "git_coauthor"))
        out["git_coauthor"] = b["git_coauthor"]
    if "dispatch" in b:  # 2.481.0 (#3662)
        v = b["dispatch"] if b["dispatch"] is not None else ""
        if v not in DISPATCH_MODES:
            raise BadInput(tr("Invalid value: {0}", "dispatch"))
        out["dispatch"] = v
    return out


def perm_user_ok(c, a, uid):
    """2.312.0 D (#3266): may person uid answer the permission questions of agent a? A personal agent: only its owner. A team
    agent: an active person the agent reaches in the chat (agent_shares, where its host posts the question)."""
    if a["owner_id"]:
        return uid == a["owner_id"]
    u = c.execute("SELECT id FROM users WHERE id=? AND kind<>'agent' AND disabled=0", (uid,)).fetchone()
    return bool(u) and agent_shares(c, a["user_id"], uid)


def perm_user_of(c, a):
    """2.312.0 D (#3266): the chosen person of a team agent while still allowed (GET /api/v1/agent perm_user_id), else None:
    the host keeps KALMIDO_PERM_USER of its setup / the owner."""
    v = agent_runtime(a)["perm_user"]
    return v if v and not a["owner_id"] and perm_user_ok(c, a, v) else None


def may_set_runtime(c, a, uid):
    """2.29.0 (#1029): who may switch an agent's permission mode in its chat header: the owner of a personal agent, an instance
    admin for a team agent (like the runtime section of the administration)."""
    if a["owner_id"]:
        return a["owner_id"] == uid
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return bool(u and u["is_admin"])


def agent_online(a):
    """2.4.1 (#375): False when the agent polled no events for AGENT_OFFLINE_S (None: it never polled / uses a webhook,
    so Kalmido cannot tell)."""
    if a["webhook_id"] or not a["last_poll_at"]:
        return None
    return (now_utc() - parse_iso(a["last_poll_at"])).total_seconds() <= AGENT_OFFLINE_S


def agent_contact_age(c, a):
    """2.6.0 (K08): seconds since the agent's last event poll or API call (its tokens' last_used_at), None = never."""
    used = c.execute("SELECT MAX(last_used_at) FROM api_tokens WHERE user_id=?", (a["user_id"],)).fetchone()[0]
    last = max([x for x in (a["last_poll_at"], used) if x] or [None], key=lambda x: x or "")
    return round((now_utc() - parse_iso(last)).total_seconds()) if last else None


# 2.826.0 (#5509): a person's chat message the agent has not fetched (no delivered_at) and not answered after it; the
# oldest such message counts. Older than PENDING_DAYS days is left out (messages from before delivered_at existed)
PENDING_DAYS = 30
_PENDING_SQL = """SELECT m.agent_id, MIN(m.created_at) FROM agent_chat m
                  WHERE m.agent_id = ANY(CAST(? AS BIGINT[])) AND m.sender='user' AND m.delivered_at IS NULL
                  AND COALESCE(m.kind, '')<>'unshared' AND m.created_at>?
                  AND NOT EXISTS(SELECT 1 FROM agent_chat r WHERE r.agent_id=m.agent_id AND r.user_id=m.user_id
                                 AND r.sender='agent' AND r.id>m.id)
                  GROUP BY m.agent_id"""


def agent_pending_ages(c, ids):
    """2.826.0 (#5509): {agent id: seconds the oldest waiting chat message to it waits} for the agents ids (missing = nothing
    waits). The app shows "not connected" only for an agent that never got in touch or lets a message wait over 5 minutes;
    an agent that starts on demand (a cloud or server agent) and answered its last message is "ready"."""
    if not ids:
        return {}
    cut = iso(now_utc() - timedelta(days=PENDING_DAYS))
    with system_ctx(c):  # only an age per agent, no text and no person leaves this function
        rows = c.execute(_PENDING_SQL, (st_ids(list(ids)), cut)).fetchall()
    return {r[0]: round((now_utc() - parse_iso(r[1])).total_seconds()) for r in rows if r[1]}


AGENT_NO_SERVICE_S = 600


def _no_service(c, a, age=False):
    """2.26.0 (#933): True when the agent made an API call in the last AGENT_NO_SERVICE_S but polled no events for that long
    (or never) -- "connected, but no service running". Webhook agents: never. 2.674.0 B (#4194): age = agent_contact_age
    when the caller has it (False: ask)."""
    if a["webhook_id"]:
        return False
    age = agent_contact_age(c, a) if age is False else age
    if age is None or age > AGENT_NO_SERVICE_S:
        return False
    return not a["last_poll_at"] or (now_utc() - parse_iso(a["last_poll_at"])).total_seconds() > AGENT_NO_SERVICE_S


def agent_typing_to(a, uid):
    """Seconds left of the agent's typing signal to person uid in the chat (0 = none)."""
    if not uid or a["typing_user"] != uid:
        return 0
    return max(0.0, round((a["typing_until"] or 0) - time.time(), 1))


# ---- permissions of people towards agents
def is_approver(c, t, uid, agent=None, assignee=True):
    """2.126.0 B (#1974 #1975): agent = the agent whose request is decided: uid must also be allowed to address it
    (agent_usable) or own the list; assignee=False: the assignee alone is not enough (an agent's waiting approval job)."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or is_agent(u) or u["disabled"] or not task_visible(c, t["id"], uid, full=True):
        return False
    if agent and not agent_usable(c, agent, uid, t["list_id"]) \
            and not c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (t["list_id"], uid)).fetchone():
        return False
    return list_role(c, t["list_id"], uid) in MANAGE_ROLES or (assignee and t["assignee_id"] == uid) or bool(u["is_admin"])


# 2.26.0 (#928): the events a person can only send to an agent where the agent is open to them (agent_usable); the
# others are list automations the list's owner switched on (tidy, task_added) or checked where they start (job_request:
# POST /api/proposals, chat: agent_shares, job: job_may_act). An agent's actions never reach another agent unless the list
# had agent_peers on; 2.40.0 (#1373): never (every event).
AGENT_GATED = ("mention", "comment", "assigned", "unassigned", "reaction", "team_message", "wake",
               "task_changed")  # 2.959.0 (#4030): a person without the agent switch reaches it neither by a change
AGENT_UNGATED = ("job", "ping", "runtime_changed", "reset", "followup_due")
# 2.26.0 (#928): the SQL condition "list l is open to person ? for agent ?": owner, list admin (own role), the list
# belongs to that agent (it shared the list itself); parameters (person, agent, person) or the owner switched on "Members may see and use the agent"
_OPEN_SQL = """(l.owner_id=? OR l.owner_id=? OR EXISTS(SELECT 1 FROM list_members m
               WHERE m.list_id=l.id AND m.user_id=? AND (l.agent_members=1 OR m.role IN ('owner','admin'))))"""


def agent_usable(c, aid, uid, lid):
    """2.26.0 (#928): may uid (a person or another agent) address agent aid in list lid (mention, assign, comment to it,
    chat about it)? A personal agent: only its owner. Another agent: only with lists.agent_peers on. A person: an instance
    admin, the list's owner / admins, or every member while lists.agent_members is on. Both must be in the list."""
    from ..agents.admin import agent_owner
    if uid == aid:
        return True
    u = c.execute("SELECT kind, is_admin FROM users WHERE id=?", (uid,)).fetchone()
    lst = c.execute("SELECT agent_members, agent_peers FROM lists WHERE id=?", (lid,)).fetchone()
    if not u or not lst or not list_role(c, lid, uid) or not list_role(c, lid, aid):
        return False
    if u["kind"] == "agent":
        return False  # 2.40.0 (#1373): agents never address each other (lists.agent_peers stays in the database, unused)
    o = agent_owner(c, aid)
    if o is not None:
        return o == uid
    # 2.28.0 (#965): an instance admin is no exception any more -- only the list's owner / admins and open lists
    return bool(c.execute(f"SELECT 1 FROM lists l WHERE l.id=? AND {_OPEN_SQL}", (lid, uid, aid, uid)).fetchone())


def agent_shares(c, aid, uid):
    """Does uid share a list with agent aid? 2.7.2 (#420): a personal agent only with its owner. 2.26.0 (#928): only lists
    open to uid for their agents count (see _OPEN_SQL; default: owner and list admins). 2.28.0 (#965): instance admins are no
    exception: they reach an agent in the chat, at @, when assigning and sharing only through such lists; every agent is
    listed for them in the administration alone (personal agents of others there only by name, with the kill switch)."""
    from ..agents.admin import agent_owner
    o = agent_owner(c, aid)
    if o is not None:
        return o == uid
    return bool(c.execute(f"""SELECT 1 FROM lists l WHERE l.id IN {vis_sql()} AND {_OPEN_SQL} AND l.id IN {joined_lists_sql()} LIMIT 1""",
                              (aid, aid, uid, aid, uid, uid, uid)).fetchone())


# 2.223.2 B (#2862): the events in which a person asks the agent for something (chat, @mention, assignment, a job, a draft)
AGENT_ASK_EVENTS = ("chat", "mention", "assigned", "chat_choice", "job_request", "scheduled_job", "team_message",
                    "review_requested", "letter_draft_requested")


def agent_asked_by(c, aid, uid):
    """2.223.2 B (#2862): did person uid ask agent aid for something lately -- an event of its queue (made by the server,
    never by the agent) with uid as the actor or the requested_by, within AGENT_EVENTS_STALE_H hours (else the kept 30 days)?
    An agent acts for another person than its owner (requested_by) only then."""
    since = now_utc() - (timedelta(hours=AGENT_EVENTS_STALE_H) if AGENT_EVENTS_STALE_H else timedelta(days=AGENT_EVENTS_KEEP_DAYS))
    rows = c.execute(f"SELECT payload FROM agent_events WHERE agent_id=? AND event IN ({','.join('?' * len(AGENT_ASK_EVENTS))}) "
                     "AND created_at>=? ORDER BY id DESC LIMIT 500", (aid, *AGENT_ASK_EVENTS, iso(since))).fetchall()
    for (p,) in rows:
        try:
            env = json.loads(p or "{}")
        except ValueError:
            continue
        actor = env.get("actor") if isinstance(env.get("actor"), dict) else {}
        rb = (env.get("data") or {}).get("requested_by") if isinstance(env.get("data"), dict) else None
        rb = rb.get("id") if isinstance(rb, dict) else rb
        if (actor.get("id") == uid and actor.get("kind") == "person") or (rb == uid and not isinstance(rb, bool)):
            return True
    return False


def need_chat_agent(c, aid):
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or not agent_shares(c, aid, me()):
        raise Denied(404)
    return a


# 2.56.0 (#1793): the name a background job of an agent service carries in its title ("Clara: Release 2.50",
# part jobs "Frida B: ..."); None for other titles
JC_NAME_RE = re.compile(r"^([A-ZÄÖÜ][a-zäöüß]{1,11}(?: [A-Z])?): ")


# 2.58.0 (#1803): ordinary title words are no name ("Release: 2.56", "Fix: Login"); the title is only the fallback
# for jobs without their own name (agent_jobs.name, POST /agent/jobs {name})
F8F_NOT_NAMES = frozenset((
    "release", "fix", "hotfix", "bugfix", "bug", "patch", "feature", "test", "tests", "build", "deploy", "update", "upgrade",
    "review", "audit", "check", "task", "todo", "job", "note", "docs", "doc", "chore", "refactor", "migration", "import",
    "export", "backup", "sync", "cleanup", "report", "plan", "draft", "idea", "issue", "error", "warning", "info", "status",
    "fehler", "aufgabe", "bericht", "entwurf", "idee", "wartung", "prüfung", "hinweis", "notiz"))
# 2.58.0 (#1803): a job name: letters, spaces, . ' - (no digits / colons, so it never reads like "Job 12:")
F8F_NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'-]){0,23}$")


def f8f_job_name_in(v):
    """The cleaned name of POST /agent/jobs {name}; None = none, ValueError = not a name."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError
    v = " ".join(v.split())
    if not v:
        return None
    if not F8F_NAME_RE.match(v) or v.lower() in F8F_NOT_NAMES:
        raise ValueError
    return v


def jc_job_name(title, name=None):
    if name:
        return name
    m = JC_NAME_RE.match(title or "")
    return m.group(1) if m and m.group(1).split(" ")[0].lower() not in F8F_NOT_NAMES else None


def _jd_sees(c, tid, lid, aid):
    """2.223.7 (#2941): task_visible for job_dict, one list_role per list and request (a job list of 200 jobs polled by agents);
    only participant / unknown lists check the single task."""
    memo = g.__dict__.setdefault("_jd_roles", {})
    if (aid, lid) not in memo:
        memo[(aid, lid)] = list_role(c, lid, aid)
    role = memo[(aid, lid)]
    return True if role and role != "participant" else task_visible(c, tid, aid)


def job_task_ids(c, j):
    """2.392.2 (#3366): the tasks of job j in their order (task_id first; agent_job_tasks for a job of several)."""
    ids = [r[0] for r in c.execute("SELECT task_id FROM agent_job_tasks WHERE job_id=? ORDER BY pos, task_id", (j["id"],))]
    return ids or ([j["task_id"]] if j["task_id"] else [])


def job_links(c, j, viewer=None, pre=None):
    """2.392.2 (#3366): task_ids (only the tasks the viewer sees, an agent its own shares), continue_of / continued_by (the
    job it continues, the job that continues it) and parts (its part jobs, parent_id = j).
    2.674.0 B (#4194): pre = jobs_pre() of a job list (the same answers, read for all jobs at once)."""
    if pre is not None:
        ids = pre["jtasks"].get(j["id"]) or ([j["task_id"]] if j["task_id"] else [])
        if viewer and len(ids) > 1:
            ids = [x for x in ids if x == j["task_id"] or x in pre["tvis"]]
        return {"task_ids": ids, "continue_of": j["continue_of"] if "continue_of" in j.keys() else None,
                "continued_by": pre["next"].get(j["id"]), "parts": pre["parts"].get(j["id"], [])}
    ids = job_task_ids(c, j)
    if viewer and len(ids) > 1:
        ids = [x for x in ids if x == j["task_id"] or task_visible(c, x, viewer, full=True)]
    seen = (lambda x: job_visible(c, x, viewer)) if viewer else (lambda x: True)  # only the jobs the viewer may see
    nxt = next((x["id"] for x in c.execute("SELECT * FROM agent_jobs WHERE continue_of=? ORDER BY id LIMIT 5", (j["id"],)) if seen(x)), None)
    parts = [x["id"] for x in c.execute("SELECT * FROM agent_jobs WHERE parent_id=? ORDER BY id LIMIT 50", (j["id"],)) if seen(x)]
    return {"task_ids": ids, "continue_of": j["continue_of"] if "continue_of" in j.keys() else None,
            "continued_by": nxt, "parts": parts}


def jobs_pre(c, rows, viewer):
    """2.674.0 B (#4194): what job_dict / job_links read per job, read once for a whole job list: the tasks (title, list),
    which of them the viewer sees (full), the tasks of jobs of several, the visible job that continues each and its visible
    part jobs (same order and limits as job_links)."""
    jids = [j["id"] for j in rows]
    q = st_ids(jids) if jids else "{}"
    jt = {}
    for r in c.execute("SELECT job_id, task_id FROM agent_job_tasks WHERE job_id = ANY(CAST(? AS BIGINT[])) ORDER BY job_id, pos, task_id", (q,)):
        jt.setdefault(r[0], []).append(r[1])
    tids = {j["task_id"] for j in rows if j["task_id"]} | {x for v in jt.values() for x in v}
    tasks = {r["id"]: r for r in c.execute("SELECT id, title, list_id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[]))", (st_ids(sorted(tids)) if tids else "{}",))}
    tvis = tasks_visible(c, tids, viewer, full=True) if viewer else set(tids)
    nx = c.execute("""SELECT * FROM (SELECT id, agent_id, user_id, task_id, continue_of, row_number() OVER (PARTITION BY continue_of ORDER BY id) AS rn
                      FROM agent_jobs WHERE continue_of = ANY(CAST(? AS BIGINT[]))) x WHERE rn<=5 ORDER BY continue_of, id""", (q,)).fetchall()
    pa = c.execute("""SELECT * FROM (SELECT id, agent_id, user_id, task_id, parent_id, row_number() OVER (PARTITION BY parent_id ORDER BY id) AS rn
                      FROM agent_jobs WHERE parent_id = ANY(CAST(? AS BIGINT[]))) x WHERE rn<=50 ORDER BY parent_id, id""", (q,)).fetchall()
    seen = jobs_seen(c, list(nx) + list(pa), viewer) if viewer else {x["id"] for x in list(nx) + list(pa)}
    nxt, parts = {}, {}
    for x in nx:
        if x["id"] in seen and x["continue_of"] not in nxt:
            nxt[x["continue_of"]] = x["id"]
    for x in pa:
        if x["id"] in seen:
            parts.setdefault(x["parent_id"], []).append(x["id"])
    return {"jtasks": jt, "tasks": tasks, "tvis": tvis, "next": nxt, "parts": parts}


def job_dict(c, j, names=None, pre=None):
    names = names or user_names(c, [j["agent_id"], j["user_id"], j["action_by"]])
    viewer = g.user["id"] if has_request_context() and getattr(g, "user", None) else None
    if pre is not None:  # 2.674.0 B (#4194): read once for the whole list (jobs_pre)
        t = pre["tasks"].get(j["task_id"]) if j["task_id"] else None
        if t and viewer and viewer != j["agent_id"] and j["task_id"] not in pre["tvis"]:
            t = None
    else:
        t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (j["task_id"],)).fetchone() if j["task_id"] else None
    if pre is None and t and viewer and viewer != j["agent_id"] and not task_visible(c, j["task_id"], viewer, full=True):
        t = None  # 2.306.0 D3 (#2875): the task's title / list only for who sees the task (the job itself stays visible)
    if t and viewer and viewer == j["agent_id"] and not _jd_sees(c, j["task_id"], t["list_id"], j["agent_id"]):
        t = None  # 2.223.7 D (#2941): the agent no longer sees the task (share withdrawn): the job stays, without its title / list
    return {"id": j["id"], "agent_id": j["agent_id"], "agent_name": names.get(j["agent_id"], ""), "task_id": j["task_id"],
            "task_title": t["title"] if t else None, "list_id": t["list_id"] if t else None, "user_id": j["user_id"],
            "title": j["title"], "state": j["state"], "action": j["action"], "action_by": j["action_by"],
            **jl_log(j),  # 2.674.0 B (#4194): a job list carries only the log's last line (the whole log: ?id=)
            "action_by_name": names.get(j["action_by"], "") if j["action_by"] else "", "action_at": j["action_at"],
            "created_at": j["created_at"], "updated_at": j["updated_at"],
            "kind": j["kind"], "proposal_state": j["prop_state"] or None,  # 2.3.0: proposal jobs
            "approval": bool(j["approval"]) if "approval" in j.keys() else False,  # 2.15.0 (#479): a request waiting for approval
            "name": jc_job_name(j["title"], j["name"] if "name" in j.keys() else None),  # 2.56.0 (#1793), 2.58.0 (#1803): own field first: "Clara" of "Clara: Release 2.50" (null without)
            "parent_id": j["parent_id"] if "parent_id" in j.keys() else None,  # 2.59.0 (#1827): the leading job of a part job
            **job_links(c, j, viewer, pre)}  # 2.392.2 (#3366): task_ids, continue_of, continued_by, parts


def jl_log(j):
    """2.674.0 B (#4194): {log} of a job row with its log; a row of a job list (JL_COLS: without the log) gives {log: null,
    log_last: the log's last line (at most 140 characters, what the list shows folded), has_log}."""
    if "log" in j.keys():
        return {"log": j["log"]}
    return {"log": None, "log_last": j["log_last"] or "", "has_log": bool(j["has_log"])}


_JL_COLS = []


def jl_cols(c):
    """2.674.0 B (#4194): the SELECT list of agent_jobs for job lists: every column but the log, plus its last line and
    whether there is one (the columns are read once per process; migrations only add columns at start-up)."""
    if not _JL_COLS:
        cols = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agent_jobs' "
                                        "AND table_schema=current_schema() ORDER BY ordinal_position")]
        _JL_COLS.append(", ".join(f'"{x}"' for x in cols if x != "log")
                        + r", left(substring(btrim(COALESCE(log, ''), E' \t\r\n') from '[^\n]*$'), 140) AS log_last"
                        + ", COALESCE(log, '')<>'' AS has_log")
    return _JL_COLS[0]


# 2.59.0 (#1827): name + leading job of the jobs ids that uid may see ({id: {"name", "parent_id", "parent_name"}}; jobs
# uid may not see are left out, so is the name of a leader uid may not see). The one place that derives a job's name for
# the chat (jc_job_name), so a name column only needs adding here.
def jn9_job_names(c, ids, uid):
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = {j["id"]: j for j in c.execute(f"SELECT * FROM agent_jobs WHERE id IN ({','.join('?' * len(ids))})", ids)}
    pids = sorted({j["parent_id"] for j in rows.values() if "parent_id" in j.keys() and j["parent_id"]} - set(rows))
    if pids:
        rows.update({j["id"]: j for j in c.execute(f"SELECT * FROM agent_jobs WHERE id IN ({','.join('?' * len(pids))})", pids)})
    seen = {i: j for i, j in rows.items() if job_visible(c, j, uid)}
    out = {}
    for i in ids:
        j = seen.get(i)
        if not j:
            continue
        par = seen.get(j["parent_id"]) if "parent_id" in j.keys() and j["parent_id"] else None
        out[i] = {"name": jc_job_name(j["title"], j["name"] if "name" in j.keys() else None), "parent_id": par["id"] if par else None,
                  "parent_name": jc_job_name(par["title"], par["name"] if "name" in par.keys() else None) if par else None}
    return out


def job_visible(c, j, uid):
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return False
    if u["kind"] == "agent":
        return j["agent_id"] == uid
    if j["user_id"] == uid:
        return True
    if u["is_admin"] and agent_shares(c, j["agent_id"], uid):  # 2.28.0 (#965): an admin sees the jobs of agents it reaches
        return True
    return bool(j["task_id"]) and task_visible(c, j["task_id"], uid, full=True)


def agents_shared(c, aids, uid):
    """2.674.0 B (#4194): {agent id} among aids that share a list with uid -- agent_shares for many: the owners of all in one
    query (a personal agent: only its owner); a team agent asks its lists as agent_shares does. The same answers."""
    ids = sorted({int(x) for x in aids or () if x})
    if not ids:
        return set()
    own = {r[0]: r[1] for r in c.execute("SELECT user_id, owner_id FROM agents WHERE user_id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),))}
    out = set()
    for aid in ids:
        o = own.get(aid)
        if o is not None:
            if o == uid:
                out.add(aid)
        elif c.execute(f"""SELECT 1 FROM lists l WHERE l.id IN {vis_sql()} AND {_OPEN_SQL} AND l.id IN {joined_lists_sql()} LIMIT 1""",
                       (aid, aid, uid, aid, uid, uid, uid)).fetchone():
            out.add(aid)
    return out


def jobs_seen(c, rows, uid, u=None):
    """2.674.0 B (#4194): {job id} of the agent_jobs rows that uid may see -- job_visible for many rows at once (the account
    once, agent_shares once per agent, the tasks with tasks_visible). The same answers as job_visible row by row.
    u = uid's users row (is_admin, kind) when the caller has read it already."""
    rows = list(rows or ())
    if not rows or not uid:
        return set()
    u = u or c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return set()
    if u["kind"] == "agent":
        return {j["id"] for j in rows if j["agent_id"] == uid}
    out = {j["id"] for j in rows if j["user_id"] == uid}
    rest = [j for j in rows if j["id"] not in out]
    if u["is_admin"] and rest:  # 2.28.0 (#965): an admin sees the jobs of agents it reaches
        sh = agents_shared(c, {j["agent_id"] for j in rest}, uid)
        out.update(j["id"] for j in rest if j["agent_id"] in sh)
        rest = [j for j in rest if j["id"] not in out]
    tv = tasks_visible(c, [j["task_id"] for j in rest if j["task_id"]], uid, full=True)
    out.update(j["id"] for j in rest if j["task_id"] and j["task_id"] in tv)
    return out


def job_vis_sql(c, uid):
    """2.674.0 B (#4194): (SQL condition on agent_jobs, args) that keeps every job uid may see and leaves out most others, so
    a job list filters in the database before it checks: a person's own jobs, (an admin) the jobs of the agents it reaches,
    jobs on tasks of lists the person owns, is a member of or sees through its organisation. Only a pre-filter (a superset):
    the exact check stays job_visible / jobs_seen."""
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u:
        return "FALSE", []
    if u["kind"] == "agent":
        return "agent_id=?", [uid]
    cond, args = ["user_id=?"], [uid]
    if u["is_admin"]:
        sh = agents_shared(c, [r[0] for r in c.execute("SELECT user_id FROM agents")], uid)
        if sh:
            cond.append(f"agent_id IN ({','.join(str(int(x)) for x in sorted(sh))})")
    cond.append("task_id IN (SELECT t.id FROM tasks t WHERE t.list_id IN (SELECT id FROM lists WHERE owner_id=? UNION "
                "SELECT list_id FROM list_members WHERE user_id=? UNION SELECT l.id FROM lists l JOIN org_members om "
                "ON om.org_id=l.org_id AND om.user_id=? WHERE l.org_visibility='org'))")
    args += [uid, uid, uid]
    return "(" + " OR ".join(cond) + ")", args


def job_may_act(c, j, uid, action):
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kind"] == "agent":
        return False
    if j["user_id"] == uid or (u["is_admin"] and agent_shares(c, j["agent_id"], uid)):
        return True
    if not j["task_id"]:
        return False
    t = c.execute("SELECT * FROM tasks WHERE id=?", (j["task_id"],)).fetchone()
    if not t:
        return False
    if j["approval"]:  # 2.126.0 B (#1974): an approval job: the approver, an admin, the list's owner / admins who may address the agent
        return is_approver(c, t, uid, agent=j["agent_id"], assignee=False) or (action == "stop" and task_visible(c, t["id"], uid, write=True))
    return is_approver(c, t, uid) or (action == "stop" and task_visible(c, t["id"], uid, write=True))


def jobs_may_act(c, rows, uid):
    """2.674.0 B (#4194): {job id: (may approve, may stop)} for a job list -- job_may_act(..., "approve") and (..., "stop")
    with the account read once and agent_shares once per agent; only a job someone else started on a task is asked one by
    one (job_may_act). The same answers."""
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or u["kind"] == "agent":
        return {j["id"]: (False, False) for j in rows}
    sh = agents_shared(c, {j["agent_id"] for j in rows if j["user_id"] != uid}, uid) if u["is_admin"] else set()
    out, memo = {}, {}
    for j in rows:
        if j["user_id"] == uid or j["agent_id"] in sh:
            out[j["id"]] = (True, True)
        elif not j["task_id"]:
            out[j["id"]] = (False, False)
        else:  # the rest depends on the task, whether it is an approval job and (then) its agent only: once per such key
            k = (j["task_id"], bool(j["approval"]), j["agent_id"] if j["approval"] else None)
            if k not in memo:
                memo[k] = (job_may_act(c, j, uid, "approve"), job_may_act(c, j, uid, "stop"))
            out[j["id"]] = memo[k]
    return out


def agent_is_ai(a):
    """2.482.0 (#3530): an agent counts as AI unless it is marked as a bot without AI (agents.ai = 0)."""
    return not (a is not None and "ai" in a.keys() and a["ai"] is not None and int(a["ai"]) == 0)


def agent_public(c, a, uid=None, pre=None):
    """An agent as the people who share lists with it see it: status + their visible running / waiting jobs + unread chat.
    2.674.0 B (#4194): pre = ag_pre() of agents_for (what is asked per agent, read for all of them at once; same answers)."""
    from ..agents.usage import usage_block, usage_cost_public, usage_flows_public
    if pre is not None:
        jobs, unread = pre["jobs"].get(a["user_id"], []), pre["unread"].get(a["user_id"], 0)
    else:
        jobs = c.execute("SELECT * FROM agent_jobs WHERE agent_id=? AND state IN ('running','waiting') ORDER BY id DESC LIMIT 200",
                         (a["user_id"],)).fetchall()
        if uid is not None:
            jobs = [j for j in jobs if job_visible(c, j, uid)]
        unread = c.execute("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND read_at IS NULL",
                           (a["user_id"], uid)).fetchone()[0] if uid else 0
    p = pre or {}
    age = p["age"].get(a["user_id"]) if pre is not None else agent_contact_age(c, a)
    may_rt = (p["may_rt"](a) if pre is not None else may_set_runtime(c, a, uid)) if uid else False
    return {"id": a["user_id"], "username": a["username"], "name": a["display_name"] or a["username"],
            "display_name": a["display_name"] or a["username"],
            "ai": agent_is_ai(a),  # 2.482.0 (#3530): labelled "AI agent" (EU AI Act Art. 50); 0 = a bot without AI
            # 2.28.0 (#935 / #965): the workspace it works in (null = private) and whose personal agent it is (null = team)
            "org_id": a["org_id"] if "org_id" in a.keys() else None, "owner_id": a["owner_id"] if "owner_id" in a.keys() else None,
            "avatar": avatar_url(p["avatars"].get(a["user_id"]) if pre is not None else c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()),
            "enabled": agent_active(a), "status": a["status"] or "idle", "status_text": a["status_text"] or "", "status_at": a["status_at"],
            "status_key": (a["status_key"] or "") if a["status_text"] else "", "status_key_at": (a["status_key_at"] or "") if a["status_text"] else "",  # 2.450.0 (#3769)
            # 2.26.0 (#949): paused with a reason (the agent itself, its owner or an admin)
            "paused": a["status"] == "paused", "pause_reason": (a["status_text"] or "") if a["status"] == "paused" else "",
            # 2.0.2: the task it says it works on (only when the viewer may see it) + the tasks of its running jobs
            "status_task": a["status_task"] if a["status_task"] and (uid is None or (a["status_task"] in p["tvis"] if pre is not None else task_visible(c, a["status_task"], uid, full=True))) else None,
            "job_tasks": sorted({j["task_id"] for j in jobs if j["state"] == "running" and j["task_id"]}),
            "running": sum(1 for j in jobs if j["state"] == "running"), "waiting": sum(1 for j in jobs if j["state"] == "waiting"),
            "chat_unread": unread, "limit_reached": bool(usage_block(c, a["user_id"], a if pre is not None else None)),  # 2.1.1 (#326): its hard usage limit
            # 2.4.1 (#375): the chat header: offline (no event poll for 5 minutes; null = cannot tell), its typing signal to
            # the viewer (seconds left), a running job for the viewer
            "online": agent_online(a), "last_poll_at": a["last_poll_at"], "typing": agent_typing_to(a, uid),
            # 2.6.0 (K08): seconds since its last contact (an event poll or any API call with its token; null = never): the
            # app shows "not connected" after 5 minutes without one. A webhook agent is told about events, so for it only
            # "online": false counts
            "webhook": bool(a["webhook_id"]), "contact_age": age,
            # 2.826.0 (#5509): seconds the oldest chat message to it waits unfetched and unanswered (null = nothing waits);
            # only then (over 5 minutes) or without any contact the app says "not connected"
            "pending_age": p["pending"].get(a["user_id"]) if pre is not None else agent_pending_ages(c, [a["user_id"]]).get(a["user_id"]),
            "poll_age": round((now_utc() - parse_iso(a["last_poll_at"])).total_seconds()) if a["last_poll_at"] else None,
            # 2.26.0 (#933): its token is in use (an interactive session) but nothing collects its events -- the setup is not
            # finished until a service (launcher / LaunchAgent / task) keeps polling
            "no_service": _no_service(c, a, age),
            "my_job": bool(uid) and any(j["state"] == "running" and j["user_id"] == uid for j in jobs),
            # 2.29.0 (#1029): the chat header's badge (Auto / Ask) and whether the viewer may switch it
            "permission_mode": agent_runtime(a)["permission_mode"], "may_set_mode": bool(uid) and may_rt,
            # 2.32.0 (#1079): what its host reports it really runs with (model as the host names it, the mode of the current
            # run, the host's own default); the runtime's wished model next to it (set: … · runs: …)
            "host": _host_info(a), "runtime_model": _rt_model_shown(a),
            # 2.33.0 (#1045): its plan usage (the ring in the chat header; null = never reported)
            "quota": _quota(a),
            # 2.407.0 B (#3493): its costs (API-key agents: the ring against its cost limit; amounts only for owner / admins)
            "cost": usage_cost_public(c, a, uid, **({"sums": p["cost"].get(a["user_id"], (None, None)), "admin": p["admin"]} if pre is not None else {})),
            # 2.565.0 D (#4674): a server agent's tokens per starter routine this month (owner / admins; the ring's list)
            "flows": usage_flows_public(c, a, uid, **({"admin": p["admin"]} if pre is not None else {})),
            # 2.35.0 (#1103): open approval requests + permission questions to the viewer (the badge "1 approval open")
            "approvals_open": p["appr"].get(a["user_id"], 0) if pre is not None and uid else _approvals_open(c, a["user_id"], uid),
            # 2.58.0 (#1761): its list limit, only for the people who manage it (owner / admin); [] = all its lists
            **({"list_ids": f8c_list_ids(a)} if uid and may_rt else {}),
            # 2.83.0 (#1775): the viewer may change its colour (same rule as PATCH /api/agents/<id>/color)
            "can_color": p["color"](a) if pre is not None and uid else o3b_can_color(c, a, uid)}


def o3b_can_color(c, a, uid):
    """2.83.0 (#1775): instance admin, owner of a personal agent or admin of the agent's organisation."""
    if not uid:
        return False
    if "owner_id" in a.keys() and a["owner_id"] == uid:
        return True
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if u and u["is_admin"]:
        return True
    org = a["org_id"] if "org_id" in a.keys() else None
    return bool(org and is_org_admin(c, uid, org))


def f8c_list_ids(a):
    from ..agents.safety import list_ids_out
    return list_ids_out(a["list_ids"] if "list_ids" in a.keys() else "")


def _approvals_open(c, aid, uid):
    if not uid:
        return 0
    from ..agents.chat import chat_approvals_open
    return len(chat_approvals_open(c, aid, uid))


def _quota(a):
    from ..agents.quota import quota_public
    return quota_public(a)


def _host_info(a):
    from ..agents.steps import host_info
    return host_info(a)


def agent_org_orgs(c, uid):
    """2.777.0 C (#5378, decided 09.11.2026): the organisations whose TEAM agents person uid sees without a shared project: the ones
    uid is a member or admin of (not a guest, read-only or accounting role, not a retired organisation); none for an agent."""
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or (u["kind"] or "user") == "agent":
        return set()
    return set(user_orgs(c, uid)) & set(user_orgs_full(c, uid, write=True))


def agent_org_sees(c, a, uid):
    """2.777.0 C (#5378): does person uid see team agent a (agent_row, no owner) only as a member of its organisation? It grants NO
    data: the agent still reaches only what is shared with it; such a person's chat never reaches the agent (agents/chat.py
    chat_unshared_answer: Kalmido answers with a fixed hint how to share a project). A personal agent: never."""
    return bool(a) and not a["owner_id"] and bool(a["org_id"]) and a["org_id"] in agent_org_orgs(c, uid)


def agent_projects_counts(c, aids):
    """2.777.0 C (#5378): {agent id: how many projects are shared with it} for the agents aids, in one query (its own basket and
    projects in the trash not counted; 0 = none) - numbers only, no names."""
    ids = sorted({int(x) for x in aids or () if x})
    if not ids:
        return {}
    with system_ctx(c):  # a count over the agents' memberships (structure; no project is named)
        n = {r[0]: r[1] for r in c.execute(f"""SELECT m.user_id, COUNT(*) FROM list_members m JOIN lists l ON l.id=m.list_id
                                               WHERE m.user_id = ANY(CAST(? AS BIGINT[])) AND l.is_inbox=0 AND {otr_live("l")}
                                               AND l.owner_id<>m.user_id GROUP BY m.user_id""", (st_ids(ids),))}
    return {a: n.get(a, 0) for a in ids}


def agent_projects_count(c, aid):
    """2.777.0 C (#5378): agent_projects_counts for one agent."""
    return agent_projects_counts(c, [aid]).get(aid, 0)


def agents_for(c, uid):
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    sh = agents_shared(c, [a["user_id"] for a in rows], uid)  # 2.674.0 B (#4194): agent_shares for all at once
    # 2.777.0 C (#5378, decided 09.11.2026): a team agent of my organisation also without a shared project (agent_org_orgs)
    oo = agent_org_orgs(c, uid) if any(not a["owner_id"] and a["org_id"] and a["user_id"] not in sh for a in rows) else set()
    rows = [a for a in rows if a["user_id"] in sh or (not a["owner_id"] and a["org_id"] in oo)]
    pre = ag_pre(c, rows, uid) if rows and uid else None
    out = [agent_public(c, a, uid, pre) for a in rows]
    if not any(not a["owner_id"] for a in rows):
        return out
    pn = agent_projects_counts(c, [a["user_id"] for a in rows if not a["owner_id"]])
    for a, d in zip(rows, out):
        if a["owner_id"]:
            continue
        d["shared"] = a["user_id"] in sh
        d["projects"] = pn.get(a["user_id"], 0)  # how many projects it is in: a number, no names
        if not d["shared"]:  # seen only as an organisation member: nothing of its work (what it does, on which task)
            agent_unshared_view(d)
    return out


def agent_unshared_view(d):
    """2.777.0 C (#5378, review F3): agent_public d as a member of a team agent's organisation sees it without a shared project:
    name, picture, online and the number of its projects -- nothing of its work, host, model, rights mode, plan usage, costs or
    contact times (status always "idle"). Used by agents_for and the chat (agents/chat.py agent_chat_get). Changes d, returns it."""
    d.update(shared=False, status="idle", status_text="", status_at=None, status_key="", status_key_at="", status_task=None,
             paused=False, pause_reason="", job_tasks=[], running=0, waiting=0, my_job=False, typing=0, limit_reached=False,
             last_poll_at=None, poll_age=None, contact_age=None, pending_age=None, no_service=False, host=None, runtime_model="", permission_mode="",
             may_set_mode=False, quota=None, cost=None, flows=None, approvals_open=0)
    return d


def agent_shared_by(c, aid, uid):
    """2.777.0 C (#5378, review F2): has person uid THEMSELVES shared a project with agent aid -- they own it or are its admin and
    the agent is a member (a personal agent: only its owner)? Being a member of someone else's project that opens the agent to its
    members (agent_shares) is not enough: the waiting starter plans of uid wake only by uid's own act (schedules.py
    sched_wait_wake). For any account (the watchdog has no request): the agent's own lists, no request filters."""
    from ..agents.admin import agent_owner
    o = agent_owner(c, aid)
    if o is not None:
        return o == uid
    with system_ctx(c):  # the agent's memberships and uid's role in them (structure, nothing is read out)
        return bool(c.execute(f"""SELECT 1 FROM lists l WHERE {otr_live("l")} AND l.is_inbox=0
                                 AND l.id IN (SELECT list_id FROM list_members WHERE user_id=?)
                                 AND (l.owner_id=? OR EXISTS(SELECT 1 FROM list_members m WHERE m.list_id=l.id AND m.user_id=?
                                                             AND m.role IN ('owner','admin'))) LIMIT 1""", (aid, uid, uid)).fetchone())


def ag_pre(c, rows, uid):
    """2.674.0 B (#4194): what agent_public asks per agent, read once for the agents rows of agents_for: their running /
    waiting jobs (the newest 200 each) that uid sees, the unread chat, pictures, last API use, which status tasks uid sees,
    this month's costs, open approval cards, and the viewer's own row for the runtime / colour rights."""
    from ..agents.chat import CHAT_CARD_SQL, choice_state, _jload
    from ..agents.usage import usage_cost_sums
    ids = [a["user_id"] for a in rows]
    q = st_ids(ids)
    u = c.execute("SELECT is_admin, kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
    jobs = c.execute("""SELECT * FROM (SELECT id, agent_id, user_id, task_id, state, row_number() OVER (PARTITION BY agent_id ORDER BY id DESC) AS rn
                        FROM agent_jobs WHERE agent_id = ANY(CAST(? AS BIGINT[])) AND state IN ('running','waiting')) x
                        WHERE rn<=200 ORDER BY agent_id, id DESC""", (q,)).fetchall()
    seen = jobs_seen(c, jobs, uid, u) if u else set()
    by = {}
    for j in jobs:
        if j["id"] in seen:
            by.setdefault(j["agent_id"], []).append(j)
    unread = {r[0]: r[1] for r in c.execute("""SELECT agent_id, COUNT(*) FROM agent_chat WHERE agent_id = ANY(CAST(? AS BIGINT[])) AND user_id=?
                                               AND sender='agent' AND read_at IS NULL GROUP BY agent_id""", (q, uid))}
    avatars = {r["id"]: r for r in c.execute("SELECT id, avatar, kind FROM users WHERE id = ANY(CAST(? AS BIGINT[]))", (q,))}
    used = {r[0]: r[1] for r in c.execute("SELECT user_id, MAX(last_used_at) FROM api_tokens WHERE user_id = ANY(CAST(? AS BIGINT[])) "
                                          "GROUP BY user_id", (q,))}
    age = {}
    for a in rows:  # = agent_contact_age
        last = max([x for x in (a["last_poll_at"], used.get(a["user_id"])) if x] or [None], key=lambda x: x or "")
        age[a["user_id"]] = round((now_utc() - parse_iso(last)).total_seconds()) if last else None
    appr = {}
    for r in c.execute(f"SELECT * FROM agent_chat WHERE agent_id = ANY(CAST(? AS BIGINT[])) AND user_id=? AND {CHAT_CARD_SQL} ORDER BY id", (q, uid)):
        if choice_state(r, _jload(r["choices"]), None) == "open":  # = chat_approvals_open
            appr[r["agent_id"]] = appr.get(r["agent_id"], 0) + 1
    admin = bool(u and u["is_admin"] and not u["disabled"] and (u["kind"] or "user") != "agent")  # = usage.is_admin_id
    oadm = {}

    def color(a):  # = o3b_can_color
        if "owner_id" in a.keys() and a["owner_id"] == uid:
            return True
        if u and u["is_admin"]:
            return True
        org = a["org_id"] if "org_id" in a.keys() else None
        if org and org not in oadm:
            oadm[org] = bool(is_org_admin(c, uid, org))
        return bool(org and oadm[org])
    return {"jobs": by, "unread": unread, "avatars": avatars, "age": age, "appr": appr, "admin": admin, "color": color,
            "tvis": tasks_visible(c, [a["status_task"] for a in rows if a["status_task"]], uid, full=True),
            "cost": usage_cost_sums(c, ids), "pending": agent_pending_ages(c, ids),  # 2.826.0 (#5509)
            "may_rt": lambda a: a["owner_id"] == uid if a["owner_id"] else bool(u and u["is_admin"])}  # = may_set_runtime
