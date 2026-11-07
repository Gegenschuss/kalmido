"""2.625.0 C (#3961): the private polls of a personal agent go into its former owner's trash when the agent changes hands
(agents/admin.py agent_owner_set): sched_polls.trash_owner = who still sees them there (the former owner; a former team
agent: the agent itself), read-only -- nobody restores them (the new owner sees only what the agent makes from then on).
NULL = an ordinary poll. Its account deleted = its kept polls go along. Older versions ignore the column (the polls stay in
the trash there with their links closed, but the agent's new owner sees them in the trash)."""
MIGRATIONS = [
    ("sched_polls", "trash_owner", "ALTER TABLE sched_polls ADD COLUMN IF NOT EXISTS trash_owner BIGINT REFERENCES users(id) ON DELETE CASCADE"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix3961_sched_polls_trash_owner ON sched_polls(trash_owner) WHERE trash_owner IS NOT NULL",
]
