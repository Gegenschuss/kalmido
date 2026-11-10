"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- the booking page's appointment types in the core's step
groups (core/undoareas.py).

An appointment type (table appt_types, always one person's own) is the tracked kind "appt_type" (core/writes.py obj_track): a
change in its dialog (PATCH /api/appt/types/<id>: name, length, buffer, notice, place, note, on / off), deleting it and
restoring it record a snap step of its owner under its lock (appt_types-<id>), labelled with its name. Its bookings are not
part of the copy (they stay as they are, as with the delete). Taking back (core/undoweb.py): only its owner, the booking page
switched on (calendars/apptbook.py apb_gate). Adding a type records none (the browser's step deletes it)."""
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .apptbook import apb_gate

APU_KIND = "appt_type"
APU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def apu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(APU_KIND, "appt_types", area="calendar", undo_keep={"appt_types": {"user_id", "sort"}}, undo_nofp={"appt_types": {"sort"}},
          undo_label=apu_label, undo_free=("deleted_at",))
GONE[APU_KIND] = "appt_types"  # an account's deletion takes its history / undo rows (core/objhooks.py)


def apu_pre(c, uid, tid, what=None):
    """The owner's step before a write of appointment type tid (after its lock appt_types-<id>); an agent records none."""
    r = c.execute("SELECT name FROM appt_types WHERE id=?", (int(tid),)).fetchone()
    key = APU_WHAT.get(what or "")
    ua_pre(c, uid, APU_KIND, tid, *((key, ua_plain(r["name"] if r else "", tid)) if key else ()))


def apu_post(c):
    ua_post(c)


def apu_need(c, uid, rid, oid):
    """Who may take an appointment type's step back now: its owner with the booking page on."""
    if apb_gate(c) != uid or not c.execute("SELECT 1 FROM appt_types WHERE id=? AND user_id=?", (int(rid), int(uid))).fetchone():
        raise Denied(404)
    return {"lock": f"appt_types-{int(rid)}"}


undo_need_reg(APU_KIND, apu_need)
