"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- bookings of the dispatch board in the core's step groups
(core/undoareas.py).

A booking (table hub_bookings, one row per resource of a job) is the tracked kind "booking" (core/writes.py obj_track): a
change of a job or one booking (PATCH /api/team/dispo/bookings/<id>: title, period, status, note -- one part per booking it
changes, one group), filling an open place / opening it again (…/fill), deleting (one or the whole job) and restoring record
a snap step of the person under each booking's lock (hub_bookings-<id>), labelled with the job's title. Taking back
(core/undoweb.py): the person may change the booking NOW (hub/dispo.py _may_change: who saved it or an admin of the area,
the dispatch board on); a place filled back with a resource checks it is one of the area's resources NOW (409 otherwise). An
undo tells nobody (no News for a booking that turns firm again; the forward change does). Booking a job records none (the
browser's step deletes it)."""
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .dispo import DSP_SLOT, _gate, _may_change, _res_index, _row, dsp_resources

DSU_KIND = "booking"
DSU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def dsu_label(r):
    return UG_LABEL, [ua_plain(r.get("title"), r.get("id"))]


obj_track(DSU_KIND, "hub_bookings", area="team",
          undo_keep={"hub_bookings": {"job", "created_by", "list_id", "event_id", "offer_root", "offer_doc", "offer_pos"}},
          undo_label=dsu_label, undo_free=("deleted_at",))
GONE[DSU_KIND] = "hub_bookings"  # history / undo rows of objects that went (core/objhooks.py)


def dsu_pre(c, uid, bid, what=None):
    """The person's step before a write of booking bid (after its lock hub_bookings-<id>); an agent records none."""
    r = c.execute("SELECT title FROM hub_bookings WHERE id=?", (int(bid),)).fetchone()
    key = DSU_WHAT.get(what or "")
    ua_pre(c, uid, DSU_KIND, bid, *((key, ua_plain(r["title"] if r else "", bid)) if key else ()))


def dsu_post(c):
    ua_post(c)


def dsu_need(c, uid, rid, oid):
    """Who may take a booking's step back now: who saved it or an admin of its area (the dispatch board on)."""
    _gate()
    r = _row(c, int(rid))
    _may_change(c, uid, [r])
    was = (r["resource_kind"], r["resource_id"])

    def fix(c):
        n = c.execute("SELECT * FROM hub_bookings WHERE id=?", (int(rid),)).fetchone()
        now = (n["resource_kind"], n["resource_id"])
        if now != was and n["resource_kind"] != DSP_SLOT and now not in _res_index(dsp_resources(c, uid, n["org_id"])):
            raise Denied(409, tr("unknown"))  # the place filled back with someone who is no resource of the area any more
    return {"fix": fix, "lock": f"hub_bookings-{int(rid)}"}


undo_need_reg(DSU_KIND, dsu_need)
