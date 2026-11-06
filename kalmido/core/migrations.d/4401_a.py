"""2.580.0 (#4401): a stack the recognition found clear waits for the queue's automatic split (doc_meta.split_scan state "auto",
docs/split.py sp_auto_queued). The queue looks for one at every step: a small partial index (like doc_meta_split_wait for the
page scan). An index only: older versions ignore it (a stack in state "auto" shows there as no stack, "Split stack…" stays)."""
AFTER = [
    """CREATE INDEX IF NOT EXISTS ix4401_doc_meta_split_auto ON doc_meta(node_id) WHERE split_scan ILIKE '%"state":"auto"%'""",
]
