"""2.800.0 (#5409): undo across devices, stage 5 rest -- a person's structural changes of a table as changes of its batch.

The cells, rows and columns added were the first steps of a table (sheets/shundo.py, #5253). The other changes of a person
are kept in the same batch of the request (sheet_changes, sheets/shundo.py shu_rec) with what their way back needs, and
taken back / forward through sheets/core.py sh_undo_batch / sheets/shundo.py shu_redo (SH_STEP_KINDS), so "Recent steps"
lists one pointer step per request and table like for the cells:
  rdel / cdel   a row / column deleted (old = how the table named it, new = its time in the trash): back = out of the trash
                while it is still in it from this delete, forward = into the trash again while it is live
  cset          a column's settings (title, type, options, colour, width, place, decimals, currency; old / new = the
                fields that changed): back = sheets/web.py shx_col_apply with _prev = the values the step left -- a field
                changed elsewhere since stays and is named, the others go back
  order         rows / columns moved or sorted (old = the order before, new = after, the block and the formulas a move
                changed): back = sh_order_apply with prev = the order the step left (moved elsewhere since: stays)
  chart / rules the table's chart / colour rules (old / new = the stored JSON): only while it is still the one the step left
  freeze / name a cell's frozen value / name: only while the cell still has the step's state
  fixed         the rows / columns kept in view while scrolling: only while they are as the step left them
  tadd / tdel / tname / tpos   the sheets of the bar: a sheet added (back = to the trash), deleted (back = out of it), its
                name, the order of the sheets (each only while it is as the step left it)
A change that cannot go (changed elsewhere since) stays and is named, the rest of the step goes back (shundo.py shu_run).
The table's own title and project are written through the core's write layer (sheets/shhist.py shh_meta_write -> ow_write
-> a copy step of the tracked kind "sheet"): their way back is the core's copy step, here only who may take it (write access
to the table now) and which columns of the sheets row it writes back (title, the sheet's name, the project)."""
import json

from ..core.access import Denied, live_sql, need_feat
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.undoweb import undo_need_reg
from ..files.fsref import fs_ref_rename
from .core import SH_STEP_KINDS, ShBook, sh_check_list, sh_freeze, sh_may_rebind, sh_need, sh_reload, sh_set_name, sh_touch
from .shbook import SHB_TABS_MAX, _name_free, shb_bid, shb_label, shb_name_set, shb_rows, shb_sync
from ..core.pg import qi, table_columns, ts_canon
from .shhist import SHH_KIND, SHH_OWN, _core, shh_meta
from .shshare import shs_need_own
from .web import sh_order_apply, shx_col_apply, shx_place


def _js(v):
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None


def _ends(ch, redo):
    """(to, from) of a change: back = to its old value from the new one, forward the other way."""
    return (ch["new_raw"], ch["old_raw"]) if redo else (ch["old_raw"], ch["new_raw"])


SHU_TABLES = ("sheet_rows", "sheet_columns")
SHU_SHEET_COLS = ("chart", "fmt_rules")


def _trash(table, what):
    def run(c, r, ch, uid, ts, redo):
        xid = ch["row_id"] if what == "row" else ch["col_id"]
        if redo:  # 2.884.0 (#5479): into the trash with the time of now (the old time would let the trash purge take it at once)
            n = c.execute(f"UPDATE {qi(table, SHU_TABLES)} SET deleted_at=? WHERE id=? AND sheet_id=? AND {live_sql()}", (ts, xid, r["id"])).rowcount
            if n:  # the next undo finds it by this time (a step redone before 2.884.0 keeps its old one: found as well)
                c.execute("UPDATE sheet_changes SET new_raw=? WHERE id=?", (ts, ch["id"]))
        else:
            n = c.execute(f"UPDATE {qi(table, SHU_TABLES)} SET deleted_at=NULL WHERE id=? AND sheet_id=? AND deleted_at=?", (xid, r["id"], ch["new_raw"])).rowcount
        return (True, None) if n else (False, ch["old_raw"] or tr("Table"))
    return run


def _col_name(c, r, col_id):
    return shx_place(c, r["id"], "col", col_id)


def _cset(c, r, ch, uid, ts, redo):
    to, frm = (_js(x) or {} for x in _ends(ch, redo))
    col = c.execute("SELECT * FROM sheet_columns WHERE id=? AND sheet_id=?", (ch["col_id"], r["id"])).fetchone()
    name = _col_name(c, r, ch["col_id"]) if col else tr("Column {0}", "?")
    if col is None or col["deleted_at"]:
        return False, name
    b, kept = {}, []
    for k, v in to.items():
        if k == "options":  # the whole list: only while it is the one the step left
            if (_js(col["options"]) or []) != (_js(frm.get("options")) or []):
                kept.append(k)
            else:
                b["options"] = _js(v) or []
        else:
            b[k] = v
    if not b:
        return False, name
    b["_prev"] = {k: v for k, v in frm.items() if k != "options"}
    try:
        _added, cf = shx_col_apply(c, r, ch["col_id"], b, uid)
    except BadInput:  # a value the column's checks refuse now
        return False, name
    went = len(b) - 1 - len(cf)
    return went > 0, (name if (cf or kept) else None)


def _order(c, r, ch, uid, ts, redo):
    a, z = _js(ch["old_raw"]) or {}, _js(ch["new_raw"]) or {}
    kind = "row" if a.get("k") == "row" else "col"
    name = tr("Rows") if kind == "row" else tr("Columns")
    table = "sheet_rows" if kind == "row" else "sheet_columns"
    live = {x[0] for x in c.execute(f"SELECT id FROM {qi(table, SHU_TABLES)} WHERE sheet_id=? AND {live_sql()}", (r["id"],))}
    to, frm = (z.get("ids"), a.get("ids")) if redo else (a.get("ids"), z.get("ids"))
    b = {"ids": [x for x in to or [] if x in live], "prev": [x for x in frm or [] if x in live]}
    if z.get("move"):
        mv = [x for x in z.get("mv") or [] if x in live]
        if redo and mv:
            b["moved"] = mv
        else:  # back: the formulas the move changed get their text again (named, so it is no sorting)
            b["formulas"] = [] if redo else (z.get("fx") or [])
    if not b["ids"]:
        return False, name
    try:
        out = sh_order_apply(c, r, kind, b, uid)
    except BadInput:
        return False, name
    if isinstance(out, dict):  # moved elsewhere since
        return False, name
    if redo and z.get("move") and "moved" in b:  # the move again changed its formulas anew: their way back
        c.execute("UPDATE sheet_changes SET new_raw=? WHERE id=?", (json.dumps({**z, "fx": out}), ch["id"]))
    return True, None


def _sheet_val(col, what, label):
    def run(c, r, ch, uid, ts, redo):
        to, frm = (x or "" for x in _ends(ch, redo))
        cur = c.execute(f"SELECT {qi(col, SHU_SHEET_COLS)} FROM sheets WHERE id=?", (r["id"],)).fetchone()[0] or ""
        if cur != frm:
            return False, tr(label)
        c.execute(f"UPDATE sheets SET {qi(col, SHU_SHEET_COLS)}=? WHERE id=?", (to, r["id"]))
        if what == "rules":
            shh_meta(c, r["id"], what, str(len(_js(frm) or [])) if frm else "", str(len(_js(to) or [])) if to else "", uid)
        else:
            shh_meta(c, r["id"], what, frm, to, uid)
        sh_touch(c, r["id"], uid)
        return True, None
    return run


def _fixed(c, r, ch, uid, ts, redo):
    """The rows / columns kept in view (sheets/shkinds.py shk_fixed): only while they are still as the step left them."""
    to, frm = (_js(x) or {} for x in _ends(ch, redo))
    cur = c.execute("SELECT freeze_rows, freeze_cols FROM sheets WHERE id=?", (r["id"],)).fetchone()
    if any(cur[k] != frm.get(k) for k in ("freeze_rows", "freeze_cols")):
        return False, tr("Kept rows and columns")
    c.execute("UPDATE sheets SET freeze_rows=?, freeze_cols=? WHERE id=?", (to.get("freeze_rows") or 0, to.get("freeze_cols") or 0, r["id"]))
    sh_touch(c, r["id"], uid)
    return True, None


def _cell(c, r, ch):
    x = c.execute("SELECT * FROM sheet_cells WHERE id=? AND sheet_id=?", (ch["cell_id"], r["id"])).fetchone()
    book = ShBook(c, sh_reload(c, r["id"]))
    y = book.at.get((ch["row_id"], ch["col_id"]))
    return x, (book.addr(y) if y is not None and book.live(y) else tr("Table"))


def _freeze(c, r, ch, uid, ts, redo):
    to, frm = _ends(ch, redo)
    x, name = _cell(c, r, ch)
    if x is None or ("1" if x["frozen"] else "0") != frm:
        return False, name
    try:
        sh_freeze(c, r, x, to == "1", uid)
    except BadInput:  # no value to freeze any more (an error now)
        return False, name
    return True, None


def _name(c, r, ch, uid, ts, redo):
    to, frm = _ends(ch, redo)
    x, name = _cell(c, r, ch)
    if x is None or (x["name"] or "") != (frm or ""):
        return False, name
    try:
        sh_set_name(c, r, x, to or "", uid)
    except BadInput:  # the name is taken by another cell / column since
        return False, name
    return True, None


def _tab(c, r, tid):
    t = c.execute("SELECT * FROM sheets WHERE id=?", (int(tid),)).fetchone() if str(tid or "").isdigit() else None
    return t if t is not None and shb_bid(t) == r["id"] else None


def _tab_name(t):
    return tr("Sheet {0}", shb_label(t)) if t is not None else tr("Sheets")


def _tab_trash(added):
    """tadd: back = the new sheet to the trash, forward = out again; tdel the other way round (its time in the trash)."""
    def run(c, r, ch, uid, ts, redo):
        t = _tab(c, r, ch["new_raw"] if added else ch["old_raw"])
        if t is None or not t["book_id"]:
            return False, _tab_name(t)
        out = (not redo) if added else redo  # into the trash
        # 2.884.0 (#5479): a deleted sheet deleted again (redo) gets the time of now, like the rows / columns (_trash)
        when = ts if out else (ch["undone_at"] if added else ch["new_raw"])
        # 2.1093.0 (#5472): in and out through the core's trash (sheets/shkern.py, checked: the step's rights were checked by
        # the undo), with the step's time -- the way back compares it
        from .shkern import shk_restore, shk_trash  # shkern loads sheets/core.py, as this module does
        if out:
            n = 0 if t["deleted_at"] else 1
            if n:
                shk_trash(c, uid, t["id"], checked=True, ts=when)
            if n and not added:
                c.execute("UPDATE sheet_changes SET new_raw=? WHERE id=?", (ts, ch["id"]))
        else:
            tabs = shb_rows(c, r["id"])
            if len(tabs) >= SHB_TABS_MAX:  # 2.884.0 (#5479): back only below the limit, as sheets_tabs_restore
                return False, _tab_name(t)
            if any(shb_label(x).casefold() == shb_label(t).casefold() for x in tabs):
                return False, _tab_name(t)  # its name is taken meanwhile
            n = 1 if t["deleted_at"] and ts_canon(t["deleted_at"]) == ts_canon(when) else 0
            if n:
                shk_restore(c, uid, t["id"], checked=True)
        if not n:
            return False, _tab_name(t)
        sh_touch(c, r["id"], uid)
        return True, None
    return run


def _tname(c, r, ch, uid, ts, redo):
    to, frm = (_js(x) or {} for x in _ends(ch, redo))
    t = _tab(c, r, to.get("t"))
    if t is None or t["deleted_at"] or shb_label(t) != frm.get("v"):
        return False, _tab_name(t)
    try:
        _name_free(shb_rows(c, r["id"]), to.get("v") or "", but=t["id"])
    except BadInput:
        return False, _tab_name(t)
    shb_name_set(c, t, to.get("v") or "", uid)
    sh_touch(c, t["id"], uid)
    return True, None


def _tpos(c, r, ch, uid, ts, redo):
    to, frm = (_js(x) or [] for x in _ends(ch, redo))
    live = [x["id"] for x in shb_rows(c, r["id"])]
    seen = set(frm)
    if [x for x in live if x in seen] != [x for x in frm if x in set(live)]:
        return False, tr("Sheets")  # moved elsewhere since
    want = [x for x in to if x in set(live)]
    order = want + [x for x in live if x not in set(want)]
    for k, x in enumerate(order):
        c.execute("UPDATE sheets SET tab_pos=? WHERE id=?", (float(k + 1), x))
    sh_touch(c, r["id"], uid)
    return True, None


SH_STEP_KINDS.update({
    "rdel": _trash("sheet_rows", "row"), "cdel": _trash("sheet_columns", "col"), "cset": _cset, "order": _order,
    "chart": _sheet_val("chart", "chart", "Chart"), "rules": _sheet_val("fmt_rules", "rules", "Colour rules"),
    "freeze": _freeze, "name": _name, "fixed": _fixed,
    "tadd": _tab_trash(True), "tdel": _tab_trash(False), "tname": _tname, "tpos": _tpos,
})


# ---------------------------------------------------------------- the table's own fields: the core's copy step
def _rebind_ok(c, uid, r, now):
    """An undo / redo that hangs table r on another project (now = the row after the write-back) is held to what
    sheets_patch asks for a change of project: never through a share, its creator or the list's owner / admins only,
    write access to the target project, same workspace, no project with a lock. Denied rolls the part back (savepoint).
    2.800.0 (#5409, review): before, only write access to the table was checked."""
    shs_need_own(c, r)
    if not sh_may_rebind(c, uid, r):
        raise Denied(403)
    try:
        sh_check_list(c, r["org_id"], now["list_id"], uid)
    except BadInput as e:  # a project of another workspace / with a lock since: the step stays, named like a conflict
        raise Denied(409, str(e)) from None


def _sheet_need(c, uid, rid, oid):
    """Who may take a copy step of the tracked kind "sheet" back (core/undoweb.py _need): write access to the table now.
    Only its own fields go back (title, the sheet's name, the project); the rest of the row stays as it is now (a cell
    typed since changes rev / updated_at only, never part of the check)."""
    need_feat("sheets")
    r = sh_need(c, int(rid), write=True)
    keep = {k for k in table_columns(c, "sheets") if k not in SHH_OWN}
    if r["book_id"]:  # 2.884.0 (#5479): a further sheet's project follows the first sheet (shb_sync), never its own step
        keep.add("list_id")

    def fix(c):
        now = sh_reload(c, int(rid))
        if now["list_id"] != r["list_id"]:
            _rebind_ok(c, uid, r, now)  # 2.800.0 (#5409, review): the project back only with the checks of PATCH /api/sheets
        shb_sync(c, int(rid))  # every sheet of the table hangs on the same list
        if not now["book_id"]:
            fs_ref_rename(c, "sheet", int(rid), now["title"])  # the table's name in its folder
        sh_touch(c, int(rid), uid)
    if r["deleted_at"]:
        raise Denied(404)
    return {"keep": {"sheets": keep}, "fix": fix, "lock": "sheet:" + str(int(rid))}


_core()  # the kind is tracked before its first step is taken back (a fresh process: no title written yet)
undo_need_reg(SHH_KIND, _sheet_need)
