"""2.40.0 (#1344): "My tasks" in the person's own order (table user_task_order: user_id, task_id, pos).

Personal: it never changes tasks.sort (a shared list keeps its order for everyone), nobody else sees it, agents have none.
The web app sends the whole order after a drag (PUT /api/tasks/mine-order, queued offline like the other task writes); a task
without a row (new, or newly assigned and not yet placed) stands above the placed ones. /api/state carries it as mine_order."""
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, write_lock
from ..core.access import Denied, tvis, vis_sql
from ..accounts.session import me

VW_MINE_MAX = 5000  # tasks in one order (more are cut: the oldest placed ones fall back to "not placed")


def vw_mine_order(c, uid):
    """{task id (str): pos} of the person's own order of "My tasks" (for /api/state)."""
    # 2.82.0 (#1464): only tasks the person still sees (a row of a list they left / were removed from stays hidden)
    return {str(r[0]): r[1] for r in c.execute(
        f"SELECT o.task_id, o.pos FROM user_task_order o JOIN tasks t ON t.id=o.task_id WHERE o.user_id=? "
        f"AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.')}", (uid, uid, uid))}


@app.put("/api/tasks/mine-order")
def vw_mine_order_put():
    """{ids: [task ids, top first]} replaces the signed-in person's order of "My tasks". Ids of tasks the person cannot see
    (or that do not exist) are skipped. Agents have no own order (403)."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("The own order of My tasks belongs to a person"))
    ids = (body() or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return jsonify(error=tr("Invalid value: {0}", "ids")), 400
    ids = [x for x in dict.fromkeys(ids) if 0 < x < 10 ** 12][:VW_MINE_MAX]
    c = db()
    uid = me()
    ok = set()
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        ok |= {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND list_id IN {vis_sql()} AND {tvis(c, uid)}",
                                       (*part, uid, uid))}
    write_lock(c, f"mine-order-{uid}")
    c.execute("DELETE FROM user_task_order WHERE user_id=?", (uid,))
    rows = [(uid, t, n) for n, t in enumerate(x for x in ids if x in ok)]
    if rows:
        c.executemany("INSERT INTO user_task_order(user_id, task_id, pos) VALUES(?,?,?)", rows)
    bump(c)
    c.commit()
    return jsonify(ok=True, count=len(rows))


# ---- 2.41.0 (#1365): "Show in My tasks" per person and list (table list_mine_hide: a row = switched off). The tasks of such a
# list move into the folded group "Hidden" at the end of "My tasks" (the web app decides that, from /api/state mine_hidden);
# assigned tasks of such a list due today or overdue stay visible in a small line of their own. Nothing changes for the
# list's other members, the tasks or the other views.
def mt_mine_hidden(c, uid):
    """Ids of the lists the person switched off for "My tasks" (only lists the person still sees)."""
    return [r[0] for r in c.execute(f"SELECT list_id FROM list_mine_hide WHERE user_id=? AND list_id IN {vis_sql()} ORDER BY list_id",
                                    (uid, uid, uid))]


@app.put("/api/lists/<int:lid>/in-mine")
def mt_in_mine_put(lid):
    """{on: true | false}: show the list's tasks in the signed-in person's "My tasks" (default) or not. Only for the person
    (shared lists: everyone decides for themselves). 404 for a list the person cannot see."""
    from ..core.access import list_role
    from ..core.db import iso, now_utc
    c = db()
    uid = me()
    if not list_role(c, lid, uid):
        raise Denied(404)
    on = (body() or {}).get("on")
    if not isinstance(on, bool):
        return jsonify(error=tr("Invalid value: {0}", "on")), 400
    if on:
        c.execute("DELETE FROM list_mine_hide WHERE user_id=? AND list_id=?", (uid, lid))
    else:
        c.execute("INSERT INTO list_mine_hide(user_id, list_id, created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                  (uid, lid, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(ok=True, on=on, mine_hidden=mt_mine_hidden(c, uid))
