"""2.124.0 B (#2112): the change history of a table's cells -- every input a person (or an agent) stored: who, when, before /
after. Written by sheets/core.py _store (one row per changed cell), kept short: the newest SHH_KEEP rows of a sheet within
SHH_DAYS (older ones go on the next write), at most SHH_KEEP rows of one call (an import logs nothing: io.py sets shh_off).
Its own table (sheet_hist), so the agents' trail (sheet_changes, sh_undo_batch, the "Changes by agents" panel) stays as it
is. Inputs are stored as the cells keep them (sheet_cells.raw is not sealed at rest either) and shown for the viewer:
formulas with the names they may see, options / people / files by their names. Read = the right to read the table; the
rows hang on the sheet, so they move with it (private <-> organisation) and go with it.
"""
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import db, iso_ms, now_utc
from ..core.i18n import N_, tr
from ..accounts.session import me
from ..collab.comments import user_names
from .shkinds import SHK_FILE_RE, shk_bool, shk_people  # 2.369.5 (#2517): pulled up from functions

SHH_KEEP = 200
SHH_DAYS = 90
SHH_CELL_MAX = 50


def shh_log(c, book, xid, rid, cid, old, new, uid, agent_id, ts):
    """One changed cell (core._store). The first entry of a call prunes the sheet's history."""
    if getattr(book, "shh_off", False):
        return
    n = getattr(book, "_shh_n", 0)
    if n >= SHH_KEEP:
        return
    sid = book.sheet["id"]
    if not n:
        cut = iso_ms(now_utc() - timedelta(days=SHH_DAYS))
        c.execute("DELETE FROM sheet_hist WHERE sheet_id=? AND (at<? OR id<=(SELECT id FROM sheet_hist WHERE sheet_id=? "
                  "ORDER BY id DESC LIMIT 1 OFFSET ?))", (sid, cut, sid, SHH_KEEP - 1))
    book._shh_n = n + 1
    c.execute("INSERT INTO sheet_hist(sheet_id,cell_id,row_id,col_id,user_id,agent_id,old_raw,new_raw,at) VALUES(?,?,?,?,?,?,?,?,?)",
              (sid, xid, rid, cid, uid, agent_id, old or "", new or "", ts))


# 2.564.0 (#4701): changes of the table itself in the same history (sheet_hist.what): their label
SHH_META = {"title": N_("Title"), "tab": N_("Sheet"), "chart": N_("Chart"), "name": N_("Name"), "freeze": N_("Frozen value"),
            "format": N_("Format"), "rules": N_("Colour rules")}  # 2.578.0 (#3462 C)


def shh_meta(c, sid, what, old, new, uid, cell=None):
    """2.564.0 (#4701): a change of table sid that is no typed input (what = a key of SHH_META; cell = the cell row for name /
    freeze), with the value before / after as text. Nothing when it stayed the same."""
    old, new = "" if old is None else str(old), "" if new is None else str(new)
    if old == new:
        return
    c.execute("INSERT INTO sheet_hist(sheet_id,cell_id,row_id,col_id,user_id,agent_id,old_raw,new_raw,at,what) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (sid, cell["id"] if cell else None, cell["row_id"] if cell else None, cell["col_id"] if cell else None, uid, None,
               old, new, iso_ms(now_utc()), what))


# 2.571.0 (#4766): the table's own fields (its title, a sheet's name, the project it hangs on) are written through the core's
# write layer (office/owrite.py ow_write on the tracked kind "sheet": the table's lock, the version, the history, bump) and noted
# in the core's history obj_history, no longer in sheet_hist. Rows of sheet_hist with what title / tab written by 2.564-2.570
# stay and read as before; GET /api/sheets/<id>/history shows both, newest first (shh_core_entries).
SHH_KIND = "sheet"
SHH_CORE = {"title": "title", "tab_name": "tab", "list_id": "list"}  # column of sheets -> what (SHH_META)
SHH_META["list"] = N_("Project")


SHH_OWN = ("title", "tab_name", "list_id")  # 2.800.0 (#5409): the table's own fields of its copy step (sheets/shustep.py)


class _NotOwn:
    """2.800.0 (#5409): every column of the sheets row but its own fields -- not part of the copy step's check (a chart, a
    colour rule, the sheet's place changed since do not stop the title's way back)."""

    def __contains__(self, k):
        return k not in SHH_OWN and k != "deleted_at"


def _label(main):
    from ..core.undogroups import UG_LABEL
    return UG_LABEL, [main.get("title") or "Table"]


def _core():
    """2.571.0 (#4766): the core's write layer, imported on first use (core/writes.py -> core/objects.py -> files/web.py ->
    ... -> sheets: a module-level import would be a cycle); the kind is tracked once. 2.800.0 (#5409): its steps are in the
    area of the tables, name the table and check only its own fields (sheets/shustep.py takes them back)."""
    from ..core.writes import OBJ_TRACK, obj_history_add, obj_track
    if SHH_KIND not in OBJ_TRACK:
        obj_track(SHH_KIND, "sheets", area="sheets", undo_nofp={"sheets": _NotOwn()}, undo_label=_label)
    return obj_history_add


def shh_meta_write(c, uid, r, b, clean, public, version=True):
    """2.571.0 (#4766): change the table's own fields of sheet row r: clean(c, b, cur) -> {column: value} under the lock (its
    checks may refuse), public(c, cur) -> the current state of a 409 ("current"); version=False: the caller checked its own
    version (API v1: expect_rev). The table's name in its folder, the list on its other sheets, rev + the area follow.
    Returns {column: (before, after)}. The caller commits."""
    _core()
    from ..office.owrite import ow_write
    from ..files.fsref import fs_ref_rename
    from .core import sh_touch
    from .shbook import shb_sync
    sid = int(r["id"])
    _, ch = ow_write(c, uid, SHH_KIND, sid, b, clean, where="id=? AND deleted_at IS NULL", args=(sid,), public=public,
                     version=version, lock="sheet:" + str(sid))
    if ch:
        if "list_id" in ch:
            shb_sync(c, sid)  # 2.124.0 E (#2116): every sheet of the table hangs on the same list
        if "title" in ch and not r["book_id"]:
            fs_ref_rename(c, "sheet", sid, ch["title"][1])  # 2.199.0 C (#2742): the table's name in its folder
        sh_touch(c, sid, uid)
    return ch


def shh_meta_note(c, sid, col, old, new, uid):
    """2.571.0 (#4766): a change of one own field of table sid written by a route of its own (a sheet's name in the bar) ->
    the core's history (the changes of one person within ten minutes merge there)."""
    if ("" if old is None else str(old)) != ("" if new is None else str(new)):
        _core()(c, uid, SHH_KIND, sid, {col: old}, {col: new})


def shh_core_entries(c, sheet, uid, limit):
    """2.571.0 (#4766): the entries of obj_history of table sheet in the form of shh_entries (what = title | tab | list)."""
    from .core import sh_list_title
    rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?", (SHH_KIND, sheet["id"], int(limit))).fetchall()
    names = user_names(c, {r["user_id"] for r in rows if r["user_id"]})

    def txt(col, v):
        if col == "list_id":  # only a project the viewer may see is named
            return (sh_list_title(c, {"list_id": v}, uid) or "?") if v else ""
        return "" if v is None else str(v)
    out = []
    for r in rows:
        before, after = json.loads(r["vals_before"] or "{}"), json.loads(r["vals_after"] or "{}")
        for col in [k for k in SHH_CORE if k in before or k in after]:
            out.append({"id": f"h{r['id']}:{col}", "at": r["updated_at"], "user_id": r["user_id"],
                        "user_name": names.get(r["user_id"], "") or tr("Unknown"), "agent": bool(r["agent"]), "cell_id": None,
                        "row_id": None, "col_id": None, "addr": None, "what": SHH_CORE[col], "col_title": tr(SHH_META[SHH_CORE[col]]),
                        "old": txt(col, before.get(col)), "new": txt(col, after.get(col))})
    return out


def _meta_text(c, what, raw, cols):
    """2.564.0 (#4701): how a change of the table reads: a chart as its kind and columns, a freeze as yes / no."""
    if not raw:
        return ""
    if what == "freeze":
        return tr("Yes") if raw == "1" else tr("No")
    if what == "chart":
        import json
        try:
            ch = json.loads(raw)
        except ValueError:
            return raw
        if not isinstance(ch, dict):
            return raw
        names = [(cols.get(y)["title"] if cols.get(y) else "?") for y in ch.get("y") or []]
        return (tr("Line|chart") if ch.get("type") == "line" else tr("Bars")) + (": " + ", ".join(names) if names else "")
    return raw


def _text(c, sheet, book, col, raw, uid, people, files):
    """How an input reads in the history (for viewer uid)."""
    from .core import sh_options, sh_to_display
    raw = raw or ""
    if not raw or col is None:
        return raw
    if raw.startswith("="):
        return sh_to_display(c, sheet, raw, book, uid)
    k = col["kind"]
    if k == "select":
        o = next((o for o in sh_options(col["options"]) if o.get("id") == raw), None)
        return o.get("label", "") if o else raw
    if k == "checkbox" and shk_bool(raw) in (True, False):
        return tr("Yes") if shk_bool(raw) else tr("No")
    if k == "person" and raw.strip().isdigit():
        return people.get(int(raw)) or tr("Unknown")
    if k == "file":
        m = SHK_FILE_RE.fullmatch(raw.strip())
        if m:
            return files.get(int(m.group(1))) or tr("File missing")
    return raw


def shh_entries(c, sheet, rows, uid):
    from .core import ShBook
    book = ShBook(c, sheet)
    cols = {r["id"]: r for r in c.execute("SELECT * FROM sheet_columns WHERE sheet_id=?", (sheet["id"],))}
    people = shk_people(c, sheet)
    files = {r[0]: r[1] for r in c.execute("SELECT id, name FROM sheet_files WHERE sheet_id=?", (sheet["id"],))}
    names = user_names(c, {r["user_id"] for r in rows})
    out = []
    for r in rows:
        col = cols.get(r["col_id"])
        x = book.cells.get(r["cell_id"])
        if r["what"] in SHH_META:  # 2.564.0 (#4701): a change of the table (title, sheet name, chart) or of a cell's name / freeze
            out.append({"id": r["id"], "at": r["at"], "user_id": r["user_id"], "user_name": names.get(r["user_id"], "") or tr("Unknown"),
                        "agent": bool(r["agent_id"]), "cell_id": r["cell_id"], "row_id": r["row_id"], "col_id": r["col_id"],
                        "addr": book.addr(x) if x and book.live(x) else None, "what": r["what"], "col_title": tr(SHH_META[r["what"]]),
                        "old": _meta_text(c, r["what"], r["old_raw"], cols), "new": _meta_text(c, r["what"], r["new_raw"], cols)})
            continue
        out.append({"id": r["id"], "at": r["at"], "user_id": r["user_id"], "user_name": names.get(r["user_id"], "") or tr("Unknown"),
                    "agent": bool(r["agent_id"]), "cell_id": r["cell_id"], "row_id": r["row_id"], "col_id": r["col_id"],
                    "addr": book.addr(x) if book.live(x) else None, "col_title": col["title"] if col else "",
                    "old": _text(c, sheet, book, col, r["old_raw"], uid, people, files),
                    "new": _text(c, sheet, book, col, r["new_raw"], uid, people, files)})
    return out


@app.get("/api/sheets/<int:sid>/history")
def shh_sheet(sid):
    """The table's latest cell changes (newest first; ?limit=1..200, default 100) -> {entries}."""
    from .core import sh_need
    c = db()
    r = sh_need(c, sid)
    try:
        n = max(1, min(SHH_KEEP, int(request.args.get("limit") or 100)))
    except ValueError:
        n = 100
    rows = c.execute("SELECT * FROM sheet_hist WHERE sheet_id=? ORDER BY id DESC LIMIT ?", (sid, n)).fetchall()
    out = shh_entries(c, r, rows, me()) + shh_core_entries(c, r, me(), n)  # 2.571.0 (#4766): + the table's own fields
    out.sort(key=lambda x: str(x["at"] or ""), reverse=True)
    return jsonify(entries=out[:n])


@app.get("/api/sheets/<int:sid>/cells/<int:cid>/history")
def shh_cell(sid, cid):
    """The latest changes of one cell (newest first) -> {entries}."""
    from .core import sh_need, sh_need_cell
    c = db()
    r = sh_need(c, sid)
    sh_need_cell(c, r, cid)
    rows = c.execute("SELECT * FROM sheet_hist WHERE sheet_id=? AND cell_id=? ORDER BY id DESC LIMIT ?", (sid, cid, SHH_CELL_MAX)).fetchall()
    return jsonify(entries=shh_entries(c, r, rows, me()))
