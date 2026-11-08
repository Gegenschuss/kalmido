"""2.674.0 (#4028, review F13 of 2.488.0): revoked_creds (the hashes of every API token / app password that went, core/schema.py
REVOKED_TRIGGER, read and written back by a restore: admin/backup.py bkr_creds_*) grew without end: the hosted MCP access
(agents/mcpremote.py) rotates its access token every hour, each one a row. exp = the end (api_tokens.expires_at) of a token that
had one, filled by its own trigger next to REVOKED_TRIGGER (an insert that updates the row when it is there already: the order of
the two triggers does not matter). A row with exp may go once the token had ended long ago (admin/dataretention.py lgc_expired): a backup that still
holds that token gives back only an expired one, which /api/v1 and /mcp refuse. Rows without exp (tokens that never expire, app
passwords) stay as before. Additive: the version before ignores the column; the trigger only fills it."""
MIGRATIONS = [
    ("revoked_creds", "exp", "ALTER TABLE revoked_creds ADD COLUMN IF NOT EXISTS exp TEXT"),
]
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_revoked_exp() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(OLD.expires_at, '') <> '' THEN
    INSERT INTO revoked_creds(hash, at, exp)
      VALUES (OLD.token_hash, to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'), OLD.expires_at)
      ON CONFLICT (hash) DO UPDATE SET exp = EXCLUDED.exp;
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_revoked_exp AFTER DELETE ON api_tokens FOR EACH ROW EXECUTE FUNCTION kalmido_revoked_exp();
"""
