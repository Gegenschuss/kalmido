"""2.872.0 (#5532): the call sheet of a shoot day becomes a kind of the shared core (hub/dspkern.py, kind "callsheet"): its
table gets the columns the core writes (docs/dev/kern.md section 1) -- owner_id (who made it; the rights come from the shoot
day's area, so an account deleted only clears it), rev, updated_by, deleted_at / deleted_by (the core's trash: the call sheet
goes there with the last booking of its shoot day). New nullable / defaulted columns only: an older version ignores them (a
call sheet in the trash it would show again only while its shoot day has live bookings, which the trash rule rules out)."""
MIGRATIONS = [
    ("hub_callsheets", "owner_id",
     "ALTER TABLE hub_callsheets ADD COLUMN IF NOT EXISTS owner_id BIGINT REFERENCES users(id) ON DELETE SET NULL"),
    ("hub_callsheets", "rev", "ALTER TABLE hub_callsheets ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("hub_callsheets", "updated_by", "ALTER TABLE hub_callsheets ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("hub_callsheets", "deleted_at", "ALTER TABLE hub_callsheets ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("hub_callsheets", "deleted_by", "ALTER TABLE hub_callsheets ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS hub_callsheets_trash ON hub_callsheets(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5532_hub_callsheets_owner_id ON hub_callsheets(owner_id) WHERE owner_id IS NOT NULL",
]
