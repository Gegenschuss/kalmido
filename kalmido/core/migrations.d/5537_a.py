"""2.1029.0 (#5537, stage 1): a project (lists) carries ONE state marker -- lists.state = 'live' | 'archived' | 'trash' -- next to
the old columns archived / deleted_at. Reads ask for the state through core/access.py list_state_sql() (otr_live too); the
columns archived / archived_at / deleted_at stay the ones the write paths set in this stage.

The database keeps the marker equal to them: the trigger kalmido_list_state sets it before every INSERT and every UPDATE
(no column list: SCHEMA runs before the MIGRATIONS step that adds state, and Postgres checks an UPDATE OF list when it creates
the trigger -- review of 2.1029; the function reads the row as JSON, so a database whose lists still lack state / deleted_at
during its first start breaks nothing): 'trash' while deleted_at is set, else
'archived' while archived <> 0, else 'live'. So no write path changes, a copy of all columns (merges, account import, undo of a row) can never write a wrong marker, and the rows
of before get theirs at the start (core/db.py, the reconcile next to migr_liststate5537 runs at every start: after a restore
of a dump, or a rollback that dropped the trigger, a row never stays with a wrong marker).

Not a column Postgres computes (GENERATED ALWAYS AS): such a column refuses every INSERT / UPDATE that names it, and the generic
copies of rows (core/merges.py, core/undoareas.py, admin/acctimport.py) name every column of the table.

Additive only: a new column with a DEFAULT, a new function and trigger. An older version ignores the column; its writes still
get the right marker from the trigger, so the way forward again needs nothing. Stage 2 (one way, a task of its own) moves the
write paths onto the marker and drops the old columns."""
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_list_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  j JSONB := to_jsonb(NEW);
BEGIN
  IF NOT j ? 'state' THEN RETURN NEW; END IF;  -- an older database during its first start (a step before the column, e.g. tap_done)
  NEW.state := CASE WHEN COALESCE(j->>'deleted_at', '') <> '' THEN 'trash' WHEN COALESCE(j->>'archived', '0') NOT IN ('0', '') THEN 'archived' ELSE 'live' END;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER kalmido_list_state BEFORE INSERT OR UPDATE ON lists FOR EACH ROW EXECUTE FUNCTION kalmido_list_state();
"""
MIGRATIONS = [
    ("lists", "state", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'live'"),
]
# the archive view and the trash read the few rows that are not live
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5537_lists_state ON lists(state) WHERE state <> 'live'",
]
