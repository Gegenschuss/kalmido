"""2.616.0 (#2473): the direct bank fetch over FinTS (office/fints.py) remembers per bank account the login name at the bank
(fints_login, sealed like the IBAN: core/orgcrypt.py) and the address of the bank's FinTS server (fints_server, https only).
Never the PIN: it is asked at every fetch and lives only in the memory of the running dialog. New columns only: an older
version ignores them."""
MIGRATIONS = [
    ("office_bank_accounts", "fints_login", "ALTER TABLE office_bank_accounts ADD COLUMN IF NOT EXISTS fints_login TEXT NOT NULL DEFAULT ''"),
    ("office_bank_accounts", "fints_server", "ALTER TABLE office_bank_accounts ADD COLUMN IF NOT EXISTS fints_server TEXT NOT NULL DEFAULT ''"),
]
