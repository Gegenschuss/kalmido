"""2.631.0 (#4620): ranges of formulas when rows or columns are moved (dragged in the grid, "Move up / down / left / right").

A formula stores its references by cell id ({c:<id>}, sheets/core.py sh_to_internal), so a single reference follows its cell
wherever the row / column goes. A range is stored as its two corner cells ({c:a}:{c:b}, {x:a}:{x:b} from another sheet of
the table) and means every cell between them at the time it is computed. Moving a corner row / column on its own would make
that rectangle silently take in rows / columns that never were in it (SUM(A1:A3), row 1 moved to row 10: A2:A10) or keep
out ones that were. sho_ranges keeps a range's members instead, like a spreadsheet does when cut cells are inserted
elsewhere: the rows / columns of the range that did not move stay its members and its ends move to the first and last of
them; a moved block dropped between them belongs to it, members dragged to right beside its edge stay in it (a row dragged
from the top of summed rows to just above their total), ones taken further away do not any more; a range that moved as a
whole (all its members in the block) simply follows its corners.

Only for a move with its block named (moved = the ids that were dragged): a sorting or any other new order keeps the stored
corners as before (sheets.web rows/order without "moved"). The answer names the changed formulas with their text before and
after, so the Undo of a move (the old order, without "moved") can put them back exactly (PUT /cells, prev = after).
"""
from ..core.errors import BadInput
from ..core.i18n import tr
from .core import ShBook, sh_reload, sh_to_display, sh_to_internal
from .formula import ShErr, sh_tokens

SHO_MOVED_MAX = 5000  # ids in "moved" (rows of a sheet are fewer, SH_ROWS_MAX)


def sho_moved(b, live):
    """The block of a move from the body (b["moved"]): a set of live ids, or None without one. BadInput if malformed."""
    m = b.get("moved")
    if m is None:
        return None
    lset = set(live)
    if not isinstance(m, list) or not m or len(m) > SHO_MOVED_MAX or any(isinstance(x, bool) or x not in lset for x in m):
        raise BadInput(tr("Invalid value: {0}", "moved"))
    return set(m)


def _span(old_idx, new_idx, old, moved, a, b):
    """The new (first, last) index along the moved dimension of a range whose corners lie on a / b (row or column ids), or
    None when nothing changes for it."""
    if a not in old_idx or b not in old_idx:
        return None
    lo, hi = sorted((old_idx[a], old_idx[b]))
    stay = [x for x in old[lo:hi + 1] if x not in moved]
    if not stay:
        return None  # the whole range moved: its corners follow
    ni = [new_idx[x] for x in stay]
    span = (min(ni), max(ni))
    # members of the range that were dragged and land right at its edge stay in it (a row dragged below the last row of the
    # summed rows, above the total line, is still summed); further away they leave it
    ki = sorted(new_idx[x] for x in old[lo:hi + 1] if x in moved)
    if ki and ki == list(range(ki[0], ki[0] + len(ki))):
        if ki[0] == span[1] + 1:
            span = (span[0], ki[-1])
        elif ki[-1] == span[0] - 1:
            span = (ki[0], span[1])
    return None if span == tuple(sorted((new_idx[a], new_idx[b]))) else span


def sho_plan(c, sheet_row, kind, old, new, moved, uid):
    """Before rows (kind "row") / columns ("col") of sheet_row go from order old to new (lists of the live ids) by moving the
    block moved: the formulas whose ranges reaching into this sheet change so that the ranges keep their members (module
    text) -> [{id, sheet_id, row_id, col_id, raw, new, before}] (raw / new stored, before = the writer's text in the old
    order). Writes nothing but the empty corner cells a new end may need (ShBook.ensure). Run it before the new order is
    stored, sho_apply after."""
    if not moved or old == new:
        return []
    if [x for x in old if x not in moved] != [x for x in new if x not in moved]:
        return []  # not one block moved (a sorting): the corners stay as stored
    sid = sheet_row["id"]
    old_idx, new_idx = {x: i for i, x in enumerate(old)}, {x: i for i, x in enumerate(new)}
    book = ShBook(c, sheet_row)  # still the old order
    if [r["id"] for r in (book.rows if kind == "row" else book.cols)] != old:
        return []  # the stored order is not the one the move started from (should not happen under the sheet's lock)
    line = (lambda x: x["row_id"]) if kind == "row" else (lambda x: x["col_id"])
    bid = c.execute("SELECT COALESCE(book_id, id) FROM sheets WHERE id=?", (sid,)).fetchone()[0]
    sheets = {r["id"]: r for r in c.execute("SELECT * FROM sheets WHERE (id=? OR book_id=?) AND deleted_at IS NULL", (bid, bid))}
    sheets[sid] = sheet_row
    books, out = {sid: book}, []
    q = "SELECT id, sheet_id, row_id, col_id, raw FROM sheet_cells WHERE sheet_id IN (%s) AND raw ILIKE ? ORDER BY id" % ",".join("?" * len(sheets))
    for x in c.execute(q, [*sheets, "=%:%"]).fetchall():
        raw, typ = x["raw"], "c" if x["sheet_id"] == sid else "x"
        if "{%s:" % typ not in raw:
            continue
        try:
            toks = sh_tokens(raw[1:])
        except ShErr:
            continue
        body, parts, last = raw[1:], [], 0
        for i in range(len(toks) - 2):
            t1, t2, t3 = toks[i], toks[i + 1], toks[i + 2]
            if t2[0] != ":" or t1[0] != "idref" or t3[0] != "idref" or t1[1][0] != typ or t3[1][0] != typ or t1[2] < last:
                continue
            ca, cb = book.cells.get(t1[1][1]), book.cells.get(t3[1][1])
            if not book.live(ca) or not book.live(cb):
                continue  # not a range of this sheet (or a corner in the trash: it keeps its error as before)
            span = _span(old_idx, new_idx, old, moved, line(ca), line(cb))
            if span is None:
                continue
            ends = span if old_idx[line(ca)] <= old_idx[line(cb)] else (span[1], span[0])  # the corner that came first stays first
            ids = []
            for cell, at in ((ca, ends[0]), (cb, ends[1])):
                rid, cid = (new[at], cell["col_id"]) if kind == "row" else (cell["row_id"], new[at])
                ids.append(book.ensure(rid, cid, uid)["id"])
            parts += [body[last:t1[2]], "{%s:%d}:{%s:%d}" % (typ, ids[0], typ, ids[1])]
            last = t3[3]
        if not parts:
            continue
        new_raw = "=" + "".join(parts) + body[last:]
        if new_raw == raw:
            continue
        sb = books.get(x["sheet_id"]) or books.setdefault(x["sheet_id"], ShBook(c, sheets[x["sheet_id"]]))
        out.append({"id": x["id"], "sheet_id": x["sheet_id"], "row_id": x["row_id"], "col_id": x["col_id"], "raw": raw,
                    "new": new_raw, "before": sh_to_display(c, sb.sheet, raw, sb, uid)})
    return out


def sho_apply(c, plan, uid):
    """Stores the formulas of sho_plan (after the new order is stored) -> [{sheet_id, row_id, col_id, raw: before, now: after}]
    in the writer's form: the Undo of the move puts raw back with prev = now (PUT /cells)."""
    books, res = {}, []
    for f in plan:
        c.execute("UPDATE sheet_cells SET raw=? WHERE id=? AND raw=?", (f["new"], f["id"], f["raw"]))
    for f in plan:
        sb = books.get(f["sheet_id"]) or books.setdefault(f["sheet_id"], ShBook(c, sh_reload(c, f["sheet_id"])))
        res.append({"sheet_id": f["sheet_id"], "row_id": f["row_id"], "col_id": f["col_id"], "raw": f["before"],
                    "now": sh_to_display(c, sb.sheet, f["new"], sb, uid)})
    return res


def sho_restore_plan(c, sheet_row, items, uid):
    """The Undo of a move: items = the "formulas" its answer named ([{sheet_id, row_id, col_id, raw, now}]). Before the old
    order comes back: the cells whose text is still `now` (changed since: left as they are) -> [(cell id, sheet row, raw)];
    raw (written in the old order's addresses) is stored by sho_restore_apply once that order is back. BadInput if malformed."""
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > SHO_MOVED_MAX:
        raise BadInput(tr("Invalid value: {0}", "formulas"))
    sid = sheet_row["id"]
    bid = c.execute("SELECT COALESCE(book_id, id) FROM sheets WHERE id=?", (sid,)).fetchone()[0]
    sheets = {r["id"]: r for r in c.execute("SELECT * FROM sheets WHERE (id=? OR book_id=?) AND deleted_at IS NULL", (bid, bid))}
    books, out = {}, []
    for f in items:
        if not isinstance(f, dict) or not all(isinstance(f.get(k), int) and not isinstance(f.get(k), bool) for k in ("sheet_id", "row_id", "col_id")) \
                or not isinstance(f.get("raw"), str) or not isinstance(f.get("now"), str) or f["sheet_id"] not in sheets:
            raise BadInput(tr("Invalid value: {0}", "formulas"))
        sb = books.get(f["sheet_id"]) or books.setdefault(f["sheet_id"], ShBook(c, sheets[f["sheet_id"]]))
        x = sb.at.get((f["row_id"], f["col_id"]))
        if not x or not sb.live(x) or sh_to_display(c, sb.sheet, x["raw"], sb, uid) != f["now"]:
            continue
        out.append((x["id"], sheets[f["sheet_id"]], f["raw"], x["raw"]))
    return out


def sho_restore_apply(c, plan, uid):
    """Stores the texts of sho_restore_plan in the order that is back (sh_to_internal: their addresses become ids again)."""
    books = {}
    for cid, srow, raw, was in plan:
        sb = books.get(srow["id"]) or books.setdefault(srow["id"], ShBook(c, sh_reload(c, srow["id"])))
        c.execute("UPDATE sheet_cells SET raw=? WHERE id=? AND raw=?", (sh_to_internal(c, srow, raw, uid, book=sb, keep=was), cid, was))
