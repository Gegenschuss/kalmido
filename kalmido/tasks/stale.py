"""2.34.0 (#266): stale tasks ("Liegt") -- open tasks nobody touched for a while, and tasks waiting on someone without a
follow-up day. Pure data: the app shows them (smart view "Stale"), the agent API / MCP reads them, and the agents of lists
with "Agent follows up" (lists.agent_followup) get ONE bundled event stale_tasks a day (see stale_events)."""
import os
from datetime import date

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import db, inbox_default, local_now, now_utc
from ..core.i18n import tr
from ..core.access import Denied, MANAGE_ROLES, WRITE_ROLES, list_role, need_list, tvis, vis_sql
from ..accounts.session import me
from ..api.v1 import v1_args, v1_view

# A task counts as stale after this many days without a change, comment or time entry (per list: lists.stale_days,
# NULL = this default, 0 = the list never has stale tasks).
STALE_DAYS = 7
STALE_DAYS_MAX = 365
STALE_LIMIT_MAX = 200

# The newest sign of life of a task: its own change, a comment, a time entry on it.
_LAST_SQL = """MAX(t.updated_at,
                   COALESCE((SELECT MAX(cm.created_at) FROM comments cm WHERE cm.task_id=t.id AND cm.deleted_at IS NULL), ''),
                   COALESCE((SELECT MAX(te.updated_at) FROM time_entries te WHERE te.task_id=t.id), ''))"""


def stale_tasks(c, uid, *, lids=None, limit=50, days=None):
    """The stale tasks uid may see, the longest idle first: [{id, title, list_id, list_name, idle_days, reason, since,
    due, assignee_id, wait_note}]. reason: "waiting" (waiting on external without a follow-up day ahead) or "no_change".
    Only open, top-level, ordinary tasks (no milestones, no family / home & life lists or entries, nothing due or
    starting later, no repeating ones) in lists that are not archived. lids: only these lists (still only the visible
    ones). days: overrides every list's own threshold (1..STALE_DAYS_MAX)."""
    try:
        limit = max(1, min(STALE_LIMIT_MAX, int(limit or 50)))
    except (TypeError, ValueError):
        limit = 50
    today = local_now().date().isoformat()
    args = [uid, uid]
    where = ""
    if lids is not None:
        ids = sorted({int(x) for x in lids if str(x).lstrip("-").isdigit()})
        if not ids:
            return []
        where += f" AND t.list_id IN ({','.join(str(i) for i in ids)})"
    if days is not None:
        thr = "?"
        args_thr = [max(1, min(STALE_DAYS_MAX, int(days)))]
    else:
        thr = "COALESCE(l.stale_days, ?)"
        args_thr = [STALE_DAYS]
    rows = c.execute(f"""
        SELECT * FROM (
          SELECT t.id, t.title, t.list_id, l.name AS list_name, l.is_inbox, t.due, t.assignee_id, t.waiting_at,
                 t.wait_note, t.wait_until, {_LAST_SQL} AS last, {thr} AS thr
          FROM tasks t JOIN lists l ON l.id=t.list_id
          WHERE t.status=0 AND t.deleted_at IS NULL AND t.parent_id IS NULL AND t.ms=0 AND t.fam='' AND t.repeat=''
            AND l.archived=0 AND l.family='' AND l.life=''
            AND (t.due IS NULL OR substr(t.due,1,10)<=?) AND (t.start IS NULL OR t.start='' OR substr(t.start,1,10)<=?)
            AND (t.waiting_at IS NULL OR t.wait_until IS NULL OR t.wait_until<?)
            AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.')}{where})
        WHERE thr>0 AND julianday('now') - julianday(substr(last,1,19)) >= thr
        ORDER BY last, id LIMIT ?""", args_thr + [today, today, today] + args + [limit]).fetchall()
    now = now_utc()
    out = []
    for r in rows:
        try:
            idle = max(0, (now.date() - date.fromisoformat(r["last"][:10])).days)
        except ValueError:
            idle = 0
        out.append({"id": r["id"], "title": r["title"], "list_id": r["list_id"],
                    "list_name": tr("Inbox") if r["is_inbox"] and inbox_default(r["list_name"]) else r["list_name"],
                    "idle_days": idle, "reason": "waiting" if r["waiting_at"] else "no_change",
                    "since": r["last"], "due": r["due"], "assignee_id": r["assignee_id"],
                    "wait_note": r["wait_note"] if r["waiting_at"] else ""})
    return out



STALE_EVENT_MAX = 30     # tasks in one stale_tasks event (the agent reads more with GET /api/v1/stale)
STALE_EVENT_HOUR = (os.environ.get("KALMIDO_STALE_HOUR") or "09:00").strip()  # local time from which the day's event goes out
STALE_HINT = ("These tasks have been lying idle. For each one you can help, write ONE short, friendly follow-up as a comment on "
              "the task: a question to the person in charge, or a reminder text they could send (for a task waiting on someone "
              "outside: a draft message to them). Ask before doing more. Never contact anyone outside the app yourself.")


def _int_or_none(v, name, lo, hi):
    from ..personal.timetrack import BadInput
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None
    if not lo <= n <= hi:
        raise BadInput(tr("Invalid value: {0}", name))
    return n


def list_stale_update(c, lid, b):
    """PATCH /api/lists/<lid> {stale_days?, agent_followup?}: the list's owner or a list admin (a list that belongs to an
    agent: its members with edit rights); never an agent (it would switch on its own events). BadInput / Denied."""
    from ..personal.timetrack import BadInput
    from ..agents.core import agent_ids, is_agent
    role = need_list(c, lid, write=False)
    owner = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if is_agent(g.user) or not (role in MANAGE_ROLES or (owner in agent_ids(c) and role in WRITE_ROLES)):
        raise Denied(403, tr("Only the list owner or a list admin can change this"))
    if "stale_days" in b:
        c.execute("UPDATE lists SET stale_days=? WHERE id=?", (_int_or_none(b["stale_days"], "stale_days", 0, STALE_DAYS_MAX), lid))
    if "agent_followup" in b:
        if not isinstance(b["agent_followup"], bool) and b["agent_followup"] not in (0, 1):
            raise BadInput(tr("Invalid value: {0}", "agent_followup"))
        c.execute("UPDATE lists SET agent_followup=? WHERE id=?", (int(bool(b["agent_followup"])), lid))


def stale_query(c, uid, a):
    """The shared part of GET /api/stale and GET /api/v1/stale: ?list_id= (a list uid sees, else 404), ?days=, ?limit=."""
    from ..personal.timetrack import BadInput
    lids = None
    if a.get("list_id"):
        lid = _int_or_none(a.get("list_id"), "list_id", 1, 2 ** 62)
        if not list_role(c, lid, uid):
            raise Denied(404)
        lids = [lid]
    days = _int_or_none(a.get("days"), "days", 1, STALE_DAYS_MAX)
    try:
        limit = int(a.get("limit") or 50)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit")) from None
    items = stale_tasks(c, uid, lids=lids, limit=limit, days=days)
    return {"tasks": items, "count": len(items), "default_days": STALE_DAYS}


@app.get("/api/stale")
def stale_get():
    """2.34.0 (#266): the app's view "Stale" (smart list) / a list's stale tasks."""
    return jsonify(stale_query(db(), me(), request.args))


@app.get("/api/v1/stale")
@v1_view
def v1_stale():
    """2.34.0 (#266): the agent API's "read stale tasks" (only lists the token's user sees -- an agent: lists shared with it)."""
    return jsonify(stale_query(db(), me(), v1_args(("list_id", "days", "limit"))))


def _wd_stale(c, now):
    """Once a day (from STALE_EVENT_HOUR on): every active agent with stale tasks in lists that have "Agent follows up" on
    and that it may see gets ONE event stale_tasks (at most STALE_EVENT_MAX tasks, the longest idle first)."""
    from ..agents.core import agent_active, agent_emit, agent_row
    from ..agents.safety import ids_parse
    if now.strftime("%H:%M") < STALE_EVENT_HOUR:
        return
    today = now.date().isoformat()
    rows = c.execute("""SELECT DISTINCT a.user_id FROM agents a JOIN users u ON u.id=a.user_id AND u.kind='agent'
                        WHERE a.enabled=1 AND u.disabled=0 AND a.stale_sent!=?""", (today,)).fetchall()
    for (aid,) in rows:
        lids = [r[0] for r in c.execute(f"""SELECT id FROM lists WHERE agent_followup=1 AND archived=0 AND life=''
                                             AND id IN {vis_sql()}""", (aid, aid))]
        a = agent_row(c, aid)
        if a is not None and a["list_ids"]:
            allowed = set(ids_parse(a["list_ids"]))
            lids = [x for x in lids if x in allowed]
        if not lids:
            continue  # nothing switched on: look again at the next tick (a list may switch it on later today)
        c.execute("UPDATE agents SET stale_sent=? WHERE user_id=?", (today, aid))
        if agent_active(a):
            items = stale_tasks(c, aid, lids=lids, limit=STALE_EVENT_MAX)
            if items:
                names = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM lists WHERE id IN ({','.join(str(int(x)) for x in lids)})")}
                used = sorted({t["list_id"] for t in items})
                agent_emit(c, aid, "stale_tasks", {"tasks": items, "count": len(items), "default_days": STALE_DAYS,
                                                   "lists": [{"id": x, "name": names.get(x, "")} for x in used],
                                                   "hint": STALE_HINT}, actor=None)
        c.commit()


def stale_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """OpenAPI of GET /api/v1/stale (2.34.0, #266)."""
    schemas["StaleTask"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "list_name": {"type": "string"},
        "idle_days": {"type": "integer", "description": "Days since the last change, comment or time entry"},
        "reason": {"type": "string", "enum": ["no_change", "waiting"],
                   "description": "waiting = waiting on someone outside without a follow-up day ahead; no_change = nobody touched it"},
        "since": {"type": "string", "format": "date-time", "description": "The last sign of life (UTC)"},
        "due": nul("string", format="date"), "assignee_id": nul("integer"),
        "wait_note": {"type": "string", "description": "Who / what it waits for (reason waiting)"}}}
    paths["/stale"] = {"get": op(
        "Stale tasks: open tasks nobody touched for a while (longest idle first)", "Tasks",
        ok({"type": "object", "properties": {"tasks": {"type": "array", "items": ref("StaleTask")}, "count": {"type": "integer"},
                                             "default_days": {"type": "integer"}}}) | errs("400", "404"),
        [q("list_id", "Only this list", {"type": "integer"}),
         q("days", f"Idle for at least this many days (1-{STALE_DAYS_MAX}; default: each list's own setting, else {STALE_DAYS})",
           {"type": "integer", "minimum": 1, "maximum": STALE_DAYS_MAX}),
         q("limit", f"At most this many (1-{STALE_LIMIT_MAX}, default 50)", {"type": "integer", "minimum": 1, "maximum": STALE_LIMIT_MAX})],
        desc="2.34.0 (#266). Only open top-level tasks you can see (an agent: in lists shared with it), without milestones, repeating "
             "tasks, family / home & life lists and tasks due or starting later. A task waiting on someone with a follow-up day "
             "ahead is not stale (it gets followup_due). The agents of lists with \"Agent follows up\" get these once a day as "
             "the event stale_tasks. Nothing is ever sent to anyone outside.")}
