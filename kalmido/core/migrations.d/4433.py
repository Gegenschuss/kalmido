"""2.522.0 (#4433): the office and the private file store apart (docs/area.py). doc_meta.area = the area of a document in the
own space of a person with a personal office ('office' | 'private' | '' = never sorted); doc_meta.area_sort = how it got there
('' | 'pending' = the general input waits for the recognition | 'sorting' = the queue took it (review 2.522) | 'auto' = sorted, "Wrong area" offered | 'person' = a person
chose). New columns only: older versions ignore them (everything stays in the file store, as before)."""
MIGRATIONS = [
    ("doc_meta", "area", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS area TEXT NOT NULL DEFAULT ''"),
    ("doc_meta", "area_sort", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS area_sort TEXT NOT NULL DEFAULT ''"),
]
