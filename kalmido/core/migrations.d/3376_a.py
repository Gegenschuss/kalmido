"""2.574.0 (#3376): lists.two_eyes: an integrate / deploy request or a merge request needs the 👍 of two different
approvers (agents/gates.py gate_two_eyes; default off). New column only: older versions ignore it (one 👍 approves)."""
MIGRATIONS = [
    ("lists", "two_eyes", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS two_eyes BIGINT NOT NULL DEFAULT 0"),
]
