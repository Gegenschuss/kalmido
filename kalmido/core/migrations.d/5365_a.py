"""2.790.0 (#5365, stage 3 of the core's trash): knowledge pages, tables and file-store nodes go into the ONE trash of the
core (core/writes.py obj_trash / obj_restore, wiki/wkkern.py, sheets/shkern.py, files/fskern.py), which writes the columns
every core object carries: wiki_pages.rev + deleted_by, sheets.deleted_by, fs_nodes.rev + updated_by. New columns with a
default / nullable only: an older version ignores them. No data moves: deleted_at stays the trash mark of these rows."""
MIGRATIONS = [
    ("wiki_pages", "rev", "ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 0"),
    ("wiki_pages", "deleted_by", "ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("sheets", "deleted_by", "ALTER TABLE sheets ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("fs_nodes", "rev", "ALTER TABLE fs_nodes ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 0"),
    ("fs_nodes", "updated_by", "ALTER TABLE fs_nodes ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
]
