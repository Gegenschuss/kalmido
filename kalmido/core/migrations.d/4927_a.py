"""2.603.0 (#4927): an entertainment receipt as the proof of its payment (office/mealpay.py): pay_kind = bank (office_bank_tx.id) |
cash (office_cash_entries.id) | card (office_cc_lines.id), '' = none; pay_id = that line. With the basis "bank and cash" of the
income statement (office/euerbasis.py) the meal counts only through that line and gives it the 70 / 30 split. New columns only:
an older version ignores them (the meal counts on its own date there, as before)."""
MIGRATIONS = [
    ("office_meals", "pay_kind", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS pay_kind TEXT NOT NULL DEFAULT ''"),
    ("office_meals", "pay_id", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS pay_id BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4927_office_meals_pay ON office_meals(org_id, pay_kind, pay_id) WHERE pay_kind<>''",
]
