"""2.272.0 E2 (#3038): the office trash -- deleted document drafts and master data (services, texts, contracts, ...).

Before the row goes, otb_put stores a raw copy (office_trash.snap): the row, the rows that go with it by ON DELETE CASCADE
(positions, parts, signoff links, ... -- read from the database's foreign keys, so a new child table is covered) and the
rows whose reference is emptied by ON DELETE SET NULL (and the time entries the draft billed). Sealed columns stay sealed
as they are stored. The office lists never see the trash (the row is gone), so numbers, exports and the agent API stay as
they are. GET /api/office/trash lists the trash of the office area, POST .../<id>/restore writes the copy back with the
old ids (a number taken since is left empty, a reference emptied since is set again only where it is still empty),
DELETE .../<id> (the app asks first) deletes one copy for good. After the trash period (ret_days("trash"), at least one day)
files/trashpurge.py tp_tick calls otb_tick: it counts, and deletes the copies while ret_on("trash") is on.
Booked / sent documents never come here: they stay locked (legal retention)."""
import base64
import json
from datetime import timedelta

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.pg import IntegrityError, insert_id, table_columns, write_lock
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
            "SELECT cl.relname, a.attname, co.confdeltype FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid "
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


def _insert(c, table, row):
    c.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def otb_restore(c, oid, tid):
    """Writes trash copy tid of office area oid back (the caller checked the rights and commits). -> (kind, ref_id)"""
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
                        row["number"] = ""  # taken since: the draft comes back without one
                    if row.get("series_id") and c.execute("SELECT 1 FROM office_docs WHERE series_id=? AND series_period IS NOT DISTINCT FROM ?",
                                                          (row["series_id"], row.get("series_period"))).fetchone():
                        row["series_id"] = None  # the series made this period again meanwhile
                if "updated_at" in cols:
                    row["updated_at"] = iso(now_utc())
                try:  # 2.272.0 F (#3038, review E2-M2): a client / service it points at is gone for good since: 409, not 500
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
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    return c, uid, oid


def _need_kind(c, uid, oid, tid):
    """Master data (services, texts, contracts, ...) only for the office admin, as deleting them."""
    r = c.execute("SELECT kind FROM office_trash WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["kind"] != "doc" and office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))


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
    kind, ref = otb_restore(c, oid, tid)
    if kind == "contracts" and t0:  # 2.272.0 F (#3038, review E2-M3): its PDF files that went with it come back too
        since = parse_iso(t0["deleted_at"]) - timedelta(seconds=2)
        for f in c.execute("SELECT id, deleted_at FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NOT NULL",
                           (oid, int(ref))).fetchall():
            if parse_iso(f["deleted_at"]) >= since:
                c.execute("UPDATE office_contract_files SET deleted_at=NULL WHERE id=?", (f["id"],))
    ofx_log(c, oid, "restore", **({"doc_id": ref} if kind == "doc" else {"target": kind}), detail={"id": ref})
    bump(c)
    c.commit()
    return jsonify(ok=True, kind=kind, id=ref)


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
