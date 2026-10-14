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
    return {str(r[0]): r[1] for r in c.execute("SELECT task_id, pos FROM user_task_order WHERE user_id=?", (uid,))}


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
