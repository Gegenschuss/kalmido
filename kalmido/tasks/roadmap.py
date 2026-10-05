"""The roadmap and shifting a list's dates (dependent tasks move along)."""
import json
from datetime import date, timedelta
from flask import jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, local_now, usettings
from ..accounts.session import me
from ..core.access import need_list, tvis, vis_sql, WRITE_ROLES
from ..core.state import visible_lists
from ..tasks.validation import as_int
from ..tasks.tasks import dep_shift


# ---------------------------------------------------------------- roadmap (package D3)
# "All" as a timeline: every visible, not archived list with its dated tasks, lists grouped by folder, a summary span
# per list (earliest start -- or due without a start -- to the latest due of its OPEN dated tasks; every such task,
# not only the ones inside the requested window) and the list progress (same numbers as the project progress).
# POST /api/lists/<id>/shift moves every open dated task of a list (subtasks too) by the same number of days in one
# transaction: start and due, so durations stay; tasks without a date stay where they are. Edit rights on the list.
# Moving LATER also moves dependent tasks in other lists along, but only where that list has "Move dependent tasks
# along" on (dep_shift: same rules and caps as a single task). More than SHIFT_MAX_TASKS dated tasks: refused.
SHIFT_MAX_TASKS, SHIFT_MAX_DAYS, ROADMAP_MAX_DAYS = 500, 3650, 1100


def _flag(v, what):
    from ..personal.timetrack import BadInput
    if v in (None, ""):
        return False
    if str(v).lower() in ("1", "true", "yes"):
        return True
    if str(v).lower() in ("0", "false", "no"):
        return False
    raise BadInput(tr("Invalid value: {0}", what))


def roadmap_build(c, uid, a):
    """a: the query args (from, to, projects_only, include_done). The JSON of GET /api/roadmap and /api/v1/roadmap."""
    from ..personal.timetrack import BadInput
    from ..api.v1 import PRIO_NAMES, STATUS_NAMES, v1_list
    t0 = local_now().date()
    try:
        lo = date.fromisoformat(a["from"]) if a.get("from") else t0 - timedelta(days=14)
        hi = date.fromisoformat(a["to"]) if a.get("to") else lo + timedelta(days=194)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "from/to")) from None
    if hi < lo or (hi - lo).days > ROADMAP_MAX_DAYS:
        raise BadInput(tr("Date range too large"))
    po, inc = _flag(a.get("projects_only"), "projects_only"), _flag(a.get("include_done"), "include_done")
    lists = [d for d in visible_lists(c, uid) if not d["archived"] and (not po or d.get("kind") == "project")]
    try:
        order = [f for f in json.loads(usettings(c, uid).get("folders") or "[]") if isinstance(f, str) and f]
    except ValueError:
        order = []
    folders = list(dict.fromkeys(order + [d["folder"] for d in lists if d["folder"] and not d["is_inbox"]]))
    rank = {f: i for i, f in enumerate(folders)}
    lists.sort(key=lambda d: (-d["is_inbox"], 0 if d["is_inbox"] or not d["folder"] else 1 + rank[d["folder"]], d["sort"], d["id"]))
    folders = [f for f in folders if any(d["folder"] == f and not d["is_inbox"] for d in lists)]
    ids = [d["id"] for d in lists]
    spans, undated, tasks, deps = {}, {}, {}, []
    if ids:
        q = ",".join("?" * len(ids))
        tv = tvis(c, uid)
        for r in c.execute(f"""SELECT list_id, MIN(COALESCE(start, due)) AS s, MAX(due) AS e, COUNT(*) AS n FROM tasks
                               WHERE list_id IN ({q}) AND {tv} AND status=0 AND deleted_at IS NULL AND due IS NOT NULL GROUP BY list_id""", ids):
            spans[r["list_id"]] = r
        undated = dict(c.execute(f"""SELECT list_id, COUNT(*) FROM tasks WHERE list_id IN ({q}) AND {tv} AND status=0 AND deleted_at IS NULL
                                     AND due IS NULL GROUP BY list_id""", ids).fetchall())
        st = "status IN (0, 2)" if inc else "status=0"
        rows = c.execute(f"""SELECT id, list_id, parent_id, title, start, due, status, priority, assignee_id FROM tasks
                             WHERE list_id IN ({q}) AND {tv} AND deleted_at IS NULL AND {st} AND due IS NOT NULL AND due>=?
                             AND COALESCE(start, due)<=? ORDER BY COALESCE(start, due), due, id""", [*ids, lo.isoformat(), hi.isoformat()]).fetchall()
        for r in rows:
            tasks.setdefault(r["list_id"], []).append({"id": r["id"], "parent_id": r["parent_id"], "title": r["title"], "start": r["start"],
                                                       "due": r["due"], "status": STATUS_NAMES.get(r["status"], "open"),
                                                       "priority": PRIO_NAMES.get(r["priority"], "none"), "assignee_id": r["assignee_id"]})
        tids = [r["id"] for r in rows]
        for i in range(0, len(tids), 900):
            part = tids[i:i + 900]
            deps += [{"task_id": r[0], "blocker_id": r[1]} for r in c.execute(
                f"""SELECT d.task_id, d.blocker_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                    WHERE d.task_id IN ({','.join('?' * len(part))}) AND b.deleted_at IS NULL AND b.list_id IN {vis_sql()}
                    AND {tvis(c, uid, "b.")}
                    ORDER BY d.task_id, d.blocker_id""", [*part, uid, uid])]
    groups = []
    for d in lists:
        sp = spans.get(d["id"])
        groups.append({"list": v1_list(d), "folder": "" if d["is_inbox"] else d["folder"] or "",
                       "span": {"start": sp["s"], "end": sp["e"]} if sp else None, "open_dated": sp["n"] if sp else 0,
                       "undated": undated.get(d["id"], 0), "can_edit": d["role"] in WRITE_ROLES, "tasks": tasks.get(d["id"], [])})
    return {"from": lo.isoformat(), "to": hi.isoformat(), "projects_only": po, "folders": folders, "groups": groups, "deps": deps}


@app.get("/api/roadmap")
def roadmap():
    return jsonify(roadmap_build(db(), me(), request.args))


@app.post("/api/lists/<int:lid>/shift")
def list_shift(lid):
    """{days}: every open dated task of the list moves by that many days (see "roadmap"). One transaction."""
    from ..tasks.lifecycle import apply_update
    b = body()
    c = db()
    need_list(c, lid)  # unknown / not visible: 404, view only: 403
    days = as_int(b.get("days"), "days", -SHIFT_MAX_DAYS, SHIFT_MAX_DAYS)
    if not days:
        return err(tr("Invalid value: {0}", "days"))
    rows = c.execute("""SELECT id, title, start, due FROM tasks WHERE list_id=? AND status=0 AND deleted_at IS NULL
                        AND due IS NOT NULL ORDER BY id""", (lid,)).fetchall()
    if len(rows) > SHIFT_MAX_TASKS:
        return err(tr("This list has {0} tasks with a date, at most {1} can be moved at once", len(rows), SHIFT_MAX_TASKS), 409)
    plan = []
    for r in rows:  # every new date first: nothing is written when one of them is out of range
        try:
            plan.append((r, (date.fromisoformat(r["due"]) + timedelta(days=days)).isoformat(),
                         (date.fromisoformat(r["start"]) + timedelta(days=days)).isoformat() if r["start"] else None))
        except (ValueError, OverflowError):
            return err(tr("Invalid value: {0}", "days"))
    moved, shifted = [], []
    for r, nd, ns in plan:
        e = apply_update(c, r["id"], {"due": nd, "start": ns})
        if e:
            c.rollback()
            return err(e)
        moved.append({"id": r["id"], "title": r["title"], "start": ns, "due": nd, "prev_start": r["start"], "prev_due": r["due"]})
    if days > 0:
        seen = {r["id"] for r in rows}
        for m in moved:
            dep_shift(c, m["id"], m["prev_due"], m["due"], seen=seen, moved=shifted)
    if moved:
        bump(c)
    c.commit()
    return jsonify(ok=True, count=len(moved), days=days, moved=moved, shifted=shifted)
