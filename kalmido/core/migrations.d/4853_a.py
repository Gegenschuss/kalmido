"""2.636.0 (#4853): the state of one mail rule (hub/mailrules.py): last_error = the code of its last run in which a mail it took
became no document ('target' = the mailbox's holder cannot file into the target folder, 'nodoc' = every document was refused:
storage full, a locked folder, the hour's limit); '' = fine. The mail is then not remembered (the next run tries it again).
A new column with a default only: an older version ignores it."""
MIGRATIONS = [
    ("hub_mailbox_rules", "last_error", "ALTER TABLE hub_mailbox_rules ADD COLUMN IF NOT EXISTS last_error TEXT NOT NULL DEFAULT ''"),
]
