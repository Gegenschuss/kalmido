"""2.784.0 (#5366, stage 4 of the core's trash): office kinds on the ONE trash of the core (core/writes.py obj_trash /
obj_restore / obj_trash_prune, docs/dev/kern.md). An office kind that deletes by deleted_at is registered here as a core
object without routes, folder node or listing (ofk_register): its own office routes check the office rights as before and
then put the row into the core's trash (ofk_trash: deleted_at / deleted_by, the person's undo step, mode trash) and take it
back (ofk_restore: mode restore); the core's hourly retention run (obj_trash_tick, trash_prune=True) deletes it for good
after the trash period, with its children (obj_register children) -- the area's own purge runs are gone.
The core's role of such a row (the second floor under the route's own check): 'manage' for who may manage the office area
in the kind's rights area (a personal office: its owner; an organisation: the level `need` of deleting it there, the
admin role or the groups, office/rights.py office_can), nothing for anyone else -- no shares, no agents' own way (agents keep the office routes).
GoBD: rows that are locked (booked / finalised) never get here -- the routes refuse to delete them (409) before
ofk_trash, and the retention run only ever reads rows in the trash.
The office trash of copies (office/otrash.py, office_trash) stays for the kinds that delete the row itself (drafts, parts,
trips, card lines, ...) until their stage moves them here.
2.905.0 (#5414, stage 4c): the master data (office/model.py MD), the rights groups, the fixed costs (and
an import of them taken back), the cash flow's corrections and a letter's links moved here. view= shows such a kind in the
office trash (GET /api/office/trash, restore / delete for good through POST/DELETE /api/office/trash/core/<kind>/<id>, the
toast's undo through ?undo=1); old copies of these kinds already in office_trash stay restorable there until their period ends.
2.1004.0 (#5494, stage 4c rest): a kind whose rows may have no organisation (the approval records of deleted video reviews,
office_signoffs: a private one has org_id NULL) registers with personal= the column naming its person; such a row belongs to
that person's personal office (office/model.py pb_personal, never made here) for the gates, the role, the trash list and
the office trash's restore / delete (ofk_office_of).
2.1005.0 (#5415, stage 4d part 1): document drafts (odoc, office/docs.py) and quotation parts (opart, office/parts.py) moved here.
2.1005.0 (#5415, part E): the old copies of office_trash of these kinds come back as rows of the core's trash (ofk_copies_back,
every start); only the start balance still goes as a copy (office/otrash.py OTB_KINDS)."""
import json  # 2.1005.0 (#5415): the copies written back (ofk_copies_back)

from ..core.access import Denied, trash_sql
from ..core.objects import OBJ, obj_register, obj_row
from ..core.pg import qi, system_ctx
from ..core.retention import ret_on, ret_trash_cut
from ..core.writes import OBJ_PURGE, _kids, _purge_rows, obj_purge_after, obj_restore, obj_trash, obj_trash_prune  # 2.993.0 (#5413): + obj_purge_after
from ..core.writes import _unval  # 2.1005.0 (#5415): a copy's bytes (the same encoding as the copies of office/otrash.py)
from ..core.serializers import unlink_files  # 2.993.0 (#5413): an overdue row's stored files after the commit (ofk_restore)
from ..core.objects import obj_forget  # 2.809.0 (#5418)
from ..core.undoweb import undo_trash_reg  # 2.1004.0 (#5494): a kind with a limit takes its undo step back through it
from ..core.pg import write_lock  # 2.809.0 (#5418)
from ..core.pg import table_columns, table_exists, table_names  # 2.1005.0 (#5415)
from .model import office_on, office_role, pb_owner, pb_personal  # 2.1004.0 (#5494): + pb_personal
from ..accounts.orgroles import is_write_request, office_allowed  # 2.809.0 (#5418)
from ..accounts.supportgrant import sga_org_foreign  # 2.809.0 (#5418)
from contextvars import ContextVar  # 2.1005.0 (#5415)
from .rights import office_can  # 2.905.0 (#5414): rights.py never imports this module at its top (its trash kind is registered in office/web.py)

OFK = {}  # kind -> {table, area, need, base, view, step, personal}
_CHECKED = ContextVar("ofk_checked", default=None)  # 2.1005.0 (#5415): (kind, id) a caller checked itself (ofk_trash checked=True)


def _tables():
    """The allowlist of the table names for SQL text (core/pg.py qi): the ones registered here."""
    return {k["table"] for k in OFK.values()}


def ofk_office_of(c, kind, row):
    """2.1004.0 (#5494): the office area of a row of an office kind: its organisation, or for a kind registered with personal=
    a row without one: the personal office of the person its column names (None while that person has none)."""
    if row is None:
        return None
    if row["org_id"]:
        return row["org_id"]
    col = OFK.get(kind, {}).get("personal")
    return pb_personal(c, row[col], create=False) if col and row[col] else None


def _base_of(kind):
    def base(c, uid, rid):
        row = obj_row(c, kind, rid)
        oid = ofk_office_of(c, kind, row)  # 2.1004.0 (#5494): + a personal kind's row without an organisation
        if not oid:
            return None
        if _CHECKED.get() == (kind, int(rid)):  # 2.1005.0 (#5415): the caller checked its own rights (ofk_trash checked=True)
            return "manage"
        # 2.809.0 (#5418): the same gates as the office routes (office_gate / office_org) also on the core's way (/api/undo,
        # the trash): the office switched on for the person, the organisation role may write there (office_allowed: no
        # read-only, accounting or guest), and a support session writes into no foreign organisation (sga_org_foreign)
        if not office_on(c, uid) or office_allowed(c, uid, oid, write=True) is not None:
            return None
        if is_write_request() and sga_org_foreign(c, oid):
            return None
        if OFK[kind].get("base"):  # 2.905.0 (#5414): a kind whose rights are not one area's level (the rights groups), after the gates
            return OFK[kind]["base"](c, uid, row)
        owner = pb_owner(c, oid)
        if owner is not None:  # a personal office: only its owner
            return "manage" if owner == uid else None
        if office_role(c, uid, oid) is None:
            return None  # not of this organisation at all
        k = OFK[kind]
        return "manage" if office_can(c, uid, oid, k["area"], k["need"]) else None
    return base


def _visible_of(table, personal=None):
    def visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
        u = int(uid)
        own = f" OR (org_id IS NULL AND {qi(personal, (personal,))} = {u})" if personal else ""  # 2.1004.0 (#5494)
        return (f"(SELECT id FROM {qi(table, _tables())} WHERE org_id IN (SELECT id FROM orgs WHERE personal_of = {u}) "
                f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}){own})")
    return visible


def _space_of(table):
    def space(c, rid):
        r = c.execute(f"SELECT org_id FROM {qi(table, _tables())} WHERE id=?", (int(rid),)).fetchone()
        if r is None:
            return None
        # a personal office has no organisation floor (its owner is checked by the base role), an organisation's has
        return (None, None) if pb_owner(c, r["org_id"]) is not None else (r["org_id"], None)
    return space


def ofk_register(kind, table, label, area, need="manage", children=(), base=None, view=None, step=True, trash_keep=None,
                 personal=None, limit=None):
    """Registers an office kind on the core's trash (module docstring); area = its rights area (office/rights.py), need =
    the level its route needs to delete a row (an "own" level: the route checks the row is the person's own).
    2.905.0 (#5414): base(c, uid, row) -> 'manage' | None replaces the area's level (the rights groups: who manages the
    rights); view = {"kind": the app's name of it (or fn(row)), "label": fn(c, oid, row) -> text, "ctx": the module's context
    () -> (c, uid, oid) for the toast's undo, "back": fn(c, oid, row) after a restore} shows it in the office trash.
    2.1005.0 (#5415): view "lock" = fn(oid, row) -> the names of the area's write locks the office trash's restore takes first
    (otrash.otb_core_restore: a draft's number, a part's quotation, a statement's positions, as the kind's own routes);
    view "where" = a fixed SQL condition (no parameters) on the kind's rows of the office trash list (the
    receipts that went into the trash with their trip are the trip's entry).
    2.905.0 (#5414, review): step=False = no step in the person's undo list (GET /api/undo): a kind whose route does more
    than the core on trash / restore (in-use checks, members out, the view's back hook) is only taken back through its
    own routes (the toast's undo, the office trash), never by the core's undo / redo that would skip them.
    2.993.0 (#5413): trash_keep = obj_register trash_keep (rows of the trash kept by law, the retention run leaves them; the
    exact check stays the kind's obj_on_purge hook, Denied = kept).
    2.1004.0 (#5494): personal = the column naming the person of a row without an organisation (ofk_office_of); limit =
    fn(c, oid, row) after a restore (ofk_restore, the office trash, the toast's undo and - for a kind with a step - the
    person's undo list): raises Denied(409) when the row back would pass the kind's maximum (delete, add anew, restore)."""
    OFK[kind] = {"table": table, "area": area, "need": need, "base": base, "view": view, "step": step, "personal": personal,
                 "limit": limit}
    if limit and step:  # 2.1004.0 (#5494): the person's undo list takes a trash step back through the limit too
        undo_trash_reg(kind, lambda c, uid, rid: _restored(c, uid, kind, rid, undo=True, step=False),
                       lambda c, uid, rid: obj_trash(c, uid, kind, rid, step=False))
    return obj_register(kind, table, label=label, fields={}, area="office", routes=False, listed=False, fsref=False,
                        space=_space_of(table), base_role=_base_of(kind), visible=_visible_of(table, personal), cap=lambda c, uid, rid: None,
                        scopes=("office", "office"), children=children, trash_prune=True, trash_keep=trash_keep)


def ofk_trash(c, uid, kind, rid, checked=False):
    """Into the core's trash (the route checked the office rights and that the row may go); one undo step of the person
    (not for a kind registered with step=False, see ofk_register).
    2.1005.0 (#5415): checked=True = a way of its own checked the rights already (a table's offer step or an agent's proposal
    taken back: office/docs.py odoc_trash): the core's role of the row is 'manage' for this one call."""
    tok = _CHECKED.set((kind, int(rid))) if checked else None
    try:
        return obj_trash(c, uid, kind, rid, step=OFK.get(kind, {}).get("step", True))
    finally:
        if tok is not None:
            _CHECKED.reset(tok)


def ofk_restore(c, uid, kind, rid, undo=False):
    """Out of the core's trash. One past the trash period (switch on) is deleted for good first and answers 404 (committed
    before the refusal rolls back), as the office's own runs did on the next write. undo: the person's own step taken back
    (core/writes.py obj_restore undo=True: only who put it there, while it is still that trash)."""
    row = obj_row(c, kind, rid)
    if row is not None and row["deleted_at"] and ret_on("trash"):
        with system_ctx(c):
            due = c.execute(f"SELECT 1 FROM {qi(OBJ[kind]['table'], _tables())} WHERE id=? AND deleted_at<?", (int(rid), ret_trash_cut())).fetchone()
        if due:
            with obj_purge_after(keep_locked=True) as box:  # 2.993.0 (#5413): its stored files (obj_on_purge) after the commit
                obj_trash_prune(c, kind, purge=True, ids=[int(rid)])
            c.commit()
            unlink_files(box["after"])
            with system_ctx(c):
                kept = c.execute(f"SELECT 1 FROM {qi(OBJ[kind]['table'], _tables())} WHERE id=?", (int(rid),)).fetchone()
            if kept and box["err"]:  # 2.993.0 (#5413, fable F2): the purge failed (not a lock) - no restore of a half-checked row,
                raise Denied(409)  # the next retention run tries again
            if kept:  # kept by law (a receipt: trash_keep / the hook's Denied): it stays in the trash and comes back as any other
                return _restored(c, uid, kind, rid, undo=undo, step=OFK.get(kind, {}).get("step", True))
            raise Denied(404)
    return _restored(c, uid, kind, rid, undo=undo, step=OFK.get(kind, {}).get("step", True))  # 2.905.0 (#5414, review): ofk_register step


def _restored(c, uid, kind, rid, undo, step):
    """obj_restore, then 2.1004.0 (#5494) the kind's limit (ofk_register limit=; Denied rolls the restore back)."""
    row = obj_restore(c, uid, kind, rid, undo=undo, step=step)
    lim = OFK.get(kind, {}).get("limit")
    if lim and row is not None:
        lim(c, ofk_office_of(c, kind, row), dict(row))
    return row


def ofk_purge(c, kind, rid):
    """2.809.0 (#5418): delete one row of an office kind for good on the core's way (core/writes.py _purge_rows: its history,
    undo steps with their emptied groups, revoked shares and children go along, no obj_undo / obj_history left behind) --
    for the office's own deletes that checked the rights themselves (the DATEV import's undo, office/datevimp.py di_undo)."""
    write_lock(c, f"obj-{kind}-{int(rid)}")
    _purge_rows(c, kind, OBJ[kind], rid)
    obj_forget()


def ofk_purge_many(c, kind, ids):
    """2.1015.0 (#5675): ofk_purge for many rows of one kind in one transaction (a data import's undo, a moving office's letter
    links, an agent import's undo). ofk_purge holds one advisory lock per row until the commit - a few thousand of them
    (FI_ROWS_MAX 2000 per sheet, four kinds) break the transaction with "out of shared memory" (max_locks_per_transaction).
    Here: ONE advisory lock for the kind's mass deletes (two of them one after the other) and the rows' own row locks
    (SELECT ... FOR UPDATE, kept on the rows, not in the lock table) in id order - a single write (obj_write, obj_trash,
    obj_restore) updates its row and so waits for this commit, as it waited for the row's advisory lock. Each row then goes
    the core's way as in ofk_purge. -> the number of ids handed in."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return 0
    reg = OBJ[kind]
    t = reg["table"]
    # review: a kind with children or an area's purge hook locks those before its row elsewhere (obj_restore) - one row at a time
    if _kids(reg) or kind in OBJ_PURGE:
        raise ValueError(f"ofk_purge_many: {kind} has children or a purge hook, use ofk_purge")
    write_lock(c, f"obj-{kind}-many")
    c.execute(f"SELECT id FROM {qi(t, _tables())} WHERE id = ANY(CAST(? AS BIGINT[])) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    for rid in ids:
        _purge_rows(c, kind, reg, rid)
    obj_forget()
    return len(ids)


def ofk_kind_of(table):
    """2.1004.0 (#5494): the office kind registered here for table (None: not on the core's trash) -- for a hard delete of a
    row that may be one (ofk_purge instead of a DELETE, so no obj_history / obj_undo is left behind)."""
    return next((k for k, v in sorted(OFK.items()) if v["table"] == table), None)


def ofk_trash_items(c, oid, uid=None):
    """2.905.0 (#5414): the rows of office area oid in the core's trash of the kinds shown in the office trash (view=), in the
    shape of the office trash's list (GET /api/office/trash) plus core = the core's kind; id = the row's id.
    2.1005.0 (#5415): uid given = only the kinds ofk_view_may lets uid see (a draft also for who may manage documents);
    view "sub" = fn(row) -> the list's sub (a document's kind)."""
    out, owner = [], pb_owner(c, oid)
    for kind, k in sorted(OFK.items()):
        v = k.get("view")
        if not v:
            continue
        if uid is not None and not ofk_view_may(c, uid, oid, kind):
            continue
        more = f" AND {v['where']}" if v.get("where") else ""  # 2.1005.0 (#5415): view where = a fixed SQL condition of the kind's rows
        # 2.1004.0 (#5494): a personal office lists the rows without an organisation of its owner too (personal=)
        mine, args = (f"(org_id=? OR (org_id IS NULL AND {qi(k['personal'], (k['personal'],))}=?))", (oid, owner)) \
            if k.get("personal") and owner is not None else ("org_id=?", (oid,))
        for r in c.execute(f"SELECT * FROM {qi(k['table'], _tables())} WHERE {mine} AND {trash_sql()}{more} "
                           "ORDER BY deleted_at DESC, id DESC LIMIT 500", args).fetchall():  # review 2.905.0: bounded per kind
            row = dict(r)
            out.append({"id": row["id"], "core": kind, "kind": v["kind"](row) if callable(v["kind"]) else v["kind"],
                        "sub": v["sub"](row) if v.get("sub") else "",
                        "ref_id": row["id"], "label": (v["label"](c, oid, row) or "")[:300], "deleted_by": row.get("deleted_by"),
                        "deleted_at": str(row["deleted_at"])})
    return out


def ofk_view_may(c, uid, oid, kind):
    """2.1005.0 (#5415): may uid see, restore and delete for good the rows of kind in the office trash of area oid? The office
    admin always (2.993.0, #5413 fable F1: the core's rows are the admin's alone); a kind registered with view "who" =
    fn(c, uid, oid) also who that names (a document draft: who may delete it, office/docs.py)."""
    if office_role(c, uid, oid) == "admin":
        return True
    who = (OFK.get(kind, {}).get("view") or {}).get("who")
    return bool(who and who(c, uid, oid))


# 2.1005.0 (#5415, stage 4d part E): the references of a table (was office/otrash.py otb_refs / otb_dangling, the copies' office
# trash is gone): a draft going into the core's trash empties what the database's ON DELETE SET NULL emptied on a delete
# (office/docs.py odoc_trash), and the copies written back below
OFK_REFS = {}  # table -> [(child table, column, 'c' cascade | 'n' set null)]
OFK_OUT = {}  # table -> [(column, referenced table, referenced column)]: its single-column ON DELETE SET NULL references


def ofk_fk_refs(c, table):
    """The single-column foreign keys pointing at table (cached per process)."""
    if table not in OFK_REFS:
        OFK_REFS[table] = [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT cl.relname, a.attname, co.confdeltype FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid "  # pg-ok: catalog oid (Postgres only)
            "JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=co.conkey[1] WHERE co.contype='f' "
            "AND co.confrelid=CAST(? AS regclass) AND array_length(co.conkey, 1)=1 ORDER BY cl.relname, a.attname", (table,))
            if r[2] in ("c", "n")]
    return OFK_REFS[table]


def _dangling(c, table, row):
    """The columns of row whose ON DELETE SET NULL reference names a row gone for good (a client purged after the draft went
    into the trash): emptying them is what the database had done had the row still been there (2.552.0, #4561 B19)."""
    if table not in OFK_OUT:
        OFK_OUT[table] = [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT a.attname, cl.relname, fa.attname FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.confrelid "  # pg-ok: catalog oid (Postgres only)
            "JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=co.conkey[1] "
            "JOIN pg_attribute fa ON fa.attrelid=co.confrelid AND fa.attnum=co.confkey[1] WHERE co.contype='f' "
            "AND co.conrelid=CAST(? AS regclass) AND array_length(co.conkey, 1)=1 AND co.confdeltype='n' ORDER BY a.attname", (table,)).fetchall()]
    names = table_names(c)
    out = []
    for col, ref, rcol in OFK_OUT[table]:
        if row.get(col) is not None and not c.execute(f"SELECT 1 FROM {qi(ref, names)} WHERE {qi(rcol, table_columns(c, ref))}=?",
                                                      (row[col],)).fetchone():
            out.append(col)
    return out


# 2.1005.0 (#5415, stage 4d part E, one way): the copies an older version put into office_trash (a draft, a quotation's part,
# a trip, a card position, master data, ...: office/otrash.py otb_put before 2.1005) go back into their tables as rows of the
# core's trash -- deleted_at / deleted_by of the copy, the children of the kind (obj_register children) with the same time, the
# other rows of the copy (a draft's positions, parts, payments) live with it as on any draft of the core's trash; sealed columns
# as stored. The core's trash lists, restores and purges them from then on (its period counts from the copy's deleted_at).
# A draft as odoc_trash leaves it: number / series place free (kept in trash_refs, back on restore where still free), the
# emptied references and billed time entries in trash_refs; a finalised quotation as a draft (its delete since 2.1005). A copy
# whose row or a unique key is there again (restored meanwhile, a new text with its key) is left in office_trash and counted.
# Every start (kalmido/startup.py after init_db, the app's modules loaded): a no-op once no copy of a core kind is left; the table stays for
# one more version (an older version still reads it).
def _copy_insert(c, table, names, row):
    cols = table_columns(c, table)
    c.execute(f"INSERT INTO {qi(table, names)}({','.join(qi(k, cols) for k in row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _doc_refs_row(row, snap, orig):
    """A copied draft as odoc_trash leaves it (office/docs.py); orig = the copy's row before a reference gone for good was emptied
    (the restore's answer says "without a client")."""
    refs = {"number": orig.get("number") or "", "series_id": orig.get("series_id"), "series_period": orig.get("series_period") or "",
            "client_id": orig.get("client_id"), "nulls": [[t, col, list(ids)] for t, col, _v, ids in snap.get("nulls") or []]}
    row.update(number="", series_id=None, client_ref=None, trash_refs=json.dumps(refs))
    if row.get("locked_at") and (row.get("kind") != "offer" or (row.get("status") or "draft") != "draft" or row.get("sent_at")):
        raise Denied(409)  # review 2.1005.0 (F3): only a finalised quotation never sent ever came here; anything else stays a copy
    if row.get("locked_at"):  # a finalised quotation never sent: as a draft (ledger.ofx_unlock), a finalised row never lies in the trash
        row.update(locked_at=None, locked_by=None, sender=None, recipient_snapshot=None, tax_snapshot=None, pdf_sha256="", xml_sha256="")
    return row


def _copy_back(c, kind, t, snap, names):
    """Copy t (a row of office_trash) of kind back; raises on a conflict (the caller's savepoint takes it all back)."""
    ts, by = t["deleted_at"], t["deleted_by"]
    table, top = snap["rows"][0]
    cols = table_columns(c, table)
    ids = []
    for raw in top:
        row = {k: _unval(v) for k, v in raw.items() if k in cols}
        if "org_id" in cols and ofk_office_of(c, kind, row) != t["org_id"]:
            raise Denied(409)  # review 2.1005.0 (F2): never into another area than the copy's (a personal kind's row without an
            # organisation: its person's personal office, as the copy named it - an old sign-off record's copy, #5494)
        orig = dict(row)
        if c.execute(f"SELECT 1 FROM {qi(table, names)} WHERE id=?", (row["id"],)).fetchone():
            raise Denied(409)  # restored meanwhile (or its id taken)
        for col in _dangling(c, table, row):  # gone for good since: empty, as the database had done
            row[col] = None
        row.update(deleted_at=ts, **({"deleted_by": by} if "deleted_by" in cols else {}))
        if table == "office_docs":
            row = _doc_refs_row(row, snap, orig)
        _copy_insert(c, table, names, row)
        ids.append(row["id"])
    kids = OBJ[kind].get("children") or ()
    for table2, rows2 in snap["rows"][1:]:
        if table2 not in names:
            continue
        cols2 = table_columns(c, table2)
        mine = [col for kt, col in kids if kt == table2]
        for raw in rows2:
            row = {k: _unval(v) for k, v in raw.items() if k in cols2}
            if "org_id" in cols2 and row.get("org_id") is not None and row.get("org_id") != t["org_id"]:
                continue  # review 2.1005.0 (F2): a child of another area never comes back
            if "deleted_at" in cols2 and any(row.get(col) in ids for col in mine):
                row["deleted_at"] = ts  # a child of the kind: in the trash with it (core/writes.py _kids_trash)
            try:  # a row that cannot come back (its other parent is gone, a duplicate) is left out, as the copies' restore did
                with c.savepoint():
                    _copy_insert(c, table2, names, row)
            except Exception:  # noqa: BLE001
                continue
    if table != "office_docs":  # the references emptied on the delete point at it again (the row is there, in the trash)
        for table2, col, value, rids in snap.get("nulls") or []:
            cols3 = table_columns(c, table2) if table2 in names else ()
            if col in cols3:  # review 2.1005.0 (F2): only rows of the copy's area
                area = " AND org_id=?" if "org_id" in cols3 else ""
                c.execute(f"UPDATE {qi(table2, names)} SET {qi(col, cols3)}=? WHERE id = ANY(CAST(? AS BIGINT[])) "
                          f"AND {qi(col, cols3)} IS NULL{area}", (value, list(rids), *((t["org_id"],) if area else ())))


def ofk_copies_back(c):
    """The copies of office_trash of the kinds on the core's trash back into their tables (see above) -> {back, kept}."""
    out = {"back": 0, "kept": 0}
    if not table_exists(c, "office_trash"):
        return out
    kinds = {k["table"]: kind for kind, k in OFK.items()}
    names = table_names(c)
    with system_ctx(c):
        for t in c.execute("SELECT * FROM office_trash ORDER BY id").fetchall():
            try:  # review 2.1005.0 (F1): a copy that cannot be read stays a copy, the start goes on
                snap = json.loads(t["snap"] or "{}")
                rows = (snap.get("rows") or []) if isinstance(snap, dict) else []
                kind = kinds.get(rows[0][0]) if rows and (snap.get("key") or "id") == "id" else None
                if kind is None or rows[0][0] not in names or "deleted_at" not in table_columns(c, rows[0][0]):
                    continue  # a kind not on the core's trash (the start balance): stays a copy
            except (ValueError, TypeError, IndexError, KeyError, AttributeError):
                continue
            try:
                with c.savepoint():
                    # review 2.1005.0 (F7): the copy is taken first -- a second process starting at once skips it
                    if not c.execute("DELETE FROM office_trash WHERE id=?", (t["id"],)).rowcount:
                        continue
                    _copy_back(c, kind, t, snap, names)
                out["back"] += 1
            except Exception as e:  # noqa: BLE001  (a conflict: the copy stays, counted)
                out["kept"] += 1
                print(f"office trash: copy {t['id']} ({t['kind']}) stays a copy: {type(e).__name__}", flush=True)  # review F8
    return out
