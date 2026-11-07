"""2.642.0 (#4772): the customer link of a sign-off (office_signoffs kind video) for clients without an account. Several live
links per sign-off; show_old = the client may also look at the older versions (ticked when the link was made); a new version
carries a decided link on (videos/vdlink.py vdl_carry): the decided record stays as it is (the history), a new open record
takes over the same token, carried_from = the record before it, carried_ver = the version that carried it on (its undo).
Nullable / defaulted columns only: an older version ignores them."""
MIGRATIONS = [
    ("office_signoffs", "show_old", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS show_old INTEGER NOT NULL DEFAULT 0"),
    ("office_signoffs", "carried_from", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS carried_from BIGINT REFERENCES office_signoffs(id) ON DELETE SET NULL"),
    ("office_signoffs", "carried_ver", "ALTER TABLE office_signoffs ADD COLUMN IF NOT EXISTS carried_ver BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4772_office_signoffs_carried_from ON office_signoffs(carried_from) WHERE carried_from IS NOT NULL",
]
