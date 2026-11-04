"""2.531.0 (#4497): the hash chain over finalised documents (office/chain.py). office_docs.chain_key = the number series the
document is chained in ('' = none: a quotation, a trial document, not finalised yet), chain_seq = its place there (NULL = none),
chain_prev / chain_hash = the hash of the one before and its own (sha256 hex). The documents finalised before are chained once
at the next start (ledger.ofx_migrate -> chain.hch_migrate, in the order they were finalised). New columns only: older versions
ignore them (a document they finalise is chained by the next start of a newer one). The index is NOT unique (review job/2606):
an older version after a rollback copies the columns when it duplicates a document (its DUP_SKIP does not know them) - a unique
index would make that fail; the chain lock keeps places unique, hch_migrate frees copied places and hch_check names doubles."""
MIGRATIONS = [
    ("office_docs", "chain_key", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS chain_key TEXT NOT NULL DEFAULT ''"),
    ("office_docs", "chain_seq", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS chain_seq BIGINT"),
    ("office_docs", "chain_prev", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS chain_prev TEXT NOT NULL DEFAULT ''"),
    ("office_docs", "chain_hash", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS chain_hash TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4497_office_docs_chain ON office_docs(org_id, chain_key, chain_seq) WHERE chain_seq IS NOT NULL",
]
