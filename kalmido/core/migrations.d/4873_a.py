"""2.892.0 (#4873, includes #4806): "Optimise PDF" -- doc_meta.pdf_opt holds the state of a document's optimisation (docs/pdfoptq.py:
queued / running / measured / the result with both sizes and the versions; JSON without any content of the document). The
documents queue looks for a queued one at every idle step: a small partial index on the rows that have a state at all (most
documents never get one). Its predicate calls no function: a backup's index statements may only call the functions of
admin/backup.py _CALL_HEADS, so left(pdf_opt, 6) there made every backup unrestorable ("objects", backup suites).
A column with a DEFAULT and an index only: older versions ignore both (a queued optimisation then simply waits)."""
MIGRATIONS = [
    ("doc_meta", "pdf_opt", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS pdf_opt TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4873_doc_meta_pdfopt ON doc_meta(node_id) WHERE pdf_opt <> ''",
]
