"""2.809.0 (#5476): undo across devices -- a project's custom fields in the core's step groups (core/undoareas.py,
core/undodiff.py).

- A change of a field (PATCH /api/fields/<id>: name, options, shown on the rows, order, required) records a snap step of its
  row (tracked kind "list_field", obj_track) under the field's lock (field-<id>, core/objparts.py part_write), labelled with its
  name. Not a formula field (its expression lives in more than the row) and not a change that removed options holding values
  (those values are gone; the browser keeps its own way back for it): such a save records no step.
- Creating a field, deleting it (into the field trash) and restoring it from there record a diff part (kind "field_life",
  {op, trash}) in the person's group: taken back / forward through the area's own ways -- a new / restored field goes into the
  field trash (fields.py fd_trash), a deleted one comes back with its id and its values that still fit (fd_back).
Taking back with the rights of today (core/undoweb.py): the project's owner or admins (need_field / need_list manage), never
an agent; a change whose options would drop an option that holds values now, or show more fields on the rows than allowed,
stays (409).

Interface:
  fdu_pre(c, fid, r) -> state for fdu_post          before the PATCH writes (after part_write's lock and checks)
  fdu_post(c, fid, state) -> group id | None        right before its commit
  fdu_life(c, fid, op, name, lid, trash_id) -> group id | None    after create / delete / restore"""
import json

from flask import g

from ..core.access import need_list
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.objhooks import GONE
from ..core.pg import write_lock
from ..core.undoareas import UA_DELETED, ua_done, ua_plain, ua_pre
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .fields import FIELD_KIND, FIELD_PINNED_MAX, fd_back, fd_trash, fields_pinned_ok, ftr_person, need_field

FDU_KIND = "list_field"
FDU_LIFE = "field_life"
FDU_AREA = "tasks"
FDU_NEW = N_("New field: {0}")
FDU_GONE = N_("The field is not where this step left it, so it cannot be undone")
FDU_USED = N_("An option this would remove holds values now, so it cannot be undone")


def fdu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(FDU_KIND, "list_fields", area=FDU_AREA, undo_keep={"list_fields": {"list_id", "type", "created_at", "org_field_id"}},
          undo_label=fdu_label)
GONE[FDU_KIND] = "list_fields"  # the history / undo rows of a field deleted for good go (core/objhooks.py)


def _nvals(c, fid):
    return c.execute("SELECT COUNT(*) FROM task_field_values WHERE field_id=?", (int(fid),)).fetchone()[0]


def fdu_pre(c, fid, r):
    if r["type"] == "formula" or undo_person(c) is None:
        return None
    ua_pre(c, undo_person(c), FDU_KIND, fid)
    return _nvals(c, fid)


def fdu_post(c, fid, n0):
    if n0 is None:
        return None
    return ua_done(c, drop=_nvals(c, fid) != n0)  # values went with removed options: no step of the server


def _opt_ids(row):
    try:
        return {str(o.get("id")) for o in (json.loads(row["options"] or "{}").get("options") or []) if isinstance(o, dict)}
    except (ValueError, AttributeError):
        return set()


def fdu_need(c, uid, rid, oid):
    r = need_field(c, rid)  # 404 / 403: the owner and admins of its project now

    def fix(c):
        now = c.execute("SELECT * FROM list_fields WHERE id=?", (int(rid),)).fetchone()
        if now["type"] in ("select", "multiselect"):
            keep = _opt_ids(now)
            for (v,) in c.execute("SELECT DISTINCT value FROM task_field_values WHERE field_id=?", (int(rid),)).fetchall():
                if any(x not in keep for x in str(v).split(",") if x):
                    raise Denied(409, tr(FDU_USED))
        if now["pinned"] and not r["pinned"] and not fields_pinned_ok(c, now["list_id"], int(rid)):
            raise Denied(409, tr("At most {0} fields can be shown on the task rows", FIELD_PINNED_MAX))
    return {"fix": fix, "lock": f"field-{int(rid)}"}


undo_need_reg(FDU_KIND, fdu_need)


def fdu_life(c, fid, op, name, lid, trash_id):
    uid = undo_person(c)
    if uid is None:
        return None
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    label = (UA_DELETED if op == "delete" else FDU_NEW, [ua_plain(name, fid)])
    if not ug_diff_add(c, uid, FDU_LIFE, fid, org[0] if org else None, FDU_AREA, label,
                       {"op": op, "list_id": int(lid), "trash": trash_id}):
        return None
    return (g.get("undo_group") or {}).get("id")


def fdu_life_run(c, uid, fid, data, redo):
    """Back / forward: there = the field should exist after this run (create / restore forward, a delete back)."""
    ftr_person()
    there = (data.get("op") == "delete") != bool(redo)
    write_lock(c, f"field-{int(fid)}")
    row = c.execute("SELECT * FROM list_fields WHERE id=?", (int(fid),)).fetchone()
    if there:
        tr_row = c.execute("SELECT * FROM list_part_trash WHERE id=? AND kind=? AND ref_id=?",  # 2.783.0 (#5368): the core's copy trash
                           (int(data.get("trash") or 0), FIELD_KIND, int(fid))).fetchone()
        if row is not None or tr_row is None:
            raise Denied(409, tr(FDU_GONE))
        need_list(c, tr_row["list_id"], manage=True)
        try:
            fd_back(c, tr_row)
        except BadInput as e:
            raise Denied(409, str(e)) from None
        return {**data, "trash": None}, []
    if row is None:
        raise Denied(409, tr(FDU_GONE))
    need_field(c, fid)
    _n, tid = fd_trash(c, row)
    return {**data, "trash": tid}, []


undo_diff_reg(FDU_LIFE, fdu_life_run, FDU_AREA)
