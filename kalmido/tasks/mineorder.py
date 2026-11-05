"""2.40.0 (#1344): "My tasks" in the person's own order (table user_task_order: user_id, task_id, pos).

Personal: it never changes tasks.sort (a shared list keeps its order for everyone), nobody else sees it, agents have none.
The web app sends the whole order after a drag (PUT /api/tasks/mine-order, queued offline like the other task writes); a task
without a row (new, or newly assigned and not yet placed) stands above the placed ones. /api/state carries it as mine_order."""
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, write_lock, iso, now_utc
from ..core.access import Denied, tvis, vis_sql, list_role
from ..core.conflict import ccf_check  # 2.569.0 (#4395): versions of the own sections
from ..accounts.session import me

VW_MINE_MAX = 5000  # tasks in one order (more are cut: the oldest placed ones fall back to "not placed")


def vw_mine_order(c, uid):
    """{task id (str): pos} of the person's own order of "My tasks" (for /api/state)."""
    # 2.82.0 (#1464): only tasks the person still sees (a row of a list they left / were removed from stays hidden)
    return {str(r[0]): r[1] for r in c.execute(
        f"SELECT o.task_id, o.pos FROM user_task_order o JOIN tasks t ON t.id=o.task_id WHERE o.user_id=? "
        f"AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.')}", (uid, uid, uid))}


def _mine_done_kept(c, cur, ids):
    """2.363.3 (#3133): ids with the completed tasks of the old order cur put back behind the task they followed: the app sends
    open tasks only, a task opened again finds its place."""
    have = set(ids)
    rest = [x for x in cur if x not in have]
    done = set()
    for i in range(0, len(rest), 500):
        part = rest[i:i + 500]
        done |= {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({','.join('?' * len(part))}) AND status!=0", part)}
    after, last = {}, None
    for x in cur:
        if x in done:
            after.setdefault(last, []).append(x)
        elif x in have:
            last = x
    out = list(after.get(None, ()))
    for x in ids:
        out += [x, *after.get(x, ())]
    return out


@app.put("/api/tasks/mine-order")
def vw_mine_order_put():
    """{ids: [task ids, top first], _prev?: {ids}, secs?: {task id: own section id | null}} replaces the signed-in person's order of "My tasks". Ids of tasks the person
    cannot see (or that do not exist) are skipped. Agents have no own order (403). 2.363.3 (#3133): _prev = the order the device
    saw: when the tasks known to both stand differently now (another device, while this one waited offline) nothing changes
    -> {order_kept: true}; only the difference counts, a task placed or gone since is none. Places of completed tasks stay.
    2.569.0 (#4395): secs = the own sections (user_mine_sections) the person put tasks into; a task not named keeps its section,
    an unknown section or "Recently assigned" = none."""
    from ..agents.core import need_person
    need_person(403, tr("The own order of My tasks belongs to a person"))
    b = body() or {}
    ids, prev = b.get("ids"), b.get("_prev")
    if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return jsonify(error=tr("Invalid value: {0}", "ids")), 400
    secs = b.get("secs")  # 2.569.0 (#4395): {task id: section id | null} = put into an own section by hand (the rest keep theirs)
    if secs is not None and (not isinstance(secs, dict) or not all(x is None or (isinstance(x, int) and not isinstance(x, bool)) for x in secs.values())):
        return jsonify(error=tr("Invalid value: {0}", "secs")), 400
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
    cur_rows = c.execute("SELECT task_id, section_id FROM user_task_order WHERE user_id=? ORDER BY pos, task_id", (uid,)).fetchall()
    cur, had = [r[0] for r in cur_rows], {r[0]: r[1] for r in cur_rows}
    seen = prev.get("ids") if isinstance(prev, dict) else None
    if isinstance(seen, list):
        both = set(cur) & {x for x in seen if isinstance(x, int)}
        if [x for x in cur if x in both] != [x for x in seen if x in both]:
            c.rollback()
            return jsonify(ok=True, count=0, order_kept=True)
    keep = [x for x in ids if x in ok]
    if secs:
        own = {r[0] for r in c.execute("SELECT id FROM user_mine_sections WHERE user_id=? AND kind<>'recent'", (uid,))}
        for k, v in secs.items():
            if str(k).isdigit():
                had[int(k)] = v if v in own else None
    c.execute("DELETE FROM user_task_order WHERE user_id=?", (uid,))
    rows = [(uid, t, n, had.get(t)) for n, t in enumerate(_mine_done_kept(c, cur, keep)[:VW_MINE_MAX])]
    if rows:
        c.executemany("INSERT INTO user_task_order(user_id, task_id, pos, section_id) VALUES(?,?,?,?)", rows)
    bump(c)
    c.commit()
    return jsonify(ok=True, count=len(keep))


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


# ---- 2.569.0 (#4395): the person's own sections of "My tasks" (own order only; table user_mine_sections, migrations.d/4395_a.py).
# Personal like the order: no list, its sections or its order changes; agents have none. The first opening makes the fixed
# section "Recently assigned" (kind recent: tasks without a place stand there; never renamed or deleted, only folded) and
# "Now", "Soon", "Someday" (kinds now / soon / later, name '' = the translated default; renamed, moved and deleted like the
# person's own). The client puts a task due today or overdue into the section of kind now unless the person put it into a
# section by hand (user_task_order.section_id). Renaming and deleting carry the version (updated_at, expect_updated_at): one
# made on another device meanwhile -> 409 with the current section under "section" (core/conflict.py ccf_check).
MS_MAX = 100  # own sections per person
MS_NAME_MAX = 200
MS_DEFAULTS = ("recent", "now", "soon", "later")


def _ms_row(r):
    return {"id": r["id"], "name": r["name"] or "", "pos": r["pos"], "collapsed": bool(r["collapsed"]), "kind": r["kind"] or "",
            "updated_at": r["updated_at"]}


def ms_list(c, uid):
    """The person's sections, top first ([] = not made yet: the client asks for them once, POST /api/mine-sections/init)."""
    return [_ms_row(r) for r in c.execute("SELECT id, name, pos, collapsed, kind, updated_at FROM user_mine_sections WHERE user_id=? "
                                          "ORDER BY kind<>'recent', pos, id", (uid,))]


def vw_mine_sections(c, uid):
    """/api/state mine_sections: {list: the sections, tasks: {task id (str): section id} of the tasks put into one by hand}."""
    return {"list": ms_list(c, uid), "tasks": {str(r[0]): r[1] for r in c.execute(
        f"SELECT o.task_id, o.section_id FROM user_task_order o JOIN tasks t ON t.id=o.task_id WHERE o.user_id=? "
        f"AND o.section_id IS NOT NULL AND t.list_id IN {vis_sql()} AND {tvis(c, uid, 't.')}", (uid, uid, uid))}}


def _ms_person():
    from ..agents.core import need_person
    need_person(403, tr("The own order of My tasks belongs to a person"))
    return db(), me()


def _ms_init(c, uid):
    """Makes the four default sections once (the caller holds the write lock)."""
    if c.execute("SELECT 1 FROM user_mine_sections WHERE user_id=? LIMIT 1", (uid,)).fetchone():
        return False
    t = iso(now_utc())
    c.executemany("INSERT INTO user_mine_sections(user_id, name, pos, collapsed, kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                  [(uid, "", n, 0, k, t, t) for n, k in enumerate(MS_DEFAULTS)])
    return True


def _ms_get(c, uid, sid):
    r = c.execute("SELECT id, name, pos, collapsed, kind, updated_at FROM user_mine_sections WHERE id=? AND user_id=?", (sid, uid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _ms_name(v):
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()[:MS_NAME_MAX]


def _ms_answer(c, uid, **kw):
    bump(c)
    c.commit()
    return jsonify(ok=True, mine_sections=vw_mine_sections(c, uid), **kw)


@app.post("/api/mine-sections/init")
def ms_init_post():
    """Makes "Recently assigned", "Now", "Soon" and "Someday" when the person has no sections yet (else nothing changes)."""
    c, uid = _ms_person()
    write_lock(c, f"mine-order-{uid}")
    if not _ms_init(c, uid):
        c.rollback()
        return jsonify(ok=True, created=False, mine_sections=vw_mine_sections(c, uid))
    return _ms_answer(c, uid, created=True)


@app.post("/api/mine-sections")
def ms_create():
    """{name, after?: section id (default: at the end), restore?: {kind, collapsed, pos, tasks: [task ids]}} -> a new own section.
    restore = the Undo of a deletion: the section comes back with its kind, place and folding, and the tasks it had."""
    c, uid = _ms_person()
    b = body() or {}
    rs = b.get("restore") if isinstance(b.get("restore"), dict) else None
    kind = rs.get("kind") if rs and rs.get("kind") in MS_DEFAULTS[1:] else ""
    name = _ms_name(b.get("name"))
    if name is None and not kind:
        return jsonify(error=tr("Invalid value: {0}", "name")), 400
    write_lock(c, f"mine-order-{uid}")
    _ms_init(c, uid)
    if c.execute("SELECT COUNT(*) FROM user_mine_sections WHERE user_id=?", (uid,)).fetchone()[0] > MS_MAX:
        c.rollback()
        return jsonify(error=tr("Too many sections")), 400
    if kind and c.execute("SELECT 1 FROM user_mine_sections WHERE user_id=? AND kind=?", (uid, kind)).fetchone():
        kind = ""  # a second "Now" would make the rule ambiguous: the restored one becomes an own section
        if name is None:
            c.rollback()
            return jsonify(error=tr("Invalid value: {0}", "name")), 400
    rows = [r[0] for r in c.execute("SELECT id FROM user_mine_sections WHERE user_id=? AND kind<>'recent' ORDER BY pos, id", (uid,))]
    at = len(rows)
    if rs and isinstance(rs.get("pos"), int) and not isinstance(rs.get("pos"), bool):
        at = max(0, min(len(rows), rs["pos"] - 1))
    elif isinstance(b.get("after"), int) and b["after"] in rows:
        at = rows.index(b["after"]) + 1
    t = iso(now_utc())
    sid = c.execute("INSERT INTO user_mine_sections(user_id, name, pos, collapsed, kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?) "
                    "RETURNING id", (uid, name or "", 0, 1 if rs and rs.get("collapsed") else 0, kind, t, t)).fetchone()[0]
    rows.insert(at, sid)
    c.executemany("UPDATE user_mine_sections SET pos=? WHERE id=?", [(n + 1, x) for n, x in enumerate(rows)])
    back = [x for x in (rs.get("tasks") or []) if isinstance(x, int) and not isinstance(x, bool)][:VW_MINE_MAX] if rs and isinstance(rs.get("tasks"), list) else []
    for i in range(0, len(back), 500):
        part = back[i:i + 500]
        c.execute(f"UPDATE user_task_order SET section_id=? WHERE user_id=? AND task_id IN ({','.join('?' * len(part))})", (sid, uid, *part))
    return _ms_answer(c, uid, id=sid)


@app.patch("/api/mine-sections/<int:sid>")
def ms_patch(sid):
    """{name?, collapsed?, expect_updated_at?}: rename (not "Recently assigned") or fold the section. Only a new name changes the
    version; expect_updated_at set and another version now -> 409 {error, section}."""
    c, uid = _ms_person()
    b = body() or {}
    write_lock(c, f"mine-order-{uid}")
    r = _ms_get(c, uid, sid)
    ccf_check(b, r["updated_at"], "section", lambda: _ms_row(r))
    sets, args = [], []
    if "name" in b:
        name = _ms_name(b.get("name"))
        if name is None or r["kind"] == "recent":
            c.rollback()
            return jsonify(error=tr("Invalid value: {0}", "name")), 400
        sets += ["name=?", "updated_at=?"]
        args += [name, iso(now_utc())]
    if "collapsed" in b:
        if not isinstance(b["collapsed"], bool):
            c.rollback()
            return jsonify(error=tr("Invalid value: {0}", "collapsed")), 400
        sets.append("collapsed=?")
        args.append(1 if b["collapsed"] else 0)
    if not sets:
        c.rollback()
        return jsonify(ok=True, section=_ms_row(r), mine_sections=vw_mine_sections(c, uid))
    c.execute(f"UPDATE user_mine_sections SET {', '.join(sets)} WHERE id=?", (*args, sid))
    return _ms_answer(c, uid, section=_ms_row(_ms_get(c, uid, sid)))


@app.delete("/api/mine-sections/<int:sid>")
def ms_delete(sid):
    """{expect_updated_at?}: deletes an own section (not "Recently assigned"); its tasks fall into the topmost section that is left
    (none left: no section). -> {restore: what POST /api/mine-sections takes back for the Undo}."""
    c, uid = _ms_person()
    b = body() or {}
    write_lock(c, f"mine-order-{uid}")
    r = _ms_get(c, uid, sid)
    ccf_check(b, r["updated_at"], "section", lambda: _ms_row(r))
    if r["kind"] == "recent":
        c.rollback()
        return jsonify(error=tr("Recently assigned stays")), 400
    rows = [x[0] for x in c.execute("SELECT id FROM user_mine_sections WHERE user_id=? AND kind<>'recent' ORDER BY pos, id", (uid,))]
    tasks = [x[0] for x in c.execute("SELECT task_id FROM user_task_order WHERE user_id=? AND section_id=? ORDER BY pos", (uid, sid))]
    top = next((x for x in rows if x != sid), None)
    c.execute("UPDATE user_task_order SET section_id=? WHERE user_id=? AND section_id=?", (top, uid, sid))
    c.execute("DELETE FROM user_mine_sections WHERE id=?", (sid,))
    c.executemany("UPDATE user_mine_sections SET pos=? WHERE id=?", [(n + 1, x) for n, x in enumerate(y for y in rows if y != sid)])
    restore = {"name": r["name"] or "", "kind": r["kind"] or "", "pos": rows.index(sid) + 1, "collapsed": bool(r["collapsed"]), "tasks": tasks}
    return _ms_answer(c, uid, restore=restore, moved_to=top)


@app.put("/api/mine-sections/order")
def ms_order_put():
    """{ids: [own section ids, top first], _prev?: {ids}}: the order of the sections ("Recently assigned" stays on top). _prev =
    the order the device saw: another one now (another device) -> nothing changes, {order_kept: true}."""
    c, uid = _ms_person()
    b = body() or {}
    ids, prev = b.get("ids"), b.get("_prev")
    if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return jsonify(error=tr("Invalid value: {0}", "ids")), 400
    write_lock(c, f"mine-order-{uid}")
    rows = [x[0] for x in c.execute("SELECT id FROM user_mine_sections WHERE user_id=? AND kind<>'recent' ORDER BY pos, id", (uid,))]
    seen = prev.get("ids") if isinstance(prev, dict) else None
    if isinstance(seen, list) and [x for x in seen if x in rows] != [x for x in rows if x in seen]:
        c.rollback()
        return jsonify(ok=True, order_kept=True, mine_sections=vw_mine_sections(c, uid))
    new = [x for x in dict.fromkeys(ids) if x in rows]
    new += [x for x in rows if x not in new]  # sections the list did not name keep their place at the end
    c.executemany("UPDATE user_mine_sections SET pos=? WHERE id=?", [(n + 1, x) for n, x in enumerate(new)])
    return _ms_answer(c, uid)
