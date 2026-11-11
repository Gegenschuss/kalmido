"""2.777.0 (#5254): undo across devices, stage 6 -- calendar events in the core's step groups (core/undoareas.py).

An event (table events) is the tracked kind "event" (core/writes.py obj_track): a change (web: PATCH /api/events/<id>, also
one occurrence, moving it into another calendar), putting it into the trash and taking it out record a snap step of the
person under the event's lock (events/model.py ev_lock), labelled with its title. Its identity for devices (uid, href), the
invitations' sequence and the import marks stay as they are on undo (undo_keep); the attendees are not part of the copy
(their answers are theirs). Taking back (core/undoweb.py): the person needs write on the event NOW (need_event), and on the
calendar the copy puts it back into; coming out of / going into the trash runs the calendar's own restore / delete
(cal_touch, bump; ev_delete tells the invited people of the server). No mails from an undo: a restored event does not invite
its external attendees again (the forward restore does).
2.985.0 (#5394, stage 6 rest): a change / delete through CalDAV (events/dav.py PUT / DELETE) records its step the same way
(API v1 shares the web's op_event_*); a whole calendar into the trash and out of it (events/web.py op_cal_delete /
op_cal_restore) is a trash step of the core kind "evcal" taken back the calendar's way (core/undoweb.py undo_trash_reg):
back = cal_restore_do (manage, the calendars' limit, its events with it), forward = evu_cal_away (the core's obj_trash with
its events, 2.947.0 #5367; the people of the server told; no mails to external attendees from an undo)."""
from ..accounts.orgs import ws_fit_problem
from ..core.access import live_sql  # 2.985.0 (#5394)
from ..core.errors import Denied
from ..core.undoareas import ua_plain, ua_trash_fix
from ..core.undogroups import UG_LABEL, undo_label  # 2.985.0 (#5394): undo_label
from ..core.undoweb import undo_need_reg, undo_trash_reg  # 2.985.0 (#5394): undo_trash_reg
from ..core.objhooks import GONE
from ..core.writes import UG_RESTORED, obj_track  # 2.985.0 (#5394): UG_RESTORED
from ..core.db import bump, iso_ms, now_utc
from ..core.i18n import tr  # 2.985.0 (#5394)
from ..core.pg import system_ctx  # 2.985.0 (#5394)
from .model import EV_CALS_MAX, EV_KIND, KERN, cal_touch, ev_delete, ev_tell, need_evcal, need_event  # 2.985.0 (#5394): EV_CALS_MAX, EV_KIND, KERN, ev_tell

EVU_KIND = "event"
EVU_KEEP = {"events": {"uid", "href", "seq", "imp_at", "imp_rev", "created_by"}}


def evu_label(r):
    return UG_LABEL, [ua_plain(r.get("title"), r.get("id"))]


obj_track(EVU_KIND, "events", area="calendar", undo_keep=EVU_KEEP, undo_nofp={"events": {"seq", "imp_at", "imp_rev"}},
          undo_label=evu_label, undo_free=("deleted_at",))

GONE[EVU_KIND] = "events"  # review F4: an account's deletion takes its history / undo rows of the objects that went (core/objhooks.py)

def _restore(uid):
    def run(c, r):
        c.execute("UPDATE events SET deleted_at=NULL, updated_at=?, updated_by=? WHERE id=?", (iso_ms(now_utc()), uid, r["id"]))
        cal_touch(c, r["cal_id"])
        bump(c)
    return run


def evu_need(c, uid, rid, oid):
    """Who may take an event's step back now: write on the event (in the trash or not) and on the calendar it goes back to."""
    r = c.execute("SELECT * FROM events WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    need_event(c, rid, write=True, uid=uid, deleted=bool(r["deleted_at"]))
    trash = ua_trash_fix("events", rid, r["deleted_at"], _restore(uid), lambda c, x: ev_delete(c, x, uid))
    old_cal = r["cal_id"]

    def fix(c):
        n = c.execute("SELECT cal_id FROM events WHERE id=?", (int(rid),)).fetchone()
        if n["cal_id"] != old_cal:
            nk, _ = need_evcal(c, n["cal_id"], write=True, uid=uid)  # back into a calendar the person may still write
            if nk["org_id"]:  # review F7: its invited people of the server fit that calendar's organisation (as op_event_edit)
                for (au,) in c.execute("SELECT user_id FROM event_attendees WHERE event_id=? AND user_id IS NOT NULL ORDER BY user_id",
                                       (int(rid),)).fetchall():
                    p = ws_fit_problem(c, nk["org_id"], au, "cal")
                    if p:
                        raise Denied(409, p)
            cal_touch(c, old_cal)
        trash(c)
        cal_touch(c, n["cal_id"])  # the devices' sync (CalDAV ctag)
    return {"fix": fix, "lock": f"event-{int(rid)}"}  # events/model.py ev_lock


undo_need_reg(EVU_KIND, evu_need)


def cal_restore_do(c, uid, cid, step=False, undo=False):
    """2.985.0 (#5394): the restore of events/web.py op_cal_restore without its commit (also the undo of a calendar's trash step)."""
    cal, _ = need_evcal(c, cid, manage=True, trash=True, uid=uid)
    with system_ctx(c):
        n = c.execute(f"SELECT COUNT(*) FROM ev_cals WHERE owner_id=(SELECT owner_id FROM ev_cals WHERE id=?) AND {live_sql()}", (cid,)).fetchone()[0]
    if n >= EV_CALS_MAX:
        raise Denied(409, tr("At most {0} calendars", EV_CALS_MAX))
    if step:
        undo_label(c, UG_RESTORED, ua_plain(cal["name"], cid))
    KERN["restore"](c, uid, EV_KIND, cid, step=step, undo=undo)  # 2.947.0 (#5367): the core's way, its events (children) with it
    cal_touch(c, cid)


def evu_cal_back(c, uid, cid):
    """2.985.0 (#5394): a calendar's trash step taken back = its restore (cal_restore_do, no step of its own)."""
    cal_restore_do(c, uid, cid, undo=True)
    bump(c)


def evu_cal_away(c, uid, cid):
    """A calendar's restore step taken back / its trash step forward again = into the trash with its events (no mails)."""
    need_evcal(c, cid, manage=True, uid=uid)
    for r in c.execute(f"SELECT * FROM events WHERE cal_id=? AND {live_sql()}", (int(cid),)).fetchall():
        ev_tell(c, r, "cancelled")  # 2.367.2 (#2969): the people of the server learn it; review F3: no mails made, none counted
    KERN["trash"](c, uid, EV_KIND, cid, step=False)  # 2.947.0 (#5367): the core's trash with its events (children)
    cal_touch(c, cid)
    bump(c)


undo_trash_reg(EV_KIND, evu_cal_back, evu_cal_away)
