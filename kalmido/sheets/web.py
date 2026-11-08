"""2.89.0 (#1916): the routes of the tables area (/api/sheets) for the web app. People only (session.py refuses agents on
these routes; agents use the REST API of part C). Reading needs the sheet visible (sheets/core.py sh_need), every change the
right to write it and the module "sheets" switched on (409 like the other modules; reading stays)."""
import json

from flask import jsonify, request

from ..core.config import app
from ..core.access import Denied, need_feat
from ..core.db import body, db, iso_ms, now_utc
from ..core.i18n import tr
from ..accounts.session import me
from ..core.errors import BadInput
from ..core.pg import write_lock
from .core import (SH_ROWS_MAX, ShBook, sh_add_col, sh_add_rows, sh_brief, sh_check_list, sh_clean_col, sh_clean_title,
                   sh_col_dict, sh_create, sh_dict, sh_freeze, sh_index, sh_list_bound, sh_may_rebind, sh_need, sh_need_cell, sh_option_ops, sh_options, sh_presence_set, sh_reload, sh_rev_conflict,
                   sh_set_cells, sh_set_name, sh_touch, sh_undo_batch, sh_vars)
from .core import sh_cell_dicts, sh_eval, _select_raw  # 2.369.5 (#2517): pulled up from functions
from ..collab.comments import user_names  # 2.528.0 (#4305 A12)
from ..core.i18n import N_  # 2.528.0 (#4306 B22): the trash of tables
from ..core.db import bump
from ..core.retention import ret_on, ret_trash_days
from ..core.serializers import unlink_files
from ..accounts.orgs import is_org_admin
from .core import sh_list_title, sh_may, sh_space, sh_space_key, sh_to_display
from .shorder import sho_apply, sho_moved, sho_plan, sho_restore_apply, sho_restore_plan, sho_sort_plan  # 2.631.0 (#4620), 2.658.0 (#5000)
from .shhist import shh_meta_write  # 2.564.0 (#4701/#4702); 2.571.0 (#4766): shh_meta_write


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
    """{title, space, list_id?, folder_id?} -> the new sheet (3 text columns, 10 rows); folder_id: filed there at once."""
    need_feat("sheets")
    c = db()
    uid = me()
    b = body()
    sid = sh_create(c, uid, b.get("space"), b.get("title"), b.get("list_id"))
    if b.get("folder_id") is not None:  # 2.199.0 C (#2742): a new table in the chosen folder (its workspace only)
        from ..files.fsref import fs_ref_place
        fs_ref_place(c, uid, "sheet", sid, _int(b.get("folder_id"), "folder_id"))
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
    """{title?, list_id? (null = detach), expect_updated_at? (the updated_at read: changed since -> 409 with "current")}.
    2.571.0 (#4766): through the core's write layer (sheets/shhist.py shh_meta_write: lock, version, obj_history, bump)."""
    c = db()
    _need_w(c, sid)
    uid = me()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))

    def clean(c, b, cur):
        r = _need_w(c, sid)  # again under the table's lock
        f = {}
        if "title" in b:
            f["title"] = sh_clean_title(b["title"]) or r["title"]
        if "list_id" in b and b["list_id"] != r["list_id"]:
            from .shshare import shs_need_own
            shs_need_own(c, r)  # 2.124.0 C (#2113): never through a share
            if not sh_may_rebind(c, uid, r):
                raise Denied(403)  # detaching opens the table to the whole space: its creator or the list's owner / admins only
            f["list_id"] = sh_check_list(c, r["org_id"], b["list_id"], uid)
        from .shbook import shb_patch
        return shb_patch(c, r, f)  # 2.124.0 E (#2116): the list on the first sheet only; a further sheet's title = its name in the bar

    shh_meta_write(c, uid, _need_w(c, sid), b, clean, lambda c, cur: sh_dict(c, sh_reload(c, sid)))
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
    from .shshare import shs_core_move
    shs_core_move(c, sid)  # 2.565.0 (#4717): its old share rows not moved yet get their core shares
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.put("/api/sheets/<int:sid>/cells")
def sheets_cells(sid):
    """{cells: [{row_id, col_id, raw, prev?}], expect_rev?} -> {cells: the changed cells + the cells depending on them, rev,
    conflicts}. 2.270.0 B (#3021): prev = the input seen before; a cell changed since stays and comes back in conflicts."""
    c = db()
    r = _need_w(c, sid)
    b = body()
    cur = sh_rev_conflict(c, r, b)
    if cur:
        return jsonify(cur), 409
    cf = []
    out = sh_set_cells(c, r, b.get("cells"), me(), conflicts=cf)
    c.commit()
    return jsonify(cells=out, rev=sh_reload(c, sid)["rev"], conflicts=cf)


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


SHX_COL_PREV = ("title", "kind", "color_mode", "width", "pos")


def shx_col_prev(old, b):
    """2.528.0 (#4305 A12): b without the fields whose stored value differs from b["_prev"][field] (changed elsewhere since the
    writer read the column) unless it already is the new value, like the lists' _prev (lists.py lp_prev_conflicts) -> (b,
    conflicts [{field, server, mine}]). Without _prev: b unchanged (older clients, agents)."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "body"))
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    b, out = {k: v for k, v in b.items() if k != "_prev"}, []
    if not prev:
        return b, out
    for k, was in prev.items():
        if k not in SHX_COL_PREV or k not in b:
            continue
        cur = old[k]
        same = (lambda x, y: (x is None and y is None) or (x is not None and y is not None and str(x) == str(y))) if k != "pos" else (
            lambda x, y: isinstance(y, (int, float)) and not isinstance(y, bool) and float(x) == float(y))
        if not same(cur, was) and not same(cur, b[k]):
            out.append({"field": k, "server": cur, "mine": b[k]})
            del b[k]
    return b, out


def shx_order_moved(live, prev):
    """2.528.0 (#4305 A12): True when the rows the writer saw (prev, in order) are no longer in that order or one of them is gone;
    rows added since do not count. prev None = no check (older clients); BadInput for a malformed prev."""
    if prev is None:
        return False
    if not isinstance(prev, list) or len(prev) > SH_ROWS_MAX or any(isinstance(x, bool) or not isinstance(x, int) for x in prev):
        raise BadInput(tr("Invalid value: {0}", "prev"))
    seen = set(prev)
    return [x for x in live if x in seen] != prev


@app.patch("/api/sheets/<int:sid>/columns/<int:col_id>")
def sheets_col_patch(sid, col_id):
    """{title?, kind?, options?, options_ops?, color_mode?, width?, pos?} -- a select column takes typed labels over as its options'
    ids. 2.270.0 B (#3021): options_ops = single add / rename / remove (sh_option_ops) -> also {added: ids, conflicts}."""
    c = db()
    r = _need_w(c, sid)
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
    old = _need_col(c, sid, col_id)
    b, cf = shx_col_prev(old, body())  # 2.528.0 (#4305 A12): a field changed elsewhere since the writer read it stays (conflicts)
    f = sh_clean_col(b, partial=True)
    added = []
    if b.get("options_ops") is not None:  # 2.270.0 B (#3021): single option changes on the current list, one writer per sheet
        cur = c.execute("SELECT options FROM sheet_columns WHERE id=?", (col_id,)).fetchone()["options"]
        opts, added, ocf = sh_option_ops(sh_options(cur), b["options_ops"])
        cf += ocf
        if json.dumps(opts, ensure_ascii=False) != cur:
            f["options"] = json.dumps(opts, ensure_ascii=False)
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
    return jsonify(column=sh_col_dict(book.col_by[col_id], book.col_idx[col_id]), rev=book.sheet["rev"], added=added, conflicts=cf)


@app.delete("/api/sheets/<int:sid>/columns/<int:col_id>")
def sheets_col_delete(sid, col_id):
    """To the trash (formulas pointing at it show "ref"; Undo: .../restore)."""
    c = db()
    _need_w(c, sid)
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
    _need_col(c, sid, col_id)
    c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), col_id))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/columns/<int:col_id>/restore")
def sheets_col_restore(sid, col_id):
    c = db()
    _need_w(c, sid)
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
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
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
    _need_row(c, sid, rid)
    c.execute("UPDATE sheet_rows SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), rid))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/rows/<int:rid>/restore")
def sheets_row_restore(sid, rid):
    c = db()
    _need_w(c, sid)
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
    _need_row(c, sid, rid, deleted=True)
    c.execute("UPDATE sheet_rows SET deleted_at=NULL WHERE id=?", (rid,))
    sh_touch(c, sid, me())
    return _done(c, sid)


@app.post("/api/sheets/<int:sid>/rows/order")
def sheets_rows_order(sid):
    """{ids: [row ids in the new order], prev?: [the row ids in the order the writer saw], moved?: [the rows dragged]} -- sorting
    for good (rows not named keep their order behind). 2.528.0 (#4305 A12): under the sheet's lock; with prev a sorting / moving
    elsewhere since (or a row of it deleted) gives 409 {error, rows: the current order, rev} instead of a silent overwrite (rows
    added since: fine). 2.631.0 (#4620): with moved the ranges of formulas keep their rows (sheets/shorder.py) -> also
    {formulas: [{sheet_id, row_id, col_id, raw, now}]} (the changed ones); the Undo sends them back as formulas (with the old
    order, without moved): the ones still as the move left them get their text again. 2.658.0 (#5000): without moved and without
    formulas it is a sorting: every range keeps its span on the same positions (SUM(A1:A3) stays A1:A3, shorder.sho_sort_plan),
    single references follow their cells; inserting rows at a place is a move of the new rows (moved)."""
    return _sh_order(sid, "row")


@app.post("/api/sheets/<int:sid>/columns/order")
def sheets_cols_order(sid):
    """2.631.0 (#4620): {ids: [column ids in the new order], prev?: [the column ids in the order the writer saw], moved?: [the
    columns dragged]} -- like rows/order: columns not named keep their order behind, prev guards against a move elsewhere
    since (409 {error, columns, rev}), moved keeps the ranges of formulas on their columns -> {ok, rev, formulas?}; formulas =
    the Undo's texts (rows/order)."""
    return _sh_order(sid, "col")


def _sh_order(sid, kind):
    """rows/order and columns/order (2.631.0, #4620: one way for both)."""
    c = db()
    r0 = _need_w(c, sid)
    write_lock(c, "sheet:" + str(sid))  # 2.528.0 (#4305 A12): one writer per sheet, also for rows / columns
    b = body()
    ids = b.get("ids")
    table, key = ("sheet_rows", "rows") if kind == "row" else ("sheet_columns", "columns")
    live = [x[0] for x in c.execute(f"SELECT id FROM {table} WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (sid,))]
    lset = set(live)
    if shx_order_moved(live, b.get("prev")):
        r = sh_reload(c, sid)
        name = user_names(c, [r["updated_by"]]).get(r["updated_by"]) or "?"
        return jsonify(error=tr("Changed in the meantime by {0}", name), **{key: live}, rev=r["rev"]), 409
    if not isinstance(ids, list) or len(ids) > len(live) or any(isinstance(x, bool) or x not in lset for x in ids) or len(set(ids)) != len(ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    given = set(ids)
    order = ids + [x for x in live if x not in given]
    back = sho_restore_plan(c, r0, b.get("formulas"), me())  # 2.631.0 (#4620): the Undo of a move puts its formulas back
    mv = sho_moved(b, live)
    if mv is None and b.get("formulas") is None:  # 2.658.0 (#5000): a sorting keeps the spans of ranges on their positions
        plan = sho_sort_plan(c, r0, kind, live, order, me())
    else:  # a move (or its Undo, which names its formulas, maybe none): the ranges keep their members
        plan = sho_plan(c, r0, kind, live, order, mv, me())  # before the new order is stored
    for i, x in enumerate(order):
        c.execute(f"UPDATE {table} SET pos=? WHERE id=?", (float(i + 1), x))
    fx = sho_apply(c, plan, me())
    sho_restore_apply(c, back, me())
    sh_touch(c, sid, me())
    return _done(c, sid, {"formulas": fx} if b.get("moved") is not None else None)


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
    kept = {}  # 2.528.0 (#4306 B24): rows / columns / the table a person typed into since stay
    n = sh_undo_batch(c, r, batch[:80], me(), kept=kept)
    return _done(c, sid, {"undone": n, "kept": kept})


# ---------------------------------------------------------------- 2.528.0 (#4306 B22): the trash of tables, like knowledge
SHX_TRASH_MAX = 500
SHX_ADMIN_ONLY = N_("Only admins of the organisation can empty its trash.")


def shx_may_empty(c, uid, oid):
    """Empty a whole space's table trash (or several at once): the private one its person, an organisation's only its admins
    (like knowledge, wiki/pages.py _wkp_may_empty)."""
    return not oid or is_org_admin(c, uid, oid)


def shx_trashed(c, uid, oid):
    """The tables of space oid in the trash uid may restore (newest first): through the space or its project, never through a
    share or a folder (like restoring, _need_w deleted=True)."""
    w, a = ("org_id=?", (oid,)) if oid else ("org_id IS NULL AND owner_id=?", (uid,))
    rows = c.execute(f"SELECT * FROM sheets WHERE deleted_at IS NOT NULL AND book_id IS NULL AND {w} "
                     f"ORDER BY deleted_at DESC, id DESC LIMIT {SHX_TRASH_MAX}", a).fetchall()
    return [r for r in rows if sh_may(c, uid, r, share=False, fold=False)]


@app.get("/api/sheets/trash")
def sheets_trash_list():
    """?space=private|org:<id> -- the tables of the space in the trash with their files' count / size, the trash period and
    whether the person may empty it. Restore: POST /api/sheets/<id>/restore; for good: POST /api/sheets/purge."""
    c = db()
    uid = me()
    oid = sh_space(c, uid, request.args.get("space") or "private")
    rows = shx_trashed(c, uid, oid)
    ids = [r["id"] for r in rows]
    files = {}
    if ids:
        q = ",".join("?" * len(ids))
        for x in c.execute(f"SELECT COALESCE(s.book_id, s.id) AS t, COUNT(f.id) AS n, COALESCE(SUM(f.size), 0) AS size FROM sheet_files f "
                           f"JOIN sheets s ON s.id=f.sheet_id WHERE s.id IN ({q}) OR s.book_id IN ({q}) GROUP BY COALESCE(s.book_id, s.id)",
                           [*ids, *ids]).fetchall():
            files[x["t"]] = (x["n"], int(x["size"]))
    return jsonify(space=sh_space_key(oid), days=ret_trash_days(), purge_on=ret_on("trash"), may_empty=shx_may_empty(c, uid, oid),
                   sheets=[{"id": r["id"], "title": r["title"], "deleted_at": r["deleted_at"], "list_title": sh_list_title(c, r, uid),
                            "files": files.get(r["id"], (0, 0))[0], "size": files.get(r["id"], (0, 0))[1],
                            "can_write": sh_may(c, uid, r, write=True, share=False, fold=False)} for r in rows])


def shx_preview(c, sheet_row, book, cells, n=3):
    """A few of the inputs of a trashed row / column as words (formulas in the display form, a choice by its label; files,
    people and ticks left out) so the person recognises it."""
    out = []
    for x in cells:
        raw = (x["raw"] or "").strip()
        col = book.col_all.get(x["col_id"])
        if not raw or not col or col["kind"] in ("file", "person", "checkbox"):
            continue
        if col["kind"] == "select" and not raw.startswith("="):
            raw = next((o.get("label") or "" for o in sh_options(col["options"]) if o.get("id") == raw), raw)
        elif raw.startswith("="):
            raw = sh_to_display(c, sheet_row, raw, book)
        if raw:
            out.append(raw[:60])
        if len(out) >= n:
            break
    return out


@app.get("/api/sheets/<int:sid>/trash")
def sheets_sheet_trash(sid):
    """The rows, columns and further sheets of a table in the trash (reading = seeing the table), each with a few of its inputs;
    restore: .../rows/<id>/restore, .../columns/<id>/restore, POST /api/sheets/<tab>/restore (the right to write)."""
    c = db()
    r = sh_need(c, sid)
    book = ShBook(c, r)
    book.col_all = {x["id"]: x for x in c.execute("SELECT * FROM sheet_columns WHERE sheet_id=?", (sid,)).fetchall()}
    by_row, by_col = {}, {}
    for x in sorted(book.cells.values(), key=lambda x: (x["row_id"], x["col_id"])):
        by_row.setdefault(x["row_id"], []).append(x)
        by_col.setdefault(x["col_id"], []).append(x)
    rows = c.execute(f"SELECT id, deleted_at FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC, id DESC "
                     f"LIMIT {SHX_TRASH_MAX}", (sid,)).fetchall()
    cols = [x for x in sorted(book.col_all.values(), key=lambda x: (x["deleted_at"] or "", x["id"]), reverse=True) if x["deleted_at"]]
    tabs = []
    if not r["book_id"]:  # the first sheet: its further sheets in the trash (a further sheet is opened through its table)
        tabs = c.execute("SELECT id, tab_name, title, deleted_at FROM sheets WHERE book_id=? AND deleted_at IS NOT NULL "
                         "ORDER BY deleted_at DESC, id DESC", (sid,)).fetchall()
    return jsonify(days=ret_trash_days(), purge_on=ret_on("trash"), can_write=sh_may(c, me(), r, write=True),
                   rows=[{"id": x["id"], "deleted_at": x["deleted_at"], "values": shx_preview(c, r, book, by_row.get(x["id"], []))} for x in rows],
                   columns=[{"id": x["id"], "title": x["title"], "kind": x["kind"], "deleted_at": x["deleted_at"],
                             "values": shx_preview(c, r, book, by_col.get(x["id"], []))} for x in cols[:SHX_TRASH_MAX]],
                   tabs=[{"id": x["id"], "name": x["tab_name"] or x["title"], "deleted_at": x["deleted_at"]} for x in tabs])


def shx_purge(c, ids):
    """Tables ids (first sheets in the trash) for good, as the trash run does (files/trashpurge.py tp_tick): the stored files
    of their file cells (also of their further sheets) with their scan / text rows, their folder nodes; the rest cascades.
    -> stored paths to unlink after the commit."""
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    fr = c.execute(f"SELECT f.id, f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE s.id IN ({q}) OR s.book_id IN ({q})",
                   [*ids, *ids]).fetchall()
    for i in range(0, len(fr), 500):
        fids = [x["id"] for x in fr[i:i + 500]]
        fq = ",".join("?" * len(fids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='sheet' AND ref_id IN ({fq})", fids)
        c.execute(f"DELETE FROM file_text WHERE kind='sheet' AND ref_id IN ({fq})", fids)
    c.execute(f"DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id IN ({q})", ids)
    # 2.571.0 (#4766): the core's history of the table's own fields (no FK) goes with it
    c.execute(f"DELETE FROM obj_history WHERE kind='sheet' AND ref_id IN (SELECT id FROM sheets WHERE book_id IN ({q}) "
              f"OR (id IN ({q}) AND deleted_at IS NOT NULL))", [*ids, *ids])
    c.execute(f"DELETE FROM sheets WHERE book_id IN ({q})", ids)
    c.execute(f"DELETE FROM sheets WHERE id IN ({q}) AND deleted_at IS NOT NULL", ids)
    return [x["path"] for x in fr]


@app.post("/api/sheets/purge")
def sheets_purge_many():
    """{space, ids} -- these tables of the trash for good; {space, all: true} -- empty the space's table trash. Rights as
    restoring (the right to write through the space); several / all of an organisation only its admins. -> {ids, skipped}"""
    need_feat("sheets")
    c = db()
    uid = me()
    b = body()
    oid = sh_space(c, uid, b.get("space") or "private")
    ids = b.get("ids")
    if b.get("all") is not True and (not isinstance(ids, list) or len(ids) > SHX_TRASH_MAX
                                     or any(isinstance(x, bool) or not isinstance(x, int) for x in ids)):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    mine = [r["id"] for r in shx_trashed(c, uid, oid) if sh_may(c, uid, r, write=True, share=False, fold=False)]
    if b.get("all") is not True:
        want = set(ids)
        mine = [x for x in mine if x in want]
    if oid and (b.get("all") is True or len(mine) > 1) and not shx_may_empty(c, uid, oid):
        raise Denied(403, tr(SHX_ADMIN_ONLY))  # one's own single table stays allowed (like knowledge)
    paths = shx_purge(c, mine)
    if mine:
        if oid:  # the organisation's admins see it in the history of its projects (no table names)
            c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at,detail) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", (oid, None, f"Tables ({len(mine)})", "purge", uid, None, None, iso_ms(now_utc()),
                                                    json.dumps({"kind": "sheet", "sheets": len(mine)})))
        bump(c)
    c.commit()
    unlink_files(paths)  # after the commit: a failed commit keeps the rows and their files
    return jsonify(ok=True, ids=mine, skipped=[x for x in (ids or []) if x not in set(mine)])
