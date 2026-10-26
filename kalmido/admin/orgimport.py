"""2.137.0 (#2344): organisation import, stage 2 -- the areas of an organisation export (admin/orgexport.py OX_AREAS) beyond
lists, tasks, calendars and address books (admin/acctimport.py umz_write does those): office, clients, file store,
documents, knowledge pages, tables, chat, absences, forms and the rest.

Each area module (oi_office, oi_store, oi_team) describes its tables as OiT entries in SPECS; this engine creates their
rows in the order given, after the lists and tasks. Like the account import nothing of the file is trusted as an id:
every row is created anew (umz_row: only columns this server has, never ids / *_id / *_by / foreign keys unless mapped
here), references are mapped through run.maps (the kinds of umz_write: lists, tasks, sections, comments, list_fields,
list_tags, list_milestones, books, contacts, ev_cals, events; and every table of SPECS under its own name), people
through who() (only people ticked in the preview), the organisation columns are set to the target. Fields the server
encrypts (core/orgcrypt.py FIELDS) come decrypted from the archive and are encrypted again with the target's key.
Every created row is recorded as [table, id, space] in run.created["oi"]; oi_undo removes them again (newest first).
Into the private space (#1941) an area goes where the private space has the same thing: "office" = the person's own
office (office/model.py pb_personal), "user" = the private space (organisation column NULL); False = not taken over
(named in the preview)."""
import os
import uuid

from ..core.config import ATT_DIR, MAX_FILE_MB, OFFICE_DIR
from ..core.i18n import N_
from .acctimport import UmzStop, _BAD, _coerce, _oid, _read_entry, _txt, tr, umz_cols, umz_insert, umz_row
from .acctimport import UMZ_ORG_SKIP  # 2.278.0 B (#3094)
from ..core.orgcrypt import oc_enc_fields, oc_user_space, oc_write_file  # 2.149.0 G (#2517): pulled up from functions
from ..core.db import iso, now_utc  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import Denied  # 2.237.0 D (#2870)
from ..accounts.orgs import org_role  # 2.237.0 D (#2870)
from ..office.periodlock import pl_month  # 2.237.0 D (#2870)


# 2.237.0 D (#2870): person columns with a name column beside them: a person not taken over as an account keeps the name
OI_NAME_COLS = {("video_comments", "author_id"): "ext_name", ("office_meal_log", "user_id"): "user_name"}


class OiT:
    """One table of the archive.
    path     archive entry ("office/documents.json")
    table    target table
    kind     map kind of its ids (default: table)
    refs     {column: kind} references mapped while inserting (unmapped -> NULL)
    need     columns of refs that must map, else the row is skipped (default: none)
    late     {column: kind} references set after all areas are in (self references, forward references)
    people   {column: "need" | "null" | "me" | "member"}: unmapped person -> skip the row / NULL / the importing person;
             2.237.0 D (#2870): a ticked person only maps in "member" columns (membership, sharing, assignment), every other
             column maps the importing person alone ("member" skips the row like "need")
    space    columns that get the target space (organisation id, personal office id or NULL)
    private  where the rows go on an import into the private space: "office", "user" or False (not taken over)
    label    what the preview / report names (N_ text)
    prep     prep(c, run, src, d, ctx) -> d (or None = skip with a warning, False = skip silently): special values (files, JSON, sealed texts); ctx = OiCtx
    after    after(c, run, src, new_id, ctx): rows that hang on this one in the same entry, logs ...
    (an area module may also have FINISH = [fn(c, run, uid, data, who)]: called once after every area and the late references)
    enc      encrypt the FIELDS of core/orgcrypt.py with the space's key (default True; "user": in the private space with the
             person's own key, core/orgcrypt.py oc_user_space -- only where the app itself seals those rows so)
    rid      the table has an id column (False: link tables without id; nothing is recorded for undo, so only for tables whose
             rows are removed with their parent by a foreign key ON DELETE CASCADE)
    fixed    constant values
    key      2.137.0 A (#2344): tables without id (rid=False) whose rows are recorded for undo by these columns + the space
             column (office_numbers, office_settings ...: [table, {column: value}, space] in run.created["oi"])"""

    def __init__(self, path, table, kind=None, refs=None, need=(), late=None, people=None, space=("org_id",), private="user",
                 label=None, prep=None, after=None, enc=True, rid=True, fixed=None, key=()):
        self.path, self.table, self.kind = path, table, kind or table
        self.refs, self.need, self.late, self.people = refs or {}, tuple(need), late or {}, people or {}
        self.space, self.private, self.label = tuple(space), private, label
        self.prep, self.after, self.enc, self.rid, self.fixed = prep, after, enc, rid, fixed or {}
        self.key = tuple(key)


class OiFix:
    """A reference of a row umz_write created (lists, tasks, events ...) into an area of this engine: set once the area is in.
    data  the data key of the base rows ("lists", "tasks"), kind their map kind, col the column, ref the kind it points at."""

    def __init__(self, data, kind, col, ref):
        self.data, self.kind, self.col, self.ref = data, kind, col, ref


def _areas():
    """The area modules in their order (office first: its clients are referenced by the others)."""
    from . import oi_office, oi_store, oi_team
    return (oi_office, oi_store, oi_team)


def oi_specs():
    return [s for m in _areas() for s in getattr(m, "SPECS", ())]


def oi_fixes():
    return [f for m in _areas() for f in getattr(m, "FIXES", ())]


def oi_covers(path):
    """True when the engine takes this archive entry over (umz_org_open loads it, the preview does not name it as skipped)."""
    return any(s.path == path for s in oi_specs())


def oi_tables():
    return {s.table for s in oi_specs() if s.rid}


def oi_key_tables():
    """2.137.0 A (#2344): {table: key columns} of the tables without id recorded by their key."""
    return {s.table: s.key for s in oi_specs() if not s.rid and s.key}


class OiCtx:
    """What prep / after hooks need besides the row."""

    def __init__(self, c, run, uid, man, zf, files, data, who, spec, space):
        self.c, self.run, self.uid, self.man, self.zf, self.files, self.data, self.who = c, run, uid, man, zf, files, data, who
        self.spec, self.space = spec, space

    def file(self, path, sub, name, space=None, base=ATT_DIR, check=True, mime="", seal=True):
        """The archive file `path` written sealed below base/sub (quota counted, new content scanned like an upload).
        -> (relative path below base, size) or None (missing / refused: a warning is recorded). seal=False: in plain, for
        files the app itself keeps plain (2.137.0 A: the office logos, read by the PDF renderer)."""
        return oi_file(self, path, sub, name, space=self.space if space is None else space, base=base, check=check, mime=mime, seal=seal)


def oi_space(c, run, spec):
    """-> (take, space id) of a spec for this run."""
    if run.org:
        return True, run.org
    if spec.private == "office":
        return bool(getattr(run, "pb", None)), getattr(run, "pb", None)
    if spec.private == "user":
        return True, None
    return False, None


def oi_prepare(c, run, uid, data):
    """Before the run's transaction (pb_personal commits): the personal office when office parts go into the private space."""
    if run.org or getattr(run, "pb", None):
        return
    oi = data.get("oi") or {}
    if any(oi.get(s.path) for s in oi_specs() if s.private == "office"):
        from ..office.model import pb_personal
        run.pb_new = pb_personal(c, uid, create=False) is None  # 2.137.1 (#2399): made by this run (oi_drop_empty_pb)
        run.pb = pb_personal(c, uid)
        from .acctexport import umz_user_conn
        umz_user_conn(c, uid)  # 2.137.0 A (#2344): a personal office made just now joins the thread's access context


def oi_drop_empty_pb(c, run, uid):
    """2.137.1 (#2399): an import that failed removes the personal office oi_prepare made for it -- only while nothing at all
    points at it (every foreign key on orgs checked; something written meanwhile keeps it)."""
    pb = getattr(run, "pb", None) if run is not None and getattr(run, "pb_new", False) else None
    if not pb:
        return False
    from ..core.access import acx_drop
    from ..core.pg import system_ctx
    try:
        with system_ctx(c):  # every table that points at the office, across organisations (only a yes / no leaves this block)
            refs = c.execute("""SELECT con.conrelid::regclass::text, a.attname FROM pg_constraint con
                                JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
                                WHERE con.contype = 'f' AND con.confrelid = 'orgs'::regclass""").fetchall()
            used = any(c.execute(f'SELECT 1 FROM {t} WHERE "{col}"=? LIMIT 1', (pb,)).fetchone() for t, col in refs
                       if t != "org_keys")  # its key (made in an own transaction while sealing) goes with it: nothing is sealed with it any more
            n = 0 if used else c.execute("DELETE FROM orgs WHERE id=? AND personal_of=?", (pb, uid)).rowcount
        c.commit()
    except Exception as e:  # noqa: BLE001 -- the empty office stays (harmless); the import's own error is what counts
        print(f"orgimport: empty personal office left: {type(e).__name__}", flush=True)
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    if n:
        acx_drop()
        run.pb = None
    return bool(n)


def oi_file(ctx, path, sub, name, space=None, base=ATT_DIR, check=True, mime="", seal=True):
    from ..admin.hosting import QuotaExceeded, quota_guard
    from ..files.upsafe import up_check, UploadRefused
    from ..tasks.attachments import safe_name
    from .acctimport import _file_bytes
    c, run = ctx.c, ctx.run
    raw = _file_bytes(ctx.zf, ctx.files, path)
    name = safe_name(_txt(name, 150)) or "file"
    if raw is None:
        run.warning(N_("A file is missing in the export: {0}"), name)
        return None
    if not raw or len(raw) > MAX_FILE_MB * 1024 * 1024 * 4:
        run.warning(N_("A file is empty or too large and was skipped: {0}"), name)
        return None
    try:
        quota_guard(c, ctx.uid, len(raw))
    except QuotaExceeded:
        run.stopped = "quota"
        raise UmzStop() from None
    if check:
        try:
            raw, _m, _i = up_check(c, name, raw, mime or "application/octet-stream", ctx.uid, space if space and space > 0 else None, "att")
        except UploadRefused:
            run.warning(N_("A file could not be taken over: {0}"), name)
            return None
    rel = os.path.join(sub, f"{uuid.uuid4().hex[:12]}-{name}") if sub is not None else name
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(os.path.realpath(base) + os.sep):
        run.warning(N_("A file could not be taken over: {0}"), name)
        return None
    os.makedirs(os.path.dirname(full), exist_ok=True)
    run.written.append(full)
    if seal:
        oc_write_file(c, space or oc_user_space(ctx.uid), full, raw, fresh=True)
    else:  # 2.137.0 A (#2344): a file the app keeps plain
        from ..core.orgcrypt import _write_atomic
        _write_atomic(full, raw)
    run.created.setdefault("oi_files", []).append(full)
    return rel, len(raw)


# 2.278.0 B (#3094): what a dropped row's warning names for tables without a label of their own
_OI_AREA = {"office_payments": N_("Payments"), "office_pay_props": N_("Payments"), "office_trip_items": N_("Travel expenses"),
            "office_cash_entries": N_("Cash book"), "office_cash_closings": N_("Cash book"), "office_cash_log": N_("Cash book"),
            "ev_cal_members": N_("Calendars"), "book_members": N_("Address books")}


def oi_area(spec):
    """2.278.0 B (#3094): the translated area of a spec for a warning (by table, else its label or archive folder)."""
    k = _OI_AREA.get(spec.table) or spec.label or next((t for pre, t in UMZ_ORG_SKIP if spec.path.startswith(pre)), None)
    return tr(k) if k else spec.path


def oi_write(c, run, uid, man, zf, files, data, who):
    """Creates the rows of every area (inside the run's transaction; the caller commits)."""
    oi = data.get("oi") or {}
    ts = iso(now_utc())
    run.created.setdefault("oi", [])
    names = {_oid(p.get("user_id")): _txt(p.get("name"), 100) for p in data.get("people") or [] if isinstance(p, dict)}
    lates = []
    for spec in oi_specs():
        rows = oi.get(spec.path) or []
        if not rows:
            continue
        take, space = oi_space(c, run, spec)
        if not take:
            run.warning(N_("Not taken over into the private space: {0}"), tr(spec.label) if spec.label else spec.path)
            continue
        cols, _fks = umz_cols(c, spec.table)
        if not cols:
            continue
        ctx = OiCtx(c, run, uid, man, zf, files, data, who, spec, space)
        for src in rows:
            run.step()
            fixed = dict(spec.fixed)
            skip = False
            for col, kind in spec.refs.items():
                v = src.get(col)
                new = run.m(kind, v) if v is not None else None
                if new is None and v is not None and col in spec.need:
                    skip = "left" if kind in ("tasks", "comments") and run.m(kind + "_left", v) else True
                    break
                fixed[col] = new
            if skip:  # 2.278.0 B (#3094): counted, one warning per area with the number (never silently; the trash stays behind)
                if skip is True:
                    run.warning(N_("Not taken over because the entry it belongs to is missing: {0}"), oi_area(spec))
                continue
            for col, mode in spec.people.items():
                v = src.get(col)
                new = who(v) if v is not None else None
                if new is not None and new != uid and mode != "member":
                    new = None  # 2.237.0 D (#2870): authors / deciders / owners: the importing person alone (like #2492)
                ncol = OI_NAME_COLS.get((spec.table, col)) if new is None and v is not None else None
                if ncol and (_txt(src.get(ncol), 100) or names.get(_oid(v))):
                    fixed[ncol] = _txt(src.get(ncol), 100) or names.get(_oid(v))
                if new is None and v is not None:
                    if mode in ("need", "member"):
                        skip = True
                        break
                    new = uid if mode == "me" else None
                fixed[col] = new
            if skip:  # 2.278.0 B (#3094)
                run.warning(N_("Entries of people who were not chosen were not taken over: {0}"), oi_area(spec))
                continue
            for col in spec.space:
                fixed[col] = space
            for col in spec.late:
                fixed.setdefault(col, None)
            d = umz_row(c, spec.table, src, fixed, ts)
            if d is not None and spec.prep:
                d = spec.prep(c, run, src, d, ctx)
            if d is False:  # 2.137.0 C (#2344): prep left the row out on purpose (it warned itself, or nothing to warn)
                continue
            if d is None:
                if spec.label:
                    run.warning(N_("A row could not be taken over: {0}"), tr(spec.label))
                continue
            enc_space = space or (oc_user_space(uid) if spec.enc == "user" else None)
            if spec.enc and enc_space:
                d = oc_enc_fields(c, enc_space, spec.table, d)
            nid = umz_insert(c, spec.table, d, rid=spec.rid)
            if not nid:
                if spec.label:
                    run.warning(N_("A row could not be taken over: {0}"), tr(spec.label))
                continue
            if spec.rid:
                run.put(spec.kind, src.get("id"), nid)
                run.created["oi"].append([spec.table, nid, space])
                if spec.late:
                    lates.append((spec, src, nid))
            elif spec.key:  # 2.137.0 A (#2344): a row without id, recorded by its key for the undo
                run.created["oi"].append([spec.table, {k: d.get(k) for k in spec.key}, space])
            if spec.after:
                spec.after(c, run, src, nid, ctx)
            run.count(spec.table)
    for spec, src, nid in lates:  # self and forward references
        sets = {}
        for col, kind in spec.late.items():
            new = run.m(kind, src.get(col))
            if new:
                sets[col] = new
        if sets:
            c.execute(f"UPDATE {spec.table} SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), nid))
    for fx in oi_fixes():  # references of lists / tasks / events into the areas
        if fx.col not in umz_cols(c, fx.data)[0]:
            continue
        for src in data.get(fx.data) or []:
            new_row, new_ref = run.m(fx.kind, src.get("id")), run.m(fx.ref, src.get(fx.col))
            if new_row and new_ref:
                c.execute(f"UPDATE {fx.data} SET {fx.col}=? WHERE id=?", (new_ref, new_row))
    for m in _areas():  # 2.137.0 B (#2344): passes of an area once every row is in (ids inside texts, indexes)
        for fn in getattr(m, "FINISH", ()):
            fn(c, run, uid, data, who)


def oi_counts(data):
    """[{what, count}] of the areas this engine takes over (the preview)."""
    out = {}
    for s in oi_specs():
        n = len((data.get("oi") or {}).get(s.path) or [])
        if n and s.label:
            out[s.label] = out.get(s.label, 0) + n
    return [{"what": tr(k), "count": n} for k, n in out.items()]


def oi_undo(c, cr):
    """Removes the rows this engine created (newest first), then their files. Only tables of SPECS, only rows still in the
    space they were created in. -> number of rows removed."""
    tables = oi_tables()
    space_cols = {s.table: s.space for s in oi_specs()}
    n = 0
    keyed = oi_key_tables()
    for item in reversed(cr.get("oi") or []):
        if isinstance(item, list) and len(item) == 3 and item[0] in keyed and isinstance(item[1], dict):
            n += _oi_undo_key(c, item[0], keyed[item[0]], item[1], item[2], (space_cols.get(item[0]) or (None,))[0])
            continue
        if not (isinstance(item, list) and len(item) == 3 and item[0] in tables and isinstance(item[1], int)):
            continue
        table, rid, space = item
        col = (space_cols.get(table) or (None,))[0]
        if col and col in umz_cols(c, table)[0]:
            if space is None:
                n += c.execute(f"DELETE FROM {table} WHERE id=? AND {col} IS NULL", (rid,)).rowcount
            else:
                n += c.execute(f"DELETE FROM {table} WHERE id=? AND {col}=?", (rid, space)).rowcount
        else:
            n += c.execute(f"DELETE FROM {table} WHERE id=?", (rid,)).rowcount
    return n


# 2.237.0 D (#2870): rows frozen in the target (finalised, a day closing, a locked month) are never removed by an undo
OI_UNDO_LOCKED = N_("The import can no longer be undone: some of its office entries are finalised or lie in a locked month.")
_OI_DATED = {"office_docs": "date", "office_payments": "date", "office_bank_tx": "day", "office_cash_entries": "day",
             "office_trips": "date_from"}  # office/periodlock.py _DATED


def oi_undo_check(c, uid, cr, since):
    """2.237.0 D (#2870): before an undo removes anything (Denied, nothing removed): every organisation the rows went into is
    administered by uid now (a personal office: uid's own); no row was finalised after the import (since = its created_at),
    lies in a month locked by a lock not of this import, or (cash entries) up to a day closing not of this import."""
    items = [x for x in cr.get("oi") or [] if isinstance(x, list) and len(x) == 3]
    for sp in {x[2] for x in items if isinstance(x[2], int)}:
        r = c.execute("SELECT personal_of FROM orgs WHERE id=?", (sp,)).fetchone()
        if not (r and r["personal_of"] == uid) and org_role(c, uid, sp) != "admin":
            raise Denied(403, tr("Only an admin of this organisation can do this"))
    # bundle 2.305 (2.237 + 2.239 D): a closed logbook month keeps its vehicle (vehicle_id has no cascade any more) - the
    # undo says so instead of failing in the database
    veh = [x[1] for x in items if x[0] == "office_vehicles" and isinstance(x[1], int)]
    if veh and c.execute(f"SELECT 1 FROM office_drive_closed WHERE vehicle_id IN ({','.join('?' * len(veh))}) LIMIT 1", veh).fetchone():
        raise Denied(409, tr(OI_UNDO_LOCKED))
    own_locks = {(x[1].get("org_id"), x[1].get("period")) for x in items if x[0] == "office_period_locks" and isinstance(x[1], dict)}
    own_closings = {x[1] for x in items if x[0] == "office_cash_closings" and isinstance(x[1], int)}
    locked, closed = {}, {}
    for table, rid, sp in items:
        if not isinstance(rid, int) or not isinstance(sp, int) or table not in oi_tables():
            continue
        cols = umz_cols(c, table)[0]
        want = [k for k in ("locked_at", _OI_DATED.get(table), "book_id") if k and k in cols]
        if not want:
            continue
        r = c.execute(f"SELECT {', '.join(want)} FROM {table} WHERE id=?", (rid,)).fetchone()
        if r is None:
            continue
        if "locked_at" in want and r["locked_at"] and str(r["locked_at"]) > str(since or ""):
            raise Denied(409, tr(OI_UNDO_LOCKED))
        day = r[_OI_DATED[table]] if table in _OI_DATED else None
        if not day:
            continue
        if sp not in locked:
            locked[sp] = {p["period"] for p in c.execute("SELECT period FROM office_period_locks WHERE org_id=?", (sp,))
                          if (sp, p["period"]) not in own_locks}
        if pl_month(day) in locked[sp]:
            raise Denied(409, tr(OI_UNDO_LOCKED))
        if table == "office_cash_entries" and r["book_id"]:
            if r["book_id"] not in closed:
                closed[r["book_id"]] = max((x["day"] for x in c.execute("SELECT id, day FROM office_cash_closings WHERE book_id=?",
                                            (r["book_id"],)) if x["id"] not in own_closings), default="")
            if closed[r["book_id"]] and str(day) <= closed[r["book_id"]]:
                raise Denied(409, tr(OI_UNDO_LOCKED))


def _oi_undo_key(c, table, key, vals, space, col):
    """2.137.0 A (#2344): removes one row recorded by its key (only the spec's key columns, only in its space)."""
    cols = umz_cols(c, table)[0]
    if not key or set(vals) != set(key) or not all(k in cols for k in key) or not col or col not in cols:
        return 0
    if not (isinstance(space, int) or space is None and any(vals[k] is not None for k in key)):
        return 0  # 2.137.1 (#2399): the private space (column NULL) only with a key that names the row (doc_cfg: ws "u<id>")
    if not all(v is None or isinstance(v, (int, str)) for v in vals.values()):
        return 0
    where = " AND ".join(f"{k} IS NULL" if vals[k] is None else f"{k}=?" for k in key)
    args = [vals[k] for k in key if vals[k] is not None]
    if space is None:
        return c.execute(f"DELETE FROM {table} WHERE {where} AND {col} IS NULL", args).rowcount
    return c.execute(f"DELETE FROM {table} WHERE {where} AND {col}=?", (*args, space)).rowcount


def oi_undo_files(cr):
    roots = [os.path.realpath(ATT_DIR) + os.sep, os.path.realpath(OFFICE_DIR) + os.sep]
    for p in cr.get("oi_files") or []:
        if isinstance(p, str) and any(os.path.realpath(p).startswith(r) for r in roots):
            try:
                os.remove(p)
            except OSError:
                pass


__all__ = ["OiT", "OiFix", "OiCtx", "oi_specs", "oi_covers", "oi_write", "oi_prepare", "oi_drop_empty_pb", "oi_counts", "oi_undo", "oi_undo_check", "oi_undo_files",
           "_BAD", "_coerce", "_oid", "_read_entry", "_txt", "umz_cols", "umz_insert", "umz_row"]
