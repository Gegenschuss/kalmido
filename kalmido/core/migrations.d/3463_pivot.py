"""2.671.0 (#3463 b): sheets.pivot = the setting of a pivot sheet (JSON {source, rows, cols, values, filter, updated_at}: sheet and
column ids only, sheets/shpivot.py); '' = an ordinary sheet. A pivot sheet has no cells of its own: its table is computed from
its source sheet on every read. Older versions ignore it (they show the pivot sheet as an empty sheet of the table)."""
MIGRATIONS = [
    ("sheets", "pivot", "ALTER TABLE sheets ADD COLUMN pivot TEXT NOT NULL DEFAULT ''"),
]
