"""2.577.0 C (#4466): named document addresses (docs/mailaddr.py) as more doc_mail rows of a person and space: aid = the
address's own id (stays when the token is renewed; '' = the general address, every row before 2.577), name, target_folder
(a folder below the documents folder, NULL = the documents folder), tags (JSON list of tag names), active (off = mails are
refused), updated_at (the version for expect_updated_at). New columns only: an older version sees every row as a general
address of that space (it reads the first one)."""
MIGRATIONS = [
    ("doc_mail", "aid", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS aid TEXT NOT NULL DEFAULT ''"),
    ("doc_mail", "name", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''"),
    ("doc_mail", "target_folder", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS target_folder BIGINT"),
    ("doc_mail", "tags", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'"),
    ("doc_mail", "active", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE"),
    ("doc_mail", "updated_at", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4466_doc_mail_aid ON doc_mail(aid) WHERE aid <> ''",
]
