"""2.774.0 (#5251): undo across devices, stage 3 -- the tasks' steps on the server (diff parts, core/undodiff.py).

Every change of a person to a task records its step in the request's step group (core/undogroups.py), kind 'task', area
'tasks', whatever way it came (PATCH, multi-select / batch, drag, keyboard, the offline queue sent later, a proposal applied):
  fields    tasks/lifecycle.py apply_update: the task's own values before (tu_mark, once per request and task) and after, only
            the ones that changed ({op: fields, b: before, a: after}); taken back = apply_update with the values before and
            _prev = the values the step left: a field changed elsewhere since stays (named), the others go back
  complete  do_complete: what its undo payload needs ({op, st, u}); taken back = undo_status (the completed copy of a recurring
            task goes, the date comes back), forward again = tsk_finish
  reopen    tsk_reopen / the batch's reopen: the completion it ended; taken back = undo_status, forward = tsk_reopen
  delete / restore   the trash: back = restore_task / do_delete (only while the task is still there / not there)
  create    a new task: back = to the trash (not when someone else changed it since), forward = back from the trash
Recorded right before the commit (core/pg.py Conn.pre_commit, tu_flush), so a task a batch left as it was records nothing.
The label names the task (one) or counts them (several); a ciphertext title (a list with the lock) is never put in a label,
the app sets the title it can read (GET /api/undo kind / ref_id).
Sections (lists/sections.py): a section's name, limits, time limits and meaning (kind 'section', sec_apply with _prev) and the
order of a project's sections (kind 'section_order', ref = the project, only while the order is still the one the step left).
2.997.0 (#5613 #5614): the code snippets (the whole list, unchanged ones keep their author: snip_keep) and the lock are fields
of the step too -- since stage 7 the browser keeps no copy, so without them "Code snippet removed" / "Task unlocked" had no
way back (the arrow took back an older step instead).
Not here: creating / deleting a section and a project's settings (a step of their own later)."""
import json
from datetime import date

from flask import g

from ..collab.liste2e import le2a_moving, le2a_subtree, le2e_is_cipher
from ..collab.reactions import ltag_names
from ..core.access import need_list, need_task
from ..core.db import bump, iso_ms, now_utc
from ..core.errors import Denied
from ..core.i18n import N_, short_day, tr
from ..core.pg import write_lock
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_TRACKED
from ..core.undoweb import UG_KEPT, UG_KEPT_REDO
from ..lists.listtrash import otr_err_task
from ..lists.sections import sec_apply
from ..tasks.lifecycle import apply_update, need_live, restore_task, signed, trash_task, tsk_finish, tsk_reopen, undo_status
from ..tasks.snippets import snip_parse
from ..tasks.tasks import my_tags
from ..tasks.validation import TASK_FIELDS

TU_COLS = TASK_FIELDS  # 2.997.0 (#5613 #5614): with the snippets and the lock (was: without, no way back for them since stage 7)
TU_EXTRA = ("tags", "ltags", "fields", "people")
TU_KIND = "task"
TU_AREA = "tasks"
TU_EDIT = N_("Edited {0}")
TU_DONE = N_("Completed {0}")
TU_REOPEN = N_("Reopened {0}")
TU_DEL = N_("Deleted {0}")
TU_RESTORE = N_("Restored {0}")
TU_NEW = N_("Created: {0}")
TU_MANY = N_("{0} tasks changed")
TU_TASK = N_("Task")
TU_LABEL = {"fields": TU_EDIT, "complete": TU_DONE, "reopen": TU_REOPEN, "delete": TU_DEL, "restore": TU_RESTORE, "create": TU_NEW}
TU_GONE = N_("Changed in the meantime, nothing to undo")
TU_SEC = N_("Section renamed to {0}")
TU_SEC_SET = N_("Section {0}")
TU_SEC_ORDER = N_("Sections reordered")
TU_OTHER = N_("Changed by someone else in the meantime")  # 2.905.0 (#5255): the key exists (objsave.js)


def _marks(c):
    """The request's marks (None when nothing is recorded: no person, an agent, an undo running); registers the flush."""
    uid = undo_person(c)
    if uid is None:
        return None
    m = g.get("tu_marks")
    if m is None or m["uid"] != uid:
        m = g.tu_marks = {"uid": uid, "fields": {}, "seq": []}
    c.pre_commit["tasks.undo"] = tu_flush
    return m


def _extra(c, tid, k):
    if k == "tags":
        return sorted(my_tags(c, tid))
    if k == "ltags":
        return sorted(ltag_names(c, tid))
    if k == "fields":
        return {str(r[0]): r[1] for r in c.execute("SELECT field_id, value FROM task_field_values WHERE task_id=? ORDER BY field_id", (tid,))}
    return [r[0] for r in c.execute("SELECT user_id FROM task_people WHERE task_id=? ORDER BY user_id", (tid,))]


def _state(c, row, extras):
    st = {k: row[k] for k in TU_COLS if k in row.keys()}
    if isinstance(st.get("snippets"), str) and st["snippets"].startswith("["):  # 2.997.0 (#5613): the list (the way back writes a list)
        st["snippets"] = snip_parse(st["snippets"])
    for k in extras:
        st[k] = _extra(c, row["id"], k)
    return st


def tu_mark(c, tid, row, b):
    """apply_update, before it writes: the task's values (row = as stored now) and the extras b touches (tags, list tags,
    field values, people). The first mark of a task in a request is its "before"; a later one adds extras not read yet."""
    m = _marks(c)
    if m is None or row is None:
        return
    want = {k for k in TU_EXTRA if k in b} | ({"tags"} if "add_tags" in b else set())
    have = m["fields"].get(tid)
    if have is None:
        m["fields"][tid] = (_state(c, row, want), set(want))
        m["seq"].append(("fields", tid, None))
        return
    for k in want - have[1]:
        have[0][k] = _extra(c, tid, k)
        have[1].add(k)


def tu_op(c, tid, op, data=None):
    """complete / reopen / delete / restore / create of task tid (data = what its way back needs), checked at the commit."""
    m = _marks(c)
    if m is not None:
        m["seq"].append((op, int(tid), dict(data or {})))


def _js(v):
    if v in ("", None):
        return None
    return json.dumps(v, sort_keys=True, default=str) if isinstance(v, (dict, list)) else str(v)


def _holds(row, op, data):
    """Does the op still hold at the commit (not rolled back to a savepoint)?"""
    if op == "complete":
        u = data.get("u") or {}
        return bool(u.get("at")) and (row["due"] == u.get("next") if u.get("copy_id") else row["status"] == data.get("st"))
    if op == "reopen":
        return row["status"] == 0
    if op in ("delete", "create"):
        return (op == "delete") == bool(row["deleted_at"])
    if op == "restore":
        return not row["deleted_at"]
    return False


def tu_flush(c):
    """The marked tasks' steps into the request's group (core/pg.py Conn.pre_commit, right before the commit). A failure
    here never costs the write itself: it runs in a savepoint and only logs."""
    m = g.pop("tu_marks", None)
    if not m or not m["seq"]:
        return
    try:
        with c.savepoint():
            _flush(c, m)
    except Exception as e:  # noqa: BLE001 -- the step is lost, the change itself commits
        print("tasks undo step not recorded:", type(e).__name__, str(e)[:200], flush=True)


TU_PLAIN = ("title", "content", "url")  # 2.787.0 (#5417): the task's own texts a locked list keeps as ciphertexts


def _tu_locked(c, lid):
    return bool(lid) and bool(c.execute("SELECT 1 FROM lists WHERE id=? AND e2e IS NOT NULL", (lid,)).fetchone())


def _plain_under_lock(c, row, b):
    """2.787.0 (#5417, Fable review #5408): the task's list has the lock now and "before" would keep a plain text (it came
    in from an open list in this request, or a text of it is not a ciphertext): the step would put that text into
    obj_undo.snap AFTER the move's scrub (le2b_scrub_undo). Such a task records no step at all -- not a half one, whose way
    back would write a ciphertext into the open list (400)."""
    if not _tu_locked(c, row["list_id"]):
        return False
    if "list_id" in b and b["list_id"] != row["list_id"] and not _tu_locked(c, b["list_id"]):
        return True
    return any(isinstance(b.get(k), str) and b[k] and not le2e_is_cipher(b[k]) for k in TU_PLAIN)


def _lock_extras(c, tid):
    """2.800.0 (#5447): texts a move of task tid between a locked and another list would have to carry re-encrypted besides
    its own (subtasks, comments, text field values -- liste2e.py le2a_move); the server cannot, it has no key."""
    ids = le2a_subtree(c, tid)
    if len(ids) > 1:
        return True
    return bool(c.execute("SELECT 1 FROM obj_comments WHERE kind='task' AND ref_id=? AND COALESCE(body, '')<>'' LIMIT 1", (tid,)).fetchone()
                or c.execute("""SELECT 1 FROM task_field_values v JOIN list_fields lf ON lf.id=v.field_id WHERE v.task_id=?
                                AND lf.type='text' AND COALESCE(v.value, '')<>'' LIMIT 1""", (tid,)).fetchone())


def _kept_move(c, row, b):
    """2.800.0 (#5447, Fable review 2.787): a move OUT of a locked list (or between two locks) whose way back would need the
    browser for more than the task's own texts (subtasks, comments, text field values): the move and the texts that changed
    format are marked as not undoable at recording ("keep"), so taking the step back leaves them and names them (UG_KEPT)
    instead of ending in 4xx (list_e2e_move); the other fields of the step still go back."""
    src = b.get("list_id")
    if not src or src == row["list_id"] or not _tu_locked(c, src) or not le2a_moving(c, row["list_id"], src):
        return []
    if not _lock_extras(c, row["id"]):
        return []
    return ["list_id"] + [k for k in TU_PLAIN if k in b]


def _flush(c, m):
    parts, skip = [], set()
    for op, tid, data in m["seq"]:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if row is None:
            continue
        if op == "fields":
            before, extras = m["fields"][tid]
            after = _state(c, row, extras)
            keys = [k for k in before if _js(before[k]) != _js(after.get(k))]
            b = {k: before[k] for k in keys}
            if keys and _plain_under_lock(c, row, b):
                skip.add(tid)
            elif keys:
                a = {k: after.get(k) for k in keys}
                if "fields" in b:  # 2.905.0 (#5255): per field, a value that was not there (or is gone) is None, so it goes back empty
                    ids = [i for i in sorted(set(b["fields"] or {}) | set(a.get("fields") or {})) if _js((b["fields"] or {}).get(i)) != _js((a.get("fields") or {}).get(i))]
                    b["fields"], a["fields"] = {i: (b["fields"] or {}).get(i) for i in ids}, {i: (a.get("fields") or {}).get(i) for i in ids}
                d = {"op": "fields", "b": b, "a": a}
                kept = _kept_move(c, row, b)
                if kept:
                    d["keep"] = kept
                parts.append((row, d))
        elif _holds(row, op, data):
            parts.append((row, {"op": op, **data}))
    parts = [p for p in parts if p[0]["id"] not in skip]  # 2.787.0 (#5417): no part at all for such a task in this request
    if not parts:
        return
    tids = {r["id"] for r, _ in parts}
    if len(tids) == 1:
        last = parts[-1][0]
        # 2.787.0 (#5417, review): a list that is locking itself (e2e set, task not converted yet) names no plain title
        ttl = [TU_TASK] if _tu_locked(c, last["list_id"]) else _title(last["title"])
        # 2.1074.0 (#5493): the title in quotes, as the app's history writes it (undo.js qn)
        label = (TU_LABEL.get(parts[0][1]["op"], TU_EDIT), [[TU_Q, ttl] if isinstance(ttl, str) else ttl])
        if len(parts) == 1 and parts[0][1]["op"] == "fields":  # 2.1074.0 (#5493): what changed, as the app names it
            label = _fields_label(c, parts[0][1], ttl) or label
    else:
        label = (TU_MANY, [len(tids)])
    orgs = {}
    for row, data in parts:
        lid = row["list_id"]
        if lid not in orgs:
            orgs[lid] = _org(c, lid)
        ug_diff_add(c, m["uid"], TU_KIND, row["id"], orgs[lid], TU_AREA, label, data)


TU_Q = N_("“{0}”")  # the key exists (static/js/undo.js qn)
TU_PRIO = (N_("None"), N_("Low"), "", N_("Medium"), "", N_("High"), "", N_("Urgent"))


def _fields_label(c, d, ttl):
    """2.1074.0 (#5493): the label of one task's field step as the app's history names it (static/js/undo.js histLabel):
    "Priority of “Jump”: High" instead of "Edited Jump". None = the general one."""
    b, a = d.get("b") or {}, d.get("a") or {}
    ch = set(a) | set(b)
    n = [TU_Q, ttl] if isinstance(ttl, str) else ttl
    one = len(ch) == 1
    if ch == {"locked"}:
        return (N_("Locked {0}") if a.get("locked") else N_("Unlocked {0}"), [n])
    if "list_id" in ch:  # no project / section / field name in a label (Fable review 2.1074: a lock later keeps it)
        return (N_("Moved {0}"), [n])
    if "parent_id" in ch:
        return (N_("{0} is now a subtask") if a.get("parent_id") else N_("{0} is now a main task"), [n])
    if one and "title" in ch:
        return (N_("Renamed {0}"), [n])
    if one and "content" in ch:
        return (N_("Description of {0}"), [n])
    if one and "priority" in ch:
        try:
            p = TU_PRIO[int(a.get("priority") or 0)] or TU_PRIO[0]
        except (IndexError, TypeError, ValueError):
            p = TU_PRIO[0]
        return (N_("Priority of {0}: {1}"), [n, [p]])
    if one and "tags" in ch:
        return (N_("Tags of {0}"), [n])
    if one and "assignee_id" in ch:
        if not a.get("assignee_id"):
            return (N_("{0} unassigned"), [n])
        r = c.execute("SELECT display_name, username FROM users WHERE id=?", (a["assignee_id"],)).fetchone()
        return (N_("{0} assigned to {1}"), [n, (r["display_name"] or r["username"]) if r else "?"])
    if one and "fields" in ch:
        return (N_("Custom fields of {0}"), [n])
    if one and "pinned" in ch:
        return (N_("Pinned {0}") if a.get("pinned") else N_("Unpinned {0}"), [n])
    if one and "url" in ch:
        return (N_("Link of {0}"), [n])
    if one and "section_id" in ch:
        return (N_("Moved {0}"), [n])
    if "plan_start" in ch and "due" not in ch:
        return (N_("Planned {0}") if a.get("plan_start") else N_("Unplanned {0}"), [n])
    if ch & {"due", "start", "due_time"}:
        if not a.get("due"):
            return (N_("Date of {0} removed"), [n])
        try:
            day = short_day(date.fromisoformat(str(a["due"])[:10]))
        except ValueError:
            day = str(a["due"])[:10]
        return (N_("Date of {0}: {1}"), [n, day])
    if ch & {"repeat", "repeat_from"}:
        return (N_("Repeat of {0}"), [n])
    if ch & {"reminders", "remind_at"}:
        return (N_("Reminder of {0}"), [n])
    return (TU_EDIT, [n])


def _org(c, lid):
    r = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
    return r[0] if r else None


def _title(v):
    return [TU_TASK] if not v or le2e_is_cipher(v) else str(v)[:60]


def tu_section(c, sid, cur, keys):
    """sec_apply: the section's values before (cur) and now; a step when one of keys changed (written at once: the routes of
    a section have no savepoints)."""
    uid = undo_person(c)
    if uid is None or cur is None:
        return
    now = c.execute("SELECT list_id, name, wip_limit, wip_hard, dwell_warn_h, dwell_alert_h, kind FROM sections WHERE id=?", (sid,)).fetchone()
    ch = [k for k in keys if _js(cur[k]) != _js(now[k])]
    if not ch:
        return
    plain = not le2e_is_cipher(now["name"] or "")  # a list with the lock: the name is a ciphertext, never in a label
    label = (TU_SEC, [now["name"]]) if "name" in ch and plain else (TU_SEC_SET, [now["name"] if plain else ""])
    ug_diff_add(c, uid, "section", sid, _org(c, now["list_id"]), TU_AREA, label,
                {"op": "fields", "b": {k: cur[k] for k in ch}, "a": {k: now[k] for k in ch}})


def tu_sec_order(c, lid, before, after):
    uid = undo_person(c)
    if uid is not None:
        ug_diff_add(c, uid, "section_order", lid, _org(c, lid), TU_AREA, (TU_SEC_ORDER, []), {"op": "order", "b": before, "a": after})


# ---------------------------------------------------------------- taking a step back / forward (core/undoweb.py)
def _fields(c, tid, data, redo):
    need_live(c, tid)
    src, dst = (data.get("b") or {}, data.get("a") or {}) if redo else (data.get("a") or {}, data.get("b") or {})
    if not dst:
        raise Denied(409, tr(TU_GONE))
    kept = [k for k in data.get("keep") or [] if k in dst]  # 2.800.0 (#5447): marked at recording, never written back
    if kept:
        dst = {k: v for k, v in dst.items() if k not in kept}
        if not dst:
            raise Denied(409, tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(kept)))
        src = {k: v for k, v in src.items() if k not in kept}
    cf = []
    e = apply_update(c, tid, {**dst, "_prev": src}, cf, lock=True)
    if e:
        raise Denied(409, e)
    left = [x["field"] for x in cf]
    if left and len(left) >= sum(len(v) if k == "fields" and isinstance(v, dict) else 1 for k, v in dst.items()):
        raise Denied(409, tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(kept + left)))
    return data, kept + left


def _status_back(c, tid, u):
    e = undo_status(c, tid, signed(tid, u))
    if e:
        raise Denied(409, e)


def _complete(c, tid, data, redo):
    if not redo:
        _status_back(c, tid, data.get("u") or {})
        return data, []
    need_live(c, tid)
    if c.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] != 0:
        raise Denied(409, tr(TU_GONE))
    u = {}
    tsk_finish(c, tid, int(data.get("st") or 2), u)
    return {**data, "u": u}, []


def _reopen(c, tid, data, redo):
    if not redo:
        _status_back(c, tid, data.get("u") or {})
        return data, []
    need_live(c, tid)
    old = c.execute("SELECT status, completed_at, completed_by FROM tasks WHERE id=?", (tid,)).fetchone()
    if old["status"] == 0:
        raise Denied(409, tr(TU_GONE))
    u = {"op": "reopen", "status": old["status"], "completed_at": old["completed_at"], "completed_by": old["completed_by"]}
    tsk_reopen(c, tid, u)
    return {**data, "u": u}, []


def _trash(c, tid, out):
    """out = True: to the trash (only while it is not there), False: back (only while it is there)."""
    row = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if bool(row["deleted_at"]) == out:
        raise Denied(409, tr(TU_GONE))
    if out:
        trash_task(c, tid)
        return
    if otr_err_task(c, tid) is not None:  # the project is in the trash: it comes back with its project only
        raise Denied(409, tr("This task’s project is in the trash: restore the project"))
    restore_task(c, tid)


def _created_changed(c, uid, tid, since):
    """Someone else changed the created task since (activity of another account): it is not put to the trash."""
    return bool(since) and c.execute("SELECT 1 FROM activity WHERE task_id=? AND created_at>? AND (user_id IS NULL OR user_id!=?) LIMIT 1",
                                     (tid, str(since), int(uid))).fetchone()


def tu_run(c, uid, tid, data, redo):
    """core/undodiff.py run: one task part back (redo: forward). The rights of now: write access to the task (need_task)."""
    role = need_task(c, tid)
    op = data.get("op")
    if op in ("delete", "create", "restore") and role == "participant":
        raise Denied(403, tr("Participants cannot delete tasks"))
    if op == "fields":
        out = _fields(c, tid, data, redo)
    elif op == "complete":
        out = _complete(c, tid, data, redo)
    elif op == "reopen":
        out = _reopen(c, tid, data, redo)
    elif op in ("delete", "restore"):
        out_ = (op == "delete") == redo
        # 2.905.0 (#5255, was the browser's guard): back into the trash only while nobody else changed it since it came out
        if out_ and _created_changed(c, uid, tid, data.get("back_at")):
            raise Denied(409, tr(TU_OTHER))
        _trash(c, tid, out_)
        out = ({**data, "back_at": iso_ms(now_utc())} if not out_ else data, [])
    elif op == "create":
        if not redo and _created_changed(c, uid, tid, data.get("at")):
            raise Denied(409, tr(TU_GONE))
        _trash(c, tid, not redo)
        out = (data, [])
    else:
        raise Denied(404)
    bump(c, TU_AREA)
    return out


def sec_run(c, uid, sid, data, redo):
    """A section's step back / forward: sec_apply with _prev (a value changed elsewhere since stays, named)."""
    src, dst = (data.get("b") or {}, data.get("a") or {}) if redo else (data.get("a") or {}, data.get("b") or {})
    left = [x["field"] for x in sec_apply(c, sid, {**dst, "_prev": src})]
    if left and len(set(left)) >= len(dst):
        raise Denied(409, tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(left)))
    bump(c, TU_AREA)
    return data, left


def sec_order_run(c, uid, lid, data, redo):
    """The order of a project's sections back / forward: only while it is still the one the step left (same sections)."""
    need_list(c, lid)
    write_lock(c, f"sections:{lid}")
    src, dst = (data.get("b"), data.get("a")) if redo else (data.get("a"), data.get("b"))
    cur = [r[0] for r in c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))]
    if not isinstance(dst, list) or cur != src or sorted(dst) != sorted(cur):
        raise Denied(409, tr(TU_GONE))
    c.executemany("UPDATE sections SET sort=? WHERE id=?", [(k, i) for k, i in enumerate(dst)])
    bump(c, TU_AREA)
    return data, []


undo_diff_reg(TU_KIND, tu_run, TU_AREA)
undo_diff_reg("section", sec_run, TU_AREA)
undo_diff_reg("section_order", sec_order_run, TU_AREA)
# the watchdog drops the parts of a task / section / project deleted for good (core/undogroups.py ug_drop_orphans)
UG_TRACKED.update({TU_KIND: "tasks", "section": "sections", "section_order": "lists"})
