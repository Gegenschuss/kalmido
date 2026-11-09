"""2.778.0 (#5253): undo across devices, stage 5 -- a person's table writes as pointer steps (core/undodiff.py, mode "ref").

Every write of a person to a table's cells, rows or columns (PUT /api/sheets/<id>/cells, POST .../rows, POST .../columns)
gets a batch of its own, like an agent's call: the changes land in sheet_changes (old / new input, the rows and columns
added) and the person's step (kind 'sheet', ref = the sheet) points to that batch ({b: batch, rev: the table's rev after
it}). No second copy: taking it back is sheets/core.py sh_undo_batch (a cell changed since keeps its newer input and is
named, the rest goes back; a row / column someone typed into since stays), forward again shu_redo (the same, the other way).
The person's batch carries no agent mark (sheet_cells.agent_batch stays empty, the agents' panel and their batch-undo
routes never list or take it). The rights are the ones of now: write access to the table (sh_need write).
Recorded right before the commit (core/pg.py Conn.pre_commit), only when the batch changed something.
2.800.0 (#5409): the other changes of a person to a table are steps of the same batch too (sheets/shustep.py): deleting rows
and columns, a column's settings (title, type, options, width, ...), moving / sorting rows and columns, the chart, the colour
rules, a cell's name and frozen value, the sheets of the bar (add, rename, move, delete); the table's own title and project
go through the core's write layer (sheets/shhist.py shh_meta_write) and are a step of their own there."""
import secrets

from flask import g

from ..core.db import iso_ms, now_utc
from ..core.access import Denied, need_feat
from ..core.i18n import tr
from ..core.pg import write_lock
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_LABEL, UG_TRACKED
from ..core.undoweb import UG_GONE, UG_KEPT, UG_KEPT_REDO
from ..core.writes import UNDO_NOTHING
from .core import SH_STEP_KINDS, ShBook, sh_change, sh_need, sh_reload, sh_touch, sh_undo_batch
from .formula import sh_col_letter
from .shfmt import shfm_undo
from .shkinds import _shk_file_swap

SHU_KIND = "sheet"
SHU_AREA = "sheets"


def shu_batch(c, sheet_row):
    """The batch of a person's write to this sheet in this request (one per sheet and request), or None (an agent, no
    person, an undo running: the agents' own batches stay as they are)."""
    uid = undo_person(c)
    if uid is None:
        return None
    m = g.get("shu_batches")
    if m is None or m.get("uid") != uid:
        m = g.shu_batches = {"uid": uid, "b": {}}
    sid = int(sheet_row["id"])
    if sid not in m["b"]:
        m["b"][sid] = "p" + secrets.token_hex(8)
    c.pre_commit["sheets.undo"] = shu_flush
    return m["b"][sid]


def shu_flush(c):
    """The request's batches that changed something -> one pointer part each (pre-commit; a failure costs only the step)."""
    m = g.pop("shu_batches", None)
    if not m or not m["b"]:
        return
    try:
        with c.savepoint():
            for sid, batch in m["b"].items():
                if not c.execute("SELECT 1 FROM sheet_changes WHERE sheet_id=? AND batch=? AND agent_id IS NULL AND substr(batch, 1, 1) = 'p' LIMIT 1", (sid, batch)).fetchone():
                    continue
                r = sh_reload(c, sid)
                if r is None:
                    continue
                ug_diff_add(c, m["uid"], SHU_KIND, sid, r["org_id"] or None, SHU_AREA, (UG_LABEL, [r["title"] or [N_TABLE]]),
                            {"b": batch, "rev": r["rev"]}, mode="ref")
    except Exception as e:  # noqa: BLE001 -- the step is lost, the change itself commits
        print("sheets undo step not recorded:", type(e).__name__, str(e)[:200], flush=True)


N_TABLE = "Table"


def shu_rec(c, sheet_row, kind, old=None, new=None, cell_id=None, row_id=None, col_id=None):
    """2.800.0 (#5409): a person's structural change of sheet_row into the request's batch (sheets/shustep.py takes it back);
    nothing for an agent / no person / an undo running (shu_batch None)."""
    batch = shu_batch(c, sheet_row)
    if batch:
        sh_change(c, int(sheet_row["id"]), batch, None, kind, cell_id=cell_id, row_id=row_id, col_id=col_id, old=old, new=new)


def _names(c, sheet_row, stayed, kept):
    """What stayed, as the table shows it: cell addresses (B4), rows / columns by number / letter."""
    book = ShBook(c, sh_reload(c, sheet_row["id"]))
    out = []
    for ch in stayed:
        if ch.get("label"):  # 2.800.0 (#5409): a structural change names itself (sheets/shustep.py)
            out.append(ch["label"])
            continue
        x = book.at.get((ch["row_id"], ch["col_id"]))
        if x is not None and book.live(x):
            out.append(book.addr(x))
        elif ch["row_id"] in book.row_idx:
            out.append(tr("Row {0}", book.row_idx[ch["row_id"]] + 1))
    for rid in (kept or {}).get("rows", ()):
        if rid in book.row_idx:
            out.append(tr("Row {0}", book.row_idx[rid] + 1))
    for cid in (kept or {}).get("cols", ()):
        if cid in book.col_idx:
            out.append(tr("Column {0}", sh_col_letter(book.col_idx[cid])))
    if (kept or {}).get("sheet"):
        out.append(tr(N_TABLE))
    return sorted(set(out), key=out.index)


def shu_redo(c, sheet_row, batch, uid, stayed):
    """The undone changes of a person's batch forward again (oldest first): a cell only while it still holds the input the
    undo left, a row / column / format the same way. -> number of changes redone."""
    rows = c.execute("SELECT * FROM sheet_changes WHERE sheet_id=? AND batch=? AND agent_id IS NULL AND substr(batch, 1, 1) = 'p' AND undone_at IS NOT NULL ORDER BY id",
                     (sheet_row["id"], batch)).fetchall()
    ts, n, book = iso_ms(now_utc()), 0, None
    for r in rows:
        if r["kind"] == "cell":
            x = c.execute("SELECT x.raw, x.row_id, x.col_id, k.kind FROM sheet_cells x JOIN sheet_columns k ON k.id=x.col_id "
                          "WHERE x.id=?", (r["cell_id"],)).fetchone()
            if not x or x["raw"] != (r["old_raw"] or ""):
                stayed.append(dict(r))
                continue
            if x["kind"] == "file":
                book = book or ShBook(c, sheet_row)
                _shk_file_swap(c, book, x["col_id"], x["row_id"], (r["new_raw"] or "").strip())
                y = book.at.get((x["row_id"], x["col_id"]))
                if y is not None:
                    y["raw"] = r["new_raw"] or ""
            c.execute("UPDATE sheet_cells SET raw=?, frozen=0, frozen_value=NULL, updated_by=?, updated_at=? WHERE id=?",
                      (r["new_raw"] or "", uid, ts, r["cell_id"]))
        elif r["kind"] == "fmt":
            if not shfm_undo(c, {**dict(r), "old_raw": r["new_raw"], "new_raw": r["old_raw"]}, uid):
                stayed.append(dict(r))
                continue
        elif r["kind"] in SH_STEP_KINDS:  # 2.800.0 (#5409): a structural change (sheets/shustep.py)
            went, left = SH_STEP_KINDS[r["kind"]](c, sheet_row, r, uid, ts, True)
            if left:
                stayed.append({**dict(r), "label": left})
            if not went:
                continue
        elif r["kind"] in ("row", "col"):
            # review r2778 F1: only a row / column this undo put into the trash comes back (deleted_at = the undo's time);
            # one kept at the undo (someone typed into it) is live already, one deleted since by someone else stays deleted
            back = (c.execute("UPDATE sheet_rows SET deleted_at=NULL WHERE id=? AND deleted_at=?", (r["row_id"], r["undone_at"]))
                    if r["kind"] == "row" else
                    c.execute("UPDATE sheet_columns SET deleted_at=NULL WHERE id=? AND deleted_at=?", (r["col_id"], r["undone_at"])))
            gone = (c.execute("SELECT 1 FROM sheet_rows WHERE id=? AND deleted_at IS NOT NULL", (r["row_id"],))
                    if r["kind"] == "row" else
                    c.execute("SELECT 1 FROM sheet_columns WHERE id=? AND deleted_at IS NOT NULL", (r["col_id"],))).fetchone()
            if not back.rowcount and gone:
                stayed.append(dict(r))
                continue
        else:
            continue  # 'create' is no step of a person here
        c.execute("UPDATE sheet_changes SET undone_at=NULL WHERE id=?", (r["id"],))
        n += 1
    if n:
        sh_touch(c, sheet_row["id"], uid)
    return n


def shu_run(c, uid, sid, data, redo):
    """core/undodiff.py run: a person's table step back (redo: forward). Rights of now (write access); a cell changed since
    stays and is named (UG_KEPT), the rest goes; nothing went at all = 409 naming what stayed."""
    need_feat("sheets")
    r = sh_need(c, int(sid), write=True)
    write_lock(c, "sheet:" + str(int(sid)))  # the lock of the table's own writes (sh_set_cells)
    batch = str(data.get("b") or "")
    if not batch or not c.execute("SELECT 1 FROM sheet_changes WHERE sheet_id=? AND batch=? AND agent_id IS NULL AND substr(batch, 1, 1) = 'p' LIMIT 1",
                                  (int(sid), batch)).fetchone():
        raise Denied(404, tr(UG_GONE))  # the changes' trail is gone (retention) or never was
    stayed, kept = [], {}
    n = shu_redo(c, r, batch, uid, stayed) if redo else sh_undo_batch(c, r, batch, uid, kept=kept, stayed=stayed)
    left = _names(c, r, stayed, kept)
    if not n:  # nothing went (a row / column kept alone is no step back either): the savepoint drops the marks
        if left:
            raise Denied(409, tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(left)))
        raise Denied(409, tr(UNDO_NOTHING))
    data = {**data, "rev": sh_reload(c, int(sid))["rev"]}
    return data, left


undo_diff_reg(SHU_KIND, shu_run, SHU_AREA)
UG_TRACKED.setdefault(SHU_KIND, "sheets")  # the watchdog drops the steps of a table deleted for good (ug_drop_orphans)
