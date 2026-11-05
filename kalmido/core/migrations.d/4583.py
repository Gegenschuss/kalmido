"""2.556.0 C (#4583): tasks.sub_snapshot -- the completed copy of a recurring task keeps what its subtasks were when it was
completed (JSON {"done", "total", "items": [{"title", "status", "depth"}]}, tasks/lifecycle.do_complete rsn_take; '' = none).
Written once on completion, never changed; the original's subtasks are reset as before. New column only: older versions
ignore it."""
MIGRATIONS = [
    ("tasks", "sub_snapshot", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sub_snapshot TEXT NOT NULL DEFAULT ''"),
]
