"""2.72.0 (#1333): the household budget of "At home" (the model; the web routes are in life/budget_web.py).

A budget is a list (lists.life 'budget', no tasks): sharing it with the family is the usual sharing of the list, reading
needs the list visible, everything else the right to change the list. Like health lists a budget never reaches an agent
(core/access.py list_role / acx_lists_sql, lists.py, webhooks.py) and an API token only with the scope "private".
  categories  budget_cats      name (plain like a list name), kind out | in, a monthly limit (lim), sort
  entries     budget_entries   day, amount > 0, kind, title, note, counterpart, cat_id, recurring_id + rmonth (a booked
                               template: once per month), source manual | csv | recurring, dkey (duplicate check)
  templates   budget_recurring every month / quarter / year from a start month (until an end month); NO automatic
                               bookings: the month shows them as "open" until booked; optionally taken over from a contract
  receipts    budget_files     files of an entry, sealed like attachments
Amounts, titles, notes, counterparts and the limits are encrypted at rest with the key of the list's space (organisation,
else the owner's account; core/orgcrypt.py): sid = the space a row was encrypted with (0 = plain), so a row stays
readable while a moved list is resealed in the background (bud_settle, called by admin/orgcrypt_cli.py's passes).
Amounts are stored as text ("12.30"), every sum is made here in Decimal.
"""
import hashlib
import hmac
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from ..core.config import SECRET_KEY
from ..core.db import IntegrityError, iso, local_now, now_utc
from ..core.i18n import lang, N_, tr
from ..core.pg import insert_id, system_ctx
from ..core.access import Denied, health_hidden, list_role, vis_sql, WRITE_ROLES
from ..core import orgcrypt as oc
from ..core import csvimport as cx  # 2.140.0 B (#2134): the shared statement reader
from ..core import stmtfiles as sf  # 2.146.0 C (#2455): several files / a ZIP in one import
from ..personal.timetrack import BadInput

BUD_TABLES = ("budget_cats", "budget_recurring", "budget_entries")
BUD_AMOUNT_MAX = Decimal("10000000")
BUD_TITLE_MAX, BUD_NOTE_MAX, BUD_CP_MAX, BUD_CAT_MAX = 200, 1000, 200, 60
BUD_CATS_MAX, BUD_REC_MAX, BUD_FILES_MAX = 100, 500, 20
BUD_CSV_MAX, BUD_CSV_ROWS = 2 * 1024 * 1024, 3000
# 2.146.0 C (#2455): one import reads up to BUD_ROWS_MAX rows (several files / a ZIP, like the office's BNK_ROWS_MAX); the
# app takes them over in parts of at most BUD_CSV_ROWS rows per request, all under one import run (BUD_RUNS remembered)
BUD_ROWS_MAX, BUD_RUNS = 20000, 20
BUD_RUN_RE = re.compile(r"^[0-9a-f]{16}$")
IBAN_RE = cx.IBAN_RE
BUD_PER = {"month": 1, "quarter": 3, "year": 12}
BUD_KINDS = ("out", "in")
BUD_SOURCES = ("manual", "csv", "recurring")
BUD_TREND = 6
BUD_DATE_FORMATS = cx.DATE_FORMATS  # 2.140.0 B (#2134): core/csvimport.py
BUD_DEFAULT_CATS = ((N_("Housing"), "out"), (N_("Groceries"), "out"), (N_("Mobility"), "out"), (N_("Insurance"), "out"),
                    (N_("Leisure"), "out"), (N_("Other"), "out"), (N_("Salary"), "in"), (N_("Other income"), "in"))
BUD_MONTH_RE = re.compile(r"(20\d\d|19\d\d)-(0[1-9]|1[0-2])")


# ---------------------------------------------------------------- access
def bud_hidden(c=None, uid=None):
    """True when the request (an agent, an API token without the scope "private") must not see budgets (like health)."""
    return health_hidden(c, uid)


def bud_need_on(c, uid):
    from ..life.model import need_life
    need_life(c, uid, "budget")


def bud_need_list(c, uid, lid, write=False):
    """The budget list lid for the current person: 404 when it is no budget / not visible (agents, tokens without
    "private": never), 403 when a change needs the right to change the list."""
    if bud_hidden(c, uid):
        raise Denied(404)
    r = c.execute("SELECT life, archived FROM lists WHERE id=?", (int(lid),)).fetchone()
    if not r or r["life"] != "budget":
        raise Denied(404)
    role = list_role(c, int(lid), uid)
    if not role or role == "participant":  # a participant sees single tasks; a budget has none
        raise Denied(404)
    if write and role not in WRITE_ROLES:
        raise Denied(403)
    return role


def bud_obj(c, uid, table, oid, write=True):
    """The row of table (budget_cats / _entries / _recurring / _files) with id oid and its list checked; 404 otherwise."""
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    r = c.execute(f"SELECT * FROM {table} WHERE id=?", (oid,)).fetchone()
    if not r:
        raise Denied(404)
    bud_need_list(c, uid, r["list_id"], write)
    return r


# ---------------------------------------------------------------- encryption at rest
def bud_sid(c, lid):
    """The space whose key encrypts new rows of list lid now (0 = plain: no master key / encryption switched off)."""
    sid = oc.oc_list_space(c, lid)
    return int(sid) if sid and oc.oc_active_for(c, sid) else 0


def _key(c, sid, create=False):
    return oc.oc_key(c, sid, create=create) if sid else None


def bud_enc(c, table, sid, values):
    """values with the protected columns of table encrypted for space sid -> (values, sid actually used)."""
    key = _key(c, sid, True)
    if key is None:
        return dict(values), 0
    d = dict(values)
    for k in oc.FIELDS[table]:
        if d.get(k) not in (None, ""):
            d[k] = oc.oc_enc_k(key, sid, f"{table}.{k}", str(d[k]))
    return d, sid


def bud_dec(c, table, row):
    d = dict(row)
    sid = int(d.get("sid") or 0)
    key = None
    for k in oc.FIELDS[table]:
        if oc.oc_is_enc(d.get(k)):
            key = key or _key(c, sid)
            d[k] = oc.oc_dec_k(key, sid, f"{table}.{k}", d[k])
    return d


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"\s+", " ", s).strip()


def bud_dkey(c, lid, sid, day, amount, kind, title):
    """The keyed hash of an entry for the duplicate check (no plain column): HMAC with the space key (plain lists: a key
    from the server key); the list id is part of it, so equal entries of two lists never match."""
    key = _key(c, sid) if sid else None
    if key is None:
        sk = SECRET_KEY or b""
        key = hashlib.sha256(b"kalmido-budget-dup|" + (sk.encode() if isinstance(sk, str) else bytes(sk))).digest()
    msg = f"{int(lid)}|{day}|{_amt_s(amount)}|{kind}|{_norm(title)}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:40]


def bud_settle(c, list_ids=None, plain=None, force_from=None, stop=None, commit=True):
    """Every budget row encrypted for the space of its list now. plain(sid) -> True: decrypt that row (the way back:
    decrypt-all / decrypt-private); force_from = a space whose key is about to go (an account / organisation is
    deleted): its rows are moved to the space they lie in now even when that one is switched off. Rows of a space that is
    not active stay as they are (like files_settle). Commits per list (commit=False: inside the caller's transaction).
    -> number of rows changed."""
    n = 0
    with system_ctx(c):  # orgcrypt: server-side bulk work over every space (no content leaves this function)
        q, args = "SELECT id, org_id, owner_id FROM lists WHERE life='budget'", []
        if list_ids is not None:
            ids = sorted({int(x) for x in list_ids})
            if not ids:
                return 0
            q += f" AND id IN ({','.join('?' * len(ids))})"
            args = ids
        lists = c.execute(q + " ORDER BY id", args).fetchall()
    for lr in lists:
        if stop and stop():
            break
        lid = lr["id"]
        space = int(lr["org_id"]) if lr["org_id"] else (oc.oc_user_space(lr["owner_id"]) or 0)
        active = bool(space) and oc.oc_active_for(c, space)
        changed = 0
        with system_ctx(c):  # orgcrypt: the rows of one budget list, resealed for its space
            for table in BUD_TABLES:
                for r in c.execute(f"SELECT * FROM {table} WHERE list_id=? ORDER BY id", (lid,)).fetchall():
                    sid = int(r["sid"] or 0)
                    if plain and sid and plain(sid):
                        target = 0
                    elif force_from is not None:
                        if sid != force_from or space == force_from:
                            continue
                        target = space
                    elif active and sid != space:
                        target = space
                    else:
                        continue
                    if target == sid:
                        continue
                    d = bud_dec(c, table, r)
                    vals = {k: d[k] for k in oc.FIELDS[table]}
                    if target:
                        enc, used = bud_enc(c, table, target, vals)
                    else:
                        enc, used = vals, 0
                    sets = {**enc, "sid": used}
                    if table == "budget_entries":
                        sets["dkey"] = bud_dkey(c, lid, used, d["day"], d["amount"], d["kind"], d["title"])
                    cols = list(sets)
                    c.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in cols)} WHERE id=?", [sets[k] for k in cols] + [r["id"]])
                    changed += 1
        if changed and commit:
            c.commit()
            n += changed
    return n


# ---------------------------------------------------------------- values
def _amt(v, what=N_("Amount")):
    """A positive amount (number or text "1.234,56" / "12.30") -> Decimal with two places."""
    if isinstance(v, bool) or v in (None, ""):
        raise BadInput(tr("Invalid value: {0}", tr(what)))
    if isinstance(v, (int, float)):
        d = Decimal(str(v))
    elif isinstance(v, str):
        s = v.strip().replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        if not re.fullmatch(r"\d{1,8}(\.\d{1,2})?", s):
            raise BadInput(tr("Invalid value: {0}", tr(what)))
        d = Decimal(s)
    else:
        raise BadInput(tr("Invalid value: {0}", tr(what)))
    if not d.is_finite() or d != d.quantize(Decimal("0.01")):
        raise BadInput(tr("Invalid value: {0}", tr(what)))
    d = d.quantize(Decimal("0.01"))
    if d <= 0 or d > BUD_AMOUNT_MAX:
        raise BadInput(tr("Invalid value: {0}", tr(what)))
    return d


def _amt_s(v):
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def _num(s):
    """Stored text -> Decimal (0 when empty)."""
    try:
        return Decimal(s) if s not in (None, "") else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _f(d):
    return float(Decimal(d).quantize(Decimal("0.01")))


def _txt(v, n, what, need=False):
    if v is None or v == "":
        if need:
            raise BadInput(tr("Please enter a name") if what == "name" else tr("Invalid value: {0}", what))
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()
    if need and not v:
        raise BadInput(tr("Please enter a name") if what == "name" else tr("Invalid value: {0}", what))
    return v[:n]


def _kind(v):
    v = v or "out"
    if v not in BUD_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    return v


def _day(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise BadInput(tr("Please enter the date"))
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise BadInput(tr("Please enter the date")) from None
    if not 1900 <= d.year <= 2199:
        raise BadInput(tr("Please enter the date"))
    return v


def bud_month(v, need=True):
    if v in (None, "") and not need:
        return None
    if not isinstance(v, str) or not BUD_MONTH_RE.fullmatch(v):
        raise BadInput(tr("Invalid value: {0}", "month"))
    return v


def _mi(m):
    """'YYYY-MM' -> a month number."""
    return int(m[:4]) * 12 + int(m[5:7]) - 1


def _mstr(i):
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def bud_this_month():
    return local_now().date().isoformat()[:7]


def _cat_of(c, lid, v):
    """cat_id of a client: None, or a category of THIS list (another list's id is refused)."""
    if v in (None, "", 0):
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise BadInput(tr("Invalid value: {0}", "cat_id"))
    if not c.execute("SELECT 1 FROM budget_cats WHERE id=? AND list_id=?", (v, lid)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "cat_id"))
    return v


def _rec_of(c, lid, v):
    if v in (None, "", 0):
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise BadInput(tr("Invalid value: {0}", "recurring_id"))
    r = c.execute("SELECT * FROM budget_recurring WHERE id=? AND list_id=?", (v, lid)).fetchone()
    if not r:
        raise BadInput(tr("Invalid value: {0}", "recurring_id"))
    return r


def _ts():
    return iso(now_utc())


# ---------------------------------------------------------------- lists
def bud_lists(c, uid):
    """The budget lists the person sees (not archived): [{id, name, color, owner_id, shared, can_write}]."""
    if bud_hidden(c, uid):
        return []
    rows = c.execute(f"""SELECT id, name, color, owner_id, sort,
                                EXISTS (SELECT 1 FROM list_members m WHERE m.list_id=lists.id) AS shared
                         FROM lists WHERE life='budget' AND archived=0 AND id IN {vis_sql()}
                         ORDER BY owner_id!=?, sort, id""", (uid, uid, uid)).fetchall()
    out = []
    for r in rows:
        role = list_role(c, r["id"], uid)
        if not role or role == "participant":
            continue
        out.append({"id": r["id"], "name": r["name"], "color": r["color"], "owner_id": r["owner_id"], "shared": bool(r["shared"]),
                    "can_write": role in WRITE_ROLES})
    return out


def bud_list_create(c, uid, b):
    """{name?} -> the id of a new budget list with the default categories."""
    from ..life.model import life_list_create
    bud_need_on(c, uid)
    if bud_hidden(c, uid):
        raise Denied(403)
    name = _txt(b.get("name"), 100, "name") or None
    lid = life_list_create(c, uid, "budget", name=name)
    lg = lang(c, uid)
    for i, (n, k) in enumerate(BUD_DEFAULT_CATS):
        c.execute("INSERT INTO budget_cats(list_id,name,kind,lim,sort,sid,created_at) VALUES(?,?,?,?,?,?,?)",
                  (lid, tr(n, lg=lg), k, "", i, 0, _ts()))
    return lid


# ---------------------------------------------------------------- categories
def cat_out(d):
    lim = _num(d.get("lim"))
    return {"id": d["id"], "list_id": d["list_id"], "name": d["name"], "kind": d["kind"], "limit": _f(lim) if d.get("lim") else None,
            "sort": d["sort"]}


def _limit(v):
    if v in (None, "", 0):
        return ""
    return _amt_s(_amt(v, N_("Monthly limit")))


def cat_create(c, uid, lid, b):
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    if c.execute("SELECT COUNT(*) FROM budget_cats WHERE list_id=?", (lid,)).fetchone()[0] >= BUD_CATS_MAX:
        raise BadInput(tr("Too many categories"))
    name = _txt(b.get("name"), BUD_CAT_MAX, "name", need=True)
    kind = _kind(b.get("kind"))
    vals, sid = bud_enc(c, "budget_cats", bud_sid(c, lid), {"lim": _limit(b.get("limit"))})
    sort = c.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM budget_cats WHERE list_id=?", (lid,)).fetchone()[0]
    cid = insert_id(c, "INSERT INTO budget_cats(list_id,name,kind,lim,sort,sid,created_at) VALUES(?,?,?,?,?,?,?)",
                    (lid, name, kind, vals["lim"], sort, sid, _ts()))
    return cat_get(c, cid)


def cat_get(c, cid):
    return cat_out(bud_dec(c, "budget_cats", c.execute("SELECT * FROM budget_cats WHERE id=?", (cid,)).fetchone()))


def cat_update(c, uid, cid, b):
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_cats", cid)
    sets = {}
    if "name" in b:
        sets["name"] = _txt(b.get("name"), BUD_CAT_MAX, "name", need=True)
    if "kind" in b:
        sets["kind"] = _kind(b.get("kind"))
    if "sort" in b:
        if isinstance(b["sort"], bool) or not isinstance(b["sort"], int) or not -10000 <= b["sort"] <= 10000:
            raise BadInput(tr("Invalid value: {0}", "sort"))
        sets["sort"] = b["sort"]
    if "limit" in b:
        vals, sid = bud_enc(c, "budget_cats", bud_sid(c, r["list_id"]), {"lim": _limit(b.get("limit"))})
        sets.update(lim=vals["lim"], sid=sid)  # lim is the row's only protected column: the row's space follows it
    if sets:
        cols = list(sets)
        c.execute(f"UPDATE budget_cats SET {', '.join(k + '=?' for k in cols)} WHERE id=?", [sets[k] for k in cols] + [r["id"]])
    return cat_get(c, r["id"])


def cat_delete(c, uid, cid):
    """Deletes a category; its entries and templates stay without one (ON DELETE SET NULL) -> {cat, entry_ids,
    recurring_ids}: what the app's undo needs (the category created again, the rows linked back with PATCH)."""
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_cats", cid)
    out = {"cat": cat_get(c, r["id"]),
           "entry_ids": [x[0] for x in c.execute("SELECT id FROM budget_entries WHERE cat_id=? ORDER BY id", (r["id"],))],
           "recurring_ids": [x[0] for x in c.execute("SELECT id FROM budget_recurring WHERE cat_id=? ORDER BY id", (r["id"],))]}
    c.execute("DELETE FROM budget_cats WHERE id=?", (r["id"],))
    return out


# ---------------------------------------------------------------- entries
def _files_of(c, eids):
    out = {}
    if not eids:
        return out
    ids = sorted(set(eids))
    for f in c.execute(f"SELECT id, entry_id, name, size, mime FROM budget_files WHERE entry_id IN ({','.join('?' * len(ids))}) ORDER BY id",
                       ids):
        out.setdefault(f["entry_id"], []).append({"id": f["id"], "name": f["name"], "size": f["size"], "mime": f["mime"]})
    return out


def entry_out(d, files=None):
    return {"id": d["id"], "list_id": d["list_id"], "day": d["day"], "amount": _f(_num(d["amount"])), "kind": d["kind"],
            "title": d["title"], "note": d["note"], "counterpart": d["counterpart"], "cat_id": d["cat_id"],
            "recurring_id": d["recurring_id"], "source": d["source"], "files": files or [], "created_by": d["created_by"],
            "updated_at": d["updated_at"]}


def entry_get(c, eid):
    r = c.execute("SELECT * FROM budget_entries WHERE id=?", (eid,)).fetchone()
    return entry_out(bud_dec(c, "budget_entries", r), _files_of(c, [eid]).get(eid))


def _entry_vals(c, lid, b, old=None):
    """The checked fields of an entry (old: the decrypted row of a PATCH; missing fields keep their value)."""
    o = old or {}

    def has(k):
        return old is None or k in b
    v = {"day": _day(b.get("day")) if has("day") else o["day"],
         "amount": _amt_s(_amt(b.get("amount"))) if has("amount") else o["amount"],
         "kind": _kind(b.get("kind")) if has("kind") else o["kind"],
         "title": _txt(b.get("title"), BUD_TITLE_MAX, "title", need=True) if has("title") else o["title"],
         "note": _txt(b.get("note"), BUD_NOTE_MAX, "note") if has("note") else o["note"],
         "counterpart": _txt(b.get("counterpart"), BUD_CP_MAX, "counterpart") if has("counterpart") else o["counterpart"],
         "cat_id": _cat_of(c, lid, b.get("cat_id")) if has("cat_id") else o["cat_id"]}
    if has("recurring_id"):
        rr = _rec_of(c, lid, b.get("recurring_id"))
        v["recurring_id"] = rr["id"] if rr else None
    else:
        v["recurring_id"] = o["recurring_id"]
    v["rmonth"] = v["day"][:7] if v["recurring_id"] else ""
    return v


def _booked(c, rid, month, but=None):
    r = c.execute("SELECT id FROM budget_entries WHERE recurring_id=? AND rmonth=?", (rid, month)).fetchone()
    return bool(r) and r[0] != but


def entry_insert(c, uid, lid, v, source, imp=None):
    """Inserts checked values v (plain) -> the new id. 409 when the template v.recurring_id is booked in that month.
    2.146.0 C (#2455): imp = {import_run, rkeys, ikey} of an imported row."""
    if v["recurring_id"] and _booked(c, v["recurring_id"], v["rmonth"]):
        raise Denied(409, tr("This item is already booked in this month"))
    sid0 = bud_sid(c, lid)
    enc, sid = bud_enc(c, "budget_entries", sid0, {k: v[k] for k in oc.FIELDS["budget_entries"]})
    ts = _ts()
    try:
        with c.savepoint():
            if imp:  # 2.146.0 C (#2455): the import run and the keys of the duplicate check
                return insert_id(c, """INSERT INTO budget_entries(list_id,day,amount,kind,title,note,counterpart,cat_id,recurring_id,rmonth,source,
                                                         dkey,sid,created_by,created_at,updated_at,import_run,rkeys,ikey)
                                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (lid, v["day"], enc["amount"], v["kind"], enc["title"], enc["note"], enc["counterpart"], v["cat_id"], v["recurring_id"],
                                  v["rmonth"], source, bud_dkey(c, lid, sid, v["day"], v["amount"], v["kind"], v["title"]), sid, uid, ts, ts,
                                  imp["import_run"], imp["rkeys"], imp["ikey"]))
            return insert_id(c, """INSERT INTO budget_entries(list_id,day,amount,kind,title,note,counterpart,cat_id,recurring_id,rmonth,source,
                                                     dkey,sid,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (lid, v["day"], enc["amount"], v["kind"], enc["title"], enc["note"], enc["counterpart"], v["cat_id"], v["recurring_id"],
                              v["rmonth"], source, bud_dkey(c, lid, sid, v["day"], v["amount"], v["kind"], v["title"]), sid, uid, ts, ts))
    except IntegrityError:  # 2.72.0 (#1333): a parallel booking of the same month (unique index)
        raise Denied(409, tr("This item is already booked in this month")) from None


def entry_create(c, uid, lid, b):
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    v = _entry_vals(c, lid, b)
    src = "recurring" if v["recurring_id"] else "manual"
    if b.get("source") in BUD_SOURCES:  # the app's undo re-creates a deleted entry with its source
        src = b["source"]
    return entry_get(c, entry_insert(c, uid, lid, v, src))


def entry_update(c, uid, eid, b):
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_entries", eid)
    lid = r["list_id"]
    old = bud_dec(c, "budget_entries", r)
    v = _entry_vals(c, lid, b, old)
    if v["recurring_id"] and _booked(c, v["recurring_id"], v["rmonth"], but=r["id"]):
        raise Denied(409, tr("This item is already booked in this month"))
    enc, sid = bud_enc(c, "budget_entries", bud_sid(c, lid), {k: v[k] for k in oc.FIELDS["budget_entries"]})
    try:
        with c.savepoint():
            c.execute("""UPDATE budget_entries SET day=?, amount=?, kind=?, title=?, note=?, counterpart=?, cat_id=?, recurring_id=?, rmonth=?,
                         dkey=?, sid=?, updated_at=? WHERE id=?""",
                      (v["day"], enc["amount"], v["kind"], enc["title"], enc["note"], enc["counterpart"], v["cat_id"], v["recurring_id"], v["rmonth"],
                       bud_dkey(c, lid, sid, v["day"], v["amount"], v["kind"], v["title"]), sid, _ts(), r["id"]))
    except IntegrityError:  # 2.72.0 (#1333): a parallel booking of the same month (unique index)
        raise Denied(409, tr("This item is already booked in this month")) from None
    return entry_get(c, r["id"])


def entry_delete(c, uid, eid):
    """Deletes an entry (its receipts too) -> (the entry as it was, the file paths to remove after the commit)."""
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_entries", eid)
    out = entry_get(c, r["id"])
    paths = [x[0] for x in c.execute("SELECT path FROM budget_files WHERE entry_id=?", (r["id"],))]
    c.execute("DELETE FROM budget_entries WHERE id=?", (r["id"],))
    return out, paths


# ---------------------------------------------------------------- recurring templates
def rec_due(d, month):
    """True when template d (start, until, per) falls due in month 'YYYY-MM'."""
    m, s = _mi(month), _mi(d["start"])
    if m < s or (d.get("until") and m > _mi(d["until"])):
        return False
    return (m - s) % BUD_PER.get(d["per"], 1) == 0


def _contracts(c, uid):
    """{task id: (task, list org)} of the contracts the person sees (with a cost)."""
    from ..core.serializers import load_tasks
    out = {}
    rows = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND status=0 AND fam!=''", (uid, uid))  # as life_overview
    orgs = {}
    for t in rows:
        f = t.get("fam") or {}
        if f.get("kind") != "contract" or f.get("cost") is None:
            continue
        if t["list_id"] not in orgs:
            orgs[t["list_id"]] = c.execute("SELECT org_id FROM lists WHERE id=?", (t["list_id"],)).fetchone()[0]
        out[t["id"]] = (t, orgs[t["list_id"]])
    return out


def rec_out(d, contracts=None):
    amount = _f(_num(d["amount"]))
    con, changed = None, False
    if d.get("contract_task_id") and contracts is not None and d["contract_task_id"] in contracts:
        f = contracts[d["contract_task_id"]][0]["fam"]
        con = {"cost": float(f["cost"]), "per": f.get("per") or "month"}
        changed = abs(con["cost"] - amount) > 0.004 or con["per"] != d["per"]
    return {"id": d["id"], "list_id": d["list_id"], "title": d["title"], "amount": amount, "kind": d["kind"], "cat_id": d["cat_id"],
            "per": d["per"], "start": d["start"], "until": d["until"], "contract_task_id": d["contract_task_id"],
            "contract_changed": changed, "contract": con}


def _rec_rows(c, lid):
    return [bud_dec(c, "budget_recurring", r) for r in c.execute("SELECT * FROM budget_recurring WHERE list_id=? ORDER BY id", (lid,))]


def rec_list(c, uid, lid):
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid)
    cons = _contracts(c, uid)
    return [rec_out(d, cons) for d in _rec_rows(c, lid)]


def rec_get(c, uid, rid):
    d = bud_dec(c, "budget_recurring", c.execute("SELECT * FROM budget_recurring WHERE id=?", (rid,)).fetchone())
    return rec_out(d, _contracts(c, uid) if d["contract_task_id"] else None)


def _per(v):
    v = v or "month"
    if v not in BUD_PER:
        raise BadInput(tr("Invalid value: {0}", "per"))
    return v


def _rec_vals(c, lid, b, old=None):
    o = old or {}

    def has(k):
        return old is None or k in b
    v = {"title": _txt(b.get("title"), BUD_TITLE_MAX, "title", need=True) if has("title") else o["title"],
         "amount": _amt_s(_amt(b.get("amount"))) if has("amount") else o["amount"],
         "kind": _kind(b.get("kind")) if has("kind") else o["kind"],
         "cat_id": _cat_of(c, lid, b.get("cat_id")) if has("cat_id") else o["cat_id"],
         "per": _per(b.get("per")) if has("per") else o["per"],
         "start": bud_month(b.get("start") or (bud_this_month() if old is None else None)) if has("start") else o["start"],
         "until": bud_month(b.get("until"), need=False) if has("until") else o["until"]}
    if v["until"] and v["until"] < v["start"]:
        raise BadInput(tr("The end month lies before the start month"))
    return v


def rec_insert(c, uid, lid, v, contract_task_id=None):
    if c.execute("SELECT COUNT(*) FROM budget_recurring WHERE list_id=?", (lid,)).fetchone()[0] >= BUD_REC_MAX:
        raise BadInput(tr("Too many recurring items"))
    enc, sid = bud_enc(c, "budget_recurring", bud_sid(c, lid), {k: v[k] for k in oc.FIELDS["budget_recurring"]})
    ts = _ts()
    return insert_id(c, """INSERT INTO budget_recurring(list_id,title,amount,kind,cat_id,per,start,until,contract_task_id,sid,created_by,
                                                       created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (lid, enc["title"], enc["amount"], v["kind"], v["cat_id"], v["per"], v["start"], v["until"], contract_task_id, sid, uid,
                      ts, ts))


def rec_create(c, uid, lid, b):
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    return rec_get(c, uid, rec_insert(c, uid, lid, _rec_vals(c, lid, b)))


def rec_update(c, uid, rid, b):
    """Fields of a template; {sync_contract: true} = amount and period from its contract again."""
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_recurring", rid)
    lid = r["list_id"]
    old = bud_dec(c, "budget_recurring", r)
    sync = b.get("sync_contract") is True
    b = {k: x for k, x in b.items() if k != "sync_contract"}
    if sync:
        cons = _contracts(c, uid)
        if not r["contract_task_id"] or r["contract_task_id"] not in cons:
            raise BadInput(tr("The contract is not available any more"))
        f = cons[r["contract_task_id"]][0]["fam"]
        b = {**b, "amount": f["cost"], "per": f.get("per") or "month"}
    v = _rec_vals(c, lid, b, old)
    enc, sid = bud_enc(c, "budget_recurring", bud_sid(c, lid), {k: v[k] for k in oc.FIELDS["budget_recurring"]})
    c.execute("UPDATE budget_recurring SET title=?, amount=?, kind=?, cat_id=?, per=?, start=?, until=?, sid=?, updated_at=? WHERE id=?",
              (enc["title"], enc["amount"], v["kind"], v["cat_id"], v["per"], v["start"], v["until"], sid, _ts(), r["id"]))
    return rec_get(c, uid, r["id"])


def rec_delete(c, uid, rid):
    """Deletes a template; booked entries stay (recurring_id -> NULL)."""
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_recurring", rid)
    out = rec_get(c, uid, r["id"])
    c.execute("DELETE FROM budget_recurring WHERE id=?", (r["id"],))
    return out


def rec_book(c, uid, rid, b):
    """{month, day?} -> the entry booked from template rid in that month (409 when it is booked there already)."""
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_recurring", rid)
    d = bud_dec(c, "budget_recurring", r)
    month = bud_month(b.get("month") or bud_this_month())
    day = _day(b["day"]) if b.get("day") else f"{month}-01"
    if day[:7] != month:
        raise BadInput(tr("Invalid value: {0}", "day"))
    if not rec_due(d, month):
        raise BadInput(tr("This item is not due in this month"))
    v = {"day": day, "amount": d["amount"], "kind": d["kind"], "title": d["title"], "note": "", "counterpart": "", "cat_id": d["cat_id"],
         "recurring_id": d["id"], "rmonth": month}
    try:
        with c.savepoint():
            eid = entry_insert(c, uid, r["list_id"], v, "recurring")
    except IntegrityError:  # a parallel booking of the same month (unique index)
        raise Denied(409, tr("This item is already booked in this month")) from None
    return entry_get(c, eid)


# ---------------------------------------------------------------- contracts -> templates
def bud_contracts(c, uid, lid):
    """The contracts the person sees whose list lies in the same space as the budget (organisation / private): never
    copies an organisation's figures into a private budget or the other way."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid)
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    taken = {r[0] for r in c.execute("SELECT contract_task_id FROM budget_recurring WHERE list_id=? AND contract_task_id IS NOT NULL", (lid,))}
    out = []
    for tid, (t, torg) in _contracts(c, uid).items():
        if torg != org:
            continue
        f = t["fam"]
        per = f.get("per") or "month"
        out.append({"task_id": tid, "name": f.get("name") or t["title"], "provider": f.get("provider") or "", "cost": float(f["cost"]),
                    "per": per, "monthly": round(float(f["cost"]) / BUD_PER.get(per, 1), 2), "taken": tid in taken})
    out.sort(key=lambda x: (x["taken"], x["name"].casefold(), x["task_id"]))
    return out


def bud_contracts_take(c, uid, lid, b):
    """{task_ids: [..], cat_id?} -> {created, items}: one template per contract (title = name, amount = cost, its period,
    kind out, from this month). A contract taken over before is skipped."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    ids = b.get("task_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 200 or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "task_ids"))
    cat = _cat_of(c, lid, b.get("cat_id"))
    avail = {x["task_id"]: x for x in bud_contracts(c, uid, lid)}
    made = []
    for tid in dict.fromkeys(ids):
        x = avail.get(tid)
        if not x:
            raise Denied(404)
        if x["taken"]:
            continue
        v = {"title": x["name"][:BUD_TITLE_MAX] or tr("Contract"), "amount": _amt_s(_amt(x["cost"])), "kind": "out", "cat_id": cat,
             "per": x["per"] if x["per"] in BUD_PER else "month", "start": bud_this_month(), "until": None}
        made.append(rec_insert(c, uid, lid, v, contract_task_id=tid))
    cons = _contracts(c, uid)
    items = []
    for rid in made:
        d = bud_dec(c, "budget_recurring", c.execute("SELECT * FROM budget_recurring WHERE id=?", (rid,)).fetchone())
        items.append(rec_out(d, cons))
    return {"created": len(made), "items": items}


# ---------------------------------------------------------------- the month
def _entries(c, lid, lo, hi):
    """The decrypted entries of list lid with lo <= month <= hi."""
    rows = c.execute("SELECT * FROM budget_entries WHERE list_id=? AND day>=? AND day<? ORDER BY day DESC, id DESC",
                     (lid, f"{lo}-01", f"{_mstr(_mi(hi) + 1)}-01")).fetchall()
    return [bud_dec(c, "budget_entries", r) for r in rows]


def _cats(c, lid):
    return [bud_dec(c, "budget_cats", r) for r in c.execute("SELECT * FROM budget_cats WHERE list_id=? ORDER BY sort, id", (lid,))]


def _signed(e, kind):
    a = _num(e["amount"])
    return a if e["kind"] == kind else -a


def bud_totals(c, lid, month):
    """The month of a budget: categories with soll / ist / planned, without category, the totals and the open templates."""
    cats, recs = _cats(c, lid), _rec_rows(c, lid)
    ents = _entries(c, lid, month, month)
    due = [d for d in recs if rec_due(d, month)]
    booked = {e["recurring_id"] for e in ents if e["recurring_id"] and e["rmonth"] == month}
    cat_ids = {d["id"] for d in cats}
    out_cats = []
    tot = {"soll_in": Decimal(0), "ist_in": Decimal(0), "soll_out": Decimal(0), "ist_out": Decimal(0)}
    for d in cats:
        planned = sum((_num(r["amount"]) for r in due if r["cat_id"] == d["id"] and r["kind"] == d["kind"]), Decimal(0))
        soll = _num(d["lim"]) if d["lim"] else planned
        ist = sum((_signed(e, d["kind"]) for e in ents if e["cat_id"] == d["id"]), Decimal(0))
        tot["soll_" + d["kind"]] += soll
        o = cat_out(d)
        o.update(soll=_f(soll), ist=_f(ist), planned=_f(planned))
        out_cats.append(o)
    for r in due:  # templates without a category (or of the other kind than their category) still plan the month
        if r["cat_id"] not in cat_ids or next(d["kind"] for d in cats if d["id"] == r["cat_id"]) != r["kind"]:
            tot["soll_" + r["kind"]] += _num(r["amount"])
    none = {"ist_in": Decimal(0), "ist_out": Decimal(0)}
    for e in ents:
        tot["ist_" + e["kind"]] += _num(e["amount"])
        if e["cat_id"] is None:
            none["ist_" + e["kind"]] += _num(e["amount"])
    totals = {k: _f(v) for k, v in tot.items()}
    totals["saldo"] = _f(tot["ist_in"] - tot["ist_out"])
    open_ = [{"recurring": rec_out(r), "amount": _f(_num(r["amount"])), "day": f"{month}-01"} for r in due if r["id"] not in booked]
    return {"cats": out_cats, "none": {k: _f(v) for k, v in none.items()}, "totals": totals, "open_recurring": open_, "entries": ents,
            "recs": recs}


def bud_month_view(c, uid, lid, month):
    bud_need_on(c, uid)
    role = bud_need_list(c, uid, lid)
    m = bud_totals(c, lid, month)
    cons = _contracts(c, uid)
    rec_by = {r["id"]: rec_out(r, cons) for r in m["recs"]}
    for o in m["open_recurring"]:
        o["recurring"] = rec_by[o["recurring"]["id"]]
    ents = m["entries"]
    files = _files_of(c, [e["id"] for e in ents])
    lo = _mstr(_mi(month) - BUD_TREND + 1)
    trend = {_mstr(i): {"ist_in": Decimal(0), "ist_out": Decimal(0)} for i in range(_mi(lo), _mi(month) + 1)}
    for e in _entries(c, lid, lo, month):
        trend[e["day"][:7]]["ist_" + e["kind"]] += _num(e["amount"])
    name = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    return {"list_id": lid, "name": name, "month": month, "can_write": role in WRITE_ROLES, "cats": m["cats"], "none": m["none"],
            "totals": m["totals"], "entries": [entry_out(e, files.get(e["id"])) for e in ents], "open_recurring": m["open_recurring"],
            "trend": [{"month": k, "ist_in": _f(v["ist_in"]), "ist_out": _f(v["ist_out"])} for k, v in trend.items()]}


BUD_COMPARE = (3, 6, 12)  # 2.140.0 B (#2134): the periods of the month comparison


def _pct(cur, base):
    return None if not base else float(((cur - base) / base * 100).quantize(Decimal("0.1")))


def bud_compare(c, uid, lid, month, n):
    """2.140.0 B (#2134): the month comparison -- month against the n - 1 months before it, per category: ist / soll of
    every month (from the entries and the plan as bud_totals makes it), the difference to the month before and to the
    average of the earlier months that have any entry at all (months before the budget was used do not pull the average
    down; absolute and in percent; None when there is nothing to compare with)."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid)
    if n not in BUD_COMPARE:
        raise BadInput(tr("Invalid value: {0}", "months"))
    months = [_mstr(i) for i in range(_mi(month) - n + 1, _mi(month) + 1)]
    per = {m: bud_totals(c, lid, m) for m in months}
    active = [i for i, m in enumerate(months[:-1]) if per[m]["totals"]["ist_in"] or per[m]["totals"]["ist_out"]]
    cats = []

    def entry(key, name, kind, ist_of, soll_of):
        ist = [ist_of(m) for m in months]
        soll = [soll_of(m) for m in months]
        cur, prev, earlier = ist[-1], ist[-2] if n > 1 else None, [ist[i] for i in active]
        avg = (sum(earlier, Decimal(0)) / len(earlier)).quantize(Decimal("0.01")) if earlier else None
        return {"key": key, "name": name, "kind": kind,
                "months": [{"month": m, "ist": _f(i), "soll": _f(sl)} for m, i, sl in zip(months, ist, soll)],
                "ist": _f(cur), "soll": _f(soll[-1]), "prev": _f(prev) if prev is not None else None,
                "diff_prev": _f(cur - prev) if prev is not None else None, "pct_prev": _pct(cur, prev) if prev is not None else None,
                "avg": _f(avg) if avg is not None else None, "diff_avg": _f(cur - avg) if avg is not None else None,
                "pct_avg": _pct(cur, avg) if avg is not None else None, "diff_plan": _f(soll[-1] - cur) if soll[-1] else None}
    dec_ = lambda v: Decimal(str(v))  # noqa: E731 -- bud_totals hands out floats of two decimals
    for d in _cats(c, lid):
        def ist_of(m, cid=d["id"]):
            return dec_(next(x["ist"] for x in per[m]["cats"] if x["id"] == cid))

        def soll_of(m, cid=d["id"]):
            return dec_(next(x["soll"] for x in per[m]["cats"] if x["id"] == cid))
        e = entry(d["id"], d["name"], d["kind"], ist_of, soll_of)
        if any(x["ist"] or x["soll"] for x in e["months"]):
            cats.append(e)
    for kind in BUD_KINDS:
        e = entry(f"none-{kind}", None, kind, lambda m, k=kind: dec_(per[m]["none"]["ist_" + k]), lambda m: Decimal(0))
        if any(x["ist"] for x in e["months"]):
            cats.append(e)
    totals = {kind: entry(f"total-{kind}", None, kind, lambda m, k=kind: dec_(per[m]["totals"]["ist_" + k]),
                          lambda m, k=kind: dec_(per[m]["totals"]["soll_" + k])) for kind in BUD_KINDS}
    return {"list_id": lid, "month": month, "months": months, "n": n, "cats": cats, "totals": totals}


def bud_overview(c, uid):
    """GET /api/budget: the lists, this month and the totals of the first list (the card on "At home")."""
    bud_need_on(c, uid)
    if bud_hidden(c, uid):
        raise Denied(403)
    ls = bud_lists(c, uid)
    month = bud_this_month()
    return {"lists": ls, "month": month, "summary": bud_totals(c, ls[0]["id"], month)["totals"] if ls else None}


# ---------------------------------------------------------------- receipts
def bud_files_save(c, uid, eid, files, saved):
    """Stores uploaded receipts of entry eid (sealed with the list's space key) -> the entry's files; the stored paths go
    to saved. BadInput on an error (the caller rolls back and removes the saved paths)."""
    import os
    import uuid
    import mimetypes
    from ..core.config import ATT_DIR, MAX_FILE_MB
    from ..tasks.attachments import safe_name
    from ..admin.hosting import quota_guard
    bud_need_on(c, uid)
    r = bud_obj(c, uid, "budget_entries", eid)
    lid = r["list_id"]
    if not files:
        raise BadInput(tr("File missing"))
    if c.execute("SELECT COUNT(*) FROM budget_files WHERE entry_id=?", (r["id"],)).fetchone()[0] + len(files) > BUD_FILES_MAX:
        raise BadInput(tr("Too many files"))
    quota_guard(c, uid)
    rel_dir = os.path.join("budget", str(int(lid)))
    os.makedirs(os.path.join(ATT_DIR, rel_dir), exist_ok=True)
    sid = oc.oc_list_space(c, lid) or 0
    ids = []
    for f in files:
        name = safe_name(f.filename)
        rel = os.path.join(rel_dir, f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        f.save(full)
        saved.append(rel)
        size = os.path.getsize(full)
        if size > MAX_FILE_MB * 1024 * 1024:
            raise BadInput(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))
        if not size:
            raise BadInput(tr("{0}: the file is empty and was not uploaded", name))
        mime = (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) or mimetypes.guess_type(name)[0] \
            or "application/octet-stream"
        from ..files.upsafe import up_check_path, UploadRefused
        try:  # 2.61.0 (#1818 #1819): virus scan + photo metadata like every upload, before sealing
            size, mime, _info = up_check_path(c, full, name, mime, uid, oc.oc_list_org(c, lid) or None, "budget")
        except UploadRefused as e:  # up_check_path removed the file
            saved.remove(rel)
            raise BadInput(str(e))
        oc.oc_seal_path(c, sid, full, fresh=True)  # like attachments: the space key of the list (organisation / owner)
        ids.append(insert_id(c, "INSERT INTO budget_files(entry_id,list_id,name,mime,size,path,user_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (r["id"], lid, name, mime, size, rel, uid, _ts())))
        from ..files.scan import sc_after_store
        sc_after_store(c, "budget", ids[-1], oc.oc_list_org(c, lid) or None, _info)  # 2.126.0 A (#1979 L1): unchecked = scanned later
    c.execute("UPDATE budget_entries SET updated_at=? WHERE id=?", (_ts(), r["id"]))
    return _files_of(c, [r["id"]]).get(r["id"], [])


# ---------------------------------------------------------------- the bank import (CSV, CAMT)
# 2.140.0 B (#2134): the reading itself is core/csvimport.py, shared with the office's bank reconciliation (the same
# formats, layouts and checks); the names below stay for the callers of earlier versions
_GUESS = cx.GUESS
_decode = cx.csv_decode
_delim = cx.csv_delim
_parse_amount = cx.csv_amount
_parse_day = cx.csv_day
_guess = cx.csv_guess
_hkey = cx.csv_hkey
_mapping = cx.csv_mapping


def bud_csv_table(text):
    """CSV text -> (delimiter, header, rows) (core/csvimport.csv_table); 2.146.0 C (#2455): up to BUD_ROWS_MAX rows."""
    return cx.csv_table(text, BUD_ROWS_MAX)


def _row_of(r, m):
    """One CSV row with mapping m -> {day, amount, kind, title, counterpart, error} (2.146.0 C: with the S/H mark)."""
    return cx.csv_row(r, m, BUD_TITLE_MAX, BUD_CP_MAX, BUD_AMOUNT_MAX)


def _camt_rows(text):
    """2.140.0 B (#2134): a CAMT.052 / .053 statement -> budget rows like _row_of (text = purpose, else the counterpart).
    The budget has no currency of its own: a booking in another currency than most of the file is refused.
    2.146.0 C (#2469): + pending (a CAMT.052 entry not booked yet), iban, ref (AcctSvcrRef), e2e (EndToEndId)."""
    rows = cx.camt_rows(text)
    curs = [r["currency"] for r in rows if r["currency"]]
    main = max(set(curs), key=curs.count) if curs else ""
    out = []
    for r in rows:
        x = {"day": r["day"], "amount": None, "kind": "out", "title": "", "counterpart": (r["counterpart"] or "")[:BUD_CP_MAX], "error": r["error"],
             "pending": r["pending"], "iban": r["iban"], "ref": r["svc_ref"], "e2e": r["e2e"]}
        x["title"] = re.sub(r"\s+", " ", r["purpose"] or r["counterpart"] or "").strip()[:BUD_TITLE_MAX]
        a = r["amount"]
        if a is not None:
            x["amount"], x["kind"] = _f(abs(a)), "in" if a > 0 else "out"
        if x["error"] is None and r["currency"] and r["currency"] != main:
            x["error"] = tr("Other currency than the rest of the file ({0})", main)
        elif x["error"] is None and abs(a) > BUD_AMOUNT_MAX:
            x["error"] = tr("The amount cannot be read")
        elif x["error"] is None and not x["title"]:
            x["error"] = tr("The row has no text")
        out.append(x)
    if len(out) > BUD_ROWS_MAX:
        raise BadInput(tr("At most {0} rows per import", BUD_ROWS_MAX))
    return out


def _csv_rows(text, m):
    """2.146.0 C (#2455): a CSV file with mapping m -> budget rows (+ iban of the counterpart's IBAN column)."""
    _d, header, body = bud_csv_table(text)
    m = _mapping(m, len(header))
    if len(body) > BUD_ROWS_MAX:
        raise BadInput(tr("At most {0} rows per import", BUD_ROWS_MAX))
    ic = cx.csv_iban_col(header)
    out = []
    for r in body:
        x = _row_of(r, m)
        iban = (r[ic] if ic is not None and ic < len(r) else "").replace(" ", "").upper()
        out.append({**x, "pending": False, "iban": iban if IBAN_RE.match(iban) else None, "ref": None, "e2e": None})
    return out


def _meta(c, lid):
    r = c.execute("SELECT mappings FROM budget_meta WHERE list_id=?", (lid,)).fetchone()
    try:
        return json.loads(r[0]) if r else {}
    except ValueError:
        return {}


def _meta_put(c, lid, hk, mapping):
    m = _meta(c, lid)
    m.pop(hk, None)
    m[hk] = mapping
    while len(m) > 20:
        m.pop(next(iter(m)))
    c.execute("INSERT INTO budget_meta(list_id, mappings, updated_at) VALUES(?,?,?) ON CONFLICT(list_id) DO UPDATE SET "
              "mappings=excluded.mappings, updated_at=excluded.updated_at", (lid, json.dumps(m, separators=(",", ":")), _ts()))


def _suggest_maps(c, lid):
    """{counterpart: cat_id}, {title: cat_id} from the list's earlier entries (the newest wins)."""
    by_cp, by_title = {}, {}
    rows = c.execute("SELECT * FROM budget_entries WHERE list_id=? AND cat_id IS NOT NULL ORDER BY id DESC LIMIT 3000", (lid,)).fetchall()
    for r in rows:
        d = bud_dec(c, "budget_entries", r)
        if d["counterpart"]:
            by_cp.setdefault(_norm(d["counterpart"]), d["cat_id"])
        by_title.setdefault(_norm(d["title"]), d["cat_id"])
    return by_cp, by_title


def _dkey_counts(c, lid):
    """{dkey: n} of the list's entries, and the spaces their keys came from."""
    counts, sids = {}, set()
    for r in c.execute("SELECT dkey, sid FROM budget_entries WHERE list_id=?", (lid,)):
        counts[r[0]] = counts.get(r[0], 0) + 1
        sids.add(int(r[1] or 0))
    return counts, sids


def _open_recs(c, lid):
    """{month: [template rows due and not booked]} -- computed per month when asked."""
    recs = _rec_rows(c, lid)
    booked = {(r[0], r[1]) for r in c.execute("SELECT recurring_id, rmonth FROM budget_entries WHERE list_id=? AND recurring_id IS NOT NULL",
                                               (lid,))}
    cache = {}

    def get(month):
        if month not in cache:
            cache[month] = [d for d in recs if rec_due(d, month) and (d["id"], month) not in booked]
        return cache[month]
    return get


def _dup_key():
    sk = SECRET_KEY or b""
    return hashlib.sha256(b"kalmido-budget-ref|" + (sk.encode() if isinstance(sk, str) else bytes(sk))).digest()


def bud_ikey(lid, day, amount, kind, iban):
    """2.146.0 C (#2455): the duplicate key without the text -- day + amount + kind + the counterpart's IBAN (so a CSV and a
    CAMT file of the same account find each other although their texts differ); only for rows with an IBAN. Keyed with a
    key from the server key (not the space key: it stays valid while a list is resealed), the list id is part of it."""
    if not iban:
        return ""
    msg = f"i|{int(lid)}|{day}|{_amt_s(amount)}|{kind}|{iban}".encode()
    return hmac.new(_dup_key(), msg, hashlib.sha256).hexdigest()[:40]


def bud_rkeys(lid, amount, kind, ref, e2e):
    """2.146.0 C (#2469): the keyed reference keys of a row (core/csvimport.csv_ref_parts), space separated."""
    a = Decimal(str(amount)) if amount is not None else None
    parts = cx.csv_ref_parts({"amount": None if a is None else (a if kind == "in" else -a), "svc_ref": ref, "e2e": e2e})
    return " ".join(hmac.new(_dup_key(), f"r|{int(lid)}|{p}".encode(), hashlib.sha256).hexdigest()[:40] for p in parts)


class _Dups:
    """2.146.0 C (#2455 #2469): the duplicate check of one import (preview and commit alike). A row is there already when
    one of its references is in the list or in an EARLIER file of this import (a pending entry booked later with another
    day or text is found so), else by day + amount + counterpart IBAN, else by the old key with the text (dkey; entries of
    earlier versions only have that one, so it stays checked). Rows of one file are distinct: two equal rows need two
    existing ones; across files the larger number counts, never the sum (like the office's import, 2.144.1)."""

    def __init__(self, c, lid):
        self.c, self.lid = c, lid
        self.dk, self.sids = _dkey_counts(c, lid)
        self.sid = bud_sid(c, lid)
        self.sids |= {self.sid}
        self.ik, self.refs = {}, set()
        for r in c.execute("SELECT ikey, rkeys FROM budget_entries WHERE list_id=?", (lid,)):
            if r[0]:
                self.ik[r[0]] = self.ik.get(r[0], 0) + 1
            if r[1]:
                self.refs.update(r[1].split())
        self.fi = None
        self._start()

    def _start(self):
        self.l_dk, self.l_ik, self.s_dk, self.s_ik, self.s_refs = dict(self.dk), dict(self.ik), {}, {}, set()

    def _end(self):
        for mine, have in ((self.s_dk, self.dk), (self.s_ik, self.ik)):
            for k, n in mine.items():
                have[k] = max(have.get(k, 0), n)
        self.refs |= self.s_refs

    def check(self, x, fi=0):
        """x: day, amount, kind, title, iban?, rkeys (str) -> True when it is there already; the row counts as seen."""
        if fi != self.fi:
            if self.fi is not None:
                self._end()
            self.fi = fi
            self._start()
        rk, ik = (x.get("rkeys") or "").split(), x.get("ikey") or ""
        dks = [bud_dkey(self.c, self.lid, s, x["day"], x["amount"], x["kind"], x["title"]) for s in self.sids]
        dup = any(k in self.refs for k in rk) or bool(ik and cx.csv_dup_take(self.l_ik, ik)) or any(cx.csv_dup_take(self.l_dk, k) for k in dks)
        self.s_refs.update(rk)
        cur = bud_dkey(self.c, self.lid, self.sid, x["day"], x["amount"], x["kind"], x["title"])
        self.s_dk[cur] = self.s_dk.get(cur, 0) + 1
        if ik:
            self.s_ik[ik] = self.s_ik.get(ik, 0) + 1
        return dup


def _fail(fs):
    return BadInput(fs.errors[0]["error"] if len(fs.errors) == 1 else
                    "; ".join(f"{e['file']}: {e['error']}" for e in fs.errors[:5]) if fs.errors else tr("No statement found in the files"))


def bud_import_parse(c, uid, lid, b, fs=None):
    """{text, mapping?} or the uploads of the request (2.146.0 C #2455: several files / a ZIP, core/stmtfiles): without a
    mapping the columns, a sample and a guess (the remembered mapping of this header first, then a known bank layout); with
    one the checked rows (suggested category / template, duplicates). 2.140.0 B (#2134): a CAMT.052 / .053 statement (like
    the office's bank import) -> the checked rows at once (fmt camt). 2.146.0 C (#2469): a pending CAMT.052 entry comes
    with pending (shown apart, never taken over); camt052 = a day report was read (the dialog recommends CAMT.053). Every
    CSV file of one import needs the same columns. Rows carry fi + file (several files: one list by day)."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    fs = fs or sf.stmt_uploads(b)
    n_files = len(fs.files) + len(fs.errors)
    parts = []
    for f in fs.files:
        if cx.camt_is(f["text"]):
            parts.append({**f, "fmt": "camt"})
        elif sf.is_mt940(f["text"]):
            fs.errors.append({"file": f["name"], "error": tr("MT940 / MT942 is not read; please export CAMT.053 (XML) from your online banking")})
        else:
            parts.append({**f, "fmt": "csv"})
    if not parts:
        raise _fail(fs)
    csvs = [p for p in parts if p["fmt"] == "csv"]
    first = None
    for p in csvs:
        try:
            d, header, sample = bud_csv_table(p["text"])
        except BadInput as x:
            if len(parts) == 1:
                raise
            p["error"] = x.args[0] if x.args else tr("The file cannot be read")
            continue
        if first is None:
            first = (d, header, sample)
        elif _hkey(header) != _hkey(first[1]):
            raise BadInput(tr("CSV files with different columns: please import them one by one"))
    info = {"files": n_files, "file_errors": fs.errors, "skipped_files": fs.skipped[:100], "label": ", ".join(fs.labels)[:200]}
    if first is not None and b.get("mapping") is None:
        d, header, sample = first
        g_ = _meta(c, lid).get(_hkey(header)) or _guess(header, sample)
        return {"fmt": "csv", "columns": header, "sample": sample[:8], "delimiter": d, "guess": g_, **info}
    parsed = []
    for fi, p in enumerate(parts):
        if p.get("error"):
            fs.errors.append({"file": p["name"], "error": p["error"]})
            continue
        try:
            got = _camt_rows(p["text"]) if p["fmt"] == "camt" else _csv_rows(p["text"], b["mapping"])
        except BadInput as x:
            if len(parts) == 1:
                raise
            fs.errors.append({"file": p["name"], "error": x.args[0] if x.args else tr("The file cannot be read")})
            p["error"] = True
            continue
        for n, x in enumerate(got, 1):
            x["n"], x["fi"], x["file"] = n, fi, p["name"]
        parsed += got
        if len(parsed) > BUD_ROWS_MAX:
            raise BadInput(tr("At most {0} rows per import", BUD_ROWS_MAX))
    ok_parts = [p for p in parts if not p.get("error")]
    if not ok_parts:
        raise _fail(fs)
    by_cp, by_title = _suggest_maps(c, lid)
    dups = _Dups(c, lid)
    open_for = _open_recs(c, lid)
    used_rec = set()
    for x in parsed:
        x["cat_id"] = x["recurring_id"] = None
        x["dup"] = False
        if x["error"] or x["pending"]:
            continue
        x["cat_id"] = by_cp.get(_norm(x["counterpart"])) if x["counterpart"] else None
        if x["cat_id"] is None:
            x["cat_id"] = by_title.get(_norm(x["title"]))
        x["dup"] = dups.check({**x, "rkeys": bud_rkeys(lid, x["amount"], x["kind"], x["ref"], x["e2e"]),
                               "ikey": bud_ikey(lid, x["day"], x["amount"], x["kind"], x["iban"])}, x["fi"])
        if not x["dup"]:
            for rr in open_for(x["day"][:7]):
                if rr["id"] not in used_rec and rr["kind"] == x["kind"] and _num(rr["amount"]) == Decimal(str(x["amount"])).quantize(Decimal("0.01")):
                    x["recurring_id"] = rr["id"]
                    used_rec.add(rr["id"])
                    x["cat_id"] = x["cat_id"] or rr["cat_id"]
                    break
    if len(ok_parts) > 1:  # one list by day: day, then file, then row (rows without a day at the end)
        parsed.sort(key=lambda r: (r["day"] is None, r["day"] or "", r["fi"], r["n"]))
    kinds = {p["fmt"] for p in ok_parts}
    return {"fmt": kinds.pop() if len(kinds) == 1 else "mixed", "rows": parsed, "skipped": sum(1 for x in parsed if x["error"]),
            "pending": sum(1 for x in parsed if x["pending"] and not x["error"]),
            "camt052": any(p["fmt"] == "camt" and cx.camt_version(p["text"]) == "052" for p in ok_parts), **info}


def _runs(c, lid):
    r = c.execute("SELECT runs FROM budget_meta WHERE list_id=?", (lid,)).fetchone()
    try:
        v = json.loads(r[0]) if r and r[0] else []
    except ValueError:
        v = []
    return [x for x in v if isinstance(x, dict) and BUD_RUN_RE.match(str(x.get("id") or ""))] if isinstance(v, list) else []


def _runs_put(c, lid, runs):
    c.execute("INSERT INTO budget_meta(list_id, runs, updated_at) VALUES(?,?,?) ON CONFLICT(list_id) DO UPDATE SET "
              "runs=excluded.runs, updated_at=excluded.updated_at", (lid, json.dumps(runs[-BUD_RUNS:], separators=(",", ":")), _ts()))


def _ref_txt(v):
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "ref"))
    return cx.csv_clean(v, 120) or None


def bud_import_commit(c, uid, lid, b):
    """{rows: [{day, amount, kind, title, counterpart?, cat_id?, recurring_id?, iban?, ref?, e2e?, fi?}], mapping?, columns?,
    run?, label?, fmt?} -> {created, skipped_dup, run}. Everything is checked again; an equal entry of the list is never
    created twice; a template link only when that template is due and still open in the row's month.
    2.146.0 C (#2455): every import is one run (an id, remembered in budget_meta.runs with its label and count): the app
    sends a long import in parts with the run of the first part; rows of a pending CAMT entry are refused."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    rows = b.get("rows")
    if not isinstance(rows, list) or not rows:
        raise BadInput(tr("Nothing to import"))
    if len(rows) > BUD_CSV_ROWS:
        raise BadInput(tr("At most {0} rows per import", BUD_CSV_ROWS))
    runs = _runs(c, lid)
    run = b.get("run")
    if run is not None:
        if not isinstance(run, str) or not any(x["id"] == run and not x.get("undone_at") for x in runs):
            raise BadInput(tr("Invalid value: {0}", "run"))
    open_for = _open_recs(c, lid)
    used_rec = set()
    vals = []
    for x in rows:
        if not isinstance(x, dict):
            raise BadInput(tr("Invalid value: {0}", "rows"))
        if x.get("pending"):
            raise BadInput(tr("Pending bookings are not taken over"))
        v = {"day": _day(x.get("day")), "amount": _amt_s(_amt(x.get("amount"))), "kind": _kind(x.get("kind")),
             "title": _txt(x.get("title"), BUD_TITLE_MAX, "title", need=True), "note": "",
             "counterpart": _txt(x.get("counterpart"), BUD_CP_MAX, "counterpart"), "cat_id": _cat_of(c, lid, x.get("cat_id")),
             "recurring_id": None, "rmonth": ""}
        iban = x.get("iban")
        iban = iban.replace(" ", "").upper() if isinstance(iban, str) else ""
        fi = x.get("fi")
        imp = {"rkeys": bud_rkeys(lid, v["amount"], v["kind"], _ref_txt(x.get("ref")), _ref_txt(x.get("e2e"))),
               "ikey": bud_ikey(lid, v["day"], v["amount"], v["kind"], iban if IBAN_RE.match(iban) else None),
               "fi": fi if isinstance(fi, int) and not isinstance(fi, bool) and 0 <= fi < 10000 else 0}
        rr = _rec_of(c, lid, x.get("recurring_id"))
        if rr and rr["id"] not in used_rec and any(o["id"] == rr["id"] for o in open_for(v["day"][:7])):
            v["recurring_id"], v["rmonth"] = rr["id"], v["day"][:7]
            used_rec.add(rr["id"])
        vals.append((v, imp))
    if run is None:
        import secrets  # noqa: PLC0415
        run = secrets.token_hex(8)
        fmt = b.get("fmt") if b.get("fmt") in ("csv", "camt", "mixed") else "csv"
        runs.append({"id": run, "at": iso(now_utc()), "label": cx.csv_clean(b.get("label"), 200), "fmt": fmt, "count": 0, "by": uid})
    dups = _Dups(c, lid)
    created = dup = 0
    for v, imp in sorted(vals, key=lambda t: t[1]["fi"]):  # the rows of one file together (stable: the app's order inside)
        if dups.check({**v, **imp}, imp["fi"]):
            dup += 1
            continue
        entry_insert(c, uid, lid, v, "csv", {"import_run": run, "rkeys": imp["rkeys"], "ikey": imp["ikey"]})
        created += 1
    for x in runs:
        if x["id"] == run:
            x["count"] = int(x.get("count") or 0) + created
    _runs_put(c, lid, runs)
    cols = b.get("columns")
    if b.get("mapping") is not None and isinstance(cols, list) and 0 < len(cols) <= 200 and all(isinstance(x, str) for x in cols):
        _meta_put(c, lid, _hkey([x[:80] for x in cols]), _mapping(b["mapping"], len(cols)))
    return {"created": created, "skipped_dup": dup, "run": run}


def _run_entries(c, lid, run):
    """The entries of an import run still there: (untouched ids, [edited entries]) -- edited = changed after the import
    or with a receipt."""
    rows = c.execute("SELECT * FROM budget_entries WHERE list_id=? AND import_run=? ORDER BY day, id", (lid, run)).fetchall()
    with_files = {r[0] for r in c.execute("SELECT DISTINCT entry_id FROM budget_files WHERE list_id=?", (lid,))} if rows else set()
    plain, edited = [], []
    for r in rows:
        if r["updated_at"] != r["created_at"] or r["id"] in with_files:
            edited.append(r)
        else:
            plain.append(r["id"])
    return plain, edited


def bud_import_runs(c, uid, lid):
    """2.146.0 C (#2455): the list's last import runs, newest first: {id, at, label, fmt, count, left, edited, undone_at}."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    left = {}
    for r in c.execute("SELECT import_run, COUNT(*) FROM budget_entries WHERE list_id=? AND import_run<>'' GROUP BY import_run", (lid,)):
        left[r[0]] = r[1]
    out = []
    for x in reversed(_runs(c, lid)):
        n = left.get(x["id"], 0)
        out.append({"id": x["id"], "at": x.get("at") or "", "label": x.get("label") or "", "fmt": x.get("fmt") or "csv",
                    "count": int(x.get("count") or 0), "left": n, "edited": len(_run_entries(c, lid, x["id"])[1]) if n else 0,
                    "undone_at": x.get("undone_at")})
    return {"items": out}


def bud_import_undo(c, uid, lid, run, b):
    """2.146.0 C (#2455): takes an import run back -- deletes exactly its entries still there (with their receipts; the budget
    has no trash: like deleting an entry). Entries changed after the import (or with a receipt) are kept and named,
    unless edited = "delete" -> ({deleted, kept: [entries]}, file paths to remove after the commit)."""
    bud_need_on(c, uid)
    bud_need_list(c, uid, lid, True)
    if not isinstance(run, str) or not BUD_RUN_RE.match(run):
        raise Denied(404)
    runs = _runs(c, lid)
    it = next((x for x in runs if x["id"] == run), None)
    if it is None:
        raise Denied(404)
    plain, edited = _run_entries(c, lid, run)
    take = plain + ([r["id"] for r in edited] if b.get("edited") == "delete" else [])
    kept = [] if b.get("edited") == "delete" else [entry_out(bud_dec(c, "budget_entries", r)) for r in edited]
    paths = []
    for i in range(0, len(take), 500):
        ids = take[i:i + 500]
        q = ",".join("?" * len(ids))
        paths += [r[0] for r in c.execute(f"SELECT path FROM budget_files WHERE entry_id IN ({q})", ids)]
        c.execute(f"DELETE FROM budget_entries WHERE list_id=? AND id IN ({q})", [lid, *ids])
    if not kept:
        it["undone_at"] = iso(now_utc())
    _runs_put(c, lid, runs)
    return {"deleted": len(take), "kept": kept}, paths


# ---------------------------------------------------------------- the person's export
def bud_export(c, uid):
    """The budgets the person owns, decrypted (Settings > Export): categories, templates, entries, receipt names."""
    out = []
    for l in c.execute("SELECT id, name FROM lists WHERE owner_id=? AND life='budget' ORDER BY id", (uid,)).fetchall():
        lid = l["id"]
        out.append({"list_id": lid, "name": l["name"], "categories": [cat_out(d) for d in _cats(c, lid)],
                    "recurring": [rec_out(d) for d in _rec_rows(c, lid)],
                    "entries": [entry_out(bud_dec(c, "budget_entries", r)) for r in
                                c.execute("SELECT * FROM budget_entries WHERE list_id=? ORDER BY day, id", (lid,))],
                    "files": [dict(r) for r in c.execute("SELECT id, entry_id, name, mime, size, created_at FROM budget_files WHERE list_id=?",
                                                         (lid,))]})
    return out

