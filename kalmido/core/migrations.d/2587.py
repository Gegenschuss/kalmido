"""2.383.0 (#2587): an attendee's answers to single dates of a series (a phone answers one occurrence, RECURRENCE-ID):
JSON {occurrence key: partstat} with only the dates whose answer differs from the answer to the series ('' = none).
Written by CalDAV (events/dav.py ev_occ_answers), read by the calendar views, the free / busy spans and the rendering
(events/ics.py ev_lines). A column only: older versions ignore it."""
MIGRATIONS = [
    ("event_attendees", "occ_ps", "ALTER TABLE event_attendees ADD COLUMN IF NOT EXISTS occ_ps TEXT NOT NULL DEFAULT ''"),
]
