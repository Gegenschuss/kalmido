"""2.1005.0 (#5415, stage 4d of the core's trash, part D): trips (office_trips), their travel receipts (office_trip_items, also
the trips of a per diem import taken back) and the positions of a credit card statement (office_cc_lines) are deleted into the
core's trash (office/okern.py ofk_register, core/writes.py obj_trash) instead of a copy in office_trash and the row deleted:
the columns the core writes (updated_by is there since 2.567.0, #4711) and a partial index for the trash list and the
retention run. New nullable / defaulted columns only: an older version ignores them (it would show a row of the trash in its
lists again, nothing is lost)."""
MIGRATIONS = [
    ("office_trips", "deleted_at", "ALTER TABLE office_trips ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_trips", "deleted_by", "ALTER TABLE office_trips ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_trips", "rev", "ALTER TABLE office_trips ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_trip_items", "deleted_at", "ALTER TABLE office_trip_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_trip_items", "deleted_by", "ALTER TABLE office_trip_items ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_trip_items", "rev", "ALTER TABLE office_trip_items ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_cc_lines", "deleted_at", "ALTER TABLE office_cc_lines ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_cc_lines", "deleted_by", "ALTER TABLE office_cc_lines ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_cc_lines", "rev", "ALTER TABLE office_cc_lines ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5415_office_trips_trash ON office_trips(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5415_office_trip_items_trash ON office_trip_items(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5415_office_cc_lines_trash ON office_cc_lines(deleted_at) WHERE deleted_at IS NOT NULL",
]
