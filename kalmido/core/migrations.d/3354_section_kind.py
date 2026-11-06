"""2.577.0 (#3354): the meaning of a kanban column (sections.kind: '' = none, else open / progress / review / done / rejected;
kalmido/lists/seckind.py). New column with a default only: older versions ignore it (the column is a plain column there)."""
MIGRATIONS = [
    ("sections", "kind", "ALTER TABLE sections ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT ''"),
]
