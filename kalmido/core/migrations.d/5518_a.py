"""2.857.0 (#5518): doc_views.rules = the saved view's filter in the shared core's format (docs/dev/kern.md "Filter",
kalmido/docs/dfilter.py): JSON {op, conds, sort?, dir?, ...}; '' = an older view that has only its query string (it opens
converted: dfilter.py dvf_from_query). The column query stays as it is. New column with a default: older versions ignore it."""
MIGRATIONS = [
    ("doc_views", "rules", "ALTER TABLE doc_views ADD COLUMN IF NOT EXISTS rules TEXT NOT NULL DEFAULT ''"),
]
