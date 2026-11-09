"""2.777.0 (#5254): undo across devices, stage 6 -- what the areas outside the office share to record their steps in the
core's step groups (core/undogroups.py) and to take them back (core/undoweb.py): calendar events (events/evundo.py),
contacts (contacts/ctundo.py), the file store's metadata and content versions (files/fsundo.py), the small areas.

Every area does the same three things the office does (office/owrite.py, office/undogrp.py):
- its rows are a tracked kind (core/writes.py obj_track) with an undo_label naming the object and undo_free = its trash
  columns, so a step "into the trash" / "out of the trash" goes back too;
- its write routes call ua_pre before they change the row (after the area's own lock: ev_lock, write_lock) and ua_post
  right before their commit -- a snap step of the person, an agent records nothing (obj_undo_pre);
- it registers who may take a step back NOW (core/undoweb.py undo_need_reg): the area's own write check of today, and a
  fix that does what the area's own trash / restore does besides the flag (ua_trash_fix) and re-checks a target (another
  calendar, book, folder) the copy would put the row back into.

A label never carries a sealed value (kenc / e2e cipher): the object's number then.

Interface:
  ua_plain(v, rid) -> text for a label          the value (at most 80 characters) or "#<id>"
  ua_pre(c, uid, kind, rid, key=None, *args)    the step before the write (key: the label of the group, else undo_label)
  ua_post(c)                                    right before the commit (the state after the step)
  ua_trash_fix(table, rid, was, on_restore, on_trash) -> fix(c)   the area's own trash / restore after the flag went back"""
from .i18n import N_
from .pg import qi, table_columns
from .undogroups import undo_label
from .writes import obj_undo_post, obj_undo_pre

UA_MOVED = N_("Moved: {0}")
UA_RESTORED = N_("Restored: {0}")
UA_DELETED = N_("Deleted: {0}")  # the key exists (core/i18n)
UA_RENAMED = N_("Renamed: {0}")  # the key exists
UA_VERSION = N_("New version: {0}")
UA_TABLES = ("events", "contacts", "fs_nodes")  # the tables of ua_trash_fix (names only through qi)
UA_SEALED = ("kenc", "e2e")  # core/orgcrypt.py PREFIX kenc1:, collab/liste2e.py e2e1: never in a label (stored in plain text)


def ua_plain(v, rid=None):
    v = v if isinstance(v, str) else ("" if v is None else str(v))
    v = " ".join(v.split())
    if not v or v.startswith(UA_SEALED):
        return f"#{int(rid)}" if rid is not None else "#"
    return v[:80]


def ua_pre(c, uid, kind, rid, key=None, *args, oid=None):
    """The undo step of uid's write of (kind, rid) -- before the write, in its transaction (core/writes.py obj_undo_pre)."""
    if key:
        undo_label(c, key, *args)
    obj_undo_pre(c, uid, kind, rid, oid)


def ua_post(c):
    obj_undo_post(c)


def ua_trash_fix(table, rid, was, on_restore=None, on_trash=None, cols=("deleted_at",)):
    """The fix (core/undoweb.py) of a tracked kind with undo_free = its trash columns: the copy put the flag back as it was
    (was = the row's deleted_at before the undo / redo). Coming out of the trash: the flag is set again and the area's own
    restore on_restore(c, row) does it all (its checks may refuse: the part stays); going into the trash: the flag is cleared
    again and on_trash(c, row) puts it there the area's way. Without a change of the flag nothing runs."""
    def fix(c):
        cols_now = table_columns(c, table)
        r = c.execute(f"SELECT * FROM {qi(table, UA_TABLES)} WHERE id=?", (int(rid),)).fetchone()
        if r is None or bool(r["deleted_at"]) == bool(was):
            return
        if was and on_restore:
            c.execute(f"UPDATE {qi(table, UA_TABLES)} SET deleted_at=? WHERE id=?", (was, int(rid)))
            on_restore(c, c.execute(f"SELECT * FROM {qi(table, UA_TABLES)} WHERE id=?", (int(rid),)).fetchone())
        elif not was and on_trash:
            c.execute(f"UPDATE {qi(table, UA_TABLES)} SET {', '.join(qi(k, cols_now) + '=NULL' for k in cols)} WHERE id=?", (int(rid),))
            on_trash(c, c.execute(f"SELECT * FROM {qi(table, UA_TABLES)} WHERE id=?", (int(rid),)).fetchone())
    return fix
