"""2.574.0 (#3376, built in 2.393.0 D): an organisation admin's read-only view of the tasks in the organisation's projects (Settings > Workspaces >
the organisation > Tasks of the organisation), also of projects the admin is not a member of.

Exactly the projects of "Projects of the organisation" (orglists._ol_out / ol_shared): lists of the organisation shared with at least
one more person or open to everyone in it -- never private lists, inboxes, the trash or a project encrypted in the browser
(lists.e2e: the server could not read it anyway), never a health or budget project (2.574.0: they stay with their people, as
for agents). Every read runs in the request's access context (core/access.py AccessCtx: the admin's own organisations, the
row-level policies hold), nothing runs as system. Only reading, only the overview fields (title, state, priority, dates, assignee,
type, points, section; never notes, comments, files or fields), no write route. People only: agents 403, also with admin rights.
Every call is written to the organisation's list log (org_list_log, action "tasks" with the project / "tasksall"), which the
admins see in the history of "Projects of the organisation". A person without an organisation has no such view (404, like every
/api/orgs/<id> route): everything of theirs is their own anyway."""
from flask import jsonify, request

from ..core.config import app
from ..core.srchreg import SRCH_HOOKS  # 2.1026.0 (#5280)
from ..core.i18n import tr
from ..core.db import db, iso, now_utc
from ..accounts.session import me
from ..core.errors import BadInput
from ..core.access import Denied, otr_live
from ..accounts.orgs import _need_org_admin
from ..accounts.orglists import _ol_log, ol_shared


def _ot_names(c, ids):
    """display names of the assignees (the accounts layer may not import collab.comments.user_names)"""
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r["display_name"] or r["username"]
            for r in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q})", ids)}


OT_LIMIT, OT_LIMIT_MAX = 200, 500
OT_STATUS = {0: "open", 2: "done", -1: "wont_do"}  # the names of API v1


def ot_lists(c, oid):
    """The lists of organisation oid whose tasks its admins may read (rows)."""
    rows = c.execute(f"""SELECT * FROM lists WHERE org_id=? AND is_inbox=0 AND {otr_live('')} AND e2e IS NULL
                        AND COALESCE(life, '') NOT IN ('health', 'budget') ORDER BY lower(name), id""", (oid,)).fetchall()
    return [r for r in rows if ol_shared(c, r)]


@app.get("/api/orgs/<int:oid>/tasks")
def oadm_tasks(oid):
    """?list_id= (one project of the overview, else all), status = open (default) | done | all, q = words in the title, limit
    (default 200, at most 500), offset -> {lists: [{id, name, archived}], tasks: [...], total, offset, limit}. Logged."""
    c = db()
    _need_org_admin(c, oid)
    a = request.args
    try:
        lim = min(max(int(a.get("limit") or OT_LIMIT), 1), OT_LIMIT_MAX)
        off = max(int(a.get("offset") or 0), 0)
        lid = int(a["list_id"]) if a.get("list_id") else None
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit / offset / list_id"))
    st = a.get("status") or "open"
    if st not in ("open", "done", "all"):
        raise BadInput(tr("Invalid value: {0}", "status"))
    lists = ot_lists(c, oid)
    by_id = {r["id"]: r for r in lists}
    if lid is not None and lid not in by_id:
        raise Denied(404)  # a private list, another organisation's, an encrypted one: the same answer as a missing one
    ids = [lid] if lid is not None else list(by_id)
    where, args = [f"t.list_id IN ({','.join('?' * len(ids)) or 'NULL'})", "t.deleted_at IS NULL"], list(ids)
    if st == "open":
        where.append("t.status=0")
    elif st == "done":
        where.append("t.status!=0")
    q = (a.get("q") or "").strip()[:200]
    if q:
        # 2.1026.0 (#5280, stage Q6c): the shared search index (core/objsearch.py: a word start, umlauts as ae / oe / ue, a part
        # of the ticket key anywhere) instead of an ILIKE on the title
        ids, x = SRCH_HOOKS["task_ids"](q, names=True)  # the domain layer's index without an upward import
        where.append(f"t.id IN {ids}" if ids else "FALSE")
        args += x
    w = " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM tasks t WHERE {w}", args).fetchone()[0]
    rows = c.execute(f"""SELECT t.id, t.list_id, t.parent_id, t.title, t.status, t.priority, t.due, t.due_time, t.assignee_id, t.ttype,
                                t.points, t.updated_at, t.created_at, s.name AS section
                         FROM tasks t LEFT JOIN sections s ON s.id=t.section_id
                         WHERE {w} ORDER BY t.list_id, t.status, t.priority DESC, t.due IS NULL, t.due, t.id LIMIT ? OFFSET ?""",
                     args + [lim, off]).fetchall()
    names = _ot_names(c, [r["assignee_id"] for r in rows])
    if lid is not None:
        _ol_log(c, oid, by_id[lid], "tasks")
    else:
        c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at) "
                  "SELECT ?, NULL, '', 'tasksall', ?, NULL, NULL, ?", (oid, me(), iso(now_utc())))
    c.commit()
    return jsonify(
        lists=[{"id": r["id"], "name": r["name"], "archived": bool(r["archived"])} for r in lists],
        tasks=[{"id": r["id"], "list_id": r["list_id"], "list_name": by_id[r["list_id"]]["name"], "parent_id": r["parent_id"],
                "title": r["title"], "status": OT_STATUS.get(r["status"], "open"), "priority": r["priority"] or 0, "due": r["due"],
                "due_time": r["due_time"], "assignee_id": r["assignee_id"], "assignee_name": names.get(r["assignee_id"], ""),
                "type": r["ttype"] or None, "points": r["points"], "section": r["section"] or "", "updated_at": r["updated_at"]}
               for r in rows],
        total=total, offset=off, limit=lim, read_only=True)

