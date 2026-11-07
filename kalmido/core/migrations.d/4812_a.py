"""2.583.0 (#4812): the sharper preview of a document for big cards (800 px wide, next to the 320 px one in doc_meta.thumb):
its path below attachments/docthumbs, sealed like the small one (docs/store.py thumb_store). Empty / NULL = none yet: the card
shows the small one and the catch-up (docs/thumbfill.py) makes it while the queue is idle. Nullable column only: older
versions ignore it."""
MIGRATIONS = [
    ("doc_meta", "thumb_l", "ALTER TABLE doc_meta ADD COLUMN IF NOT EXISTS thumb_l TEXT"),
]
