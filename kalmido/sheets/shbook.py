"""2.124.0 E (#2116): several sheets in one table (a "book", like the sheets of a spreadsheet file).

A table is its first sheet (a row of `sheets`, book_id NULL). A further sheet is a row of its own with book_id = the first
sheet's id, tab_pos = its place in the sheet bar and tab_name = its name there (its title carries the same name, so 2.123,
which never reads book_id, lists it as a table of its own: nothing is lost). The first sheet carries the table: its title,
space, list, shares (sheets/shshare.py), the trash and a move to another workspace (sheets/shmove.py) count for every sheet.
Rights: sh_may / sh_need (sheets/core.py) look at the first sheet for a further one (who reads the table reads all its
sheets, who may change it changes all of them; a further sheet of a table in the trash is gone with it). The space fields
(org_id, owner_id, list_id) are copied onto every sheet (the currency, Kalmido variables, files and the nightly boundary
check read them there) and kept equal by shb_sync; accounts/tenancy.py sheet_book counts any difference.

Formulas reach into another sheet of the same table as in .xlsx: Blatt2!A1, 'Mein Blatt'!A1:B5 (stored as {x:<cell id>}, so a
renamed sheet keeps its formulas). The other sheet is evaluated for the same viewer when a formula reads it (every read
evaluates afresh: a change in one sheet shows in the other at its next load; sh_touch counts the whole table's rev up).
Sheets reading each other in a circle get "Circular reference" after SHB_DEPTH sheets.
"""
import re

from flask import jsonify

from ..core.config import app
from ..core.access import Denied, need_feat
from ..core.db import body, db, iso_ms, now_utc
from ..core.i18n import tr
from ..core.pg import insert_id
from ..accounts.session import me
from ..core.errors import BadInput
from .formula import ShErr

SHB_TABS_MAX = 30          # sheets of one table
SHB_NAME_MAX = 100
SHB_DEPTH = 4              # sheets reading each other: deeper = "Circular reference"
SHB_SUBS = 40              # other sheets evaluated for one evaluation (else "Too much to compute"); review: was 60, budgets now shared
SHB_BARE = re.compile(r"[^\W\d][\w.]{0,99}")
_PAIR = re.compile(r"(?<![\w.'])(?P<n>'(?:[^']|'')+'|[^\W\d][\w.]*)!(?P<a>\$?[A-Z]{1,3}\$?\d+):(?P=n)!")


def shb_bid(r):
    """The id of the table (its first sheet) sheet row r belongs to."""
    try:
        b = r["book_id"]
    except (KeyError, IndexError):
        b = None
    return b or r["id"]


def shb_rights_row(c, r):
    """sh_may's hook: the row whose rights count for r -- the first sheet for a further one (None when it is gone)."""
    try:
        b = r["book_id"]
    except (KeyError, IndexError):
        return r
    if not b:
        return r
    return c.execute("SELECT * FROM sheets WHERE id=? AND book_id IS NULL", (b,)).fetchone()


def shb_deleted(c, r):
    """sh_need's hook: is sheet r in the trash -- itself, or (a further sheet) its table?"""
    if r["deleted_at"]:
        return True
    try:
        b = r["book_id"]
    except (KeyError, IndexError):
        return False
    if not b:
        return False
    a = c.execute("SELECT deleted_at FROM sheets WHERE id=?", (b,)).fetchone()
    return not a or bool(a[0])


def shb_rows(c, bid, deleted=False):
    """The live sheets of table bid in the order of the sheet bar (deleted: also those in the trash)."""
    q = "SELECT * FROM sheets WHERE (id=? AND book_id IS NULL OR book_id=?)" + ("" if deleted else " AND deleted_at IS NULL")
    return c.execute(q + " ORDER BY tab_pos, id", (bid, bid)).fetchall()


def shb_label(r):
    """The sheet's name in the bar: its tab_name; a further sheet without one its title, the first one "Sheet 1"."""
    return r["tab_name"] or (r["title"] if r["book_id"] else "") or tr("Sheet {0}", 1)


def shb_tab(r, i):
    return {"id": r["id"], "name": shb_label(r), "pos": i, "first": not r["book_id"]}


def shb_dict(c, r):
    """sh_dict's hook: the table this sheet belongs to and its sheets {id, name, pos, first}."""
    bid = shb_bid(r)
    rows = shb_rows(c, bid)
    first = next((x for x in rows if x["id"] == bid), None)
    return {"book_id": bid, "book_title": first["title"] if first else r["title"], "tab_name": shb_label(r),
            "tabs": [shb_tab(x, i) for i, x in enumerate(rows)]}


def shb_only_books(c, rows):
    """sh_index's hook: only tables (first sheets), never a further sheet on its own."""
    return [r for r in rows if not r["book_id"]]


def shb_counts(c, rows, out):
    """sh_brief's hook: + sheets = the number of live sheets of each table."""
    ids = [int(r["id"]) for r in rows]
    n = {}
    if ids:
        for x in c.execute(f"SELECT book_id, COUNT(*) FROM sheets WHERE deleted_at IS NULL AND book_id IN ({','.join(map(str, ids))}) "
                           "GROUP BY book_id").fetchall():
            n[x[0]] = x[1]
    for d in out:
        d["sheets"] = 1 + n.get(d["id"], 0)
    return out


def shb_touch(c, sid, ts, uid):
    """sh_touch's hook: the other sheets of the table count up too (a formula there may read the changed sheet)."""
    c.execute("UPDATE sheets SET rev=rev+1, updated_at=?, updated_by=? WHERE id<>? AND book_id IS NOT NULL AND book_id="
              "(SELECT COALESCE(book_id, id) FROM sheets WHERE id=?)", (ts, uid, sid, sid))
    c.execute("UPDATE sheets SET rev=rev+1, updated_at=?, updated_by=? WHERE id=(SELECT book_id FROM sheets WHERE id=?)", (ts, uid, sid))


def shb_sync(c, bid):
    """The space fields of the first sheet onto every further sheet (after a list change or a move)."""
    c.execute("UPDATE sheets SET org_id=(SELECT org_id FROM sheets WHERE id=?), owner_id=(SELECT owner_id FROM sheets WHERE id=?), "
              "list_id=(SELECT list_id FROM sheets WHERE id=?) WHERE book_id=?", (bid, bid, bid, bid))


def shb_patch(c, r, f):
    """The PATCH hook (web and API v1): the list belongs to the whole table (set it on the first sheet); a further sheet's
    title is its name in the sheet bar."""
    if not r["book_id"]:
        return f
    if "list_id" in f:
        raise Denied(409, tr("Change this on the first sheet of the table"))
    if "title" in f:
        f["tab_name"] = f["title"][:SHB_NAME_MAX]
    return f


def shb_whole(r):
    """A route that works on the whole table (shares): a further sheet -> 409."""
    if r["book_id"]:
        raise Denied(409, tr("Change this on the first sheet of the table"))


# ---------------------------------------------------------------- formulas across sheets
def _tab_named(c, sheet_row, name, cache):
    key = ("n", name.casefold())
    if key not in cache:
        cache[key] = next((x for x in shb_rows(c, shb_bid(sheet_row)) if shb_label(x).casefold() == name.casefold()), None)
    return cache[key]


def _book_of_tab(c, tab, cache):
    from .core import ShBook
    key = ("b", tab["id"])
    if key not in cache:
        cache[key] = ShBook(c, tab)
    return cache[key]


def shb_internal(c, sheet_row, book, val, uid):
    """sh_to_internal's hook: the stored form of Name!A1 / Name!A1:B5 -- {x:<id>}[:{x:<id>}] for another sheet of the table,
    {c:<id>} for this one; BadInput when the sheet or cell does not exist."""
    name, p1, p2 = val
    cache = book.__dict__.setdefault("shb_cache", {})
    tab = _tab_named(c, sheet_row, name, cache)
    if tab is None:
        raise BadInput(tr("There is no sheet {0}", name))
    tb = book if tab["id"] == sheet_row["id"] else _book_of_tab(c, tab, cache)
    typ = "c" if tb is book else "x"
    out = []
    for p in ((p1, p2) if p2 else (p1,)):
        pos = tb.pos_of(*p)
        if not pos:
            raise BadInput(tr("There is no cell {0}", f"{name}!{p[0]}{p[1]}"))
        out.append("{%s:%d}" % (typ, tb.ensure(pos[0], pos[1], uid)["id"]))
    return ":".join(out)


def shb_check(c, sheet_row, xid, cache=None):
    """The sheet row holding cell xid when it is a live sheet of sheet_row's table (else None)."""
    r = c.execute("SELECT s.* FROM sheet_cells x JOIN sheets s ON s.id=x.sheet_id WHERE x.id=?", (xid,)).fetchone()
    if not r or r["deleted_at"] or shb_bid(r) != shb_bid(sheet_row):
        return None
    return r


def shb_display(c, sheet_row, xid, cache):
    """sh_to_display's hook: Name!B3 of cell xid of another sheet (None when gone: the bare id stays)."""
    key = ("d", xid)
    if key not in cache:
        cache[key] = None
        tab = shb_check(c, sheet_row, xid)
        if tab is not None:
            tb = _book_of_tab(c, tab, cache)
            x = tb.cells.get(xid)
            if tb.live(x):
                cache[key] = shb_quote(shb_label(tab)) + "!" + tb.addr(x)
    return cache[key]


def shb_pairs(text):
    """Name!A1:Name!B5 -> Name!A1:B5 (how a range into another sheet is written)."""
    return _PAIR.sub(lambda m: f"{m.group('n')}!{m.group('a')}:", text) if "!" in text else text


def shb_quote(name):
    return name if SHB_BARE.fullmatch(name) else "'" + name.replace("'", "''") + "'"


def _sub(ev, cid):
    """The evaluator of the sheet of ev's table that holds cell cid (evaluated once per viewer and chain of sheets)."""
    ctx = getattr(ev, "shb", None)
    if ctx is None:
        ctx = ev.shb = {"of": {}, "done": {}, "n": 0}
        ev.shb_stack = (ev.book.sheet["id"],)
    stack = ev.shb_stack
    of = ctx["of"]
    if cid not in of:
        of[cid] = shb_check(ev.c, ev.book.sheet, cid)
    tab = of[cid]
    if tab is None:
        raise ShErr("ref")
    if tab["id"] == ev.book.sheet["id"]:
        return ev
    if tab["id"] in stack and len(stack) >= SHB_DEPTH:
        raise ShErr("cycle")
    key = (tab["id"], stack)
    sub = ctx["done"].get(key)
    if sub is None:
        ctx["n"] += 1
        if ctx["n"] > SHB_SUBS:
            raise ShErr("type", "big")
        from .core import ShBook, ShEvaluator
        books = ctx.setdefault("books", {})
        if tab["id"] not in books:
            books[tab["id"]] = ShBook(ev.c, tab)
        sub = ShEvaluator(ev.c, books[tab["id"]], ev.uid)
        sub.shb, sub.shb_stack = ctx, stack + (tab["id"],)
        # 2.124.0 review: one text / function budget for the whole chain (a sheet does not get a fresh one per sheet it reads)
        from .shfuncs import SHF_WORK_BUDGET
        from .core import SH_RANGE_BUDGET  # 2.148.1 D (#2485): the range budget is shared along the chain, too
        sub.text_left, sub.shf_work = ev.text_left, getattr(ev, "shf_work", SHF_WORK_BUDGET)
        sub.rng_work = getattr(ev, "rng_work", SH_RANGE_BUDGET)
        try:
            sub.run()
        finally:
            ev.text_left, ev.shf_work = sub.text_left, getattr(sub, "shf_work", SHF_WORK_BUDGET)
            ev.rng_work = getattr(sub, "rng_work", SH_RANGE_BUDGET)
        ctx["done"][key] = sub
    return sub


def shb_value(ev, cid):
    """The value of cell cid of another sheet (raises ShErr like a cell of this one)."""
    return _sub(ev, cid).value_of(cid)


def shb_range(ev, a, b):
    from .core import _range_cells
    sub = _sub(ev, a)
    if _sub(ev, b) is not sub:
        raise ShErr("ref")
    book = sub.book
    if not book.live(book.cells.get(a)) or not book.live(book.cells.get(b)):
        raise ShErr("ref")
    return [sub.value_of(x["id"]) for x in _range_cells(book, a, b)]


def shb_grid(sv, node):
    """shf_grid's hook (SUMMEWENN, SVERWEIS ...): the grid of a range / cell of another sheet."""
    from .shfuncs import _Grid, _book_of, shf_spend
    ev = _book_of(sv)
    if ev is None:
        raise ShErr("ref")
    a, b = (node[1], node[1]) if node[0] == "xcell" else (node[1], node[2])
    sub = _sub(ev, a)
    if _sub(ev, b) is not sub:
        raise ShErr("ref")
    book = sub.book
    xa, xb = book.cells.get(a), book.cells.get(b)
    if not book.live(xa) or not book.live(xb):
        raise ShErr("ref")
    r1, r2 = sorted((book.row_idx[xa["row_id"]], book.row_idx[xb["row_id"]]))
    c1, c2 = sorted((book.col_idx[xa["col_id"]], book.col_idx[xb["col_id"]]))
    ids = {(book.row_idx[x["row_id"]] - r1, book.col_idx[x["col_id"]] - c1): x["id"] for x in book.rect(r1, r2, c1, c2)}
    shf_spend(sv, len(ids) + 1)
    g = _Grid(r2 - r1 + 1, c2 - c1 + 1, ids, sub.value_of)
    g.shb = True  # its values come from the other sheet's evaluator (shfuncs.py _index)
    return g


# ---------------------------------------------------------------- sheets of a table
def shb_clean_name(v):
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "name"))
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f!\[\]:*?/\\]", " ", v or "")).strip().strip("'").strip()[:SHB_NAME_MAX]


def _name_free(rows, name, but=None):
    if any(shb_label(x).casefold() == name.casefold() and x["id"] != but for x in rows):
        raise BadInput(tr("A sheet with this name already exists"))


def shb_create(c, first, uid, name=None, after_id=None, columns=None, rows=None, agent_id=None, batch=None, copy_of=None):
    """A new sheet in table `first` (its first sheet's row) -> its id. columns / rows as sh_create (default 3 text columns,
    10 rows); copy_of = a sheet of the table to copy (columns, rows, inputs, names; file cells stay empty)."""
    from .core import SH_COLS_MAX, SH_START_COLS, SH_START_ROWS, sh_add_rows, sh_change, sh_clean_col, sh_reload
    tabs = shb_rows(c, first["id"])
    if len(tabs) >= SHB_TABS_MAX:
        raise BadInput(tr("Too many sheets (at most {0})", SHB_TABS_MAX))
    ts = iso_ms(now_utc())
    if not first["tab_name"]:  # the first sheet gets its name once the table has two (formulas name it)
        c.execute("UPDATE sheets SET tab_name=? WHERE id=?", (tr("Sheet {0}", 1), first["id"]))
        tabs = shb_rows(c, first["id"])
    name = shb_clean_name(name)
    if not name:
        n = len(tabs) + 1
        while any(shb_label(x).casefold() == tr("Sheet {0}", n).casefold() for x in tabs):
            n += 1
        name = tr("Sheet {0}", n)
    _name_free(tabs, name)
    i = next((k for k, x in enumerate(tabs) if x["id"] == after_id), None) if after_id else None
    if i is None:
        pos = (tabs[-1]["tab_pos"] if tabs else 0) + 1
    else:
        nxt = tabs[i + 1]["tab_pos"] if i + 1 < len(tabs) else tabs[i]["tab_pos"] + 2
        pos = (tabs[i]["tab_pos"] + nxt) / 2
    tid = insert_id(c, "INSERT INTO sheets(org_id,owner_id,title,list_id,created_by,created_at,updated_at,updated_by,agent_id,agent_batch,"
                       "book_id,tab_pos,tab_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (first["org_id"], first["owner_id"], name, first["list_id"], uid, ts, ts, uid, agent_id, batch, first["id"], pos, name))
    sh_change(c, tid, batch, agent_id, "create")
    if copy_of is not None:
        _copy(c, copy_of, tid, uid, ts)
        return tid
    cols = columns if columns is not None else [{"title": "", "kind": "text"} for _ in range(SH_START_COLS)]
    if not isinstance(cols, list) or len(cols) > SH_COLS_MAX:
        raise BadInput(tr("Too many columns (at most {0})", SH_COLS_MAX))
    for k, col in enumerate(cols):
        if not isinstance(col, dict):
            raise BadInput(tr("Invalid value: {0}", "columns"))
        f = sh_clean_col(col)
        c.execute("INSERT INTO sheet_columns(sheet_id,pos,title,kind,options,color_mode,width) VALUES(?,?,?,?,?,?,?)",
                  (tid, float(k + 1), f["title"], f["kind"], f.get("options", "[]"), f["color_mode"], f.get("width")))
    r = sh_reload(c, tid)
    sh_add_rows(c, r, SH_START_ROWS if rows is None else rows, uid, agent_id=agent_id, batch=batch)
    return tid


def _copy(c, src, tid, uid, ts):
    """The columns, rows and inputs of sheet src into the new sheet tid (formula ids mapped onto the copies)."""
    cmap, rmap, xmap = {}, {}, {}
    for col in c.execute("SELECT * FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (src["id"],)).fetchall():
        cmap[col["id"]] = insert_id(c, "INSERT INTO sheet_columns(sheet_id,pos,title,kind,options,color_mode,width) VALUES(?,?,?,?,?,?,?)",
                                    (tid, col["pos"], col["title"], col["kind"], col["options"], col["color_mode"], col["width"]))
    for row in c.execute("SELECT * FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL ORDER BY pos, id", (src["id"],)).fetchall():
        rmap[row["id"]] = insert_id(c, "INSERT INTO sheet_rows(sheet_id,pos) VALUES(?,?)", (tid, row["pos"]))
    kinds = {r["id"]: r["kind"] for r in c.execute("SELECT id, kind FROM sheet_columns WHERE sheet_id=?", (src["id"],)).fetchall()}
    cells = [x for x in c.execute("SELECT * FROM sheet_cells WHERE sheet_id=?", (src["id"],)).fetchall()
             if x["row_id"] in rmap and x["col_id"] in cmap]
    from .core import SH_BOOK_CELLS_MAX  # 2.148.1 G (#2485): a copied sheet counts against the table's cell cap, too
    bid = c.execute("SELECT COALESCE(book_id, id) FROM sheets WHERE id=?", (tid,)).fetchone()[0]
    have = c.execute("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id IN (SELECT id FROM sheets WHERE id=? OR book_id=?)",
                     (bid, bid)).fetchone()[0]
    if have + len(cells) > SH_BOOK_CELLS_MAX:
        raise BadInput(tr("The table is full (at most {0} cells)", SH_BOOK_CELLS_MAX))
    for x in cells:
        raw = "" if kinds.get(x["col_id"]) == "file" else (x["raw"] or "")  # a cell file belongs to its sheet
        xmap[x["id"]] = insert_id(c, "INSERT INTO sheet_cells(sheet_id,row_id,col_id,raw,name,frozen,frozen_value,updated_by,updated_at) "
                                     "VALUES(?,?,?,?,?,?,?,?,?)", (tid, rmap[x["row_id"]], cmap[x["col_id"]], raw, x["name"], x["frozen"],
                                                                  x["frozen_value"], uid, ts))

    def remap(m):
        t, i = m.group(1), int(m.group(2))
        new = (xmap if t == "c" else cmap).get(i)
        return "{%s:%d}" % (t, new) if new else m.group(0)
    for x in cells:
        raw = x["raw"] or ""
        if raw.startswith("=") and "{" in raw:
            new = re.sub(r"\{(c|col):(\d{1,18})\}", remap, raw)
            if new != raw:
                c.execute("UPDATE sheet_cells SET raw=? WHERE id=?", (new, xmap[x["id"]]))
    c.execute("UPDATE sheets SET freeze_rows=?, freeze_cols=? WHERE id=?", (src["freeze_rows"], src["freeze_cols"], tid))


def _need_book(c, sid, write=False):
    """(first sheet row, uid) of the table sheet sid belongs to; the rights of the table (sh_need)."""
    from .core import sh_need, sh_reload
    if write:
        need_feat("sheets")
    r = sh_need(c, sid, write=write)
    first = sh_reload(c, shb_bid(r))
    return first, me()


def _need_tab(c, first, tid, deleted=False):
    r = c.execute("SELECT * FROM sheets WHERE id=?", (tid,)).fetchone() if isinstance(tid, int) and 0 < tid < 2 ** 62 else None
    if not r or shb_bid(r) != first["id"] or bool(r["deleted_at"]) != deleted:
        raise Denied(404)
    return r


def _answer(c, first, code=200, **extra):
    c.commit()
    return jsonify(tabs=[shb_tab(x, i) for i, x in enumerate(shb_rows(c, first["id"]))], book_id=first["id"], **extra), code


@app.get("/api/sheets/<int:sid>/tabs")
def sheets_tabs_get(sid):
    """The sheets of the table sheet sid belongs to: {tabs: [{id, name, pos, first}], book_id}."""
    c = db()
    first, _uid = _need_book(c, sid)
    return _answer(c, first)


@app.post("/api/sheets/<int:sid>/tabs")
def sheets_tabs_add(sid):
    """{name?, after_id?, copy_of?} -> a new sheet (3 text columns, 10 rows; copy_of: a copy of that sheet) (201)."""
    from .core import sh_touch
    c = db()
    first, uid = _need_book(c, sid, write=True)
    b = body()
    after = b.get("after_id")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int)):
        raise BadInput(tr("Invalid value: {0}", "after_id"))
    src = None
    if b.get("copy_of") is not None:
        src = _need_tab(c, first, b.get("copy_of"))
    tid = shb_create(c, first, uid, b.get("name"), after, copy_of=src)
    sh_touch(c, tid, uid)
    r = c.execute("SELECT * FROM sheets WHERE id=?", (tid,)).fetchone()
    return _answer(c, first, 201, tab={"id": tid, "name": shb_label(r)})


@app.patch("/api/sheets/<int:sid>/tabs/<int:tid>")
def sheets_tabs_patch(sid, tid):
    """{name?, pos?} -- rename a sheet / move it to place pos (0 = first) of the sheet bar."""
    from .core import sh_touch
    c = db()
    first, uid = _need_book(c, sid, write=True)
    r = _need_tab(c, first, tid)
    b = body()
    tabs = shb_rows(c, first["id"])
    if "name" in b:
        name = shb_clean_name(b.get("name"))
        if not name:
            raise BadInput(tr("Invalid value: {0}", "name"))
        _name_free(tabs, name, but=tid)
        if r["book_id"]:
            c.execute("UPDATE sheets SET tab_name=?, title=? WHERE id=?", (name, name, tid))
        else:
            c.execute("UPDATE sheets SET tab_name=? WHERE id=?", (name, tid))
    if "pos" in b:
        p = b.get("pos")
        if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < len(tabs):
            raise BadInput(tr("Invalid value: {0}", "pos"))
        order = [x["id"] for x in tabs if x["id"] != tid]
        order.insert(p, tid)
        for k, x in enumerate(order):
            c.execute("UPDATE sheets SET tab_pos=? WHERE id=?", (float(k + 1), x))
    sh_touch(c, tid, uid)
    return _answer(c, first)


@app.delete("/api/sheets/<int:sid>/tabs/<int:tid>")
def sheets_tabs_delete(sid, tid):
    """A sheet to the trash (Undo: POST .../tabs/<tid>/restore). The first sheet carries the table (shares, list): 409."""
    from .core import sh_touch
    c = db()
    first, uid = _need_book(c, sid, write=True)
    r = _need_tab(c, first, tid)
    if not r["book_id"]:
        raise Denied(409, tr("This sheet carries the table and cannot be deleted on its own: delete the table instead"))
    c.execute("UPDATE sheets SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), tid))
    sh_touch(c, first["id"], uid)
    return _answer(c, first)


@app.post("/api/sheets/<int:sid>/tabs/<int:tid>/restore")
def sheets_tabs_restore(sid, tid):
    from .core import sh_touch
    c = db()
    first, uid = _need_book(c, sid, write=True)
    r = _need_tab(c, first, tid, deleted=True)
    tabs = shb_rows(c, first["id"])
    if len(tabs) >= SHB_TABS_MAX:
        raise BadInput(tr("Too many sheets (at most {0})", SHB_TABS_MAX))
    if any(shb_label(x).casefold() == shb_label(r).casefold() for x in tabs):  # its name was taken meanwhile
        name = shb_label(r)[:SHB_NAME_MAX - 4] + " (2)"
        c.execute("UPDATE sheets SET tab_name=?, title=? WHERE id=?", (name, name, tid))
    c.execute("UPDATE sheets SET deleted_at=NULL WHERE id=?", (tid,))
    sh_touch(c, tid, uid)
    return _answer(c, first)


# ---------------------------------------------------------------- a move to another workspace (sheets/shmove.py)
def shb_member_ids(c, sid):
    """The ids of every sheet of the table sid belongs to (also those in the trash)."""
    bid = c.execute("SELECT COALESCE(book_id, id) FROM sheets WHERE id=?", (sid,)).fetchone()
    return [x["id"] for x in shb_rows(c, bid[0], deleted=True)] if bid else [sid]


def shb_move(c, sid, to, uid):
    """After the first sheet moved: the further sheets follow (space fields, the files of their file cells)."""
    from .shkinds import shk_move_files
    shb_sync(c, sid)
    for t in shb_member_ids(c, sid):
        if t != sid:
            shk_move_files(c, t, to, uid)


# ---------------------------------------------------------------- files (sheets/io.py)
def shb_import(c, uid, grids, space, title, list_id=None):
    """A new table from the sheets read from a file -> (first sheet id, report): the first sheet as before, every further one
    a further sheet of it; formulas into another sheet of the file are set once all sheets exist (else they stay values)."""
    from .core import ShBook, _write_cells, sh_reload, sh_to_internal, sh_touch
    from .io import SHX_CHUNK, shx_import, shx_kalmido_formula
    grids = grids if isinstance(grids, list) else [grids]
    many = len(grids) > 1
    for g in grids:
        g.xlater = []
    sid, rep = shx_import(c, uid, grids[0], space, title, list_id)
    rep["sheets"] = len(grids)
    rep["sheets_total"] = max(len(grids), getattr(grids[0], "n_sheets", 1))
    if not many:
        return sid, rep
    first = sh_reload(c, sid)
    label = shb_clean_name(grids[0].sheet_name) or tr("Sheet {0}", 1)
    c.execute("UPDATE sheets SET tab_name=? WHERE id=?", (label, sid))
    first = sh_reload(c, sid)
    made = [(grids[0], sid, label)]
    for g in grids[1:]:
        name = shb_clean_name(g.sheet_name)
        taken = {x[2].casefold() for x in made}
        if not name or name.casefold() in taken:
            n = len(made) + 1
            while tr("Sheet {0}", n).casefold() in taken:
                n += 1
            name = tr("Sheet {0}", n)
        tid, r2 = shx_import(c, uid, g, space, name, list_id, into=first)
        made.append((g, tid, name))
        for k in ("rows", "formulas", "as_value", "options_added", "names"):
            rep[k] += r2[k]
        rep["columns"] = max(rep["columns"], r2["columns"])
    xs = {g.sheet_name: (name, getattr(g, "hdr", 0)) for g, _t, name in made}
    for g, tid, _name in made:
        if not g.xlater:
            continue
        sheet = sh_reload(c, tid)
        book = ShBook(c, sheet)
        book.shh_off = True  # 2.124.0 B (#2112): a new table from a file has no history of its own
        ok = []
        for rid, col_id, f, _v, names_at in g.xlater:
            kf = shx_kalmido_formula(f, g.hdr, names_at, xs)
            if not kf:
                continue
            try:
                with c.savepoint():
                    sh_to_internal(c, sheet, kf, uid, book)
                ok.append({"row_id": rid, "col_id": col_id, "raw": kf})
            except BadInput:
                continue
        if ok:
            book = ShBook(c, sheet)
            book.shh_off = True
            for i in range(0, len(ok), SHX_CHUNK):
                _write_cells(c, sheet, ok[i:i + SHX_CHUNK], uid, None, None, book)
            rep["formulas"] += len(ok)
            rep["as_value"] -= len(ok)
    sh_touch(c, sid, uid)
    return sid, rep


def shb_xl_names(rows):
    """{sheet id: its name in an .xlsx} (Excel: at most 31 characters, unique, none of []:*?/\\, not "_lists")."""
    from .io import _sheet_name
    out, seen = {}, {"_lists"}
    for r in rows:
        base = _sheet_name(shb_label(r))
        name, n = base, 2
        while name.casefold() in seen:
            suf = f" ({n})"
            name, n = base[:31 - len(suf)] + suf, n + 1
        seen.add(name.casefold())
        out[r["id"]] = name
    return out


def shb_xl_ref(book, xid):
    """shx_xl_formula's hook: 'Name'!B4 of a cell of another sheet when the whole table is written (else None: the value)."""
    names = getattr(book, "shb_xl", None)
    if not names:
        return None
    cache = book.__dict__.setdefault("shb_cache", {})
    tab = shb_check(book.c, book.sheet, xid)
    if tab is None or tab["id"] not in names:
        return None
    tb = _book_of_tab(book.c, tab, cache)
    x = tb.cells.get(xid)
    if not tb.live(x):
        return None
    from .io import _xl_ref
    return "'" + names[tab["id"]].replace("'", "''") + "'!" + _xl_ref(tb, x)


_DXF = re.compile(r'<dxfs count="\d+">(.*?)</dxfs>', re.S)
_DNAME = re.compile(r"<definedName [^>]*>.*?</definedName>", re.S)


def shb_xlsx(c, sheet_row):
    """(the .xlsx bytes of the table sheet_row belongs to: one worksheet per sheet, its title). Each sheet is written as
    before (sheets/io.py shx_xlsx) and the files are put together: worksheets, drop-down lists, notes and colour rules
    renumbered, cell names of a further sheet local to it."""
    import io as _io
    import zipfile
    from .io import _MAIN, _NS, _q, shx_xlsx
    bid = shb_bid(sheet_row)
    rows = shb_rows(c, bid)
    first = next((x for x in rows if x["id"] == bid), None) or sheet_row
    if len(rows) < 2:
        return shx_xlsx(c, rows[0] if rows else sheet_row), first["title"]
    names = shb_xl_names(rows)
    parts, dxfs, wsheets, lists, defs, notes = {}, [], [], [], [], 0
    styles = None
    n = len(rows)
    for k, r in enumerate(rows, 1):
        z = zipfile.ZipFile(_io.BytesIO(shx_xlsx(c, dict(r) | {"title": names[r["id"]]}, names)))
        st = z.read("xl/styles.xml").decode()
        m = _DXF.search(st)
        own = re.findall(r"<dxf>.*?</dxf>", m.group(1), re.S) if m else []
        styles = styles or st
        ws = z.read("xl/worksheets/sheet1.xml").decode()
        off = len(dxfs)
        dxfs.extend(own)
        ws = re.sub(r'dxfId="(\d+)"', lambda mm: f'dxfId="{int(mm.group(1)) + off}"', ws)
        if "xl/worksheets/sheet2.xml" in z.namelist():  # its drop-down lists that were too long to write inline
            ln = "_lists" if k == 1 else f"_lists{k}"
            ws = ws.replace("'_lists'!", f"'{ln}'!")
            lists.append((ln, z.read("xl/worksheets/sheet2.xml").decode()))
        if "xl/comments1.xml" in z.namelist():
            notes += 1
            parts[f"xl/comments{k}.xml"] = z.read("xl/comments1.xml")
            parts[f"xl/drawings/vmlDrawing{k}.vml"] = z.read("xl/drawings/vmlDrawing1.vml")
            parts[f"xl/worksheets/_rels/sheet{k}.xml.rels"] = z.read("xl/worksheets/_rels/sheet1.xml.rels").decode().replace(
                "../comments1.xml", f"../comments{k}.xml").replace("vmlDrawing1.vml", f"vmlDrawing{k}.vml")
        parts[f"xl/worksheets/sheet{k}.xml"] = ws
        wsheets.append(names[r["id"]])
        for d in _DNAME.findall(z.read("xl/workbook.xml").decode()):
            defs.append(d if k == 1 else d.replace("<definedName ", f'<definedName localSheetId="{k - 1}" ', 1))
    styles = _DXF.sub(lambda _m: f'<dxfs count="{len(dxfs)}">{"".join(dxfs)}</dxfs>', styles, count=1)
    rel = f"{_NS}/officeDocument/2006/relationships"
    sheets_xml, wrels, ct = [], [], []
    for k, nm in enumerate(wsheets, 1):
        sheets_xml.append(f'<sheet name="{_q(nm)}" sheetId="{k}" r:id="rId{k}"/>')
        wrels.append(f'<Relationship Id="rId{k}" Type="{rel}/worksheet" Target="worksheets/sheet{k}.xml"/>')
        ct.append(f'<Override PartName="/xl/worksheets/sheet{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        if f"xl/comments{k}.xml" in parts:
            ct.append(f'<Override PartName="/xl/comments{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
    for j, (ln, xml) in enumerate(lists, n + 1):
        sheets_xml.append(f'<sheet name="{ln}" sheetId="{j}" state="hidden" r:id="rId{j}"/>')
        wrels.append(f'<Relationship Id="rId{j}" Type="{rel}/worksheet" Target="worksheets/sheet{j}.xml"/>')
        ct.append(f'<Override PartName="/xl/worksheets/sheet{j}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        parts[f"xl/worksheets/sheet{j}.xml"] = xml
    sid_styles = n + len(lists) + 1
    wrels.append(f'<Relationship Id="rId{sid_styles}" Type="{rel}/styles" Target="styles.xml"/>')
    glob = sorted(d for d in defs if "localSheetId" not in d)
    defs = glob + [d for d in defs if "localSheetId" in d]
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_MAIN}" xmlns:r="{rel}">'
                                f'<bookViews><workbookView/></bookViews><sheets>{"".join(sheets_xml)}</sheets>'
                                + (f'<definedNames>{"".join(defs)}</definedNames>' if defs else "")
                                + '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
    parts["xl/_rels/workbook.xml.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
                                           + "".join(wrels) + "</Relationships>")
    parts["xl/styles.xml"] = styles
    parts["_rels/.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
                            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts["[Content_Types].xml"] = "".join([
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{_NS}/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>' if notes else "",
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        *ct, '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        "</Types>"])
    order = ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml"]
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for key in order + sorted(k for k in parts if k not in order):
            z.writestr(key, parts[key])
    return buf.getvalue(), first["title"]


# ---------------------------------------------------------------- API v1 (agents, scripts)
from ..api.common import v1_args, v1_json, v1_view  # noqa: E402  (api.v1 comes earlier in ORDER; sheets.v1 later: imported in the routes)


@app.get("/api/v1/sheets/<int:sid>/tabs")
@v1_view
def v1_sheet_tabs(sid):
    """The sheets of the table sheet sid belongs to: {data: [{id, name, pos, first}], book_id}. Read / write one sheet with the
    routes of a table and its id."""
    v1_args(())
    c = db()
    first, _uid = _need_book(c, sid)
    return jsonify(data=[shb_tab(x, i) for i, x in enumerate(shb_rows(c, first["id"]))], book_id=first["id"])


@app.post("/api/v1/sheets/<int:sid>/tabs")
@v1_view
def v1_sheet_tab_add(sid):
    """{name?, columns?, rows?} -> the new sheet of the table (like a table: columns, rows, cells; 201)."""
    from .core import sh_need, sh_reload, sh_touch
    from .v1 import _check_fields, _v1_sheet, _write_ctx
    b = v1_json()
    _check_fields(b, ("name", "columns", "rows"))
    agent_id, batch = _write_ctx()
    c = db()
    r = sh_need(c, sid, write=True)
    cols, rows = b.get("columns"), b.get("rows")
    if cols is not None and not isinstance(cols, list):
        raise BadInput(tr("Invalid value: {0}", "columns"))
    if rows is not None and not isinstance(rows, list):
        raise BadInput(tr("Invalid value: {0}", "rows"))
    tid = shb_create(c, sh_reload(c, shb_bid(r)), me(), b.get("name"), columns=cols, rows=rows, agent_id=agent_id, batch=batch)
    sh_touch(c, tid, me())
    c.commit()
    return jsonify(_v1_sheet(c, sh_reload(c, tid), batch)), 201


def shb_spec(paths, schemas, op, ok, errs, ref, pid, q, inputs, col_in, write):
    """sheets_spec's hook (OpenAPI)."""
    T = "Tables"
    sid = pid("id", "Table id (any of its sheets)")
    tab = {"type": "object", "properties": {"id": {"type": "integer", "description": "The sheet's id: use it like a table id"},
                                            "name": {"type": "string"}, "pos": {"type": "integer"},
                                            "first": {"type": "boolean", "description": "The first sheet carries the table"}}}
    paths["/sheets/{id}/tabs"] = {
        "get": op("The sheets of a table (2.124.0)", T, ok({"type": "object", "properties": {"data": {"type": "array", "items": tab},
                                                                                            "book_id": {"type": "integer"}}})
                  | errs("403", "404"), [sid], scope="sheets:read",
                  desc="A table can have several sheets (like a spreadsheet file). Read and change one sheet with the routes of a table "
                       "and the sheet's id; formulas reach into another sheet with Name!A1 or 'Sheet name'!A1:B5."),
        "post": op("Add a sheet to a table (2.124.0)", T, ok(ref("Sheet"), "Created", "201") | errs("400", "403", "404", "409"), [sid],
                   body={"type": "object", "properties": {"name": {"type": "string", "maxLength": 100},
                                                          "columns": {"type": "array", "items": col_in, "maxItems": 200}, "rows": inputs}},
                   scope="sheets:write", desc=write + " Taking back the call moves the new sheet to the trash.")}
