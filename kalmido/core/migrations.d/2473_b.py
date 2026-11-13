"""2.616.0 (#2473, Fable finding 4): who set the FinTS server address of a bank account last and when (fints_server_by: the
person, fints_server_at: the time) -- the fetch dialog shows it when somebody else changed the address since. New columns
only: an older version ignores them."""
MIGRATIONS = [
    ("office_bank_accounts", "fints_server_by", "ALTER TABLE office_bank_accounts ADD COLUMN IF NOT EXISTS fints_server_by BIGINT"),
    ("office_bank_accounts", "fints_server_at", "ALTER TABLE office_bank_accounts ADD COLUMN IF NOT EXISTS fints_server_at TIMESTAMPTZ"),  # 2.1115.0 (#5951): TIMESTAMPTZ
]
