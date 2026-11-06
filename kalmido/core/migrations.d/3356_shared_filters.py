"""2.577.0 (#3356): a shared view of a project (kalmido/lists/sections.py): filters.list_id + shared = 1; NULL + 0 = a private
filter as before. It goes with its project. New columns only: older versions ignore both (they would show a shared view to its
creator as a private filter)."""
MIGRATIONS = [
    ("filters", "list_id", "ALTER TABLE filters ADD COLUMN IF NOT EXISTS list_id BIGINT REFERENCES lists(id) ON DELETE CASCADE"),
    ("filters", "shared", "ALTER TABLE filters ADD COLUMN IF NOT EXISTS shared BIGINT NOT NULL DEFAULT 0"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix3356_filters_list_id ON filters(list_id) WHERE list_id IS NOT NULL",
]
