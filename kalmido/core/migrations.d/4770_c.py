"""2.570.0 (#4770): lists.page_layout_at = the version of a project page's standard arrangement (lists.page_layout,
accounts/layouts.py), like list_layouts.updated_at for a person's own one: changing the standard checks expect_updated_at
against it (409 with the current arrangements: an undo never overwrites what someone else set as the default meanwhile).
NULL = not set since (no check against an empty version); older versions ignore the column."""
MIGRATIONS = [
    ("lists", "page_layout_at", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS page_layout_at TEXT"),
]
