"""2.750.0 (#4876): a document's own title, apart from its file name (fs_nodes.name). Empty = the file name without its
ending (docs/store.py doc_title); old documents are not rewritten. Changing the title never renames the file, two documents
may share one; the file name stays unique per folder and is what downloads, ZIPs and shares use. Plain like the file name it
stands for (the list sorts by it in SQL). New column with a default only: an older version ignores it (it shows the file name)."""
MIGRATIONS = [
    ("doc_meta", "title", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''"),
]
