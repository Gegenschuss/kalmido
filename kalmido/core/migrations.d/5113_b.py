"""2.665.0 (#5113): git_issue_comments.send_at = when the issue sync began to send this comment (set and committed before
its POST, kalmido/integrations/git_sync.py _push_comments). A row with send_at but no remote_id: the store after the POST
broke off; the next try looks for the comment in the repository first instead of sending it again. Older versions ignore it
(they send such a row again, as before)."""
MIGRATIONS = [
    ("git_issue_comments", "send_at", "ALTER TABLE git_issue_comments ADD COLUMN IF NOT EXISTS send_at TEXT NOT NULL DEFAULT ''"),
]
