"""2.674.0 (#4382 finding 12): the end of a receipt fetcher key (docs/fetcher.py FX_DAYS, like a scan inbox key). A key made
before has none: it gets its year at its first use with this version (not cut off at once). A new nullable column only: the
version before ignores it (its keys then never run out, as before)."""
MIGRATIONS = [
    ("doc_fetchers", "expires_at", "ALTER TABLE doc_fetchers ADD COLUMN IF NOT EXISTS expires_at TEXT"),
]
