"""2.545.0 (#4387): the VAT rate of a travel receipt (office_trip_items.vat_pct: "19" | "7" | "0" | NULL = none, as before):
with a rate the receipt counts net in the income statement and its input tax in field 66 of the VAT return (office/books.py)
and DATEV books it with the input tax key. New column only: older versions ignore it (no input tax, as before)."""
MIGRATIONS = [
    ("office_trip_items", "vat_pct", "ALTER TABLE office_trip_items ADD COLUMN IF NOT EXISTS vat_pct TEXT"),
]
