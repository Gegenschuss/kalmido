"""2.395.0 (#3380): lists.mail_guests -- guests (role participant / view, an organisation reader) of a project read its filed
e-mails only with this switch on (project admin, default off; hub/hubmail.py hbm_list_read). New column only: older versions
ignore it (there every role reads, as before)."""
MIGRATIONS = [
    ("lists", "mail_guests", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS mail_guests BIGINT NOT NULL DEFAULT 0"),
]
