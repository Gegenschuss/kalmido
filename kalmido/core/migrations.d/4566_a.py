"""2.1158.0 (#4566 A): the packing list of a shoot day. A device of a quotation's equipment set is pencilled in as one booking
of the disposition (resource_kind 'equipment', office/offerdispo.py) with the quantity the quotation asks for (qty, whole
pieces, at least 1; a booking made by hand keeps 1). The call sheet (hub/callsheet.py) shows it in its packing list. A column
with a default only: older versions ignore it."""
MIGRATIONS = [
    ("hub_bookings", "qty", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS qty INTEGER NOT NULL DEFAULT 1"),
]
