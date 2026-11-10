"""2.809.0 (#5476): undo across devices -- the household budget's entries in the core's step groups (core/undoareas.py).

A budget entry (table budget_entries) is the tracked kind "budget_entry" (obj_track): a change (PATCH
/api/budget/entries/<id>), putting it into the trash (DELETE) and taking it out (POST .../restore) record a snap step of the
person under the entry's lock (budget_entries-<id>, budget.py _ccf_lock), labelled with its title (a value sealed at rest:
its number). The copy holds the encrypted columns with their space (sid), so they go back together; a key rotation since
rewrote the row (changed since: 409). Its link to a recurring entry (recurring_id, rmonth, trash_rec_id) is never written
back from the copy -- a month booked again meanwhile would collide; coming out of / going into the trash links / unlinks it
the area's way (entry_restore / entry_delete). Taking back with the rules of today (core/undoweb.py): the budget module on,
the right to change the budget list (bud_need_list), never an agent.

Interface:
  bdu_pre(c, uid, eid, what=None)   after the route's checks are possible: rights, lock, the step ("delete" | "restore")
  bdu_post(c) -> group id | None    right before the commit"""
from ..core.access import live_sql
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_done, ua_plain, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .budget import _booked, _ccf_lock, bud_need_list, bud_need_on

BDU_KIND = "budget_entry"
BDU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def bdu_label(r):
    return UG_LABEL, [ua_plain(r.get("title"), r.get("id"))]


obj_track(BDU_KIND, "budget_entries", area="budget",
          undo_keep={"budget_entries": {"list_id", "created_at", "created_by", "recurring_id", "rmonth", "trash_rec_id",
                                         "trash_cat_id", "source", "import_run", "ikey", "rkeys"}},
          undo_nofp={"budget_entries": {"recurring_id", "rmonth", "trash_rec_id"}}, undo_label=bdu_label,
          undo_free=("deleted_at", "deleted_by"))
GONE[BDU_KIND] = "budget_entries"


def bdu_pre(c, uid, eid, what=None):
    """The step before the route's write; nothing when the entry is not there (the route answers 404 then)."""
    try:
        eid = int(eid)
    except (TypeError, ValueError):
        return
    r = c.execute("SELECT list_id, title FROM budget_entries WHERE id=?", (eid,)).fetchone()
    if r is None:
        return
    bud_need_on(c, uid)
    bud_need_list(c, uid, r["list_id"], True)
    _ccf_lock(c, "budget_entries", eid)  # first the area's lock, then the row's (obj_undo_pre), as its writes
    key = BDU_WHAT.get(what or "")
    ua_pre(c, uid, BDU_KIND, eid, *((key, ua_plain(r["title"], eid)) if key else ()))


def bdu_post(c):
    return ua_done(c)


def bdu_need(c, uid, rid, oid):
    bud_need_on(c, uid)
    was = c.execute("SELECT * FROM budget_entries WHERE id=?", (int(rid),)).fetchone()
    if was is None:
        raise Denied(404)
    bud_need_list(c, uid, was["list_id"], True)

    def fix(c):
        now = c.execute("SELECT * FROM budget_entries WHERE id=?", (int(rid),)).fetchone()
        if bool(now["deleted_at"]) == bool(was["deleted_at"]):
            return
        if now["deleted_at"]:  # into the trash again: its booked month is free (entry_delete)
            c.execute("UPDATE budget_entries SET trash_rec_id=COALESCE(recurring_id, trash_rec_id), recurring_id=NULL WHERE id=?", (int(rid),))
            return
        rec = now["trash_rec_id"]  # out of the trash: the link back while its month is free (entry_restore)
        if rec and c.execute(f"SELECT 1 FROM budget_recurring WHERE id=? AND {live_sql()}", (rec,)).fetchone():
            if now["rmonth"] and not _booked(c, rec, now["rmonth"]):
                c.execute("UPDATE budget_entries SET recurring_id=?, trash_rec_id=NULL WHERE id=?", (rec, int(rid)))
            else:
                c.execute("UPDATE budget_entries SET trash_rec_id=NULL, rmonth='' WHERE id=?", (int(rid),))
    return {"fix": fix, "lock": f"budget_entries-{int(rid)}"}


undo_need_reg(BDU_KIND, bdu_need)
