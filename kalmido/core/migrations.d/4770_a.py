"""2.570.0 (#4770): office_archive.updated_at = the version of an archived document's bookkeeping notes (office/archiveedit.py:
client, amount / tax lines, paid). A correction checks expect_updated_at against it (409 with the entry: an undo never
overwrites what someone else corrected meanwhile). '' = never corrected since: the entry's created_at stands for it
(archiveedit.r81b_ver), so the old rows have a version without a rewrite; older versions ignore the column."""
MIGRATIONS = [
    ("office_archive", "updated_at", "ALTER TABLE office_archive ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
]
