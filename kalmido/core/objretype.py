"""2.1101.0 (#5954, rest of #5949 / #5305): the core's own tables obj_history, obj_undo and obj_revoked (core/migrations.d/4709_a.py,
docs/dev/kern.md "history / undo / revoked") take real types: created_at / updated_at TEXT -> TIMESTAMPTZ, vals_before /
vals_after / snap / row_json TEXT -> JSONB. A new database makes them so at once (the fragment's CREATE TABLE); obj_retype moves a
database of before, at every start (core/db.py init_db, under its lock "kalmido-init", inside its one transaction), each column
only while it is still TEXT, each in its own savepoint:

  - a time Postgres reads (it starts with a date and pg_input_is_valid says yes) keeps its instant; any other value (empty, "last
    tuesday", 2026-02-30) becomes the start's time (the columns are NOT NULL; they only order and age the rows: the 30 days of
    obj_revoked / obj_undo, the ten minutes a history entry merges)
  - a JSON text keeps its value (an array or a scalar too: the readers decide, as before); one that is no JSON becomes '{}'
  - a column Postgres still refuses stays as it was, the log says why, and the next start tries again

The readers do not change: the driver hands JSONB and TIMESTAMPTZ back as text (core/pg.py: jsonb as its JSON text, a time as
canonical ISO in UTC, ts_canon), so json.loads and the ISO comparisons stay. What changes is SQL that treated them as text: a
VALUES list typed text (core/writes.py obj_history_add_many) and a regex on snap (collab/liste2eguard.py le2b_undo_copies).

One way (the leader's --einbahn): once a column has its type the database's back limit (kalmido_meta back_floor, core/kernretire.py
kern_retire_floor) rises to this minor -- a version before would send its text-typed values / text operators into the new
columns (obj_history_add_many fails, the list guard's regex fails). A backup from before restores the old state.
Python standard library + the driver layer only (layer core)."""
import sys

from .kernretire import kern_retire_floor
from .pg import qi

ORT_COLS = (("obj_history", "created_at", "time"), ("obj_history", "updated_at", "time"), ("obj_history", "vals_before", "json"),
            ("obj_history", "vals_after", "json"), ("obj_undo", "created_at", "time"), ("obj_undo", "snap", "json"),
            ("obj_revoked", "created_at", "time"), ("obj_revoked", "row_json", "json"))
ORT_TABLES = tuple(dict.fromkeys(t for t, _, _ in ORT_COLS))
ORT_NAMES = {*ORT_TABLES, *(x for _, x, _ in ORT_COLS)}  # the allowlist of qi() (#5296)
ORT_TYPE = {"time": "timestamp with time zone", "json": "jsonb"}
ORT_HOW = ("the shared core's history, undo steps and taken-back shares keep their times as TIMESTAMPTZ and their copies as JSONB "
           "(#5954) - an older version would write and search them as text; go back only with a backup from before")


def ort_types(c):
    """{(table, column): data_type} of the columns of ORT_COLS that exist."""
    q = ",".join("?" * len(ORT_TABLES))
    return {(r[0], r[1]): r[2] for r in c.execute(
        f"SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() "
        f"AND table_name IN ({q})", ORT_TABLES).fetchall()}


def ort_sql(table, col, how):
    """The ALTER TABLE of one column (module docstring)."""
    t, q = qi(table, ORT_NAMES), qi(col, ORT_NAMES)
    if how == "time":
        return (f"ALTER TABLE {t} ALTER COLUMN {q} TYPE TIMESTAMPTZ USING (CASE WHEN {q} ~ '^\\d{{4}}-\\d\\d-\\d\\d' "
                f"AND pg_input_is_valid({q}, 'timestamptz') THEN {q}::timestamptz ELSE CURRENT_TIMESTAMP END)")
    return (f"ALTER TABLE {t} ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE JSONB USING (CASE WHEN "
            f"pg_input_is_valid({q}, 'jsonb') THEN {q}::jsonb ELSE '{{}}'::jsonb END), ALTER COLUMN {q} SET DEFAULT '{{}}'::jsonb")


def obj_retype(c):
    """init_db (core/db.py), in the system context -> [table.column moved at this start]; raises the back limit once a column
    has its type (on a new database too: the fragment made them so)."""
    have = ort_types(c)
    out = []
    for table, col, how in ORT_COLS:
        if have.get((table, col)) != "text":
            continue
        try:
            with c.savepoint():
                c.execute(ort_sql(table, col, how))
            out.append(f"{table}.{col}")
        except Exception as e:  # noqa: BLE001 -- the start goes on with the column as it was, the log says why
            print(f"migrations: 5954: {table}.{col} keeps its type: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
    if out:
        print("the core's history / undo / revoked onto real types (#5954):", out, flush=True)
        have = ort_types(c)
    if any(have.get((t, x)) == ORT_TYPE[how] for t, x, how in ORT_COLS):
        kern_retire_floor(c, how=ORT_HOW)
    return out
