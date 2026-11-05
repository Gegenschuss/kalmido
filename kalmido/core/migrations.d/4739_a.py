"""2.568.0 (#4739): stage 6 of the shared core -- a project's own member shares (PUT /api/lists/<id>/members, the agent of a
project) are share rows of the core on the project's reference node too (fs_shares, list_role = the list role, expiry,
created_by, revoked rows in obj_revoked). list_own = 1 marks such a row: list_members stays the role table every reader uses
(its own_role); the folders' rows (lists/lffolder.py lf_want, list_members.frole) leave it out and the file store's share
dialog does not show it. New column with a default only: older versions ignore it (they read the row as a share of the
project's node with the same list role)."""
MIGRATIONS = [
    ("fs_shares", "list_own", "ALTER TABLE fs_shares ADD COLUMN IF NOT EXISTS list_own BIGINT NOT NULL DEFAULT 0"),
]
