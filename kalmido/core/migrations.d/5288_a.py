"""2.905.0 (#5288, stage Q10 of the cross-cutting core, analysis #3563, decided 08.11.2026): templates and section templates
are one kind of the shared core, "template" (lists/templates.py: kind task | list | sections, org_access view, org_join admin).
templates gets the columns the core writes (rev, created_by, updated_by; owner_id is its old user_id, renamed by
core/tplmove.py tpl_move at the start, which also moves the times to TIMESTAMPTZ and data / extra to JSONB).

The move: core/db.py init_db calls tpl_move before AFTER runs -- the rows of section_templates become templates of kind
'sections' (the first start of 2.905, or the rows a version before 2.905 wrote after a rollback), then the table is dropped.
One-way: a version before 2.905 makes section_templates again, empty (its schema.py), and finds no templates.user_id; a backup
restores the old state."""
MIGRATIONS = [
    ("templates", "rev", "ALTER TABLE templates ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("templates", "created_by", "ALTER TABLE templates ADD COLUMN IF NOT EXISTS created_by BIGINT"),
    ("templates", "updated_by", "ALTER TABLE templates ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
# drop-ok section_templates: moved into templates (kind 'sections') by core/tplmove.py tpl_move just before (stage Q10, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS section_templates",
]
