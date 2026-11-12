"""2.1005.0 (#5415, stage 4d of the core's trash, part 1): a document draft of the office (office_docs) is deleted into the core's
trash (office/okern.py ofk_register, kind odoc; core/writes.py obj_trash) instead of a copy in office_trash and the row deleted:
the columns the core writes (deleted_at, deleted_by, rev, updated_by), trash_refs = what went out of the row and of the rows
pointing at it when it went into the trash (its number, series, the references the database had emptied on a delete, the
time entries it billed; put back on restore where still free) and a partial index for the trash list and the retention run.
New nullable / defaulted columns only: an older version ignores them (it would show a draft of the trash in its lists again,
nothing is lost)."""
MIGRATIONS = [
    ("office_docs", "deleted_at", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_docs", "deleted_by", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_docs", "rev", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_docs", "updated_by", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_docs", "trash_refs", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS trash_refs JSONB"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5415_office_docs_trash ON office_docs(deleted_at) WHERE deleted_at IS NOT NULL",
]
