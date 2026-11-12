"""2.1041.0 (#5814): an optional or alternative position of a quotation. office_doc_items.opt = '' (a normal position, every
row of before), 'optional' or 'alternative': printed with its quantity, unit price and amount, but counted in no sum (net, tax,
gross, discount, producing, surcharges, surplus; office/calc.py office_calc). New column with a default only: an older version
ignores it (after a rollback such a position counts again, nothing is lost)."""
MIGRATIONS = [
    ("office_doc_items", "opt", "ALTER TABLE office_doc_items ADD COLUMN IF NOT EXISTS opt TEXT NOT NULL DEFAULT ''"),
]
