"""2.565.0 (#4719): the shared core, stage 5 -- the team chat's channels and group conversations are a kind of the core
(tchat_room, collab/teamchan.py). tchat_rooms.deleted_at = the core's trash column (always NULL so far: rooms are archived,
not trashed). The members are shares of the room's reference node (fs_shares: person, agent, group); tchat_members stays as
the reader fallback and is kept in step (collab/teamchan.py tcx_core_sync copies its rows forward at every start, and takes
back shares of people an older version removed). A nullable column only: older versions ignore it."""
MIGRATIONS = [
    ("tchat_rooms", "deleted_at", "ALTER TABLE tchat_rooms ADD COLUMN IF NOT EXISTS deleted_at TEXT"),
]
