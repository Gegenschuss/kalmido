"""2.569.0 B (#4675): the Kalmido AI in team projects (agents/srvteam.py). agent_usage.asked_by / agent_runs.asked_by = the person
whose request a run of a server agent worked on (NULL: nobody's, e.g. a planned check of the server or an old row): the usage of a
team agent counts per member. agent_server.member_limits = the limit per member of a team agent (json {period: day | month,
metric: tokens, hard}, '' = none), set by an admin of its organisation. New columns only (nullable or with a default), older
versions ignore them."""
MIGRATIONS = [
    ("agent_usage", "asked_by", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS asked_by BIGINT"),
    ("agent_runs", "asked_by", "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS asked_by BIGINT"),
    ("agent_server", "member_limits", "ALTER TABLE agent_server ADD COLUMN IF NOT EXISTS member_limits TEXT NOT NULL DEFAULT ''"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4675_agent_usage_asked ON agent_usage(agent_id, asked_by, day) WHERE asked_by IS NOT NULL",
]
