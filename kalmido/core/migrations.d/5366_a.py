"""2.784.0 (#5366, stage 4 of the core's trash): the office kinds that delete by deleted_at move onto the core's trash
(office/okern.py ofk_register, core/writes.py obj_trash): their tables get the columns the core writes when a row goes into
the trash or comes back (rev, updated_by, deleted_by; created_by for the history). New nullable / defaulted columns only:
an older version ignores them and keeps reading deleted_at as before."""
MIGRATIONS = [
    ("office_suppliers", "rev", "ALTER TABLE office_suppliers ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_suppliers", "created_by", "ALTER TABLE office_suppliers ADD COLUMN IF NOT EXISTS created_by BIGINT"),
    ("office_suppliers", "updated_by", "ALTER TABLE office_suppliers ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_suppliers", "deleted_by", "ALTER TABLE office_suppliers ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
