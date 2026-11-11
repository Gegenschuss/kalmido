"""2.992.0 (#5684): the model per run, stage 2 - the usage per kind of run. agent_usage.run_class = the kind of run a usage
report belonged to (decide | review | routine; '' = not told: the model per run off, an older starter, a report of its own)
and agent_usage.run_id = the starter's short id of that run ('' = none), so the owner's section Model counts runs and tokens
per kind over the last 7 days. New columns with defaults only: older versions ignore them, old rows keep ''."""
MIGRATIONS = [
    ("agent_usage", "run_class", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS run_class TEXT NOT NULL DEFAULT ''"),
    ("agent_usage", "run_id", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT ''"),
]
