"""2.1118.0 (#5952): the old yes / no columns as BOOLEAN instead of BIGINT / INTEGER 0/1.

Since the move to Postgres (2.37.0, #1150) the flags of the areas kept the SQLite habit of a number 0/1 (tools/check_coltypes.py,
tools/coltypes_baseline.txt, rule bool). This step moves the 53 columns of CB_BOOL (office_agreements.archived
stays a number: it has three states, 2 = deleted, office/agreements.py AGR_DELETED; coltype-ok in the baseline note). A new database makes them BOOLEAN at once
(core/schema.py, the fragments of migrations.d); cb_migrate (init_db, before the schema script, so its partial indexes
`WHERE enabled` meet a BOOLEAN) turns an existing one, table by table, each in its own savepoint:

  - 0 is false, every other number true (none the app wrote: it wrote 0 / 1 only; the log names column, count and first ids)
  - the DEFAULT stays what it was (0 -> false, 1 -> true), NOT NULL stays
  - a partial index whose condition compares such a column with 0 / 1 (`enabled = 1`) is dropped and made anew with the
    condition in the new type (`enabled`); Postgres rebuilds an index on ALTER ... TYPE from its stored text and has no
    `boolean = integer`
  - a table Postgres refuses to turn (an error in the ALTER), or a column of another type than a number / BOOLEAN, stops the
    start (review 2.1118, F1 / F4): the SQL of the app is boolean only, a table left as a number would fail on every read of
    it; init_db is one transaction, so nothing of the turn stays and the version before starts again on the same database

Reading stays as it was: the driver gives these columns to Python as 0 / 1 (core/pg.py, the row maker looks at the table
and column a result's BOOLEAN comes from), so the answers of the app and of the agents' API keep 0 / 1 and Python code that
compares with 1 / 0 or adds them up works unchanged. A BOOLEAN that was BOOLEAN before (office_docs.subtotals, the wiki's
is_folder, ...) or one computed in SQL (CASE, EXISTS, a comparison) still reads as True / False.
Writing: a `?` parameter 0 / 1 / True / False goes as an untyped literal (core/pg.py _IntUnknown) and Postgres reads '0' / '1'
as a boolean, so the write paths stay. SQL text compares the column as a boolean (docs/dev/kern.md): `NOT archived` /
`archived`, never `archived = 0`, `COALESCE(x, 0)`, `SUM(x)`, `MAX(x)` (`CAST(x AS INTEGER)` where a number is wanted), and
INSERT / UPDATE write `true` / `false` in SQL text, never 0 / 1.

One way (the leader's --einbahn): the type does not change back. A version before reads the BOOLEAN as True / False and its
SQL `archived = 0` fails; a backup restores the old state."""
import re
import sys

from .pg import qi, system_ctx

CB_BOOL = {  # table -> the yes / no columns that were BIGINT / INTEGER 0/1 (the bool lines of tools/coltypes_baseline.txt)
    "agent_schedules": ("enabled",), "agents": ("enabled",), "appt_pages": ("enabled",), "appt_types": ("active",),
    "cal_subs": ("visible",), "clients": ("archived",), "doc_fetch_portals": ("enabled",), "doc_meta": ("dup_ok",),
    "filters": ("shared",), "forms": ("enabled",), "habits": ("archived",), "hub_mailbox_rules": ("active",),
    "hub_mailboxes": ("active",), "list_fields": ("pinned",), "list_milestones": ("done",), "list_rules": ("active",),
    "lists": ("archived", "is_inbox"), "notes": ("pinned",), "notify_channels": ("enabled",),
    "office_archive": ("paid",), "office_bank_accounts": ("archived", "is_default"),
    "office_bank_rules": ("active",), "office_bank_vendors": ("active",), "office_cashbooks": ("archived", "is_default"),
    "office_client_contacts": ("is_default",), "office_contracts": ("archived",), "office_doc_templates": ("archived",),
    "office_equipment": ("archived",), "office_gen_docs": ("archived",), "office_inv_series": ("active",),
    "office_letter_blocks": ("archived",), "office_letters": ("archived",), "office_payonline": ("enabled",),
    "office_privacy_sheets": ("archived",), "office_roles": ("archived",), "office_services": ("archived",),
    "office_sets": ("archived",), "office_texts": ("archived",), "office_vehicles": ("archived",), "org_joins": ("silent",),
    "pomos": ("done",), "tasks": ("locked", "pinned"), "tchat_rooms": ("is_open",), "ticket_types": ("enabled",),
    "time_entries": ("billable",), "users": ("disabled", "is_admin"), "view_layouts": ("active",), "webhooks": ("enabled",),
}
CB_PAIRS = frozenset(f"{t}.{c}" for t, cs in CB_BOOL.items() for c in cs)  # "table.column", core/pg.py reads them as 0 / 1
CB_NAMES = {c for cs in CB_BOOL.values() for c in cs}
CB_INTS = ("bigint", "integer", "smallint")
CB_SHOW = 5  # ids named in the log per column
CB_ID = "type:{0}.{1}"  # its row in kalmido_migrations (as core/coltype.py)


def cb_types(c):
    """{(table, column): (data_type, default)} of the CB_BOOL columns that exist."""
    out = {}
    for t, col, typ, dflt in c.execute(
            "SELECT table_name, column_name, data_type, column_default FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND column_name = ANY(?)", (sorted(CB_NAMES),)).fetchall():
        if col in CB_BOOL.get(t, ()):
            out[(t, col)] = (typ, dflt)
    return out


def cb_index_cond(cond, col):
    """The condition of a partial index with `col = 1` / `col <> 0` -> `col`, `col = 0` / `col <> 1` -> `NOT col` (the text
    pg_indexes gives: `(enabled = 1)`, `((trig = 'due'::text) AND (active = 1))`); unchanged when it names no such comparison."""
    def one(m):
        return f"({col})" if (m.group(1) == "=") == (m.group(2) == "1") else f"(NOT {col})"
    cmp = rf"{re.escape(col)}\s*(=|<>|!=)\s*'?([01])'?(?:::\w+)?"
    cond = re.sub(rf"\(\s*{cmp}\s*\)", one, cond)  # (active = 1)
    return re.sub(rf"\b{cmp}", one, cond)  # active = 1 without brackets


def cb_indexes(c, table, cols):
    """[(index name, its definition for the new type)] of table's partial indexes whose condition compares one of cols with
    0 / 1 (Postgres rebuilds an index on ALTER ... TYPE from its stored definition: `boolean = integer` has no operator)."""
    out = []
    for name, d in c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename=?",
                             (table,)).fetchall():
        if " WHERE " not in d:
            continue
        head, cond = d.split(" WHERE ", 1)
        new = cond
        for col in cols:
            new = cb_index_cond(new, col)
        if new != cond:
            out.append((name, f"{head} WHERE {new}"))
    return out


def cb_misfits(c, table, col):
    """[ids] (or [ctid text] without an id column) of the rows whose col is neither 0 nor 1 nor NULL (for the log)."""
    q = qi(col, CB_NAMES)
    has_id = c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? "
                       "AND column_name='id'", (table,)).fetchone()
    key = "id" if has_id else "ctid::text"
    # 2.1121.0 (#4949): as text - the same statement must prepare on a number column and on one already BOOLEAN
    return [r[0] for r in c.execute(f"SELECT {key} FROM {qi(table, CB_BOOL)} "
                                    f"WHERE {q}::text NOT IN ('0', '1', 'true', 'false') ORDER BY 1").fetchall()]


def cb_migrate(c, at):
    """init_db (2.1118.0, #5952): every CB_BOOL column that is still a number becomes BOOLEAN (module text), one savepoint
    per table (one rewrite of the table for all its columns; at = the start's time, ISO)
    -> {"table.col": "done" | "present" | "missing"}; a table that cannot turn raises (the start stops, nothing kept).
    System context: the check must see every organisation's rows
    (the ALTER rewrites all of them, row security or not), as core/coltype.py ct_migrate."""
    with system_ctx(c):
        return _cb_run(c, at)


def _cb_run(c, at):
    out = {}
    types = cb_types(c)
    for table, cols in CB_BOOL.items():
        todo = []
        for col in cols:
            typ, _d = types.get((table, col), (None, None))
            if typ in CB_INTS:
                todo.append(col)
            elif typ in ("boolean", None):
                out[f"{table}.{col}"] = "present" if typ else "missing"
            else:  # review 2.1118 (F4): TEXT / NUMERIC on a database made by hand - the boolean SQL would fail later
                raise RuntimeError(f"migrations: 5952: {table}.{col} is {typ}, neither a number nor BOOLEAN - the start stops")
        if not todo:
            continue
        parts = []
        for col in todo:
            bad = cb_misfits(c, table, col)
            if bad:
                print(f"migrations: 5952: {table}.{col}: {len(bad)} value(s) are neither 0 nor 1 and count as yes (ids "
                      f"{', '.join(map(str, bad[:CB_SHOW]))}{', ...' if len(bad) > CB_SHOW else ''})", file=sys.stderr, flush=True)
            q = qi(col, CB_NAMES)
            dflt = types[(table, col)][1]
            parts.append(f"ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE BOOLEAN USING ({q} <> 0)")
            if dflt is not None:
                on = str(dflt).split("::", 1)[0].strip("()' ") not in ("0", "")
                parts.append(f"ALTER COLUMN {q} SET DEFAULT {'true' if on else 'false'}")
        try:
            idx = cb_indexes(c, table, todo)
            for name, _d in idx:
                c.execute(f"DROP INDEX {qi(name, {name})}")
            c.execute(f"ALTER TABLE {qi(table, CB_BOOL)} {', '.join(parts)}")
            for _n, d in idx:
                c.execute(d)
        except Exception as e:  # review 2.1118 (F1): no half-turned database - the whole start rolls back
            print(f"migrations: 5952: {table} ({', '.join(todo)}) cannot turn into BOOLEAN, the start stops: "
                  f"{type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
            raise
        for col in todo:
            if c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() "
                         "AND table_name='kalmido_migrations'").fetchone():
                c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'applied') ON CONFLICT(id) DO UPDATE "
                          "SET applied_at=excluded.applied_at, note=excluded.note", (CB_ID.format(table, col), at))
            out[f"{table}.{col}"] = "done"
    n = sum(1 for v in out.values() if v == "done")
    if n:
        print(f"migrations: 5952: {n} yes / no column(s) are BOOLEAN now", flush=True)
    return out
