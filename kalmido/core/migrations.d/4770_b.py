"""2.570.0 (#4770): doc_meta.edited_at = the version of a document's changes (docs/web.py doc_update: people, batches, agents):
PATCH /api/docs/<id> checks expect_updated_at against it (409 with the document: an undo never overwrites another
session's change). updated_at stays what the background stamps (the recognition queue's heartbeat, the thumbnail's cache
key), so a recognition run that finished no longer turns an undo into a conflict. NULL = not edited since: the row's
created_at stands for it (web.doc_ver); older versions ignore the column."""
MIGRATIONS = [
    ("doc_meta", "edited_at", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ"),
]
