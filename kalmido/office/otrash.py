"""2.272.0 E2 (#3038): the office trash -- deleted document drafts and master data (services, texts, contracts, ...).

Before the row goes, otb_put stores a raw copy (office_trash.snap): the row, the rows that go with it by ON DELETE CASCADE
(positions, parts, signoff links, ... -- read from the database's foreign keys, so a new child table is covered) and the
rows whose reference is emptied by ON DELETE SET NULL (and the time entries the draft billed). Sealed columns stay sealed
as they are stored. The office lists never see the trash (the row is gone), so numbers, exports and the agent API stay as
they are. GET /api/office/trash lists the trash of the office area, POST .../<id>/restore writes the copy back with the
old ids (a number taken since is left empty, a reference emptied since is set again only where it is still empty),
DELETE .../<id> (the app asks first) deletes one copy for good. After the trash period (ret_days("trash"), at least one day)
files/trashpurge.py tp_tick calls otb_tick: it counts, and deletes the copies while ret_on("trash") is on.
Booked / sent documents never come here: they stay locked (legal retention). 2.530.0 C (#4315): also a finalised quotation
that was never sent (deleting it is allowed, bga_offer_block), trips and travel receipts (kinds trip / trip_item, office/travel.py)."""
import base64
import json
from datetime import timedelta

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.pg import IntegrityError, insert_id, system_ctx, table_columns, write_lock
from ..core.i18n import tr
from ..core.db import bump, iso, iso_ms, now_utc, parse_iso
from ..core.access import Denied
from ..core.retention import ret_days
from .ledger import ofx_log
from .model import office_ctx, office_role
from .rights import ofr_admin_or

OTB_REFS = {}  # table -> [(child table, column, 'c' cascade | 'n' set null)]
OTB_DEPTH = 3


def otb_refs(c, table):
    """The single-column foreign keys pointing at table (cached per process)."""
    if table not in OTB_REFS:
        OTB_REFS[table] = [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT cl.relname, a.attname, co.confdeltype FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid "  # pg-ok: catalog oid (Postgres only)
            "JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=co.conkey[1] WHERE co.contype='f' "
            "AND co.confrelid=CAST(? AS regclass) AND array_length(co.conkey, 1)=1 ORDER BY cl.relname, a.attname", (table,))
            if r[2] in ("c", "n")]
    return OTB_REFS[table]


def _val(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    return v


def _unval(v):
    return base64.b64decode(v["$b"]) if isinstance(v, dict) and "$b" in v else v


def otb_snap(c, table, ids, out=None, depth=0):
    """{"rows": [[table, [rows]]] parents first, "nulls": [[table, column, value, [row ids]]]}"""
    out = out or {"rows": [], "nulls": []}
    rows = c.execute(f"SELECT * FROM {table} WHERE id = ANY(CAST(? AS BIGINT[])) ORDER BY id", (list(ids),)).fetchall()
    if not rows:
        return out
    out["rows"].append([table, [{k: _val(r[k]) for k in r.keys()} for r in rows]])
    for child, col, kind in otb_refs(c, table):
        if "id" not in table_columns(c, child):  # 2.530.0 C (#4315): a link table without an id (life_trip_costs -> office_trips)
            continue  # cannot be pointed at by id: its reference stays emptied after a restore
        for pid in [r["id"] for r in rows]:
            got = [x[0] for x in c.execute(f"SELECT id FROM {child} WHERE {col}=?", (pid,)).fetchall()]
            if not got:
                continue
            if kind == "n":
                if not (child == table and set(got) <= set(ids)):
                    out["nulls"].append([child, col, pid, got])
            elif depth < OTB_DEPTH:
                otb_snap(c, child, got, out, depth + 1)
    return out


def otb_put(c, oid, uid, kind, table, rid, label, sub="", extra_nulls=()):
    """Stores the copy of row rid of table (call it BEFORE the DELETE, in the same transaction). -> the trash id"""
    snap = otb_snap(c, table, [rid])
    snap["nulls"] += [list(x) for x in extra_nulls]
    tid = insert_id(c, "INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
                     (oid, kind, sub or "", rid, (label or "")[:300], json.dumps(snap, default=str), uid, iso_ms(now_utc())))
    if has_request_context():
        g.otb_id = tid  # the route's answer names it (trash_id: the app's Undo)
    return tid


def dvb_otb_draft(c, oid, uid, did):
    """2.533.0 A2 (#4318 B20): the office trash copy of draft did before an undo deletes it (a table's offer step, an agent's
    proposal taken back), labelled as docs.odoc_delete does, with the time entries it billed. None when the row is gone."""
    r = c.execute("SELECT id, kind, number, project_title, client_id FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    if not r:
        return None
    te = [x[0] for x in c.execute("SELECT id FROM time_entries WHERE billed_doc_id=?", (did,)).fetchall()]
    cl = c.execute("SELECT name FROM clients WHERE id=?", (r["client_id"],)).fetchone() if r["client_id"] else None
    return otb_put(c, oid, uid, "doc", "office_docs", did, " · ".join(x for x in (r["project_title"] or r["number"], cl and cl["name"]) if x),
                   sub=r["kind"], extra_nulls=[("time_entries", "billed_doc_id", did, te)] if te else ())


OTB_OUT = {}  # table -> [(column, referenced table, referenced column)]: its single-column ON DELETE SET NULL references


def otb_dangling(c, table, row):
    """2.552.0 (#4561 B19): the columns of row whose ON DELETE SET NULL reference points at a row gone for good since (a client
    purged after the draft went to the trash). Emptying them is what the database had done had the row still been there."""
    if table not in OTB_OUT:
        OTB_OUT[table] = [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT a.attname, cl.relname, fa.attname FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.confrelid "  # pg-ok: catalog oid (Postgres only)
            "JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=co.conkey[1] "
            "JOIN pg_attribute fa ON fa.attrelid=co.confrelid AND fa.attnum=co.confkey[1] WHERE co.contype='f' "
            "AND co.conrelid=CAST(? AS regclass) AND array_length(co.conkey, 1)=1 AND co.confdeltype='n' ORDER BY a.attname", (table,)).fetchall()]
    # 2.552.0 (#4561, review F2): whether the row is there at all, like the database's own check (row-level security
    # would hide a row of another organisation that is still there and must not be emptied); only yes / no leaves the block
    with system_ctx(c):
        return [col for col, ref, rcol in OTB_OUT[table]
                if row.get(col) is not None and not c.execute(f"SELECT 1 FROM {ref} WHERE {rcol}=?", (row[col],)).fetchone()]


def _insert(c, table, row):
    if table == "office_docs":  # 2.370.2 (#3088): the same request may have made a new document meanwhile (ofi_ref_doc)
        row = {**row, "client_ref": None}
    c.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def otb_restore(c, oid, tid, notes=None):
    """Writes trash copy tid of office area oid back (the caller checked the rights and commits). -> (kind, ref_id); notes (a
    dict) gets "gone": [columns emptied because what they named is gone for good] (2.552.0, #4561 B19)."""
    r = c.execute("SELECT * FROM office_trash WHERE id=? AND org_id=? FOR UPDATE", (tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    snap = json.loads(r["snap"] or "{}")
    for n, (table, rows) in enumerate(snap.get("rows") or []):
        cols = table_columns(c, table)
        for raw in rows:
            row = {k: _unval(v) for k, v in raw.items() if k in cols}
            if n == 0:  # the object itself: it must come back whole
                if c.execute(f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)).fetchone():
                    raise Denied(409, tr("Already restored"))
                if table == "office_docs":
                    if row.get("number") and c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=?", (oid, row["number"])).fetchone():
                        if row.get("locked_at"):  # 2.530.0 (#4315, review K1): a finalised document never comes back without its number
                            raise Denied(409, tr("The number {0} is already used", row["number"]))
                        row["number"] = ""  # taken since: the draft comes back without one
                    if row.get("series_id") and c.execute("SELECT 1 FROM office_docs WHERE series_id=? AND series_period IS NOT DISTINCT FROM ?",
                                                          (row["series_id"], row.get("series_period"))).fetchone():
                        row["series_id"] = None  # the series made this period again meanwhile
                if "updated_at" in cols:
                    row["updated_at"] = iso(now_utc())
                gone = otb_dangling(c, table, row)  # 2.552.0 (#4561 B19): a client gone for good since: back without it, the answer says so
                if gone and table == "office_docs" and row.get("locked_at"):  # 2.552.0 (#4561, review F1): a finalised document never comes back changed
                    raise Denied(409, tr("This cannot be restored: something it refers to (a client, a service) is gone meanwhile."))
                for col in gone:
                    row[col] = None
                if notes is not None and gone:
                    notes["gone"] = gone
                try:  # 2.272.0 F (#3038, review E2-M2): something else it needs is gone for good since: 409, not 500
                    with c.savepoint():
                        _insert(c, table, row)
                except IntegrityError:
                    raise Denied(409, tr("This cannot be restored: something it refers to (a client, a service) is gone meanwhile.")) from None
                continue
            try:  # a row that cannot come back (its other parent is gone, a duplicate) is left out
                with c.savepoint():
                    _insert(c, table, row)
            except Exception:  # noqa: BLE001  (any refusal of the database: the row stays out, the rest comes back)
                continue
    for table, col, value, ids in snap.get("nulls") or []:
        if col in table_columns(c, table):
            c.execute(f"UPDATE {table} SET {col}=? WHERE id = ANY(CAST(? AS BIGINT[])) AND {col} IS NULL", (value, list(ids)))
    c.execute("DELETE FROM office_trash WHERE id=?", (tid,))
    return r["kind"], r["ref_id"]


def otb_tick(c, cut, purge):
    """Copies in the trash since before cut (the caller runs it in the system context): counted, deleted while purge is on."""
    if purge:
        return c.execute("DELETE FROM office_trash WHERE deleted_at<?", (cut,)).rowcount
    return c.execute("SELECT COUNT(*) FROM office_trash WHERE deleted_at<?", (cut,)).fetchone()[0]


def _ctx_admin():
    c, uid, oid = office_ctx()
    if office_role(c, uid, oid) != "admin" and not ofr_admin_or(c, uid, oid, "offers", "manage"):
        raise Denied(403, tr("Only an admin of this workspace can do this"))
    return c, uid, oid


def _need_kind(c, uid, oid, tid):
    """Master data (services, texts, contracts, ...) only for the office admin, as deleting them."""
    r = c.execute("SELECT kind FROM office_trash WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["kind"] != "doc" and office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this workspace can do this"))


@app.get("/api/office/trash")
def otb_list():
    """The trash of the office area (admins / people who may manage documents): newest first, without the copies."""
    c, uid, oid = _ctx_admin()
    rows = c.execute("SELECT id, kind, sub, ref_id, label, deleted_by, deleted_at FROM office_trash WHERE org_id=? "
                     "ORDER BY deleted_at DESC, id DESC LIMIT 500", (oid,)).fetchall()
    return jsonify(items=[dict(r) for r in rows], days=max(1, ret_days("trash")))


@app.post("/api/office/trash/<int:tid>/restore")
def otb_restore_route(tid):
    c, uid, oid = _ctx_admin()
    write_lock(c, f"office_trash_{int(tid)}")
    _need_kind(c, uid, oid, tid)
    t0 = c.execute("SELECT deleted_at FROM office_trash WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    notes = {}
    kind, ref = otb_restore(c, oid, tid, notes)
    if kind in ("trip", "trip_item"):  # 2.530.0 C (#4315, B17): a trip / travel receipt only into open months
        from .travel import rk_trash_check
        rk_trash_check(c, oid, kind, ref)
    if kind == "cc_line":  # 2.552.0 (#4561 B21): a credit card position only into its statement while that is a draft
        from .cardlines import cl_trash_check
        cl_trash_check(c, oid, ref)
    if kind == "contracts" and t0:  # 2.272.0 F (#3038, review E2-M3): its PDF files that went with it come back too
        since = parse_iso(t0["deleted_at"]) - timedelta(seconds=2)
        for f in c.execute("SELECT id, deleted_at FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NOT NULL",
                           (oid, int(ref))).fetchall():
            if parse_iso(f["deleted_at"]) >= since:
                c.execute("UPDATE office_contract_files SET deleted_at=NULL WHERE id=?", (f["id"],))
    ofx_log(c, oid, "restore", **({"doc_id": ref} if kind == "doc" else {"target": kind}), detail={"id": ref})
    bump(c)
    c.commit()
    out = {"gone": notes["gone"]} if notes.get("gone") else {}
    if "client_id" in out.get("gone", ()):  # 2.552.0 (#4561 B19): the app shows this sentence
        out["note"] = tr("Restored without a client: the client was deleted for good meanwhile.")
    return jsonify(ok=True, kind=kind, id=ref, **out)


@app.delete("/api/office/trash/<int:tid>")
def otb_delete_route(tid):
    """Deletes one copy for good (the app asks first)."""
    c, uid, oid = _ctx_admin()
    _need_kind(c, uid, oid, tid)
    n = c.execute("DELETE FROM office_trash WHERE id=? AND org_id=?", (tid, oid)).rowcount
    if not n:
        raise Denied(404)
    bump(c)
    c.commit()
    return jsonify(ok=True)
