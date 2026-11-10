"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- absences of the team in the core's step groups
(core/undoareas.py).

An absence (table hub_absences) is the tracked kind "absence" (core/writes.py obj_track): a change in its dialog
(PATCH /api/team/absences/<id>: kind, days, half day, note), putting it into the trash and taking it out record a snap step of
the person under the absence's lock (hub_absences-<id>), labelled with its days (the kind and the note may be sealed). A
holiday request's decision (hub/leave.py) is not a step of the person who changed it: a decision since makes the step a
conflict (the fingerprint), an undo never approves anything the admins did not approve -- it puts back the row as it was,
an approved absence only as it was approved. Taking back (core/undoweb.py): the person may change the absence NOW (its own
person or an admin of its area, hub/absence.py _may_edit), never an agent. Entering an absence records none (the browser's
step deletes it)."""
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .absence import _gate, _may_edit, _row

ABU_KIND = "absence"
ABU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def abu_days(r):
    s, e = (r.get("start_date") or ""), (r.get("end_date") or "")
    return s if not e or e == s else f"{s} - {e}"


def abu_label(r):
    return UG_LABEL, [abu_days(r)]


obj_track(ABU_KIND, "hub_absences", area="team", undo_keep={"hub_absences": {"user_id", "created_by"}},
          undo_label=abu_label, undo_free=("deleted_at",))
GONE[ABU_KIND] = "hub_absences"  # an account's deletion takes its history / undo rows (core/objhooks.py)


def abu_pre(c, uid, aid, what=None):
    """The person's step before a write of absence aid (after its lock hub_absences-<id>); an agent records none."""
    key = ABU_WHAT.get(what or "")
    r = c.execute("SELECT start_date, end_date FROM hub_absences WHERE id=?", (int(aid),)).fetchone()
    ua_pre(c, uid, ABU_KIND, aid, *((key, abu_days(dict(r)) if r else f"#{int(aid)}") if key else ()))


def abu_post(c):
    ua_post(c)


def abu_need(c, uid, rid, oid):
    """Who may take an absence's step back now: its own person or an admin of its area (in the trash or not)."""
    _gate()
    r = _row(c, int(rid))
    if not _may_edit(c, uid, r):
        raise Denied(403)
    return {"lock": f"hub_absences-{int(rid)}"}


undo_need_reg(ABU_KIND, abu_need)
