"""2.653.0 (#5079): what a line of an agent's history needs beyond its kind and title (agents/control.py), as JSON text:
fields = the fields of a task the agent changed ("Priority changed", "Moved to another project"), count = how many tasks one
batch step changed, ref = the reference an agent gave to a decision it wrote itself (POST /api/v1/agent/decisions). '' = nothing.
New column only, with a default: an older version ignores it (its lines then read as before)."""
MIGRATIONS = [
    ("agent_decisions", "info", "ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS info TEXT NOT NULL DEFAULT ''"),
]
