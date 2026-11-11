"""2.993.0 (#5413, stage 4b of the core's trash): the entertainment receipts (office_meals), their restaurant bills
(office_meal_files) and the PDF files of framework contracts (office_contract_files) are deleted into the core's trash
(office/okern.py ofk_register, kinds omeal / omealfile / ocfile; core/writes.py obj_trash) and purged by its retention run
(obj_trash_tick) instead of their own runs: the columns the core writes when a row goes into the trash or comes back (rev,
updated_by, deleted_by; updated_at where the table had none, as TIMESTAMPTZ) and a partial index for the retention run.
New nullable / defaulted columns only: an older version ignores them and keeps reading deleted_at as before. No data moves,
nothing is deleted here; the old TEXT columns (created_at, deleted_at) keep their type (a type change is no additive step)."""
MIGRATIONS = [
    ("office_meals", "rev", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_meals", "updated_by", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_meals", "deleted_by", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_meal_files", "rev", "ALTER TABLE office_meal_files ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_meal_files", "updated_at", "ALTER TABLE office_meal_files ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
    ("office_meal_files", "updated_by", "ALTER TABLE office_meal_files ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_meal_files", "deleted_by", "ALTER TABLE office_meal_files ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_contract_files", "rev", "ALTER TABLE office_contract_files ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("office_contract_files", "updated_at", "ALTER TABLE office_contract_files ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
    ("office_contract_files", "updated_by", "ALTER TABLE office_contract_files ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("office_contract_files", "deleted_by", "ALTER TABLE office_contract_files ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5413_office_meals_trash ON office_meals(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5413_office_meal_files_trash ON office_meal_files(deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix5413_office_contract_files_trash ON office_contract_files(deleted_at) WHERE deleted_at IS NOT NULL",
]
