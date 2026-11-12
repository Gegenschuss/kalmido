"""2.1062.0 (#5864): users.oinv_made_at = when an organisation's invitation by address set the account up (POST
/api/orgs/<id>/invites, accounts/orginvite.py). The mark of "made by an organisation invitation" that withdrawing one
organisation's invitation no longer takes along (the org_invites row goes with it): the exception for a never used account
(orgs.py _oinv_pending, orginvite.py ojn_hidden) holds for the next organisation's invitation as well. NULL = not made so (or
made before; the daily clean-up fills it from org_invites). New column only: an older version ignores it."""
MIGRATIONS = [
    ("users", "oinv_made_at", "ALTER TABLE users ADD COLUMN IF NOT EXISTS oinv_made_at TIMESTAMPTZ"),
]
