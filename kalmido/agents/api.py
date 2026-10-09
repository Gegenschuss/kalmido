"""The REST API of an agent itself (token of an agent account)."""
import json
import time
from datetime import timedelta
from flask import g, jsonify

from ..core.config import app, PUBLIC_URL, TZ
from ..core.i18n import tr
from ..core.db import bump, connect, db, iso, now_utc, parse_iso
from ..accounts.session import GATE
from ..core.access import Denied, task_visible
from ..tasks.validation import as_int
from ..collab.comments import collab_user, lang_of, user_names
from ..collab.news import news_add, notif_ok
from ..personal.timetrack import BadInput, UnknownFields
from ..notify.push import push_prio
from ..api.v1 import v1_args, v1_err, v1_json, v1_view
from ..agents.core import (
    _AGENT_COND, _AGENT_GEN, _AGENT_WAITERS, agent_active, AGENT_EVENTS, AGENT_EVENTS_STALE_H, agent_ids, AGENT_JOBS_KEEP, AGENT_OFFLINE_S,
    AGENT_POLL_WRITE_S, agent_public, agent_row, agent_runtime, agent_shares, AGENT_STATUSES, AGENT_WAIT_MAX,
    AGENT_WAITERS_ALL, AGENT_WAITERS_PER, job_dict, JOB_LOG_MAX, JOB_STATES, JOB_TITLE_MAX, job_visible, need_agent,
    STATUS_TEXT_MAX,
)
from ..agents.chat import chat_delivered, chat_event_mids


# ---- agents: the REST API of the agent itself (token of an agent account)
def agent_self(c, aid):
    from ..agents.usage import usage_state
    a = agent_row(c, aid)
    cur = c.execute("SELECT COALESCE(MAX(id),0) FROM agent_events WHERE agent_id=?", (aid,)).fetchone()[0]
    p = agent_public(c, a)
    return {**p, "note": a["note"] or "", "enabled": agent_active(a), "cursor": cur, "events_cursor": cur,
            "jobs": {"running": p["running"], "waiting": p["waiting"]},
            "webhook": {"configured": bool(a["webhook_id"]),
                        "enabled": bool(a["webhook_id"] and c.execute("SELECT enabled FROM webhooks WHERE id=?", (a["webhook_id"],)).fetchone()[0])},
            "events": list(AGENT_EVENTS), "long_poll_max": AGENT_WAIT_MAX,
            "usage_limit": usage_state(c, a),  # 2.1.1 (#326): where it stands against its limits (None = no limits)
            "runtime": {**agent_runtime(a), "timezone": str(TZ)}}  # 2.4.1 (#377): what the host's launcher applies


@app.get("/api/v1/agent")
@v1_view
def v1_agent():
    v1_args(())
    aid = need_agent()
    return jsonify(agent_self(db(), aid))


@app.put("/api/v1/agent/status")
@v1_view
def v1_agent_status():
    """{status: idle|working|waiting|error, text?, task_id?, model?, permission_mode?, host_permission_mode?} -- shown as the dot on the agent's avatar and in the header chip;
    while "working", the task_id's panel (else every task of its lists) shows "<agent> is working on it" (2.0.2; "is writing
    ..." only with a typing signal since 2.13.2)."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("status", "text", "task_id", "model", "permission_mode", "host_permission_mode"))
    if unknown:
        raise UnknownFields(unknown)
    from ..agents.steps import host_info_in, host_info_set, steps_end
    hinfo = host_info_in(b)  # 2.32.0 (#1079): what the host really runs with (model, permission mode, its default)
    if b.get("status") not in AGENT_STATUSES:
        raise BadInput(tr("Invalid value: {0}", "status"))
    text = b.get("text") or ""
    if not isinstance(text, str) or (b["status"] == "paused" and not text.strip()):  # 2.26.0 (#949): a pause needs its reason
        raise BadInput(tr("Invalid value: {0}", "text"))
    c = db()
    tid = b.get("task_id")
    if tid is not None:
        if isinstance(tid, bool) or not isinstance(tid, int) or not task_visible(c, tid, aid):
            raise BadInput(tr("Invalid value: {0}", "task_id"))
    tid = tid if b["status"] in ("working", "waiting") else None
    old = agent_row(c, aid)
    c.execute("UPDATE agents SET status=?, status_text=?, status_at=?, status_task=? WHERE user_id=?",
              (b["status"], text.strip()[:STATUS_TEXT_MAX], iso(now_utc()), tid, aid))
    hchg = host_info_set(c, old, hinfo)
    if b["status"] in ("idle", "error", "paused"):
        steps_end(c, aid)  # 2.32.0 (#1081): a run without a chat answer leaves no live steps behind
    if hchg or (old["status"], old["status_text"], old["status_task"]) != (b["status"], text.strip()[:STATUS_TEXT_MAX], tid):
        bump(c)  # clients reload only when something visible changed (agents may report often)
    c.commit()
    return jsonify(agent_self(c, aid))


_AGENT_POLLED = {}  # agent id -> monotonic time of the last written poll (2.4.1: at most every AGENT_POLL_WRITE_S)


def agent_poll_mark(c, aid):
    """2.4.1 (#375): remembers the agent's last event poll (the chat shows "offline" after AGENT_OFFLINE_S without one).
    Written at most every AGENT_POLL_WRITE_S; coming back from offline moves the version so the clients update at once."""
    t = time.monotonic()
    if t - _AGENT_POLLED.get(aid, -1e9) < AGENT_POLL_WRITE_S:
        return
    _AGENT_POLLED[aid] = t
    last = c.execute("SELECT last_poll_at FROM agents WHERE user_id=?", (aid,)).fetchone()
    c.execute("UPDATE agents SET last_poll_at=? WHERE user_id=?", (iso(now_utc()), aid))
    if not last or not last[0] or (now_utc() - parse_iso(last[0])).total_seconds() > AGENT_OFFLINE_S:
        bump(c)
    c.commit()


def _agent_events_after(c, aid, since, n):
    """Rows {id, payload} after since. 2.29.0 (#1031): events older than AGENT_EVENTS_STALE_H come as ONE 'missed' summary
    (count per event type, time span; seq = the newest folded event) instead of one by one -- an agent that was offline for
    days or connects for the first time is not flooded; it reads the current state instead (GET /api/v1/... as needed)."""
    out = []
    if AGENT_EVENTS_STALE_H > 0:
        cut = iso(now_utc() - timedelta(hours=AGENT_EVENTS_STALE_H))
        st = c.execute("""SELECT event, COUNT(*), MAX(id), MIN(created_at), MAX(created_at) FROM agent_events
                          WHERE agent_id=? AND id>? AND created_at<? GROUP BY event""", (aid, since, cut)).fetchall()
        if st:
            last = max(r[2] for r in st)
            env = {"id": f"missed-{aid}-{last}", "seq": last, "event": "missed", "created_at": iso(now_utc()), "agent_id": aid,
                   "actor": None, "via": "web",
                   "data": {"count": sum(r[1] for r in st), "events": {r[0]: r[1] for r in st},
                            "from": min(r[3] for r in st), "to": max(r[4] for r in st), "stale_hours": AGENT_EVENTS_STALE_H}}
            out.append({"id": last, "payload": json.dumps(env, ensure_ascii=False)})
            since = last
    return out + c.execute("SELECT id, payload FROM agent_events WHERE agent_id=? AND id>? ORDER BY id LIMIT ?",
                           (aid, since, n - len(out))).fetchall()


def _waiter(aid, on):
    with _AGENT_COND:
        if on:
            if _AGENT_WAITERS.get(aid, 0) >= AGENT_WAITERS_PER or sum(_AGENT_WAITERS.values()) >= AGENT_WAITERS_ALL:
                return False
            _AGENT_WAITERS[aid] = _AGENT_WAITERS.get(aid, 0) + 1
        else:
            _AGENT_WAITERS[aid] = max(0, _AGENT_WAITERS.get(aid, 0) - 1)
            if not _AGENT_WAITERS[aid]:
                _AGENT_WAITERS.pop(aid, None)
        return True


@app.get("/api/v1/agent/events")
@v1_view
def v1_agent_events():
    """Events after ?since=<seq> (oldest first, at most ?limit=). ?wait=1..60: long-polling -- when there is nothing yet the
    request waits until an event arrives or the time is up (no busy loop; the database and the maintenance gate are released
    meanwhile). At most AGENT_WAITERS_PER waiting requests per agent and AGENT_WAITERS_ALL on the server: beyond that the
    answer comes at once with busy: true (poll again later)."""
    a = v1_args(("since", "limit", "wait"))
    aid = need_agent()
    if str(a.get("since", "")).strip().lower() in ("latest", "now"):  # 2.29.0 (#1031): a new poller starts from now
        cur = db().execute("SELECT COALESCE(MAX(id),0) FROM agent_events WHERE agent_id=?", (aid,)).fetchone()[0]
        agent_poll_mark(db(), aid)
        return jsonify(data=[], cursor=cur, has_more=False, busy=False, waited=0.0)
    since = as_int(a.get("since", 0) or 0, "since", 0)
    limit = as_int(a.get("limit", 100), "limit", 1, 500)
    wait = as_int(a.get("wait", 0) or 0, "wait", 0, AGENT_WAIT_MAX)
    agent_poll_mark(db(), aid)
    rows = _agent_events_after(db(), aid, since, limit + 1)
    busy, waited = False, 0.0
    if not rows and wait:
        if not _waiter(aid, True):
            busy = True
        else:
            t0 = time.monotonic()
            try:
                c0 = g.pop("db", None)
                if c0 is not None:
                    c0.close()
                if g.pop("gate", False):
                    GATE.leave()
                while True:
                    with _AGENT_COND:
                        gen = _AGENT_GEN[0]
                    c1 = connect()
                    try:
                        rows = _agent_events_after(c1, aid, since, limit + 1)
                    finally:
                        c1.close()
                    left = wait - (time.monotonic() - t0)
                    if rows or left <= 0 or GATE.maint:
                        break
                    with _AGENT_COND:
                        if _AGENT_GEN[0] == gen:
                            _AGENT_COND.wait(left)
            finally:
                _waiter(aid, False)
                waited = round(time.monotonic() - t0, 1)
            if not GATE.enter(False):
                return v1_err(503, tr("The server is restoring a backup, please try again in a minute"))
            g.gate = True
    more = len(rows) > limit
    rows = rows[:limit]
    data = [json.loads(r["payload"]) for r in rows]
    from ..agents.safety import access_events
    access_events(data)  # 2.30.0 (#919): the lists these events come from count as read in the access log
    mids = chat_event_mids(data)
    if mids:  # 2.7.2 (#422): these chat messages reached the agent
        c2 = db()
        if chat_delivered(c2, aid, mids):
            c2.commit()
    resp = jsonify(data=data, cursor=rows[-1]["id"] if rows else since, has_more=more, busy=busy, waited=waited)
    if busy:
        resp.headers["Retry-After"] = "5"
    return resp


def v1_job_in(c, aid, b, create):
    allowed = ("title", "task_id", "state", "log", "append_log", "user_id")
    unknown = sorted(k for k in b if k not in allowed)
    if unknown:
        raise UnknownFields(unknown)
    f = {}
    if "title" in b or create:
        if not isinstance(b.get("title"), str) or not b["title"].strip():
            raise BadInput(tr("Title missing"))
        f["title"] = b["title"].strip()[:JOB_TITLE_MAX]
    if "state" in b:
        if b["state"] not in JOB_STATES:
            raise BadInput(tr("Invalid value: {0}", "state"))
        f["state"] = b["state"]
    for k in ("log", "append_log"):
        if k in b and not isinstance(b[k], str):
            raise BadInput(tr("Invalid value: {0}", k))
    if create:
        if b.get("task_id") not in (None, ""):
            tid = as_int(b["task_id"], "task_id", 1)
            if not task_visible(c, tid, aid, full=True):
                raise Denied(404)
            f["task_id"] = tid
        if b.get("user_id") not in (None, ""):
            uid = as_int(b["user_id"], "user_id", 1)
            u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
            if not u or u["kind"] == "agent" or not agent_shares(c, aid, uid):
                raise BadInput(tr("Invalid value: {0}", "user_id"))
            f["user_id"] = uid
    elif "task_id" in b or "user_id" in b:
        raise UnknownFields([k for k in ("task_id", "user_id") if k in b])
    return f


@app.get("/api/v1/agent/jobs")
@v1_view
def v1_agent_jobs():
    a = v1_args(("state",))
    aid = need_agent()
    c = db()
    st = a.get("state", "all")
    if st not in ("all", "open", *JOB_STATES):
        raise BadInput(tr("Invalid value: {0}", "state"))
    q = "SELECT * FROM agent_jobs WHERE agent_id=?" + \
        ("" if st == "all" else " AND state IN ('running','waiting')" if st == "open" else " AND state=?")
    rows = c.execute(q + " ORDER BY id DESC LIMIT 200", (aid,) if st in ("all", "open") else (aid, st)).fetchall()
    return jsonify(data=[job_dict(c, j) for j in rows], next_cursor=None)


@app.post("/api/v1/agent/jobs")
@v1_view
def v1_agent_job_create():
    """{title, task_id?, state? (running), log?, user_id?} -- a job shown in the Agents tab (and linked to the task)."""
    v1_args(())
    aid = need_agent()
    c = db()
    b = v1_json()
    f = v1_job_in(c, aid, b, True)
    ts = iso(now_utc())
    log = (b.get("log") or b.get("append_log") or "")[-JOB_LOG_MAX:]
    jid = c.execute("""INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (aid, f.get("task_id"), f.get("user_id"), f["title"], f.get("state", "running"), log, ts, ts)).lastrowid
    c.execute("""DELETE FROM agent_jobs WHERE agent_id=? AND state NOT IN ('running','waiting') AND id<=(SELECT id FROM agent_jobs
                 WHERE agent_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)""", (aid, aid, AGENT_JOBS_KEEP))
    job_notify(c, c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone(), None)
    if log:
        from ..agents.steps import steps_job_log
        steps_job_log(c, c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone(), log)  # 2.32.0 (#1081)
    bump(c)
    c.commit()
    return jsonify(job_dict(c, c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone())), 201


def job_notify(c, j, old_state):
    """A job that starts waiting for approval: push to the person it is for (else the task's assignee), once per change."""
    if j["state"] != "waiting" or old_state == "waiting":
        return
    uid = j["user_id"]
    if not uid and j["task_id"]:
        t = c.execute("SELECT assignee_id, created_by FROM tasks WHERE id=?", (j["task_id"],)).fetchone()
        uid = t and (t["assignee_id"] if t["assignee_id"] not in agent_ids(c) else None) or (t and t["created_by"])
    if not uid or uid in agent_ids(c):
        return
    s = collab_user(c, uid, None)
    if not s or not job_visible(c, j, uid):
        return
    lid = None
    if j["task_id"]:  # 2.1.0 (#317): "agent waits for me" as News (off by default) + the push per the settings
        lr = c.execute("SELECT list_id FROM tasks WHERE id=?", (j["task_id"],)).fetchone()
        lid = lr[0] if lr else None
        news_add(c, uid, "approval", task_id=j["task_id"], data={"title": (j["title"] or "")[:200]}, actor=j["agent_id"], s=s)
    if not notif_ok(c, uid, s, "approval", "push", lid):
        return
    lg = lang_of(s)
    name = user_names(c, [j["agent_id"]]).get(j["agent_id"], "?")
    g.pushes.append((uid, tr("{0} is waiting for your approval", name, lg=lg), j["title"],
                     f"{PUBLIC_URL}/#t/{j['task_id']}" if j["task_id"] else f"{PUBLIC_URL}/#agents", push_prio(s)))


@app.patch("/api/v1/agent/jobs/<int:jid>")
@v1_view
def v1_agent_job_update(jid):
    """{title?, state?, log? (replaces), append_log? (adds a line)}"""
    v1_args(())
    aid = need_agent()
    c = db()
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
    if not j:
        raise Denied(404)
    if j["approval"]:  # 2.15.0 (#479): a request waiting for approval: its title and state belong to the server
        raise Denied(409, tr("A request waiting for approval cannot be changed"))
    b = v1_json()
    f = v1_job_in(c, aid, b, False)
    log = j["log"] or ""
    if "log" in b:
        log = b["log"]
    if b.get("append_log"):
        log = (log + ("\n" if log else "") + b["append_log"])
    f["log"] = log[-JOB_LOG_MAX:]
    f["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE agent_jobs SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), jid])
    j2 = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    if b.get("append_log"):  # 2.32.0 (#1081): a progress line is a heading of the job's history
        from ..agents.steps import steps_job_log
        steps_job_log(c, j2, b["append_log"])
    job_notify(c, j2, j["state"])
    if (j2["state"], j2["title"]) != (j["state"], j["title"]):
        bump(c)  # a log line alone does not make every client reload
    c.commit()
    return jsonify(job_dict(c, j2))
