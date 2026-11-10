"""2.809.0 (#5476): undo across devices -- a project's sprints in the core's step groups (core/undoareas.py, core/undodiff.py).

- A change of a sprint (PATCH /api/sprints/<id>: name, goal, dates) records a snap step of its row (tracked kind
  "list_sprint", obj_track) under the list's sprint lock (sprints:<list>, as the route), labelled with its name. Only those
  columns go back (undo_keep = the rest: its state, number, review ...) and only they count for "changed since"; a sprint
  started or closed since is changed (its dates) only while it is still planned / running as the step left it.
- Planning a sprint (POST /api/lists/<id>/sprints), removing a planned one (DELETE, into the trash with a copy) and taking it
  out (POST /api/sprints/<id>/restore) record a diff part (kind "sprint_life", {op, list_id}): taken back / forward through
  the area's own ways -- a planned sprint goes into the trash again (sprints.py spr_trash, its tasks back to the backlog), a
  removed one comes back with its id and the tasks still in no sprint (parttrash.py lpt_sprint_back). Only a planned sprint
  is removed by an undo (a sprint started since stays, named).
Rights of today: whoever may change the project (need_list), never an agent.

Interface:
  spu_pre(c, uid, sid) / spu_post(c) -> group id | None    around the PATCH's write
  spu_life(c, sid, op, lid, name=None) -> group id | None  after plan / remove / restore"""
from flask import g

from ..core.access import need_list
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.objhooks import GONE
from ..core.pg import write_lock
from ..core.undoareas import UA_DELETED, ua_done, ua_plain, ua_pre
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .lpundo import AllBut
from .parttrash import lpt_sprint_back
from .sprints import spr_row, spr_trash

SPU_KIND = "list_sprint"
SPU_LIFE = "sprint_life"
SPU_AREA = "tasks"
SPU_COLS = frozenset({"name", "goal", "start", "end_day"})
SPU_PLANNED = N_("Planned: {0}")
SPU_GONE = N_("The sprint is not where this step left it, so it cannot be undone")


def _name(r):
    n = ua_plain(r.get("name"), None) if r.get("name") else ""
    return n if n and n != "#" else ["Sprint {0}", r.get("num") or ""]


def spu_label(r):
    return UG_LABEL, [_name(r)]


obj_track(SPU_KIND, "sprints", area=SPU_AREA, undo_keep={"sprints": AllBut(SPU_COLS)},
          undo_nofp={"sprints": AllBut(SPU_COLS | {"state"})}, undo_label=spu_label)
GONE[SPU_KIND] = "sprints"


def spu_pre(c, uid, sid):
    ua_pre(c, uid, SPU_KIND, sid)


def spu_post(c):
    return ua_done(c)


def spu_need(c, uid, rid, oid):
    s = spr_row(c, rid)
    if not s:
        raise Denied(404)
    need_list(c, s["list_id"])
    if s["state"] == "closed":
        raise Denied(409, tr("A closed sprint keeps its dates"))
    return {"lock": f"sprints:{s['list_id']}"}


undo_need_reg(SPU_KIND, spu_need)


def spu_life(c, sid, op, lid, name=None):
    uid = undo_person(c)
    if uid is None:
        return None
    s = spr_row(c, sid)
    nm = _name(dict(s)) if s else (ua_plain(name, sid) if name else ["Sprint {0}", ""])
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    label = (UA_DELETED if op == "delete" else SPU_PLANNED, [nm])
    if not ug_diff_add(c, uid, SPU_LIFE, sid, org[0] if org else None, SPU_AREA, label, {"op": op, "list_id": int(lid)}):
        return None
    return (g.get("undo_group") or {}).get("id")


def spu_life_run(c, uid, sid, data, redo):
    there = (data.get("op") == "delete") != bool(redo)
    lid = int(data.get("list_id") or 0)
    need_list(c, lid)
    write_lock(c, f"sprints:{lid}")
    s = spr_row(c, sid)
    if there:
        if s:
            raise Denied(409, tr(SPU_GONE))
        try:
            lpt_sprint_back(c, sid, uid)
        except Denied as e:
            raise (Denied(409, tr(SPU_GONE)) if e.code == 404 else e) from None
    else:
        if not s or s["state"] != "planned":
            raise Denied(409, tr(SPU_GONE))
        spr_trash(c, sid, uid)
    return data, []


undo_diff_reg(SPU_LIFE, spu_life_run, SPU_AREA)
