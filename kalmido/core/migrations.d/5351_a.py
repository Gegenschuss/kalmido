"""2.769.0 (#5351): a table column's own number format. sheet_columns.dec = decimal places 0-4 of a number / currency /
percent column (NULL = automatic, as before), sheet_columns.cur = the ISO 4217 currency of a currency column (NULL = the
table's currency, as before). Only the display, sums, pivot, print and export follow them; stored values and formulas keep
the full value (sheets/core.py sh_col_numfmt). New nullable columns only: an older version ignores them."""
MIGRATIONS = [
    ("sheet_columns", "dec", "ALTER TABLE sheet_columns ADD COLUMN IF NOT EXISTS dec BIGINT"),
    ("sheet_columns", "cur", "ALTER TABLE sheet_columns ADD COLUMN IF NOT EXISTS cur TEXT"),
]
