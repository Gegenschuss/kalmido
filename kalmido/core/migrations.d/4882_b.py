"""2.783.0 (#4882): whether a document's title was set by hand (doc_meta.title_manual). 1 = by a person / an agent: the area's
title pattern never replaces it; 0 = from the pattern (or emptied): the recognition, the rules, "Apply what was learned" and
"Recognise again" may set it anew. NULL = a row from before: a title there counts as set by hand (old documents are not
rewritten, docs/store.py title_is_manual). New nullable column only: an older version ignores it."""
MIGRATIONS = [
    ("doc_meta", "title_manual", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS title_manual BIGINT"),
]
