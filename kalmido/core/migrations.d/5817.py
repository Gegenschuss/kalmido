"""2.1041.0 (#5817): a quotation printed as a flat price. office_docs.flat_print = the positions keep title and description,
quantity, unit, unit price and amount per line are left out of the PDF, the preview and the customer's approval page (the
server leaves them out of the print model); net, tax and gross stay. New column with a default only: an older version ignores
it and prints every price as before."""
MIGRATIONS = [
    ("office_docs", "flat_print", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS flat_print BOOLEAN NOT NULL DEFAULT FALSE"),
]
