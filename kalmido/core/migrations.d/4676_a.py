"""2.571.0 D (#4676): read-only web research of the Kalmido AI (server agent, agents/srvweb.py), per routine, default off.
agent_server.flow_web = JSON {key: true} (keys: the starter routines + "other" for runs without one; a missing key = off).
agent_runs.web = the web state of a run with web access ('' = none): the people it may write to, the source addresses and the
counts (searches, fetched pages, VAT checks); the control gate reads it while the run is on. agent_usage.web_searches /
web_fetches = the provider's web tool uses of one usage report. New columns with defaults only: older versions ignore them."""
MIGRATIONS = [
    ("agent_server", "flow_web", "ALTER TABLE agent_server ADD COLUMN IF NOT EXISTS flow_web JSONB NOT NULL DEFAULT '{}'"),
    ("agent_runs", "web", "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS web TEXT NOT NULL DEFAULT ''"),
    ("agent_usage", "web_searches", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS web_searches INTEGER NOT NULL DEFAULT 0"),
    ("agent_usage", "web_fetches", "ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS web_fetches INTEGER NOT NULL DEFAULT 0"),
]
