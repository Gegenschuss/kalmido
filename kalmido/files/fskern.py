"""2.809.0 (#5365, stage 3 of the core's trash): the file store's nodes on the ONE trash of the core (core/writes.py obj_trash /
obj_restore / obj_purge / obj_trash_prune, docs/dev/kern.md). A node is registered as a core object without routes, folder
node or listing (the pattern of the office's kinds): the file store's routes (files/web.py, files/bulk.py) check their rights,
locks and protected nodes as before and then put the node into the core's trash (fsk_trash: deleted_at / deleted_by; what
lies below it carries no mark of its own and goes with it), take it back (fsk_restore) and delete it for good (fsk_purge:
"Delete permanently", "Empty trash"; the core's hourly retention run obj_trash_tick after the trash period, trash_prune=True).
The area's own run (files/trashpurge.py tp_files) is gone; what only the file store knows -- the documents locked in one
order, the hooks of fs_on_delete, the stored versions -- is the hook of obj_on_purge (_fsk_purge, store.fs_purge_prep).
GoBD / legal retention (#2168): a hook of fs_on_delete that refuses (Denied: a booked receipt) keeps the node: the person's
purge is refused as before, the retention run counts it as locked (obj_trash_tick: fs_entry_locked) and it stays in the trash.
The core's role of a node (the second floor under the route's own check, store.fs_role): 'manage' for its owner (the branch's
owner, an organisation's admin) and for who edits it; in the trash only for the owner and for who put it there with edit
rights (the file store's rule of restoring), nothing for anyone else. Its space hook names no organisation: fs_role checks the
organisation boundary, shares and agents itself.
The kind's name differs from the one of the file store's undo steps ("fs_node", files/fsundo.py): those stay the area's."""
from functools import partial

from ..core.access import live_sql
from ..core.i18n import N_
from ..core.objects import obj_register
from ..core.writes import obj_on_purge, obj_purge, obj_restore, obj_trash
from .store import fs_chain, fs_purge_files, fs_purge_lock, fs_purge_prep, fs_role, fs_subtree, fs_trash_root

FSK_KIND = "fs_entry"


def _row(c, rid):
    return c.execute("SELECT * FROM fs_nodes WHERE id=?", (int(rid),)).fetchone()


def _base(c, uid, rid):
    r = _row(c, rid)
    if r is None:
        return None
    role = fs_role(c, int(rid), uid)
    if r["deleted_at"]:
        return "manage" if role == "owner" or (role == "edit" and r["deleted_by"] == uid) else None
    return "manage" if role in ("owner", "edit") else None


def _visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
    u = int(uid)
    return (f"(SELECT id FROM fs_nodes WHERE owner_id = {u} OR deleted_by = {u} "
            f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")


def _space(c, rid):
    return (None, None) if _row(c, rid) is not None else None


def _fsk_purge(c, rid):
    """The file store's part of the delete for good of node rid and its subtree (core/writes.py obj_on_purge; was fs_purge in
    tp_files): Denied of a hook keeps it (legal retention). -> the removal of the stored files after the commit."""
    if _row(c, rid) is None:
        return None  # went with a folder above it
    ids, paths = fs_purge_prep(c, rid)
    return [partial(fs_purge_files, ids, paths)]


obj_register(FSK_KIND, "fs_nodes", label=N_("File"), fields={}, area="other", routes=False, listed=False, fsref=False,
             space=_space, base_role=_base, visible=_visible, cap=lambda c, uid, rid: None, trash_prune=True)
obj_on_purge(FSK_KIND, _fsk_purge, lock=lambda c, rid: fs_purge_lock(c, fs_subtree(c, rid)))  # 2.1047.0 (#5835)


def fsk_trash(c, uid, nid):
    """Into the core's trash (the route checked the rights, the locks and moved the protected nodes up). No step of the core's
    list: the file store records its own (files/fsundo.py)."""
    return obj_trash(c, uid, FSK_KIND, nid, step=False)


def fsk_restore(c, uid, nid):
    """Out of the core's trash (the route freed the name first)."""
    return obj_restore(c, uid, FSK_KIND, nid, step=False)


def fsk_purge(c, uid, nid):
    """For good (the route checked that uid owns it and runs it inside core/writes.py obj_purge_after). A node inside a folder in
    the trash carries no mark of its own: it gets the folder's first, so the core's purge (only from the trash) takes it alone."""
    r = _row(c, nid)
    if r is not None and not r["deleted_at"]:
        fs_purge_lock(c, fs_subtree(c, nid))  # 2.1047.0 (#5835): its documents before the node row's first write
        top = fs_trash_root(fs_chain(c, nid))
        if top is not None:
            c.execute(f"UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=? AND {live_sql()}",
                      (top["deleted_at"], top["deleted_by"], int(nid)))
    return obj_purge(c, uid, FSK_KIND, nid)
