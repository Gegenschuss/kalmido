"""2.571.0 (#4776): who changed an event / a contact last (updated_by), set on every write path (the app, the API and its
agents, CalDAV / CardDAV, imports, moves, trash): an agent's change can be found (audit #2822 B-F2). Rows from before stay
NULL ("not known"). Nullable columns only: older versions ignore them."""
MIGRATIONS = [
    ("events", "updated_by", "ALTER TABLE events ADD COLUMN IF NOT EXISTS updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL"),
    ("contacts", "updated_by", "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4776_events_updated_by ON events(updated_by) WHERE updated_by IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix4776_contacts_updated_by ON contacts(updated_by) WHERE updated_by IS NOT NULL",
]
