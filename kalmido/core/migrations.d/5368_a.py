"""2.783.0 (#5368, stage 6 of the trash core): the inbound webhooks go into the trash through the core (core/objparts.py
part_trash / part_restore), which writes who deleted it and stamps the restore. Two new nullable columns only: an older version
ignores them. The field trash (field_trash) and the Undo copies of "Delete all times" (time_wipes) stay as tables for that older
version; their rows move into the core's copy trash (list_part_trash) at every start (lists/fields.py ftr_move,
personal/timewipe.py tzw_move)."""
MIGRATIONS = [
    ("hook_in", "deleted_by", "ALTER TABLE hook_in ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("hook_in", "updated_at", "ALTER TABLE hook_in ADD COLUMN IF NOT EXISTS updated_at TEXT"),
]
