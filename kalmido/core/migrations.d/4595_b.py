"""2.545.0 (#4595): the switch "Extend the lock" of an office (an organisation or a personal office): orgs.ret_hold_at = since when
(ISO time, NULL = off), orgs.ret_hold_by = who switched it on. While it is on nothing kept by law of that office is deleted,
not even after its period (office/olock.py olk_held). New columns only: older versions ignore them."""
MIGRATIONS = [
    ("orgs", "ret_hold_at", "ALTER TABLE orgs ADD COLUMN IF NOT EXISTS ret_hold_at TEXT"),
    ("orgs", "ret_hold_by", "ALTER TABLE orgs ADD COLUMN IF NOT EXISTS ret_hold_by BIGINT"),
]
