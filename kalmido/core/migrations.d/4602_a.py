"""2.662.0 (#4602): tasks, comments, events and contacts carry the organisation of their parent (lists / tasks / ev_cals / books),
so row-level security (core/rls.py) is the second floor there too; the app's own scope (core/access.py vis_sql) stays the first.
NULL = a private parent (a person's own list, calendar, address book), like the parent's own org_id.

The app never writes the column: database triggers (core/orgrows.py) fill it from the parent on every INSERT and move (list_id,
task_id, cal_id, book_id) and carry it to the children when a parent changes its organisation -- every write path, also of the
version before. The rows from before get it once at the start (core/orgrows.py orw_backfill).

New nullable columns, indexes and triggers only: the version before keeps running (its INSERTs leave org_id out, the trigger fills
it; its policies come from the database's columns). The way back: DROP the triggers kalmido_orw_* and the function kalmido_orw_*();
the columns may stay (an older version ignores them; rls.apply gives them the policy with a warning)."""
MIGRATIONS = [
    ("tasks", "org_id", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES orgs(id) ON DELETE SET NULL"),
    # 2.972.0 (#5272): comments.org_id went with comments (obj_comments has its own org_id, migrations.d/5272_a.py)
    ("events", "org_id", "ALTER TABLE events ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES orgs(id) ON DELETE SET NULL"),
    ("contacts", "org_id", "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES orgs(id) ON DELETE SET NULL"),
]
AFTER = [
    # the foreign keys' ON DELETE SET NULL of an organisation removed for good finds its rows by these
    "CREATE INDEX IF NOT EXISTS ix4602_tasks_org ON tasks(org_id) WHERE org_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix4602_events_org ON events(org_id) WHERE org_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix4602_contacts_org ON contacts(org_id) WHERE org_id IS NOT NULL",
]
