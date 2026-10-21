"""2.72.0 (#1333): the household budget -- the web API (the model is life/budget.py). Every route needs the module
"budget" (409 otherwise); reading needs the budget list visible, everything else the right to change it; agents and API
tokens without the scope "private" never reach a budget (404 / 403). No REST v1 / MCP routes in 2.72.0."""
from flask import jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..accounts.session import me
from ..core.serializers import unlink_files
from ..core.access import Denied
from ..core.stmtfiles import stmt_req
from ..life.budget import (
    bud_compare, bud_contracts, bud_contracts_take, bud_files_save, bud_import_commit, bud_import_parse, bud_import_runs, bud_import_undo,
    bud_list_create, bud_month,
    bud_month_view, bud_need_on, bud_obj, bud_overview, bud_this_month, cat_create, cat_delete, cat_update, entry_create,
    entry_delete, entry_update, rec_book, rec_create, rec_delete, rec_list, rec_update,
)
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions


def _done(c, out, code=200):
    bump(c)  # the area "budget" of /api/version: open budget views of other devices / family members reload
    c.commit()
    return jsonify(out), code


@app.get("/api/budget")
def budget_overview():
    """{lists: [{id, name, color, owner_id, shared, can_write}], month, summary: totals of the first list | null}."""
    c = db()
    return jsonify(bud_overview(c, me()))


@app.post("/api/budget/lists")
def budget_list_new():
    """{name?} -> {list_id}: a new budget list with the default categories."""
    c, uid = db(), me()
    lid = bud_list_create(c, uid, body())
    return _done(c, {"list_id": lid}, 201)


@app.get("/api/budget/<int:lid>")
def budget_month(lid):
    """?month=YYYY-MM (default: this month): categories with soll / ist, totals, entries, open templates, 6-month trend."""
    c = db()
    return jsonify(bud_month_view(c, me(), lid, bud_month(request.args.get("month") or bud_this_month())))


@app.get("/api/budget/<int:lid>/compare")
def budget_compare(lid):
    """2.140.0 B (#2134): ?month=YYYY-MM (default: this month) &months=3|6|12 (default 6): per category ist / plan of every
    month, the difference to the month before and to the average of the earlier months."""
    c = db()
    try:
        n = int(request.args.get("months") or 6)
    except ValueError:
        return err(tr("Invalid value: {0}", "months"))
    return jsonify(bud_compare(c, me(), lid, bud_month(request.args.get("month") or bud_this_month()), n))


@app.post("/api/budget/<int:lid>/cats")
def budget_cat_new(lid):
    c, uid = db(), me()
    return _done(c, cat_create(c, uid, lid, body()), 201)


@app.patch("/api/budget/cats/<int:cid>")
def budget_cat_patch(cid):
    c, uid = db(), me()
    return _done(c, cat_update(c, uid, cid, body()))


@app.delete("/api/budget/cats/<int:cid>")
def budget_cat_delete(cid):
    """-> {ok, cat, entry_ids, recurring_ids}: the deleted category and the rows that lost it (for the undo)."""
    c, uid = db(), me()
    return _done(c, {"ok": True, **cat_delete(c, uid, cid)})


@app.post("/api/budget/<int:lid>/entries")
def budget_entry_new(lid):
    """{day, amount, kind, title, note?, counterpart?, cat_id?, recurring_id?} -> the entry."""
    c, uid = db(), me()
    return _done(c, entry_create(c, uid, lid, body()), 201)


@app.patch("/api/budget/entries/<int:eid>")
def budget_entry_patch(eid):
    c, uid = db(), me()
    return _done(c, entry_update(c, uid, eid, body()))


@app.delete("/api/budget/entries/<int:eid>")
def budget_entry_delete(eid):
    """-> {ok, entry}: the entry as it was (the app's undo creates it again; its receipts are gone)."""
    c, uid = db(), me()
    out, paths = entry_delete(c, uid, eid)
    bump(c)
    c.commit()
    unlink_files(paths)
    return jsonify(ok=True, entry=out)


@app.get("/api/budget/<int:lid>/recurring")
def budget_rec_list(lid):
    c = db()
    return jsonify(items=rec_list(c, me(), lid))


@app.post("/api/budget/<int:lid>/recurring")
def budget_rec_new(lid):
    """{title, amount, kind, cat_id?, per: month|quarter|year, start: YYYY-MM, until?} -> the template."""
    c, uid = db(), me()
    return _done(c, rec_create(c, uid, lid, body()), 201)


@app.patch("/api/budget/recurring/<int:rid>")
def budget_rec_patch(rid):
    """Fields of the template; {sync_contract: true} = amount and period from its contract."""
    c, uid = db(), me()
    return _done(c, rec_update(c, uid, rid, body()))


@app.delete("/api/budget/recurring/<int:rid>")
def budget_rec_delete(rid):
    """-> {ok, item}: booked entries stay (without the link)."""
    c, uid = db(), me()
    out = rec_delete(c, uid, rid)
    return _done(c, {"ok": True, "item": out})


@app.post("/api/budget/recurring/<int:rid>/book")
def budget_rec_book(rid):
    """{month: YYYY-MM, day?} -> the booked entry (409 when it is booked in that month already)."""
    c, uid = db(), me()
    return _done(c, rec_book(c, uid, rid, body()), 201)


@app.get("/api/budget/<int:lid>/contracts")
def budget_contracts(lid):
    c = db()
    return jsonify(items=bud_contracts(c, me(), lid))


@app.post("/api/budget/<int:lid>/contracts")
def budget_contracts_take(lid):
    """{task_ids: [..], cat_id?} -> {created, items}: templates from contracts."""
    c, uid = db(), me()
    return _done(c, bud_contracts_take(c, uid, lid, body()), 201)


@app.post("/api/budget/<int:lid>/import/parse")
def budget_import_parse(lid):
    """{text, mapping?} or a multipart upload (2.146.0 C #2455: field files, several / a ZIP; mapping as JSON): the columns +
    a guess, or (with a mapping / CAMT) the checked rows. Nothing is stored."""
    c = db()
    return jsonify(bud_import_parse(c, me(), lid, stmt_req()))


@app.post("/api/budget/<int:lid>/import/commit")
def budget_import_commit(lid):
    """{rows: [..], mapping?, columns?, run?, label?, fmt?} -> {created, skipped_dup, run}."""
    c, uid = db(), me()
    return _done(c, bud_import_commit(c, uid, lid, body()), 201)


@app.get("/api/budget/<int:lid>/import/runs")
def budget_import_runs(lid):
    """2.146.0 C (#2455): the last imports of the list -> {items: [{id, at, label, fmt, count, left, edited, undone_at}]}."""
    c = db()
    return jsonify(bud_import_runs(c, me(), lid))


@app.post("/api/budget/<int:lid>/import/runs/<run>/undo")
def budget_import_undo(lid, run):
    """2.146.0 C (#2455): {edited?: keep | delete} -> {deleted, kept}: takes one import back (its entries, with receipts)."""
    c, uid = db(), me()
    b = body()
    out, paths = bud_import_undo(c, uid, lid, run, b if isinstance(b, dict) else {})
    bump(c)
    c.commit()
    unlink_files(paths)
    return jsonify(out)


@app.post("/api/budget/entries/<int:eid>/files")
def budget_files_upload(eid):
    """multipart file (several allowed) -> {files: [..]} of the entry."""
    c, uid = db(), me()
    files = request.files.getlist("file")
    if not files:
        return err(tr("File missing"))
    saved = []
    try:
        out = bud_files_save(c, uid, eid, files, saved)
    except (BadInput, Denied, OSError):
        c.rollback()
        unlink_files(saved)
        raise
    bump(c)
    c.commit()
    return jsonify(files=out)


@app.get("/api/budget/files/<int:fid>")
def budget_file_get(fid):
    """The receipt (?inline=1 or an inline type: shown; ?dl=1: a download), served like attachments."""
    from ..tasks.attachments import send_stored
    c = db()
    uid = me()
    bud_need_on(c, uid)
    r = dict(bud_obj(c, uid, "budget_files", fid, write=False))
    from ..files.scan import sc_guard
    sc_guard(c, "budget", fid)  # 2.126.0 A (#1979 L1): like the other stored files
    return send_stored(r)


@app.delete("/api/budget/files/<int:fid>")
def budget_file_delete(fid):
    c, uid = db(), me()
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_files", fid)
    c.execute("DELETE FROM budget_files WHERE id=?", (r["id"],))
    bump(c)
    c.commit()
    unlink_files([r["path"]])
    return jsonify(ok=True)
