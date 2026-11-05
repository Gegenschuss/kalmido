"""2.553.0 B (#3460): requests by e-mail (integrations/reqmail.py). lists.req_mail = the list's switch "Requests by e-mail"
(1 = a mail to its request address becomes a task + a portal ticket); lists.req_mail_done = also a mail to the customer when
the ticket is done (default off). The address is a hub_tokens row of kind 'ticket' (one per list, the same token kind as the
hub addresses). portal_tickets.via = how the ticket came in ('' = a form, 'mail' = by e-mail); portal_tickets.unverified = 1
when the receiving mail server did not confirm the sender's domain (the ticket is marked). New columns and an index only:
older versions ignore them (a 'ticket' token is then an unknown hub address kind, no mail is filed for it)."""
MIGRATIONS = [
    ("lists", "req_mail", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS req_mail BIGINT NOT NULL DEFAULT 0"),
    ("lists", "req_mail_done", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS req_mail_done BIGINT NOT NULL DEFAULT 0"),
    ("portal_tickets", "via", "ALTER TABLE portal_tickets ADD COLUMN IF NOT EXISTS via TEXT NOT NULL DEFAULT ''"),
    ("portal_tickets", "unverified", "ALTER TABLE portal_tickets ADD COLUMN IF NOT EXISTS unverified BIGINT NOT NULL DEFAULT 0"),
]
# unique-ok ix3460_hub_tokens_ticket: the kind 'ticket' is new with this fragment, no row of it exists before
AFTER = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix3460_hub_tokens_ticket ON hub_tokens(list_id) WHERE kind='ticket'",
]
