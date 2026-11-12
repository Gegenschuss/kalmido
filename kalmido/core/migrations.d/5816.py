"""2.1041.0 (#5816): a net subtotal under every section of a quotation or invoice (the positions from a heading to the next).
office_docs.subtotals = the switch of the document (a new one takes the office setting subtotals_on); display only, it changes
no sum, no tax and no e-invoice. New column with a default only: an older version ignores it and prints as before."""
MIGRATIONS = [
    ("office_docs", "subtotals", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS subtotals BOOLEAN NOT NULL DEFAULT FALSE"),
]
