"""2.1042.0 (#5815): discounts of quotations as a fixed amount and per position.
office_docs.discount_amount = the document discount as a fixed net amount in the home currency (NULL = none: the percent
discount_pct counts as before); office_doc_items.discount_pct = a position's own discount in percent of its quantity x rate
(0 = none). New columns with defaults only: older versions ignore them and compute as before, old rows keep NULL / 0."""
MIGRATIONS = [
    ("office_docs", "discount_amount", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(14,2)"),
    ("office_doc_items", "discount_pct", "ALTER TABLE office_doc_items ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(14,4) NOT NULL DEFAULT 0"),
]
