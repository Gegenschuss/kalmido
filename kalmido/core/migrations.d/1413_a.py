"""2.553.0 (#1413): a person deletes their own account (admin/selfdelete.py). users.delete_at = when the deletion runs (NULL =
none asked for; set, the account is locked: disabled = 1, the sign-in offers only "Cancel the deletion"), users.delete_plan =
what was chosen when it was asked for (JSON: per own project hand over to a member or delete along, the retention step, the
paused own agents, the hashes of the cancel links). New columns only: an older version ignores them (the account stays
disabled there, an admin can enable it again; the deletion runs once a newer version is back)."""
MIGRATIONS = [
    ("users", "delete_at", "ALTER TABLE users ADD COLUMN IF NOT EXISTS delete_at TEXT"),
    ("users", "delete_plan", "ALTER TABLE users ADD COLUMN IF NOT EXISTS delete_plan TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix1413_users_delete_at ON users(delete_at) WHERE delete_at IS NOT NULL",
]
