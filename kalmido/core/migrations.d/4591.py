"""2.558.0 C (#4591): warranty end and maintenance of office equipment (office/eqcare.py): office_equipment.warranty_until
(YYYY-MM-DD, '' = none), warranty_task_id (the task due on that day), maint (JSON list of maintenances, each with its
repeating task). New columns only: older versions ignore them."""
MIGRATIONS = [
    ("office_equipment", "warranty_until", "ALTER TABLE office_equipment ADD COLUMN IF NOT EXISTS warranty_until TEXT NOT NULL DEFAULT ''"),
    ("office_equipment", "warranty_task_id", "ALTER TABLE office_equipment ADD COLUMN IF NOT EXISTS warranty_task_id BIGINT"),
    ("office_equipment", "maint", "ALTER TABLE office_equipment ADD COLUMN IF NOT EXISTS maint TEXT NOT NULL DEFAULT '[]'"),
]
