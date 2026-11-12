"""2.272.0 E2 (#3038): the office trash -- the list and the routes of the office area's trash.

2.1005.0 (#5415, stage 4d part E): every kind of the office deletes into the ONE trash of the core (office/okern.py
ofk_register): GET /api/office/trash lists its rows of the kinds shown there (okern.ofk_trash_items), POST
/api/office/trash/core/<kind>/<id>/restore and DELETE /api/office/trash/core/<kind>/<id> restore / delete them for good.
2.1050.0 (#5789, stage 4e): the last kind of copies (the start balance of the cash flow, office/cfstart.py) is on the core's
trash too; the copies of office_trash (otb_put before 2.1050), their routes (POST /api/office/trash/<id>/restore, DELETE
/api/office/trash/<id>, the toast's undo POST /api/office/trash/undo/<kind>/<id>) and their purge run (otb_tick) are gone --
okern.ofk_copies_back writes old copies back at the start. The table office_trash stays for one more version (an older
version still reads it)."""
from flask import jsonify, request

from ..core.config import app
from ..core.pg import write_lock
from ..core.i18n import tr
from ..core.access import Denied
from ..core.retention import ret_days
from .ledger import ofx_log
from .model import office_ctx, office_role
from .rights import ofr_admin_or, ofr_group_restored
from .okern import OFK, ofk_restore, ofk_trash_items  # 2.905.0 (#5414): the kinds that moved onto the core's trash
from .okern import ofk_view_may  # 2.1005.0 (#5415)
from .okern import ofk_office_of  # 2.1004.0 (#5494)
from ..core.objects import obj_row
from ..core.writes import obj_purge, obj_purge_after  # 2.993.0 (#5413): + obj_purge_after
from ..core.serializers import unlink_files  # 2.993.0 (#5413)


def _ctx_admin():
    c, uid, oid = office_ctx()
    if office_role(c, uid, oid) != "admin" and not ofr_admin_or(c, uid, oid, "offers", "manage"):
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    return c, uid, oid


@app.get("/api/office/trash")
def otb_list():
    """The trash of the office area (admins / people who may manage documents): newest first."""
    c, uid, oid = _ctx_admin()
    # 2.905.0 (#5414): the rows of the kinds on the core's trash (office/okern.py view=), marked core = their kind; per kind
    # (ofk_view_may, 2.1005.0): the admin, a document draft also who may manage documents. 2.1050.0 (#5789): no copies any more.
    items = ofk_trash_items(c, oid, uid)
    items.sort(key=lambda x: (str(x["deleted_at"] or ""), x["id"]), reverse=True)
    return jsonify(items=items[:500], days=max(1, ret_days("trash")))


def _core_kind(c, uid, oid, kind, rid):
    """2.905.0 (#5414): (OFK entry, row) of a row of office area oid in the core's trash of a kind the office trash shows; 404
    otherwise (another organisation, live, unknown kind)."""
    k = OFK.get(kind)
    if not k or not k.get("view"):
        raise Denied(404)
    row = obj_row(c, kind, rid)
    if row is None or ofk_office_of(c, kind, row) != oid or not row["deleted_at"]:  # 2.1004.0 (#5494): + a personal kind's row
        raise Denied(404)
    return k, dict(row)


@app.post("/api/office/trash/core/<kind>/<int:rid>/restore")
def otb_core_restore(kind, rid):
    """2.905.0 (#5414): a row of the office trash that lies in the core's trash (master data, rights groups, sign-offs, fixed
    costs, corrections, a letter's links) comes back. The trash's restore: the office admin, as with the copies (_need_kind).
    ?undo=1 = the toast's undo: the module's own rights (view ctx), then the person who deleted it (the core's own step,
    obj_restore undo=True) or an office admin."""
    k = OFK.get(kind) or {}
    undo = request.args.get("undo") == "1" and (k.get("view") or {}).get("ctx")
    c, uid, oid = k["view"]["ctx"]() if undo else _ctx_admin()
    write_lock(c, f"office_trash_core_{kind}_{int(rid)}")
    k, row = _core_kind(c, uid, oid, kind, rid)
    for name in k["view"]["lock"](oid, row) if k["view"].get("lock") else ():  # 2.1005.0 (#5415, fable): the area's own locks of
        write_lock(c, name)  # the kind, as its own routes take them (a draft's number, a part's quotation, a statement's positions)
    own = undo and row.get("deleted_by") == uid
    if not own and not ofk_view_may(c, uid, oid, kind):  # 2.1005.0 (#5415): the admin, or who the kind's view names (a draft)
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    ofk_restore(c, uid, kind, rid, undo=own)
    extra = k["view"]["back"](c, oid, row) if k["view"].get("back") else None  # 2.1005.0 (#5415): back may add to the answer
    if kind == "orgroup":  # 2.997.0 (#5708): since 2.905.0 a rights group comes back here, not via otb_restore_route's "rgroup" branch -- the rights log names the restore again (#5302 F5)
        ofr_group_restored(c, oid, uid, int(rid))
    ui = k["view"]["kind"](row) if callable(k["view"]["kind"]) else k["view"]["kind"]
    if ui == "doc":  # 2.1005.0 (#5415): the office log names a document's restore by its doc_id, as with the copies
        ofx_log(c, oid, "restore", doc_id=rid, detail={"id": rid})
    else:
        ofx_log(c, oid, "restore", target=ui, detail={"id": rid})
    c.commit()
    return jsonify(ok=True, kind=ui, id=rid, ids=[rid], **(extra or {}))


@app.delete("/api/office/trash/core/<kind>/<int:rid>")
def otb_core_delete(kind, rid):
    """2.905.0 (#5414): deletes such a row for good (the app asks first): the core's purge (core/writes.py obj_purge)."""
    c, uid, oid = _ctx_admin()
    _core_kind(c, uid, oid, kind, rid)
    if not ofk_view_may(c, uid, oid, kind):  # 2.1005.0 (#5415): the admin, or who the kind's view names (a draft)
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    with obj_purge_after() as box:  # 2.993.0 (#5413): the kind's stored files (obj_on_purge) after the commit; a receipt kept by law = 409
        obj_purge(c, uid, kind, rid)
    c.commit()
    unlink_files(box["after"])
    return jsonify(ok=True)
