"""2.89.0 (#1916, D): step 2 of the tables -- carrying data over BY BUTTON, never a silent live link.

- POST /api/sheets/<id>/to-tasks: chosen rows -> tasks of a list the person may change in the sheet's space (title column,
  optional due / notes column). The task's history says it came from a table (with a link, never the table's name: the
  list may be shared with people who cannot open the table); the row is marked "carried over into <task>".
- POST /api/sheets/<id>/to-offer: the sheet (or chosen rows) -> a quotation draft in the office of the sheet's space (an
  organisation's office, a private sheet: the person's own office); columns description / quantity / unit / unit price,
  a client of that office. Only a draft (the office's own creation path: rights, number, texts); nothing is finalised.
- POST /api/sheets/<id>/rows-from-list: one row per task of a visible list / project of the space; the cells are LIVE
  Kalmido values (aufgabe.<id>.<field>, evaluated per viewer, sheets/vars.py). Pressed again for the same list = "fetch
  the list's new tasks": only the rows still missing are appended, into the same columns (no silent sync).
- GET /api/sheets/<id>/links: the marks of the rows / the sheet (labels only for a viewer who may see the target) plus
  what the dialogs offer (writable lists, visible lists, office on + its clients).
- POST /api/sheets/<id>/links/<batch>/undo | redo: one button press = one undo step (tasks to the trash, rows / columns
  of "list as rows" to the trash, the quotation draft deleted when the office allows it).

People only: agents get 403 (the table tools of part C stay inside the sheet). 2.126.1 B (#2125): an agent proposes rows
instead (POST /api/v1/agent/proposals/sheet-tasks, agents/sheetprop.py); the person applies the card and sh2_to_tasks runs
as them, with the same checks. Every route needs the right to write the sheet AND the target (list / office), the source visible and
the same space."""
import secrets

from flask import jsonify, request

from ..core.config import app
from ..core.access import Denied, WRITE_ROLES, list_role, need_feat, task_visible, tvis, vis_sql
from ..core.db import body, bump, db, iso, iso_ms, now_utc
from ..core.i18n import N_, tr
from ..core.pg import insert_id
from ..accounts.session import me
from ..collab.comments import user_names
from ..core.errors import BadInput
from .core import SH_ROWS_MAX, ShBook, sh_eval, sh_is_agent, sh_need, sh_reload, sh_set_cells, sh_touch
from .formula import sh_parse_date, sh_parse_number
from .vars import sh_list_ok, sh_task_ok

SH2_ROWS_MAX = 500  # rows / tasks per button press
SH2_FIELDS = (("titel", "text", N_("Title")), ("status", "text", N_("Status")), ("faellig", "date", N_("Due")),
              ("zeit", "number", N_("Time|tracked")), ("zustaendig", "text", N_("Assignee")))
# the units of the office (office/model.py UNITS) by the words people type into a unit column
SH2_UNITS = {"day": ("tag", "tage", "tg", "day", "days", "d", "jour", "jours", "giorno", "giorni", "dag", "dagen", "día", "días"),
             "hour": ("std", "std.", "stunde", "stunden", "h", "hour", "hours", "hr", "hrs", "heure", "heures", "ora", "ore", "uur", "hora", "horas"),
             "minute": ("min", "min.", "minute", "minuten", "minutes", "minuto", "minuti", "minuut", "minuten"),
             "flat": ("pauschal", "pausch.", "psch", "flat", "pauschale", "forfait", "forfait", "a corpo", "vast", "tanto alzado"),
             "piece": ("stk", "stk.", "stück", "st", "st.", "piece", "pieces", "pc", "pcs", "x", "pièce", "pièces", "pezzo", "pezzi",
                       "stuk", "stuks", "pieza", "piezas")}
SH2_NO_OFFICE = N_("Office & finance is not available for this table's space")


def _gate(c, sid, write=True):
    """The sheet for a person (agents: 403) with the module on; write: the right to change it."""
    uid = me()
    if sh_is_agent(c, uid):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    if write:
        need_feat("sheets")
    r = sh_need(c, sid, write=write)
    if write:  # 2.124.0 C (#2113): carrying rows over (tasks, quotation, list as rows) never through a share
        from .shshare import shs_need_own
        shs_need_own(c, r)
    return r, uid


def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _col(book, v, what, required=False):
    if v in (None, "", 0) and not required:
        return None
    v = _int(v, what)
    if v not in book.col_idx:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _rows(book, v):
    """The chosen live rows in sheet order (None / missing = every row)."""
    if v is None:
        return [r["id"] for r in book.rows]
    if not isinstance(v, list) or len(v) > SH_ROWS_MAX:
        raise BadInput(tr("Invalid value: {0}", "rows"))
    want = {_int(x, "rows") for x in v}
    if want - set(book.row_idx):
        raise BadInput(tr("Invalid value: {0}", "rows"))
    return [r["id"] for r in book.rows if r["id"] in want]


def _cell(book, res, rid, cid):
    """(value, display) of a cell for the viewer ((None, "") when empty, an error or no column)."""
    if cid is None:
        return None, ""
    x = book.at.get((rid, cid))
    r = res.get(x["id"]) if x else None
    if not r or r.get("error"):
        return None, ""
    return r.get("value"), (r.get("display") or "").strip()


def _batch():
    return secrets.token_hex(8)


def _link(c, sid, kind, target, batch, uid, row_id=None, list_id=None):
    c.execute("INSERT INTO sheet_links(sheet_id,row_id,kind,target_id,list_id,batch,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (sid, row_id, kind, target, list_id, batch, uid, iso_ms(now_utc())))


def sh2_target_list(c, sheet, uid, lid):
    """The list tasks may go to: uid may change it (no participant / viewer), it lies in the sheet's space (an organisation's
    sheet: that organisation's lists; a private sheet: lists without organisation), no lock, not archived."""
    lid = _int(lid, "list_id")
    role = list_role(c, lid, uid)
    l = c.execute("SELECT id, name, org_id, e2e, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not role or not l or l["org_id"] != sheet["org_id"]:
        raise Denied(404)
    if role not in WRITE_ROLES:
        raise Denied(403)
    from ..collab.liste2eguard import le2b_list_locked
    if l["e2e"] is not None or le2b_list_locked(c, lid):
        raise Denied(409, tr("This project is locked: its texts can only be written in the app"))
    if l["archived"]:
        raise Denied(409, tr("This project is archived"))
    return l


def sh2_office(c, sheet, uid, create=False, write=False):
    """The office area of the sheet's space for uid, or None when it is not available there (module off, no role; a
    private sheet: uid's own personal office). 2.143.0 A (#2151, review): guests never; read-only / accounting only to
    read (create / write: members and admins)."""
    from ..office.model import office_on, office_role, pb_personal
    if not office_on(c, uid):
        return None
    if sheet["org_id"] is None:
        return pb_personal(c, uid, create=create)
    from ..accounts.orgroles import office_allowed
    if not office_role(c, uid, sheet["org_id"]) or office_allowed(c, uid, sheet["org_id"], write=bool(create or write)):
        return None
    from ..office.rights import ofr_allows
    if not ofr_allows(c, uid, sheet["org_id"], "offers", "edit" if create or write else "view"):  # 2.187.0 C (#2476)
        return None
    return sheet["org_id"]


def _unit(s):
    low = (s or "").strip().casefold()
    if not low:
        return None
    return next((u for u, words in SH2_UNITS.items() if low in words or low == u), None)


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return sh_parse_number(v)
    return None


def _linked(c, sid, kind, rows=None):
    """{row_id: target_id} of the live (not undone) links of a kind."""
    out = {}
    for r in c.execute("SELECT row_id, target_id FROM sheet_links WHERE sheet_id=? AND kind=? AND undone_at IS NULL ORDER BY id",
                       (sid, kind)):
        if rows is None or r["row_id"] in rows:
            out[r["row_id"]] = r["target_id"]
    return out


# ---------------------------------------------------------------- rows -> tasks
def sh2_to_tasks(c, sheet, uid, b, titles=None, dues=None, via=None):
    """The core of POST .../to-tasks, without the request (the caller checked uid may write the sheet: _gate). People only:
    uid is the person; an agent's rows come as a proposal (agents/sheetprop.py) that the person applies, then via =
    {agent_id} names the agent in the history. 2.126.1 B (#2125): titles / dues = {row id: the person's edit of the card}."""
    from ..tasks.validation import log_act
    from ..agents.core import agent_added_events
    from ..tasks.dependencies import newtask_events
    from ..lists.rules import rul_fire, rul_snap_new
    book = ShBook(c, sheet)
    l = sh2_target_list(c, sheet, uid, b.get("list_id"))
    tcol = _col(book, b.get("title_col"), "title_col", required=True)
    dcol = _col(book, b.get("due_col"), "due_col")
    ncol = _col(book, b.get("notes_col"), "notes_col")
    rows = _rows(book, b.get("rows"))
    done = _linked(c, sheet["id"], "task", set(rows))
    res = sh_eval(c, sheet, book, uid)
    items, skipped = [], 0
    for rid in rows:
        _, title = _cell(book, res, rid, tcol)
        title = ((titles or {}).get(rid) or title or "").strip()  # 2.126.1 B (#2125): a title edited on the proposal card
        if not title or rid in done:
            skipped += 1
            continue
        due = None
        if dcol:
            v, d = _cell(book, res, rid, dcol)
            dd = sh_parse_date(str(v)) if v not in (None, "") else None
            due = dd.isoformat() if dd else None
        if dues and rid in dues:  # 2.126.1 B (#2125): the date of the proposal card (None = none)
            due = dues[rid]
        notes = _cell(book, res, rid, ncol)[1] if ncol else ""
        items.append((rid, title[:300], due, notes[:20000]))
    if not items:
        raise BadInput(tr("No row with a title to carry over"))
    if len(items) > SH2_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", SH2_ROWS_MAX))
    batch, ts = _batch(), iso(now_utc())
    base = c.execute("SELECT COALESCE(MIN(sort),0) FROM tasks WHERE list_id=? AND parent_id IS NULL", (l["id"],)).fetchone()[0] - len(items) - 1
    out = []
    for i, (rid, title, due, notes) in enumerate(items):
        tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                        (l["id"], title, notes, due, base + i, ts, ts, uid))
        # the history: "carried over from a table" + link (no table name); 2.126.1 B (#2125): + "from a proposal by <agent>"
        log_act(c, tid, "created", {"sheet": sheet["id"], **({"agent": via["agent_id"], "proposal": True} if via else {})})
        agent_added_events(c, tid, source="proposal" if via else None)
        newtask_events(c, tid)
        rul_fire(c, tid, rul_snap_new(c))
        _link(c, sheet["id"], "task", tid, batch, uid, row_id=rid, list_id=l["id"])
        out.append({"row_id": rid, "task_id": tid, "title": title})
    sh_touch(c, sheet["id"], uid)
    return {"batch": batch, "list_id": l["id"], "tasks": out, "skipped": skipped}


# ---------------------------------------------------------------- sheet -> quotation draft
def sh2_to_offer(c, sheet, uid, b):
    from ..office.docs import doc_create, doc_row
    from ..office.ledger import ofx_log
    from ..office.model import office_role, office_seed_texts
    oid = sh2_office(c, sheet, uid, create=True)
    if not oid:
        raise Denied(403, tr(SH2_NO_OFFICE))
    book = ShBook(c, sheet)
    dcol = _col(book, b.get("desc_col"), "desc_col", required=True)
    qcol = _col(book, b.get("qty_col"), "qty_col")
    ucol = _col(book, b.get("unit_col"), "unit_col")
    pcol = _col(book, b.get("price_col"), "price_col")
    rows = _rows(book, b.get("rows"))
    res = sh_eval(c, sheet, book, uid)
    items, used = [], []
    for rid in rows:
        _, desc = _cell(book, res, rid, dcol)
        if not desc:
            continue
        it = {"kind": "service", "title": desc[:500]}
        if qcol:
            q = _number(_cell(book, res, rid, qcol)[0])
            if q is not None and 0 <= q <= 1e6:
                it["qty"] = q
        if ucol:
            u = _unit(_cell(book, res, rid, ucol)[1])
            if u:
                it["unit"] = u
        if pcol:
            p = _number(_cell(book, res, rid, pcol)[0])
            if p is not None and -1e8 <= p <= 1e8:
                it["rate"] = round(p, 2)
        it.setdefault("unit", "piece" if ucol or qcol else "flat")
        items.append(it)
        used.append(rid)
    if not items:
        raise BadInput(tr("No row with a description to carry over"))
    if len(items) > 300:
        raise BadInput(tr("Too many rows (at most {0})", 300))
    office_seed_texts(c, oid)
    admin = office_role(c, uid, oid) == "admin"
    d = {"project_title": (b.get("title") if isinstance(b.get("title"), str) and b.get("title").strip() else sheet["title"])[:200],
         "items": items}
    if b.get("client_id") not in (None, "", 0):
        d["client_id"] = _int(b.get("client_id"), "client_id")  # office/docs.py clean_doc: only a client of this office (404)
    did = doc_create(c, oid, uid, d, admin)
    r = doc_row(c, oid, did)
    ofx_log(c, oid, "create", doc_id=did, detail={"number": r["number"], "items": len(items)})
    ofx_log(c, oid, "from_sheet", doc_id=did, detail={"sheet": sheet["id"], "rows": len(used)})  # the office history: "created from a table"
    batch = _batch()
    _link(c, sheet["id"], "offer", did, batch, uid)
    sh_touch(c, sheet["id"], uid)
    return {"batch": batch, "doc_id": did, "number": r["number"], "items": len(items)}


# ---------------------------------------------------------------- list -> rows (live task values)
def _field_cols(book, linked_rows):
    """{field: col_id} of the columns that carry the task values of rows put in earlier (read from their formulas)."""
    import re
    out = {}
    pat = re.compile(r"=\{t:\d+\}\.(\w+)$")
    for rid in linked_rows:
        for col in book.cols:
            x = book.at.get((rid, col["id"]))
            m = pat.match((x or {}).get("raw") or "") if x else None
            if m and m.group(1) not in out:
                out[m.group(1)] = col["id"]
    return out


def _sheet_empty(book):
    return not any(x["raw"] or x.get("name") for x in book.cells.values() if book.live(x)) \
        and all(not (col["title"] or "").strip() and col["kind"] == "text" for col in book.cols)


def sh2_rows_from_list(c, sheet, uid, b):
    sid = sheet["id"]
    lid = _int(b.get("list_id"), "list_id")
    lrow = sh_list_ok(c, sheet, uid, lid)
    if lrow in (None, "deleted"):
        raise Denied(404)
    tasks = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE list_id=? AND parent_id IS NULL AND deleted_at IS NULL AND {tvis(c, uid)} "
                                     f"ORDER BY status=0 DESC, sort, id LIMIT {SH2_ROWS_MAX + 1}", (lid,)).fetchall()]
    book = ShBook(c, sheet)
    mine = {}  # task id -> row id of the live rows that came from this list
    rows_any = []  # the live rows of any list (their columns are reused: one set of task columns per sheet)
    for r in c.execute("SELECT row_id, target_id, list_id FROM sheet_links WHERE sheet_id=? AND kind='row' AND undone_at IS NULL",
                       (sid,)).fetchall():
        if r["row_id"] in book.row_idx:
            rows_any.append(r["row_id"])
            if r["list_id"] == lid:
                mine[r["target_id"]] = r["row_id"]
    todo = [t for t in tasks if t not in mine and sh_task_ok(c, sheet, uid, t) not in (None, "deleted")]
    if not todo:
        return {"batch": None, "rows": [], "added": 0}
    if len(tasks) > SH2_ROWS_MAX and not mine:
        raise BadInput(tr("Too many rows (at most {0})", SH2_ROWS_MAX))
    todo = todo[:SH2_ROWS_MAX]
    if len(book.rows) + len(todo) > SH_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", SH_ROWS_MAX))
    batch, ts = _batch(), iso_ms(now_utc())
    cols = _field_cols(book, rows_any) if rows_any else {}  # the columns of the rows put in before
    empty = _sheet_empty(book)
    if len(cols) < len(SH2_FIELDS):
        if empty and not cols:  # a new, empty sheet: its blank columns make room (back with the undo)
            for col in book.cols:
                c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=?", (ts, col["id"]))
                _link(c, sid, "colhide", col["id"], batch, uid)
        pos = (c.execute("SELECT COALESCE(MAX(pos),0) FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL", (sid,)).fetchone()[0])
        for field, kind, label in SH2_FIELDS:
            if field in cols:
                continue
            pos += 1
            cid = insert_id(c, "INSERT INTO sheet_columns(sheet_id,pos,title,kind,options,color_mode) VALUES(?,?,?,?,'[]','cell')",
                            (sid, pos, tr(label)[:200], kind))
            _link(c, sid, "col", cid, batch, uid)
            cols[field] = cid
    # the new rows: on an empty sheet above its blank rows, else after the last row with content (or of this list)
    live = list(book.rows)
    if empty:
        first = live[0]["pos"] if live else 1.0
        positions = [first - len(todo) + i - 0.5 for i in range(len(todo))]
    else:
        filled = {x["row_id"] for x in book.cells.values() if book.live(x) and x["raw"]}
        last = next((r for r in reversed(live) if r["id"] in filled), None)
        lo = last["pos"] if last else (live[0]["pos"] - 1 if live else 0.0)
        nxt = next((r["pos"] for r in live if r["pos"] > lo), None)
        step = ((nxt - lo) / (len(todo) + 1)) if nxt is not None else 1.0
        positions = [lo + (i + 1) * step for i in range(len(todo))]
    cells, out = [], []
    for t, p in zip(todo, positions):
        rid = insert_id(c, "INSERT INTO sheet_rows(sheet_id,pos) VALUES(?,?)", (sid, p))
        _link(c, sid, "row", t, batch, uid, row_id=rid, list_id=lid)
        out.append(rid)
        for field, _, _ in SH2_FIELDS:
            cells.append({"row_id": rid, "col_id": cols[field], "raw": "={t:%d}.%s" % (t, field)})
    sh_set_cells(c, sh_reload(c, sid), cells, uid)  # checks every task once more (visible, same space) and stores the ids
    sh_touch(c, sid, uid)
    return {"batch": batch, "rows": out, "added": len(out), "more": len(tasks) > SH2_ROWS_MAX}


# ---------------------------------------------------------------- the marks + undo
def sh2_links(c, sheet, uid):
    """The live marks of a sheet for viewer uid: labels only of targets they may see."""
    rows = c.execute("SELECT * FROM sheet_links WHERE sheet_id=? AND undone_at IS NULL AND kind IN ('task', 'offer') ORDER BY id",
                     (sheet["id"],)).fetchall()
    names = user_names(c, {r["created_by"] for r in rows})
    oid = sh2_office(c, sheet, uid) if any(r["kind"] == "offer" for r in rows) else None
    out = []
    for r in rows:
        d = {"id": r["id"], "kind": r["kind"], "row_id": r["row_id"], "target_id": r["target_id"], "batch": r["batch"],
             "created_at": r["created_at"], "created_by_name": names.get(r["created_by"], ""), "label": None, "denied": False,
             "deleted": False}
        if r["kind"] == "task":
            t = c.execute("SELECT title, deleted_at, list_id FROM tasks WHERE id=?", (r["target_id"],)).fetchone()
            if not t or t["deleted_at"]:
                # 2.89.0 (#1916): "deleted" only for whom the task's list is visible (or who made the link), else as denied
                seen = r["created_by"] == uid or (t and sh_list_ok(c, sheet, uid, t["list_id"]) not in (None, "deleted"))
                d["deleted" if seen else "denied"] = True
            elif not task_visible(c, r["target_id"], uid) or sh_list_ok(c, sheet, uid, t["list_id"]) in (None, "deleted"):
                d["denied"] = True
            else:
                d["label"], d["list_id"] = t["title"], t["list_id"]
        else:
            o = c.execute("SELECT number, project_title, org_id FROM office_docs WHERE id=?", (r["target_id"],)).fetchone()
            if not o:
                d["deleted" if oid or r["created_by"] == uid else "denied"] = True  # 2.89.0 (#1916): no hint without the office
            elif not oid or o["org_id"] != oid:
                d["denied"] = True
            else:
                d["label"] = o["number"] or o["project_title"] or tr("Quotation")
        out.append(d)
    return out


def sh2_offers(c, sheet, uid):
    """What the dialogs need: lists of the space (writable ones for tasks), the office (on? its clients)."""
    lists = []
    for r in c.execute(f"SELECT id, name, kind, org_id, archived FROM lists WHERE id IN {vis_sql()} AND e2e IS NULL ORDER BY lower(name), id",
                       (uid, uid)).fetchall():
        if r["org_id"] != sheet["org_id"] or sh_list_ok(c, sheet, uid, r["id"]) in (None, "deleted"):
            continue
        role = list_role(c, r["id"], uid)
        lists.append({"id": r["id"], "name": r["name"], "project": r["kind"] == "project",
                      "writable": role in WRITE_ROLES and not r["archived"]})
    oid = sh2_office(c, sheet, uid)
    clients = []
    if oid:
        from ..office.model import pb_cl_sql
        clients = [{"id": r["id"], "name": r["name"]} for r in
                   c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)} AND deleted_at IS NULL ORDER BY lower(name), id LIMIT 1000")]
    return {"lists": lists, "office": bool(oid) or (sheet["org_id"] is None and _office_private_on(c, uid)), "clients": clients}


def _office_private_on(c, uid):
    from ..office.model import office_on
    return office_on(c, uid)  # a private sheet: the personal office is made on its first use


def sh2_undo(c, sheet, uid, batch, redo=False):
    """Takes back (redo: brings back) one button press. -> {done, kept, edited} (kept: a quotation the office keeps;
    edited: of those, the ones changed in the office since the press, 2.270.0 B #3021)."""
    rows = c.execute("SELECT * FROM sheet_links WHERE sheet_id=? AND batch=? ORDER BY id DESC", (sheet["id"], batch)).fetchall()
    if not rows:
        raise Denied(404)
    from ..tasks.lifecycle import restore_task, trash_task
    ts, done, kept, edited = iso_ms(now_utc()), 0, [], []
    for r in rows:
        if bool(r["undone_at"]) != redo:
            continue
        k = r["kind"]
        if k == "task":
            t = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (r["target_id"],)).fetchone()
            if not t or not task_visible(c, r["target_id"], uid, write=True):
                continue
            if redo and t["deleted_at"]:
                restore_task(c, r["target_id"])
            elif not redo and not t["deleted_at"]:
                trash_task(c, r["target_id"])
        elif k == "offer":
            if redo:
                continue  # a deleted draft does not come back (the app makes a new one)
            res = _offer_drop(c, sheet, uid, r["target_id"])
            if res is not True:
                kept.append(r["target_id"])
                if res == "edited":
                    edited.append(r["target_id"])  # 2.270.0 B (#3021)
                continue
        elif k == "row":
            c.execute("UPDATE sheet_rows SET deleted_at=? WHERE id=? AND sheet_id=?", (None if redo else ts, r["row_id"], sheet["id"]))
        elif k == "col" and not redo and c.execute(
                "SELECT 1 FROM sheet_cells x JOIN sheet_rows w ON w.id=x.row_id WHERE x.col_id=? AND w.deleted_at IS NULL AND x.raw<>'' LIMIT 1",
                (r["target_id"],)).fetchone():
            pass  # rows of a later press (or typed values) use the column: it stays
        elif k == "col":
            c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=? AND sheet_id=?", (None if redo else ts, r["target_id"], sheet["id"]))
        elif k == "colhide":
            c.execute("UPDATE sheet_columns SET deleted_at=? WHERE id=? AND sheet_id=?", (ts if redo else None, r["target_id"], sheet["id"]))
        c.execute("UPDATE sheet_links SET undone_at=? WHERE id=?", (None if redo else ts, r["id"]))
        done += 1
    if done:
        sh_touch(c, sheet["id"], uid)
    return {"done": done, "kept": kept, "edited": edited}


# 2.270.0 B (#3021): office log entries of a draft that do not change it (the press itself and reads)
SH2_OFFER_UNTOUCHED = ("create", "from_sheet", "open", "pdf", "render", "export", "xml", "ubl", "viewing", "agent_read")  # 2.270.0: a reading agent is no edit


def _offer_drop(c, sheet, uid, did):
    """Deletes the quotation draft a button press made, when the office lets uid delete it (its admin; still a draft) and nobody
    changed it since (else "edited")."""
    from ..office.docref import ofd_deleted
    from ..office.ledger import ofx_locked, ofx_log
    from ..office.model import office_role
    oid = sh2_office(c, sheet, uid, write=True)
    r = c.execute("SELECT * FROM office_docs WHERE id=?", (did,)).fetchone()
    if not r:
        return True  # already gone
    if not oid or r["org_id"] != oid or office_role(c, uid, oid) != "admin" or ofx_locked(r) or r["status"] != "draft":
        return False
    if c.execute("SELECT 1 FROM office_signoffs WHERE doc_id=? AND org_id=? LIMIT 1", (did, oid)).fetchone():
        return False
    q = ",".join("?" * len(SH2_OFFER_UNTOUCHED))
    if c.execute(f"SELECT 1 FROM office_doc_log WHERE doc_id=? AND org_id=? AND action NOT IN ({q}) LIMIT 1",
                 (did, oid, *SH2_OFFER_UNTOUCHED)).fetchone():
        return "edited"  # 2.270.0 B (#3021): changed in the office since the press (items, client, texts ...): the work stays
    ofx_log(c, oid, "delete", doc_id=did, detail={"number": r["number"], "status": r["status"]})
    c.execute("DELETE FROM office_docs WHERE id=? AND org_id=?", (did, oid))
    ofd_deleted(c, did)  # 2.199.0 G (#2742): its folder node goes with it
    return True


# ---------------------------------------------------------------- routes
def _bump_area(c, area):
    """The change counter of another area too (core/db.py bump counts only the route's own: /api/sheets): the task lists /
    the office of the other devices reload the new tasks / the draft."""
    c.execute("INSERT INTO settings(key,value) VALUES(?, '1') ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(settings.value AS BIGINT)+1 AS TEXT)",
              ("version:" + area,))


def _ok(c, sid, out, areas=()):
    for a in areas:
        _bump_area(c, a)
    bump(c)
    c.commit()
    out["rev"] = sh_reload(c, sid)["rev"]
    return jsonify(out)


@app.get("/api/sheets/<int:sid>/links")
def sh2_links_get(sid):
    """The marks of the rows / the sheet and what the step-2 dialogs offer."""
    c = db()
    r, uid = _gate(c, sid, write=False)
    rl = [x[0] for x in c.execute("SELECT DISTINCT k.list_id FROM sheet_links k JOIN sheet_rows w ON w.id=k.row_id WHERE k.sheet_id=? "
                                  "AND k.kind='row' AND k.undone_at IS NULL AND w.deleted_at IS NULL", (sid,)).fetchall()]
    out = {"links": sh2_links(c, r, uid), **sh2_offers(c, r, uid)}
    out["row_lists"] = [x for x in rl if any(l["id"] == x for l in out["lists"])]  # "fetch new tasks of …" (visible lists only)
    return jsonify(out)


@app.post("/api/sheets/<int:sid>/to-tasks")
def sh2_to_tasks_post(sid):
    """{list_id, title_col, due_col?, notes_col?, rows?: [row ids]} -> {batch, list_id, tasks: [{row_id, task_id, title}], skipped}.
    Rows without a title and rows carried over before are skipped."""
    c = db()
    r, uid = _gate(c, sid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    return _ok(c, sid, sh2_to_tasks(c, r, uid, b), ("tasks",))


@app.post("/api/sheets/<int:sid>/to-offer")
def sh2_to_offer_post(sid):
    """{desc_col, qty_col?, unit_col?, price_col?, client_id?, title?, rows?} -> {batch, doc_id, number, items} (a draft)."""
    c = db()
    r, uid = _gate(c, sid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    return _ok(c, sid, sh2_to_offer(c, r, uid, b), ("office",))


@app.post("/api/sheets/<int:sid>/rows-from-list")
def sh2_rows_from_list_post(sid):
    """{list_id} -> {batch, rows: [row ids], added, more}: the list's tasks without a row in this sheet yet (all on the first press)."""
    c = db()
    r, uid = _gate(c, sid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    return _ok(c, sid, sh2_rows_from_list(c, r, uid, b))


@app.post("/api/sheets/<int:sid>/links/<batch>/undo")
def sh2_undo_post(sid, batch):
    c = db()
    r, uid = _gate(c, sid)
    return _ok(c, sid, sh2_undo(c, r, uid, (batch or "")[:40]), ("tasks", "office"))


@app.post("/api/sheets/<int:sid>/links/<batch>/redo")
def sh2_redo_post(sid, batch):
    c = db()
    r, uid = _gate(c, sid)
    return _ok(c, sid, sh2_undo(c, r, uid, (batch or "")[:40], redo=True), ("tasks",))
