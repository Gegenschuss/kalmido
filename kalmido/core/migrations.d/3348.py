"""2.953 (#3348): the key change of a locked folder of the file store (files/fslock.py) after someone lost access, like the knowledge
spaces (wiki_spaces.e2e_rotate / e2e_reenc): fs_locks.e2e_rotate = the generation a key holder's account was deleted in (0 = none;
who lost a share or left the organisation is seen from the rights, the account's key rows go with it), fs_locks.e2e_reenc = the
generation the files are being encrypted again with (0 = nothing running). New columns with a default only: the version before
ignores them (a folder keeps working with the generation it shows)."""
# AFTER, not MIGRATIONS: fs_locks is made with the indexes (core/schema.py), after the steps on a new database (as 4300.py)
AFTER = [
    "ALTER TABLE fs_locks ADD COLUMN IF NOT EXISTS e2e_rotate BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE fs_locks ADD COLUMN IF NOT EXISTS e2e_reenc BIGINT NOT NULL DEFAULT 0",
]
