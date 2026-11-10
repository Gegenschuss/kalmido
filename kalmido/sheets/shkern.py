"""2.809.0 (#5365, stage 3 of the core's trash): tables on the ONE trash of the core (core/writes.py obj_trash / obj_restore /
obj_purge / obj_trash_prune, docs/dev/kern.md). A sheet row (a table's first sheet or a further sheet of it, book_id) is
registered as a core object without routes, folder node or listing (the pattern of the office's kinds): the tables' routes
(sheets/web.py, sheets/shbook.py) check their rights as before and then put the sheet into the core's trash (shk_trash:
deleted_at / deleted_by), take it back (shk_restore) and delete it for good (shk_purge: "Delete permanently", "Empty trash";
the core's hourly retention run obj_trash_tick after the trash period, trash_prune=True). The area's own purge (shx_purge)
and the tables' line of the file store's run (files/trashpurge.py TP_PLAIN "sheets") are gone; what only the tables know --
the stored files of the file cells of the sheet and of its further sheets with their scan / text rows, the table's folder node
(reference kind 'sheet') and the history of its own fields (obj_history kind 'sheet') -- is the hook of obj_on_purge
(_shk_purge). Its further sheets, columns, rows and cells go with the row (ON DELETE CASCADE).
Deleted rows / columns of a live table are no objects: they keep the file store's run (TP_PLAIN sheet_rows / sheet_columns).
The core's role of a sheet (the second floor under the route's own check): 'manage' for who may write the table (sheets/core.py
sh_may of its first sheet), nothing for anyone else. Its space hook names no organisation: sh_may checks the organisation, the
project, an agent's data lock itself. The kind's name differs from the reference kind and the history's kind ("sheet")."""
from ..core.i18n import N_
from ..core.objects import obj_register
from ..core.writes import obj_on_purge, obj_purge, obj_restore, obj_trash
from .core import sh_may

SHK_KIND = "sheet_table"


def _row(c, rid):
    return c.execute("SELECT * FROM sheets WHERE id=?", (int(rid),)).fetchone()


def _base(c, uid, rid):
    r = _row(c, rid)
    if r is not None and r["book_id"]:
        r = _row(c, r["book_id"])  # a further sheet: the table's rights hang on its first sheet
    return "manage" if r is not None and sh_may(c, uid, r, write=True) else None


def _visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
    u = int(uid)
    return (f"(SELECT id FROM sheets WHERE (org_id IS NULL AND owner_id = {u}) "
            f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")


def _space(c, rid):
    return (None, None) if _row(c, rid) is not None else None


def _shk_purge(c, rid):
    """The tables' part of the delete for good of sheet rid (core/writes.py obj_on_purge; was shx_purge / the file store's run):
    the stored files of its file cells and of its further sheets with their scan / text rows, its folder node, the history
    of its own fields and of its further sheets. -> the stored paths (unlinked after the commit)."""
    if _row(c, rid) is None:
        return None
    sids = [int(rid)] + [x[0] for x in c.execute("SELECT id FROM sheets WHERE book_id=?", (int(rid),))]
    fr = c.execute("SELECT id, path FROM sheet_files WHERE sheet_id = ANY(CAST(? AS BIGINT[]))", (sids,)).fetchall()
    for i in range(0, len(fr), 500):
        fids = [x["id"] for x in fr[i:i + 500]]
        c.execute("DELETE FROM upload_scan WHERE kind='sheet' AND ref_id = ANY(CAST(? AS BIGINT[]))", (fids,))
        c.execute("DELETE FROM file_text WHERE kind='sheet' AND ref_id = ANY(CAST(? AS BIGINT[]))", (fids,))
    c.execute("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id=?", (int(rid),))
    c.execute("DELETE FROM obj_history WHERE kind='sheet' AND ref_id = ANY(CAST(? AS BIGINT[]))", (sids,))  # 2.571.0 (#4766), no FK
    return [x["path"] for x in fr]


obj_register(SHK_KIND, "sheets", label=N_("Table"), fields={}, area="sheets", routes=False, listed=False, fsref=False,
             space=_space, base_role=_base, visible=_visible, cap=lambda c, uid, rid: None, list_col="list_id", trash_prune=True)
obj_on_purge(SHK_KIND, _shk_purge)


def shk_trash(c, uid, sid):
    """Into the core's trash (the route checked the rights). No step of the core's list: the tables' own Undo brings it back."""
    return obj_trash(c, uid, SHK_KIND, sid, step=False)


def shk_restore(c, uid, sid):
    """Out of the core's trash (the route checked the rights and the name of a further sheet)."""
    return obj_restore(c, uid, SHK_KIND, sid, step=False)


def shk_purge(c, uid, sid):
    """For good (only from the trash; the route checked the rights and runs it inside core/writes.py obj_purge_after)."""
    return obj_purge(c, uid, SHK_KIND, sid)
