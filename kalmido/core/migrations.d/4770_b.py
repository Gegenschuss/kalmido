"""2.570.0 (#4770): doc_meta.run_at = when the recognition queue last took the document (docs/ingest.py): the heartbeat its
stale check reads. Before, the queue stamped updated_at for that, so a run that finished moved the version a person's undo
is checked against (expect_updated_at) and the undo was refused for nothing; updated_at is now the version of the changes
of people and agents only. Nullable: older rows and older versions fall back to updated_at."""
MIGRATIONS = [
    ("doc_meta", "run_at", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS run_at TEXT"),
]
