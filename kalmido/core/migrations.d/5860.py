"""2.1072.0 (#5860): agent_chat.show_steps = the steps of "Show me" of an agent's message ([{target, text?}], api/showme.py): the
keys of the named places (docs/help-targets.json) the app opens and highlights one after the other. NULL = none. New column
only: an older version ignores it."""
MIGRATIONS = [
    ("agent_chat", "show_steps", "ALTER TABLE agent_chat ADD COLUMN IF NOT EXISTS show_steps JSONB"),
]
