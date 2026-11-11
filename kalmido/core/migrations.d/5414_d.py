"""2.905.0 (#5414, stage 4c of the core's trash): a correction of the cash flow (office_cf_adjust) is deleted into the core's
trash (office/cfstart.py, office/okern.py ofk_register) instead of a copy in office_trash and the row deleted: the columns
the core writes and a partial index for the trash list and the retention run. New nullable / defaulted columns only: an
older version ignores them (it would count a correction of the trash in its cash flow again)."""
MIGRATIONS = [
    ("office_cf_adjust", "deleted_at", "ALTER TABLE office_cf_adjust ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_cf_adjust", "deleted_by", "ALTER TABLE office_cf_adjust ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_cf_adjust", "rev", "ALTER TABLE office_cf_adjust ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_cf_adjust", "updated_by", "ALTER TABLE office_cf_adjust ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5414_office_cf_adjust_trash ON office_cf_adjust(deleted_at) WHERE deleted_at IS NOT NULL",
]
