"""2.577.0 (#4708 6): the secret of an event calendar's subscription link (ev_cal_feeds, events/evfeed.py) is kept only as a
SHA-256 hash, as the task feed's (core/tokenhash.py). The plain column stays (NOT NULL, written '') so the version before
still runs on the database; core/tokenhash.py tkh_migrate turns the plain secrets left into hashes at every start. New
nullable column only."""
MIGRATIONS = [
    ("ev_cal_feeds", "secret_hash", "ALTER TABLE ev_cal_feeds ADD COLUMN IF NOT EXISTS secret_hash TEXT"),
]
