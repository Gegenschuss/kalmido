"""2.635.0 (#4856): a document flow (doc_rules) is edited in Settings > Documents with the version check of the shared core
(core/conflict.py): updated_at = when its content or place was saved last ('' = never since it was made: created_at counts,
docs/web.py _rule_ver). A column with a DEFAULT only: older versions ignore it."""
MIGRATIONS = [
    ("doc_rules", "updated_at", "ALTER TABLE doc_rules ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
]
