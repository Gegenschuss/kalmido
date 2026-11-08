"""2.674.0 (#4382 finding 5): the SHA-256 of the plus address tokens (integrations/mailtok.py). New rows store the token
sealed and its hash here; a mail is matched by the hash. Rows of an older version keep token in plain text and token_hash NULL
(found by the plain token as before). Only new nullable columns and indexes: the version before ignores them (it does not find
the addresses made after this version, the old ones keep working)."""
MIGRATIONS = [
    ("mail_tokens", "token_hash", "ALTER TABLE mail_tokens ADD COLUMN IF NOT EXISTS token_hash TEXT"),
    ("hub_tokens", "token_hash", "ALTER TABLE hub_tokens ADD COLUMN IF NOT EXISTS token_hash TEXT"),
    ("doc_mail", "token_hash", "ALTER TABLE doc_mail ADD COLUMN IF NOT EXISTS token_hash TEXT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4382_mail_tokens_hash ON mail_tokens(token_hash) WHERE token_hash IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix4382_hub_tokens_hash ON hub_tokens(token_hash) WHERE token_hash IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix4382_doc_mail_hash ON doc_mail(token_hash) WHERE token_hash IS NOT NULL",
]
