"""2.777.0 (#5254): undo across devices, stage 6 -- the file store's metadata and content in the core's step groups.

A node (table fs_nodes) is the tracked kind "fs_node" (core/writes.py obj_track, core/undoareas.py): renaming, moving
(PATCH /api/files/nodes/<id>), putting it into the trash and taking it out, a new version and restoring an older version
record a snap step of the person. The content is never copied: the copy of the row holds the version it pointed at
(cur_version, size, mime), so taking a new version back points the file at its older version again -- the versions
themselves stay (fs_versions); a version the clean-up removed since cannot come back (409). FSU_VERSION_HOOKS: fn(c, uid,
nid) runs when an undo changed the version a node points at (an area keeping things derived from the content).

Taking back (core/undoweb.py) asks what the forward way asks NOW: write on the node (need_node, in the trash too), not an
area's root folder, not in a locked folder (its names are ciphers, 409), no receipt of a locked month below it; a node going
back into another folder: write on that folder, a folder (not in the trash, not below itself, not too deep), the area's fit
and edit on the documents filed below (fs_ref_need_move); a name taken meanwhile gets " (2)" (_free_name). Coming out of /
going into the trash runs the file store's own restore / trash (its owner or who deleted it; protected nodes move up, the
areas' on_trash). The owner, workspace, kind, links and the organisation access of a node never change on undo (undo_keep)."""
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.undoareas import UA_DELETED, UA_MOVED, UA_RENAMED, UA_RESTORED, UA_VERSION, ua_plain, ua_post, ua_pre, ua_trash_fix
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from ..office.periodlock import pl_tree_need_open
from .fslock import fsl_move_guard, fsl_of
from .fsref import fs_ref_need_move, fs_ref_trashed, fs_trash_prepare, fs_trash_restored
from .fsroots import fs_area_after, fs_area_before, fs_area_need_fit, fs_area_root_need_free
from .store import DEPTH_MAX, _free_name, _now, fs_chain, fs_deleted, fs_height, fs_log_add, need_node

FSU_KIND = "fs_node"
FSU_KEEP = {"fs_nodes": {"kind", "agent_id", "ref_kind", "ref_id", "org_access", "created_by"}}
FSU_LOCKED = N_("It lies in a locked folder, so it cannot be undone here")
FSU_NO_VERSION = N_("That version of the file is no longer there, so it cannot be undone")
FSU_VERSION_HOOKS = []


def fsu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(FSU_KIND, "fs_nodes", area="other", undo_keep=FSU_KEEP, undo_label=fsu_label, undo_free=("deleted_at", "deleted_by"))


FSU_WHAT = {"rename": UA_RENAMED, "move": UA_MOVED, "delete": UA_DELETED, "restore": UA_RESTORED, "version": UA_VERSION}


def fsu_pre(c, uid, n, what=None):
    """The step of uid's change of node n (a row), labelled FSU_WHAT[what] + its name (in a locked folder: its number only).
    files/web.py calls it (and fsu_post before its commit) through a function-local import: core/objects.py imports web.py."""
    key = FSU_WHAT.get(what or "")
    nm = f"#{int(n['id'])}" if fsl_of(c, n["id"]) is not None else ua_plain(n["name"], n["id"])
    ua_pre(c, uid, FSU_KIND, n["id"], *((key, nm) if key else ()))


def _target(c, uid, n, m):
    """Node n (as before the undo, with its role) goes back into folder m["parent_id"] (the checks of web.py _move)."""
    tid = m["parent_id"]
    if tid:
        need_node(c, tid)  # a folder the person does not see: 404 before its lock is checked (as _move)
    fsl_move_guard(c, n, tid)  # review F1: across a locked folder's border only re-encrypted (409, as _move)
    fs_area_need_fit(c, tid, m["kind"], m["ref_kind"], node=m)
    fs_ref_need_move(c, uid, n)
    if tid:
        t = need_node(c, tid, write=True)
        if t["kind"] != "folder":
            raise Denied(409, tr("Not a folder"))
        up = fs_chain(c, tid)
        if fs_deleted(up):
            raise Denied(400, tr("The target folder is in the trash"))
        if n["id"] in [r["id"] for r in up]:
            raise Denied(409, tr("A folder cannot be moved into itself"))
        if len(up) + 1 + fs_height(c, n["id"]) > DEPTH_MAX:
            raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
        if (t["org_id"] or None) != (n["org_id"] or None) or t["owner_id"] != n["owner_id"]:
            # review F2: the folder went into another workspace / tree since (files/fsmove.py) -- as _move (2.48.0, #1207)
            raise Denied(409, tr("Files can only be moved within the same workspace"))
    elif n["owner_id"] != uid and not (n["org_id"] and n["role"] == "owner"):
        raise Denied(403)


def fsu_need(c, uid, rid, oid):
    """Who may take a node's step back now (module docstring)."""
    n = need_node(c, rid, write=True, trash=True)
    if fsl_of(c, rid) is not None:
        raise Denied(409, tr(FSU_LOCKED))
    fs_area_root_need_free(c, rid)
    pl_tree_need_open(c, rid)  # a receipt of a locked month stays where and as it is
    ctx = fs_area_before(c, uid, n)
    was, was_by = c.execute("SELECT deleted_at, deleted_by FROM fs_nodes WHERE id=?", (int(rid),)).fetchone()

    def back(c, x):
        if n["role"] != "owner" and was_by != uid:  # as the restore route: its owner or who put it there
            raise Denied(403)
        fs_ref_need_move(c, uid, x, restore=True)
        c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL WHERE id=?", (int(rid),))
        fs_log_add(c, rid, "restore")
        fs_trash_restored(c, uid, x)

    def away(c, x):
        if x["parent_id"] is None and n["role"] != "owner":
            raise Denied(403)
        _kept, refs = fs_trash_prepare(c, uid, x)
        c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (_now(), uid, int(rid)))
        fs_log_add(c, rid, "trash")
        for r in refs:
            fs_ref_trashed(c, uid, r, False)
    trash = ua_trash_fix("fs_nodes", rid, was, back, away, cols=("deleted_at", "deleted_by"))

    def fix(c):
        m = c.execute("SELECT * FROM fs_nodes WHERE id=?", (int(rid),)).fetchone()
        if m["parent_id"] != n["parent_id"]:
            _target(c, uid, n, m)
        if m["parent_id"] != n["parent_id"] or m["name"] != n["name"]:
            nm = _free_name(c, m["parent_id"], m["owner_id"], m["org_id"], m["name"], skip=int(rid))
            if nm != m["name"]:
                c.execute("UPDATE fs_nodes SET name=? WHERE id=?", (nm, int(rid)))
        if m["cur_version"] != n["cur_version"]:
            if m["kind"] == "file" and not c.execute("SELECT 1 FROM fs_versions WHERE node_id=? AND no=?", (int(rid), m["cur_version"])).fetchone():
                raise Denied(409, tr(FSU_NO_VERSION))
            for fn in FSU_VERSION_HOOKS:
                fn(c, uid, int(rid))
        trash(c)
        fs_area_after(c, uid, rid, ctx)
    return {"fix": fix}


def fsu_post(c):
    ua_post(c)


undo_need_reg(FSU_KIND, fsu_need)
