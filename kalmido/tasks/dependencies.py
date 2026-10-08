"""Dependencies between tasks ("waiting on")."""
from flask import g, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, err, inbox_default, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_people, list_role, need_project, need_task, PROJ_SQL, task_visible, tvis, vis_sql
from ..tasks.validation import descendants, log_act
from ..tasks.tasks import one_task
from ..collab.comments import burst_gate, collab_user, lang_of, user_names
from ..collab.news import news_add, notif_ok
from ..personal.timetrack import BadInput, vis_ids, VisIds


# ---------------------------------------------------------------- dependencies ("waiting on"), package 3
# task_deps(task_id, blocker_id): task_id waits on blocker_id. A blocker is open while status=0 and it is
# not in the trash (a trashed blocker is ignored until it is restored; done / won't do resolves it; a
# recurring blocker stays open, its done copies do not unblock). Adding or removing a dependency changes
# the waiting task: it needs write access to that task, and both tasks must be visible to the user. No
# self-dependency, no cycles (checked on the whole graph, also through tasks the user cannot see).
# Titles of tasks the user cannot see are never sent ("a task you cannot see").
# When the LAST open blocker of a task is completed (done or won't do), the waiting task gets an activity
# line and its assignee (else its creator) a News item "unblock" + push (module collab of the recipient,
# burst rule, never the person who completed it).
DEP_MAX = 50


def dep_reaches(c, start, target):
    """True if target is reachable from start along "waits on" edges (start waits on ... on target)."""
    seen, todo = set(), [start]
    while todo:
        x = todo.pop()
        if x == target:
            return True
        if x in seen or len(seen) > 10000:
            continue
        seen.add(x)
        todo.extend(r[0] for r in c.execute("SELECT blocker_id FROM task_deps WHERE task_id=?", (x,)))
    return False


def open_blockers(c, tid):
    return c.execute(f"""SELECT COUNT(*) FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                        WHERE d.task_id=? AND b.status=0 AND b.deleted_at IS NULL AND b.list_id IN {PROJ_SQL}""", (tid,)).fetchone()[0]


def dep_rows(c, sql, tid, vis):
    out = []
    for r in c.execute(sql, (tid,)):
        if r["deleted_at"]:
            continue  # in the trash: ignored while it is there
        if r["list_id"] in vis and (not isinstance(vis, VisIds) or vis.task_ok(r["id"], r["list_id"])):
            out.append({"id": r["id"], "title": r["title"], "status": r["status"], "list_id": r["list_id"],
                        "due": r["due"], "assignee_id": r["assignee_id"], "hidden": False})
        else:
            out.append({"id": None, "title": None, "status": r["status"], "hidden": True})
    return out


@app.get("/api/tasks/<int:tid>/deps")
def deps_get(tid):
    """What the task waits on (blocked_by) and what waits on it (blocking), for the detail panel."""
    c = db()
    need_task(c, tid, write=False, full=True)
    vis = vis_ids(c, me())
    return jsonify(
        blocked_by=dep_rows(c, "SELECT t.* FROM task_deps d JOIN tasks t ON t.id=d.blocker_id WHERE d.task_id=? ORDER BY d.created_at, t.id", tid, vis),
        blocking=dep_rows(c, "SELECT t.* FROM task_deps d JOIN tasks t ON t.id=d.task_id WHERE d.blocker_id=? ORDER BY d.created_at, t.id", tid, vis))


@app.get("/api/deps")
def deps_all():
    """Every dependency between tasks the user can see whose waiting task is open (timeline arrows, package D2):
    edges [[task_id, blocker_id], ...] + the blockers that are no longer open (done / won't do) as short rows,
    so the timeline can draw their arrows muted. Blockers in the trash are left out (ignored while there)."""
    c = db()
    uid = me()
    vis = vis_sql()
    edges, closed = [], {}
    for r in c.execute(f"""SELECT d.task_id, d.blocker_id, b.status, b.title, b.list_id, b.start, b.due FROM task_deps d
                           JOIN tasks t ON t.id=d.task_id JOIN tasks b ON b.id=d.blocker_id
                           WHERE t.status=0 AND t.deleted_at IS NULL AND b.deleted_at IS NULL
                           AND t.list_id IN {vis} AND b.list_id IN {vis} AND t.list_id IN {PROJ_SQL} AND b.list_id IN {PROJ_SQL}
                           AND {tvis(c, uid, "t.")} AND {tvis(c, uid, "b.")}
                           ORDER BY d.created_at LIMIT 20000""", (uid, uid, uid, uid)):
        edges.append([r["task_id"], r["blocker_id"]])
        if r["status"] != 0:
            closed[r["blocker_id"]] = {"id": r["blocker_id"], "title": r["title"], "status": r["status"], "list_id": r["list_id"],
                                       "start": r["start"], "due": r["due"]}
    return jsonify(edges=edges, closed=list(closed.values()))


def dep_ids(b):
    try:
        return int(b.get("task_id")), int(b.get("blocker_id"))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None


@app.post("/api/deps")
def dep_add():
    """{task_id, blocker_id}: task_id waits on blocker_id."""
    c = db()
    t, bl = dep_ids(body())
    need_task(c, t)                 # the waiting task changes: write access
    need_task(c, bl, write=False)   # the blocker must be visible
    if t == bl:
        return err(tr("A task cannot block itself"))
    rows = {r["id"]: r for r in c.execute("SELECT id, title, deleted_at FROM tasks WHERE id IN (?,?)", (t, bl))}
    if rows[t]["deleted_at"] or rows[bl]["deleted_at"]:
        return err(tr("The task is in the trash"), 409)
    for x in (t, bl):
        need_project(c, c.execute("SELECT list_id FROM tasks WHERE id=?", (x,)).fetchone()[0], "deps")
    if not c.execute("SELECT 1 FROM task_deps WHERE task_id=? AND blocker_id=?", (t, bl)).fetchone():
        if dep_reaches(c, bl, t):
            return err(tr("That would create a circular dependency"))
        if c.execute("SELECT COUNT(*) FROM task_deps WHERE task_id=?", (t,)).fetchone()[0] >= DEP_MAX:
            return err(tr("At most {0} dependencies per task", DEP_MAX))
        c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?)",
                  (t, bl, me(), iso_ms(now_utc())))
        log_act(c, t, "dep_add", {"id": bl, "title": rows[bl]["title"][:200]})
        log_act(c, bl, "blocks_add", {"id": t, "title": rows[t]["title"][:200]})
        bump(c)
        c.commit()
    return jsonify(ok=True, task=one_task(c, t))


@app.delete("/api/deps/<int:t>/<int:bl>")
def dep_remove(t, bl):
    """Removes "t waits on bl". bl = 0: every blocker of t the user cannot see (lost access)."""
    c = db()
    need_task(c, t)
    if bl == 0:
        vis = vis_ids(c, me())
        gone = [r[0] for r in c.execute("SELECT d.blocker_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id WHERE d.task_id=?", (t,))
                if r[1] not in vis or not vis.task_ok(r[0], r[1])]
        for x in gone:
            c.execute("DELETE FROM task_deps WHERE task_id=? AND blocker_id=?", (t, x))
        if gone:
            log_act(c, t, "dep_rm", {"hidden": True, "n": len(gone)})
    else:
        r = c.execute("SELECT b.title, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id WHERE d.task_id=? AND d.blocker_id=?",
                      (t, bl)).fetchone()
        if not r or not list_role(c, r["list_id"]) or not task_visible(c, bl, me()):
            raise Denied(404)
        c.execute("DELETE FROM task_deps WHERE task_id=? AND blocker_id=?", (t, bl))
        title = c.execute("SELECT title FROM tasks WHERE id=?", (t,)).fetchone()[0]
        log_act(c, t, "dep_rm", {"id": bl, "title": r["title"][:200]})
        log_act(c, bl, "blocks_rm", {"id": t, "title": title[:200]})
    bump(c)
    c.commit()
    return jsonify(ok=True, task=one_task(c, t))


def newtask_events(c, tid):
    """2.1.0 (#317): someone else created a task in a shared list -> event "newtask" (News + push per the settings, off by
    default; the bell "All" of the list turns it on). Not for the new assignee (they get "assigned"), never for agents."""
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_ids
    t = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                     WHERE t.id=?""", (tid,)).fetchone()
    if not t or not c.execute("SELECT 1 FROM list_members WHERE list_id=?", (t["list_id"],)).fetchone():
        return
    actor = me()
    ag = agent_ids(c)
    who = user_names(c, [actor]).get(actor, "?") if actor else None
    for uid in sorted(list_people(c, t["list_id"])):
        if uid in (actor, t["assignee_id"]) or uid in ag:
            continue
        s = collab_user(c, uid, t["list_id"])
        if not s or not task_visible(c, tid, uid, full=True):
            continue
        news_add(c, uid, "newtask", task_id=tid, actor=actor, s=s)
        from ..collab.news import agent_push_ok
        if not notif_ok(c, uid, s, "newtask", "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not burst_gate(c, uid, tid, event=True) or not agent_push_ok(c, uid, s, actor):  # 2.28.0 (#987)
            continue
        lg = lang_of(s)
        lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
        g.pushes.append((uid, tr("{0} added: {1}", who or tr("Someone via the public link", lg=lg), t["title"], lg=lg), lname,
                         f"{PUBLIC_URL}/#t/{tid}", push_prio(s)))


def unblock_events(c, done_ids):
    """done_ids: tasks just completed (done / won't do, incl. subtasks completed with them). Each open task
    that waited on one of them and has no open blocker left: activity line + News / push (see above)."""
    from ..notify.push import push_prio, push_reachable
    done_ids = list(dict.fromkeys(done_ids))
    if not done_ids:
        return
    q = ",".join("?" * len(done_ids))
    waiting = {}
    for r in c.execute(f"""SELECT d.task_id, d.blocker_id FROM task_deps d JOIN tasks t ON t.id=d.task_id JOIN tasks b ON b.id=d.blocker_id
                           WHERE d.blocker_id IN ({q}) AND b.status!=0 AND t.status=0 AND t.deleted_at IS NULL
                           AND t.list_id IN {PROJ_SQL} AND b.list_id IN {PROJ_SQL}
                           ORDER BY d.created_at""", done_ids):
        waiting.setdefault(r["task_id"], r["blocker_id"])
    actor = me()
    for w, bl in waiting.items():
        if open_blockers(c, w):
            continue
        b = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (bl,)).fetchone()
        log_act(c, w, "unblocked", {"id": bl, "title": b["title"][:200]})
        t = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.id=?""", (w,)).fetchone()
        uid = t["assignee_id"] or t["created_by"]
        if not uid or uid == actor:
            continue
        s = collab_user(c, uid, t["list_id"])
        if not s or "deps" not in (s.get("features") or "").split(",") or not task_visible(c, w, uid, full=True):
            continue  # module "deps" off: no News / push about dependencies (the activity line stays)
        news_add(c, uid, "unblock", task_id=w, data={"blocker": bl}, actor=actor, s=s)
        if not notif_ok(c, uid, s, "unblock", "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not burst_gate(c, uid, w, event=True):
            continue
        lg = lang_of(s)
        who = user_names(c, [actor]).get(actor, "?") if actor else tr("Someone via the public link", lg=lg)
        bt = b["title"] if list_role(c, b["list_id"], uid) and task_visible(c, bl, uid) else tr("a task you cannot see", lg=lg)
        lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
        g.pushes.append((uid, tr("Unblocked: {0}", t["title"], lg=lg),
                         tr("{0} completed {1}", who, bt, lg=lg) + " · " + lname, f"{PUBLIC_URL}/#t/{w}", push_prio(s)))


def completed_ids(c, tid):
    """The task + its subtasks that are completed now (after do_complete)."""
    return [x for x in [tid, *descendants(c, tid)]
            if (c.execute("SELECT status FROM tasks WHERE id=?", (x,)).fetchone() or [0])[0] != 0]


DEP_ACTS = ("dep_add", "dep_rm", "blocks_add", "blocks_rm", "unblocked")
