"""2.152.0 C (#2174): foreign keys for references that had none (GDPR art. 17: no reference to a deleted person / object).

FK_2103 lists (table, column, referenced table, action). fk_ensure(c) runs at every start (core/db.py init_db): for each
column without a foreign key yet it first cleans the orphans (a reference to a row that is gone: SET NULL -> emptied,
CASCADE -> the row goes, like the key would have done), then adds the constraint fk2103_<table>_<column>; every column gets an
index (the delete of a task / list / person must not scan the table). Idempotent: a column that already has a foreign key
(a new database: schema.py writes REFERENCES; a restored backup of 2.152) is skipped, so a restore of an older backup gets
its keys again at the next start. The numbers of cleaned orphans per column: server log + gsetting fk2103_orphans (JSON).
2.102 runs on with the keys: none of its code paths writes such a reference to a row that does not exist (they are set
from rows it just read or created) -- and deleting the parent now empties the reference instead of leaving it behind.

Not here, with the reason (schema.py "-- no FK"): office_docs.contact_id (0 = "no contact person", a deleted contact person
falls back to the client's default), the log tables (agent_audit, dl_changes, org_list_log, assistant_log: they keep ids of
what is gone on purpose), playbooks.author_id (2.152.0, review B-M7: a version keeps its author's id like the log tables;
NULL would make a gone author's text the owner's own text, which the agent follows -- #1978: a foreign text stays foreign).
"""
import json

from .db import gset, gsetting
from .pg import system_ctx

FK_2103 = (
    ("doc_meta", "task_id", "tasks", "SET NULL"),
    ("office_agreements", "task_id", "tasks", "SET NULL"),
    ("budget_recurring", "contract_task_id", "tasks", "SET NULL"),
    ("rss_items", "saved_task_id", "tasks", "SET NULL"),
    ("rc_receipts", "list_id", "lists", "SET NULL"),
    ("rc_suggest", "list_id", "lists", "SET NULL"),
    ("rc_suggest", "prev_list_id", "lists", "SET NULL"),
    ("kk_conns", "list_id", "lists", "SET NULL"),
    ("agent_jobs", "list_id", "lists", "SET NULL"),
    ("notes", "created_by", "users", "SET NULL"),
    ("notes", "updated_by", "users", "SET NULL"),
    ("agents", "owner_id", "users", "SET NULL"),  # a safety net: deleting an account hands over / removes its agents first;
    # 2.152.0 (#2174, review B-M6): fk_ensure pauses its orphans instead of making them team agents
    ("habits", "user_id", "users", "CASCADE"),
    ("pomos", "user_id", "users", "CASCADE"),
)
FK_INDEXED = {("rc_receipts", "list_id"), ("habits", "user_id"), ("pomos", "user_id")}  # schema.py has an index on these


def fk_has(c, table, col):
    """Has column table.col a foreign key already (any name)?"""
    return bool(c.execute("""SELECT 1 FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid -- pg-ok: pg_catalog oid
                             JOIN pg_namespace n ON n.oid=cl.relnamespace
                             JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1]
                             WHERE con.contype='f' AND n.nspname=current_schema() AND cl.relname=? AND a.attname=?
                             AND array_length(con.conkey, 1)=1""", (table, col)).fetchone())


def fk_orphans(c, table, col, ref):
    """Rows of table whose col points to a row of ref that does not exist."""
    return c.execute(f"SELECT COUNT(*) FROM {table} t WHERE t.{col} IS NOT NULL AND NOT EXISTS "
                     f"(SELECT 1 FROM {ref} r WHERE r.id=t.{col})").fetchone()[0]


def fk_ensure(c):
    """Adds the missing keys of FK_2103 (orphans cleaned first); the caller commits. Returns {"table.col": orphans} of the
    columns that got their key now."""
    done = {}
    # system: the clean-up and the keys span every organisation (row-level security would hide the rows of the others)
    with system_ctx(c):
        for table, col, ref, act in FK_2103:
            if (table, col) not in FK_INDEXED:  # also on a new database (its key comes from schema.py)
                c.execute(f"CREATE INDEX IF NOT EXISTS fk2103_{table}_{col}_ix ON {table}({col}) WHERE {col} IS NOT NULL")
            if fk_has(c, table, col):
                continue
            n = fk_orphans(c, table, col, ref)
            if n:
                cond = f"{col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {ref} r WHERE r.id={table}.{col})"
                if act == "CASCADE":
                    c.execute(f"DELETE FROM {table} WHERE {cond}")
                elif (table, col) == ("agents", "owner_id"):
                    # 2.152.0 (#2174, review B-M6): an agent of a gone person does not become a team agent that runs on: it
                    # is paused by the admin, without office drafts, until an admin decides
                    c.execute(f"UPDATE agents SET owner_id=NULL, admin_paused=1, office_drafts=0 WHERE {cond}")
                else:
                    c.execute(f"UPDATE {table} SET {col}=NULL WHERE {cond}")
            c.execute(f"ALTER TABLE {table} ADD CONSTRAINT fk2103_{table}_{col} FOREIGN KEY ({col}) REFERENCES {ref}(id) ON DELETE {act}")
            done[f"{table}.{col}"] = int(n)
    if done:
        try:
            old = json.loads(gsetting(c, "fk2103_orphans") or "{}")
        except ValueError:
            old = {}
        gset(c, "fk2103_orphans", json.dumps(dict(old if isinstance(old, dict) else {}, **done), sort_keys=True))
        print("foreign keys: added", len(done), "- orphans cleaned:",
              ", ".join(f"{k}={v}" for k, v in sorted(done.items()) if v) or "none", flush=True)
    return done
