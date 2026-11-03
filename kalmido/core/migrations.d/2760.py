"""2.370.3 (#2760): the progress of a running queue row (accounts/bgjobs.py bgj_progress / bgj_state, e.g. a contacts import:
counts and a state, no content), so a browser asking any process of the instance reads it from the row instead of the memory
of the process that runs it. JSON text, '' = none. Older versions ignore the column."""
MIGRATIONS = [
    ("bg_jobs", "progress", "ALTER TABLE bg_jobs ADD COLUMN IF NOT EXISTS progress TEXT NOT NULL DEFAULT ''"),
]
