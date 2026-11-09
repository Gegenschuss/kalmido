"""2.777.0 (#5254): undo across devices, stage 6 -- habits in the core's step groups (core/undoareas.py).

A habit (table habits, always one person's own) is the tracked kind "habit" (core/writes.py obj_track): a change of its
settings (PATCH /api/habits/<id>, not a new order alone), putting it into the trash and taking it out record a snap step of
the person under the habit's lock (habits-<id>), labelled with its name. Its ticks and notes (habit_logs) are not part of the
copy. Taking back (core/undoweb.py): only its owner (need_habit's rule); the trash is the flag alone (undo_free), nothing
else happens on delete / restore. personal/habits.py calls hbu_pre / hbu_post through a function-local import (it comes
early in the module order, the core's write layer late)."""
from ..core.errors import Denied
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track

HBU_KIND = "habit"
HBU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def hbu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(HBU_KIND, "habits", area="self", undo_keep={"habits": {"user_id", "created_at", "sort", "reminded_on"}},
          undo_nofp={"habits": {"sort", "reminded_on"}},
          undo_label=hbu_label, undo_free=("deleted_at",))


def hbu_pre(c, uid, hid, what=None):
    r = c.execute("SELECT name FROM habits WHERE id=?", (int(hid),)).fetchone()
    key = HBU_WHAT.get(what or "")
    ua_pre(c, uid, HBU_KIND, hid, *((key, ua_plain(r["name"] if r else "", hid)) if key else ()))


def hbu_post(c):
    ua_post(c)


def hbu_need(c, uid, rid, oid):
    if not c.execute("SELECT 1 FROM habits WHERE id=? AND user_id=?", (int(rid), int(uid))).fetchone():
        raise Denied(404)
    return {"lock": f"habits-{int(rid)}"}


undo_need_reg(HBU_KIND, hbu_need)
