"""Reordering and batch changes of tasks, occurrences of repeating tasks, deleting attachments."""
import time
from datetime import date, datetime
from flask import jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc, parse_iso
from ..accounts.session import me
from ..core.access import Denied, list_people, list_role, need_list, need_task, task_visible, tvis, vis_sql
from ..core.serializers import unlink_files
from ..tasks.validation import (
    as_int, clean_task, log_act, log_changes, RR_OCC_PER_TASK, RR_OCC_SECONDS, RR_OCC_TOTAL, rr_rule,
)
from ..tasks.tasks import check_move, dep_shift, move_subtree, ms_cleanup, one_task
from ..tasks.lifecycle import _norm, apply_update, do_complete, do_delete, restore_task, signed, undo_status
from ..tasks.attachments import need_attachment


@app.delete("/api/attachments/<int:aid>")
def attachment_delete(aid):
    c = db()
    a = need_attachment(c, aid, True)
    c.execute("DELETE FROM attachments WHERE id=?", (aid,))
    if a["comment_id"] is None:
        log_act(c, a["task_id"], "attach_rm", {"name": a["name"]})
    else:
        c.execute("UPDATE comments SET edited_at=? WHERE id=?", (iso(now_utc()), a["comment_id"]))
    bump(c)
    c.commit()
    unlink_files([a["path"]])
    return jsonify(one_task(c, a["task_id"]) if a["comment_id"] is None else {"ok": True})


@app.post("/api/tasks/reorder")
def task_reorder():
    """[{id, sort, section_id?, list_id?, priority?, due?}] — one call per drag. All items are checked
    first (write on the task, and on the target list for moves); nothing changes if one is forbidden."""
    c = db()
    ts = iso(now_utc())
    items = []
    for it in body().get("items", []):
        if not isinstance(it, dict) or not it.get("id"):
            continue
        r = c.execute("SELECT list_id FROM tasks WHERE id=?", (int(it["id"]),)).fetchone()
        if not r or not list_role(c, r[0]) or not task_visible(c, int(it["id"]), me()):
            continue  # unknown (e.g. deleted elsewhere, or not visible): nothing to do
        role = need_task(c, int(it["id"]))
        if it.get("list_id"):
            if role == "participant" and as_int(it["list_id"], "list_id", 1) != r[0]:
                raise Denied(403, tr("Participants cannot move tasks to another list"))
            need_list(c, as_int(it["list_id"], "list_id", 1))
            check_move(c, r[0], int(it["list_id"]))
        items.append(it)
    shifted = []
    for it in items:
        f = clean_task({k: v for k, v in it.items()
                        if k in ("sort", "section_id", "list_id", "priority", "due", "start", "due_time")})
        if "list_id" in f and not f["list_id"]:
            del f["list_id"]
        if f:
            cur = c.execute("SELECT list_id, assignee_id FROM tasks WHERE id=?", (it["id"],)).fetchone()
            lid = f.get("list_id", cur["list_id"])
            if f.get("section_id") and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?",
                                                     (f["section_id"], lid)).fetchone():
                f["section_id"] = None
            if lid != cur["list_id"] and cur["assignee_id"] and cur["assignee_id"] not in list_people(c, lid):
                f["assignee_id"] = None
            if lid != cur["list_id"]:
                f["milestone_id"] = None  # 2.18.0 (#430): the milestone stays in its list
            f["updated_at"] = ts
            before = c.execute("SELECT * FROM tasks WHERE id=?", (it["id"],)).fetchone()
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), it["id"]])
            log_changes(c, it["id"], before)
            if "list_id" in f:
                move_subtree(c, int(it["id"]), f["list_id"])
                if f["list_id"] != before["list_id"]:  # 2.23.0 (#795)
                    from ..agents.core import agent_added_events
                    agent_added_events(c, int(it["id"]), before["list_id"])
                ms_cleanup(c)  # 2.18.0 (#430): a moved milestone lets its tasks go, moved subtasks leave theirs
            if "due" in f and before["status"] == 0 and not before["deleted_at"]:  # dropped on a later day
                shifted += dep_shift(c, int(it["id"]), before["due"], f["due"])
    bump(c)
    c.commit()
    return jsonify(ok=True, shifted=shifted)


@app.post("/api/tasks/batch")
def task_batch():
    """{ids: [...], action: patch|patch_each|complete|reopen|delete|restore|undo, data: {...}} -- multi-select, and the
    undo / redo history (D4), which sends every multi-part step here so it is one transaction.
    Tasks the user may not change are skipped and reported in errors. D4 additions (all optional):
      patch_each: data.items = {id: {field: value, ..., _prev: {...}}}; a field changed elsewhere meanwhile is skipped
                  and reported in conflicts (see apply_update)
      complete:   data.expect = {id: due}: a task whose date moved meanwhile is not completed (conflict "due"); a task
                  that is already done is reported (conflict "status")
      reopen:     returns signed undo payloads like complete (to complete it again)
      delete:     data.guard = {id: time}: not moved to the trash if someone else changed it after that time
                  (conflict "changed")
      undo:       a completion / reopen that changed meanwhile is reported as a conflict too
    The answer carries conflicts [{id, title, field, server, mine}] and the server time (now)."""
    from ..collab.comments import task_event
    from ..personal.timetrack import BadInput
    from ..tasks.dependencies import completed_ids, unblock_events
    b = body()
    c = db()
    try:
        ids = [int(i) for i in b.get("ids", [])]
    except (TypeError, ValueError):
        return err(tr("Invalid data"))
    action, data = b.get("action"), b.get("data") or {}
    if not isinstance(data, dict):
        return err(tr("Invalid data"))
    ts = iso(now_utc())
    errors, done, undo, finished, conflicts = [], 0, {}, [], []
    per = data.get("items") if isinstance(data.get("items"), dict) else {}  # patch_each / undo: per task id
    expect = data.get("expect") if isinstance(data.get("expect"), dict) else {}
    guard = {}
    for k, v in (data.get("guard") if isinstance(data.get("guard"), dict) else {}).items():
        try:
            guard[str(k)] = iso_ms(parse_iso(str(v))) if v else None
        except ValueError:
            return err(tr("Invalid value: {0}", "guard"))

    def conflict(tid, field, server=None, mine=None, title=None):
        t = c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()
        conflicts.append({"id": tid, "title": title if title is not None else t[0] if t else "", "field": field, "server": server, "mine": mine})
    for tid in ids:
        deleted = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if not deleted or (deleted[0] and action != "restore") or (not deleted[0] and action == "restore"):
            continue
        try:
            role = need_task(c, tid)
            if role == "participant" and action == "delete":
                raise Denied(403, tr("Participants cannot delete tasks"))
            if action == "patch":
                e = apply_update(c, tid, data)
                if e:
                    errors.append(e)
                    continue
            elif action == "patch_each":  # undo / redo: every task to its own values
                if str(tid) not in per or not isinstance(per[str(tid)], dict):
                    continue
                cf, title = [], c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()[0]
                e = apply_update(c, tid, per[str(tid)], cf)
                for x in cf:
                    conflict(tid, x["field"], x["server"], x["mine"], title)
                if e:
                    errors.append(e)
                    continue
            elif action == "complete":
                st = int(data.get("status", 2))
                u = {}
                row = c.execute("SELECT status, due FROM tasks WHERE id=?", (tid,)).fetchone()
                if row["status"] != 0:
                    if str(tid) in expect:  # redo: done elsewhere meanwhile
                        conflict(tid, "status", row["status"], st)
                    continue  # already completed: nothing to do (and nothing to undo)
                if str(tid) in expect and _norm(expect[str(tid)]) != _norm(row["due"]):
                    conflict(tid, "due", row["due"], expect[str(tid)])
                    continue
                nxt = do_complete(c, tid, st, u)
                undo[str(tid)] = signed(tid, u)
                log_act(c, tid, "wont" if st == -1 else "reopen" if st == 0 else "complete", {"next": nxt} if nxt else None)
                if st == 2:
                    task_event(c, tid, "complete")
                if st != 0:
                    finished += completed_ids(c, tid)
            elif action == "undo":
                e = undo_status(c, tid, per.get(str(tid)))
                if e:
                    errors.append(e)
                    conflict(tid, "status")
                    continue
            elif action == "reopen":
                old = c.execute("SELECT status, completed_at, completed_by FROM tasks WHERE id=?", (tid,)).fetchone()
                if old["status"] == 0:
                    continue
                c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=?", (ts, tid))
                log_act(c, tid, "reopen")
                undo[str(tid)] = signed(tid, {"op": "reopen", "status": old["status"], "completed_at": old["completed_at"],
                                              "completed_by": old["completed_by"]})
            elif action == "delete":
                since = guard.get(str(tid))
                if since and c.execute("""SELECT 1 FROM activity WHERE task_id=? AND created_at>? AND (user_id IS NULL OR user_id!=?)
                                          LIMIT 1""", (tid, str(since), me())).fetchone():
                    conflict(tid, "changed")
                    continue
                do_delete(c, tid)
                log_act(c, tid, "delete")
            elif action == "restore":
                restore_task(c, tid)
            done += 1
        except Denied as e:
            errors.append(e.text())
        except BadInput as e:
            errors.append(str(e))
    unblock_events(c, finished)
    bump(c)
    c.commit()
    return jsonify(ok=True, count=done, errors=list(dict.fromkeys(errors)), undo=undo, conflicts=conflicts, now=iso_ms(now_utc()))


@app.get("/api/occurrences")
def occurrences():
    """Future repeats of open recurring tasks in [from, to] (calendar ghosts)."""
    try:
        lo = date.fromisoformat(request.args["from"])
        hi = date.fromisoformat(request.args["to"])
    except (KeyError, ValueError):
        return err(tr("from/to missing"))
    if (hi - lo).days > 400:
        return err(tr("Date range too large"))
    out, t0 = [], time.monotonic()
    a, z = datetime(lo.year, lo.month, lo.day), datetime(hi.year, hi.month, hi.day, 23, 59)
    for t in db().execute(f"""SELECT id, due, repeat FROM tasks WHERE status=0 AND deleted_at IS NULL
                              AND repeat!='' AND due IS NOT NULL AND due<=? AND list_id IN {vis_sql()}
                              AND {tvis(db(), me(), write=True)} AND list_id NOT IN (SELECT id FROM lists WHERE archived=1)""",
                          (hi.isoformat(), me(), me())):
        if len(out) >= RR_OCC_TOTAL or time.monotonic() - t0 > RR_OCC_SECONDS:
            break  # hard caps: count + time
        try:
            rule = rr_rule(t["repeat"], t["due"])
            if rule is None:
                continue
            n = 0
            for occ in rule.xafter(a, inc=True):  # lazy: never materializes the whole range
                if occ > z or n >= RR_OCC_PER_TASK:
                    break
                n += 1
                if occ.date().isoformat() != t["due"]:
                    out.append({"id": t["id"], "date": occ.date().isoformat()})
        except (ValueError, TypeError, OverflowError):
            continue
    return jsonify(items=out)
