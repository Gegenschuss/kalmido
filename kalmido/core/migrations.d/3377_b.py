"""2.394.0 B (#3377): GitHub / GitLab issues of a repository connection (kalmido/integrations/git_issues.py).
git_issue_links = which task an issue became (one task per issue and connection, one issue per task); remote_updated_at /
local_updated_at / etag are the state the two-way sync (part C) compares against. git_conns.issue_sync / issue_create are
that sync's switches, created now with the default off, without effect yet. Older versions ignore all of them."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS git_issue_links (
  conn_id BIGINT NOT NULL REFERENCES git_conns(id) ON DELETE CASCADE, issue_no BIGINT NOT NULL,
  task_id BIGINT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
  remote_updated_at TEXT, local_updated_at TEXT, etag TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  PRIMARY KEY (conn_id, issue_no));
"""
MIGRATIONS = [
    ("git_conns", "issue_sync", "ALTER TABLE git_conns ADD COLUMN IF NOT EXISTS issue_sync BIGINT NOT NULL DEFAULT 0"),
    ("git_conns", "issue_create", "ALTER TABLE git_conns ADD COLUMN IF NOT EXISTS issue_create BIGINT NOT NULL DEFAULT 0"),
]
