"""2.609.0 (#3373): required custom fields (lists/fields.py field_required_check): 1 = a new task of the list needs a value in
it (app, API, MCP), an existing one only when the field itself is cleared. New column with a default: older versions ignore it."""
MIGRATIONS = [
    ("list_fields", "required", "ALTER TABLE list_fields ADD COLUMN IF NOT EXISTS required BIGINT NOT NULL DEFAULT 0"),
]
