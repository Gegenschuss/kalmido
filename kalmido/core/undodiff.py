"""2.774.0 (#5251): undo across devices, stage 3 -- diff parts of the step groups (core/undogroups.py).

A snap part (core/writes.py obj_undo_pre) keeps the raw copy of every row of its object. An area whose objects are changed
field by field and in masses (tasks: one drag of 1000 tasks) keeps only what a step changed instead: a DIFF part, obj_undo.mode
'diff', snap = the area's own JSON ({op, before / after values or the data its own way back needs}). Taking it back runs the
area's own write path (the tasks: tasks/lifecycle.py apply_update with _prev = the values the step left, field by field), so
nothing new writes rows back and the area's checks, history, events and rules apply as for any edit.

The area records its parts when the request's writes are final: right before the commit (core/pg.py Conn.pre_commit), so a
change rolled back (a task of a batch that failed, back to its savepoint) records nothing; it reads the state then and keeps
the difference. While a group is taken back (core/undoweb.py) nothing records (undo_quiet), the undo is not a new step.

Interface:
  undo_diff_reg(kind, run, area)   run(c, uid, rid, data, redo) -> (data to keep, [what stayed]); raises Denied (403 / 404 =
                                   no access, 409 = changed elsewhere / its own reason) when nothing of the part could go
  undo_quiet() -> bool             a group is being taken back / forward in this request: record nothing
  undo_person(c) -> uid | None     the person whose steps this request records (None: no request, no person, an agent)
  ug_diff_add(c, uid, kind, rid, org_id, area, label, data)   one diff part into the request's group (in a pre-commit hook)"""
import json

from flask import g, has_request_context

from .db import iso, now_utc
from .pg import insert_id
from .undogroups import _agent, ug_added, ug_current, ug_fits

UNDO_DIFF = {}  # kind -> {"run": fn, "area": str}


def undo_diff_reg(kind, run, area):
    UNDO_DIFF[kind] = {"run": run, "area": area}


def undo_quiet():
    return has_request_context() and bool(g.get("undo_running"))


def undo_person(c):
    """The account a request records steps for: a signed-in person (not an agent), not while an undo runs."""
    if not has_request_context() or undo_quiet():
        return None
    u = getattr(g, "user", None)
    if u is None:
        return None
    uid = int(u["id"])
    key = f"undo_person_{uid}"
    if key not in g:
        g.setdefault(key, None if _agent(c, uid) else uid)
    return g.get(key)


def ug_diff_add(c, uid, kind, rid, org_id, area, label, data):
    """One diff part of uid into the request's group; nothing for a group too big for copies (it counts the part)."""
    js = json.dumps(data, ensure_ascii=False, default=str)
    n = len(js.encode())
    grp = ug_current(c, uid, area, org_id, label)
    if grp is None or not ug_fits(c, grp, n):
        return None
    pid = insert_id(c, "INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, fp_before, fp_after, created_at, "
                       "group_id, mode, bytes) VALUES(?,?,'',?,?,1,'done',?,'','',?,?,'diff',?)",
                    (org_id, int(uid), kind, int(rid), js, iso(now_utc()), grp["id"], n))
    ug_added(c, grp, n)
    return pid
