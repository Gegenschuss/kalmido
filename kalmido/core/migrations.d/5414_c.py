"""2.905.0 (#5414, stage 4c of the core's trash): a fixed cost / subscription (office_fixed_costs) is deleted into the core's
trash (office/cashflow.py, office/okern.py ofk_register) instead of a copy in office_trash and the row deleted -- also the
rows of an import taken back (office/fixedimport.py fci_remove): the columns the core writes and a partial index for the trash
list and the retention run. New nullable / defaulted columns only: an older version ignores them (it would count a fixed cost
of the trash in its cash flow again)."""
MIGRATIONS = [
    ("office_fixed_costs", "deleted_at", "ALTER TABLE office_fixed_costs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"),
    ("office_fixed_costs", "deleted_by", "ALTER TABLE office_fixed_costs ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("office_fixed_costs", "rev", "ALTER TABLE office_fixed_costs ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5414_office_fixed_costs_trash ON office_fixed_costs(deleted_at) WHERE deleted_at IS NOT NULL",
]
