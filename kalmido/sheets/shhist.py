"""2.124.0 B (#2112): the change history of a table's cells -- every input a person (or an agent) stored: who, when, before /
after. Written by sheets/core.py _store (one row per changed cell), kept short: the newest SHH_KEEP rows of a sheet within
SHH_DAYS (older ones go on the next write), at most SHH_KEEP rows of one call (an import logs nothing: io.py sets shh_off).
Its own table (sheet_hist), so the agents' trail (sheet_changes, sh_undo_batch, the "Changes by agents" panel) stays as it
is. Inputs are stored as the cells keep them (sheet_cells.raw is not sealed at rest either) and shown for the viewer:
formulas with the names they may see, options / people / files by their names. Read = the right to read the table; the
rows hang on the sheet, so they move with it (private <-> organisation) and go with it.
"""
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import db, iso_ms, now_utc
from ..core.i18n import tr
from ..accounts.session import me
from ..collab.comments import user_names

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


def _text(c, sheet, book, col, raw, uid, people, files):
    """How an input reads in the history (for viewer uid)."""
    from .core import sh_options, sh_to_display
    from .shkinds import SHK_FILE_RE, shk_bool
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
    from .shkinds import shk_people
    book = ShBook(c, sheet)
    cols = {r["id"]: r for r in c.execute("SELECT * FROM sheet_columns WHERE sheet_id=?", (sheet["id"],))}
    people = shk_people(c, sheet)
    files = {r[0]: r[1] for r in c.execute("SELECT id, name FROM sheet_files WHERE sheet_id=?", (sheet["id"],))}
    names = user_names(c, {r["user_id"] for r in rows})
    out = []
    for r in rows:
        col = cols.get(r["col_id"])
        x = book.cells.get(r["cell_id"])
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
    return jsonify(entries=shh_entries(c, r, rows, me()))


@app.get("/api/sheets/<int:sid>/cells/<int:cid>/history")
def shh_cell(sid, cid):
    """The latest changes of one cell (newest first) -> {entries}."""
    from .core import sh_need, sh_need_cell
    c = db()
    r = sh_need(c, sid)
    sh_need_cell(c, r, cid)
    rows = c.execute("SELECT * FROM sheet_hist WHERE sheet_id=? AND cell_id=? ORDER BY id DESC LIMIT ?", (sid, cid, SHH_CELL_MAX)).fetchall()
    return jsonify(entries=shh_entries(c, r, rows, me()))
