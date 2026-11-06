"""2.607.0 (#4872): "Apply what was learned" (docs/batch.py docs_apply_learned, docs/store.py learn_apply) can be taken back as
one step: doc_meta.learn_prev keeps per document what the sorting replaced (sender / type ids, the folder, the marks and the
suggestions as stored, sealed ones stay sealed) with the run's token, learn_at when; the queue's clean-up (store.py redo_purge)
empties it after 24 h. Columns with a DEFAULT only: older versions ignore them."""
MIGRATIONS = [
    ("doc_meta", "learn_prev", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS learn_prev TEXT NOT NULL DEFAULT ''"),
    ("doc_meta", "learn_at", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS learn_at TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4872_doc_meta_learn ON doc_meta(learn_at) WHERE learn_at <> ''",
]
