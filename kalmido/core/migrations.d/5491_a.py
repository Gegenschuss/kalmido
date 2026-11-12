"""2.1002.0 (#5491, stage 2b of the core's trash): projects (lists) and tasks come back from the trash / go for good through the
core (core/writes.py obj_restore / obj_purge): their tables get the columns the core writes when a row goes into the trash
or comes back (lists: rev, updated_by -- updated_at has been there since 5052_a; tasks: rev, updated_by, deleted_by). New
nullable / defaulted columns only: an older version ignores them and keeps reading deleted_at as before."""
MIGRATIONS = [
    ("lists", "rev", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("lists", "updated_by", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("tasks", "rev", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("tasks", "updated_by", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("tasks", "deleted_by", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
