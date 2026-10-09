"""Agents: accounts, event queue + long polling, runtime settings, permissions of people towards agents."""
import json
import os
import re
import uuid
import threading
import time
from datetime import timedelta
from flask import g, has_request_context

from ..core.config import app
from ..core.i18n import tr
from ..core.db import inbox_default, iso, now_utc, parse_iso
from ..accounts.session import me
from ..accounts.pictures import avatar_url
from ..core.access import Denied, list_people, list_role, MANAGE_ROLES, need_list, need_task, task_visible, vis_sql, WRITE_ROLES
from ..core.state import visible_sections
from ..tasks.validation import valid_hm
from ..collab.comments import comment_plain, user_names
from ..personal.timetrack import BadInput
from ..notify.alerts import _env_int
from ..api.v1 import act_via, task_for, WH_ON
from ..integrations.webhooks import wh_actor, wh_log, WH_QUEUE_MAX


# ---------------------------------------------------------------- 2.0.0: agents, reactions, shared list tags, tidy
# AGENTS are users of kind 'agent' (users.kind): an AI assistant, a bot, an n8n flow -- anything that works through the
# REST API. An admin creates them (Settings > Users > Agents) or turns an existing user into one. An agent is never an admin,
# never gets Paperless, cannot log in to the web app (only its API tokens work) and sees exactly the lists shared with it
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
# tags (task_tags, per user, unchanged). Members with edit rights create / rename / colour / delete them; participants may
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
                "team_message",  # 2.17.0 (#419): someone @mentioned the agent in a list's team chat
                "task_added",  # 2.23.0 (#795): a task was created in / moved into a list shared with the agent
                "chat_choice",  # 2.28.0 (#1005): the person pressed an answer button of a chat message (message_id, choice_ids)
                "tasks_added",  # 2.29.0 (#1031): many tasks at once (a bulk move / import / script) -> ONE event with their ids
                "missed",  # 2.29.0 (#1031): events older than AGENT_EVENTS_STALE_H, folded into one summary at the next poll
                "stale_tasks",  # 2.34.0 (#266): once a day, the stale tasks of lists with "Agent follows up" on (bundled)
                "scheduled_job",  # 2.34.0 (#272): a planned job of a person is due (agents/schedules.py); answer in their chat
                )
JOB_STATES = ("running", "waiting", "done", "failed", "stopped")
JOB_ACTIONS = ("approve", "reject", "stop")
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
AGENT_JOBS_KEEP = 300                                       # per agent (finished ones beyond are removed)
JOB_LOG_MAX, JOB_TITLE_MAX, AGENT_NOTE_MAX, STATUS_TEXT_MAX = 8000, 200, 2000, 200
CHAT_MAX, CHAT_KEEP = 8000, 1000                            # characters per message, messages per person and agent
AGENT_WAIT_MAX = 60                                         # s: long-polling (GET /api/v1/agent/events?wait=)
AGENT_WAITERS_PER = 2                                       # concurrent long-polls per agent
AGENT_WAITERS_ALL = _env_int("KALMIDO_AGENT_WAITERS", 6)     # ... on the whole server (each holds a server thread)
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


def lst_brief(c, lid):
    r = c.execute("SELECT id, name, is_inbox, agent_tidy, ptype FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return {"id": lid, "name": ""}
    return {"id": r["id"], "name": tr("Inbox") if r["is_inbox"] and inbox_default(r["name"]) else r["name"], "agent_tidy": r["agent_tidy"] or "off",
            "tidy_agent_id": tidy_agent_of(c, lid),  # 2.4.1 (#379)
            # 2.30.0 (#1034): the list's project type and the agents that listen in (new / moved tasks, every comment)
            "project_type": r["ptype"] or None, "listen_agent_ids": listen_agents_of(c, lid)}


# ---- events: queue (polling) + webhook, long-polling wake-up
_AGENT_COND = threading.Condition()
_AGENT_GEN = [0]
_AGENT_WAITERS = {}


def agent_notify():
    with _AGENT_COND:
        _AGENT_GEN[0] += 1
        _AGENT_COND.notify_all()


@app.after_request
def agent_wakeup(resp):
    if has_request_context() and g.pop("agent_wake", False):
        agent_notify()
    return resp


def wh_queue_raw(c, w, env):
    """Queues an agent event for the agent's webhook: the delivery id is the event id, the body the event envelope."""
    if c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (w["id"],)).fetchone()[0] >= WH_QUEUE_MAX:
        wh_log(c, w["id"], env["id"], env["event"], 0, False, None, "dropped", 0)
        return
    c.execute("INSERT INTO webhook_queue(webhook_id,delivery,event,payload,attempt,next_at,created_at) VALUES(?,?,?,?,0,?,?)",
              (w["id"], env["id"], env["event"], json.dumps({**env, "webhook_id": w["id"]}, ensure_ascii=False), time.time(), iso(now_utc())))


def agent_emit(c, aid, event, data, actor="auto"):
    """Records an event for agent aid (the polling queue) and queues its webhook delivery; the caller commits. Nothing for a
    paused / disabled agent or for the agent's own actions. Returns the event's seq or None."""
    a = agent_row(c, aid)
    if not agent_active(a):
        return None
    lid = None
    if isinstance(data, dict):  # 2.22.0 (#663): nothing of a health list ever reaches an agent
        lid = data.get("list_id") or (data.get("task") or {}).get("list_id") or (data.get("list") or {}).get("id") \
            or (data.get("room") or {}).get("list_id")
        if lid and c.execute("SELECT 1 FROM lists WHERE id=? AND life='health'", (lid,)).fetchone():
            return None
        if lid and a["list_ids"]:  # 2.30.0 (#919): an agent limited to selected lists hears nothing of the others
            from ..agents.safety import ids_parse
            if lid not in ids_parse(a["list_ids"]):
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
    ev, ts = str(uuid.uuid4()), iso(now_utc())
    via = (act_via() or "web") if has_request_context() else "web"
    seq = c.execute("INSERT INTO agent_events(agent_id,uuid,event,payload,created_at) VALUES(?,?,?,'{}',?)", (aid, ev, event, ts)).lastrowid
    env = {"id": ev, "seq": seq, "event": event, "created_at": ts, "agent_id": aid, "actor": actor, "via": via, "data": data}
    c.execute("UPDATE agent_events SET payload=? WHERE id=?", (json.dumps(env, ensure_ascii=False), seq))
    if a["webhook_id"] and WH_ON:
        w = c.execute("SELECT * FROM webhooks WHERE id=? AND enabled=1", (a["webhook_id"],)).fetchone()
        if w:
            wh_queue_raw(c, w, env)
    c.execute("""DELETE FROM agent_events WHERE agent_id=? AND (created_at<? OR id<=(SELECT id FROM agent_events WHERE agent_id=?
                 ORDER BY id DESC LIMIT 1 OFFSET ?))""",
              (aid, iso(now_utc() - timedelta(days=AGENT_EVENTS_KEEP_DAYS)), aid, AGENT_EVENTS_KEEP_MAX))
    if has_request_context():
        g.agent_wake = True
    else:
        agent_notify()
    return seq


AGENT_EVENT_COMMENTS = 20     # 2.0.8 (#333): newest comments of the task inside a task event
AGENT_EVENT_COMMENT_CHARS = 2000


def list_sections(c, uid, lid):
    """[{id, name}] of list lid as uid sees it (participants: only sections with a task of theirs), in their order."""
    return [{"id": r["id"], "name": r["name"]} for r in visible_sections(c, uid) if r["list_id"] == lid]


def agent_event_comments(c, tid):
    """The newest AGENT_EVENT_COMMENTS comments of a task, oldest first, text shortened to AGENT_EVENT_COMMENT_CHARS."""
    rows = c.execute("SELECT * FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id DESC LIMIT ?",
                     (tid, AGENT_EVENT_COMMENTS)).fetchall()[::-1]
    names = user_names(c, [r["user_id"] for r in rows])
    ag = agent_ids(c)
    nat = {r[0]: r[1] for r in c.execute("SELECT comment_id, COUNT(*) FROM attachments WHERE task_id=? AND comment_id IS NOT NULL "
                                         "GROUP BY comment_id", (tid,))}
    out = []
    for r in rows:
        txt = comment_plain(c, r["body"])
        d = {"id": r["id"], "author": {"id": r["user_id"], "name": names.get(r["user_id"], ""), "agent": r["user_id"] in ag},
             "text": txt[:AGENT_EVENT_COMMENT_CHARS], "created_at": r["created_at"], "edited_at": r["edited_at"],
             "attachments": nat.get(r["id"], 0)}
        if len(txt) > AGENT_EVENT_COMMENT_CHARS:
            d["truncated"] = True
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
    if full is None:
        full = task_visible(c, tid, aid, full=True)
    if full:
        task["comments"] = agent_event_comments(c, tid)
        task["comments_total"] = c.execute("SELECT COUNT(*) FROM comments WHERE task_id=? AND deleted_at IS NULL", (tid,)).fetchone()[0]
        lst["sections"] = list_sections(c, aid, row["list_id"])
        rp = git_repo_for_task(c, row)  # 2.2.0 (#339): the repository to work in, a branch name, the linked code
        if rp:
            return {"task": task, "list": lst, "repo": rp, **extra}
    return {"task": task, "list": lst, **extra}


def agent_comment(c, k):
    from ..collab.replies import reply_of
    rt, rq = reply_of(c, "c", k)  # 2.33.0 (#1076): the comment answers this one (a short quote)
    return {"id": k["id"], "author_id": k["user_id"], "text": comment_plain(c, k["body"]), "body": k["body"], "created_at": k["created_at"],
            "suggestion": json.loads(k["suggestion"]) if k["suggestion"] else None, "reply_to": rt, "reply": rq}


def agent_comment_events(c, t, cid, mentions, new_mentions, created=True):
    """Comment on task t: 'mention' to newly mentioned agents, 'comment' to agents that follow the task (assignee, creator,
    earlier commenters). Only agents that see the task with its comments."""
    ag = agent_ids(c)
    if not ag:
        return
    k = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    follow = {t["assignee_id"], t["created_by"]} | {r[0] for r in c.execute(
        "SELECT DISTINCT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id!=?", (t["id"], cid))}
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


def agent_assign_event(c, tid, kind, uid):
    if uid and uid in agent_ids(c) and (kind == "unassigned" or task_visible(c, tid, uid, full=True)):
        agent_emit(c, uid, kind, agent_task_data(c, tid, uid))


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
        raise Denied(403, tr("Only the list owner or a list admin can change this"))
    ags = set(list_agents(c, lid))
    bad = [x for x in ids if x not in ags]
    if bad:
        raise BadInput(tr("This agent is not in the list"))
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
        raise Denied(403, tr("Only the list owner or a list admin can change this"))
    for k in ("agent_members", "agent_peers"):
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


_BURST, _BURST_HELD, _BURST_LOCK = {}, {}, threading.Lock()


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
        return len(ts) > AGENT_BURST


def _burst_hold(lid, tid, how, from_lid, source):
    a = _burst_actor()
    with _BURST_LOCK:
        h = _BURST_HELD.setdefault((a["id"], lid), {"actor": a, "ids": [], "how": set(), "from": set(), "source": set()})
        if len(h["ids"]) < AGENT_BURST_IDS:
            h["ids"].append(tid)
        h["n"] = h.get("n", 0) + 1
        h["how"].add(how)
        if from_lid:
            h["from"].add(from_lid)
        if source:
            h["source"].add(source)
        h["last"] = time.monotonic()


def burst_tick(c):
    """Watchdog: one 'tasks_added' per agent of the list for every burst that has been quiet for AGENT_BURST_QUIET_S."""
    now = time.monotonic()
    with _BURST_LOCK:
        ready = [(k, _BURST_HELD.pop(k)) for k, h in list(_BURST_HELD.items()) if now - h["last"] >= AGENT_BURST_QUIET_S]
    sent = 0
    for (_, lid), h in ready:
        if not c.execute("SELECT 1 FROM lists WHERE id=?", (lid,)).fetchone():
            continue
        ids = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE list_id=? AND deleted_at IS NULL AND id IN ({','.join('?' * len(h['ids']))})",
                                       (lid, *h["ids"]))] if h["ids"] else []
        listen = set(listen_agents_of(c, lid))  # 2.30.0 (#1034): only agents that listen in
        for aid in list_agents(c, lid):
            if aid not in listen:
                continue
            mine = [t for t in ids if task_visible(c, t, aid, full=True)]
            if not mine:
                continue
            data = {"list": lst_brief(c, lid), "list_id": lid, "task_ids": mine, "count": len(mine),
                    "how": "moved" if h["how"] == {"moved"} else ("created" if h["how"] == {"created"} else "mixed"),
                    "truncated": h.get("n", 0) > len(h["ids"])}
            if h["source"]:
                data["source"] = sorted(h["source"])[0]
            moved_from = [{"id": f, "name": lst_brief(c, f)["name"]} for f in sorted(h["from"]) if list_role(c, f, aid)]
            if moved_from:
                data["moved_from"] = moved_from
            if agent_emit(c, aid, "tasks_added", data, actor=h["actor"]):
                sent += 1
    c.commit()
    return sent


def agent_added_events(c, tid, from_lid=None, source=None):
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
        _burst_hold(t["list_id"], tid, "moved" if from_lid else "created", from_lid, source)
        return
    for aid in list_agents(c, t["list_id"]):
        if aid not in listen or not task_visible(c, tid, aid, full=True):
            continue
        extra = {"how": "moved" if from_lid else "created"}
        if from_lid and list_role(c, from_lid, aid):
            extra["moved_from"] = {"id": from_lid, "name": lst_brief(c, from_lid)["name"]}
        if source:
            extra["source"] = source
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
    return {"ok": True, "seconds": TASK_EDIT_S}


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
            c.execute("INSERT OR REPLACE INTO tidy_pending(task_id,actor_id,created_at,sent_at) VALUES(?,?,?,?)", (tid, g.user["id"], iso(now_utc()), iso(now_utc())))
            return
        c.execute("INSERT OR REPLACE INTO tidy_pending(task_id,actor_id,created_at,sent_at) VALUES(?,?,?,NULL)", (tid, g.user["id"], iso(now_utc())))


def tidy_tick(c):
    """Watchdog: sends the waiting 'tidy' events of tasks nobody touched for TIDY_QUIET_S and nobody edits right now."""
    now = now_utc()
    quiet = iso(now - timedelta(seconds=TIDY_QUIET_S))
    c.execute("DELETE FROM tidy_pending WHERE sent_at IS NOT NULL AND sent_at<?", (iso(now - timedelta(days=2)),))
    # people changed the task after its event went out (the agent's tidy is refused then): it waits for quiet again and
    # gets a new event, so an agent is never stuck on "try again later"
    c.execute("""UPDATE tidy_pending SET sent_at=NULL, created_at=? WHERE sent_at IS NOT NULL
                 AND (SELECT updated_at FROM tasks WHERE id=tidy_pending.task_id) > sent_at
                 AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.task_id=tidy_pending.task_id AND a.kind='tidy' AND a.created_at>=tidy_pending.sent_at)
                 AND NOT EXISTS (SELECT 1 FROM comments k WHERE k.task_id=tidy_pending.task_id AND COALESCE(k.suggestion,'')!=''
                                 AND k.created_at>=tidy_pending.sent_at)""",
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
RUNTIME_DEFAULTS = {"model": "", "autocompact": True, "autocompact_pct": None, "nightly_reset": "", "permission_mode": ""}
# 2.29.0 (#1029): how the agent's host handles actions outside its allow list: ask = asks the person in the chat every time,
# auto = the host's safety check decides (risky things stay blocked); '' = the host's own default
PERMISSION_MODES = ("", "ask", "auto")


def agent_runtime(a):
    try:
        d = json.loads(a["runtime"] or "{}")
    except (ValueError, TypeError):
        d = {}
    out = {k: d.get(k, v) for k, v in RUNTIME_DEFAULTS.items()}
    out["reset_seq"] = int(a["reset_seq"] or 0)
    return out


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
    return out


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


AGENT_NO_SERVICE_S = 600


def _no_service(c, a):
    """2.26.0 (#933): True when the agent made an API call in the last AGENT_NO_SERVICE_S but polled no events for that long
    (or never) -- "connected, but no service running". Webhook agents: never."""
    if a["webhook_id"]:
        return False
    age = agent_contact_age(c, a)
    if age is None or age > AGENT_NO_SERVICE_S:
        return False
    return not a["last_poll_at"] or (now_utc() - parse_iso(a["last_poll_at"])).total_seconds() > AGENT_NO_SERVICE_S


def agent_typing_to(a, uid):
    """Seconds left of the agent's typing signal to person uid in the chat (0 = none)."""
    if not uid or a["typing_user"] != uid:
        return 0
    return max(0.0, round((a["typing_until"] or 0) - time.time(), 1))


# ---- permissions of people towards agents
def is_approver(c, t, uid):
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or is_agent(u) or u["disabled"] or not task_visible(c, t["id"], uid, full=True):
        return False
    return list_role(c, t["list_id"], uid) in MANAGE_ROLES or t["assignee_id"] == uid or bool(u["is_admin"])


# 2.26.0 (#928): the events a person can only send to an agent where the agent is open to them (agent_usable); the
# others are list automations the list's owner switched on (tidy, task_added) or checked where they start (job_request:
# POST /api/proposals, chat: agent_shares, job: job_may_act). An agent's actions never reach another agent unless the list
# has agent_peers on (every event).
AGENT_GATED = ("mention", "comment", "assigned", "unassigned", "reaction", "team_message", "wake")
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
        return bool(lst["agent_peers"])
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
    return bool(c.execute(f"""SELECT 1 FROM lists l WHERE l.id IN {vis_sql()} AND {_OPEN_SQL} AND (l.owner_id=? OR l.id IN
                              (SELECT list_id FROM list_members WHERE user_id=?)) LIMIT 1""", (aid, aid, uid, aid, uid, uid, uid)).fetchone())


def need_chat_agent(c, aid):
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or not agent_shares(c, aid, me()):
        raise Denied(404)
    return a


def job_dict(c, j, names=None):
    names = names or user_names(c, [j["agent_id"], j["user_id"], j["action_by"]])
    t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (j["task_id"],)).fetchone() if j["task_id"] else None
    return {"id": j["id"], "agent_id": j["agent_id"], "agent_name": names.get(j["agent_id"], ""), "task_id": j["task_id"],
            "task_title": t["title"] if t else None, "list_id": t["list_id"] if t else None, "user_id": j["user_id"],
            "title": j["title"], "state": j["state"], "log": j["log"], "action": j["action"], "action_by": j["action_by"],
            "action_by_name": names.get(j["action_by"], "") if j["action_by"] else "", "action_at": j["action_at"],
            "created_at": j["created_at"], "updated_at": j["updated_at"],
            "kind": j["kind"], "proposal_state": j["prop_state"] or None,  # 2.3.0: proposal jobs
            "approval": bool(j["approval"]) if "approval" in j.keys() else False}  # 2.15.0 (#479): a request waiting for approval


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
    return is_approver(c, t, uid) or (action == "stop" and task_visible(c, t["id"], uid, write=True))


def agent_public(c, a, uid=None):
    """An agent as the people who share lists with it see it: status + their visible running / waiting jobs + unread chat."""
    from ..agents.usage import usage_block
    jobs = c.execute("SELECT * FROM agent_jobs WHERE agent_id=? AND state IN ('running','waiting') ORDER BY id DESC LIMIT 200",
                     (a["user_id"],)).fetchall()
    if uid is not None:
        jobs = [j for j in jobs if job_visible(c, j, uid)]
    unread = c.execute("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND read_at IS NULL",
                       (a["user_id"], uid)).fetchone()[0] if uid else 0
    return {"id": a["user_id"], "username": a["username"], "name": a["display_name"] or a["username"],
            "display_name": a["display_name"] or a["username"],
            # 2.28.0 (#935 / #965): the workspace it works in (null = private) and whose personal agent it is (null = team)
            "org_id": a["org_id"] if "org_id" in a.keys() else None, "owner_id": a["owner_id"] if "owner_id" in a.keys() else None,
            "avatar": avatar_url(c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()),
            "enabled": agent_active(a), "status": a["status"] or "idle", "status_text": a["status_text"] or "", "status_at": a["status_at"],
            # 2.26.0 (#949): paused with a reason (the agent itself, its owner or an admin)
            "paused": a["status"] == "paused", "pause_reason": (a["status_text"] or "") if a["status"] == "paused" else "",
            # 2.0.2: the task it says it works on (only when the viewer may see it) + the tasks of its running jobs
            "status_task": a["status_task"] if a["status_task"] and (uid is None or task_visible(c, a["status_task"], uid, full=True)) else None,
            "job_tasks": sorted({j["task_id"] for j in jobs if j["state"] == "running" and j["task_id"]}),
            "running": sum(1 for j in jobs if j["state"] == "running"), "waiting": sum(1 for j in jobs if j["state"] == "waiting"),
            "chat_unread": unread, "limit_reached": bool(usage_block(c, a["user_id"])),  # 2.1.1 (#326): its hard usage limit
            # 2.4.1 (#375): the chat header: offline (no event poll for 5 minutes; null = cannot tell), its typing signal to
            # the viewer (seconds left), a running job for the viewer
            "online": agent_online(a), "last_poll_at": a["last_poll_at"], "typing": agent_typing_to(a, uid),
            # 2.6.0 (K08): seconds since its last contact (an event poll or any API call with its token; null = never): the
            # app shows "not connected" after 5 minutes without one. A webhook agent is told about events, so for it only
            # "online": false counts
            "webhook": bool(a["webhook_id"]), "contact_age": agent_contact_age(c, a),
            "poll_age": round((now_utc() - parse_iso(a["last_poll_at"])).total_seconds()) if a["last_poll_at"] else None,
            # 2.26.0 (#933): its token is in use (an interactive session) but nothing collects its events -- the setup is not
            # finished until a service (launcher / LaunchAgent / task) keeps polling
            "no_service": _no_service(c, a),
            "my_job": bool(uid) and any(j["state"] == "running" and j["user_id"] == uid for j in jobs),
            # 2.29.0 (#1029): the chat header's badge (Auto / Ask) and whether the viewer may switch it
            "permission_mode": agent_runtime(a)["permission_mode"], "may_set_mode": bool(uid) and may_set_runtime(c, a, uid),
            # 2.32.0 (#1079): what its host reports it really runs with (model as the host names it, the mode of the current
            # run, the host's own default); the runtime's wished model next to it (set: … · runs: …)
            "host": _host_info(a), "runtime_model": agent_runtime(a)["model"],
            # 2.33.0 (#1045): its plan usage (the ring in the chat header; null = never reported)
            "quota": _quota(a),
            # 2.35.0 (#1103): open approval requests + permission questions to the viewer (the badge "1 approval open")
            "approvals_open": _approvals_open(c, a["user_id"], uid)}


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


def agents_for(c, uid):
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    return [agent_public(c, a, uid) for a in rows if agent_shares(c, a["user_id"], uid)]
