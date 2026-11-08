"""2.702.0 (#5183): the bank account (office_bank_accounts.id) a CSV statement was imported into -- asked for in the import
dialog when the office has more than one account, so its lines land on that account in the balance sheet (office/ledger_dbl.py)
instead of the default one. No foreign key: a bank account is archived, never deleted, and the ledger ignores an id it does
not know. New nullable column only: an older version ignores it (the lines go to the default account, as before)."""
MIGRATIONS = [
    ("office_bank_imports", "bank_account_id", "ALTER TABLE office_bank_imports ADD COLUMN IF NOT EXISTS bank_account_id BIGINT"),
]
