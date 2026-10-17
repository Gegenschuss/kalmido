"""2.66.0 (#1835): merging duplicate records by hand (contacts: contacts/merge.py, clients: team/clientmerge.py), reversible.

A merge keeps one record (the target), moves every reference of the other records (the merged ones) to it and deletes
them. Before that it writes one row of merge_runs: the merged rows as they were, the target before the merge and every
reference it moved or dropped (a reference that would collide with one the target has already, e.g. the same task linked
to both contacts, is dropped and kept in the snapshot). "Undo" (mg_undo_refs + mg_reinsert) puts the deleted rows back
under their old ids, moves the references back and restores the target's columns. The snapshot is kept MG_UNDO_DAYS days
(mg_prune empties it after that; the summary stays as the history line).

The references are found from the database itself (mg_fk_refs: every foreign key to the table), so a table a later
version adds (e.g. 2.63.0 portal_tickets.client_id) moves along without a change here; references without a foreign key
(lists.client_id, hub_bookings) are named by the caller.
"""
import base64
import json
from datetime import timedelta

from .db import insert_id, IntegrityError, iso, now_utc

MG_UNDO_DAYS = 30
MG_MAX = 10  # records in one merge (target included)


# ---- snapshot values: JSON with bytes as {"$b": base64}
def _jdef(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    return str(v)


def _jval(v):
    if isinstance(v, dict) and set(v) == {"$b"}:
        return base64.b64decode(v["$b"])
    return v


def mg_dumps(x):
    return json.dumps(x, ensure_ascii=False, default=_jdef)


def mg_row(c, table, rid):
    """The row of table with id rid as a plain dict (None when gone)."""
    r = c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    return dict(r) if r else None


def mg_fk_refs(c, table):
    """[(table, column, on_delete)] of every single-column foreign key that points to table.id ('c' cascade, 'n' set null,
    'a' / 'r' no action / restrict)."""
    return [(r[0], r[1], r[2]) for r in c.execute(
        "SELECT cl.relname, a.attname, con.confdeltype FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid "
        "JOIN pg_class rf ON rf.oid=con.confrelid JOIN pg_namespace n ON n.oid=rf.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] "
        "WHERE con.contype='f' AND rf.relname=? AND n.nspname=current_schema() AND array_length(con.conkey,1)=1 "
        "ORDER BY cl.relname, a.attname", (table,)).fetchall()]


def _pk_cols(c, table):
    return [r[0] for r in c.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_class cl ON cl.oid=i.indrelid JOIN pg_namespace n ON n.oid=cl.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indisprimary AND cl.relname=? AND n.nspname=current_schema() ORDER BY a.attnum", (table,)).fetchall()]


def mg_repoint(c, table, col, from_ids, to_id, where="", args=()):
    """Moves the rows of table whose col is one of from_ids to to_id. A row whose primary key would then collide with a
    row the target already has (col is part of the primary key) is deleted instead. where / args narrow the rows (e.g.
    "resource_kind='contact'"). Returns the undo record {t, col, moved: [pk dicts], dropped: [rows], to} for mg_undo_refs."""
    from_ids = [int(x) for x in from_ids]
    rec = {"t": table, "col": col, "to": to_id, "moved": [], "dropped": []}
    if not from_ids:
        return rec
    pk = _pk_cols(c, table) or ["id"]
    extra = f" AND ({where})" if where else ""
    qs = ",".join("?" * len(from_ids))
    rows = [dict(r) for r in c.execute(f"SELECT * FROM {table} WHERE {col} IN ({qs}){extra}", [*from_ids, *args]).fetchall()]
    for r in rows:
        key = {k: r[k] for k in pk}
        if col in pk:
            probe = {**key, col: to_id}
            hit = c.execute(f"SELECT 1 FROM {table} WHERE {' AND '.join(k + '=?' for k in probe)}", list(probe.values())).fetchone()
            if hit:
                c.execute(f"DELETE FROM {table} WHERE {' AND '.join(k + '=?' for k in key)}", list(key.values()))
                rec["dropped"].append(r)
                continue
        c.execute(f"UPDATE {table} SET {col}=? WHERE {' AND '.join(k + '=?' for k in key)}", [to_id, *key.values()])
        rec["moved"].append({**key, "_from": r[col]})
    return rec


def mg_cascade_rows(c, table, ids):
    """Every row that deleting the rows ids of table would remove through ON DELETE CASCADE / SET NULL, one level deep:
    [{t, col, rows}] (kept in the snapshot so that Undo can put them back). Call it AFTER mg_repoint moved what should move."""
    out = []
    ids = [int(x) for x in ids]
    if not ids:
        return out
    qs = ",".join("?" * len(ids))
    for t, col, rule in mg_fk_refs(c, table):
        if rule not in ("c", "n"):
            continue
        rows = [dict(r) for r in c.execute(f"SELECT * FROM {t} WHERE {col} IN ({qs})", ids).fetchall()]
        if rows:
            out.append({"t": t, "col": col, "rule": rule, "rows": rows})
    return out


def mg_reinsert(c, table, row):
    """Puts a deleted row back with its old id and columns (only the columns the table still has). False when it could not
    (a row it refers to is gone meanwhile, e.g. a task emptied from the trash; it stays away, the rest of the undo goes on)."""
    from .pg import table_columns
    have = table_columns(c, table)
    row = {k: _jval(v) for k, v in row.items() if k in have}
    try:  # 2.66.0 A (#1835): a broken reference must not abort the whole undo
        with c.savepoint():
            return bool(c.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' * len(row))}) ON CONFLICT DO NOTHING",
                                  list(row.values())).rowcount)
    except IntegrityError:
        return False


def mg_undo_refs(c, recs, target_gone=False):
    """Reverses mg_repoint records (in reverse order): moved rows get their old value back, dropped rows come back.
    A moved row goes back only while it still points at the target; target_gone: also when it lost it (SET NULL) --
    a reference someone took away on purpose since stays away (review)."""
    for rec in reversed(recs or []):
        t, col = rec["t"], rec["col"]
        for k in rec.get("moved") or []:
            key = {x: v for x, v in k.items() if x != "_from"}
            if col in key:
                key[col] = rec["to"]
                guard, ga = "", []
            else:  # 2.66.0 A (#1835): only while it still points at the target (or lost it with a deleted target: SET NULL)
                guard, ga = (f" AND ({col}=? OR {col} IS NULL)" if target_gone else f" AND {col}=?"), [rec["to"]]
            c.execute(f"UPDATE {t} SET {col}=? WHERE {' AND '.join(x + '=?' for x in key)}{guard}", [k["_from"], *key.values(), *ga])
        for r in rec.get("dropped") or []:
            mg_reinsert(c, t, r)


def mg_undo_cascade(c, groups):
    """Puts back what mg_cascade_rows listed (after the parent rows are back): cascade rows again, set-null columns again."""
    for g in groups or []:
        for r in g["rows"]:
            if g["rule"] == "c":
                mg_reinsert(c, g["t"], r)
            else:
                pk = {k: v for k, v in r.items() if k == "id"}
                if pk:
                    c.execute(f"UPDATE {g['t']} SET {g['col']}=? WHERE id=? AND {g['col']} IS NULL", (r[g["col"]], pk["id"]))


def mg_run_create(c, kind, target_id, merged_ids, uid, snapshot, summary, org_id=None, book_id=None):
    """One merge in the history; returns its id. summary = what the history line shows (names, counts), kept for good."""
    mg_prune(c)
    return insert_id(c, "INSERT INTO merge_runs(kind,target_id,org_id,book_id,user_id,merged_ids,snapshot,summary,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                     (kind, target_id, org_id, book_id, uid, json.dumps([int(x) for x in merged_ids]), mg_dumps(snapshot),
                      mg_dumps(summary), iso(now_utc())))


def mg_run(c, rid, kind):
    """The merge rid of kind as a dict with parsed JSON (None when unknown)."""
    r = c.execute("SELECT * FROM merge_runs WHERE id=? AND kind=?", (rid, kind)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k, dflt in (("merged_ids", []), ("snapshot", {}), ("summary", {})):
        try:
            d[k] = json.loads(d[k] or "null") or dflt
        except ValueError:
            d[k] = dflt
    return d


def mg_undoable(d):
    """'' when merge d can still be undone, else the reason (already undone / too old)."""
    if d.get("undone_at"):
        return "undone"
    if not d.get("snapshot") or d["created_at"] < iso(now_utc() - timedelta(days=MG_UNDO_DAYS)):
        return "expired"
    return ""


def mg_mark_undone(c, rid, uid):
    c.execute("UPDATE merge_runs SET undone_at=?, undone_by=?, snapshot='{}' WHERE id=?", (iso(now_utc()), uid, rid))


def mg_history(c, kind, target_id, limit=20):
    """The merges into target_id (newest first): [{id, at, by, merged_ids, summary, undone_at, undo}] (undo: '' = possible)."""
    out = []
    for r in c.execute("SELECT id FROM merge_runs WHERE kind=? AND target_id=? ORDER BY id DESC LIMIT ?", (kind, target_id, limit)):
        d = mg_run(c, r[0], kind)
        out.append({"id": d["id"], "at": d["created_at"], "by": d["user_id"], "merged_ids": d["merged_ids"], "summary": d["summary"],
                    "undone_at": d["undone_at"], "undo": mg_undoable(d)})
    return out


MG_PRUNE = {"at": 0.0}


def mg_prune(c, force=True):
    """Empties the snapshots older than MG_UNDO_DAYS (the deleted records' data does not stay forever). The watchdog calls
    it with force=False (at most hourly, system context: every workspace); a merge calls it for what the person sees."""
    import time
    if not force:
        if time.time() - MG_PRUNE["at"] < 3600:
            return
        MG_PRUNE["at"] = time.time()
    c.execute("UPDATE merge_runs SET snapshot='{}' WHERE snapshot!='{}' AND created_at<?", (iso(now_utc() - timedelta(days=MG_UNDO_DAYS)),))
    if not force:
        c.commit()
