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
                "task_added")  # 2.23.0 (#795): a task was created in / moved into a list shared with the agent
JOB_STATES = ("running", "waiting", "done", "failed", "stopped")
JOB_ACTIONS = ("approve", "reject", "stop")
REACTIONS = ("up", "down", "heart")   # the fixed set; any other single emoji is stored as itself
REACTION_ALIASES = {**{k: k for k in REACTIONS}, "+1": "up", "-1": "down", "\U0001f44d": "up", "\U0001f44e": "down",
                    "\u2764\ufe0f": "heart", "\u2764": "heart"}
TIDY_MODES = ("off", "suggest", "auto")
AGENT_EVENTS_KEEP_DAYS, AGENT_EVENTS_KEEP_MAX = 30, 1000   # per agent
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
    r = c.execute("SELECT id, name, is_inbox, agent_tidy FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return {"id": lid, "name": ""}
    return {"id": r["id"], "name": tr("Inbox") if r["is_inbox"] and inbox_default(r["name"]) else r["name"], "agent_tidy": r["agent_tidy"] or "off",
            "tidy_agent_id": tidy_agent_of(c, lid)}  # 2.4.1 (#379)


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
    return {"id": k["id"], "author_id": k["user_id"], "text": comment_plain(c, k["body"]), "body": k["body"], "created_at": k["created_at"],
            "suggestion": json.loads(k["suggestion"]) if k["suggestion"] else None}


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


def listen_ids(raw, tidy_mode, tidy_agent, agents):
    """2.13.1 (#471): lists.agent_listen -> the agent ids (sorted) among `agents` (the list's agents). NULL = the default:
    the tidy agent while tidying is on."""
    if raw is None:
        ids = {tidy_agent} if tidy_agent and (tidy_mode or "off") != "off" else set()
    else:
        ids = {int(x) for x in str(raw).split(",") if x.strip().isdigit()}
    return sorted(i for i in ids if i in agents)


def listen_agents_of(c, lid):
    r = c.execute("SELECT agent_listen, agent_tidy FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return []
    ags = set(list_agents(c, lid))
    return listen_ids(r["agent_listen"], r["agent_tidy"], tidy_agent_of(c, lid) if r["agent_listen"] is None else None, ags)


def list_listen_update(c, lid, ids):
    """2.13.1 (#471): "Agent reads every comment" -- owner / list admins (agent-owned list: its members with edit rights);
    never an agent. ids: agents of the list ([] = nobody)."""
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
    c.execute("UPDATE lists SET agent_listen=? WHERE id=?", (",".join(str(x) for x in sorted(set(ids))), lid))


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


def agent_added_events(c, tid, from_lid=None, source=None):
    """2.23.0 (#795): a top-level task was created in (from_lid None) or moved into (from_lid = the list it came from) a list:
    'task_added' to every agent of that list that sees the task (the agent's own actions excluded by agent_emit). moved_from
    {id, name} only when the agent may see the list it came from; source: 'form' / 'mail' / 'errors' / 'capture' ..."""
    ag = agent_ids(c)
    if not ag:
        return
    t = c.execute("SELECT id, list_id, parent_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["parent_id"] or t["deleted_at"] or t["list_id"] == from_lid:
        return
    for aid in list_agents(c, t["list_id"]):
        if not task_visible(c, tid, aid, full=True):
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


def agent_tidy_events(c, tid):
    """A new top-level task by a person in a list with tidy on: 'tidy' to the list's tidy agent (2.4.1: only that one),
    2.27.0 (#999): once the task is left alone (tidy_tick)."""
    t = c.execute("SELECT t.*, l.agent_tidy FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    if not t or t["parent_id"] or (t["agent_tidy"] or "off") == "off" or is_agent(g.user):
        return
    aid = tidy_agent_of(c, t["list_id"])
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
RUNTIME_DEFAULTS = {"model": "", "autocompact": True, "autocompact_pct": None, "nightly_reset": ""}


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
    return out


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
    if u["is_admin"]:
        return True
    return bool(c.execute(f"SELECT 1 FROM lists l WHERE l.id=? AND {_OPEN_SQL}", (lid, uid, aid, uid)).fetchone())


def agent_shares(c, aid, uid):
    """Does uid share a list with agent aid (or is uid an admin)? 2.7.2 (#420): a personal agent only with its owner.
    2.26.0 (#928): only lists open to uid for their agents count (see _OPEN_SQL; default: owner and list admins)."""
    from ..agents.admin import agent_owner
    o = agent_owner(c, aid)
    if o is not None:
        return o == uid
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if u and u["is_admin"]:
        return True
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
    if u["is_admin"] or j["user_id"] == uid:
        return True
    return bool(j["task_id"]) and task_visible(c, j["task_id"], uid, full=True)


def job_may_act(c, j, uid, action):
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kind"] == "agent":
        return False
    if u["is_admin"] or j["user_id"] == uid:
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
            "my_job": bool(uid) and any(j["state"] == "running" and j["user_id"] == uid for j in jobs)}


def agents_for(c, uid):
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    return [agent_public(c, a, uid) for a in rows if agent_shares(c, a["user_id"], uid)]
