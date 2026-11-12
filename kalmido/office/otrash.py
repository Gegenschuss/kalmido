"""2.272.0 E2 (#3038): the office trash -- the list and the routes of the office area's trash.

2.1005.0 (#5415, stage 4d part E): every kind of the office deletes into the ONE trash of the core (office/okern.py
ofk_register): GET /api/office/trash lists its rows of the kinds shown there (okern.ofk_trash_items), POST
/api/office/trash/core/<kind>/<id>/restore and DELETE /api/office/trash/core/<kind>/<id> restore / delete them for good. The
copies of office_trash (otb_put: a raw copy of the row before it went) were written back into their tables as rows of the
core's trash (okern.ofk_copies_back, at the start); the routes of the copies of those kinds went. One kind still deletes
its row with a copy here (no deleted_at, a later stage): the start balance of the cash flow (office/cfstart.py, a table
keyed by the organisation); a sign-off record whose film / document is gone is on the core's trash since 2.1004.0 (#5494,
office/signoff.py sig_gone_delete). Only these copies are listed, restored (POST .../<id>/restore, the toast's undo POST .../undo/<kind>/<id>) and deleted for good
(DELETE .../<id>); files/trashpurge.py tp_tick calls otb_tick after the trash period. The table stays for one more version."""
import json

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import IntegrityError, insert_id, qi, table_columns, table_names, write_lock
from ..core.i18n import tr
from ..core.db import bump, iso_ms, now_utc
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
from ..core.writes import _unval, _val  # 2.1005.0 (#5415): the bytes of a copy, as the core's undo copies
from ..core.serializers import unlink_files  # 2.993.0 (#5413)

OTB_KINDS = ("cf_start",)  # 2.1005.0 (#5415): the kind still deleted with a copy here (module docstring; signoff on the core since #5494)


def otb_put(c, oid, uid, kind, table, rid, label, key="id"):
    """Stores the copy of row rid of table (call it BEFORE the DELETE, in the same transaction). -> the trash id. key = the
    column naming the row (office_cf_start: org_id). 2.1005.0 (#5415): only the row itself (the kind of OTB_KINDS has no
    rows that go with it)."""
    if kind not in OTB_KINDS:
        raise ValueError(f"otb_put: {kind} is on the core's trash (office/okern.py)")
    cols = table_columns(c, table)
    rows = c.execute(f"SELECT * FROM {qi(table, table_names(c))} WHERE {qi(key, cols)}=?", (rid,)).fetchall()
    snap = {"rows": [[table, [{k: _val(r[k]) for k in r.keys()} for r in rows]]] if rows else [], "nulls": [], "key": key}
    tid = insert_id(c, "INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
                     (oid, kind, "", rid, (label or "")[:300], json.dumps(snap, default=str), uid, iso_ms(now_utc())))
    if has_request_context():
        g.otb_id = tid  # the route's answer names it (trash_id: the app's Undo)
    return tid


OTB_UNDO = {}  # 2.567.0 (#4707): kind -> the context of its module () -> (c, uid, oid): the rights of deleting it, for the
# toast's undo (otb_undo_route); set by the module of the kind (cfstart)


def otb_restore(c, oid, tid):
    """Writes trash copy tid of office area oid back (the caller checked the rights and commits). -> (kind, ref_id)"""
    r = c.execute("SELECT * FROM office_trash WHERE id=? AND org_id=? AND kind = ANY(CAST(? AS TEXT[])) FOR UPDATE", (tid, oid, list(OTB_KINDS))).fetchone()
    if not r:
        raise Denied(404)
    snap = json.loads(r["snap"] or "{}")
    key = snap.get("key") or "id"  # 2.567.0 (#4707): a table without an id
    names = table_names(c)
    for table, rows in (snap.get("rows") or [])[:1]:
        cols = table_columns(c, table)
        for raw in rows:
            row = {k: _unval(v) for k, v in raw.items() if k in cols}
            if c.execute(f"SELECT 1 FROM {qi(table, names)} WHERE {qi(key, cols)}=?", (row[key],)).fetchone():
                raise Denied(409, tr("Already restored") if key == "id" else tr("Set again meanwhile: the earlier value was not restored."))
            try:  # 2.272.0 F (#3038, review E2-M2): something else it needs is gone for good since: 409, not 500
                with c.savepoint():
                    c.execute(f"INSERT INTO {qi(table, names)}({','.join(qi(k, cols) for k in row)}) VALUES({','.join('?' * len(row))})",
                              list(row.values()))
            except IntegrityError:
                raise Denied(409, tr("This cannot be restored: something it refers to (a client, a service) is gone meanwhile.")) from None
    c.execute("DELETE FROM office_trash WHERE id=?", (tid,))
    return r["kind"], r["ref_id"]


def otb_tick(c, cut, purge):
    """Copies in the trash since before cut (the caller runs it in the system context): counted, deleted while purge is on.
    2.1005.0 (#5415): also a copy okern.ofk_copies_back left (its row is there again): never listed, it goes after its period."""
    if purge:
        return c.execute("DELETE FROM office_trash WHERE deleted_at<?", (cut,)).rowcount
    return c.execute("SELECT COUNT(*) FROM office_trash WHERE deleted_at<?", (cut,)).fetchone()[0]


def _ctx_admin():
    c, uid, oid = office_ctx()
    if office_role(c, uid, oid) != "admin" and not ofr_admin_or(c, uid, oid, "offers", "manage"):
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    return c, uid, oid


def _need_admin(c, uid, oid):
    """The copies (a start balance) only for the office admin, as deleting it."""
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this workspace can do this"))


@app.get("/api/office/trash")
def otb_list():
    """The trash of the office area (admins / people who may manage documents): newest first."""
    c, uid, oid = _ctx_admin()
    # 2.905.0 (#5414): the rows of the kinds on the core's trash (office/okern.py view=), marked core = their kind; per kind
    # (ofk_view_may, 2.1005.0): the admin, a document draft also who may manage documents. The copies (OTB_KINDS) for the admin.
    rows = c.execute("SELECT id, kind, sub, ref_id, label, deleted_by, deleted_at FROM office_trash WHERE org_id=? AND kind = ANY(CAST(? AS TEXT[])) "
                     "ORDER BY deleted_at DESC, id DESC LIMIT 500", (oid, list(OTB_KINDS))).fetchall() if office_role(c, uid, oid) == "admin" else []
    items = [dict(r) for r in rows] + ofk_trash_items(c, oid, uid)
    items.sort(key=lambda x: (str(x["deleted_at"] or ""), x["id"]), reverse=True)
    return jsonify(items=items[:500], days=max(1, ret_days("trash")))


@app.post("/api/office/trash/<int:tid>/restore")
def otb_restore_route(tid):
    """A copy (OTB_KINDS) back; any other id 404 (2.1005.0, #5415: the other kinds restore through .../core/<kind>/<id>)."""
    c, uid, oid = _ctx_admin()
    write_lock(c, f"office_trash_{int(tid)}")
    _need_admin(c, uid, oid)
    kind, ref = otb_restore(c, oid, tid)
    ofx_log(c, oid, "restore", target=kind, detail={"id": ref})
    bump(c)
    c.commit()
    return jsonify(ok=True, kind=kind, id=ref)


@app.delete("/api/office/trash/<int:tid>")
def otb_delete_route(tid):
    """Deletes one copy for good (the app asks first)."""
    c, uid, oid = _ctx_admin()
    _need_admin(c, uid, oid)
    n = c.execute("DELETE FROM office_trash WHERE id=? AND org_id=? AND kind = ANY(CAST(? AS TEXT[]))", (tid, oid, list(OTB_KINDS))).rowcount
    if not n:
        raise Denied(404)
    bump(c)
    c.commit()
    return jsonify(ok=True)


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


@app.post("/api/office/trash/undo/<kind>/<int:tid>")
def otb_undo_route(kind, tid):
    """2.567.0 (#4707): the toast's undo of a delete in an office module (2.1005.0, #5415: the start balance of the cash flow;
    the other kinds take a delete back through the core): the module's own rights (OTB_UNDO), then the person who deleted it
    or an office admin; writes the trash copy back as the restore of the trash does. -> {ok, kind, id, ids}"""
    if kind not in OTB_UNDO:
        raise Denied(404)
    c, uid, oid = OTB_UNDO[kind]()
    write_lock(c, f"office_trash_{int(tid)}")
    t = c.execute("SELECT kind, deleted_by FROM office_trash WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if not t or t["kind"] != kind:
        raise Denied(404)
    if t["deleted_by"] != uid and office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    kind, ref = otb_restore(c, oid, tid)
    ofx_log(c, oid, "restore", target=kind, detail={"id": ref})
    bump(c)
    c.commit()
    return jsonify(ok=True, kind=kind, id=ref, ids=[ref])
