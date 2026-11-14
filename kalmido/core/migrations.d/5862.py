"""2.1160.0 (#5862): fs_shares.excl = the folders kept out of a person's share of a whole knowledge area (a JSON list of
fs_nodes ids of that tree, set in the area's Share dialog; core/dlock.py dl_wiki_folders reads it for people like an agent's
data lock wiki_folders). NULL = none. New column only: an older version ignores it (the person then sees the whole area)."""
MIGRATIONS = [
    ("fs_shares", "excl", "ALTER TABLE fs_shares ADD COLUMN IF NOT EXISTS excl TEXT"),
]
# Fable review 6: core/dlock.py _dl_person_wkf reads a person's rows with exclusions on every request that checks a share
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5862_fs_shares_excl ON fs_shares(user_id) WHERE excl IS NOT NULL",
]
