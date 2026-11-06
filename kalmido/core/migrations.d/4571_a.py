"""2.589.0 (#4571): shoot days from a quotation as pencilled-in bookings of the disposition (office/offerdispo.py). A booking
made from a quotation remembers its chain (offer_root = the first quotation, version_of), the quotation it came from last
(offer_doc) and its place in it (offer_pos "d:<part>:<crew row>:<n>"); offer_mark = '' | 'changed' | 'gone' marks a booking a
newer version of the quotation would change but may not (a firm one, or a filled place). slot_name = the crew function of an
open place (resource_kind 'slot', resource_id 0) -- it stays when the place is filled. Nullable columns / columns with a
default only: older versions ignore them (an open place shows to them as a booking without a resource)."""
MIGRATIONS = [
    ("hub_bookings", "offer_root", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS offer_root BIGINT"),
    ("hub_bookings", "offer_doc", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS offer_doc BIGINT"),
    ("hub_bookings", "offer_pos", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS offer_pos TEXT NOT NULL DEFAULT ''"),
    ("hub_bookings", "offer_mark", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS offer_mark TEXT NOT NULL DEFAULT ''"),
    ("hub_bookings", "slot_name", "ALTER TABLE hub_bookings ADD COLUMN IF NOT EXISTS slot_name TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS hub_bookings_offer ON hub_bookings(org_id, offer_root) WHERE offer_root IS NOT NULL",
]
