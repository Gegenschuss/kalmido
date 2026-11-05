"""2.565.0 D (#4674): the Kalmido AI (server agent, #4670) can run each starter routine with a model of its own.
agent_server.flow_models = JSON {routine: model} (routine = briefing | tidy | meetings | followup; a missing or '' entry = the
agent's model). agent_schedules.srv_flow = the routine a planned job of the starter pack stands for ('' = a plan of its own).
agent_runs.flow and agent_usage.flow = the routine a run / a usage report belonged to ('' = none: chat, mention, ...), so the
usage shows per routine. New columns with defaults only: older versions ignore them, old rows keep ''."""
MIGRATIONS = [
    ("agent_server", "flow_models", "ALTER TABLE agent_server ADD COLUMN IF NOT EXISTS flow_models TEXT NOT NULL DEFAULT '{}'"),
    ("agent_schedules", "srv_flow", "ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS srv_flow TEXT NOT NULL DEFAULT ''"),
    ("agent_runs", "flow", "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS flow TEXT NOT NULL DEFAULT ''"),
    ("agent_usage", "flow", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS flow TEXT NOT NULL DEFAULT ''"),
]
