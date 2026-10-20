"""2.89.0 (#1916): the routes of the tables area (/api/sheets) for the web app. People only (session.py refuses agents on
these routes; agents use the REST API of part C). Reading needs the sheet visible (sheets/core.py sh_need), every change the
right to write it and the module "sheets" switched on (409 like the other modules; reading stays)."""
from flask import jsonify, request

from ..core.config import app
from ..core.access import Denied, need_feat
from ..core.db import body, db, iso_ms, now_utc
from ..core.i18n import tr
from ..accounts.session import me
from ..personal.timetrack import BadInput
from .core import (SH_ROWS_MAX, ShBook, sh_add_col, sh_add_rows, sh_brief, sh_check_list, sh_clean_col, sh_clean_title,
                   sh_col_dict, sh_create, sh_dict, sh_freeze, sh_index, sh_list_bound, sh_may_rebind, sh_need, sh_need_cell, sh_options, sh_presence_set, sh_reload,
                   sh_set_cells, sh_set_name, sh_touch, sh_undo_batch, sh_vars)


def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _need_w(c, sid, deleted=False):
    need_feat("sheets")
    r = sh_need(c, sid, write=True, deleted=deleted)
    if deleted:  # 2.124.0 C (#2113): a table in the trash: never through a share
        from .shshare import shs_need_own
        shs_need_own(c, r, 404)
    return r


def _done(c, sid, extra=None):
    c.commit()
    r = sh_reload(c, sid)
    out = {"ok": True, "rev": r["rev"]}
    out.update(extra or {})
    return jsonify(out)


@app.get("/api/sheets")
def sheets_index():
    """?space=private|org:<id>|all (default all) or ?list_id=<id> -- the sheets one may read, without their cells."""
    c = db()
    uid = me()
    lid = request.args.get("list_id")
    if lid is not None:
        try:
            lid = int(lid)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "list_id")) from None
    rows = sh_index(c, uid, request.args.get("space"), lid)
    return jsonify(sheets=sh_brief(c, rows, uid))


@app.post("/api/sheets")
def sheets_create():
    """{title, space, list_id?} -> the new sheet (3 text columns, 10 rows)."""
    need_feat("sheets")
    c = db()
    uid = me()
    b = body()
    sid = sh_create(c, uid, b.get("space"), b.get("title"), b.get("list_id"))
    c.commit()
    return jsonify(sh_dict(c, sh_reload(c, sid))), 201


@app.get("/api/sheets/<int:sid>")
def sheets_get(sid):
    c = db()
    r = sh_need(c, sid)
    d = sh_dict(c, r)
    from .shmove import shm_last  # 2.96.0 B (#1941): the last move between workspaces (both sides see it)
    d["moved"] = shm_last(c, sid)
    from .shshare import shs_flags  # 2.124.0 C (#2113): shared_in, can_share, shared
    from .shbook import shb_rights_row
    d.update(shs_flags(c, shb_rights_row(c, r) or r, me()))  # 2.124.0 E (#2116): the shares of the whole table
    c.commit()  # sheet_lastvals of the viewer
    return jsonify(d)


@app.patch("/api/sheets/<int:sid>")
def sheets_patch(sid):
    """{title?, list_id? (null = detach)}"""
    c = db()
    r = _need_w(c, sid)
    uid = me()
    b = body()
    f = {}
    if "title" in b:
        f["title"] = sh_clean_title(b["title"]) or r["title"]
    if "list_id" in b and b["list_id"] != r["list_id"]:
        from .shshare import shs_need_own
        shs_need_own(c, r)  # 2.124.0 C (#2113): never through a share
        if not sh_may_rebind(c, uid, r):
            raise Denied(403)  # detaching opens the table to the whole space: its creator or the list's owner / admins only
        f["list_id"] = sh_check_list(c, r["org_id"], b["list_id"], uid)
    from .shbook import shb_patch, shb_sync
    f = shb_patch(c, r, f)  # 2.124.0 E (#2116): the list on the first sheet only; a further sheet's title = its name in the bar
    if f:
        c.execute(f"UPDATE sheets SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), sid])
        if "list_id" in f:
            shb_sync(c, sid)  # 2.124.0 E (#2116): every sheet of the table hangs on the same list
        sh_touch(c, sid, uid)
    c.commit()
    return jsonify(sh_dict(c, sh_reload(c, sid)))


@app.delete("/api/sheets/<int:sid>")
def sheets_delete(sid):
    """To the trash (Undo: POST /api/sheets/<id>/restore)."""
    c = db()
    from .shshare import shs_need_own
    shs_need_own(c, _need_w(c, sid))  # 2.124.0 C (#2113): never through a share
    c.execute("UPDATE sheets SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), sid))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/restore")
def sheets_restore(sid):
    c = db()
    r = _need_w(c, sid, deleted=True)
    if r["book_id"]:  # 2.124.0 (#2116, review): a further sheet comes back through its sheet route (name and count checks)
        from .shbook import sheets_tabs_restore
        return sheets_tabs_restore(r["book_id"], sid)
    c.execute("UPDATE sheets SET deleted_at=NULL WHERE id=?", (sid,))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.put("/api/sheets/<int:sid>/cells")
def sheets_cells(sid):
    """{cells: [{row_id, col_id, raw}]} -> {cells: the changed cells + the cells depending on them, rev}"""
    c = db()
    r = _need_w(c, sid)
    cells = body().get("cells")
    out = sh_set_cells(c, r, cells, me())
    c.commit()
    return jsonify(cells=out, rev=sh_reload(c, sid)["rev"])


@app.post("/api/sheets/<int:sid>/cells/<int:cid>/freeze")
def sheets_freeze(sid, cid):
    """{frozen: true|false} -- keep the current value (a copy) instead of the formula, or calculate again."""
    c = db()
    r = _need_w(c, sid)
    x = sh_need_cell(c, r, cid)
    fr = body().get("frozen")
    if not isinstance(fr, bool):
        raise BadInput(tr("Invalid value: {0}", "frozen"))
    sh_freeze(c, r, x, fr, me())
    return _cell_answer(c, sid, cid)


@app.post("/api/sheets/<int:sid>/cells/<int:cid>/name")
def sheets_name(sid, cid):
    """{name} -- the cell's name in formulas ("" = none); 400 when invalid or taken."""
    c = db()
    r = _need_w(c, sid)
    x = sh_need_cell(c, r, cid)
    sh_set_name(c, r, x, body().get("name"), me())
    return _cell_answer(c, sid, cid)


def _cell_answer(c, sid, cid):
    from .core import sh_cell_dicts, sh_eval
    c.commit()
    r = sh_reload(c, sid)
    book = ShBook(c, r)
    res = sh_eval(c, r, book)
    cells = sh_cell_dicts(c, r, book, res)  # every cell: names and frozen values change the display of others
    c.commit()
    return jsonify(cell=next((d for d in cells if d["id"] == cid), None), cells=cells, rev=r["rev"])


@app.post("/api/sheets/<int:sid>/columns")
def sheets_col_add(sid):
    """{title, kind, options?, color_mode?, width?, after_col_id?} -> {column, rev}"""
    c = db()
    r = _need_w(c, sid)
    b = body()
    after = b.get("after_col_id")
    col_id = sh_add_col(c, r, b, me(), after_col_id=_int(after, "after_col_id") if after is not None else None)
    sh_touch(c, sid, me())
    c.commit()
    book = ShBook(c, sh_reload(c, sid))
    i = book.col_idx.get(col_id)
    return jsonify(column=sh_col_dict(book.col_by[col_id], i), rev=book.sheet["rev"]), 201


def _need_col(c, sid, col_id, deleted=False):
    x = c.execute("SELECT * FROM sheet_columns WHERE id=? AND sheet_id=?", (col_id, sid)).fetchone()
    if not x or bool(x["deleted_at"]) != deleted:
        raise Denied(404)
    return x


@app.patch("/api/sheets/<int:sid>/columns/<int:col_id>")
def sheets_col_patch(sid, col_id):
    """{title?, kind?, options?, color_mode?, width?, pos?} -- a select column takes typed labels over as its options' ids."""
    from .core import _select_raw
    c = db()
    r = _need_w(c, sid)
    old = _need_col(c, sid, col_id)
    b = body()
    f = sh_clean_col(b, partial=True)
    if "pos" in b:
        p = b["pos"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not -1e9 < p < 1e9:
            raise BadInput(tr("Invalid value: {0}", "pos"))
        f["pos"] = float(p)
    if f:
        c.execute(f"UPDATE sheet_columns SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), col_id])
        if f.get("kind") == "select":  # typed texts of the column become options (their ids are stored)
            book = ShBook(c, sh_reload(c, sid))
            col = book.col_by[col_id]
            for x in [x for x in book.cells.values() if x["col_id"] == col_id and x["raw"] and not x["raw"].startswith("=")]:
                nr = _select_raw(c, book, col, x["raw"].strip())
                if nr != x["raw"]:
                    c.execute("UPDATE sheet_cells SET raw=? WHERE id=?", (nr, x["id"]))
        elif old["kind"] == "select" and f.get("kind") not in (None, "select"):  # the option ids become their labels again
            labels = {o.get("id"): o.get("label", "") for o in sh_options(old["options"])}
            for x in c.execute("SELECT id, raw FROM sheet_cells WHERE col_id=?", (col_id,)).fetchall():
                if x["raw"] in labels:
                    c.execute("UPDATE sheet_cells SET raw=? WHERE id=?", (labels[x["raw"]], x["id"]))
        sh_touch(c, sid, me())
    c.commit()
    book = ShBook(c, sh_reload(c, sid))
    return jsonify(column=sh_col_dict(book.col_by[col_id], book.col_idx[col_id]), rev=book.sheet["rev"])


@app.delete("/api/sheets/<int:sid>/columns/<int:col_id>")
def sheets_col_delete(sid, col_id):
    """To the trash (formulas pointing at it show "ref"; Undo: .../restore)."""
    c = db()
    _need_w(c, sid)
    _need_col(c, sid, col_id)
    c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), col_id))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/columns/<int:col_id>/restore")
def sheets_col_restore(sid, col_id):
    c = db()
    _need_w(c, sid)
    _need_col(c, sid, col_id, deleted=True)
    c.execute("UPDATE sheet_columns SET deleted_at=NULL WHERE id=?", (col_id,))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/rows")
def sheets_rows_add(sid):
    """{after_row_id?, count? (default 1)} -> {ids, rev}"""
    c = db()
    r = _need_w(c, sid)
    b = body()
    n = b.get("count", 1)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= SH_ROWS_MAX:
        raise BadInput(tr("Invalid value: {0}", "count"))
    after = b.get("after_row_id")
    ids = sh_add_rows(c, r, n, me(), after_row_id=_int(after, "after_row_id") if after is not None else None)
    sh_touch(c, sid, me())
    return _done(c, sid, {"ids": ids})


def _need_row(c, sid, rid, deleted=False):
    x = c.execute("SELECT * FROM sheet_rows WHERE id=? AND sheet_id=?", (rid, sid)).fetchone()
    if not x or bool(x["deleted_at"]) != deleted:
        raise Denied(404)
    return x


@app.delete("/api/sheets/<int:sid>/rows/<int:rid>")
def sheets_row_delete(sid, rid):
    c = db()
    _need_w(c, sid)
    _need_row(c, sid, rid)
    c.execute("UPDATE sheet_rows SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), rid))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/rows/<int:rid>/restore")
def sheets_row_restore(sid, rid):
    c = db()
    _need_w(c, sid)
    _need_row(c, sid, rid, deleted=True)
    c.execute("UPDATE sheet_rows SET deleted_at=NULL WHERE id=?", (rid,))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/rows/order")
def sheets_rows_order(sid):
    """{ids: [row ids in the new order]} -- sorting for good (rows not named keep their order behind)."""
    c = db()
    _need_w(c, sid)
    ids = body().get("ids")
    live = [x[0] for x in c.execute("SELECT id FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (sid,))]
    lset = set(live)
    if not isinstance(ids, list) or len(ids) > len(live) or any(isinstance(x, bool) or x not in lset for x in ids) or len(set(ids)) != len(ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    given = set(ids)
    order = ids + [x for x in live if x not in given]
    for i, rid in enumerate(order):
        c.execute("UPDATE sheet_rows SET pos=? WHERE id=?", (float(i + 1), rid))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/presence")
def sheets_presence(sid):
    """{cell_id | null} -- "I am in this cell" for a few seconds (GET answers it as presence to the others)."""
    c = db()
    r = sh_need(c, sid)
    cid = body().get("cell_id")
    if cid is not None:
        cid = _int(cid, "cell_id")
    return jsonify(sh_presence_set(c, r, me(), cid))


@app.get("/api/sheets/<int:sid>/vars")
def sheets_vars(sid):
    """?q= -- the completion after "=": names, columns, projects / lists / clients one may use here, functions."""
    c = db()
    r = sh_need(c, sid)
    out = sh_vars(c, r, me(), request.args.get("q") or "")
    c.commit()
    return jsonify(vars=out)


@app.post("/api/sheets/<int:sid>/batches/<batch>/undo")
def sheets_batch_undo(sid, batch):
    """Takes back one agent call's changes (a person who may write the sheet)."""
    c = db()
    r = _need_w(c, sid)
    if not c.execute("SELECT 1 FROM sheet_changes WHERE sheet_id=? AND batch=? LIMIT 1", (sid, batch[:80])).fetchone():
        raise Denied(404)
    n = sh_undo_batch(c, r, batch[:80], me())
    return _done(c, sid, {"undone": n})
