"""2.905.0 (#5414, stage 4c of the core's trash): a letter's link to a document (office_letter_links) is removed into the
core's trash (office/letterlinks.py, office/okern.py ofk_register) instead of a copy in office_trash and the row deleted:
the columns the core writes and a partial index for the trash list and the retention run. New nullable / defaulted columns
only: an older version ignores them (it would show a link of the trash again). Linking the same document again takes the
row of the trash back as a new link (office_letter_links_one stays unique)."""
MIGRATIONS = [
    ("office_letter_links", "deleted_at", "ALTER TABLE office_letter_links ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_letter_links", "deleted_by", "ALTER TABLE office_letter_links ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_letter_links", "rev", "ALTER TABLE office_letter_links ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_letter_links", "updated_at", "ALTER TABLE office_letter_links ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
    ("office_letter_links", "updated_by", "ALTER TABLE office_letter_links ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5414_office_letter_links_trash ON office_letter_links(deleted_at) WHERE deleted_at IS NOT NULL",
]
