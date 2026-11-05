"""2.564.0 (#4701): sheet_hist.what = a change of the table itself, not a typed input: title | tab | chart (no cell) or name |
freeze (of a cell); empty for the cell inputs as before (sheets/shhist.py shh_meta). A nullable column only: older versions
ignore it."""
MIGRATIONS = [
    ("sheet_hist", "what", "ALTER TABLE sheet_hist ADD COLUMN IF NOT EXISTS what TEXT"),
]
