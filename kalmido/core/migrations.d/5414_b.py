"""2.905.0 (#5414, stage 4c of the core's trash): an own office rights group (office_rgroups) is deleted into the core's trash
(office/rights.py, office/okern.py ofk_register) instead of a copy in office_trash and the row deleted: the columns the core
writes and a partial index for the trash list and the retention run. New nullable / defaulted columns only: an older
version ignores them (it would list a group of the trash again; its members were taken out when it was deleted)."""
MIGRATIONS = [
    ("office_rgroups", "deleted_at", "ALTER TABLE office_rgroups ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_rgroups", "deleted_by", "ALTER TABLE office_rgroups ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_rgroups", "rev", "ALTER TABLE office_rgroups ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_rgroups", "updated_by", "ALTER TABLE office_rgroups ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5414_office_rgroups_trash ON office_rgroups(deleted_at) WHERE deleted_at IS NOT NULL",
]
