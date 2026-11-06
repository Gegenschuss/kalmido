"""2.609.0 (#3373): templates of an organisation (lists/templates.py need_template): templates.org_id NULL = the person's own
as before, else every member of the organisation with the full view reads and uses it, its admins change it. New column only:
older versions ignore it (they show such a template to its creator alone)."""
MIGRATIONS = [
    ("templates", "org_id", "ALTER TABLE templates ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES orgs(id) ON DELETE CASCADE"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix3373_templates_org_id ON templates(org_id) WHERE org_id IS NOT NULL",
]
