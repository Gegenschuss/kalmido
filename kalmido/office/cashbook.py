"""2.121.0 B (#2095): the cash book of an office area: cash boxes, cash entries, day closings, change log, CSV / PDF.

Cash boxes (office_cashbooks: name, opening balance with its day; one default box per office, made on the first look,
more possible; archived instead of deleted). Entries (office_cash_entries): a number per box without gaps (given under
write_lock, unique index (book_id, no)), day, in | out, amount (decimal text, office currency), VAT rate 19 | 7 | 0, text
(encrypted at rest), category (the receipt categories as choice, free text allowed), optionally a receipt (a document of
the office's documents space the person sees) or an invoice paid in cash. Nothing is ever deleted: an entry is taken back
only by a cancellation = a counter entry with a new number pointing at the original (storno_of; both stay, the original
shows as cancelled). A day closing (office_cash_closings) freezes every entry up to that day for good (409 afterwards, no
entries before it any more); an open day may still change entries, every change is logged (office_cash_log, values before,
encrypted). The balance never goes below zero (a clear 400). The cash book does NOT count in the income/expense statement
in this package (receipts and invoice payments do; books.bk_euer is untouched) -- the note says so.

Every route: office_gate + office_org with the admin of the office area (like the logbook; members 403, agents and kids
403, ids of other areas 404); a person without an organisation is the admin of the personal office."""
import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal

from flask import jsonify, request, Response

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, lang, tr
from ..core.db import bump, db, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .logbook import _body, _day, _id, _text
from .model import ofx_name1, office_gate, office_org, office_settings

CB_DIRS = ("in", "out")
CB_VATS = ("19", "7", "0")
CB_NOTE = N_("The cash book records cash and its balance; it does not count in the income/expense statement (receipts and invoice payments do). Closed days cannot be changed, every change is logged. No tax advice.")  # noqa: E501
CB_FIELDS = ("day", "dir", "amount", "vat_pct", "text", "category", "node_id", "invoice_id")
CB_ACTIONS = {"create": N_("Created"), "change": N_("Changed"), "cancel": N_("Cancelled"), "close": N_("Day closed"),
              "book_create": N_("Cash box created"), "book_change": N_("Cash box changed")}
MAX_BOOKS = 20
MAX_AMOUNT = Decimal(10 ** 9)


def cb_log_fk_migrate(c):
    """2.144.11 (#2354, review N3): office_cash_log.entry_id was ON DELETE CASCADE (2.121-2.144.10), now ON DELETE SET NULL:
    should a tool ever remove an entry, its change log stays (GoBD). Runs on every start and changes only a CASCADE
    constraint (also one a restore of an older backup brings back); there is no delete path, so older versions behave the
    same with either rule (rollback needs nothing)."""
    for (name,) in c.execute(
            "SELECT con.conname FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid "  # pg-ok: catalog oid (Postgres only)
            "JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(con.conkey) "  # pg-ok: catalog oid (Postgres only)
            "WHERE n.nspname=current_schema() AND t.relname='office_cash_log' AND con.contype='f' "
            "AND a.attname='entry_id' AND con.confdeltype='c'").fetchall():
        c.execute(f'ALTER TABLE office_cash_log DROP CONSTRAINT "{name}"')
        c.execute("ALTER TABLE office_cash_log ADD CONSTRAINT office_cash_log_entry_id_fkey FOREIGN KEY (entry_id) "
                  "REFERENCES office_cash_entries(id) ON DELETE SET NULL")


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy
from .homecur import hc_home  # noqa: E402  2.189.0 B (#2475)


def _today():
    from ..core.db import local_now  # 2.121.0 review N2: the instance's day, like the year (books)
    return local_now().date().isoformat()


def _not_future(day):
    """2.121.0 review M1: an entry (also a cancellation) lies at most one day ahead (time zones), never in the future."""
    if day > (date.fromisoformat(_today()) + timedelta(days=1)).isoformat():
        raise BadInput(tr("A cash entry cannot lie in the future."))
    return day


def _amount(v, name="amount", zero=False):
    """A money amount (> 0, or >= 0 with zero) -> Decimal with two places."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)) or v == "":
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        d = dec(v.strip() if isinstance(v, str) else v, "NaN")
    except Exception:
        raise BadInput(tr("Invalid value: {0}", name))
    if d.is_nan() or not d.is_finite():
        raise BadInput(tr("Invalid value: {0}", name))
    d = money(d)  # 2.121.0 review M2: rounded first, so 0.004 is no entry of 0,00
    if d < 0 or (d == 0 and not zero) or d > MAX_AMOUNT:
        raise BadInput(tr("Invalid value: {0}", name))
    return d


def _de(v):
    return "" if v in (None, "") else str(v).replace(".", ",")


def _locked(msg):
    return Denied(409, tr(msg))


# ---------------------------------------------------------------- cash boxes
def _book(c, oid, bid):
    r = c.execute("SELECT * FROM office_cashbooks WHERE id=? AND org_id=?", (bid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def cb_last_closed(c, bid):
    r = c.execute("SELECT MAX(day) FROM office_cash_closings WHERE book_id=?", (bid,)).fetchone()
    return r[0] if r and r[0] else ""


def _rows(c, oid, bid, full=False):
    """Every entry of a box in booking order (day, number). 2.144.11 (#2354, review N4): nothing is decrypted here -- the
    balance, the counts and the checks need only the plain columns (default: no text at all); full=True = every column, the
    text still encrypted (cb_list decrypts just the entries it shows)."""
    cols = "*" if full else "id, no, day, dir, amount, storno_of, created_by"
    return [dict(r) for r in
            c.execute(f"SELECT {cols} FROM office_cash_entries WHERE org_id=? AND book_id=? ORDER BY day, no", (oid, bid))]


def _signed(r):
    a = dec(r["amount"])
    return a if r["dir"] == "in" else -a


def cb_negative(opening, rows):
    """The first (day, balance) where the running balance goes below zero, else None. rows: dicts with day, dir, amount, no."""
    bal = dec(opening)
    for r in sorted(rows, key=lambda x: (x["day"], x["no"])):
        bal += _signed(r)
        if bal < 0:
            return r["day"], bal
    return None


def _neg_check(opening, rows):
    hit = cb_negative(opening, rows)
    if hit:
        raise BadInput(tr("The cash balance would drop below zero on {0} ({1}). Book the income first or check the amount.",
                          hit[0], _de(dstr(hit[1])) if lang() != "en" else dstr(hit[1])))


def cb_balance(opening, rows, upto=None):
    bal = dec(opening)
    for r in rows:
        if upto is None or r["day"] <= upto:
            bal += _signed(r)
    return money(bal)


def cb_default(c, oid, uid):
    """The default cash box of an office: made on the first look (opening 0.00 today)."""
    if c.execute("SELECT 1 FROM office_cashbooks WHERE org_id=?", (oid,)).fetchone():
        return
    write_lock(c, f"office_cashbook_{oid}")
    if c.execute("SELECT 1 FROM office_cashbooks WHERE org_id=?", (oid,)).fetchone():
        return
    ts = iso(now_utc())
    bid = insert_id(c, "INSERT INTO office_cashbooks(org_id, name, opening, opening_day, is_default, archived, created_by, created_at, updated_at) "
                       "VALUES(?,?,?,?,1,0,?,?,?)", (oid, tr("Cash box"), "0.00", _today(), uid, ts, ts))
    _log(c, oid, bid, None, "book_create", {"name": tr("Cash box"), "opening": "0.00", "opening_day": _today()}, uid)
    c.commit()


def cb_books(c, oid):
    out = []
    for r in c.execute("SELECT * FROM office_cashbooks WHERE org_id=? ORDER BY archived, is_default DESC, lower(name), id", (oid,)):
        rows = _rows(c, oid, r["id"])
        out.append({"id": r["id"], "name": r["name"], "opening": dstr(r["opening"]), "opening_day": r["opening_day"], "is_default": bool(r["is_default"]),
                    "archived": r["archived"], "balance": dstr(cb_balance(r["opening"], rows)), "last_closed": cb_last_closed(c, r["id"]),
                    "entries": len(rows)})
    return out


def _book_public(c, oid, bid):
    return next(b for b in cb_books(c, oid) if b["id"] == bid)


@app.get("/api/office/cashbooks")
def cb_books_get():
    """-> {books, categories (the receipt categories), currency, note, today}: what the cash book view needs to start."""
    from ..receipts.suggest import rc_categories
    from .books import bk_ws
    c, uid, oid = _ctx()
    cb_default(c, oid, uid)
    s = office_settings(c, oid)
    return jsonify(books=cb_books(c, oid), categories=rc_categories(c, bk_ws(c, oid)), currency=hc_home(s),
                   note=tr(CB_NOTE), today=_today())


@app.get("/api/office/cashbooks/links")
def cb_links_get():
    """-> {receipts (the last 13 months the person sees: node_id, title, date, amount), invoices (issued: id, number, date,
    client)}: what an entry may point at."""
    from .books import bk_receipts
    c, uid, oid = _ctx()
    to = date.fromisoformat(_today())
    rcs = bk_receipts(c, oid, (to - timedelta(days=400)).isoformat(), (to + timedelta(days=1)).isoformat(), uid)
    rcs = [{"node_id": r["node_id"], "title": r["title"], "date": r["date"], "amount": dstr(r["amount"])} for r in reversed(rcs)][:300]
    inv = [{"id": r["id"], "number": r["number"], "date": r["date"], "client": r["name"] or ""} for r in c.execute(
        "SELECT d.id, d.number, d.date, cl.name FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id "
        "WHERE d.org_id=? AND d.kind='invoice' AND d.status<>'draft' AND d.trial=0 ORDER BY d.date DESC, d.id DESC LIMIT 300", (oid,))]
    return jsonify(receipts=rcs, invoices=inv)


def _book_clean(b, cur=None):
    out = {}
    if "name" in b or cur is None:
        out["name"] = _text(b.get("name"), "name", 80)
        if not out["name"]:
            raise BadInput(tr("Please enter a name"))
    if "opening" in b or cur is None:
        out["opening"] = dstr(_amount(b.get("opening") if b.get("opening") not in (None, "") else "0", "opening", zero=True))
    if "opening_day" in b or cur is None:
        out["opening_day"] = _day(b.get("opening_day") or _today(), "opening_day")
    if "archived" in b and cur is not None:
        out["archived"] = 1 if b.get("archived") else 0
    return out


@app.post("/api/office/cashbooks")
def cb_book_post():
    """Another cash box {name, opening "0.00", opening_day}. 201 the box."""
    c, uid, oid = _ctx()
    row = _book_clean(_body())
    write_lock(c, f"office_cashbook_{oid}")
    if c.execute("SELECT COUNT(*) FROM office_cashbooks WHERE org_id=?", (oid,)).fetchone()[0] >= MAX_BOOKS:
        raise BadInput(tr("Too many entries"))
    ts = iso(now_utc())
    first = not c.execute("SELECT 1 FROM office_cashbooks WHERE org_id=?", (oid,)).fetchone()
    vals = dict(row)
    row.update(org_id=oid, is_default=1 if first else 0, archived=0, created_by=uid, created_at=ts, updated_at=ts)
    bid = insert_id(c, f"INSERT INTO office_cashbooks({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _log(c, oid, bid, None, "book_create", vals, uid)
    bump(c)
    c.commit()
    return jsonify(_book_public(c, oid, bid)), 201


@app.patch("/api/office/cashbooks/<int:bid>")
def cb_book_patch(bid):
    """Partial {name, opening, opening_day, archived 0|1}. The opening balance / day only while no day is closed (409) and
    never after the first entry / below zero; the default box cannot be archived."""
    c, uid, oid = _ctx()
    _book(c, oid, bid)
    write_lock(c, f"office_cash_{bid}")
    cur = _book(c, oid, bid)
    row = _book_clean(_body(), cur)
    before = {"name": cur["name"], "opening": dstr(cur["opening"]), "opening_day": cur["opening_day"], "archived": cur["archived"]}
    prev = {k: before[k] for k in row if before[k] != row[k]}
    if not prev:
        return jsonify(_book_public(c, oid, bid))
    rows = _rows(c, oid, bid)
    if ("opening" in prev or "opening_day" in prev) and cb_last_closed(c, bid):
        raise _locked(N_("The opening balance cannot change after a day closing."))
    if "opening_day" in prev and rows and rows[0]["day"] < row["opening_day"]:
        raise BadInput(tr("There are entries before this day."))
    if "opening" in prev and rows:  # 2.190.0 D (#2496): fixed with the first entry (a correction entry changes the balance)
        raise _locked(N_("The opening balance cannot change after the first entry."))
    if prev.get("archived") == 0 and cur["is_default"]:
        raise BadInput(tr("The default cash box cannot be archived."))
    row["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE office_cashbooks SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [bid, oid])
    _log(c, oid, bid, None, "book_change", prev, uid)
    bump(c)
    c.commit()
    return jsonify(_book_public(c, oid, bid))


# ---------------------------------------------------------------- entries
def _log(c, oid, bid, eid, action, prev, uid):
    row = oc_enc_fields(c, oid, "office_cash_log", {"org_id": oid, "book_id": bid, "entry_id": eid, "action": action,
                                                    "prev": json.dumps(prev, ensure_ascii=False), "by_user": uid, "at": iso(now_utc())})
    c.execute(f"INSERT INTO office_cash_log({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _entry(c, oid, eid):
    r = c.execute("SELECT * FROM office_cash_entries WHERE id=? AND org_id=?", (eid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _vals(d):
    out = {k: d.get(k) for k in CB_FIELDS}
    out["amount"] = dstr(d["amount"]) if d.get("amount") not in (None, "") else None
    return out


def _node_ok(c, oid, uid, v):
    """A receipt the person sees in the office's documents space (404 otherwise) or None."""
    from ..files.store import fs_chain, fs_deleted, fs_role
    from .books import bk_ws
    nid = _id(v, "node_id")
    if nid is None:
        return None
    r = c.execute("SELECT n.id FROM fs_nodes n JOIN doc_meta d ON d.node_id=n.id WHERE n.id=? AND n.kind='file' AND d.ws=?",
                  (nid, bk_ws(c, oid))).fetchone()
    ch = fs_chain(c, nid) if r else []
    if not r or fs_deleted(ch) or not fs_role(c, nid, uid, ch):
        raise Denied(404)
    return nid


def _invoice_ok(c, oid, v):
    """An issued invoice of the office area (404 otherwise) or None."""
    iid = _id(v, "invoice_id")
    if iid is None:
        return None
    # 2.144.10 B (#2576): a cash book entry never names a trial invoice
    if not c.execute("SELECT 1 FROM office_docs WHERE id=? AND org_id=? AND kind='invoice' AND status<>'draft' AND trial=0",
                     (iid, oid)).fetchone():
        raise Denied(404)
    return iid


def _entry_clean(c, oid, uid, b, cur=None):
    new = cur is None
    out = {}
    if "day" in b or new:
        out["day"] = _not_future(_day(b.get("day") or _today()))
    if "dir" in b or new:
        if b.get("dir") not in CB_DIRS:
            raise BadInput(tr("Invalid value: {0}", "dir"))
        out["dir"] = b["dir"]
    if "amount" in b or new:
        out["amount"] = dstr(_amount(b.get("amount")))
    if "vat_pct" in b or new:
        v = b.get("vat_pct")
        v = str(v) if isinstance(v, int) and not isinstance(v, bool) else v
        if v in (None, ""):
            v = None
        elif v not in CB_VATS:
            raise BadInput(tr("Invalid value: {0}", "vat_pct"))
        out["vat_pct"] = v
    if "text" in b or new:
        out["text"] = _text(b.get("text"), "text", 300)
        if not out["text"]:
            raise BadInput(tr("Please enter a text"))
    if "category" in b or new:
        out["category"] = _text(b.get("category"), "category", 60)
    if "node_id" in b or new:
        nid = _id(b.get("node_id"), "node_id")
        # the receipt linked already stays even when the person does not see it (another admin linked it)
        out["node_id"] = nid if cur is not None and nid is not None and nid == cur.get("node_id") else _node_ok(c, oid, uid, nid)
    if "invoice_id" in b or new:
        out["invoice_id"] = _invoice_ok(c, oid, b.get("invoice_id"))
    return out


def _day_rules(c, book, day):
    from .periodlock import period_need_open
    period_need_open(c, book["org_id"], day)  # 2.148.0 A (#2471): no entry in a locked month
    last = cb_last_closed(c, book["id"])
    if last and day <= last:
        raise _locked(N_("This day is closed already: book on a later day, or cancel the entry."))
    if day < book["opening_day"]:
        raise BadInput(tr("The day lies before the opening balance of the cash box ({0}).", book["opening_day"]))


def cb_public(c, oid, uid, rows, d, last, bal=None, names=None):
    """One entry for the client: + balance after it, cancelled_by / storno_of with their numbers, locked, receipt / invoice."""
    from ..files.store import fs_chain, fs_deleted, fs_role
    by_id = {r["id"]: r for r in rows}
    canc = next((r for r in rows if r.get("storno_of") == d["id"]), None)
    node = None
    if d.get("node_id"):
        ch = fs_chain(c, d["node_id"])
        if ch and not fs_deleted(ch) and fs_role(c, d["node_id"], uid, ch):
            node = {"id": d["node_id"], "name": ch[0]["name"] or ""}
    inv = None
    if d.get("invoice_id"):
        r = c.execute("SELECT id, number FROM office_docs WHERE id=? AND org_id=?", (d["invoice_id"], oid)).fetchone()
        inv = {"id": r["id"], "number": r["number"]} if r else None
    so = by_id.get(d.get("storno_of"))
    return dict(_vals(d), id=d["id"], no=d["no"], book_id=d["book_id"], node=node, invoice=inv, storno_of=d.get("storno_of"),
                storno_of_no=so["no"] if so else None, cancelled_by=canc["id"] if canc else None, cancelled_by_no=canc["no"] if canc else None,
                locked=bool(last and d["day"] <= last), balance=dstr(bal) if bal is not None else None,
                by=(names or {}).get(d.get("created_by"), ""), created_at=d["created_at"], updated_at=d["updated_at"])


def _names(c, ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {r["id"]: r["display_name"] or r["username"] for r in
            c.execute(f"SELECT id, display_name, username FROM users WHERE id IN ({','.join('?' * len(ids))})", ids)}


def cb_list(c, oid, uid, book, frm=None, to=None):
    """The entries of a box in [frm, to] in booking order, each with the running balance after it."""
    rows = _rows(c, oid, book["id"], full=True)
    last = cb_last_closed(c, book["id"])
    names = _names(c, [r.get("created_by") for r in rows])
    bal, out = dec(book["opening"]), []
    for r in rows:
        bal += _signed(r)
        if (frm and r["day"] < frm) or (to and r["day"] > to):
            continue
        out.append(cb_public(c, oid, uid, rows, oc_dec_fields(c, oid, "office_cash_entries", r), last, bal, names))
    return out, rows, last


def _one(c, oid, uid, eid):
    r = _entry(c, oid, eid)
    book = _book(c, oid, r["book_id"])
    ents, _, _ = cb_list(c, oid, uid, book, r["day"], r["day"])  # 2.144.11 (#2354, N4): decrypts only that day
    return next(e for e in ents if e["id"] == eid)


def _range():
    """?from=&to= or ?year= (default: this year) -> (from, to, year or None)."""
    from .books import _year
    frm, to = request.args.get("from"), request.args.get("to")
    if frm or to:
        f = _day(frm, "from") if frm else "0000-01-01"
        t = _day(to, "to") if to else "9999-12-31"
        if f > t:
            raise BadInput(tr("Invalid value: {0}", "to"))
        return f, t, None
    y = _year(request.args.get("year"))
    return f"{y}-01-01", f"{y}-12-31", y


def cb_closings(c, oid, bid, frm="0000-01-01", to="9999-12-31"):
    names = {}
    out = []
    for r in c.execute("SELECT * FROM office_cash_closings WHERE org_id=? AND book_id=? AND day>=? AND day<=? ORDER BY day", (oid, bid, frm, to)):
        names.setdefault(r["closed_by"], None)
        out.append({"day": r["day"], "opening": dstr(r["opening"]), "sum_in": dstr(r["sum_in"]), "sum_out": dstr(r["sum_out"]),
                    "closing": dstr(r["closing"]), "count": r["count"], "closed_by": r["closed_by"], "closed_at": r["closed_at"]})
    nm = _names(c, list(names))
    for x in out:
        x["by"] = nm.get(x.pop("closed_by"), "")
    return out


@app.get("/api/office/cashbooks/<int:bid>/entries")
def cb_entries_get(bid):
    """?year=YYYY | ?from=&to= -> {entries (newest first, balance = after the entry), closings, last_closed, balance, year}."""
    c, uid, oid = _ctx()
    book = _book(c, oid, bid)
    frm, to, y = _range()
    ents, rows, last = cb_list(c, oid, uid, book, frm, to)
    return jsonify(entries=list(reversed(ents)), closings=cb_closings(c, oid, bid, frm, to), last_closed=last,
                   balance=dstr(cb_balance(book["opening"], rows)), year=y, opening=dstr(book["opening"]), opening_day=book["opening_day"])


@app.post("/api/office/cashbooks/<int:bid>/entries")
def cb_entry_post(bid):
    """A new entry {day (default today), dir in|out, amount, vat_pct 19|7|0|null, text, category, node_id, invoice_id}.
    The next number of the box (no gaps); 409 on a closed day; 400 when the balance would drop below zero. 201 the entry."""
    c, uid, oid = _ctx()
    _book(c, oid, bid)
    row = _entry_clean(c, oid, uid, _body())
    write_lock(c, f"office_cash_{bid}")
    book = _book(c, oid, bid)
    if book["archived"]:
        raise _locked(N_("This cash box is archived."))
    _day_rules(c, book, row["day"])
    rows = _rows(c, oid, bid)
    no = (c.execute("SELECT MAX(no) FROM office_cash_entries WHERE book_id=?", (bid,)).fetchone()[0] or 0) + 1
    _neg_check(book["opening"], rows + [dict(row, no=no)])
    ts = iso(now_utc())
    plain = dict(row)
    row.update(org_id=oid, book_id=bid, no=no, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_cash_entries", row)
    eid = insert_id(c, f"INSERT INTO office_cash_entries({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _log(c, oid, bid, eid, "create", _vals(plain), uid)
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, uid, eid)), 201


@app.patch("/api/office/cash-entries/<int:eid>")
def cb_entry_patch(eid):
    """Partial entry (keys as POST) while its day is open (409 when closed, cancelled or itself a cancellation); logs the
    values before of every changed field."""
    c, uid, oid = _ctx()
    bid = _entry(c, oid, eid)["book_id"]
    write_lock(c, f"office_cash_{bid}")
    book = _book(c, oid, bid)
    if book["archived"]:  # 2.121.0 review N1: an archived box takes no changes (like no new entries)
        raise _locked(N_("This cash box is archived."))
    cur = oc_dec_fields(c, oid, "office_cash_entries", _entry(c, oid, eid))
    last = cb_last_closed(c, bid)
    if last and cur["day"] <= last:
        raise _locked(N_("This entry lies on a closed day and cannot change any more; cancel it instead."))
    from .periodlock import period_need_open
    period_need_open(c, oid, cur["day"])  # 2.148.0 A (#2471)
    rows = _rows(c, oid, bid)
    if cur.get("storno_of") or any(r.get("storno_of") == eid for r in rows):
        raise _locked(N_("A cancelled entry or a cancellation cannot change."))
    row = _entry_clean(c, oid, uid, _body(), cur)
    before, after = _vals(cur), _vals(dict(cur, **row))
    prev = {k: before[k] for k in CB_FIELDS if before[k] != after[k]}
    if prev:
        if "day" in prev:
            _day_rules(c, book, row["day"])
        _neg_check(book["opening"], [dict(r, **row) if r["id"] == eid else r for r in rows])
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_cash_entries", row)
        c.execute(f"UPDATE office_cash_entries SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [eid, oid])
        _log(c, oid, bid, eid, "change", prev, uid)
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, uid, eid))


@app.post("/api/office/cash-entries/<int:eid>/cancel")
def cb_entry_cancel(eid):
    """Cancels an entry {day (default today)}: a counter entry (the other direction, same amount, VAT, text, category) with
    the next number and storno_of = the original; both stay. 409 when it is cancelled already or itself a cancellation, or
    the day is closed. 201 {entry: the counter entry, original}."""
    c, uid, oid = _ctx()
    bid = _entry(c, oid, eid)["book_id"]
    b = _body()
    day = _not_future(_day(b.get("day") or _today()))
    write_lock(c, f"office_cash_{bid}")
    book = _book(c, oid, bid)
    if book["archived"]:  # 2.121.0 review N1
        raise _locked(N_("This cash box is archived."))
    cur = oc_dec_fields(c, oid, "office_cash_entries", _entry(c, oid, eid))
    rows = _rows(c, oid, bid)
    if cur.get("storno_of") or any(r.get("storno_of") == eid for r in rows):
        raise _locked(N_("This entry is cancelled already or is itself a cancellation."))
    if day < cur["day"]:
        day = cur["day"]
    _day_rules(c, book, day)
    no = (c.execute("SELECT MAX(no) FROM office_cash_entries WHERE book_id=?", (bid,)).fetchone()[0] or 0) + 1
    row = {"day": day, "dir": "out" if cur["dir"] == "in" else "in", "amount": dstr(cur["amount"]), "vat_pct": cur.get("vat_pct"),
           "text": cur["text"], "category": cur.get("category") or "", "node_id": None, "invoice_id": None}
    _neg_check(book["opening"], rows + [dict(row, no=no)])
    ts = iso(now_utc())
    plain = dict(row)
    row.update(org_id=oid, book_id=bid, no=no, storno_of=eid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_cash_entries", row)
    sid = insert_id(c, f"INSERT INTO office_cash_entries({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _log(c, oid, bid, sid, "create", dict(_vals(plain), storno_of=cur["no"]), uid)
    _log(c, oid, bid, eid, "cancel", {"by_no": no}, uid)
    bump(c)
    c.commit()
    return jsonify(entry=_one(c, oid, uid, sid), original=_one(c, oid, uid, eid)), 201


def cb_log_rows(c, oid, bid, entry_id=None):
    sql, args = ("SELECT l.*, u.display_name, u.username FROM office_cash_log l LEFT JOIN users u ON u.id=l.by_user "
                 "WHERE l.org_id=? AND l.book_id=?"), [oid, bid]
    if entry_id is not None:
        sql += " AND l.entry_id=?"
        args.append(entry_id)
    nos = {r[0]: r[1] for r in c.execute("SELECT id, no FROM office_cash_entries WHERE book_id=?", (bid,))}
    out = []
    for r in c.execute(sql + " ORDER BY l.at, l.id", args):
        d = oc_dec_fields(c, oid, "office_cash_log", r)
        try:
            prev = json.loads(d.get("prev") or "{}")
        except ValueError:
            prev = {}
        prev = prev if isinstance(prev, dict) else {}
        out.append({"id": d["id"], "entry_id": d["entry_id"], "no": nos.get(d["entry_id"]) if d["entry_id"] else prev.get("no"),  # #2603: a deleted one keeps its no
                    "action": d["action"], "prev": prev, "by": d.get("display_name") or d.get("username") or "", "at": d["at"]})
    return out


@app.get("/api/office/cash-entries/<int:eid>/log")
def cb_entry_log(eid):
    """The change log of one entry, oldest first."""
    c, uid, oid = _ctx()
    r = _entry(c, oid, eid)
    return jsonify(log=cb_log_rows(c, oid, r["book_id"], eid))


# ---------------------------------------------------------------- day closing
def cb_close_plan(c, oid, book, day):
    """What closing `day` means: one row per open day up to it with entries (and the day itself) ->
    {day, from, opening, sum_in, sum_out, closing, count, days: [{day, opening, sum_in, sum_out, closing, count}]}."""
    last = cb_last_closed(c, book["id"])
    rows = _rows(c, oid, book["id"])
    opening = cb_balance(book["opening"], rows, last) if last else money(dec(book["opening"]))
    days = sorted({r["day"] for r in rows if (not last or r["day"] > last) and r["day"] <= day} | {day})
    bal, plan, tin, tout, n = opening, [], Decimal(0), Decimal(0), 0
    for d in days:
        din = sum((dec(r["amount"]) for r in rows if r["day"] == d and r["dir"] == "in"), Decimal(0))
        dout = sum((dec(r["amount"]) for r in rows if r["day"] == d and r["dir"] == "out"), Decimal(0))
        cnt = sum(1 for r in rows if r["day"] == d)
        plan.append({"day": d, "opening": dstr(bal), "sum_in": dstr(din), "sum_out": dstr(dout), "closing": dstr(bal + din - dout), "count": cnt})
        bal += din - dout
        tin, tout, n = tin + din, tout + dout, n + cnt
    return {"day": day, "from": plan[0]["day"], "opening": dstr(opening), "sum_in": dstr(tin), "sum_out": dstr(tout), "closing": dstr(bal),
            "count": n, "days": plan, "last_closed": last}


def _close_day(c, book, b):
    day = _day(b.get("day") or _today())
    last = cb_last_closed(c, book["id"])
    if last and day <= last:
        raise _locked(N_("This day is closed already."))
    if day > _today():
        raise BadInput(tr("Only days up to today can be closed."))
    if day < book["opening_day"]:
        raise BadInput(tr("The day lies before the opening balance of the cash box ({0}).", book["opening_day"]))
    return day


@app.get("/api/office/cashbooks/<int:bid>/closing")
def cb_closing_get(bid):
    """?day= (default today) -> the day closing preview (cb_close_plan)."""
    c, uid, oid = _ctx()
    book = _book(c, oid, bid)
    return jsonify(cb_close_plan(c, oid, book, _close_day(c, book, request.args)))


@app.post("/api/office/cashbooks/<int:bid>/closing")
def cb_closing_post(bid):
    """{day} closes the day (and every open day before it with entries) for good: opening, in, out, closing balance per
    day; afterwards no entry up to it changes and none is booked before it. No undo. 201 the plan + closings."""
    c, uid, oid = _ctx()
    _book(c, oid, bid)
    write_lock(c, f"office_cash_{bid}")
    book = _book(c, oid, bid)
    plan = cb_close_plan(c, oid, book, _close_day(c, book, _body()))
    ts = iso(now_utc())
    for p in plan["days"]:
        c.execute("INSERT INTO office_cash_closings(org_id, book_id, day, opening, sum_in, sum_out, closing, count, closed_by, closed_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (oid, bid, p["day"], p["opening"], p["sum_in"], p["sum_out"], p["closing"], p["count"], uid, ts))
    _log(c, oid, bid, None, "close", {k: plan[k] for k in ("day", "from", "opening", "sum_in", "sum_out", "closing", "count")}, uid)
    bump(c)
    c.commit()
    return jsonify(dict(plan, closings=cb_closings(c, oid, bid, plan["from"], plan["day"]))), 201


@app.get("/api/office/cashbooks/<int:bid>/log")
def cb_book_log(bid):
    """The change log of a box (entries, closings, the box itself), oldest first."""
    c, uid, oid = _ctx()
    _book(c, oid, bid)
    return jsonify(log=cb_log_rows(c, oid, bid))


# ---------------------------------------------------------------- the hint on a receipt
@app.get("/api/docs/<int:nid>/cashbook")
def cb_doc_hint(nid):
    """-> {entries: [{id, no, day, book}]}: the cash entries pointing at this receipt -- only for the admin of the office
    the document belongs to (everybody else: an empty list; a document the person does not see: 404). 2.144.11 (#2354,
    review N6): the office gate like every cash book route (agents, kids and persons without the office: 403)."""
    from ..files.store import fs_role
    from .model import office_role, pb_personal
    c = db()
    uid = office_gate(c)
    m = c.execute("SELECT ws FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
    if not m or not fs_role(c, nid, uid):
        raise Denied(404)
    ws = m["ws"] or ""
    oid = None
    if ws.startswith("o") and ws[1:].isdigit():
        oid = int(ws[1:]) if office_role(c, uid, int(ws[1:])) == "admin" else None
    elif ws == f"u{uid}":
        oid = pb_personal(c, uid, create=False)
    if not oid:
        return jsonify(entries=[])
    out = [{"id": r["id"], "no": r["no"], "day": r["day"], "book": r["name"]} for r in c.execute(
        "SELECT e.id, e.no, e.day, b.name FROM office_cash_entries e JOIN office_cashbooks b ON b.id=e.book_id "
        "WHERE e.org_id=? AND e.node_id=? ORDER BY e.day, e.no", (oid, nid))]
    return jsonify(entries=out)


# ---------------------------------------------------------------- exports
def _export_data(c, oid, uid):
    bid = _id(request.args.get("book_id"), "book_id")
    if bid is None:
        cb_default(c, oid, uid)
        bid = next(b["id"] for b in cb_books(c, oid))
    frm, to, y = _range()
    return cb_export_data(c, oid, uid, _book(c, oid, bid), frm, to, y)


def cb_export_data(c, oid, uid, book, frm, to, y=None):
    """2.146.0 D (#2468): what the CSV / PDF of cash book row book show for [frm, to] (also without a request: the
    retention export, admin/retexport.py)."""
    bid = book["id"]
    ents, rows, last = cb_list(c, oid, uid, book, frm, to)
    closings = cb_closings(c, oid, bid, frm, to)
    log = [r for r in cb_log_rows(c, oid, bid) if frm <= r["at"][:10] <= to or (r["entry_id"] and any(e["id"] == r["entry_id"] for e in ents))]
    start = cb_balance(book["opening"], [r for r in rows if r["day"] < frm]) if frm > book["opening_day"] else money(dec(book["opening"]))
    end = dec(ents[-1]["balance"]) if ents else start
    return book, frm, to, y, ents, closings, log, start, money(end)


def _label(frm, to, y):
    return str(y) if y else f"{frm} – {to}"


def _num(v):
    return _de(v) if lang() != "en" else (v or "")


def _ref(e):
    if e["storno_of_no"]:
        return tr("Cancels no. {0}", e["storno_of_no"])
    if e["cancelled_by_no"]:
        return tr("Cancelled by no. {0}", e["cancelled_by_no"])
    return ""


def _link(e):
    parts = []
    if e.get("node"):
        parts.append(tr("Receipt") + ": " + e["node"]["name"])
    if e.get("invoice"):
        parts.append(tr("Invoice") + " " + (e["invoice"]["number"] or ""))
    return ", ".join(parts)


def _prev_text(prev):
    labels = {"day": tr("Date"), "dir": tr("Kind"), "amount": tr("Amount"), "vat_pct": tr("VAT"), "text": tr("Text"), "category": tr("Category"),
              "node_id": tr("Receipt"), "invoice_id": tr("Invoice"), "name": tr("Name"), "opening": tr("Opening balance"),
              "opening_day": tr("Opening day"), "archived": tr("Archived"), "storno_of": tr("Cancels no. {0}", "").strip(),
              "by_no": tr("Cancelled by no. {0}", "").strip(), "from": tr("From"), "sum_in": tr("Income"), "sum_out": tr("Expense"),
              "closing": tr("Closing balance"), "count": tr("Entries")}
    out = []
    for k, v in prev.items():
        if k == "dir":
            v = tr("Income") if v == "in" else tr("Expense")
        elif k in ("amount", "opening", "sum_in", "sum_out", "closing"):
            v = _num(v)
        out.append(f"{labels.get(k, k)}: {'' if v is None else v}")
    return ", ".join(out)


@app.get("/api/office/cashbook.csv")
def cb_csv():
    """?book_id=&year= | &from=&to= -> the entries (number, date, text, income, expense, VAT, balance, cancellation link),
    the day closings and the change log (semicolon, decimal comma like the EUeR CSV)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    book, frm, to, y, ents, closings, log, start, end = _export_data(c, oid, uid)
    data = cb_csv_text(book, frm, to, y, ents, closings, log, start, end)
    ofx_log(c, oid, "export", target="cashbook", detail={"what": "cashbook.csv", "book_id": book["id"], "from": frm, "to": to})
    c.commit()
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="cashbook-{_label(frm, to, y).replace(" – ", "_")}.csv"', "Cache-Control": "no-store"})


def cb_csv_text(book, frm, to, y, ents, closings, log, start, end):
    """The cash book CSV (with the byte order mark) of cb_export_data's values; 2.146.0 D (#2468): also for the retention export."""
    from .books import bk_csv_cell as cell
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([cell(tr("Cash book")), cell(book["name"]), _label(frm, to, y)])
    w.writerow([tr("Opening balance"), _de(dstr(start))])
    w.writerow([tr("No."), tr("Date"), tr("Text"), tr("Category"), tr("Income"), tr("Expense"), tr("VAT"), tr("Balance"), tr("Cancellation"), tr("Receipt / invoice")])
    for e in ents:
        w.writerow([e["no"], e["day"], cell(e["text"]), cell(e["category"]), _de(e["amount"]) if e["dir"] == "in" else "", _de(e["amount"]) if e["dir"] == "out" else "",
                    f"{e['vat_pct']} %" if e["vat_pct"] else "", _de(e["balance"]), cell(_ref(e)), cell(_link(e))])
    w.writerow([tr("Closing balance"), _de(dstr(end))])
    w.writerow([])
    w.writerow([cell(tr("Day closings"))])
    w.writerow([tr("Date"), tr("Opening balance"), tr("Income"), tr("Expense"), tr("Closing balance"), tr("Entries"), tr("By"), tr("Time")])
    for x in closings:
        w.writerow([x["day"], _de(x["opening"]), _de(x["sum_in"]), _de(x["sum_out"]), _de(x["closing"]), x["count"], cell(x["by"]), x["closed_at"]])
    w.writerow([])
    w.writerow([cell(tr("Change log"))])
    w.writerow([tr("Time"), tr("No."), tr("Action"), tr("By"), tr("Values")])
    for r in log:
        w.writerow([r["at"], r["no"] or "", cell(tr(CB_ACTIONS.get(r["action"], r["action"]))), cell(r["by"]), cell(_prev_text(r["prev"]))])
    w.writerow([cell(tr(CB_NOTE))])
    return "﻿" + buf.getvalue()


def cb_pdf_bytes(c, oid, book, frm, to, y, ents, closings, log, start, end, lg):
    """A plain A4 PDF: the entries with balance, the day closings and the change log as appendix."""
    from .ledger import ofx_company
    from .pdf import A4_H, A4_W, C_INK2, C_RULE, _Page, pdf_money, pdf_write
    s = office_settings(c, oid)
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))
    lg = "de" if lg == "de" else "en"
    cur = hc_home(s)  # 2.189.0 B (#2475): the home currency
    x0, x1 = 40, A4_W - 40
    pages, st = [], {"pg": None, "y": 0}

    def page():
        st["pg"] = _Page()
        pages.append(st["pg"])
        st["y"] = 48

    def need(h):
        if st["pg"] is None or st["y"] + h > A4_H - 48:
            page()

    def m(v):
        return "" if v in (None, "") else pdf_money(v, lg, cur)

    page()
    pg = lambda: st["pg"]  # noqa: E731
    if company:
        pg().text(x0, st["y"], company, 10, color=C_INK2)
        st["y"] += 18
    pg().text(x0, st["y"], f"{tr('Cash book')} {book['name']} · {_label(frm, to, y)}", 15, bold=True)
    st["y"] += 26
    pg().text(x0, st["y"], f"{tr('Opening balance')}: {m(dstr(start))}", 9)
    st["y"] += 16
    # columns: no, date, text, income, expense, VAT, balance (x, width, align)
    cols = [(x0, 24, "r"), (x0 + 30, 48, "l"), (x0 + 82, 200, "l"), (x0 + 286, 58, "r"), (x0 + 348, 58, "r"), (x0 + 410, 26, "r"), (x1 - 70, 70, "r")]
    heads = (tr("No."), tr("Date"), tr("Text"), tr("Income"), tr("Expense"), tr("VAT"), tr("Balance"))

    def head():
        for (cx, cw, al), h in zip(cols, heads):
            pg().text(cx, st["y"], h, 7, color=C_INK2, align=al, width=cw)
        st["y"] += 11
        pg().line(x0, st["y"], x1, st["y"], color=C_RULE)
        st["y"] += 4

    head()
    for e in ents:
        if st["y"] + 20 > A4_H - 48:
            page()
            head()
        txt = e["text"] + (f" ({_ref(e)})" if _ref(e) else "")
        vals = (str(e["no"]), e["day"], txt[:52], m(e["amount"]) if e["dir"] == "in" else "", m(e["amount"]) if e["dir"] == "out" else "",
                f"{e['vat_pct']} %" if e["vat_pct"] else "", m(e["balance"]))
        for (cx, cw, al), val in zip(cols, vals):
            pg().text(cx, st["y"], val, 7, align=al, width=cw)
        st["y"] += 10
        sub = ", ".join(x for x in (e["category"], _link(e)) if x)
        if sub:
            pg().text(cols[2][0], st["y"], sub[:70], 6.5, color=C_INK2)
            st["y"] += 9
    if not ents:
        pg().text(x0, st["y"], tr("No entries in this period."), 8, color=C_INK2)
        st["y"] += 12
    st["y"] += 6
    pg().text(x0, st["y"], f"{tr('Closing balance')}: {m(dstr(end))}", 9, bold=True)
    st["y"] += 22
    need(40)
    pg().text(x0, st["y"], tr("Day closings"), 11, bold=True)
    st["y"] += 16
    for x in closings:
        need(22)
        st["y"] += pg().para(x0, st["y"], f"{x['day']} · {tr('Opening balance')} {m(x['opening'])} · {tr('Income')} {m(x['sum_in'])} · "
                             f"{tr('Expense')} {m(x['sum_out'])} · {tr('Closing balance')} {m(x['closing'])} · {x['by']}", 7.5, x1 - x0) + 3
    if not closings:
        pg().text(x0, st["y"], tr("None"), 8, color=C_INK2)
        st["y"] += 12
    st["y"] += 8
    need(30)
    st["y"] += pg().para(x0, st["y"], tr(CB_NOTE), 7.5, x1 - x0, color=C_INK2) + 10
    page()
    pg().text(x0, st["y"], tr("Change log"), 13, bold=True)
    st["y"] += 22
    for r in log:
        need(24)
        pg().text(x0, st["y"], f"{r['at'][:16].replace('T', ' ')} · {tr(CB_ACTIONS.get(r['action'], r['action']))} · {r['by']}"
                  + (f" · {tr('No.')} {r['no']}" if r["no"] else ""), 8, bold=True)
        st["y"] += 11
        t = _prev_text(r["prev"])
        if t:
            st["y"] += pg().para(x0 + 8, st["y"], t, 7.5, x1 - x0 - 8, color=C_INK2)
        st["y"] += 5
    if not log:
        pg().text(x0, st["y"], tr("None"), 8, color=C_INK2)
    return pdf_write(pages, {}, title=f"{tr('Cash book')} {_label(frm, to, y)}", author=company)


@app.get("/api/office/cashbook.pdf")
def cb_pdf():
    """?book_id=&year= | &from=&to= -> the cash book of the period as PDF (entries, day closings, change log)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    book, frm, to, y, ents, closings, log, start, end = _export_data(c, oid, uid)
    data = cb_pdf_bytes(c, oid, book, frm, to, y, ents, closings, log, start, end, lang())
    ofx_log(c, oid, "export", target="cashbook", detail={"what": "cashbook.pdf", "book_id": book["id"], "from": frm, "to": to})
    c.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="cashbook-{_label(frm, to, y).replace(" – ", "_")}.pdf"', "Cache-Control": "no-store"})
