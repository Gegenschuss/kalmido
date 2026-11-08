"""2.673.0 (#5130): an index on doc_notes(user_id). The key doc_notes.user_id -> users (ON DELETE SET NULL, #4807) had none:
every person that goes made the database scan all document notes for that key. New index only: older versions ignore it."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS doc_notes_user ON doc_notes(user_id)",
]
