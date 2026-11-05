"""2.545.0 (#4387): the reverse charge mark of a receipt (section 13b UStG, the office is the one who owes the VAT):
rc_receipts.rc13b = '' (none) | 'eu' (a service of a business in another EU state, section 13b (1): UStVA fields 46 / 47)
| 'other' (the other cases of section 13b (2) no. 1, 2, 4-12, e.g. a service from a third country or construction work at
home: fields 84 / 85); the input tax of both goes to field 67 (office/books.py bk_ustva). New column only: older versions
ignore it (the receipt counts as before)."""
MIGRATIONS = [
    ("rc_receipts", "rc13b", "ALTER TABLE rc_receipts ADD COLUMN IF NOT EXISTS rc13b TEXT NOT NULL DEFAULT ''"),
]
