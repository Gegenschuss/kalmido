"""2.578.0 (#3462 part C): the format of a table's cells and its colour rules (sheets/shfmt.py). sheet_cells.fmt = JSON of the
cell's format on top of its column's kind ('' = none): bold, italic, color / fill (a key of the app's palette), align, wrap,
merge [rows, columns] on the top left cell of a merged block. sheets.fmt_rules = JSON list of the sheet's conditional colour
rules ('' = none). New columns with a default only: older versions ignore both (the cells read as before, without format)."""
MIGRATIONS = [
    ("sheet_cells", "fmt", "ALTER TABLE sheet_cells ADD COLUMN IF NOT EXISTS fmt TEXT NOT NULL DEFAULT ''"),
    ("sheets", "fmt_rules", "ALTER TABLE sheets ADD COLUMN IF NOT EXISTS fmt_rules TEXT NOT NULL DEFAULT ''"),
]
