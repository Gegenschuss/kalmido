"""2.1004.0 (#5494, stage 4c rest of the core's trash): a video review's approval record whose review is gone (office_signoffs,
kind video, video_id NULL; settings > Move and export everything) is deleted into the core's trash (office/signoff.py,
office/okern.py ofk_register with personal= for a private record without an organisation) instead of a copy in office_trash
and the row deleted: the columns the core writes and a partial index for the trash list and the retention run. New nullable /
defaulted columns only: an older version ignores them (it would list a record of the trash again, nothing is lost)."""
MIGRATIONS = [
    ("office_signoffs", "deleted_at", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_signoffs", "deleted_by", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_signoffs", "rev", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_signoffs", "updated_at", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
    ("office_signoffs", "updated_by", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5494_office_signoffs_trash ON office_signoffs(deleted_at) WHERE deleted_at IS NOT NULL",
]
