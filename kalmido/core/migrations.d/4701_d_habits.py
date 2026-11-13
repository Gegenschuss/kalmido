"""2.564.0 D (#4701): habits.updated_at = the version of a habit's settings (name, goal, days, reminders, colour, archived);
the habit dialog sends it back as expect_updated_at (saved meantime on another device -> 409). A nullable column only:
older versions ignore it; a habit without one counts with its created_at."""
MIGRATIONS = [
    ("habits", "updated_at", "ALTER TABLE habits ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
]
