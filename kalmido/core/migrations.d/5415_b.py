"""2.1005.0 (#5415, stage 4d of the core's trash, part 1): a part of a quotation (office_doc_parts) is deleted into the core's trash
(office/okern.py ofk_register, kind opart; core/writes.py obj_trash) instead of a copy in office_trash and the rows deleted: the
columns the core writes on the part (deleted_at, deleted_by, rev, updated_by) and deleted_at on its positions and its lines on
the title page (office_doc_items: children of the part, they go into the trash and come back with it), with partial indexes.
New nullable / defaulted columns only: an older version ignores them (it would show a part of the trash again, nothing is lost)."""
MIGRATIONS = [
    ("office_doc_parts", "deleted_at", "ALTER TABLE office_doc_parts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_doc_parts", "deleted_by", "ALTER TABLE office_doc_parts ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_doc_parts", "rev", "ALTER TABLE office_doc_parts ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_doc_parts", "updated_by", "ALTER TABLE office_doc_parts ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_doc_items", "deleted_at", "ALTER TABLE office_doc_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5415_office_doc_parts_trash ON office_doc_parts(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5415_office_doc_items_trash ON office_doc_items(deleted_at) WHERE deleted_at IS NOT NULL",
]
