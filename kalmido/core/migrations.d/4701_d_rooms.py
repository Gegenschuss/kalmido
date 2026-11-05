"""2.564.0 D (#4701): tchat_rooms.updated_at = the version of a channel's / group's settings (name, open, archived); the
settings dialog sends it back as expect_updated_at (changed meantime -> 409). A nullable column only: older versions ignore
it; a room without one counts with its created_at."""
MIGRATIONS = [
    ("tchat_rooms", "updated_at", "ALTER TABLE tchat_rooms ADD COLUMN IF NOT EXISTS updated_at TEXT"),
]
