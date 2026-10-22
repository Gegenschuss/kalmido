"""2.71.0 B (#1459): a task in several lists without a copy.

The task stays ONE row in its own list (tasks.list_id, "origin"); task_links places it in further lists of the same
workspace with its own section / position there. Every right stays with the origin (task_visible / need_task / tvis are
NOT widened): whoever sees only the further list never gets the task -- not in the state, search, events, agents, public
links, calendar feeds or exports (they all read tasks.list_id). The task dict carries "also" = the further lists the
viewer sees themselves (ml_fill). Linking needs write on the task and on the target list, both lists in the same
workspace (lists.org_id equal, NULL == NULL), no health list, no locked list, no archived target, top-level tasks only,
at most ML_MAX further lists. A database trigger (core/schema.py kalmido_ml_prune) drops links that a move of the task
or a workspace change of a list would carry across the boundary, whatever the write path.
"""
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, need_list, need_task, task_visible, vis_sql, WRITE_ROLES

ML_MAX = 10  # further lists per task


# A move of the task (other list, now a subtask) or a list's new workspace drops the links that would cross the workspace
# boundary or point at the task's own list -- in the database, so every write path is covered. As "system" inside the
# function only (the rows of the old workspace may be outside the writer's row-level scope), the caller's value back
# before it returns (like kalmido_org_count). Without the table (the way back) it does nothing.
ML_TRIGGERS = """CREATE OR REPLACE FUNCTION kalmido_ml_prune() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  IF to_regclass('task_links') IS NULL THEN RETURN NULL; END IF;
  PERFORM set_config('app.role', 'system', true);
  IF TG_TABLE_NAME = 'tasks' THEN
    DELETE FROM task_links k WHERE k.task_id = NEW.id AND (k.list_id = NEW.list_id OR NEW.parent_id IS NOT NULL
      OR (SELECT x.org_id FROM lists x WHERE x.id = k.list_id) IS DISTINCT FROM (SELECT o.org_id FROM lists o WHERE o.id = NEW.list_id));
  ELSE
    DELETE FROM task_links k WHERE (k.list_id = NEW.id OR k.task_id IN (SELECT t.id FROM tasks t WHERE t.list_id = NEW.id))
      AND (SELECT x.org_id FROM lists x WHERE x.id = k.list_id) IS DISTINCT FROM
          (SELECT o.org_id FROM tasks t JOIN lists o ON o.id = t.list_id WHERE t.id = k.task_id);
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $fn$;
CREATE OR REPLACE TRIGGER kalmido_ml_task AFTER UPDATE OF list_id, parent_id ON tasks FOR EACH ROW
  WHEN (NEW.list_id IS DISTINCT FROM OLD.list_id OR NEW.parent_id IS DISTINCT FROM OLD.parent_id) EXECUTE FUNCTION kalmido_ml_prune();
CREATE OR REPLACE TRIGGER kalmido_ml_list AFTER UPDATE OF org_id ON lists FOR EACH ROW
  WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_ml_prune();"""


def ml_setup(c):
    """init_db (every start, after the migrations: lists.org_id is one): the pruning triggers (idempotent)."""
    c.executescript(ML_TRIGGERS)


def ml_locked(c, lid):
    """Is list lid locked (end-to-end encrypted, 2.64a)?"""
    if not lid:  # lists.e2e exists since 2.64a (merged before 2.71: no column probe any more)
        return False
    r = c.execute("SELECT e2e IS NOT NULL FROM lists WHERE id=?", (lid,)).fetchone()
    return bool(r and r[0])


def ml_fill(c, out, viewer):
    """load_tasks: "also" on the top-level tasks of out = [{list_id, section_id, sort}] of their further lists that the
    viewer sees (the request's list scope: health lists, a token's list limit and the organisation boundary included),
    only where both lists are still in one workspace. Absent when there is none."""
    ids = [d["id"] for d in out if not d.get("parent_id")]
    if not viewer or not ids or not c.execute("SELECT 1 FROM task_links LIMIT 1").fetchone():
        return
    q = ",".join("?" * len(ids))
    also = {}
    for r in c.execute(f"""SELECT k.task_id, k.list_id, k.section_id, k.sort FROM task_links k JOIN tasks t ON t.id=k.task_id
                           JOIN lists o ON o.id=t.list_id JOIN lists x ON x.id=k.list_id
                           WHERE k.task_id IN ({q}) AND k.list_id!=t.list_id AND t.parent_id IS NULL
                           AND o.org_id IS NOT DISTINCT FROM x.org_id
                           AND COALESCE(o.life, '') NOT IN ('health', 'budget') AND COALESCE(x.life, '') NOT IN ('health', 'budget')
                           AND k.list_id IN {vis_sql()} ORDER BY k.task_id, k.list_id""", (*ids, viewer, viewer)):
        if ml_locked(c, r["list_id"]):
            continue
        also.setdefault(r["task_id"], []).append({"list_id": r["list_id"], "section_id": r["section_id"], "sort": r["sort"]})
    for d in out:
        if d["id"] in also:
            d["also"] = also[d["id"]]


def ml_acts(c, acts):
    """The task's history: "also in list X" / "removed from list X" name X only for a viewer who sees X."""
    vis = None
    for a in acts:
        if a["kind"] in ("ml_add", "ml_rm"):
            if vis is None:
                vis = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM lists WHERE id IN {vis_sql()}", (me(), me()))}
            lid = a["data"].get("list_id")
            a["data"] = {"list_id": lid, "name": vis[lid]} if lid in vis else {}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def ml_check(c, tid, lid):
    """None when the current user may show task tid also in list lid, else (message, status). Raises Denied (404 / 403)
    for the task (write on the origin) and the target list (write: owner / admin / member)."""
    need_task(c, tid)
    t = c.execute("SELECT list_id, parent_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if t["deleted_at"]:
        raise Denied(404)
    need_list(c, lid)
    if t["parent_id"]:
        return tr("Only top-level tasks can be shown in further projects"), 400
    if lid == t["list_id"]:
        return tr("The task is already in this project"), 400
    o = c.execute("SELECT org_id, life FROM lists WHERE id=?", (t["list_id"],)).fetchone()
    x = c.execute("SELECT org_id, life, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if o["org_id"] != x["org_id"]:
        return tr("Both projects must be in the same workspace"), 400
    if (o["life"] or "") == "health" or (x["life"] or "") == "health":
        return tr("Health projects cannot share tasks with other projects"), 400
    if "budget" in ((o["life"] or ""), (x["life"] or "")):  # 2.72.0 (#1333): a budget stays private, like a health list
        return tr("Budgets cannot share tasks with other projects"), 400
    if ml_locked(c, t["list_id"]) or ml_locked(c, lid):
        return tr("Locked projects cannot share tasks with other projects"), 400
    if x["archived"]:
        return tr("The project is archived"), 400
    n = c.execute("SELECT COUNT(*) FROM task_links WHERE task_id=? AND list_id!=? AND list_id IN (SELECT id FROM lists WHERE deleted_at IS NULL)",
                  (tid, lid)).fetchone()[0]  # 2.102.0 A (#1988): a further list in the trash does not count (its link comes back with it)
    if n >= ML_MAX:
        return tr("A task can be shown in at most {0} further projects", ML_MAX), 400
    return None


def _place(c, lid, sid):
    """(section id or None, error) of a section given for list lid."""
    if sid is None:
        return None, None
    if not _int(sid) or not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, lid)).fetchone():
        return None, tr("Invalid value: {0}", "section_id")
    return sid, None


@app.post("/api/tasks/<int:tid>/links")
def ml_link(tid):
    """{list_id, section_id?, sort?}: show the task also in list_id (again: only the place changes)."""
    c, b = db(), body()
    lid = _int(b.get("list_id"))
    if not lid:
        return err(tr("Invalid value: {0}", "list_id"))
    e = ml_check(c, tid, lid)
    if e:
        return err(*e)
    sid, e = _place(c, lid, b.get("section_id"))
    if e:
        return err(e)
    srt = b.get("sort")
    if not isinstance(srt, (int, float)) or isinstance(srt, bool):
        srt = max(c.execute("SELECT COALESCE(MAX(sort), 0) FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0],
                  c.execute("SELECT COALESCE(MAX(sort), 0) FROM task_links WHERE list_id=?", (lid,)).fetchone()[0]) + 1
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    had = c.execute("SELECT 1 FROM task_links WHERE task_id=? AND list_id=?", (tid, lid)).fetchone()
    c.execute("""INSERT INTO task_links(task_id, list_id, section_id, sort, org_id, added_by, created_at) VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT (task_id, list_id) DO UPDATE SET section_id=excluded.section_id, sort=excluded.sort""",
              (tid, lid, sid, float(srt), org, me(), iso(now_utc())))
    if not had:
        from ..tasks.validation import log_act
        log_act(c, tid, "ml_add", {"list_id": lid})
    bump(c)
    c.commit()
    from ..tasks.tasks import one_task
    return jsonify(one_task(c, tid))  # 200 (v1_call takes every tuple for an error)


@app.delete("/api/tasks/<int:tid>/links/<int:lid>")
def ml_unlink(tid, lid):
    """Remove the task from further list lid (the task itself stays): write on that list OR on the task. Someone with
    write on the list who cannot see the task gets the same answer whether a link existed or not."""
    c = db()
    role = list_role(c, lid)
    if role not in WRITE_ROLES:
        need_task(c, tid)  # 404 / 403 from the task's own list
    gone = c.execute("DELETE FROM task_links WHERE task_id=? AND list_id=?", (tid, lid)).rowcount
    if gone:
        from ..tasks.validation import log_act
        log_act(c, tid, "ml_rm", {"list_id": lid})
        bump(c)
    c.commit()
    if not task_visible(c, tid, me()):
        return jsonify(ok=True)
    from ..tasks.tasks import one_task
    return jsonify(one_task(c, tid))


@app.patch("/api/tasks/<int:tid>/links/<int:lid>")
def ml_place(tid, lid):
    """{section_id?, sort?}: the task's place in further list lid (its board column there); the origin is untouched."""
    c, b = db(), body()
    need_list(c, lid)
    if not task_visible(c, tid, me()):
        raise Denied(404)
    if not c.execute("SELECT 1 FROM task_links WHERE task_id=? AND list_id=?", (tid, lid)).fetchone():
        raise Denied(404)
    sets, args = [], []
    if "section_id" in b:
        sid, e = _place(c, lid, b["section_id"])
        if e:
            return err(e)
        sets.append("section_id=?")
        args.append(sid)
    if "sort" in b:
        if not isinstance(b["sort"], (int, float)) or isinstance(b["sort"], bool):
            return err(tr("Invalid value: {0}", "sort"))
        sets.append("sort=?")
        args.append(float(b["sort"]))
    if sets:
        c.execute(f"UPDATE task_links SET {', '.join(sets)} WHERE task_id=? AND list_id=?", (*args, tid, lid))
        bump(c)
        c.commit()
    from ..tasks.tasks import one_task
    return jsonify(one_task(c, tid))


# ---- API v1 (agents): the same rules through the web endpoints
from ..api.v1 import v1_one  # noqa: E402
from ..api.common import v1_args, v1_call, v1_json, v1_view  # noqa: E402


@app.post("/api/v1/tasks/<int:tid>/links")
@v1_view
def v1_ml_link(tid):
    """{list_id, section_id?}: show the task also in another list (no copy; rights stay with the task's own list)."""
    v1_args(())
    b = v1_json()
    v1_call(ml_link, tid, body={k: b[k] for k in ("list_id", "section_id") if k in b})
    return jsonify(v1_one(db(), tid))


@app.delete("/api/v1/tasks/<int:tid>/links/<list_id>")  # second id as text like /contacts/<contact_id>: the spec says {list_id}
@v1_view
def v1_ml_unlink(tid, list_id):
    from .validation import as_int
    v1_args(())
    lid = as_int(list_id, "list_id", 1)
    v1_call(ml_unlink, tid, lid)
    c = db()
    return jsonify(v1_one(c, tid)) if task_visible(c, tid, me()) else jsonify(ok=True)


def ml_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI of the further-list routes (2.71.0 B, #1459)."""
    T = "Tasks"
    lp = pid("list_id", "List id")
    paths["/tasks/{id}/links"] = {"post": op(
        "2.71.0 (#1459): show a task also in another list (no copy)", T, ok(ref("Task")) | errs("400", "403", "404"), [pid()],
        scope="tasks:write", body={"type": "object", "required": ["list_id"], "properties": {
            "list_id": {"type": "integer"}, "section_id": {"type": ["integer", "null"], "description": "A section of that list"}}},
        desc=f"Needs write access to the task and to the list; both lists in the same workspace (organisation or private), no "
             f"health or locked lists, top-level tasks only, at most {ML_MAX} further lists. Rights stay with the task's own list: "
             "who sees only the further list does not see the task. The task's `also` lists the further lists you see.")}
    paths["/tasks/{id}/links/{list_id}"] = {"delete": op(
        "2.71.0 (#1459): remove a task from a further list (the task stays)", T, ok(ref("Task")) | errs("403", "404"), [pid(), lp],
        scope="tasks:write", desc="Needs write access to that list or to the task.")}
