"""2.809.0 (#5476) / 2.985.0 (#5394): undo across devices -- budget entries in the core's step groups (core/undoareas.py).

A budget entry (table budget_entries) is the tracked kind "budget_entry" (core/writes.py obj_track): a change (PATCH
/api/budget/entries/<id>), putting it into the trash and taking it out record a snap step of the person under the entry's
lock (budget_entries-<id>, life/budget.py _ccf_lock), labelled with its title when it is plain, else with its day (a sealed
title never goes into a label). The copy holds the row AS STORED: the amount, title, note and counterpart sealed with the key
of the list's space (sid, core/orgcrypt.py), nothing decrypted.

The lock per list space (decision of 08.11.2026): a copy is only written back with the key it was sealed with. undo_spaces
(core/writes.py _undo_rekeyed) refuses a step (409, "the key of its space was changed") when
  - the copy's space (sid) is no longer the one of the entry's list now (the list moved into another space, the encryption
    was switched on or off: the rows were resealed meanwhile), or
  - the key of that space was rotated after the step or a rotation runs now (an organisation's key, admin/orgcrypt_cli.py);
    an account's own key is never rotated.
That is checked before the fingerprint, so the answer names the key change.

Taking back (core/undoweb.py): the person needs the right to change the list NOW (bud_need_list write; agents and tokens
without "private" never see a budget). The template link (recurring_id / trash_rec_id), the month it books (rmonth), its
source and import marks stay as they are (undo_keep): coming out of the trash runs the entry's own restore (entry_restore:
the template month again unless it was booked since), going into it the entry's own delete (entry_delete); a day moved back
into another month of a booked template keeps the link only while that month is free (409 otherwise, as the PATCH).
The receipts (budget_files) are not part of the copy."""
from ..core import orgcrypt as oc
from ..core.access import live_sql
from ..core.db import IntegrityError
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_done, ua_plain, ua_pre, ua_trash_fix
from ..core.undogroups import UG_LABEL
from ..core.undoweb import UG_GONE, undo_need_reg
from ..core.objhooks import GONE
from ..core.pg import qi  # 2.1013.0 (#5513)
from ..core.writes import UNDO_SPACE_REKEYED, obj_track, obj_undo_forget
from .budget import _booked, _ccf_lock, bud_need_list, bud_need_on, bud_sid, entry_delete, entry_restore
from .budget import cat_delete, cat_restore, rec_delete, rec_restore  # 2.1013.0 (#5513)

BDU_KIND = "budget_entry"
BDU_ENTRY = N_("Budget entry of {0}")
BDU_REKEYED = UNDO_SPACE_REKEYED  # the same answer as a rotation of that space's key (core/writes.py)
BDU_BOOKED = N_("This item is already booked in this month")  # the key exists (life/budget.py)
BDU_SEALED = N_("The list was encrypted since then, so it cannot be undone")  # 2.985.0 (#5394, review F7): a plain copy
BDU_KEEP = {"budget_entries": {"list_id", "recurring_id", "trash_rec_id", "rmonth", "source", "import_run", "rkeys", "ikey",
                               "created_by", "created_at", "trash_cat_id"}}  # 2.809.0 (#5476): created_at, trash_cat_id
BDU_NOFP = {"budget_entries": {"recurring_id", "rmonth", "trash_rec_id"}}  # 2.809.0 (#5476): the link is not "changed since"
BDU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def bdu_name(r):
    """A label value: the plain title, else [the entry of its day] (a sealed title never)."""
    r = dict(r) if r is not None else {}
    t = ua_plain(r.get("title"), r.get("id"))
    return [BDU_ENTRY, str(r.get("day") or "")] if t.startswith("#") else t


def bdu_label(r):
    return UG_LABEL, [bdu_name(r)]


def bdu_spaces(c, snap):
    """The spaces whose keys sealed the copy (core/writes.py undo_spaces); 409 when one is not its list's space now. Checked
    before anything is written back, so also: the copy's category must still exist (deleted for good since = 409, never a
    broken reference)."""
    out = []
    for r in (snap or {}).get("budget_entries") or []:
        sid = int(r.get("sid") or 0)
        now = bud_sid(c, r["list_id"])
        if sid != now:  # review F7: a plain copy of a list that is sealed now says so
            raise Denied(409, tr(BDU_SEALED if not sid and now else BDU_REKEYED))
        # review F7: a category in the trash counts as gone too (never written back onto a deleted one)
        if r.get("cat_id") and not c.execute(f"SELECT 1 FROM budget_cats WHERE id=? AND {live_sql()}", (int(r["cat_id"]),)).fetchone():
            raise Denied(409, tr(UG_GONE))
        if sid:
            out.append(sid)
    return out


obj_track(BDU_KIND, "budget_entries", area="budget", undo_keep=BDU_KEEP, undo_nofp=BDU_NOFP, undo_label=bdu_label,
          undo_free=("deleted_at", "deleted_by"), undo_spaces=bdu_spaces, hist_skip=oc.FIELDS["budget_entries"] + ("dkey", "sid"))
GONE[BDU_KIND] = "budget_entries"  # an account's deletion takes its history / undo rows of the entries that went (core/objhooks.py)


def bdu_pre(c, uid, eid, what=None):
    """The person's step before the route's write of entry eid; what = delete | restore names it so. 2.809.0 (#5476) calls it
    from the routes (life/budget_web.py): the rights and the entry's lock first, as its writes; nothing when the entry is not
    there (the route answers 404 then)."""
    try:
        eid = int(eid)
    except (TypeError, ValueError):
        return
    r = c.execute("SELECT id, list_id, title, day, sid FROM budget_entries WHERE id=?", (eid,)).fetchone()
    if r is None:
        return
    from flask import g, has_request_context
    if has_request_context():  # 2.985.0 (#5394, review F2): the space that sealed the copy (bdu_post compares)
        g.bdu_sid = (eid, int(r["sid"] or 0))
    bud_need_on(c, uid)
    bud_need_list(c, uid, r["list_id"], True)
    _ccf_lock(c, "budget_entries", eid)  # first the area's lock, then the row's (obj_undo_pre), as its writes
    key = BDU_WHAT.get(what or "")
    if key:
        ua_pre(c, uid, BDU_KIND, eid, key, bdu_name(r))
    else:
        ua_pre(c, uid, BDU_KIND, eid)


def bdu_post(c):
    """-> the request's group id when the step stayed (ua_done: a save of the same values leaves none), else None.
    2.985.0 (#5394, review F2): the write sealed the entry with another space's key than the copy (the encryption switched on or
    the list moved before bud_settle reached the row): the step goes, and with it every older copy and the history of the
    entry (obj_undo_forget) - bud_settle finds nothing left to reseal, so a plain copy would otherwise stay up to 30 days."""
    from flask import g, has_request_context
    was = g.pop("bdu_sid", None) if has_request_context() else None
    if was:
        now = c.execute("SELECT sid FROM budget_entries WHERE id=?", (was[0],)).fetchone()
        if now is not None and int(now["sid"] or 0) != was[1]:
            ua_done(c, drop=True)
            obj_undo_forget(c, BDU_KIND, [was[0]])
            return None
    return ua_done(c)


def bdu_need(c, uid, rid, oid):
    """Who may take an entry's step back now (module docstring)."""
    r = c.execute("SELECT * FROM budget_entries WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    bud_need_on(c, uid)
    bud_need_list(c, uid, r["list_id"], True)
    trash = ua_trash_fix("budget_entries", rid, r["deleted_at"], lambda c, x: entry_restore(c, uid, x["id"]),
                         lambda c, x: entry_delete(c, uid, x["id"]), cols=("deleted_at", "deleted_by"))

    def fix(c):
        trash(c)
        n = c.execute("SELECT id, day, recurring_id, rmonth, deleted_at FROM budget_entries WHERE id=?", (int(rid),)).fetchone()
        if n["recurring_id"] and not n["deleted_at"] and n["rmonth"] != str(n["day"])[:7]:
            if _booked(c, n["recurring_id"], str(n["day"])[:7], but=n["id"]):
                raise Denied(409, tr(BDU_BOOKED))
            try:  # review F8: a parallel booking of that month between the check and the write (unique index), as entry_update
                with c.savepoint():
                    c.execute("UPDATE budget_entries SET rmonth=? WHERE id=?", (str(n["day"])[:7], n["id"]))
            except IntegrityError:
                raise Denied(409, tr(BDU_BOOKED)) from None
    return {"fix": fix, "lock": f"budget_entries-{int(rid)}"}  # life/budget.py _ccf_lock


undo_need_reg(BDU_KIND, bdu_need)


# ---------------------------------------------------------------- 2.1013.0 (#5513): categories and templates
# The rest of #5394 (decision of 08.11.2026): a category (budget_cats, kind "budget_cat") and a template (budget_recurring, kind
# "budget_rec") record a snap step of the person like an entry -- a change (PATCH), into the trash (DELETE) and out of it
# (POST .../restore) -- under the row's lock (<table>-<id>, life/budget.py _ccf_lock), with the same lock per list space: the
# copy holds the sealed columns as stored (a category's limit, a template's title and amount) and goes back only under the
# key that sealed it (_bdx_spaces). Coming out of the trash / going into it again runs the area's own way (cat_restore /
# cat_delete hang the entries and templates back on the category or take them off; rec_restore / rec_delete do the booked
# entries' link). A category's label is its name (plain); a template's its title when plain, else "Budget template".
# A category's order (a PATCH with sort only, the drag of the list) is no step: it would bury the real ones.
BCU_KIND, BRU_KIND = "budget_cat", "budget_rec"
BCU_LABEL = N_("Budget category {0}")
BRU_LABEL = N_("Budget template")
BXU_TABLE = {BCU_KIND: "budget_cats", BRU_KIND: "budget_recurring"}
BXU_TABLES = tuple(BXU_TABLE.values())  # the names of qi()
BXU_KEEP = {"budget_cats": {"list_id", "created_at", "sort"},
            "budget_recurring": {"list_id", "contract_task_id", "created_by", "created_at", "trash_cat_id"}}
BXU_META = ("expect_updated_at", "_prev")


def _bxu_name(kind, r):
    r = dict(r) if r is not None else {}
    if kind == BCU_KIND:
        return [BCU_LABEL, ua_plain(r.get("name"), r.get("id"))]
    t = ua_plain(r.get("title"), r.get("id"))
    return [BRU_LABEL] if t.startswith("#") else t


def _bxu_spaces(table):
    def spaces(c, snap):
        """As bdu_spaces: the copy's space must be its list's space now (a category without a limit seals nothing: its space
        does not count); its category (a template's) must still be there."""
        out = []
        for r in (snap or {}).get(table) or []:
            sid = int(r.get("sid") or 0)
            sealed = any(r.get(k) not in (None, "") for k in oc.FIELDS[table])
            now = bud_sid(c, r["list_id"])
            if sealed and sid != now:
                raise Denied(409, tr(BDU_SEALED if not sid and now else BDU_REKEYED))
            if r.get("cat_id") and not c.execute(f"SELECT 1 FROM budget_cats WHERE id=? AND {live_sql()}", (int(r["cat_id"]),)).fetchone():
                raise Denied(409, tr(UG_GONE))
            if sealed and sid:
                out.append(sid)
        return out
    return spaces


for _k, _t in BXU_TABLE.items():
    obj_track(_k, _t, area="budget", undo_keep={_t: BXU_KEEP[_t]}, undo_nofp={_t: {"sort"} if _t == "budget_cats" else set()},
              undo_label=(lambda r, _k=_k: (UG_LABEL, [_bxu_name(_k, r)])), undo_free=("deleted_at", "deleted_by"),
              undo_spaces=_bxu_spaces(_t), hist_skip=oc.FIELDS[_t] + ("sid",))
    GONE[_k] = _t


def bxu_pre(c, uid, kind, rid, what=None, b=None):
    """The person's step before the route's write of a category / template rid (what = delete | restore names it so; b = the
    PATCH body: a category's order alone is no step). The rights and the row's lock first, as its writes; nothing when the row
    is not there (the route answers 404 then)."""
    table = BXU_TABLE[kind]
    if b is not None and (not isinstance(b, dict) or not [k for k in b if k not in BXU_META and k != "sort"]):
        return
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return
    r = c.execute(f"SELECT * FROM {qi(table, BXU_TABLES)} WHERE id=?", (rid,)).fetchone()
    if r is None:
        return
    from flask import g, has_request_context
    if has_request_context():  # as bdu_pre (review F2 of #5394): the space that sealed the copy (bxu_post compares)
        g.bxu_sid = (table, rid, int(r["sid"] or 0), kind)
    bud_need_on(c, uid)
    bud_need_list(c, uid, r["list_id"], True)
    _ccf_lock(c, table, rid)
    key = BDU_WHAT.get(what or "")
    if key:
        ua_pre(c, uid, kind, rid, key, _bxu_name(kind, r))
    else:
        ua_pre(c, uid, kind, rid)


def bxu_post(c):
    """-> the request's group id when the step stayed, else None; as bdu_post: a write that sealed the row with another space's
    key than the copy drops the step and every older copy of the row."""
    from flask import g, has_request_context
    was = g.pop("bxu_sid", None) if has_request_context() else None
    if was:
        now = c.execute(f"SELECT sid FROM {qi(was[0], BXU_TABLES)} WHERE id=?", (was[1],)).fetchone()
        if now is not None and int(now["sid"] or 0) != was[2]:
            ua_done(c, drop=True)
            obj_undo_forget(c, was[3], [was[1]])
            return None
    return ua_done(c)


def _bxu_need(kind):
    table = BXU_TABLE[kind]

    def need(c, uid, rid, oid):
        """Who may take a category's / template's step back now: the right to change its list NOW."""
        r = c.execute(f"SELECT * FROM {qi(table, BXU_TABLES)} WHERE id=?", (int(rid),)).fetchone()
        if r is None:
            raise Denied(404)
        bud_need_on(c, uid)
        bud_need_list(c, uid, r["list_id"], True)
        on, off = (cat_restore, cat_delete) if kind == BCU_KIND else (rec_restore, rec_delete)
        trash = ua_trash_fix(table, rid, r["deleted_at"], lambda c, x: on(c, uid, x["id"]), lambda c, x: off(c, uid, x["id"]),
                             cols=("deleted_at", "deleted_by"))
        return {"fix": trash, "lock": f"{table}-{int(rid)}"}  # life/budget.py _ccf_lock
    return need


for _k in BXU_TABLE:
    undo_need_reg(_k, _bxu_need(_k))
