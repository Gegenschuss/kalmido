"""2.1050.0 (#5789, stage 4e of the core's trash): the start balance of the cash flow (office_cf_start, one row per office
area, key org_id) is deleted into the core's trash (office/cfstart.py, office/okern.py ofk_register) instead of a copy in
office_trash and the row deleted. The core names its rows by id: the column id holds the row's org_id (the app writes it
on every save and before the trash; a row an older version wrote has none until then), plus the columns the core writes
and a partial index for the trash list and the retention run. New nullable / defaulted columns only: an older version
ignores them (it would show a start balance of the trash again). Review 2.1050.0 (F1): one the older version set again
on such a row comes back live at the next start (office/cfstart.py cfs_start_fix)."""
MIGRATIONS = [
    ("office_cf_start", "id", "ALTER TABLE office_cf_start ADD COLUMN IF NOT EXISTS id BIGINT"),
    ("office_cf_start", "deleted_at", "ALTER TABLE office_cf_start ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_cf_start", "deleted_by", "ALTER TABLE office_cf_start ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_cf_start", "rev", "ALTER TABLE office_cf_start ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
]
# unique-ok ix5789_office_cf_start_id: id is NULL or the row's org_id, the table's primary key - no two rows share one
AFTER = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix5789_office_cf_start_id ON office_cf_start(id)",
    "CREATE INDEX IF NOT EXISTS ix5789_office_cf_start_trash ON office_cf_start(deleted_at) WHERE deleted_at IS NOT NULL",
]
