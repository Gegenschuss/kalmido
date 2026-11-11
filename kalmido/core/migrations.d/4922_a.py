"""2.985.0 (#4922): a silent invitation (org_joins.silent = 1, #3570) no longer vanishes with the invited account: when the
account is deleted (its own deletion, the clean-up of unconfirmed registrations, every way through accounts/users.py
_user_purge) the row becomes a neutral one without an account (user_id NULL) that keeps the address as the list showed it
(email), its role and its time - it stays in the organisation's list of open invitations and runs out like any other, so the
list never tells that an account was there (accounts/orginvite.py ojn_neutral). Review H3: core/schema.py still creates
org_joins.user_id NOT NULL (schema.py is never changed): it is this AFTER that drops the NOT NULL, on every start, and that is
meant. Review F1: a silent row keeps the address the admin typed in email from the start (ojn_silent). org_joins is made by core/schema.py after the
steps, so the column comes in AFTER (#4300). A column without a DEFAULT and a NOT NULL that goes: rows of an ordinary invitation
keep their user_id as before.
Way back: the version before reads org_joins only joined with users (the list, Resend, Withdraw) or by user_id (the person's own
invitations, accepting, the import): a neutral row is simply not there for it (as before #4922, when the row went with the
account); nothing to remove first."""
# nullable-ok org_joins.user_id: the version before reads org_joins only joined with users or by user_id - a neutral row is not there for it
AFTER = [
    "ALTER TABLE org_joins ADD COLUMN IF NOT EXISTS email TEXT",
    "ALTER TABLE org_joins ALTER COLUMN user_id DROP NOT NULL",
]
