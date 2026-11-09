"""2.777.0 C (#5378): agent_schedules.share_wait = 1 for a planned job of the starter pack of a server agent that was made while its
person shares no project with the agent yet (a new team agent): the plan is stored switched off and switches itself on (enabled,
next due time) as soon as the person reaches the agent through a shared project (agents/schedules.py sched_wait_wake: the watchdog,
or the starter pack asked again). A plan switched on or off by hand loses the mark. New column with a
default: older versions ignore it (their plans stay switched off until someone switches them on)."""
MIGRATIONS = [
    ("agent_schedules", "share_wait", "ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS share_wait SMALLINT NOT NULL DEFAULT 0"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5378_agent_schedules_wait ON agent_schedules(agent_id) WHERE share_wait=1",
]
