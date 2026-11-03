"""2.498.0 (#3884): bytes and uploader of a list's own icon / header picture for the storage quota (NULL size = not measured
yet, the watchdog fills it in: lists/listhead.py o3c_pic_tick; NULL uploader = it counts for the owner). New columns only:
older versions ignore them."""
MIGRATIONS = [
    ("lists", "icon_size", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS icon_size BIGINT"),
    ("lists", "icon_by", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS icon_by BIGINT REFERENCES users(id) ON DELETE SET NULL"),
    ("lists", "header_size", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS header_size BIGINT"),
    ("lists", "header_by", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS header_by BIGINT REFERENCES users(id) ON DELETE SET NULL"),
]
AFTER = [  # behind the columns: SCHEMA runs before MIGRATIONS
    "CREATE INDEX IF NOT EXISTS ix3884_lists_icon_by ON lists(icon_by) WHERE icon_by IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix3884_lists_header_by ON lists(header_by) WHERE header_by IS NOT NULL",
]
