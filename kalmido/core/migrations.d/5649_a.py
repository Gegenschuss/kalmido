"""2.986.0 (#5649): the call sheet's agency is chosen from the contacts and remembered at the project: lists.cs_agency_id = the
contact chosen last as the agency on a call sheet of this project (hub/callsheet.py cs_put writes it, the next new call sheet
of the project starts with it). Only an id: whether the viewer may read that contact is checked on every read (the area's
address books, hub/dispo.py dsp_book_ids). A contact deleted for good clears it. Additive: an older version ignores the column."""
MIGRATIONS = [
    ("lists", "cs_agency_id",
     "ALTER TABLE lists ADD COLUMN IF NOT EXISTS cs_agency_id BIGINT REFERENCES contacts(id) ON DELETE SET NULL"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5649_lists_cs_agency_id ON lists(cs_agency_id) WHERE cs_agency_id IS NOT NULL",
]
