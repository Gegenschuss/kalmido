"""2.593.0 (#3570): org_joins.silent = 1 marks an invitation of an existing account that the inviting admin of a company of its
own (orgs.self_made) may not see: it is dropped for the invited person (no News item, no mail, no push, it can be neither
accepted nor declined; accounts/orginvite.py ojn_* read only silent=0), but it stands in the organisation's list of open
invitations like any other, so the list never tells an address with an account from a new one. org_joins is made by
core/schema.py after the steps, so the column comes in AFTER (#4300). A column with a DEFAULT only: older versions ignore it
(they would show such an invitation to the person like an ordinary one).
Way back (review F6): before an older version starts on this database, remove the silent invitations first:
    DELETE FROM org_joins WHERE silent=1
(the column itself may stay; the admins' lists then just lack those rows)."""
AFTER = [
    "ALTER TABLE org_joins ADD COLUMN IF NOT EXISTS silent BOOLEAN NOT NULL DEFAULT false",
]
