"""2.1068.0 (#5831): agent_chat.apv_diff = the short line diff an approval card's step made in a text, stored when the person
answered the card (agents/apvdiff.py apvd_snapshot), so a decided card still shows what was approved. Outside choices on
purpose: choices go to the agent and into events, the diff was read with the person's rights and is served only through
GET /api/approvals/diff after checking them again. A comment card keeps it in obj_comments.extra->'apvdiff' (no column).
A nullable column only: an older version ignores it."""
MIGRATIONS = [
    ("agent_chat", "apv_diff", "ALTER TABLE agent_chat ADD COLUMN IF NOT EXISTS apv_diff JSONB"),
]
