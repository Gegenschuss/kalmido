"""2.705.0 (#5151): the optional address rule of a receipt fetcher key (docs/fetcher.py fx_authenticate), like the
allowed_ips of an API token / scan inbox key: '' = any address, else IPs / networks separated by commas (api/scopes.py
ips_clean). A new column with a default only: the version before ignores it (its fetcher keys then work from anywhere,
as before)."""
MIGRATIONS = [
    ("doc_fetchers", "allowed_ips", "ALTER TABLE doc_fetchers ADD COLUMN IF NOT EXISTS allowed_ips TEXT NOT NULL DEFAULT ''"),
]
