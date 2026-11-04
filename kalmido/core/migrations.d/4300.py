"""#4300: a locked folder of the file store (files/fslock.py) moved by an account or organisation import. Its names, files and
key wraps are bound to the ids of the server they were made on: fs_locks.aad_folder = the folder id in those bindings (NULL = its
own id), fs_lock_keys.aad_r / aad_w = recipient and wrapper in the binding of that copy (NULL = user_id / wrapped_by). New
columns only: older versions ignore them (a folder that was imported cannot be opened there, nothing is changed)."""
# AFTER, not MIGRATIONS: these two tables are made with the indexes (core/schema.py), after the steps on a new database
AFTER = [
    "ALTER TABLE fs_locks ADD COLUMN IF NOT EXISTS aad_folder BIGINT",
    "ALTER TABLE fs_lock_keys ADD COLUMN IF NOT EXISTS aad_r BIGINT",
    "ALTER TABLE fs_lock_keys ADD COLUMN IF NOT EXISTS aad_w BIGINT",
]
