"""2.1062.0 (#5786): users.oinv_warned_at = when the warning went out that a never used account an organisation's invitation
set up (users.oinv_made_at, #5864) will be withdrawn automatically (accounts/orginvite.py oinv_expire: the daily clean-up).
It counts only while no invitation of the account is newer (a Resend starts the period again, and a new warning with it);
NULL = none delivered, then nothing is withdrawn. New column only: an older version ignores it (and withdraws nothing by
itself, as before). Review F2: users.oinv_used = the account signed in once (accounts/session.py start_session): durable,
unlike a session or a used link, which the clean-up deletes later - such an account is never withdrawn by itself."""
MIGRATIONS = [
    ("users", "oinv_warned_at", "ALTER TABLE users ADD COLUMN IF NOT EXISTS oinv_warned_at TIMESTAMPTZ"),
    ("users", "oinv_used", "ALTER TABLE users ADD COLUMN IF NOT EXISTS oinv_used BOOLEAN NOT NULL DEFAULT FALSE"),
]
