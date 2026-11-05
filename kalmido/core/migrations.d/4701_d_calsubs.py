"""2.564.0 D (#4701): cal_subs.updated_at = the version of a calendar subscription's settings (name, colour, shown, refresh,
link / login), set only when a person saves them (changed_at moves on every fetch too); the edit dialog sends it back as
expect_updated_at (saved meantime on another device -> 409). A nullable column only: older versions ignore it; a
subscription without one counts with its created_at."""
MIGRATIONS = [
    ("cal_subs", "updated_at", "ALTER TABLE cal_subs ADD COLUMN IF NOT EXISTS updated_at TEXT"),
]
